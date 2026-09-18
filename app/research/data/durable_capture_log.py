"""Single-writer, segmented raw capture journal with a durable publication fence.

POSIX local-filesystem implementation. Resume preserves all uncommitted bytes,
starts a new segment/epoch, and never appends after an uncertain old tail.
No market, account, order, or strategy code is called here.
"""
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import uuid

ZERO = '0'*64


class JournalError(RuntimeError):
    pass


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                       allow_nan=False)+'\n').encode('utf-8')


def decoded(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise JournalError('duplicate JSON key')
            result[key] = value
        return result
    def bad_constant(value):
        raise JournalError('nonfinite JSON value')
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=bad_constant)
    except (ValueError, UnicodeError) as exc:
        raise JournalError('malformed journal JSON') from exc


def keys(value, expected):
    if type(value) is not dict or set(value) != set(expected.split()):
        raise JournalError('journal fields differ from schema')


def integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise JournalError('integer outside journal bounds')
    return value


def digest(value):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise JournalError('invalid digest')
    return value


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(directory, name, value, hook=lambda stage: None):
    temporary = directory/f'.{name}.{uuid.uuid4().hex}.tmp'
    with temporary.open('xb') as stream:
        stream.write(encoded(value))
        stream.flush()
        os.fsync(stream.fileno())
    hook('after_checkpoint_fsync')
    os.replace(temporary, directory/name)
    hook('after_checkpoint_replace')
    sync_directory(directory)
    hook('after_directory_fsync')


def file_hash(path, start=0, length=None):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        stream.seek(start)
        remaining = length
        while remaining is None or remaining:
            data = stream.read(1024*1024 if remaining is None else min(remaining, 1024*1024))
            if not data:
                if remaining:
                    raise JournalError('committed file truncated')
                break
            h.update(data)
            if remaining is not None:
                remaining -= len(data)
    return h.hexdigest()


def lock_directory(directory):
    stream = (directory/'.writer.lock').open('a+b')
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        stream.close()
        raise JournalError('journal busy: another writer or reader holds the lock') from exc
    return stream


def load_state(directory):
    # Checkpoints are bounded metadata, never a way to load an entire day's raw data.
    result = []
    for name in ('metadata.json', 'checkpoint.json'):
        path = directory/name
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 4*1024**2:
            raise JournalError('missing or oversized journal metadata')
        result.append(decoded(path.read_bytes()))
    meta, cp = result
    keys(meta, 'version run_id rotation_bytes max_record_bytes max_total_bytes min_free_bytes')
    if type(meta['version']) is not int or meta['version'] != 1 or type(meta['run_id']) is not str or not meta['run_id']:
        raise JournalError('unsupported journal metadata')
    for name in ('rotation_bytes', 'max_record_bytes', 'max_total_bytes'):
        integer(meta[name], 1)
    integer(meta['min_free_bytes'])
    if not 512 <= meta['rotation_bytes'] or not meta['max_record_bytes'] <= meta['rotation_bytes']-256:
        raise JournalError('invalid segment/record bounds')
    keys(cp, 'version run_id metadata_sha256 last_sequence last_record_sha256 segments')
    if type(cp['version']) is not int or cp['version'] != 1 or cp['run_id'] != meta['run_id']:
        raise JournalError('checkpoint identity mismatch')
    if digest(cp['metadata_sha256']) != file_hash(directory/'metadata.json'):
        raise JournalError('metadata hash mismatch')
    integer(cp['last_sequence'])
    digest(cp['last_record_sha256'])
    if type(cp['segments']) is not list or len(cp['segments']) > 10000:
        raise JournalError('invalid segment manifest')
    return meta, cp


