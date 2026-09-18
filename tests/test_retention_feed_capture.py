import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.research.data import retention_feed_capture as module
from app.research.data.durable_capture_log import JournalError, file_hash
from app.research.data.queued_feed_fixture import QueuedTransport
from app.research.data.retention_feed_capture import RetentionFeedCapture
from app.research.data.sealed_feed_pipeline import PipelineLimits
from tests.test_bounded_feed_collector import ScriptedTransport, ROOT, load_contract


class RetentionSupervisorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()/'run'
        self.owners = []
        self.policy = load_contract(ROOT/'configs/research/forward_data_policy_v1.json')

    def tearDown(self):
        for owner in self.owners:
            if not owner.running:
                owner.close()
        self.temp.cleanup()

    def create(self, *, seconds=.45, seal=.5, hook=lambda stage: None):
        owner = RetentionFeedCapture.create(self.root, duration_ns=int(seconds*1e9), policy=self.policy,
                    pipeline_limits=PipelineLimits(seal_seconds=seal), hook=hook)
        self.owners.append(owner)
        return owner

    def resume(self, handle, *, hook=lambda stage: None):
        owner = RetentionFeedCapture.resume(self.root, handle=handle, hook=hook)
        self.owners.append(owner)
        return owner

    async def collected(self, *, large=False, seal=.5):
        owner = self.create(seconds=1 if large else .45, seal=seal)
        result = await owner.run(QueuedTransport(per_tick=200, capacity=1024) if large else ScriptedTransport())
        self.assertEqual(result['stop_reason'], 'ORIGINAL_DEADLINE')
        return owner, result

    async def prepared(self):
        owner, result = await self.collected()
        decision = owner.prepare_closed_retention(0)
        self.assertTrue(decision['admitted'], decision)
        return owner, result, decision['handle']

    def inventory(self):
        return {str(p.relative_to(self.root)): (p.stat().st_size, file_hash(p))
                for p in self.root.rglob('*') if p.is_file()}

    def raws(self):
        return sorted(self.root.glob('capture-*/epoch-*/*/segment-*.jsonl'))

    async def test_new_capture_opts_in_before_data_under_shared_budget(self):
        owner, result = await self.collected()
        capture = self.root/'capture-00'
        self.assertEqual(json.loads((capture/'storage.json').read_text()), owner.budget.contract)
        self.assertTrue((capture/'raw_retention_policy.json').is_file())
        self.assertEqual(owner.budget.snapshot()['used_bytes'], sum(v[0] for v in self.inventory().values()))
        self.assertEqual(result['retention'], [])
        self.assertFalse(result['original_deletion'])

    async def test_preparation_is_separate_from_deletion_and_charges_registration(self):
        owner, result, handle = await self.prepared()
        self.assertTrue(self.raws())
        path = self.root/'retention-00.json'
        self.assertEqual(handle['retention_anchors']['00'], file_hash(path))
        before = self.inventory()
        owner.close()
        resumed = self.resume(handle)
        self.assertEqual(before, self.inventory())
        self.assertEqual(resumed.summary()['retention'][0]['phase'], 'PENDING')

    async def test_registered_restart_routes_to_gzip_and_preserves_audit(self):
        owner, result, handle = await self.prepared()
        owner.close()
        resumed = self.resume(handle)
        transport = ScriptedTransport()
        # Frozen raw-dependent interrupted recovery must not be invoked for an
        # ended, registered attempt whose original files may disappear.
        with patch('app.research.data.restartable_feed_capture.recover_admitted_work',
                   side_effect=AssertionError('raw recovery forbidden')):
            after = await resumed.run(transport)
        self.assertEqual(transport.connections, [])
        self.assertFalse(self.raws())
        self.assertEqual(after['retention'][0]['phase'], 'RETIRED')
        self.assertEqual(after['combined'], result['combined'])
        self.assertEqual(after['original_window'], result['original_window'])
        self.assertFalse(after['live_market_state_restored'])
        self.assertFalse(after['combined']['quality']['profitability_evaluation_ready'])

    async def test_repeated_retired_restart_writes_no_new_files(self):
        owner, result, handle = await self.prepared()
        await owner.run(ScriptedTransport())
        before = self.inventory()
        owner.close()
        resumed = self.resume(handle)
        one = await resumed.run(ScriptedTransport())
        two = await resumed.run(ScriptedTransport())
        self.assertEqual(one['retention'], two['retention'])
        self.assertEqual(before, self.inventory())

    async def test_unprofitable_preparation_does_not_write_registration(self):
        owner, result = await self.collected(seal=.1)
        before = self.inventory()
        decision = owner.prepare_closed_retention(0)
        self.assertFalse(decision['admitted'])
        self.assertEqual(before, self.inventory())
        self.assertEqual(decision['handle']['retention_anchors'], {})

    async def test_recovery_after_unlink_finishes_without_recreating_raw(self):
        owner, result, handle = await self.prepared()
        def hook(stage):
            if stage == 'retention:after_unlink':
                raise OSError('injected process-loss boundary')
        owner.hook = hook
        with self.assertRaises(OSError):
            await owner.run(ScriptedTransport())
        owner.close()
        resumed = self.resume(handle)
        self.assertEqual(resumed.summary()['retention'][0]['phase'], 'PENDING')
        self.assertTrue(resumed.summary()['original_deletion'])
        after = await resumed.run(ScriptedTransport())
        self.assertEqual(after['retention'][0]['phase'], 'RETIRED')
        self.assertFalse(self.raws())

    async def test_corrupt_archive_after_retirement_blocks_resume(self):
        owner, result, handle = await self.prepared()
        await owner.run(ScriptedTransport())
        owner.close()
        archive = next(self.root.glob('capture-*/epoch-*/*-archives/*.gz'))
        archive.write_bytes(archive.read_bytes()[:-1])
        before = self.inventory()
        with self.assertRaises(JournalError):
            self.resume(handle)
        self.assertEqual(before, self.inventory())

    async def test_missing_source_without_intent_blocks_resume(self):
        owner, result, handle = await self.prepared()
        owner.close()
        self.raws()[0].unlink()
        with self.assertRaisesRegex(JournalError, 'missing raw without'):
            self.resume(handle)

    async def test_reappeared_raw_preserved_and_resume_refused(self):
        owner, result, handle = await self.prepared()
        path = self.raws()[0]
        raw = path.read_bytes()
        await owner.run(ScriptedTransport())
        owner.close()
        path.write_bytes(raw)
        with self.assertRaisesRegex(JournalError, 'reappeared'):
            self.resume(handle)
        self.assertEqual(path.read_bytes(), raw)

    async def test_missing_registration_is_not_inferred_from_archive(self):
        owner, result, handle = await self.prepared()
        owner.close()
        (self.root/'retention-00.json').unlink()
        with self.assertRaisesRegex(JournalError, 'missing retention registration'):
            self.resume(handle)

    async def test_old_external_handle_cannot_silently_adopt_registration(self):
        owner, result = await self.collected()
        old_handle = owner.handle()
        owner.prepare_closed_retention(0)
        owner.close()
        with self.assertRaisesRegex(JournalError, 'unanchored'):
            self.resume(old_handle)

    async def test_changed_registration_binding_blocks_resume(self):
        owner, result, handle = await self.prepared()
        owner.close()
        path = self.root/'retention-00.json'
        path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(JournalError, 'external anchor differs'):
            self.resume(handle)

    async def test_missing_mode_contract_blocks_resume(self):
        owner, result = await self.collected()
        handle = owner.handle()
        owner.close()
        (self.root/'retention-mode.json').unlink()
        with self.assertRaisesRegex(JournalError, 'mode binding'):
            self.resume(handle)

    async def test_preparation_before_finish_refused(self):
        owner = self.create()
        with self.assertRaisesRegex(JournalError, 'finished idle'):
            owner.prepare_closed_retention(0)

    async def test_registration_write_failure_preserves_raw_and_orphan(self):
        owner, result = await self.collected()
        handle = owner.handle()
        before = self.raws()
        def hook(stage):
            if stage == 'retention_register:after_checkpoint_fsync':
                raise OSError('registration publication interrupted')
        owner.hook = hook
        with self.assertRaises(OSError):
            owner.prepare_closed_retention(0)
        self.assertEqual(before, self.raws())
        self.assertTrue(list(self.root.glob('.retention-00.json.*.tmp')))
        owner.close()
        with self.assertRaisesRegex(JournalError, 'unregistered retirement evidence'):
            self.resume(handle)

    async def test_declined_large_minimum_keeps_entire_run_unchanged(self):
        owner, result = await self.collected(large=True)
        before = self.inventory()
        decision = owner.prepare_closed_retention(0, minimum_net_savings_bytes=10**9)
        self.assertFalse(decision['admitted'])
        self.assertEqual(before, self.inventory())

    async def test_legacy_handle_cannot_open_new_retention_api(self):
        owner, result = await self.collected()
        handle = owner.handle()
        owner.close()
        with self.assertRaises(JournalError):
            self.resume({k:handle[k] for k in ('storage', 'supervisor_anchor')})

    async def test_ordinary_interrupt_still_uses_raw_recovery(self):
        fired = []
        def hook(stage):
            if stage == 'pipeline:before_audit_receipt' and not fired:
                fired.append(stage)
                raise OSError('ordinary collection interruption')
        owner = self.create(seconds=2.5, seal=.1, hook=hook)
        initial = owner.handle()
        with self.assertRaises(Exception):
            await owner.run(ScriptedTransport())
        owner.close()
        resumed = self.resume(initial)
        result = await resumed.run(ScriptedTransport())
        self.assertEqual(result['retention'], [])
        self.assertTrue(result['results'][0]['interrupted'])
        self.assertEqual(result['combined']['quality']['status'], 'QUALITY_INPUTS_REJECTED')
        self.assertFalse(result['live_market_state_restored'])
