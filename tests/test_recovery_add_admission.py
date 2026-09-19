from dataclasses import replace
import unittest
from app.research.recovery.models import Bar, Costs, Plan, Quote, Zone, jsonable, dec
from app.research.recovery.evidence import Evidence, ZoneEvent, ZoneHistory, TargetEvidence
from app.research.recovery.zone_observer import ZoneObserver
from app.research.recovery.entry_assessment import AdmissionPolicy, measure_reachability
from app.research.recovery.exit_execution import ExitExecution
from app.research.recovery.guarded_engine import EntrySubmission
from app.research.recovery.guarded_replay import GuardedReplay
from app.research.recovery.add_admission import AddSubmission
from app.research.recovery.scenarios import confirmed_path


class AddAdmissionTests(unittest.TestCase):
    def setUp(self):
        costs = Costs(".00025", 0, ".01", ".1", ".1", 1)
        self.config = dict(initial_equity="10000", costs=jsonable(costs), mode="no_add")
        self.r = GuardedReplay(self.config)
        bars = [Bar(i*60000, 104, "104.1", "103.9", 104, i*60000) for i in range(1,49)]
        for b in bars:
            self.r.process({"type":"bar", **jsonable(b)})
        s, t = Zone("s",1,100,101,0,"fixture"), Zone("t",1,110,111,0,"fixture")
        def observer(z, side):
            events = (ZoneEvent("formed", "formed", Evidence("fixture",0,0,0,"known zone")),
                      ZoneEvent("validated", "validated", Evidence("fixture",1,1,1,"independent historical validation")))
            return ZoneObserver(ZoneHistory(z,events), side, dec(0), "fixture", bars[-1])
        self.support, self.target = observer(s,1), observer(t,-1)
        now = 48*60000
        deadline = getattr(self,"deadline_minutes",60)*60000
        c = TargetEvidence(t.key,now,1,104,110,deadline,deadline,
            Evidence("fixture",now,now,now,"target"),"explicit fixture","first resistance","exit","exit")
        sub = EntrySubmission(self.support,self.target,c,measure_reachability(c,bars,source="fixture",lookback_minutes=48),
            AdmissionPolicy(1,0,"1.5",100,0),c.evidence,1,"trend",False,"","",True,
            ExitExecution(c.reaction_by_ms,c.expected_by_ms,"104.5",100,
                          first_response_qty=getattr(self,"first_response_qty",None)))
        sub = replace(sub,preplanned=bool(getattr(self,"splits",())))
        q = Quote(now,"102.99",103,100,100,100,True,True)
        p = Plan("p",1,now,s,t,99,4,"fixture",splits=getattr(self,"splits",()),
                 expires_ms=getattr(self,"split_expiry",None))
        self.r.process(jsonable(dict(type="start",plan=p,quote=q,submission=sub,simulate_fills=True)))
        for raw in confirmed_path()[:-1]:
            self.r.process(raw)
            b = Bar(**{k:v for k,v in raw.items() if k != "type"})
            self.support = self.support.observe(b)
            self.target = self.target.observe(b)
        self.q = replace(q,time_ms=53*60000+1,bid=dec("101.39"),ask=dec("101.4"))
        self.sub = AddSubmission("p",self.q.time_ms,53*60000,self.support,self.target,
            Evidence("fixture",53*60000,53*60000,self.q.time_ms,"fresh reaction"),
            True,True,True,"3m recovery and independent later retest hold",10,25)

    @property
    def e(self):
        return self.r.engine

    def submit(self, sub=None, quote=None, auto=False):
        return self.r.process(jsonable(dict(type="add",quote=quote or self.q,
            submission=sub or self.sub,simulate_fills=auto)))

    def adds(self):
        return [o for o in self.e.ledger.orders.values() if o.kind == "add"]

    def test_live_stream_confirmation_required_and_bounded(self):
        self.assertEqual(self.e.confirmation.state,"confirmed")
        self.assertEqual(len(self.adds()),0)
        self.submit()
        order = self.adds()[0]
        self.assertLessEqual(order.quantity,10)
        self.assertGreaterEqual(order.stop,self.e.plan.stop)
        self.assertLessEqual(self.e.ledger.risk_used(),self.e.budget)
        self.assertEqual(self.e.ledger.quantity,4)

    def test_normal_quote_never_automatically_adds(self):
        self.r.process({"type":"quote",**jsonable(self.q),"simulate_fills":True})
        self.assertEqual(len(self.adds()),0)

    def test_duplicate_request_cannot_create_second_order(self):
        self.submit()
        self.submit()
        self.assertEqual(len(self.adds()),1)

    def test_old_confirmation_or_wrong_campaign_rejected(self):
        for sub in (replace(self.sub,confirmed_ms=0),replace(self.sub,plan_id="another")):
            self.submit(sub)
        self.assertEqual(len(self.adds()),0)

    def test_changed_price_recomputes_adverse_geometry(self):
        self.submit(quote=replace(self.q,bid=dec("108.99"),ask=dec(109)))
        self.assertEqual(len(self.adds()),0)

    def test_current_capacity_caps_quantity(self):
        self.submit(quote=replace(self.q,margin_room_qty=dec(".3")))
        self.assertEqual(self.adds()[0].quantity,dec(".3"))

    def test_below_minimum_does_not_round_up(self):
        self.submit(sub=replace(self.sub,maximum_qty=".01"))
        self.assertEqual(len(self.adds()),0)

    def test_incomplete_thesis_rejected(self):
        self.submit(sub=replace(self.sub,conflicts_resolved=False))
        self.assertEqual(len(self.adds()),0)

    def test_funding_losses_do_not_expand_budget(self):
        self.e.ledger.funding("test",90,self.e.last_time)
        self.submit()
        self.assertEqual(len(self.adds()),0)

    def test_reduction_has_priority(self):
        self.e._reduce({"p:1":dec(1)},"test_reduction")
        self.submit()
        self.assertEqual(len(self.adds()),0)

    def test_partial_fills_count_as_one_event(self):
        self.submit()
        o = self.adds()[0]
        self.r.process(dict(type="fill",fill_id="a",order_id=o.id,quantity=".1",price="101.4",fee=0,time_ms=self.q.time_ms+1))
        self.r.process(dict(type="fill",fill_id="b",order_id=o.id,quantity=".1",price="101.4",fee=0,time_ms=self.q.time_ms+2))
        self.assertEqual(len(self.e.ledger.add_events),1)

    def test_replay_and_restart_preserve_guarded_add(self):
        self.submit(auto=True)
        restored = GuardedReplay.restore(self.config,self.r.checkpoint(),self.q.time_ms+1)
        self.assertEqual(len(restored.engine.ledger.add_events),1)
        self.assertIn("restart",restored.engine.locks)
        self.assertGreater(restored.engine.ledger.quantity,4)


if __name__ == "__main__":
    unittest.main()
