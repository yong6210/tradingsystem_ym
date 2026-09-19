import unittest
from app.research.recovery.campaign_recovery_review import campaign_recovery_mark,net_if_closed
from app.research.recovery.position_alternatives import PositionExample,ExampleCosts
from decimal import Decimal as D


class RecoveryMarkTests(unittest.TestCase):
    def test_minimal_profitable_mark_for_both_sides(self):
        costs=ExampleCosts('.0004','.00005','.0002','.1','.001',2)
        for side in (1,-1):
            p=PositionExample(side,'.1',63050,-16,7,2,10000)
            mark=campaign_recovery_mark(p,costs)
            self.assertGreaterEqual(net_if_closed(p,costs,mark),0)
            self.assertLess(net_if_closed(p,costs,mark-side*costs.tick),0)

    def test_prior_losses_not_reset_to_position_average(self):
        costs=ExampleCosts(0,0,0,'.1','.001',2)
        p=PositionExample(1,'.1',10000,-10,2,0,1000)
        self.assertEqual(campaign_recovery_mark(p,costs),10120)
        self.assertEqual(net_if_closed(p,costs,10120),0)

    def test_flat_has_no_recovery_price(self):
        p=PositionExample(1,0,None,-10,2,0,1000)
        c=ExampleCosts(0,0,0,'.1','.001',2)
        self.assertIsNone(campaign_recovery_mark(p,c))
        self.assertEqual(net_if_closed(p,c,10000),-12)


if __name__=='__main__':unittest.main()
