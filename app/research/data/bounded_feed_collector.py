"""Finite, data-only collection supervisor. No order or account interfaces.

Each transport retry gets fresh raw/processing state, with one original clock
window and a run-wide retry budget. This is a <=120-second qualification tool,
not a registered 24-hour collector or a process-restart service.
"""
import asyncio
import os
from pathlib import Path
import time
import uuid

from .durable_capture_log import DurableCaptureLog, encoded, integer, sync_directory, atomic_json
from .durable_market_feed import DurableFeedBridge, PUBLIC_URL, MARKET_URL, SNAPSHOT_URL
from .feed_coverage_audit import audit_epoch, combine_epochs
from ..foundation.forward_data_contract import validate_policy

NS = 1_000_000_000


class RetryableTransportError(Exception):
    """Only an explicit transport failure is eligible for the retry budget."""


class RetryBudget:
    def __init__(self, *, start_ns, end_ns, delays_ns):
        self.start, self.end = integer(start_ns), integer(end_ns, 1)
        if self.end <= self.start or not delays_ns:
            raise ValueError('fixed window and finite delays required')
        self.delays = tuple(integer(value, 1) for value in delays_ns)
        self.used, self.last_now = 0, start_ns

    def after_failure(self, now_ns):
        now = integer(now_ns)
        if now < self.last_now:
            raise ValueError('supervisor clock regressed')
        self.last_now = now
        if now >= self.end:
            return dict(action='STOP', reason='ORIGINAL_DEADLINE')
        if self.used == len(self.delays):
            return dict(action='STOP', reason='RETRY_EXHAUSTED')
        wake = now+self.delays[self.used]
        if wake >= self.end:
            return dict(action='STOP', reason='RETRY_WOULD_REACH_DEADLINE')
        self.used += 1
        return dict(action='RETRY', retry_number=self.used, wake_ns=wake)


class DurableJsonl:
    """New-file-only, bounded audit writer; every acknowledged line is fsynced."""
    def __init__(self, path, *, max_bytes, min_free_bytes=0):
        self.path, self.max_bytes = Path(path), integer(max_bytes, 1)
        self.min_free_bytes = integer(min_free_bytes)
        self.bytes = self.lines = 0
        self.failed = False
        self.stream = self.path.open('xb', buffering=0)
        try:
            os.fsync(self.stream.fileno())
            sync_directory(self.path.parent)
        except BaseException:
            self.stream.close()
            raise

    def append(self, value):
        if self.failed or self.stream.closed:
            raise OSError('audit closed or failed')
        try:
            line = encoded(value)
            if len(line) > 4*1024**2 or self.bytes+len(line) > self.max_bytes:
                raise OSError('audit byte bound exceeded')
            # Includes a reserve for metadata/stop records, not a capacity proof.
            import shutil
            if shutil.disk_usage(self.path.parent).free < self.min_free_bytes+len(line)+65536:
                raise OSError('audit free-space reserve would be crossed')
            if self.stream.write(line) != len(line):
                raise OSError('short audit write')
            os.fsync(self.stream.fileno())
            self.bytes += len(line)
            self.lines += 1
            return time.monotonic_ns()
        except BaseException:
            self.failed = True
            raise

    def close(self):
        self.stream.close()


class FeedEpoch:
    def __init__(self, directory, plan, storage, *, raw_bytes_remaining):
        self.directory, self.plan = directory, plan
        directory.mkdir()
        self.sessions = {}
        self.failed = self.closing = False
        self.batches = self.eligible_points = self.discarded_after_failure = 0
        self.max_audit_sync_ns = 0
        self.last_audited_sequence = 0
        self.latest_received_utc_ns = 0
        began, wall = time.monotonic_ns(), time.time_ns()
        if began >= plan['window_end_ns']:
            raise TimeoutError('epoch setup after original deadline')
        self.journal = DurableCaptureLog.create(directory/'journal', run_id=plan['run_id'],
            rotation_bytes=storage['rotation_bytes'], max_total_bytes=raw_bytes_remaining,
            min_free_bytes=storage['min_free_bytes'])
        try:
            self.audit = DurableJsonl(directory/'batches.jsonl', max_bytes=32*1024**2,
                                      min_free_bytes=storage['min_free_bytes'])
        except BaseException:
            self.journal.close()
            raise
        self.bridge = DurableFeedBridge(self.journal)
        try:
            self.emit('RUN_WINDOW', 'system', received_ns=began, received_utc_ns=wall,
                      started_ns=plan['window_start_ns'], deadline_ns=plan['window_end_ns'])
            self.watchdog(time.monotonic_ns())
            self.flush()  # Both durability preflights precede any network request.
        except BaseException:
            self.close()
            raise

    def emit(self, kind, channel, **fields):
        if self.failed:
            raise OSError('epoch failed; no further publication')
        record = dict(kind=kind, channel=channel, session=self.sessions.get(channel, self.journal.epoch),
                      received_ns=time.monotonic_ns(), received_utc_ns=time.time_ns()) | fields
        self.bridge.append(record)
        self.latest_received_utc_ns = max(self.latest_received_utc_ns, record['received_utc_ns'])

    def watchdog(self, expected_ns):
        self.emit('WATCHDOG', 'system', expected_ns=expected_ns)

    def flush(self):
        try:
            batch = self.bridge.flush()
            if batch is None:
                return
            persisted = self.audit.append(batch)
            self.max_audit_sync_ns = max(self.max_audit_sync_ns, persisted-batch['observation']['published_ns'])
            self.last_audited_sequence = batch['last_sequence']
            self.batches += 1
            self.eligible_points += int(batch['observation']['eligible'])
            # The frozen bridge keeps a diagnostic list. Disk is authoritative
            # here; retaining every batch would make memory grow with duration.
            self.bridge.batches.clear()
            if self.bridge.processor.errors:
                raise ValueError('processor failure: '+','.join(self.bridge.processor.errors))
        except BaseException:
            self.failed = True
            raise

    def stop(self, reason, *, detected=None):
        self.closing = True
        if self.failed or self.bridge.failed:
            return
        fields = {} if detected is None else dict(received_ns=detected[0], received_utc_ns=detected[1])
        self.emit('STOP', 'system', reason=reason, **fields)
        for channel in self.sessions:
            self.emit('END', channel, reason=reason)
        self.flush()

    def close(self):
        self.journal.close()
        self.audit.close()


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
                if not isinstance(wire, str):
                    raise ValueError('unexpected binary frame')
                if epoch.failed or epoch.bridge.failed:
                    epoch.discarded_after_failure += 1
                    continue
                epoch.emit('CLOSING_WS' if epoch.closing else 'WS', channel, wire_text=wire)
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
    return dict(outcome=outcome, reason=None if failure is None else (type(failure).__name__+':'+str(failure))[:1000],
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
