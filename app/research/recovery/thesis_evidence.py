"""Point-in-time reference validation; never a market-direction classifier."""
from copy import deepcopy
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


class ThesisEvidenceRegistry:
    def __init__(self, records):
        self._records = {}
        for raw in records:
            r = deepcopy(raw)
            key = r['id']
            if not isinstance(key,str) or not key.strip() or key in self._records:
                raise ValueError('invalid or duplicate evidence id')
            if type(r['available_ms']) is not int or r['available_ms']<0:
                raise ValueError('invalid evidence availability')
            if not isinstance(r.get('source_sha256'),str) or len(r['source_sha256'])!=64 or any(c not in '0123456789abcdef' for c in r['source_sha256']):
                raise ValueError('source digest required')
            if not isinstance(r.get('event_key'),str) or not r['event_key']:
                raise ValueError('event provenance key required')
            self._records[key]=r

    def resolve(self, evidence_ids, *, observed_ms):
        if type(observed_ms) is not int or observed_ms<0:
            raise ValueError('invalid decision time')
        if not isinstance(evidence_ids,list) or not evidence_ids or any(not isinstance(k,str) for k in evidence_ids) or len(set(evidence_ids))!=len(evidence_ids):
            raise ValueError('distinct nonempty evidence references required')
        selected=[]
        for key in evidence_ids:
            if key not in self._records:
                raise ValueError('unknown evidence id: '+key)
            r=self._records[key]
            if r['available_ms']>observed_ms:
                raise ValueError('evidence not yet available: '+key)
            selected.append(deepcopy(r))
        grouped={}
        for r in selected:grouped.setdefault(r['event_key'],[]).append(r['id'])
        body=dict(observed_ms=observed_ms,records=selected,
                  provenance_groups=[dict(event_key=k,evidence_ids=sorted(v)) for k,v in sorted(grouped.items())],
                  independent_evidence='unassessed',market_direction_verified=False)
        return dict(body=body,sha256=digest(body))


def validated_assessment(registry, assessment, *, observed_ms):
    result=deepcopy(assessment)
    if not isinstance(result,dict):raise ValueError('assessment required')
    # Ignore no externally supplied certificate: resolve the actual supplied IDs anew.
    result['evidence_audit']=registry.resolve(result.get('evidence_ids'),observed_ms=observed_ms)
    return result


def verify_audit(assessment, observed_ms):
    """Check saved evidence snapshots on replay, not external source authenticity."""
    audit=assessment['evidence_audit'];body=audit['body']
    if audit['sha256']!=digest(body) or body['observed_ms']!=observed_ms:
        raise ValueError('invalid evidence snapshot digest or decision time')
    rebuilt=ThesisEvidenceRegistry(body['records']).resolve(assessment['evidence_ids'],observed_ms=observed_ms)
    if rebuilt!=audit:
        raise ValueError('evidence snapshot does not match assessment')
