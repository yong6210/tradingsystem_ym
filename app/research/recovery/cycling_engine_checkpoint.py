"""Versioned complete research-engine checkpoint, JSON only, same-code restore.

The controller is event-replayed independently and remains reconciliation-locked.
The checksum detects corruption, not malicious authorship. No exchange I/O.
"""
from dataclasses import fields,is_dataclass
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from .models import Bar,Zone,dec
from .position_alternatives import ExampleCosts
from .cycling_reduction_engine import ReductionReference
from .thesis_evidence import ThesisEvidenceRegistry
from .cycling_plan_recovery import CyclingPlanRecoveryEngine
from .cycling_orders import CyclingOrders

TYPES={c.__name__:c for c in (Bar,Zone,ExampleCosts,ReductionReference)}
STATE=frozenset('retired_references reference_previous_close main_status main_assessed_ms main_evidence_ids last clock previous departed crossed weak local_failed growth reduced_growth queued_half pending_half last_basis grown_orders submitted order_bases used journal planned_limits paused_plans order_handoff plan_revision replan_required plan_recovery'.split())


def encode(v):
    if isinstance(v,Decimal):return {'type':'decimal','value':str(v)}
    if is_dataclass(v):return {'type':type(v).__name__,'value':{f.name:encode(getattr(v,f.name)) for f in fields(v)}}
    if isinstance(v,dict):return {'type':'dict','value':[[encode(k),encode(x)] for k,x in v.items()]}
    if isinstance(v,(tuple,set,list)):
        values=[encode(x) for x in v]
        if isinstance(v,set):values.sort(key=lambda x:json.dumps(x,sort_keys=True))
        return {'type':type(v).__name__,'value':values}
    if type(v) is float:
        if not math.isfinite(v):raise ValueError('nonfinite checkpoint value')
        return v
    if v is None or type(v) in (str,int,bool):return v
    raise ValueError('unsupported checkpoint type')


def decode(v):
    if type(v) is float:
        if not math.isfinite(v):raise ValueError('nonfinite checkpoint value')
        return v
    if v is None or type(v) in (str,int,bool):return v
    if not isinstance(v,dict) or set(v)!={'type','value'}:raise ValueError('invalid typed value')
    kind,value=v['type'],v['value']
    if kind=='decimal':return dec(value)
    if kind in TYPES:return TYPES[kind](**{k:decode(x) for k,x in value.items()})
    if kind=='dict':
        pairs=[(decode(k),decode(x)) for k,x in value];result=dict(pairs)
        if len(result)!=len(pairs):raise ValueError('duplicate key')
        return result
    if kind=='list':return [decode(x) for x in value]
    if kind=='tuple':return tuple(decode(x) for x in value)
    if kind=='set':return set(decode(x) for x in value)
    raise ValueError('unknown checkpoint type')


def digest(body):return hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def implementation():
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob('*.py'))}


def checkpoint(e):
    if type(e) is not CyclingPlanRecoveryEngine:raise ValueError('complete checkpoint supports current recovery engine only')
    static=set('reduction_references role_policy thesis_registry config config_sha256 core boundary execution exits costs requested purpose equity minimum_quantity minimum_notional max_age_ms model orders zones'.split())
    if set(vars(e))!=STATE|static:raise ValueError('engine fields changed; checkpoint schema update required')
    init=dict(config=e.config,lower=e.core[1],upper=e.core[-1],execution=e.execution,exits=e.exits,
        costs=e.costs,requested=e.requested,purpose=e.purpose,starting_equity=e.equity,
        minimum_quantity=e.minimum_quantity,minimum_notional=e.minimum_notional,max_age_ms=e.max_age_ms,
        initial_time_ms=e.journal[0]['time_ms'],role_policy=e.role_policy,reduction_references=e.reduction_references)
    body=dict(version='cycling-complete-1',implementation=implementation(),constructor=encode(init),
        evidence=encode(list(e.thesis_registry._records.values())),state=encode({k:getattr(e,k) for k in STATE}),
        controller=e.orders.checkpoint())
    return dict(body=body,sha256=digest(body))


