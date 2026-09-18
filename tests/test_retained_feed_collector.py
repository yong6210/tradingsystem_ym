"""Collector-level custody, audit parity, refusal and interrupted work tests."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.research.data.archive_segment_reader import restore_cursor, segment_ref
from app.research.data.collector_custody_ledger import CustodyLedger, validate_work
from app.research.data.durable_capture_log import JournalError, encoded, decoded, file_hash
from app.research.data.retained_feed_collector import run_bounded
from app.research.data.retained_feed_pipeline import RetainedFeedPipeline
from app.research.data.recover_retained_pipeline import recover_retained_work
from app.research.data.recover_sealed_pipeline import archive_identity
from app.research.data.retirement_admission import SizingReplay
from app.research.data.queued_feed_fixture import QueuedTransport
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.sealed_feed_pipeline import PipelineLimits
from app.research.data.sealed_segment_handoff import SealTicket, certificate, sha
from app.research.data.work_receipt_ledger import WorkReceiptLedger
from tests.incremental_audit_fixture import COMPARABLE
from tests.test_bounded_feed_collector import ScriptedTransport, load_contract, ROOT


def inventory(root):
    return {str(p.relative_to(root)):(p.stat().st_size,file_hash(p)) for p in root.rglob('*') if p.is_file()}


def cold_replay(root):
    """Cold full gzip replay from revision zero; no saved processor state."""
    events = [decoded(p.read_bytes()) for p in sorted((root/'work-ledger').glob('event-*.json'))]
    groups = []
    for event in events:
        if event['kind'] == 'EPOCH': groups.append(dict(contract=event['payload']['contract'],units=[],closed=False))
        if event['kind'] == 'UNIT': groups[event['payload']['channel']]['units'].append(event['payload'])
        if event['kind'] == 'CLOSED': groups[event['payload']['channel']]['closed'] = event['payload']
    results = []
    for group in groups:
        replay = SizingReplay.cold(group['contract'])
        for unit in group['units']:
            refs = []
            for kind,key in [('raw','raw_tickets'), ('audit','audit_tickets')]:
                for text in unit[key]:
                    ticket = SealTicket(text.encode()); row = certificate(ticket.certificate)
                    archive_id = sha(encoded(archive_identity(row)))
                    directory = str(Path(row['journal']).parent/(kind+'-archives'))
                    refs.append(segment_ref(ticket,archive_directory=directory,archive_id=archive_id))
            replay.advance(audit_ref=refs[-1],raw_refs=refs[:-1])
        if group['closed']:
            replay.finalize(**{k:restore_cursor(group['closed'][k]) for k in ('raw_cursor','audit_cursor')})
        results.append(replay.summary())
    return results


class RetainedCollectorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()/'capture'
        self.policy = load_contract(ROOT/'configs/research/forward_data_policy_v1.json')
        self.managers = []

    def tearDown(self): self.temp.cleanup()

    async def collect(self, stage=None, *, seconds=1.25, small=False, disconnect=None, hook_extra=lambda s:None):
        fired = []
        def hook(current):
            hook_extra(current)
            if current == stage and not fired:
                fired.append(current)
                raise OSError('injected '+current)
        def factory(budget, **options):
            pipeline = RetainedFeedPipeline(budget, **options, _hook=hook)
            self.managers.append(pipeline); self.initial_handle = pipeline.handle()
            return pipeline
        result = await run_bounded(self.root, duration_ns=int(seconds*1e9),
            transport=ScriptedTransport() if small else QueuedTransport(per_tick=20),
            policy=self.policy, pipeline_limits=PipelineLimits(seal_seconds=.5),
            disconnect_once_after_ns=disconnect, _pipeline_factory=factory)
        self.handle = result['pipeline']['retention_handle']
        if stage: self.assertEqual(fired,[stage], result['errors'])
        return result

    def budget(self):
        contract = json.loads((self.root/'storage.json').read_text()); contract.pop('version')
        return ReservedStorageBudget.resume(self.root, **contract)

    async def recover(self, handle=None):
        budget = self.budget()
        try:
            result = await recover_retained_work(budget,handle=handle or self.handle)
            self.assertEqual(budget.snapshot()['reserved_bytes'],0)
            return result
        finally: budget.close()

    def same(self, a, b):
        for field in COMPARABLE: self.assertEqual(encoded(a[field]), encoded(b[field]), field)

    async def test_active_retirement_and_mixed_recovery_match_cold_17_fields(self):
        result = await self.collect(seconds=2)
        self.assertEqual(result['stop_reason'],'ORIGINAL_DEADLINE',result['errors'])
        p = result['pipeline']
        self.assertGreater(p['logical_raw_bytes_removed_while_epoch_open'],0)
        self.assertEqual(p['retirement_checked_units'],len(p['units']))
        recovered = await self.recover()
        self.assertGreater(recovered['gzip_source_reads'],0); self.assertGreater(recovered['raw_source_reads'],0)
        cold, = cold_replay(self.root)
        self.same(cold,result['audits'][0]); self.same(cold,recovered['epochs'][0]['summary'])
        self.assertEqual(recovered['status'],'ADMITTED_CLOSED_EPOCHS_RECOVERED')
        self.assertFalse(recovered['live_market_state_restored'])
        self.assertEqual(recovered['resumed_network_requests'],0)

    async def test_repeated_recovery_does_not_duplicate_work_or_custody(self):
        await self.collect()
        first = await self.recover(); before = inventory(self.root)
        second = await self.recover(first['retention_handle']); after = inventory(self.root)
        self.assertEqual(first['epochs'],second['epochs'])
        self.assertEqual({p:v for p,v in before.items() if p in after},{p:after[p] for p in before})
        added = set(after)-set(before)
        self.assertEqual(len(added),1)
        self.assertTrue(next(iter(added)).startswith('work-ledger/event-'))
        self.assertEqual(second['logical_raw_bytes_removed_this_call'],0)

    async def test_small_segments_remain_raw_with_no_retention_events(self):
        result = await self.collect(seconds=.08,small=True)
        self.assertFalse(result['original_deletion'])
        self.assertFalse(self.managers[0].custody.model['retained'])
        recovered = await self.recover()
        self.assertEqual(recovered['gzip_source_reads'],0)
        self.same(cold_replay(self.root)[0],recovered['epochs'][0]['summary'])

    async def test_economic_gate_includes_registry_and_setup_cost(self):
        result = await self.collect()
        p = result['pipeline']; candidates = []
        for unit in p['retirement_decisions']:
            self.assertLessEqual(unit['registry_bytes'],unit['registry_cost_upper_bound'])
            for c in unit['candidates']:
                if c['admitted']:
                    self.assertGreater(c['normal_path_net_savings_bytes'],
                        unit['registry_cost_upper_bound']+unit['setup_cost_charged_per_candidate'])
                    candidates.append(c)
        self.assertTrue(candidates)
        metadata = sum(v[0] for name,v in inventory(self.root).items()
            if '/custody/' in name or name.endswith('custody-policy.json') or name.startswith('collector-custody/'))
        self.assertGreater(p['logical_raw_bytes_removed'],metadata)

    async def test_receipt_persisted_before_any_unlink_and_no_workers_reserved(self):
        observations = []
        def hook(stage):
            if stage == 'custody_before_unlink':
                pipeline = self.managers[0]
                validate_work(pipeline.custody,pipeline.ledger)
                self.assertEqual(pipeline.budget.snapshot()['reserved_bytes'],0)
                observations.append(len(pipeline.custody.model['retained']))
        await self.collect(hook_extra=hook)
        self.assertTrue(observations); self.assertTrue(all(observations))

    async def test_registration_ack_loss_before_unlink_recovers(self):
        result = await self.collect('collector_retention_registered')
        self.assertEqual(result['stop_reason'],'FATAL_FAILURE')
        recovered = await self.recover(self.initial_handle)
        self.assertGreater(recovered['logical_raw_bytes_removed_this_call'],0)
        self.assertEqual(recovered['status'],'ADMITTED_PREFIX_ONLY_INTERRUPTED_RUN')
        self.assertFalse(recovered['epochs'][0]['summary']['clean_stop_audited'])

    async def test_retention_event_rename_loss_is_refsynced(self):
        await self.collect('RETAIN:after_checkpoint_replace')
        recovered = await self.recover(self.initial_handle)
        self.assertGreater(recovered['gzip_source_reads'],0)

    async def test_unlink_before_completion_receipt_recovers(self):
        result = await self.collect('custody_after_unlink')
        self.assertTrue(result['original_deletion'])
        self.assertGreater(result['pipeline']['logical_raw_bytes_removed'],0)
        recovered = await self.recover()
        self.assertGreater(recovered['gzip_source_reads'],0)
        self.assertFalse(recovered['continuous_runtime_coverage_certified'])

    async def test_intent_temporary_preserved_during_recovery(self):
        await self.collect('custody_intent:after_checkpoint_fsync')
        temps = {p:p.read_bytes() for p in self.root.rglob('*.tmp')}
        self.assertTrue(temps)
        await self.recover()
        self.assertTrue(all(p.read_bytes()==v for p,v in temps.items()))

    async def test_unanchored_registration_is_preserved_and_refused(self):
        await self.collect('custody_register:after_checkpoint_replace')
        before = inventory(self.root)
        with self.assertRaisesRegex(JournalError,'unanchored'):
            await self.recover(self.initial_handle)
        self.assertEqual(before,inventory(self.root))

    async def test_retention_event_temporary_never_authorizes_deletion(self):
        await self.collect('RETAIN:after_checkpoint_fsync')
        before = inventory(self.root)
        with self.assertRaisesRegex(JournalError,'unanchored'):
            await self.recover(self.initial_handle)
        self.assertEqual(before,inventory(self.root))

    async def test_missing_custody_ledger_tail_rejected_by_latest_anchor(self):
        await self.collect()
        sorted((self.root/'collector-custody').glob('event-*.json'))[-1].unlink()
        with self.assertRaisesRegex(JournalError,'rollback'):
            await self.recover()

    async def test_missing_work_audit_cannot_authorize_registered_custody(self):
        await self.collect()
        # Delete a middle event: neither ledger gaps nor custody may excuse it.
        for p in sorted((self.root/'work-ledger').glob('event-*.json')):
            if decoded(p.read_bytes())['kind']=='AUDIT': p.unlink(); break
        with self.assertRaisesRegex(JournalError,'gap'):
            await self.recover()

    async def test_corrupt_gzip_cannot_fall_back_to_retained_raw(self):
        await self.collect()
        path = next(self.root.glob('epoch-*/audit-archives/*.gz'))
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaises(JournalError): await self.recover()

    async def test_corrupt_retired_gzip_rejected(self):
        await self.collect()
        path = next(self.root.glob('epoch-*/raw-archives/*.gz'))
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaises(JournalError): await self.recover()

    async def test_missing_retained_raw_without_intent_rejected(self):
        await self.collect()
        next(self.root.glob('epoch-*/audit/segment-*.jsonl')).unlink()
        with self.assertRaises(JournalError): await self.recover()

    async def test_reappeared_retired_source_rejected(self):
        await self.collect()
        registration = next(self.root.glob('epoch-*/journal/custody/segment-*.jsonl.json'))
        row = decoded(registration.read_bytes()); name = decoded(row['ref']['certificate'])['segment']['name']
        (registration.parent.parent/name).write_bytes(b'reappeared')
        with self.assertRaisesRegex(JournalError,'reappeared'):
            await self.recover()

    async def test_unadmitted_raw_tail_preserved_without_coverage(self):
        await self.collect('before_unit_admission')
        before = {p:p.read_bytes() for p in self.root.glob('epoch-*/*/segment-*.jsonl')}
        recovered = await self.recover()
        self.assertEqual(recovered['epochs'][0]['summary']['last_audited_sequence'],0)
        self.assertTrue(recovered['unadmitted_segment_files'])
        self.assertTrue(all(p.read_bytes()==v for p,v in before.items()))

    async def test_pending_audit_receipt_reconstructed_before_retirement(self):
        await self.collect('before_audit_receipt')
        recovered = await self.recover()
        self.assertGreater(recovered['epochs'][0]['summary']['last_audited_sequence'],0)
        self.assertEqual(recovered['registered_retired_units'],0)
        self.assertEqual(recovered['logical_raw_bytes_removed_this_call'],0)

    async def test_ownership_cleanup_releases_journal_locks_after_failure(self):
        await self.collect('collector_epoch_bound')
        from app.research.data.durable_capture_log import lock_directory
        for name in ('journal','audit'):
            lock = lock_directory(self.root/'epoch-00'/name); lock.close()
        self.assertTrue(all(m.closed for m in self.managers))

    async def test_reconnect_keeps_separate_epochs_and_original_window(self):
        # Frozen retry delay is one second, so allow a complete second epoch.
        result = await self.collect(seconds=3,disconnect=750_000_000)
        self.assertEqual(result['stop_reason'],'ORIGINAL_DEADLINE',result['errors'])
        self.assertEqual(len(result['epochs']),2)
        recovered = await self.recover()
        for actual,expected in zip(recovered['epochs'],cold_replay(self.root),strict=True):
            self.same(actual['summary'],expected)
            self.assertEqual(expected['window_start_ns'],result['original_window']['window_start_ns'])
            self.assertEqual(expected['window_end_ns'],result['original_window']['window_end_ns'])
        self.assertNotEqual(result['audits'][0]['epoch'],result['audits'][1]['epoch'])

    async def test_existing_limits_not_relaxed(self):
        with self.assertRaisesRegex(ValueError,'120'):
            await run_bounded(self.root,duration_ns=121_000_000_000,transport=ScriptedTransport(),policy=self.policy)
        self.assertFalse(self.root.exists())

    async def test_uncommitted_unsealed_suffix_preserved_and_never_replayed(self):
        def hook(stage):
            if stage=='collector_retention_registered':
                journal=self.managers[0].journals[0]['raw']
                journal.append(dict(uncertain='must never be a market observation'))
        await self.collect('collector_retention_registered',hook_extra=hook)
        before={p:p.read_bytes() for p in self.root.glob('epoch-*/journal/segment-*.jsonl')}
        recovered=await self.recover()
        self.assertTrue(recovered['preserved_uncommitted_suffixes'])
        for suffix in recovered['preserved_uncommitted_suffixes']:
            path=self.root/suffix['journal']/suffix['source']
            self.assertEqual(path.read_bytes(),before[path])
        self.same(cold_replay(self.root)[0],recovered['epochs'][0]['summary'])

    async def test_sealed_source_suffix_is_rejected_and_preserved(self):
        await self.collect()
        path=next(self.root.glob('epoch-*/audit/segment-*.jsonl'))
        path.write_bytes(path.read_bytes()+b'uncertain bytes')
        before=inventory(self.root)
        with self.assertRaisesRegex(JournalError,'sealed raw has uncertain suffix'):
            await self.recover()
        self.assertEqual(before,inventory(self.root))

    async def test_recovery_view_cannot_append_commit_or_issue_new_seals(self):
        from app.research.data.recovery_custody_journal import RecoveryCustodyJournal
        await self.collect()
        budget=self.budget();registry=None;journal=None;before=inventory(self.root)
        try:
            registry=CustodyLedger.resume(self.root/'collector-custody',budget=budget,anchor=self.handle['custody_anchor'])
            journal=RecoveryCustodyJournal.open_for_recovery(self.root/'epoch-00/journal',budget=budget,
                handle=registry.model['epochs'][0]['raw'])
            for operation in (lambda:journal.append({}),journal.commit,journal.seal):
                with self.assertRaisesRegex(JournalError,'historical recovery view'):operation()
        finally:
            if journal:journal.close()
            if registry:registry.close()
            budget.close()
        self.assertEqual(before,inventory(self.root))

    async def test_independent_full_raw_replay_matches_retired_collector(self):
        import shutil
        from app.research.data.snapshot_feed_audit import audit_epoch
        reference=Path(self.temp.name)/'reference';reference.mkdir()
        def preserve(stage):
            if stage=='custody_before_unlink':
                for group in self.managers[0].journals.values():
                    for journal in group.values():
                        target=reference/journal.directory.relative_to(self.root)
                        target.mkdir(parents=True,exist_ok=True)
                        for source in journal.directory.glob('segment-*.jsonl'):
                            shutil.copyfile(source,target/source.name)
        result=await self.collect(hook_extra=preserve)
        for directory in self.root.glob('epoch-*'):
            for name in ('journal','audit'):
                shutil.copytree(directory/name,reference/directory.name/name,dirs_exist_ok=True)
        expected=audit_epoch(reference/'epoch-00/journal',reference/'epoch-00/audit',
                             **result['original_window'],max_intervals=10000)
        self.same(result['audits'][0],expected)
        recovered=await self.recover()
        self.same(recovered['epochs'][0]['summary'],expected)
