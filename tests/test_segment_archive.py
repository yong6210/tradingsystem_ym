import hashlib
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from app.research.data.durable_capture_log import JournalError, encoded, file_hash
from app.research.data.shared_feed_storage import SharedStorageBudget, BudgetedJournal
from app.research.data.segment_archive import SegmentArchive, MAX_SEGMENT_BYTES


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()/'capture'
        self.contract = dict(run_id='archive-test', max_bytes=2*1024**2, min_free_bytes=0)
        self.disk = SharedStorageBudget.create(self.root, **self.contract)
        self.writer = BudgetedJournal.create(self.root/'raw', budget=self.disk,
            run_id=self.contract['run_id'], rotation_bytes=4096, max_record_bytes=2048)
        rng = random.Random(7)
        for index in range(12): self.writer.append(dict(index=index, text=rng.randbytes(200).hex()))
        self.writer.commit(); self.writer.close()
        self.store = SegmentArchive(self.root/'archives', budget=self.disk)
        self.name = 'segment-0000000.jsonl'
        self.source = self.root/'raw'/self.name

    def tearDown(self):
        self.writer.close(); self.disk.close(); self.temp.cleanup()

    def publish(self, **kwargs): return self.store.publish(self.root/'raw', self.name, **kwargs)

    def rewritten_descriptor(self, row):
        body = {key:value for key,value in row.items() if key != 'descriptor_sha256'}
        row['descriptor_sha256'] = hashlib.sha256(encoded(body)).hexdigest()
        (self.root/'archives'/(row['archive_id']+'.json')).write_bytes(encoded(row))

    def test_roundtrip_witness_and_exact_budget_inventory(self):
        before = self.source.read_bytes()
        row = self.publish()
        self.assertEqual(b''.join(self.store.read_chunks(row['archive_id'])), before)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertGreaterEqual(row['witness']['last_sequence'], row['witness']['first_sequence'])
        self.assertEqual(self.disk.used, sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file()))
        self.assertTrue(self.store.recover()['catalog_complete'])

    def test_publish_is_idempotent(self):
        first = self.publish(); used = self.disk.used
        self.assertEqual(self.publish(), first)
        self.assertEqual(self.disk.used, used)

    def test_active_writer_cannot_be_archived(self):
        writer = BudgetedJournal.resume(self.root/'raw', budget=self.disk)
        try:
            with self.assertRaises(JournalError): self.publish()
            self.assertTrue(self.disk.failed)
        finally: writer.close()

    def test_uncommitted_tail_never_archived(self):
        with self.source.open('ab') as stream: stream.write(b'uncertain')
        with self.assertRaisesRegex(JournalError, 'uncertain'): self.publish()
        self.assertFalse(list((self.root/'archives').glob('*.json')))

    def test_pending_source_checkpoint_is_not_ignored(self):
        (self.root/'raw/.checkpoint.json.orphan.tmp').write_bytes(b'uncertain')
        with self.assertRaisesRegex(JournalError, 'uncertain'): self.publish()

    def test_corrupt_source_cannot_publish(self):
        data = bytearray(self.source.read_bytes()); data[-5] ^= 1; self.source.write_bytes(data)
        with self.assertRaises(JournalError): self.publish()
        self.assertFalse(list((self.root/'archives').glob('*.json')))

    def test_path_traversal_rejected(self):
        with self.assertRaises(JournalError): self.store.publish(self.root/'raw', '../segment-0000000.jsonl')

    def test_symlink_archive_refused(self):
        (self.root/'archives/link').symlink_to(self.source)
        with self.assertRaises(JournalError): self.store.recover()

    def test_invalid_archive_id_refused(self):
        with self.assertRaises(JournalError): next(self.store.read_chunks('../bad'))

    def test_corrupt_compressed_bytes_withheld_before_first_yield(self):
        row = self.publish(); path = self.root/'archives'/row['compressed_name']
        data = bytearray(path.read_bytes()); data[-5] ^= 1; path.write_bytes(data)
        with self.assertRaises(JournalError): next(self.store.read_chunks(row['archive_id']))

    def test_wrong_restored_hash_withheld_even_if_compressed_hash_matches(self):
        row = self.publish()
        identity = row['identity'] | dict(raw_sha256='0'*64)
        modified = row | dict(identity=identity, archive_id=hashlib.sha256(encoded(identity)).hexdigest())
        self.rewritten_descriptor(modified)
        with self.assertRaisesRegex(JournalError, 'restored raw'): next(self.store.read_chunks(modified['archive_id']))

    def test_expansion_beyond_declared_bytes_rejected_before_yield(self):
        row = self.publish()
        identity = row['identity'] | dict(raw_bytes=1)
        modified = row | dict(identity=identity, archive_id=hashlib.sha256(encoded(identity)).hexdigest())
        self.rewritten_descriptor(modified)
        with self.assertRaisesRegex(JournalError, 'expansion'): next(self.store.read_chunks(modified['archive_id']))

    def test_missing_archive_not_silently_replaced_by_raw(self):
        row = self.publish(); (self.root/'archives'/row['compressed_name']).unlink()
        with self.assertRaises(FileNotFoundError): self.store.recover()
        self.assertTrue(self.disk.failed)

    def test_missing_source_reported_but_archive_can_recover_bytes(self):
        row = self.publish(); expected = self.source.read_bytes(); self.source.unlink()
        recovery = self.store.recover()
        self.assertFalse(recovery['catalog_complete'])
        self.assertEqual(recovery['registered'][0]['source_state'], 'MISSING')
        self.assertEqual(b''.join(self.store.read_chunks(row['archive_id'])), expected)

    def test_changed_source_reported_without_overwriting_it(self):
        self.publish(); self.source.write_bytes(b'changed')
        recovery = self.store.recover()
        self.assertFalse(recovery['catalog_complete'])
        self.assertEqual(recovery['registered'][0]['source_state'], 'DIFFERS')
        self.assertEqual(self.source.read_bytes(), b'changed')

    def test_orphan_and_temporary_preserved_and_not_registered(self):
        names = ['0'*32+'.jsonl.gz', '.pending.gz.tmp']
        for name in names: (self.root/'archives'/name).write_bytes(b'partial')
        recovery = self.store.recover()
        self.assertEqual(recovery['registered'], [])
        self.assertEqual(recovery['unregistered_files'], sorted(names))
        self.assertFalse(recovery['catalog_complete'])

    def test_failed_publish_latches_budget_and_keeps_source(self):
        original = file_hash(self.source)
        with patch('app.research.data.segment_archive.os.fsync', side_effect=OSError('disk fault')):
            with self.assertRaises(OSError): self.publish()
        self.assertTrue(self.disk.failed)
        self.assertEqual(file_hash(self.source), original)
        self.assertFalse(list((self.root/'archives').glob('*.json')))
        with self.assertRaises(JournalError): self.publish()

    def test_double_storage_counts_against_budget(self):
        # Deliberately tighten this test object's cap after fixture creation.
        self.disk.contract['max_bytes'] = self.disk.peak+50
        original = file_hash(self.source)
        with self.assertRaisesRegex(JournalError, 'budget'): self.publish()
        self.assertLessEqual(self.disk.peak, self.disk.contract['max_bytes'])
        self.assertEqual(file_hash(self.source), original)

    def test_interrupted_attempt_can_retry_without_deleting_orphans(self):
        def stop(stage):
            if stage == 'after_archive_directory_fsync': raise RuntimeError('interrupted')
        with self.assertRaises(RuntimeError): self.publish(hook=stop)
        self.disk.close()
        self.disk = SharedStorageBudget.resume(self.root, **self.contract)
        self.store = SegmentArchive(self.root/'archives', budget=self.disk)
        before = self.store.recover()
        self.assertEqual(len(before['unregistered_files']), 1)
        row = self.publish()
        after = self.store.recover()
        self.assertEqual(len(after['registered']), 1)
        self.assertEqual(after['unregistered_files'], before['unregistered_files'])
        self.assertEqual(b''.join(self.store.read_chunks(row['archive_id'])), self.source.read_bytes())

    def test_descriptor_path_is_not_trusted(self):
        row = self.publish(); row['compressed_name'] = '../raw/'+self.name
        self.rewritten_descriptor(row)
        with self.assertRaisesRegex(JournalError, 'compressed name'): next(self.store.read_chunks(row['archive_id']))

    def test_descriptor_raw_size_is_bounded(self):
        row = self.publish(); row['identity']['raw_bytes'] = MAX_SEGMENT_BYTES+1
        self.rewritten_descriptor(row)
        with self.assertRaisesRegex(JournalError, 'size bound'): next(self.store.read_chunks(row['archive_id']))

    def test_duplicate_descriptor_keys_rejected(self):
        row = self.publish(); path = self.root/'archives'/(row['archive_id']+'.json')
        path.write_bytes(b'{"version":1,"version":1}')
        with self.assertRaises(JournalError): next(self.store.read_chunks(row['archive_id']))

    def test_idempotent_publish_reanchors_directory_fence(self):
        self.publish()
        with patch('app.research.data.segment_archive.sync_directory', side_effect=OSError('directory fence')):
            with self.assertRaises(OSError): self.publish()
        self.assertTrue(self.disk.failed)

    def test_valid_json_witness_corruption_rejected_before_first_yield(self):
        row = self.publish(); row['witness']['first_sequence'] += 1
        (self.root/'archives'/(row['archive_id']+'.json')).write_bytes(encoded(row))
        with self.assertRaisesRegex(JournalError, 'descriptor checksum'):
            next(self.store.read_chunks(row['archive_id']))

    def test_recovery_does_not_skip_corrupt_descriptor(self):
        row = self.publish(); row['witness']['checkpoint_sha256'] = '1'*64
        (self.root/'archives'/(row['archive_id']+'.json')).write_bytes(encoded(row))
        with self.assertRaisesRegex(JournalError, 'descriptor checksum'): self.store.recover()
        self.assertTrue(self.disk.failed)


if __name__ == '__main__': unittest.main()
