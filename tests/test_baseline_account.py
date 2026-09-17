import unittest
from app.research.baseline.account import Account, Costs, replay, round_step


class BaselineAccountTests(unittest.TestCase):
    def test_long_short_fees_and_funding(self):
        for side in (-1,1):
            a=Account(1000)
            a.enter('t0',side,.01,60000,5)
            a.pay_funding('t1',60000,1)
            a.close('t2',60000+side*1000,5,'test')
            expected=1000+10-.3-.06-.01*(60000+side*1000)*.0005
            self.assertAlmostEqual(a.balance,expected)
            self.assertAlmostEqual(replay(a.events,1000)['balance'],expected)

    def test_fixed_quantity_no_rebalance_charge(self):
        a=Account(1000)
        a.enter('t0',1,.01,60000,5)
        a.equity(61000)
        a.equity(62000)
        self.assertEqual(a.quantity,.01)
        self.assertEqual(len(a.events),1)
        self.assertAlmostEqual(a.fees,.3)

    def test_reversal_requires_two_fills(self):
        a=Account(1000)
        a.enter('a',1,.01,60000,5)
        with self.assertRaises(ValueError):
            a.enter('b',-1,.01,60000,5)
        a.close('b',60000,5,'reverse')
        a.enter('b',-1,.01,60000,5)
        self.assertAlmostEqual(a.fees,.9)
        self.assertEqual(replay(a.events,1000)['quantity'],-.01)

    def test_tick_rounding_is_adverse(self):
        c=Costs()
        self.assertEqual(c.fill(60000,1),60012)
        self.assertEqual(c.fill(60000,-1),59988)
        self.assertEqual(round_step(.003999,.001),.003)
        self.assertEqual(round_step(.002001,.001,True),.003)

    def test_replay_rejects_tampering(self):
        a=Account(1000);a.enter('a',1,.01,60000,5)
        a.events[0]['balance']+=1
        with self.assertRaises(ValueError):
            replay(a.events,1000)


if __name__=='__main__': unittest.main()
