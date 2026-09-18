"""Opt-in journal with explicitly anchored raw/gzip custody while still writable.

A segment may retire only after a durable seal and verified registered archive.
The caller must stop raw-only consumers first. Collector/audit coordination and
metadata rotation are NOT provided by this journal component. All old formats
remain immutable; reopening this format requires its own explicit handle.
"""
from dataclasses import replace
import io
import os
from pathlib import Path
import re

from .archive_segment_reader import SegmentReader, cursor_dict, restore_cursor, segment_ref, validate_bytes
from .durable_capture_log import JournalError, ZERO, decoded, digest, encoded, file_hash, integer, keys, load_state, lock_directory, sync_directory
from .sealed_segment_handoff import SealedJournal, SealTicket, SegmentCursor, certificate, sha, MAX_SEGMENTS, MAX_SEAL_BYTES
from .segment_archive import SegmentArchive
from .work_receipt_ledger import implementation_hashes

MAX_CUSTODY_BYTES = 32768
MAX_RETIREMENT_BATCH = 16


def implementations():
    return implementation_hashes() | {'retained_sealed_journal.py': file_hash(Path(__file__))}


def mode(budget, directory, metadata_sha256):
    return dict(version=1, root=str(budget.root), journal=str(directory.relative_to(budget.root)),
                run_id=budget.contract['run_id'], metadata_sha256=metadata_sha256,
                mode='EXPLICIT_SEALED_RAW_GZIP_CUSTODY', implementations=implementations())


