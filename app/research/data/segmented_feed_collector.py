"""Storage v3 qualification runner, <=120s and no restart of live market state.

Reuses the frozen v2 asynchronous controller. Raw, audit, supervisor, plan,
metadata, checkpoints and the final result share one exclusive run budget.
"""
import asyncio
from pathlib import Path
import time
import sys
import uuid

from .bounded_feed_collector import NS, RetryBudget
from .bounded_feed_collector_v2 import collect_epoch
from .feed_runtime_diagnostics import GuardedFeedEpoch, PhaseStats
from .durable_market_feed import DurableFeedBridge
from .durable_capture_log import integer
from .shared_feed_storage import SharedStorageBudget, BudgetedJournal, SegmentedAudit
from .segmented_feed_audit import audit_epoch
from .feed_coverage_audit import combine_epochs
from ..foundation.forward_data_contract import validate_policy


class SegmentedFeedEpoch(GuardedFeedEpoch):
    def __init__(self, directory, plan, storage, *, budget,
                 audit_rotation_bytes=32*1024**2, audit_record_bytes=4*1024**2):
        self.metrics = PhaseStats()
        self.pending_peak = self.attempted_pending_peak = 0
        self.sampled_book_levels_peak = self.sampled_book_buffer_peak = 0
        self.directory, self.plan = Path(directory), plan
        budget.reconcile()  # Old epoch files/tails stay in the same run budget.
        budget.path(directory).mkdir()
        self.sessions = {}
        self.failed = self.closing = False
        self.batches = self.eligible_points = self.discarded_after_failure = 0
        self.max_audit_sync_ns = self.last_audited_sequence = self.latest_received_utc_ns = 0
        began, wall = time.monotonic_ns(), time.time_ns()
        if began >= plan['window_end_ns']:
            raise TimeoutError('epoch setup after original deadline')
        self.journal = BudgetedJournal.create(self.directory/'journal', budget=budget, run_id=plan['run_id'],
                                             rotation_bytes=storage['rotation_bytes'])
        try:
            self.audit = SegmentedAudit(self.directory/'audit', budget=budget,
                                       rotation_bytes=audit_rotation_bytes, max_record_bytes=audit_record_bytes)
        except BaseException:
            self.journal.close()
            raise
        self.bridge = DurableFeedBridge(self.journal)
        try:
            self.emit('RUN_WINDOW', 'system', received_ns=began, received_utc_ns=wall,
                      started_ns=plan['window_start_ns'], deadline_ns=plan['window_end_ns'])
            self.watchdog(time.monotonic_ns())
            self.flush()
        except BaseException:
            self.close()
            raise


