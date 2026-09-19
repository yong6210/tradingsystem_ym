import unittest
import numpy as np
from scripts.audit_volume_zone_coverage import peaks_without_cap
from app.research.diagnostics.multiscale_profile import zones_from_hist


class CoverageTests(unittest.TestCase):
    def test_top_five_prefix_and_lower_rank_retained(self):
        v=np.zeros(45)
        for i,x in enumerate([1,2,3,4,5,6,7]):v[3+i*6]=x
        new=peaks_without_cap(v,100)
        old=zones_from_hist(v,100,'test')
        self.assertEqual(len(new),7)
        self.assertEqual([(c['low'],c['high'],c['share']) for c in new[:5]],[(c.low,c.high,c.share) for c in old])
        self.assertTrue(new[-1]['excluded_by_top_five_cap'])
        self.assertAlmostEqual(new[-1]['share'],1/28)

    def test_empty_volume_and_invalid_values(self):
        self.assertEqual(peaks_without_cap(np.zeros(8),0),[])
        for value in ([1,-1,2],[1,float('nan'),2],[[1,2,3]]):
            with self.assertRaises(ValueError):peaks_without_cap(value,0)

    def test_no_input_mutation(self):
        v=np.array([0,1,4,1,0,2,3,2,0.]);before=v.copy()
        self.assertEqual(peaks_without_cap(v,0),peaks_without_cap(v.copy(),0))
        np.testing.assert_array_equal(v,before)


if __name__=='__main__':unittest.main()
