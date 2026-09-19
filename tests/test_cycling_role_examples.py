import unittest
from decimal import Decimal as D
from scripts.replay_cycling_role_examples import run_path
from app.research.recovery.position_alternatives import PositionExample,ExampleCosts


class RolePathTests(unittest.TestCase):
    def initial(self):return PositionExample(1,'.2',10100,0,0,0,1000)
    def costs(self):return ExampleCosts(0,0,0,'.1','.001',2)
    def steps(self):return [dict(decision_ms=i+1,evidence_available_ms=i+1,mark=p,action=a,quantity=q)
        for i,(p,a,q) in enumerate([(10090,'retracement_reduce',0),(10080,'increase','.1'),(10090,'retracement_reduce',0)])]

    def test_losses_carried_and_each_half_uses_current_total(self):
        r=run_path(self.initial(),self.costs(),self.steps())
        self.assertEqual([h['result']['after'].quantity for h in r['history']],[D('.1'),D('.2'),D('.1')])
        self.assertEqual(r['final'].realized_gross,-1)
        self.assertEqual(r['final'].average,10090)
        self.assertEqual(r['history'][-1]['result']['total_net'],-1)
        self.assertEqual(r['history'][1]['before'],r['history'][0]['result']['after'])

    def test_wait_branch_reduces_actual_remaining_half(self):
        s=self.steps();s[1].update(action='wait',quantity=0)
        r=run_path(self.initial(),self.costs(),s)
        self.assertEqual(r['final'].quantity,D('.05'))
        self.assertEqual(r['final'].realized_gross,D('-1.5'))
        self.assertEqual(r['history'][-1]['result']['total_net'],-2)

    def test_future_or_out_of_order_rejected(self):
        s=self.steps();s[1]['evidence_available_ms']=10
        with self.assertRaises(ValueError):run_path(self.initial(),self.costs(),s)
        s=self.steps();s[1]['decision_ms']=1
        with self.assertRaises(ValueError):run_path(self.initial(),self.costs(),s)

    def test_prefix_state_unchanged_by_later_steps(self):
        a=run_path(self.initial(),self.costs(),self.steps()[:2])
        b=run_path(self.initial(),self.costs(),self.steps())
        self.assertEqual(a['history'],b['history'][:2])
        self.assertEqual(a['final'].side,1)


if __name__=='__main__':unittest.main()
