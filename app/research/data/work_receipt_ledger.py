"""Bounded immutable work-admission/receipt events under one run storage owner.

Recovery requires an externally retained event receipt. Hashes detect corruption,
not adversarial rollback of every artifact beyond the latest external anchor.
"""
from pathlib import Path
import re
import time

from .archive_segment_reader import cursor_dict, restore_cursor
from .background_segment_archive import advance_cursor, ArchiveLimits
from .durable_capture_log import JournalError, ZERO, decoded, digest, encoded, file_hash, integer, keys, lock_directory, sync_directory
from .incremental_feed_audit import make_contract, IMPLEMENTATIONS
from .sealed_feed_pipeline import PipelineLimits
from .sealed_segment_handoff import certificate, sha

MAX_EVENTS = 256
MAX_EVENT_BYTES = 512*1024
MAX_LEDGER_BYTES = 16*1024**2
SOURCE_NAMES = tuple(sorted(set(IMPLEMENTATIONS + (
    'work_receipt_ledger.py','durable_sealed_pipeline.py','recover_sealed_pipeline.py','parent_bound_worker.py',
    'sealed_feed_pipeline.py','pipelined_feed_collector.py','incremental_audit_protocol.py',
    'incremental_audit_worker.py','background_incremental_audit.py','sealed_archive_worker.py'))))


def implementation_hashes():
    return {p:file_hash(Path(__file__).parent/p) for p in SOURCE_NAMES}


def receipt(value):
    keys(value, 'revision checkpoint_sha256')
    integer(value['revision']); digest(value['checkpoint_sha256'])
    return value


def path_name(value):
    if (type(value) is not str or not value or len(value)>4096 or Path(value).is_absolute() or
            '..' in Path(value).parts or str(Path(value)) != value or value == '.'):
        raise JournalError('ledger relative directory required')
    return value


def reduce_events(events, budget):
    """Pure strict state machine; no dynamic imports, no filesystem mutation."""
    model = dict(epochs=[], units=[], complete=False, recoveries=0)
    for number, event in enumerate(events):
        kind, p = event['kind'], event['payload']
        if number == 0:
            if kind != 'START': raise JournalError('ledger missing START')
            keys(p, 'version root budget pipeline_limits worker_limits implementations')
            if (type(p['version']) is not int or p['version'] != 1 or p['root'] != str(budget.root) or
                    p['budget'] != budget.contract or p['implementations'] != implementation_hashes()):
                raise JournalError('ledger storage or implementation binding')
            PipelineLimits(**p['pipeline_limits']); ArchiveLimits(**p['worker_limits'])
            model['contract'] = p
            continue
        limits = model['contract']['pipeline_limits']
        if kind == 'RECOVERY':
            keys(p, 'attempt')
            if integer(p['attempt'], 1) != model['recoveries']+1 or p['attempt'] > 16:
                raise JournalError('recovery attempt bound or sequence')
            model['recoveries'] += 1
            continue
        if model['complete']: raise JournalError('event after complete ledger')
        if kind == 'EPOCH':
            keys(p, 'index directory contract initial_receipt')
            if integer(p['index']) != len(model['epochs']) or len(model['epochs']) >= limits['max_epochs']:
                raise JournalError('epoch admission sequence or bound')
            directory = path_name(p['directory'])
            if any(c['directory'] == directory for c in model['epochs']): raise JournalError('duplicate epoch directory')
            contract = p['contract']
            raw, audit = restore_cursor(contract['raw_initial']), restore_cursor(contract['audit_initial'])
            expected = make_contract(raw, audit, **{k:contract[k] for k in ('window_start_ns','window_end_ns','clock_domain','max_intervals')})
            if contract != expected or raw.root != budget.root or raw.run_id != budget.contract['run_id']:
                raise JournalError('epoch replay contract differs')
            if receipt(p['initial_receipt'])['revision'] != 0: raise JournalError('epoch must start at revision zero')
            model['epochs'].append(dict(p, receipt=p['initial_receipt'], unit_ids=[], done=0, closed=False, final=False,
                raw_cursor=cursor_dict(raw), audit_cursor=cursor_dict(audit)))
        elif kind == 'UNIT':
            keys(p, 'index channel raw_tickets audit_tickets')
            if integer(p['index']) != len(model['units']) or len(model['units']) >= limits['max_units']:
                raise JournalError('unit admission sequence or bound')
            c = model['epochs'][integer(p['channel'])]
            if c['closed'] or c['final']: raise JournalError('unit after epoch close')
            if type(p['raw_tickets']) is not list or type(p['audit_tickets']) is not list or not 1<=len(p['raw_tickets'])<=16 or len(p['audit_tickets'])!=1:
                raise JournalError('unit ticket bound')
            raw, audit = restore_cursor(c['raw_cursor']), restore_cursor(c['audit_cursor'])
            for ticket in p['raw_tickets']: raw = advance_cursor(certificate(ticket.encode()), raw)
            audit = advance_cursor(certificate(p['audit_tickets'][0].encode()), audit)
            u = dict(p, raw_cursor=cursor_dict(raw), audit_cursor=cursor_dict(audit), receipt=None)
            model['units'].append(u); c['unit_ids'].append(p['index'])
            c.update(raw_cursor=u['raw_cursor'], audit_cursor=u['audit_cursor'])
        elif kind == 'AUDIT':
            keys(p, 'unit receipt')
            u = model['units'][integer(p['unit'])]; c = model['epochs'][u['channel']]
            if c['final'] or c['done']>=len(c['unit_ids']) or c['unit_ids'][c['done']]!=p['unit']:
                raise JournalError('duplicate, skipped or reordered audit receipt')
            if receipt(p['receipt'])['revision'] != c['receipt']['revision']+1:
                raise JournalError('audit receipt revision differs')
            u['receipt'] = p['receipt']; c['receipt'] = p['receipt']; c['done'] += 1
        elif kind == 'CLOSED':
            keys(p, 'channel raw_cursor audit_cursor')
            c = model['epochs'][integer(p['channel'])]
            if c['closed'] or not c['unit_ids'] or p['raw_cursor']!=c['raw_cursor'] or p['audit_cursor']!=c['audit_cursor']:
                raise JournalError('closed epoch terminal anchors differ')
            c['closed'] = True
        elif kind == 'FINAL':
            keys(p, 'channel receipt')
            c = model['epochs'][integer(p['channel'])]
            if not c['closed'] or c['final'] or c['done']!=len(c['unit_ids']):
                raise JournalError('final receipt before complete closed epoch')
            if receipt(p['receipt'])['revision'] != c['receipt']['revision']+1:
                raise JournalError('final receipt revision differs')
            c['receipt'] = p['receipt']; c['final'] = True
        elif kind == 'COMPLETE':
            keys(p, '')
            if not model['epochs'] or not all(c['final'] for c in model['epochs']):
                raise JournalError('complete before all epoch finals')
            model['complete'] = True
        else: raise JournalError('unknown ledger event')
    return model