def restore(payload):
    body=payload['body']
    if payload.get('sha256')!=digest(body) or body.get('version')!='cycling-complete-1':
        raise ValueError('invalid complete checkpoint checksum/version')
    if body['implementation']!=implementation():raise ValueError('implementation changed; explicit migration required')
    init=decode(body['constructor'])
    e=CyclingPlanRecoveryEngine(thesis_registry=ThesisEvidenceRegistry(decode(body['evidence'])),**init)
    state=decode(body['state'])
    if set(state)!=STATE:raise ValueError('incomplete/unknown engine state')
    controller=CyclingOrders.restore(body['controller'])
    for k,v in state.items():setattr(e,k,v)
    e.orders=controller;e.model=controller.model
    if type(e.clock) is not int or e.clock<init['initial_time_ms']:raise ValueError('invalid event clock')
    if e.last is not None:
        if not isinstance(e.last,Bar) or e.last.received_ms>e.clock:raise ValueError('invalid last bar')
        if e.previous!={k:e._geometry(z,e.last) for k,z in e.zones.items()}:raise ValueError('geometry/history mismatch')
        if e.reference_previous_close!=e.last.close:raise ValueError('reference history mismatch')
    if type(e.growth) is not int or e.growth!=len(e.grown_orders):raise ValueError('growth mismatch')
    filled_increases={o.id for o in e.orders.orders.values() if o.kind=='increase' and o.filled>0}
    if e.grown_orders!=filled_increases:raise ValueError('growth/fill mismatch')
    if set(e.submitted)!=set(e.orders.orders) or any(type(t) is not int or t>e.clock for t in e.submitted.values()):
        raise ValueError('order submission mismatch')
    if e.pending_half is not None and (e.model.reduction is None or e.pending_half!=e.model.reduction.event_id):
        raise ValueError('pending reduction mismatch')
    if not e.retired_references <= {r.id for r in e.reduction_references}:raise ValueError('unknown retired reference')
    if any(k not in e.model._reductions or v<=0 for k,v in e.planned_limits.items()):raise ValueError('unknown planned target')
    recorded_limits={r['event_id']:dec(r['limit_price']) for r in e.journal if r['action']=='planned_reduction_intent'}
    if recorded_limits!=e.planned_limits:raise ValueError('plan price/provenance mismatch')
    if e.orders.active and e.orders.active.kind=='limit_reduce':
        if e.planned_limits.get(e.orders.active.event_id)!=e.orders.active.price_cap:raise ValueError('active limit/plan mismatch')
    if not e.paused_plans<=set(e.planned_limits):raise ValueError('unknown paused plan')
    if e.order_handoff is not None:
        old=e.orders.orders.get(e.order_handoff['order_id'])
        if old is None or old.kind!='limit_reduce' or old.status not in ('cancel_pending','cancelled','filled'):
            raise ValueError('invalid pending handoff')
    if e.plan_recovery is not None:
        p=e.plan_recovery
        if p['event_id'] not in e.model._reductions or p['reference_id'] not in {r.id for r in e.reduction_references} or p['settled_ms']>e.clock:
            raise ValueError('invalid pending plan recovery')
    if e.main_status not in ('assessed','unassessed','uncertain'):raise ValueError('invalid main status')
    if e.main_evidence_ids:e.thesis_registry.resolve(e.main_evidence_ids,observed_ms=e.clock)
    return e


def save(e,path):
    path=Path(path);payload=checkpoint(e);restore(payload)
    path.parent.mkdir(parents=True,exist_ok=True);temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as f:
            temporary=Path(f.name);json.dump(payload,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
        os.replace(temporary,path)
        fd=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if temporary is not None and temporary.exists():temporary.unlink()
