"""Bounded four-feed public integration probe; no private endpoints or orders."""
import argparse
import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import sys
import time
from urllib.request import urlopen
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.durable_capture_log import DurableCaptureLog, iter_committed, inspect_journal
from app.research.data.durable_market_feed import DurableFeedBridge, MarketFeedProcessor, PUBLIC_URL, MARKET_URL, SNAPSHOT_URL


def fetch_snapshot():
    started = time.monotonic_ns()
    with urlopen(SNAPSHOT_URL, timeout=8) as response:
        body = response.read(4_000_001)
        received, wall = time.monotonic_ns(), time.time_ns()
        if len(body) > 4_000_000:
            raise ValueError('snapshot size bound exceeded')
        return dict(request_started_ns=started, received_ns=received, received_utc_ns=wall,
                    http_status=response.status, wire_text=body.decode('utf-8'))


def replay_batches(journal, batches):
    processor = MarketFeedProcessor()
    records = iter(iter_committed(journal))
    for batch in batches:
        if batch['first_sequence'] != processor.sequence+1:
            raise ValueError('audit batch sequence gap')
        last = None
        for sequence in range(batch['first_sequence'], batch['last_sequence']+1):
            last = next(records)
            if last['sequence'] != sequence:
                raise ValueError('raw sequence differs from batch')
            processor.apply(sequence, last['payload'], processed_ns=batch['committed_ns'])
        if last is None or last['sha256'] != batch['record_sha256']:
            raise ValueError('batch fence hash differs from raw prefix')
        actual = processor.observe(now_ns=batch['observation']['published_ns'], committed_ns=batch['committed_ns'],
                                   committed_sequence=batch['last_sequence'])
        if actual != batch['observation']:
            raise ValueError('observation replay mismatch')
    if next(records, None) is not None:
        raise ValueError('committed raw records lack processing audit')
    return processor


