from decimal import Decimal as D
import unittest
from app.research.diagnostics.carry_capital import capital_rows, quote_cost


def book(bids, asks): return dict(bids=bids,asks=asks)


class CarryCapitalTests(unittest.TestCase):
    def test_depth_is_not_scaled_from_first_level(self):
        self.assertEqual(quote_cost([['100','1'],['99','2']],D(2)),D(199))
        self.assertIsNone(quote_cost([['100','1']],D(2)))

    def test_all_lots_include_first_unaffordable_boundary(self):
        spot=book([['99','100']],[['100','100']])
        future=book([['102','100']],[['103','100']])
        rows=capital_rows(spot,future,cash=D(1000),step=D(1))
        self.assertEqual(len(rows),11)
        self.assertTrue(rows[9]['spot_only_cash_feasible'])
        self.assertFalse(rows[10]['spot_only_cash_feasible'])
        self.assertFalse(rows[9]['spot_plus_entry_fee_cash_feasible'])
        self.assertTrue(rows[3]['full_entry_notional_cash_reference_feasible'])
        self.assertFalse(rows[4]['full_entry_notional_cash_reference_feasible'])

    def test_entry_fee_can_consume_positive_basis(self):
        spot=book([['99','100']],[['100','100']])
        future=book([['100.05','100']],[['101','100']])
        row=capital_rows(spot,future,cash=D(100),step=D(1))[0]
        self.assertEqual(D(row['basis_component_usdt']),D('.05'))
        self.assertEqual(D(row['basis_after_entry_fee_only_usdt']),D('-.05'))
        self.assertEqual(D(row['cash_after_spot_entry_fee_usdt']),D('-.1'))

    def test_insufficient_depth_is_not_invented(self):
        spot=book([['99','1']],[['100','1']])
        future=book([['102','1']],[['103','1']])
        rows=capital_rows(spot,future,cash=D(1000),step=D(1))
        self.assertEqual(rows[1]['status'],'INSUFFICIENT_DISPLAYED_DEPTH')
        self.assertNotIn('basis_component_usdt',rows[1])

    def test_bad_budget_rejected(self):
        b=book([['99','1']],[['100','1']])
        for kw in [dict(cash=D(0)),dict(step=D(0)),dict(entry_fee_rate=D(-1))]:
            with self.assertRaises(ValueError):capital_rows(b,b,**kw)


if __name__=='__main__':unittest.main()
