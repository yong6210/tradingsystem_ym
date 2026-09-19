import unittest
import json
from pathlib import Path
from copy import deepcopy
from test_recovery_cycling_trial_engine import make, seed, observe, add
from app.research.recovery.cycling_role_engine import CyclingRoleEngine
from app.research.recovery.thesis_evidence import ThesisEvidenceRegistry


def record(key,role,side,available=1,**extra):
    return dict(id=key,role=role,side=side,available_ms=available,scope='main_trend',
        source_sha256='a'*64,event_key=key,rationale='explicit synthetic main structure fixture',**extra)


def assessment(kind,ids):
    out=dict(scope='main_trend',confirmed=True,kind=kind,evidence_ids=ids,
        invalidation_condition='separate main structure invalidation')
    if kind=='reversal':out['prior_thesis_invalidated_by']='separate invalidation fixture'
    return out


def engine(records=(),side=1):
    return make(side,engine_class=CyclingRoleEngine,thesis_registry=ThesisEvidenceRegistry(records),
        role_policy=json.loads((Path(__file__).resolve().parents[1]/'configs/research/cycling_role_v2.json').read_text()))


class RoleTests(unittest.TestCase):
    def test_local_break_and_retest_never_certifies_reversal(self):
        e=engine();seed(e)
        observe(e,1,9800,9850,9840)
        r=observe(e,2,9880,9930,9890)
        self.assertEqual(e.model.direction,1)
        self.assertEqual(e.model.quantity,4)
        self.assertEqual(r['action'],'main_thesis_unassessed_no_increase')
        self.assertFalse(e.orders.orders)

    def test_unknown_main_thesis_blocks_add_but_allows_half(self):
        e=engine();seed(e)
        observe(e,1,10420,10450,10430)
        r=observe(e,2,10390,10430,10420)
        self.assertNotEqual(r['action'],'order')
        r=observe(e,3,10790,10850,10795)
        self.assertEqual(r['kind'],'reduce')
        self.assertEqual(e.orders.active.quantity,2)

    def test_assessed_main_thesis_allows_same_direction_cycle(self):
        e=engine([record('long','formation',1)]);seed(e)
        e.assess_main_trend(1,observed_ms=1,reason='synthetic long structure',assessment=assessment('maintain',['long']))
        add(e)
        self.assertEqual(e.model.quantity,6)
        e.mark_main_uncertain(observed_ms=120002,reason='conflicting main evidence')
        r=observe(e,3,10790,10850,10795)
        self.assertEqual(r['kind'],'reduce')
        self.assertEqual(e.orders.active.quantity,3)

    def test_reversal_cancels_active_then_exits_actual_quantity(self):
        records=[record('long','formation',1),
            record('break','prior_thesis_invalidation',1,120001,invalidates_evidence_ids=['long']),
            record('short','opposite_formation',-1,120001)]
        e=engine(records);seed(e)
        e.assess_main_trend(1,observed_ms=1,reason='long',assessment=assessment('maintain',['long']))
        observe(e,1,10420,10450,10430);r=observe(e,2,10390,10430,10420)
        oid=r['order_id']
        e.assess_main_trend(-1,observed_ms=120001,reason='main reversal',assessment=assessment('reversal',['break','short']))
        self.assertEqual(e.orders.active.status,'cancel_pending')
        e.fill('late',oid,1,10420,received_ms=120002)
        e.orders.confirm_cancel(oid,1)
        r=observe(e,3,10300,10350,10320)
        self.assertEqual(r['kind'],'exit');self.assertEqual(e.orders.active.quantity,5)
        e.fill('exit',r['order_id'],5,10320,received_ms=180001)
        self.assertEqual(e.model.quantity,0);self.assertEqual(e.model.direction,-1)
        r=observe(e,4,10300,10350,10320)
        self.assertNotEqual(r['action'],'order')

    def test_invalid_assessments_are_atomic(self):
        bad=record('local','formation',1);bad['scope']='execution'
        for records,ids in [([bad],['local']),([record('future','formation',1,60000)],['future']),
                            ([record('wrong','formation',-1)],['wrong']),([],['missing'])]:
            with self.subTest(ids=ids):
                e=engine(records);seed(e);before=deepcopy(e.model.events)
                with self.assertRaises(ValueError):
                    e.assess_main_trend(1,observed_ms=1,reason='bad',assessment=assessment('maintain',ids))
                self.assertEqual(before,e.model.events)
                self.assertEqual(e.main_status,'unassessed')

    def test_uncertainty_cancels_pending_increase_without_exit(self):
        e=engine([record('long','formation',1)]);seed(e)
        e.assess_main_trend(1,observed_ms=1,reason='long',assessment=assessment('maintain',['long']))
        observe(e,1,10420,10450,10430);observe(e,2,10390,10430,10420)
        e.mark_main_uncertain(observed_ms=120001,reason='conflicting formation')
        self.assertEqual(e.orders.active.status,'cancel_pending')
        self.assertIsNone(e.orders.transition)

    def test_reversal_must_invalidate_current_thesis(self):
        records=[record('long','formation',1),record('break','prior_thesis_invalidation',1,2,
            invalidates_evidence_ids=['unrelated']),record('short','opposite_formation',-1,2)]
        e=engine(records)
        e.assess_main_trend(1,observed_ms=1,reason='long',assessment=assessment('maintain',['long']))
        with self.assertRaises(ValueError):
            e.assess_main_trend(-1,observed_ms=2,reason='bad linkage',assessment=assessment('reversal',['break','short']))
        self.assertEqual(e.model.direction,1);self.assertIsNone(e.orders.transition)

    def test_same_event_cannot_be_both_reversal_premises(self):
        invalid=record('break','prior_thesis_invalidation',1,2,invalidates_evidence_ids=['long'])
        opposite=record('short','opposite_formation',-1,2)
        invalid['event_key']=opposite['event_key']='same-touch'
        e=engine([record('long','formation',1),invalid,opposite])
        e.assess_main_trend(1,observed_ms=1,reason='long',assessment=assessment('maintain',['long']))
        with self.assertRaises(ValueError):
            e.assess_main_trend(-1,observed_ms=2,reason='duplicated event',assessment=assessment('reversal',['break','short']))
        self.assertIsNone(e.orders.transition)

    def test_new_main_assessment_does_not_enter_on_same_bar(self):
        e=engine([record('long','formation',1)])
        observe(e,1,10420,10450,10430)
        e.assess_main_trend(1,observed_ms=120000,reason='long',assessment=assessment('maintain',['long']))
        r=observe(e,2,10390,10430,10420)
        self.assertEqual(r['action'],'main_assessment_wait_new_reaction')
        self.assertFalse(e.orders.orders)

    def test_local_failure_capacity_trim_survives_unknown_thesis(self):
        from test_recovery_cycling_trial_engine import cap
        e=engine();seed(e,6)
        r=observe(e,1,10250,10320,10280,capacity=cap(1,maximum_total=4))
        self.assertEqual(r['kind'],'trim')
        self.assertEqual(e.orders.active.quantity,2)
        self.assertEqual(e.model.direction,1)
