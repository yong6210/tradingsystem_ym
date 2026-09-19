from dataclasses import replace
import unittest
from app.research.recovery.models import Bar, jsonable
from app.research.recovery.exit_execution import ExitExecution
from app.research.recovery.guarded_replay import GuardedReplay
from tests import test_recovery_guarded_engine as fixtures


class ExitExecutionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.GuardedTests()
        self.f.setUp()
        f = self.f.f
        contract = replace(f.contract, reaction_by_ms=200000, expected_by_ms=240000)
        self.submission = replace(self.f.submission, contract=contract, reach=f.reach(contract),
            policy=replace(f.policy, minimum_samples=1), execution=ExitExecution(200000, 240000, "100.5", "99.9"))
        self.e = self.f.engine

    def start(self, qty=1):
        self.e.start(self.f.f.plan, self.f.f.quote, submission=self.submission)
        self.order = next(iter(self.e.ledger.orders.values()))
        if qty:
            self.e.fill("initial", self.order.id, qty, 100, 0, 120001)

    def reductions(self):
        return [o for o in self.e.ledger.orders.values() if o.kind == "reduce"]

    def response_bar(self, received=180000):
        return Bar(180000, 100, 101, 100, "100.5", received)

    def test_missing_execution_rules_rejected(self):
        self.e.start(self.f.f.plan, self.f.f.quote, submission=replace(self.submission, execution=None))
        self.assertIsNone(self.e.ledger)

    def test_deadline_exact_boundary_and_no_duplicate_reductions(self):
        self.start()
        self.e.heartbeat(199999)
        self.assertEqual(len(self.reductions()), 0)
        self.e.heartbeat(200000)
        self.e.heartbeat(200001)
        self.assertEqual(len(self.reductions()), 1)
        self.assertEqual(self.e.execution_exit_reason, "reaction_deadline")
        self.assertEqual(self.e.ledger.quantity, 1)  # intent is not a fill

    def test_response_satisfied_but_hard_deadline_still_exits(self):
        self.start()
        self.e.on_bar(self.response_bar())
        self.assertTrue(self.e.reaction_seen)
        self.e.heartbeat(200000)
        self.assertEqual(len(self.reductions()), 0)
        self.e.heartbeat(240000)
        self.assertEqual(len(self.reductions()), 1)
        self.assertEqual(self.e.execution_exit_reason, "holding_deadline")

    def test_delayed_response_cannot_rescue_expired_trade(self):
        self.start()
        self.e.on_bar(self.response_bar(received=200000))
        self.assertFalse(self.e.reaction_seen)
        self.assertEqual(len(self.reductions()), 1)

    def test_unfilled_entry_cancelled_without_fictitious_close(self):
        self.start(qty=0)
        self.e.heartbeat(200000)
        self.assertEqual(self.order.status, "cancel_pending")
        self.assertEqual(len(self.reductions()), 0)

    def test_partial_entry_then_cancel_race_all_quantity_reserved(self):
        self.start(qty=".4")
        self.e.heartbeat(200000)
        self.e.fill("late", self.order.id, ".6", 100, 0, 200001)
        self.assertEqual(self.e.ledger.quantity, 1)
        self.assertEqual(sum(o.remaining for o in self.reductions()), 1)

    def test_partial_reduction_arms_residual_stop(self):
        self.start()
        self.e._reduce({self.order.id: self.e.ledger.quantity / 2}, "test_partial")
        reduction = self.reductions()[0]
        self.e.fill("partial", reduction.id, ".5", 100, 0, 130000)
        self.assertTrue(self.e.residual_armed)
        self.e.on_quote(replace(self.f.f.quote, time_ms=130001, bid="99.9", ask="99.9"))
        self.assertEqual(sum(o.remaining for o in self.reductions()), self.e.ledger.quantity)
        self.assertEqual(self.e.execution_exit_reason, "residual_stop")

    def test_unfilled_reduction_does_not_arm_stop(self):
        self.start()
        self.e._reduce({self.order.id: self.e.ledger.quantity / 2}, "test_partial")
        self.assertFalse(self.e.residual_armed)

    def test_disconnect_deadline_latched_until_transport_returns(self):
        self.start()
        self.e.fault(130000, "connection", connected=False)
        self.e.heartbeat(200000)
        self.assertTrue(self.e.exit_latched)
        self.assertEqual(len(self.reductions()), 0)
        self.e.reconcile(200001, actual_quantity=1, orders_match=True, balance_matches=True,
                         protection_ok=True, thesis_restored=True, gaps_repaired=True, connected=True)
        self.e.heartbeat(200002)
        self.assertEqual(len(self.reductions()), 1)

    def test_restart_restores_rules_and_enforces_elapsed_deadline(self):
        config = dict(initial_equity="10000", costs=jsonable(self.f.f.costs), mode="no_add")
        r = GuardedReplay(config)
        r.process(jsonable(dict(type="start", plan=self.f.f.plan, quote=self.f.f.quote,
                                submission=self.submission, simulate_fills=True)))
        restored = GuardedReplay.restore(config, r.checkpoint(), 240000)
        self.assertEqual(restored.engine.execution, self.submission.execution)
        self.assertTrue(restored.engine.exit_latched)
        self.assertEqual(restored.engine.execution_exit_reason, "holding_deadline")
        self.assertEqual(len([o for o in restored.engine.ledger.orders.values() if o.kind == "reduce"]), 1)

    def test_mismatched_deadlines_rejected(self):
        s = replace(self.submission, execution=replace(self.submission.execution, exit_by_ms=300000))
        self.e.start(self.f.f.plan, self.f.f.quote, submission=s)
        self.assertIsNone(self.e.ledger)

    def test_residual_stop_cannot_widen_initial_stop(self):
        s = replace(self.submission, execution=replace(self.submission.execution, residual_stop=90))
        self.e.start(self.f.f.plan, self.f.f.quote, submission=s)
        self.assertIsNone(self.e.ledger)


if __name__ == "__main__":
    unittest.main()
