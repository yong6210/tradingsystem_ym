import unittest
import numpy as np
import pandas as pd
from app.research.diagnostics.multiscale_profile import Profiles,Zone,zones_from_hist,context_features,reaction,broken,direction


class ProfileTests(unittest.TestCase):
    def test_real_volume_peak_not_candle_midpoint(self):
        h=np.array([1.,2.,50.,2.,1.])
        z=zones_from_hist(h,1000,'week')[0]
        self.assertEqual(z.poc,50125)
        self.assertAlmostEqual(z.share,54/56)

    def test_completed_slot_and_delay(self):
        h=np.ones((100,5));p=Profiles(h,1000,0)
        self.assertEqual(p.snapshot(96*900000+59999)[1],95*900000)
        zones,cut=p.snapshot(96*900000+60000)
        self.assertEqual(cut,96*900000)
        self.assertIn('day',{z.horizon for z in zones})

    def test_future_volume_cannot_change_past_profile(self):
        h=np.ones((6000,5));p=Profiles(h,1000,0)
        h[5800:]*=100000
        q=Profiles(h,1000,0)
        self.assertEqual(p.snapshot(5800*900000+60000),q.snapshot(5800*900000+60000))

    def test_sixty_days_not_partial_warmup(self):
        p=Profiles(np.ones((5800,5)),1000,0)
        self.assertNotIn('sixty_day',{z.horizon for z in p.snapshot(5759*900000+60000)[0]})
        self.assertIn('sixty_day',{z.horizon for z in p.snapshot(5760*900000+60000)[0]})

    def test_long_reclaim_and_short_rejection(self):
        z=Zone(100,150,125,.3,'week')
        v=dict(b_l=140,b_h=170,b_c=160,b_o=145,m_c=160,m_o=150)
        self.assertTrue(reaction(z,1,v));self.assertFalse(reaction(z,-1,v))
        v.update(b_l=80,b_h=110,b_c=90,b_o=105,m_c=90,m_o=100)
        self.assertTrue(reaction(z,-1,v));self.assertFalse(reaction(z,1,v))

    def test_thesis_failure_needs_two_closes(self):
        z=Zone(100,150,125,.3,'week')
        self.assertFalse(broken(z,1,dict(b_c=99,b_previous_close=101)))
        self.assertTrue(broken(z,1,dict(b_c=99,b_previous_close=98)))
        self.assertTrue(broken(z,-1,dict(b_c=151,b_previous_close=152)))

    def test_upper_timeframes_and_lower_confirmation(self):
        v=dict(daily=1,four_hour=1,hour=1,quarter=1)
        self.assertEqual(direction(v),1)
        v['four_hour']=-1;self.assertEqual(direction(v),0)
        v.update(daily=-1,hour=-1,quarter=-1);self.assertEqual(direction(v),-1)

    def test_anchor_and_features_prefix_invariant(self):
        idx=pd.date_range('2026-01-01',periods=35*1440,freq='min',tz='UTC')
        px=60000+np.sin(np.arange(len(idx))/600)*1000+np.arange(len(idx))*.01
        m=pd.DataFrame(dict(o=px,h=px+20,l=px-20,c=px+1,v=1.),index=idx)
        full=context_features(m);prefix=context_features(m.iloc[:33*1440])
        pd.testing.assert_frame_equal(full.loc[prefix.index],prefix)
        finite=full.anchor_ms.dropna()
        observed=finite.index.asi8//10**6
        self.assertTrue(((observed-finite.to_numpy())>=12*3600000+60000).all())

if __name__=='__main__':unittest.main()
