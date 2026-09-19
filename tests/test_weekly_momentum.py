import unittest
import numpy as np
import pandas as pd
from app.research.diagnostics.weekly_momentum import sessions,decisions,verify_signals


class WeeklyMomentumTest(unittest.TestCase):
    def setUp(self):
        index=pd.date_range('2026-01-01',periods=35*1440,freq='min',tz='UTC')
        x=100+np.arange(len(index))*.001+np.sin(np.arange(len(index))/500)
        self.m=pd.DataFrame(dict(o=x,h=x+.2,l=x-.2,c=x+.01,v=1.),index=index)
        self.start,self.end='2026-01-12T00:00Z','2026-02-02T00:00Z'

    def test_signal_and_independent_atr(self):
        rows=sessions(self.m,self.start,self.end)
        self.assertEqual(len(rows),2)
        self.assertEqual(verify_signals(self.m,rows)['status'],'PASS')
        self.assertTrue(all(r['side']==1 for r in rows))

    def test_future_prices_do_not_change_past_signal(self):
        a=sessions(self.m,self.start,self.end)
        changed=self.m.copy();changed.loc[changed.index>=pd.Timestamp(a[0]['boundary']),['o','h','l','c']]*=2
        b=sessions(changed,self.start,self.end)
        self.assertEqual(a[0],b[0])

    def test_partial_origin_and_incomplete_warmup_block(self):
        partial=self.m.iloc[31:].drop(self.m.index[1000])
        rows=sessions(partial,self.start,self.end)
        self.assertEqual(verify_signals(partial,rows)['status'],'PASS')

    def test_neutral_week_and_no_reentry(self):
        b=pd.Timestamp(self.start)
        self.m.at[b-pd.Timedelta(minutes=1),'c']=self.m.at[b-pd.Timedelta(days=7,minutes=1),'c']
        rows=sessions(self.m,self.start,self.end);self.assertEqual(rows[0]['side'],0)
        d=decisions(rows,'MOMENTUM')
        self.assertNotIn(rows[1]['entry_minute']+1,d)
        self.assertEqual(d[rows[1]['exit_minute']][0],0)
        self.assertEqual(rows[1]['exit_minute']-rows[1]['entry_minute'],10079)


if __name__=='__main__':unittest.main()
