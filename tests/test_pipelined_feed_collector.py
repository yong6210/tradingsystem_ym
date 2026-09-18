import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from app.research.data.background_incremental_audit import BackgroundIncrementalAudits
from app.research.data.background_segment_archive import BackgroundArchives, ArchiveLimits
from app.research.data.durable_capture_log import JournalError, iter_committed
from app.research.data.pipelined_feed_collector import run_bounded, SealedAudit, PipelinedFeedEpoch
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.sealed_feed_pipeline import SealedFeedPipeline, PipelineLimits
from app.research.data.sealed_segment_handoff import SealedJournal
from app.research.data.snapshot_feed_audit import audit_epoch
from tests.incremental_audit_fixture import COMPARABLE, fixture
from tests.test_bounded_feed_collector import ScriptedTransport, load_contract, ROOT


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(.005)


def fault_factory(*, archive=None, audit=None, release=None, hook=None):
    def factory(budget, **kwargs):
        def archive_factory(directory, **kw):
            command = None if archive is None else [sys.executable, '-m', 'tests.sealed_archive_fixture_worker', archive, str(release)]
            return BackgroundArchives(directory, **kw, _command=command)
        def audit_factory(owner, **kw):
            command = None if audit is None else [sys.executable, '-m', 'tests.incremental_audit_fixture_worker', audit, str(release)]
            return BackgroundIncrementalAudits(owner, **kw, _command=command, _hook=hook or (lambda stage: None))
        return SealedFeedPipeline(budget, **kwargs, _archive_factory=archive_factory, _audit_factory=audit_factory)
    return factory


class CollectorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name).resolve()/'capture'
        self.policy = load_contract(ROOT/'configs/research/forward_data_policy_v1.json')

    def tearDown(self):
        self.temp.cleanup()

    async def run_case(self, transport=None, duration=400_000_000, **kwargs):
        return await run_bounded(self.output, duration_ns=duration, transport=transport or ScriptedTransport(),
            policy=self.policy, pipeline_limits=kwargs.pop('pipeline_limits', PipelineLimits(seal_seconds=.1)), **kwargs)

    def reaped(self, result):
        self.assertEqual(result['storage_after_result']['reserved_bytes'], 0)
        for c in result['pipeline']['channels']:
            for kind in ('raw', 'audit_log', 'auditor'):
                manager = c[kind]
                self.assertTrue(manager['child_reaped'])
                self.assertEqual(manager['pending'], 0)
                for job in manager['jobs']:
                    if 'pid' in job:
                        with self.assertRaises(ProcessLookupError):
                            os.kill(job['pid'], 0)

    def equivalent(self, result):
        for row, actual in zip(result['epochs'], result['audits']):
            directory = self.output/row['directory']
            baseline = audit_epoch(directory/'journal', directory/'audit', **result['original_window'], max_intervals=10000)
            for k in COMPARABLE:
                self.assertEqual(actual[k], baseline[k], k)

    async def test_active_seal_archive_and_gzip_replay_matches_full_replay(self):
        result = await self.run_case()
        self.assertEqual(result['stop_reason'], 'ORIGINAL_DEADLINE', result['errors'])
        self.assertTrue(result['result_persisted'])
        self.assertGreater(len(result['pipeline']['units']), 1)
        self.assertEqual(result['pipeline']['peak_reservations'], 2)
        self.assertEqual(result['combined']['quality']['calendar_ns'], 400_000_000)
        self.assertEqual(result['epochs'][0]['diagnostics']['last_sealed_sequence'], result['audits'][0]['last_audited_sequence'])
        self.assertTrue(list(self.output.glob('epoch-*/raw-archives/*.jsonl.gz')))
        self.assertTrue(list(self.output.glob('epoch-*/journal/segment-*.jsonl')))
        channel = result['pipeline']['channels'][0]
        self.assertLess(channel['auditor']['jobs'][0]['completed_ns'], channel['closed_ns'])
        self.equivalent(result)
        self.reaped(result)

    async def test_reconnect_retains_original_window_and_all_epoch_audits(self):
        result = await self.run_case(ScriptedTransport(disconnect_first=True), duration=1_700_000_000)
        self.assertEqual(result['stop_reason'], 'ORIGINAL_DEADLINE', result['errors'])
        self.assertEqual(len(result['epochs']), 2)
        self.assertEqual(len(result['audits']), 2)
        self.assertEqual(result['retries_used'], 1)
        self.assertEqual(result['combined']['quality']['calendar_ns'], 1_700_000_000)
        self.equivalent(result)
        self.reaped(result)

    async def test_common_scheduler_runs_archive_while_audit_is_pending(self):
        managers = []
        release = self.output.parent/'release'
        def factory(budget, **kwargs):
            manager = fault_factory(audit='gate', release=release)(budget, **kwargs)
            managers.append(manager)
            return manager
        async def unlock():
            await until(lambda: managers and managers[0].audit_archive_overlap_samples > 0)
            release.touch()
        task = asyncio.create_task(unlock())
        try:
            result = await self.run_case(duration=800_000_000, _pipeline_factory=factory)
            await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(result['stop_reason'], 'ORIGINAL_DEADLINE', result['errors'])
        self.assertGreater(result['pipeline']['audit_archive_overlap_samples'], 0)
        self.assertEqual(result['pipeline']['peak_reservations'], 2)
        self.equivalent(result)
        self.reaped(result)

    async def failure(self, **kwargs):
        transport = kwargs.pop('transport', ScriptedTransport())
        result = await self.run_case(transport, duration=2_000_000_000, **kwargs)
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE', result['errors'])
        self.assertEqual(result['combined']['quality']['status'], 'QUALITY_INPUTS_REJECTED')
        self.assertFalse(result['result_persisted'])
        self.assertTrue(all(s.closed.is_set() for s in transport.sockets))
        self.reaped(result)
        return result

    async def test_archive_failure_stops_receiver(self):
        result = await self.failure(_pipeline_factory=fault_factory(archive='crash'))
        self.assertLess(result['completed_ns'], result['original_window']['window_end_ns'])
        self.assertFalse(result['audits'])

    async def test_auditor_failure_stops_receiver(self):
        result = await self.failure(_pipeline_factory=fault_factory(audit='crash'))
        self.assertFalse(result['audits'])
        self.assertLess(result['completed_ns'], result['original_window']['window_end_ns'])

    async def test_bad_audit_reply_never_publishes_quality(self):
        await self.failure(_pipeline_factory=fault_factory(audit='wrong-request'))

    async def test_worker_timeout_reaps_all_shared_workers(self):
        await self.failure(_pipeline_factory=fault_factory(archive='hang'), worker_limits=ArchiveLimits(job_seconds=.12))

    async def test_pipeline_age_includes_time_before_worker_dispatch(self):
        result = await self.failure(_pipeline_factory=fault_factory(archive='hang'),
            pipeline_limits=PipelineLimits(seal_seconds=.1, unit_seconds=.12))
        self.assertTrue(any('UNIT_DEADLINE' in e for e in result['errors']), result['errors'])

    async def test_global_backlog_refuses_new_unit_without_silent_drop(self):
        result = await self.failure(_pipeline_factory=fault_factory(archive='hang'),
            pipeline_limits=PipelineLimits(seal_seconds=.05, max_pending_units=1))
        self.assertTrue(any('BACKLOG' in e for e in result['errors']))
        self.assertEqual(len(result['pipeline']['units']), 1)
        self.assertGreater(len(list(self.output.glob('epoch-*/journal/seals/*.json'))), 1)

    async def test_lifetime_unit_limit_does_not_reset_after_completion(self):
        result = await self.failure(pipeline_limits=PipelineLimits(seal_seconds=.1, max_units=1))
        self.assertTrue(any('BACKLOG' in e for e in result['errors']))

    async def test_final_drain_timeout_rejects_remaining_results(self):
        result = await self.run_case(duration=200_000_000, _pipeline_factory=fault_factory(audit='hang'),
            pipeline_limits=PipelineLimits(seal_seconds=2, drain_seconds=.12))
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
        self.assertFalse(result['audits'])
        self.reaped(result)

    async def test_background_failure_cancels_pending_snapshot(self):
        transport = ScriptedTransport(hang_snapshot=True)
        await self.failure(transport=transport, _pipeline_factory=fault_factory(archive='crash'))
        self.assertEqual(transport.cancelled_operations, 1)

    async def test_background_failure_cancels_pending_connection(self):
        transport = ScriptedTransport(hang_channel='public')
        await self.failure(transport=transport, _pipeline_factory=fault_factory(archive='crash'))
        self.assertEqual(transport.cancelled_operations, 1)

    async def test_previous_epoch_late_failure_cancels_reconnected_rest(self):
        class SecondRestHangs(ScriptedTransport):
            async def snapshot(self, *args, **kwargs):
                if self.snapshot_count:
                    self.hang_snapshot = True
                return await super().snapshot(*args, **kwargs)
        transport = SecondRestHangs(disconnect_first=True)
        result = await self.failure(transport=transport, _pipeline_factory=fault_factory(audit='hang'),
            worker_limits=ArchiveLimits(job_seconds=1.3), pipeline_limits=PipelineLimits(seal_seconds=2))
        self.assertEqual(result['retries_used'], 1)
        self.assertEqual(transport.snapshot_count, 2)
        self.assertEqual(transport.cancelled_operations, 1)

    async def test_old_deadline_cancels_rest_and_still_audits_stop(self):
        transport = ScriptedTransport(hang_snapshot=True)
        result = await self.run_case(transport, duration=250_000_000)
        self.assertEqual(result['stop_reason'], 'ORIGINAL_DEADLINE', result['errors'])
        self.assertEqual(transport.cancelled_operations, 1)
        self.equivalent(result)

    async def test_protocol_error_never_retries(self):
        result = await self.run_case(ScriptedTransport(malformed=True))
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
        self.assertEqual(result['retries_used'], 0)
        self.reaped(result)

    async def test_capacity_preflight_opens_no_connection(self):
        original = ReservedStorageBudget.create.__func__
        def small(cls, root, **kwargs):
            return original(cls, root, **(kwargs | dict(max_bytes=100000)))
        transport = ScriptedTransport()
        with patch.object(ReservedStorageBudget, 'create', classmethod(small)):
            result = await self.run_case(transport)
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
        self.assertFalse(transport.connections)

    async def test_audit_disk_failure_never_seals_unaudited_raw(self):
        original = SealedAudit.append
        def broken(writer, value):
            if writer.lines:
                with writer.journal.budget.mutation():
                    raise OSError('injected ENOSPC')
            return original(writer, value)
        with patch.object(SealedAudit, 'append', broken):
            result = await self.failure()
        self.assertFalse(result['pipeline']['units'])

    async def test_slow_parent_checkpoint_is_detected_by_runtime_watchdog(self):
        injected = []
        def hook(stage):
            if stage == 'after_audit_checkpoint_directory_fsync' and not injected:
                injected.append(True)
                time.sleep(.6)
        result = await self.failure(_pipeline_factory=fault_factory(hook=hook))
        self.assertTrue(injected)
        self.assertTrue(result['errors'])

    async def test_slow_seal_fails_even_when_raw_flush_is_fast(self):
        original = SealedJournal.seal
        def slow(writer):
            time.sleep(.3)
            return original(writer)
        with patch.object(SealedJournal, 'seal', slow):
            result = await self.failure()
        self.assertTrue(any('seal' in e.lower() for e in result['errors']))

    async def test_cancel_collect_reaps_children_and_releases_run_lock(self):
        managers = []
        def factory(budget, **kwargs):
            manager = fault_factory(archive='hang')(budget, **kwargs)
            managers.append(manager)
            return manager
        transport = ScriptedTransport()
        task = asyncio.create_task(self.run_case(transport, duration=5_000_000_000, _pipeline_factory=factory))
        await until(lambda: managers and any(m.process for m in managers[0].managers()))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(all(m.process is None and not m.pending for m in managers[0].managers()))
        disk = managers[0].budget
        self.assertTrue(disk.closed)
        self.assertEqual(disk.snapshot()['reserved_bytes'], 0)
        self.assertTrue(all(s.closed.is_set() for s in transport.sockets))
        contract = {k:v for k,v in disk.contract.items() if k != 'version'}
        reopened = ReservedStorageBudget.resume(self.output, **contract)
        reopened.close()

    async def test_duration_cap_remains_before_disk_or_network(self):
        transport = ScriptedTransport()
        with self.assertRaises(ValueError):
            await self.run_case(transport, duration=121_000_000_000)
        self.assertFalse(self.output.exists())
        self.assertFalse(transport.connections)

    async def test_final_result_storage_failure_rejects_quality(self):
        original = ReservedStorageBudget.atomic_json
        def broken(budget, path, value, *args):
            if Path(path).name == 'collection_result.json':
                with budget.mutation():
                    raise OSError('result ENOSPC')
            return original(budget, path, value, *args)
        with patch.object(ReservedStorageBudget, 'atomic_json', broken):
            result = await self.run_case()
        self.assertFalse(result['result_persisted'])
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
        self.assertEqual(result['combined']['quality']['status'], 'QUALITY_INPUTS_REJECTED')


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.fix = fixture(Path(self.temp.name).resolve(), raw_step=100, audit_step=100)
        self.managers = []

    async def asyncTearDown(self):
        for m in self.managers:
            await m.close()
        self.fix['budget'].close()
        self.temp.cleanup()

    def manager(self, **kwargs):
        f = self.fix
        manager = SealedFeedPipeline(f['budget'], **kwargs)
        self.managers.append(manager)
        from app.research.data.archive_segment_reader import restore_cursor
        manager.add_epoch(f['root'], restore_cursor(f['contract']['raw_initial']),
            restore_cursor(f['contract']['audit_initial']), f['scope'])
        return manager

    async def test_whole_unit_requires_both_archives_then_terminal_anchors(self):
        manager = self.manager()
        manager.submit(0, self.fix['raw_tickets'], self.fix['audit_tickets'])
        manager.end_epoch(0)
        await manager.drain()
        for k in COMPARABLE:
            self.assertEqual(manager.channels[0]['result'][k], self.fix['expected'][k])
        self.assertEqual(manager.peak_reservations, 2)

    async def test_duplicate_raw_ticket_fails_admission(self):
        manager = self.manager()
        manager.submit(0, self.fix['raw_tickets'], self.fix['audit_tickets'])
        with self.assertRaises(JournalError):
            manager.submit(0, self.fix['raw_tickets'], self.fix['audit_tickets'])
        self.assertTrue(manager.failed.is_set())

    async def test_multi_audit_segment_unit_is_not_silently_truncated(self):
        manager = self.manager()
        with self.assertRaisesRegex(JournalError, 'SEGMENT_BOUND'):
            manager.submit(0, self.fix['raw_tickets'], self.fix['audit_tickets']*2)

    async def test_missing_raw_input_rejected(self):
        manager = self.manager()
        with self.assertRaisesRegex(JournalError, 'SEGMENT_BOUND'):
            manager.submit(0, [], self.fix['audit_tickets'])

    async def test_negative_epoch_index_rejected(self):
        manager = self.manager()
        with self.assertRaises(JournalError):
            manager.submit(-1, self.fix['raw_tickets'], self.fix['audit_tickets'])

    async def test_close_cancellation_waits_for_spawn_reaping(self):
        manager = self.manager()
        original = asyncio.create_subprocess_exec
        spawned, release = asyncio.Event(), asyncio.Event()
        children = []
        async def delayed(*args, **kwargs):
            child = await original(*args, **kwargs)
            children.append(child)
            spawned.set()
            await release.wait()
            return child
        with patch('asyncio.create_subprocess_exec', side_effect=delayed):
            manager.submit(0, self.fix['raw_tickets'], self.fix['audit_tickets'])
            await spawned.wait()
            closing = asyncio.create_task(manager.close())
            await asyncio.sleep(.01)
            closing.cancel()
            await asyncio.sleep(.01)
            closing.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await closing
        self.assertTrue(children and all(c.returncode is not None for c in children))
        self.assertEqual(self.fix['budget'].snapshot()['reserved_bytes'], 0)
        self.assertTrue(manager.channels[0]['owner'].closed)

    def test_invalid_limits_are_rejected(self):
        for kwargs in (dict(seal_seconds=0), dict(unit_seconds=float('nan')), dict(max_units=63),
                       dict(max_pending_units=5), dict(max_epochs=True), dict(drain_seconds=16)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                PipelineLimits(**kwargs)
