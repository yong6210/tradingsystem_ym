"""Bounded collector v2: measured synchronous storage phases and fair failure drain.

The archived v1 remains untouched. Retry/window/transport contracts are the same;
this controller uses GuardedFeedEpoch and timestamps every received frame,
including frames discarded after a terminal storage failure. Not a daily runner.
"""
import asyncio
from pathlib import Path
import time
import uuid

from .bounded_feed_collector import NS, RetryBudget, DurableJsonl, RetryableTransportError
from .feed_runtime_diagnostics import GuardedFeedEpoch as FeedEpoch
from .durable_capture_log import integer, atomic_json, sync_directory
from .durable_market_feed import PUBLIC_URL, MARKET_URL, SNAPSHOT_URL
from .feed_coverage_audit import audit_epoch, combine_epochs
from ..foundation.forward_data_contract import validate_policy


async def collect_epoch(epoch, transport, *, disconnect_after_ns=None):
    """One task owner; cancel connection/REST waits on failure or fixed deadline."""
    stop = asyncio.Event()
    sockets, receivers, jobs = {}, [], []
    failure, forced = None, False
    detected = None
    attempts, rest = 0, 0
    close_errors = []
    deadline = epoch.plan['window_end_ns']

    def fail(exc):
        nonlocal failure, detected
        if detected is None:
            detected = (time.monotonic_ns(), time.time_ns())
        # A storage/processing error cannot be masked by a concurrent disconnect.
        if failure is None or (isinstance(failure, RetryableTransportError) and
                               not isinstance(exc, RetryableTransportError)):
            failure = exc
        stop.set()

    def remaining():
        duration = (deadline-time.monotonic_ns())/NS
        if duration <= 0 or stop.is_set():
            raise asyncio.TimeoutError('original deadline or stop')
        return min(8, duration)

    async def receive(channel, ws):
        try:
            while True:
                wire = await ws.recv()
                received, wall = time.monotonic_ns(), time.time_ns()
                epoch.latest_received_utc_ns = max(epoch.latest_received_utc_ns, wall)
                if not isinstance(wire, str):
                    raise ValueError('unexpected binary frame')
                if epoch.failed or epoch.bridge.failed:
                    epoch.discarded_after_failure += 1
                    await asyncio.sleep(0)
                    continue
                epoch.emit('CLOSING_WS' if epoch.closing else 'WS', channel, wire_text=wire,
                           received_ns=received, received_utc_ns=wall)
                # recv() can complete synchronously while its queue is full.
                # Always yield so bursts cannot starve watchdog/flush/deadline tasks.
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not epoch.closing:
                fail(exc)

    async def watchdog():
        expected = time.monotonic_ns()
        try:
            while not stop.is_set():
                await asyncio.sleep(max(0, (expected-time.monotonic_ns())/NS))
                if stop.is_set() or time.monotonic_ns() >= deadline:
                    return
                epoch.watchdog(expected)
                expected += 250_000_000
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            fail(exc)

    async def flusher():
        try:
            while not stop.is_set():
                await asyncio.sleep(.05)
                if stop.is_set() or time.monotonic_ns() >= deadline:
                    return
                epoch.flush()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            fail(exc)

    async def disconnect_drill():
        nonlocal forced
        await asyncio.sleep(disconnect_after_ns/NS)
        if not stop.is_set() and time.monotonic_ns() < deadline:
            forced = True
            # Invalidate at the deliberate disconnect decision, before waiting
            # for a close handshake. The common cleanup path closes both sockets.
            fail(RetryableTransportError('PLANNED_LOCAL_DISCONNECT'))

    async def setup():
        nonlocal attempts, rest
        for channel, url in [('public', PUBLIC_URL), ('market', MARKET_URL)]:
            timeout = remaining()
            attempts += 1
            ws = await asyncio.wait_for(transport.connect(channel, url, timeout, deadline_ns=deadline), timeout)
            sockets[channel] = ws
            epoch.sessions[channel] = uuid.uuid4().hex
            epoch.emit('OPEN', channel, url=url)
            receivers.append(asyncio.create_task(receive(channel, ws)))
        timeout = remaining()
        epoch.emit('REQUEST', 'public', request_id='snapshot', url=SNAPSHOT_URL)
        rest += 1
        payload = await asyncio.wait_for(transport.snapshot(timeout, deadline_ns=deadline), timeout)
        if time.monotonic_ns() >= deadline or stop.is_set():
            return  # A late response never reopens the decision window.
        epoch.emit('SNAPSHOT', 'public', request_id='snapshot', **payload)
        if disconnect_after_ns is not None:
            jobs.append(asyncio.create_task(disconnect_drill()))
        await stop.wait()

    outcome = 'ORIGINAL_DEADLINE'
    setup_task = waiter = None
    try:
        if time.monotonic_ns() < deadline:
            jobs.extend([asyncio.create_task(watchdog()), asyncio.create_task(flusher())])
            setup_task = asyncio.create_task(setup())
            waiter = asyncio.create_task(stop.wait())
            done, _ = await asyncio.wait([setup_task, waiter], timeout=max(0, (deadline-time.monotonic_ns())/NS),
                                         return_when=asyncio.FIRST_COMPLETED)
            if setup_task in done and not setup_task.cancelled():
                error = setup_task.exception()
                if error is not None:
                    if isinstance(error, asyncio.TimeoutError) and time.monotonic_ns() >= deadline:
                        pass
                    else:
                        fail(RetryableTransportError('OPERATION_TIMEOUT') if isinstance(error, asyncio.TimeoutError) else error)
    except asyncio.CancelledError:
        outcome = 'CANCELLED'
        raise
    finally:
        stop.set()
        for task in [setup_task, waiter, *jobs]:
            if task is not None:
                task.cancel()
        await asyncio.gather(*(task for task in [setup_task, waiter, *jobs] if task is not None), return_exceptions=True)
        if failure is not None:
            outcome = 'TRANSPORT_FAILURE' if isinstance(failure, RetryableTransportError) else 'FATAL_FAILURE'
        try:
            epoch.stop(outcome, detected=detected)
        except Exception as exc:
            fail(exc)
        async def close_socket(ws):
            try:
                await asyncio.wait_for(ws.close(), timeout=2)
            except Exception as exc:
                close_errors.append(type(exc).__name__)
        await asyncio.gather(*(close_socket(ws) for ws in sockets.values()))
        for task in receivers:
            task.cancel()
        await asyncio.gather(*receivers, return_exceptions=True)
        if not epoch.failed and not epoch.bridge.failed:
            try:
                epoch.flush()  # Retain closing frames; they cannot update state.
            except Exception as exc:
                fail(exc)
        epoch.close()
    if close_errors:
        fail(OSError('socket cleanup failed: '+','.join(close_errors)))
    if failure is not None:
        outcome = 'TRANSPORT_FAILURE' if isinstance(failure, RetryableTransportError) else 'FATAL_FAILURE'
    return dict(diagnostics=epoch.diagnostics(), outcome=outcome, reason=None if failure is None else (type(failure).__name__+':'+str(failure))[:1000],
                failure_detected_ns=None if detected is None else detected[0],
                public_connection_attempts=attempts, snapshot_requests=rest, forced_local_disconnect=forced,
                counts=dict(epoch.bridge.processor.counts), processor_errors=epoch.bridge.processor.errors,
                audited_batches=epoch.batches, eligible_point_observations=epoch.eligible_points,
                audit_bytes=epoch.audit.bytes, raw_bytes=epoch.journal.total_bytes,
                last_audited_sequence=epoch.last_audited_sequence, max_audit_sync_ns=epoch.max_audit_sync_ns,
                discarded_frames_after_storage_failure=epoch.discarded_after_failure,
                latest_received_utc_ns=epoch.latest_received_utc_ns, close_errors=close_errors)


