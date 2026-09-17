import unittest
import numpy as np
import pandas as pd
from app.research.candidate_accounts.policies import entry_conditions,build_policy
from app.research.multistrategy_audit import feature_bank
from app.research.comparison.engine import simulate
from app.research.baseline.risk import Risk
from dataclasses import replace


def fixture():
    index=pd.date_range('2025-01-01',periods=6,freq='15min',tz='UTC')
    f=pd.DataFrame(dict(c=[90.,94.,96.,99.,101.,101.],atr=2.,z=[-3.,-1.,-.8,-.2,.1,.1],
                        mean=100.,high24=110.,low24=80.,high12=108.,low12=82.,volume_ratio=2.),index=index)
    higher=pd.DataFrame(dict(er=.1,ema80=100.),index=index)
    minute=pd.DataFrame(dict(o=100.,h=101.,l=99.,c=100.,v=1.),index=pd.date_range(index[0],periods=100,freq='min'))
    return minute,{15:f,60:f,240:higher}


class CandidateAccountTests(unittest.TestCase):
    def test_confirmation_waits_and_absence_does_not_exit(self):
        minutes,bank=fixture()
        d,_=build_policy(minutes,bank,'S05')
        self.assertNotIn(1,d)
        self.assertEqual(d[16][0],1)
        self.assertNotIn(31,d)
        self.assertNotIn(46,d)
        self.assertEqual(d[61][0],0)

    def test_immediate_and_confirmation_differ(self):
        minutes,bank=fixture()
        a,_=build_policy(minutes,bank,'S04');b,_=build_policy(minutes,bank,'S05')
        self.assertEqual(a[1][0],1);self.assertNotIn(1,b)

    def test_confirmation_past_target_is_rejected(self):
        minutes,bank=fixture();bank[15].loc[bank[15].index[1],'c']=101.
        self.assertFalse(entry_conditions(bank,'S05').event.iloc[1])

    def test_short_symmetry(self):
        minutes,bank=fixture()
        f=bank[15];f['c']=200-f.c;f['z']=-f.z
        d,_=build_policy(minutes,bank,'S05')
        self.assertEqual(d[16][0],-1);self.assertEqual(d[61][0],0)

    def test_regime_exit_before_target(self):
        minutes,bank=fixture();bank[240].loc[bank[240].index[2]:,'er']=.3
        d,_=build_policy(minutes,bank,'S05')
        self.assertEqual(d[31][0],0)

    def test_channel_exit_separate_from_absent_entry(self):
        minutes,bank=fixture()
        f=bank[60];f['c']=[111.,105.,100.,90.,81.,81.]
        d,_=build_policy(minutes,bank,'S02')
        self.assertEqual(d[1][0],1)
        self.assertNotIn(16,d)
        self.assertEqual(d[61][0],0)

    def test_same_direction_requires_new_event_after_stop(self):
        minutes,bank=fixture()
        # Entry1 stops before observation16; no fresh event until later, so no
        # automatic same-direction re-entry at each observation.
        minutes.loc[minutes.index[2],'l']=80
        d,_=build_policy(minutes,bank,'S04')
        r=simulate(minutes,d,minutes.index[0],minutes.index[-1],risk=replace(Risk(),minimum_qty=.001,minimum_notional=1,stop_atr=4))
        self.assertEqual(r['metrics']['cycles'],1)

    def test_future_invariance_and_squeeze_subset(self):
        n=45000
        index=pd.date_range('2025-01-01',periods=n,freq='min',tz='UTC')
        price=60000*np.exp(np.cumsum(np.random.default_rng(29).normal(0,.0007,n)))
        minutes=pd.DataFrame(dict(o=price,h=price+10,l=price-10,c=price,v=np.arange(n)%13+1),index=index)
        changed=minutes.copy();changed.iloc[40000:,:4]*=2
        a,b=feature_bank(minutes),feature_bank(changed)
        s02=entry_conditions(a,'S02');s08=entry_conditions(a,'S08')
        self.assertTrue((~s08.event|s02.event).all())
        for model in ('S04','S05','S02','S08'):
            x,_=build_policy(minutes,a,model);y,_=build_policy(changed,b,model)
            self.assertEqual({i:v for i,v in x.items() if i<=40000},{i:v for i,v in y.items() if i<=40000})
            period=15 if model in ('S04','S05') else 60
            self.assertTrue(all(i%period==1 for i in x))
