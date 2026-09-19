import unittest

from app.research.recovery.zone_review import ReviewZone, ZoneReview
from app.research.recovery.models import Bar


class ZoneReviewTests(unittest.TestCase):
    def review(self, reference=110):
        return ZoneReview([ReviewZone('z',100,105)], reference_price=reference, available_ms=60000)

    def bar(self, minute, low, high, close):
        return Bar(minute*60000, close, high, low, close, minute*60000)

    def test_contact_is_observation_not_order(self):
        r=self.review()
        events=r.observe(self.bar(1,103,110,104))
        self.assertIn('contact_from_above',events[0]['labels'])
        self.assertIsNone(events[0]['order'])
        self.assertEqual(events[0]['interpretation'],'geometric_observation_only')

    def test_one_minute_undercut_and_recovery_preserve_history(self):
        r=self.review()
        r.observe(self.bar(1,101,110,102))
        below=r.observe(self.bar(2,99,104,99))[0]
        recovered=r.observe(self.bar(3,99,106,103))[0]
        self.assertIn('close_inside_to_below',below['labels'])
        self.assertTrue(recovered['previously_closed_below'])
        self.assertEqual(recovered['close_position'],'inside')

    def test_gap_cannot_be_counted_as_zone_trade(self):
        r=self.review()
        e=r.observe(self.bar(1,95,99,98))[0]
        self.assertFalse(e['touched'])
        self.assertIn('gap_over_zone_without_observed_trade',e['labels'])
        self.assertEqual(r.states['z']['touch_minutes'],0)

    def test_both_boundaries_do_not_invent_intrabar_order(self):
        r=self.review()
        e=r.observe(self.bar(1,98,108,103))[0]
        self.assertIn('both_boundaries_in_range_sequence_unknown',e['labels'])
        self.assertNotIn('first_crossing',e)

    def test_redelivery_gap_and_premature_observation(self):
        r=self.review()
        with self.assertRaises(ValueError):
            r.observe(Bar(0,110,111,109,110,0))
        bar=self.bar(1,103,110,104)
        r.observe(bar)
        self.assertEqual(r.observe(bar),[])
        with self.assertRaises(ValueError):
            r.observe(self.bar(3,103,110,104))
        self.assertEqual(r.states['z']['touch_minutes'],1)
        r.observe(self.bar(2,103,110,104))
        self.assertEqual(r.states['z']['touch_minutes'],2)

    def test_prefix_replay_is_independent_of_later_break(self):
        bars=[self.bar(1,103,110,104),self.bar(2,104,108,106),self.bar(3,95,102,96)]
        whole=self.review()
        outputs=[whole.observe(b) for b in bars]
        prefix=self.review()
        self.assertEqual([prefix.observe(b) for b in bars[:2]],outputs[:2])
        self.assertFalse(prefix.states['z']['below_seen'])


if __name__=='__main__':
    unittest.main()
