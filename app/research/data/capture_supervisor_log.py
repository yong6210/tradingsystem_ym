"""Bounded immutable supervisor events and separately retained work receipts.

Stored outside each capture namespace, on the same owned local filesystem.
This is not an off-host backup or protection from rollback of every copy.
"""
import os
import re

from .durable_capture_log import JournalError, ZERO, decoded, encoded, integer, digest, keys, sync_directory
from .sealed_segment_handoff import sha

MAX_EVENTS = 4096
MAX_EVENT_BYTES = 128*1024
MAX_BYTES = 32*1024**2


def reduce_events(events):
    state = dict(attempts=[], finish=None)
    for i,e in enumerate(events):
        k,p = e['kind'], e['payload']
        if i == 0:
            if k != 'INIT': raise JournalError('supervisor INIT required')
            state['plan'] = p
            continue
        if state['finish'] is not None: raise JournalError('supervisor already finished')
        if k == 'ATTEMPT':
            keys(p, 'index admitted_ns wake_ns')
            index=integer(p['index']); integer(p['admitted_ns']); integer(p['wake_ns'])
            if index!=len(state['attempts']) or index>len(state['plan']['retry_delays_seconds']):
                raise JournalError('attempt budget or sequence')
            if state['attempts'] and state['attempts'][-1]['end'] is None:
                raise JournalError('overlapping attempts')
            minimum = p['admitted_ns'] + (0 if index==0 else state['plan']['retry_delays_seconds'][index-1]*10**9)
            if p['wake_ns']!=minimum or p['wake_ns']>=state['plan']['window_end_ns']:
                raise JournalError('retry delay or original deadline differs')
            state['attempts'].append(dict(p, anchor=None, end=None))
        elif k == 'RECEIPT':
            keys(p, 'index anchor')
            a=state['attempts'][integer(p['index'])]
            keys(p['anchor'], 'sequence event_sha256'); digest(p['anchor']['event_sha256'])
            sequence=integer(p['anchor']['sequence'])
            if a['end'] is not None or sequence!=(0 if a['anchor'] is None else a['anchor']['sequence']+1):
                raise JournalError('receipt reorder or closed attempt')
            a['anchor']=p['anchor']
        elif k == 'END':
            keys(p, 'index outcome result_file result_sha256')
            a=state['attempts'][integer(p['index'])]; digest(p['result_sha256'])
            if type(p['result_file']) is not str or not re.fullmatch(r'result-[0-9]{2}-[0-9a-f]{32}\.json',p['result_file']):
                raise JournalError('result filename differs')
            if a['end'] is not None or p['outcome'] not in (
                    'ORIGINAL_DEADLINE','TRANSPORT_FAILURE','FATAL_FAILURE','PROCESS_INTERRUPTED','ABANDONED_BEFORE_RECEIPT'):
                raise JournalError('attempt end differs')
            a['end']=p
        elif k == 'FINISH':
            keys(p, 'reason')
            if any(a['end'] is None for a in state['attempts']) or p['reason'] not in (
                    'ORIGINAL_DEADLINE','FATAL_FAILURE','RETRY_EXHAUSTED','RETRY_WOULD_REACH_DEADLINE'):
                raise JournalError('finish before closed attempts or unknown reason')
            state['finish']=p['reason']
        else: raise JournalError('unknown supervisor event')
    return state


class CaptureSupervisorLog:
    def __init__(self, budget, *, hook=lambda stage: None):
        self.budget=budget; self.directory=budget.root/'receipts'; self.hook=hook
        self.events=[]; self.bytes=0

    @classmethod
    def create(cls,budget,plan,*,hook=lambda stage:None):
        obj=cls(budget,hook=hook)
        with budget.mutation():
            obj.directory.mkdir(); sync_directory(budget.root)
            obj.append('INIT',plan)
        return obj

    def append(self,kind,payload):
        with self.budget.mutation():
            n=len(self.events)
            body=dict(version=1,sequence=n,previous_sha256=self.events[-1]['sha256'] if n else ZERO,
                      kind=kind,payload=payload)
            event=decoded(encoded(body | dict(sha256=sha(encoded(body)))))
            raw=encoded(event)
            if n>=MAX_EVENTS or len(raw)>MAX_EVENT_BYTES or self.bytes+len(raw)>MAX_BYTES:
                raise JournalError('supervisor event bound')
            state=reduce_events(self.events+[event])
            path=self.directory/f'event-{n:06d}.json'
            if path.exists(): raise JournalError('supervisor would overwrite evidence')
            self.budget.atomic_json(path,event,lambda stage:self.hook('supervisor:'+kind+':'+stage))
            self.events.append(event); self.bytes+=len(raw); self.state=state
            self.hook('supervisor:'+kind+':acknowledged')
            return self.anchor()

    def anchor(self):
        return dict(sequence=self.events[-1]['sequence'],event_sha256=self.events[-1]['sha256'])

    @classmethod
    def resume(cls,budget,anchor,*,hook=lambda stage:None):
        obj=cls(budget,hook=hook)
        keys(anchor,'sequence event_sha256'); integer(anchor['sequence']); digest(anchor['event_sha256'])
        entries=sorted(obj.directory.iterdir())
        if len(entries)>MAX_EVENTS*2: raise JournalError('supervisor inventory bound')
        paths=[]
        for p in entries:
            if not p.is_file() or p.resolve()!=p: raise JournalError('nonregular supervisor event')
            if re.fullmatch(r'event-[0-9]{6}\.json',p.name): paths.append(p)
            elif not (p.name.startswith('.') and p.name.endswith('.tmp')): raise JournalError('unknown supervisor file')
        for i,p in enumerate(paths):
            if p.name!=f'event-{i:06d}.json' or i>=MAX_EVENTS: raise JournalError('supervisor event gap or count')
            with p.open('rb') as f: raw=f.read(MAX_EVENT_BYTES+1)
            obj.bytes+=len(raw)
            if len(raw)>MAX_EVENT_BYTES or obj.bytes>MAX_BYTES: raise JournalError('supervisor byte bound')
            e=decoded(raw); keys(e,'version sequence previous_sha256 kind payload sha256')
            if (type(e['version']) is not int or e['version']!=1 or integer(e['sequence'])!=i or
                e['previous_sha256']!=(obj.events[-1]['sha256'] if i else ZERO) or
                digest(e['sha256'])!=sha(encoded({k:v for k,v in e.items() if k!='sha256'}))):
                raise JournalError('supervisor event checksum or chain')
            obj.events.append(e)
        if anchor['sequence']>=len(obj.events) or obj.events[anchor['sequence']]['sha256']!=anchor['event_sha256']:
            raise JournalError('supervisor rollback or external anchor mismatch')
        obj.state=reduce_events(obj.events)
        for p in paths:
            with p.open('rb') as f: os.fsync(f.fileno())
        sync_directory(obj.directory)
        return obj
