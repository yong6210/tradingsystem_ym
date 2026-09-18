"""Bounded append-only custody acknowledgements tied to audited work receipts.

Only this new opt-in collector uses the registry. Its initial external anchor
permits linked extensions; a latest external anchor detects rollback to an older
prefix. Unregistered journal custody is preserved and rejected, never adopted.
"""
from copy import deepcopy
from pathlib import Path
import re

from .durable_capture_log import JournalError, ZERO, decoded, digest, encoded, file_hash, integer, keys, lock_directory, sync_directory
from .retained_sealed_journal import implementations as journal_implementations
from .sealed_segment_handoff import certificate, sha

MAX_CUSTODY_EVENTS = 1 + 8 + 62
MAX_CUSTODY_EVENT_BYTES = 512*1024
MAX_CUSTODY_LEDGER_BYTES = 16*1024**2


def implementations():
    return journal_implementations() | {n:file_hash(Path(__file__).parent/n) for n in (
        'collector_custody_ledger.py', 'retained_feed_collector.py',
        'retained_feed_pipeline.py', 'recover_retained_pipeline.py', 'recovery_custody_journal.py')}


def check_handle(value):
    keys(value, 'policy_sha256 metadata_sha256 checkpoint custody_anchors')
    digest(value['policy_sha256']); digest(value['metadata_sha256'])
    keys(value['checkpoint'], 'sequence record_sha256')
    integer(value['checkpoint']['sequence']); digest(value['checkpoint']['record_sha256'])
    if type(value['custody_anchors']) is not dict or len(value['custody_anchors']) > 1024:
        raise JournalError('custody anchors bound')
    for name, anchor in value['custody_anchors'].items():
        if type(name) is not str or not re.fullmatch(r'segment-[0-9]{7}\.jsonl', name):
            raise JournalError('custody source filename')
        digest(anchor)


def reduce_custody_events(events, budget):
    model = dict(epochs=[], retained={})
    for number, event in enumerate(events):
        kind, payload = event['kind'], event['payload']
        if number == 0:
            keys(payload, 'version root budget implementations')
            if (kind != 'START' or type(payload['version']) is not int or payload['version'] != 1 or
                    payload['root'] != str(budget.root) or payload['budget'] != budget.contract or
                    payload['implementations'] != implementations()):
                raise JournalError('custody storage or implementation binding')
            continue
        if kind == 'EPOCH':
            keys(payload, 'channel handles')
            if integer(payload['channel']) != len(model['epochs']) or len(model['epochs']) >= 8:
                raise JournalError('custody epoch sequence or bound')
            keys(payload['handles'], 'raw audit_log')
            for handle in payload['handles'].values():
                check_handle(handle)
                if handle['custody_anchors'] or handle['checkpoint']['sequence'] != 0:
                    raise JournalError('custody epoch must precede recording')
            model['epochs'].append(deepcopy(payload['handles']))
        elif kind == 'RETAIN':
            keys(payload, 'unit channel work_anchor audit_receipt handles names')
            unit = integer(payload['unit']); channel = integer(payload['channel'])
            if unit >= 62 or unit in model['retained'] or channel >= len(model['epochs']):
                raise JournalError('custody unit duplicate or bound')
            keys(payload['work_anchor'], 'sequence event_sha256')
            integer(payload['work_anchor']['sequence']); digest(payload['work_anchor']['event_sha256'])
            keys(payload['audit_receipt'], 'revision checkpoint_sha256')
            integer(payload['audit_receipt']['revision'], 1); digest(payload['audit_receipt']['checkpoint_sha256'])
            keys(payload['handles'], 'raw audit_log'); keys(payload['names'], 'raw audit_log')
            if not any(payload['names'].values()): raise JournalError('empty custody retention')
            for kind in ('raw', 'audit_log'):
                before = model['epochs'][channel][kind]; after = payload['handles'][kind]
                check_handle(after)
                names = payload['names'][kind]
                if (type(names) is not list or len(names) > (16 if kind == 'raw' else 1) or
                        any(type(n) is not str for n in names) or len(set(names)) != len(names)):
                    raise JournalError('custody unit source bound')
                if (any(after[k] != before[k] for k in ('policy_sha256', 'metadata_sha256')) or
                        after['checkpoint']['sequence'] < before['checkpoint']['sequence'] or
                        any(after['custody_anchors'].get(k) != v for k,v in before['custody_anchors'].items()) or
                        set(after['custody_anchors']) - set(before['custody_anchors']) != set(names)):
                    raise JournalError('custody handle extension differs')
            model['epochs'][channel] = deepcopy(payload['handles'])
            model['retained'][unit] = deepcopy(payload)
        else: raise JournalError('unknown custody event')
    return model


