import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from app.research.data.durable_capture_log import (
    DurableCaptureLog, JournalError, inspect_journal, iter_committed,
)


class DurableCaptureLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)/'journal'
        self.writer = DurableCaptureLog.create(self.root, run_id='fixture', rotation_bytes=1024,
                    max_record_bytes=700, max_total_bytes=100_000, min_free_bytes=0)

    def tearDown(self):
        self.writer.close()
        self.temp.cleanup()

    def resume(self):
        self.writer.close()
        self.writer = DurableCaptureLog.resume(self.root)

    def test_append_is_not_durable_permission_and_close_does_not_commit(self):
        self.writer.append({'wire_text': 'one'})
        self.assertEqual(self.writer.publication_fence().sequence, 0)
        self.writer.close()
        self.assertEqual(list(iter_committed(self.root)), [])
        self.assertEqual(len(inspect_journal(self.root)['uncommitted_suffixes']), 1)

    def test_receipt_after_sync_and_records_roundtrip(self):
        payload = {'wire_text': '{"literal":"한글"}', 'received_ns': 100}
        self.writer.append(payload)
        before = time.monotonic_ns()
        receipt = self.writer.commit()
        self.assertEqual(receipt.sequence, 1)
        self.assertGreaterEqual(receipt.available_monotonic_ns, before)
        self.assertEqual(self.writer.commit(), receipt)
        self.writer.close()
        self.assertEqual([r['payload'] for r in iter_committed(self.root)], [payload])

    def test_writer_and_recovery_readers_are_exclusive(self):
        with self.assertRaises(JournalError):
            DurableCaptureLog.resume(self.root)
        with self.assertRaises(JournalError):
            inspect_journal(self.root)

    def test_rotation_preserves_chain_and_global_sequence(self):
        for i in range(8):
            self.writer.append({'index': i, 'wire_text': 'x'*280})
        self.assertEqual(self.writer.publication_fence().sequence, 0)
        self.writer.commit()
        self.writer.close()
        state = inspect_journal(self.root)
        self.assertGreater(state['committed_segments'], 1)
        rows = list(iter_committed(self.root))
        self.assertEqual([r['sequence'] for r in rows], list(range(1, 9)))
        self.assertEqual([r['payload']['index'] for r in rows], list(range(8)))

    def test_resume_keeps_uncertain_tail_bytes_and_uses_new_epoch(self):
        self.writer.append({'value': 'committed'})
        self.writer.commit()
        epoch = self.writer.epoch
        self.writer.append({'value': 'uncertain'})
        self.writer.close()
        originals = {p: p.read_bytes() for p in self.root.glob('segment-*.jsonl')}
        self.writer = DurableCaptureLog.resume(self.root)
        self.assertEqual(self.writer.publication_fence().sequence, 1)
        self.assertNotEqual(self.writer.epoch, epoch)
        self.assertEqual(len(self.writer.recovery['uncommitted_suffixes']), 1)
        self.writer.append({'value': 'new epoch'})
        self.writer.commit()
        self.writer.close()
        self.assertTrue(all(p.read_bytes() == raw for p, raw in originals.items()))
        rows = list(iter_committed(self.root))
        self.assertEqual([r['sequence'] for r in rows], [1, 2])
        self.assertEqual([r['payload']['value'] for r in rows], ['committed', 'new epoch'])
        self.assertFalse(inspect_journal(self.root)['live_market_state_restored'])

    def test_torn_uncommitted_line_retained_but_not_replayed(self):
        self.writer.append({'value': 'kept'})
        self.writer.commit()
        path = self.root/self.writer.entries[-1]['name']
        self.writer.close()
        with path.open('ab') as stream:
            stream.write(b'{"sequence":2,"payload":')
        before = path.read_bytes()
        self.writer = DurableCaptureLog.resume(self.root)
        self.assertEqual(self.writer.recovery['last_sequence'], 1)
        self.assertEqual(path.read_bytes(), before)
        self.writer.close()
        self.assertEqual(len(list(iter_committed(self.root))), 1)

    def test_fsync_error_poisoned_writer_cannot_publish_or_append(self):
        self.writer.append({'one': 1})
        self.writer.commit()
        self.writer.append({'two': 2})
        with patch('app.research.data.durable_capture_log.os.fsync', side_effect=OSError('injected disk error')):
            with self.assertRaises(OSError):
                self.writer.commit()
        for operation in [self.writer.publication_fence, self.writer.commit, lambda: self.writer.append({'x': 1})]:
            with self.assertRaises(JournalError):
                operation()
        self.resume()
        self.assertEqual(self.writer.publication_fence().sequence, 1)

    def test_checkpoint_replace_error_preserves_old_prefix_and_pending_metadata(self):
        self.writer.append({'one': 1})
        self.writer.commit()
        self.writer.append({'two': 2})
        with patch('app.research.data.durable_capture_log.os.replace', side_effect=OSError('injected rename error')):
            with self.assertRaises(OSError):
                self.writer.commit()
        self.resume()
        self.assertEqual(self.writer.publication_fence().sequence, 1)
        self.assertTrue(self.writer.recovery['pending_checkpoint_files'])

    def test_rename_visible_but_ack_lost_can_recover_verified_new_prefix(self):
        self.writer.append({'one': 1})
        self.writer.commit()
        old_receipt = self.writer.receipt
        def fail(stage):
            if stage == 'after_checkpoint_replace':
                raise OSError('lost acknowledgement before directory sync')
        self.writer.hook = fail
        self.writer.append({'two': 2})
        with self.assertRaises(OSError):
            self.writer.commit()
        self.assertEqual(self.writer.receipt, old_receipt)
        self.resume()
        self.assertEqual(self.writer.publication_fence().sequence, 2)

    def test_corrupt_committed_byte_rejects_before_any_record_is_yielded(self):
        self.writer.append({'value': 'committed'})
        self.writer.commit()
        path = self.root/self.writer.entries[-1]['name']
        self.writer.close()
        path.write_bytes(path.read_bytes().replace(b'committed', b'CORRUPTED'))
        with self.assertRaises(JournalError):
            next(iter_committed(self.root))
        with self.assertRaises(JournalError):
            DurableCaptureLog.resume(self.root)

    def test_truncated_committed_file_rejected(self):
        self.writer.append({'one': 1})
        self.writer.commit()
        path = self.root/self.writer.entries[-1]['name']
        self.writer.close()
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaises(JournalError):
            inspect_journal(self.root)

    def test_record_chain_checked_even_if_segment_hash_updated(self):
        self.writer.append({'one': 1})
        self.writer.commit()
        path = self.root/self.writer.entries[-1]['name']
        self.writer.close()
        content = path.read_bytes().replace(b'"sequence":1', b'"sequence":2')
        path.write_bytes(content)
        cp = json.loads((self.root/'checkpoint.json').read_text())
        cp['segments'][0]['sha256'] = hashlib.sha256(content).hexdigest()
        (self.root/'checkpoint.json').write_text(json.dumps(cp))
        with self.assertRaises(JournalError):
            inspect_journal(self.root)

    def test_missing_checkpoint_not_reinterpreted_as_empty_log(self):
        self.writer.close()
        (self.root/'checkpoint.json').unlink()
        with self.assertRaises(JournalError):
            DurableCaptureLog.resume(self.root)

    def test_metadata_mutation_and_checkpoint_boolean_reject(self):
        self.writer.close()
        cp_path = self.root/'checkpoint.json'
        original = cp_path.read_text()
        cp = json.loads(original)
        cp['last_sequence'] = True
        cp_path.write_text(json.dumps(cp))
        with self.assertRaises(JournalError):
            inspect_journal(self.root)
        cp_path.write_text(original)
        meta_path = self.root/'metadata.json'
        meta = json.loads(meta_path.read_text())
        meta['run_id'] = 'changed'
        meta_path.write_text(json.dumps(meta))
        with self.assertRaises(JournalError):
            inspect_journal(self.root)

    def test_invalid_payloads_rejected_without_writing(self):
        for payload in [[], {'bad': float('nan')}, {'oversized': 'x'*1000}]:
            with self.assertRaises((JournalError, ValueError)):
                self.writer.append(payload)
        self.assertEqual(self.writer.sequence, 0)
        self.writer.append({'valid': True})
        self.assertEqual(self.writer.commit().sequence, 1)

    def test_space_reserve_and_total_byte_budget_fail_closed(self):
        with patch('app.research.data.durable_capture_log.shutil.disk_usage') as usage:
            usage.return_value.free = 1
            with self.assertRaises(JournalError):
                self.writer.append({'one': 1})
        with self.assertRaises(JournalError):
            self.writer.publication_fence()
        self.resume()
        self.writer.meta['max_total_bytes'] = 300
        with self.assertRaises(JournalError):
            self.writer.append({'body': 'x'*100})
        self.assertLessEqual(self.writer.total_bytes, 300)

    def test_short_write_retained_as_tail_with_no_sequence_advance(self):
        self.writer.append({'one': 1})
        self.writer.commit()
        original = self.writer.active
        class Partial:
            def write(self, data):
                return original.write(data[:10])
            def close(self):
                original.close()
        self.writer.active = Partial()
        with self.assertRaises(JournalError):
            self.writer.append({'two': 2})
        self.assertEqual(self.writer.sequence, 1)
        self.resume()
        self.assertEqual(self.writer.recovery['uncommitted_suffixes'][0]['bytes'], 10)

    def test_existing_directory_never_overwritten(self):
        with self.assertRaises(FileExistsError):
            DurableCaptureLog.create(self.root, run_id='other')


if __name__ == '__main__':
    unittest.main()
