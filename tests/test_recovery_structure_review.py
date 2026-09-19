import unittest
from app.research.recovery.structure_review import completed_bars, observe_structure, MINUTE


def bars(values):
    return [dict(end_ms=(i+1)*MINUTE, high=h, low=l, close=c) for i,(h,l,c) in enumerate(values)]


class StructureReviewTests(unittest.TestCase):
    def test_confirmation_delay_and_ties(self):
        data=bars([(9,5,7),(12,6,8),(10,5,7)])
        self.assertEqual(observe_structure(data[:2],1)['pivots'],[])
        p=observe_structure(data,1)['pivots'][0]
        self.assertEqual((p['pivot_bar_end_ms'],p['available_ms']),(2*MINUTE,3*MINUTE))
        self.assertEqual(observe_structure(bars([(12,5,7)]*3),1)['pivots'],[])

    def test_break_bar_not_retouch_and_next_bar_failure(self):
        data=bars([(9,5,7),(12,6,8),(10,5,7),(14,7,13),(14,11,13),(13,10,11)])
        events=observe_structure(data,1)['events']
        selected=[e for e in events if e['pivot_id']==f'high:{2*MINUTE}']
        self.assertEqual([e['kind'] for e in selected],['close_break','retouch_close_outside','close_back_across'])
        self.assertEqual([e['available_ms'] for e in selected],[4*MINUTE,5*MINUTE,6*MINUTE])

    def test_low_break_symmetry(self):
        data=bars([(10,6,8),(9,3,7),(10,5,8),(8,1,2),(5,1,2),(7,2,4)])
        events=observe_structure(data,1)['events']
        self.assertEqual([e['kind'] for e in events if e['pivot_id']==f'low:{2*MINUTE}'],
                         ['close_break','retouch_close_outside','close_back_across'])

    def test_future_and_incomplete_bars_excluded(self):
        data=bars([(10,5,8)]*10)
        a=completed_bars(data,7*MINUTE,3)
        self.assertEqual([b['end_ms'] for b in a],[3*MINUTE,6*MINUTE])
        self.assertEqual(a,completed_bars(data[:7],7*MINUTE,3))
        data[8]['high']=999
        self.assertEqual(a,completed_bars(data,7*MINUTE,3))

    def test_gap_duplicate_rejected(self):
        data=bars([(10,5,8)]*5)
        for invalid in (data[:2]+data[3:], data[:2]+data[1:]):
            with self.assertRaises(ValueError):
                completed_bars(invalid,5*MINUTE,3)

    def test_future_does_not_rewrite_event_history(self):
        data=bars([(9,5,7),(12,6,8),(10,5,7),(14,7,13),(14,11,13),(13,10,11)])
        prefix=observe_structure(data[:4],1)
        full=observe_structure(data,1)
        self.assertEqual(prefix['events'],[e for e in full['events'] if e['available_ms']<=4*MINUTE])
        self.assertEqual(prefix['direction'],'unassessed')


if __name__=='__main__': unittest.main()
