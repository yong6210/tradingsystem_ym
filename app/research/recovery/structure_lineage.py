"""As-of structural candidate provenance; geometry does not prove independence."""
from copy import deepcopy
from math import isfinite


def candidate_lineage(candidates, bands, *, asof_ms):
    known = [deepcopy(c) for c in candidates if c['available_ms'] <= asof_ms]
    seen = set()
    for c in known:
        if c['id'] in seen:
            raise ValueError('duplicate candidate id')
        seen.add(c['id'])
        if c['kind'] not in ('high','low') or not isfinite(c['price']) or c['price'] <= 0:
            raise ValueError('invalid candidate')
        if not c['evidence_start_ms'] < c['pivot_bar_end_ms'] <= c['available_ms']:
            raise ValueError('invalid evidence chronology')
    known.sort(key=lambda c:(c['available_ms'],c['id']))
    result=[]
    for c in known:
        contemporaries=[p for p in known if p['id'] != c['id'] and p['available_ms'] <= c['available_ms']]
        repeats=[p['id'] for p in contemporaries if p['price']==c['price']]
        shared=[p['id'] for p in contemporaries
                if max(p['evidence_start_ms'],c['evidence_start_ms']) < min(p['available_ms'],c['available_ms'])]
        relations=[]
        for b in bands:
            if b['available_ms'] > c['available_ms']:
                continue
            if b['low'] > b['high']:
                raise ValueError('invalid band')
            location='below' if c['price']<b['low'] else 'above' if c['price']>b['high'] else 'inside'
            relations.append(dict(basis_id=b['id'],location=location))
        result.append(dict(**c, same_price_known_ids=sorted(repeats), overlapping_evidence_ids=sorted(shared),
            band_relations=relations, new_record=True, independent_basis='unassessed', entry_approved=False))
    return result
