import unittest
from app.research.recovery.position_alternatives import PositionExample, ExampleCosts, alternative
from app.research.recovery.models import dec


class AlternativeTests(unittest.TestCase):
    def costs(self, fee=0):
        return ExampleCosts(fee,0,0,'.1','.001',2)

    def test_video_loss_split_and_campaign_recovery(self):
        p=PositionExample(-1,5,100000,0,0,0,100000)
        add=alternative(p,self.costs(),mark=102000,action='increase',quantity=5,stress_moves=(2000,3000))
        half=alternative(add['after'],self.costs(),mark=101200,action='retracement_reduce',quantity=5,stress_moves=(2000,3000))
        self.assertEqual(half['after'].average,101000)
        self.assertEqual(half['after'].realized_gross,-1000)
        self.assertEqual(half['unrealized'],-1000)
        self.assertEqual(half['total_net'],-2000)
        self.assertEqual(half['campaign_break_even_fill'],100800)
        self.assertEqual(half['change_at_same_mark'],0)

    def test_fee_slippage_changes_total_only_by_execution_friction(self):
        p=PositionExample(1,'.2',63050,-10,5,2,10000)
        c=ExampleCosts('.0004','.00005','.0002','.1','.001',2)
        for action,qty,sign in [('increase','.1',1),('retracement_reduce','.1',-1)]:
            result=alternative(p,c,mark='62902.9',action=action,quantity=qty,stress_moves=(2000,))
            expected=sign*dec(qty)*(dec('62902.9')-result['execution_price'])-result['action_fee']
            self.assertLess(abs(result['change_at_same_mark']-expected),dec('1e-20'))
            self.assertLess(result['change_at_same_mark'],0)

    def test_campaign_recovery_solves_full_net_after_exit_fee_both_sides(self):
        for side in (-1,1):
            p=PositionExample(side,'.2',63000,-25,7,2,10000)
            r=alternative(p,self.costs('.0004'),mark=62900,action='wait',stress_moves=(2000,))
            be=r['campaign_break_even_fill']
            net=p.pnl(be)-p.quantity*be*dec('.0004')
            self.assertLess(abs(net),dec('1e-20'))

    def test_more_inventory_worsens_same_adverse_move(self):
        p=PositionExample(1,'.1',63300,0,0,0,10000)
        wait=alternative(p,self.costs(),mark=63000,action='wait',stress_moves=(3000,))
        add=alternative(p,self.costs(),mark=63000,action='increase',quantity='.1',stress_moves=(3000,))
        self.assertEqual(add['adverse_scenarios'][0]['pnl']-wait['adverse_scenarios'][0]['pnl'],-300)
        self.assertLess(add['after'].average,p.average)

    def test_partial_loss_is_not_silently_half_rule(self):
        p=PositionExample(1,'.2',63300,0,0,0,10000)
        with self.assertRaises(ValueError):
            alternative(p,self.costs(),mark=63000,action='retracement_reduce',quantity='.05',stress_moves=(2000,))
        result=alternative(p,self.costs(),mark=63000,action='partial_loss_example',quantity='.05',stress_moves=(2000,))
        self.assertEqual(result['after'].quantity,dec('.15'))
        self.assertEqual(result['after'].realized_gross,-15)
        self.assertEqual(result['change_at_same_mark'],0)

    def test_prior_losses_survive_flatten_and_reentry(self):
        p=PositionExample(1,'.1',63300,-10,5,2,10000)
        flat=alternative(p,self.costs(),mark=63000,action='retracement_reduce',quantity='.1',stress_moves=(2000,))
        self.assertIsNone(flat['campaign_break_even_fill'])
        self.assertEqual(flat['total_net'],-45)
        new=alternative(flat['after'],self.costs(),mark=63000,action='increase',quantity='.1',stress_moves=(2000,))
        self.assertEqual(new['campaign_break_even_fill'],63450)

    def test_margin_deficit_not_hidden_and_inputs_immutable(self):
        p=PositionExample(1,1,63000,0,0,0,1000)
        r=alternative(p,self.costs(),mark=63000,action='wait',stress_moves=(2000,))
        self.assertEqual(r['free_margin_proxy'],-30500)
        self.assertEqual(p.quantity,1)
        with self.assertRaises(ValueError):
            alternative(p,self.costs(),mark=63000,action='increase',quantity='.0001',stress_moves=(2000,))


if __name__=='__main__':unittest.main()
