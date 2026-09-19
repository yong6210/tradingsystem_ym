import json
from pathlib import Path
from dataclasses import replace
import unittest
from decimal import Decimal as D
from app.research.recovery.cycling_trial_engine import CyclingTrialEngine
from app.research.recovery.models import Zone,Bar
from app.research.recovery.position_alternatives import ExampleCosts
from app.research.recovery.cycling_admission import Capacity
from app.research.recovery.cycling_orders import CyclingOrders

ROOT=Path(__file__).resolve().parents[1]


def make(side=1,engine_class=CyclingTrialEngine,**extra):
    def z(key,lo,hi):return Zone(key,1,lo,hi,0,'explicit synthetic reviewed manifest')
    return engine_class(config=json.loads((ROOT/'configs/research/cycling_decision_trial_v1.json').read_text()),
        lower=z('A',9900,10000),upper=z('B',11000,11100),
        execution={1:z('long-entry',10300,10400),-1:z('short-entry',10600,10700)},
        exits={1:z('long-exit',10800,10900),-1:z('short-exit',10200,10300)},
        costs=ExampleCosts(0,0,0,1,'.1',2),requested=2,purpose='nearby_cycle',starting_equity=1000000,
        minimum_quantity='.1',minimum_notional=1,max_age_ms=0,initial_side=side,**extra)


def bar(i,lo,hi,close):return Bar(i*60000,close,hi,lo,close,i*60000)
def cap(i,**kw):
    d=dict(observed_ms=i*60000,free_margin=100000,reserve_margin=10000,margin_per_unit=1000,
           maximum_total=20,stress_loss_budget=100000,stress_moves=(2000,3000));d.update(kw)
    return Capacity(**d)
def observe(e,i,lo,hi,close,capacity=True,**kw):
    return e.observe(bar(i,lo,hi,close),capacity=cap(i) if capacity is True else capacity,
                     liquidity_qty=20,execution_ok=True,funding_known=True,**kw)
def seed(e,qty=4):
    e.model.increase('seed',e.model.direction,qty,10500)
    e.last_basis=e.execution[e.model.direction].key

def add(e):
    observe(e,1,10420,10450,10430)
    r=observe(e,2,10390,10430,10420)
    e.fill('add-fill',r['order_id'],2,10420,received_ms=120001)
    return r