def scan_records(directory, meta, cp):
    sequence, previous_record, previous_segment, previous_index = 0, ZERO, ZERO, -1
    for entry in cp['segments']:
        keys(entry, 'name bytes sha256')
        name = entry['name']
        if type(name) is not str or len(name) != 21 or not name.startswith('segment-') or not name.endswith('.jsonl') or not name[8:15].isdigit():
            raise JournalError('invalid segment filename')
        index = int(name[8:15])
        if index <= previous_index:
            raise JournalError('segment order regressed')
        previous_index = index
        length = integer(entry['bytes'], 1)
        if length > meta['rotation_bytes']:
            raise JournalError('segment bound exceeded')
        path = directory/name
        if not path.is_file() or path.is_symlink() or file_hash(path, length=length) != digest(entry['sha256']):
            raise JournalError('committed segment missing or hash mismatch')
        with path.open('rb') as stream:
            remaining = length
            header_line = stream.readline(min(remaining, 4096)+1)
            if len(header_line) > remaining or not header_line.endswith(b'\n'):
                raise JournalError('invalid segment header boundary')
            remaining -= len(header_line)
            header = decoded(header_line)
            keys(header, 'kind run_id epoch index first_sequence previous_segment_sha256')
            if (header['kind'] != 'SEGMENT' or header['run_id'] != meta['run_id'] or
                    integer(header['index']) != index or integer(header['first_sequence'], 1) != sequence+1 or
                    header['previous_segment_sha256'] != previous_segment or type(header['epoch']) is not str or not header['epoch']):
                raise JournalError('segment link invalid')
            while remaining:
                line = stream.readline(min(remaining, meta['max_record_bytes'])+1)
                if len(line) > min(remaining, meta['max_record_bytes']) or not line.endswith(b'\n'):
                    raise JournalError('committed record boundary invalid')
                remaining -= len(line)
                row = decoded(line)
                keys(row, 'sequence epoch previous_record_sha256 payload sha256')
                body = {key: row[key] for key in row if key != 'sha256'}
                if (integer(row['sequence'], 1) != sequence+1 or row['epoch'] != header['epoch'] or
                        row['previous_record_sha256'] != previous_record or type(row['payload']) is not dict or
                        digest(row['sha256']) != hashlib.sha256(encoded(body)).hexdigest()):
                    raise JournalError('record hash/sequence/epoch invalid')
                sequence, previous_record = row['sequence'], row['sha256']
                yield row
        previous_segment = entry['sha256']
    if sequence != cp['last_sequence'] or previous_record != cp['last_record_sha256']:
        raise JournalError('checkpoint terminal record mismatch')


def inspect_locked(directory):
    meta, cp = load_state(directory)
    for _ in scan_records(directory, meta, cp):
        pass  # Validate the whole prefix before returning anything publishable.
    known = {entry['name']: entry['bytes'] for entry in cp['segments']}
    tails = []
    for path in sorted(directory.glob('segment-*.jsonl')):
        if path.is_symlink():
            raise JournalError('symlink segment refused')
        offset = known.get(path.name, 0)
        size = path.stat().st_size
        if size > offset:
            tails.append(dict(name=path.name, offset=offset, bytes=size-offset,
                              sha256=file_hash(path, start=offset)))
    return meta, cp, dict(last_sequence=cp['last_sequence'], last_record_sha256=cp['last_record_sha256'],
                         committed_segments=len(cp['segments']), uncommitted_suffixes=tails,
                         pending_checkpoint_files=sorted(p.name for p in directory.glob('.checkpoint.json.*.tmp')),
                         live_market_state_restored=False)


def inspect_journal(directory):
    directory = Path(directory)
    with lock_directory(directory):
        return inspect_locked(directory)[2]


def iter_committed(directory):
    """Offline verified-prefix iterator; holds the lock until closed/exhausted."""
    directory = Path(directory)
    with lock_directory(directory):
        meta, cp, _ = inspect_locked(directory)
        yield from scan_records(directory, meta, cp)


@dataclass(frozen=True)
class CommitReceipt:
    sequence: int
    record_sha256: str
    available_monotonic_ns: int


