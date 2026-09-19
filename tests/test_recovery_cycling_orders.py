import unittest
from dataclasses import replace

from app.research.recovery.cycling_admission import Capacity, Location, assess_increase
from app.research.recovery.cycling_orders import CyclingOrders
from app.research.recovery.directional_cycling import DirectionalCycling
from app.research.recovery.evidence import Evidence, ZoneEvent, ZoneHistory
from app.research.recovery.models import Costs, Quote, Zone, dec


class CyclingOrderTests(unittest.TestCase):
    def setup_case(self, side=-1):
        m = DirectionalCycling('.1')
        m.set_direction(side, timeframe='4h', observed_ms=0, reason='scenario direction')
        costs = Costs(0, 0, 1, '.1', '.1', 1)
        orders = CyclingOrders(m, costs)
        quote = Quote(100, 102000, 102000, 10, 10, 10, True, True)
        cap = Capacity(100, 100000, 50000, 10000, 10, 100000, (2000, 3000))
        return m, orders, quote, cap

    def location(self, side=-1, suffix='1', observed=100):
        zone = Zone('zone' + suffix, 1, 101000, 103000, 0, 'fixture structure')
        formed = ZoneEvent('formed', 'formed', Evidence('fixture', 0, 0, 0, 'registered'))
        reaction = ZoneEvent('reaction' + suffix, 'validated', Evidence('fixture', observed, observed, observed, 'reaction'))
        return Location(ZoneHistory(zone, (formed, reaction)), side, reaction.id, 101000, 104000)

    def submit(self, orders, quote, cap, order_id='add', location=None, requested=5):
        return orders.increase(order_id, location or self.location(), quote, cap,
                               requested=requested, now_ms=100, max_age_ms=10)

    def test_capacity_margin_reserve_and_stress_are_not_stops(self):
        m, orders, q, cap = self.setup_case()
        m.increase('base', -1, 5, 100000)
        result = self.submit(orders, q, cap)
        self.assertEqual((result['quantity'], result['margin_remaining']), (5, 50000))
        self.assertEqual([s['total_pnl'] for s in result['scenarios']], [-30000, -40000])
        orders.fill('added', 'add', 5, 102000)
        self.assertEqual(m.total_pnl(105000), -40000)
        self.assertEqual(m.quantity, 10)

    def test_loss_budget_selects_quantity_using_entire_campaign(self):
        m, orders, q, cap = self.setup_case()
        m.increase('base', -1, 5, 100000)
        cap = replace(cap, stress_loss_budget=31000)
        result = self.submit(orders, q, cap)
        # Existing loss at 105000 is 25000; each added BTC loses 3000.
        self.assertEqual(result['quantity'], 2)
        self.assertEqual(result['scenarios'][-1]['total_pnl'], -31000)

    def test_partial_cancel_late_fill_then_half_and_readd(self):
        m, orders, q, cap = self.setup_case()
        m.increase('base', -1, 5, 100000)
        self.submit(orders, q, cap)
        orders.fill('a1', 'add', 2, 102000)
        orders.request_cancel('add')
        with self.assertRaises(ValueError):
            self.submit(orders, q, cap, 'other')
        with self.assertRaises(ValueError):
            orders.confirm_cancel('add', 3)
        orders.fill('a2', 'add', 1, 102000)
        orders.confirm_cancel('add', 3)
        self.assertEqual(m.quantity, 8)
        order = orders.retracement('reduce', 'r', reference_price=101000)
        self.assertEqual(order.quantity, 4)
        orders.fill('r1', 'reduce', 1, 101000)
        orders.request_cancel('reduce')
        orders.confirm_cancel('reduce', 1)
        retry = orders.retracement('retry', 'r', reference_price=101000)
        self.assertEqual(retry.quantity, 3)
        orders.fill('r2', 'retry', 3, 101000)
        self.assertEqual((m.quantity, m.average), (4, 100750))
        # Account capacity is explicitly refreshed by the caller, not inferred.
        result = self.submit(orders, q, cap, 'next', self.location(suffix='2'))
        self.assertTrue(result['allowed'])
        orders.fill('next-fill', 'next', result['quantity'], 102000)
        self.assertEqual(m.quantity, 9)

    def test_fresh_evidence_and_future_or_broken_zone(self):
        m, orders, q, cap = self.setup_case()
        result = self.submit(orders, q, cap, location=self.location(observed=101))
        self.assertFalse(result['allowed'])
        loc = self.location()
        broken = ZoneEvent('broken', 'broken', Evidence('fixture', 100, 100, 100, 'broken'))
        result = self.submit(orders, q, cap, location=replace(loc, history=loc.history.append(broken)))
        self.assertIn('zone_not_valid', result['reasons'])
        self.submit(orders, q, cap)
        orders.request_cancel('add')
        orders.confirm_cancel('add', 0)
        with self.assertRaises(ValueError):
            self.submit(orders, q, cap, 'reuse')

    def test_stale_capacity_and_direction_do_not_create_orders(self):
        m, orders, q, cap = self.setup_case()
        result = self.submit(orders, q, replace(cap, observed_ms=0))
        self.assertIn('capacity_not_current', result['reasons'])
        m.set_direction(-1, timeframe='4h', observed_ms=101, reason='future')
        result = self.submit(orders, q, cap)
        self.assertIn('future_direction_assessment', result['reasons'])
        self.assertFalse(orders.orders)

    def test_long_sizing_costs_and_rounding_respect_budget(self):
        m, orders, q, cap = self.setup_case(1)
        m.increase('base', 1, 5, 104000, 50)
        costs = Costs('.001', '.0001', 1, '.1', '.1', 1)
        cap = replace(cap, stress_loss_budget=32000)
        result = assess_increase(m, self.location(1), q, costs, cap,
                                 requested=5, now_ms=100, max_age_ms=10)
        self.assertTrue(result['allowed'])
        self.assertGreater(result['price'], q.ask)
        self.assertGreaterEqual(result['margin_remaining'], cap.reserve_margin)
        self.assertTrue(all(s['total_pnl'] >= -32000 for s in result['scenarios']))
        self.assertEqual(result['quantity'] % dec('.1'), 0)

    def test_direction_change_requires_cancel_reconciliation(self):
        m, orders, q, cap = self.setup_case()
        self.submit(orders, q, cap)
        with self.assertRaises(ValueError):
            orders.set_direction(1, timeframe='4h', observed_ms=101, reason='reversal')
        orders.request_cancel('add')
        orders.fill('during-cancel', 'add', 2, 102000)
        orders.confirm_cancel('add', 2)
        orders.set_direction(1, timeframe='4h', observed_ms=101, reason='reversal')
        self.assertEqual((m.direction, m.position_side, m.quantity), (1, -1, 2))

    def test_minimum_reduction_fails_without_mutation(self):
        m, orders, q, cap = self.setup_case()
        m.increase('base', -1, '.1', 102000)
        orders.costs = Costs(0, 0, 1, '.1', '.1', 20000)
        with self.assertRaises(ValueError):
            orders.retracement('small', 'r', reference_price=101000)
        self.assertIsNone(m.reduction)
        self.assertFalse(orders.orders)

    def test_duplicate_fill_and_terminal_fill_lock(self):
        m, orders, q, cap = self.setup_case()
        self.submit(orders, q, cap)
        orders.fill('part', 'add', 2, 102000)
        orders.request_cancel('add')
        orders.confirm_cancel('add', 2)
        self.assertFalse(orders.fill('part', 'add', 2, 102000))
        with self.assertRaises(ValueError):
            orders.fill('unexpected', 'add', 1, 102000)
        self.assertTrue(orders.locked)
        with self.assertRaises(ValueError):
            orders.retracement('blocked', 'r', reference_price=101000)

    def test_external_fill_id_cannot_advance_order_twice(self):
        m, orders, q, cap = self.setup_case()
        m.increase('existing', -1, 5, 102000)
        self.submit(orders, q, cap)
        with self.assertRaises(ValueError):
            orders.fill('existing', 'add', 5, 102000)
        self.assertEqual(orders.orders['add'].filled, 0)
        self.assertEqual(m.quantity, 5)
        self.assertTrue(orders.locked)


if __name__ == '__main__':
    unittest.main()
