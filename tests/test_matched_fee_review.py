import unittest
from scripts.run_matched_fee_review import joint_loss, necessary_checks


class MatchedFeeReviewTests(unittest.TestCase):
    def test_cash_days_remain_and_loss_overlap_is_conditional(self):
        def account(values):
            return dict(daily=[dict(day=f'2026-01-{i+1:02d}',equity=v) for i,v in enumerate(values)],trades=[])
        got=joint_loss(account([990,980,980]),account([990,995,995]))
        self.assertEqual(got['calendar_days'],3)
        self.assertEqual(got['both_loss_days'],1)
        self.assertEqual(got['both_loss_given_right_loss'],1)
        self.assertEqual(got['joint_holding_days'],0)

    def test_mismatched_dates_fail(self):
        a=dict(daily=[dict(day='2026-01-01',equity=1000)],trades=[])
        b=dict(daily=[dict(day='2026-01-02',equity=1000)],trades=[])
        with self.assertRaises(ValueError): joint_loss(a,b)

    def test_profitable_halted_or_bad_year_does_not_pass(self):
        good=dict(return_pct=2,drawdown_halted=False,cycles=120,
            annual={'2025':dict(return_pct=1),'2026':dict(return_pct=1)})
        self.assertTrue(all(necessary_checks(good,good).values()))
        self.assertFalse(all(necessary_checks(good,good|dict(drawdown_halted=True)).values()))
        self.assertFalse(all(necessary_checks(good,good|dict(annual={'2025':dict(return_pct=-1),'2026':dict(return_pct=3)})).values()))


if __name__=='__main__': unittest.main()
