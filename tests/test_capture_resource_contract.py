import copy
import unittest

from app.research.foundation.capture_resource_contract import (
    ENVELOPE_FIELDS, LIMIT_FIELDS, GIB, NS, review_resources,
)


class ResourceContractTests(unittest.TestCase):
    def setUp(self):
        self.request = dict(duration_ns=9*NS, rotation_ns=8*NS, seal_ns=NS//2, transport='SYNTHETIC')
        self.limits = dict.fromkeys(LIMIT_FIELDS.split(), 10**12)
        self.limits.update(capture_bytes=64*GIB, free_reserve_bytes=16*GIB)
        self.envelope = dict.fromkeys(ENVELOPE_FIELDS.split(), 1)
        self.envelope['basis'] = 'ASSUMPTION'

    def review(self, **kwargs):
        return review_resources(self.request, self.limits, self.envelope, free_bytes=100*GIB, **kwargs)

    def test_partial_generation_uses_ceiling_and_two_extra_units(self):
        result = self.review()
        self.assertEqual(result['generations_required'], 2)
        self.assertEqual(result['conservative_units_required'], 22)
        self.assertEqual(result['peak_units_per_generation'], 18)

    def test_exact_boundary_has_no_empty_generation(self):
        self.request['duration_ns'] = 8*NS
        result = self.review()
        self.assertEqual(result['generations_required'], 1)
        self.assertEqual(result['conservative_units_required'], 18)

    def test_one_nanosecond_tail_counts_as_generation(self):
        self.request['duration_ns'] = 8*NS+1
        self.assertEqual(self.review()['conservative_units_required'], 21)

    def test_large_disk_cannot_override_protocol(self):
        self.request.update(duration_ns=86400*NS, transport='PUBLIC')
        result = self.review()
        self.assertEqual(result['generations_required'], 10800)
        self.assertEqual(result['conservative_units_required'], 194400)
        for reason in ('DURATION_EXCEEDS_120_SECONDS', 'GENERATIONS_EXCEED_16',
                       'PUBLIC_GENERATION_TRANSPORT_NOT_INTEGRATED'):
            self.assertIn(reason, result['blockers'])
        self.assertFalse(result['execution_authorized'])

    def test_raw_archive_seed_metadata_transients_and_failures_all_charged(self):
        # 1 fixed + 2 generations * 4 components + 22 units + 2 transient/tail.
        result = self.review(existing_capture_bytes=100)
        self.assertEqual(result['projections']['capture_peak_bytes'], 33)
        self.assertEqual(result['projections']['logical_peak_bytes'], 133)
        self.assertFalse(result['early_raw_retirement_credit'])

    def test_validation_copy_is_disk_cost_not_capture_cap_cost(self):
        self.envelope['validation_copy_bytes'] = 400
        result = self.review(existing_capture_bytes=100)
        self.assertEqual(result['projections']['disk_growth_bytes'], 433)
        self.assertEqual(result['projections']['logical_peak_bytes'], 133)

    def test_reconcile_counts_both_dictionaries(self):
        p = self.review()['projections']
        self.assertEqual(p['capture_files'], 26)
        self.assertEqual(p['inventory_reconcile_peak_bytes'], 54)
        self.assertEqual(p['process_tree_rss_bytes'], 56)
        self.assertEqual(p['cold_elapsed_ns'], 3)

    def test_every_unknown_envelope_field_is_reported(self):
        for field in ENVELOPE_FIELDS.split():
            with self.subTest(field=field):
                e = dict(self.envelope, **{field: None})
                result = review_resources(self.request, self.limits, e, free_bytes=100*GIB)
                self.assertIn(field, result['missing_envelope'])
                self.assertFalse(result['execution_authorized'])

    def test_unknown_bytes_are_not_zero_or_fit(self):
        self.envelope['raw_bytes_per_generation'] = None
        result = self.review()
        self.assertIsNone(result['projections']['capture_peak_bytes'])
        self.assertIsNone(result['conditional_fits']['logical_peak_bytes'])

    def test_unknown_limit_is_not_infinite(self):
        self.limits['capture_files'] = None
        result = self.review()
        self.assertIn('capture_files', result['missing_limits'])
        self.assertIsNone(result['conditional_fits']['capture_files'])

    def test_each_resource_limit_and_exact_equality(self):
        mapping = dict(logical_peak_bytes='capture_bytes', capture_files='capture_files',
            inventory_reconcile_peak_bytes='inventory_bytes', process_tree_rss_bytes='process_tree_rss_bytes',
            cold_records='cold_records', cold_elapsed_ns='cold_elapsed_ns', cold_rss_bytes='cold_rss_bytes')
        for field, key in mapping.items():
            if key == 'capture_bytes':
                continue  # Fixed policy cap tested via existing usage below.
            with self.subTest(field=field):
                value = self.review()['projections'][field]
                self.limits[key] = value
                self.assertTrue(self.review()['conditional_fits'][field])
                self.limits[key] = value-1
                self.assertIn('RESOURCE_LIMIT_EXCEEDED:'+field, self.review()['blockers'])
                self.limits[key] = 10**12

    def test_existing_logical_usage_and_disk_reserve_are_independent(self):
        self.assertFalse(self.review(existing_capture_bytes=64*GIB)['conditional_fits']['logical_peak_bytes'])
        args = (self.request, self.limits, self.envelope)
        for free, expected in ((16*GIB+65536+34, True), (16*GIB+65536+33, False)):
            self.assertIs(review_resources(*args, free_bytes=free)['conditional_fits']['disk_growth_bytes'], expected)

    def test_pending_at_cap_is_not_headroom(self):
        self.envelope.update(peak_pending_generations=2, max_parent_phase_ns=NS//2+1)
        reasons = self.review()['blockers']
        self.assertIn('NO_PENDING_GENERATION_HEADROOM', reasons)
        self.assertIn('PARENT_PHASE_EXCEEDS_500_MS', reasons)

    def test_even_complete_observations_never_authorize(self):
        for basis in ('UNQUALIFIED', 'OBSERVED_SAMPLE', 'ASSUMPTION'):
            self.envelope['basis'] = basis
            r = self.review()
            self.assertFalse(r['execution_authorized'])
            self.assertFalse(r['full_day_ready'])
            self.assertIn('INPUT_AND_RESOURCE_ENVELOPE_NOT_ENFORCED_OR_QUALIFIED', r['blockers'])

    def test_forged_qualification_and_relaxed_operating_limits_rejected(self):
        self.envelope['basis'] = 'QUALIFIED'
        with self.assertRaises(ValueError): self.review()
        self.envelope['basis'] = 'ASSUMPTION'
        self.limits['free_reserve_bytes'] = 0
        with self.assertRaises(ValueError): self.review()

    def test_bad_types_extra_fields_and_negative_values(self):
        for target, key in ((self.request, 'duration_ns'), (self.limits, 'capture_files'),
                            (self.envelope, 'raw_bytes_per_generation')):
            original = target[key]
            for invalid in (True, 1.0, -1, '1'):
                target[key] = invalid
                with self.assertRaises(ValueError): self.review()
            target[key] = original
        self.envelope['unknown'] = 0
        with self.assertRaises(ValueError): self.review()

    def test_input_dictionaries_unchanged(self):
        before = copy.deepcopy((self.request, self.limits, self.envelope))
        self.review()
        self.assertEqual(before, (self.request, self.limits, self.envelope))


if __name__ == '__main__':
    unittest.main()
