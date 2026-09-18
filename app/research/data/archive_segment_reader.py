"""One explicit raw OR gzip source, verified identically before any record use."""
from dataclasses import asdict
import io
from pathlib import Path

from .background_segment_archive import advance_cursor
from .durable_capture_log import JournalError, decoded, digest, encoded, integer, keys
from .sealed_segment_handoff import SealTicket, SegmentCursor, VerifiedSegment, certificate, sha
from .segment_archive import SegmentArchive


def cursor_dict(cursor):
    row = asdict(cursor)
    row['root'] = str(row['root'])
    return row


def restore_cursor(row):
    keys(row, 'root journal run_id metadata_sha256 sequence record_sha256 segment_sha256 seal_sha256 index')
    integer(row['sequence'])
    if type(row['index']) is not int or row['index'] < -1: raise JournalError('cursor index')
    for k in ('root','journal','run_id'):
        if type(row[k]) is not str or not row[k]: raise JournalError('cursor identity')
    for k in ('metadata_sha256','record_sha256','segment_sha256','seal_sha256'): digest(row[k])
    return SegmentCursor(**(row | dict(root=Path(row['root']))))


def segment_ref(ticket, *, archive_directory=None, archive_id=None):
    certificate(ticket.certificate)
    if (archive_directory is None) != (archive_id is None): raise JournalError('complete archive source required')
    return dict(certificate=ticket.certificate.decode(), archive=None if archive_id is None else
                dict(directory=archive_directory, archive_id=archive_id))


def validate_bytes(ticket, cursor, raw):
    row = certificate(ticket.certificate)
    next_cursor = advance_cursor(row, cursor)
    if len(raw) != row['segment']['bytes'] or sha(raw) != row['segment']['sha256']:
        raise JournalError('segment bytes differ from seal')
    stream = io.BytesIO(raw)
    line = stream.readline(4097)
    if len(line) > 4096 or not line.endswith(b'\n'): raise JournalError('segment header boundary')
    header = decoded(line)
    keys(header, 'kind run_id epoch index first_sequence previous_segment_sha256')
    if (header['kind'] != 'SEGMENT' or header['run_id'] != row['run_id'] or
            header['epoch'] != row['epoch'] or integer(header['index']) != next_cursor.index or
            integer(header['first_sequence'], 1) != row['first_sequence'] or
            header['previous_segment_sha256'] != row['previous_segment_sha256']):
        raise JournalError('segment header differs from seal')
    sequence, previous = cursor.sequence, cursor.record_sha256
    while line := stream.readline(row['max_record_bytes']+1):
        if len(line) > row['max_record_bytes'] or not line.endswith(b'\n'): raise JournalError('segment record boundary')
        record = decoded(line)
        keys(record, 'sequence epoch previous_record_sha256 payload sha256')
        if (integer(record['sequence'], 1) != sequence+1 or record['epoch'] != row['epoch'] or
                record['previous_record_sha256'] != previous or type(record['payload']) is not dict or
                digest(record['sha256']) != sha(encoded({k:v for k,v in record.items() if k != 'sha256'}))):
            raise JournalError('segment record chain differs')
        sequence, previous = record['sequence'], record['sha256']
    if sequence != row['last_sequence'] or previous != row['last_record_sha256']:
        raise JournalError('segment terminal differs from seal')
    return VerifiedSegment(raw, next_cursor)


class SegmentReader:
    def __init__(self, *, budget):
        self.budget = budget
        self.reads = []

    def read(self, ref, cursor):
        self.budget.check(0)
        keys(ref, 'certificate archive')
        if type(ref['certificate']) is not str: raise JournalError('certificate text required')
        ticket = SealTicket(ref['certificate'].encode())
        row = certificate(ticket.certificate)
        advance_cursor(row, cursor)
        if cursor.root != self.budget.root or cursor.run_id != self.budget.contract['run_id']:
            raise JournalError('reader root or run differs')
        if ref['archive'] is None:
            path = self.budget.path(cursor.root/row['journal']/row['segment']['name'])
            if not path.is_file(): raise JournalError('raw source missing')
            with path.open('rb') as stream: raw = stream.read(row['segment']['bytes']+1)
            source = 'RAW'
        else:
            archive = ref['archive']
            keys(archive, 'directory archive_id')
            if (type(archive['directory']) is not str or Path(archive['directory']).is_absolute() or
                    '..' in Path(archive['directory']).parts or not archive['directory']):
                raise JournalError('relative archive directory required')
            directory = self.budget.path(cursor.root/archive['directory'])
            if not directory.is_dir(): raise JournalError('archive directory missing')
            # Read-only adapter: no constructor inventory, directory creation or
            # historical source validation on the selected-segment read path.
            store = object.__new__(SegmentArchive)
            store.directory, store.budget = directory, self.budget
            descriptor = store._descriptor(archive['archive_id'])
            expected = dict(run_id=row['run_id'], journal=row['journal'], segment_name=row['segment']['name'],
                raw_bytes=row['segment']['bytes'], raw_sha256=row['segment']['sha256'], metadata_sha256=row['metadata_sha256'])
            if (descriptor['identity'] != expected or any(descriptor['witness'][k] != row[k]
                    for k in ('first_sequence','last_sequence','last_record_sha256'))):
                raise JournalError('archive binding differs from seal')
            raw = b''.join(store.read_chunks(archive['archive_id']))
            source = 'GZIP'
        result = validate_bytes(ticket, cursor, raw)
        # Diagnostics describe only this bounded operation; callers clear per job.
        if len(self.reads) >= 32: raise JournalError('reader operation count bound')
        self.reads.append(dict(source=source, segment=row['segment']['name'], bytes=len(raw)))
        return result
