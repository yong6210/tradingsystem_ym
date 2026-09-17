"""Counterexamples for design integrity, independent of research dependencies."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.research.foundation.validation import DesignError, load_design, parse_design, validate_references

ROOT = Path(__file__).resolve().parents[1]


class ResearchDesignTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads((ROOT / 'configs/research/e001_entry_information.json').read_text())

    def test_actual_design_and_pinned_references_pass(self):
        design = load_design(ROOT / 'configs/research/e001_entry_information.json', ROOT)
        self.assertEqual(design.primary_horizon_minutes, 60)
        self.assertEqual(len(design.windows), 4)
        self.assertEqual(design.status, 'design')

    def test_misspelled_and_missing_keys_fail(self):
        for key in ('top', 'matching'):
            with self.subTest(key=key):
                raw = copy.deepcopy(self.raw)
                destination = raw if key == 'top' else raw['matching']
                destination['typo'] = 1
                with self.assertRaises(DesignError):
                    parse_design(raw)
        raw = copy.deepcopy(self.raw)
        del raw['question']
        with self.assertRaises(DesignError):
            parse_design(raw)

    def test_boolean_is_not_accepted_as_minutes(self):
        self.raw['decision_delay_minutes'] = True
        with self.assertRaises(DesignError):
            parse_design(self.raw)

    def test_primary_must_be_measured_and_horizons_unique(self):
        for key, value in [('primary_horizon_minutes', 30), ('horizons_minutes', [15, 60, 60])]:
            with self.subTest(key=key):
                raw = copy.deepcopy(self.raw)
                raw[key] = value
                with self.assertRaises(DesignError):
                    parse_design(raw)

    def test_ambiguous_timezone_and_overlapping_windows_fail(self):
        for start in ('2023-04-01', '2023-04-01T00:00:00+09:00'):
            with self.subTest(start=start):
                raw = copy.deepcopy(self.raw)
                raw['windows'][0]['start'] = start
                with self.assertRaises(DesignError):
                    parse_design(raw)
        self.raw['windows'][1]['start'] = '2023-12-01T00:00:00Z'
        with self.assertRaises(DesignError):
            parse_design(self.raw)

    def test_nonfinite_or_wrong_unit_costs_fail(self):
        for value in (float('nan'), float('inf'), -1, True, 10000):
            with self.subTest(value=value):
                raw = copy.deepcopy(self.raw)
                raw['costs']['slippage_bps'] = value
                with self.assertRaises(DesignError):
                    parse_design(raw)

    def test_old_data_cannot_be_relabelled_as_fresh(self):
        self.raw['evidence_kind'] = 'virgin_holdout'
        with self.assertRaises(DesignError):
            parse_design(self.raw)

    def test_design_checker_cannot_claim_registration(self):
        self.raw['status'] = 'registered'
        with self.assertRaises(DesignError):
            parse_design(self.raw)

    def test_changed_source_is_detected(self):
        self.raw['references'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(DesignError, 'changed reference'):
            validate_references(parse_design(self.raw), ROOT)

    def test_reference_cannot_escape_project(self):
        self.raw['references'][0]['path'] = '../outside.py'
        with self.assertRaisesRegex(DesignError, 'inside project'):
            validate_references(parse_design(self.raw), ROOT)

    def test_coverage_and_warmup_are_enforced(self):
        for boundary in ('2023-02-01T00:00:00Z', '2027-01-01T00:00:00Z'):
            raw = copy.deepcopy(self.raw)
            if boundary.startswith('2023'):
                raw['windows'][0]['start'] = boundary
            else:
                raw['windows'][-1]['end'] = boundary
            with self.subTest(boundary=boundary), self.assertRaisesRegex(DesignError, 'coverage'):
                validate_references(parse_design(raw), ROOT)

    def test_delay_cannot_exhaust_the_control_history(self):
        self.raw['decision_delay_minutes'] = 28 * 1440
        with self.assertRaisesRegex(DesignError, 'decision delay'):
            parse_design(self.raw)

    def test_duplicate_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'duplicate.json'
            path.write_text('{"status":"design","status":"registered"}')
            with self.assertRaisesRegex(DesignError, 'duplicate JSON key'):
                load_design(path, ROOT)

    def test_failed_quality_manifest_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({'status': 'FAIL', 'errors': {'gap': 1}}))
            reference = root / 'source.py'
            reference.write_text('# fixture\n')
            raw = copy.deepcopy(self.raw)
            raw['dataset'] = {'path': 'manifest.json', 'sha256': hashlib.sha256(manifest.read_bytes()).hexdigest()}
            raw['references'] = [{'path': 'source.py', 'sha256': hashlib.sha256(reference.read_bytes()).hexdigest()}]
            with self.assertRaisesRegex(DesignError, 'did not pass'):
                validate_references(parse_design(raw), root)


if __name__ == '__main__':
    unittest.main()
