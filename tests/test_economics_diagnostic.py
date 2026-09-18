import unittest
from decimal import Decimal as D
import pandas as pd
from app.research.diagnostics.economics import (
    cost_bridge, exit_reference, fill_components, sizing_rows,
    holding_bounds, exposure, recovery_episodes, operating_costs)


class EconomicsTests(unittest.TestCase):
    def test_buy_sell_slippage_and_tick_are_separate(self):
        costs = dict(slippage_bps=5, tick=.1)
        self.assertEqual(fill_components(100, 100.1, 1, 2, costs), (D('.1000'), D('.1000')))
        self.assertEqual(fill_components(100, 99.9, -1, 2, costs), (D('.1000'), D('.1000')))
        with self.assertRaises(ValueError):
            fill_components(100, 100, 1, 2, costs)

    def test_bridge_funding_receipt_and_stress_are_distinct(self):
        frame = pd.DataFrame(dict(o=[100.,110.], c=[100.,110.]))
        trade = dict(entry_time='a', exit_time='b', entry_minute=0, exit_minute=1,
                     side=1, quantity=1, reason='end_exit')
        events = [dict(kind='entry',time='a',side=1,qty=1,price=100,fee=1),
                  dict(kind='funding',historical_amount=-2,stress_amount=.5,amount=-1.5),
                  dict(kind='exit',time='b',side=-1,qty=1,price=110,fee=1,balance=1009.5)]
        result = cost_bridge(events,[trade],{},frame,dict(slippage_bps=0,tick=.1),1000)
        self.assertEqual(result['historical_funding_received'],2)
        self.assertEqual(result['historical_funding_net'],-2)
        self.assertEqual(result['stress_funding'],.5)
        self.assertEqual(result['net_profit'],9.5)

    def test_unknown_exit_cannot_be_treated_as_free_fill(self):
        with self.assertRaises(ValueError):
            exit_reference(dict(reason='unexpected'),0,{},None)
        with self.assertRaises(KeyError):
            exit_reference(dict(reason='price_stop'),0,{},None)
        with self.assertRaises(ValueError):
            holding_bounds(dict(reason='unexpected'))

    def test_risk_sizing_rounding_loses_fraction_of_budget(self):
        event = dict(kind='entry',balance=1000,fee=0)
        trade = dict(entry_time='a',entry_price=100,quantity=.01,budget=.15,side=1,stop=90,planned_loss=.1)
        risk = dict(cycle_fraction=.00015,aggregate_fraction=.01,exposure_multiple=1,step=.01)
        row = sizing_rows([event],[trade],dict(slippage_bps=0,tick=.1,fee_bps=0),risk)[0]
        self.assertEqual(row['binding'],'risk')
        self.assertAlmostEqual(row['budget_utilization'],2/3)
        self.assertAlmostEqual(row['rounding_unused_fraction'],1/3)
        self.assertEqual(row['notional_cap_unused_fraction'],0)

    def test_notional_cap_is_not_rounding(self):
        event = dict(kind='entry',balance=100,fee=0)
        trade = dict(entry_time='a',entry_price=100,quantity=1,budget=50,side=1,stop=90,planned_loss=10)
        risk = dict(cycle_fraction=.5,aggregate_fraction=.5,exposure_multiple=1,step=.01)
        row = sizing_rows([event],[trade],dict(slippage_bps=0,tick=.1,fee_bps=0),risk)[0]
        self.assertEqual(row['binding'],'notional')
        self.assertEqual(row['notional_cap_unused_fraction'],.8)
        self.assertEqual(row['rounding_unused_fraction'],0)

    def test_open_exit_excluded_and_intrabar_exit_included(self):
        frame = pd.DataFrame(dict(o=[10.,20.,30.,40.]))
        trades = [dict(entry_minute=0,exit_minute=1,quantity=2,reason='reverse_exit'),
                  dict(entry_minute=1,exit_minute=2,quantity=1,reason='price_stop')]
        result = exposure(trades,frame,0,4)
        self.assertEqual(result['active_minutes'],3)
        self.assertEqual(result['mean_notional'],17.5)
        trades[1]['entry_minute']=0
        with self.assertRaises(ValueError):
            exposure(trades,frame,0,4)

    def test_recovery_days_differ_from_below_peak_closes(self):
        rows = [dict(day=f'2025-01-0{i+1}',equity=e) for i,e in enumerate((110,100,105,110,110,109))]
        episodes = recovery_episodes(rows,100)
        self.assertEqual(episodes[0]['elapsed_days'],3)
        self.assertEqual(episodes[0]['below_peak_closes'],2)
        self.assertEqual(episodes[0]['trough_day'],'2025-01-02')
        self.assertTrue(episodes[0]['recovered'])
        self.assertFalse(episodes[1]['recovered'])
        self.assertEqual(episodes[1]['peak_day'],'2025-01-05')
        self.assertEqual(episodes[1]['elapsed_days'],1)

    def test_missing_day_and_nonfinite_equity_rejected(self):
        for rows in ([dict(day='2025-01-01',equity=100),dict(day='2025-01-03',equity=100)],
                     [dict(day='2025-01-01',equity=float('nan'))]):
            with self.assertRaises(ValueError):
                recovery_episodes(rows,100)

    def test_operating_cost_is_fixed_path_accounting(self):
        result = operating_costs(48,24)
        self.assertEqual(result['break_even_monthly'],2)
        self.assertEqual([r['residual_profit'] for r in result['scenarios']],[48,24,0,-72])
        with self.assertRaises(ValueError):
            operating_costs(48,0)


if __name__ == '__main__':
    unittest.main()
