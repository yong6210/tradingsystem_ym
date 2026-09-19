from dataclasses import replace
import unittest
from app.research.recovery.guarded_engine import GuardedRecoveryEngine, EntrySubmission
from app.research.recovery.exit_execution import ExitExecution
from tests import test_recovery_entry_assessment as fixtures


class GuardedTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.AdmissionTests()
        self.f.setUp()
        f = self.f
        self.engine = GuardedRecoveryEngine(10000, f.costs)
        self.submission = EntrySubmission(f.support, f.target, f.contract, f.reach(), f.policy,
                                         f.contract.evidence, 1, "trend", False, "", "", True,
                                         ExitExecution(180000, 180000, "100.5", "99.9"))

    def start(self, **changes):
        args = dict(plan=self.f.plan, quote=self.f.quote, submission=self.submission)
        args.update(changes)
        return self.engine.start(**args)

    def assert_no_order(self):
        self.assertFalse(any(r["action"] == "order_intent" for r in self.engine.trace))
        self.assertIsNone(self.engine.ledger)

    def test_ready_creates_intent_not_fill(self):
        self.assertEqual(self.start()["action"], "plan_accepted")
        self.assertEqual(len(self.engine.ledger.orders), 1)
        self.assertEqual(self.engine.ledger.quantity, 0)
        audit = next(r for r in self.engine.trace if r["action"] == "entry_assessment")
        self.assertIn("submission", audit)

    def test_missing_evidence_cannot_use_old_start_api(self):
        self.start(submission=None)
        self.assert_no_order()

    def test_changed_quote_reassesses_reward_risk(self):
        self.assertEqual(self.f.evaluate()["status"], "READY")
        self.start(quote=replace(self.f.quote, bid="100.9", ask="100.9"))
        self.assert_no_order()

    def test_delayed_submission_not_reused(self):
        self.start(quote=replace(self.f.quote, time_ms=120001))
        self.assert_no_order()

    def test_latest_account_and_protection_faults(self):
        for field in ("connected", "reconciled", "protection_ok", "context_known", "thesis_valid"):
            with self.subTest(field=field):
                self.engine = GuardedRecoveryEngine(10000, self.f.costs)
                setattr(self.engine, field, False)
                self.start()
                self.assert_no_order()

    def test_current_equity_caps_submitted_budget(self):
        self.engine.equity = self.f.costs.tick  # budget now smaller than initial risk
        self.start()
        self.assert_no_order()

    def test_ambiguity_rejected_without_consuming_plan(self):
        self.start(submission=replace(self.submission, conflict=True))
        self.assert_no_order()
        self.assertNotIn(self.f.plan.id, self.engine.used_plans)
        self.assertEqual(self.start()["action"], "plan_accepted")

    def test_duplicate_submission_does_not_duplicate_orders(self):
        self.start()
        self.start()
        self.assertEqual(len(self.engine.ledger.orders), 1)

    def test_version_changes_rejected(self):
        other = replace(self.f.plan.support, version=2)
        with self.assertRaises(ValueError):
            self.start(plan=replace(self.f.plan, support=other))
        self.assert_no_order()

    def test_unsupported_splits_cannot_bypass_gate(self):
        self.start(plan=replace(self.f.plan, splits=(("99", 1),), expires_ms=180000))
        self.assert_no_order()

    def test_engine_rr_cannot_be_weakened(self):
        self.engine.policy = replace(self.engine.policy, minimum_rr=10)
        self.start(submission=replace(self.submission, policy=replace(self.f.policy, minimum_rr=".1")))
        self.assert_no_order()

    def test_missing_target_contract_rejected(self):
        self.start(submission=replace(self.submission, contract=None, reach=None))
        self.assert_no_order()

    def test_nearer_first_response_requires_executable_exit_plan(self):
        self.start(submission=replace(self.submission, contract=replace(self.f.contract, first_response_price="100.5")))
        self.assert_no_order()

    def test_malformed_submission_rejected(self):
        with self.assertRaises(ValueError):
            self.start(submission={"status": "READY"})
        self.assert_no_order()

    def test_filled_position_can_still_be_closed(self):
        self.start()
        order = next(iter(self.engine.ledger.orders.values()))
        self.engine.fill("f", order.id, 1, 100, 0, 120001)
        self.engine.set_context(120002, thesis_valid=False, context_known=True)
        reductions = [o for o in self.engine.ledger.orders.values() if o.kind == "reduce"]
        self.assertEqual(len(reductions), 1)
        self.assertEqual(reductions[0].quantity, 1)


if __name__ == "__main__":
    unittest.main()
