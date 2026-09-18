"""Bounded replay worker, parent-owned checkpoint and shared space reservations.

Reuses the frozen archive supervisor's bounded process I/O and cancellation
ownership. No collector integration or automatic post-crash job resubmission.
"""
import asyncio
from dataclasses import asdict
from pathlib import Path
import sys
import time
import uuid

from .archive_segment_reader import cursor_dict,restore_cursor
from .background_segment_archive import BackgroundArchives,ArchiveLimits,advance_cursor
from .durable_capture_log import JournalError,decoded,encoded,file_hash
from .incremental_feed_audit import MAX_CHECKPOINT_BYTES
from .incremental_audit_protocol import build_request,validate_inputs,validate_reply,worker_sources
from .reserved_feed_storage import ReservedStorageBudget
from .sealed_segment_handoff import certificate,sha


class BackgroundIncrementalAudits(BackgroundArchives):
    def __init__(self,owner,*,limits=None,_command=None,_hook=lambda stage:None):
        if not isinstance(owner.budget,ReservedStorageBudget):raise JournalError('reservation-aware audit owner required')
        owner.receipt();owner.budget.check(0)
        self.owner,self.budget=owner,owner.budget
        self.limits=limits or ArchiveLimits()
        self.command=_command or [sys.executable,'-m','app.research.data.incremental_audit_worker']
        self.hook=_hook
        self.queue=asyncio.Queue(maxsize=self.limits.max_pending)
        self.failed=asyncio.Event();self.errors,self.jobs,self.results=[],[],{}
        self.pending=self.peak_pending=0;self.detected_ns=None
        self.process=self.task=None;self.closed=False
        self.reservation_prefix=uuid.uuid4().hex
        self.planned_audit_cursor=restore_cursor(owner._doc['state']['audit_cursor'])
        self.final_submitted=False
        self.source_binding=worker_sources()

    def fail(self,message):
        self.owner.failed=True
        super().fail(str(message).replace('ARCHIVE','INCREMENTAL_AUDIT'))

    def submit(self,audit_ref,raw_refs):
        return self._submit('advance',dict(audit_ref=audit_ref,raw_refs=raw_refs))

    def submit_finalize(self,*,raw_cursor,audit_cursor):
        return self._submit('finalize',dict(raw_cursor=cursor_dict(raw_cursor),audit_cursor=cursor_dict(audit_cursor)))

    def _submit(self,operation,inputs):
        if self.closed or self.failed.is_set():raise JournalError('incremental audit supervisor unavailable')
        key=None
        try:
            asyncio.get_running_loop()
            self.budget.check(0)
            if self.pending>=self.limits.max_pending or len(self.jobs)>=self.limits.max_jobs:
                raise JournalError('INCREMENTAL_AUDIT_BACKLOG_LIMIT')
            if self.final_submitted:raise JournalError('audit already queued finalization')
            validate_inputs(operation,inputs)
            owned=decoded(encoded(inputs))
            next_cursor=self.planned_audit_cursor
            if operation=='advance':
                next_cursor=advance_cursor(certificate(owned['audit_ref']['certificate'].encode()),next_cursor)
            elif owned['audit_cursor']!=cursor_dict(next_cursor):raise JournalError('queued final audit cursor differs')
            index=len(self.jobs);key=self.reservation_prefix+':'+str(index)
            self.budget.reserve(key,MAX_CHECKPOINT_BYTES)
            self.jobs.append(dict(job_id=index,operation=operation,status='QUEUED',submitted_ns=time.monotonic_ns(),
                                  reservation=key,reserved_bytes=MAX_CHECKPOINT_BYTES))
            self.queue.put_nowait((dict(job_id=index),dict(operation=operation,inputs=owned)))
            self.planned_audit_cursor=next_cursor;self.final_submitted=operation=='finalize'
            self.pending+=1;self.peak_pending=max(self.peak_pending,self.pending)
            if self.task is None:self.task=asyncio.create_task(self._run(),name='incremental-feed-auditor')
            return index
        except BaseException as exc:
            if key is not None:self.budget.release(key)
            self.fail('INCREMENTAL_AUDIT_SUBMISSION:'+type(exc).__name__+':'+str(exc))
            raise

    async def _run(self):
        while True:
            stub,work=await self.queue.get();job=self.jobs[stub['job_id']]
            job.update(status='RUNNING',started_ns=time.monotonic_ns())
            try:
                deadline=job['submitted_ns']+int(self.limits.job_seconds*1e9)
                self.budget.check(0)
                if worker_sources()!=self.source_binding:raise JournalError('audit supervisor implementation changed')
                request=build_request(stub['job_id'],self.owner._doc,work['operation'],work['inputs'],self.limits.rss_limit_bytes)
                left=(deadline-time.monotonic_ns())/1e9
                if left<=0:raise TimeoutError('incremental audit queue/request deadline')
                job['base_receipt']=self.owner.receipt()
                async with asyncio.timeout(left):
                    # Frozen process adapter: bounds stdout by 8MiB+80KiB+4,
                    # stderr16KiB; stdin is our independently bounded request.
                    reply=await self._execute(request,dict(segment=dict(bytes=MAX_CHECKPOINT_BYTES)))
                started=time.monotonic_ns();self.budget.check(0)
                if time.monotonic_ns()>=deadline:raise TimeoutError('incremental audit response deadline')
                if worker_sources()!=request['worker_sources']:raise JournalError('audit worker sources changed')
                doc,rss=validate_reply(reply,request,self.owner)
                encoded_base=encoded(request['base_document'])
                if (self.owner.path.stat().st_size!=len(encoded_base) or file_hash(self.owner.path)!=sha(encoded_base)):
                    raise JournalError('parent audit checkpoint changed on disk')
                self.hook('after_audit_proposal_validated')
                if time.monotonic_ns()>=deadline:raise TimeoutError('incremental audit parent validation deadline')
                original_hook=self.owner.hook
                def guard(stage):
                    original_hook(stage);self.hook(stage)
                    if time.monotonic_ns()>=deadline:raise TimeoutError('incremental audit parent commit deadline')
                self.owner.hook=guard
                try:
                    with self.budget.spend(job['reservation']):
                        self.owner._write(doc['state'],revision=doc['revision'],previous=doc['previous_checkpoint_sha256'])
                finally:self.owner.hook=original_hook
                receipt=self.owner.receipt()
                if receipt['checkpoint_sha256']!=doc['checkpoint_sha256']:raise JournalError('parent generated checkpoint differs')
                if time.monotonic_ns()>=deadline:raise TimeoutError('incremental audit parent publication deadline')
                self.results[stub['job_id']]=receipt
                job.update(status='COMPLETE',receipt=receipt,peak_rss_bytes=rss,
                    reply_bytes=len(reply),parent_validation_and_commit_ns=time.monotonic_ns()-started)
            except asyncio.CancelledError:
                job['status']='CANCELLED';self.fail('INCREMENTAL_AUDIT_CANCELLED');raise
            except Exception as exc:
                job['status']='FAILED';self.fail(type(exc).__name__+':'+str(exc));return
            finally:
                self.budget.release(job['reservation']);job['completed_ns']=time.monotonic_ns()
                self.pending-=1;self.queue.task_done()

    def snapshot(self):
        return dict(limits=asdict(self.limits),jobs=list(self.jobs),errors=list(self.errors),
            pending=self.pending,peak_pending=self.peak_pending,closed=self.closed,
            child_reaped=self.process is None,failure_detected_ns=self.detected_ns,
            storage=self.budget.snapshot(),child_writes_capture=False,parent_only_checkpoint_commit=True,
            source_binding=dict(self.source_binding),rss_guard='SAMPLED_CHILD_HIGH_WATER_50MS_NOT_HARD_CAP',
            parent_repeats_market_replay=False,parent_work='STRUCTURAL_VALIDATION_AND_FSYNC_NOT_PREEMPTIBLE')
