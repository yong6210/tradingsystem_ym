"""Bounded sealed-segment compression; one read-only child, parent-only writes.

This component is not wired to the market collector. All synchronous parent
verification/fsync durations are measured and rejected if late; they cannot be
preempted by asyncio. Raw files, failed temporaries and orphan archives remain.
"""
import asyncio
from dataclasses import asdict, dataclass, replace
import gzip
import hashlib
import io
import math
import os
from pathlib import Path
import struct
import sys
import time
import uuid

from .durable_capture_log import JournalError, decoded, digest, encoded, integer, keys, sync_directory
from .reserved_feed_storage import ReservedStorageBudget
from .sealed_segment_handoff import certificate, sha
from .sealed_archive_worker import MAX_REQUEST, MAX_HEADER, OVERHEAD
from .segment_archive import SegmentArchive, MAX_DESCRIPTOR_BYTES, MAX_FILES, CHUNK


def advance_cursor(row, cursor):
    entry = row['segment']
    index = int(entry['name'][8:15])
    if (row['journal'] != cursor.journal or row['run_id'] != cursor.run_id or
            row['metadata_sha256'] != cursor.metadata_sha256 or index <= cursor.index or
            row['first_sequence'] != cursor.sequence+1 or
            row['previous_record_sha256'] != cursor.record_sha256 or
            row['previous_segment_sha256'] != cursor.segment_sha256 or
            row['previous_seal_sha256'] != cursor.seal_sha256):
        raise JournalError('archive ticket continuity mismatch')
    return replace(cursor, sequence=row['last_sequence'], record_sha256=row['last_record_sha256'],
                   segment_sha256=entry['sha256'], seal_sha256=row['seal_sha256'], index=index)


def validate_reply(data, request, row):
    if len(data) < 4: raise JournalError('archive IPC missing frame')
    length = struct.unpack('!I', data[:4])[0]
    if not 0 < length <= MAX_HEADER or 4+length > len(data):
        raise JournalError('archive IPC header boundary')
    header = decoded(data[4:4+length])
    keys(header, 'version job_id ticket_sha256 compressed_bytes compressed_sha256 peak_rss_bytes')
    if (type(header['version']) is not int or header['version'] != 1 or
            integer(header['job_id']) != request['job_id'] or
            digest(header['ticket_sha256']) != sha(request['certificate'].encode())):
        raise JournalError('archive IPC binding mismatch')
    if not 0 < integer(header['peak_rss_bytes'], 1) <= request['rss_limit_bytes']:
        raise JournalError('archive worker RSS bound')
    compressed = data[4+length:]
    if (not 0 < integer(header['compressed_bytes'], 1) <= row['segment']['bytes']+OVERHEAD or
            len(compressed) != header['compressed_bytes'] or
            digest(header['compressed_sha256']) != sha(compressed)):
        raise JournalError('archive IPC payload mismatch')
    # Independent parent verification: never trust the child's success flag/hash.
    total, raw_hash = 0, hashlib.sha256()
    with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode='rb') as reader:
        while chunk := reader.read(min(CHUNK, row['segment']['bytes']-total+1)):
            total += len(chunk)
            if total > row['segment']['bytes']: raise JournalError('archive expansion bound')
            raw_hash.update(chunk)
    if total != row['segment']['bytes'] or raw_hash.hexdigest() != row['segment']['sha256']:
        raise JournalError('archive restored bytes mismatch')
    return compressed, header


