import unittest
import numpy as np
import pandas as pd
from app.research.diagnostics.intraday_inventory_v2 import features,simulate,location_signal,sufficient_room,Account
from tests.test_intraday_inventory_v1 import config as old_config

def config():
    c=old_config();c.update(minimum_room_fraction=.0045,reload_spacing_fraction=.0015,reentry_cooldown_minutes=6);return c

class LocationInventoryTest(unittest.TestCase):
    def fixture(self,n=18):
        idx=pd.date_range('2024-09-01T00:01:00Z',periods=n,freq='min')
        m=pd.DataFrame({'o':10000.,'h':10001.,'l':9999.,'c':10000.,'v':1.},index=idx)
        f=pd.DataFrame({'bias':1.,'large':1.,'atr':10.,'breakout':0.,'resistance':10100.,'support':9990.,'vwap':9990.,'po':9998.,'ph':10001.,'pl':9990.,'pc':10000.,'decision':(idx.minute%3==1).astype(int),'three_up':1.,'three_down':0.},index=idx)
        return m,m.copy(),f
    def run_case(self,m,k,f):return simulate(m,k,f,{},config(),3,'base',0,'inventory',m.index[0],m.index[-1]+pd.Timedelta(minutes=1))
    def test_no_entry_from_stale_direction_alone(self):
        m,k,f=self.fixture();f['three_up']=0
        r,*_=self.run_case(m,k,f);self.assertEqual(r['fills'],0)
    def test_cost_room_gate(self):
        m,k,f=self.fixture();v=f.iloc[0].to_dict()
        self.assertEqual(location_signal(v),1);self.assertTrue(sufficient_room(v,10000,1,config()))
        v['resistance']=10040;self.assertFalse(sufficient_room(v,10000,1,config()))
    def test_countertrend_support_can_enter(self):
        m,k,f=self.fixture();f['bias']=-1;f['large']=-1
        r,*_=self.run_case(m,k,f);self.assertGreater(r['long_campaigns'],0)
    def test_fresh_opposite_rejection_flips(self):
        m,k,f=self.fixture();f.loc[f.index[3]:,['po','ph','pl','pc','resistance','support','three_up','three_down']]=[10002,10021,9999,10000,10020,9900,0,1]
        r,l,_,_=self.run_case(m,k,f);self.assertEqual(r['flips'],1)
        closes=[x for x in l if x.get('reason')=='flip_close'];opens=[x for x in l if x.get('reason')=='open' and x['new_qty']<0]
        self.assertEqual(closes[0]['time_ms'],opens[0]['time_ms'])
    def test_reentry_waits_six_minutes(self):
        m,k,f=self.fixture();m.iloc[2:,0:4]=[9800,9801,9799,9800];k=m.copy()
        f.loc[f.index[2]:,['po','ph','pl','pc','resistance','support','vwap']]=[9798,9801,9790,9800,9900,9790,9790]
        r,l,_,_=self.run_case(m,k,f);ex=next(x for x in l if x.get('reason')=='stop')
        opens=[x for x in l if x.get('reason')=='open' and x['time_ms']>ex['time_ms']]
        self.assertTrue(opens);self.assertGreaterEqual(opens[0]['time_ms']-ex['time_ms'],360000)
    def test_trim_rejects_same_price_reload_then_allows_cheaper(self):
        m,k,f=self.fixture();m.iloc[3:,0:4]=[10050,10051,10049,10050]
        f.loc[f.index[3]:f.index[5],['po','pc','ph','resistance']]=[10070,10055,10065,10060]
        f.loc[f.index[6]:,['po','pc','pl','support','vwap','resistance']]=[10049,10051,10049,10050,10050,10150]
        m.iloc[9:,0:4]=[10030,10031,10029,10030]
        f.loc[f.index[9]:,['po','pc','pl','support','vwap']]=[10029,10031,10029,10030,10030]
        k=m.copy();r,l,_,_=self.run_case(m,k,f)
        trims=[x for x in l if x.get('reason')=='trim'];adds=[x for x in l if x.get('reason')=='reload'];self.assertTrue(trims);self.assertTrue(adds)
        self.assertGreaterEqual(trims[0]['reference']-adds[0]['reference'],adds[0]['reference']*.0015)
    def test_causal_features(self):
        idx=pd.date_range('2024-01-01',periods=12000,freq='min',tz='UTC');v=np.arange(len(idx))*.01+50000
        m=pd.DataFrame({'o':v,'h':v+3,'l':v-3,'c':v+1,'v':1.},index=idx);a=features(m);cut=idx[11000];m.loc[cut:,'c']*=1.2
        b=features(m);pd.testing.assert_frame_equal(a.loc[:cut],b.loc[:cut])
    def test_partial_short_account_identity(self):
        a=Account(config(),0);a.adjust(0,-2,100,'open');a.adjust(1,-1,90,'trim');a.adjust(2,-2,110,'reload');a.adjust(3,0,100,'close')
        self.assertAlmostEqual(a.realized,20);self.assertAlmostEqual(a.cash,1020-.00025*600)

if __name__=='__main__':unittest.main()
