import unittest
import numpy as np
import pandas as pd
from app.research.diagnostics.daily_flow_forecast import daily_panel,predict,signals,PRICE,FLOW,verify_features


class DailyForecastTests(unittest.TestCase):
    def test_future_targets_and_features_do_not_change_prediction(self):
        rng=np.random.default_rng(40);idx=pd.date_range('2025-01-01',periods=210,tz='UTC')
        x=pd.DataFrame(rng.normal(size=(210,4)),columns=FLOW,index=idx)
        x['exit_time']=idx+pd.Timedelta(days=1);y=pd.Series(rng.normal(size=210),index=idx)
        a=predict(x,y,190,FLOW)
        future=x.copy();future.loc[idx[191]:,FLOW]*=1000
        changed=y.copy();changed.iloc[189:]=999999
        other=predict(future,changed,190,FLOW)
        self.assertAlmostEqual(a['prediction_bps'],other['prediction_bps'],places=10)
        for key in ('train_mean','train_std','coefficients'):
            np.testing.assert_allclose(a[key],other[key],rtol=0,atol=1e-12)
        self.assertLess(pd.Timestamp(a['training_last_target_exit']),idx[190])
        self.assertEqual(pd.Timestamp(a['training_start']),idx[9])

    def test_constant_features_predict_training_mean(self):
        idx=pd.date_range('2025-01-01',periods=190,tz='UTC')
        x=pd.DataFrame(1.,columns=PRICE,index=idx);x['exit_time']=idx+pd.Timedelta(days=1)
        y=pd.Series(np.arange(190.),index=idx)
        p=predict(x,y,181,PRICE)
        self.assertAlmostEqual(p['prediction_bps'],np.arange(180.).mean())
        self.assertEqual(p['coefficients'],[0.,0.,0.])

    def test_daily_features_are_available_only_after_close(self):
        idx=pd.date_range('2026-01-01',periods=12*1440,freq='min',tz='UTC')
        price=100+np.arange(len(idx))*.001
        m=pd.DataFrame(dict(o=price,h=price+.1,l=price-.1,c=price,v=1.),index=idx)
        f=m.copy();f['taker_buy_volume']=.75
        a=daily_panel(m,f);self.assertAlmostEqual(a.imbalance_1d.iloc[0],.5)
        self.assertEqual(verify_features(m,f,a)['status'],'PASS')
        b=pd.Timestamp('2026-01-10',tz='UTC');mm=m.copy();ff=f.copy()
        mm.loc[b:,['o','h','l','c']]*=2;ff.loc[b:,['o','h','l','c']]*=2
        ff.loc[b:,'taker_buy_volume']=.1
        changed=daily_panel(mm,ff)
        np.testing.assert_equal(a.loc[b,FLOW].to_numpy(),changed.loc[b,FLOW].to_numpy())

    def test_missing_training_values_fail_closed(self):
        idx=pd.date_range('2025-01-01',periods=190,tz='UTC')
        x=pd.DataFrame(1.,columns=PRICE,index=idx);x['exit_time']=idx+pd.Timedelta(days=1)
        x.iloc[50,0]=np.nan
        with self.assertRaises(ValueError):predict(x,pd.Series(1.,index=idx),181,PRICE)

    def test_boundary_funding_is_excluded_from_signal_threshold(self):
        idx=pd.date_range('2025-01-01',periods=200,tz='UTC')
        x=pd.DataFrame(1.,columns=FLOW,index=idx)
        x['entry_time']=idx+pd.Timedelta(minutes=1);x['exit_time']=idx+pd.Timedelta(days=1)
        x['target_bps']=30.;x['decision_close']=100000.
        b=idx[190]
        funding=[dict(fundingTime=int((b-pd.Timedelta(hours=h)).timestamp()*1000),fundingRate='.0001') for h in (24,16,8)]
        funding.append(dict(fundingTime=int(b.timestamp()*1000),fundingRate='10'))
        r=signals(x,funding,b,b+pd.Timedelta(days=2))['FLOW'][0]
        self.assertAlmostEqual(r['threshold_bps'],21.02)
        self.assertEqual(r['side'],1)
        self.assertEqual(len(r['past_funding_times']),3)


if __name__=='__main__':unittest.main()
