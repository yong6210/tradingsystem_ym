import unittest
import pandas as pd

from app.research.diagnostics.direction_controls import controls, paired_interval, daily_returns, trade_sides, verify_t0_from_minutes
from app.research.comparison.engine import simulate
from tests.test_comparison import market
from app.research.baseline.engine import policies
from app.research.multistrategy_audit import frame_features


class DirectionControlTests(unittest.TestCase):
    def test_independent_indicators_and_clock_reject_direction_or_atr_change(self):
        import numpy as np
        frame = market(30000)
        price = 60000+np.arange(len(frame))*.1
        frame['o'] = frame['c'] = price
        frame['h'], frame['l'] = price+2, price-2
        original = policies(frame, {240: frame_features(frame, 240)})['T0']
        self.assertEqual(verify_t0_from_minutes(frame, original)['decisions'], len(original))
        index = next(iter(original))
        for change in ((-1, original[index][1], original[index][2]),
                       (1, original[index][1], original[index][2]+1)):
            with self.assertRaises(ValueError): verify_t0_from_minutes(frame, original | {index: change})
        shifted = {i+1: row for i, row in original.items()}
        with self.assertRaises(ValueError): verify_t0_from_minutes(frame, shifted)

    def test_preserves_decision_times_close_atr_and_original(self):
        original = {1: (1, 60000., 500.), 5: (-1, 60020., 400.), 9: (0, 60100., 300.)}
        c = controls(original)
        self.assertEqual(c['T0'], original)
        self.assertEqual(list(c['INVERSE'].values()), [(-1, 60000., 500.), (1, 60020., 400.), (0, 60100., 300.)])
        for model in c:
            self.assertEqual(set(c[model]), set(original))
            for i in original: self.assertEqual(c[model][i][1:], original[i][1:])
        self.assertEqual([v[0] for v in c['LONG'].values()], [1, 1, 1])
        self.assertEqual([v[0] for v in c['SHORT'].values()], [-1, -1, -1])
        c['T0'].clear()
        self.assertEqual(len(original), 3)

    def test_future_decisions_cannot_change_prefix(self):
        before = {1: (1, 60000., 500.)}
        after = before | {10: (-1, 80000., 2000.)}
        for model, rows in controls(after).items():
            self.assertEqual({k: v for k, v in rows.items() if k < 10}, controls(before)[model])

    def test_empty_signal_set_does_not_fabricate_entries(self):
        self.assertTrue(all(not rows for rows in controls({}).values()))

    def test_invalid_side_bool_or_nonfinite_rejected(self):
        for values in ((2, 1., 1.), (True, 1., 1.), (1, float('nan'), 1.), (1, 1., 0.)):
            with self.assertRaises(ValueError): controls({1: values})

    def test_cash_control_has_no_position_fee_or_funding(self):
        frame = market(10)
        result = simulate(frame, controls({1: (1, 60000., 500.)})['CASH'], frame.index[0],
            frame.index[-1]+pd.Timedelta(minutes=1), funding=[dict(fundingTime=int(frame.index[3].value//10**6),
            fundingRate='.0001', markPrice='60000')])
        self.assertEqual(result['events'], [])
        for k in ('fees', 'funding', 'cycles', 'return_pct', 'max_drawdown_pct'):
            self.assertEqual(result['metrics'][k], 0)

    def test_constant_direction_still_has_execution_costs(self):
        frame = market(10)
        for name, side in (('LONG', 1), ('SHORT', -1)):
            r = simulate(frame, controls({1: (-1, 60000., 500.)})[name], frame.index[0],
                         frame.index[-1]+pd.Timedelta(minutes=1))
            self.assertEqual(r['trades'][0]['side'], side)
            self.assertLess(r['metrics']['return_pct'], 0)

    def test_paired_identical_calendar_including_cash_days_is_zero(self):
        rows = [dict(day=f'2025-01-0{i+1}', equity=e) for i, e in enumerate((1010, 980, 980, 980))]
        r = paired_interval(rows, rows, repetitions=20)
        self.assertEqual(r['interval95_bps'], [0., 0.])
        self.assertEqual(r['calendar_days'], 4)

    def test_paired_order_reverses_effect_and_interval(self):
        a = [dict(day=f'2025-01-0{i+1}', equity=e) for i, e in enumerate((1010, 1030, 990, 980))]
        b = [dict(day=r['day'], equity=1000) for r in a]
        ab = paired_interval(a, b, repetitions=30, block_days=2)
        ba = paired_interval(b, a, repetitions=30, block_days=2)
        self.assertAlmostEqual(ab['mean_daily_difference_bps'], -ba['mean_daily_difference_bps'])
        self.assertAlmostEqual(ab['interval95_bps'][0], -ba['interval95_bps'][1])

    def test_missing_days_or_mismatched_dates_or_zero_equity_rejected(self):
        for rows in ([dict(day='2025-01-01', equity=0)],
                     [dict(day='2025-01-01', equity=1000), dict(day='2025-01-03', equity=1000)]):
            with self.assertRaises(ValueError): daily_returns(rows, 1000)
        with self.assertRaises(ValueError):
            paired_interval([dict(day='2025-01-01', equity=1000)], [dict(day='2025-01-02', equity=1000)])

    def test_side_attribution_uses_complete_cycles_and_rejects_unknown(self):
        trades = [dict(side=1, net_pnl=10, entry_minute=1, exit_minute=5),
                  dict(side=-1, net_pnl=-3, entry_minute=10, exit_minute=15)]
        r = trade_sides(trades)
        self.assertEqual(sum(x['net_pnl'] for x in r.values()), 7)
        self.assertEqual(r['long']['held_minutes'], 4)
        with self.assertRaises(ValueError): trade_sides([dict(side=0)])


if __name__ == '__main__': unittest.main()