class WorkReceiptLedger:
    def __init__(self, directory, budget, hook):
        self.budget = budget; self.directory = budget.path(directory); self.hook = hook
        self.events = []; self.bytes = 0; self.lock = None; self.closed = False

    @classmethod
    def create(cls, directory, *, budget, limits, worker_limits, hook=lambda stage: None):
        obj = cls(directory, budget, hook)
        try:
            with budget.mutation():
                obj.directory.mkdir(); obj.lock = lock_directory(obj.directory); sync_directory(obj.directory.parent)
                obj.append('START', dict(version=1, root=str(budget.root), budget=budget.contract,
                    pipeline_limits=limits, worker_limits=worker_limits, implementations=implementation_hashes()))
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
            if number>=MAX_EVENTS or len(raw)>MAX_EVENT_BYTES or self.bytes+len(raw)>MAX_LEDGER_BYTES:
                raise JournalError('work ledger bound')
            model = reduce_events(self.events+[event], self.budget)
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
                if len(paths)>MAX_EVENTS*3: raise JournalError('ledger file inventory bound')
                files = []
                for path in paths:
                    if not path.is_file() or path.resolve()!=path: raise JournalError('nonregular ledger file')
                    if re.fullmatch(r'event-[0-9]{6}\.json', path.name): files.append(path)
                    elif path.name != '.writer.lock' and not (path.name.startswith('.') and path.name.endswith('.tmp')):
                        raise JournalError('unknown ledger file')
                for number, path in enumerate(files):
                    if path.name != f'event-{number:06d}.json': raise JournalError('ledger event gap')
                    with path.open('rb') as f: raw = f.read(MAX_EVENT_BYTES+1)
                    if len(raw)>MAX_EVENT_BYTES: raise JournalError('ledger event size bound')
                    obj.bytes += len(raw)
                    if number>=MAX_EVENTS or obj.bytes>MAX_LEDGER_BYTES: raise JournalError('ledger total bound')
                    event = decoded(raw)
                    keys(event, 'version sequence previous_event_sha256 kind payload event_sha256')
                    if (type(event['version']) is not int or event['version']!=1 or integer(event['sequence'])!=number or
                            event['previous_event_sha256']!=(obj.events[-1]['event_sha256'] if number else ZERO) or
                            digest(event['event_sha256'])!=sha(encoded({k:v for k,v in event.items() if k!='event_sha256'}))):
                        raise JournalError('ledger chain or checksum differs')
                    obj.events.append(event)
                if not obj.events or anchor['sequence']>=len(obj.events) or obj.events[anchor['sequence']]['event_sha256']!=anchor['event_sha256']:
                    raise JournalError('ledger rollback or external anchor mismatch')
                obj.model = reduce_events(obj.events, budget)
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
