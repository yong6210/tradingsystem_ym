"""Historical collector custody view: preserve uncertain unsealed suffixes.

The writable journal component intentionally refuses suffixes. This separate
read/retirement view validates the committed prefix, never truncates or seals
unadmitted tails, and prohibits append/commit/seal. Saved market state is not
restored. Durable work tickets independently constrain what replay can consume.
"""
import io
import os
import re

from .archive_segment_reader import cursor_dict, validate_bytes
from .durable_capture_log import JournalError, ZERO, decoded, digest, encoded, integer, keys, load_state, lock_directory, sync_directory
from .retained_sealed_journal import RetainedSealedJournal
from .sealed_segment_handoff import MAX_SEGMENTS, MAX_SEAL_BYTES, SealTicket, certificate, sha


class RecoveryCustodyJournal(RetainedSealedJournal):
    def append(self, payload):
        raise JournalError('historical recovery view cannot append')

    def commit(self):
        raise JournalError('historical recovery view cannot commit')

    def seal(self):
        raise JournalError('historical recovery view cannot seal')

    @classmethod
    def open_for_recovery(cls, directory, *, budget, handle, hook=lambda stage: None):
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
            cursor = obj.initial_cursor(); matched = saved_sequence == 0
            obj.preserved_suffixes = []
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
                    if not path.is_file() or path.stat().st_size < integer(entry['bytes'], 1):
                        raise JournalError('committed raw prefix missing')
                    if entry['bytes'] > meta['rotation_bytes']:
                        raise JournalError('mixed segment size bound')
                    if path.stat().st_size > entry['bytes']:
                        # A durable seal forbids suffixes. Only an unsealed,
                        # unadmitted tail may contain uncommitted extra bytes.
                        if (obj.seals/(name+'.seal.json')).exists():
                            raise JournalError('sealed raw has uncertain suffix')
                        obj.preserved_suffixes.append(dict(journal=cursor.journal, source=name,
                            committed_bytes=entry['bytes'], extra_bytes=path.stat().st_size-entry['bytes']))
                    with path.open('rb') as stream: raw = stream.read(entry['bytes'])
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
                cursor = verified.cursor
            if not matched or cursor.sequence != cp['last_sequence'] or cursor.record_sha256 != cp['last_record_sha256']:
                raise JournalError('mixed checkpoint terminal differs')
            if set(anchors)-{entry['name'] for entry in cp['segments']}:
                raise JournalError('custody source absent from checkpoint')
            # No reissuing seals, no checkpoint writes and no live append.
            # Only finish_retirement on pre-registered audited sources is allowed.
            for name in ('metadata.json', 'checkpoint.json'):
                with (directory/name).open('rb') as stream: os.fsync(stream.fileno())
            sync_directory(directory)
            return obj
        except BaseException:
            if obj is not None: obj.close()
            else: lock.close()
            raise
