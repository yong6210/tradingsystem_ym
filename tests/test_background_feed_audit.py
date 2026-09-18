import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from app.research.data.background_feed_audit import AuditLimits, BackgroundAudits
from app.research.data.background_feed_collector import run_bounded
from app.research.data.shared_feed_storage import SharedStorageBudget, SegmentedAudit
from app.research.data.snapshot_feed_audit import audit_epoch
from app.research.data.synthetic_feed_fixture import build_fixture
from tests import test_segmented_feed_storage as storage_tests
from tests import test_bounded_feed_collector as fixtures


def command(mode, release):
    return lambda request: [sys.executable, '-m', 'tests.background_audit_fixture_worker',
                           json.dumps(request), mode, str(release)]


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate(): await asyncio.sleep(.01)


class SupervisorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.fixture = self.root/'fixture'
        build_fixture(self.fixture, 1, min_free_bytes=0)
        self.scope = dict(window_start_ns=0, window_end_ns=1_000_000_000,
                          clock_domain='synthetic-full-file-v1')
        self.managers = []

    async def asyncTearDown(self):
        for manager in self.managers: await manager.close()
        self.temp.cleanup()

    def manager(self, mode=None, **limits):
        manager = BackgroundAudits(limits=AuditLimits(**limits),
            _command=None if mode is None else command(mode, self.root/'release'))
        self.managers.append(manager)
        return manager

    async def run_job(self, mode=None, **limits):
        manager = self.manager(mode, **limits)
        manager.submit(self.fixture, self.scope)
        await manager.drain()
        await manager.close()
        self.assertTrue(manager.snapshot()['child_reaped'])
        for job in manager.jobs:
            if 'pid' in job:
                with self.assertRaises(ProcessLookupError): os.kill(job['pid'], 0)
        return manager

    async def test_real_worker_matches_direct_replay(self):
        manager = await self.run_job()
        self.assertFalse(manager.errors)
        direct = audit_epoch(self.fixture/'journal', self.fixture/'audit', **self.scope,
                             max_intervals=10_000)
        self.assertEqual(manager.results[0], direct)
        self.assertEqual(manager.jobs[0]['status'], 'COMPLETE')

    async def test_worker_crash_fails_closed(self):
        manager = await self.run_job('crash')
        self.assertIn('AUDIT_WORKER_EXIT:71', manager.errors[0])

    async def test_malformed_reply_fails_closed(self):
        self.assertTrue((await self.run_job('invalid')).failed.is_set())

    async def test_reply_job_binding(self):
        self.assertIn('BINDING', (await self.run_job('wrong-job')).errors[0])

    async def test_reply_window_binding(self):
        self.assertIn('BINDING', (await self.run_job('wrong-window')).errors[0])

    async def test_reply_checkpoint_binding(self):
        self.assertIn('BINDING', (await self.run_job('wrong-checkpoint')).errors[0])

    async def test_reported_memory_over_limit_rejected(self):
        self.assertIn('MEMORY_LIMIT', (await self.run_job('memory')).errors[0])

    async def test_malformed_result_not_retained(self):
        manager = await self.run_job('bad-result')
        self.assertTrue(manager.errors)
        self.assertFalse(manager.results)

    async def test_real_worker_rss_watchdog_rejects_tiny_budget(self):
        self.assertTrue((await self.run_job(rss_limit_bytes=1)).errors)

    async def test_stdout_overflow_kills_and_reaps(self):
        self.assertIn('IPC_LIMIT', (await self.run_job('stdout', max_reply_bytes=1024)).errors[0])

    async def test_stderr_overflow_kills_and_reaps(self):
        self.assertIn('IPC_LIMIT', (await self.run_job('stderr')).errors[0])

    async def test_job_timeout_kills_and_reaps(self):
        manager = await self.run_job('hang', job_seconds=.15)
        self.assertIn('TimeoutError', manager.errors[0])

    async def test_final_drain_timeout_kills_and_reaps(self):
        manager = await self.run_job('hang', drain_seconds=.15)
        self.assertIn('AUDIT_DRAIN_TIMEOUT', manager.errors)

    async def test_backlog_counts_running_job_and_rejects_without_waiting(self):
        manager = self.manager('hang')
        manager.submit(self.fixture, self.scope)
        await until(lambda: manager.process is not None)
        manager.submit(self.fixture, self.scope)
        with self.assertRaisesRegex(RuntimeError, 'BACKLOG'):
            manager.submit(self.fixture, self.scope)
        await manager.close()
        self.assertEqual(manager.peak_pending, 2)
        self.assertEqual(manager.pending, 0)

    async def test_cancellation_during_spawn_keeps_child_owned_until_reaped(self):
        original = asyncio.create_subprocess_exec
        created = asyncio.Event()
        children = []
        async def delayed(*args, **kwargs):
            child = await original(*args, **kwargs)
            children.append(child)
            created.set()
            await asyncio.sleep(.1)
            return child
        manager = self.manager('hang')
        with patch('asyncio.create_subprocess_exec', side_effect=delayed):
            manager.submit(self.fixture, self.scope)
            await asyncio.wait_for(created.wait(), 2)
            await manager.close()
        self.assertIsNotNone(children[0].returncode)
        with self.assertRaises(ProcessLookupError): os.kill(children[0].pid, 0)

    async def test_total_reply_memory_bound(self):
        manager = await self.run_job(max_total_reply_bytes=1)
        self.assertIn('TOTAL_IPC_LIMIT', manager.errors[0])

    async def test_job_count_limit_remains_after_completed_work(self):
        manager = self.manager(max_jobs=1)
        manager.submit(self.fixture, self.scope)
        await manager.drain()
        self.assertFalse(manager.errors)
        with self.assertRaisesRegex(RuntimeError, 'BACKLOG'):
            manager.submit(self.fixture, self.scope)

    async def test_audit_fragmentation_bound_rejects_without_truncation(self):
        manager = await self.run_job(max_intervals=1)
        self.assertTrue(manager.failed.is_set())
        self.assertTrue(manager.results[0]['interval_reduction']['failed'])

    async def test_changed_checkpoint_after_submission_rejected(self):
        manager = self.manager('wait')
        manager.submit(self.fixture, self.scope)
        path = self.fixture/'journal/checkpoint.json'
        path.write_bytes(path.read_bytes()+b' ')
        (self.root/'release').touch()
        await manager.drain()
        self.assertTrue(manager.failed.is_set())

    async def test_corrupt_raw_hash_is_rejected(self):
        path = self.fixture/'journal/segment-0000000.jsonl'
        data = bytearray(path.read_bytes()); data[-5] ^= 1; path.write_bytes(data)
        manager = await self.run_job()
        self.assertTrue(manager.failed.is_set())
        self.assertTrue(manager.results[0]['errors'])

    def test_invalid_limits_rejected(self):
        for limits in ({'max_pending': 3}, {'max_jobs': 8}, {'job_seconds': float('nan')},
                       {'job_seconds': 16}, {'drain_seconds': 0}, {'max_reply_bytes': True}):
            with self.subTest(limits=limits), self.assertRaises(ValueError): AuditLimits(**limits)


