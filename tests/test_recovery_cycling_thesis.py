import json
import unittest
from copy import deepcopy
from app.research.recovery.directional_cycling import DirectionalCycling
from app.research.recovery.cycling_orders import CyclingOrders
import test_recovery_cycling_orders as fixtures


def assessment(kind='initial'):
    r=dict(scope='main_trend',confirmed=True,kind=kind,evidence_ids=['structure:v1','zone:v2'],
           invalidation_condition='explicit scenario structural invalidation')
    if kind=='reversal':r['prior_thesis_invalidated_by']='scenario old thesis invalidated by new structure'
    return r


def kwargs(kind='initial',time=1):
    return dict(timeframe='1h + daily structure',observed_ms=time,reason='synthetic thesis, not market signal',assessment=assessment(kind))


class ThesisTests(unittest.TestCase):
    def test_initial_maintain_reversal_without_four_hours(self):
        m=DirectionalCycling('.001')
        m.set_direction(1,**kwargs())
        m.set_direction(1,**kwargs('maintain',2))
        m.set_direction(-1,**kwargs('reversal',3))
        self.assertEqual(m.direction,-1)
        self.assertEqual(len(m.events),3)

    def test_local_unconfirmed_missing_evidence_rejected_without_mutation(self):
        for field,value in [('scope','local_reaction'),('confirmed',False),('evidence_ids',[]),('invalidation_condition','')]:
            m=DirectionalCycling('.001');arg=kwargs();arg['assessment'][field]=value
            with self.assertRaises(ValueError):m.set_direction(1,**arg)
            self.assertIsNone(m.direction)
            self.assertEqual(m.events,[])

    def test_changed_direction_requires_reversal_and_invalidation(self):
        m=DirectionalCycling('.001');m.set_direction(1,**kwargs())
        for arg in (kwargs('maintain',2),kwargs('reversal',2)):
            arg['assessment'].pop('prior_thesis_invalidated_by',None)
            with self.assertRaises(ValueError):m.set_direction(-1,**arg)
        self.assertEqual(m.direction,1)

    def test_idempotence_conflict_and_caller_mutation(self):
        m=DirectionalCycling('.001');arg=kwargs();original=deepcopy(arg)
        m.set_direction(1,**arg);arg['assessment']['evidence_ids'].append('later')
        m.set_direction(1,**original)
        self.assertEqual(len(m.events),1)
        with self.assertRaises(ValueError):m.set_direction(1,**arg)

    def test_structured_thesis_cannot_fall_back_to_legacy(self):
        m=DirectionalCycling('.001');m.set_direction(1,**kwargs())
        with self.assertRaises(ValueError):
            m.set_direction(-1,timeframe='4h',observed_ms=2,reason='legacy vote')
        self.assertEqual(m.direction,1)

    def test_transition_checkpoint_and_flat_before_opposite_fill(self):
        _,o,_,_=fixtures.CyclingOrderTests().setup_case()
        o.model.increase('base',-1,5,100000)
        arg=kwargs('reversal',101)
        o.request_transition(1,**arg)
        arg['assessment']['evidence_ids'].append('caller mutation')
        restored=CyclingOrders.restore(json.loads(json.dumps(o.checkpoint())))
        self.assertNotIn('caller mutation',restored.transition['assessment']['evidence_ids'])
        restored.reconcile(side=-1,quantity=5,average=100000,open_orders={})
        order=restored.continue_transition('exit',reference_price=100000)
        restored.fill('partial','exit',2,100000,0)
        with self.assertRaises(ValueError):restored.model.increase('opposite',1,1,100000)
        restored.fill('rest','exit',3,100000,0)
        self.assertEqual(restored.model.quantity,0)
        self.assertEqual(restored.model.direction,1)
        self.assertIsNone(restored.transition)
        again=CyclingOrders.restore(json.loads(json.dumps(restored.checkpoint())))
        self.assertEqual(again.model.direction,1)


if __name__=='__main__':unittest.main()
