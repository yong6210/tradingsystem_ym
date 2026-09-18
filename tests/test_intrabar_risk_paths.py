from dataclasses import replace
import unittest
import pandas as pd

from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.comparison.engine import simulate as legacy
from app.research.diagnostics.intrabar_engine import simulate


class IntrabarRiskPathTests(unittest.TestCase):
    def run_case(self, rows, decisions, *, path='OHLC', risk=None, costs=Costs(0, 0, 0, .01), funding=()):
        frame=pd.DataFrame(rows,columns=['o','h','l','c'])
        frame['v']=1.
        frame.index=pd.date_range('2025-01-01',periods=len(frame),freq='min',tz='UTC')
        # Synthetic unit-size fixture: do not use this risk configuration in E015.
        risk=risk or Risk(initial=1000,cycle_fraction=.1,aggregate_fraction=.1,exposure_multiple=1,
            daily_stop=.9,warning=.05,halt=.08,minimum_qty=1,step=1,minimum_notional=1,
            stop_atr=1,maximum_hold_minutes=100)
        return simulate(frame,decisions,frame.index[0],frame.index[-1]+pd.Timedelta(minutes=1),costs,risk,
                        funding=funding,path=path)

    def test_favorable_high_changes_protective_line_before_later_low(self):
        # One unit from 100; high=200 creates equity peak1100 and an8% stop112.
        rows=[(100,100,100,100),(100,200,90,190)]
        r=self.run_case(rows,{0:(1,100,100)})
        # raw stop zero rejected; use ATR90 for one unit and stop10.
        self.assertEqual(r['metrics']['cycles'],0)
        r=self.run_case(rows,{0:(1,100,90)})
        self.assertAlmostEqual(r['path_stops'][0]['peak_before'],1100)
        self.assertAlmostEqual(r['path_stops'][0]['protective_line'],112)
        self.assertAlmostEqual(r['trades'][0]['net_pnl'],12)
        self.assertAlmostEqual(r['metrics']['max_drawdown_pct'],8)
        self.assertTrue(r['metrics']['drawdown_halted'])

    def test_same_ohlc_other_order_does_not_cross_the_later_stop(self):
        r=self.run_case([(100,100,100,100),(100,200,90,190)],{0:(1,100,90)},path='OLHC')
        self.assertEqual(r['path_stops'],[])
        self.assertAlmostEqual(r['metrics']['final_equity'],1090)
        self.assertFalse(r['metrics']['drawdown_halted'])
        self.assertAlmostEqual(r['metrics']['max_drawdown_pct'],1)

    def test_short_favorable_low_can_create_later_risk_stop(self):
        # Short one unit at200 with ATR100: low100 => peak1100 => stop188.
        rows=[(200,200,200,200),(200,210,100,110)]
        r=self.run_case(rows,{0:(-1,200,100)},path='OLHC')
        self.assertAlmostEqual(r['path_stops'][0]['protective_line'],188)
        self.assertAlmostEqual(r['metrics']['final_equity'],1012)
        other=self.run_case(rows,{0:(-1,200,100)},path='OHLC')
        self.assertAlmostEqual(other['metrics']['final_equity'],1090)

    def test_warning_sees_adverse_excursion_even_if_close_recovers(self):
        r=self.run_case([(100,100,100,100),(100,110,40,100)],{0:(1,100,90)},path='OLHC')
        self.assertTrue(r['metrics']['warned'])
        self.assertFalse(r['metrics']['drawdown_halted'])
        self.assertAlmostEqual(r['metrics']['max_drawdown_pct'],6)

    def test_unknown_path_rejected(self):
        with self.assertRaises(ValueError): self.run_case([(100,100,100,100)],{},path='BEST')

    def test_no_position_has_no_market_drawdown(self):
        for path in ('OHLC','OLHC'):
            r=self.run_case([(100,10000,1,100)],{},path=path)
            self.assertEqual(r['metrics']['max_drawdown_pct'],0)
            self.assertEqual(r['metrics']['final_equity'],1000)

    def test_stop_touch_is_inclusive_and_never_visits_later_extreme(self):
        r=self.run_case([(100,100,100,100),(100,500,20,200)],{0:(1,100,90)},path='OLHC')
        self.assertEqual(r['path_stops'][0]['reference'],20)
        self.assertEqual(r['path_stops'][0]['leg'],0)
        self.assertAlmostEqual(r['metrics']['final_equity'],920)
        self.assertEqual(r['path_diagnostics']['favorable_peak_updates'],0)

    def test_existing_open_gap_uses_market_open(self):
        r=self.run_case([(100,100,100,100),(10,15,5,12)],{0:(1,100,90)})
        self.assertEqual(r['trades'][0]['reason'],'risk_stop_gap')
        self.assertEqual(r['metrics']['final_equity'],910)
        self.assertGreater(r['metrics']['max_drawdown_pct'],8)

    def test_new_entry_stop_already_breached_uses_open_not_favorable_line(self):
        risk=Risk(initial=1000,cycle_fraction=.1,aggregate_fraction=.1,exposure_multiple=1,
            daily_stop=.9,warning=.5,halt=.8,minimum_qty=1,step=1,minimum_notional=1,
            stop_atr=1,maximum_hold_minutes=100)
        r=self.run_case([(100,100,100,100)],{0:(1,111,10)},risk=risk,costs=Costs(0,200,0,.01))
        self.assertTrue(r['path_stops'][0]['breached_at_origin'])
        self.assertEqual(r['path_stops'][0]['reference'],100)

    def test_flat_price_paths_reproduce_frozen_account(self):
        frame=pd.DataFrame(dict(o=60000.,h=60000.,l=60000.,c=60000.,v=1.),
            index=pd.date_range('2025-01-01',periods=10,freq='min',tz='UTC'))
        args=(frame,{1:(1,60000.,500.),6:(-1,60000.,500.)},frame.index[0],frame.index[-1]+pd.Timedelta(minutes=1))
        old=legacy(*args)
        for path in ('OHLC','OLHC'):
            new=simulate(*args,path=path)
            for field in ('metrics','events','trades','daily','rejections','verification'):
                self.assertEqual(new[field],old[field])


if __name__=='__main__':unittest.main()
