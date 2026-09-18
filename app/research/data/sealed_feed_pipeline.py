"""Single admission owner for sealed feed compression and incremental replay.

Two global storage reservations, bounded units, no raw deletion or live restart.
Only completed gzip registrations feed the auditor; source hashes remain pinned
by the frozen archive/replay components. Cooperative event-loop ownership only.
"""
import asyncio
from dataclasses import asdict, dataclass
import math
import time

from .archive_segment_reader import segment_ref
from .background_incremental_audit import BackgroundIncrementalAudits
from .background_segment_archive import BackgroundArchives, ArchiveLimits, advance_cursor
from .durable_capture_log import JournalError, integer
from .incremental_feed_audit import IncrementalFeedAudit, make_contract
from .sealed_segment_handoff import certificate
from .sealed_archive_worker import OVERHEAD
from .segment_archive import MAX_DESCRIPTOR_BYTES
from .sealed_segment_handoff import MAX_SEGMENT_BYTES


@dataclass(frozen=True)
class PipelineLimits:
    seal_seconds: float = 2
    unit_seconds: float = 15
    drain_seconds: float = 15
    max_pending_units: int = 4
    max_units: int = 62
    max_epochs: int = 8

    def __post_init__(self):
        for name, low, high in [('seal_seconds', .05, 2), ('unit_seconds', .01, 15), ('drain_seconds', .01, 15)]:
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError('pipeline '+name+' bound')
        for name, high in [('max_pending_units', 4), ('max_units', 62), ('max_epochs', 8)]:
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= high:
                raise ValueError('pipeline '+name+' bound')


