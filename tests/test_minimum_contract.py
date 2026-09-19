from dataclasses import replace
import unittest
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk,size_order as budget_size
from app.research.diagnostics.minimum_contract import size_order


class MinimumContractTests(unittest.TestCase):
    def setUp(self):
        self.r=Risk(cycle_fraction=.005,aggregate_fraction=.005,warning=.025,halt=.04)
        self.c=Costs(2.5,5,1)

    def order(self,price=100000,atr=100,side=1,equity=1000,warned=False,risk=None):
        return size_order(price,price,atr,side,equity,warned,self.c,risk or self.r)

    def test_unused_budget_does_not_increase_quantity(self):
        old=budget_size(100000,100000,100,1,1000,False,self.c,self.r)
        new=self.order()
        self.assertGreater(old['quantity'],.001);self.assertEqual(new['quantity'],.001)
        self.assertAlmostEqual(old['planned_loss']/old['quantity'],new['planned_loss']/new['quantity'])

    def test_smallest_order_still_rejected_if_risk_too_high(self):
        self.assertEqual(self.order(atr=2000)['reason'],'size_constraint')

    def test_warning_halves_budget_and_can_reject_minimum(self):
        before=self.order(atr=1000);after=self.order(atr=1000,warned=True)
        self.assertTrue(before['approved']);self.assertEqual(after['reason'],'size_constraint')

    def test_aggregate_limit_still_binds(self):
        r=replace(self.r,aggregate_fraction=.001)
        self.assertFalse(self.order(atr=500,risk=r)['approved'])

    def test_notional_floor_rounds_up_to_two_contract_units(self):
        v=self.order(price=40000,atr=100)
        self.assertTrue(v['approved']);self.assertEqual(v['quantity'],.002)

    def test_short_side_preserves_adverse_stop_and_budget(self):
        v=self.order(side=-1,atr=1000)
        self.assertTrue(v['approved']);self.assertGreater(v['stop'],v['entry'])
        self.assertLessEqual(v['planned_loss'],v['budget']);self.assertEqual(v['quantity'],.001)

    def test_invalid_stop_rejected(self):
        self.assertFalse(self.order(price=100,atr=200)['approved'])


if __name__=='__main__':unittest.main()
