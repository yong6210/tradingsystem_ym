import unittest
from app.research.diagnostics.review_metrics import calendar_risk


class ReviewMetricTests(unittest.TestCase):
    def test_recovery_and_right_censoring(self):
        rows=[dict(day=f'2025-01-0{i}',equity=v) for i,v in enumerate((1100,1000,1050,1100,1000),1)]
        m=calendar_risk(rows)
        self.assertEqual(m['longest_completed_recovery_days'],3)
        self.assertEqual(m['current_underwater_days'],1)
        self.assertTrue(m['unrecovered_at_end'])

    def test_flat_after_halt_is_not_recovery(self):
        m=calendar_risk([dict(day=f'2025-01-0{i}',equity=900) for i in range(1,5)])
        self.assertEqual(m['longest_underwater_days'],4)
        self.assertEqual(m['completed_recoveries'],0)
        self.assertAlmostEqual(m['daily_es_5pct'],-10)

    def test_cash_has_zero_tail_and_no_drawdown(self):
        m=calendar_risk([dict(day='2025-01-01',equity=1000)])
        self.assertEqual(m['daily_es_5pct'],0)
        self.assertFalse(m['unrecovered_at_end'])

    def test_gap_and_invalid_equity_rejected(self):
        for rows in ([dict(day='2025-01-01',equity=1000),dict(day='2025-01-03',equity=990)],
                     [dict(day='2025-01-01',equity=float('nan'))]):
            with self.assertRaises(ValueError):calendar_risk(rows)
