"""V6 bounded collector: active sealed raw/audit -> gzip -> incremental replay.

Uses the frozen interruptible transport lifecycle. <=120s qualification only;
no live restart, raw retirement, private API or trading strategy execution.
"""
import asyncio
from dataclasses import asdict
from pathlib import Path
import time
import uuid

from .bounded_feed_collector import NS, RetryBudget
from .durable_capture_log import integer
from .durable_market_feed import DurableFeedBridge
from .feed_coverage_audit import combine_epochs
from .feed_runtime_diagnostics import GuardedFeedEpoch, PhaseStats, SynchronousStallError
from .interruptible_feed_epoch import collect_epoch
from .reserved_feed_storage import ReservedStorageBudget
from .sealed_feed_pipeline import SealedFeedPipeline, PipelineLimits
from .sealed_segment_handoff import SealedJournal, MAX_SEGMENT_BYTES
from .shared_feed_storage import SegmentedAudit
from ..foundation.forward_data_contract import validate_policy


class SealedAudit(SegmentedAudit):
    def __init__(self, directory, *, budget):
        self.journal = SealedJournal.create(directory, budget=budget, run_id=budget.contract['run_id'],
            rotation_bytes=MAX_SEGMENT_BYTES, max_record_bytes=4*1024**2)
        self.lines = self.bytes = 0


class PipelinedFeedEpoch(GuardedFeedEpoch):
    def __init__(self, directory, plan, storage, *, budget, pipeline):
        self.metrics = PhaseStats()
        self.pending_peak = self.attempted_pending_peak = 0
        self.sampled_book_levels_peak = self.sampled_book_buffer_peak = 0
        self.directory, self.plan = Path(directory), plan
        self.pipeline, self.budget = pipeline, budget
        self.pipeline_index = None
        self.seal_calls = self.max_seal_ns = self.max_flush_with_seal_ns = 0
        self.last_sealed_sequence = 0
        self.last_seal_ns = time.monotonic_ns()
        self.epoch_closed = False
        budget.reconcile()
        budget.path(directory).mkdir()
        self.sessions = {}
        self.failed = self.closing = False
        self.batches = self.eligible_points = self.discarded_after_failure = 0
        self.max_audit_sync_ns = self.last_audited_sequence = self.latest_received_utc_ns = 0
        began, wall = time.monotonic_ns(), time.time_ns()
        if began >= plan['window_end_ns']:
            raise TimeoutError('epoch setup after original deadline')
        self.journal = SealedJournal.create(self.directory/'journal', budget=budget, run_id=plan['run_id'],
            rotation_bytes=min(storage['rotation_bytes'], MAX_SEGMENT_BYTES))
        try:
            self.audit = SealedAudit(self.directory/'audit', budget=budget)
        except BaseException:
            self.journal.close()
            raise
        self.bridge = DurableFeedBridge(self.journal)
        try:
            scope = {k:plan[k] for k in ('window_start_ns','window_end_ns','clock_domain')}
            self.pipeline_index = pipeline.add_epoch(self.directory, self.journal.initial_cursor(),
                                                     self.audit.journal.initial_cursor(), scope)
            self.emit('RUN_WINDOW', 'system', received_ns=began, received_utc_ns=wall,
                      started_ns=plan['window_start_ns'], deadline_ns=plan['window_end_ns'])
            self.watchdog(time.monotonic_ns())
            self.flush()
        except BaseException:
            self.failed = True
            self.close()
            raise

    def _seal(self):
        if self.journal.sequence == self.last_sealed_sequence:
            return
        began = time.monotonic_ns()
        if self.bridge.pending or self.last_audited_sequence != self.journal.sequence:
            raise RuntimeError('seal requires fully audited raw batch boundary')
        raw = self.journal.seal()
        audit = self.audit.journal.seal()
        self.pipeline.submit(self.pipeline_index, raw, audit)
        self.last_sealed_sequence = self.journal.sequence
        self.last_seal_ns = time.monotonic_ns()
        self.seal_calls += 1
        elapsed = self.last_seal_ns-began
        self.max_seal_ns = max(self.max_seal_ns, elapsed)
        if elapsed > self.metrics.max_block_ns:
            raise SynchronousStallError('seal blocked beyond phase limit')

    def flush(self):
        began = time.monotonic_ns()
        try:
            self.pipeline.check()
            super().flush()
            if time.monotonic_ns()-self.last_seal_ns >= self.pipeline.limits.seal_seconds*NS:
                self._seal()
            elapsed = time.monotonic_ns()-began
            self.max_flush_with_seal_ns = max(self.max_flush_with_seal_ns, elapsed)
            if elapsed > self.metrics.max_block_ns:
                raise SynchronousStallError('flush plus seal blocked beyond phase limit')
        except BaseException as exc:
            self.failed = True
            self.pipeline.fail(type(exc).__name__+':'+str(exc))
            raise

    def close(self):
        if self.epoch_closed:
            return
        self.epoch_closed = True
        try:
            if not self.failed and not self.bridge.failed and not self.budget.failed:
                self._seal()
                self.pipeline.end_epoch(self.pipeline_index)
        except Exception as exc:
            self.failed = True
            self.pipeline.fail(type(exc).__name__+':'+str(exc))
        finally:
            self.journal.close()
            self.audit.close()

    def diagnostics(self):
        return super().diagnostics() | dict(seal_calls=self.seal_calls, max_seal_ns=self.max_seal_ns,
            max_flush_with_seal_ns=self.max_flush_with_seal_ns, last_sealed_sequence=self.last_sealed_sequence)


