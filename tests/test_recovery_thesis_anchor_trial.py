import unittest
from app.research.recovery.thesis_anchor_trial import review_anchor


def bars(values):return [dict(end_ms=(i+1)*60000,low=l,high=h,close=c) for i,(l,h,c) in enumerate(values)]
def run(data,side=1,reference=105,asof=None):return review_anchor(data,side=side,anchor=100,
    available_ms=0,reference_close=reference,asof_ms=len(data)*60000 if asof is None else asof)


class AnchorTrialTests(unittest.TestCase):
    def test_break_retest_recovery_separate(self):
        r=run(bars([(98,106,99),(96,99,98),(97,101,99),(99,103,102)]))
        self.assertEqual([e['state'] for e in r['events']],['challenged','failed_retest','recovered'])
        self.assertFalse(r['direction_confirmation'])

    def test_cross_bar_cannot_also_be_failed_retest(self):
        r=run(bars([(90,110,95)]))
        self.assertEqual(len(r['events']),1)
        self.assertEqual(r['state'],'challenged')

    def test_short_symmetry(self):
        data=bars([(98,106,99),(96,99,98),(97,101,99),(99,103,102)])
        mirror=[dict(end_ms=r['end_ms'],low=200-r['high'],high=200-r['low'],close=200-r['close']) for r in data]
        self.assertEqual([e['state'] for e in run(data)['events']],
                         [e['state'] for e in run(mirror,-1,95)['events']])

    def test_already_broken_anchor_is_not_initial_support(self):
        r=run(bars([(96,99,98)]),reference=95)
        self.assertEqual(r['initial_state'],'challenged')
        self.assertEqual(r['events'],[])

    def test_future_excluded(self):
        data=bars([(98,106,99),(96,99,98),(97,101,99)])
        self.assertEqual(run(data,asof=120000),run(data[:2]))

    def test_gap_and_invalid_candle_rejected(self):
        with self.assertRaises(ValueError):run(bars([(99,102,100)]*3)[1:])
        with self.assertRaises(ValueError):run(bars([(99,102,103)]))


if __name__=='__main__':unittest.main()
