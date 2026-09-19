import unittest

from app.research.recovery.directional_cycling import DirectionalCycling
from app.research.recovery.models import dec


class CyclingTests(unittest.TestCase):
    def model(self, side=-1, step='0.001'):
        model = DirectionalCycling(step)
        model.set_direction(side, timeframe='4h', observed_ms=0, reason='explicit scenario assessment')
        return model

    def test_video_two_cycles_and_same_price_baseline(self):
        m = self.model()
        m.increase('base', -1, 5, 100000)
        m.increase('add', -1, 5, 102000)
        r = m.begin_retracement('r1')
        self.assertEqual((r.basis, r.target), (10, 5))
        m.reduce('reduce', 5, 101200, event_id='r1')
        self.assertEqual((m.quantity, m.average, m.realized_gross), (5, 101000, -1000))
        self.assertEqual(m.total_pnl(101200), -2000)
        self.assertEqual(m.total_pnl(101200) - 5 * (100000 - 101200), 4000)
        self.assertEqual(m.break_evens(), dict(position=101000, campaign=100800))
        m.increase('add2', -1, 5, 103000)
        m.begin_retracement('r2')
        m.reduce('reduce2', 5, 102200, event_id='r2')
        self.assertEqual((m.quantity, m.average, m.realized_gross), (5, 102000, -2000))
        self.assertEqual(m.total_pnl(102200), -3000)
        self.assertEqual(m.break_evens()['campaign'], 101600)

    def test_long_symmetry_and_no_automatic_exit_on_adverse_mark(self):
        m = self.model(1)
        m.increase('base', 1, 5, 100000)
        self.assertEqual(m.total_pnl(97000), -15000)
        self.assertEqual(m.quantity, 5)
        m.increase('add', 1, 5, 98000)
        m.begin_retracement('r')
        m.reduce('reduce', 5, 98800, event_id='r')
        self.assertEqual(m.total_pnl(98800), -2000)
        self.assertEqual(m.break_evens()['campaign'], 99200)

    def test_no_retracement_exposes_larger_loss(self):
        m = self.model()
        m.increase('base', -1, 5, 100000)
        m.increase('add', -1, 5, 102000)
        self.assertEqual(m.total_pnl(103000), -20000)
        self.assertEqual(m.total_pnl(103000) - 5 * (100000 - 103000), -5000)
        self.assertEqual(m.quantity, 10)

    def test_flat_does_not_erase_direction_or_accumulated_loss(self):
        m = self.model()
        m.increase('base', -1, 5, 100000)
        m.begin_retracement('all', 1)
        m.reduce('flat', 5, 101000, event_id='all')
        m.increase('reentry', -1, 5, 102000)
        self.assertEqual((m.direction, m.average, m.realized_gross), (-1, 102000, -5000))
        self.assertEqual(m.break_evens()['campaign'], 101000)

    def test_partial_fill_retry_preserves_original_half(self):
        m = self.model()
        m.increase('base', -1, 10, 101000)
        r = m.begin_retracement('r')
        m.reduce('part', 2, 101200, event_id='r')
        self.assertIs(m.begin_retracement('r'), r)
        self.assertEqual((r.basis, r.target, r.remaining), (10, 5, 3))
        self.assertFalse(m.reduce('part', 2, 101200, event_id='r'))
        with self.assertRaises(ValueError):
            m.increase('early', -1, 1, 102000)
        with self.assertRaises(ValueError):
            m.reduce('too-much', 4, 101200, event_id='r')
        m.reduce('rest', 3, 101200, event_id='r')
        m.increase('next', -1, 5, 103000)
        self.assertEqual(m.begin_retracement('r').remaining, 0)
        self.assertEqual(m.quantity, 10)

    def test_round_half_up_and_reject_less_than_half(self):
        m = self.model(step='1')
        m.increase('base', -1, 5, 100000)
        with self.assertRaises(ValueError):
            m.begin_retracement('bad', '.49')
        self.assertEqual(m.begin_retracement('r').target, 3)

    def test_direction_separate_from_position_and_flatten_before_reverse(self):
        m = self.model()
        m.increase('base', -1, 5, 100000)
        with self.assertRaises(ValueError):
            m.set_direction(1, timeframe='1m', observed_ms=1, reason='bounce')
        with self.assertRaises(ValueError):
            m.increase('counter', 1, 1, 101000)
        m.set_direction(1, timeframe='4h', observed_ms=1, reason='explicit reversal')
        with self.assertRaises(ValueError):
            m.increase('before-flat', 1, 1, 101000)
        m.reduce('flat', 5, 101000)
        self.assertEqual(m.direction, 1)
        self.assertEqual(m.break_evens(), dict(position=None, campaign=None))
        m.increase('long', 1, 5, 101000)
        self.assertEqual(m.position_side, 1)

    def test_costs_funding_and_break_even_reconcile(self):
        for side in (-1, 1):
            with self.subTest(side=side):
                m = self.model(side)
                m.increase('base', side, 10, 100000, 100)
                m.funding('funding', -10)
                self.assertFalse(m.funding('funding', -10))
                m.begin_retracement('r')
                m.reduce('half', 5, 100000, 50, event_id='r')
                self.assertEqual(m.total_pnl(100000), -140)
                self.assertEqual(m.position_costs, 45)
                price = m.break_evens('.001')['campaign']
                self.assertLess(abs(m.total_pnl(price) - m.quantity * price * dec('.001')), dec('1e-20'))

    def test_duplicate_conflicts_leave_state_unchanged(self):
        m = self.model()
        m.increase('base', -1, 5, 100000)
        with self.assertRaises(ValueError):
            m.increase('base', -1, 4, 100000)
        with self.assertRaises(ValueError):
            m.set_direction(1, timeframe='4h', observed_ms=0, reason='conflict')
        self.assertEqual((m.quantity, m.direction), (5, -1))


if __name__ == '__main__':
    unittest.main()
