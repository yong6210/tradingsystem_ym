"""V5 qualification collector: bounded background audit, original <=120s window.

Closed epochs are audited while reconnect proceeds. No result is acceptable
until every epoch has passed. Delayed audit failure stops active collection.
"""
import asyncio
from pathlib import Path
import time
import sys
import uuid

from .bounded_feed_collector import NS, RetryBudget
from .interruptible_feed_epoch import collect_epoch
from .background_feed_audit import BackgroundAudits
from .durable_capture_log import integer
from .shared_feed_storage import SharedStorageBudget, SegmentedAudit
from .feed_coverage_audit import combine_epochs
from ..foundation.forward_data_contract import validate_policy


from .segmented_feed_collector import SegmentedFeedEpoch


async def run_bounded(output, *, duration_ns, transport, policy, disconnect_once_after_ns=None,
                      source_hashes=None, audit_limits=None, _audit_factory=BackgroundAudits):
    validate_policy(policy)
    integer(duration_ns, 1)
    if duration_ns > 120*NS:
        raise ValueError('unqualified runner limited to 120 seconds')
    if disconnect_once_after_ns is not None:
        integer(disconnect_once_after_ns, 1)
        if disconnect_once_after_ns >= duration_ns:
            raise ValueError('disconnect must precede original deadline')
    auditor = _audit_factory(limits=audit_limits)
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
                disconnect_once_after_ns=disconnect_once_after_ns, storage_contract=disk.contract,
                background_audit_limits=auditor.snapshot()['limits'])
    retry = RetryBudget(start_ns=start, end_ns=plan['window_end_ns'],
                        delays_ns=[value*NS for value in plan['retry_delays_seconds']])
    epochs, audits, errors = [], [], []
    stop_reason, events = 'ORIGINAL_DEADLINE', None
    scope = {key: plan[key] for key in ('window_start_ns', 'window_end_ns', 'clock_domain')}
    result = None
    try:
        disk.atomic_json(output/'plan.json', plan)
        events = SegmentedAudit(output/'supervisor', budget=disk)
        while time.monotonic_ns() < plan['window_end_ns'] and not auditor.failed.is_set():
            index = len(epochs)
            events.append(dict(kind='ATTEMPT_START', attempt=index, received_ns=time.monotonic_ns(), **scope))
            directory = output/f'epoch-{index:02d}'
            epoch = SegmentedFeedEpoch(directory, plan, storage, budget=disk)
            row = await collect_epoch(epoch, transport,
                disconnect_after_ns=disconnect_once_after_ns if index == 0 else None, audit_control=auditor)
            row['directory'] = directory.name
            epochs.append(row)
            if disk.failed:
                stop_reason = 'FATAL_FAILURE'
                break
            if not auditor.failed.is_set():
                auditor.submit(directory, scope)
            events.append(dict(kind='ATTEMPT_END', attempt=index, received_ns=time.monotonic_ns(), result=row))
            if row['outcome'] == 'FATAL_FAILURE' or auditor.failed.is_set():
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
            try:
                await asyncio.wait_for(auditor.failed.wait(), timeout=max(0,
                    (decision['wake_ns']-time.monotonic_ns())/NS))
            except asyncio.TimeoutError:
                pass
        if not disk.failed:
            await auditor.drain()
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
        await auditor.close()
        if events is not None:
            events.close()
        # Release the budget lock even when cancellation propagates.
        if sys.exc_info()[0] is not None:
            disk.close()
    try:
        audits = [auditor.results[i] for i in sorted(auditor.results)]
        errors.extend(auditor.errors)
        if len(audits) != len(epochs) or any(job['status'] != 'COMPLETE' for job in auditor.jobs):
            errors.append('AUDIT_SET_INCOMPLETE')
        if errors or auditor.failed.is_set() or disk.failed:
            stop_reason = 'FATAL_FAILURE'
        quality = None
        if all(row['epoch'] is not None for row in audits):
            try:
                quality = combine_epochs(policy, audits, **scope)
            except Exception as exc:
                errors.append('AUDIT_COMBINATION_FAILURE:'+str(exc)[:1000])
                stop_reason = 'FATAL_FAILURE'
                quality = combine_epochs(policy, [], **scope)
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
            storage_before_result=disk.snapshot(), result_persisted=False,
            background_audit=auditor.snapshot())
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
