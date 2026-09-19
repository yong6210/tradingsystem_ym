import json
import tempfile
from pathlib import Path
import unittest
from test_recovery_cycling_plan_recovery import settled
from test_recovery_cycling_order_coordination import prepared
from test_recovery_cycling_trial_engine import observe
from app.research.recovery.cycling_plan_recovery import CyclingPlanRecoveryEngine
from app.research.recovery.cycling_engine_checkpoint import checkpoint,restore,save,decode,encode,digest


def external_snapshot(e):
    return dict(side=e.model.position_side,quantity=e.model.quantity,average=e.model.average,
        open_orders={o.id:dict(filled=str(o.filled),status=o.status) for o in e.orders.orders.values()
                     if o.status in ('open','cancel_pending')})


def restart(e):
    snapshot=external_snapshot(e)  # independent simulated venue before restoring
    r=restore(json.loads(json.dumps(checkpoint(e))))
    r.orders.reconcile(**snapshot)
    return r


class EngineCheckpointTests(unittest.TestCase):
    def test_pending_cancel_late_fill_survives_restart(self):
        e,oid=prepared(CyclingPlanRecoveryEngine)
        observe(e,1,10420,10450,10430);observe(e,2,10390,10430,10420)
        r=restart(e)
        for x in (e,r):
            x.fill('late',oid,1,10600,received_ms=120001);x.orders.confirm_cancel(oid,1)
            observe(x,3,10420,10450,10430);observe(x,4,10420,10450,10430)
        self.assertEqual(checkpoint(e),checkpoint(r))
        self.assertEqual(r.orders.active.quantity,2)

    def test_restart_lock_does_not_consume_next_bar(self):
        e,oid=settled();r=restore(checkpoint(e));before=checkpoint(r)
        out=observe(r,4,10420,10450,10430)
        self.assertEqual(out['action'],'reconciliation_required');self.assertEqual(checkpoint(r),before)
        with self.assertRaises(ValueError):r.orders.reconcile(side=1,quantity=999,average=10500,open_orders={})
        self.assertTrue(r.orders.restart_required)
        r.orders.reconcile(**external_snapshot(e))
        observe(r,4,10420,10450,10430)
        self.assertEqual(r.orders.active.quantity,2)

    def test_partial_add_pending_cancel_restores_total(self):
        e,oid=settled();a=observe(e,4,10390,10430,10420)['order_id']
        e.fill('part',a,'.5',10420,received_ms=240001);e.orders.request_cancel(a)
        r=restart(e)
        for x in (e,r):
            x.fill('late',a,'.5',10420,received_ms=240002);x.orders.confirm_cancel(a,1)
            observe(x,5,10420,10450,10430)
        self.assertEqual(checkpoint(e),checkpoint(r));self.assertEqual(r.orders.active.quantity,3)

    def test_multiple_cycles_equal_with_restart_at_every_stage(self):
        e,oid=prepared(CyclingPlanRecoveryEngine);r=restart(e)
        for cycle in range(3):
            i=cycle*4
            for x in (e,r):
                observe(x,i+1,10420,10450,10430);observe(x,i+2,10390,10430,10420)
                oid=x.orders.active.id
                x.fill('reduce:'+str(cycle),oid,1,10600,received_ms=(i+2)*60000+1)
                x.orders.confirm_cancel(oid,1)
            r=restart(r)
            for x in (e,r):
                observe(x,i+3,10420,10450,10430)
                a=observe(x,i+4,10390,10430,10420)['order_id']
                x.fill('add:'+str(cycle),a,2,10420,received_ms=(i+4)*60000+1)
                # Explicit next plan here keeps cycles contiguous without inventing an extra bar.
                x.plan_reduction('target',observed_ms=(i+4)*60000+2,mark=10420,execution_ok=True,funding_known=True)
            r=restart(r)
            self.assertEqual(checkpoint(e),checkpoint(r))
        self.assertEqual(e.model.quantity,9)

    def test_corruption_and_inconsistent_growth_rejected(self):
        e,oid=settled();p=checkpoint(e);p['body']['version']='broken'
        with self.assertRaises(ValueError):restore(p)
        p=checkpoint(e);s=decode(p['body']['state']);s['growth']=99;p['body']['state']=encode(s);p['sha256']=digest(p['body'])
        with self.assertRaises(ValueError):restore(p)

    def test_atomic_disk_roundtrip(self):
        e,oid=settled()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'engine.json';save(e,path)
            r=restore(json.loads(path.read_text()));self.assertTrue(r.orders.restart_required)
            self.assertEqual(r.plan_recovery,e.plan_recovery)

    def test_three_automatic_recovery_cycles_match_restarts(self):
        e,oid=prepared(CyclingPlanRecoveryEngine);r=restart(e)
        for cycle in range(3):
            i=cycle*5
            for x in (e,r):
                observe(x,i+1,10420,10450,10430);observe(x,i+2,10390,10430,10420)
                oid=x.orders.active.id
                x.fill('reduce:'+str(cycle),oid,1,10600,received_ms=(i+2)*60000+1)
                x.orders.confirm_cancel(oid,1)
            r=restart(r)
            for x in (e,r):
                observe(x,i+3,10420,10450,10430)
                oid=observe(x,i+4,10390,10430,10420)['order_id']
                x.fill('add:'+str(cycle),oid,2,10420,received_ms=(i+4)*60000+1)
            r=restart(r)
            for x in (e,r):observe(x,i+5,10420,10450,10430)
            self.assertEqual(checkpoint(e),checkpoint(r))
            self.assertEqual(r.orders.active.quantity,r.model.quantity/2)
        self.assertEqual(r.model.quantity,9)

    def test_duplicate_fill_after_restart_not_counted_twice(self):
        e,oid=settled();a=observe(e,4,10390,10430,10420)['order_id']
        e.fill('part',a,1,10420,received_ms=240001)
        r=restart(e)
        self.assertFalse(r.fill('part',a,1,10420,received_ms=240002))
        self.assertEqual(r.model.quantity,6)
        self.assertEqual(r.orders.active.filled,1)

    def test_unknown_field_and_wrong_plan_price_rejected(self):
        e,oid=settled();e.unserialized_future_field=True
        with self.assertRaises(ValueError):checkpoint(e)
        del e.unserialized_future_field
        p=checkpoint(e);s=decode(p['body']['state'])
        key=next(iter(s['planned_limits']));s['planned_limits'][key]+=1
        p['body']['state']=encode(s);p['sha256']=digest(p['body'])
        with self.assertRaises(ValueError):restore(p)
