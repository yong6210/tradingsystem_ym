import json
import unittest
from test_recovery_cycling_reduction_references import engine,ref
from test_recovery_cycling_trial_engine import seed,observe,cap
from test_recovery_cycling_roles import record,assessment
from app.research.recovery.thesis_evidence import ThesisEvidenceRegistry
from app.research.recovery.cycling_order_coordination import CyclingCoordinatedEngine
from app.research.recovery.cycling_orders import CyclingOrders


def prepared(engine_class=CyclingCoordinatedEngine):
    e=engine([ref(key='target')],engine_class=engine_class);seed(e,6)
    e.thesis_registry=ThesisEvidenceRegistry([record('long','formation',1)])
    e.assess_main_trend(1,observed_ms=1,reason='synthetic main long',assessment=assessment('maintain',['long']))
    r=e.plan_reduction('target',observed_ms=2,mark=10500,execution_ok=True,funding_known=True)
    return e,r['order_id']


class CoordinationTests(unittest.TestCase):
    def test_new_add_requires_settlement_and_fresh_reaction(self):
        e,oid=prepared()
        observe(e,1,10420,10450,10430)
        r=observe(e,2,10390,10430,10420)
        self.assertEqual(r['action'],'handoff_cancel_requested')
        self.assertIsNone(r['next_order_quantity'])
        e.fill('late',oid,1,10600,received_ms=120001)
        with self.assertRaises(ValueError):e.orders.confirm_cancel(oid,0)
        self.assertEqual(len(e.orders.orders),1)
        e.orders.confirm_cancel(oid,1)
        r=observe(e,3,10420,10450,10430)
        self.assertEqual(r['action'],'handoff_wait_fresh_add_reaction')
        r=observe(e,4,10390,10430,10420)
        self.assertEqual(r['kind'],'increase')
        e.fill('add',r['order_id'],2,10420,received_ms=240001)
        self.assertEqual(e.model.quantity,7)
        r=e.plan_reduction('target',observed_ms=240002,mark=10420,execution_ok=True,funding_known=True)
        self.assertEqual(e.orders.active.quantity,e.model.quantity/2)
        self.assertEqual(e.orders.active.quantity,3.5)
        self.assertEqual(e.model.direction,1)
        restored=CyclingOrders.restore(json.loads(json.dumps(e.orders.checkpoint())))
        self.assertEqual(restored.model.quantity,7)

    def test_risk_trim_uses_quantity_after_late_fill_and_new_limits(self):
        e,oid=prepared()
        r=observe(e,1,10250,10320,10280,capacity=cap(1,maximum_total=4))
        self.assertEqual(r['purpose'],'capacity_reduction')
        e.fill('late',oid,1,10600,received_ms=60001)
        e.orders.confirm_cancel(oid,1)
        r=observe(e,2,10250,10320,10280,capacity=cap(2,maximum_total=4))
        self.assertEqual(r['kind'],'trim');self.assertEqual(e.orders.active.quantity,1)
        e.fill('trim',r['order_id'],1,10280,received_ms=120001)
        self.assertEqual(e.model.quantity,4)

    def test_cancel_pending_never_releases_inventory(self):
        e,oid=prepared()
        observe(e,1,10250,10320,10280,capacity=cap(1,maximum_total=4))
        r=observe(e,2,10250,10320,10280,capacity=cap(2,maximum_total=4))
        self.assertEqual(r['action'],'handoff_await_cancel_reconciliation')
        self.assertEqual(e.model.quantity,6);self.assertEqual(len(e.orders.orders),1)

    def test_resolved_risk_does_not_force_old_trim_quantity(self):
        e,oid=prepared()
        observe(e,1,10250,10320,10280,capacity=cap(1,maximum_total=4))
        e.fill('all',oid,3,10600,received_ms=60001)
        r=observe(e,2,10250,10320,10280,capacity=cap(2,maximum_total=4))
        self.assertNotEqual(r['action'],'order')
        self.assertEqual(e.model.quantity,3);self.assertIsNone(e.orders.active)

    def test_new_capacity_can_deny_fresh_add_after_cancel(self):
        e,oid=prepared()
        observe(e,1,10420,10450,10430)
        observe(e,2,10390,10430,10420)
        e.orders.confirm_cancel(oid,0)
        observe(e,3,10420,10450,10430)
        r=observe(e,4,10390,10430,10420,capacity=cap(4,maximum_total=6))
        self.assertNotEqual(r['action'],'order')
        self.assertIsNone(e.orders.active)
        self.assertEqual(e.model.quantity,6)

    def test_partial_old_plan_can_be_replanned_without_reusing_old_event(self):
        e,oid=prepared()
        observe(e,1,10250,10320,10280,capacity=cap(1,maximum_total=4))
        e.fill('late',oid,1,10600,received_ms=60001);e.orders.confirm_cancel(oid,1)
        r=observe(e,2,10250,10320,10280,capacity=cap(2,maximum_total=4))
        e.fill('trim',r['order_id'],1,10280,received_ms=120001)
        r=e.plan_reduction('target',observed_ms=120002,mark=10280,execution_ok=True,funding_known=True)
        self.assertEqual(e.orders.active.quantity,2)
        self.assertNotEqual(e.orders.active.event_id,e.orders.orders[oid].event_id)
        self.assertEqual(e.model._reductions[e.orders.orders[oid].event_id][1].filled,1)

    def test_explicit_pause_overrides_automatic_handoff(self):
        e,oid=prepared()
        observe(e,1,10420,10450,10430);observe(e,2,10390,10430,10420)
        e.set_plan_paused(True,observed_ms=120001,reason='retain paused original intent')
        e.orders.confirm_cancel(oid,0)
        r=observe(e,3,10420,10450,10430)
        self.assertEqual(r['action'],'planned_reduction_paused_await_explicit_resume')
        self.assertEqual(e.model.reduction.event_id,e.orders.orders[oid].event_id)
        self.assertIsNone(e.order_handoff)