class RetainedSealedJournal(SealedJournal):
    def __init__(self, *args):
        super().__init__(*args)
        self.custody = self.directory/'custody'
        self.custody_anchors = {}
        self.mode_hash = None
        # Deleted raw filenames must never cause index reuse on restart.
        self.next_index = max(self.next_index, max((int(e['name'][8:15])+1 for e in self.entries), default=0))

    @classmethod
    def create(cls, directory, *, budget, run_id, **kwargs):
        obj = super().create(directory, budget=budget, run_id=run_id, **kwargs)
        try:
            with budget.mutation():
                obj.custody.mkdir()
                sync_directory(obj.directory)
                budget.atomic_json(obj.directory/'custody-policy.json',
                                   mode(budget, obj.directory, obj.cp['metadata_sha256']))
            obj.mode_hash = file_hash(obj.directory/'custody-policy.json')
            return obj
        except BaseException:
            obj.close()
            raise

    def handle(self):
        self._writable()
        return dict(policy_sha256=self.mode_hash, metadata_sha256=self.cp['metadata_sha256'],
                    checkpoint=dict(sequence=self.cp['last_sequence'], record_sha256=self.cp['last_record_sha256']),
                    custody_anchors=dict(self.custody_anchors))

    def _check_policy(self):
        path = self.budget.path(self.directory/'custody-policy.json')
        if (not path.is_file() or path.stat().st_size > MAX_CUSTODY_BYTES or
                file_hash(path) != self.mode_hash or
                decoded(path.read_bytes()) != mode(self.budget, self.directory, self.cp['metadata_sha256'])):
            raise JournalError('journal custody policy binding')
        inventory = list(self.custody.iterdir())
        if len(inventory) > MAX_SEGMENTS*6:
            raise JournalError('custody file inventory bound')
        names = {p.name for p in inventory if re.fullmatch(r'segment-[0-9]{7}\.jsonl\.json', p.name)}
        if names != {name+'.json' for name in self.custody_anchors}:
            raise JournalError('unanchored or missing custody registration')

    def _entry(self, name):
        found = [entry for entry in self.cp['segments'] if entry['name'] == name]
        if len(found) != 1:
            raise JournalError('custody source not committed exactly once')
        return found[0]

    def _load(self, name):
        path = self.budget.path(self.custody/(name+'.json'))
        if path.stat().st_size > MAX_CUSTODY_BYTES or file_hash(path) != self.custody_anchors[name]:
            raise JournalError('custody external anchor differs')
        value = decoded(path.read_bytes())
        keys(value, 'version policy_sha256 ref cursor descriptor_sha256')
        if type(value['version']) is not int or value['version'] != 1 or value['policy_sha256'] != self.mode_hash:
            raise JournalError('custody registration policy')
        row = certificate(value['ref']['certificate'].encode())
        if row['segment'] != self._entry(name) or row['segment']['name'] != name:
            raise JournalError('custody checkpoint entry differs')
        cursor = restore_cursor(value['cursor'])
        if (cursor.root != self.budget.root or cursor.journal != str(self.directory.relative_to(self.budget.root)) or
                cursor.run_id != self.meta['run_id'] or cursor.metadata_sha256 != self.cp['metadata_sha256']):
            raise JournalError('custody journal identity differs')
        seal = self.budget.path(self.seals/(name+'.seal.json'))
        if seal.read_bytes() != value['ref']['certificate'].encode():
            raise JournalError('custody durable seal differs')
        return value

    def _archive(self, value):
        ref = value['ref']
        if ref['archive'] is None:
            raise JournalError('custody requires explicit gzip')
        # SegmentReader validates path, descriptor, witness, gzip and raw chain.
        result = SegmentReader(budget=self.budget).read(ref, restore_cursor(value['cursor']))
        store = object.__new__(SegmentArchive)
        store.budget = self.budget
        store.directory = self.budget.path(self.budget.root/ref['archive']['directory'])
        descriptor = store._descriptor(ref['archive']['archive_id'])
        if file_hash(store.directory/(descriptor['archive_id']+'.json')) != value['descriptor_sha256']:
            raise JournalError('custody archive descriptor changed')
        store._sync_registered(descriptor)
        return result

    def _binding(self, name):
        return dict(custody_sha256=self.custody_anchors[name], source=name, **self._entry(name))

    def _state(self, name):
        source = self.budget.path(self.directory/name)
        intent = self.budget.path(self.custody/(name+'.intent.json'))
        done = self.budget.path(self.custody/(name+'.done.json'))
        expected = self._binding(name)
        for path in (intent, done):
            if path.exists() and (path.stat().st_size > 4096 or decoded(path.read_bytes()) != expected):
                raise JournalError('custody intent or done differs')
        if done.exists() and (not intent.exists() or source.exists()):
            raise JournalError('retired source reappeared or intent lost')
        if not source.exists() and not intent.exists():
            raise JournalError('missing raw without custody intent')
        if source.exists() and (source.stat().st_size != expected['bytes'] or file_hash(source) != expected['sha256']):
            raise JournalError('custody raw changed or has uncertain suffix')
        return source, intent, done

    def admit_archive(self, ticket, archive_ref, *, minimum_net_savings_bytes=1):
        """Registers one sealed archive; returns a handle, does not delete raw.

        Persist this handle before finish_retirement. Caller coordination must
        ensure no raw-only worker will read this segment after retirement.
        """
        self._writable(); integer(minimum_net_savings_bytes, 1); self._check_policy()
        row = certificate(ticket.certificate); name = row['segment']['name']
        if name in self.custody_anchors:
            raise JournalError('custody already registered')
        if (row['segment'] != self._entry(name) or name in self.dirty or
                (self.active is not None and Path(self.active.name).name == name)):
            raise JournalError('only immutable closed committed sources may retire')
        seal = self.budget.path(self.seals/(name+'.seal.json'))
        if not seal.is_file() or seal.read_bytes() != ticket.certificate:
            raise JournalError('durable seal required before custody')
        if archive_ref['certificate'] != ticket.certificate.decode() or archive_ref['archive'] is None:
            raise JournalError('archive reference differs from issued ticket')
        position = self.cp['segments'].index(row['segment'])
        previous_index = -1 if not position else int(self.cp['segments'][position-1]['name'][8:15])
        cursor = replace(self.initial_cursor(), sequence=row['first_sequence']-1,
                         record_sha256=row['previous_record_sha256'], segment_sha256=row['previous_segment_sha256'],
                         seal_sha256=row['previous_seal_sha256'], index=previous_index)
        source = SegmentReader(budget=self.budget).read(segment_ref(ticket), cursor)
        archive = archive_ref['archive']
        path = self.budget.path(self.budget.root/archive['directory']/(archive['archive_id']+'.json'))
        value = dict(version=1, policy_sha256=self.mode_hash, ref=decoded(encoded(archive_ref)),
                     cursor=cursor_dict(cursor), descriptor_sha256=file_hash(path))
        if self._archive(value).raw != source.raw:
            raise JournalError('archive and raw bytes differ')
        record_bytes = len(encoded(value))
        if record_bytes > MAX_CUSTODY_BYTES:
            raise JournalError('custody record bound')
        binding = dict(custody_sha256=ZERO, source=name, **row['segment'])
        added_bytes = record_bytes+2*len(encoded(binding))
        savings = row['segment']['bytes']-added_bytes
        decision = dict(admitted=savings >= minimum_net_savings_bytes, raw_bytes=row['segment']['bytes'],
                        added_metadata_bytes=added_bytes, normal_path_net_savings_bytes=savings,
                        source=name, raw_deletion_performed=False)
        if not decision['admitted']:
            return decision | dict(handle=self.handle())
        with self.budget.mutation():
            self.budget.check(added_bytes)
            target = self.custody/(name+'.json')
            self.budget.atomic_json(target, value, lambda s: self.hook('custody_register:'+s))
            self.custody_anchors[name] = file_hash(target)
        return decision | dict(handle=self.handle())

    def finish_retirement(self, *, names=None):
        """Finish at most 16 explicitly selected sources without yielding.

        A collector must submit just its ready batch, not rescan every old gzip
        on each seal. Defaulting to all is only allowed for small registrations.
        Full historical validation belongs to resume and explicit replay.
        """
        self._writable(); self._check_policy()
        targets = sorted(self.custody_anchors) if names is None else names
        if (type(targets) is not list or len(targets) > MAX_RETIREMENT_BATCH or
                any(type(name) is not str for name in targets) or len(set(targets)) != len(targets)):
            raise JournalError('retirement batch bound or duplicate sources')
        if any(name not in self.custody_anchors for name in targets):
            raise JournalError('retirement batch contains unregistered source')
        targets = sorted(targets)
        removed = 0
        with self.budget.mutation():
            if self.budget.snapshot()['reserved_bytes']:
                raise JournalError('pending workers prohibit active retirement')
            # Validate all admitted targets before changing any of them.
            for name in targets:
                if name in self.dirty or (self.active is not None and Path(self.active.name).name == name):
                    raise JournalError('active or dirty custody source')
                self._archive(self._load(name)); self._state(name)
            for name in targets:
                self._archive(self._load(name))
                source, intent, done = self._state(name)
                if done.exists():
                    for path in (intent, done):
                        with path.open('rb') as stream: os.fsync(stream.fileno())
                    sync_directory(self.custody)
                    continue
                if not intent.exists():
                    self.budget.atomic_json(intent, self._binding(name), lambda s: self.hook('custody_intent:'+s))
                with intent.open('rb') as stream: os.fsync(stream.fileno())
                sync_directory(self.custody)
                if source.exists():
                    self.hook('custody_before_unlink')
                    source.unlink(); self.budget._refresh(source)
                    removed += self._entry(name)['bytes']; self.total_bytes -= self._entry(name)['bytes']
                    self.hook('custody_after_unlink')
                sync_directory(self.directory)
                self.hook('custody_after_source_directory_fsync')
                self.budget.atomic_json(done, self._binding(name), lambda s: self.hook('custody_done:'+s))
            return dict(raw_bytes_removed_this_call=removed, registered_segments=len(self.custody_anchors),
                        journal_still_writable=True, live_collector_integrated=False)

    @classmethod
    def resume(cls, directory, *, budget, handle, hook=lambda stage: None):
        keys(handle, 'policy_sha256 metadata_sha256 checkpoint custody_anchors')
        keys(handle['checkpoint'], 'sequence record_sha256')
        saved_sequence = integer(handle['checkpoint']['sequence'])
        saved_hash = digest(handle['checkpoint']['record_sha256'])
        if not saved_sequence and saved_hash != ZERO:
            raise JournalError('empty checkpoint anchor differs')
        anchors = handle['custody_anchors']
        if type(anchors) is not dict or len(anchors) > MAX_SEGMENTS:
            raise JournalError('custody anchor bound')
        for name, value in anchors.items():
            if type(name) is not str or not re.fullmatch(r'segment-[0-9]{7}\.jsonl', name):
                raise JournalError('custody anchor filename')
            digest(value)
        directory = budget.path(directory); budget.reconcile()
        lock = lock_directory(directory); obj = None
        try:
            meta, cp = load_state(directory)
            if (meta['run_id'] != budget.contract['run_id'] or meta['max_total_bytes'] != budget.contract['max_bytes'] or
                    meta['min_free_bytes'] != budget.contract['min_free_bytes'] or
                    cp['metadata_sha256'] != handle['metadata_sha256'] or cp['last_sequence'] < saved_sequence):
                raise JournalError('mixed journal contract or checkpoint rollback')
            obj = cls(directory, lock, meta, cp, hook); obj.budget = budget
            obj.mode_hash = digest(handle['policy_sha256']); obj.custody_anchors = dict(anchors)
            obj._check_policy()
            if not obj.seals.is_dir() or not obj.custody.is_dir():
                raise JournalError('missing journal custody directories')
            if list(directory.glob('.checkpoint.json.*.tmp')):
                raise JournalError('uncertain checkpoint temporary requires inspection')
            cursor = obj.initial_cursor(); items = []; matched = saved_sequence == 0
            # One bounded segment at a time: no materialized raw copies and no
            # array containing a whole capture's records.
            for entry in cp['segments']:
                keys(entry, 'name bytes sha256')
                name = entry['name']
                if type(name) is not str or not re.fullmatch(r'segment-[0-9]{7}\.jsonl', name):
                    raise JournalError('mixed segment filename')
                if name in anchors:
                    value = obj._load(name); obj._state(name)
                    if value['cursor'] != cursor_dict(cursor):
                        raise JournalError('mixed custody cursor discontinuity')
                    verified = obj._archive(value)
                    row = certificate(value['ref']['certificate'].encode())
                else:
                    path = budget.path(directory/name)
                    if not path.is_file() or path.stat().st_size != integer(entry['bytes'], 1):
                        raise JournalError('unregistered raw missing or uncertain suffix')
                    if entry['bytes'] > meta['rotation_bytes']:
                        raise JournalError('mixed segment size bound')
                    raw = path.read_bytes()
                    stream = io.BytesIO(raw); header = decoded(stream.readline(4097)); last = None
                    for line in stream:
                        if len(line) > meta['max_record_bytes']:
                            raise JournalError('mixed record size bound')
                        last = decoded(line)
                    if last is None:
                        raise JournalError('empty committed segment')
                    body = dict(version=1, run_id=meta['run_id'], journal=cursor.journal,
                        metadata_sha256=cp['metadata_sha256'], segment=entry, first_sequence=cursor.sequence+1,
                        last_sequence=last['sequence'], previous_record_sha256=cursor.record_sha256,
                        last_record_sha256=last['sha256'], previous_segment_sha256=cursor.segment_sha256,
                        previous_seal_sha256=cursor.seal_sha256, epoch=header['epoch'],
                        max_record_bytes=meta['max_record_bytes'], checkpoint_sha256=sha(encoded(cp)))
                    row = body | dict(seal_sha256=sha(encoded(body)))
                    seal = budget.path(obj.seals/(name+'.seal.json'))
                    if seal.exists():
                        if seal.stat().st_size > MAX_SEAL_BYTES:
                            raise JournalError('mixed seal bound')
                        original = certificate(seal.read_bytes())
                        exclude = ('seal_sha256', 'checkpoint_sha256')
                        if {k:v for k,v in original.items() if k not in exclude} != {k:v for k,v in row.items() if k not in exclude}:
                            raise JournalError('mixed durable seal differs')
                        row = original
                    verified = validate_bytes(SealTicket(encoded(row)), cursor, raw)
                    with path.open('rb') as stream: os.fsync(stream.fileno())
                for record in verified.records():
                    if record['sequence'] == saved_sequence:
                        if record['sha256'] != saved_hash:
                            raise JournalError('mixed checkpoint anchor chain differs')
                        matched = True
                items.append({k:row[k] for k in ('segment','first_sequence','last_sequence','previous_record_sha256',
                                                  'last_record_sha256','previous_segment_sha256','epoch')})
                cursor = verified.cursor
            if not matched or cursor.sequence != cp['last_sequence'] or cursor.record_sha256 != cp['last_record_sha256']:
                raise JournalError('mixed checkpoint terminal differs')
            if set(anchors)-{entry['name'] for entry in cp['segments']}:
                raise JournalError('custody source absent from checkpoint')
            # Validation is complete. Reissue missing seals only for committed
            # raw tails, then restore the chain and resume with a new epoch.
            for name in ('metadata.json', 'checkpoint.json'):
                with (directory/name).open('rb') as stream: os.fsync(stream.fileno())
            sync_directory(directory)
            obj.recovered_tickets = tuple(obj._issue(item, sha(encoded(cp))) for item in items)
            obj.recovery = dict(committed_segments=len(items), archive_segments=len(anchors),
                                live_market_state_restored=False, checkpoint_anchor_verified=True)
            return obj
        except BaseException:
            if obj is not None: obj.close()
            else: lock.close()
            raise