class ParentArchiveStore(SegmentArchive):
    def __init__(self, directory, *, budget):
        if not isinstance(budget, ReservedStorageBudget):
            raise JournalError('reservation-aware parent budget required')
        super().__init__(directory, budget=budget)
        self.file_count = len(list(self.directory.iterdir()))

    def publish_reply(self, row, compressed, *, reservation, deadline_ns, hook=lambda stage: None):
        def timely():
            if time.monotonic_ns() >= deadline_ns: raise TimeoutError('archive parent publication deadline')
        timely()
        identity = dict(run_id=row['run_id'], journal=row['journal'], segment_name=row['segment']['name'],
            raw_bytes=row['segment']['bytes'], raw_sha256=row['segment']['sha256'],
            metadata_sha256=row['metadata_sha256'])
        witness = {k:row[k] for k in ('checkpoint_sha256','first_sequence','last_sequence','last_record_sha256')}
        archive_id = sha(encoded(identity))
        with self.budget.spend(reservation):
            if (self.directory/(archive_id+'.json')).exists():
                existing = self._descriptor(archive_id)
                if (existing['identity'] != identity or any(existing['witness'][k] != witness[k]
                        for k in ('first_sequence','last_sequence','last_record_sha256'))):
                    raise JournalError('registered archive differs from ticket')
                self._sync_registered(existing)
                timely()
                return existing
            if self.file_count+3 > MAX_FILES: raise JournalError('archive file-count headroom')
            token = uuid.uuid4().hex
            temporary = self.directory/('.'+token+'.gz.tmp')
            target = self.directory/(token+'.jsonl.gz')
            with temporary.open('xb', buffering=0) as stream:
                for offset in range(0, len(compressed), CHUNK):
                    timely()
                    self.budget.append(stream, compressed[offset:offset+CHUNK])
                    hook('after_parent_archive_chunk')
                os.fsync(stream.fileno())
            hook('after_parent_archive_fsync'); timely()
            descriptor = dict(version=1, archive_id=archive_id, identity=identity, witness=witness,
                codec='gzip', level=1, compressed_name=target.name, compressed_bytes=len(compressed),
                compressed_sha256=sha(compressed), originals_retained=True)
            descriptor['descriptor_sha256'] = sha(encoded(descriptor))
            if len(encoded(descriptor)) > MAX_DESCRIPTOR_BYTES: raise JournalError('archive descriptor size')
            # Verify persisted bytes as well as IPC bytes before publishing.
            with self._verified_file(descriptor | dict(compressed_name=temporary.name)): pass
            hook('after_parent_archive_verify'); timely()
            if target.exists(): raise JournalError('archive target already exists')
            os.replace(temporary, target)
            self.budget._refresh(temporary); self.budget._refresh(target)
            hook('after_parent_archive_rename')
            sync_directory(self.directory)
            hook('after_parent_archive_directory_fsync'); timely()
            stages = {'after_checkpoint_fsync':'after_parent_manifest_fsync',
                      'after_checkpoint_replace':'after_parent_manifest_replace',
                      'after_directory_fsync':'after_parent_manifest_directory_fsync'}
            self.budget.atomic_json(self.directory/(archive_id+'.json'), descriptor,
                                    lambda stage: hook(stages[stage]))
            self.file_count += 2
            timely()
            return descriptor


@dataclass(frozen=True)
class ArchiveLimits:
    max_pending: int = 2
    max_jobs: int = 64
    job_seconds: float = 15
    drain_seconds: float = 15
    rss_limit_bytes: int = 384*1024**2

    def __post_init__(self):
        for key, maximum in dict(max_pending=2, max_jobs=64, rss_limit_bytes=384*1024**2).items():
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= maximum: raise ValueError('invalid '+key)
        for key in ('job_seconds','drain_seconds'):
            value = getattr(self, key)
            if type(value) not in (int,float) or not math.isfinite(value) or not 0 < value <= 15:
                raise ValueError('invalid '+key)


