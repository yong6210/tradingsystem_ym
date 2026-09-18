from dataclasses import asdict, replace
import unittest

import pandas as pd

from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.diagnostics.intrabar_engine import simulate
from app.research.diagnostics.time_exit_policy import risk_pair, verify_window, verify_no_time_exit


class TimeExitPolicyTests(unittest.TestCase):
    def setup_case(self, count=6):
        frame = pd.DataFrame(dict(o=100., h=100., l=100., c=100., v=1.),
                             index=pd.date_range('2025-01-01', periods=count, freq='min', tz='UTC'))
        # Synthetic fixtures only. Production control uses the unchanged Risk().
        risk = Risk(cycle_fraction=.1, aggregate_fraction=.1, daily_stop=.9,
                    warning=.5, halt=.8, minimum_qty=1, step=1, minimum_notional=1,
                    stop_atr=1, maximum_hold_minutes=2)
        start, end = frame.index[0], frame.index[-1]+pd.Timedelta(minutes=1)
        return frame, start, end, risk

    def run_case(self, frame, start, end, risk, decisions=None, funding=(), path='OHLC'):
        return simulate(frame, decisions if decisions is not None else {0:(1,100,90)},
                        start, end, Costs(0,0,0,.01), risk, funding=funding, path=path)

    def test_only_holding_cap_changes_and_zero_is_rejected(self):
        frame, start, end, risk = self.setup_case()
        pair = risk_pair(start, end, risk)
        a, b = (asdict(r) for r in pair.values())
        self.assertEqual([k for k in a if a[k] != b[k]], ['maximum_hold_minutes'])
        for invalid in (0,-1,True,2.5):
            with self.assertRaises(ValueError): risk_pair(start,end,replace(risk,maximum_hold_minutes=invalid))

    def test_control_exits_at_cap_variant_keeps_fixed_quantity_to_end(self):
        frame,start,end,risk = self.setup_case()
        for path in ('OHLC','OLHC'):
            pair = risk_pair(start,end,risk)
            a,b = (self.run_case(frame,start,end,r,path=path) for r in pair.values())
            self.assertEqual((a['trades'][0]['reason'],a['trades'][0]['exit_minute']), ('time_exit',2))
            self.assertEqual((b['trades'][0]['reason'],b['trades'][0]['exit_minute']), ('end_exit',5))
            self.assertEqual(a['events'][0],b['events'][0])
            self.assertEqual(verify_no_time_exit(b,start,end,pair['no_time_exit'])['time_exits'],0)
            with self.assertRaises(ValueError): verify_no_time_exit(a,start,end,pair['no_time_exit'])

    def test_protective_stop_survives_after_old_cap(self):
        frame,start,end,risk = self.setup_case()
        frame.iloc[4] = [100,100,5,100,1]
        variant = risk_pair(start,end,risk)['no_time_exit']
        for path in ('OHLC','OLHC'):
            result = self.run_case(frame,start,end,variant,path=path)
            self.assertEqual(result['trades'][0]['reason'],'price_stop')
            self.assertEqual(result['trades'][0]['exit_minute'],4)
            self.assertAlmostEqual(result['metrics']['final_equity'],910)

    def test_account_drawdown_stop_and_latched_halt_survive(self):
        frame,start,end,risk = self.setup_case()
        frame.iloc[4] = [100,200,90,190,1]
        variant = risk_pair(start,end,replace(risk,halt=.08))['no_time_exit']
        result = self.run_case(frame,start,end,variant,decisions={0:(1,100,90),5:(1,100,90)})
        self.assertEqual(result['trades'][0]['reason'],'risk_stop')
        self.assertTrue(result['metrics']['drawdown_halted'])
        self.assertEqual(result['metrics']['cycles'],1)
        self.assertAlmostEqual(result['metrics']['final_equity'],1012)

    def test_neutral_and_reversal_survive(self):
        frame,start,end,risk = self.setup_case()
        variant = risk_pair(start,end,risk)['no_time_exit']
        for side,reason in ((0,'neutral_exit'),(-1,'reverse_exit')):
            result = self.run_case(frame,start,end,variant,decisions={0:(1,100,90),4:(side,100,90)})
            self.assertEqual(result['trades'][0]['reason'],reason)
            self.assertEqual(result['trades'][0]['exit_minute'],4)
            self.assertEqual(result['metrics']['cycles'],1 if side==0 else 2)

    def test_funding_continues_during_extra_holding(self):
        frame,start,end,risk = self.setup_case()
        funding = [dict(fundingTime=int(frame.index[3].timestamp()*1000),fundingRate='.01',markPrice='100')]
        a,b = (self.run_case(frame,start,end,r,funding=funding) for r in risk_pair(start,end,risk).values())
        self.assertEqual(a['metrics']['funding'],0)
        self.assertEqual(b['metrics']['funding'],1)
        self.assertEqual(b['metrics']['final_equity'],999)

    def test_no_effect_before_control_cap(self):
        frame,start,end,risk = self.setup_case(count=2)
        a,b = (self.run_case(frame,start,end,r) for r in risk_pair(start,end,risk).values())
        for field in ('events','trades','daily','rejections','path_stops'):
            self.assertEqual(a[field],b[field])

    def test_window_rejects_missing_duplicate_and_unaligned_minutes(self):
        frame,start,end,risk = self.setup_case()
        self.assertEqual(verify_window(frame.index,start,end),6)
        for index in (frame.index.delete(2),frame.index.insert(2,frame.index[2]),frame.index[::-1]):
            with self.assertRaises(ValueError): verify_window(index,start,end)
        for a,b in ((start.tz_localize(None),end),(end,start),(start+pd.Timedelta(seconds=1),end)):
            with self.assertRaises(ValueError): risk_pair(a,b,risk)


if __name__ == '__main__': unittest.main()