async def run(output, seconds):
    if type(seconds) is not int or not 5 <= seconds <= 20:
        raise ValueError('bounded probe duration must be 5..20 seconds')
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosedOK

    output.mkdir(parents=True, exist_ok=False)
    journal = DurableCaptureLog.create(output/'journal', run_id=str(uuid.uuid4()))
    bridge = DurableFeedBridge(journal)
    stop, closing = asyncio.Event(), asyncio.Event()
    sockets, sessions, receivers, errors = {}, {}, [], []
    started = time.monotonic_ns()
    deadline = started+seconds*1_000_000_000
    rest_requests, connection_attempts = 0, 0
    audit = (output/'batches.jsonl').open('x')

    def emit(kind, channel, **fields):
        record = dict(kind=kind, channel=channel, session=sessions.get(channel, journal.epoch),
                      received_ns=time.monotonic_ns(), received_utc_ns=time.time_ns()) | fields
        bridge.append(record)

    def flush():
        batch = bridge.flush()
        if batch is not None:
            audit.write(json.dumps(batch, separators=(',', ':'))+'\n')
            audit.flush()
        if bridge.processor.errors:
            stop.set()

    async def receive(channel, ws):
        try:
            while True:
                wire = await ws.recv()
                if not isinstance(wire, str):
                    raise ValueError('unexpected binary message')
                emit('CLOSING_WS' if closing.is_set() else 'WS', channel, wire_text=wire)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if closing.is_set() and isinstance(exc, ConnectionClosedOK):
                return
            reason = f'TRANSPORT:{channel}:{type(exc).__name__}'
            errors.append(reason)
            bridge.processor.abort(reason)
            if not bridge.failed:
                emit('FAULT', channel, reason=reason)
            stop.set()

    async def ticker():
        expected = started
        try:
            while True:
                await asyncio.sleep(max(0, (expected-time.monotonic_ns())/1e9))
                emit('WATCHDOG', 'system', expected_ns=expected)
                expected += 250_000_000
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            errors.append(f'WATCHDOG:{type(exc).__name__}')
            stop.set()

    async def flusher():
        try:
            while True:
                await asyncio.sleep(.05)
                flush()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            errors.append(f'FLUSH:{type(exc).__name__}:{exc}')
            stop.set()

    clock_job = flush_job = None
    try:
        emit('RUN_WINDOW', 'system', started_ns=started, deadline_ns=deadline)
        emit('WATCHDOG', 'system', expected_ns=started)
        flush()  # Space/durability preflight before any network connection.
        clock_job = asyncio.create_task(ticker())
        flush_job = asyncio.create_task(flusher())
        for channel, url in [('public', PUBLIC_URL), ('market', MARKET_URL)]:
            connection_attempts += 1
            remaining = (deadline-time.monotonic_ns())/1e9
            if remaining <= 0:
                raise TimeoutError('probe deadline before connection')
            ws = await asyncio.wait_for(connect(url, open_timeout=min(8, remaining), close_timeout=2,
                                                max_size=4_000_000, max_queue=32, proxy=None), timeout=remaining)
            sockets[channel], sessions[channel] = ws, str(uuid.uuid4())
            emit('OPEN', channel, url=url)
            receivers.append(asyncio.create_task(receive(channel, ws)))
        request_id = str(uuid.uuid4())
        emit('REQUEST', 'public', request_id=request_id, url=SNAPSHOT_URL)
        rest_requests += 1
        remaining = (deadline-time.monotonic_ns())/1e9
        if remaining <= 0:
            raise TimeoutError('probe deadline before snapshot')
        payload = await asyncio.wait_for(asyncio.to_thread(fetch_snapshot), timeout=remaining)
        emit('SNAPSHOT', 'public', request_id=request_id, **payload)
        remaining = max(0, (deadline-time.monotonic_ns())/1e9)
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=remaining)
    except Exception as exc:
        reason = f'PROBE:{type(exc).__name__}:{exc}'
        errors.append(reason)
        bridge.processor.abort(reason)
        if not bridge.failed:
            emit('FAULT', 'system', reason=reason)
    finally:
        closing.set()
        if clock_job:
            clock_job.cancel()
            with suppress(asyncio.CancelledError):
                await clock_job
        if not bridge.failed:
            try:
                emit('STOP', 'system', planned_end_ns=deadline)
                for channel in sockets:
                    emit('END', channel, reason='PROBE_STOP')
                flush()  # Invalidate before socket close; receive tasks drain raw closing frames.
            except Exception as exc:
                errors.append(f'STOP_FLUSH:{type(exc).__name__}:{exc}')
        outcomes = await asyncio.gather(*(ws.close(code=1000) for ws in sockets.values()), return_exceptions=True)
        errors.extend('CLOSE:'+type(v).__name__ for v in outcomes if isinstance(v, Exception))
        for task in receivers:
            task.cancel()
        for task in receivers:
            with suppress(asyncio.CancelledError, Exception):
                await task
        if flush_job:
            flush_job.cancel()
            with suppress(asyncio.CancelledError):
                await flush_job
        if not bridge.failed:
            try:
                flush()
            except Exception as exc:
                errors.append(f'FINAL_FLUSH:{type(exc).__name__}:{exc}')
        journal.close()
        audit.flush()
        os.fsync(audit.fileno())
        audit.close()
    replay_ok, replay_error = False, None
    try:
        batches = [json.loads(line) for line in (output/'batches.jsonl').read_text().splitlines()]
        replay = replay_batches(output/'journal', batches)
        replay_ok = dict(replay.counts) == dict(bridge.processor.counts) and replay.errors == bridge.processor.errors
    except Exception as exc:
        replay_error = f'{type(exc).__name__}:{exc}'
    eligible = [b for b in bridge.batches if b['observation']['eligible']]
    codes = {channel: ws.close_code for channel, ws in sockets.items()}
    required = ('depthUpdate', 'bookTicker', 'aggTrade', 'markPriceUpdate')
    passed = (not errors and not bridge.failed and not bridge.processor.errors and replay_ok and eligible
              and len(codes) == 2 and all(code == 1000 for code in codes.values())
              and all(bridge.processor.counts[k] > 0 for k in required)
              and bridge.processor.closed and not bridge.batches[-1]['observation']['eligible'])
    result = dict(status='PASS_SCOPED_DURABLE_FOUR_FEED' if passed else 'FAILED_DURABLE_FOUR_FEED',
                  planned_observation_seconds=seconds, started_ns=started, planned_end_ns=deadline,
                  completed_ns=time.monotonic_ns(), counts=dict(bridge.processor.counts),
                  errors=errors, processor_errors=bridge.processor.errors, bridge_failed=bridge.failed,
                  batches=len(bridge.batches), eligible_observations=len(eligible),
                  close_codes=codes, exact_same_engine_replay=replay_ok, replay_error=replay_error,
                  connection_attempts=connection_attempts, rest_requests=rest_requests,
                  actual_orders=0, private_requests=0, full_day_pilot=False, fill_calibration=False,
                  limitations=['Point observations, not certified continuous coverage or market latency.',
                               'Bounded probe; no integrated reconnect, restart or 24-hour run.',
                               'Processing audit must be present to reproduce historical availability; raw alone is insufficient.'])
    (output/'probe_result.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=12)
    args = parser.parse_args()
    result = asyncio.run(run(args.output, args.seconds))
    print(json.dumps(result, indent=2))
    return 0 if result['status'].startswith('PASS_') else 1


if __name__ == '__main__':
    raise SystemExit(main())
