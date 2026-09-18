import asyncio
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch

from app.research.data.capture_failure_boundary import GuardedRestartableFeedCapture
from app.research.data.durable_capture_log import JournalError, decoded, encoded, file_hash, lock_directory
from app.research.data import guarded_generation_capture as guarded
from app.research.data.queued_feed_fixture import QueuedTransport
from app.research.data.restartable_feed_capture import RestartableFeedCapture
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.durable_sealed_pipeline import DurableSealedPipeline
from app.research.data.scoped_feed_budget import ScopedFeedBudget
from app.research.data.sealed_segment_handoff import SealTicket
from tests.test_bounded_feed_collector import ScriptedTransport, load_contract, ROOT
from tests.test_retained_feed_collector import inventory
from tests import test_retention_feed_capture as retention
from tests.fixed_capture_fixture import populate_closed_attempt
from tests.incremental_audit_fixture import fixture, jobs, COMPARABLE
from tests.test_pipelined_feed_collector import fault_factory, until
from tests import test_incremental_generation_capture as incremental
from tests import test_archived_generation_capture as archived
from app.research.data.retained_sealed_journal import RetainedSealedJournal
from app.research.data.recovery_custody_journal import RecoveryCustodyJournal


def simulated_space(test):
    # Isolate behavior from the host's currently insufficient 16GiB reserve.
    # Production policy is unchanged; these are explicitly OFFLINE unit tests.
    mock = patch('app.research.data.shared_feed_storage.shutil.disk_usage',
                 return_value=SimpleNamespace(free=64*1024**3))
    mock.start()
    test.addCleanup(mock.stop)


class StorageFailureBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        simulated_space(self)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()/'capture'
        self.policy = load_contract(ROOT/'configs/research/forward_data_policy_v1.json')
        self.owner = GuardedRestartableFeedCapture.create(self.root, duration_ns=60*10**9, policy=self.policy)

    def tearDown(self):
        self.owner.close()
        self.temp.cleanup()

    async def failed_collection(self):
        captured = {}
        async def fail(epoch, transport, *, audit_control):
            audit_control.fail('INJECTED_ORIGINAL_STORAGE_CAUSE')
            captured['before'] = inventory(self.root)
            return dict(outcome='FATAL_FAILURE', reason='INJECTED_ORIGINAL_STORAGE_CAUSE')
        with patch('app.research.data.restartable_feed_capture.collect_epoch', side_effect=fail):
            result = await self.owner.run(ScriptedTransport())
        return result, captured['before']

    async def test_failed_budget_preserves_original_reason_without_result_write(self):
        result, before = await self.failed_collection()
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
        self.assertIn('INJECTED_ORIGINAL_STORAGE_CAUSE', result['errors'])
        self.assertEqual(inventory(self.root), before)
        self.assertFalse(result['result_persisted'])
        self.assertFalse(result['completion_receipt_acknowledged'])
        self.assertTrue(self.owner.budget.failed)
        self.assertIsNone(self.owner.log.state['finish'])
        self.assertIsNone(self.owner.log.state['attempts'][0]['end'])
        self.assertEqual(result['storage']['reserved_bytes'], 0)

    async def test_repeat_failed_owner_never_retries_or_opens_transport(self):
        first, _ = await self.failed_collection()
        before = inventory(self.root)
        transport = ScriptedTransport()
        second = await self.owner.run(transport)
        self.assertEqual(first, second)
        self.assertEqual(transport.connections, [])
        self.assertEqual(inventory(self.root), before)
        second['errors'].clear()
        self.assertTrue((await self.owner.run(transport))['errors'])

    async def test_result_publication_failure_preserves_temporary_and_no_end(self):
        owner = self.owner
        at = owner.plan['window_start_ns']
        owner.log.append('ATTEMPT', dict(index=0, admitted_ns=at, wake_ns=at))
        original = owner.budget.atomic_json
        def atomic(path, value, hook=lambda stage:None):
            def fail(stage):
                if stage == 'after_checkpoint_fsync': raise OSError('INJECTED_RESULT_FSYNC_ACK_LOSS')
            return original(path, value, fail if path.name.startswith('result-') else hook)
        async def end_only(instance, transport):
            instance._end(0, 'FATAL_FAILURE', dict(epoch=dict(reason='ORIGINAL_INPUT_FAILURE'), pipeline={}))
        with patch.object(owner.budget, 'atomic_json', side_effect=atomic), patch.object(RestartableFeedCapture, 'run', end_only):
            result = await owner.run(ScriptedTransport())
        self.assertFalse(result['result_persisted'])
        self.assertIn('ORIGINAL_INPUT_FAILURE', result['errors'])
        self.assertTrue(any('INJECTED_RESULT_FSYNC_ACK_LOSS' in error for error in result['errors']))
        self.assertTrue(list(self.root.glob('.result-*.tmp')))
        self.assertFalse(list(self.root.glob('result-*.json')))
        self.assertIsNone(owner.log.state['attempts'][0]['end'])

    async def test_healthy_storage_errors_are_not_silently_converted(self):
        with patch.object(RestartableFeedCapture, 'run', side_effect=ValueError('contract differs')):
            with self.assertRaisesRegex(ValueError, 'contract differs'):
                await self.owner.run(ScriptedTransport())

    async def test_end_ack_loss_keeps_written_receipt_unconfirmed(self):
        owner = self.owner
        at = owner.plan['window_start_ns']
        owner.log.append('ATTEMPT', dict(index=0, admitted_ns=at, wake_ns=at))
        def fail(stage):
            if stage == 'supervisor:END:after_checkpoint_replace':
                raise OSError('INJECTED_END_ACK_LOSS')
        owner.log.hook = fail
        async def end_only(instance, transport):
            instance._end(0, 'ORIGINAL_DEADLINE', dict(audits=[], interrupted=False))
        with patch.object(RestartableFeedCapture, 'run', end_only):
            result = await owner.run(ScriptedTransport())
        self.assertFalse(result['completion_receipt_acknowledged'])
        self.assertFalse(result['durable_result_acknowledged'])
        self.assertTrue(result['physical_result_files_may_exist'])
        self.assertEqual(len(list(self.root.glob('result-*.json'))), 1)
        last = sorted((self.root/'receipts').glob('event-*.json'))[-1]
        self.assertEqual(decoded(last.read_bytes())['kind'], 'END')
        self.assertIsNone(owner.log.state['attempts'][0]['end'])

    async def test_cancel_is_not_reported_as_an_ordinary_failure(self):
        with patch.object(RestartableFeedCapture, 'run', side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError): await self.owner.run(ScriptedTransport())

    async def receipt_recovery(self, stage):
        owner = self.owner
        initial = owner.handle()
        at = owner.plan['window_start_ns']
        owner.log.append('ATTEMPT', dict(index=0, admitted_ns=at, wake_ns=at))
        root = owner.capture_root(0)
        root.mkdir()
        fired = []
        def fail(current):
            if current == stage:
                fired.append(current)
                raise OSError('INJECTED_RECEIPT_ACK_LOSS')
        owner.hook = fail
        owner.log.hook = fail
        pipeline = None
        try:
            with self.assertRaisesRegex(OSError, 'INJECTED_RECEIPT_ACK_LOSS'):
                pipeline = DurableSealedPipeline(ScopedFeedBudget(owner.budget, root), _hook=owner._receipt_hook(0))
        finally:
            if pipeline is not None: await pipeline.close()
        self.assertEqual(fired, [stage])
        preserved = {p:p.read_bytes() for p in (self.root/'receipts').glob('*.tmp')}
        owner.close()
        self.owner = GuardedRestartableFeedCapture.resume(self.root, handle=initial)
        await self.owner._recover_interrupted()
        self.assertEqual(len(self.owner.log.state['attempts']), 1)
        self.assertEqual(preserved, {p:p.read_bytes() for p in preserved})
        return self.owner._results()[0]

    async def test_receipt_temporary_does_not_authorize_old_epoch(self):
        result = await self.receipt_recovery('supervisor:RECEIPT:after_checkpoint_fsync')
        self.assertEqual(result['outcome'], 'ABANDONED_BEFORE_RECEIPT')
        self.assertEqual(result['audits'], [])

    async def test_renamed_receipt_is_recovered_before_any_new_attempt(self):
        result = await self.receipt_recovery('supervisor:RECEIPT:after_checkpoint_replace')
        self.assertEqual(result['outcome'], 'PROCESS_INTERRUPTED')
        self.assertTrue(result['interrupted'])


class SetupDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_late_setup_preserves_deadline_files_and_never_connects(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()/'capture'
            start = time.monotonic_ns()
            stamps = iter((start, start+100_000_000))
            transport = QueuedTransport()
            with patch.object(guarded, 'time', SimpleNamespace(monotonic_ns=lambda:next(stamps))):
                result = await guarded.run_synthetic_capture(root, duration_ns=100_000_000, transport=transport)
            self.assertEqual(result['phase'], 'EPOCH_SETUP')
            self.assertEqual(result['outcome'], 'FATAL_FAILURE')
            self.assertEqual(transport.connections, [])
            self.assertFalse(result['result_persisted'])
            self.assertEqual(result['original_window']['window_end_ns'], start+100_000_000)
            self.assertFalse(list(root.glob('generation-*/end.json')))
            self.assertEqual(result['pipeline']['submitted'], 0)
            self.assertTrue(result['pipeline']['children_reaped'])
            with lock_directory(root): pass

    async def test_setup_exception_after_precheck_is_reported_without_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()/'capture'
            transport = QueuedTransport()
            with patch.object(guarded, 'ArchivedGenerationEpoch', side_effect=ValueError('late during constructor')):
                result = await guarded.run_synthetic_capture(root, duration_ns=10**9, transport=transport)
            self.assertTrue(any('late during constructor' in e for e in result['errors']))
            self.assertEqual(transport.connections, [])
            self.assertFalse(result['completion_receipt_acknowledged'])
            with lock_directory(root): pass

    async def test_store_cleanup_error_still_releases_root_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()/'capture'
            constructor = guarded.ArchivedGenerationStore
            def create(*args, **kwargs):
                store = constructor(*args, **kwargs)
                close = store.close
                def fail():
                    close()
                    raise OSError('INJECTED_STORE_CLEANUP_ERROR')
                store.close = fail
                return store
            with patch.object(guarded, 'ArchivedGenerationStore', side_effect=create), \
                    patch.object(guarded, 'ArchivedGenerationEpoch', side_effect=ValueError('setup failed')):
                with self.assertRaisesRegex(OSError, 'INJECTED_STORE_CLEANUP_ERROR'):
                    await guarded.run_synthetic_capture(root, duration_ns=10**9, transport=QueuedTransport())
            with lock_directory(root): pass


class FixedRetentionPreconditions(unittest.IsolatedAsyncioTestCase):
    """Same five failed assertions; replace only wall-clock-generated preparation."""
    def setUp(self):
        simulated_space(self)
        retention.RetentionSupervisorTests.setUp(self)
    tearDown = retention.RetentionSupervisorTests.tearDown
    create = retention.RetentionSupervisorTests.create
    resume = retention.RetentionSupervisorTests.resume
    prepared = retention.RetentionSupervisorTests.prepared
    inventory = retention.RetentionSupervisorTests.inventory
    raws = retention.RetentionSupervisorTests.raws

    async def collected(self, **kwargs):
        owner = self.create(seconds=60)
        result = await populate_closed_attempt(owner)
        self.assertEqual(result['stop_reason'], 'ORIGINAL_DEADLINE')
        evidence = owner._results()[0]
        self.assertTrue(evidence['offline_fixture'])
        self.assertEqual(evidence['modeled_raw_records'], 152)
        self.assertEqual(evidence['modeled_audit_batches'], 81)
        return owner, result

    test_changed_registration_binding_blocks_resume = retention.RetentionSupervisorTests.test_changed_registration_binding_blocks_resume
    test_preparation_is_separate_from_deletion_and_charges_registration = retention.RetentionSupervisorTests.test_preparation_is_separate_from_deletion_and_charges_registration
    test_reappeared_raw_preserved_and_resume_refused = retention.RetentionSupervisorTests.test_reappeared_raw_preserved_and_resume_refused
    test_recovery_after_unlink_finishes_without_recreating_raw = retention.RetentionSupervisorTests.test_recovery_after_unlink_finishes_without_recreating_raw
    test_registration_write_failure_preserves_raw_and_orphan = retention.RetentionSupervisorTests.test_registration_write_failure_preserves_raw_and_orphan


class FreeSpaceGuardTests(unittest.TestCase):
    def test_exact_reserve_boundary_includes_pending_growth(self):
        with tempfile.TemporaryDirectory() as temp:
            reserve = 16*1024**3
            with patch('app.research.data.shared_feed_storage.shutil.disk_usage',
                       return_value=SimpleNamespace(free=64*1024**3)):
                budget = ReservedStorageBudget.create(Path(temp).resolve()/'capture', run_id='boundary',
                    max_bytes=1024**2, min_free_bytes=reserve)
            try:
                with patch('app.research.data.shared_feed_storage.shutil.disk_usage',
                           return_value=SimpleNamespace(free=reserve+65536+42)):
                    budget.check(42)
                    with self.assertRaisesRegex(JournalError, 'free-space'): budget.check(43)
                self.assertEqual(budget.contract['min_free_bytes'], reserve)
            finally: budget.close()

    def test_low_space_rejects_before_journal_or_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()/'capture'
            with patch('app.research.data.shared_feed_storage.shutil.disk_usage',
                       return_value=SimpleNamespace(free=16*1024**3-1)):
                with self.assertRaisesRegex(JournalError, 'free-space'):
                    GuardedRestartableFeedCapture.create(root, duration_ns=60*10**9,
                        policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json'))
            self.assertFalse((root/'storage.json').exists())
            with lock_directory(root): pass


class CountDrivenSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_archive_progresses_while_first_audit_is_explicitly_gated(self):
        with tempfile.TemporaryDirectory() as temp:
            fix = fixture(Path(temp).resolve(), raw_step=32, audit_step=11)
            release = Path(temp)/'release'
            pipeline = fault_factory(audit='gate', release=release)(fix['budget'])
            try:
                # Two prebuilt units, no live producer and no 800ms collection
                # assumption. Existing backlog and worker timeouts remain fixed.
                contract = fix['contract']
                from app.research.data.archive_segment_reader import restore_cursor
                pipeline.add_epoch(fix['root'], restore_cursor(contract['raw_initial']),
                                   restore_cursor(contract['audit_initial']), fix['scope'])
                units = jobs(fix)
                self.assertEqual(len(units), 2)
                for audit_ref, raw_refs in units:
                    pipeline.submit(0, [SealTicket(r['certificate'].encode()) for r in raw_refs],
                                    [SealTicket(audit_ref['certificate'].encode())])
                pipeline.end_epoch(0)
                await until(lambda:pipeline.audit_archive_overlap_samples > 0 or pipeline.failed.is_set())
                self.assertFalse(pipeline.failed.is_set(), pipeline.errors)
                release.touch()
                await pipeline.drain()
                self.assertGreater(pipeline.audit_archive_overlap_samples, 0)
                for field in COMPARABLE:
                    self.assertEqual(encoded(pipeline.channels[0]['result'][field]), encoded(fix['expected'][field]), field)
            finally:
                await pipeline.close()
                self.assertEqual(fix['budget'].snapshot()['reserved_bytes'], 0)
                fix['budget'].close()


class GuardedGenerationIntegrationTests(incremental.IncrementalEvidenceTests):
    @classmethod
    def setUpClass(cls):
        with patch.object(incremental, 'run_synthetic_capture', guarded.run_synthetic_capture):
            super().setUpClass()


class GuardedFailureInjectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        archived.ArchiveFailureTests.setUp(self)
        runner = patch.object(archived, 'run_synthetic_capture', guarded.run_synthetic_capture)
        runner.start()
        self.addCleanup(runner.stop)

    tearDown = archived.ArchiveFailureTests.tearDown
    test_worker_failure_interrupts_collection_and_releases_reservations = archived.ArchiveFailureTests.test_worker_failure_interrupts_collection_and_releases_reservations
    test_parent_storage_stall_rejected = archived.ArchiveFailureTests.test_parent_storage_stall_rejected


class FixedUncertainSuffixTests(unittest.TestCase):
    def case(self, sealed):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()/'capture'
            budget = ReservedStorageBudget.create(root, run_id='fixed-tail', max_bytes=1024**2, min_free_bytes=0)
            writer = RetainedSealedJournal.create(root/'raw', budget=budget, run_id='fixed-tail',
                rotation_bytes=128*1024, max_record_bytes=65536)
            try:
                writer.append(dict(committed='known record'))
                if sealed: writer.seal()
                else: writer.commit()
                handle = writer.handle()
                source = root/'raw'/writer.cp['segments'][0]['name']
                if sealed:
                    writer.close()
                    with source.open('ab') as stream: stream.write(b'untrusted suffix')
                else:
                    writer.append(dict(uncertain='not a market observation'))
                    writer.close()
                before = inventory(root)
                if sealed:
                    with self.assertRaisesRegex(JournalError, 'sealed raw has uncertain suffix'):
                        RecoveryCustodyJournal.open_for_recovery(root/'raw', budget=budget, handle=handle)
                else:
                    recovered = RecoveryCustodyJournal.open_for_recovery(root/'raw', budget=budget, handle=handle)
                    try:
                        self.assertEqual(recovered.cp['last_sequence'], 1)
                        self.assertEqual(len(recovered.preserved_suffixes), 1)
                        self.assertGreater(recovered.preserved_suffixes[0]['extra_bytes'], 0)
                        with self.assertRaisesRegex(JournalError, 'cannot append'):
                            recovered.append(dict(not_allowed=True))
                    finally: recovered.close()
                self.assertEqual(inventory(root), before)
            finally:
                writer.close(); budget.close()

    def test_unsealed_uncommitted_suffix_is_preserved_without_adoption(self): self.case(False)
    def test_sealed_suffix_is_rejected_without_truncation(self): self.case(True)


if __name__ == '__main__': unittest.main()
