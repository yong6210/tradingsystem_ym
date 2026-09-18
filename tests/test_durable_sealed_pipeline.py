import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.research.data.durable_capture_log import JournalError, encoded, decoded
from app.research.data.durable_sealed_pipeline import DurableSealedPipeline, guarded_command
from app.research.data.incremental_feed_audit import IncrementalFeedAudit
from app.research.data.pipelined_feed_collector import run_bounded
from app.research.data.recover_sealed_pipeline import recover_admitted_work
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.sealed_feed_pipeline import PipelineLimits
from app.research.data.snapshot_feed_audit import audit_epoch
from app.research.data.work_receipt_ledger import WorkReceiptLedger
from tests.incremental_audit_fixture import COMPARABLE
from tests.test_bounded_feed_collector import ScriptedTransport, load_contract, ROOT


class DurableCollectorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()/'capture'
        self.policy = load_contract(ROOT/'configs/research/forward_data_policy_v1.json')
        self.managers = []

    def tearDown(self): self.temp.cleanup()

    async def collect(self, stage=None, *, duration=450_000_000, transport=None, **kwargs):
        fired = []
        def hook(current):
            if current == stage and not fired:
                fired.append(current)
                raise OSError('injected '+current)
        def factory(budget, **options):
            manager = DurableSealedPipeline(budget, **options, _hook=hook)
            self.initial_anchor = manager.ledger.anchor()
            self.managers.append(manager)
            return manager
        result = await run_bounded(self.root, duration_ns=duration, transport=transport or ScriptedTransport(), policy=self.policy,
            pipeline_limits=PipelineLimits(seal_seconds=.1), _pipeline_factory=factory, **kwargs)
        if stage is not None: self.assertEqual(fired, [stage])
        return result

    def budget(self):
        contract = json.loads((self.root/'storage.json').read_text())
        return ReservedStorageBudget.resume(self.root, **{k:v for k,v in contract.items() if k!='version'})

    async def recover(self, anchor=None):
        budget = self.budget()
        try:
            result = await recover_admitted_work(budget, anchor=anchor or self.initial_anchor)
            self.assertEqual(budget.snapshot()['reserved_bytes'], 0)
            return result
        finally: budget.close()

    def same(self, actual, expected):
        for k in COMPARABLE: self.assertEqual(encoded(actual[k]), encoded(expected[k]), k)

    def check_receipts_once(self, before, recovered):
        events = [decoded(p.read_bytes()) for p in sorted((self.root/'work-ledger').glob('event-*.json'))]
        receipts = [e['payload']['receipt'] for e in events if e['kind'] in ('AUDIT','FINAL')]
        expected = {k:before[k] for k in ('revision','checkpoint_sha256')}
        self.assertEqual(receipts.count(expected), 1)
        self.assertEqual([r['revision'] for r in receipts], list(range(1,len(receipts)+1)))
        self.assertEqual(len(receipts), sum(e['kind']=='UNIT' for e in events)+sum(e['kind']=='FINAL' for e in events))
        self.assertEqual(recovered['epochs'][0]['summary']['receipt'], receipts[-1])

    async def test_live_code_path_ledger_matches_full_replay_and_recovery(self):
        result = await self.collect()
        self.assertEqual(result['stop_reason'], 'ORIGINAL_DEADLINE', result['errors'])
        self.assertTrue(result['pipeline']['work_ledger_complete'])
        recovered = await self.recover(result['pipeline']['work_ledger_anchor'])
        baseline = audit_epoch(self.root/'epoch-00/journal', self.root/'epoch-00/audit', **result['original_window'], max_intervals=10000)
        self.same(recovered['epochs'][0]['summary'], baseline)
        self.same(recovered['epochs'][0]['summary'], result['audits'][0])
        self.assertEqual(recovered['status'], 'ADMITTED_CLOSED_EPOCHS_RECOVERED')
        self.assertFalse(recovered['live_market_state_restored'])

    async def test_repeated_recovery_does_not_duplicate_audit_or_archives(self):
        result = await self.collect()
        first = await self.recover(result['pipeline']['work_ledger_anchor'])
        checkpoint = (self.root/'epoch-00/replay-state/checkpoint.json').read_bytes()
        archives = {str(p):p.read_bytes() for p in self.root.glob('epoch-*/*-archives/*')}
        second = await self.recover(first['work_ledger_anchor'])
        self.assertEqual(first['epochs'], second['epochs'])
        self.assertEqual(checkpoint, (self.root/'epoch-00/replay-state/checkpoint.json').read_bytes())
        self.assertEqual(archives, {str(p):p.read_bytes() for p in self.root.glob('epoch-*/*-archives/*')})

    async def test_unadmitted_seals_are_preserved_and_not_adopted(self):
        await self.collect('before_unit_admission')
        original = {str(p):p.read_bytes() for p in self.root.glob('epoch-*/journal/segment-*.jsonl')}
        recovered = await self.recover()
        self.assertEqual(recovered['epochs'][0]['summary']['last_audited_sequence'], 0)
        self.assertEqual(recovered['status'], 'ADMITTED_PREFIX_ONLY_INTERRUPTED_RUN')
        self.assertTrue(recovered['unadmitted_segment_files'])
        self.assertEqual(original, {str(p):p.read_bytes() for p in self.root.glob('epoch-*/journal/segment-*.jsonl')})

    async def test_temporary_unit_event_never_authorizes_work(self):
        await self.collect('UNIT:after_checkpoint_fsync')
        temps = {p:p.read_bytes() for p in (self.root/'work-ledger').glob('*.tmp')}
        self.assertTrue(temps)
        recovered = await self.recover()
        self.assertEqual(recovered['epochs'][0]['summary']['last_audited_sequence'], 0)
        self.assertTrue(all(p.read_bytes()==v for p,v in temps.items()))

    async def test_renamed_unit_without_ack_is_refsynced_and_recovered(self):
        await self.collect('UNIT:after_checkpoint_replace')
        recovered = await self.recover()
        self.assertGreater(recovered['epochs'][0]['summary']['last_audited_sequence'], 0)
        self.assertEqual(recovered['status'], 'ADMITTED_PREFIX_ONLY_INTERRUPTED_RUN')

    async def test_audit_checkpoint_before_receipt_does_not_replay_twice(self):
        await self.collect('before_audit_receipt')
        before = decoded((self.root/'epoch-00/replay-state/checkpoint.json').read_bytes())
        recovered = await self.recover()
        self.check_receipts_once(before, recovered)

    async def test_receipt_rename_without_ack_is_recovered(self):
        await self.collect('AUDIT:after_checkpoint_replace')
        before = decoded((self.root/'epoch-00/replay-state/checkpoint.json').read_bytes())
        recovered = await self.recover()
        self.check_receipts_once(before, recovered)

    async def test_durable_close_can_finish_remaining_work(self):
        result = await self.collect('CLOSED:after_checkpoint_replace')
        recovered = await self.recover()
        self.assertEqual(recovered['status'], 'ADMITTED_CLOSED_EPOCHS_RECOVERED')
        baseline = audit_epoch(self.root/'epoch-00/journal', self.root/'epoch-00/audit', **result['original_window'], max_intervals=10000)
        self.same(recovered['epochs'][0]['summary'], baseline)

    async def test_final_checkpoint_before_final_receipt_reconstructed_once(self):
        await self.collect('before_final_receipt')
        before = (self.root/'epoch-00/replay-state/checkpoint.json').read_bytes()
        recovered = await self.recover()
        self.assertTrue(recovered['work_ledger_complete'])
        self.assertEqual(before, (self.root/'epoch-00/replay-state/checkpoint.json').read_bytes())

    async def test_final_event_rename_without_ack_recovered(self):
        await self.collect('FINAL:after_checkpoint_replace')
        self.assertTrue((await self.recover())['work_ledger_complete'])

    async def test_complete_event_rename_without_ack_recovered(self):
        await self.collect('COMPLETE:after_checkpoint_replace')
        self.assertTrue((await self.recover())['work_ledger_complete'])

    async def test_external_latest_anchor_detects_removed_ledger_tail(self):
        result = await self.collect()
        path = sorted((self.root/'work-ledger').glob('event-*.json'))[-1]
        path.unlink()
        with self.assertRaisesRegex(JournalError, 'rollback'):
            await self.recover(result['pipeline']['work_ledger_anchor'])

    async def test_removed_middle_event_is_not_skipped(self):
        await self.collect()
        sorted((self.root/'work-ledger').glob('event-*.json'))[2].unlink()
        with self.assertRaisesRegex(JournalError, 'gap'):
            await self.recover()

    async def test_corrupt_event_is_not_used(self):
        await self.collect()
        path = sorted((self.root/'work-ledger').glob('event-*.json'))[2]
        row = decoded(path.read_bytes()); row['payload']['index'] += 1; path.write_bytes(encoded(row))
        with self.assertRaisesRegex(JournalError, 'checksum'):
            await self.recover()

    async def test_corrupt_registered_gzip_cannot_fall_back_to_raw(self):
        await self.collect()
        path = next(self.root.glob('epoch-*/raw-archives/*.gz'))
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaisesRegex(JournalError, 'archive mismatch'):
            await self.recover()

    async def test_corrupt_admitted_raw_rejected_even_with_good_gzip(self):
        await self.collect()
        path = next(self.root.glob('epoch-*/journal/segment-*.jsonl'))
        path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(JournalError, 'size or hash'):
            await self.recover()

    async def test_checkpoint_rollback_rejected_by_receipt(self):
        await self.collect()
        path = self.root/'epoch-00/replay-state/checkpoint.json'
        row = decoded(path.read_bytes()); row['revision'] = 0
        from app.research.data.sealed_segment_handoff import sha
        row['checkpoint_sha256'] = sha(encoded({k:v for k,v in row.items() if k!='checkpoint_sha256'}))
        path.write_bytes(encoded(row))
        with self.assertRaisesRegex(JournalError, 'rollback'):
            await self.recover()

    async def test_checkpoint_at_unadmitted_endpoint_rejected(self):
        await self.collect('before_audit_receipt')
        path = self.root/'epoch-00/replay-state/checkpoint.json'
        row = decoded(path.read_bytes()); row['state']['finalized'] = True
        from app.research.data.sealed_segment_handoff import sha
        row['checkpoint_sha256'] = sha(encoded({k:v for k,v in row.items() if k!='checkpoint_sha256'}))
        path.write_bytes(encoded(row))
        with self.assertRaises(JournalError): await self.recover()

    async def test_recovery_receipt_fault_can_resume_without_duplicate_work(self):
        await self.collect('UNIT:after_checkpoint_replace')
        budget = self.budget()
        def fail(stage):
            if stage == 'recovery_before_audit_receipt': raise OSError('lost recovery ack')
        try:
            with self.assertRaises(OSError):
                await recover_admitted_work(budget, anchor=self.initial_anchor, hook=fail)
            self.assertEqual(budget.snapshot()['reserved_bytes'], 0)
        finally: budget.close()
        before = (self.root/'epoch-00/replay-state/checkpoint.json').read_bytes()
        await self.recover()
        self.assertEqual(before, (self.root/'epoch-00/replay-state/checkpoint.json').read_bytes())

    async def test_recovery_refuses_changed_implementation_binding(self):
        await self.collect()
        from app.research.data import work_receipt_ledger as module
        with patch.object(module, 'implementation_hashes', return_value={}):
            with self.assertRaisesRegex(JournalError, 'implementation'):
                await self.recover()

    async def test_second_ledger_owner_rejected(self):
        await self.collect()
        budget = self.budget(); first = WorkReceiptLedger.resume(self.root/'work-ledger', budget=budget, anchor=self.initial_anchor)
        try:
            with self.assertRaises(JournalError):
                WorkReceiptLedger.resume(self.root/'work-ledger', budget=budget, anchor=self.initial_anchor)
        finally: first.close(); budget.close()

    async def test_recording_duplicate_receipt_rejected(self):
        await self.collect()
        budget = self.budget(); ledger = WorkReceiptLedger.resume(self.root/'work-ledger', budget=budget, anchor=self.initial_anchor)
        try:
            with self.assertRaises(JournalError):
                ledger.append('AUDIT', dict(unit=0, receipt=ledger.model['units'][0]['receipt']))
        finally: ledger.close(); budget.close()

    async def test_recovery_has_no_network_path(self):
        await self.collect()
        with patch('app.research.data.public_feed_transport.PublicFeedTransport.connect', side_effect=AssertionError('network forbidden')):
            recovered = await self.recover()
        self.assertEqual(recovered['resumed_network_requests'], 0)

    async def test_reconnected_epochs_recover_without_merging_the_gap(self):
        result = await self.collect(duration=1_700_000_000, transport=ScriptedTransport(disconnect_first=True))
        self.assertEqual(result['stop_reason'], 'ORIGINAL_DEADLINE', result['errors'])
        self.assertEqual(len(result['audits']), 2)
        recovered = await self.recover(result['pipeline']['work_ledger_anchor'])
        self.assertEqual(len(recovered['epochs']), 2)
        for epoch, expected in zip(recovered['epochs'], result['audits']):
            self.same(epoch['summary'], expected)
        self.assertFalse(recovered['full_original_run_certified'])

    async def test_cancel_recovery_releases_reservations_and_can_resume(self):
        await self.collect('UNIT:after_checkpoint_replace')
        budget = self.budget(); entered = asyncio.Event()
        async def hold(manager, job):
            entered.set()
            await asyncio.Event().wait()
        try:
            with patch('app.research.data.recover_sealed_pipeline.wait_result', side_effect=hold):
                task = asyncio.create_task(recover_admitted_work(budget, anchor=self.initial_anchor))
                await asyncio.wait_for(entered.wait(), 3)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await asyncio.wait_for(task, 3)
            self.assertEqual(budget.snapshot()['reserved_bytes'], 0)
        finally: budget.close()
        recovered = await self.recover()
        self.assertGreater(recovered['epochs'][0]['summary']['last_audited_sequence'], 0)


class GuardianTests(unittest.IsolatedAsyncioTestCase):
    async def test_independent_lifetime_exits_while_stdin_is_still_open(self):
        proc = await asyncio.create_subprocess_exec(*guarded_command('audit', .15), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            await asyncio.wait_for(proc.wait(), 3)
            self.assertEqual(proc.returncode, 73)
        finally:
            if proc.returncode is None: proc.kill()
            await proc.communicate()

    async def test_wrong_parent_exits_before_request(self):
        command = guarded_command('archive', 1); command[command.index('--parent')+1] = '99999999'
        proc = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await asyncio.wait_for(proc.communicate(), 3)
        self.assertEqual(proc.returncode, 73)
