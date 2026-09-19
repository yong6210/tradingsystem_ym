import unittest
from decimal import Decimal as D
from fractions import Fraction as F
from scripts.check_options_preflight import common_quantity, vwap


class OptionsPreflightTests(unittest.TestCase):
    def test_common_lot_uses_joint_grid_and_ceiling(self):
        legs = [dict(minQty=m, maxQty='10', filters=[dict(stepSize=s)])
                for m,s in [('0.03','0.02'),('0.02','0.03')]]
        self.assertEqual(common_quantity(legs), D('.06'))
        legs[1]['maxQty'] = '.05'
        with self.assertRaises(ValueError): common_quantity(legs)

    def test_vwap_matches_rational_cash_and_rejects_insufficient_depth(self):
        levels = [['100','0.003'], ['99','0.005'], ['98','1']]
        value = vwap(levels, D('.01'), True)
        self.assertEqual(F(value), (F(100)*F('0.003')+F(99)*F('0.005')+F(98)*F('0.002'))/F('.01'))
        with self.assertRaises(ValueError): vwap(levels[:2], D('.01'), True)
        with self.assertRaises(ValueError): vwap(levels, D('.01'), False)

    def test_contractual_payoff_bound_excludes_exercise_fees(self):
        # Synthetic unequal wings: q=.01, L=79000,K=80000,U=82000, C=5.
        for spot in [D(x) for x in ['0','78999','79000','80000','82000','90000','100000000']]:
            intrinsic = [max(spot-D(80000),D(0)),max(D(80000)-spot,D(0)),
                         max(D(79000)-spot,D(0)),max(spot-D(82000),D(0))]
            pnl = D(5)+D('.01')*sum(s*v for s,v in zip([-1,-1,1,1],intrinsic))
            self.assertGreaterEqual(pnl,D(-15))
            self.assertLessEqual(pnl,D(5))
            fee = D('.01')*sum(min(spot*D('.00015'), x*D('.1')) for x in intrinsic)
            if spot == D(100000000):
                self.assertEqual(pnl,D(-15))
                self.assertEqual(fee,D(300))
                self.assertEqual(pnl-fee,D(-315))


if __name__ == '__main__': unittest.main()
