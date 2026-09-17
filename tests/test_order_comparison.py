import unittest
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
import numpy as np
import pandas as pd
from app.research.execution.order_rules import (Rules,Reentry,TargetAnchor,TakeProfit,StopBasis,SignalState,Levels,update_signal)
from app.research.order_comparison.engine import simulate
from app.research.order_comparison.adapter import observations,load_profiles
from app.research.order_comparison.sizing import size_plan
from app.research.execution.order_rules import prepare_cycle
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.multistrategy_audit import feature_bank


def market(n=20):
    return pd.DataFrame(dict(o=10000.,h=10001.,l=9999.,c=10000.,v=1.),index=pd.date_range('2025-01-01',periods=n,freq='min',tz='UTC'))


def policy(**changes):
    return replace(Rules(Reentry.CONTINUING_NEXT_DECISION,TargetAnchor.EPISODE_START,TakeProfit.CLOSE_CONFIRM_MARKET,StopBasis.ATR),**changes)


def decisions(frame,indices=(1,6,11)):
    state=SignalState('test/BTCUSDC/F0')
    result={}
    for i in indices:
        source=i-1
        levels=Levels(int(frame.index[source].value//1_000_000),D('10000'),D('50'),D('9800'),D('10200'),D('10100'))
        state=update_signal(state,1,levels);result[i]=state
    return result


def run(frame,signals=None,rules=None,**kwargs):
    return simulate(frame,signals or decisions(frame),frame.index[0],frame.index[-1]+pd.Timedelta(minutes=1),
                    rules or policy(),marks=frame.o,**kwargs)


class OrderIntegrationTests(unittest.TestCase):
    def test_resting_limit_not_synthetic_fill(self):
        with self.assertRaises(ValueError):run(market(),rules=policy(take_profit=TakeProfit.RESTING_LIMIT))

    def test_close_target_executes_next_delayed_open(self):
        frame=market();frame.loc[frame.index[4],['h','c']]=[10151.,10150.]
        r=run(frame)
        self.assertEqual(r['trades'][0]['exit_minute'],6)
        self.assertEqual(r['trades'][0]['reason'],'TARGET_CLOSE_CONFIRMED')
        self.assertAlmostEqual(r['events'][1]['price'],Costs().fill(10000,-1))

    def test_touch_target_executes_before_close_confirmation(self):
        frame=market();frame.loc[frame.index[3],'h']=10150
        r=run(frame,rules=policy(take_profit=TakeProfit.TOUCH_MARKET))
        self.assertEqual(r['trades'][0]['exit_minute'],3)
        self.assertEqual(r['trades'][0]['reason'],'TARGET_TOUCH_MARKET_PROXY')

    def test_same_bar_stop_first_and_later_decision_reentry(self):
        frame=market();frame.loc[frame.index[2],['l','h']]=[9700.,10200.]
        r=run(frame,rules=policy(take_profit=TakeProfit.TOUCH_MARKET))
        self.assertEqual(r['trades'][0]['reason'],'STOP_FIRST_OHLC')
        self.assertTrue(r['trades'][0]['ambiguous'])
        self.assertEqual(r['trades'][1]['entry_minute'],6)

    def test_fresh_episode_blocks_stop_reentry(self):
        frame=market();frame.loc[frame.index[2],'l']=9700.
        r=run(frame,rules=policy(reentry=Reentry.FRESH_EPISODE))
        self.assertEqual(r['metrics']['cycles'],1)
        self.assertEqual(r['metrics']['actions']['EPISODE_ALREADY_RESERVED'],2)

    def test_structural_stop_uses_its_own_sizing(self):
        frame=market()
        a=run(frame);b=run(frame,rules=policy(stop_basis=StopBasis.STRUCTURE))
        self.assertEqual(a['trades'][0]['stop'],9850.)
        self.assertEqual(b['trades'][0]['stop'],9799.9)
        self.assertLess(b['trades'][0]['quantity'],a['trades'][0]['quantity'])
        self.assertLessEqual(b['trades'][0]['planned_loss'],b['trades'][0]['budget'])

    def test_adverse_entry_gap_rejected_before_reservation(self):
        frame=market();frame.loc[frame.index[1],['o','h','l','c']]=[10200,10201,10199,10200]
        r=run(frame,signals=decisions(frame,(1,)))
        self.assertEqual(r['metrics']['cycles'],0)
        self.assertEqual(r['rejections'][0]['reason'],'invalid_target_or_stop')

    def test_funding_sign_and_cycle_reconciliation(self):
        frame=market()
        funding=[dict(fundingTime=int(frame.index[3].value//1_000_000),fundingRate='.0001',markPrice='10000')]
        r=run(frame,funding=funding)
        self.assertGreater(r['metrics']['funding'],0)
        self.assertAlmostEqual(sum(t['net_pnl'] for t in r['trades']),r['metrics']['final_equity']-1000)

    def test_minimum_notional_uses_mark(self):
        frame=market();signal=decisions(frame)[1];rules=policy()
        plan=prepare_cycle(signal,rules,'a',D('10000'))
        r=size_plan(plan,10000.,1000.,1000.,False,Costs(),Risk())
        self.assertFalse(r['approved'])

    def test_invalid_mark_window_rejected(self):
        frame=market();marks=frame.o.copy();marks.iloc[2]=np.nan
        with self.assertRaises(ValueError):
            simulate(frame,decisions(frame),frame.index[0],frame.index[-1],policy(),marks=marks)

    def test_profiles_change_only_one_axis(self):
        profiles=load_profiles(Path('configs/research/order_rule_profiles_v1.json'))
        for name,rules in profiles.items():
            if name!='control':
                self.assertEqual(sum(getattr(rules,key)!=getattr(profiles['control'],key) for key in ('reentry','target_anchor','take_profit','stop_basis')),1)

    def test_adapter_and_account_future_invariance(self):
        frame=market(30000)
        prices=10000*np.exp(np.cumsum(np.random.default_rng(17).normal(0,.0007,len(frame))))
        frame['o']=frame['c']=prices;frame['h']=prices+2;frame['l']=prices-2
        changed=frame.copy();changed.iloc[27000:,:4]*=1.5
        a,b=feature_bank(frame),feature_bank(changed)
        for model in ('R0','F0'):
            x=observations(frame,a[60],model);y=observations(changed,b[60],model)
            self.assertEqual({k:v for k,v in x.items() if k<=27000},{k:v for k,v in y.items() if k<=27000})
            for i,s in x.items(): self.assertLess(s.latest.available_ms,int(frame.index[i].value//1_000_000))
            end=frame.index[27000]
            one=simulate(frame,x,frame.index[10000],end,policy(),marks=frame.o)
            two=simulate(changed,y,frame.index[10000],end,policy(),marks=changed.o)
            self.assertEqual(one['events'],two['events'])
