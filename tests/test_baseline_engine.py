import unittest
from dataclasses import replace
import numpy as np
import pandas as pd
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk, size_order
from app.research.baseline.engine import simulate,policies
from app.research.multistrategy_audit import feature_bank


def market(n=20,price=60000):
    return pd.DataFrame(dict(o=price,h=price+1,l=price-1,c=price,v=1000),
                        index=pd.date_range('2024-01-01',periods=n,freq='min',tz='UTC'))


def run(frame, decisions, costs=Costs(),risk=Risk()):
    return simulate(frame,decisions,frame.index[0],frame.index[-1]+pd.Timedelta(minutes=1),costs,risk)


class BaselineRiskTests(unittest.TestCase):
    def test_hand_sizing_with_cost_and_step(self):
        p=size_order(60000,60000,500,1,1000,False,Costs(),Risk())
        self.assertTrue(p['approved'])
        self.assertEqual(p['quantity'],.003)
        self.assertEqual(p['entry'],60012)
        self.assertEqual(p['stop'],58500)
        self.assertLessEqual(p['planned_loss'],5)
        self.assertGreater(p['planned_loss']+p['planned_loss']/3,5)

    def test_small_account_and_warning(self):
        self.assertFalse(size_order(60000,60000,500,1,100,False,Costs(),Risk())['approved'])
        p=size_order(60000,60000,500,1,1000,True,Costs(),Risk())
        self.assertEqual(p['quantity'],.001)
        self.assertLessEqual(p['planned_loss'],2.5)

    def test_short_risk_and_invalid_stop(self):
        p=size_order(60000,60000,500,-1,1000,False,Costs(),Risk())
        self.assertTrue(p['approved']);self.assertEqual(p['stop'],61500)
        self.assertFalse(size_order(50000,60000,500,1,1000,False,Costs(),Risk())['approved'])


class BaselineEngineTests(unittest.TestCase):
    def test_same_direction_fixed_quantity_and_neutral_exit(self):
        frame=market()
        result=run(frame,{1:(1,60000,500),4:(1,60000,20),8:(0,60000,500)})
        self.assertEqual(len(result['trades']),1)
        self.assertEqual(len(result['events']),2)
        self.assertEqual(result['events'][0]['qty'],.003)
        self.assertEqual(result['trades'][0]['exit_minute'],8)

    def test_reversal_two_events_then_new_trade(self):
        result=run(market(),{1:(1,60000,500),4:(-1,60000,500)})
        self.assertEqual([e['kind'] for e in result['events']],['entry','exit','entry','exit'])
        self.assertEqual(result['events'][1]['time'],result['events'][2]['time'])

    def test_gap_stop_uses_open_not_stop_price(self):
        frame=market()
        frame.loc[frame.index[3]:,['o','h','l','c']]=[58000,58001,57999,58000]
        result=run(frame,{1:(1,60000,500)})
        self.assertEqual(result['trades'][0]['reason'],'price_stop_gap')
        self.assertAlmostEqual(result['events'][1]['price'],Costs().fill(58000,-1))

    def test_entry_bar_stop_and_next_signal_only(self):
        frame=market()
        frame.loc[frame.index[1],'l']=58000
        result=run(frame,{1:(1,60000,500)})
        self.assertEqual(result['trades'][0]['exit_minute'],1)
        self.assertEqual(result['metrics']['cycles'],1)

    def test_no_future_extreme_peak_before_adverse_stop(self):
        frame=market()
        frame.loc[frame.index[2],'h']=200000
        result=run(frame,{1:(1,60000,500)})
        self.assertFalse(result['metrics']['drawdown_halted'])
        self.assertEqual(result['trades'][0]['reason'],'end_exit')

    def test_halt_latches_after_gap(self):
        frame=market()
        frame.loc[frame.index[2]:,['o','h','l','c']]=[10000,10001,9999,10000]
        result=run(frame,{1:(1,60000,500),4:(1,10000,100)})
        self.assertTrue(result['metrics']['drawdown_halted'])
        self.assertEqual(result['metrics']['cycles'],1)
        self.assertEqual(result['metrics']['actions']['halted_entry'],1)

    def test_risk_line_exits_before_wider_price_stop(self):
        frame=market()
        frame.loc[frame.index[2],'l']=58000
        result=run(frame,{1:(1,60000,500)},risk=replace(Risk(),daily_stop=.001))
        self.assertEqual(result['trades'][0]['reason'],'risk_stop')
        self.assertGreater(result['events'][1]['price'],58500)

    def test_funding_only_when_already_held_and_flat_cash(self):
        frame=market(490)
        result=run(frame,{1:(1,60000,500)},costs=Costs(funding_bps_8h=1))
        self.assertEqual(sum(e['kind']=='funding' for e in result['events']),1)
        self.assertAlmostEqual(result['metrics']['funding'],.018)
        flat=run(frame,{})
        self.assertEqual(flat['metrics']['final_equity'],1000)
        self.assertEqual(flat['metrics']['cycles'],0)

    def test_end_uses_last_close_not_outside_price(self):
        frame=market()
        result=simulate(frame,{1:(1,60000,500)},frame.index[0],frame.index[10])
        self.assertEqual(result['trades'][0]['exit_minute'],9)

    def test_signal_delay_and_future_invariance(self):
        frame=market(30000)
        rng=np.random.default_rng(3)
        prices=60000*np.exp(np.cumsum(rng.normal(0,.0005,len(frame))))
        for key in ('o','c'):frame[key]=prices
        frame['h']=prices+10;frame['l']=prices-10
        altered=frame.copy();altered.iloc[27000:,:4]*=2
        a=policies(frame,feature_bank(frame));b=policies(altered,feature_bank(altered))
        for model in a:
            self.assertEqual({i:v for i,v in a[model].items() if i<=27000},{i:v for i,v in b[model].items() if i<=27000})
            self.assertTrue(all(i%240==1 for i in a[model]))


if __name__=='__main__':unittest.main()