def validate_work(registry, ledger):
    """Every deletion authority must follow this exact unit's durable AUDIT."""
    if len(registry.model['epochs']) != len(ledger.model['epochs']):
        raise JournalError('custody and work epoch sets differ')
    for channel, handles in enumerate(registry.model['epochs']):
        contract = ledger.model['epochs'][channel]['contract']
        for kind, key in [('raw','raw_initial'), ('audit_log','audit_initial')]:
            if handles[kind]['metadata_sha256'] != contract[key]['metadata_sha256']:
                raise JournalError('custody journal identity differs from work')
    for unit_id, entry in registry.model['retained'].items():
        if unit_id >= len(ledger.model['units']): raise JournalError('custody unadmitted unit')
        unit = ledger.model['units'][unit_id]; anchor = entry['work_anchor']
        if (unit['channel'] != entry['channel'] or unit['receipt'] != entry['audit_receipt'] or
                anchor['sequence'] >= len(ledger.events) or
                ledger.events[anchor['sequence']]['event_sha256'] != anchor['event_sha256'] or
                not any(e['kind'] == 'AUDIT' and e['payload'] == dict(unit=unit_id, receipt=entry['audit_receipt'])
                        for e in ledger.events[:anchor['sequence']+1])):
            raise JournalError('custody lacks matching durable audit receipt')
        for kind, key in [('raw','raw_tickets'), ('audit_log','audit_tickets')]:
            permitted = {certificate(t.encode())['segment']['name'] for t in unit[key]}
            if not set(entry['names'][kind]) <= permitted:
                raise JournalError('custody source outside audited unit')


class CustodyLedger:
    def __init__(self, directory, budget, hook):
        self.budget = budget; self.directory = budget.path(directory); self.hook = hook
        self.events = []; self.bytes = 0; self.lock = None; self.closed = False

    @classmethod
    def create(cls, directory, *, budget, hook=lambda stage: None):
        obj = cls(directory, budget, hook)
        try:
            with budget.mutation():
                obj.directory.mkdir(); obj.lock = lock_directory(obj.directory); sync_directory(obj.directory.parent)
                obj.append('START', dict(version=1, root=str(budget.root), budget=budget.contract,
                    implementations=implementations()))
            return obj
        except BaseException:
            obj.close(); raise

    def anchor(self):
        if not self.events: raise JournalError('ledger has no durable receipt')
        last = self.events[-1]
        return dict(sequence=last['sequence'], event_sha256=last['event_sha256'])

    def append(self, kind, payload):
        if self.closed: raise JournalError('ledger closed')
        with self.budget.mutation():
            number = len(self.events)
            body = dict(version=1, sequence=number, previous_event_sha256=self.events[-1]['event_sha256'] if number else ZERO,
                        kind=kind, payload=payload)
            event = decoded(encoded(body | dict(event_sha256=sha(encoded(body)))))
            raw = encoded(event)
            if number>=MAX_CUSTODY_EVENTS or len(raw)>MAX_CUSTODY_EVENT_BYTES or self.bytes+len(raw)>MAX_CUSTODY_LEDGER_BYTES:
                raise JournalError('custody ledger bound')
            model = reduce_custody_events(self.events+[event], self.budget)
            target = self.directory/f'event-{number:06d}.json'
            if target.exists(): raise JournalError('ledger event would overwrite existing evidence')
            def guard(stage): self.hook(kind+':'+stage)
            self.budget.atomic_json(target, event, guard)
            self.events.append(event); self.bytes += len(raw); self.model = model
            self.hook(kind+':acknowledged')
            return self.anchor()

    @classmethod
    def resume(cls, directory, *, budget, anchor, hook=lambda stage: None):
        obj = cls(directory, budget, hook)
        try:
            with budget.mutation():
                obj.lock = lock_directory(obj.directory)
                keys(anchor, 'sequence event_sha256'); integer(anchor['sequence']); digest(anchor['event_sha256'])
                paths = sorted(obj.directory.iterdir())
                if len(paths)>MAX_CUSTODY_EVENTS*3: raise JournalError('ledger file inventory bound')
                files = []
                for path in paths:
                    if not path.is_file() or path.resolve()!=path: raise JournalError('nonregular ledger file')
                    if re.fullmatch(r'event-[0-9]{6}\.json', path.name): files.append(path)
                    elif path.name != '.writer.lock' and not (path.name.startswith('.') and path.name.endswith('.tmp')):
                        raise JournalError('unknown ledger file')
                for number, path in enumerate(files):
                    if path.name != f'event-{number:06d}.json': raise JournalError('ledger event gap')
                    with path.open('rb') as f: raw = f.read(MAX_CUSTODY_EVENT_BYTES+1)
                    if len(raw)>MAX_CUSTODY_EVENT_BYTES: raise JournalError('ledger event size bound')
                    obj.bytes += len(raw)
                    if number>=MAX_CUSTODY_EVENTS or obj.bytes>MAX_CUSTODY_LEDGER_BYTES: raise JournalError('ledger total bound')
                    event = decoded(raw)
                    keys(event, 'version sequence previous_event_sha256 kind payload event_sha256')
                    if (type(event['version']) is not int or event['version']!=1 or integer(event['sequence'])!=number or
                            event['previous_event_sha256']!=(obj.events[-1]['event_sha256'] if number else ZERO) or
                            digest(event['event_sha256'])!=sha(encoded({k:v for k,v in event.items() if k!='event_sha256'}))):
                        raise JournalError('ledger chain or checksum differs')
                    obj.events.append(event)
                if not obj.events or anchor['sequence']>=len(obj.events) or obj.events[anchor['sequence']]['event_sha256']!=anchor['event_sha256']:
                    raise JournalError('ledger rollback or external anchor mismatch')
                obj.model = reduce_custody_events(obj.events, budget)
                # A renamed event may have lost its acknowledgement. Reestablish
                # file+directory fences before allowing it to authorize work.
                import os
                for path in files:
                    with path.open('rb') as f: os.fsync(f.fileno())
                sync_directory(obj.directory)
            return obj
        except BaseException:
            obj.close(); raise

    def close(self):
        if self.lock is not None: self.lock.close(); self.lock = None
        self.closed = True
