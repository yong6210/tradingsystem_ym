from dataclasses import replace
import unittest
from app.research.recovery.models import Zone
from app.research.recovery.evidence import Evidence, ZoneEvent, ZoneHistory, TargetEvidence, assess_evidence


def event(kind, time, recorded=None):
    return ZoneEvent(f"{kind}:{time}", kind, Evidence("completed-bar:fixture", time, time,
                                                     time if recorded is None else recorded, "explicit test criterion"))


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.support = ZoneHistory(Zone("s", 1, 90, 95, 10, "fixture"),
                                   (event("formed", 10), event("validated", 20)))
        self.target = ZoneHistory(Zone("t", 1, 110, 115, 10, "fixture"),
                                  (event("formed", 10), event("validated", 20)))
        self.contract = TargetEvidence("t:1", 30, 1, 100, 110, 300, 60,
                                       Evidence("fixture", 25, 26, 27, "target selection"),
                                       "explicit horizon-linked structure", "no nearer structure in inspected source",
                                       "exit on timeout", "exit if retest fails")

    def test_complete_does_not_authorize_order(self):
        result = assess_evidence(self.support, self.target, self.contract, 30)
        self.assertEqual(result["status"], "EVIDENCE_COMPLETE")
        self.assertFalse(result["order_authorized"])

    def test_late_information_not_backdated(self):
        later = self.support.append(event("broken", 25, 40))
        self.assertEqual(later.as_of(30), self.support.as_of(30))
        self.assertEqual(later.as_of(40)["state"], "broken")

    def test_reclaim_requires_revalidation(self):
        h = self.support.append(event("broken", 25)).append(event("reclaimed", 26))
        self.assertEqual(assess_evidence(h, self.target, self.contract, 30)["status"], "UNASSESSED")
        self.assertEqual(h.append(event("validated", 29)).as_of(30)["state"], "valid")

    def test_invalidated_priority_over_missing(self):
        h = self.support.append(event("broken", 25))
        self.assertEqual(assess_evidence(h, self.target, None, 30)["status"], "INVALIDATED")

    def test_future_target_evidence_rejected(self):
        with self.assertRaises(ValueError):
            replace(self.contract, evidence=Evidence("fixture", 20, 25, 31, "late"))

    def test_version_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            assess_evidence(self.support, self.target, replace(self.contract, target_key="t:2"), 30)

    def test_missing_target_reason_not_defaulted(self):
        result = assess_evidence(self.support, self.target, replace(self.contract, reachability_reason=""), 30)
        self.assertEqual(result["status"], "UNASSESSED")
        self.assertIn("reachability_reason", result["reasons"])

    def test_cannot_skip_nearest_response(self):
        result = assess_evidence(self.support, self.target, replace(self.contract, first_response_price=120), 30)
        self.assertIn("first_response_beyond_target", result["reasons"])

    def test_duplicate_and_illegal_transition_rejected(self):
        for e in (event("validated", 20), event("reclaimed", 25)):
            with self.assertRaises(ValueError):
                self.support.append(e)

    def test_stale_observation_rejected(self):
        with self.assertRaises(ValueError):
            self.support.append(event("reaction", 15, 25))

    def test_retired_cannot_revive(self):
        with self.assertRaises(ValueError):
            self.support.append(event("retired", 25)).append(event("validated", 26))

    def test_time_and_geometry_validation(self):
        for kwargs in (dict(reaction_by_ms=30), dict(expected_by_ms=50), dict(side=0),
                       dict(first_response_price=90), dict(decision_ms=True)):
            with self.assertRaises(ValueError):
                replace(self.contract, **kwargs)

    def test_contract_cannot_be_reused_later(self):
        with self.assertRaises(ValueError):
            assess_evidence(self.support, self.target, self.contract, 31)

    def test_short_geometry(self):
        short = replace(self.contract, side=-1, reference_price=120, first_response_price=115)
        self.assertEqual(assess_evidence(self.support, self.target, short, 30)["status"], "EVIDENCE_COMPLETE")

    def test_mutable_input_is_copied(self):
        events = list(self.support.events)
        h = ZoneHistory(self.support.zone, events)
        events.clear()
        self.assertEqual(h.as_of(30)["state"], "valid")


if __name__ == "__main__":
    unittest.main()
