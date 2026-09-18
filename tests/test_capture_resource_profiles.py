import unittest

from app.research.data.continuous_generation_capture import validate_plan
from app.research.foundation.capture_resource_contract import NS
from scripts.verify_capture_resources import verify_recovered_audit


class ResourceProfileTests(unittest.TestCase):
    def test_saved_arrays_and_replayed_interval_tuples_are_equal(self):
        verify_recovered_audit(dict(status='COMPLETE', audit={'exclusions': [(1, 2)]}),
                               {'exclusions': [[1, 2]]})

    def test_changed_interval_is_not_a_serialization_difference(self):
        with self.assertRaises(RuntimeError):
            verify_recovered_audit(dict(status='COMPLETE', audit={'exclusions': [(1, 3)]}),
                                   {'exclusions': [[1, 2]]})

    def test_bool_and_integer_are_not_equal(self):
        with self.assertRaises(RuntimeError):
            verify_recovered_audit(dict(status='COMPLETE', audit={'count': True}), {'count': 1})

    def test_matching_audit_does_not_certify_incomplete_recovery(self):
        with self.assertRaises(RuntimeError):
            verify_recovered_audit(dict(status='INTERRUPTED_PREFIX_PRESERVED', audit={}), {})

    def test_documented_protocol_boundaries_match_selected_runtime(self):
        validate_plan(120*NS, 8*NS, NS//2)
        for duration, rotation in ((120*NS+1, 8*NS), (17*NS, NS), (86400*NS, 8*NS)):
            with self.subTest(duration=duration, rotation=rotation):
                with self.assertRaises(RuntimeError): validate_plan(duration, rotation, NS//2)


if __name__ == '__main__':
    unittest.main()
