from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from app.research.foundation.acceptance_contract import ContractError, load_contract, review_contract

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 17, tzinfo=timezone.utc)


class AcceptanceContractTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_contract(ROOT / 'configs/research/forward_acceptance_policy_v1.json')

    def review(self, policy=None):
        return review_contract(policy or self.policy, ROOT, now=NOW)

    def test_real_proposal_blocks_registration_not_strategy_failure(self):
        result = self.review()
        self.assertEqual(result['status'], 'REGISTRATION_BLOCKED')
        self.assertIn('OPERATING_COST_NOT_SPECIFIED', result['blockers'])
        self.assertIn('POLICY_NOT_FROZEN', result['blockers'])
        self.assertFalse(result['strategy_adoption'])
        self.assertEqual(result['per_hypothesis_alpha'], .025)

    def test_missing_minimum_and_precision_cannot_be_zero_defaults(self):
        for key in ('absolute_hurdle_pct', 'excess_hurdle_pp', 'ci_half_width_pp'):
            policy = deepcopy(self.policy)
            policy['economics'][key] = None
            self.assertIn('MISSING_' + key.upper(), self.review(policy)['blockers'])

    def test_ambiguous_types_unknown_keys_and_nonfinite_values_rejected(self):
        for value in (True, float('nan'), float('inf'), '5', -1, 0):
            policy = deepcopy(self.policy)
            policy['economics']['absolute_hurdle_pct'] = value
            with self.assertRaises(ContractError):
                self.review(policy)
        self.policy['unexpected'] = True
        with self.assertRaises(ContractError):
            self.review()

    def test_past_or_inspected_forward_window_blocks(self):
        self.policy['binding']['forward_start'] = '2026-08-01T00:00:00Z'
        blockers = self.review()['blockers']
        self.assertIn('FORWARD_START_NOT_IN_FUTURE', blockers)
        self.assertIn('PREVIOUSLY_INSPECTED_WINDOW', blockers)

    def test_timezone_and_window_granularity_rejected(self):
        for stamp in ('2026-10-01', '2026-10-01T00:00:00+09:00', '2026-10-01T12:00:00Z'):
            self.policy['binding']['forward_start'] = stamp
            with self.assertRaises(ContractError):
                self.review()

    def test_optional_stopping_and_silent_candidate_expansion_rejected(self):
        for field, value in (('stopping_rule', 'EXTEND_UNTIL_SIGNIFICANT'), ('candidates', 2), ('evaluation_days', 100)):
            policy = deepcopy(self.policy)
            policy['inference'][field] = value
            with self.assertRaises(ContractError):
                self.review(policy)

    def test_source_tampering_blocks_and_outside_path_rejected(self):
        self.policy['binding']['source_hashes'] = {'configs/research/forward_acceptance_policy_v1.json': '0' * 64}
        self.assertTrue(any(v.startswith('SOURCE_MISMATCH') for v in self.review()['blockers']))
        self.policy['binding']['source_hashes'] = {'../outside': '0' * 64}
        with self.assertRaises(ContractError):
            self.review()

    def test_structure_ready_is_never_adoption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'calibration.json'
            path.write_text('{"fixture": "structural check only"}')
            self.policy['status'] = 'FROZEN'
            self.policy['economics']['operating_cost_usdc_per_year'] = 60
            self.policy['binding'].update(candidate_id='synthetic-candidate', control_id='synthetic-control',
                                         forward_start='2026-10-01T00:00:00Z', calibration_report=path.name,
                                         source_hashes={path.name: hashlib.sha256(path.read_bytes()).hexdigest()})
            # Synthetic role bindings test structure only, not scientific sufficiency.
            self.policy['binding']['source_roles'] = {role: path.name for role in self.policy['binding']['source_roles']}
            result = review_contract(self.policy, root, now=NOW)
            self.assertEqual(result['status'], 'REGISTRATION_STRUCTURE_READY')
            self.assertFalse(result['strategy_adoption'])

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'duplicate.json'
            path.write_text('{"schema_version":1,"schema_version":1}')
            with self.assertRaises(ContractError):
                load_contract(path)
