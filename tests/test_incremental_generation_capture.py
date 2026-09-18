import asyncio
from pathlib import Path
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.research.data.durable_capture_log import JournalError, ZERO, decoded, encoded, file_hash
from app.research.data.generation_audit_anchor import restore_offline
from app.research.data.incremental_generation_audit import audit_generation
from app.research.data.incremental_generation_capture import run_synthetic_capture
from app.research.data.incremental_generation_pipeline import IncrementalGenerationArchives
from app.research.data.queued_feed_fixture import QueuedTransport
from app.research.data.read_archived_generation_capture import replay_capture
from tests import test_archived_generation_capture as archived


class IncrementalEvidenceTests(archived.ArchivedEvidenceTests):
    """Run the existing custody, cost and independent replay checks on the new path."""
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name).resolve()
        cls.root = cls.base/'source'
        cls.transport = QueuedTransport()
        cls.anchors = {}
        def hook(stage):
            if stage == 'archive_proof:after_directory_fsync':
                index = len(cls.anchors)
                cls.anchors[index] = file_hash(cls.root/f'generation-{index:04d}'/'archive-proof.json')
        cls.result = asyncio.run(run_synthetic_capture(cls.root, duration_ns=4_400_000_000,
            rotation_ns=2*10**9, transport=cls.transport, hook=hook))
        cls.handle = cls.result['handle']
        if cls.result['outcome'] != 'ORIGINAL_DEADLINE':
            raise AssertionError(cls.result['reason'])

    def audit(self, root=None, index=2, anchor=None):
        return audit_generation(root or self.root, **self.handle, index=index,
            previous_proof_sha256=(ZERO if index == 0 else self.anchors[index-1]) if anchor is None else anchor)

    def mutate(self, root, name, update):
        path = root/name
        value = decoded(path.read_bytes())
        update(value)
        path.write_bytes(encoded(value))

    def test_each_pass_replays_only_current_generation(self):
        work = self.result['pipeline']['audit_work']
        self.assertEqual(len(work), 2*self.result['generations'])
        records = batches = 0
        for row in work:
            directory = self.root/f'generation-{row["index"]:04d}'
            start = decoded((directory/'start.json').read_bytes())
            end = decoded((directory/'end.json').read_bytes())
            self.assertEqual(row['audited_generations'], 1)
            self.assertEqual(row['processed_records'], end['global_sequence']-start['global_sequence'])
            self.assertEqual(row['processed_batches'], end['global_audit_batches']-start['global_audit_batches'])
            records += row['processed_records']; batches += row['processed_batches']
        self.assertEqual(records, 2*self.result['audit']['last_audited_sequence'])
        self.assertEqual(batches, 2*self.result['audit']['valid_batches'])

    def test_final_incremental_equals_origin_replay(self):
        actual = self.audit()
        self.assertEqual(encoded(actual['audit']), encoded(replay_capture(self.root, **self.handle)['audit']))
        self.assertEqual(actual['status'], 'COMPLETE')
        self.assertFalse(actual['live_market_state_restored'])

    def test_proofs_link_previous_parent_anchors(self):
        previous = ZERO
        for index, expected_hash in self.anchors.items():
            proof = decoded((self.root/f'generation-{index:04d}'/'archive-proof.json').read_bytes())
            self.assertEqual(proof['audit_receipt']['previous_proof_sha256'], previous)
            self.assertEqual(proof['audit_receipt']['index'], index)
            previous = expected_hash
        self.assertEqual(self.result['pipeline']['latest_proof_sha256'], previous)
        self.assertEqual(self.result['pipeline']['trusted_completed_generations'], self.result['generations'])

    def test_missing_parent_anchor_refused(self):
        with self.assertRaises(JournalError): self.audit(anchor=ZERO)

    def test_wrong_parent_anchor_refused(self):
        with self.assertRaises(JournalError): self.audit(anchor='1'*64)

    def test_origin_rejects_inherited_anchor(self):
        with self.assertRaises(JournalError): self.audit(index=0, anchor=self.anchors[0])

    def test_changed_predecessor_proof_refused(self):
        root = self.clone()
        self.mutate(root, 'generation-0001/archive-proof.json', lambda p:p['audit_receipt'].update(index=0))
        with self.assertRaises(JournalError): self.audit(root)

    def test_changed_predecessor_end_refused(self):
        root = self.clone()
        self.mutate(root, 'generation-0001/end.json', lambda p:p.update(global_sequence=p['global_sequence']+1))
        with self.assertRaises(JournalError): self.audit(root)

    def test_changed_handoff_refused(self):
        root = self.clone()
        self.mutate(root, 'generation-0001/handoff.json', lambda p:p.update(next_start_sha256=ZERO))
        with self.assertRaises(JournalError): self.audit(root)

    def test_changed_current_seed_refused(self):
        root = self.clone()
        self.mutate(root, 'generation-0002/seed.json', lambda p:p.update(audit_bytes=p['audit_bytes']+1))
        with self.assertRaises(JournalError): self.audit(root)

    def test_changed_current_start_refused(self):
        root = self.clone()
        self.mutate(root, 'generation-0002/start.json', lambda p:p.update(global_sequence=p['global_sequence']+1))
        with self.assertRaises(JournalError): self.audit(root)

    def test_checkpoint_does_not_certify_historical_storage_health(self):
        root = self.clone()
        shutil.rmtree(root/'generation-0000')
        # Parent-trusted continuation covers the new generation only. It must
        # neither reopen old sources nor claim cold-storage validation.
        self.assertEqual(self.audit(root)['audit'], self.audit()['audit'])
        with self.assertRaises(JournalError): replay_capture(root, **self.handle)

    def test_incremental_reader_never_scans_entire_capture_tree(self):
        with patch.object(Path, 'rglob', side_effect=AssertionError('unbounded history scan')):
            self.assertEqual(self.audit()['audited_generations'], 1)

    def test_non_current_candidate_refused(self):
        with self.assertRaises(JournalError):
            audit_generation(self.root, **self.handle, index=2, previous_proof_sha256=self.anchors[1],
                             candidate=dict(index=1, sha256=ZERO))

    def test_generation_limit_unchanged(self):
        for index in (-1, 16, True):
            with self.subTest(index=index), self.assertRaises((JournalError, ValueError)):
                audit_generation(self.root, **self.handle, index=index, previous_proof_sha256=ZERO)

    def test_source_binding_refuses_changed_implementation(self):
        with patch('app.research.data.incremental_generation_audit.implementation_hashes', return_value={}):
            with self.assertRaises(JournalError): self.audit()

    def test_offline_seed_counters_must_match_reducer(self):
        seed = decoded((self.root/'generation-0002/seed.json').read_bytes())
        seed['batches'] += 1
        with self.assertRaises(JournalError): restore_offline(seed, seed['scope'])

    def test_offline_seed_scope_must_match(self):
        seed = decoded((self.root/'generation-0002/seed.json').read_bytes())
        with self.assertRaises(JournalError):
            restore_offline(seed, seed['scope'] | dict(window_end_ns=seed['scope']['window_end_ns']+1))

    def test_cancel_during_first_manager_close_still_closes_second(self):
        owners = []
        class Manager:
            def __init__(self, first):
                self.first, self.calls, self.closed = first, 0, False
            def submit(self, ticket):
                raise RuntimeError('injected archive submission failure')
            async def close(self):
                self.calls += 1
                self.closed = True
                if self.first and self.calls == 1:
                    raise asyncio.CancelledError('cancel at first close after its own cleanup')
        def factory(*args, **kwargs):
            manager = Manager(not owners)
            owners.append(manager)
            return manager
        plan = decoded((self.root/'generation-plan.json').read_bytes())
        budget = SimpleNamespace(root=self.root, contract=dict(run_id=plan['run_id']))
        pipeline = IncrementalGenerationArchives(budget, policy_hash=self.handle['policy_sha256'], factory=factory)
        with self.assertRaises(asyncio.CancelledError): asyncio.run(pipeline._compress(0))
        self.assertEqual(len(owners), 2)
        self.assertTrue(all(m.closed for m in owners))
        self.assertEqual(pipeline.managers, [])


class IncrementalFailureTests(archived.ArchiveFailureTests):
    def setUp(self):
        super().setUp()
        runner = patch.object(archived, 'run_synthetic_capture', run_synthetic_capture)
        runner.start()
        self.addCleanup(runner.stop)


if __name__ == '__main__': unittest.main()