class BackgroundArchives:
    def __init__(self, directory, *, budget, cursor, limits=None, _command=None, _hook=lambda stage: None):
        if (Path(cursor.root) != budget.root or cursor.run_id != budget.contract['run_id']):
            raise JournalError('archive cursor storage identity mismatch')
        self.store = ParentArchiveStore(directory, budget=budget)
        self.budget, self.cursor = budget, cursor
        self.limits = limits or ArchiveLimits()
        self.command = _command or [sys.executable, '-m', 'app.research.data.sealed_archive_worker']
        self.hook = _hook
        self.queue = asyncio.Queue(maxsize=self.limits.max_pending)
        self.failed = asyncio.Event()
        self.errors, self.jobs, self.results = [], [], {}
        self.pending = self.peak_pending = 0
        self.detected_ns = None
        self.process = self.task = None
        self.closed = False
        self.reservation_prefix = uuid.uuid4().hex

    def fail(self, message):
        if not self.failed.is_set():
            self.detected_ns = time.monotonic_ns()
            self.errors.append(str(message)[:1000])
            self.failed.set()
        self.budget.failed = True
        if (self.task is not None and self.task is not asyncio.current_task() and
                not self.task.done() and not self.task.cancelling()):
            self.task.cancel()

    def submit(self, ticket):
        if self.closed or self.failed.is_set(): raise JournalError('archive supervisor unavailable')
        key = None
        try:
            self.budget.check(0)
            if self.pending >= self.limits.max_pending or len(self.jobs) >= self.limits.max_jobs:
                raise JournalError('ARCHIVE_BACKLOG_LIMIT')
            row = certificate(ticket.certificate)
            next_cursor = advance_cursor(row, self.cursor)
            index = len(self.jobs)
            cursor = asdict(self.cursor); cursor['root'] = str(cursor['root'])
            request = dict(job_id=index, cursor=cursor, certificate=ticket.certificate.decode(),
                           rss_limit_bytes=self.limits.rss_limit_bytes)
            if len(encoded(request)) > MAX_REQUEST: raise JournalError('archive request bound')
            key = self.reservation_prefix+':'+str(index)
            reserved = row['segment']['bytes']+OVERHEAD+MAX_DESCRIPTOR_BYTES
            self.budget.reserve(key, reserved)
            submitted = time.monotonic_ns()
            self.jobs.append(dict(job_id=index, status='QUEUED', submitted_ns=submitted,
                                  reserved_bytes=reserved, reservation=key))
            self.queue.put_nowait((request, row))
            self.cursor = next_cursor
            self.pending += 1
            self.peak_pending = max(self.peak_pending, self.pending)
            if self.task is None: self.task = asyncio.create_task(self._run(), name='sealed-segment-archiver')
            return index
        except BaseException as exc:
            if key is not None: self.budget.release(key)
            self.fail('ARCHIVE_SUBMISSION:'+type(exc).__name__+':'+str(exc))
            raise

    async def _read(self, stream, limit):
        data = bytearray()
        while chunk := await stream.read(min(CHUNK, limit-len(data)+1)):
            data.extend(chunk)
            if len(data) > limit: raise JournalError('ARCHIVE_IPC_LIMIT')
        return bytes(data)

    async def _execute(self, request, row):
        spawn = asyncio.create_task(asyncio.create_subprocess_exec(*self.command,
            cwd=Path(__file__).resolve().parents[3], env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=CHUNK))
        tasks = []
        try:
            try: self.process = await asyncio.shield(spawn)
            except asyncio.CancelledError:
                self.process = await spawn
                raise
            self.jobs[request['job_id']]['pid'] = self.process.pid
            async def write_request():
                self.process.stdin.write(encoded(request))
                await self.process.stdin.drain()
                self.process.stdin.close()
            bound = row['segment']['bytes']+OVERHEAD+MAX_HEADER+4
            tasks = [asyncio.create_task(self._read(self.process.stdout, bound)),
                     asyncio.create_task(self._read(self.process.stderr, 16384)),
                     asyncio.create_task(self.process.wait()), asyncio.create_task(write_request())]
            stdout, stderr, code, _ = await asyncio.gather(*tasks)
            if code != 0 or stderr:
                raise JournalError(f'ARCHIVE_WORKER_EXIT:{code}:'+stderr.decode(errors='replace')[-500:])
            return stdout
        finally:
            if self.process is not None:
                if self.process.returncode is None:
                    try: self.process.kill()
                    except ProcessLookupError: pass
                if self.process.stdin is not None: self.process.stdin.close()
                for task in tasks:
                    if not task.done(): task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                async def discard(stream):
                    while await stream.read(CHUNK): pass
                await asyncio.gather(discard(self.process.stdout), discard(self.process.stderr))
                await self.process.wait()
                self.jobs[request['job_id']]['returncode'] = self.process.returncode
                self.process = None

    async def _run(self):
        while True:
            request, row = await self.queue.get()
            job = self.jobs[request['job_id']]
            job.update(status='RUNNING', started_ns=time.monotonic_ns())
            try:
                deadline = job['submitted_ns']+int(self.limits.job_seconds*1e9)
                left = (deadline-time.monotonic_ns())/1e9
                if left <= 0: raise TimeoutError('archive queue deadline')
                async with asyncio.timeout(left):
                    reply = await self._execute(request, row)
                self.budget.check(0)
                started = time.monotonic_ns()
                compressed, header = validate_reply(reply, request, row)
                if time.monotonic_ns() >= deadline: raise TimeoutError('archive parent validation deadline')
                descriptor = self.store.publish_reply(row, compressed, reservation=job['reservation'],
                                                       deadline_ns=deadline, hook=self.hook)
                job.update(parent_validation_and_publication_ns=time.monotonic_ns()-started,
                           peak_rss_bytes=header['peak_rss_bytes'], compressed_bytes=len(compressed), status='COMPLETE')
                self.results[request['job_id']] = descriptor
            except asyncio.CancelledError:
                job['status'] = 'CANCELLED'
                self.fail('ARCHIVE_CANCELLED')
                raise
            except Exception as exc:
                job['status'] = 'FAILED'
                self.fail(type(exc).__name__+':'+str(exc))
                return
            finally:
                self.budget.release(job['reservation'])
                job['completed_ns'] = time.monotonic_ns()
                self.pending -= 1
                self.queue.task_done()

    async def finish(self):
        """Drain, close/reap, then raise if anything was omitted or rejected."""
        joined = asyncio.create_task(self.queue.join())
        fault = asyncio.create_task(self.failed.wait())
        try:
            done, _ = await asyncio.wait([joined, fault], timeout=self.limits.drain_seconds,
                                         return_when=asyncio.FIRST_COMPLETED)
            if not done: self.fail('ARCHIVE_DRAIN_TIMEOUT')
        finally:
            for task in (joined, fault): task.cancel()
            await asyncio.gather(joined, fault, return_exceptions=True)
            await self.close()
        if self.failed.is_set(): raise JournalError(self.errors[0])
        if len(self.results) != len(self.jobs): raise JournalError('archive results incomplete')
        return dict(self.results)

    async def close(self):
        self.closed = True
        if self.pending: self.fail('ARCHIVE_CLOSED_WITH_PENDING_JOBS')
        try:
            if self.task is not None:
                if not self.task.done() and not self.task.cancelling(): self.task.cancel()
                # Do not send another cancellation into the child's reap/discard
                # finally block, even if the caller cancels this close operation.
                completion = asyncio.gather(self.task, return_exceptions=True)
                try:
                    await asyncio.shield(completion)
                except asyncio.CancelledError:
                    await completion
                    raise
        finally:
            while not self.queue.empty():
                request, _ = self.queue.get_nowait()
                job = self.jobs[request['job_id']]
                job['status'] = 'CANCELLED'
                self.budget.release(job['reservation'])
                self.pending -= 1
                self.queue.task_done()

    def snapshot(self):
        return dict(limits=asdict(self.limits), jobs=list(self.jobs), errors=list(self.errors),
            pending=self.pending, peak_pending=self.peak_pending, closed=self.closed,
            child_reaped=self.process is None, failure_detected_ns=self.detected_ns,
            storage=self.budget.snapshot(), child_writes_capture=False,
            rss_guard='SAMPLED_CHILD_HIGH_WATER_50MS_NOT_HARD_CAP',
            synchronous_parent_work='MEASURED_AND_LATE_FAILURE_NOT_PREEMPTIBLE')
