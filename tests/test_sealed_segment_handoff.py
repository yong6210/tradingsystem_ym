import dataclasses
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.research.data import sealed_segment_handoff as handoff
from app.research.data.durable_capture_log import JournalError, decoded, encoded, file_hash
from app.research.data.shared_feed_storage import SharedStorageBudget


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()/'run'
        self.contract = dict(run_id='handoff', max_bytes=4*1024**2, min_free_bytes=0)
        self.disk = SharedStorageBudget.create(self.root, **self.contract)
        self.writer = handoff.SealedJournal.create(self.root/'raw', budget=self.disk,
            run_id='handoff', rotation_bytes=2048, max_record_bytes=1024)
        self.cursor = self.writer.initial_cursor()

    def tearDown(self):
        self.writer.close()
        self.disk.close()
        self.temp.cleanup()

    def batch(self, count=1):
        for i in range(count):
            self.writer.append(dict(i=i, text='x'*200))
        return self.writer.seal()

    def resume(self):
        self.writer.close(); self.disk.close()
        self.disk = SharedStorageBudget.resume(self.root, **self.contract)
        self.writer = handoff.SealedJournal.resume(self.root/'raw', budget=self.disk)
        return self.writer.recovered_tickets

    def rewrite(self, ticket, **changes):
        row = decoded(ticket.certificate) | changes
        row['seal_sha256'] = handoff.sha(encoded({k:v for k,v in row.items() if k != 'seal_sha256'}))
        return handoff.SealTicket(encoded(row))

    def test_active_writer_can_continue_during_handoff_without_history_reads(self):
        ticket, = self.batch()
        self.writer.append(dict(next=True))
        self.writer.commit()
        # Reader uses only the selected segment, not a mutable checkpoint or seal lookup.
        target = self.root/'raw'/decoded(ticket.certificate)['segment']['name']
        opened = []
        original = Path.open
        def traced(path, *args, **kwargs):
            opened.append(path)
            if path != target: raise AssertionError('unexpected history read')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', traced):
            result = handoff.read_segment(ticket, self.cursor)
        self.assertEqual(opened, [target])
        self.assertEqual(result.cursor.sequence, 1)
        self.assertEqual(len(list(result.records())), 1)
        self.assertFalse(self.writer.closed)

    def test_writer_seal_does_not_read_history(self):
        self.batch()
        self.writer.append(dict(next=True))
        original = Path.open
        def traced(path, mode='r', *args, **kwargs):
            if mode == 'rb' and path.name == 'segment-0000000.jsonl':
                raise AssertionError('old segment reread')
            return original(path, mode, *args, **kwargs)
        with patch.object(Path, 'open', traced):
            tickets = self.writer.seal()
        self.assertEqual(len(tickets), 1)

    def test_rotation_is_not_a_seal_until_commit_and_explicit_handoff(self):
        for i in range(10): self.writer.append(dict(i=i, text='x'*200))
        self.assertGreater(len(self.writer.entries), 1)
        self.assertEqual(list(self.writer.seals.iterdir()), [])
        self.writer.commit()
        self.assertEqual(list(self.writer.seals.iterdir()), [])
        tickets = self.writer.seal()
        cursor = self.cursor
        for ticket in tickets: cursor = handoff.read_segment(ticket, cursor).cursor
        self.assertEqual(cursor.sequence, 10)

    def test_sealed_file_never_appended_again(self):
        ticket, = self.batch()
        path = self.root/'raw'/decoded(ticket.certificate)['segment']['name']
        before = path.read_bytes()
        self.batch(2)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self.writer.entries), 2)

    def test_duplicate_out_of_order_and_skipped_tickets_rejected(self):
        first, = self.batch()
        second, = self.batch()
        with self.assertRaises(JournalError): handoff.read_segment(second, self.cursor)
        cursor = handoff.read_segment(first, self.cursor).cursor
        with self.assertRaises(JournalError): handoff.read_segment(first, cursor)
        self.assertEqual(handoff.read_segment(second, cursor).cursor.sequence, 2)

    def test_bad_final_byte_rejected_before_any_result(self):
        ticket, = self.batch()
        path = self.root/'raw'/decoded(ticket.certificate)['segment']['name']
        raw = bytearray(path.read_bytes()); raw[-3] ^= 1; path.write_bytes(raw)
        with self.assertRaises(JournalError): handoff.read_segment(ticket, self.cursor)
        self.assertEqual(self.cursor.sequence, 0)

    def test_truncation_and_appended_suffix_rejected(self):
        ticket, = self.batch()
        path = self.root/'raw'/decoded(ticket.certificate)['segment']['name']
        raw = path.read_bytes()
        for bad in (raw[:-1], raw+b'uncertain'):
            path.write_bytes(bad)
            with self.assertRaises(JournalError): handoff.read_segment(ticket, self.cursor)

    def test_certificate_checksum_and_duplicate_json_rejected(self):
        ticket, = self.batch()
        row = decoded(ticket.certificate); row['last_sequence'] += 1
        for raw in (encoded(row), b'{"version":1,"version":1}'):
            with self.assertRaises(JournalError): handoff.read_segment(handoff.SealTicket(raw), self.cursor)

    def test_terminal_record_witness_rejected_even_with_new_checksum(self):
        ticket, = self.batch()
        with self.assertRaisesRegex(JournalError, 'terminal'):
            handoff.read_segment(self.rewrite(ticket, last_record_sha256='1'*64), self.cursor)

    def test_wrong_epoch_and_record_bound_rejected(self):
        ticket, = self.batch()
        for changes in (dict(epoch='wrong'), dict(max_record_bytes=1)):
            with self.assertRaises(JournalError):
                handoff.read_segment(self.rewrite(ticket, **changes), self.cursor)

    def test_segment_bounds_and_traversal_rejected(self):
        ticket, = self.batch()
        entry = decoded(ticket.certificate)['segment']
        for changes in (dict(journal='../raw'), dict(segment=entry|dict(name='../raw')),
                        dict(segment=entry|dict(bytes=handoff.MAX_SEGMENT_BYTES+1))):
            with self.assertRaises(JournalError):
                handoff.read_segment(self.rewrite(ticket, **changes), self.cursor)

    def test_wrong_run_metadata_or_journal_cursor_rejected(self):
        ticket, = self.batch()
        for changes in (dict(run_id='other'), dict(metadata_sha256='1'*64), dict(journal='other')):
            with self.assertRaises(JournalError):
                handoff.read_segment(ticket, dataclasses.replace(self.cursor, **changes))

    def test_symlink_refused(self):
        ticket, = self.batch()
        path = self.root/'raw'/decoded(ticket.certificate)['segment']['name']
        other = path.with_suffix('.saved'); path.rename(other); path.symlink_to(other)
        with self.assertRaises(JournalError): handoff.read_segment(ticket, self.cursor)

    def test_fsync_failure_issues_no_ticket_and_latches(self):
        self.writer.append(dict(x=1))
        with patch.object(handoff.os, 'fsync', side_effect=OSError('disk')):
            with self.assertRaises(OSError): self.writer.seal()
        self.assertTrue(self.writer.failed)
        self.assertTrue(self.disk.failed)
        self.assertEqual(list(self.writer.seals.glob('*.seal.json')), [])
        with self.assertRaises(JournalError): self.writer.append(dict(x=2))

    def test_seal_error_latches_after_checkpoint_is_committed(self):
        self.writer.append(dict(x=1))
        def fault(stage):
            if stage == 'after_seal_fsync': raise RuntimeError('stop')
        self.writer.hook = fault
        with self.assertRaises(RuntimeError): self.writer.seal()
        self.assertEqual(self.writer.cp['last_sequence'], 1)
        self.assertTrue(self.disk.failed)
        before = {p.name:p.read_bytes() for p in self.writer.seals.iterdir()}
        tickets = self.resume()
        self.assertEqual(len(tickets), 1)
        self.assertTrue(all((self.writer.seals/n).read_bytes() == b for n,b in before.items()))

    def test_resume_reanchors_unacknowledged_seal(self):
        self.writer.append(dict(x=1))
        def fault(stage):
            if stage == 'after_seal_replace': raise RuntimeError('stop')
        self.writer.hook = fault
        with self.assertRaises(RuntimeError): self.writer.seal()
        before = next(self.writer.seals.glob('*.seal.json')).read_bytes()
        tickets = self.resume()
        self.assertEqual(tickets[0].certificate, before)
        cursor = handoff.read_segment(tickets[0], self.cursor).cursor
        next_ticket, = self.batch()
        self.assertEqual(handoff.read_segment(next_ticket, cursor).cursor.sequence, 2)

    def test_restart_epoch_chain_and_stable_old_tickets(self):
        first, = self.batch(2)
        self.writer.append(dict(x=3)); self.writer.commit()
        tickets = self.resume()
        self.assertEqual(first, tickets[0])
        cursor = self.cursor
        for ticket in tickets: cursor = handoff.read_segment(ticket, cursor).cursor
        third, = self.batch()
        self.assertNotEqual(decoded(first.certificate)['epoch'], decoded(third.certificate)['epoch'])
        self.assertEqual(handoff.read_segment(third, cursor).cursor.sequence, 4)

    def test_uncommitted_new_file_preserved_not_adopted(self):
        self.batch()
        self.writer.append(dict(uncertain=True))
        old = self.root/'raw'/self.writer.entries[-1]['name']
        before = old.read_bytes()
        tickets = self.resume()
        self.assertEqual(len(tickets), 1)
        cursor = handoff.read_segment(tickets[0], self.cursor).cursor
        next_ticket, = self.batch()
        self.assertEqual(handoff.read_segment(next_ticket, cursor).cursor.sequence, 2)
        self.assertEqual(old.read_bytes(), before)
        self.assertEqual(decoded(next_ticket.certificate)['segment']['name'], 'segment-0000002.jsonl')

    def test_uncertain_suffix_on_committed_file_blocks_handoff_resume(self):
        self.writer.append(dict(x=1)); self.writer.commit(); self.writer.append(dict(uncertain=True))
        with self.assertRaisesRegex(JournalError, 'uncertain suffix'): self.resume()
        self.assertTrue(self.disk.failed)

    def test_existing_seal_corruption_not_overwritten(self):
        self.batch()
        path = next(self.writer.seals.glob('*.seal.json'))
        bad = b'broken'; path.write_bytes(bad)
        with self.assertRaises(JournalError): self.resume()
        self.assertEqual(path.read_bytes(), bad)

    def test_seal_recovery_requires_new_directory_fence(self):
        self.batch(); self.writer.close(); self.disk.close()
        self.disk = SharedStorageBudget.resume(self.root, **self.contract)
        with patch.object(handoff, 'sync_directory', side_effect=OSError('fence')):
            with self.assertRaises(OSError):
                handoff.SealedJournal.resume(self.root/'raw', budget=self.disk)
        self.assertTrue(self.disk.failed)

    def test_pending_bound_is_fail_closed(self):
        with patch.object(handoff, 'MAX_PENDING_SEGMENTS', 1):
            with self.assertRaisesRegex(JournalError, 'pending'):
                for i in range(10): self.writer.append(dict(i=i, text='x'*200))
        self.assertTrue(self.disk.failed)
        self.assertFalse(list(self.writer.seals.glob('*.seal.json')))

    def test_aggregate_budget_counts_seals_and_temporary_files(self):
        self.batch(10)
        actual = sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())
        self.assertEqual(self.disk.used, actual)
        self.assertGreater(self.disk.peak, 0)
        self.writer.append(dict(x=1)); self.writer.commit()
        self.disk.contract['max_bytes'] = self.disk.used+20
        with self.assertRaisesRegex(JournalError, 'budget'): self.writer.seal()
        self.assertTrue(self.disk.failed)

    def test_empty_seal_and_close_do_not_create_tickets(self):
        self.assertEqual(self.writer.seal(), ())
        self.writer.append(dict(x=1)); self.writer.close()
        self.assertFalse(list(self.writer.seals.glob('*.seal.json')))

    def test_verified_bytes_are_stable_after_source_changes(self):
        ticket, = self.batch()
        result = handoff.read_segment(ticket, self.cursor)
        path = self.root/'raw'/decoded(ticket.certificate)['segment']['name']
        path.write_bytes(b'corrupt')
        self.assertEqual(len(list(result.records())), 1)

    def test_create_rejects_unbounded_rotation(self):
        with self.assertRaises(JournalError):
            handoff.SealedJournal.create(self.root/'other', budget=self.disk,
                run_id='handoff', rotation_bytes=handoff.MAX_SEGMENT_BYTES+1)

    def test_bad_record_chain_rejected_even_with_new_outer_hash(self):
        ticket, = self.batch()
        row = decoded(ticket.certificate)
        path = self.root/'raw'/row['segment']['name']
        lines = path.read_bytes().splitlines(keepends=True)
        record = decoded(lines[1]); record['sequence'] = 9
        lines[1] = encoded(record)
        raw = b''.join(lines); path.write_bytes(raw)
        altered = self.rewrite(ticket, segment=row['segment'] | dict(bytes=len(raw), sha256=handoff.sha(raw)))
        with self.assertRaisesRegex(JournalError, 'record chain'):
            handoff.read_segment(altered, self.cursor)

    def test_recovery_after_partial_multi_segment_registration(self):
        for i in range(10): self.writer.append(dict(i=i, text='x'*200))
        calls = 0
        def fault(stage):
            nonlocal calls
            if stage == 'after_seal_directory_fsync':
                calls += 1
                if calls == 2: raise RuntimeError('stop')
        self.writer.hook = fault
        with self.assertRaises(RuntimeError): self.writer.seal()
        before = {p.name:p.read_bytes() for p in self.writer.seals.iterdir()}
        tickets = self.resume()
        self.assertEqual(len(tickets), len(self.writer.entries))
        cursor = self.cursor
        for ticket in tickets: cursor = handoff.read_segment(ticket, cursor).cursor
        self.assertEqual(cursor.sequence, 10)
        self.assertTrue(all((self.writer.seals/n).read_bytes() == b for n,b in before.items()))

    def test_total_segment_limit_fails_without_overwriting_old_seal(self):
        ticket, = self.batch()
        with patch.object(handoff, 'MAX_SEGMENTS', 1):
            with self.assertRaises(JournalError): self.writer.append(dict(x=2))
        self.assertTrue(self.disk.failed)
        self.assertEqual(handoff.read_segment(ticket, self.cursor).cursor.sequence, 1)

    def test_unexpected_seal_file_blocks_recovery_without_deletion(self):
        self.batch()
        unknown = self.writer.seals/'unexpected.json'; unknown.write_bytes(b'unknown')
        with self.assertRaisesRegex(JournalError, 'unexpected'): self.resume()
        self.assertEqual(unknown.read_bytes(), b'unknown')
