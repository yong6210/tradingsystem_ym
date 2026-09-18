import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.research.data.shared_feed_storage import SharedStorageBudget, BudgetedJournal, SegmentedAudit
from app.research.data.durable_capture_log import JournalError, encoded, inspect_journal, iter_committed
from app.research.data.segmented_feed_collector import run_bounded, SegmentedFeedEpoch
from app.research.data.segmented_feed_audit import audit_epoch
from tests import test_bounded_feed_collector as fixtures


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()/'run'
        self.disk = SharedStorageBudget.create(self.root, run_id='test', max_bytes=1_000_000, min_free_bytes=0)
        self.logs = []

    def tearDown(self):
        for log in self.logs:
            log.close()
        self.disk.close()
        self.temp.cleanup()

    def journal(self, name='raw'):
        obj = BudgetedJournal.create(self.root/name, budget=self.disk, run_id='test',
                                      rotation_bytes=1024, max_record_bytes=768)
        self.logs.append(obj)
        return obj

    def actual(self):
        return sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())

    def test_rotated_raw_audit_and_auxiliary_share_exact_inventory(self):
        raw, audit = self.journal(), self.journal('audit')
        for i in range(8):
            raw.append(dict(i=i, padding='x'*280))
            receipt = raw.commit()
            audit.append(dict(last=receipt.sequence, hash=receipt.record_sha256))
            audit.commit()
            self.disk.atomic_json(self.root/'status.json', dict(index=i))
            self.assertEqual(self.disk.used, self.actual())
        raw.close(); audit.close()
        self.assertEqual(len(list(iter_committed(raw.directory))), 8)
        self.assertEqual(len(list(iter_committed(audit.directory))), 8)
        self.assertGreater(inspect_journal(raw.directory)['committed_segments'], 1)
        self.assertGreater(inspect_journal(audit.directory)['committed_segments'], 1)
        self.assertGreater(self.disk.peak, self.disk.used)

    def test_default_audit_rotation_crosses_former_32_mib_limit(self):
        root = self.root.parent/'large-run'
        disk = SharedStorageBudget.create(root, run_id='large', max_bytes=64*1024**2, min_free_bytes=0)
        audit = SegmentedAudit(root/'audit', budget=disk)
        try:
            for i in range(33):
                audit.append(dict(index=i, payload='x'*(1024**2)))
            self.assertGreater(audit.bytes, 32*1024**2)
            audit.close()
            self.assertGreater(inspect_journal(root/'audit')['committed_segments'], 1)
            self.assertEqual(sum(1 for _ in iter_committed(root/'audit')), 33)
            self.assertEqual(disk.used, sum(p.stat().st_size for p in root.rglob('*') if p.is_file()))
        finally:
            audit.close()
            disk.close()

    def test_replacement_counts_old_and_new_at_peak(self):
        path = self.root/'status.json'
        self.disk.atomic_json(path, dict(text='x'*100))
        before, old = self.disk.used, path.read_bytes()
        self.disk.contract['max_bytes'] = before+len(old)-1
        with self.assertRaisesRegex(JournalError, 'aggregate run'):
            self.disk.atomic_json(path, dict(text='x'*100))
        self.assertEqual(path.read_bytes(), old)
        self.assertEqual(self.disk.used, self.actual())
        self.assertTrue(self.disk.failed)

    def test_recovery_counts_unknown_tails_and_temp_files(self):
        raw = self.journal()
        raw.append(dict(value=1)); raw.commit()
        raw.append(dict(value=2)); raw.close()
        self.disk.close()
        (self.root/'.unacknowledged.tmp').write_bytes(b'x'*97)
        self.disk = SharedStorageBudget.resume(self.root, run_id='test', max_bytes=1_000_000, min_free_bytes=0)
        self.assertEqual(self.disk.used, self.actual())
        recovered = BudgetedJournal.resume(raw.directory, budget=self.disk)
        self.logs.append(recovered)
        self.assertEqual(recovered.sequence, 1)
        self.assertTrue(recovered.recovery['uncommitted_suffixes'])
        recovered.append(dict(value=3)); recovered.commit(); recovered.close()
        self.assertEqual([r['payload']['value'] for r in iter_committed(raw.directory)], [1,3])
        self.assertTrue(inspect_journal(raw.directory)['uncommitted_suffixes'])
        self.assertEqual(self.disk.used, self.actual())

    def test_contract_change_cannot_reset_recovered_budget(self):
        self.disk.close()
        with self.assertRaisesRegex(JournalError, 'contract mismatch'):
            SharedStorageBudget.resume(self.root, run_id='test', max_bytes=2_000_000, min_free_bytes=0)

    def test_recovery_refuses_files_exceeding_original_budget(self):
        self.disk.close()
        (self.root/'unknown.bin').write_bytes(b'x'*1_000_000)
        with self.assertRaisesRegex(JournalError, 'aggregate run'):
            SharedStorageBudget.resume(self.root, run_id='test', max_bytes=1_000_000, min_free_bytes=0)

    def test_root_lock_prevents_second_budget(self):
        with self.assertRaisesRegex(JournalError, 'busy'):
            SharedStorageBudget.resume(self.root, run_id='test', max_bytes=1_000_000, min_free_bytes=0)

    def test_symlink_and_outside_write_refused(self):
        (self.root/'link').symlink_to(self.root.parent)
        with self.assertRaises(JournalError):
            self.disk.reconcile()
        with self.assertRaises(JournalError):
            self.disk.atomic_json(self.root.parent/'escape.json', dict(x=1))

    def test_free_space_failure_stops_both_writers(self):
        raw, audit = self.journal(), self.journal('audit')
        with patch('app.research.data.shared_feed_storage.shutil.disk_usage') as usage:
            usage.return_value.free = 65535
            with self.assertRaisesRegex(JournalError, 'free-space'):
                raw.append(dict(x=1))
        with self.assertRaises(JournalError):
            audit.append(dict(x=2))
        with self.assertRaises(JournalError):
            raw.publication_fence()

    def test_short_write_is_counted_and_latches_budget(self):
        path = self.root/'partial.bin'
        with path.open('xb', buffering=0) as stream:
            class Short:
                name = str(path)
                def tell(self): return stream.tell()
                def write(self, data): return stream.write(data[:3])
            with self.assertRaisesRegex(OSError, 'short'):
                self.disk.append(Short(), b'abcdefgh')
        self.assertEqual(path.read_bytes(), b'abc')
        self.assertEqual(self.disk.used, self.actual())
        self.assertTrue(self.disk.failed)

    def test_enospc_during_fsync_retains_bytes_without_commit(self):
        raw = self.journal()
        raw.append(dict(x=1))
        with patch('app.research.data.shared_feed_storage.os.fsync', side_effect=OSError(28, 'no space')):
            with self.assertRaises(OSError): raw.commit()
        raw.close()
        self.assertEqual(inspect_journal(raw.directory)['last_sequence'], 0)
        self.assertTrue(inspect_journal(raw.directory)['uncommitted_suffixes'])
        self.assertEqual(self.disk.used, self.actual())

    def test_replacement_failure_preserves_temp_and_old_checkpoint(self):
        raw = self.journal()
        raw.append(dict(x=1)); raw.commit()
        old = (raw.directory/'checkpoint.json').read_bytes()
        raw.append(dict(x=2))
        with patch('app.research.data.shared_feed_storage.os.replace', side_effect=OSError(28, 'no space')):
            with self.assertRaises(OSError): raw.commit()
        raw.close()
        self.assertEqual((raw.directory/'checkpoint.json').read_bytes(), old)
        self.assertTrue(inspect_journal(raw.directory)['pending_checkpoint_files'])
        self.assertEqual(self.disk.used, self.actual())

    def test_corrupt_rotated_segment_rejects_entire_stream(self):
        raw = self.journal()
        for i in range(3):
            raw.append(dict(x=i, padding='x'*280)); raw.commit()
        raw.close()
        path = raw.directory/'segment-0000000.jsonl'
        data = bytearray(path.read_bytes()); data[-5] ^= 1; path.write_bytes(data)
        with self.assertRaises(JournalError):
            next(iter_committed(raw.directory))

    def test_budget_exhaustion_does_not_publish_audit(self):
        audit = SegmentedAudit(self.root/'audit', budget=self.disk, rotation_bytes=2048, max_record_bytes=1792)
        self.logs.append(audit)
        audit.append(dict(x=1))
        self.disk.contract['max_bytes'] = self.disk.used
        with self.assertRaises(JournalError): audit.append(dict(x=2))
        self.assertEqual(audit.lines, 1)
        audit.close()
        self.assertEqual(inspect_journal(audit.journal.directory)['last_sequence'], 1)


