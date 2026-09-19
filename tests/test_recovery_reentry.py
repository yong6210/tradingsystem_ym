from dataclasses import replace
import unittest
from app.research.recovery.models import Bar, dec, jsonable
from app.research.recovery.evidence import Evidence
from app.research.recovery.add_admission import ReentrySubmission
from app.research.recovery.guarded_replay import GuardedReplay
from app.research.recovery.scenarios import bar, confirmed_path
from tests import test_recovery_add_admission as fixtures


class ReentryTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.AddAdmissionTests()
        self.f.first_response_qty = 1
        self.f.deadline_minutes = 90
        self.f.setUp()
        self.r = self.f.r
        self.q = replace(self.f.q, bid=dec(110), ask=dec("110.01"))
        self.r.process({"type":"quote", **jsonable(self.q), "simulate_fills":True})
        self.source = next(r for r in self.r.engine.ledger.rows if r.get("reason") == "first_response")
        self.old_confirmed = 53*60000
        path = [bar(54,104,106,105)] + [bar(i,"101.5",103,102) for i in (55,56,57)]
        path += [{**b,"end_ms":b["end_ms"]+9*60000,"received_ms":b["received_ms"]+9*60000}
                 for b in confirmed_path()[:-1]]
        for raw in path:
            self.r.process(raw)
            b = Bar(**{k:v for k,v in raw.items() if k != "type"})
            self.f.support = self.f.support.observe(b)
            self.f.target = self.f.target.observe(b)
        self.q = replace(self.f.q,time_ms=62*60000+1)
        self.sub = ReentrySubmission("p",self.q.time_ms,62*60000,self.f.support,self.f.target,
            Evidence("fixture",62*60000,62*60000,self.q.time_ms,"new reaction after reduction"),
            True,True,True,"fresh independent reentry",10,25,self.source["fill_id"])

    @property
    def e(self):
        return self.r.engine

    def submit(self, sub=None, auto=False):
        self.r.process(jsonable(dict(type="reentry",quote=self.q,submission=sub or self.sub,simulate_fills=auto)))

    def orders(self):
        return [o for o in self.e.ledger.orders.values() if o.reason == "guarded_reentry"]

    def test_fresh_reentry_capped_by_actual_reduction(self):
        self.assertEqual(self.e.ledger.quantity,3)
        self.assertEqual(self.e.confirmation.state,"confirmed")
        self.submit()
        self.assertEqual(self.orders()[0].quantity,1)
        self.assertGreaterEqual(self.orders()[0].stop,self.e.execution.residual_stop)
        self.assertEqual(self.e.ledger.quantity,3)

    def test_fill_rearms_response_without_widening_stop_or_deadline(self):
        deadline = self.e.execution.exit_by_ms
        self.submit(auto=True)
        self.assertEqual(self.e.ledger.quantity,4)
        self.assertEqual(self.e.response_goal,0)
        self.assertTrue(self.e.residual_armed)
        self.assertEqual(self.e.execution.exit_by_ms,deadline)
        self.r.process({"type":"quote",**jsonable(replace(self.q,time_ms=self.q.time_ms+1,bid=dec(110),ask=dec("110.01"))),"simulate_fills":True})
        self.assertEqual(self.e.ledger.quantity,3)

    def test_old_signal_cannot_be_reused(self):
        self.submit(replace(self.sub,confirmed_ms=self.old_confirmed))
        self.assertEqual(len(self.orders()),0)

    def test_unknown_fill_or_unfilled_order_not_credit(self):
        self.submit(replace(self.sub,reduction_fill_id="p:2"))
        self.assertEqual(len(self.orders()),0)

    def test_duplicate_request_does_not_duplicate_restored_quantity(self):
        self.submit()
        self.submit()
        self.assertEqual(len(self.orders()),1)

    def test_cannot_route_reentry_through_adverse_api(self):
        with self.assertRaises(ValueError):
            self.e.submit_add(self.q,self.sub)

    def test_current_capacity_can_reduce_restoration_amount(self):
        self.q = replace(self.q,margin_room_qty=dec(".4"))
        self.submit()
        self.assertEqual(self.orders()[0].quantity,dec(".4"))

    def test_target_price_cannot_skip_exit_priority(self):
        self.q = replace(self.q,bid=dec(110),ask=dec("110.01"))
        self.submit()
        self.assertEqual(len(self.orders()),0)

    def test_restart_preserves_fill_credit_mapping(self):
        self.submit(auto=True)
        restored = GuardedReplay.restore(self.f.config,self.r.checkpoint(),self.q.time_ms+1)
        self.assertEqual(restored.engine.reentry_sources,self.e.reentry_sources)
        self.assertEqual(restored.engine.ledger.quantity,4)
        self.assertIn("restart",restored.engine.locks)

    def test_confirmation_started_before_reduction_is_rejected(self):
        self.e.confirmation.started_ms = self.source["time_ms"]
        self.submit()
        self.assertEqual(len(self.orders()),0)

    def test_consumed_source_fill_cannot_restore_again(self):
        self.submit(auto=True)
        # Isolate the source-credit check from the independently enforced
        # consumed-signal check: no source quantity may be restored twice.
        self.submit()
        rejection = next(r for r in reversed(self.e.trace) if r["action"] == "add_rejected")
        self.assertIn("reduction_credit_consumed",rejection["reasons"])
        self.assertEqual(len(self.orders()),1)

    def test_cancelled_reentry_does_not_erase_executed_credit(self):
        self.submit()
        o = self.orders()[0]
        self.r.process(dict(type="fill",fill_id="partial-reentry",order_id=o.id,
            quantity=".4",price="101.4",fee=0,time_ms=self.q.time_ms+1))
        self.r.process(dict(type="cancel_ack",order_id=o.id,time_ms=self.q.time_ms+2))
        restored = GuardedReplay.restore(self.f.config,self.r.checkpoint(),self.q.time_ms+3)
        saved = restored.engine.ledger.orders[o.id]
        self.assertEqual(saved.filled,dec(".4"))
        self.assertFalse(saved.active)
        self.assertEqual(restored.engine.reentry_sources[o.id],self.source["fill_id"])


if __name__ == "__main__":
    unittest.main()
