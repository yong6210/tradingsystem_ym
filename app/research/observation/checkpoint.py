"""Checksummed offline state envelopes; not a live durable-journal protocol."""
import hashlib
import json


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def seal(state, binding):
    payload=dict(schema=1,evidence_kind='HISTORICAL_REPLAY',binding=binding,state=state)
    return dict(payload=payload,sha256=hashlib.sha256(canonical(payload)).hexdigest())


def unseal(envelope, expected_binding):
    payload=envelope['payload']
    if hashlib.sha256(canonical(payload)).hexdigest()!=envelope['sha256']:
        raise ValueError('checkpoint digest mismatch')
    if payload['schema']!=1 or payload['binding']!=expected_binding or payload['evidence_kind']!='HISTORICAL_REPLAY':
        raise ValueError('checkpoint binding or evidence class mismatch')
    return payload['state']
