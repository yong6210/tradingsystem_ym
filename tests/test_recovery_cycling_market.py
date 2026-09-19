import json
from pathlib import Path
import unittest
from unittest.mock import Mock

import test_recovery_cycling_orders as fixtures
from app.research.recovery.cycling_market_replay import CyclingMarketReplay
from app.research.recovery.models import Bar, dec


class MarketReplayTests(unittest.TestCase):
    def replay(self):
        config = json.loads((Path(__file__).resolve().parents[1]/'configs/research/cycling_market_candidate_v01.json').read_text())
        result = CyclingMarketReplay(config)
        result.orders.set_direction(-1, timeframe='4h', observed_ms=0, reason='fixture')
        result.last_volume = dec(100)
        return result

    def propose_increase(self, replay):
        location = fixtures.CyclingOrderTests().location(observed=60000)
        replay.signals.candidates = Mock(return_value=dict(action='increase', location=location))
        replay.propose(Bar(60000, 102000, 102001, 101999, 102000, 60000))

    def test_intent_does_not_fill_on_signal_close_and_uses_next_open(self):
        r = self.replay()
        self.propose_increase(r)
        self.assertEqual(r.model.quantity, 0)
        self.assertIsNotNone(r.orders.active)
        with self.assertRaises(ValueError):
            r.fill_open(102000, 59999)
        r.fill_open(102000, 60000)
        self.assertGreater(r.model.quantity, 0)
        fill = next(row for row in r.rows if row['kind'] == 'fill')
        self.assertLess(dec(fill['price']), 102000)
        self.assertEqual(dec(fill['fee']), dec(fill['quantity'])*dec(fill['price'])*r.costs.fee)

    def test_gap_past_limit_cancels_unfilled_entry_only(self):
        r = self.replay()
        r.model.increase('existing', -1, '.01', 100000)
        self.propose_increase(r)
        r.fill_open(101000, 60000)  # Short sale would be worse than submitted cap.
        self.assertIsNone(r.orders.active)
        self.assertEqual(r.model.quantity, dec('.01'))
        self.assertEqual(r.counts['entry_remainder_cancelled'], 1)

    def test_partial_entry_uses_prior_volume_and_releases_only_unfilled(self):
        r = self.replay()
        self.propose_increase(r)
        r.last_volume = dec('.1')
        r.fill_open(102000, 60000)
        self.assertEqual(r.model.quantity, dec('.001'))
        self.assertIsNone(r.orders.active)

    def test_same_cycle_cannot_repeatedly_halve_residual_position(self):
        r = self.replay()
        r.model.increase('base', -1, '.04', 100000)
        location = fixtures.CyclingOrderTests().location(side=1, observed=60000)
        r.signals.candidates = Mock(return_value=dict(action='retracement', location=location))
        bar = Bar(60000, 99000, 99001, 98999, 99000, 60000)
        r.propose(bar)
        self.assertEqual(r.orders.active.quantity, dec('.02'))
        r.fill_open(99000, 60000)
        r.propose(Bar(120000, 99000, 99001, 98999, 99000, 120000))
        self.assertIsNone(r.orders.active)
        self.assertEqual(r.model.quantity, dec('.02'))
        self.assertEqual(r.counts['same_cycle_reduction_suppressed'], 1)
        r.model.increase('new-add', -1, '.02', 100000)
        r.propose(Bar(180000, 99000, 99001, 98999, 99000, 180000))
        self.assertEqual(r.orders.active.quantity, dec('.02'))

    def test_reduction_partial_fills_keep_target_until_complete(self):
        r = self.replay()
        r.model.increase('base', -1, '.04', 100000)
        location = fixtures.CyclingOrderTests().location(side=1, observed=60000)
        r.signals.candidates = Mock(return_value=dict(action='retracement', location=location))
        r.propose(Bar(60000, 99000, 99001, 98999, 99000, 60000))
        r.last_volume = dec(1)
        r.fill_open(99000, 60000)
        self.assertEqual(r.orders.active.remaining, dec('.01'))
        r.fill_open(99000, 120000)
        self.assertIsNone(r.orders.active)
        self.assertEqual(r.model.quantity, dec('.02'))

    def test_funding_signed_once_and_end_is_marked_not_closed(self):
        r = self.replay()
        r.model.increase('base', -1, '.01', 100000)
        event = dict(fundingTime=60002, markPrice='102000', fundingRate='.0001')
        r.funding(event)
        r.funding(event)
        self.assertEqual(r.model.net_costs, dec('-.102'))
        summary = r.summary(102000)
        self.assertEqual(dec(summary['total_pnl']), dec('-19.898'))
        self.assertTrue(summary['open_position_right_censored'])
        self.assertEqual(r.model.quantity, dec('.01'))


if __name__ == '__main__':
    unittest.main()
