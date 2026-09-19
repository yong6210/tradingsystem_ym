"""First observable interactions after a structural marker becomes available.

Exact pivot prices are diagnostic markers, not inferred support/resistance bands.
"""
from math import isfinite


def first_interactions(candidate, rows, *, asof_ms):
    available = candidate['available_ms']
    if asof_ms < available:
        return None
    price = candidate['price']
    if candidate['kind'] not in ('high', 'low') or not isfinite(price) or price <= 0:
        raise ValueError('invalid structural marker')
    known = [r for r in rows if available <= r['end_ms'] <= asof_ms]
    if not known or known[0]['end_ms'] != available or known[-1]['end_ms'] != asof_ms:
        raise ValueError('missing confirmation or as-of candle')
    for i, r in enumerate(known):
        if i and r['end_ms'] != known[i-1]['end_ms']+60000:
            raise ValueError('missing, duplicate or unordered candle')
        if not all(isfinite(r[k]) and r[k] > 0 for k in ('low', 'high', 'close')) or not r['low'] <= r['close'] <= r['high']:
            raise ValueError('invalid candle')
    def touched(r): return r['low'] <= price <= r['high']
    def location(close): return 'above' if close > price else 'below' if close < price else 'on'
    confirming = known[0]
    prior = location(confirming['close'])
    previous_touch = touched(confirming)
    first_touch = first_new_contact = first_cross = None
    favorable = 'above' if candidate['kind']=='low' else 'below'
    for r in known[1:]:
        contact = touched(r)
        current = location(r['close'])
        observation = dict(available_ms=r['end_ms'],close=r['close'],close_position=current,
            touched=contact,from_position=prior,
            close_relative_to_marker_role='on' if current=='on' else 'favorable' if current==favorable else 'adverse',
            intrabar_sequence='unknown',entry_approved=False)
        if contact and first_touch is None:
            first_touch=dict(observation,continued_from_confirmation=previous_touch)
        if contact and not previous_touch and first_new_contact is None:
            first_new_contact=observation.copy()
        if prior != current and current != 'on' and first_cross is None:
            first_cross=dict(observation,price_traded_at_marker_observed=contact)
        prior,previous_touch=current,contact
    return dict(candidate_id=candidate['id'],price=price,kind=candidate['kind'],available_ms=available,
        observed_through_ms=asof_ms,confirmation_close=confirming['close'],
        confirmation_position=location(confirming['close']),confirmation_touched=touched(confirming),
        first_touch=first_touch,first_new_contact=first_new_contact,first_close_side_change=first_cross,
        observation_minutes=(asof_ms-available)//60000,
        status='new_contact_observed' if first_new_contact else 'no_new_contact_in_observed_window',
        orders_generated=0)
