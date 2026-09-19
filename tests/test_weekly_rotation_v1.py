import unittest
import pandas as pd
from app.research.diagnostics.weekly_rotation_v1 import signals,simulate,rounded

class RotationTest(unittest.TestCase):
    def fixture(self, prices, start='2024-09-30T01:00:00Z'):
        clocks=pd.date_range(start,periods=len(prices),freq='h').asi8//10**6
        frame=pd.DataFrame(prices,columns=['open','high','low','close']); frame['open_time']=clocks
        c={'symbols':['BTCUSDC'],'initial_equity':1000,'fee_bps_per_fill':2.5,'cost_cases':{'base':{'slippage_bps':2,'extra_funding_bps':0}},'account_halt_drawdown':.03,'atr_multiplier':3,'risk_fraction':.005,'max_notional_fraction':.5,'start':'2024-09-01','momentum_days':28,'atr_days':20}
        rule={'BTCUSDC':{'tickSize':.01,'stepSize':.001,'minQty':.001,'maxQty':1000,'minNotional':5}}
        sig={str(clocks[0]):{'BTCUSDC':{'momentum':.1,'atr':1,'close':100}}}
        return {'BTCUSDC':frame},rule,{'BTCUSDC':{}},sig,c
    def run_case(self,fixture,path='OHLC'):
        return simulate(*fixture,'rotation','base',0,path)
    def test_gap_stop_uses_open_not_stop(self):
        r,ledger,daily,trades=self.run_case(self.fixture([[100,101,99,100],[90,91,89,90]]))
        self.assertEqual(trades[0]['reason'],'gap_stop'); self.assertLess(trades[0]['exit'],90)
        self.assertGreater(-trades[0]['net'],trades[0]['initial_risk'])
    def test_known_fee_and_cash_arithmetic(self):
        r,ledger,_,trades=self.run_case(self.fixture([[100,100,100,100]]))
        x=trades[0]; expected=x['qty']*(x['exit']-x['entry'])-.00025*x['qty']*(x['entry']+x['exit'])
        self.assertAlmostEqual(r['net_usdc'],expected); self.assertEqual(len(trades),1)
        self.assertAlmostEqual(sum(e['cash_delta'] for e in ledger),r['net_usdc'])
    def test_funding_precedes_exit(self):
        args=self.fixture([[100,101,99,100]]*8)
        t=int(args[0]['BTCUSDC'].open_time.iloc[-1]); args[2]['BTCUSDC'][t//3600000]={'time_ms':t+1,'mark':100,'rate':.01}
        r,ledger,_,trades=self.run_case(args)
        self.assertAlmostEqual(r['funding_net_usdc'],-trades[0]['qty'])
        self.assertEqual([x['kind'] for x in ledger],['entry','funding','exit'])
    def test_minimum_never_rounds_up(self):
        args=self.fixture([[100,101,99,100]]); args[1]['BTCUSDC']['minQty']=10
        r,*_=self.run_case(args); self.assertEqual(r['entry_rejections'],1); self.assertEqual(r['closed_trades'],0)
    def test_stop_intrahour_and_no_same_hour_reentry(self):
        r,_,_,trades=self.run_case(self.fixture([[100,101,90,100]]))
        self.assertEqual(len(trades),1); self.assertEqual(trades[0]['reason'],'stop'); self.assertLessEqual(-trades[0]['net'],5+1e-8)
    def test_halt_on_profit_reversal_differs_by_path(self):
        args=self.fixture([[100,140,99,139]])
        a=self.run_case(args,'OHLC')[0]; b=self.run_case(args,'OLHC')[0]
        self.assertTrue(a['halted']); self.assertFalse(b['halted'])
        self.assertLess(a['net_usdc'],b['net_usdc'])
    def test_future_bars_do_not_change_past_signal(self):
        times=pd.date_range('2024-09-01',periods=40*24,freq='h',tz='UTC')
        f=pd.DataFrame({'open_time':times.asi8//10**6,'open':100.,'high':102.,'low':99.,'close':[100+i/1000 for i in range(len(times))]})
        c=self.fixture([[100,100,100,100]])[-1]; cutoff=int(times[35*24].timestamp()*1000)
        first=signals({'BTCUSDC':f},c); f.loc[f.open_time>=cutoff,'close']=1000
        second=signals({'BTCUSDC':f},c)
        self.assertTrue(first)
        for key,value in first.items():
            if int(key)<cutoff:
                self.assertEqual(value,second[key]); self.assertLess(value['BTCUSDC']['last_input_close_ms'],int(key)-3600000)
    def test_floor(self): self.assertEqual(rounded(.0019,.001),.001)

if __name__=='__main__': unittest.main()
