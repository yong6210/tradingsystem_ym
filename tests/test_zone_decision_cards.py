import unittest
import numpy as np
from scripts.build_zone_decision_cards import price_context, profile_context, MINUTE, SLOT


class DecisionCardContextTests(unittest.TestCase):
    def test_price_future_changes_do_not_change_context(self):
        rows = [dict(end_ms=i*MINUTE, close=100+i, high=102+i, low=99+i, volume=2)
                for i in range(10)]
        expected = price_context(rows, 5*MINUTE, (3,))
        self.assertEqual(expected['3']['change'], 3)
        self.assertEqual(expected['3']['low'], 102)
        self.assertEqual(expected['3']['volume_btc'], 6)
        altered = [dict(r, close=-999, high=99999) if r['end_ms']>5*MINUTE else r for r in rows]
        self.assertEqual(expected, price_context(altered, 5*MINUTE, (3,)))
        self.assertEqual(expected, price_context(rows[:6], 5*MINUTE, (3,)))

    def test_missing_minute_rejected(self):
        rows = [dict(end_ms=i*MINUTE, close=100, high=101, low=99, volume=1) for i in (0, 1, 3)]
        with self.assertRaises(ValueError):
            price_context(rows, 3*MINUTE, (3,))

    def test_profile_delay_and_future_independence(self):
        hist = np.array([[1., 3., 6.]]*8)
        t = 4*SLOT + MINUTE
        expected = profile_context(hist, 0, 0, t, 50, 100, (4,))
        self.assertEqual(expected['windows_hours']['1']['share_pct'], 30)
        self.assertEqual(expected['cutoff_exclusive_ms'], 4*SLOT)
        hist[4:] = 9999
        self.assertEqual(expected, profile_context(hist, 0, 0, t, 50, 100, (4,)))
        self.assertEqual(expected, profile_context(hist[:4], 0, 0, t, 50, 100, (4,)))
        with self.assertRaises(ValueError):
            profile_context(hist, 0, 0, t-1, 50, 100, (4,))

    def test_missing_profile_and_unaligned_zone_rejected(self):
        hist = np.ones((4, 3))
        with self.assertRaises(ValueError):
            profile_context(hist, 0, 0, 5*SLOT+MINUTE, 50, 100, (4,))
        with self.assertRaises(ValueError):
            profile_context(hist, 0, 0, 4*SLOT+MINUTE, 51, 100, (4,))


if __name__ == '__main__':
    unittest.main()
