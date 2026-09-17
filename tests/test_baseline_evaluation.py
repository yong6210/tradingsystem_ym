"""Independent checks of paired calendar returns and independent run boundaries."""
import unittest
import pandas as pd
from scripts.run_baseline_account import compare_daily
from app.research.baseline.engine import simulate


class EvaluationTests(unittest.TestCase):
    def test_paired_account_returns_not_trade_average(self):
        dates=pd.date_range('2024-01-01',periods=90,freq='D',tz='UTC')
        first=[dict(day=str(d.date()),equity=1000*1.0001**(i+1)) for i,d in enumerate(dates)]
        second=[dict(day=str(d.date()),equity=1000) for d in dates]
        result=compare_daily(first,second,dates[0],dates[-1]+pd.Timedelta(days=1))
        self.assertAlmostEqual(result['mean_daily_difference_bps'],1)
        for value in result['interval']['interval_bps']:self.assertAlmostEqual(value,1)

    def test_calendar_mismatch_is_not_silently_joined(self):
        with self.assertRaises(ValueError):
            compare_daily([dict(day='2024-01-01',equity=1000)],
                          [dict(day='2024-01-02',equity=1000)],'2024-01-01','2024-04-01')

    def test_repeat_run_has_no_shared_state(self):
        frame=pd.DataFrame(dict(o=60000,h=60001,l=59999,c=60000,v=1000),
                           index=pd.date_range('2024-01-01',periods=10,freq='min',tz='UTC'))
        args=(frame,{1:(1,60000,500)},frame.index[0],frame.index[-1]+pd.Timedelta(minutes=1))
        self.assertEqual(simulate(*args),simulate(*args))


if __name__=='__main__':unittest.main()
