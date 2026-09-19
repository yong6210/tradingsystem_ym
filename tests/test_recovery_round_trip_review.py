import unittest
from decimal import Decimal as D
from app.research.recovery.position_alternatives import ExampleCosts
from app.research.recovery.round_trip_review import round_trip


class RoundTripTests(unittest.TestCase):
    def test_long_and_short_gross_minus_both_fees(self):
        costs=ExampleCosts('.001',0,0,'.1','.01',2)
        for side,exit in [(1,110),(-1,90)]:
            r=round_trip(costs,side=side,quantity=2,entry_mark=100,exit_mark=exit)
            self.assertEqual(r['net'],D(20)-D(2)*(100+exit)*D('.001'))

    def test_same_mark_is_loss_with_friction(self):
        c=ExampleCosts('.0004','.00005','.0002','.1','.001',2)
        for side in (1,-1):self.assertLess(round_trip(c,side=side,quantity='.1',entry_mark=63000,exit_mark=63000)['net'],0)

    def test_costless_move_and_quantity_alignment(self):
        c=ExampleCosts(0,0,0,'.1','.01',2)
        self.assertEqual(round_trip(c,side=1,quantity='.1',entry_mark=100,exit_mark=110)['net'],1)
        with self.assertRaises(ValueError):round_trip(c,side=1,quantity='.001',entry_mark=100,exit_mark=110)


if __name__=='__main__':unittest.main()