class TrialEngineTests(unittest.TestCase):
    def test_1_origin_boundary_retest_sets_direction_without_entry(self):
        e=make(None)
        observe(e,1,9950,10010,9990)
        observe(e,2,10010,10050,10040)
        observe(e,3,11080,11140,11120)
        observe(e,4,11110,11160,11140)
        r=observe(e,5,11090,11140,11120)
        self.assertEqual(e.model.direction,1)
        self.assertEqual(r['action'],'direction_confirmed_wait_new_reaction')
        self.assertEqual(e.orders.orders,{})

    def test_2_local_failure_does_not_reverse(self):
        e=make();seed(e)
        r=observe(e,1,10250,10320,10280)
        self.assertTrue(e.local_failed)
        self.assertEqual(e.model.direction,1)
        self.assertEqual(e.model.quantity,4)
        self.assertNotEqual(r['action'],'order')

    def test_3_add_half_then_fresh_readd(self):
        e=make();seed(e);add(e)
        observe(e,3,10600,10700,10650)
        r=observe(e,4,10790,10850,10795)
        self.assertEqual(e.orders.active.quantity,3)
        e.fill('half',r['order_id'],3,10795,received_ms=240001)
        self.assertEqual(e.model.quantity,3)
        observe(e,5,10420,10450,10430)
        r=observe(e,6,10390,10430,10420)
        self.assertEqual(r['kind'],'increase')
        self.assertEqual(e.model.direction,1)

    def test_4_partial_cancel_late_fill_retries_original_half(self):
        e=make();seed(e);add(e)
        observe(e,3,10600,10700,10650)
        r=observe(e,4,10790,10850,10795);oid=r['order_id']
        e.fill('part',oid,1,10795,received_ms=240001)
        e.orders.request_cancel(oid)
        e.fill('late',oid,1,10795,received_ms=240002)
        e.orders.confirm_cancel(oid,2)
        r=observe(e,5,10600,10700,10650)
        self.assertEqual(e.orders.active.quantity,1)
        e.fill('remaining',r['order_id'],1,10650,received_ms=300001)
        self.assertEqual(e.model.quantity,3)
        observe(e,6,10790,10850,10795)
        self.assertIsNone(e.orders.active)

    def test_5_local_failure_and_exposure_limit_minimum_trim(self):
        e=make();seed(e,6)
        r=observe(e,1,10250,10320,10280,capacity=cap(1,maximum_total=4))
        self.assertEqual(r['kind'],'trim')
        self.assertEqual(e.orders.active.quantity,2)
        e.fill('trimmed',r['order_id'],2,10280,received_ms=60001)
        self.assertEqual(e.model.quantity,4)
        self.assertEqual(e.model.direction,1)
        restored=CyclingOrders.restore(json.loads(json.dumps(e.orders.checkpoint())))
        self.assertEqual(restored.model.quantity,4)

    def test_6_origin_recovers_no_reversal_or_automatic_add(self):
        e=make();seed(e)
        observe(e,1,9800,9850,9840);self.assertTrue(e.weak)
        observe(e,2,10010,10030,10020)
        self.assertFalse(e.weak)
        self.assertEqual(e.model.direction,1)
        self.assertEqual(e.orders.orders,{})

    def test_7_origin_failed_retest_exit_then_wait_opposite_reaction(self):
        e=make();seed(e)
        observe(e,1,9800,9850,9840)
        r=observe(e,2,9880,9930,9890)
        self.assertEqual(r['kind'],'exit')
        e.fill('exit-part',r['order_id'],2,9890,received_ms=120001)
        with self.assertRaises(ValueError):e.model.increase('illegal',-1,1,9890)
        e.fill('exit-rest',r['order_id'],2,9890,received_ms=120002)
        self.assertEqual(e.model.direction,-1);self.assertEqual(e.model.quantity,0)
        r=observe(e,3,9800,9850,9840)
        self.assertNotEqual(r['action'],'order')

    def test_8_missing_capacity_gap_and_ambiguous_bar_no_entry(self):
        e=make();observe(e,1,10420,10450,10430)
        r=observe(e,2,10390,10430,10420,capacity=None)
        self.assertEqual(r['action'],'missing_capacity')
        before=len(e.journal)
        with self.assertRaises(ValueError):observe(e,4,10420,10450,10430)
        self.assertEqual(len(e.journal),before)
        observe(e,3,10420,10450,10430)
        r=observe(e,4,10290,10430,10420)
        self.assertNotEqual(r['action'],'order')
        self.assertEqual(e.orders.orders,{})

    def test_retracement_cancels_increase_and_uses_reconciled_total(self):
        e=make();seed(e)
        observe(e,1,10420,10450,10430)
        r=observe(e,2,10390,10430,10420);oid=r['order_id']
        e.fill('early',oid,1,10420,received_ms=120001)
        observe(e,3,10790,10850,10795)
        self.assertEqual(e.orders.active.status,'cancel_pending')
        e.fill('late',oid,'.5',10420,received_ms=180001)
        e.orders.confirm_cancel(oid,'1.5')
        r=observe(e,4,10600,10700,10650)
        self.assertEqual(r['kind'],'reduce')
        self.assertEqual(e.orders.active.quantity,D('2.8'))

    def test_unknown_execution_defers_transition_order(self):
        e=make();seed(e)
        observe(e,1,9800,9850,9840)
        r=e.observe(bar(2,9880,9930,9890))
        self.assertEqual(r['action'],'execution_unknown')
        self.assertIsNone(e.orders.active)
        self.assertIsNotNone(e.orders.transition)
        r=observe(e,3,9800,9850,9840)
        self.assertEqual(r['kind'],'exit')

    def test_unknown_execution_defers_cancelled_half_retry(self):
        e=make();seed(e);add(e)
        r=observe(e,3,10790,10850,10795);oid=r['order_id']
        e.fill('part',oid,1,10795,received_ms=180001)
        e.orders.request_cancel(oid);e.orders.confirm_cancel(oid,1)
        r=e.observe(bar(4,10600,10700,10650))
        self.assertEqual(r['action'],'execution_unknown')
        self.assertIsNone(e.orders.active)
        observe(e,5,10600,10700,10650)
        self.assertEqual(e.orders.active.quantity,2)

    def test_half_rounds_up_before_minimum_check(self):
        e=make();seed(e,'.3')
        e.orders.costs=replace(e.orders.costs,minimum_qty=D('.2'))
        observe(e,1,10600,10700,10650)
        r=observe(e,2,10790,10850,10795)
        self.assertEqual(r['kind'],'reduce')
        self.assertEqual(e.orders.active.quantity,D('.2'))

    def test_weak_trim_accounts_for_minimum_notional(self):
        e=make();seed(e,6)
        e.minimum_notional=D('15000')
        e.orders.costs=replace(e.orders.costs,minimum_notional=e.minimum_notional)
        r=observe(e,1,10250,10320,10280,capacity=cap(1,maximum_total=5))
        self.assertEqual(r['kind'],'trim')
        self.assertEqual(e.orders.active.quantity,D('1.5'))

    def test_short_add_half_keeps_short_direction(self):
        e=make(-1);seed(e)
        observe(e,1,10550,10580,10570)
        r=observe(e,2,10570,10610,10580)
        self.assertEqual(r['kind'],'increase')
        e.fill('short-add',r['order_id'],2,10580,received_ms=120001)
        r=observe(e,3,10250,10310,10305)
        self.assertEqual(e.orders.active.quantity,3)
        e.fill('short-half',r['order_id'],3,10305,received_ms=180001)
        self.assertEqual(e.model.direction,-1)
        self.assertEqual(e.model.quantity,3)

    def test_no_fill_on_decision_close(self):
        e=make();observe(e,1,10420,10450,10430);r=observe(e,2,10390,10430,10420)
        with self.assertRaises(ValueError):e.fill('too-soon',r['order_id'],2,10420,received_ms=120000)
        self.assertEqual(e.model.quantity,0)


if __name__=='__main__':unittest.main()
