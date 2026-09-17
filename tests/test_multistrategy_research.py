"""Research controls, causal signals and explicit accounting regression tests."""
import unittest
try:
    import numpy as np
    import pandas as pd
except ModuleNotFoundError as exc:
    raise unittest.SkipTest('Install requirements-research.txt for offline research tests') from exc

from app.research.multistrategy import (Model, FAMILIES, REGIMES, feature_bank,
                                       signals, simulate, select_router, block_interval)


def market(n=8):
    return pd.DataFrame({'o': np.full(n, 100.), 'h': np.full(n, 100.5),
                         'l': np.full(n, 99.5), 'c': np.full(n, 100.), 'v': np.full(n, 10000.)},
                        index=pd.date_range('2026-01-01', periods=n, freq='min', tz='UTC'))


def one_signal(n=8):
    a = {k: np.zeros(n, dtype=d) for k, d in [('side', int), ('decision', bool), ('atr', float), ('close', float), ('direction', int)]}
    a['side'][0] = a['direction'][0] = 1
    a['decision'][0] = True
    a['atr'][0], a['close'][0] = 1., 100.
    a.update(stop_atr=2., target_atr=3., max_hold=100, trail=False, rotation=False, period=1)
    return a


class ResearchTests(unittest.TestCase):
    def run_case(self, f, signal=None, **kwargs):
        return simulate(f, {'a': signal or one_signal(len(f))}, np.full(len(f), 2),
                        '2026-01-01', '2026-01-02', model_name='a', record_events=True, **kwargs)

    def test_fee_and_cycle_cash_reconciliation(self):
        r = self.run_case(market())
        self.assertEqual(r['cycles'], 1)
        self.assertAlmostEqual(r['final_equity'], 10000+r['realized']-r['fees']-r['funding'])
        fee = sum(e['price']*e['qty']*.0005 for e in r['events'] if e['action'].startswith('market_'))
        self.assertAlmostEqual(fee, r['fees'])
        self.assertAlmostEqual(sum(x['pnl'] for x in r['cycle_log']), r['final_equity']-10000)

    def test_entry_and_stop_same_minute(self):
        f = market(); f.iloc[0, f.columns.get_loc('l')] = 97.
        r = self.run_case(f)
        self.assertEqual(r['counts']['stop'], 1)
        self.assertLess(r['return_pct'], 0)

    def test_profit_does_not_precede_stop(self):
        f = market(); f.iloc[1, f.columns.get_loc('h')] = 105.; f.iloc[1, f.columns.get_loc('l')] = 97.
        r = self.run_case(f)
        self.assertEqual(r['counts']['stop'], 1)
        self.assertNotIn('profit', r['counts'])

    def test_post_only_market_cross_is_rejected(self):
        f = market(); f.iloc[0, f.columns.get_loc('o')] = 99.
        r = self.run_case(f)
        self.assertEqual(r['counts']['post_only_rejected'], 1)
        self.assertEqual(r['cycles'], 0)

    def test_gap_through_stop_exits_at_adverse_open(self):
        f = market()
        f.loc[f.index[1], ['o', 'h', 'l', 'c']] = [95., 96., 94., 95.]
        r = self.run_case(f)
        stop_event = next(e for e in r['events'] if e['action'] == 'market_stop')
        self.assertAlmostEqual(stop_event['price'], 95*(1-.0002))

    def test_partial_fill_is_volume_limited(self):
        f = market(); f['v'] = 1.
        r = self.run_case(f)
        self.assertGreater(r['counts']['partial_fills'], 0)
        self.assertLessEqual(max(e['qty'] for e in r['events'] if e['action'] == 'maker_add'), .001)

    def test_unfilled_addition_cannot_disable_protective_stop(self):
        f = market()
        s = one_signal()
        s.update(rotation=True, stop_atr=4., target_atr=1.5)
        s['decision'][5] = True
        s['atr'][5], s['close'][5] = 1., 98.8
        f.loc[f.index[5], ['o', 'h', 'l', 'c']] = [99., 99.5, 98.9, 99.]
        f.loc[f.index[6], ['o', 'h', 'l', 'c', 'v']] = [99., 99.5, 95., 98., 0.]
        r = self.run_case(f, s)
        self.assertEqual(r['counts']['stop'], 1)
        self.assertEqual(r['cycle_log'][0]['exit'], f.index[6].isoformat())

    def test_new_addition_precedes_same_minute_stop_both_sides(self):
        for direction in (1, -1):
            with self.subTest(direction=direction):
                f = market()
                s = one_signal()
                s.update(rotation=True, stop_atr=4., target_atr=1.5)
                s['decision'][5] = True
                s['atr'][5], s['close'][5] = 1., 98.8
                f.loc[f.index[5], ['o', 'h', 'l', 'c']] = [99., 99.5, 95., 98.]
                if direction == -1:
                    f[['o', 'c']] = 200-f[['o', 'c']]
                    f['h'], f['l'] = 200-f['l'].copy(), 200-f['h'].copy()
                    s['side'] *= -1
                    s['direction'] *= -1
                    s['close'][s['decision']] = 200-s['close'][s['decision']]
                r = self.run_case(f, s)
                self.assertEqual(r['counts'].get('rotation_add', 0), 1)
                actions = [e['action'] for e in r['events'] if e['time'] == f.index[5].isoformat()]
                self.assertEqual(actions, ['maker_add', 'market_stop'])

    def test_no_qualified_strategy_is_cash(self):
        r = simulate(market(), {'a': one_signal()}, np.full(8, 2), '2026-01-01', '2026-01-02', routing={})
        self.assertEqual(r['return_pct'], 0)
        self.assertEqual(r['cycles'], 0)

    def test_router_uses_validation_and_stress_gate(self):
        base = {'return_pct': 2, 'max_drawdown_pct': 3, 'cycles': 12,
                'regime_cycles': {reg: {'count': 6, 'pnl': 50} for reg in REGIMES}}
        rejected = select_router({'a': base}, {'a': {'return_pct': -.1}})
        self.assertEqual(rejected['routing'], {})
        admitted = select_router({'a': base}, {'a': {'return_pct': 1}})
        self.assertNotIn('high_volatility', admitted['routing'])

    def test_future_candles_cannot_change_past_signals(self):
        n = 45*1440
        f = market(n)
        price = 100+np.arange(n)*.001+np.sin(np.arange(n)/40)
        for k, delta in [('o', 0), ('c', .01), ('h', .2), ('l', -.2)]:
            f[k] = price+delta
        cut = 35*1440
        modified = f.copy()
        modified.iloc[cut:, :4] *= 2
        a, b = feature_bank(f), feature_bank(modified)
        np.testing.assert_array_equal(a['regime'][:cut], b['regime'][:cut])
        for family in FAMILIES:
            s1, s2 = signals(f, a, Model(family)), signals(modified, b, Model(family))
            for key in ('side', 'atr', 'close', 'decision'):
                np.testing.assert_array_equal(s1[key][:cut], s2[key][:cut])
        # The 4h candle starting at the cut cannot enter a signal before its end.
        self.assertTrue(a[240].index[0] == f.index[0]+pd.Timedelta(hours=4))

    def test_bootstrap_flat_returns_are_zero(self):
        r = block_interval([{'equity': 10000} for _ in range(30)])
        self.assertEqual(r['return_95pct'], [0, 0])


if __name__ == '__main__':
    unittest.main()
