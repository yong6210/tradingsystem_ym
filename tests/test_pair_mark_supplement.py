from decimal import Decimal as D
import unittest
from scripts.supplement_pair_mark import parse,compare,HOUR


def records(start,end,step):
    return [[t,'100','110','90','105','0',t+step-1,'0',0,'0','0','0'] for t in range(start,end,step)]


class PairMarkSupplementTests(unittest.TestCase):
    def test_complete_cross_resolution(self):
        h=parse(records(0,HOUR,HOUR),0,HOUR,HOUR);m=parse(records(0,HOUR,60000),0,HOUR,60000)
        self.assertEqual(compare(h,m,0,HOUR),4)
    def test_missing_or_duplicate_minute_rejected(self):
        raw=records(0,HOUR,60000)
        for bad in (raw[:-1],raw+[raw[-1]]):
            with self.assertRaises(ValueError):parse(bad,0,HOUR,60000)
    def test_wrong_boundary_or_geometry_rejected(self):
        for column,value in ((6,HOUR),(2,'95')):
            raw=records(0,HOUR,HOUR);raw[0][column]=value
            with self.assertRaises(ValueError):parse(raw,0,HOUR,HOUR)
    def test_aggregate_mismatch_rejected(self):
        h=parse(records(0,HOUR,HOUR),0,HOUR,HOUR);m=parse(records(0,HOUR,60000),0,HOUR,60000)
        m[60000]['high']=D('111')
        with self.assertRaises(ValueError):compare(h,m,0,HOUR)


if __name__=='__main__':unittest.main()
