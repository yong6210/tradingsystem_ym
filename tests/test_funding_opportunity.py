import itertools
import unittest
from decimal import Decimal as D
from app.research.diagnostics.funding_opportunity import oracle_with_costs,causal_windows


class FundingOpportunityTest(unittest.TestCase):
    def test_oracle_matches_all_position_paths(self):
        payments=list(map(D,['1','-2','3','-.2','1']))
        cost=D('.3');brute=[]
        for path in itertools.product([0,1],repeat=len(payments)):
            previous=0;net=D(0)
            for position,payment in zip(path,payments):
                net+=position*payment-abs(position-previous)*cost;previous=position
            net-=previous*cost;brute.append(net)
        self.assertEqual(oracle_with_costs(payments,cost,cost),max(brute))

    def test_losing_cashflows_choose_flat(self):
        self.assertEqual(oracle_with_costs([D('-1')]*4,D('.3'),D('.3')),0)

    def test_future_rates_do_not_change_first_decision(self):
        past=[D('.0004')]*21
        a=causal_windows(past+[D('.01')]*45)
        b=causal_windows(past+[D('-.01')]*45)
        self.assertEqual(a[0],b[0])
        self.assertEqual(a[0]['first'],21)
        self.assertEqual(a[0]['last'],41)

    def test_expense_threshold_and_no_overlapping_holdings(self):
        self.assertEqual(causal_windows([D('.0001')]*100),[])
        rows=causal_windows([D('.001')]*100)
        self.assertTrue(all(b['decision_index']>a['last'] for a,b in zip(rows,rows[1:])))
        self.assertTrue(all(r['last']<100 for r in rows))


if __name__=='__main__':unittest.main()
