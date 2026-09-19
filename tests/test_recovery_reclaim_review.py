import unittest
from app.research.recovery.reclaim_review import replay_reclaims


def rows(values):
    return [dict(end_ms=(i+1)*60000,low=l,high=h,close=c) for i,(l,h,c) in enumerate(values)]


def review(data):
    return replay_reclaims(data,low=100,high=110,available_ms=0,reference_close=95)


class ReclaimReviewTests(unittest.TestCase):
    def test_inside_is_not_reclaim_and_reclaim_is_not_retest(self):
        result=review(rows([(99,108,105),(104,114,112)]))
        self.assertEqual(result['cycle_count'],1)
        self.assertNotIn('close_reclaim_above',result['events'][0]['labels'])
        self.assertIn('close_reclaim_above',result['events'][1]['labels'])
        self.assertFalse(any('retest' in label for label in result['events'][1]['labels']))

    def test_repeat_cycles_and_separate_retest(self):
        data=rows([(105,114,112),(112,118,116),(108,115,113),(95,109,97),(105,114,112)])
        result=review(data)
        self.assertEqual(result['cycle_count'],2)
        self.assertIn('retest_close_above',result['events'][1]['labels'])
        self.assertIn('rebreak_below_after_reclaim',result['events'][2]['labels'])
        self.assertEqual(review(data[:3])['events'],result['events'][:2])

    def test_gap_no_fictitious_touch_and_wide_bar_ambiguity(self):
        result=review(rows([(112,118,114),(90,120,95)]))
        self.assertFalse(result['events'][0]['touched'])
        self.assertIn('both_boundaries_intrabar_order_unknown',result['events'][1]['labels'])

    def test_missing_and_invalid_rejected(self):
        with self.assertRaises(ValueError): review(rows([(90,99,95)]*3)[1:])
        with self.assertRaises(ValueError): review(rows([(100,110,120)]))

    def test_preavailability_cannot_create_cycle(self):
        result=replay_reclaims(rows([(90,99,95),(110,120,115)]),low=100,high=110,
                               available_ms=60000,reference_close=115)
        self.assertEqual(result['cycle_count'],0)


if __name__=='__main__': unittest.main()
