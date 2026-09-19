"""Side-symmetric observations with provenance, not entry approval."""
from math import isfinite


def review_directional_reclaims(rows, *, side, low, high, available_ms,
                                reference_close, basis_id):
    if side not in (-1, 1) or not basis_id:
        raise ValueError('explicit side and basis id required')
    if not all(isfinite(x) and x > 0 for x in (low, high, reference_close)) or low > high:
        raise ValueError('invalid band')
    def location(price):
        return 'below' if price < low else 'above' if price > high else 'inside'
    favorable = 'above' if side == 1 else 'below'
    adverse = 'below' if side == 1 else 'above'
    prior = location(reference_close)
    adverse_seen = prior == adverse
    recovered = False
    touching = False
    cycle = 0
    last = available_ms
    events = []
    for r in rows:
        t = r['end_ms']
        if t <= available_ms:
            continue
        if t != last + 60000:
            raise ValueError('missing, duplicated or unordered minute')
        if not all(isfinite(r[k]) and r[k] > 0 for k in ('low','high','close')) or not r['low'] <= r['close'] <= r['high']:
            raise ValueError('invalid candle')
        last = t
        current = location(r['close'])
        touched = r['low'] <= high and r['high'] >= low
        labels = []
        if recovered:
            if current == adverse:
                labels.append('recovery_lost')
                recovered = False
            elif touched and not touching:
                labels.append('retest_close_favorable' if current == favorable else 'retest_close_inside')
        elif adverse_seen and current == favorable:
            cycle += 1
            recovered = True
            labels.append('close_recovery')
        if touched and not touching:
            labels.append('contact_from_'+prior)
        if current != prior:
            labels.append('close_'+prior+'_to_'+current)
        if r['low'] < low and r['high'] > high:
            labels.append('both_boundaries_intrabar_order_unknown')
        if current == adverse:
            adverse_seen = True
        if labels:
            events.append(dict(available_ms=t, close=r['close'], labels=labels, cycle=cycle,
                close_position=current, touched=touched, recovery_active=recovered,
                basis_id=basis_id, observation_id=f'{basis_id}:{side}:{t}',
                independent_new_basis=False, entry_approved=False))
        prior, touching = current, touched
    return dict(side=side, basis_id=basis_id, events=events, cycle_count=cycle,
                recovery_active=recovered, last_ms=last, close_position=prior,
                independent_basis_count=1, orders_generated=0)
