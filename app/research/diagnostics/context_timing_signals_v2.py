"""E056 v2: higher-timeframe context is separate from 1m/3m execution events."""
import pandas as pd
from app.research.diagnostics.multiscale_profile import context_features, reaction


def features(m):
    f=context_features(m)
    f['m_previous_close']=m.c.shift(3)
    f['m_previous_high']=m.h.shift(3)
    f['m_previous_low']=m.l.shift(3)
    return f


def context(v):
    score=2*v['daily']+2*v['four_hour']+v['hour']+v['quarter']
    return 1 if score>0 else -1 if score<0 else 0


def timing(zone,side,v):
    """A zone interaction plus a completed 3m structure and 1m movement."""
    if not reaction(zone,side,v):return None
    if side*(v['m_c']-v['m_previous_close'])<=0:return None
    boundary=zone.high if side>0 else zone.low
    # Two completed 1m closes hold outside the zone, then clear prior 1m extreme.
    if side*(v['m_previous_close']-boundary)<=0:return None
    extreme=v['m_previous_high'] if side>0 else v['m_previous_low']
    if side*(v['m_c']-extreme)<=0:return None
    if side*(v['b_previous_close']-boundary)<=0:
        return 'reclaim' if side>0 else 'rejection'
    # Previous 3m already held beyond the edge; the new bar retests and holds it.
    return 'retest_hold'


def select_zone(zones,side,v,strict=True):
    candidates=[z for z in zones if (timing(z,side,v) if strict else reaction(z,side,v))]
    def score(z):
        overlap=len({x.horizon for x in zones if x.low<=z.high and x.high>=z.low})
        return overlap,z.horizon in ('sixty_day','week'),-abs(v['b_c']-z.poc)
    return max(candidates,key=score) if candidates else None


def entry_intent(zones,v,strict=True):
    bias=context(v)
    found={side:select_zone(zones,side,v,strict) for side in (1,-1)}
    # No unanimity requirement. Opposite-context setups are possible at observed zones.
    if bias and found[bias]:return bias,found[bias],bias
    for side in (1,-1):
        if found[side]:return side,found[side],bias
    return 0,None,bias


def capacity_limit(side,bias):
    # Research assumption: counter-context exposure is reduced, not prohibited.
    return 3 if bias and side!=bias else 5
