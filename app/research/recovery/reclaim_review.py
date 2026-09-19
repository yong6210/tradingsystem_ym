"""Sequential band recovery observations, without direction or order inference."""
from math import isfinite


def replay_reclaims(rows, *, low, high, available_ms, reference_close):
    if not all(isfinite(x) and x > 0 for x in (low, high, reference_close)) or low > high:
        raise ValueError('invalid band')
    def location(price):
        return 'below' if price < low else 'above' if price > high else 'inside'
    prior = location(reference_close)
    below_seen = prior == 'below'
    recovered = False
    cycle = 0
    last = available_ms
    touching = False
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
        # Only a later candle can be a retest of an observed recovery.
        if recovered:
            if current == 'below':
                labels.append('rebreak_below_after_reclaim')
                recovered = False
            elif touched and not touching:
                labels.append('retest_close_above' if current == 'above' else 'retest_close_inside')
        elif below_seen and current == 'above':
            cycle += 1
            recovered = True
            labels.append('close_reclaim_above')
        if touched and not touching:
            labels.append('contact_from_'+prior)
        if current != prior:
            labels.append('close_'+prior+'_to_'+current)
        if r['low'] < low and r['high'] > high:
            labels.append('both_boundaries_intrabar_order_unknown')
        if current == 'below':
            below_seen = True
        if labels:
            events.append(dict(available_ms=t, close=r['close'], labels=labels, cycle=cycle,
                               close_position=current, touched=touched, recovery_active=recovered))
        prior, touching = current, touched
    return dict(events=events, cycle_count=cycle, recovery_active=recovered,
                last_ms=last, close_position=prior, orders_generated=0)
