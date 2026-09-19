import unittest
import numpy as np
import pandas as pd
from app.research.diagnostics.inventory_flow import build_flow_features,model_features,fit_flow_ridge

class FlowTest(unittest.TestCase):
    def fixture(self):
        idx=pd.date_range('2024-01-20',periods=14*1440,freq='min',tz='UTC');p=50000+np.sin(np.arange(len(idx))/30)*100
        m=pd.DataFrame({'o':p,'h':p+3,'l':p-3,'c':p+1,'v':10.},index=idx);flow=pd.DataFrame({'volume':10.,'taker_buy_volume':7.},index=idx);return m,flow
    def test_actual_imbalance(self):
        m,flow=self.fixture();f=build_flow_features(m,flow);self.assertAlmostEqual(f.flow3.iloc[-1],.4)
    def test_causality(self):
        m,flow=self.fixture();a=build_flow_features(m,flow);cut=m.index[-1000];flow.loc[cut:,'taker_buy_volume']=1.;b=build_flow_features(m,flow)
        pd.testing.assert_frame_equal(a.loc[:cut],b.loc[:cut])
    def test_volume_mismatch_rejected(self):
        m,flow=self.fixture();flow.iloc[-1,0]=11
        with self.assertRaises(ValueError):build_flow_features(m,flow)
    def test_adapter_preserves_direction(self):
        m,flow=self.fixture();f=build_flow_features(m,flow);mapped,engine=model_features(f,'flow_continuation')
        self.assertEqual(engine,'retest');pd.testing.assert_series_equal(mapped.direction,f.direction)
    def test_purged_flow_fit(self):
        m,flow=self.fixture();f=build_flow_features(m,flow);logs=fit_flow_ridge(m,f,'2024-02-01T00:00Z','2024-02-02T00:00Z')
        self.assertLess(pd.Timestamp(logs[0]['last_label_maturity']),pd.Timestamp('2024-01-31T00:00Z'))

if __name__=='__main__':unittest.main()
