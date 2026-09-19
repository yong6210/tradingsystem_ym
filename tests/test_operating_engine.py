from dataclasses import replace
import unittest
import pandas as pd
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.diagnostics.intrabar_engine import simulate as frozen
from app.research.diagnostics.operating_engine import simulate


class OperatingEngineTests(unittest.TestCase):
    def setUp(self):
        self.m=pd.DataFrame(dict(o=100.,h=100.,l=100.,c=100.,v=1.),
            index=pd.date_range('2026-01-01',periods=5,freq='min',tz='UTC'))
        self.args=(self.m,{0:(1,100,50),4:(0,100,50)},self.m.index[0],self.m.index[-1]+pd.Timedelta(minutes=1))
        self.risk=Risk(cycle_fraction=.1,aggregate_fraction=.1,daily_stop=.9,
                       warning=.025,halt=.04,minimum_qty=1,step=1,minimum_notional=1,stop_atr=1)
        self.cost=Costs(0,0,0,.01)

    def run_case(self,debits,risk=None):
        return simulate(*self.args,self.cost,risk or self.risk,operating_debits=debits)

    def test_zero_charge_exact_parity(self):
        for path in ('OHLC','OLHC'):
            old=frozen(*self.args,self.cost,self.risk,path=path)
            new=simulate(*self.args,self.cost,self.risk,path=path,operating_debits={1:0})
            self.assertEqual(new['metrics'].pop('operating_cost'),0)
            self.assertEqual(old,new)

    def test_charge_during_position_not_counted_as_trading_loss(self):
        r=self.run_case({2:2})
        self.assertEqual(r['metrics']['final_equity'],998)
        self.assertEqual(r['metrics']['operating_cost'],2)
        self.assertEqual(r['trades'][0]['net_pnl'],0)
        self.assertAlmostEqual(r['metrics']['max_drawdown_pct'],.2)

    def test_charge_triggers_halt_and_keeps_running_cash_costs(self):
        r=self.run_case({2:41,3:2})
        self.assertTrue(r['metrics']['drawdown_halted'])
        self.assertEqual(r['trades'][0]['exit_minute'],2)
        self.assertEqual(r['metrics']['final_equity'],957)
        self.assertAlmostEqual(r['metrics']['max_drawdown_pct'],4.3)

    def test_charge_precedes_size_and_daily_stop(self):
        old=self.run_case({});new=self.run_case({0:2})
        self.assertLess(new['trades'][0]['quantity'],old['trades'][0]['quantity'])
        stopped=self.run_case({0:11},replace(self.risk,daily_stop=.01))
        self.assertEqual(stopped['trades'],[])
        self.assertEqual(stopped['metrics']['actions']['halted_entry'],1)

    def test_invalid_charge_rejected(self):
        for d in ({-1:2},{5:2},{2:-1},{2:float('nan')}):
            with self.assertRaises(ValueError):self.run_case(d)


if __name__=='__main__':unittest.main()
