import unittest
import numpy as np
import pandas as pd
from app.research.diagnostics.multiscale_profile import Zone
from app.research.diagnostics.context_timing_signals import context,timing,entry_intent,features,capacity_limit
from app.research.diagnostics.context_timing_inventory import simulate


class ContextTimingTests(unittest.TestCase):
    def values(self):
        return dict(daily=1,four_hour=-1,hour=-1,quarter=1,b_l=140,b_h=170,b_c=160,b_o=145,
                    b_previous_close=145,m_c=160,m_o=150,m_previous_close=155)

    def test_disagreement_does_not_block_entry(self):
        v=self.values();z=Zone(100,150,125,.3,'week')
        self.assertEqual(context(v),0)
        side,zone,bias=entry_intent([z],v)
        self.assertEqual(side,1);self.assertEqual(zone,z)

    def test_counter_context_entry_allowed_with_smaller_add_limit(self):
        v=self.values();v.update(daily=-1,four_hour=-1,hour=-1,quarter=-1)
        side,_,bias=entry_intent([Zone(100,150,125,.3,'week')],v)
        self.assertEqual((side,bias),(1,-1));self.assertEqual(capacity_limit(side,bias),3)

    def test_reclaim_and_retest_are_separate(self):
        v=self.values();z=Zone(100,150,125,.3,'week')
        self.assertEqual(timing(z,1,v),'reclaim')
        v['b_previous_close']=160;self.assertEqual(timing(z,1,v),'retest_hold')

    def test_candle_color_alone_is_not_enough(self):
        v=self.values();v['m_previous_close']=170;z=Zone(100,150,125,.3,'week')
        self.assertIsNone(timing(z,1,v))
        self.assertEqual(entry_intent([z],v)[0],0)
        self.assertEqual(entry_intent([z],v,strict=False)[0],1)

    def test_no_zone_no_entry(self):
        self.assertEqual(entry_intent([],self.values())[0],0)

    def test_short_rejection(self):
        v=self.values();v.update(b_h=110,b_l=80,b_c=90,b_o=105,b_previous_close=105,m_c=90,m_o=100,m_previous_close=95)
        self.assertEqual(timing(Zone(100,150,125,.3,'week'),-1,v),'rejection')

    def test_future_features_do_not_leak(self):
        idx=pd.date_range('2026-01-01',periods=32*1440,freq='min',tz='UTC')
        p=60000+np.sin(np.arange(len(idx))/200)*500
        m=pd.DataFrame(dict(o=p,h=p+10,l=p-10,c=p+1,v=1.),index=idx)
        full=features(m);prefix=features(m.iloc[:-2000])
        pd.testing.assert_frame_equal(full.loc[prefix.index],prefix)

    def test_engine_can_open_with_disagreeing_context(self):
        idx=pd.date_range('2026-08-01T00:00Z',periods=4,freq='min')
        m=pd.DataFrame(dict(o=60160.,h=60170.,l=60140.,c=60160.,v=10.),index=idx)
        v=self.values();v.update(b_l=60140,b_h=60170,b_c=60160,b_o=60145,b_previous_close=60145,
                               m_c=60160,m_o=60150,m_previous_close=60155,atr=10.,anchor_ms=float('nan'),decision=1)
        f=pd.DataFrame([v]*len(idx),index=idx)
        class StubProfiles:
            def snapshot(self,t,anchor):return [Zone(60100,60150,60125,.3,'week'),Zone(60500,60650,60575,.3,'week')],t-60000
        c=dict(initial_equity=1000,fee_bps=2.5,tick=.1,monthly_operating=2,halt_drawdown=.04,costs={'base':[2,0]})
        result,ledger,_,_,_=simulate(m,m,f,StubProfiles(),{},c,3,'base','context_timing')
        self.assertEqual(result['campaigns'],1)
        self.assertEqual(ledger[1]['reason'],'profile_one_tenth_open')
        self.assertEqual(ledger[1]['higher_direction'],0)

    def test_engine_five_three_five_without_forced_flip(self):
        idx=pd.date_range('2026-08-01T00:00Z',periods=23,freq='min')
        prices=[];rows=[]
        for i in range(len(idx)):
            stage=min(i//3,7)
            p=[60100,60090,60080,60070,60060,60690,60080,60070][stage]
            prices.append(p)
            v=dict(daily=1,four_hour=1,hour=-1,quarter=-1,atr=20.,anchor_ms=float('nan'),decision=int(i%3==0),
                   b_l=59990,b_h=p+10,b_c=p,b_o=59995,b_previous_close=59995,
                   m_c=p,m_o=p-5,m_previous_close=p-2)
            if stage==5:v.update(b_l=60680,b_h=60710,b_c=60690,b_o=60705,b_previous_close=60705,m_c=60690,m_o=60700,m_previous_close=60700)
            rows.append(v)
        p=np.array(prices,dtype=float)
        m=pd.DataFrame(dict(o=p,h=p+10,l=p-10,c=p,v=100.),index=idx)
        class StubProfiles:
            def snapshot(self,t,anchor):return [Zone(59850,60000,59925,.3,'day'),Zone(59000,59150,59075,.3,'week'),Zone(60700,60850,60775,.3,'week')],t-60000
        c=dict(initial_equity=1000,fee_bps=2.5,tick=.1,monthly_operating=2,halt_drawdown=.04,costs={'base':[2,0]})
        _,ledger,_,_,_=simulate(m,m,pd.DataFrame(rows,index=idx),StubProfiles(),{},c,3,'base','context_timing')
        fills=[r for r in ledger if r['kind']=='fill']
        self.assertEqual(fills[5]['reason'],'opposing_zone_trim_to_three')
        self.assertAlmostEqual(fills[4]['allocated_units_after'],5)
        self.assertAlmostEqual(fills[5]['allocated_units_after'],3)
        self.assertAlmostEqual(fills[7]['allocated_units_after'],5)
        self.assertNotIn('confirmed_profile_flip',[r['reason'] for r in fills])

if __name__=='__main__':unittest.main()
