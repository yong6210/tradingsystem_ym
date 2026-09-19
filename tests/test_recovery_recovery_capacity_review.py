import unittest
from decimal import Decimal as D
from app.research.recovery.cycling_admission import Capacity
from app.research.recovery.position_alternatives import PositionExample,ExampleCosts
from app.research.recovery.recovery_capacity_review import review_capacity


class CapacityReviewTests(unittest.TestCase):
    def setup(self,side=1):
        p=PositionExample(side,'.1',63050,-16,7,2,10000)
        c=ExampleCosts('.0004','.00005','.0002','.1','.001',2)
        args=dict(mark=62972.8,quote_ms=100,requested='.15',liquidity_qty='.2',minimum_quantity='.001',
                  minimum_notional=5,now_ms=100,max_age_ms=5)
        return p,c,args
    def cap(self,**kw):
        d=dict(observed_ms=100,free_margin=6800,reserve_margin=3000,margin_per_unit=31500,
               maximum_total='.3',stress_loss_budget=500,stress_moves=(2000,3000));d.update(kw)
        return Capacity(**d)

    def test_limits_stress_reserve_and_no_entry_approval(self):
        p,c,a=self.setup();cap=self.cap();r=review_capacity(p,c,capacity=cap,**a)
        self.assertEqual(r['status'],'capacity_calculated')
        self.assertLessEqual(r['capacity_quantity'],min(r['limits'].values()))
        self.assertGreaterEqual(r['reserved_margin_remaining'],cap.reserve_margin)
        self.assertTrue(all(s['after_net_if_closed']>=-cap.stress_loss_budget for s in r['stress']))
        self.assertFalse(r['entry_approved'])

    def test_missing_stale_future(self):
        p,c,a=self.setup()
        self.assertIsNone(review_capacity(p,c,capacity=None,**a)['capacity_quantity'])
        for time in (94,101):
            self.assertEqual(review_capacity(p,c,capacity=self.cap(observed_ms=time),**a)['status'],'unavailable_snapshot')

    def test_existing_over_budget_prevents_more(self):
        p,c,a=self.setup();r=review_capacity(p,c,capacity=self.cap(stress_loss_budget=10),**a)
        self.assertEqual(r['capacity_quantity'],0)
        self.assertEqual(r['orders_generated'],0)

    def test_liquidity_and_minimum(self):
        p,c,a=self.setup();a['liquidity_qty']='.002';a['minimum_quantity']='.003'
        self.assertEqual(review_capacity(p,c,capacity=self.cap(),**a)['status'],'no_executable_capacity')

    def test_short_uses_adverse_upward_price(self):
        p,c,a=self.setup(-1);r=review_capacity(p,c,capacity=self.cap(),**a)
        self.assertTrue(all(s['mark']>D(str(a['mark'])) for s in r['stress']))
        self.assertTrue(all(s['after_net_if_closed']>=-500 for s in r['stress']))


if __name__=='__main__':unittest.main()