class SealedFeedPipeline:
    def __init__(self, budget, *, limits=None, worker_limits=None,
                 _archive_factory=BackgroundArchives, _audit_factory=BackgroundIncrementalAudits):
        self.budget = budget
        self.limits = limits or PipelineLimits()
        self.worker_limits = worker_limits or ArchiveLimits()
        self.archive_factory, self.audit_factory = _archive_factory, _audit_factory
        self.channels, self.units, self.errors = [], [], []
        self.failed = asyncio.Event()
        self.detected = None
        self.task = self.close_task = None
        self.closed = False
        self.peak_pending_units = self.peak_reservations = 0
        self.audit_archive_overlap_samples = 0
        # Admission before the first transport request. Actual reservations are
        # still checked again against the live aggregate inventory at dispatch.
        budget.check(2*(MAX_SEGMENT_BYTES+OVERHEAD+MAX_DESCRIPTOR_BYTES))

    def managers(self):
        return [m for c in self.channels for m in (c['raw'], c['audit_log'], c['auditor'])]

    def fail(self, reason):
        if not self.failed.is_set():
            self.detected = (time.monotonic_ns(), time.time_ns())
            self.errors.append(str(reason)[:1000])
            self.failed.set()
        self.budget.failed = True
        for manager in self.managers():
            if not manager.failed.is_set():
                manager.fail('PIPELINE_FAILURE:'+str(reason)[:500])

    def check(self):
        if self.closed or self.failed.is_set():
            raise JournalError('sealed pipeline unavailable')
        self.budget.check(0)

    def add_epoch(self, directory, raw_cursor, audit_cursor, scope):
        self.check()
        if len(self.channels) >= self.limits.max_epochs:
            self.fail('PIPELINE_EPOCH_LIMIT')
            raise JournalError(self.errors[0])
        contract = make_contract(raw_cursor, audit_cursor, **scope)
        owner = IncrementalFeedAudit.create(directory/'replay-state', budget=self.budget, contract=contract)
        # Constructors create no child processes. Clean the state lock if setup fails.
        try:
            raw = self.archive_factory(directory/'raw-archives', budget=self.budget,
                                       cursor=raw_cursor, limits=self.worker_limits)
            audit_log = self.archive_factory(directory/'audit-archives', budget=self.budget,
                                             cursor=audit_cursor, limits=self.worker_limits)
            auditor = self.audit_factory(owner, limits=self.worker_limits)
        except BaseException:
            owner.close()
            self.fail('PIPELINE_EPOCH_SETUP_FAILURE')
            raise
        channel = dict(index=len(self.channels), owner=owner, raw=raw, audit_log=audit_log, auditor=auditor,
            raw_cursor=raw_cursor, audit_cursor=audit_cursor, closed_ns=None, final_job=None, result=None)
        self.channels.append(channel)
        if self.task is None:
            self.task = asyncio.create_task(self._run(), name='sealed-feed-pipeline')
        return channel['index']

    def submit(self, index, raw_tickets, audit_tickets):
        try:
            self.check()
            integer(index)
            channel = self.channels[index]
            if channel['closed_ns'] is not None:
                raise JournalError('sealed epoch already closed')
            pending = sum(u['status'] != 'COMPLETE' for u in self.units)
            if pending >= self.limits.max_pending_units or len(self.units) >= self.limits.max_units:
                raise JournalError('PIPELINE_UNIT_BACKLOG_LIMIT')
            # A unit seals one complete audit segment at a raw batch boundary.
            # Multiple audit segments are rejected, never guessed or truncated.
            if not 1 <= len(raw_tickets) <= 16 or len(audit_tickets) != 1:
                raise JournalError('PIPELINE_UNIT_SEGMENT_BOUND')
            raw_cursor, audit_cursor = channel['raw_cursor'], channel['audit_cursor']
            for ticket in raw_tickets:
                raw_cursor = advance_cursor(certificate(ticket.certificate), raw_cursor)
            audit_cursor = advance_cursor(certificate(audit_tickets[0].certificate), audit_cursor)
            tasks = [dict(kind='raw', ticket=t, job=None) for t in raw_tickets]
            tasks.append(dict(kind='audit_log', ticket=audit_tickets[0], job=None))
            self.units.append(dict(index=len(self.units), channel=index, status='WAIT_ARCHIVE',
                submitted_ns=time.monotonic_ns(), archive_tasks=tasks, audit_job=None))
            channel.update(raw_cursor=raw_cursor, audit_cursor=audit_cursor)
            self.peak_pending_units = max(self.peak_pending_units, pending+1)
        except BaseException as exc:
            self.fail(type(exc).__name__+':'+str(exc))
            raise

    def end_epoch(self, index):
        self.check()
        integer(index)
        channel = self.channels[index]
        if channel['closed_ns'] is not None:
            raise JournalError('epoch closed twice')
        channel['closed_ns'] = time.monotonic_ns()

    def _slots(self):
        count = self.budget.snapshot()['pending_reservations']
        self.peak_reservations = max(self.peak_reservations, count)
        return 2-count

    def _dispatch(self):
        now = time.monotonic_ns()
        for manager in self.managers():
            if manager.failed.is_set():
                raise JournalError('CHILD_SUPERVISOR_FAILURE:'+','.join(manager.errors))
        self.budget.check(0)
        for unit in self.units:
            if unit['status'] == 'COMPLETE':
                continue
            if now-unit['submitted_ns'] >= self.limits.unit_seconds*1e9:
                raise TimeoutError('PIPELINE_UNIT_DEADLINE')
            c = self.channels[unit['channel']]
            if unit['audit_job'] is not None:
                if unit['audit_job'] in c['auditor'].results:
                    unit.update(status='COMPLETE', completed_ns=now)
                continue
            ready = all(t['job'] is not None and t['job'] in c[t['kind']].results for t in unit['archive_tasks'])
            earlier = any(u['channel'] == unit['channel'] and u['index'] < unit['index'] and
                          u['audit_job'] is None for u in self.units)
            if ready and not earlier and self._slots() and c['auditor'].pending < 1:
                refs = []
                for t in unit['archive_tasks']:
                    manager = c[t['kind']]
                    descriptor = manager.results[t['job']]
                    refs.append(segment_ref(t['ticket'],
                        archive_directory=str(manager.store.directory.relative_to(self.budget.root)),
                        archive_id=descriptor['archive_id']))
                unit['audit_job'] = c['auditor'].submit(refs[-1], refs[:-1])
                unit['status'] = 'AUDITING'
        # Prefer ready audits, then oldest uncompressed inputs. At most one
        # job per manager so a queued archive cannot monopolize both slots.
        for unit in self.units:
            c = self.channels[unit['channel']]
            for task in unit['archive_tasks']:
                manager = c[task['kind']]
                if task['job'] is None and self._slots() and manager.pending < 1:
                    task['job'] = manager.submit(task['ticket'])
        for c in self.channels:
            if c['closed_ns'] is None or c['result'] is not None:
                continue
            if now-c['closed_ns'] >= self.limits.drain_seconds*1e9:
                raise TimeoutError('PIPELINE_EPOCH_FINAL_DEADLINE')
            if c['final_job'] is not None:
                if c['final_job'] in c['auditor'].results:
                    result = c['owner'].summary()
                    if result['status'] != 'AUDIT_PREFIX_COMPLETE' or result['processor_errors']:
                        raise JournalError('PIPELINE_FINAL_AUDIT_REJECTED')
                    c['result'] = result
            elif self._slots() and all(u['status'] == 'COMPLETE' for u in self.units if u['channel'] == c['index']):
                c['final_job'] = c['auditor'].submit_finalize(raw_cursor=c['raw_cursor'], audit_cursor=c['audit_cursor'])
        self._slots()
        if any(c['auditor'].process is not None for c in self.channels) and any(
                c[k].process is not None for c in self.channels for k in ('raw','audit_log')):
            self.audit_archive_overlap_samples += 1

    async def _run(self):
        try:
            while not self.closed and not self.failed.is_set():
                self._dispatch()
                await asyncio.sleep(.005)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.fail(type(exc).__name__+':'+str(exc))

    async def drain(self):
        try:
            async with asyncio.timeout(self.limits.drain_seconds):
                while not self.failed.is_set():
                    if all(c['closed_ns'] is not None and c['result'] is not None for c in self.channels):
                        return
                    await asyncio.sleep(.005)
            raise JournalError(self.errors[0])
        except asyncio.CancelledError:
            self.fail('PIPELINE_DRAIN_CANCELLED')
            raise
        except Exception as exc:
            self.fail(type(exc).__name__+':'+str(exc))
            raise

    async def _close(self):
        self.closed = True
        if any(u['status'] != 'COMPLETE' for u in self.units) or any(c['result'] is None for c in self.channels):
            self.fail('PIPELINE_CLOSED_INCOMPLETE')
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        try:
            await asyncio.gather(*(m.close() for m in self.managers()))
        finally:
            for c in self.channels:
                c['owner'].close()

    async def close(self):
        if self.close_task is None:
            self.close_task = asyncio.create_task(self._close())
        cancelled = False
        while not self.close_task.done():
            try:
                await asyncio.shield(self.close_task)
            except asyncio.CancelledError:
                cancelled = True
        self.close_task.result()
        if cancelled:
            raise asyncio.CancelledError

    def snapshot(self):
        return dict(limits=asdict(self.limits), errors=list(self.errors), closed=self.closed,
            failure_detected=self.detected, units=[{k:v for k,v in u.items() if k != 'archive_tasks'} for u in self.units],
            peak_pending_units=self.peak_pending_units, peak_reservations=self.peak_reservations,
            audit_archive_overlap_samples=self.audit_archive_overlap_samples,
            channels=[dict(index=c['index'], closed_ns=c['closed_ns'], final_job=c['final_job'],
                complete=c['result'] is not None, raw=c['raw'].snapshot(), audit_log=c['audit_log'].snapshot(),
                auditor=c['auditor'].snapshot()) for c in self.channels],
            storage=self.budget.snapshot(), original_deletion=False, live_market_state_restored=False)
