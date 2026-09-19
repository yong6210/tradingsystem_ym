"""Unapproved fixed-anchor challenge/retest trial. Never confirms a trend reversal."""
from math import isfinite


def review_anchor(rows, *, side, anchor, available_ms, reference_close, asof_ms):
    if type(side) is not int or side not in (-1,1):
        raise ValueError('explicit thesis hypothesis required')
    if not all(isfinite(x) and x>0 for x in (anchor,reference_close)) or asof_ms<available_ms:
        raise ValueError('invalid anchor or observation window')
    def adverse(close): return side*(close-anchor)<0
    state='challenged' if adverse(reference_close) else 'not_challenged'
    initial_state=state
    events=[];last=available_ms
    separated=False
    for r in rows:
        t=r['end_ms']
        if t<=available_ms or t>asof_ms:continue
        if t!=last+60000:raise ValueError('missing, duplicate or unordered minute')
        if not all(isfinite(r[k]) and r[k]>0 for k in ('low','high','close')) or not r['low']<=r['close']<=r['high']:
            raise ValueError('invalid candle')
        last=t;previous=state;label=None
        if adverse(r['close']):
            if state in ('not_challenged','recovered'):
                state='challenged';label='close_crossed_adverse'
            elif separated and r['low']<=anchor<=r['high']:
                state='failed_retest'
                if previous!='failed_retest':label='separate_retest_closed_adverse'
        elif side*(r['close']-anchor)>0 and state in ('challenged','failed_retest'):
            state='recovered';label='close_recovered_anchor'
        # Require a complete prior candle wholly on the adverse side before retest.
        separated = r['high']<anchor if side==1 else r['low']>anchor
        if label:
            events.append(dict(available_ms=t,label=label,state=state,close=r['close'],
                               direction_confirmation=False))
    if last!=asof_ms:raise ValueError('missing observation end')
    return dict(side=side,anchor=anchor,initial_state=initial_state,state=state,events=events,
                available_ms=available_ms,asof_ms=asof_ms,orders_generated=0,
                direction_confirmation=False,method_status='unapproved_anchor_trial')
