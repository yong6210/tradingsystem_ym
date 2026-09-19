"""Trial v03 entry gate: a reclaim is not a new structural formation."""
import hashlib
import json

from .models import jsonable
from .market_adapter_v02 import MarketAdapterV02
from app.research.observation.checkpoint import seal, unseal


def assess_reuse(observer, breaks, now):
    zone=observer.history.zone
    own=[e for e in observer.history.events if e.kind=='broken' and e.evidence.recorded_ms<=now]
    reasons=[]
    if own:reasons.append('same_version_previously_broken')
    # Five completed 15m candles are the existing pivot definition. Require
    # the entire formation window, not only its confirmation time, after break.
    formation_start=None if zone.structural_close_ms is None else zone.structural_close_ms-75*60000
    related=[b for b in breaks.values() if b['time_ms']<=now and b['side']==observer.side
             and b['id']!=zone.key and zone.low<=b['high'] and zone.high>=b['low']]
    if formation_start is None:reasons.append('formation_window_unknown')
    if any(formation_start is None or formation_start<b['time_ms'] for b in related):
        reasons.append('overlapping_structure_began_before_break')
    if observer.history.as_of(now)['state']!='valid':reasons.append('current_reaction_not_valid')
    return dict(zone_key=zone.key,decision_ms=now,formation_start_ms=formation_start,
                own_break_count=len(own),related_breaks=jsonable(related),
                allowed=not reasons,reasons=reasons,scope='INITIAL_ENTRY_SUPPORT_ONLY')


class MarketAdapterV03(MarketAdapterV02):
    def __init__(self,config):
        super().__init__(config)
        self.breaks={}
        self.reuse_reviews=[]

    def observe(self,bar):
        super().observe(bar)
        for observer in self.zones.values():
            broken=[e for e in observer.history.events if e.kind=='broken']
            for event in broken:
                zone=observer.history.zone
                self.breaks[event.id]=dict(id=zone.key,side=observer.side,low=zone.low,high=zone.high,
                                           time_ms=event.evidence.recorded_ms)
        # Retain tombstones when the old candidate ages out; TTL must not wash
        # away an earlier break. No wall-clock expiry is a renewal condition.

    def propose(self,support,target,side,context,quote,simulate_fills):
        review=assess_reuse(support,self.breaks,quote.time_ms)
        self.reuse_reviews.append(review)
        if review['allowed']:
            return super().propose(support,target,side,context,quote,simulate_fills)

    def checkpoint(self):
        binding=dict(adapter='market-v03',config_sha256=hashlib.sha256(json.dumps(self.config,sort_keys=True).encode()).hexdigest())
        return seal(jsonable(dict(base=super().checkpoint(),breaks=self.breaks,reviews=self.reuse_reviews)),binding)

    @classmethod
    def restore(cls,config,envelope,restart_ms):
        binding=dict(adapter='market-v03',config_sha256=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest())
        saved=unseal(envelope,binding)
        restored=MarketAdapterV02.restore(config,saved['base'],restart_ms)
        adapter=cls(config);adapter.__dict__.update(restored.__dict__)
        from .models import dec
        adapter.breaks={k:{**b,'low':dec(b['low']),'high':dec(b['high'])} for k,b in saved['breaks'].items()}
        adapter.reuse_reviews=saved['reviews']
        return adapter
