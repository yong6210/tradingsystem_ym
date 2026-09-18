import asyncio
import gzip
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest

from app.research.data.archived_generation_capture import run_synthetic_capture
from app.research.data.background_segment_archive import BackgroundArchives
from app.research.data.durable_capture_log import JournalError, decoded, encoded, file_hash
from app.research.data.generation_archive_custody import register_policy
from app.research.data.generation_archive_pipeline import GenerationArchives
from app.research.data.queued_feed_fixture import QueuedTransport
from app.research.data.read_archived_generation_capture import replay_capture
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.shared_feed_storage import BudgetedJournal, SharedStorageBudget
from app.research.data.snapshot_feed_audit import audit_epoch
from tests.incremental_audit_fixture import COMPARABLE
from tests.test_retained_feed_collector import inventory


def reference_replay(root, output, handle):
    plan = decoded((root/'generation-plan.json').read_bytes())
    budget = SharedStorageBudget.create(output,run_id=plan['run_id'],max_bytes=256*1024**2,min_free_bytes=0)
    raw = audit = None
    try:
        raw = BudgetedJournal.create(output/'raw',budget=budget,run_id=plan['run_id'])
        audit = BudgetedJournal.create(output/'audit',budget=budget,run_id=plan['run_id'])
        raw.epoch = plan['process_epoch']
        def accept(row):
            assert raw.append(row['payload']) == row['sequence']
            assert raw.record_hash == row['sha256']
        result = replay_capture(root,**handle,raw_sink=accept,audit_sink=audit.append)
        raw.commit(); audit.commit()
    finally:
        if raw is not None: raw.close()
        if audit is not None: audit.close()
        budget.close()
    scope = {k:plan[k] for k in ('window_start_ns','window_end_ns','clock_domain')}
    return result,audit_epoch(output/'raw',output/'audit',**scope,max_intervals=10000)


class ArchivedEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.base = Path(cls.temp.name).resolve()
        cls.root = cls.base/'source'; cls.transport = QueuedTransport()
        cls.result = asyncio.run(run_synthetic_capture(cls.root,duration_ns=4_400_000_000,
            rotation_ns=2*10**9,transport=cls.transport))
        cls.handle = cls.result['handle']
        if cls.result['outcome'] != 'ORIGINAL_DEADLINE': raise AssertionError(cls.result['reason'])

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def clone(self):
        root = self.base/self._testMethodName; shutil.copytree(self.root,root); return root

    def test_same_connections_and_snapshot_while_retiring(self):
        r = self.result
        self.assertEqual(len(self.transport.connections),2); self.assertEqual(self.transport.snapshots,1)
        self.assertGreater(r['handoffs'],0)
        self.assertGreater(r['pipeline']['raw_bytes_removed_while_collecting'],0)
        self.assertEqual(r['counts']['RUN_WINDOW'],1); self.assertEqual(r['counts']['SNAPSHOT'],1)

    def test_gzip_only_replay_matches_live_audit(self):
        actual = replay_capture(self.root,**self.handle)
        self.assertEqual(actual['status'],'COMPLETE')
        self.assertEqual(actual['audit'],self.result['audit'])
        self.assertEqual(actual['source_reads']['RAW'],0)
        self.assertGreater(actual['source_reads']['GZIP'],0)

    def test_independent_frozen_raw_reader_matches_17_fields(self):
        actual,expected = reference_replay(self.root,self.base/'reference',self.handle)
        for field in COMPARABLE: self.assertEqual(encoded(actual['audit'][field]),encoded(expected[field]),field)

    def test_no_dequeued_frame_silently_dropped(self):
        counts = dict(public=0,market=0)
        def count(row):
            p = row['payload']
            if p['kind'] in ('WS','CLOSING_WS'): counts[p['channel']] += 1
        replay_capture(self.root,**self.handle,raw_sink=count)
        for socket in self.transport.sockets:
            s = socket.summary()
            self.assertEqual(counts[s['channel']],s['received'])
            self.assertEqual(s['produced'],s['received']+s['queued_at_stop'])
            self.assertFalse(s['overflow']); self.assertTrue(s['producer_thread_joined'])

    def test_all_metadata_and_archives_in_shared_budget(self):
        self.assertEqual(sum(v[0] for v in inventory(self.root).values()),self.result['storage']['used_bytes'])
        self.assertEqual(self.result['storage']['reserved_bytes'],0)
        self.assertEqual(self.result['storage']['pending_reservations'],0)

    def test_children_reaped_and_pending_bounded(self):
        p = self.result['pipeline']
        self.assertTrue(p['closed'] and p['children_reaped'])
        self.assertEqual(p['submitted'],p['completed']); self.assertEqual(p['pending_generations'],0)
        self.assertEqual(p['abandoned_generations'],[]); self.assertLessEqual(p['peak_pending_generations'],2)
        self.assertLessEqual(p['peak_parent_work_ns'],500_000_000)
        self.assertGreater(p['peak_audit_rss_bytes'],0)
        self.assertLessEqual(p['peak_audit_rss_bytes'],384*1024**2)

    def test_repeat_recovery_is_read_only(self):
        before = inventory(self.root)
        self.assertEqual(replay_capture(self.root,**self.handle),replay_capture(self.root,**self.handle))
        self.assertEqual(before,inventory(self.root))

    def test_cost_gate_charges_all_retention_files(self):
        policy_bytes = (self.root/'generation-retention-policy.json').stat().st_size
        for r in self.result['pipeline']['generations']:
            d = self.root/f'generation-{r["index"]:04d}'
            additions = sum(p.stat().st_size for folder in ('raw-archives','audit-archives') for p in (d/folder).iterdir() if p.is_file())
            additions += sum((d/name).stat().st_size for name in ('archive-candidate.json','archive-proof.json','retention.json','retire-intent.json','retire-done.json'))
            self.assertEqual(r['conservative_net_savings_bytes'],r['raw_bytes']-additions-policy_bytes)
            self.assertGreater(r['conservative_net_savings_bytes'],0)

    def test_missing_policy_anchor_refused(self):
        with self.assertRaises(JournalError): replay_capture(self.root,**(self.handle|dict(policy_sha256='0'*64)))

    def test_missing_registration_with_deleted_raw_refused(self):
        root = self.clone(); (root/'generation-0000/retention.json').unlink()
        with self.assertRaises(JournalError): replay_capture(root,**self.handle)

    def test_missing_intent_with_deleted_raw_refused(self):
        root = self.clone(); (root/'generation-0000/retire-intent.json').unlink()
        with self.assertRaises(JournalError): replay_capture(root,**self.handle)

    def test_done_loss_preserves_valid_gzip_recovery(self):
        root = self.clone(); (root/'generation-0000/retire-done.json').unlink()
        before = inventory(root)
        self.assertEqual(replay_capture(root,**self.handle)['audit'],self.result['audit'])
        self.assertEqual(before,inventory(root))

    def test_seed_cannot_hide_corrupt_old_archive(self):
        root = self.clone(); path = next(root.glob('generation-0000/raw-archives/*.gz'))
        raw = bytearray(path.read_bytes()); raw[-1] ^= 1; path.write_bytes(raw)
        with self.assertRaises((JournalError,ValueError,OSError)): replay_capture(root,**self.handle)

    def test_bad_gzip_never_falls_back_to_remaining_raw(self):
        root = self.clone(); directory = root/'generation-0000'
        (directory/'retire-done.json').unlink()
        refs = decoded((directory/'archive-candidate.json').read_bytes())['refs']
        for ref in refs:
            seal = decoded(ref['certificate']); archive = root/ref['archive']['directory']
            desc = decoded((archive/(ref['archive']['archive_id']+'.json')).read_bytes())
            (root/seal['journal']/seal['segment']['name']).write_bytes(gzip.decompress((archive/desc['compressed_name']).read_bytes()))
        path = next(directory.glob('raw-archives/*.gz'))
        with path.open('ab') as f: f.write(b'corrupt')
        before = inventory(root)
        with self.assertRaises((JournalError,ValueError,OSError)): replay_capture(root,**self.handle)
        self.assertEqual(before,inventory(root))

    def test_changed_retention_proof_refused(self):
        root = self.clone(); path = root/'generation-0000/archive-proof.json'
        proof = decoded(path.read_bytes()); proof['end_seed_sha256'] = '0'*64; path.write_bytes(encoded(proof))
        with self.assertRaises(JournalError): replay_capture(root,**self.handle)

    def test_original_closed_checkpoints_unchanged(self):
        for d in self.root.glob('generation-*'):
            if d.is_dir():
                end = decoded((d/'end.json').read_bytes())
                for kind in ('raw','audit'):
                    self.assertEqual(file_hash(d/kind/'checkpoint.json'),end[kind+'_checkpoint_sha256'])


class ArchiveFailureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()/'run'

    def tearDown(self): self.temp.cleanup()

    async def test_rejects_real_transport_before_writes(self):
        with self.assertRaises(JournalError):
            await run_synthetic_capture(self.root,duration_ns=10**9,transport=object())
        self.assertFalse(self.root.exists())

    async def test_worker_failure_interrupts_collection_and_releases_reservations(self):
        def factory(directory,**kwargs):
            return BackgroundArchives(directory,**kwargs,_command=[sys.executable,'-c','raise SystemExit(4)'])
        transport = QueuedTransport()
        r = await run_synthetic_capture(self.root,duration_ns=4*10**9,rotation_ns=10**9,
            transport=transport,_archive_factory=factory)
        self.assertEqual(r['outcome'],'FATAL_FAILURE'); self.assertTrue(r['pipeline']['error'])
        self.assertEqual(r['storage']['reserved_bytes'],0); self.assertTrue(r['pipeline']['children_reaped'])
        self.assertEqual(r['pipeline']['raw_bytes_removed'],0)
        self.assertEqual(len(transport.connections),2)
        self.assertTrue(all(s.summary()['producer_thread_joined'] for s in transport.sockets))

    async def test_worker_timeout_does_not_delete_sources(self):
        def factory(directory,**kwargs):
            return BackgroundArchives(directory,**kwargs,_command=[sys.executable,'-c','import time; time.sleep(3)'])
        r = await run_synthetic_capture(self.root,duration_ns=4*10**9,rotation_ns=10**9,
            transport=QueuedTransport(),_archive_factory=factory,_job_seconds=.5)
        self.assertEqual(r['outcome'],'FATAL_FAILURE')
        self.assertEqual(r['storage']['reserved_bytes'],0); self.assertTrue(r['pipeline']['children_reaped'])
        self.assertEqual(r['pipeline']['raw_bytes_removed'],0)

    async def test_parent_storage_stall_rejected(self):
        fired = []
        def hook(stage):
            if stage == 'after_parent_archive_fsync' and not fired:
                fired.append(stage); time.sleep(.55)
        r = await run_synthetic_capture(self.root,duration_ns=4*10**9,rotation_ns=10**9,
            transport=QueuedTransport(),hook=hook)
        self.assertTrue(fired); self.assertEqual(r['outcome'],'FATAL_FAILURE')
        self.assertEqual(r['storage']['reserved_bytes'],0)

    async def test_budget_failure_has_no_unsafe_reconnect(self):
        transport = QueuedTransport()
        r = await run_synthetic_capture(self.root,duration_ns=4*10**9,rotation_ns=10**9,
            transport=transport,max_bytes=1024**2)
        self.assertEqual(r['outcome'],'FATAL_FAILURE'); self.assertEqual(len(transport.connections),2)
        self.assertEqual(r['storage']['reserved_bytes'],0)

    async def test_small_uneconomic_generation_keeps_originals(self):
        # A single 100ms tick cannot amortize the policy/proof/custody metadata.
        r = await run_synthetic_capture(self.root,duration_ns=100_000_000,rotation_ns=10**9,
            transport=QueuedTransport(per_tick=1,levels=1))
        self.assertEqual(r['outcome'],'ORIGINAL_DEADLINE')
        self.assertFalse(r['pipeline']['generations'][0]['retired'])
        self.assertLessEqual(r['pipeline']['generations'][0]['conservative_net_savings_bytes'],0)
        self.assertEqual(r['pipeline']['raw_bytes_removed'],0)
        self.assertEqual(replay_capture(self.root,**r['handle'])['audit'],r['audit'])

    async def test_cancellation_reaps_workers_and_releases_root_lock(self):
        active = asyncio.Event()
        def hook(stage):
            if stage == 'generation_audit:child_active': active.set()
        transport = QueuedTransport()
        task = asyncio.create_task(run_synthetic_capture(self.root,duration_ns=6*10**9,
            rotation_ns=10**9,transport=transport,hook=hook))
        await asyncio.wait_for(active.wait(),4)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        from app.research.data.durable_capture_log import lock_directory
        with lock_directory(self.root): pass
        self.assertTrue(all(s.summary()['producer_thread_joined'] for s in transport.sockets))


class ArchivePolicyTests(unittest.TestCase):
    def test_retention_policy_cannot_be_retrofitted(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()/'run'
            budget = ReservedStorageBudget.create(root,run_id='test',max_bytes=10**6,min_free_bytes=0)
            try:
                budget.atomic_json(root/'existing-data.json',{})
                with self.assertRaises(JournalError): register_policy(budget)
            finally: budget.close()

    def test_backlog_is_rejected_instead_of_expanding(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()/'run'
            budget = ReservedStorageBudget.create(root,run_id='test',max_bytes=10**6,min_free_bytes=0)
            try:
                p = GenerationArchives(budget,policy_hash=register_policy(budget))
                p.pending = 2
                with self.assertRaisesRegex(JournalError,'BACKLOG'): p.submit(0)
            finally: budget.close()
