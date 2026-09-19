import unittest
from app.research.recovery.post_confirmation_review import first_interactions


def row(t,l,h,c):return dict(end_ms=t*60000,low=l,high=h,close=c)
def candidate(kind='low'):return dict(id='p',kind=kind,price=100,available_ms=60000)


class PostConfirmationTests(unittest.TestCase):
    def test_forming_and_confirmation_touches_not_future_retest(self):
        data=[row(0,99,101,100),row(1,99,102,101),row(2,99,103,102),
              row(3,102,104,103),row(4,99,103,102)]
        r=first_interactions(candidate(),data,asof_ms=240000)
        self.assertEqual(r['first_touch']['available_ms'],120000)
        self.assertTrue(r['first_touch']['continued_from_confirmation'])
        self.assertEqual(r['first_new_contact']['available_ms'],240000)

    def test_future_prefix_and_unconfirmed(self):
        data=[row(1,102,105,104),row(2,101,104,103),row(3,99,104,102)]
        self.assertIsNone(first_interactions(candidate(),data,asof_ms=0))
        a=first_interactions(candidate(),data,asof_ms=120000)
        self.assertEqual(a,first_interactions(candidate(),data[:2],asof_ms=120000))
        self.assertIsNone(a['first_touch'])

    def test_gap_cross_is_not_touch(self):
        r=first_interactions(candidate(),[row(1,102,105,104),row(2,95,99,98)],asof_ms=120000)
        self.assertIsNone(r['first_touch'])
        self.assertFalse(r['first_close_side_change']['price_traded_at_marker_observed'])

    def test_short_marker_role(self):
        r=first_interactions(candidate('high'),[row(1,95,99,98),row(2,98,101,99)],asof_ms=120000)
        self.assertEqual(r['first_new_contact']['close_relative_to_marker_role'],'favorable')
        self.assertFalse(r['first_new_contact']['entry_approved'])

    def test_missing_confirmation_gap_end_rejected(self):
        for data,end in [([row(2,99,102,101)],120000),
                         ([row(1,99,102,101),row(3,99,102,101)],180000),
                         ([row(1,99,102,101)],120000)]:
            with self.assertRaises(ValueError):first_interactions(candidate(),data,asof_ms=end)

    def test_no_contact_is_censored_not_failure(self):
        r=first_interactions(candidate(),[row(1,102,105,104)],asof_ms=60000)
        self.assertEqual(r['observation_minutes'],0)
        self.assertEqual(r['status'],'no_new_contact_in_observed_window')


if __name__=='__main__':unittest.main()
