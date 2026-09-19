"""Causal structural observations. Exploratory pivots, never trading signals."""
from math import isfinite

MINUTE = 60_000


def completed_bars(rows, asof_ms, minutes):
    if minutes <= 0:
        raise ValueError('positive timeframe required')
    known = [r for r in rows if r['end_ms'] <= asof_ms]
    for i, r in enumerate(known):
        if r['end_ms'] % MINUTE or (i and r['end_ms']-known[i-1]['end_ms'] != MINUTE):
            raise ValueError('unordered, duplicated or missing minute')
        if not all(isfinite(r[k]) and r[k] > 0 for k in ('high', 'low', 'close')):
            raise ValueError('invalid price')
        if not r['low'] <= r['close'] <= r['high']:
            raise ValueError('invalid candle')
    width = minutes*MINUTE
    groups = {}
    for r in known:
        end = ((r['end_ms']-1)//width+1)*width
        groups.setdefault(end, []).append(r)
    result = []
    for end, block in sorted(groups.items()):
        if end <= asof_ms and len(block) == minutes:
            result.append(dict(end_ms=end, high=max(r['high'] for r in block),
                               low=min(r['low'] for r in block), close=block[-1]['close']))
    return result


def observe_structure(bars, flank=2):
    """Strict pivots confirmed after flank right bars; ties produce no pivot.

    A level first exists at confirmation close. Its subsequent close crossing is
    a break observation. Retouch is assessed only on later bars, never the break
    bar; OHLC provides no within-bar sequence or fill evidence.
    """
    if flank < 1:
        raise ValueError('positive flank required')
    pivots, events = [], []
    for i, bar in enumerate(bars):
        if i and bar['end_ms'] <= bars[i-1]['end_ms']:
            raise ValueError('unordered bars')
        for p in pivots:
            if p['state'] == 'failed':
                continue
            level = p['price']
            sign = 1 if p['kind'] == 'high' else -1
            prev = bars[i-1]['close']
            now = bar['close']
            if p['state'] == 'unbroken':
                if sign*(prev-level) <= 0 < sign*(now-level):
                    p['state'] = 'broken'
                    p['break_ms'] = bar['end_ms']
                    events.append(dict(pivot_id=p['id'], available_ms=bar['end_ms'], kind='close_break', price=level))
            else:
                # Re-entry after a gap may fail without an observed trade at level.
                failed = sign*(now-level) < 0
                touched = bar['low'] <= level <= bar['high']
                if failed or touched:
                    label = 'close_back_across' if failed else 'retouch_close_outside' if sign*(now-level)>0 else 'retouch_close_on_level'
                    events.append(dict(pivot_id=p['id'], available_ms=bar['end_ms'], kind=label,
                                       price=level, touched=touched))
                    if failed:
                        p['state'] = 'failed'
        center = i-flank
        if center < flank:
            continue
        candidate = bars[center]
        neighbors = bars[center-flank:center]+bars[center+1:i+1]
        for kind in ('high', 'low'):
            value = candidate[kind]
            strict = all(value > n[kind] for n in neighbors) if kind == 'high' else all(value < n[kind] for n in neighbors)
            if strict:
                pivots.append(dict(id=f'{kind}:{candidate["end_ms"]}', kind=kind, price=value,
                                   pivot_bar_end_ms=candidate['end_ms'], available_ms=bar['end_ms'], state='unbroken'))
    for p in pivots:
        close = bars[-1]['close']
        p['latest_close_position'] = 'above' if close > p['price'] else 'below' if close < p['price'] else 'on'
    latest = {kind: [p for p in pivots if p['kind'] == kind][-2:] for kind in ('high', 'low')}
    relations = {}
    for kind, pair in latest.items():
        relations[kind] = ('insufficient' if len(pair)<2 else
                           'higher' if pair[1]['price']>pair[0]['price'] else
                           'lower' if pair[1]['price']<pair[0]['price'] else 'equal')
    return dict(pivots=pivots, events=events, latest=latest, relations=relations,
                direction='unassessed', orders_generated=0)
