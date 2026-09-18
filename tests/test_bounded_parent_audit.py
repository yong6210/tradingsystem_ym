"""Fixed-phase failure reproduction plus existing worker contract regressions."""
import asyncio
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from app.research.data.background_incremental_audit import BackgroundIncrementalAudits
from app.research.data.background_segment_archive import ArchiveLimits
from app.research.data.bounded_parent_audit import BoundedParentAudits, PARENT_PHASE_LIMIT_NS
from app.research.data import bounded_parent_capture as bounded
from app.research.data import pipelined_feed_collector as frozen_collector
from app.research.data.durable_capture_log import JournalError, decoded, encoded, lock_directory
from app.research.data.incremental_feed_audit import IncrementalFeedAudit
from app.research.data.archive_segment_reader import restore_cursor
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.sealed_feed_pipeline import SealedFeedPipeline, PipelineLimits
from app.research.data.sealed_segment_handoff import SealTicket
from tests.incremental_audit_fixture import fixture, jobs, COMPARABLE
from tests import test_background_incremental_audit as original
from tests.test_bounded_feed_collector import ScriptedTransport, load_contract, ROOT


class WorkerCompatibilityTests(original.BackgroundIncrementalAuditTests):
    def manager(self, mode=None, hook=lambda stage:None, **limits):
        command = None if mode is None else [sys.executable, '-m', 'tests.incremental_audit_fixture_worker', mode, str(self.base/'release')]
        manager = BoundedParentAudits(self.owner, limits=ArchiveLimits(**limits), _command=command, _hook=hook)
        self.managers.append(manager)
        return manager


class ParentPhaseTests(unittest.IsolatedAsyncioTestCase):
    async def case(self, stage, elapsed, *, error=None):
        with tempfile.TemporaryDirectory() as temp:
            fix = fixture(Path(temp).resolve(), raw_step=1000, audit_step=1000)
            budget = fix['budget']
            owner = IncrementalFeedAudit.create(fix['root']/'state', budget=budget, contract=fix['contract'])
            initial = owner.receipt()
            clock = [0]
            fired = []
            def hook(current):
                if current == stage and not fired:
                    fired.append(current)
                    clock[0] = elapsed
                    if error: raise OSError(error)
            manager = BoundedParentAudits(owner, _hook=hook, _parent_clock=lambda:clock[0])
            try:
                work = jobs(fix); self.assertEqual(len(work), 1)
                manager.submit(*work[0])
                failed = elapsed > PARENT_PHASE_LIMIT_NS or error is not None
                if failed:
                    with self.assertRaisesRegex(JournalError, error or 'PARENT_AUDIT_PHASE_LIMIT'):
                        await manager.finish()
                    self.assertFalse(manager.results)
                    self.assertTrue(budget.failed)
                    self.assertTrue(owner.failed)
                    self.assertEqual(owner._doc['revision'], initial['revision'])
                else:
                    await manager.finish()
                    self.assertEqual(owner.receipt()['revision'], 1)
                    self.assertEqual(manager.peak_parent_phase_ns, elapsed)
                self.assertEqual(fired, [stage])
                self.assertEqual(budget.snapshot()['reserved_bytes'], 0)
                self.assertTrue(manager.snapshot()['child_reaped'])
                if failed and stage == 'after_audit_checkpoint_directory_fsync':
                    # Physical rename happened, but no success receipt was admitted.
                    self.assertEqual(decoded(owner.path.read_bytes())['revision'], 1)
                if failed and stage == 'after_audit_proposal_validated':
                    self.assertEqual(decoded(owner.path.read_bytes())['revision'], 0)
            finally:
                await manager.close(); owner.close(); budget.close()

    async def test_exact_500ms_boundary_remains_allowed(self):
        await self.case('after_audit_checkpoint_directory_fsync', 500_000_000)

    async def test_validation_overrun_never_writes_checkpoint(self):
        await self.case('after_audit_proposal_validated', 500_000_001)

    async def test_fsync_overrun_never_acknowledges_temporary(self):
        await self.case('after_audit_checkpoint_fsync', 500_000_001)

    async def test_rename_overrun_never_acknowledges_written_checkpoint(self):
        await self.case('after_audit_checkpoint_replace', 500_000_001)

    async def test_directory_sync_overrun_never_acknowledges_written_checkpoint(self):
        await self.case('after_audit_checkpoint_directory_fsync', 500_000_001)

    async def test_slow_receipt_after_successful_write_is_not_published(self):
        with tempfile.TemporaryDirectory() as temp:
            fix = fixture(Path(temp).resolve(), raw_step=1000, audit_step=1000)
            owner = IncrementalFeedAudit.create(fix['root']/'state', budget=fix['budget'], contract=fix['contract'])
            clock = [0]
            manager = BoundedParentAudits(owner, _parent_clock=lambda:clock[0])
            original_receipt = owner.receipt
            def receipt():
                result = original_receipt()
                if result['revision'] > 0: clock[0] = 500_000_001
                return result
            try:
                with patch.object(owner, 'receipt', side_effect=receipt):
                    manager.submit(*jobs(fix)[0])
                    with self.assertRaisesRegex(JournalError, 'before_receipt_publication'):
                        await manager.finish()
                self.assertEqual(owner._doc['revision'], 1)
                self.assertEqual(decoded(owner.path.read_bytes())['revision'], 1)
                self.assertFalse(manager.results)
                self.assertTrue(owner.failed)
                self.assertEqual(fix['budget'].snapshot()['reserved_bytes'], 0)
            finally:
                await manager.close(); owner.close(); fix['budget'].close()

    async def test_original_storage_error_is_preserved(self):
        await self.case('after_audit_checkpoint_fsync', 0, error='ORIGINAL_FSYNC_ERROR')


class ClosedPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def case(self, guarded):
        with tempfile.TemporaryDirectory() as temp:
            fix = fixture(Path(temp).resolve(), raw_step=1000, audit_step=1000)
            budget = fix['budget']; fired = []; pipeline = None
            def hook(stage):
                if stage == 'after_audit_checkpoint_directory_fsync' and not fired:
                    self.assertIsNotNone(pipeline.channels[0]['closed_ns'])
                    fired.append(stage)
                    time.sleep(.6)
            def factory(owner, **kwargs):
                cls = BoundedParentAudits if guarded else BackgroundIncrementalAudits
                return cls(owner, **kwargs, _hook=hook)
            pipeline = SealedFeedPipeline(budget, _audit_factory=factory)
            try:
                c = fix['contract']
                pipeline.add_epoch(fix['root'], restore_cursor(c['raw_initial']), restore_cursor(c['audit_initial']), fix['scope'])
                anchor = pipeline.channels[0]['owner'].receipt()
                work = jobs(fix); self.assertEqual(len(work), 1)
                a, raw = work[0]
                pipeline.submit(0, [SealTicket(r['certificate'].encode()) for r in raw], [SealTicket(a['certificate'].encode())])
                pipeline.end_epoch(0)  # Closure is explicit, independent of a short live clock.
                if guarded:
                    with self.assertRaises(JournalError): await pipeline.drain()
                    self.assertTrue(pipeline.failed.is_set())
                    self.assertIsNone(pipeline.channels[0]['result'])
                    auditor = pipeline.channels[0]['auditor']
                    self.assertFalse(auditor.results)
                    self.assertTrue(any('PARENT_AUDIT_PHASE_LIMIT' in s for s in auditor.errors))
                    self.assertGreater(auditor.peak_parent_phase_ns, 500_000_000)
                else:
                    await pipeline.drain()
                    for key in COMPARABLE:
                        self.assertEqual(encoded(pipeline.channels[0]['result'][key]), encoded(fix['expected'][key]), key)
                    self.assertGreater(pipeline.channels[0]['auditor'].jobs[0]['parent_validation_and_commit_ns'], 500_000_000)
                self.assertEqual(fired, ['after_audit_checkpoint_directory_fsync'])
            finally:
                await pipeline.close()
                self.assertEqual(budget.snapshot()['reserved_bytes'], 0)
                self.assertTrue(all(m.process is None for m in pipeline.managers()))
                budget.close()
            if guarded:
                # Existing offline successor recovery remains possible, explicitly.
                contract = dict(budget.contract); contract.pop('version')
                recovered_budget = ReservedStorageBudget.resume(fix['root'], **contract)
                owner = None
                try:
                    owner = IncrementalFeedAudit.resume(fix['root']/'replay-state', budget=recovered_budget,
                                                       contract=fix['contract'], anchor=anchor)
                    self.assertEqual(owner.receipt()['revision'], 1)
                finally:
                    if owner: owner.close()
                    recovered_budget.close()

    async def test_frozen_pipeline_reproduces_acceptance_after_closed_epoch_stall(self):
        await self.case(False)

    async def test_guard_rejects_same_closed_epoch_stall_and_recovers_successor(self):
        await self.case(True)


class CollectorIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_runner_rejects_stall_after_collect_epoch_has_returned(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()/'capture'
            closed = asyncio.Event()
            original_collect = frozen_collector.collect_epoch
            async def collect(*args, **kwargs):
                result = await original_collect(*args, **kwargs)
                closed.set()
                return result
            fired = []
            def hook(stage):
                if stage == 'after_audit_checkpoint_directory_fsync' and not fired:
                    self.assertTrue(closed.is_set())
                    fired.append(stage)
                    time.sleep(.6)
            def factory(owner, **kwargs):
                return BoundedParentAudits(owner, **kwargs, _hook=hook)
            with patch.object(frozen_collector, 'collect_epoch', side_effect=collect), \
                 patch.object(bounded, 'BoundedParentAudits', side_effect=factory):
                result = await bounded.run_bounded(root, duration_ns=10**9, transport=ScriptedTransport(),
                    policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json'),
                    pipeline_limits=PipelineLimits(seal_seconds=2))
            self.assertEqual(fired, ['after_audit_checkpoint_directory_fsync'])
            self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
            self.assertFalse(result['result_persisted'])
            self.assertEqual(result['combined']['quality']['status'], 'QUALITY_INPUTS_REJECTED')
            self.assertEqual(result['storage_after_result']['reserved_bytes'], 0)
            self.assertTrue(any('PARENT_AUDIT_PHASE_LIMIT' in e for e in result['errors']))
            self.assertFalse((root/'collection_result.json').exists())
            with lock_directory(root): pass

    async def test_bounded_parent_runner_completes_and_releases_storage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()/'capture'
            result = await bounded.run_bounded(root, duration_ns=10**9, transport=ScriptedTransport(),
                policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json'),
                pipeline_limits=PipelineLimits(seal_seconds=2))
            self.assertEqual(result['stop_reason'], 'ORIGINAL_DEADLINE', result['errors'])
            self.assertTrue(result['result_persisted'])
            self.assertEqual(result['storage_after_result']['reserved_bytes'], 0)
            self.assertEqual(result['pipeline']['channels'][0]['auditor']['parent_phase_limit_ns'], 500_000_000)
            with lock_directory(root): pass


if __name__ == '__main__': unittest.main()
