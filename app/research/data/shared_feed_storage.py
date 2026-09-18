"""Single-owner run storage: aggregate logical bytes, segmented raw/audit logs.

All cooperating writes below share one budget. The root must be exclusively
owned, on one local filesystem; external edits and power-loss survival are not
certified. Physical free space is checked independently of logical file bytes.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import shutil
import stat
import time
import uuid

from .durable_capture_log import (
    DurableCaptureLog, CommitReceipt, JournalError, ZERO, encoded, decoded,
    integer, keys, file_hash, lock_directory, sync_directory, inspect_locked,
)


class SharedStorageBudget:
    @classmethod
    def create(cls, root, *, run_id, max_bytes, min_free_bytes):
        integer(max_bytes, 1)
        integer(min_free_bytes)
        if type(run_id) is not str or not run_id or len(run_id) > 128:
            raise ValueError('bounded run ID required')
        root = Path(root).absolute()
        root.mkdir(parents=True, exist_ok=False)
        obj = cls(root, dict(version=1, run_id=run_id, max_bytes=max_bytes,
                            min_free_bytes=min_free_bytes))
        try:
            obj.atomic_json(root/'storage.json', obj.contract)
            sync_directory(root.parent)
            return obj
        except BaseException:
            obj.close()
            raise

    @classmethod
    def resume(cls, root, *, run_id, max_bytes, min_free_bytes):
        # Caller supplies the previously fixed contract; a changed on-disk cap
        # cannot silently replenish this run's budget.
        integer(max_bytes, 1)
        integer(min_free_bytes)
        root = Path(root).absolute()
        expected = dict(version=1, run_id=run_id, max_bytes=max_bytes, min_free_bytes=min_free_bytes)
        obj = cls(root, expected)
        try:
            path = root/'storage.json'
            if path.stat().st_size > 4096 or decoded(path.read_bytes()) != expected:
                raise JournalError('storage contract mismatch')
            obj.check(0)
            return obj
        except BaseException:
            obj.close()
            raise

    def __init__(self, root, contract):
        if root.is_symlink() or root.resolve() != root:
            raise JournalError('canonical storage root required')
        self.root, self.contract = root, contract
        self.lock = lock_directory(root)
        self.failed = self.closed = False
        self.sizes = {}
        self.used = self.peak = 0
        try:
            self.reconcile()
        except BaseException:
            self.lock.close()
            raise

    def path(self, path):
        path = Path(path).absolute()
        if not path.is_relative_to(self.root) or path.resolve() != path:
            raise JournalError('path outside owned storage or symlink')
        return path

    def reconcile(self):
        """Startup/epoch boundary inventory, including unknown tails and temps."""
        if self.closed or self.failed:
            raise JournalError('storage closed or failed')
        sizes = {}
        device = self.root.stat().st_dev
        for path in self.root.rglob('*'):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or info.st_dev != device:
                raise JournalError('symlink or other filesystem in run storage')
            if stat.S_ISREG(info.st_mode):
                sizes[path] = info.st_size
            elif not stat.S_ISDIR(info.st_mode):
                raise JournalError('nonregular run storage entry')
        self.sizes, self.used = sizes, sum(sizes.values())
        self.peak = max(self.peak, self.used)
        self.check(0)

    def check(self, growth):
        integer(growth)
        if self.closed or self.failed:
            raise JournalError('storage closed or failed')
        if self.used+growth > self.contract['max_bytes']:
            raise JournalError('aggregate run byte budget exceeded')
        if shutil.disk_usage(self.root).free < self.contract['min_free_bytes']+growth+65536:
            raise JournalError('aggregate free-space reserve would be crossed')

    def _refresh(self, path):
        old = self.sizes.get(path, 0)
        size = path.stat().st_size if path.exists() else 0
        self.sizes[path] = size
        self.used += size-old
        self.peak = max(self.peak, self.used)
        if not path.exists():
            self.sizes.pop(path, None)

    @contextmanager
    def mutation(self):
        try:
            self.check(0)
            yield
        except BaseException:
            self.failed = True
            raise

    def append(self, stream, data):
        path = self.path(stream.name)
        with self.mutation():
            # Unbuffered append-only streams; no unaccounted buffered writes.
            if stream.tell() != self.sizes.get(path, 0):
                raise JournalError('owned file changed or write position regressed')
            self.check(len(data))
            try:
                if stream.write(data) != len(data):
                    raise OSError('short budgeted write')
            finally:
                self._refresh(path)  # Includes bytes left by a short/failed write.

    def atomic_json(self, path, value, hook=lambda stage: None):
        path = self.path(path)
        data = encoded(value)
        with self.mutation():
            # Reserve the full replacement while the previous file still exists.
            self.check(len(data))
            temp = path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
            with temp.open('xb', buffering=0) as stream:
                self.append(stream, data)
                os.fsync(stream.fileno())
            hook('after_checkpoint_fsync')
            os.replace(temp, path)
            self._refresh(temp)
            self._refresh(path)
            hook('after_checkpoint_replace')
            sync_directory(path.parent)
            hook('after_directory_fsync')

    def snapshot(self):
        return dict(used_bytes=self.used, peak_bytes=self.peak,
                    max_bytes=self.contract['max_bytes'], min_free_bytes=self.contract['min_free_bytes'],
                    failed=self.failed, scope='ALL_RUN_REGULAR_FILES_INCLUDING_TEMPORARIES',
                    accounting='LOGICAL_BYTES_PHYSICAL_FREE_SPACE_CHECKED_SEPARATELY')

    def close(self):
        if not self.closed:
            self.lock.close()
            self.closed = True


class BudgetedJournal(DurableCaptureLog):
    """Frozen journal format with all writes routed through the run budget."""
    @classmethod
    def create(cls, directory, *, budget, run_id, rotation_bytes=128*1024**2,
               max_record_bytes=4*1024**2, hook=lambda stage: None):
        integer(rotation_bytes, 512)
        integer(max_record_bytes, 1)
        if max_record_bytes > rotation_bytes-256 or run_id != budget.contract['run_id']:
            raise JournalError('journal bounds or run identity differ')
        directory = budget.path(directory)
        with budget.mutation():
            directory.mkdir()
            lock = lock_directory(directory)
            try:
                meta = dict(version=1, run_id=run_id, rotation_bytes=rotation_bytes,
                            max_record_bytes=max_record_bytes, max_total_bytes=budget.contract['max_bytes'],
                            min_free_bytes=budget.contract['min_free_bytes'])
                budget.atomic_json(directory/'metadata.json', meta)
                cp = dict(version=1, run_id=run_id, metadata_sha256=file_hash(directory/'metadata.json'),
                          last_sequence=0, last_record_sha256=ZERO, segments=[])
                budget.atomic_json(directory/'checkpoint.json', cp)
                sync_directory(directory.parent)
                obj = cls(directory, lock, meta, cp, hook)
                obj.budget = budget
                return obj
            except BaseException:
                lock.close()
                raise

    @classmethod
    def resume(cls, directory, *, budget, hook=lambda stage: None):
        directory = budget.path(directory)
        budget.reconcile()
        with budget.mutation():
            lock = lock_directory(directory)
            try:
                meta, cp, recovery = inspect_locked(directory)
                if (meta['run_id'] != budget.contract['run_id'] or
                        meta['max_total_bytes'] != budget.contract['max_bytes'] or
                        meta['min_free_bytes'] != budget.contract['min_free_bytes']):
                    raise JournalError('journal and aggregate contract differ')
                for name in ['metadata.json', 'checkpoint.json']+[e['name'] for e in cp['segments']]:
                    with (directory/name).open('rb') as stream:
                        os.fsync(stream.fileno())
                sync_directory(directory)
                obj = cls(directory, lock, meta, cp, hook)
                obj.budget, obj.recovery = budget, recovery
                return obj
            except BaseException:
                lock.close()
                raise

    def _space(self, extra):
        self.budget.check(extra)

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
        self.budget.append(self.active, header)
        self.active_hash = hashlib.sha256(header)
        self.entries.append(dict(name=name, bytes=len(header), sha256=self.active_hash.hexdigest()))
        self.total_bytes += len(header)
        self.dirty.add(name)

    def append(self, payload):
        self._writable()
        with self.budget.mutation():
            try:
                if type(payload) is not dict:
                    raise JournalError('payload object required')
                body = dict(sequence=self.sequence+1, epoch=self.epoch,
                            previous_record_sha256=self.record_hash, payload=payload)
                identity = hashlib.sha256(encoded(body)).hexdigest()
                line = encoded(body | dict(sha256=identity))
                if len(line) > self.meta['max_record_bytes']:
                    raise JournalError('record exceeds bound')
                if self.active is None or self.entries[-1]['bytes']+len(line) > self.meta['rotation_bytes']:
                    self._new_segment()
                if self.entries[-1]['bytes']+len(line) > self.meta['rotation_bytes']:
                    raise JournalError('record cannot fit beside segment header')
                self.budget.append(self.active, line)
                self.active_hash.update(line)
                self.entries[-1]['bytes'] += len(line)
                self.entries[-1]['sha256'] = self.active_hash.hexdigest()
                self.dirty.add(self.entries[-1]['name'])
                self.total_bytes += len(line)
                self.sequence, self.record_hash = body['sequence'], identity
                self.hook('after_append')
                return self.sequence
            except BaseException:
                self.failed = True
                raise

    def commit(self):
        self._writable()
        with self.budget.mutation():
            if not self.dirty:
                return self.receipt
            try:
                for name in sorted(self.dirty):
                    with (self.directory/name).open('rb') as stream:
                        os.fsync(stream.fileno())
                sync_directory(self.directory)
                self.hook('after_raw_fsync')
                cp = dict(self.cp, last_sequence=self.sequence, last_record_sha256=self.record_hash,
                          segments=[dict(e) for e in self.entries])
                if len(encoded(cp)) > 4*1024**2:
                    raise JournalError('checkpoint metadata bound exceeded')
                self.budget.atomic_json(self.directory/'checkpoint.json', cp, self.hook)
                self.cp = cp
                self.receipt = CommitReceipt(self.sequence, self.record_hash, time.monotonic_ns())
                self.dirty.clear()
                return self.receipt
            except BaseException:
                self.failed = True
                raise

    def publication_fence(self):
        self.budget.check(0)
        return super().publication_fence()


class SegmentedAudit:
    def __init__(self, directory, *, budget, rotation_bytes=32*1024**2, max_record_bytes=4*1024**2):
        self.journal = BudgetedJournal.create(directory, budget=budget, run_id=budget.contract['run_id'],
                rotation_bytes=rotation_bytes, max_record_bytes=max_record_bytes)
        self.lines = self.bytes = 0

    def append(self, value):
        self.journal.append(value)
        receipt = self.journal.commit()
        self.lines += 1
        self.bytes = self.journal.total_bytes
        return receipt.available_monotonic_ns

    def close(self):
        self.journal.close()
