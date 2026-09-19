import copy
import unittest
import pandas as pd
from app.research.diagnostics.funding_tail import ranks,signals,verify_ranks,decision_map,EIGHT,WINDOW


def tape(n=570):
    return [dict(fundingTime=i*EIGHT,fundingRate=str((i%100)/100000),markPrice='100') for i in range(n)]


class FundingTailTests(unittest.TestCase):
    def test_equal_rates_are_midpoint_not_low_tail(self):
        f=tape();[e.update(fundingRate='0') for e in f]
        self.assertTrue(all(r['midrank']==.5 and not r['tail'] for r in ranks(f)))

    def test_exact_decile_tie_boundary(self):
        f=tape(WINDOW+1)
        for i,e in enumerate(f):e['fundingRate']='-1' if i<54 else '1'
        f[-1]['fundingRate']='0'
        self.assertEqual(ranks(f)[0]['midrank'],.1);self.assertTrue(ranks(f)[0]['tail'])
        f[54]['fundingRate']='0'
        self.assertFalse(ranks(f)[0]['tail'])

    def test_future_rate_does_not_change_past_selection(self):
        f=tape();start=pd.Timestamp(WINDOW*EIGHT,unit='ms',tz='UTC');end=pd.Timestamp(len(f)*EIGHT,unit='ms',tz='UTC')
        old=signals(f,start,end);g=copy.deepcopy(f)
        for e in g[560:]:e['fundingRate']='-99'
        new=signals(g,start,end)
        self.assertEqual([r for r in old if r['index']<560],[r for r in new if r['index']<560])

    def test_nonoverlap_and_publication_delay(self):
        f=tape()
        for i,e in enumerate(f):e['fundingRate']=str(-i);e['fundingTime']+=1
        start=pd.Timestamp(WINDOW*EIGHT,unit='ms',tz='UTC');end=pd.Timestamp(len(f)*EIGHT,unit='ms',tz='UTC')
        rows=signals(f,start,end);a=[r for r in rows if r['side']]
        self.assertTrue(a);self.assertTrue(any(r['overlap_suppressed'] for r in rows))
        self.assertTrue(all(b['index']-a['index']==3 for a,b in zip(a,a[1:])))
        self.assertTrue(all(pd.Timestamp(r['entry_time']).value//1_000_000>r['funding_time_ms'] for r in a))
        verify_ranks(f,rows)

    def test_gap_and_duplicate_rejected(self):
        f=tape();f[10]['fundingTime']=f[9]['fundingTime']
        with self.assertRaises(ValueError):ranks(f)

    def test_no_current_observation_in_history(self):
        f=tape(WINDOW+1);f[-1]['fundingRate']='-100'
        r=ranks(f)[0];self.assertEqual(r['midrank'],0);self.assertLess(r['history_last_ms'],r['funding_time_ms'])

    def test_incomplete_last_day_excluded(self):
        f=tape();start=pd.Timestamp(WINDOW*EIGHT,unit='ms',tz='UTC');end=pd.Timestamp(len(f)*EIGHT,unit='ms',tz='UTC')
        self.assertTrue(all(pd.Timestamp(r['exit_time'])<end for r in signals(f,start,end)))

    def test_ignored_signal_does_not_flatten_active_trade(self):
        rows=[dict(side=1,entry_minute=2,exit_minute=1441,decision_close=100,atr=2),
              dict(side=0,entry_minute=482,exit_minute=1921,decision_close=99,atr=2)]
        self.assertEqual(set(decision_map(rows)),{2,1441})


if __name__=='__main__':unittest.main()
