from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import unittest

from app.research.baseline.account import Account, Costs
from app.research.baseline.risk import Risk, size_order
from app.research.diagnostics.account_fee import reported_taker_costs


class AccountFeeTests(unittest.TestCase):
    def setUp(self):
        self.context = json.loads((Path(__file__).resolve().parents[1]/
            'configs/research/account_cost_context_20260919.json').read_text())

    def test_only_taker_fee_changes_in_both_execution_conditions(self):
        original = deepcopy(self.context)
        for old in (Costs(),Costs(7,5,1)):
            new = reported_taker_costs(self.context,old)
            self.assertEqual(new.fee_bps,2.5)
            self.assertEqual([k for k,v in asdict(old).items() if v!=asdict(new)[k]],['fee_bps'])
        self.assertEqual(self.context,original)

    def test_two_fills_charge_actual_notional_not_initial_equity(self):
        costs = reported_taker_costs(self.context)
        account = Account(1000)
        account.enter('entry',1,.002,50000,costs.fee_bps)
        account.close('exit',55000,costs.fee_bps,'fixture_exit')
        self.assertAlmostEqual(account.fees,.025+.0275)
        self.assertAlmostEqual(account.balance,1009.9475)

    def test_fee_change_can_change_quantity_with_same_risk_budget(self):
        old = Costs(5,0,0,.01)
        new = reported_taker_costs(self.context,old)
        risk = Risk(stop_atr=1)
        a,b = (size_order(100,100,1,1,1000,False,c,risk) for c in (old,new))
        self.assertTrue(a['approved'] and b['approved'])
        self.assertGreater(b['quantity'],a['quantity'])
        self.assertEqual(a['budget'],b['budget'])
        self.assertLessEqual(b['planned_loss'],b['budget'])

    def test_invalid_rate_or_unit_or_instrument_is_rejected(self):
        for value in (True,-1,'NaN','Infinity','bad',25):
            context = deepcopy(self.context)
            context['fees_per_fill']['taker']['basis_points'] = value
            with self.assertRaises(ValueError): reported_taker_costs(context)
        context = deepcopy(self.context);context['symbol']='BTCUSDT'
        with self.assertRaises(ValueError): reported_taker_costs(context)
        context = deepcopy(self.context);context['fees_per_fill']['basis']='ACCOUNT_EQUITY'
        with self.assertRaises(ValueError): reported_taker_costs(context)


if __name__ == '__main__': unittest.main()
