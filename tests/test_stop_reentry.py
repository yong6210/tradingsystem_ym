from dataclasses import replace
import unittest
import pandas as pd
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.diagnostics.intrabar_engine import simulate as original
from app.research.diagnostics.stop_reentry_engine import simulate
from app.research.diagnostics.stop_reentry_audit import verify


class StopReentryTests(unittest.TestCase):
    def run_case(self,rows,signals,enabled=True,risk=None,path='OHLC'):
        frame=pd.DataFrame(rows,columns=['o','h','l','c'],index=pd.date_range('2025-01-01',periods=len(rows),freq='min',tz='UTC'))
        risk=risk or Risk(initial=1000,cycle_fraction=.02,aggregate_fraction=.02,exposure_multiple=1,daily_stop=.5,warning=.5,halt=.8,
            minimum_qty=1,step=1,minimum_notional=1,stop_atr=1,maximum_hold_minutes=100)
        args=(frame,signals,frame.index[0],frame.index[-1]+pd.Timedelta(minutes=1),Costs(0,0,0,.01),risk)
        r=simulate(*args,path=path,block_stop_reentry=enabled)
        verify(r,signals,0,len(rows),enabled)
        return r,args

    def test_same_direction_after_price_stop_blocked(self):
        r,_=self.run_case([(100,100,100,100),(100,100,89,90),(100,100,100,100),(100,100,100,100)],{0:(1,100,10),2:(1,100,10)})
        self.assertEqual([e['kind'] for e in r['reentry_events']],['LOCK','BLOCK'])
        self.assertEqual(len(r['trades']),1)

    def test_neutral_does_not_unlock_opposite_does(self):
        rows=[(100,100,100,100),(100,100,89,90)]+[(100,100,100,100)]*4
        r,_=self.run_case(rows,{0:(1,100,10),2:(0,100,10),3:(1,100,10),4:(-1,100,10)})
        self.assertEqual([e['kind'] for e in r['reentry_events']],['LOCK','BLOCK','UNLOCK'])
        self.assertEqual([t['side'] for t in r['trades']],[1,-1])

    def test_gap_stop_and_opposite_same_minute_cannot_enter(self):
        r,_=self.run_case([(100,100,100,100),(80,80,80,80),(80,80,80,80)],{0:(1,100,10),1:(-1,80,10),2:(-1,80,10)})
        self.assertEqual(r['trades'][0]['reason'],'price_stop_gap')
        self.assertEqual(r['trades'][1]['entry_minute'],2)
        self.assertEqual([e['kind'] for e in r['reentry_events']],['LOCK','UNLOCK'])

    def test_short_lock_mirror(self):
        r,_=self.run_case([(100,100,100,100),(100,111,100,110),(100,100,100,100)],{0:(-1,100,10),2:(-1,100,10)},path='OLHC')
        self.assertEqual([e['side'] for e in r['reentry_events']],[-1,-1])

    def test_time_exit_does_not_lock(self):
        rows=[(100,100,100,100)]*5
        risk=Risk(maximum_hold_minutes=1)
        # Production order units at BTC price.
        rows=[(60000,60000,60000,60000)]*5
        r,_=self.run_case(rows,{0:(1,60000,500),2:(1,60000,500)},risk=risk)
        self.assertEqual(r['reentry_events'],[]);self.assertEqual(len(r['trades']),2)

    def test_disabled_mode_exactly_matches_frozen_engine(self):
        for path in ['OHLC','OLHC']:
            r,args=self.run_case([(100,100,100,100),(100,100,89,90),(100,100,100,100),(100,100,100,100)],{0:(1,100,10),2:(1,100,10)},enabled=False,path=path)
            old=original(*args,path=path)
            self.assertEqual({k:v for k,v in r.items() if k!='reentry_events'},old)

    def test_independent_audit_rejects_missing_block(self):
        signals={0:(1,100,10),2:(1,100,10)}
        r,_=self.run_case([(100,100,100,100),(100,100,89,90),(100,100,100,100)],signals)
        r['reentry_events'].pop()
        with self.assertRaisesRegex(ValueError,'timeline'):verify(r,signals,0,3,True)

    def test_no_future_unlock(self):
        rows=[(100,100,100,100),(100,100,89,90)]+[(100,100,100,100)]*4
        signals={0:(1,100,10),2:(1,100,10),3:(1,100,10),4:(-1,100,10)}
        r,_=self.run_case(rows,signals)
        self.assertEqual([e['minute'] for e in r['reentry_events'] if e['kind']=='BLOCK'],[2,3])
