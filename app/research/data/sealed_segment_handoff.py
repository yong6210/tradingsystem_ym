"""Writer-issued, durable segment handoff; workers never lock an active journal.

Cooperative single storage owner only. A ticket is issued after the directory
fence, not by polling seal files. Recovery scans the committed journal offline.
This does not schedule jobs, compress data, delete raw files, or restore markets.
"""
from dataclasses import dataclass, replace
import hashlib
import io
import os
from pathlib import Path
import re

from .durable_capture_log import (
    JournalError, ZERO, decoded, digest, encoded, integer, keys, scan_records,
    sync_directory,
)
from .shared_feed_storage import BudgetedJournal

MAX_SEGMENT_BYTES = 8 * 1024**2
MAX_SEAL_BYTES = 16384
MAX_PENDING_SEGMENTS = 16
MAX_SEGMENTS = 1024
NAME = re.compile(r'segment-[0-9]{7}\.jsonl\Z')


def sha(data):
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class SealTicket:
    # Only returned by seal() or offline resume after all persistence fences.
    certificate: bytes


@dataclass(frozen=True)
class SegmentCursor:
    root: Path
    journal: str
    run_id: str
    metadata_sha256: str
    sequence: int = 0
    record_sha256: str = ZERO
    segment_sha256: str = ZERO
    seal_sha256: str = ZERO
    index: int = -1


@dataclass(frozen=True)
class VerifiedSegment:
    raw: bytes
    cursor: SegmentCursor

    def records(self):
        stream = io.BytesIO(self.raw)
        stream.readline()
        for line in stream:
            yield decoded(line)


def certificate(raw):
    if type(raw) is not bytes or len(raw) > MAX_SEAL_BYTES:
        raise JournalError('seal size bound')
    row = decoded(raw)
    keys(row, 'version run_id journal metadata_sha256 segment first_sequence last_sequence '
         'previous_record_sha256 last_record_sha256 previous_segment_sha256 previous_seal_sha256 '
         'epoch max_record_bytes checkpoint_sha256 seal_sha256')
    if type(row['version']) is not int or row['version'] != 1:
        raise JournalError('unsupported seal version')
    for field in ('run_id', 'journal', 'epoch'):
        if type(row[field]) is not str or not row[field] or len(row[field]) > 4096:
            raise JournalError('seal identity invalid')
    journal = Path(row['journal'])
    if journal.is_absolute() or '..' in journal.parts or str(journal) != row['journal'] or row['journal'] == '.':
        raise JournalError('seal journal path invalid')
    keys(row['segment'], 'name bytes sha256')
    entry = row['segment']
    if type(entry['name']) is not str or not NAME.fullmatch(entry['name']):
        raise JournalError('seal segment name invalid')
    if integer(entry['bytes'], 1) > MAX_SEGMENT_BYTES:
        raise JournalError('seal segment size bound')
    digest(entry['sha256'])
    if integer(row['last_sequence'], 1) < integer(row['first_sequence'], 1):
        raise JournalError('seal sequence range invalid')
    if integer(row['max_record_bytes'], 1) > MAX_SEGMENT_BYTES-256:
        raise JournalError('seal record size bound')
    for field in ('metadata_sha256', 'previous_record_sha256', 'last_record_sha256',
                  'previous_segment_sha256', 'previous_seal_sha256', 'checkpoint_sha256', 'seal_sha256'):
        digest(row[field])
    if sha(encoded({k:v for k,v in row.items() if k != 'seal_sha256'})) != row['seal_sha256']:
        raise JournalError('seal checksum mismatch')
    return row


