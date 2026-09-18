import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.research.data.durable_capture_log import JournalError, DurableCaptureLog, iter_committed
from app.research.data.verified_journal_view import VerifiedJournalView
from app.research.data import verified_journal_view
from app.research.data.synthetic_feed_fixture import build_fixture, FixtureBudget
from app.research.data.compact_feed_audit import audit_epoch as original
from app.research.data.snapshot_feed_audit import audit_epoch
from tests import test_compact_feed_audit as previous_tests


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name).resolve()
        self.path=self.root/'journal'
        log=DurableCaptureLog.create(self.path,run_id='read',rotation_bytes=1024,max_record_bytes=768,min_free_bytes=0)
        for index in range(4):
            log.append(dict(index=index,pad='x'*250)); log.commit()
        log.close()

    def tearDown(self): self.temp.cleanup()

    def test_full_validation_once_before_replay_and_same_records(self):
        expected=list(iter_committed(self.path))
        with patch.object(verified_journal_view,'scan_records',wraps=verified_journal_view.scan_records) as scan:
            with VerifiedJournalView(self.path,summarize_payload=True) as view:
                self.assertEqual(scan.call_count,1)
                self.assertEqual(list(view.records()),expected)
                self.assertEqual(scan.call_count,2)
                self.assertGreater(view.payload_bytes,0)

    def test_late_segment_corruption_rejected_before_any_yield(self):
        path=sorted(self.path.glob('segment-*.jsonl'))[-1]
        data=bytearray(path.read_bytes()); data[-5]^=1; path.write_bytes(data)
        with self.assertRaises(JournalError):
            with VerifiedJournalView(self.path): self.fail('published corrupt prefix')

    def test_terminal_checkpoint_mismatch_rejected_before_context_is_available(self):
        path = self.path/'checkpoint.json'
        checkpoint = json.loads(path.read_text())
        checkpoint['last_sequence'] += 1
        path.write_text(json.dumps(checkpoint))
        with self.assertRaisesRegex(JournalError, 'terminal record mismatch'):
            with VerifiedJournalView(self.path):
                self.fail('terminal mismatch must fail before publication')

    def test_uncommitted_symlink_segment_is_rejected(self):
        target = self.root/'outside'
        target.write_bytes(b'not a journal')
        (self.path/'segment-0000999.jsonl').symlink_to(target)
        with self.assertRaisesRegex(JournalError, 'symlink'):
            with VerifiedJournalView(self.path):
                self.fail('symlink must be rejected')

    def test_lock_held_until_exit_and_released_after_early_stop(self):
        with VerifiedJournalView(self.path) as view:
            records=view.records()
            next(records)
            with self.assertRaises(JournalError): DurableCaptureLog.resume(self.path)
            records.close()
        writer=DurableCaptureLog.resume(self.path)
        writer.close()

    def test_closed_snapshot_and_double_consumption_rejected(self):
        with VerifiedJournalView(self.path) as view:
            list(view.records())
            with self.assertRaises(JournalError): list(view.records())
        with self.assertRaises(JournalError): list(view.records())
        with self.assertRaises(JournalError): view.__enter__()

    def test_tail_and_checkpoint_temporary_preserved(self):
        path=sorted(self.path.glob('segment-*.jsonl'))[-1]
        with path.open('ab') as stream: stream.write(b'uncertain')
        temp=self.path/'.checkpoint.json.orphan.tmp'; temp.write_bytes(b'uncertain')
        before={p.name:p.read_bytes() for p in self.path.iterdir() if p.is_file()}
        with VerifiedJournalView(self.path) as view:
            self.assertEqual(view.recovery['uncommitted_suffixes'][0]['bytes'],9)
            self.assertEqual(view.recovery['pending_checkpoint_files'],[temp.name])
            self.assertEqual(len(list(view.records())),4)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.path.iterdir() if p.is_file()})

    def test_failed_validation_releases_lock(self):
        path=self.path/'checkpoint.json'
        data=path.read_bytes(); path.write_bytes(b'bad')
        with self.assertRaises(JournalError): VerifiedJournalView(self.path).__enter__()
        path.write_bytes(data)
        writer=DurableCaptureLog.resume(self.path); writer.close()


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name).resolve()

    def tearDown(self): self.temp.cleanup()

    def test_four_stream_fixture_full_replay_matches_original_and_independent_counts(self):
        path=self.root/'fixture'
        plan=build_fixture(path,2,min_free_bytes=0)
        scope={k:plan[k] for k in ('window_start_ns','window_end_ns','clock_domain')}
        result=audit_epoch(path/'journal',path/'audit',**scope)
        self.assertEqual(result,original(path/'journal',path/'audit',**scope))
        self.assertEqual(result['intervals'],plan['expected_intervals'])
        self.assertEqual(result['valid_batches'],41)
        self.assertEqual(result['committed_raw_records'],80)
        self.assertTrue(result['clean_stop_audited'])
        self.assertFalse(result['errors'])
        self.assertFalse(result['processor_errors'])

    def test_fixture_reproduces_exact_bytes(self):
        for name in ('a','b'): build_fixture(self.root/name,1,min_free_bytes=0)
        digests=lambda root:{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in root.rglob('*') if p.is_file()}
        self.assertEqual(digests(self.root/'a'),digests(self.root/'b'))

    def test_existing_directory_never_overwritten(self):
        path=self.root/'fixture'; path.mkdir(); (path/'keep').write_text('user')
        with self.assertRaises(FileExistsError): build_fixture(path,1,min_free_bytes=0)
        self.assertEqual((path/'keep').read_text(),'user')

    def test_fixture_budget_refuses_overflow(self):
        budget=FixtureBudget(self.root,max_bytes=100,min_free_bytes=0)
        budget.reserve(100)
        with self.assertRaises(OSError): budget.reserve(1)
        self.assertEqual(budget.used,100)

    def test_fixture_free_space_floor_checked(self):
        with patch('app.research.data.synthetic_feed_fixture.shutil.disk_usage') as disk:
            disk.return_value.free=100
            with self.assertRaises(OSError): FixtureBudget(self.root,min_free_bytes=100)

    def test_fixture_failure_preserves_partial_files_without_checkpoint(self):
        path=self.root/'fixture'
        with self.assertRaises(OSError): build_fixture(path,2,max_bytes=2000,min_free_bytes=0)
        self.assertTrue((path/'journal/metadata.json').exists())
        self.assertFalse((path/'journal/checkpoint.json').exists())


class ReplayContracts(previous_tests.ReplayTests):
    def compare(self,path,**extra):
        expected=original(self.e.root/'journal',path,**self.scope,**extra)
        current=audit_epoch(self.e.root/'journal',path,**self.scope,**extra)
        self.assertEqual(current,expected)
        details=current.pop('interval_reduction')
        return current,details

    def test_replay_budget_failure_cannot_certify_partial_coverage(self):
        self.e.fresh(100_000_000); self.e.tick(300_000_000)
        path=self.convert()
        result=audit_epoch(self.e.root/'journal',path,**self.scope,max_intervals=1)
        self.assertTrue(result['errors'])
        self.assertTrue(result['interval_reduction']['failed'])
        self.assertTrue(all(not rows for rows in result['intervals'].values()))


if __name__=='__main__': unittest.main()
