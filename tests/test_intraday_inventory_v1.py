import unittest
import numpy as np
import pandas as pd
from app.research.diagnostics.intraday_inventory_v1 import Account,features,simulate

def config():
    return {'initial_equity':1000,'fee_bps':2.5,'tick':.1,'lot_step':.001,'min_qty':.001,'max_qty':50,'min_notional':50,'costs':{'base':{'slippage_bps':2,'extra_funding_bps':0}},'halt_drawdown':.04,'max_hold_minutes':1440,'max_initial_stop_risk':.005}

class InventoryTest(unittest.TestCase):
    def test_partial_long_average_and_cash(self):
        a=Account(config(),0);a.adjust(0,1,100,'open');a.adjust(1,2,110,'add')
        self.assertEqual(a.avg,105);a.adjust(2,1,120,'trim');self.assertEqual(a.avg,105)
        a.adjust(3,0,90,'close');self.assertAlmostEqual(a.realized,0);self.assertAlmostEqual(a.cash,1000-.00025*420)
    def test_short_reload_and_close(self):
        a=Account(config(),0);a.adjust(0,-2,100,'open');a.adjust(1,-1,90,'trim');a.adjust(2,-2,110,'reload');a.adjust(3,0,100,'close')
        self.assertAlmostEqual(a.realized,20);self.assertAlmostEqual(a.cash,1020-.00025*600)
    def test_flip_requires_close(self):
        a=Account(config(),0);a.adjust(0,.01,100,'open')
        with self.assertRaises(ValueError):a.adjust(1,-.01,100,'flip')
        a.adjust(1,0,100,'close');a.adjust(1,-.01,100,'open');self.assertLess(a.q,0)
    def test_causality(self):
        idx=pd.date_range('2024-01-01',periods=12000,freq='min',tz='UTC');v=np.arange(len(idx))*.01+50000
        m=pd.DataFrame({'o':v,'h':v+3,'l':v-3,'c':v+1,'v':1.},index=idx)
        a=features(m);cut=idx[11000];m.loc[cut:,'c']*=1.2;m.loc[cut:,'v']*=100
        b=features(m);pd.testing.assert_frame_equal(a.loc[:cut],b.loc[:cut])
    def fixture(self):
        idx=pd.date_range('2024-09-01T00:01:00Z',periods=9,freq='min')
        m=pd.DataFrame({'o':10000.,'h':10001.,'l':9999.,'c':10000.,'v':1.},index=idx)
        f=pd.DataFrame({'bias':1.,'large':1.,'atr':20.,'breakout':0.,'resistance':10010.,'support':9900.,'vwap':9990.,'po':9998.,'ph':10001.,'pl':9990.,'pc':10000.,'decision':(idx.minute%3==1).astype(int)},index=idx)
        return m,m.copy(),f
    def test_flip_long_to_short(self):
        m,k,f=self.fixture();f.iloc[3:,f.columns.get_loc('breakout')]=-1;f.iloc[3:,f.columns.get_loc('po')]=10002
        r,l,d,c=simulate(m,k,f,{},config(),3,'base',0,'inventory',m.index[0],m.index[-1]+pd.Timedelta(minutes=1))
        self.assertEqual(r['flips'],1);self.assertEqual(r['long_campaigns'],1);self.assertEqual(r['short_campaigns'],1)
        self.assertLess(c[-1]['direction'],0)
    def test_trim_then_reload(self):
        m,k,f=self.fixture();m.iloc[3:,0:4]=[10050,10051,10049,10050];k=m.copy()
        f.iloc[3:6,f.columns.get_loc('po')]=10070;f.iloc[3:6,f.columns.get_loc('pc')]=10055
        f.iloc[3:6,f.columns.get_loc('ph')]=10065;f.iloc[3:6,f.columns.get_loc('resistance')]=10060
        f.iloc[6:,f.columns.get_loc('po')]=10049;f.iloc[6:,f.columns.get_loc('pc')]=10051
        f.iloc[6:,f.columns.get_loc('vwap')]=10050;f.iloc[6:,f.columns.get_loc('pl')]=10049
        r,l,_,_=simulate(m,k,f,{},config(),3,'base',0,'inventory',m.index[0],m.index[-1]+pd.Timedelta(minutes=1))
        self.assertGreaterEqual(r['trims'],1);self.assertGreaterEqual(r['reloads'],1)
    def test_gap_stop_not_filled_at_threshold(self):
        m,k,f=self.fixture();m.iloc[2:,0:4]=[9800,9801,9799,9800];k=m.copy()
        r,l,_,_=simulate(m,k,f,{},config(),3,'base',0,'inventory',m.index[0],m.index[-1]+pd.Timedelta(minutes=1))
        exits=[e for e in l if e['kind']=='fill' and e['reason']=='stop'];self.assertTrue(exits);self.assertLess(exits[0]['price'],9800)
    def test_funding_sign(self):
        m,k,f=self.fixture();t=int(m.index[2].timestamp()*1000)
        r,l,_,_=simulate(m,k,f,{t:{'time_ms':t,'mark':10000.,'rate':.001}},config(),3,'base',0,'inventory',m.index[0],m.index[-1]+pd.Timedelta(minutes=1))
        e=next(e for e in l if e['kind']=='funding');self.assertAlmostEqual(e['cash_delta'],-e['qty']*10)
    def test_minimum_order_rejection(self):
        m,k,f=self.fixture();c=config();c['min_notional']=100000
        r,*_=simulate(m,k,f,{},c,3,'base',0,'inventory',m.index[0],m.index[-1]+pd.Timedelta(minutes=1));self.assertEqual(r['fills'],0);self.assertGreater(r['entry_rejections'],0)
    def test_account_halt_does_not_reopen(self):
        m,k,f=self.fixture();m.iloc[2:,0:4]=[8000,8001,7999,8000];k=m.copy()
        r,l,_,_=simulate(m,k,f,{},config(),3,'base',0,'inventory',m.index[0],m.index[-1]+pd.Timedelta(minutes=1))
        self.assertTrue(r['halted']);self.assertEqual(r['campaigns'],1);self.assertGreater(r['max_drawdown_envelope_pct'],5)

if __name__=='__main__':unittest.main()
