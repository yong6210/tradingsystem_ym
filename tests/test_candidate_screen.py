"""Boundary and causal checks before screening real candidate outcomes."""
import unittest
import json
from pathlib import Path
import numpy as np
import pandas as pd
from app.research.diagnostics.candidate_screen import candidate_conditions, feasibility, minimum_order, independent_interval
from app.research.diagnostics.entry_information import moving_block_interval
from app.research.multistrategy_audit import feature_bank


class CandidateScreenTests(unittest.TestCase):
    def test_quantity_rounding(self):
        self.assertEqual(minimum_order(60000, .001, .001, 50), .001)
        self.assertEqual(minimum_order(20000, .001, .001, 50), .003)
        self.assertEqual(minimum_order(50000, .001, .001, 50), .001)
        with self.assertRaises(ValueError):
            minimum_order(0, .001, .001, 50)

    def test_risk_limit_and_gap(self):
        settings = json.loads(Path('configs/research/e003_candidate_screen.json').read_text())
        for side in (-1, 1):
            result = feasibility(60000, 60000, 500, side, 1, settings)
            self.assertTrue(result['gross_eligible'])
            self.assertFalse(result['cost_eligible'])
            self.assertAlmostEqual(result['planned_price_loss'], .5)
        self.assertEqual(feasibility(120000,120000,100,1,1,settings)['feasibility_reason'],'notional_cap')
        self.assertEqual(feasibility(59000,60000,500,1,1,settings)['feasibility_reason'],'invalid_stop')

    def test_independent_bootstrap_nonconstant(self):
        start, end = pd.Timestamp('2024-01-01',tz='UTC'), pd.Timestamp('2024-04-01',tz='UTC')
        rows = [dict(decision_time=(start+pd.Timedelta(days=i)).isoformat(), excess_bps=float(i%7-3))
                for i in range(91) if i%3 for _ in range(1+i%4)]
        expected = moving_block_interval(rows,start,end,28,2000,17)['interval_bps']
        np.testing.assert_allclose(independent_interval(rows,start,end,28,2000,17),expected,rtol=0,atol=1e-12)

    def test_reentry_uses_previous_fixed_channel(self):
        idx=pd.date_range('2023-01-01', periods=3, freq='h', tz='UTC')
        frame=pd.DataFrame(dict(c=[105,110,99], high24=[100,100,110],low24=[90,90,90],atr=2,ema80=95,er=.2),index=idx)
        rule=candidate_conditions({60:frame,240:frame},'S07')
        self.assertEqual(rule.side.tolist(),[0,0,-1])
        self.assertEqual(rule.event.tolist(),[False,False,True])

    def test_event_thinning_and_recovery_threshold(self):
        idx=pd.date_range('2023-01-01',periods=5,freq='15min',tz='UTC')
        frame=pd.DataFrame(dict(c=100,atr=2,ema80=100,er=.1,z=[-3,-3,-1.5,3,1.5]),index=idx)
        bank={15:frame,240:frame}
        self.assertEqual(candidate_conditions(bank,'S04').event.tolist(),[True,False,False,True,False])
        self.assertEqual(candidate_conditions(bank,'S05').side.tolist(),[0,0,1,0,-1])

    def test_all_candidates_future_invariance(self):
        rng=np.random.default_rng(10)
        size=35000
        prices=100*np.exp(np.cumsum(rng.normal(0,.001,size)))
        frame=pd.DataFrame(dict(o=prices,h=prices*1.001,l=prices*.999,c=prices,v=100),
                           index=pd.date_range('2023-01-01',periods=size,freq='min',tz='UTC'))
        modified=frame.copy()
        modified.iloc[30000:,:4]*=3
        a,b=feature_bank(frame),feature_bank(modified)
        for model in ('S01','S02','S04','S05','S07','S08'):
            x,y=candidate_conditions(a,model),candidate_conditions(b,model)
            pd.testing.assert_frame_equal(x.loc[x.index<=frame.index[30000]],y.loc[y.index<=frame.index[30000]])


if __name__=='__main__':
    unittest.main()