def read_segment(ticket, cursor):
    """Validate one bounded immutable byte snapshot before releasing any records.

    No checkpoint, previous segment, seal directory scan, or writer lock needed.
    The caller owns cursor advancement and must persist it with downstream state.
    A checksum detects corruption; it is not a signature against a hostile owner.
    """
    row = certificate(ticket.certificate)
    entry = row['segment']
    index = int(entry['name'][8:15])
    if (row['journal'] != cursor.journal or row['run_id'] != cursor.run_id or
            row['metadata_sha256'] != cursor.metadata_sha256 or index <= cursor.index or
            row['first_sequence'] != cursor.sequence+1 or
            row['previous_record_sha256'] != cursor.record_sha256 or
            row['previous_segment_sha256'] != cursor.segment_sha256 or
            row['previous_seal_sha256'] != cursor.seal_sha256):
        raise JournalError('handoff cursor continuity mismatch')
    root = Path(cursor.root).absolute()
    path = root/row['journal']/entry['name']
    if root.resolve() != root or path.resolve() != path or not path.is_file():
        raise JournalError('canonical regular segment required')
    with path.open('rb') as stream:
        raw = stream.read(entry['bytes']+1)
    if len(raw) != entry['bytes'] or sha(raw) != entry['sha256']:
        raise JournalError('sealed segment size or hash mismatch')
    stream = io.BytesIO(raw)
    header_line = stream.readline(4097)
    if len(header_line) > 4096 or not header_line.endswith(b'\n'):
        raise JournalError('sealed header boundary invalid')
    header = decoded(header_line)
    keys(header, 'kind run_id epoch index first_sequence previous_segment_sha256')
    if (header['kind'] != 'SEGMENT' or header['run_id'] != row['run_id'] or
            header['epoch'] != row['epoch'] or integer(header['index']) != index or
            integer(header['first_sequence'], 1) != row['first_sequence'] or
            header['previous_segment_sha256'] != row['previous_segment_sha256']):
        raise JournalError('sealed header mismatch')
    sequence, previous = cursor.sequence, cursor.record_sha256
    while line := stream.readline(row['max_record_bytes']+1):
        if len(line) > row['max_record_bytes'] or not line.endswith(b'\n'):
            raise JournalError('sealed record boundary invalid')
        record = decoded(line)
        keys(record, 'sequence epoch previous_record_sha256 payload sha256')
        if (integer(record['sequence'], 1) != sequence+1 or record['epoch'] != row['epoch'] or
                record['previous_record_sha256'] != previous or type(record['payload']) is not dict or
                digest(record['sha256']) != sha(encoded({k:v for k,v in record.items() if k != 'sha256'}))):
            raise JournalError('sealed record chain invalid')
        sequence, previous = record['sequence'], record['sha256']
    if sequence != row['last_sequence'] or previous != row['last_record_sha256']:
        raise JournalError('sealed terminal record mismatch')
    return VerifiedSegment(raw, replace(cursor, sequence=sequence, record_sha256=previous,
        segment_sha256=entry['sha256'], seal_sha256=row['seal_sha256'], index=index))


