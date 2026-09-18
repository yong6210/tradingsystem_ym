import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.research.data import retirement_admission as admission
from app.research.data.closed_capture_retirement import (
    register_retention_policy, retire_raw, replay_retired_capture)
from app.research.data.durable_capture_log import JournalError, file_hash, lock_directory
from app.research.data.durable_sealed_pipeline import DurableSealedPipeline
from app.research.data.pipelined_feed_collector import run_bounded
from app.research.data.queued_feed_fixture import QueuedTransport
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.sealed_feed_pipeline import PipelineLimits
from tests.test_bounded_feed_collector import ROOT, ScriptedTransport, load_contract


class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()/'capture'
        self.budget = None

    def tearDown(self):
        if self.budget:
            self.budget.close()
        self.temp.cleanup()

    async def collect(self, *, large=False, opt_in=True):
        def factory(budget, **kw):
            if opt_in:
                register_retention_policy(budget)
            return DurableSealedPipeline(budget, **kw)
        result = await run_bounded(self.root, duration_ns=1_000_000_000 if large else 350_000_000,
            transport=QueuedTransport(per_tick=200, capacity=1024) if large else ScriptedTransport(),
            policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json'),
            pipeline_limits=PipelineLimits(seal_seconds=.5 if large else .1), _pipeline_factory=factory)
        self.assertEqual(result['stop_reason'], 'ORIGINAL_DEADLINE', result['errors'])
        self.anchor = result['pipeline']['work_ledger_anchor']
        contract = json.loads((self.root/'storage.json').read_text())
        self.budget = ReservedStorageBudget.resume(self.root, **{k:v for k,v in contract.items() if k != 'version'})

    def inventory(self):
        return {str(p.relative_to(self.root)): (p.stat().st_size, file_hash(p))
                for p in self.root.rglob('*') if p.is_file()}

    def raw_files(self):
        return sorted(self.root.glob('epoch-*/*/segment-*.jsonl'))

    def forecast(self, **kw):
        return admission.forecast_retirement(self.budget, work_anchor=self.anchor, **kw)

    def prepare(self, **kw):
        return admission.prepare_if_economic(self.budget, work_anchor=self.anchor, **kw)

    async def test_small_rejection_writes_nothing_and_deletes_nothing(self):
        await self.collect()
        before = self.inventory()
        result = self.prepare()
        self.assertFalse(result['estimate']['admitted'])
        self.assertIsNone(result['anchor'])
        self.assertLess(result['estimate']['projected_net_savings_bytes'], 0)
        self.assertEqual(before, self.inventory())
        self.assertFalse((self.root/'retirement').exists())
        self.assertFalse(list(self.root.glob('retirement-replay-*')))

    async def test_read_only_forecast_repeats_without_accumulating_files(self):
        await self.collect()
        before = self.inventory()
        first = self.forecast()
        self.assertEqual(first, self.forecast())
        self.assertEqual(before, self.inventory())

    async def test_large_clean_path_matches_exact_bytes_and_gzip_replay(self):
        await self.collect(large=True)
        before = self.inventory()
        raw_before = self.raw_files()
        result = self.prepare()
        estimate = result['estimate']
        self.assertTrue(estimate['admitted'])
        self.assertEqual(self.raw_files(), raw_before)
        retired = retire_raw(self.budget, anchor=result['anchor'])
        proof = replay_retired_capture(self.budget, anchor=result['anchor'])
        self.assertEqual(proof['fields_each'], 17)
        after = self.inventory()
        self.assertEqual(sum(v[0] for v in after.values()), estimate['projected_final_bytes'])
        self.assertEqual(retired['logical_raw_bytes_removed_this_call'], estimate['raw_bytes'])
        self.assertLess(sum(v[0] for v in after.values()), sum(v[0] for v in before.values()))
        self.assertEqual({p:v for p,v in before.items() if p in after},
                         {p:v for p,v in after.items() if p in before})
        self.assertLessEqual(self.budget.snapshot()['peak_bytes'],
                            estimate['closed_capture_bytes']+estimate['conservative_peak_growth_bytes'])

    async def test_savings_boundary_has_no_rounding_or_threshold_tuning(self):
        await self.collect(large=True)
        estimate = self.forecast()
        savings = estimate['projected_net_savings_bytes']
        self.assertGreater(savings, 0)
        self.assertTrue(self.forecast(minimum_net_savings_bytes=savings)['admitted'])
        before = self.inventory()
        result = self.prepare(minimum_net_savings_bytes=savings+1)
        self.assertFalse(result['estimate']['admitted'])
        self.assertEqual(before, self.inventory())

    async def test_requires_original_opt_in(self):
        await self.collect(opt_in=False)
        before = self.inventory()
        with self.assertRaisesRegex(JournalError, 'policy missing'):
            self.forecast()
        self.assertEqual(before, self.inventory())

    async def test_bad_anchor_preserves_raw_without_preparation(self):
        await self.collect()
        self.anchor = dict(sequence=0, event_sha256='0'*64)
        before = self.inventory()
        with self.assertRaisesRegex(JournalError, 'anchor mismatch'):
            self.forecast()
        self.assertEqual(before, self.inventory())

    async def test_archive_damage_cannot_use_raw_fallback(self):
        await self.collect()
        archive = next(self.root.glob('epoch-*/*-archives/*.gz'))
        archive.write_bytes(archive.read_bytes()[:-1])
        before = self.inventory()
        with self.assertRaises(JournalError):
            self.forecast()
        self.assertEqual(before, self.inventory())

    async def test_active_worker_refused_without_metadata_growth(self):
        await self.collect()
        self.budget.reserve('pending', 1)
        before = self.inventory()
        with self.assertRaisesRegex(JournalError, 'active workers'):
            self.forecast()
        self.assertEqual(before, self.inventory())

    async def test_active_journal_writer_refused(self):
        await self.collect()
        before = self.inventory()
        lock = lock_directory(self.root/'epoch-00/journal')
        try:
            with self.assertRaisesRegex(JournalError, 'busy'):
                self.forecast()
        finally:
            lock.close()
        self.assertEqual(before, self.inventory())

    async def test_unknown_tail_is_preserved_and_refused(self):
        await self.collect()
        raw = self.raw_files()[0]
        raw.write_bytes(raw.read_bytes()+b'uncertain')
        before = self.inventory()
        with self.assertRaises(JournalError):
            self.forecast()
        self.assertEqual(before, self.inventory())

    async def test_missing_lock_is_not_recreated_by_read_only_gate(self):
        await self.collect()
        (self.root/'epoch-00/journal/.writer.lock').unlink()
        before = self.inventory()
        with self.assertRaisesRegex(JournalError, 'existing journal lock'):
            self.forecast()
        self.assertEqual(before, self.inventory())

    async def test_existing_partial_preparation_requires_recovery(self):
        await self.collect()
        (self.root/'retirement').mkdir()
        before = self.inventory()
        with self.assertRaisesRegex(JournalError, 'requires recovery'):
            self.forecast()
        self.assertEqual(before, self.inventory())

    async def test_existing_replay_orphan_is_not_ignored(self):
        await self.collect()
        (self.root/'retirement-replay-orphan').mkdir()
        before = self.inventory()
        with self.assertRaisesRegex(JournalError, 'requires recovery'):
            self.forecast()
        self.assertEqual(before, self.inventory())

    async def test_transient_space_checked_before_any_preparation(self):
        await self.collect(large=True)
        before = self.inventory()
        original = self.budget.check
        def check(growth):
            if growth:
                raise JournalError('simulated insufficient peak space')
            original(growth)
        with patch.object(self.budget, 'check', check):
            with self.assertRaisesRegex(JournalError, 'insufficient peak'):
                self.prepare()
        self.assertEqual(before, self.inventory())

    async def test_unexpected_preparation_bytes_refuse_anchor_and_keep_raw(self):
        await self.collect(large=True)
        before = self.raw_files()
        def hook(stage):
            if stage == 'before_plan':
                (self.root/'unexpected-evidence').write_bytes(b'preserve me')
        with self.assertRaisesRegex(JournalError, 'footprint differs'):
            self.prepare(hook=hook)
        self.assertEqual(before, self.raw_files())
        self.assertEqual((self.root/'unexpected-evidence').read_bytes(), b'preserve me')

    async def test_prepared_plan_drift_refuses_anchor_and_keeps_raw(self):
        await self.collect(large=True)
        before = self.raw_files()
        original = admission.forecast_retirement
        def drift(*args, **kw):
            return original(*args, **kw) | dict(normalized_plan_sha256='f'*64)
        with patch.object(admission, 'forecast_retirement', drift):
            with self.assertRaisesRegex(JournalError, 'plan differs'):
                self.prepare()
        self.assertEqual(before, self.raw_files())

    async def test_threshold_must_be_positive_integer(self):
        await self.collect()
        for value in (0, -1, True, 1.5, '1'):
            with self.subTest(value=value):
                with self.assertRaises((JournalError, ValueError)):
                    self.forecast(minimum_net_savings_bytes=value)
