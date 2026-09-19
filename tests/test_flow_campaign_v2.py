import unittest
import numpy as np
import pandas as pd
from app.research.diagnostics.flow_campaign_v2 import features,adaptive_add,reduction_target,thesis_failed,simulate
from app.research.diagnostics.intraday_inventory_v1 import Account
from app.research.diagnostics.multiscale_profile import Zone

C=dict(initial_equity=1000,fee_bps=2.5,tick=.1,lot_step=.001,monthly_operating=2,
       halt_drawdown=.04,campaign_risk=.01,margin_cap=.6,costs={'base':[2,0]})

class FlowCampaignTests(unittest.TestCase):
    def test_wider_invalidation_reduces_quantity(self):
        a=Account(C,.0002);z=Zone(59900,60000,59950,.2,'day')
        narrow=adaptive_add(a,1,60100,60100,Zone(59000,59100,59050,.2,'week'),[z],z,C,3,1000)[0]
        wide=adaptive_add(a,1,60100,60100,Zone(57000,57100,57050,.2,'week'),[z],z,C,3,1000)[0]
        self.assertGreater(narrow,wide)

    def test_realized_loss_does_not_reset_budget(self):
        a=Account(C,.0002);a.cash=989;z=Zone(59900,60000,59950,.2,'day')
        qty,info=adaptive_add(a,1,60100,60100,z,[z],z,C,3,1000)
        self.assertEqual(qty,0);self.assertEqual(info['remaining_risk_usdc'],0)

    def test_opposite_root_rejects_add(self):
        a=Account(C,.0002);z=Zone(61000,61100,61050,.2,'day')
        self.assertEqual(adaptive_add(a,1,60100,60100,z,[z],z,C,3,1000)[0],0)

    def test_reduction_varies_with_exposure(self):
        low,f1=reduction_target(.02,.1,False,.001);high,f2=reduction_target(.02,.9,True,.001)
        self.assertLess(high,low);self.assertGreater(f2,f1)

    def test_intraday_pullback_does_not_invalidate_hourly_thesis(self):
        z=Zone(59000,59150,59075,.3,'week')
        self.assertFalse(thesis_failed(z,1,dict(h_close=59010,h_previous_close=58990,b_c=58000)))
        self.assertTrue(thesis_failed(z,1,dict(h_close=58980,h_previous_close=58990)))

    def test_causal_features(self):
        idx=pd.date_range('2026-01-01',periods=32*1440,freq='min',tz='UTC');px=60000+np.sin(np.arange(len(idx))/500)*500
        m=pd.DataFrame(dict(o=px,h=px+10,l=px-10,c=px+1,v=1.),index=idx)
        full=features(m);prefix=features(m.iloc[:-2000]);pd.testing.assert_frame_equal(full.loc[prefix.index],prefix)

    def test_position_can_survive_more_than_one_day(self):
        idx=pd.date_range('2026-08-01T00:00Z',periods=3000,freq='min')
        m=pd.DataFrame(dict(o=60160.,h=60170.,l=60140.,c=60160.,v=100.),index=idx)
        f=pd.DataFrame([dict(flow=1,decision=int(i%3==0),anchor_ms=float('nan'),b_l=60140,b_h=60170,b_c=60160,b_o=60145,
                            b_previous_close=60145,m_c=60160,m_o=60150,m_previous_close=60155,m_previous_high=60159,
                            m_previous_low=60140,h_close=60160,h_previous_close=60160) for i in range(len(idx))],index=idx)
        class Profiles:
            def snapshot(self,t,anchor):return [Zone(60100,60150,60125,.3,'day'),Zone(59000,59150,59075,.3,'week'),Zone(60700,60850,60775,.3,'week')],t-60000
        r,ledger,_,campaigns,_=simulate(m,m,f,Profiles(),{},C,3,'base','adaptive')
        self.assertEqual(len(campaigns),1);self.assertGreater(r['max_campaign_hours'],48)
        self.assertEqual(campaigns[0]['reason'],'end');self.assertNotIn('time_exit',[x.get('reason') for x in ledger])

    def test_repeated_opposite_reactions_keep_core_until_thesis_fails(self):
        idx=pd.date_range('2026-08-01T00:00Z',periods=40,freq='min')
        p=np.array([60160 if i<3 else 60580 for i in range(len(idx))],dtype=float)
        m=pd.DataFrame(dict(o=p,h=p+10,l=p-10,c=p,v=100.),index=idx)
        rows=[]
        for i in range(len(idx)):
            v=dict(flow=1,decision=int(i%3==0),anchor_ms=float('nan'),b_l=60140,b_h=60170,b_c=60160,b_o=60145,
                   b_previous_close=60145,m_c=60160,m_o=60150,m_previous_close=60155,m_previous_high=60159,
                   m_previous_low=60140,h_close=60160,h_previous_close=60160)
            if i>=3:v.update(b_l=60570,b_h=60610,b_c=60580,b_o=60605,b_previous_close=60605,
                             m_c=60580,m_o=60595,m_previous_close=60590,m_previous_low=60585,m_previous_high=60600)
            if i>=36:v.update(h_close=58900,h_previous_close=58890)
            rows.append(v)
        class Profiles:
            def snapshot(self,t,anchor):return [Zone(60100,60150,60125,.3,'day'),Zone(59000,59150,59075,.3,'week'),Zone(60600,60750,60675,.3,'week')],t-60000
        _,ledger,_,campaigns,_=simulate(m,m,pd.DataFrame(rows,index=idx),Profiles(),{},C,3,'base','adaptive')
        fills=[r for r in ledger if r['kind']=='fill']
        self.assertEqual(len(campaigns),1)
        self.assertEqual(campaigns[0]['reason'],'hourly_thesis_failure')
        self.assertEqual(fills[-1]['time_ms'],int(idx[36].timestamp()*1000))
        self.assertEqual(fills[-1]['old_qty'],.001)
        self.assertTrue(all(r['new_qty']>0 for r in fills[:-1]))

if __name__=='__main__':unittest.main()
