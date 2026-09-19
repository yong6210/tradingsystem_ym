import math
import unittest
from app.research.diagnostics.forward_sample import rolling_counts, planning, count_summary


class ForwardSampleTests(unittest.TestCase):
    def test_rolling_includes_both_calendar_edges(self):
        self.assertEqual(rolling_counts([1,0,1,0,0],3),[2,1,1])
        self.assertEqual(rolling_counts([0,0,0],3),[0])
        self.assertEqual(count_summary([0,1,3])['zero_windows'],1)

    def test_variance_uses_active_events_and_n_minus_one(self):
        r=planning([1,3],20,90)
        self.assertEqual(r['reference_count'],9)
        self.assertEqual(r['historical_mean_bps'],2)
        self.assertAlmostEqual(r['historical_sample_sd_bps'],math.sqrt(2))
        self.assertAlmostEqual(r['iid_planning_standard_error_bps'],math.sqrt(2)/3)

    def test_zero_signals_are_not_zero_precision(self):
        r=planning([],100)
        self.assertEqual(r['reference_count'],0)
        self.assertIsNone(r['historical_mean_bps'])
        self.assertIsNone(r['iid_planning_standard_error_bps'])
        self.assertIsNone(planning([2],100)['historical_sample_sd_bps'])

    def test_half_up_count_is_planning_only(self):
        r=planning([1,2],120)
        self.assertEqual(r['reference_count'],1.5)
        self.assertEqual(r['rounded_reference_count'],2)
        self.assertIsNone(r['future_confidence_interval'])
        self.assertIsNone(r['statistical_power'])

    def test_invalid_inputs_rejected(self):
        for xs,days in [([0,2],1),([0,1],3),([0,1],0)]:
            with self.assertRaises(ValueError):rolling_counts(xs,days)
        with self.assertRaises(ValueError):planning([float('nan')],10)
        with self.assertRaises(ValueError):planning([1,2],1)


if __name__=='__main__':unittest.main()
