import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from app.research.data.archive_segment_reader import SegmentReader, segment_ref
from app.research.data.background_segment_archive import BackgroundArchives, advance_cursor
from app.research.data.durable_capture_log import JournalError, file_hash
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.retained_sealed_journal import RetainedSealedJournal
from app.research.data.sealed_segment_handoff import SealedJournal, certificate


class RetainedJournalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()/'run'
        self.contract = dict(run_id='mixed-journal', max_bytes=16*1024**2, min_free_bytes=0)
        self.budget = ReservedStorageBudget.create(self.root, **self.contract)
        self.writer = RetainedSealedJournal.create(self.root/'raw', budget=self.budget,
            run_id=self.contract['run_id'], rotation_bytes=256*1024, max_record_bytes=128*1024)
        self.cursor = self.writer.initial_cursor()
        self.starts = {}; self.archives = 0

    def tearDown(self):
        self.writer.close(); self.budget.close(); self.temp.cleanup()

    def seal(self, size=65536):
        self.writer.append(dict(data='x'*size, number=self.writer.sequence+1))
        ticket, = self.writer.seal()
        self.starts[ticket.certificate] = self.cursor
        self.cursor = advance_cursor(certificate(ticket.certificate), self.cursor)
        return ticket

    async def archive(self, ticket):
        directory = self.root/f'archives-{self.archives}'
        self.archives += 1
        manager = BackgroundArchives(directory, budget=self.budget, cursor=self.starts[ticket.certificate])
        manager.submit(ticket)
        rows = await manager.finish()
        row = rows[0]
        return segment_ref(ticket, archive_directory=directory.name, archive_id=row['archive_id'])

    async def prepare(self, size=65536):
        ticket = self.seal(size)
        ref = await self.archive(ticket)
        decision = self.writer.admit_archive(ticket, ref)
        return ticket, ref, decision

    def reopen(self, handle):
        self.writer.close(); self.budget.close()
        self.budget = ReservedStorageBudget.resume(self.root, **self.contract)
        self.writer = RetainedSealedJournal.resume(self.root/'raw', budget=self.budget, handle=handle)
        return self.writer

    def inventory(self):
        return {str(p.relative_to(self.root)): (p.stat().st_size, file_hash(p))
                for p in self.root.rglob('*') if p.is_file()}

    async def test_retire_earlier_segment_while_next_file_is_open_and_continue(self):
        ticket, ref, decision = await self.prepare()
        self.assertTrue(decision['admitted'])
        self.writer.append(dict(next_file='still active'))
        active = Path(self.writer.active.name)
        active_before = active.read_bytes()
        self.writer.finish_retirement()
        self.assertEqual(active.read_bytes(), active_before)
        self.assertFalse((self.root/'raw'/decision['source']).exists())
        self.writer.append(dict(after_retirement=True))
        self.writer.seal()
        handle = self.writer.handle()
        self.reopen(handle)
        self.assertEqual(self.writer.sequence, 3)
        self.assertEqual(self.writer.recovery['archive_segments'], 1)
        self.assertEqual(len(self.writer.recovered_tickets), 2)

    async def test_all_raw_retired_restart_does_not_reuse_index(self):
        ticket, ref, decision = await self.prepare()
        self.writer.finish_retirement()
        handle = self.writer.handle()
        self.assertEqual(list((self.root/'raw').glob('segment-*.jsonl')), [])
        self.reopen(handle)
        self.writer.append(dict(next=True)); next_ticket, = self.writer.seal()
        self.assertEqual(certificate(next_ticket.certificate)['segment']['name'], 'segment-0000001.jsonl')
        self.assertEqual(certificate(next_ticket.certificate)['first_sequence'], 2)
        self.reopen(self.writer.handle())
        self.assertEqual(self.writer.sequence, 2)

    async def test_mixed_raw_gzip_full_replay_preserves_record_sequence(self):
        first, ref, decision = await self.prepare()
        self.writer.finish_retirement()
        second = self.seal(); third = self.seal()
        self.reopen(self.writer.handle())
        cursor = self.writer.initial_cursor(); rows = []
        for i, ticket in enumerate(self.writer.recovered_tickets):
            verified = SegmentReader(budget=self.budget).read(ref if i == 0 else segment_ref(ticket), cursor)
            rows.extend(verified.records()); cursor = verified.cursor
        self.assertEqual([r['sequence'] for r in rows], [1, 2, 3])
        self.assertEqual([r['payload']['number'] for r in rows], [1, 2, 3])

    async def test_small_source_rejected_without_metadata_writes(self):
        ticket = self.seal(10); ref = await self.archive(ticket)
        before = self.inventory()
        decision = self.writer.admit_archive(ticket, ref)
        self.assertFalse(decision['admitted'])
        self.assertEqual(before, self.inventory())

    async def test_exact_normal_path_cost_includes_registration_intent_done(self):
        ticket = self.seal(); ref = await self.archive(ticket)
        before = sum(v[0] for v in self.inventory().values())
        decision = self.writer.admit_archive(ticket, ref)
        self.writer.finish_retirement()
        after = sum(v[0] for v in self.inventory().values())
        self.assertEqual(before-after, decision['normal_path_net_savings_bytes'])
        self.assertEqual(self.budget.used, after)

    async def test_prepare_never_deletes_source(self):
        ticket, ref, decision = await self.prepare()
        self.assertTrue((self.root/'raw'/decision['source']).exists())
        self.assertEqual(list(self.writer.custody.glob('*.intent.json')), [])

    async def test_pending_worker_blocks_unlink(self):
        ticket, ref, decision = await self.prepare()
        before = self.inventory(); self.budget.reserve('worker', 1)
        with self.assertRaisesRegex(JournalError, 'pending workers'):
            self.writer.finish_retirement()
        self.assertEqual(before, self.inventory())
        self.budget.release('worker')

    async def test_missing_raw_without_intent_fails_closed(self):
        ticket, ref, decision = await self.prepare(); handle = self.writer.handle()
        (self.root/'raw'/decision['source']).unlink()
        with self.assertRaisesRegex(JournalError, 'missing raw without'):
            self.reopen(handle)

    async def test_corrupt_gzip_never_falls_back_to_existing_raw(self):
        ticket, ref, decision = await self.prepare(); handle = self.writer.handle()
        gz = next((self.root/ref['archive']['directory']).glob('*.gz'))
        gz.write_bytes(gz.read_bytes()[:-1])
        before = self.inventory()
        with self.assertRaises(JournalError): self.reopen(handle)
        self.assertEqual(before, self.inventory())

    async def test_reappeared_retired_source_is_preserved(self):
        ticket, ref, decision = await self.prepare(); source = self.root/'raw'/decision['source']
        saved = source.read_bytes(); self.writer.finish_retirement(); handle = self.writer.handle()
        source.write_bytes(saved)
        with self.assertRaisesRegex(JournalError, 'reappeared'):
            self.reopen(handle)
        self.assertEqual(source.read_bytes(), saved)

    async def test_old_external_handle_cannot_adopt_new_registration(self):
        ticket = self.seal(); ref = await self.archive(ticket); old = self.writer.handle()
        self.writer.admit_archive(ticket, ref)
        with self.assertRaisesRegex(JournalError, 'unanchored'):
            self.reopen(old)

    async def test_anchor_checkpoint_rollback_rejected(self):
        self.seal(); old_cp = (self.root/'raw/checkpoint.json').read_bytes()
        self.seal(); handle = self.writer.handle()
        (self.root/'raw/checkpoint.json').write_bytes(old_cp)
        with self.assertRaisesRegex(JournalError, 'rollback'):
            self.reopen(handle)

    async def test_later_commit_is_accepted_only_on_saved_anchor_chain(self):
        self.seal(); handle = self.writer.handle(); self.seal()
        self.reopen(handle)
        self.assertEqual(self.writer.sequence, 2)
        handle = self.writer.handle(); handle['checkpoint']['record_sha256'] = 'f'*64
        with self.assertRaisesRegex(JournalError, 'anchor chain'):
            self.reopen(handle)

    async def test_unsealed_committed_raw_tail_gets_recovered_seal(self):
        ticket, ref, decision = await self.prepare(); self.writer.finish_retirement()
        self.writer.append(dict(committed_tail=True)); self.writer.commit()
        handle = self.writer.handle()
        self.reopen(handle)
        self.assertEqual(len(self.writer.recovered_tickets), 2)
        self.assertTrue((self.writer.seals/'segment-0000001.jsonl.seal.json').is_file())
        self.writer.append(dict(after_resume=True)); self.writer.seal()
        self.reopen(self.writer.handle())
        self.assertEqual(self.writer.sequence, 3)

    async def test_uncertain_suffix_refused_and_preserved(self):
        self.seal(); handle = self.writer.handle()
        raw = next((self.root/'raw').glob('segment-*.jsonl')); raw.write_bytes(raw.read_bytes()+b'uncertain')
        before = self.inventory()
        with self.assertRaisesRegex(JournalError, 'uncertain suffix'):
            self.reopen(handle)
        self.assertEqual(before, self.inventory())

    async def test_orphan_filename_is_preserved_and_never_reused(self):
        ticket, ref, decision = await self.prepare(); self.writer.finish_retirement(); handle = self.writer.handle()
        orphan = self.root/'raw/segment-0000008.jsonl'; orphan.write_bytes(b'orphan evidence')
        self.reopen(handle)
        self.writer.append(dict(next=True)); next_ticket, = self.writer.seal()
        self.assertEqual(certificate(next_ticket.certificate)['segment']['name'], 'segment-0000009.jsonl')
        self.assertEqual(orphan.read_bytes(), b'orphan evidence')

    async def test_retirement_repetition_is_idempotent(self):
        await self.prepare(); self.writer.finish_retirement(); before = self.inventory()
        result = self.writer.finish_retirement()
        self.assertEqual(result['raw_bytes_removed_this_call'], 0)
        self.assertEqual(before, self.inventory())

    async def test_resume_after_unlink_and_finish_preserves_crash_state(self):
        ticket, ref, decision = await self.prepare(); handle = self.writer.handle()
        def hook(stage):
            if stage == 'custody_after_unlink': raise OSError('injected loss')
        self.writer.hook = hook
        with self.assertRaises(OSError): self.writer.finish_retirement()
        self.reopen(handle); self.writer.finish_retirement()
        self.writer.append(dict(continued=True)); self.writer.seal()
        self.assertEqual(self.writer.sequence, 2)

    async def test_registration_rename_without_external_anchor_blocks_resume(self):
        ticket = self.seal(); ref = await self.archive(ticket); old = self.writer.handle()
        def hook(stage):
            if stage == 'custody_register:after_checkpoint_replace': raise OSError('lost registration acknowledgement')
        self.writer.hook = hook
        with self.assertRaises(OSError): self.writer.admit_archive(ticket, ref)
        before = self.inventory()
        with self.assertRaisesRegex(JournalError, 'unanchored'): self.reopen(old)
        self.assertEqual(before, self.inventory())

    async def test_legacy_writer_cannot_resume_retired_sources(self):
        await self.prepare(); self.writer.finish_retirement(); self.writer.close()
        with self.assertRaises(JournalError):
            SealedJournal.resume(self.root/'raw', budget=self.budget)

    async def test_no_seal_no_admission_even_if_archive_exists(self):
        ticket = self.seal(); ref = await self.archive(ticket)
        name = certificate(ticket.certificate)['segment']['name']
        (self.writer.seals/(name+'.seal.json')).unlink()
        with self.assertRaisesRegex(JournalError, 'durable seal'):
            self.writer.admit_archive(ticket, ref)

    async def test_changed_policy_cannot_be_used_to_resume(self):
        self.seal(); handle = self.writer.handle()
        (self.root/'raw/custody-policy.json').write_text('{}')
        with self.assertRaisesRegex(JournalError, 'policy binding'): self.reopen(handle)

    async def test_selected_batch_leaves_other_admitted_source_in_place(self):
        first, ref, one = await self.prepare()
        second, ref, two = await self.prepare()
        self.writer.finish_retirement(names=[one['source']])
        self.assertFalse((self.root/'raw'/one['source']).exists())
        self.assertTrue((self.root/'raw'/two['source']).exists())
        self.writer.finish_retirement(names=[two['source']])
        self.assertFalse((self.root/'raw'/two['source']).exists())

    async def test_oversized_duplicate_or_unknown_batch_has_no_side_effects(self):
        ticket, ref, decision = await self.prepare(); name = decision['source']
        before = self.inventory()
        for names in ([name]*17, [name, name], ['segment-9999999.jsonl'], name):
            with self.subTest(names=names):
                with self.assertRaisesRegex(JournalError, 'retirement batch'):
                    self.writer.finish_retirement(names=names)
                self.assertEqual(before, self.inventory())
