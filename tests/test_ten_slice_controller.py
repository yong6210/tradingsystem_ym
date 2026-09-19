import unittest
from app.research.diagnostics.ten_slice_controller import TenSliceController, action


class TenSliceTests(unittest.TestCase):
    def loaded(self):
        c = TenSliceController(1000, 3, .001)
        for p in [100000, 99000, 98000, 97000, 96000]:
            c.record_add(c.proposed_add(p), p)
        return c

    def test_whole_account_tenth_and_leverage(self):
        c = TenSliceController(1000, 3)
        self.assertEqual(c.unit_margin, 100)
        self.assertEqual(c.proposed_add(100000), .003)

    def test_fifth_locks_reserve(self):
        c = self.loaded()
        self.assertEqual(c.units, 5)
        self.assertEqual(c.proposed_add(95000), 0)
        with self.assertRaises(ValueError): c.record_add(.003, 95000)

    def test_five_to_three_then_two_adds(self):
        c = self.loaded()
        q = c.reduction(3, 'newest')
        c.record_reduction(q, 'newest')
        self.assertAlmostEqual(c.units, 3)
        self.assertFalse(c.defensive)
        c.record_add(c.proposed_add(95000), 95000)
        c.record_add(c.proposed_add(94000), 94000)
        self.assertTrue(c.defensive)
        self.assertAlmostEqual(c.units, 5)

    def test_proportional_cut_to_two(self):
        c = self.loaded()
        c.record_reduction(c.reduction(2, 'proportional'), 'proportional')
        self.assertAlmostEqual(c.units, 2)
        self.assertAlmostEqual(c.qty, .006)
        self.assertFalse(c.defensive)

    def test_adverse_cut_precedes_bounce(self):
        c = self.loaded()
        self.assertEqual(action(c, 1, 95000, 400, True, False, True, False, 98000, .001)[0], 'cut')

    def test_short_symmetry(self):
        c = self.loaded()
        self.assertEqual(action(c, -1, 97000, 400, True, False, False, True, 98000, .001)[0], 'cut')
        self.assertEqual(action(c, -1, 95000, 400, True, False, False, True, 98000, .001)[0], 'rebound_trim')

    def test_no_blind_averaging(self):
        c = TenSliceController(1000, 3)
        c.record_add(.003, 100000)
        self.assertEqual(action(c, 1, 98000, 400, False, True, True, False, 100000, .001)[0], 'wait')
        self.assertEqual(action(c, 1, 98000, 400, True, False, True, False, 100000, .001)[0], 'add')

    def test_rounding_never_exceeds_budget(self):
        c = TenSliceController(1000, 3)
        q = c.proposed_add(113000)
        self.assertLessEqual(q * 113000 / 3, 100)
        c.record_add(q, 113000)
        self.assertEqual(c.units, 1)

if __name__ == '__main__': unittest.main()
