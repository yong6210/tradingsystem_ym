import json
import unittest
from pathlib import Path
from test_recovery_cycling_trial_engine import make,seed,observe
from app.research.recovery.cycling_reduction_engine import CyclingReductionEngine,ReductionReference
from app.research.recovery.thesis_evidence import ThesisEvidenceRegistry


def ref(side=1,price=10600,key='structural-high',available=0):
    return ReductionReference(key,side,price,available,'a'*64,'predeclared synthetic structural price')

def engine(refs,side=1,engine_class=CyclingReductionEngine):
    return make(side,engine_class=engine_class,reduction_references=refs,
        thesis_registry=ThesisEvidenceRegistry([]),role_policy=json.loads((Path(__file__).resolve().parents[1]/'configs/research/cycling_role_v2.json').read_text()))

class ReferenceTests(unittest.TestCase):
    def test_nearby_price_reduces_half_without_main_reversal(self):
        e=engine([ref()]);seed(e,6)
        observe(e,1,10500,10550,10520)
        r=observe(e,2,10580,10620,10590)
        self.assertEqual(r['kind'],'reduce');self.assertEqual(e.orders.active.quantity,3)
        self.assertEqual(e.model.direction,1);self.assertEqual(e.main_status,'unassessed')

    def test_duplicate_prices_do_not_double_reduce(self):
        e=engine([ref(),ref(key='other-scale')]);seed(e,6)
        observe(e,1,10500,10550,10520);r=observe(e,2,10580,10620,10590)
        e.fill('half',r['order_id'],3,10590,received_ms=120001)
        observe(e,3,10580,10620,10590)
        self.assertEqual(len(e.orders.orders),1);self.assertEqual(e.model.quantity,3)

    def test_breakthrough_retires_price_without_role_flip(self):
        e=engine([ref()]);seed(e)
        observe(e,1,10500,10550,10520)
        observe(e,2,10580,10620,10610)
        observe(e,3,10580,10620,10590)
        self.assertIn('structural-high',e.retired_references)
        self.assertFalse(e.orders.orders)

    def test_short_mirror(self):
        e=engine([ref(-1,10400,'low')],-1);seed(e)
        observe(e,1,10450,10500,10480)
        r=observe(e,2,10380,10420,10410)
        self.assertEqual(r['kind'],'reduce');self.assertEqual(e.orders.active.quantity,2)
        self.assertEqual(e.model.direction,-1)

    def test_future_reference_rejected(self):
        with self.assertRaises(ValueError):engine([ref(available=1)])

    def test_no_prior_approach_no_reduction(self):
        e=engine([ref()]);seed(e)
        observe(e,1,10580,10620,10590)
        self.assertFalse(e.orders.orders)

    def test_nearer_price_constrains_entry_target(self):
        e=engine([ref()])
        self.assertEqual(e._increase_target(1,10500,e.exits[1]),10600)
        e.retired_references.add('structural-high')
        self.assertEqual(e._increase_target(1,10500,e.exits[1]),10800)