async def run_bounded(output, *, duration_ns, transport, policy, disconnect_once_after_ns=None,
                      source_hashes=None, pipeline_limits=None, worker_limits=None,
                      _pipeline_factory=SealedFeedPipeline):
    validate_policy(policy)
    integer(duration_ns, 1)
    if duration_ns > 120*NS:
        raise ValueError('unqualified runner limited to 120 seconds')
    if disconnect_once_after_ns is not None:
        integer(disconnect_once_after_ns, 1)
        if disconnect_once_after_ns >= duration_ns:
            raise ValueError('disconnect must precede original deadline')
    limits = pipeline_limits or PipelineLimits()
    output = Path(output).absolute()
    storage = policy['storage']
    run_id = uuid.uuid4().hex
    disk = ReservedStorageBudget.create(output, run_id=run_id, max_bytes=storage['hard_run_bytes'],
                                        min_free_bytes=storage['min_free_bytes'])
    pipeline = None
    events = None
    epochs, errors = [], []
    stop_reason = 'ORIGINAL_DEADLINE'
    start = time.monotonic_ns()
    scope = dict(window_start_ns=start, window_end_ns=start+duration_ns, clock_domain='one-process:'+uuid.uuid4().hex)
    plan = dict(run_id=run_id, **scope, started_utc_ns=time.time_ns(),
        retry_delays_seconds=storage['retry_delays_seconds'], purpose='BOUNDED_PIPELINED_DATA_ONLY_NOT_REGISTERED_PILOT',
        source_hashes=source_hashes or {}, disconnect_once_after_ns=disconnect_once_after_ns,
        storage_contract=disk.contract, pipeline_limits=asdict(limits),
        raw_rotation_bytes=min(storage['rotation_bytes'], MAX_SEGMENT_BYTES),
        audit_rotation_bytes=MAX_SEGMENT_BYTES)
    retry = RetryBudget(start_ns=start, end_ns=scope['window_end_ns'],
                       delays_ns=[v*NS for v in plan['retry_delays_seconds']])
    try:
        try:
            pipeline = _pipeline_factory(disk, limits=limits, worker_limits=worker_limits)
            plan['worker_limits'] = asdict(pipeline.worker_limits)
            disk.atomic_json(output/'plan.json', plan)
            events = SegmentedAudit(output/'supervisor', budget=disk)
            while time.monotonic_ns() < scope['window_end_ns'] and not pipeline.failed.is_set():
                index = len(epochs)
                events.append(dict(kind='ATTEMPT_START', attempt=index, received_ns=time.monotonic_ns(), **scope))
                directory = output/f'epoch-{index:02d}'
                epoch = PipelinedFeedEpoch(directory, plan, storage, budget=disk, pipeline=pipeline)
                row = await collect_epoch(epoch, transport, audit_control=pipeline,
                    disconnect_after_ns=disconnect_once_after_ns if index == 0 else None)
                row['directory'] = directory.name
                epochs.append(row)
                if disk.failed or pipeline.failed.is_set():
                    stop_reason = 'FATAL_FAILURE'
                    break
                events.append(dict(kind='ATTEMPT_END', attempt=index, received_ns=time.monotonic_ns(), result=row))
                if row['outcome'] != 'TRANSPORT_FAILURE':
                    stop_reason = row['outcome']
                    break
                decision = retry.after_failure(time.monotonic_ns())
                events.append(dict(kind='RETRY_DECISION', received_ns=time.monotonic_ns(), **decision))
                if decision['action'] == 'STOP':
                    stop_reason = decision['reason']
                    break
                try:
                    await asyncio.wait_for(pipeline.failed.wait(), timeout=max(0,
                        (decision['wake_ns']-time.monotonic_ns())/NS))
                except asyncio.TimeoutError:
                    pass
            if not disk.failed and not pipeline.failed.is_set():
                await pipeline.drain()
        except asyncio.CancelledError:
            if pipeline is not None:
                pipeline.fail('COLLECTOR_CANCELLED')
            raise
        except Exception as exc:
            errors.append(type(exc).__name__+':'+str(exc))
            stop_reason = 'FATAL_FAILURE'
            if pipeline is not None:
                pipeline.fail(errors[-1])
        finally:
            if pipeline is not None:
                await pipeline.close()
            if events is not None:
                events.close()
        audits = [c['result'] for c in pipeline.channels if c['result'] is not None] if pipeline else []
        if pipeline:
            errors.extend(pipeline.errors)
        if not epochs or len(audits) != len(epochs):
            errors.append('AUDIT_SET_INCOMPLETE')
        if errors or disk.failed or (pipeline and pipeline.failed.is_set()):
            stop_reason = 'FATAL_FAILURE'
        try:
            quality = combine_epochs(policy, audits, **scope)
        except Exception as exc:
            errors.append('AUDIT_COMBINATION_FAILURE:'+str(exc)[:1000])
            stop_reason = 'FATAL_FAILURE'
            quality = combine_epochs(policy, [], **scope)
        if stop_reason == 'FATAL_FAILURE':
            quality['quality']['status'] = 'QUALITY_INPUTS_REJECTED'
            quality['quality']['reasons'].append('COLLECTOR_FAILURE')
        result = dict(stop_reason=stop_reason, original_window=scope, completed_ns=time.monotonic_ns(),
            retries_used=retry.used, epochs=epochs, audits=audits, combined=quality, errors=errors,
            total_raw_bytes=sum(p.stat().st_size for p in output.glob('epoch-*/journal/segment-*.jsonl')),
            actual_orders=0, private_requests=0, full_day_pilot=False, strategy_adoption=False,
            continuous_runtime_coverage_certified=False, original_deletion=False,
            total_public_connection_attempts=sum(r['public_connection_attempts'] for r in epochs),
            total_snapshot_requests=sum(r['snapshot_requests'] for r in epochs),
            latest_received_utc_ns=max((r['latest_received_utc_ns'] for r in epochs), default=plan['started_utc_ns']),
            storage_before_result=disk.snapshot(), result_persisted=False,
            pipeline=None if pipeline is None else pipeline.snapshot())
        if not disk.failed:
            try:
                disk.atomic_json(output/'collection_result.json', result | dict(result_persisted=True))
                result['result_persisted'] = True
            except Exception as exc:
                result['errors'].append('RESULT_STORAGE_FAILURE:'+str(exc))
                result['stop_reason'] = 'FATAL_FAILURE'
                quality['quality']['status'] = 'QUALITY_INPUTS_REJECTED'
                quality['quality']['reasons'].append('RESULT_STORAGE_FAILURE')
        result['storage_after_result'] = disk.snapshot()
        return result
    finally:
        disk.close()
