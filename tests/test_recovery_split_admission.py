from dataclasses import replace
import unittest
from app.research.recovery.models import dec, jsonable
from app.research.recovery.evidence import Evidence
from app.research.recovery.split_admission import SplitSubmission
from app.research.recovery.guarded_replay import GuardedReplay
from tests import test_recovery_add_admission as fixtures


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.AddAdmissionTests()
        self.f.splits = (("100.8",1),("100.4",1))
        self.f.split_expiry = 58*60000
        self.f.setUp()
        self.r = self.f.r
        self.q = replace(self.f.q,bid=dec("100.79"),ask=dec("100.8"))
        self.sub = SplitSubmission("p",0,self.q.time_ms,self.f.support,self.f.target,
            Evidence("fixture",53*60000,53*60000,self.q.time_ms,"original support still valid"),
            True,True,True,"predeclared tranche remains valid")

    @property
    def e(self):
        return self.r.engine

    def submit(self, sub=None, auto=False):
        self.r.process(jsonable(dict(type="split",quote=self.q,submission=sub or self.sub,simulate_fills=auto)))

    def planned(self):
        return [o for o in self.e.ledger.orders.values() if o.kind == "planned"]

    def test_full_schedule_reserved_without_creating_split_orders(self):
        self.assertEqual(len(self.e.ledger.orders),1)
        self.assertEqual(len(self.e.plan.splits),2)
        self.assertGreater(self.e.unsubmitted_split_risk(),0)
        snap = self.e.snapshot()["guarded_splits"]
        self.assertGreater(dec(snap["total_committed_loss"]),self.e.ledger.risk_used())

    def test_explicit_tranche_transfers_reservation_without_double_count(self):
        before = self.e.ledger.risk_used()+self.e.unsubmitted_split_risk()
        self.submit()
        self.assertEqual(self.planned()[0].quantity,1)
        self.assertEqual(self.planned()[0].limit,dec("100.8"))
        self.assertEqual(self.e.ledger.risk_used()+self.e.unsubmitted_split_risk(),before)
        self.assertEqual(self.e.ledger.quantity,4)

    def test_quote_alone_cannot_release_schedule(self):
        self.r.process({"type":"quote",**jsonable(self.q),"simulate_fills":True})
        self.assertEqual(len(self.planned()),0)

    def test_outside_declared_price_rejected(self):
        self.q = replace(self.q,bid=dec("100.89"),ask=dec("100.9"))
        self.submit()
        self.assertEqual(len(self.planned()),0)

    def test_current_capacity_does_not_inflate_or_rewrite_quantity(self):
        self.q = replace(self.q,liquidity_qty=dec(".5"))
        self.submit()
        self.assertEqual(len(self.planned()),0)
        self.assertEqual(self.e.split_slots[0]["qty"],1)

    def test_missing_or_relabelled_tranche_rejected(self):
        self.submit(replace(self.sub,index=2))
        self.assertEqual(len(self.planned()),0)

    def test_one_tranche_cannot_be_submitted_twice(self):
        self.submit(auto=True)
        self.submit()
        self.assertEqual(len(self.planned()),1)
        self.assertEqual(self.e.ledger.quantity,5)

    def test_reserved_budget_cannot_be_used_for_another_add(self):
        self.f.submit()
        self.assertFalse(any(o.kind == "add" for o in self.e.ledger.orders.values()))
        self.assertIn("preplanned_reservations_must_finish_or_expire",self.e.trace[-1]["reasons"])

    def test_exact_expiry_releases_unsubmitted_and_cancels_pending(self):
        self.submit()
        self.r.process(dict(type="heartbeat",time_ms=58*60000))
        self.assertEqual(self.e.unsubmitted_split_risk(),0)
        self.assertEqual(self.planned()[0].status,"cancel_pending")

    def test_funding_cost_requires_full_reserved_budget_recheck(self):
        self.r.process(dict(type="funding",event_id="fund",amount=81,time_ms=self.q.time_ms))
        self.submit()
        self.assertEqual(len(self.planned()),0)

    def test_partial_fill_and_cancel_never_reopens_same_slot(self):
        self.submit()
        o = self.planned()[0]
        self.r.process(dict(type="fill",fill_id="part",order_id=o.id,quantity=".4",price="100.8",fee=0,time_ms=self.q.time_ms+1))
        self.r.process(dict(type="cancel_ack",order_id=o.id,time_ms=self.q.time_ms+2))
        self.q = replace(self.q,time_ms=self.q.time_ms+3)
        self.submit(replace(self.sub,decision_ms=self.q.time_ms))
        self.assertEqual(len(self.planned()),1)
        self.assertEqual(self.e.ledger.quantity,dec("4.4"))

    def test_checkpoint_keeps_reservations_and_restart_lock(self):
        self.submit(auto=True)
        restored = GuardedReplay.restore(self.f.config,self.r.checkpoint(),self.q.time_ms+1)
        self.assertEqual(restored.engine.split_slots,self.e.split_slots)
        self.assertEqual(restored.engine.unsubmitted_split_risk(),self.e.unsubmitted_split_risk())
        self.assertIn("restart",restored.engine.locks)

    def test_whole_thesis_exit_releases_remaining_schedule(self):
        self.r.process(dict(type="context",time_ms=self.q.time_ms,thesis_valid=False,context_known=True))
        self.assertEqual(self.e.unsubmitted_split_risk(),0)
        self.assertTrue(all(s["released"] for s in self.e.split_slots))

    def test_original_zone_version_is_required(self):
        self.r.process(dict(type="context",time_ms=self.q.time_ms,thesis_valid=True,context_known=True,
                            support=jsonable(replace(self.e.support,version=2))))
        self.submit()
        self.assertEqual(len(self.planned()),0)
        self.assertIn("original_split_basis_changed",self.e.trace[-1]["reasons"])

    def test_adverse_price_below_stop_cannot_fill_split(self):
        self.q = replace(self.q,bid=dec("98.99"),ask=dec(99))
        self.submit(auto=True)
        self.assertEqual(len(self.planned()),0)
        self.assertEqual(self.e.unsubmitted_split_risk(),0)


if __name__ == "__main__":
    unittest.main()