class CollectorTests(storage_tests.CollectorTests):
    async def run_case(self, transport, duration=200_000_000, **kwargs):
        return await run_bounded(self.output, duration_ns=duration, transport=transport,
                                 policy=self.policy, **kwargs)

    async def test_audit_failure_retains_raw_but_prevents_retry(self):
        original = SegmentedAudit.append
        def broken(writer, value):
            if writer.journal.directory.name == 'audit' and writer.lines == 1:
                with writer.journal.budget.mutation(): raise OSError(28, 'injected ENOSPC')
            return original(writer, value)
        with patch.object(SegmentedAudit, 'append', broken):
            result = await self.run_case(fixtures.ScriptedTransport())
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
        self.assertEqual(result['retries_used'], 0)
        # No new workers or result writes after the global storage latch fails.
        self.assertFalse(result['background_audit']['jobs'])
        self.assertFalse(result['result_persisted'])
        self.assertGreater(len(self.raw()), result['epochs'][0]['last_audited_sequence'])

    async def test_delayed_retry_timer_cannot_start_after_original_end(self):
        # v5 wakes on either the fixed timer or a fault, rather than sleep().
        transport = fixtures.ScriptedTransport(connect_error=fixtures.RetryableTransportError('offline'))
        original = asyncio.wait_for
        async def delayed(waiter, timeout):
            if timeout > .5 and getattr(getattr(waiter, 'cr_code', None), 'co_qualname', '') == 'Event.wait':
                await asyncio.sleep(timeout+.35)
                waiter.close()
                raise asyncio.TimeoutError
            return await original(waiter, timeout)
        with patch('app.research.data.background_feed_collector.asyncio.wait_for', side_effect=delayed):
            result = await self.run_case(transport, duration=1_200_000_000)
        self.assertEqual(len(transport.connections), 1)
        self.assertEqual(result['stop_reason'], 'ORIGINAL_DEADLINE')

    def factory(self, mode, managers):
        def create(**kwargs):
            manager = BackgroundAudits(**kwargs, _command=command(mode, self.output.parent/'release'))
            managers.append(manager)
            return manager
        return create

    async def test_reconnect_occurs_before_previous_audit_finishes(self):
        managers, seen = [], []
        owner = self
        class Transport(fixtures.ScriptedTransport):
            async def snapshot(self, *args, **kwargs):
                if self.snapshot_count == 1:
                    seen.append(managers[0].jobs[0]['status'])
                    (owner.output.parent/'release').touch()
                return await super().snapshot(*args, **kwargs)
        result = await self.run_case(Transport(disconnect_first=True), duration=1_800_000_000,
                                    _audit_factory=self.factory('wait', managers))
        self.assertEqual(seen, ['RUNNING'])
        self.assertEqual(result['stop_reason'], 'ORIGINAL_DEADLINE')
        self.assertEqual(len(result['audits']), 2)
        self.assertFalse(result['errors'])
        jobs = result['background_audit']['jobs']
        self.assertLess(self.raw(1)[0]['payload']['received_ns'], jobs[0]['completed_ns'])

    async def test_late_audit_fault_stops_active_epoch_at_detection(self):
        managers = []
        owner = self
        class Transport(fixtures.ScriptedTransport):
            async def snapshot(self, *args, **kwargs):
                if self.snapshot_count == 1: (owner.output.parent/'release').touch()
                return await super().snapshot(*args, **kwargs)
        transport = Transport(disconnect_first=True)
        result = await self.run_case(transport, duration=4_000_000_000,
                                    _audit_factory=self.factory('wait-fail', managers))
        self.assertEqual(len(result['epochs']), 2)
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
        self.assertEqual(result['epochs'][1]['outcome'], 'FATAL_FAILURE')
        stopped = next(row['payload'] for row in self.raw(1) if row['payload']['kind'] == 'STOP')
        self.assertEqual(stopped['received_ns'], result['background_audit']['failure_detected_ns'])
        self.assertLess(result['completed_ns'], result['original_window']['window_end_ns'])
        self.assertEqual(result['combined']['quality']['status'], 'QUALITY_INPUTS_REJECTED')
        self.assertTrue(all(socket.closed.is_set() for socket in transport.sockets))

    async def test_audit_fault_in_backoff_prevents_next_connection(self):
        managers = []
        transport = fixtures.ScriptedTransport(disconnect_first=True)
        result = await self.run_case(transport, duration=3_000_000_000,
                                    _audit_factory=self.factory('crash', managers))
        self.assertEqual(len(transport.connections), 2)
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')

    async def test_late_audit_fault_cancels_hanging_rest(self):
        managers = []
        owner = self
        class Transport(fixtures.ScriptedTransport):
            async def snapshot(self, *args, **kwargs):
                if self.snapshot_count == 1:
                    self.hang_snapshot = True
                    (owner.output.parent/'release').touch()
                return await super().snapshot(*args, **kwargs)
        transport = Transport(disconnect_first=True)
        result = await self.run_case(transport, duration=4_000_000_000,
                                    _audit_factory=self.factory('wait-fail', managers))
        self.assertEqual(transport.cancelled_operations, 1)
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
        self.assertTrue(all(socket.closed.is_set() for socket in transport.sockets))

    async def test_audit_fault_after_deadline_rejects_whole_result(self):
        managers = []
        result = await self.run_case(fixtures.ScriptedTransport(),
                                    _audit_factory=self.factory('crash', managers))
        self.assertEqual(result['epochs'][0]['outcome'], 'ORIGINAL_DEADLINE')
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
        self.assertIn('AUDIT_SET_INCOMPLETE', result['errors'])

    async def test_cancellation_during_worker_drain_reaps_and_releases_lock(self):
        managers = []
        task = asyncio.create_task(self.run_case(fixtures.ScriptedTransport(),
                                  _audit_factory=self.factory('hang', managers)))
        await until(lambda: managers and managers[0].process is not None)
        pid = managers[0].process.pid
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)
        cfg = json.loads((self.output/'storage.json').read_text()); cfg.pop('version')
        SharedStorageBudget.resume(self.output, **cfg).close()

    async def test_cancellation_with_worker_and_active_second_epoch(self):
        managers = []
        transport = fixtures.ScriptedTransport(disconnect_first=True)
        task = asyncio.create_task(self.run_case(transport, duration=4_000_000_000,
                                  _audit_factory=self.factory('hang', managers)))
        await until(lambda: len(transport.sockets) == 4)
        pid = managers[0].process.pid
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(all(socket.closed.is_set() for socket in transport.sockets))
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)


if __name__ == '__main__': unittest.main()
