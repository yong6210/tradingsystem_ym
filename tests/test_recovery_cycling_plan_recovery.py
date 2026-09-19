import json
import unittest
from decimal import Decimal as D
from test_recovery_cycling_order_coordination import prepared
from test_recovery_cycling_trial_engine import observe,cap
from app.research.recovery.cycling_plan_recovery import CyclingPlanRecoveryEngine
from app.research.recovery.cycling_orders import CyclingOrders


def settled():
    e,oid=prepared(CyclingPlanRecoveryEngine)
    observe(e,1,10420,10450,10430);observe(e,2,10390,10430,10420)
    e.fill('old-late',oid,1,10600,received_ms=120001);e.orders.confirm_cancel(oid,1)
    observe(e,3,10420,10450,10430)
    return e,oid


class RecoveryTests(unittest.TestCase):
    def test_disappeared_signal_restores_original_two_not_half_of_five(self):
        e,oid=settled();r=observe(e,4,10420,10450,10430)
        self.assertEqual(r['kind'],'limit_reduce');self.assertEqual(e.orders.active.quantity,2)
        self.assertEqual(e.orders.active.event_id,e.orders.orders[oid].event_id)
        self.assertFalse(e.replan_required)
        restored=CyclingOrders.restore(json.loads(json.dumps(e.orders.checkpoint())))
        self.assertEqual(restored.model.reduction.remaining,2)

    def test_denied_add_restores_original_remainder(self):
        e,oid=settled()
        r=observe(e,4,10390,10430,10420,capacity=cap(4,maximum_total=5))
        self.assertEqual(r['kind'],'limit_reduce');self.assertEqual(e.orders.active.quantity,2)

    def test_partial_add_waits_for_cancel_ack_then_halves_new_total(self):
        e,oid=settled();r=observe(e,4,10390,10430,10420);addid=r['order_id']
        e.fill('partial',addid,'.5',10420,received_ms=240001)
        e.orders.request_cancel(addid)
        observe(e,5,10420,10450,10430)
        self.assertEqual(e.orders.active.id,addid)
        e.fill('late-add',addid,'.5',10420,received_ms=300001)
        e.orders.confirm_cancel(addid,1)
        r=observe(e,6,10420,10450,10430)
        self.assertEqual(r['kind'],'limit_reduce');self.assertEqual(e.model.quantity,6)
        self.assertEqual(e.orders.active.quantity,3)
        self.assertNotEqual(e.orders.active.event_id,e.orders.orders[oid].event_id)

    def test_unfilled_add_restores_original_remaining(self):
        e,oid=settled();r=observe(e,4,10390,10430,10420);addid=r['order_id']
        e.orders.request_cancel(addid);e.orders.confirm_cancel(addid,0)
        r=observe(e,5,10420,10450,10430)
        self.assertEqual(r['kind'],'limit_reduce');self.assertEqual(e.orders.active.quantity,2)

    def test_invalidated_reference_no_farther_replacement(self):
        e,oid=settled();r=observe(e,4,10610,10650,10630)
        self.assertEqual(r['action'],'plan_recovery_reference_unavailable')
        self.assertIsNone(e.orders.active);self.assertTrue(e.replan_required)

    def test_missing_capacity_defers_recovery(self):
        e,oid=settled();r=observe(e,4,10420,10450,10430,capacity=None)
        self.assertEqual(r['action'],'plan_recovery_wait_fresh_capacity')
        self.assertIsNone(e.orders.active)
        r=observe(e,5,10420,10450,10430)
        self.assertEqual(r['kind'],'limit_reduce')

    def test_full_add_restores_new_half_before_another_add(self):
        e,oid=settled();r=observe(e,4,10390,10430,10420)
        e.fill('all-add',r['order_id'],2,10420,received_ms=240001)
        observe(e,5,10420,10450,10430)
        self.assertEqual(e.orders.active.kind,'limit_reduce')
        self.assertEqual(e.orders.active.quantity,D('3.5'))

    def test_duplicate_bar_cannot_issue_second_recovery(self):
        e,oid=settled();observe(e,4,10420,10450,10430)
        n=len(e.orders.orders)
        observe(e,4,10420,10450,10430)
        self.assertEqual(len(e.orders.orders),n)

    def test_ledger_resume_rejects_inventory_change(self):
        e,oid=settled()
        e.model.increase('outside-add',1,1,10420)
        with self.assertRaises(ValueError):
            e.model.resume_reduction(e.orders.orders[oid].event_id,'cannot restore old basis after add')

    def test_short_restores_original_remainder_symmetrically(self):
        from test_recovery_cycling_reduction_references import engine,ref
        from test_recovery_cycling_trial_engine import seed
        from test_recovery_cycling_roles import record,assessment
        from app.research.recovery.thesis_evidence import ThesisEvidenceRegistry
        e=engine([ref(-1,10400,'target')],-1,engine_class=CyclingPlanRecoveryEngine);seed(e,6)
        e.thesis_registry=ThesisEvidenceRegistry([record('short','formation',-1)])
        e.assess_main_trend(-1,observed_ms=1,reason='synthetic short',assessment=assessment('maintain',['short']))
        oid=e.plan_reduction('target',observed_ms=2,mark=10500,execution_ok=True,funding_known=True)['order_id']
        observe(e,1,10550,10580,10570);observe(e,2,10570,10610,10580)
        e.fill('late-short-reduce',oid,1,10400,received_ms=120001);e.orders.confirm_cancel(oid,1)
        observe(e,3,10550,10580,10570)
        r=observe(e,4,10550,10580,10570)
        self.assertEqual(r['kind'],'limit_reduce');self.assertEqual(e.orders.active.quantity,2)
        self.assertEqual(e.orders.active.price_cap,10400);self.assertEqual(e.model.direction,-1)

    def test_fully_filled_old_target_does_not_need_recovery(self):
        e,oid=prepared(CyclingPlanRecoveryEngine)
        observe(e,1,10420,10450,10430);observe(e,2,10390,10430,10420)
        e.fill('late-all',oid,3,10600,received_ms=120001)
        observe(e,3,10420,10450,10430)
        observe(e,4,10420,10450,10430)
        self.assertIsNone(e.plan_recovery);self.assertFalse(e.replan_required)
        self.assertIsNone(e.orders.active);self.assertEqual(e.model.quantity,3)
