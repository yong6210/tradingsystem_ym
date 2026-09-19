from dataclasses import replace
import unittest
from app.research.recovery.models import Bar, Zone, Plan, Quote, Costs
from app.research.recovery.evidence import Evidence, TargetEvidence
from app.research.recovery.zone_observer import ZoneObserver, replay_zone
from app.research.recovery.entry_assessment import measure_reachability, AdmissionPolicy, assess_entry


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.bars = [Bar(60000, 100, 102, 98, 100, 60000),
                     Bar(120000, 100, 110, 99, 100, 120000)]
        s = Zone("s", 1, 98, 99, 0, "fixture")
        t = Zone("t", 1, 101, 102, 0, "fixture")
        self.support = replay_zone(ZoneObserver.start(s, 1, 0, "fixture", 0), self.bars)
        self.target = replay_zone(ZoneObserver.start(t, -1, 0, "fixture", 0), self.bars)
        self.plan = Plan("p", 1, 120000, s, t, "99.8", 1, "fixture")
        self.contract = TargetEvidence(t.key, 120000, 1, 100, 101, 180000, 180000,
                                       Evidence("fixture", 120000, 120000, 120000, "known structure"),
                                       "historical excursion diagnostic", "first resistance", "exit", "exit")
        self.quote = Quote(120000, 100, 100, 10, 10, 10, True, True)
        self.costs = Costs(0, 0, ".1", ".1", ".1", 0)
        self.policy = AdmissionPolicy(2, ".5", "1.5", 1, 0)

    def reach(self, contract=None, bars=None, lookback=2):
        return measure_reachability(contract or self.contract, self.bars if bars is None else bars,
                                    source="fixture", lookback_minutes=lookback)

    def evaluate(self, **changes):
        args = dict(plan=self.plan, support=self.support, target=self.target,
                    contract=self.contract, reach=self.reach(), quote=self.quote, costs=self.costs,
                    policy=self.policy, context_evidence=self.contract.evidence,
                    market_side=1, trade_type="trend", conflict=False,
                    conflict_resolution="", countertrend_reason="", thesis_valid=True)
        args.update(changes)
        return assess_entry(**args)

    def test_ready_is_research_only(self):
        result = self.evaluate()
        self.assertEqual(result["status"], "READY")
        self.assertFalse(result["order_authorized"])

    def test_future_bar_invariance(self):
        extra = Bar(180000, 100, 999, 1, 100, 180000)
        self.assertEqual(self.reach(), self.reach(bars=self.bars+[extra]))

    def test_late_missing_duplicate_and_reverse_rejected(self):
        for bars in (self.bars[1:], self.bars+self.bars[-1:], list(reversed(self.bars)),
                     [self.bars[0], replace(self.bars[1], received_ms=180000)]):
            with self.assertRaises(ValueError):
                self.reach(bars=bars)

    def test_horizon_uses_disjoint_complete_blocks(self):
        c = replace(self.contract, expected_by_ms=240000)
        r = self.reach(c)
        self.assertEqual(len(r.excursions), 1)
        self.assertEqual(r.reached_fraction, 1)

    def test_insufficient_samples_not_zero_probability(self):
        c = replace(self.contract, expected_by_ms=300000)
        r = self.reach(c)
        self.assertIsNone(r.reached_fraction)
        self.assertEqual(self.evaluate(contract=c, reach=r)["status"], "UNASSESSED")

    def test_missing_contract(self):
        self.assertEqual(self.evaluate(contract=None, reach=None)["status"], "UNASSESSED")

    def test_context_conflict_and_independent_countertrend(self):
        self.assertEqual(self.evaluate(conflict=True)["status"], "CONFLICTED")
        self.assertEqual(self.evaluate(market_side=-1, trade_type="countertrend")["status"], "UNASSESSED")
        self.assertEqual(self.evaluate(market_side=-1, trade_type="countertrend", countertrend_reason="independent rejection")["status"], "READY")

    def test_execution_fault_wins_but_retains_other_reasons(self):
        result = self.evaluate(quote=replace(self.quote, execution_ok=False), thesis_valid=False, reach=None)
        self.assertEqual(result["status"], "EXECUTION_BLOCKED")
        self.assertIn("thesis_or_zone_invalidated", result["reasons"])
        self.assertIn("horizon_evidence_missing", result["reasons"])

    def test_all_planned_splits_count_toward_loss(self):
        p = replace(self.plan, splits=(("99.9", 10),), expires_ms=180000)
        result = self.evaluate(plan=p)
        self.assertIn("planned_loss_budget_exceeded", result["reasons"])
        self.assertIn("capacity_insufficient_for_plan", result["reasons"])

    def test_fees_affect_first_response_rr(self):
        result = self.evaluate(costs=Costs(".01", 0, ".1", ".1", ".1", 0))
        self.assertIn("order:0:cost_adjusted_rr", result["reasons"])

    def test_wrong_contract_binding_rejected(self):
        with self.assertRaises(ValueError):
            self.evaluate(contract=replace(self.contract, expected_by_ms=240000))

    def test_stale_quote_blocked(self):
        self.assertEqual(self.evaluate(quote=replace(self.quote, time_ms=119999))["status"], "EXECUTION_BLOCKED")

    def test_future_context_rejected(self):
        with self.assertRaises(ValueError):
            self.evaluate(context_evidence=Evidence("fixture", 120000, 120000, 120001, "late"))

    def test_short_excursion(self):
        c = replace(self.contract, side=-1, first_response_price=99)
        self.assertEqual(self.reach(c).reached_fraction, 1)

    def test_non_executable_quantity_rejected(self):
        self.assertIn("order:0:invalid_quantity", self.evaluate(plan=replace(self.plan, initial_qty=".15"))["reasons"])


if __name__ == "__main__":
    unittest.main()
