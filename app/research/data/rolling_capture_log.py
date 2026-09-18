"""Finite shard admission/result chain; completed evidence is never overwritten."""
from pathlib import Path
import os
import re

from .durable_capture_log import JournalError, ZERO, decoded, digest, encoded, integer, keys, sync_directory
from .sealed_segment_handoff import sha

MAX_SHARDS = 16
MAX_EVENTS = 2 + 3*MAX_SHARDS
MAX_EVENT_BYTES = 128*1024
MAX_BYTES = 4*1024**2


def reduce_events(events):
    state = dict(shards=[], finish=None)
    for number,event in enumerate(events):
        kind,p = event['kind'],event['payload']
        if number == 0:
            if kind != 'INIT': raise JournalError('rolling INIT required')
            state['plan'] = p
            continue
        if state['finish'] is not None: raise JournalError('rolling event after finish')
        if kind == 'BEGIN':
            keys(p,'index admitted_ns deadline_ns')
            index=integer(p['index']); start=integer(p['admitted_ns']); end=integer(p['deadline_ns'])
            plan=state['plan']
            if index != len(state['shards']) or index >= MAX_SHARDS:
                raise JournalError('rolling shard sequence or bound')
            if state['shards'] and (state['shards'][-1]['end'] is None or
                    state['shards'][-1]['end']['outcome'] != 'PLANNED_ROLLOVER'):
                raise JournalError('rolling before clean completed shard')
            if (not plan['window_start_ns'] <= start < plan['window_end_ns'] or
                    end != min(start+plan['rotation_ns'],plan['window_end_ns'])):
                raise JournalError('rolling shard deadline differs')
            state['shards'].append(dict(p,handle=None,end=None))
        elif kind == 'READY':
            keys(p,'index handle');index=integer(p['index'])
            if index >= len(state['shards']): raise JournalError('unadmitted shard')
            shard=state['shards'][index]
            if shard['handle'] is not None or shard['end'] is not None:
                raise JournalError('duplicate or closed shard readiness')
            keys(p['handle'],'work_anchor custody_anchor')
            for anchor in p['handle'].values():
                keys(anchor,'sequence event_sha256');digest(anchor['event_sha256'])
                if integer(anchor['sequence']) != 0: raise JournalError('ready must precede epoch and network')
            shard['handle']=p['handle']
        elif kind == 'END':
            keys(p,'index outcome result_file result_sha256')
            index=integer(p['index']);digest(p['result_sha256'])
            if index >= len(state['shards']): raise JournalError('unadmitted shard end')
            shard=state['shards'][index]
            if (type(p['result_file']) is not str or
                    not re.fullmatch(r'result-[0-9]{2}-[0-9a-f]{32}\.json',p['result_file']) or
                    shard['end'] is not None or p['outcome'] not in (
                        'PLANNED_ROLLOVER','ORIGINAL_DEADLINE','FATAL_FAILURE','TRANSPORT_FAILURE',
                        'PROCESS_INTERRUPTED','ABANDONED_BEFORE_READY')):
                raise JournalError('rolling result identity or outcome')
            if p['outcome'] not in ('ABANDONED_BEFORE_READY','PROCESS_INTERRUPTED') and shard['handle'] is None:
                raise JournalError('shard result before ready')
            shard['end']=p
        elif kind == 'FINISH':
            keys(p,'reason')
            if any(s['end'] is None for s in state['shards']) or p['reason'] not in (
                    'ORIGINAL_DEADLINE','FATAL_FAILURE','TRANSPORT_FAILURE','PROCESS_INTERRUPTED','SHARD_LIMIT'):
                raise JournalError('rolling finish before resolved shard or unknown reason')
            state['finish']=p['reason']
        else: raise JournalError('unknown rolling event')
    return state


class RollingCaptureLog:
    def __init__(self,budget,hook):
        self.budget=budget;self.directory=budget.root/'rolling-log';self.hook=hook
        self.events=[];self.bytes=0

    @classmethod
    def create(cls,budget,plan,hook=lambda stage:None):
        obj=cls(budget,hook)
        with budget.mutation():
            obj.directory.mkdir();sync_directory(budget.root);obj.append('INIT',plan)
        return obj

    def append(self,kind,payload):
        with self.budget.mutation():
            number=len(self.events)
            body=dict(version=1,sequence=number,previous_sha256=self.events[-1]['sha256'] if number else ZERO,
                      kind=kind,payload=payload)
            event=decoded(encoded(body|dict(sha256=sha(encoded(body)))))
            raw=encoded(event)
            if number>=MAX_EVENTS or len(raw)>MAX_EVENT_BYTES or self.bytes+len(raw)>MAX_BYTES:
                raise JournalError('rolling event byte or count bound')
            state=reduce_events(self.events+[event]);path=self.directory/f'event-{number:06d}.json'
            if path.exists(): raise JournalError('rolling event would overwrite evidence')
            self.budget.atomic_json(path,event,lambda stage:self.hook('rolling:'+kind+':'+stage))
            self.events.append(event);self.bytes+=len(raw);self.state=state
            self.hook('rolling:'+kind+':acknowledged')
            return self.anchor()

    def anchor(self):
        return dict(sequence=self.events[-1]['sequence'],event_sha256=self.events[-1]['sha256'])

    @classmethod
    def resume(cls,budget,anchor,hook=lambda stage:None):
        obj=cls(budget,hook)
        keys(anchor,'sequence event_sha256');integer(anchor['sequence']);digest(anchor['event_sha256'])
        paths=sorted(obj.directory.iterdir())
        if len(paths)>MAX_EVENTS*3: raise JournalError('rolling inventory bound')
        files=[]
        for path in paths:
            if not path.is_file() or path.resolve()!=path: raise JournalError('nonregular rolling event')
            if re.fullmatch(r'event-[0-9]{6}\.json',path.name):files.append(path)
            elif not (path.name.startswith('.') and path.name.endswith('.tmp')):raise JournalError('unknown rolling file')
        for number,path in enumerate(files):
            if path.name!=f'event-{number:06d}.json':raise JournalError('rolling event gap')
            with path.open('rb') as f:raw=f.read(MAX_EVENT_BYTES+1)
            obj.bytes+=len(raw)
            if number>=MAX_EVENTS or len(raw)>MAX_EVENT_BYTES or obj.bytes>MAX_BYTES:raise JournalError('rolling ledger bound')
            row=decoded(raw);keys(row,'version sequence previous_sha256 kind payload sha256')
            if (type(row['version']) is not int or row['version']!=1 or integer(row['sequence'])!=number or
                    row['previous_sha256']!=(obj.events[-1]['sha256'] if number else ZERO) or
                    digest(row['sha256'])!=sha(encoded({k:v for k,v in row.items() if k!='sha256'}))):
                raise JournalError('rolling event chain or checksum')
            obj.events.append(row)
        if anchor['sequence']>=len(obj.events) or obj.events[anchor['sequence']]['sha256']!=anchor['event_sha256']:
            raise JournalError('rolling rollback or external anchor mismatch')
        obj.state=reduce_events(obj.events)
        for path in files:
            with path.open('rb') as f:os.fsync(f.fileno())
        sync_directory(obj.directory)
        return obj
