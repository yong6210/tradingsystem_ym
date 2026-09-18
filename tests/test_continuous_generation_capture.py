import asyncio
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from app.research.data.continuous_generation_capture import run_synthetic_capture, validate_plan
from app.research.data.durable_capture_log import JournalError, decoded, encoded, file_hash
from app.research.data.generation_feed_replay import GenerationReplay, sha
from app.research.data.queued_feed_fixture import QueuedTransport
from app.research.data.read_generation_capture import replay_capture
from app.research.data.shared_feed_storage import SharedStorageBudget, BudgetedJournal
from app.research.data.snapshot_feed_audit import audit_epoch
from tests.incremental_audit_fixture import COMPARABLE
from tests.test_retained_feed_collector import inventory


def reference_replay(root, output):
    plan = decoded((root/'generation-plan.json').read_bytes())
    budget = SharedStorageBudget.create(output, run_id=plan['run_id'], max_bytes=256*1024**2, min_free_bytes=0)
    raw = audit = None
    try:
        raw = BudgetedJournal.create(output/'raw', budget=budget, run_id=plan['run_id'])
        audit = BudgetedJournal.create(output/'audit', budget=budget, run_id=plan['run_id'])
        raw.epoch = plan['process_epoch']
        def accept(row):
            assert raw.append(row['payload']) == row['sequence']
            assert raw.record_hash == row['sha256']
        actual = replay_capture(root, plan_sha256=file_hash(root/'generation-plan.json'), raw_sink=accept, audit_sink=audit.append)
        raw.commit(); audit.commit()
    finally:
        if raw is not None: raw.close()
        if audit is not None: audit.close()
        budget.close()
    scope = {k:plan[k] for k in ('window_start_ns', 'window_end_ns', 'clock_domain')}
    expected = audit_epoch(output/'raw', output/'audit', **scope, max_intervals=10000)
    return actual, expected


class GenerationContractTests(unittest.TestCase):
    def test_fixed_capacity_plan(self):
        validate_plan(40*10**9, 8*10**9, 500_000_000)

    def test_rejects_long_or_excessive_generations(self):
        for seconds, rotation in ((121, 8), (120, 1), (2, 31), (2, 0)):
            with self.assertRaises(JournalError): validate_plan(seconds*10**9, rotation*10**9, 500_000_000)

    def test_rejects_fast_sealing(self):
        with self.assertRaises(JournalError): validate_plan(2*10**9, 10**9, 100_000_000)

    def test_rejects_real_transport_before_creating_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)/'absent'
            with self.assertRaises(JournalError):
                asyncio.run(run_synthetic_capture(root, duration_ns=10**9, transport=object()))
            self.assertFalse(root.exists())


class GenerationEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name).resolve()
        cls.root = cls.base/'source'
        cls.transport = QueuedTransport()
        cls.result = asyncio.run(run_synthetic_capture(cls.root, duration_ns=2_400_000_000,
            rotation_ns=10**9, transport=cls.transport))
        cls.plan_hash = file_hash(cls.root/'generation-plan.json')
        cls.rows, cls.batches = [], []
        cls.recovered = replay_capture(cls.root, plan_sha256=cls.plan_hash,
                                      raw_sink=cls.rows.append, audit_sink=cls.batches.append)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def clone(self):
        root = self.base/self._testMethodName
        shutil.copytree(self.root, root)
        return root

    def test_same_session_and_single_snapshot_across_generations(self):
        self.assertEqual(self.result['outcome'], 'ORIGINAL_DEADLINE')
        self.assertGreaterEqual(self.result['generations'], 2)
        self.assertEqual(len(self.transport.connections), 2)
        self.assertEqual(self.transport.snapshots, 1)
        counts = self.result['counts']
        self.assertEqual(counts['RUN_WINDOW'], 1)
        self.assertEqual(counts['OPEN'], 2)
        self.assertEqual(counts['SNAPSHOT'], 1)
        self.assertEqual(counts['STOP'], 1)
        self.assertEqual(len({r['epoch'] for r in self.rows}), 1)
        self.assertTrue(all(s.summary()['producer_thread_joined'] for s in self.transport.sockets))

    def test_reference_reader_matches_all_17_fields(self):
        actual, expected = reference_replay(self.root, self.base/'reference')
        self.assertEqual(expected['status'], 'AUDIT_PREFIX_COMPLETE', expected['errors'])
        for field in COMPARABLE:
            self.assertEqual(encoded(actual['audit'][field]), encoded(expected[field]), field)

    def test_in_memory_and_cold_replay_agree(self):
        self.assertEqual(self.recovered['audit'], self.result['audit'])
        self.assertEqual(self.recovered['status'], 'COMPLETE')

    def test_repeated_recovery_does_not_write(self):
        before = inventory(self.root)
        again = replay_capture(self.root, plan_sha256=self.plan_hash)
        self.assertEqual(again, self.recovered)
        self.assertEqual(before, inventory(self.root))

    def test_all_capture_bytes_are_in_shared_budget(self):
        self.assertEqual(sum(size for size, _ in inventory(self.root).values()), self.result['storage']['used_bytes'])

    def test_global_sequence_has_no_reset_duplicate_or_gap(self):
        self.assertEqual([r['sequence'] for r in self.rows], list(range(1, len(self.rows)+1)))
        for socket in self.transport.sockets:
            summary = socket.summary()
            persisted = sum(r['payload']['kind'] in ('WS','CLOSING_WS') and r['payload']['channel'] == socket.channel for r in self.rows)
            self.assertEqual(persisted, summary['received'])
            self.assertEqual(summary['produced'], summary['received']+summary['queued_at_stop'])
            self.assertFalse(summary['overflow'])

    def test_wrong_external_plan_rejected(self):
        with self.assertRaisesRegex(JournalError, 'plan differs'):
            replay_capture(self.root, plan_sha256='0'*64)

    def test_seed_cannot_be_substituted_even_with_new_local_hash(self):
        root = self.clone()
        directory = root/'generation-0001'
        seed = decoded((directory/'seed.json').read_bytes())
        seed['previous_published'] += 1
        (directory/'seed.json').write_bytes(encoded(seed))
        start = decoded((directory/'start.json').read_bytes())
        start['seed_sha256'] = sha(seed)
        (directory/'start.json').write_bytes(encoded(start))
        path = root/'generation-0000/handoff.json'
        link = decoded(path.read_bytes()); link['next_start_sha256'] = sha(start)
        path.write_bytes(encoded(link))
        with self.assertRaisesRegex(JournalError, 'source-backed seed'):
            replay_capture(root, plan_sha256=self.plan_hash)

    def test_missing_handoff_preserves_prepared_generation(self):
        root = self.clone()
        (root/'generation-0000/handoff.json').unlink()
        result = replay_capture(root, plan_sha256=self.plan_hash)
        self.assertEqual(result['status'], 'INTERRUPTED_PREFIX_PRESERVED')
        self.assertIn('generation-0001', result['unlinked_prepared_generations'])
        self.assertEqual(len(result['generations']), 1)

    def test_linked_missing_generation_rejected(self):
        root = self.clone(); shutil.rmtree(root/'generation-0001')
        with self.assertRaisesRegex(JournalError, 'linked generation missing'):
            replay_capture(root, plan_sha256=self.plan_hash)

    def test_corrupt_old_raw_is_not_hidden_by_seed(self):
        root = self.clone(); path = next((root/'generation-0000/raw').glob('segment-*.jsonl'))
        data = bytearray(path.read_bytes()); data[-3] ^= 1; path.write_bytes(data)
        with self.assertRaises((JournalError, ValueError)):
            replay_capture(root, plan_sha256=self.plan_hash)

    def test_sealed_raw_suffix_is_preserved_and_rejected(self):
        root = self.clone(); path = sorted(root.glob('generation-*/raw/segment-*.jsonl'))[-1]
        with path.open('ab') as stream: stream.write(b'uncertain-suffix\n')
        before = inventory(root)
        with self.assertRaisesRegex(JournalError, 'sealed segment size or hash'):
            replay_capture(root, plan_sha256=self.plan_hash)
        self.assertEqual(before, inventory(root))

    def test_global_duplicate_or_gap_rejected(self):
        scope = {k:self.result['audit'][k] for k in ('window_start_ns','window_end_ns','clock_domain')}
        first = self.batches[0]; count = first['last_sequence']
        for delta in (-1, 1):
            replay = GenerationReplay(scope); rows = copy.deepcopy(self.rows[:count])
            rows[-1]['sequence'] += delta
            rows[-1]['sha256'] = sha({k:v for k,v in rows[-1].items() if k != 'sha256'})
            with self.assertRaisesRegex(JournalError, 'global raw sequence'):
                replay.accept(rows, first)

    def test_audit_observation_substitution_rejected(self):
        scope = {k:self.result['audit'][k] for k in ('window_start_ns','window_end_ns','clock_domain')}
        batch = copy.deepcopy(self.batches[0]); batch['observation']['eligible'] = True
        with self.assertRaisesRegex(JournalError, 'observation differs'):
            GenerationReplay(scope).accept(self.rows[:batch['last_sequence']], batch)

    def test_units_start_at_zero_each_generation(self):
        for directory in self.root.glob('generation-*'):
            if directory.is_dir():
                files = sorted(directory.glob('unit-*.json'))
                self.assertEqual(files[0].name, 'unit-0000.json')
                self.assertLessEqual(len(files), 62)


class GenerationFailureTests(unittest.TestCase):
    def test_budget_exhaustion_never_reconnects(self):
        with tempfile.TemporaryDirectory() as d:
            transport = QueuedTransport()
            result = asyncio.run(run_synthetic_capture(Path(d).resolve()/'run', duration_ns=2*10**9,
                rotation_ns=10**9, transport=transport, max_bytes=120000))
            self.assertEqual(result['outcome'], 'FATAL_FAILURE')
            self.assertIn('budget', result['reason'])
            self.assertEqual(len(transport.connections), 2)
            self.assertTrue(all(s.summary()['producer_thread_joined'] for s in transport.sockets))
