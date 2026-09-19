import unittest
from app.research.recovery.directional_reclaim_review import review_directional_reclaims
from app.research.recovery.reclaim_review import replay_reclaims


def run(rows,side=1,ref=95):
    return review_directional_reclaims(rows,side=side,low=100,high=110,
        available_ms=0,reference_close=ref,basis_id='zone:v1')


def sample():
    return [dict(end_ms=(i+1)*60000,low=l,high=h,close=c) for i,(l,h,c) in
            enumerate([(105,114,112),(112,118,116),(108,115,113),(95,109,97),(105,114,112)])]


class DirectionalReviewTests(unittest.TestCase):
    def test_reflection_symmetry(self):
        rows=sample()
        mirrored=[dict(end_ms=r['end_ms'],low=210-r['high'],high=210-r['low'],close=210-r['close']) for r in rows]
        long=run(rows); short=run(mirrored,-1,115)
        self.assertEqual(long['cycle_count'],short['cycle_count'])
        names={'close_recovery','recovery_lost','retest_close_favorable','retest_close_inside'}
        self.assertEqual([[s for s in e['labels'] if s in names] for e in long['events']],
                         [[s for s in e['labels'] if s in names] for e in short['events']])

    def test_long_backwards_equivalence(self):
        rows=sample(); new=run(rows)
        old=replay_reclaims(rows,low=100,high=110,available_ms=0,reference_close=95)
        self.assertEqual(new['cycle_count'],old['cycle_count'])
        for a,b in zip(new['events'],old['events']):
            for key in ('available_ms','close','cycle','close_position','touched','recovery_active'):
                self.assertEqual(a[key],b[key])
        self.assertEqual(len(new['events']),len(old['events']))

    def test_repeats_do_not_mint_independent_basis(self):
        result=run(sample())
        self.assertEqual(result['cycle_count'],2)
        self.assertEqual(result['independent_basis_count'],1)
        self.assertEqual({e['basis_id'] for e in result['events']},{'zone:v1'})
        self.assertFalse(any(e['independent_new_basis'] or e['entry_approved'] for e in result['events']))
        self.assertEqual(len({e['observation_id'] for e in result['events']}),len(result['events']))

    def test_prefix_independent_of_future(self):
        prefix=run(sample()[:3])
        self.assertEqual(prefix['events'],[e for e in run(sample())['events'] if e['available_ms']<=180000])

    def test_bad_side_and_gap_rejected(self):
        with self.assertRaises(ValueError): run(sample(),0)
        with self.assertRaises(ValueError): run(sample()[1:])


if __name__=='__main__':unittest.main()