class SealedJournal(BudgetedJournal):
    """Explicit seal() closes/commits a bounded batch and then issues tickets.

    append()/commit() retain the frozen journal contract. Consumers must call
    seal() often enough; exceeding pending bounds fails closed, without dropping
    work. Inherited checkpoints still grow with history (at most 1,024 segments).
    """
    @classmethod
    def create(cls, directory, *, budget, run_id, rotation_bytes=MAX_SEGMENT_BYTES,
               max_record_bytes=1024**2, hook=lambda stage: None):
        if integer(rotation_bytes, 512) > MAX_SEGMENT_BYTES:
            raise JournalError('handoff rotation bound')
        obj = super().create(directory, budget=budget, run_id=run_id,
            rotation_bytes=rotation_bytes, max_record_bytes=max_record_bytes, hook=hook)
        try:
            with budget.mutation():
                obj.seals.mkdir()
                sync_directory(obj.directory)
            return obj
        except BaseException:
            obj.close()
            raise

    def __init__(self, *args):
        super().__init__(*args)
        if self.meta['rotation_bytes'] > MAX_SEGMENT_BYTES or len(self.entries) > MAX_SEGMENTS:
            raise JournalError('handoff journal bounds')
        self.seals = self.directory/'seals'
        self.pending = []
        self.previous_seal = ZERO
        self.recovered_tickets = ()

    def initial_cursor(self):
        return SegmentCursor(self.budget.root, str(self.directory.relative_to(self.budget.root)),
                             self.meta['run_id'], self.cp['metadata_sha256'])

    def _new_segment(self):
        if len(self.pending) >= MAX_PENDING_SEGMENTS or len(self.entries) >= MAX_SEGMENTS:
            raise JournalError('handoff pending or total segment bound')
        first, previous = self.sequence+1, self.record_hash
        previous_segment = self.entries[-1]['sha256'] if self.entries else ZERO
        super()._new_segment()
        self.pending.append(dict(segment=self.entries[-1], first_sequence=first,
            last_sequence=first-1, previous_record_sha256=previous,
            last_record_sha256=previous, previous_segment_sha256=previous_segment, epoch=self.epoch))

    def append(self, payload):
        result = super().append(payload)
        self.pending[-1].update(last_sequence=self.sequence, last_record_sha256=self.record_hash)
        return result

    def _issue(self, item, checkpoint_hash):
        body = dict(version=1, run_id=self.meta['run_id'],
            journal=str(self.directory.relative_to(self.budget.root)),
            metadata_sha256=self.cp['metadata_sha256'], **item,
            previous_seal_sha256=self.previous_seal, max_record_bytes=self.meta['max_record_bytes'],
            checkpoint_sha256=checkpoint_hash)
        row = body | dict(seal_sha256=sha(encoded(body)))
        raw = encoded(row)
        certificate(raw)
        path = self.budget.path(self.seals/(item['segment']['name']+'.seal.json'))
        if path.exists():
            if not path.is_file() or path.stat().st_size > MAX_SEAL_BYTES:
                raise JournalError('invalid existing seal')
            raw = path.read_bytes()
            existing = certificate(raw)
            # The original checkpoint may precede the recovered checkpoint.
            # Full source validation and identical boundaries reanchor it here.
            compare = lambda value: {k:v for k,v in value.items() if k not in ('seal_sha256', 'checkpoint_sha256')}
            if compare(existing) != compare(row):
                raise JournalError('existing seal differs from committed source')
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
            sync_directory(self.seals)
            row = existing
        else:
            stages = {'after_checkpoint_fsync':'after_seal_fsync',
                      'after_checkpoint_replace':'after_seal_replace',
                      'after_directory_fsync':'after_seal_directory_fsync'}
            self.budget.atomic_json(path, row, lambda stage: self.hook(stages[stage]))
        self.previous_seal = row['seal_sha256']
        return SealTicket(raw)

    def seal(self):
        self._writable()
        with self.budget.mutation():
            try:
                if self.active is not None:
                    self.active.close()
                    self.active = None  # Never append to a sealed file again.
                self.hook('after_seal_close')
                super().commit()
                self.hook('after_seal_commit')
                checkpoint_hash = sha(encoded(self.cp))
                tickets = tuple(self._issue(item, checkpoint_hash) for item in self.pending)
                self.pending.clear()
                return tickets
            except BaseException:
                self.failed = True
                raise

    @classmethod
    def resume(cls, directory, *, budget, hook=lambda stage: None):
        # Offline: base resume holds the journal lock, validates all committed
        # bytes and re-fsyncs them. This cost is NOT on the active handoff path.
        obj = super().resume(directory, budget=budget, hook=hook)
        try:
            with budget.mutation():
                if not obj.seals.is_dir() or obj.seals.resolve() != obj.seals:
                    raise JournalError('missing canonical seal directory')
                names = list(obj.seals.iterdir())
                if len(names) > MAX_SEGMENTS*2:
                    raise JournalError('seal inventory bound')
                expected = {e['name']+'.seal.json' for e in obj.entries}
                for path in names:
                    if not path.is_file() or (not path.name.startswith('.') and path.name not in expected):
                        raise JournalError('unexpected seal entry')
                # Do not silently clip an uncertain tail on a committed file.
                for entry in obj.entries:
                    if (obj.directory/entry['name']).stat().st_size != entry['bytes']:
                        raise JournalError('committed segment has uncertain suffix; offline repair required')
                records = iter(scan_records(obj.directory, obj.meta, obj.cp))
                previous_record = previous_segment = ZERO
                checkpoint_hash = sha(encoded(obj.cp))
                tickets = []
                for entry in obj.entries:
                    with (obj.directory/entry['name']).open('rb') as stream:
                        header = decoded(stream.readline(4097))
                        count = sum(1 for _ in stream)
                    if not count:
                        raise JournalError('empty committed segment cannot be sealed')
                    first = header['first_sequence']
                    for _ in range(count):
                        last = next(records)
                    item = dict(segment=entry, first_sequence=first, last_sequence=last['sequence'],
                        previous_record_sha256=previous_record, last_record_sha256=last['sha256'],
                        previous_segment_sha256=previous_segment, epoch=header['epoch'])
                    tickets.append(obj._issue(item, checkpoint_hash))
                    previous_record, previous_segment = last['sha256'], entry['sha256']
                if next(records, None) is not None:
                    raise JournalError('unexpected trailing committed record')
                obj.recovered_tickets = tuple(tickets)
                return obj
        except BaseException:
            obj.close()
            raise
