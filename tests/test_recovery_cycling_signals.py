import unittest

from app.research.recovery.cycling_signals import (
    CompletedCandles, ConfirmedPivots, FourHourStructure, SignalPolicy, CyclingSignals)
from app.research.recovery.directional_cycling import DirectionalCycling
from app.research.recovery.models import Bar, Zone, Costs
from app.research.recovery.cycling_orders import CyclingOrders
from app.research.recovery.zone_observer import ZoneObserver


def minute(i, price=100, received=None):
    return Bar(i*60000, price, price+1, price-1, price, received or i*60000)


def structure_bars():
    highs = [10, 15, 12, 16, 13, 17, 14, 15, 12, 14]
    lows = [8, 10, 5, 11, 6, 12, 7, 10, 4, 9]
    return [Bar((i+1)*14400000, (h+l)/2, h, l, (h+l)/2, (i+1)*14400000)
            for i, (h, l) in enumerate(zip(highs, lows))]


class SignalTests(unittest.TestCase):
    def signals(self):
        return CyclingSignals(SignalPolicy(1, 1, 60, 1, 1, '.1', 2, 0, 'fixture'))

    def test_four_hours_require_all_minutes_and_close(self):
        agg = CompletedCandles(240)
        for i in range(1, 240):
            self.assertIsNone(agg.observe(minute(i)))
        completed = agg.observe(minute(240, received=14400123))
        self.assertEqual((completed.end_ms, completed.received_ms), (14400000, 14400123))
        self.assertIsNone(agg.observe(minute(240, received=14400123)))

    def test_partial_start_not_treated_as_full_four_hours(self):
        agg = CompletedCandles(240)
        for i in range(2, 480):
            self.assertIsNone(agg.observe(minute(i)))
        self.assertIsNotNone(agg.observe(minute(480)))

    def test_gap_rejection_does_not_consume_bad_minute(self):
        signals = self.signals()
        signals.observe(minute(1))
        with self.assertRaises(ValueError):
            signals.observe(minute(3))
        self.assertEqual(signals.last.end_ms, 60000)
        signals.observe(minute(2))
        signals.observe(minute(3))

    def test_pivot_available_only_after_right_confirmation(self):
        detector = ConfirmedPivots(1, 1)
        bars = structure_bars()
        self.assertEqual(detector.observe(bars[0]), ())
        self.assertEqual(detector.observe(bars[1]), ())
        pivot = detector.observe(bars[2])[0]
        self.assertEqual(pivot.side, -1)
        self.assertEqual(pivot.center.end_ms, bars[1].end_ms)
        self.assertEqual(pivot.available_ms, bars[2].received_ms)

    def test_mixed_structure_holds_direction_until_both_turn(self):
        trend = FourHourStructure(left=1, right=1)
        rows = [trend.observe(b) for b in structure_bars()]
        self.assertTrue(all(r['side'] is None for r in rows[:5]))
        self.assertEqual(rows[5]['side'], 1)
        self.assertEqual(rows[8]['reason'], 'mixed_keep_previous_direction')
        self.assertEqual(rows[8]['side'], 1)
        self.assertEqual(rows[9]['side'], -1)
        self.assertTrue(rows[9]['changed'])

    def test_prefix_output_does_not_depend_on_future_bars(self):
        bars = structure_bars()
        full = FourHourStructure(left=1, right=1)
        rows = [full.observe(b) for b in bars]
        for stop in range(1, len(bars)+1):
            partial = FourHourStructure(left=1, right=1)
            self.assertEqual([partial.observe(b) for b in bars[:stop]], rows[:stop])

    def test_short_term_reaction_does_not_change_four_hour_bias(self):
        signals = self.signals()
        signals.trend.direction = 1
        signals.assessment = dict(available_ms=0)
        model = DirectionalCycling('.1')
        model.set_direction(1, timeframe='4h', observed_ms=0, reason='fixture')
        model.increase('base', 1, 5, 110)
        model.increase('add', 1, 5, 100)
        # Resistance rejection above the latest add but below pooled break-even.
        zone = Zone('resistance', 1, 102, 104, 0, 'fixture resistance')
        observer = ZoneObserver.start(zone, -1, 0, 'fixture', 0)
        signals.zones[zone.key] = observer
        signals.observe(Bar(60000, 103, 104, 101, 101, 60000))
        result = signals.observe(Bar(120000, 101, 102, 100, 101, 120000))
        self.assertEqual(len(result['reactions']), 1)
        proposal = signals.candidates(model)
        self.assertEqual(proposal['action'], 'retracement')
        self.assertLess(proposal['reference_price'], model.average)
        self.assertEqual(signals.trend.direction, 1)
        signals.observe(signals.last)
        self.assertEqual(signals.candidates(model)['action'], 'wait')

    def test_unconfirmed_or_wrong_side_reaction_cannot_create_entry(self):
        signals = self.signals()
        model = DirectionalCycling('.1')
        self.assertEqual(signals.candidates(model)['reason'], 'no_market_data')
        signals.observe(minute(1))
        self.assertEqual(signals.candidates(model)['reason'], 'four_hour_direction_unknown')

    def test_trial_direction_bridge_requires_opt_in_and_routes_exit(self):
        signals = self.signals()
        trend = FourHourStructure(left=1, right=1)
        for bar in structure_bars()[:6]:
            signals.assessment = trend.observe(bar)
        model = DirectionalCycling('.1')
        model.set_direction(-1, timeframe='4h', observed_ms=0, reason='existing short')
        model.increase('base', -1, 5, 10)
        orders = CyclingOrders(model, Costs(0, 0, '.1', '.1', '.1', 1))
        with self.assertRaises(ValueError):
            signals.apply_direction(orders)
        self.assertEqual(model.direction, -1)
        self.assertEqual(signals.apply_direction(orders, enable_research_candidate=True), 'transition_requested')
        self.assertEqual(signals.apply_direction(orders, enable_research_candidate=True), 'transition_pending')
        order = orders.continue_transition('exit', reference_price=12)
        self.assertEqual(order.quantity, 5)
        orders.fill('exitfill', 'exit', 5, 12)
        self.assertEqual((model.direction, model.quantity), (1, 0))
        self.assertEqual(signals.apply_direction(orders, enable_research_candidate=True), 'unchanged')

    def test_delayed_receipt_is_used_as_direction_availability(self):
        signals = self.signals()
        model = DirectionalCycling('.1')
        for bar in structure_bars()[:6]:
            signals.assessment = signals.trend.observe(Bar(bar.end_ms, bar.open, bar.high, bar.low,
                                                          bar.close, bar.end_ms+100))
        signals.last = minute(1440, received=86400200)
        signals.latest = dict(trend=signals.assessment, reactions=())
        proposal = signals.candidates(model)
        self.assertEqual(proposal['observed_ms'], 86400100)


if __name__ == '__main__':
    unittest.main()
