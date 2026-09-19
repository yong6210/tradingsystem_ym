import unittest
from app.research.recovery.protected_structure import reduce_structure,protected_structure


def pivot(key,kind,price,t):return dict(id=key,kind=kind,price=price,pivot_bar_end_ms=t,available_ms=t+1)
def bar(t,close):return dict(end_ms=t,close=close,high=close+1,low=close-1)

class ProtectedStructureTests(unittest.TestCase):
    def test_long_formation_freezes_reaction_not_new_local_low(self):
        p=[pivot('old-low','low',90,1),pivot('high','high',110,3),pivot('reaction','low',100,5),
           pivot('local','low',112,12)]
        r=reduce_structure([bar(9,109),bar(10,111),bar(14,115),bar(15,108)],p)
        self.assertEqual(r['candidate']['side'],1)
        self.assertEqual(r['candidate']['protected']['price'],100)
        self.assertEqual(r['candidate']['status'],'active')

    def test_anchor_invalidation_is_not_automatic_reversal(self):
        p=[pivot('old-low','low',90,1),pivot('high','high',110,3),pivot('reaction','low',100,5)]
        r=reduce_structure([bar(9,109),bar(10,111),bar(11,99),bar(12,95)],p)
        self.assertEqual(r['candidate']['status'],'invalidated')
        self.assertEqual(r['candidate']['side'],1)
        self.assertFalse(r['events'][-1]['opposite_direction_confirmed'])

    def test_short_mirror(self):
        p=[pivot('old-high','high',120,1),pivot('low','low',90,3),pivot('reaction','high',110,5)]
        r=reduce_structure([bar(9,91),bar(10,89),bar(11,105)],p)
        self.assertEqual(r['candidate']['side'],-1)
        self.assertEqual(r['candidate']['protected']['price'],110)

    def test_unavailable_reaction_cannot_justify_break(self):
        p=[pivot('old-low','low',90,1),pivot('high','high',110,3),pivot('reaction','low',100,9)]
        r=reduce_structure([bar(9,109),bar(10,111)],p)
        self.assertIsNone(r['candidate'])

    def test_old_formation_cannot_be_reused_after_invalidation(self):
        p=[pivot('old-low','low',90,1),pivot('high','high',110,3),pivot('reaction','low',100,5)]
        r=reduce_structure([bar(9,109),bar(10,111),bar(11,99),bar(12,111)],p)
        self.assertEqual(len(r['events']),2)
        self.assertEqual(r['candidate']['status'],'invalidated')

    def test_late_confirmation_recognizes_prior_break_only_when_known(self):
        p=[pivot('old-low','low',90,1),pivot('high','high',110,3),
           dict(pivot('reaction','low',100,5),available_ms=12)]
        bars=[bar(9,109),bar(10,111),bar(11,112),bar(12,113)]
        self.assertIsNone(reduce_structure(bars[:3],p,confirmation_mode='confirmed_path')['candidate'])
        r=reduce_structure(bars,p,confirmation_mode='confirmed_path')
        self.assertEqual(r['candidate']['formed_ms'],12)
        self.assertEqual(r['candidate']['break_ms'],10)
        self.assertIsNone(reduce_structure(bars,p)['candidate'])

    def test_anchor_advances_only_with_new_directional_extension(self):
        p=[pivot('old-low','low',90,1),pivot('high','high',110,3),pivot('reaction','low',100,5),
           pivot('new-high','high',120,13),pivot('new-low','low',112,15)]
        bars=[bar(9,109),bar(10,111),bar(17,119),bar(18,121)]
        mode='confirmed_path_reanchor'
        before=reduce_structure(bars[:-1],p,confirmation_mode=mode)
        self.assertEqual(before['candidate']['protected']['price'],100)
        after=reduce_structure(bars,p,confirmation_mode=mode)
        self.assertEqual(after['candidate']['protected']['price'],112)
        self.assertEqual(after['events'][-1]['action'],'candidate_anchor_advanced')

    def test_late_confirmation_cannot_revive_broken_reaction(self):
        p=[pivot('old-low','low',90,1),pivot('high','high',110,3),
           dict(pivot('reaction','low',100,5),available_ms=12)]
        r=reduce_structure([bar(9,109),bar(10,111),bar(11,99),bar(12,113)],p,confirmation_mode='confirmed_path')
        self.assertIsNone(r['candidate'])

    def test_future_landmarks_do_not_change_prefix_candidates(self):
        base=[pivot('old-low','low',90,1),pivot('high','high',110,3),pivot('reaction','low',100,5)]
        future=[pivot('future-high','high',150,30),pivot('future-low','low',130,35)]
        bars=[bar(9,109),bar(10,111),bar(11,115)]
        for mode in ('current_cross','confirmed_path','confirmed_path_reanchor'):
            self.assertEqual(reduce_structure(bars,base,confirmation_mode=mode),
                             reduce_structure(bars,base+future,confirmation_mode=mode))
