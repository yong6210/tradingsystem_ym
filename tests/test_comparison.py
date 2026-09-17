import unittest
import numpy as np
import pandas as pd
from app.research.baseline.account import Account, Costs, replay
from app.research.baseline.engine import simulate as baseline
from app.research.comparison.engine import simulate
from app.research.comparison.funding import funding_schedule, settle
from app.research.comparison.policies import comparison_policies, family_sides
from app.research.multistrategy_audit import feature_bank


def market(n=10):
    return pd.DataFrame(dict(o=60000.,h=60001.,l=59999.,c=60000.,v=1.),index=pd.date_range('2025-01-01',periods=n,freq='min',tz='UTC'))


class FundingTests(unittest.TestCase):
    def event(self, time):
        return dict(fundingTime=time, fundingRate='.0001', markPrice='60000')

    def test_signed_cash_and_independent_replay(self):
        for side in (1,-1):
            account=Account(1000)
            account.enter('a',side,.002,60000,0)
            settle(account,'b',self.event(1))
            self.assertAlmostEqual(account.balance,1000-side*.012)
            self.assertEqual(replay(account.events,1000)['status'],'PASS')

    def test_millisecond_timing_and_duplicate(self):
        index=market().index
        time=int(index[1].value//1_000_000)
        self.assertEqual(list(funding_schedule(index,[self.event(time)])),[1])
        self.assertEqual(list(funding_schedule(index,[self.event(time+1)])),[2])
        with self.assertRaises(ValueError): funding_schedule(index,[self.event(time),self.event(time)])

    def test_new_entry_after_settlement_does_not_pay(self):
        frame=market()
        event=self.event(int(frame.index[1].value//1_000_000))
        args=(frame,{1:(1,60000,500)},frame.index[0],frame.index[-1]+pd.Timedelta(minutes=1))
        self.assertEqual(simulate(*args,funding=[event])['metrics']['funding'],0)
        event['fundingTime']+=1
        self.assertGreater(simulate(*args,funding=[event])['metrics']['funding'],0)

    def test_zero_funding_reproduces_frozen_engine(self):
        frame=market()
        args=(frame,{1:(1,60000,500),5:(-1,60000,500)},frame.index[0],frame.index[-1]+pd.Timedelta(minutes=1))
        old,new=baseline(*args),simulate(*args)
        for key in ('events','trades','daily','rejections','verification'):
            self.assertEqual(old[key],new[key])
        for key,value in old['metrics'].items(): self.assertEqual(value,new['metrics'][key])

    def test_funding_stress_debits_both_sides(self):
        for side in (1,-1):
            account=Account(1000);account.enter('a',side,.002,60000,0)
            settle(account,'b',self.event(1),2)
            self.assertAlmostEqual(account.events[-1]['amount'],side*.012+.024)


class PolicyTests(unittest.TestCase):
    def fixture(self, **values):
        data=dict(c=[100.,100.,100.],h=[101.]*3,l=[99.]*3,atr=[2.]*3,er=[.1]*3,z=[0.]*3,
                  high24=[110.]*3,low24=[90.]*3,high12=[105.]*3,low12=[95.]*3)
        data.update(values)
        return pd.DataFrame(data)

    def test_breakout_holds_until_opposite_exit(self):
        self.assertEqual(family_sides(self.fixture(c=[111.,100.,94.]),'B0'),[1,1,0])

    def test_reversion_mean_exit_and_regime_block(self):
        self.assertEqual(family_sides(self.fixture(z=[-2.1,-1.,.1]),'R0'),[1,1,0])
        self.assertEqual(family_sides(self.fixture(z=[-2.1]*3,er=[.4]*3),'R0'),[0,0,0])

    def test_failed_break_and_ambiguous_bar(self):
        self.assertEqual(family_sides(self.fixture(l=[94.,99.,99.],c=[96.,99.,101.]),'F0'),[1,1,0])
        self.assertEqual(family_sides(self.fixture(l=[94.]*3,h=[106.]*3),'F0'),[0,0,0])

    def test_future_invariance_and_delay(self):
        frame=market(30000)
        prices=60000*np.exp(np.cumsum(np.random.default_rng(7).normal(0,.0005,len(frame))))
        frame['o']=frame['c']=prices;frame['h']=prices+10;frame['l']=prices-10
        altered=frame.copy();altered.iloc[27000:,:4]*=1.5
        a=comparison_policies(frame,feature_bank(frame));b=comparison_policies(altered,feature_bank(altered))
        for model in a:
            self.assertEqual({i:v for i,v in a[model].items() if i<=27000},{i:v for i,v in b[model].items() if i<=27000})
            period=240 if model.startswith('T') else 60
            self.assertTrue(all(i%period==1 for i in a[model]))
