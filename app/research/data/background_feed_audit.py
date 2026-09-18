"""Bounded, fail-closed audit subprocess supervisor for <=120s qualification."""
import asyncio
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
import time

from .background_audit_worker import checkpoint_hashes
from .durable_capture_log import decoded, integer, keys
from ..foundation.forward_data_contract import REQUIREMENTS, merge_intervals


def validate_result(result, scope, interval_limit):
    """Reject malformed IPC before retaining it or calling the coverage combiner."""
    if type(result) is not dict:
        raise ValueError('audit result object required')
    for name in ('errors', 'processor_errors'):
        if type(result[name]) is not list or any(type(x) is not str for x in result[name]):
            raise ValueError('audit errors must be strings')
    for name in ('clean_stop_audited', 'raw_prefix_valid', 'continuous_runtime_coverage_certified'):
        if type(result[name]) is not bool:
            raise ValueError('audit boolean required')
    if result['continuous_runtime_coverage_certified']:
        raise ValueError('audit cannot certify runtime coverage')
    if result['epoch'] is not None and (type(result['epoch']) is not str or not result['epoch']):
        raise ValueError('invalid audit epoch')
    for name in ('first_audited_publication_ns', 'last_audited_publication_ns'):
        if result[name] is not None: integer(result[name])
    first, last = result['first_audited_publication_ns'], result['last_audited_publication_ns']
    if (first is None) != (last is None) or (first is not None and last < first):
        raise ValueError('invalid audit publication range')
    for name in ('valid_batches', 'committed_raw_records', 'last_audited_sequence',
                 'unaudited_committed_records', 'valid_audit_bytes', 'unaudited_audit_bytes'):
        integer(result[name])
    if result['committed_raw_records'] != result['last_audited_sequence']+result['unaudited_committed_records']:
        raise ValueError('audit record count mismatch')
    keys(result['intervals'], ' '.join(REQUIREMENTS))
    total = 0
    for spans in [*result['intervals'].values(), result['exclusions']]:
        merge_intervals(spans, scope['window_start_ns'], scope['window_end_ns'])
        total += len(spans)
    if total > 2*interval_limit:
        raise ValueError('audit interval output bound')


@dataclass(frozen=True)
class AuditLimits:
    max_pending: int = 2  # Includes the running job.
    max_jobs: int = 7     # Initial attempt plus the frozen six retries.
    job_seconds: float = 15
    drain_seconds: float = 15
    max_reply_bytes: int = 2*1024**2
    max_total_reply_bytes: int = 8*1024**2
    max_intervals: int = 10_000
    rss_limit_bytes: int = 384*1024**2

    def __post_init__(self):
        defaults = dict(max_pending=2, max_jobs=7, max_reply_bytes=2*1024**2,
                        max_total_reply_bytes=8*1024**2, max_intervals=10_000,
                        rss_limit_bytes=384*1024**2)
        for key, maximum in defaults.items():
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError('invalid audit limit: '+key)
        for key in ('job_seconds', 'drain_seconds'):
            value = getattr(self, key)
            if type(value) not in (int, float) or not 0 < value <= 15:
                raise ValueError('invalid audit timeout: '+key)


