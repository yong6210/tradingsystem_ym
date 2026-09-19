from dataclasses import replace
import unittest
from app.research.recovery.models import Bar, Zone, dec, jsonable
from app.research.recovery.evidence import Evidence
from app.research.recovery.zone_observer import ZoneObserver
from app.research.recovery.add_admission import ProfitAddSubmission
from app.research.recovery.guarded_replay import GuardedReplay
from app.research.recovery.scenarios import bar
from tests import test_recovery_add_admission as fixtures


class ProfitAddTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.AddAdmissionTests()
        self.f.deadline_minutes = 90
        self.f.setUp()
        self.r = self.f.r
        # Register before the breakout minute begins, not after seeing its close.
        self.prior = Zone("continuation",1,104,105,53*60000,"prior resistance fixture")
        self.r.process(dict(type="continuation_zone",zone=jsonable(self.prior),time_ms=53*60000))
        raw = bar(54,104,106,"105.4",104)
        self.r.process(raw)
        b = Bar(**{k:v for k,v in raw.items() if k != "type"})
        self.target = self.f.target.observe(b)
        self.new = replace(self.prior,version=2,available_ms=54*60000,evidence="breakout support fixture")
        self.r.process(dict(type="context",time_ms=54*60000,thesis_valid=True,context_known=True,support=jsonable(self.new)))
        self.support = ZoneObserver.start(self.new,1,0,"fixture",54*60000)
        for raw in [bar(55,"104.8",106,"104.9"),bar(56,"104.9","105.5","105.3"),
                    bar(57,"105.2","105.6","105.4"),bar(58,"105.01","105.4","105.2"),
                    bar(59,"105.05","105.5","105.4")]:
            self.r.process(raw)
            b = Bar(**{k:v for k,v in raw.items() if k != "type"})
            self.support = self.support.observe(b)
            self.target = self.target.observe(b)
        self.q = replace(self.f.q,time_ms=59*60000+1,bid=dec("105.39"),ask=dec("105.4"))
        self.sub = ProfitAddSubmission("p",self.q.time_ms,59*60000,self.support,self.target,
            Evidence("fixture",59*60000,59*60000,self.q.time_ms,"fresh breakout/retest"),
            True,True,True,"independent trend continuation",10,25,self.prior.key,54*60000)

    @property
    def e(self):
        return self.r.engine

    def orders(self):
        return [o for o in self.e.ledger.orders.values() if o.reason == "guarded_profit_add"]

    def submit(self, sub=None, auto=False):
        self.r.process(jsonable(dict(type="profit_add",quote=self.q,submission=sub or self.sub,simulate_fills=auto)))

    def test_breakout_new_support_retest_then_explicit_profit_add(self):
        self.assertEqual(self.e.confirmation.state,"confirmed")
        self.submit()
        self.assertEqual(len(self.orders()),1)
        self.assertGreaterEqual(self.orders()[0].stop,self.e.plan.stop)
        self.assertLessEqual(self.e.ledger.risk_used(),self.e.budget)
        self.assertEqual(self.e.ledger.quantity,4)

    def test_normal_price_events_do_not_add(self):
        self.r.process({"type":"quote",**jsonable(self.q),"simulate_fills":True})
        self.assertEqual(len(self.orders()),0)

    def test_unknown_prior_zone_rejected(self):
        self.submit(replace(self.sub,prior_resistance_key="unknown:1"))
        self.assertEqual(len(self.orders()),0)

    def test_relabelled_bounds_not_accepted_as_role_reversal(self):
        prior = replace(self.prior,low=103)
        self.e.continuation_levels[prior.key] = (prior,53*60000)
        self.submit()
        self.assertEqual(len(self.orders()),0)

    def test_late_registration_cannot_justify_past_breakout(self):
        self.e.continuation_levels[self.prior.key] = (self.prior,54*60000)
        self.submit()
        self.assertEqual(len(self.orders()),0)

    def test_unrealized_profit_does_not_expand_risk_budget(self):
        budget = self.e.budget
        self.submit(auto=True)
        self.assertEqual(self.e.budget,budget)
        self.assertLessEqual(self.e.ledger.risk_used(),budget)

    def test_near_target_reward_risk_rejects_add(self):
        self.q = replace(self.q,bid=dec("109.89"),ask=dec("109.9"))
        self.submit()
        self.assertEqual(len(self.orders()),0)

    def test_funding_cost_can_remove_net_profit(self):
        self.r.process(dict(type="funding",event_id="cost",amount=12,time_ms=self.q.time_ms))
        self.submit()
        self.assertEqual(len(self.orders()),0)

    def test_duplicate_request_consumes_only_one_confirmation(self):
        self.submit()
        self.submit()
        self.assertEqual(len(self.orders()),1)

    def test_profit_contract_cannot_use_adverse_api(self):
        with self.assertRaises(ValueError):
            self.e.submit_add(self.q,self.sub)

    def test_restore_replays_registered_level_and_explicit_add(self):
        self.submit(auto=True)
        restored = GuardedReplay.restore(self.f.config,self.r.checkpoint(),self.q.time_ms+1)
        self.assertEqual(restored.engine.continuation_levels,self.e.continuation_levels)
        self.assertEqual(len(restored.engine.ledger.add_events),1)
        self.assertIn("restart",restored.engine.locks)

    def test_close_inside_or_already_beyond_zone_is_not_new_breakout(self):
        for minute in (55,57):
            self.submit(replace(self.sub,breakout_end_ms=minute*60000))
        self.assertEqual(len(self.orders()),0)

    def test_registration_cannot_rewrite_same_version(self):
        with self.assertRaises(ValueError):
            self.e.register_continuation_level(replace(self.prior,high=106),self.q.time_ms)

    def test_source_must_precede_new_support_version(self):
        self.e.continuation_levels[self.prior.key] = (replace(self.prior,version=2),53*60000)
        self.submit()
        self.assertEqual(len(self.orders()),0)


if __name__ == "__main__":
    unittest.main()
