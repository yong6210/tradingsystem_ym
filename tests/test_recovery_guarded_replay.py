import copy
import json
import unittest
from dataclasses import replace
from app.research.recovery.guarded_replay import GuardedReplay, make_submission
from app.research.recovery.guarded_engine import GuardedRecoveryEngine
from app.research.recovery.replay import Replay
from app.research.recovery.models import jsonable
from tests import test_recovery_guarded_engine as fixtures


class GuardedReplayTests(unittest.TestCase):
    def setUp(self):
        f = fixtures.GuardedTests()
        f.setUp()
        self.f = f
        self.config = dict(initial_equity="10000", costs=jsonable(f.f.costs), mode="no_add")
        self.event = jsonable(dict(type="start", plan=f.f.plan, quote=f.f.quote,
                                   submission=f.submission, simulate_fills=True))
        self.replay = GuardedReplay(self.config)

    def restore(self, restart=120001):
        envelope = json.loads(json.dumps(self.replay.checkpoint()))
        return GuardedReplay.restore(self.config, envelope, restart)

    def test_submission_json_roundtrip(self):
        self.assertEqual(make_submission(json.loads(json.dumps(self.event["submission"]))), self.f.submission)

    def test_restore_keeps_guard_and_position_but_locks(self):
        self.replay.process(self.event)
        restored = self.restore()
        self.assertIsInstance(restored.engine, GuardedRecoveryEngine)
        self.assertEqual(restored.engine.ledger.quantity, 1)
        self.assertIn("restart", restored.engine.locks)
        self.assertFalse(restored.engine.reconciled)
        self.assertEqual(restored.fill_sequence, 1)

    def test_no_submission_json_cannot_bypass(self):
        del self.event["submission"]
        self.replay.process(self.event)
        self.assertIsNone(self.replay.engine.ledger)
        self.assertIsNone(self.restore().engine.ledger)

    def test_restore_pending_entry_requires_cancel_ack(self):
        self.event["simulate_fills"] = False
        self.replay.process(self.event)
        restored = self.restore()
        order = next(iter(restored.engine.ledger.orders.values()))
        self.assertEqual(order.status, "cancel_pending")
        reconcile = dict(type="reconcile", time_ms=120002, actual_quantity=0, orders_match=True,
                         balance_matches=True, protection_ok=True, thesis_restored=True,
                         gaps_repaired=True, connected=True)
        restored.process(reconcile)
        self.assertFalse(restored.engine.reconciled)
        restored.process(dict(type="cancel_ack", order_id=order.id, time_ms=120003))
        restored.process({**reconcile, "time_ms": 120004})
        self.assertTrue(restored.engine.reconciled)
        # Even after reconciliation, old evidence cannot start another campaign.
        old = copy.deepcopy(self.event)
        old["quote"]["time_ms"] = 120005
        restored.process(old)
        self.assertEqual(len(restored.engine.ledger.orders), 1)
        self.assertEqual(restored.engine.ledger.quantity, 0)

    def test_incompatible_controller_binding_rejected_both_directions(self):
        self.replay.process(self.event)
        with self.assertRaises(ValueError):
            Replay.restore(self.config, self.replay.checkpoint(), 120001)
        with self.assertRaises(ValueError):
            GuardedReplay.restore(self.config, Replay(self.config).checkpoint(), 120001)

    def test_mutated_checkpoint_rejected(self):
        self.replay.process(self.event)
        envelope = self.replay.checkpoint()
        envelope["payload"]["state"]["snapshot"]["cash"] = "999999"
        with self.assertRaises(ValueError):
            GuardedReplay.restore(self.config, envelope, 120001)

    def test_config_changes_rejected_and_caller_mutation_detached(self):
        self.replay.process(self.event)
        changed = {**self.config, "initial_equity": "20000"}
        with self.assertRaises(ValueError):
            GuardedReplay.restore(changed, self.replay.checkpoint(), 120001)
        self.config["costs"]["fee"] = ".9"
        self.assertEqual(self.replay.config["costs"]["fee"], "0")

    def test_event_mutation_does_not_rewrite_journal(self):
        self.replay.process(self.event)
        self.event["submission"]["trade_type"] = "bad"
        self.assertEqual(self.replay.events[0]["submission"]["trade_type"], "trend")
        self.restore()

    def test_guarded_recheckpoint_roundtrip(self):
        self.replay.process(self.event)
        once = self.restore()
        twice = GuardedReplay.restore(self.config, once.checkpoint(), 120002)
        self.assertEqual(twice.engine.ledger.quantity, 1)
        self.assertIn("restart", twice.engine.locks)

    def test_unjournaled_state_change_fails_restore(self):
        self.replay.process(self.event)
        self.replay.engine.funding("outside-journal", 1, 120001)
        with self.assertRaises(ValueError):
            self.restore(120002)

    def test_wrong_reach_binding_not_silently_replaced(self):
        self.event["submission"]["reach"]["target"]["reachability_reason"] = "changed"
        with self.assertRaises(ValueError):
            self.replay.process(self.event)
        self.assertIsNone(self.replay.engine.ledger)

    def test_invalid_mode_and_nonboolean_simulation_rejected(self):
        with self.assertRaises(ValueError):
            GuardedReplay({**self.config, "mode": "confirmed"})
        self.event["simulate_fills"] = "false"
        with self.assertRaises(ValueError):
            self.replay.process(self.event)

    def test_restart_cannot_backdate(self):
        self.replay.process(self.event)
        with self.assertRaises(ValueError):
            self.restore(119999)


if __name__ == "__main__":
    unittest.main()
