"""Budgeted immutable gzip archives of verified closed journal segments.

Single owner, local filesystem. A durable descriptor publishes an archive;
temporary/unreferenced files never publish themselves. Originals are retained.
This synchronous component is not connected to the live collector.
"""
from contextlib import contextmanager
import gzip
import hashlib
import os
from pathlib import Path
import re
import stat
import uuid

from .durable_capture_log import JournalError, decoded, digest, encoded, file_hash, integer, keys, sync_directory
from .verified_journal_view import VerifiedJournalView

MAX_SEGMENT_BYTES = 8*1024**2
MAX_DESCRIPTOR_BYTES = 16*1024
MAX_FILES = 1024
CHUNK = 64*1024


class BudgetedSink:
    """gzip writes, including headers/trailer, participate in the same budget."""
    def __init__(self, stream, budget):
        self.stream, self.budget = stream, budget

    def write(self, data):
        self.budget.append(self.stream, data)
        return len(data)

    def tell(self): return self.stream.tell()
    def flush(self): return self.stream.flush()


def hash_stream(stream):
    value = hashlib.sha256()
    while chunk := stream.read(CHUNK): value.update(chunk)
    return value.hexdigest()


class SegmentArchive:
    def __init__(self, directory, *, budget):
        self.budget = budget
        self.directory = budget.path(directory)
        if self.directory == budget.root: raise JournalError('dedicated archive directory required')
        with budget.mutation():
            if not self.directory.exists():
                self.directory.mkdir()
                sync_directory(self.directory.parent)
        self._inventory()

    def _inventory(self):
        self.budget.reconcile()
        names = []
        for path in self.directory.iterdir():
            if not stat.S_ISREG(path.lstat().st_mode): raise JournalError('archive entries must be regular files')
            names.append(path.name)
            if len(names) > MAX_FILES: raise JournalError('archive file-count bound')
        return sorted(names)

    def _descriptor(self, archive_id):
        digest(archive_id)
        path = self.budget.path(self.directory/(archive_id+'.json'))
        with path.open('rb') as stream:
            data = stream.read(MAX_DESCRIPTOR_BYTES+1)
        if len(data) > MAX_DESCRIPTOR_BYTES: raise JournalError('archive descriptor bound')
        row = decoded(data)
        keys(row, 'version archive_id identity witness codec level compressed_name compressed_bytes compressed_sha256 originals_retained descriptor_sha256')
        body = {key:value for key,value in row.items() if key != 'descriptor_sha256'}
        if digest(row['descriptor_sha256']) != hashlib.sha256(encoded(body)).hexdigest():
            raise JournalError('archive descriptor checksum mismatch')
        if (type(row['version']) is not int or row['version'] != 1 or row['archive_id'] != archive_id or
                row['codec'] != 'gzip' or type(row['level']) is not int or row['level'] != 1 or
                row['originals_retained'] is not True):
            raise JournalError('archive contract mismatch')
        identity = row['identity']
        keys(identity, 'run_id journal segment_name raw_bytes raw_sha256 metadata_sha256')
        if identity['run_id'] != self.budget.contract['run_id']: raise JournalError('archive run differs')
        relative = identity['journal']
        if type(relative) is not str or not relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise JournalError('invalid journal identity')
        self.budget.path(self.budget.root/relative)
        if type(identity['segment_name']) is not str or not re.fullmatch(r'segment-[0-9]{7}\.jsonl', identity['segment_name']):
            raise JournalError('invalid source segment name')
        if integer(identity['raw_bytes'], 1) > MAX_SEGMENT_BYTES: raise JournalError('archive raw size bound')
        digest(identity['raw_sha256']); digest(identity['metadata_sha256'])
        if hashlib.sha256(encoded(identity)).hexdigest() != archive_id: raise JournalError('archive identity mismatch')
        keys(row['witness'], 'checkpoint_sha256 first_sequence last_sequence last_record_sha256')
        digest(row['witness']['checkpoint_sha256']); digest(row['witness']['last_record_sha256'])
        integer(row['witness']['first_sequence'], 1)
        integer(row['witness']['last_sequence'], row['witness']['first_sequence'])
        if type(row['compressed_name']) is not str or not re.fullmatch(r'[0-9a-f]{32}\.jsonl\.gz', row['compressed_name']):
            raise JournalError('invalid compressed name')
        if integer(row['compressed_bytes'], 1) > MAX_SEGMENT_BYTES+CHUNK: raise JournalError('compressed size bound')
        digest(row['compressed_sha256'])
        return row

    @contextmanager
    def _verified_file(self, row):
        """Finish compressed hash, gzip CRC, length and raw hash before yielding."""
        path = self.budget.path(self.directory/row['compressed_name'])
        with path.open('rb') as stream:
            if os.fstat(stream.fileno()).st_size != row['compressed_bytes'] or hash_stream(stream) != row['compressed_sha256']:
                raise JournalError('compressed archive mismatch')
            stream.seek(0)
            total, raw_hash = 0, hashlib.sha256()
            with gzip.GzipFile(fileobj=stream, mode='rb') as reader:
                while chunk := reader.read(min(CHUNK, row['identity']['raw_bytes']-total+1)):
                    total += len(chunk)
                    if total > row['identity']['raw_bytes']: raise JournalError('archive expansion exceeds descriptor')
                    raw_hash.update(chunk)
            if total != row['identity']['raw_bytes'] or raw_hash.hexdigest() != row['identity']['raw_sha256']:
                raise JournalError('restored raw archive mismatch')
            stream.seek(0)
            yield stream

    def _sync_registered(self, row):
        with self._verified_file(row) as stream: os.fsync(stream.fileno())
        with (self.directory/(row['archive_id']+'.json')).open('rb') as stream: os.fsync(stream.fileno())
        sync_directory(self.directory)

    def publish(self, journal, segment_name, *, hook=lambda stage: None):
        """Verify a closed source while holding its writer lock, then publish.

        Retrying after an interrupted attempt creates a fresh gzip filename.
        Old temporaries/orphans remain counted; no overwrite or implicit cleanup.
        """
        with self.budget.mutation():
            names = self._inventory()
            if len(names)+3 > MAX_FILES: raise JournalError('archive file-count headroom')
            journal = self.budget.path(journal)
            if not re.fullmatch(r'segment-[0-9]{7}\.jsonl', segment_name): raise JournalError('segment name')
            with VerifiedJournalView(journal) as view:
                if view.meta['run_id'] != self.budget.contract['run_id']: raise JournalError('source run differs')
                if view.recovery['uncommitted_suffixes'] or view.recovery['pending_checkpoint_files']:
                    raise JournalError('source contains uncommitted or uncertain data')
                entry = next((e for e in view.cp['segments'] if e['name'] == segment_name), None)
                if entry is None or not 0 < entry['bytes'] <= MAX_SEGMENT_BYTES:
                    raise JournalError('committed small segment required')
                source = journal/segment_name
                if source.stat().st_size != entry['bytes']: raise JournalError('source segment changed')
                identity = dict(run_id=view.meta['run_id'], journal=str(journal.relative_to(self.budget.root)),
                    segment_name=segment_name, raw_bytes=entry['bytes'], raw_sha256=entry['sha256'],
                    metadata_sha256=view.cp['metadata_sha256'])
                archive_id = hashlib.sha256(encoded(identity)).hexdigest()
                if (self.directory/(archive_id+'.json')).exists():
                    existing = self._descriptor(archive_id)
                    self._sync_registered(existing)
                    return existing
                # The complete source journal was already validated by the view.
                with source.open('rb') as reader:
                    header = decoded(reader.readline(view.meta['max_record_bytes']+1))
                    first = header['first_sequence']
                    last, terminal = first-1, None
                    for line in reader:
                        record = decoded(line)
                        last, terminal = record['sequence'], record['sha256']
                if last < first: raise JournalError('empty segment cannot be archived')
                witness = dict(checkpoint_sha256=file_hash(journal/'checkpoint.json'), first_sequence=first,
                               last_sequence=last, last_record_sha256=terminal)
                token = uuid.uuid4().hex
                temporary = self.directory/('.'+token+'.gz.tmp')
                target = self.directory/(token+'.jsonl.gz')
                with source.open('rb') as reader, temporary.open('xb', buffering=0) as raw:
                    with gzip.GzipFile(filename='', fileobj=BudgetedSink(raw, self.budget),
                                       mode='wb', compresslevel=1, mtime=0) as writer:
                        while chunk := reader.read(CHUNK):
                            writer.write(chunk)
                            hook('after_archive_chunk')
                    os.fsync(raw.fileno())
                hook('after_archive_fsync')
                row = dict(version=1, archive_id=archive_id, identity=identity, witness=witness,
                    codec='gzip', level=1, compressed_name=target.name,
                    compressed_bytes=temporary.stat().st_size, compressed_sha256=file_hash(temporary),
                    originals_retained=True)
                row['descriptor_sha256'] = hashlib.sha256(encoded(row)).hexdigest()
                # Verify the completed temporary before the rename/publication.
                temporary_row = row | dict(compressed_name=temporary.name)
                with self._verified_file(temporary_row): pass
                if file_hash(source) != entry['sha256']: raise JournalError('source changed during compression')
                hook('after_archive_verify')
                if target.exists(): raise JournalError('unique archive filename already exists')
                os.replace(temporary, target)
                self.budget._refresh(temporary); self.budget._refresh(target)
                hook('after_archive_rename')
                sync_directory(self.directory)
                hook('after_archive_directory_fsync')
                if len(encoded(row)) > MAX_DESCRIPTOR_BYTES: raise JournalError('descriptor size bound')
                stages = dict(after_checkpoint_fsync='after_manifest_fsync',
                              after_checkpoint_replace='after_manifest_replace',
                              after_directory_fsync='after_manifest_directory_fsync')
                if (self.directory/(archive_id+'.json')).exists(): raise JournalError('descriptor appeared during publication')
                self.budget.atomic_json(self.directory/(archive_id+'.json'), row,
                                       hook=lambda stage: hook(stages[stage]))
                return row

    def recover(self):
        """Reconcile all bytes; validate/re-fsync registered files, preserve rest.

        Orphans remain unregistered even when they contain valid gzip data.
        A corrupt descriptor/archive is a failure, not a reason to skip an entry.
        """
        with self.budget.mutation():
            names = self._inventory()
            registered, referenced = [], set()
            for name in names:
                if name.startswith('.'): continue
                if name.endswith('.json'):
                    if not re.fullmatch(r'[0-9a-f]{64}\.json', name): raise JournalError('unknown archive descriptor')
                    row = self._descriptor(name[:-5])
                    if row['compressed_name'] in referenced: raise JournalError('archive file referenced twice')
                    self._sync_registered(row)
                    source = self.budget.path(self.budget.root/row['identity']['journal']/row['identity']['segment_name'])
                    source_state = ('MISSING' if not source.exists() else
                        'MATCH' if source.stat().st_size == row['identity']['raw_bytes'] and file_hash(source) == row['identity']['raw_sha256'] else 'DIFFERS')
                    registered.append(dict(archive_id=row['archive_id'], source_state=source_state))
                    referenced.add(row['compressed_name']); referenced.add(name)
                elif not re.fullmatch(r'[0-9a-f]{32}\.jsonl\.gz', name):
                    raise JournalError('unknown archive file')
            sync_directory(self.directory)
            unregistered = [n for n in names if n not in referenced]
            return dict(status='REGISTERED_ARCHIVES_VERIFIED', registered=registered,
                unregistered_files=unregistered,
                catalog_complete=not unregistered and all(r['source_state'] == 'MATCH' for r in registered),
                originals_retained_by_this_api=True, original_deletion_implemented=False,
                all_sources_match=all(r['source_state'] == 'MATCH' for r in registered),
                storage=self.budget.snapshot(), live_market_state_restored=False)

    def read_chunks(self, archive_id):
        """Verified compressed data, independent of whether the raw file survived."""
        self.budget.check(0)
        row = self._descriptor(archive_id)
        with self._verified_file(row) as stream, gzip.GzipFile(fileobj=stream, mode='rb') as reader:
            total, digest2 = 0, hashlib.sha256()
            while chunk := reader.read(CHUNK):
                self.budget.check(0)
                total += len(chunk)
                if total > row['identity']['raw_bytes']: raise JournalError('archive changed during read')
                digest2.update(chunk)
                yield chunk
            if total != row['identity']['raw_bytes'] or digest2.hexdigest() != row['identity']['raw_sha256']:
                raise JournalError('archive changed during read')
