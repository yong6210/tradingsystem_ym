"""V3 epoch controller: frozen v2 lifecycle plus an external audit failure latch."""
import asyncio
import time
import uuid

from .bounded_feed_collector import NS, RetryableTransportError
from .durable_market_feed import PUBLIC_URL, MARKET_URL, SNAPSHOT_URL


async def collect_epoch(epoch, transport, *, disconnect_after_ns=None, audit_control=None):
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

    async def watch_audit():
        await audit_control.failed.wait()
        fail(RuntimeError('BACKGROUND_AUDIT_FAILURE'))
        # Preserve when the fault became known, before any cleanup work.
        nonlocal detected
        detected = min(detected, audit_control.detected)

    def remaining():
        if audit_control is not None and audit_control.failed.is_set():
            raise RuntimeError('BACKGROUND_AUDIT_FAILURE')
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
            if audit_control is not None:
                jobs.append(asyncio.create_task(watch_audit()))
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