class BackgroundAudits:
    def __init__(self, *, limits=None, _command=None):
        self.limits = limits or AuditLimits()
        self._command = _command or (lambda request: [sys.executable, '-m',
            'app.research.data.background_audit_worker', json.dumps(request)])
        self.failed = asyncio.Event()
        self.detected = None
        self.errors, self.results, self.jobs = [], {}, []
        self.queue = asyncio.Queue(maxsize=self.limits.max_pending)
        self.pending = self.peak_pending = self.reply_bytes = 0
        self.process = self.task = None
        self.closed = False

    def fail(self, message):
        if not self.failed.is_set():
            self.detected = (time.monotonic_ns(), time.time_ns())
            self.errors.append(str(message)[:1000])
            self.failed.set()

    def submit(self, directory, scope):
        if self.closed or self.failed.is_set():
            raise RuntimeError('audit supervisor unavailable')
        if self.pending >= self.limits.max_pending or len(self.jobs) >= self.limits.max_jobs:
            self.fail('AUDIT_BACKLOG_LIMIT')
            raise RuntimeError(self.errors[0])
        index = len(self.jobs)
        try:
            request = dict(job_id=index, directory=str(Path(directory).absolute()), scope=dict(scope),
                checkpoints=checkpoint_hashes(directory), max_intervals=self.limits.max_intervals,
                rss_limit_bytes=self.limits.rss_limit_bytes, max_reply_bytes=self.limits.max_reply_bytes)
            if len(json.dumps(request)) > 16_384:
                raise ValueError('oversized audit request')
        except Exception as exc:
            self.fail('AUDIT_SUBMISSION_FAILURE:'+str(exc))
            raise
        self.jobs.append(dict(job_id=index, submitted_ns=time.monotonic_ns(), status='QUEUED'))
        self.pending += 1
        self.peak_pending = max(self.peak_pending, self.pending)
        self.queue.put_nowait(request)
        if self.task is None:
            self.task = asyncio.create_task(self._run(), name='closed-epoch-auditor')

    async def _read(self, stream, limit):
        data = bytearray()
        while True:
            chunk = await stream.read(min(65_536, limit-len(data)+1))
            if not chunk:
                return bytes(data)
            data.extend(chunk)
            if len(data) > limit:
                raise ValueError('AUDIT_IPC_LIMIT')

    async def _execute(self, request):
        # Spawn and its cleanup remain owned by this task even on cancellation.
        spawn = asyncio.create_task(asyncio.create_subprocess_exec(*self._command(request),
            cwd=Path(__file__).resolve().parents[3], stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=65_536))
        readers = []
        try:
            try:
                self.process = await asyncio.shield(spawn)
            except asyncio.CancelledError:
                self.process = await spawn
                raise
            self.jobs[request['job_id']]['pid'] = self.process.pid
            readers = [asyncio.create_task(self._read(self.process.stdout, self.limits.max_reply_bytes)),
                       asyncio.create_task(self._read(self.process.stderr, 16_384)),
                       asyncio.create_task(self.process.wait())]
            stdout, stderr, code = await asyncio.gather(*readers)
            if code != 0:
                raise RuntimeError(f'AUDIT_WORKER_EXIT:{code}:'+stderr.decode(errors='replace')[-500:])
            if self.reply_bytes+len(stdout) > self.limits.max_total_reply_bytes:
                raise ValueError('AUDIT_TOTAL_IPC_LIMIT')
            reply = decoded(stdout)
            keys(reply, 'job_id checkpoints result peak_rss_bytes')
            integer(reply['job_id'])
            result = reply['result']
            if (reply['job_id'] != request['job_id'] or reply['checkpoints'] != request['checkpoints'] or
                    checkpoint_hashes(request['directory']) != request['checkpoints'] or
                    any(result[key] != value for key, value in request['scope'].items())):
                raise ValueError('AUDIT_REPLY_BINDING_MISMATCH')
            if (type(reply['peak_rss_bytes']) is not int or
                    not 0 < reply['peak_rss_bytes'] <= self.limits.rss_limit_bytes):
                raise ValueError('AUDIT_REPLY_SCHEMA_OR_MEMORY_LIMIT')
            validate_result(result, request['scope'], self.limits.max_intervals)
            if result['epoch'] is not None and any(row['epoch'] == result['epoch'] for row in self.results.values()):
                raise ValueError('AUDIT_REPEATED_EPOCH')
            self.reply_bytes += len(stdout)
            self.results[request['job_id']] = result
            self.jobs[request['job_id']]['peak_rss_bytes'] = reply['peak_rss_bytes']
            if (result['errors'] or result['processor_errors'] or not result['clean_stop_audited'] or
                    not result['raw_prefix_valid'] or result['status'] != 'AUDIT_PREFIX_COMPLETE'):
                raise ValueError('AUDIT_REPLAY_REJECTED')
        finally:
            if self.process is not None:
                if self.process.returncode is None:
                    try:
                        self.process.kill()
                    except ProcessLookupError:
                        pass
                # Drain bounded OS pipe buffers after canceling readers; never
                # communicate(), which would collect unbounded output in RAM.
                for task in readers:
                    if not task.done(): task.cancel()
                await asyncio.gather(*readers, return_exceptions=True)
                async def discard(stream):
                    while await stream.read(65_536):
                        pass
                await asyncio.gather(discard(self.process.stdout), discard(self.process.stderr))
                await self.process.wait()
                self.jobs[request['job_id']]['returncode'] = self.process.returncode
                self.process = None

    async def _run(self):
        while True:
            request = await self.queue.get()
            job = self.jobs[request['job_id']]
            job.update(status='RUNNING', started_ns=time.monotonic_ns())
            try:
                # Includes time already spent waiting in the bounded queue.
                left = self.limits.job_seconds-(time.monotonic_ns()-job['submitted_ns'])/1e9
                if left <= 0: raise TimeoutError('audit queue deadline')
                async with asyncio.timeout(left):
                    await self._execute(request)
                job['status'] = 'COMPLETE'
            except asyncio.CancelledError:
                job['status'] = 'CANCELLED'
                raise
            except Exception as exc:
                job['status'] = 'FAILED'
                self.fail(type(exc).__name__+':'+str(exc))
                return
            finally:
                job['completed_ns'] = time.monotonic_ns()
                self.pending -= 1
                self.queue.task_done()

    async def drain(self):
        if self.failed.is_set(): return
        joined = asyncio.create_task(self.queue.join())
        fault = asyncio.create_task(self.failed.wait())
        try:
            done, _ = await asyncio.wait([joined, fault], timeout=self.limits.drain_seconds,
                                         return_when=asyncio.FIRST_COMPLETED)
            if not done: self.fail('AUDIT_DRAIN_TIMEOUT')
        finally:
            for task in (joined, fault): task.cancel()
            await asyncio.gather(joined, fault, return_exceptions=True)

    async def close(self):
        self.closed = True
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        while not self.queue.empty():
            request = self.queue.get_nowait()
            self.jobs[request['job_id']]['status'] = 'CANCELLED'
            self.pending -= 1
            self.queue.task_done()

    def snapshot(self):
        return dict(limits=asdict(self.limits), jobs=list(self.jobs), peak_pending=self.peak_pending,
                    reply_bytes=self.reply_bytes, errors=list(self.errors),
                    failure_detected_ns=None if self.detected is None else self.detected[0],
                    closed=self.closed, child_reaped=self.process is None,
                    rss_guard='SAMPLED_CHILD_HIGH_WATER_50MS_NOT_HARD_ALLOCATION_CAP')
