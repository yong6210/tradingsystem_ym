import io
from zipfile import ZipFile
import unittest
import pandas as pd
from app.research.diagnostics.carry_feasibility import parse_spot,quantity,path,verify_decimal


def archive(month,mutate=None):
    times=pd.date_range(month+'-01',periods=1,tz='UTC');start=times[0];end=start+pd.offsets.MonthBegin(1)
    scale=1000 if month>='2025-01' else 1
    rows=[]
    for t in pd.date_range(start,end,freq='h',inclusive='left'):
        clock=t.value//1_000_000*scale
        rows.append([clock,100,102,99,101,2,clock+3_600_000*scale-1,200,2,1,100,0])
    if mutate: mutate(rows)
    stream=io.BytesIO()
    with ZipFile(stream,'w') as z:z.writestr('test.csv','\n'.join(','.join(map(str,r)) for r in rows))
    return stream.getvalue()


class CarryFeasibilityTests(unittest.TestCase):
    def test_ms_and_us_months(self):
        for month,unit in [('2024-12','ms'),('2025-01','us')]:
            f,a=parse_spot(archive(month),month)
            self.assertEqual(a['rows'],744);self.assertEqual(a['unit'],unit)
    def test_duplicate_gap_unit_and_price_fail(self):
        mutations=[lambda r:r.pop(3),lambda r:r.__setitem__(3,r[2]),
            lambda r:r[3].__setitem__(0,r[3][0]*1000),lambda r:r[3].__setitem__(2,50)]
        for mutate in mutations:
            with self.assertRaises(ValueError):parse_spot(archive('2024-12',mutate),'2024-12')
    def test_equal_hedge_does_not_move_spot_gain_to_margin(self):
        f=pd.DataFrame(dict(spot_open=[50000,130000],future_open=[50000,130000],
            spot_close=[50000,130000],future_close=[50000,130000],mark_high=[50000,140000]),
            index=pd.date_range('2024-09-01',periods=2,freq='h',tz='UTC'))
        q=quantity(50000);self.assertEqual(q,.007)
        r=path(f,[],q,0,0,0)
        self.assertIsNotNone(r['summary']['first_nonpositive_isolated_equity'])
        self.assertGreater(r['summary']['theoretical_terminal_pair_equity'],999)
        self.assertLess(r['summary']['minimum_optimistic_futures_equity'],0)
        verify_decimal(f,[],r)
    def test_funding_sign_initial_exclusion_and_optimistic_bound(self):
        f=pd.DataFrame(dict(spot_open=[50000]*2,future_open=[50000]*2,spot_close=[50000]*2,
            future_close=[50000]*2,mark_high=[50000]*2),index=pd.date_range('2024-09-01',periods=2,freq='h',tz='UTC'))
        start=int(f.index[0].value//1_000_000)
        events=[dict(fundingTime=start,markPrice='50000',fundingRate='1'),
            dict(fundingTime=start+1,markPrice='50000',fundingRate='.001'),
            dict(fundingTime=start+2,markPrice='50000',fundingRate='-.002')]
        r=path(f,events,.007,10,5,0)
        self.assertEqual(r['summary']['funding_events'],2)
        self.assertAlmostEqual(r['summary']['funding_receipts_net'],-.35)
        self.assertGreater(r['rows'][0]['optimistic_futures_equity_at_mark_high'],r['rows'][1]['optimistic_futures_equity_at_mark_high'])
        verify_decimal(f,events,r)


if __name__=='__main__':unittest.main()