class CollectorTests(fixtures.CollectorIntegrationTests):
    def setUp(self):
        super().setUp()
        self.output = self.output.resolve()

    async def run_case(self, transport, duration=200_000_000, **kwargs):
        return await run_bounded(self.output, duration_ns=duration, transport=transport, policy=self.policy, **kwargs)

    async def test_audit_failure_retains_raw_but_prevents_retry(self):
        original = SegmentedAudit.append
        def broken(writer, value):
            if writer.journal.directory.name=='audit' and writer.lines==1:
                with writer.journal.budget.mutation():
                    raise OSError(28, 'injected audit ENOSPC')
            return original(writer, value)
        with patch.object(SegmentedAudit, 'append', broken):
            result = await self.run_case(fixtures.ScriptedTransport())
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
        self.assertEqual(result['retries_used'], 0)
        self.assertGreater(result['audits'][0]['unaudited_committed_records'], 0)
        self.assertEqual(result['epochs'][0]['last_audited_sequence'], 2)
        self.assertFalse(result['result_persisted'])
        self.assertFalse((self.output/'collection_result.json').exists())

    async def test_raw_preflight_failure_opens_no_network(self):
        original = BudgetedJournal.commit
        def broken(log):
            if log.directory.name=='journal':
                with log.budget.mutation(): raise OSError(28, 'disk')
            return original(log)
        transport = fixtures.ScriptedTransport()
        with patch.object(BudgetedJournal, 'commit', broken):
            result = await self.run_case(transport)
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
        self.assertFalse(transport.connections)
        self.assertGreater(result['total_raw_bytes'], 0)
        self.assertFalse(result['result_persisted'])

    async def test_caller_cancellation_closes_sockets_and_records_stop(self):
        transport = fixtures.ScriptedTransport()
        task = asyncio.create_task(self.run_case(transport, duration=2_000_000_000))
        while len(transport.sockets)<2: await asyncio.sleep(.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(all(socket.closed.is_set() for socket in transport.sockets))
        self.assertTrue(any(row['payload']['kind']=='STOP' for row in self.raw()))
        control = [row['payload'] for row in iter_committed(self.output/'supervisor')]
        self.assertEqual(control[-1]['kind'], 'CANCELLED')
        cfg = json.loads((self.output/'storage.json').read_text())
        cfg.pop('version')
        recovered = SharedStorageBudget.resume(self.output, **cfg)
        recovered.close()

    async def test_storage_failure_during_disconnect_cleanup_overrides_retry(self):
        original = SegmentedAudit.append
        def broken(writer, value):
            if writer.journal.directory.name=='audit' and value['observation']['stopped']:
                with writer.journal.budget.mutation(): raise OSError(28, 'stop audit')
            return original(writer, value)
        with patch.object(SegmentedAudit, 'append', broken):
            result = await self.run_case(fixtures.ScriptedTransport(disconnect_first=True), duration=2_000_000_000)
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
        self.assertEqual(result['retries_used'], 0)
        self.assertEqual(len(result['epochs']), 1)

    async def test_small_audit_rotation_preserves_coverage_and_aggregate_accounting(self):
        original = SegmentedAudit.__init__
        def small(writer, directory, **kwargs):
            if Path(directory).name=='audit':
                kwargs.update(rotation_bytes=4096, max_record_bytes=3840)
            original(writer, directory, **kwargs)
        with patch.object(SegmentedAudit, '__init__', small):
            result = await self.run_case(fixtures.ScriptedTransport(), duration=550_000_000)
        self.assertEqual(result['stop_reason'], 'ORIGINAL_DEADLINE')
        self.assertTrue(result['result_persisted'])
        self.assertFalse(result['audits'][0]['errors'])
        self.assertGreater(result['audits'][0]['audit_recovery']['committed_segments'], 1)
        size = sum(p.stat().st_size for p in self.output.rglob('*') if p.is_file())
        self.assertEqual(result['storage_after_result']['used_bytes'], size)
        self.assertGreater(size, result['total_raw_bytes']+result['epochs'][0]['audit_bytes'])

    async def test_second_epoch_does_not_reset_accounting(self):
        observed=[]
        original=SegmentedFeedEpoch.__init__
        def record(epoch,*args,**kwargs):
            original(epoch,*args,**kwargs)
            observed.append(kwargs['budget'].used)
        with patch.object(SegmentedFeedEpoch,'__init__',record):
            result=await self.run_case(fixtures.ScriptedTransport(disconnect_first=True),duration=1_600_000_000)
        self.assertEqual(len(observed),2)
        self.assertGreater(observed[1],observed[0])
        self.assertEqual(result['storage_after_result']['used_bytes'],
                         sum(p.stat().st_size for p in self.output.rglob('*') if p.is_file()))

    async def test_reconnect_hits_original_aggregate_cap(self):
        original = SharedStorageBudget.create.__func__
        def small(cls, root, **kwargs):
            kwargs['max_bytes'] = 35_000  # Fixed diagnostic cap, before any write.
            return original(cls, root, **kwargs)
        with patch.object(SharedStorageBudget, 'create', classmethod(small)):
            result = await self.run_case(fixtures.ScriptedTransport(disconnect_first=True),
                                         duration=1_600_000_000)
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
        self.assertEqual(result['retries_used'], 1)
        self.assertEqual(len(result['epochs']), 2)
        self.assertTrue(result['storage_after_result']['failed'])
        self.assertLessEqual(result['storage_after_result']['peak_bytes'], 35_000)
        self.assertFalse(result['result_persisted'])

    async def test_pending_audit_checkpoint_is_not_silently_ignored(self):
        result = await self.run_case(fixtures.ScriptedTransport())
        path = self.output/'epoch-00/audit/.checkpoint.json.orphan.tmp'
        path.write_bytes(b'uncertain checkpoint')
        row = audit_epoch(self.output/'epoch-00/journal', path.parent, **result['original_window'])
        self.assertIn('PENDING_AUDIT_CHECKPOINT_PRESENT', row['errors'])
        self.assertEqual(row['valid_batches'], result['audits'][0]['valid_batches'])

    async def test_result_write_failure_is_returned_without_unsafe_fallback(self):
        original=SharedStorageBudget.atomic_json
        def broken(budget,path,value,*args,**kwargs):
            if Path(path).name=='collection_result.json':
                with budget.mutation(): raise OSError(28,'result full')
            return original(budget,path,value,*args,**kwargs)
        with patch.object(SharedStorageBudget,'atomic_json',broken):
            result=await self.run_case(fixtures.ScriptedTransport())
        self.assertEqual(result['stop_reason'],'FATAL_FAILURE')
        self.assertFalse(result['result_persisted'])
        self.assertEqual(result['combined']['quality']['status'],'QUALITY_INPUTS_REJECTED')
        self.assertFalse((self.output/'collection_result.json').exists())

    async def test_committed_audit_corruption_yields_no_coverage(self):
        result=await self.run_case(fixtures.ScriptedTransport())
        path=self.output/'epoch-00/audit/segment-0000000.jsonl'
        data=bytearray(path.read_bytes()); data[-5]^=1; path.write_bytes(data)
        row=audit_epoch(self.output/'epoch-00/journal',path.parent,**result['original_window'])
        self.assertTrue(row['errors'])
        self.assertEqual(row['valid_batches'],0)
        self.assertTrue(all(not values for values in row['intervals'].values()))

    async def test_uncommitted_audit_tail_is_preserved_and_rejected(self):
        result=await self.run_case(fixtures.ScriptedTransport())
        path=self.output/'epoch-00/audit/segment-0000000.jsonl'
        with path.open('ab') as stream: stream.write(b'uncertain tail')
        row=audit_epoch(self.output/'epoch-00/journal',path.parent,**result['original_window'])
        self.assertIn('UNCOMMITTED_AUDIT_SUFFIX_PRESENT',row['errors'])
        self.assertEqual(row['valid_batches'],result['audits'][0]['valid_batches'])


if __name__=='__main__': unittest.main()
