import io,tempfile,unittest
from pathlib import Path
from zipfile import ZipFile
import pandas as pd
from app.research.diagnostics.open_interest_pressure import parse_day,signals,decisions


class OpenInterestTests(unittest.TestCase):
    def fixture(self):
        idx=pd.date_range('2024-08-30','2024-09-03',freq='min',tz='UTC')
        frame=pd.DataFrame({'c':100.},index=idx);frame.loc[pd.Timestamp('2024-08-31T23:59Z'),'c']=99.
        return frame,{'2024-08-29':'100','2024-08-30':'105'}

    def test_exact_threshold_and_delay(self):
        frame,oi=self.fixture();r=signals(frame,oi,'2024-09-01T00:00Z','2024-09-03T00:00Z')[0]
        self.assertEqual(r['side'],-1);self.assertEqual(r['control_side'],-1)
        self.assertEqual(r['new_oi_date'],'2024-08-30');self.assertEqual(r['oi_change'],'0.05')
        self.assertEqual(r['exit_minute']-r['entry_minute'],1439)

    def test_future_oi_and_prices_do_not_change_earlier_signal(self):
        frame,oi=self.fixture();a=signals(frame,oi,'2024-09-01T00:00Z','2024-09-03T00:00Z')[0]
        oi['2024-08-31']='99999';oi['2024-09-01']='1';frame.loc['2024-09-01':,'c']=999.
        self.assertEqual(signals(frame,oi,'2024-09-01T00:00Z','2024-09-03T00:00Z')[0],a)

    def test_missing_input_abstains_both(self):
        frame,oi=self.fixture();oi['2024-08-30']=None
        r=signals(frame,oi,'2024-09-01T00:00Z','2024-09-03T00:00Z')[0]
        self.assertFalse(r['input_valid']);self.assertEqual((r['side'],r['control_side']),(0,0))

    def test_below_threshold_keeps_price_control(self):
        frame,oi=self.fixture();oi['2024-08-30']='104.999999'
        r=signals(frame,oi,'2024-09-01T00:00Z','2024-09-03T00:00Z')[0]
        self.assertEqual((r['side'],r['control_side']),(0,-1))

    def test_decision_map_preserves_short(self):
        self.assertEqual(decisions([dict(side=-1,entry_minute=1,exit_minute=2,decision_close=100,atr=2)]),
            {1:(-1,100,2),2:(0,100,2)})

    def parse(self,records):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'day.zip'
            with ZipFile(path,'w') as z:z.writestr('day.csv','create_time,symbol,sum_open_interest\n'+records)
            return parse_day(path,'2024-08-30')

    def test_shuffled_rows_and_missing_interior(self):
        value,audit=self.parse('2024-08-30 23:55:00,BTCUSDT,105\n2024-08-30 00:00:00,BTCUSDT,100\n')
        self.assertEqual(value,'105');self.assertFalse(audit['input_monotonic']);self.assertEqual(audit['missing_slots'],286)

    def test_duplicate_endpoint_is_rejected(self):
        value,audit=self.parse('2024-08-30 23:55:00,BTCUSDT,105\n2024-08-30 23:55:00,BTCUSDT,106\n')
        self.assertIsNone(value);self.assertEqual(audit['duplicate_times'],1)

    def test_invalid_oi_anywhere_rejects_day(self):
        value,audit=self.parse('2024-08-30 00:00:00,BTCUSDT,0\n2024-08-30 23:55:00,BTCUSDT,105\n')
        self.assertIsNone(value);self.assertEqual(audit['invalid_rows'],1)
