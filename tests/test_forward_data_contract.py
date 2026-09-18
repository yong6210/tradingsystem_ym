from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest

from app.research.foundation.forward_data_contract import (
    ContractError, FAULTS, NS, REQUIREMENTS, calendar_quality, load_contract,
    merge_intervals, review_collection, validate_policy,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 17, 15, tzinfo=timezone.utc)
DAY = 86400*NS


class ForwardDataContractTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_contract(ROOT/'configs/research/forward_data_policy_v1.json')
        self.intervals = {name: [[0, DAY]] for name in REQUIREMENTS}
        self.faults = dict.fromkeys(FAULTS, 0)

    def evaluate(self, **kwargs):
        return calendar_quality(self.policy, **(dict(start_ns=0, end_ns=DAY,
                 intervals=self.intervals, integrity_faults=self.faults) | kwargs))

    def test_actual_contract_is_not_ready_or_strategy_approval(self):
        result = review_collection(self.policy, ROOT, now=NOW)
        self.assertEqual(result['status'], 'COLLECTION_REGISTRATION_BLOCKED')
        self.assertIn('START_NOT_FIXED', result['blockers'])
        self.assertIn('UNPINNED_CRASH_RECOVERY_EVIDENCE', result['blockers'])
        self.assertFalse(result['profitability_evaluation_ready'])
        self.assertIsNone(self.policy['execution_assumptions']['account_fee_evidence'])

    def test_unknown_fields_boolean_nan_and_silent_policy_changes_reject(self):
        for section, key, value in [('quality', 'l2_max_age_ms', True),
                                    ('quality', 'min_joint_coverage_ppm', float('nan')),
                                    ('quality', 'backfill_repairs_decision_history', True),
                                    ('storage', 'publish_requires_durable_prefix', False),
                                    ('execution_assumptions', 'touch_is_fill', True),
                                    ('execution_assumptions', 'unknown_cost_is_zero', True)]:
            policy = deepcopy(self.policy)
            policy[section][key] = value
            with self.subTest(key=key), self.assertRaises(ContractError):
                validate_policy(policy)
        self.policy['unexpected'] = 1
        with self.assertRaises(ContractError):
            validate_policy(self.policy)

    def test_changed_costs_are_not_silently_reclassified_as_account_rates(self):
        for key, value in [('maker', True), ('taker', 0), ('extra_adverse_market_slippage', -1)]:
            policy = deepcopy(self.policy)
            policy['execution_assumptions']['fee_bps_per_fill']['user_zero_maker'][key] = value
            with self.assertRaises(ContractError):
                validate_policy(policy)

    def test_short_good_capture_does_not_pass_one_day_pilot(self):
        result = self.evaluate(end_ns=17*NS)
        self.assertEqual(result['joint_coverage_ppm'], 1_000_000)
        self.assertIn('NOT_REGISTERED_PILOT_DURATION', result['reasons'])

    def test_empty_tail_remains_in_calendar_denominator(self):
        self.intervals = {name: [[0, 3600*NS]] for name in REQUIREMENTS}
        result = self.evaluate()
        self.assertEqual(result['calendar_ns'], DAY)
        self.assertEqual(result['joint_eligible_ns'], 3600*NS)
        self.assertEqual(len(result['hourly']), 24)
        self.assertEqual(result['hourly'][-1]['coverage_ppm'], 0)
        self.assertEqual(result['longest_unavailable_ns'], 23*3600*NS)

    def test_overlap_duplicate_observations_do_not_inflate_time(self):
        self.intervals['l2'] = [[0, DAY], [0, DAY], [1, 2], [3, DAY+NS]]
        result = self.evaluate()
        self.assertEqual(result['joint_eligible_ns'], DAY)
        self.assertEqual(result['status'], 'QUALITY_INPUTS_PASS_ONLY')
        self.assertFalse(result['strategy_adoption'])

    def test_each_channel_healthy_in_different_windows_has_no_joint_coverage(self):
        self.intervals['l2'] = [[0, DAY//2]]
        self.intervals['mark'] = [[DAY//2, DAY]]
        self.assertEqual(self.evaluate()['joint_eligible_ns'], 0)

    def test_missing_channel_is_not_replaced_by_depth(self):
        self.intervals['market_connection'] = []
        result = self.evaluate()
        self.assertIn('MISSING_MARKET_CONNECTION', result['reasons'])
        self.assertEqual(result['individual_eligible_ns']['l2'], DAY)
        self.assertEqual(result['joint_eligible_ns'], 0)

    def test_daily_average_cannot_hide_bad_hour(self):
        # A 40-second hole passes 99.5% day coverage but fails the 99% hour floor.
        self.intervals['mark'] = [[40*NS, DAY]]
        result = self.evaluate()
        self.assertNotIn('JOINT_COVERAGE_BELOW_FLOOR', result['reasons'])
        self.assertIn('HOURLY_COVERAGE_BELOW_FLOOR', result['reasons'])

    def test_gap_limit_boundary_exact_and_one_nanosecond_over(self):
        self.intervals['l2'] = [[10*NS, DAY]]
        self.assertNotIn('UNAVAILABLE_GAP_EXCEEDED', self.evaluate()['reasons'])
        self.intervals['l2'] = [[10*NS+1, DAY]]
        self.assertIn('UNAVAILABLE_GAP_EXCEEDED', self.evaluate()['reasons'])

    def test_single_integrity_fault_cannot_be_diluted_by_volume(self):
        for fault in FAULTS:
            faults = dict.fromkeys(FAULTS, 0) | {fault: 1}
            result = self.evaluate(integrity_faults=faults)
            self.assertEqual(result['joint_coverage_ppm'], 1_000_000)
            self.assertIn('INTEGRITY_'+fault.upper(), result['reasons'])

    def test_bad_intervals_counts_and_windows_reject(self):
        for pair in [[-1, 3], [True, 3], [3, 3], [4, 3], [0, float('inf')]]:
            self.intervals['l2'] = [pair]
            with self.assertRaises(ContractError):
                self.evaluate()
        self.intervals['l2'] = [[0, DAY]]
        for kwargs in [dict(end_ns=0), dict(end_ns=DAY+1), dict(start_ns=True),
                       dict(integrity_faults=self.faults | dict(raw_loss=True))]:
            with self.assertRaises(ContractError):
                self.evaluate(**kwargs)

    def test_independent_discrete_coverage_enumeration(self):
        # Small clock units let exhaustive set intersection check interval math.
        self.intervals = {name: [[0, 100]] for name in REQUIREMENTS}
        self.intervals['l2'] = [[5, 25], [15, 40], [70, 99]]
        self.intervals['clock'] = [[0, 10], [20, 80]]
        expected = set(range(100))
        for spans in self.intervals.values():
            observed = set()
            for left, right in spans:
                observed.update(range(left, right))
            expected &= observed
        result = self.evaluate(end_ns=100)
        self.assertEqual(result['joint_eligible_ns'], len(expected))
        self.assertEqual(merge_intervals([[5, 10], [10, 20]], 0, 100), [(5, 20)])

    def test_missing_requirement_or_undeclared_requirement_is_rejected(self):
        del self.intervals['clock']
        with self.assertRaises(ContractError):
            self.evaluate()

    def test_past_start_or_future_registration_blocks(self):
        self.policy['binding'].update(start_utc='2026-09-17T14:00:00Z',
                                      registered_at_utc='2026-09-18T00:00:00Z')
        result = review_collection(self.policy, ROOT, now=NOW)
        self.assertIn('START_NOT_FUTURE_UNSEEN', result['blockers'])
        self.assertIn('INVALID_REGISTRATION_TIME', result['blockers'])

    def test_hash_bound_structure_ready_is_not_runtime_or_profitability_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/'fixture.txt'
            path.write_text('synthetic structural evidence only')
            binding = self.policy['binding']
            binding.update(status='REGISTERED', start_utc='2026-09-18T00:00:00Z',
                           registered_at_utc='2026-09-17T14:30:00Z',
                           source_hashes={path.name: hashlib.sha256(path.read_bytes()).hexdigest()})
            binding['roles'] = dict.fromkeys(binding['roles'], path.name)
            result = review_collection(self.policy, root, now=NOW)
            self.assertEqual(result['status'], 'COLLECTION_STRUCTURE_READY')
            self.assertEqual(result['end_utc'], '2026-09-19T00:00:00+00:00')
            self.assertFalse(result['profitability_evaluation_ready'])
            path.write_text('changed')
            self.assertIn('SOURCE_MISMATCH:fixture.txt', review_collection(self.policy, root, now=NOW)['blockers'])

    def test_outside_source_and_unzoned_time_reject(self):
        self.policy['binding']['source_hashes'] = {'../outside': '0'*64}
        with self.assertRaises(ContractError):
            review_collection(self.policy, ROOT, now=NOW)
        self.policy['binding']['source_hashes'] = {}
        self.policy['binding']['start_utc'] = '2026-09-18T00:00:00'
        with self.assertRaises(ContractError):
            review_collection(self.policy, ROOT, now=NOW)


if __name__ == '__main__':
    unittest.main()
