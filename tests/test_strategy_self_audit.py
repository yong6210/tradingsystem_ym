"""Paired mechanism tests for the separately versioned research audit."""
import unittest
from tests.test_multistrategy_research import market, one_signal
import numpy as np
from app.research.multistrategy import simulate as legacy
from app.research.multistrategy_audit import simulate

class AuditTests(unittest.TestCase):
    def run_case(self, f, s, engine=simulate, **kwargs):
        return engine(f, {'a':s}, np.full(len(f),2),'2026-01-01','2026-01-02',
                      model_name='a',record_events=True,**kwargs)

    def test_default_reproduces_legacy(self):
        f=market(); s=one_signal()
        self.assertEqual(self.run_case(f,s),self.run_case(f,s,engine=legacy))

    def test_profit_order_blocks_add_and_priority_unblocks(self):
        f=market(); s=one_signal(); s.update(rotation=True,stop_atr=4.,target_atr=1.5)
        s['decision'][2]=True; s['atr'][2]=1.; s['close'][2]=98.8
        f.loc[f.index[2],['o','h','l','c']]=[99.,99.5,98.5,99.]
        old=self.run_case(f,s)
        changed=self.run_case(f,s,add_priority=True)
        self.assertEqual(old['counts'].get('rotation_add',0),0)
        self.assertEqual(changed['counts'].get('rotation_add',0),1)
        self.assertEqual(changed['counts']['profit_cancelled_for_add'],1)
        disabled=self.run_case(f,s,add_priority=True,no_add=True)
        self.assertEqual(disabled['counts'].get('rotation_add',0),0)
        self.assertEqual(old['events'][0]['qty'],disabled['events'][0]['qty'])

    def test_pre_profit_excursion_is_counted(self):
        f=market(); f['v']=100000.; s=one_signal(); s.update(target_atr=1.)
        f.loc[f.index[1],['o','h','l','c']]=[100.,102.,98.,101.]
        old=self.run_case(f,s); revised=self.run_case(f,s,conservative_dd=True)
        self.assertEqual(old['return_pct'],revised['return_pct'])
        self.assertGreater(revised['max_drawdown_pct'],old['max_drawdown_pct'])

if __name__=='__main__': unittest.main()
