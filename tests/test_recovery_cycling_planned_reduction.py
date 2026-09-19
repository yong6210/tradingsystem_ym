import json
import unittest
from test_recovery_cycling_reduction_references import engine,ref
from test_recovery_cycling_trial_engine import seed,observe
from app.research.recovery.cycling_planned_reduction import CyclingPlannedReductionEngine
from app.research.recovery.cycling_orders import CyclingOrders


def planned(side=1):
    price=10600 if side==1 else 10400
    e=engine([ref(side,price,'target')],side,engine_class=CyclingPlannedReductionEngine)
    seed(e,6)
    r=e.plan_reduction('target',observed_ms=1,mark=10500,execution_ok=True,funding_known=True)
    return e,r['order_id']


class PlannedReductionTests(unittest.TestCase):
    def test_target_touch_is_not_a_fill(self):
        e,oid=planned()
        observe(e,1,10580,10620,10610)
        self.assertEqual(e.model.quantity,6)
        self.assertEqual(e.orders.active.quantity,3)
        self.assertEqual(e.orders.active.kind,'limit_reduce')

    def test_long_price_floor_and_short_ceiling(self):
        for side in (1,-1):
            e,oid=planned(side);price=e.orders.active.price_cap
            with self.assertRaises(ValueError):e.fill('bad',oid,1,price-side,received_ms=2)
            self.assertEqual(e.model.quantity,6)
            e.fill('good',oid,3,price+side,received_ms=2)
            self.assertEqual(e.model.quantity,3);self.assertEqual(e.model.direction,side)

    def test_partial_cancel_late_fill_resumes_same_limit_and_target(self):
        e,oid=planned()
        e.fill('part',oid,1,10600,received_ms=2)
        e.orders.request_cancel(oid)
        e.fill('late',oid,1,10600,received_ms=3)
        e.orders.confirm_cancel(oid,2)
        r=observe(e,1,10500,10550,10520)
        self.assertEqual(r['kind'],'limit_reduce')
        self.assertEqual(e.orders.active.quantity,1)
        self.assertEqual(e.orders.active.price_cap,10600)
        e.fill('rest',r['order_id'],1,10600,received_ms=60001)
        self.assertEqual(e.model.quantity,3)
        restored=CyclingOrders.restore(json.loads(json.dumps(e.orders.checkpoint())))
        self.assertEqual(restored.model.quantity,3)

    def test_no_repricing_on_breakthrough_after_partial_fill(self):
        e,oid=planned();e.fill('part',oid,1,10600,received_ms=2)
        observe(e,1,10580,10650,10640)
        e.orders.request_cancel(oid);e.orders.confirm_cancel(oid,1)
        r=observe(e,2,10500,10550,10520)
        self.assertEqual(r['kind'],'limit_reduce')
        self.assertEqual(e.orders.active.price_cap,10600)
        self.assertEqual(e.orders.active.quantity,2)

    def test_duplicate_plan_and_past_target_rejected(self):
        e,oid=planned()
        with self.assertRaises(ValueError):e.plan_reduction('target',observed_ms=2,mark=10500,execution_ok=True,funding_known=True)
        other=engine([ref()],engine_class=CyclingPlannedReductionEngine);seed(other)
        with self.assertRaises(ValueError):other.plan_reduction('structural-high',observed_ms=1,mark=10610,execution_ok=True,funding_known=True)
        self.assertFalse(other.orders.orders);self.assertIsNone(other.model.reduction)

    def test_explicit_pause_does_not_silently_replace_cancelled_order(self):
        e,oid=planned()
        e.set_plan_paused(True,observed_ms=2,reason='withdraw pending execution for review')
        e.fill('late',oid,1,10600,received_ms=3)
        e.orders.confirm_cancel(oid,1)
        r=observe(e,1,10500,10550,10520)
        self.assertEqual(r['action'],'planned_reduction_paused_await_explicit_resume')
        self.assertIsNone(e.orders.active)
        e.set_plan_paused(False,observed_ms=60001,reason='retain original plan')
        observe(e,2,10500,10550,10520)
        self.assertEqual(e.orders.active.quantity,2)
        self.assertEqual(e.orders.active.price_cap,10600)

    def test_main_reversal_cancels_limit_before_actual_remainder_exit(self):
        from test_recovery_cycling_roles import record,assessment
        from app.research.recovery.thesis_evidence import ThesisEvidenceRegistry
        e=engine([ref(key='target')],engine_class=CyclingPlannedReductionEngine);seed(e,6)
        e.thesis_registry=ThesisEvidenceRegistry([record('long','formation',1),
            record('break','prior_thesis_invalidation',1,3,invalidates_evidence_ids=['long']),
            record('short','opposite_formation',-1,3)])
        e.assess_main_trend(1,observed_ms=1,reason='synthetic main long',assessment=assessment('maintain',['long']))
        r=e.plan_reduction('target',observed_ms=2,mark=10500,execution_ok=True,funding_known=True);oid=r['order_id']
        e.assess_main_trend(-1,observed_ms=3,reason='synthetic main reversal',assessment=assessment('reversal',['break','short']))
        self.assertEqual(e.orders.active.status,'cancel_pending')
        e.fill('late',oid,1,10600,received_ms=4);e.orders.confirm_cancel(oid,1)
        r=observe(e,1,10500,10550,10520)
        self.assertEqual(r['kind'],'exit');self.assertEqual(e.orders.active.quantity,5)