async def run_bounded(output, *, duration_ns, transport, policy, disconnect_once_after_ns=None, source_hashes=None):
    validate_policy(policy)
    integer(duration_ns, 1)
    if duration_ns > 120*NS:
        raise ValueError('unqualified runner limited to 120 seconds')
    if disconnect_once_after_ns is not None:
        integer(disconnect_once_after_ns, 1)
        if disconnect_once_after_ns >= duration_ns:
            raise ValueError('disconnect must precede original deadline')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic_ns()
    plan = dict(run_id=uuid.uuid4().hex, window_start_ns=start, window_end_ns=start+duration_ns,
                started_utc_ns=time.time_ns(), clock_domain='one-process:'+uuid.uuid4().hex,
                retry_delays_seconds=policy['storage']['retry_delays_seconds'],
                purpose='BOUNDED_DATA_ONLY_NOT_REGISTERED_PILOT', source_hashes=source_hashes or {},
                disconnect_once_after_ns=disconnect_once_after_ns)
    atomic_json(output, 'plan.json', plan)
    sync_directory(output.parent)
    budget = RetryBudget(start_ns=start, end_ns=plan['window_end_ns'],
                         delays_ns=[value*NS for value in plan['retry_delays_seconds']])
    storage = policy['storage']
    events = DurableJsonl(output/'supervisor.jsonl', max_bytes=4*1024**2, min_free_bytes=storage['min_free_bytes'])
    epochs, audits, errors = [], [], []
    raw_bytes = 0
    stop_reason = 'ORIGINAL_DEADLINE'
    scope = {key: plan[key] for key in ('window_start_ns', 'window_end_ns', 'clock_domain')}
    try:
        while time.monotonic_ns() < plan['window_end_ns']:
            index = len(epochs)
            events.append(dict(kind='ATTEMPT_START', attempt=index, received_ns=time.monotonic_ns(), **scope))
            directory = output/f'epoch-{index:02d}'
            try:
                epoch = FeedEpoch(directory, plan, storage, raw_bytes_remaining=storage['hard_run_bytes']-raw_bytes)
                row = await collect_epoch(epoch, transport, disconnect_after_ns=disconnect_once_after_ns if index == 0 else None)
            except asyncio.CancelledError:
                events.append(dict(kind='CANCELLED', received_ns=time.monotonic_ns()))
                raise
            except Exception as exc:
                errors.append(type(exc).__name__+':'+str(exc))
                stop_reason = 'FATAL_FAILURE'
                break
            raw_bytes += row['raw_bytes']
            row['directory'] = directory.name
            epochs.append(row)
            audited = audit_epoch(directory/'journal', directory/'batches.jsonl', **scope)
            audits.append(audited)
            events.append(dict(kind='ATTEMPT_END', attempt=index, received_ns=time.monotonic_ns(), result=row))
            if row['outcome'] == 'FATAL_FAILURE' or audited['errors'] or audited['processor_errors']:
                stop_reason = 'FATAL_FAILURE'
                break
            if row['outcome'] != 'TRANSPORT_FAILURE':
                stop_reason = row['outcome']
                break
            decision = budget.after_failure(time.monotonic_ns())
            events.append(dict(kind='RETRY_DECISION', received_ns=time.monotonic_ns(), **decision))
            if decision['action'] == 'STOP':
                stop_reason = decision['reason']
                break
            await asyncio.sleep(max(0, (decision['wake_ns']-time.monotonic_ns())/NS))
            # A delayed timer never earns another attempt beyond the original end.
    finally:
        events.close()
    quality = None
    if all(row['epoch'] is not None for row in audits):
        quality = combine_epochs(policy, audits, **scope)
        if errors or stop_reason == 'FATAL_FAILURE':
            quality['quality']['status'] = 'QUALITY_INPUTS_REJECTED'
            quality['quality']['reasons'].append('COLLECTOR_FAILURE')
    # Also count a partial setup that failed before an epoch result existed.
    raw_bytes = sum(path.stat().st_size for path in output.glob('epoch-*/journal/segment-*.jsonl'))
    result = dict(stop_reason=stop_reason, original_window=scope, completed_ns=time.monotonic_ns(),
                  retries_used=budget.used, epochs=epochs, audits=audits, combined=quality, errors=errors,
                  total_raw_bytes=raw_bytes, actual_orders=0, private_requests=0,
                  full_day_pilot=False, strategy_adoption=False, continuous_runtime_coverage_certified=False,
                  total_public_connection_attempts=sum(row['public_connection_attempts'] for row in epochs),
                  total_snapshot_requests=sum(row['snapshot_requests'] for row in epochs),
                  latest_received_utc_ns=max((row['latest_received_utc_ns'] for row in epochs), default=plan['started_utc_ns']))
    atomic_json(output, 'collection_result.json', result)
    return result
