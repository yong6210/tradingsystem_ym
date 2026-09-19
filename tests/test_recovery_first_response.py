from dataclasses import replace
import unittest
from app.research.recovery.models import Bar, jsonable
from app.research.recovery.zone_observer import ZoneObserver, replay_zone
from app.research.recovery.entry_assessment import measure_reachability
from app.research.recovery.guarded_replay import GuardedReplay
from tests import test_recovery_exit_execution as fixtures


class FirstResponseTests(unittest.TestCase):
    def setUp(self):
        f = fixtures.ExitExecutionTests()
        f.setUp()
        self.f = f
        contract = replace(f.submission.contract, first_response_price="100.5")
        f.submission = replace(f.submission, contract=contract, reach=f.f.f.reach(contract),
                               execution=replace(f.submission.execution, first_response_qty=".3"))
        self.e = f.e

    def quote(self, time=130000, price="100.5"):
        return replace(self.f.f.f.quote, time_ms=time, bid=price, ask=price)

    def orders(self):
        return [o for o in self.e.ledger.orders.values() if o.reason == "first_response"]

    def test_explicit_quantity_and_residual_no_forced_half(self):
        self.f.start()
        self.e.on_quote(self.quote())
        order = self.orders()[0]
        self.assertEqual(str(order.quantity), "0.3")
        self.assertEqual(self.e.ledger.quantity, 1)
        self.e.fill("reduce", order.id, ".3", "100.5", 0, 130001)
        self.assertEqual(str(self.e.ledger.quantity), "0.7")
        self.assertTrue(self.e.residual_armed)
        self.e.on_quote(self.quote(130002))
        self.assertEqual(len(self.orders()), 1)

    def test_touching_bar_does_not_create_target_fill(self):
        self.f.start()
        self.e.on_bar(Bar(180000, 100, 101, 100, 100, 180000))
        self.assertEqual(len(self.orders()), 0)
        self.assertEqual(self.e.ledger.quantity, 1)

    def test_before_target_no_reduction(self):
        self.f.start()
        self.e.on_quote(self.quote(price="100.4"))
        self.assertEqual(len(self.orders()), 0)

    def test_pending_order_reservation_prevents_duplicate(self):
        self.f.start()
        self.e.on_quote(self.quote())
        self.e.on_quote(self.quote(130001))
        self.assertEqual(len(self.orders()), 1)

    def test_partial_close_cancel_retries_only_unfilled_amount(self):
        self.f.start()
        self.e.on_quote(self.quote())
        order = self.orders()[0]
        self.e.fill("part", order.id, ".1", "100.5", 0, 130001)
        self.e.cancel_ack(order.id, 130002)
        self.e.on_quote(self.quote(130003, "100.4"))
        self.assertEqual(self.orders()[1].quantity, self.e.execution.first_response_qty-self.e.response_closed)
        self.assertEqual(str(self.orders()[1].quantity), "0.2")

    def test_partial_entry_never_sells_unfilled_quantity(self):
        self.f.start(qty=".2")
        self.e.on_quote(self.quote())
        self.assertEqual(str(self.orders()[0].quantity), "0.2")
        self.assertEqual(self.f.order.status, "cancel_pending")

    def test_deadline_wins_over_target(self):
        self.f.start()
        self.e.on_quote(self.quote(200000))
        self.assertEqual(len(self.orders()), 0)
        self.assertTrue(self.e.exit_latched)

    def test_bad_quantity_rejected(self):
        for qty in ("1.1", ".15"):
            with self.subTest(qty=qty):
                s = replace(self.f.submission, execution=replace(self.f.submission.execution, first_response_qty=qty))
                self.e.start(self.f.f.f.plan, self.f.f.f.quote, submission=s)
                self.assertIsNone(self.e.ledger)

    def test_duplicate_fill_does_not_inflate_progress(self):
        self.f.start()
        self.e.on_quote(self.quote())
        order = self.orders()[0]
        for _ in range(2):
            self.e.fill("same", order.id, ".1", "100.5", 0, 130001)
        self.assertEqual(str(self.e.response_closed), "0.1")

    def test_checkpoint_preserves_partial_progress(self):
        config = dict(initial_equity="10000", costs=jsonable(self.f.f.f.costs), mode="no_add")
        replay = GuardedReplay(config)
        replay.process(jsonable(dict(type="start", plan=self.f.f.f.plan, quote=self.f.f.f.quote,
                                      submission=self.f.submission, simulate_fills=True)))
        replay.process({"type": "quote", **jsonable(self.quote()), "simulate_fills": True})
        restored = GuardedReplay.restore(config, replay.checkpoint(), 130001)
        self.assertEqual(str(restored.engine.response_closed), "0.3")
        self.assertEqual(str(restored.engine.ledger.quantity), "0.7")
        self.assertTrue(restored.engine.residual_armed)

    def test_unexecutable_residual_closes_whole_position(self):
        f = self.f.f.f
        f.plan = replace(f.plan, initial_qty=".4")
        self.e.costs = replace(self.e.costs, minimum_qty=".2")
        self.f.start(qty=".4")
        self.e.on_quote(self.quote())
        self.assertEqual(str(self.orders()[0].quantity), "0.4")

    def test_full_close_is_allowed_without_minimum_residual(self):
        self.f.submission = replace(self.f.submission,
                                   execution=replace(self.f.submission.execution, first_response_qty=1))
        self.f.start()
        self.e.on_quote(self.quote())
        self.assertEqual(self.orders()[0].quantity, 1)

    def test_short_first_response_symmetry(self):
        f = self.f.f.f
        bars = [replace(b, open=200-b.open, high=200-b.low, low=200-b.high, close=200-b.close) for b in f.bars]
        support = replace(f.plan.support, low=200-f.plan.support.high, high=200-f.plan.support.low)
        target = replace(f.plan.target, low=200-f.plan.target.high, high=200-f.plan.target.low)
        f.plan = replace(f.plan, side=-1, stop="100.2", support=support, target=target)
        contract = replace(self.f.submission.contract, side=-1, first_response_price="99.5")
        self.f.submission = replace(self.f.submission,
            support=replay_zone(ZoneObserver.start(support, -1, 0, "fixture", 0), bars),
            target=replay_zone(ZoneObserver.start(target, 1, 0, "fixture", 0), bars), contract=contract,
            reach=measure_reachability(contract, bars, source="fixture", lookback_minutes=2), market_side=-1,
            execution=replace(self.f.submission.execution, reaction_price="99.5", residual_stop="100.1"))
        self.f.start()
        self.e.on_quote(self.quote(price="99.5"))
        order = self.orders()[0]
        self.e.fill("short-reduce", order.id, ".3", "99.5", 0, 130001)
        self.assertEqual(str(self.e.ledger.quantity), "0.7")
        self.e.on_quote(self.quote(130002, "100.1"))
        self.assertEqual(self.e.execution_exit_reason, "residual_stop")


if __name__ == "__main__":
    unittest.main()