class DurableCaptureLog:
    @classmethod
    def create(cls, directory, *, run_id, rotation_bytes=128*1024**2,
               max_record_bytes=4*1024**2, max_total_bytes=64*1024**3,
               min_free_bytes=16*1024**3, hook=lambda stage: None):
        if type(run_id) is not str or not run_id or len(run_id) > 128:
            raise JournalError('bounded run ID required')
        for value in (rotation_bytes, max_record_bytes, max_total_bytes):
            integer(value, 1)
        integer(min_free_bytes)
        if rotation_bytes < 512 or max_record_bytes > rotation_bytes-256:
            raise JournalError('invalid segment/record bounds')
        directory = Path(directory)
        directory.mkdir(parents=False, exist_ok=False)
        lock = lock_directory(directory)
        try:
            meta = dict(version=1, run_id=run_id, rotation_bytes=rotation_bytes,
                        max_record_bytes=max_record_bytes, max_total_bytes=max_total_bytes,
                        min_free_bytes=min_free_bytes)
            atomic_json(directory, 'metadata.json', meta)
            cp = dict(version=1, run_id=run_id, metadata_sha256=file_hash(directory/'metadata.json'),
                      last_sequence=0, last_record_sha256=ZERO, segments=[])
            atomic_json(directory, 'checkpoint.json', cp)
            sync_directory(directory.parent)
            return cls(directory, lock, meta, cp, hook)
        except BaseException:
            lock.close()
            raise

    @classmethod
    def resume(cls, directory, *, hook=lambda stage: None):
        directory = Path(directory)
        lock = lock_directory(directory)
        try:
            meta, cp, recovery = inspect_locked(directory)
            # A rename visible after a process crash can contain an unacknowledged
            # commit. Validate and sync it now before issuing a new durable fence.
            for name in ['metadata.json', 'checkpoint.json']+[e['name'] for e in cp['segments']]:
                with (directory/name).open('rb') as stream:
                    os.fsync(stream.fileno())
            sync_directory(directory)
            obj = cls(directory, lock, meta, cp, hook)
            obj.recovery = recovery
            return obj
        except BaseException:
            lock.close()
            raise

    def __init__(self, directory, lock, meta, cp, hook):
        self.directory, self.lock, self.meta, self.cp, self.hook = directory, lock, meta, cp, hook
        self.epoch = uuid.uuid4().hex
        self.sequence, self.record_hash = cp['last_sequence'], cp['last_record_sha256']
        self.receipt = CommitReceipt(self.sequence, self.record_hash, time.monotonic_ns())
        self.entries = [dict(e) for e in cp['segments']]
        self.dirty = set()
        self.active = None
        self.active_hash = None
        self.closed = self.failed = False
        self.recovery = None
        names = [p.name for p in directory.glob('segment-*.jsonl')]
        if any(len(n) != 21 or not n[8:15].isdigit() for n in names):
            raise JournalError('unexpected segment filename')
        self.next_index = max((int(n[8:15]) for n in names), default=-1)+1
        self.total_bytes = sum(p.stat().st_size for p in directory.glob('segment-*.jsonl'))

    def _writable(self):
        if self.closed or self.failed:
            raise JournalError('journal closed or failed; reopen and recover')

    def _space(self, extra):
        if self.total_bytes+extra > self.meta['max_total_bytes']:
            raise JournalError('run raw-byte budget exceeded')
        if shutil.disk_usage(self.directory).free < self.meta['min_free_bytes']+extra+65536:
            raise JournalError('free-space reserve would be crossed')

    def _new_segment(self):
        if self.active is not None:
            self.active.close()
        if self.next_index > 9999999 or len(self.entries) >= 10000:
            raise JournalError('segment index exhausted')
        header = encoded(dict(kind='SEGMENT', run_id=self.meta['run_id'], epoch=self.epoch,
                              index=self.next_index, first_sequence=self.sequence+1,
                              previous_segment_sha256=self.entries[-1]['sha256'] if self.entries else ZERO))
        self._space(len(header))
        name = f'segment-{self.next_index:07d}.jsonl'
        self.next_index += 1
        self.active = (self.directory/name).open('xb', buffering=0)
        if self.active.write(header) != len(header):
            raise JournalError('short header write')
        self.active_hash = hashlib.sha256(header)
        self.entries.append(dict(name=name, bytes=len(header), sha256=self.active_hash.hexdigest()))
        self.total_bytes += len(header)
        self.dirty.add(name)

    def append(self, payload):
        self._writable()
        if type(payload) is not dict:
            raise JournalError('payload object required')
        body = dict(sequence=self.sequence+1, epoch=self.epoch,
                    previous_record_sha256=self.record_hash, payload=payload)
        identity = hashlib.sha256(encoded(body)).hexdigest()
        line = encoded(body | dict(sha256=identity))
        if len(line) > self.meta['max_record_bytes']:
            raise JournalError('record exceeds bound')
        try:
            self._space(len(line))
            if self.active is None or self.entries[-1]['bytes']+len(line) > self.meta['rotation_bytes']:
                self._new_segment()
            self._space(len(line))
            if self.entries[-1]['bytes']+len(line) > self.meta['rotation_bytes']:
                raise JournalError('record cannot fit beside segment header')
            if self.active.write(line) != len(line):
                raise JournalError('short record write')
            self.active_hash.update(line)
            self.entries[-1]['bytes'] += len(line)
            self.entries[-1]['sha256'] = self.active_hash.hexdigest()
            self.dirty.add(self.entries[-1]['name'])
            self.total_bytes += len(line)
            self.sequence, self.record_hash = body['sequence'], identity
            self.hook('after_append')
            return self.sequence  # Not a publication receipt.
        except BaseException:
            self.failed = True
            raise

    def commit(self):
        self._writable()
        if not self.dirty:
            return self.receipt
        try:
            self._space(0)
            for name in sorted(self.dirty):
                with (self.directory/name).open('rb') as stream:
                    os.fsync(stream.fileno())
            sync_directory(self.directory)
            self.hook('after_raw_fsync')
            cp = dict(self.cp, last_sequence=self.sequence, last_record_sha256=self.record_hash,
                      segments=[dict(e) for e in self.entries])
            atomic_json(self.directory, 'checkpoint.json', cp, self.hook)
            # Only this point advances the live publication fence.
            self.cp = cp
            self.receipt = CommitReceipt(self.sequence, self.record_hash, time.monotonic_ns())
            self.dirty.clear()
            return self.receipt
        except BaseException:
            self.failed = True
            raise

    def close(self):
        if not self.closed:
            try:
                if self.active is not None:
                    self.active.close()
            finally:
                self.lock.close()
                self.closed = True
        # Deliberately does not commit pending bytes as a side effect.

    def publication_fence(self):
        self._writable()
        return self.receipt

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