async def run_bounded(output, *, duration_ns, transport, policy, disconnect_once_after_ns=None,
                      source_hashes=None):
    validate_policy(policy)
    integer(duration_ns, 1)
    if duration_ns > 120*NS:
        raise ValueError('unqualified runner limited to 120 seconds')
    if disconnect_once_after_ns is not None:
        integer(disconnect_once_after_ns, 1)
        if disconnect_once_after_ns >= duration_ns:
            raise ValueError('disconnect must precede original deadline')
    output = Path(output).absolute()
    storage = policy['storage']
    run_id = uuid.uuid4().hex
    # This additional v3 cap is stricter than the frozen raw-only 64 GiB cap.
    disk = SharedStorageBudget.create(output, run_id=run_id, max_bytes=storage['hard_run_bytes'],
                                      min_free_bytes=storage['min_free_bytes'])
    start = time.monotonic_ns()
    plan = dict(run_id=run_id, window_start_ns=start, window_end_ns=start+duration_ns,
                started_utc_ns=time.time_ns(), clock_domain='one-process:'+uuid.uuid4().hex,
                retry_delays_seconds=storage['retry_delays_seconds'],
                purpose='BOUNDED_SEGMENTED_DATA_ONLY_NOT_REGISTERED_PILOT', source_hashes=source_hashes or {},
                disconnect_once_after_ns=disconnect_once_after_ns, storage_contract=disk.contract)
    retry = RetryBudget(start_ns=start, end_ns=plan['window_end_ns'],
                        delays_ns=[value*NS for value in plan['retry_delays_seconds']])
    epochs, audits, errors = [], [], []
    stop_reason, events = 'ORIGINAL_DEADLINE', None
    scope = {key: plan[key] for key in ('window_start_ns', 'window_end_ns', 'clock_domain')}
    result = None
    try:
        disk.atomic_json(output/'plan.json', plan)
        events = SegmentedAudit(output/'supervisor', budget=disk)
        while time.monotonic_ns() < plan['window_end_ns']:
            index = len(epochs)
            events.append(dict(kind='ATTEMPT_START', attempt=index, received_ns=time.monotonic_ns(), **scope))
            directory = output/f'epoch-{index:02d}'
            epoch = SegmentedFeedEpoch(directory, plan, storage, budget=disk)
            row = await collect_epoch(epoch, transport,
                disconnect_after_ns=disconnect_once_after_ns if index == 0 else None)
            row['directory'] = directory.name
            epochs.append(row)
            audited = audit_epoch(directory/'journal', directory/'audit', **scope)
            audits.append(audited)
            if disk.failed:
                stop_reason = 'FATAL_FAILURE'
                break
            events.append(dict(kind='ATTEMPT_END', attempt=index, received_ns=time.monotonic_ns(), result=row))
            if row['outcome'] == 'FATAL_FAILURE' or audited['errors'] or audited['processor_errors']:
                stop_reason = 'FATAL_FAILURE'
                break
            if row['outcome'] != 'TRANSPORT_FAILURE':
                stop_reason = row['outcome']
                break
            decision = retry.after_failure(time.monotonic_ns())
            events.append(dict(kind='RETRY_DECISION', received_ns=time.monotonic_ns(), **decision))
            if decision['action'] == 'STOP':
                stop_reason = decision['reason']
                break
            await asyncio.sleep(max(0, (decision['wake_ns']-time.monotonic_ns())/NS))
    except asyncio.CancelledError:
        # Cancellation cannot force a write after a storage failure.
        if events is not None and not disk.failed:
            try:
                events.append(dict(kind='CANCELLED', received_ns=time.monotonic_ns()))
            except Exception:
                pass
        raise
    except Exception as exc:
        errors.append(type(exc).__name__+':'+str(exc))
        stop_reason = 'FATAL_FAILURE'
    finally:
        if events is not None:
            events.close()
        # Release the budget lock even when cancellation propagates.
        if sys.exc_info()[0] is not None:
            disk.close()
    try:
        quality = None
        if all(row['epoch'] is not None for row in audits):
            quality = combine_epochs(policy, audits, **scope)
            if errors or stop_reason == 'FATAL_FAILURE':
                quality['quality']['status'] = 'QUALITY_INPUTS_REJECTED'
                quality['quality']['reasons'].append('COLLECTOR_FAILURE')
        raw_bytes = sum(p.stat().st_size for p in output.glob('epoch-*/journal/segment-*.jsonl'))
        result = dict(stop_reason=stop_reason, original_window=scope, completed_ns=time.monotonic_ns(),
            retries_used=retry.used, epochs=epochs, audits=audits, combined=quality, errors=errors,
            total_raw_bytes=raw_bytes, actual_orders=0, private_requests=0,
            full_day_pilot=False, strategy_adoption=False, continuous_runtime_coverage_certified=False,
            total_public_connection_attempts=sum(row['public_connection_attempts'] for row in epochs),
            total_snapshot_requests=sum(row['snapshot_requests'] for row in epochs),
            latest_received_utc_ns=max((row['latest_received_utc_ns'] for row in epochs), default=plan['started_utc_ns']),
            storage_before_result=disk.snapshot(), result_persisted=False)
        if not disk.failed:
            try:
                # Storage snapshot explicitly precedes this budgeted result write.
                disk.atomic_json(output/'collection_result.json', result | dict(result_persisted=True))
                result['result_persisted'] = True
            except Exception as exc:
                result['errors'].append('RESULT_STORAGE_FAILURE:'+str(exc))
                result['stop_reason'] = 'FATAL_FAILURE'
                if quality is not None:
                    quality['quality']['status'] = 'QUALITY_INPUTS_REJECTED'
                    quality['quality']['reasons'].append('RESULT_STORAGE_FAILURE')
        result['storage_after_result'] = disk.snapshot()
        return result
    finally:
        disk.close()
