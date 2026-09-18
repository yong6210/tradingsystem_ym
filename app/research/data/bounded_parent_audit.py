"""Parent audit phase deadline, including draining after live watchdog shutdown.

Keep frozen worker protocol/recovery semantics. A written checkpoint with a lost
acknowledgement remains on disk; a late parent phase never publishes success.
The synchronous syscall cannot be preempted: failure is reported on return.
"""
import asyncio
import time

from .background_incremental_audit import BackgroundIncrementalAudits
from .durable_capture_log import JournalError, encoded, file_hash
from .incremental_audit_protocol import build_request, validate_reply, worker_sources
from .incremental_feed_audit import MAX_CHECKPOINT_BYTES
from .sealed_segment_handoff import sha

PARENT_PHASE_LIMIT_NS = 500_000_000


class BoundedParentAudits(BackgroundIncrementalAudits):
    def __init__(self, *args, _parent_clock=time.monotonic_ns, **kwargs):
        super().__init__(*args, **kwargs)
        self._parent_clock = _parent_clock
        self.peak_parent_phase_ns = 0

    def _check_parent(self, job, began, stage):
        elapsed = self._parent_clock()-began
        if elapsed < 0:
            raise JournalError('parent phase clock regressed')
        self.peak_parent_phase_ns = max(self.peak_parent_phase_ns, elapsed)
        job['parent_phase_elapsed_ns'] = elapsed
        job['parent_phase_limit_ns'] = PARENT_PHASE_LIMIT_NS
        if elapsed > PARENT_PHASE_LIMIT_NS:
            job['parent_phase_failure_stage'] = stage
            raise JournalError(f'PARENT_AUDIT_PHASE_LIMIT:{stage}:{elapsed}ns')

    def _commit_reply(self, reply, request, deadline, job):
        began = self._parent_clock()
        self.budget.check(0)
        if time.monotonic_ns() >= deadline:
            raise TimeoutError('incremental audit response deadline')
        if worker_sources() != request['worker_sources']:
            raise JournalError('audit worker sources changed')
        doc, rss = validate_reply(reply, request, self.owner)
        encoded_base = encoded(request['base_document'])
        if (self.owner.path.stat().st_size != len(encoded_base)
                or file_hash(self.owner.path) != sha(encoded_base)):
            raise JournalError('parent audit checkpoint changed on disk')
        self.hook('after_audit_proposal_validated')
        if time.monotonic_ns() >= deadline:
            raise TimeoutError('incremental audit parent validation deadline')
        self._check_parent(job, began, 'validated')

        original_hook = self.owner.hook
        def guard(stage):
            original_hook(stage)
            self.hook(stage)
            self._check_parent(job, began, stage)
            if time.monotonic_ns() >= deadline:
                raise TimeoutError('incremental audit parent commit deadline')
        self.owner.hook = guard
        try:
            with self.budget.spend(job['reservation']):
                self.owner._write(doc['state'], revision=doc['revision'],
                                  previous=doc['previous_checkpoint_sha256'])
        finally:
            self.owner.hook = original_hook

        receipt = self.owner.receipt()
        if receipt['checkpoint_sha256'] != doc['checkpoint_sha256']:
            raise JournalError('parent generated checkpoint differs')
        if time.monotonic_ns() >= deadline:
            raise TimeoutError('incremental audit parent publication deadline')
        self._check_parent(job, began, 'before_receipt_publication')
        return receipt, rss

    async def _run(self):
        while True:
            stub, work = await self.queue.get()
            job = self.jobs[stub['job_id']]
            job.update(status='RUNNING', started_ns=time.monotonic_ns())
            try:
                deadline = job['submitted_ns']+int(self.limits.job_seconds*1e9)
                self.budget.check(0)
                if worker_sources() != self.source_binding:
                    raise JournalError('audit supervisor implementation changed')
                request = build_request(stub['job_id'], self.owner._doc,
                    work['operation'], work['inputs'], self.limits.rss_limit_bytes)
                left = (deadline-time.monotonic_ns())/1e9
                if left <= 0:
                    raise TimeoutError('incremental audit queue/request deadline')
                job['base_receipt'] = self.owner.receipt()
                async with asyncio.timeout(left):
                    # Reuse the bounded child I/O, cancellation and reap protocol.
                    reply = await self._execute(request, dict(segment=dict(bytes=MAX_CHECKPOINT_BYTES)))
                started = time.monotonic_ns()
                receipt, rss = self._commit_reply(reply, request, deadline, job)
                self.results[stub['job_id']] = receipt
                job.update(status='COMPLETE', receipt=receipt, peak_rss_bytes=rss,
                    reply_bytes=len(reply), parent_validation_and_commit_ns=time.monotonic_ns()-started)
            except asyncio.CancelledError:
                job['status'] = 'CANCELLED'
                self.fail('INCREMENTAL_AUDIT_CANCELLED')
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

    def snapshot(self):
        return super().snapshot() | dict(parent_phase_limit_ns=PARENT_PHASE_LIMIT_NS,
            peak_parent_phase_ns=self.peak_parent_phase_ns,
            parent_phase_checked_during_drain=True)
