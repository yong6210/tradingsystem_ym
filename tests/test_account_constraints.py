import unittest
import pandas as pd

from app.research.baseline.account import Costs
from app.research.comparison.engine import simulate as frozen_simulate
from app.research.diagnostics.account_constraints_engine import simulate
from app.research.diagnostics.account_constraints import diagnostic_risk, snapshot_choices, terminal_contrasts


class AccountConstraintTests(unittest.TestCase):
    def test_only_declared_contract_and_multiplier_change(self):
        for name in ('contract_half', 'contract_full', 'fine_half', 'fine_full'):
            r = diagnostic_risk(name)
            self.assertEqual((r.halt,r.daily_stop,r.warning,r.cycle_fraction,r.exposure_multiple),(.08,.02,.05,.005,1))
            self.assertEqual(r.warning_multiplier,1 if name.endswith('full') else .5)
            self.assertEqual(r.step,1e-8 if name.startswith('fine') else .001)

    def test_warning_can_prevent_minimum_lot(self):
        a = dict(reference=60000.,close=60000.,atr=1000.,side=1,equity=1000.,warned=True)
        c = snapshot_choices(a,Costs())
        self.assertFalse(c['contract_half']['approved'])
        self.assertTrue(c['contract_full']['approved'])
        self.assertTrue(c['fine_half']['approved'])
        self.assertLess(c['fine_half']['quantity'],.001)

    def test_unwarned_multiplier_is_irrelevant(self):
        a = dict(reference=60000.,close=60000.,atr=1000.,side=-1,equity=1000.,warned=False)
        c = snapshot_choices(a,Costs())
        self.assertEqual(c['contract_half'],c['contract_full'])
        self.assertEqual(c['fine_half'],c['fine_full'])

    def test_relaxed_contract_still_obeys_budget(self):
        for side in (-1,1):
            a = dict(reference=60000.,close=60000.,atr=1000.,side=side,equity=1000.,warned=True)
            c = snapshot_choices(a,Costs(7,5,1))['fine_half']
            self.assertTrue(c['approved'])
            self.assertLessEqual(c['planned_loss'],2.5+1e-8)
            self.assertLessEqual(c['quantity']*c['entry'],1000)

    def test_invalid_stop_not_rescued_by_fine_units(self):
        a = dict(reference=90.,close=100.,atr=1.,side=1,equity=1000.,warned=True)
        self.assertTrue(all(not r['approved'] for r in snapshot_choices(a,Costs()).values()))

    def test_instrumentation_matches_original_and_records_warning(self):
        idx=pd.date_range('2025-01-01',periods=10,freq='min',tz='UTC')
        f=pd.DataFrame(dict(o=60000.,h=60010.,l=59990.,c=60000.,v=1.),index=idx)
        f.loc[idx[2],['o','h','l','c']]=[53000.,53010.,52990.,53000.]
        commands={1:(1,60000.,100.),3:(1,60000.,1000.)}
        a=frozen_simulate(f,commands,idx[0],idx[-1]);b=simulate(f,commands,idx[0],idx[-1])
        for key in a:self.assertEqual(a[key],b[key])
        self.assertGreater(len(b['sizing_attempts']),0)
        self.assertEqual(len(b['risk_transitions']),1)
        self.assertEqual(b['risk_transitions'][0]['kind'],'warning_latched')

    def test_factorial_contrasts_reconcile(self):
        names=('contract_half','contract_full','fine_half','fine_full')
        v=terminal_contrasts({n:dict(return_pct=x) for n,x in zip(names,(1,3,4,8))})
        self.assertEqual(v['interaction_pp'],2)
        self.assertEqual(v['reconstruction_error_pp'],0)
