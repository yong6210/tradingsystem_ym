import unittest,json
from pathlib import Path
import numpy as np
import pandas as pd
from app.research.diagnostics.inventory_lab import build_features,fit_monthly_ridge,intent,simulate

def config():return json.loads(Path('configs/research/e052_inventory_lab.json').read_text())
class LabTest(unittest.TestCase):
    def fixture(self,n=18):
        idx=pd.date_range('2024-09-01T00:01:00Z',periods=n,freq='min')
        m=pd.DataFrame({'o':60000.,'h':60001.,'l':59999.,'c':60000.,'v':1.},index=idx)
        f=pd.DataFrame({'direction':1.,'er':.5,'atr':100.,'rsi':50.,'z':0.,'bull':1.,'bear':0.,'sweep':0.,'retest':0.,'range':0.,'ridge':0.,'decision':(idx.minute%3==1).astype(int)},index=idx)
        return m,m.copy(),f
    def run_case(self,m,k,f,family='trend'):
        return simulate(m,k,f,{},config(),family,'inventory','base',0,m.index[0],m.index[-1]+pd.Timedelta(minutes=1))
    def test_higher_direction_not_overridden_by_micro(self):
        m,k,f=self.fixture();v=f.iloc[0].to_dict();v['sweep']=-1;v['range']=-1
        self.assertEqual(intent(v,'trend'),1);self.assertEqual(intent(v,'sweep'),-1)
    def test_three_lots_capacity_no_four_lot_minimum(self):
        m,k,f=self.fixture();f['atr']=700
        r,l,_,cs=self.run_case(m,k,f);self.assertTrue(cs);self.assertEqual(cs[0]['capacity'],.003)
        opening=next(e for e in l if e.get('reason')=='open');self.assertEqual(opening['new_qty'],.001)
    def test_upper_timeframe_flip(self):
        m,k,f=self.fixture();f.loc[f.index[3]:,'direction']=-1
        r,l,_,_=self.run_case(m,k,f);self.assertEqual(r['flips'],1);self.assertEqual(r['short_campaigns'],1)
    def test_retest_no_signal_is_valid(self):
        m,k,f=self.fixture();r,*_=self.run_case(m,k,f,'retest');self.assertEqual(r['fills'],0)
    def test_trim_and_reload_keep_core(self):
        m,k,f=self.fixture();m.iloc[3:9,0:4]=[60300,60301,60299,60300]
        f.loc[f.index[3]:f.index[8],['rsi','bull','bear']]=[80,0,1]
        m.iloc[9:,0:4]=[60000,60001,59999,60000];f.loc[f.index[9]:,['rsi','bull','bear']]=[30,1,0];k=m.copy()
        r,l,_,_=self.run_case(m,k,f);self.assertGreater(r['trims'],0);self.assertGreater(r['reloads'],0)
        self.assertTrue(all(e['new_qty']>0 for e in l if e.get('reason')=='trim'))
    def test_sweep_override_does_not_flip_back_next_bar(self):
        m,k,f=self.fixture();f.loc[f.index[3]:f.index[5],'sweep']=-1
        r,l,_,_=self.run_case(m,k,f,'sweep');self.assertEqual(r['flips'],1)
    def test_halt_prevents_reopen(self):
        m,k,f=self.fixture();m.iloc[2:,0:4]=[50000,50001,49999,50000];k=m.copy()
        r,_,_,_=self.run_case(m,k,f);self.assertTrue(r['halted']);self.assertEqual(r['campaigns'],1)
    def test_causal_features(self):
        idx=pd.date_range('2024-01-01',periods=12000,freq='min',tz='UTC');p=np.arange(len(idx))*.01+50000
        m=pd.DataFrame({'o':p,'h':p+3,'l':p-3,'c':p+1,'v':1.},index=idx);a=build_features(m);cut=idx[11000];m.loc[cut:,'c']*=1.2
        b=build_features(m);pd.testing.assert_frame_equal(a.loc[:cut],b.loc[:cut])
    def test_ridge_labels_purged_and_future_does_not_change_fit(self):
        idx=pd.date_range('2024-01-20',periods=14*1440,freq='min',tz='UTC');p=50000+np.sin(np.arange(len(idx))/30)*100
        m=pd.DataFrame({'o':p},index=idx)
        f=pd.DataFrame({k:np.sin(np.arange(len(idx))/(10+i)) for i,k in enumerate(['r3','r15','r60','direction','er','z','vol_ratio'])},index=idx);f['decision']=(idx.minute%3==1).astype(int);f['ridge']=0.;f['ridge_forecast']=0.
        a=f.copy();logs=fit_monthly_ridge(m,a,'2024-02-01T00:00Z','2024-02-02T00:00Z')
        m.loc['2024-02-01':,'o']*=2;b=f.copy();other=fit_monthly_ridge(m,b,'2024-02-01T00:00Z','2024-02-02T00:00Z')
        self.assertEqual(logs[0]['coef'],other[0]['coef']);self.assertLess(pd.Timestamp(logs[0]['last_label_maturity']),pd.Timestamp('2024-01-31T00:00Z'))

if __name__=='__main__':unittest.main()
