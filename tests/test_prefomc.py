import unittest
import pandas as pd
from app.research.diagnostics.prefomc import calendar,attach_inputs


class CalendarTests(unittest.TestCase):
    def test_calendar_complete_and_preannounced(self):
        rows=calendar();self.assertEqual(len(rows),32)
        self.assertEqual(len({r['meeting'] for r in rows}),16)
        for r in rows:
            self.assertLess(pd.Timestamp(r['known_on'],tz='UTC'),pd.Timestamp(r['entry_time']))
            self.assertEqual((pd.Timestamp(r['exit_time'])-pd.Timestamp(r['entry_time'])).total_seconds(),1438*60)
            self.assertLess(pd.Timestamp(r['exit_time']),pd.Timestamp(r['release_time']))

    def test_dst_control_keeps_local_hour(self):
        rows={r['model']:r for r in calendar() if r['meeting']=='2024-11-07'}
        self.assertEqual(rows['FOMC']['entry_time'],'2024-11-06T19:01:00+00:00')
        self.assertEqual(rows['PRIOR_WEEK']['entry_time'],'2024-10-30T18:01:00+00:00')
        self.assertEqual(rows['FOMC']['exit_time'],'2024-11-07T18:59:00+00:00')

    def test_nonoverlap(self):
        rows=sorted(calendar(),key=lambda r:r['entry_time'])
        for a,b in zip(rows,rows[1:]):self.assertLess(a['exit_time'],b['entry_time'])

    def test_completed_features_only_and_future_invariance(self):
        row=calendar()[0];entry=pd.Timestamp(row['entry_time'])
        idx=pd.date_range(entry-pd.Timedelta(days=1),pd.Timestamp(row['exit_time'])+pd.Timedelta(days=1),freq='min')
        minutes=pd.DataFrame({'c':100.},index=idx)
        fidx=pd.date_range(idx[0].floor('4h'),idx[-1].ceil('4h'),freq='4h')
        features=pd.DataFrame({'atr':2.},index=fidx)
        first=attach_inputs(minutes,features,[row])[0]
        self.assertEqual(first['feature_time'],'2024-09-17T16:00:00+00:00')
        minutes.loc[entry:,'c']=999.;features.loc[features.index>entry,'atr']=99.
        self.assertEqual(attach_inputs(minutes,features,[row])[0],first)

    def test_missing_boundary_rejected(self):
        row=calendar()[0];idx=pd.date_range(row['entry_time'],row['exit_time'],freq='min')
        minutes=pd.DataFrame({'c':100.},index=idx[:-1]);features=pd.DataFrame({'atr':2.},index=idx[::240])
        with self.assertRaises(ValueError):attach_inputs(minutes,features,[row])
