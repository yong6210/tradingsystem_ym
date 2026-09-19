import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from app.research.recovery.zone_reuse import assess_reuse, MarketAdapterV03
from app.research.recovery.models import Zone, Bar, Quote, dec
from app.research.recovery.evidence import Evidence, ZoneEvent, ZoneHistory
from app.research.recovery.zone_observer import ZoneObserver


class ReuseTests(unittest.TestCase):
    def observer(self,broken=False,side=1):
        z=Zone('new',1,100,101,9000000,'fixture',structural_close_ms=9000000)
        events=[ZoneEvent('formed','formed',Evidence('fixture',9000000,9000000,9000000,'candidate')),
                ZoneEvent('validated','validated',Evidence('fixture',9120000,9120000,9120000,'reaction'))]
        if broken:
            for i,kind in enumerate(('broken','reclaimed','validated')):
                t=9180000+i*60000;events.append(ZoneEvent(kind+str(t),kind,Evidence('fixture',t,t,t,kind)))
        return ZoneObserver(ZoneHistory(z,tuple(events)),side,dec('.2'),'fixture')

    def old(self,time=4500000,side=1,low=100,high=101):
        return {'old:break':dict(id='old:1',time_ms=time,side=side,low=dec(low),high=dec(high))}

    def test_reclaim_is_valid_but_not_entry_eligible(self):
        o=self.observer(True)
        self.assertEqual(o.history.as_of(9400000)['state'],'valid')
        self.assertIn('same_version_previously_broken',assess_reuse(o,{},9400000)['reasons'])

    def test_full_formation_window_required_and_boundary_allowed(self):
        o=self.observer()
        self.assertTrue(assess_reuse(o,self.old(),9400000)['allowed'])
        self.assertFalse(assess_reuse(o,self.old(4500001),9400000)['allowed'])

    def test_future_break_does_not_change_past_assessment(self):
        o=self.observer()
        self.assertEqual(assess_reuse(o,{},9400000),assess_reuse(o,self.old(9500000),9400000))

    def test_role_and_overlap_are_explicit(self):
        o=self.observer()
        self.assertTrue(assess_reuse(o,self.old(8000000,side=-1),9400000)['allowed'])
        self.assertTrue(assess_reuse(o,self.old(8000000,low=102,high=103),9400000)['allowed'])
        self.assertFalse(assess_reuse(o,self.old(8000000,low=101,high=102),9400000)['allowed'])
        self.assertFalse(assess_reuse(self.observer(side=-1),self.old(8000000,side=-1),9400000)['allowed'])

    def test_new_id_alone_cannot_erase_overlapping_break(self):
        self.assertIn('overlapping_structure_began_before_break',assess_reuse(self.observer(),self.old(8900000),9400000)['reasons'])

    def test_restore_retains_tombstones_after_candidate_removal(self):
        root=Path(__file__).resolve().parents[1]
        a=MarketAdapterV03(json.loads((root/'configs/research/recovery_market_v03.json').read_text()))
        a.observe(Bar(60000,100,101,99,100,60000))
        a.breaks=self.old();a.reuse_reviews=[assess_reuse(self.observer(),a.breaks,9400000)]
        b=MarketAdapterV03.restore(a.config,a.checkpoint(),60001)
        self.assertEqual(b.breaks,a.breaks)
        self.assertEqual(b.reuse_reviews,a.reuse_reviews)
        self.assertIn('restart',b.replay.engine.locks)

    def test_gate_blocks_order_path_and_keeps_original_target(self):
        from app.research.recovery.market_adapter_v02 import MarketAdapterV02
        root=Path(__file__).resolve().parents[1]
        a=MarketAdapterV03(json.loads((root/'configs/research/recovery_market_v03.json').read_text()))
        q=Quote(9400000,102,103,1,1,1,True,True);target=object();context=object()
        with patch.object(MarketAdapterV02,'propose') as parent:
            a.propose(self.observer(True),target,1,context,q,True)
            parent.assert_not_called();self.assertFalse(a.replay.events)
            support=self.observer()
            a.propose(support,target,1,context,q,True)
            parent.assert_called_once_with(support,target,1,context,q,True)


if __name__=='__main__':unittest.main()
