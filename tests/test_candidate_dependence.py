from decimal import Decimal as D
import unittest
from app.research.diagnostics.candidate_dependence import longest_underwater,pair_stats,position_overlap,account_summary


def daily(values):return [dict(day=f'2024-09-{i+1:02d}',equity=v) for i,v in enumerate(values)]
def trade(start,end,side):return dict(entry_minute=start,exit_minute=end,side=side)


class CandidateDependenceTests(unittest.TestCase):
    def test_initial_peak_unrecovered_includes_first_day(self):
        x=longest_underwater(daily([999,998,999]))
        self.assertEqual((x['days'],x['start_index'],x['end_index'],x['recovered']),(3,0,2,False))

    def test_recovery_day_is_included_and_ties_choose_first(self):
        x=longest_underwater(daily([1001,1000,1001,1000,1001]))
        self.assertEqual((x['days'],x['start_index'],x['end_index'],x['recovered']),(2,1,2,True))
        self.assertIsNone(longest_underwater(daily([1000,1001,1001])))

    def test_equal_peak_moves_start_forward(self):
        x=longest_underwater(daily([1000,1000,999]))
        self.assertEqual((x['start_index'],x['days']),(2,1))

    def test_flat_return_has_no_correlation_or_loss_denominator(self):
        x=pair_stats([D(0),D(0)],[D(-1),D(1)],[0,0],[-.001,.001])
        self.assertIsNone(x['daily_return_correlation'])
        self.assertIsNone(x['simultaneous_given_a_loss'])

    def test_conditional_losses_and_tolerance(self):
        x=pair_stats([D(-2),D(3),D('-1e-12')],[D(-4),D(-1),D(2)],[-.002,.003,0],[-.004,-.001,.002])
        self.assertEqual(x['simultaneous_loss_days'],1)
        self.assertEqual(x['simultaneous_given_b_loss'],.5)
        self.assertEqual(x['b_pnl_on_a_loss_days_usdc'],-4)
        self.assertEqual(x['a_pnl_on_b_loss_days_usdc'],1)

    def test_holdings_use_half_open_intervals(self):
        x=position_overlap([trade(0,5,1),trade(5,8,-1),trade(9,9,1)],
                           [trade(3,6,1),trade(8,10,-1)])
        self.assertEqual(x,dict(same_direction_overlap_minutes=2,opposite_direction_overlap_minutes=1,total_overlap_minutes=3))

    def test_trade_daily_month_cost_bridge(self):
        rows=daily([1002,1001]);trades=[dict(side=1,net_pnl=3)]
        metrics=dict(initial=1000,final_equity=1001,operating_cost=2,cycles=1,max_drawdown_pct=.1)
        r,_,_=account_summary(rows,trades,metrics)
        self.assertEqual(r['net_usdc'],1)
        self.assertEqual(r['net_less_top1_month_usdc'],0)
        self.assertEqual(r['monthly_pnl_usdc'],{'2024-09':1.0})


if __name__=='__main__':unittest.main()
