from decimal import Decimal as D
import unittest
from app.research.diagnostics.dated_carry import entry_components, displayed_vwap, terminal_components


class DatedCarryTest(unittest.TestCase):
    def test_multiple_levels(self):
        self.assertEqual(displayed_vwap([['100', '.0004'], ['110', '.001']], D('.001')), D(106))

    def test_insufficient_depth(self):
        self.assertIsNone(displayed_vwap([['100', '.0004']], D('.001')))

    def test_uses_buy_ask_and_sell_bid(self):
        spot = dict(bids=[['99', '1']], asks=[['100', '1']])
        future = dict(bids=[['103', '1']], asks=[['104', '1']])
        r = entry_components(spot, future)
        self.assertEqual(D(r['initial_basis_component_usdt']), D('.003'))
        self.assertEqual(D(r['initial_basis_bps']), D(300))
        self.assertIsNone(r['net_profit_usdc'])

    def test_rejects_crossed_book(self):
        crossed = dict(bids=[['100', '1']], asks=[['99', '1']])
        with self.assertRaises(ValueError):
            entry_components(crossed, crossed)

    def test_price_cancellation_requires_matched_exit(self):
        for terminal in [D(50), D(100), D(200)]:
            initial, mismatch, net = terminal_components(D(1), D(100), D(103), terminal, terminal, D(1))
            self.assertEqual((initial, mismatch, net), (D(3), D(0), D(2)))

    def test_exit_mismatch_can_erase_initial_basis(self):
        initial, mismatch, net = terminal_components(D(1), D(100), D(103), D(95), D(100), D(1))
        self.assertEqual((initial, mismatch, net), (D(3), D(-5), D(-3)))


if __name__ == '__main__':
    unittest.main()
