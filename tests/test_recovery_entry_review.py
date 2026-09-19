import unittest
import pandas as pd
from app.research.recovery.entry_review import review_entry


class EntryReviewTests(unittest.TestCase):
    def setUp(self):
        self.t = pd.Timestamp("2026-08-02", tz="UTC")
        self.frame = pd.DataFrame(dict(h=[102.]*1440, l=[98.]*1440, c=[100.]*1440),
                                  index=pd.date_range(self.t-pd.Timedelta(days=1), periods=1440, freq="min"))
        self.plan = dict(id="p", created_ms=int(self.t.timestamp()*1000), side=1,
                         reason="context=1;", support=dict(low="98", high="99", available_ms=0),
                         target=dict(low="104", high="105", available_ms=0))

    def test_future_prices_cannot_change_card(self):
        before = review_entry(self.plan, self.frame)
        self.frame.loc[self.t] = [1000000., .001, 500000.]
        self.assertEqual(before, review_entry(self.plan, self.frame))
        self.assertEqual(before["target_to_prior_range"], 1.)

    def test_missing_minute_rejected(self):
        with self.assertRaises(ValueError):
            review_entry(self.plan, self.frame.iloc[1:])

    def test_future_evidence_rejected(self):
        self.plan["target"]["available_ms"] = self.plan["created_ms"]+1
        with self.assertRaises(ValueError):
            review_entry(self.plan, self.frame)

    def test_countertrend_requires_separate_contract(self):
        self.plan["side"] = -1
        self.assertIn("countertrend_exit_contract", review_entry(self.plan, self.frame)["missing_contract"])


if __name__ == "__main__":
    unittest.main()
