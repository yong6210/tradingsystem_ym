"""Observed departures and first returns; no inferred intrabar order or trades."""
from math import isfinite


def observe_excursions(rows, *, low, high):
    if not (isfinite(low) and isfinite(high) and 0<low<high):
        raise ValueError('invalid band')
    previous=None;active=None;events=[];legs=[]
    for r in rows:
        if previous and r['end_ms']!=previous['end_ms']+60000:
            raise ValueError('missing or unordered minute')
        if not all(isfinite(r[k]) and r[k]>0 for k in ('low','high','close')) or not r['low']<=r['close']<=r['high']:
            raise ValueError('invalid candle')
        touch=r['low']<=high and r['high']>=low
        position='below' if r['close']<low else 'above' if r['close']>high else 'inside'
        if active is not None:
            if touch:
                completed=dict(active,end_ms=r['end_ms'],status='returned',return_close=r['close'],
                               return_position=position,return_intrabar_order='unknown')
                legs.append(completed)
                events.append(dict(kind='first_return',available_ms=r['end_ms'],leg=completed))
                active=None
            elif position!=active['side']:
                completed=dict(active,end_ms=r['end_ms'],status='gap_across_without_observed_contact')
                legs.append(completed)
                events.append(dict(kind='gap_across',available_ms=r['end_ms'],leg=completed))
                active=None
            else:
                active['outside_minutes']+=1
                active['outside_high']=max(active['outside_high'],r['high'])
                active['outside_low']=min(active['outside_low'],r['low'])
        if active is None and not touch and previous and previous['low']<=high and previous['high']>=low:
            active=dict(start_ms=r['end_ms'],last_contact_ms=previous['end_ms'],side=position,
                        departure_close=r['close'],outside_minutes=1,outside_high=r['high'],outside_low=r['low'])
            events.append(dict(kind='departure',available_ms=r['end_ms'],leg=active.copy()))
        previous=r
    return dict(events=events,completed_legs=legs,open_leg=active,orders_generated=0)
