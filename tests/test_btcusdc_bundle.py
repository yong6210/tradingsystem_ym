import unittest
import pandas as pd
from app.research.data.btcusdc import PublicBundle, align_prices


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.index = pd.date_range('2024-01-01', periods=5, freq='min', tz='UTC')
        self.frame = pd.DataFrame(dict(o=10.,h=11.,l=9.,c=10.,v=1.), index=self.index)

    def test_missing_is_not_interpolated(self):
        aligned = align_prices(self.frame.drop(self.index[2]), self.index)
        self.assertTrue(aligned.loc[self.index[2]].isna().all())
        bundle = PublicBundle(self.frame,aligned,self.frame,[])
        with self.assertRaises(ValueError): bundle.require_complete_window(self.index[0],self.index[-1]+pd.Timedelta(minutes=1))

    def test_complete_window_and_outside(self):
        bundle = PublicBundle(self.frame,self.frame,self.frame,[])
        bundle.require_complete_window(self.index[1],self.index[4])
        with self.assertRaises(ValueError): bundle.require_complete_window(self.index[0]-pd.Timedelta(minutes=1),self.index[4])

    def test_duplicates_and_invalid_ohlc(self):
        for frame in (pd.concat([self.frame,self.frame]),self.frame.assign(h=8.)):
            with self.assertRaises(ValueError): align_prices(frame,self.index)
