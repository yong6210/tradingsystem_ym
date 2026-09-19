"""Group identical marker/time observations, preserving every source candidate."""
from .models import dec


def group_contacts(records, *, asof_ms):
    groups = {}
    seen = {}
    for record in records:
        candidate, review = record['candidate'], record['review']
        event = review['first_new_contact']
        if event is None or event['available_ms'] > asof_ms:
            continue
        if candidate['available_ms'] >= event['available_ms']:
            raise ValueError('contact must follow candidate confirmation')
        price = dec(candidate['price'])
        key = (event['available_ms'], price)
        source = dict(candidate_id=candidate['id'], kind=candidate['kind'],
                      confirmed_ms=candidate['available_ms'], timeframe_minutes=candidate['timeframe_minutes'])
        signature = (key, dec(event['close']), source)
        if candidate['id'] in seen:
            if seen[candidate['id']] != signature:
                raise ValueError('conflicting duplicate candidate contact')
            continue
        seen[candidate['id']] = signature
        close = dec(event['close'])
        if key not in groups:
            groups[key] = dict(id=f"contact:{key[0]}:{format(price.normalize(),'f')}",
                available_ms=key[0], marker_price=price, close=close,
                close_position='above' if close>price else 'below' if close<price else 'on',
                sources=[], independent_evidence='unassessed', orders_generated=0)
        group = groups[key]
        if group['close'] != close:
            raise ValueError('same candle has conflicting closes')
        group['sources'].append(source)
    result = []
    for key in sorted(groups):
        group = groups[key]
        group['sources'].sort(key=lambda r:r['candidate_id'])
        group['marker_roles'] = sorted({r['kind'] for r in group['sources']})
        group['source_count'] = len(group['sources'])
        result.append(group)
    return result
