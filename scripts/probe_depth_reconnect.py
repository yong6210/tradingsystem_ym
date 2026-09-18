"""Bounded, unauthenticated BTCUSDC depth reconnect probe; never sends orders."""
import argparse
import asyncio
from contextlib import suppress
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.request import urlopen
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.research.data.depth_capture import (
    CaptureWriter, DepthCaptureProcessor, PUBLIC_URL, SNAPSHOT_URL,
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def fetch_snapshot():
    started, started_utc = time.monotonic_ns(), utc_now()
    with urlopen(SNAPSHOT_URL, timeout=8) as response:
        body = response.read(4_000_001)
        received, received_utc = time.monotonic_ns(), utc_now()
        if len(body) > 4_000_000:
            raise ValueError('snapshot exceeds capture size limit')
        return dict(request_started_ns=started, request_started_utc=started_utc,
                    received_monotonic_ns=received, received_utc=received_utc,
                    http_status=response.status, wire_text=body.decode('utf-8'))


async def receive(ws, writer, session):
    try:
        while True:
            wire = await ws.recv()
            received, received_utc = time.monotonic_ns(), utc_now()
            if not isinstance(wire, str):
                raise ValueError('unexpected binary frame')
            writer.emit('WS_MESSAGE', session, wire_text=wire,
                        received_monotonic_ns=received, received_utc=received_utc)
            if writer.processor.book.state == 'INVALID':
                raise ValueError('depth synchronization failed')
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # Invalidate immediately on a detected transport/parser failure, including
        # while the REST request is still running in another thread.
        writer.emit('ERROR', session, reason=f'WS_RECEIVE_FAILED:{type(exc).__name__}')
        raise


async def close_and_drain(ws, writer, session, normal_close_exceptions=()):
    """Drain closing traffic so a full receive queue cannot hide the close frame.

    The session is already ended and no closing message may enter the L2 book.
    Raw closing frames are retained, rather than silently discarded.
    """
    async def drain():
        while True:
            wire = await ws.recv()
            received, received_utc = time.monotonic_ns(), utc_now()
            writer.emit('CLOSING_WS_MESSAGE', session, wire_text=wire,
                        received_monotonic_ns=received, received_utc=received_utc)

    drainer = asyncio.create_task(drain())
    close_error = None
    try:
        await asyncio.wait_for(ws.close(code=1000), timeout=4)
    except Exception as exc:
        close_error = f'{type(exc).__name__}:{exc}'
    finally:
        drainer.cancel()
        try:
            await drainer
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            # A normal close ends recv() with ConnectionClosedOK. Other reader
            # failures must not be hidden merely because close_code was 1000.
            if not isinstance(exc, normal_close_exceptions):
                close_error = f'DRAIN_FAILED:{type(exc).__name__}:{exc}'
    writer.emit('CLOSE_RESULT', session, close_code=ws.close_code, close_error=close_error)
    return ws.close_code == 1000 and close_error is None


async def capture_session(ws, writer, session, seconds, snapshot_fetch=fetch_snapshot, normal_close_exceptions=()):
    writer.emit('SESSION_START', session, url=PUBLIC_URL)
    receiver = asyncio.create_task(receive(ws, writer, session))
    successful = False
    try:
        request_id = str(uuid.uuid4())
        writer.emit('REST_REQUEST', session, url=SNAPSHOT_URL, request_id=request_id)
        payload = await asyncio.to_thread(snapshot_fetch)
        writer.emit('REST_SNAPSHOT', session, request_id=request_id, **payload)
        if writer.processor.failed:
            raise ValueError('capture invalidated during snapshot acquisition')
        done, _ = await asyncio.wait([receiver], timeout=seconds)
        if done:
            receiver.result()
            raise ValueError('receiver stopped unexpectedly')
        current = writer.processor.current
        # A past quote alone is insufficient: the book must still be fresh here.
        writer.processor.book.quote(now_ns=time.monotonic_ns())
        if not current['quotes'] or not current['ticker_events']:
            raise ValueError('missing bridged depth or ticker evidence')
        successful = True
    except Exception as exc:
        writer.emit('ERROR', session, reason=f'SESSION_FAILED:{type(exc).__name__}:{exc}')
    finally:
        receiver.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await receiver
        # Publication is revoked before waiting for a socket close handshake.
        writer.emit('SESSION_END', session, reason='PLANNED_CLIENT_CLOSE' if successful else 'FAILED')
        clean_close = await close_and_drain(ws, writer, session, normal_close_exceptions)
    return successful and clean_close


def replay_capture(path):
    processor = DepthCaptureProcessor()
    with Path(path).open() as stream:
        for line in stream:
            processor.apply(json.loads(line))
    return processor


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')


async def run(output, seconds):
    if not 1 <= seconds <= 15:
        raise ValueError('seconds must be between 1 and 15 per session')
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosedOK

    output.mkdir(parents=True, exist_ok=False)
    processor = DepthCaptureProcessor()
    failures = []
    attempts = 0
    with (output/'capture.jsonl').open('x') as stream:
        writer = CaptureWriter(stream, processor)
        for index in range(2):
            attempts += 1
            session = f'{index+1}-{uuid.uuid4()}'
            try:
                async with connect(PUBLIC_URL, open_timeout=8, close_timeout=2,
                                   max_size=4_000_000, max_queue=32, proxy=None) as ws:
                    if not await capture_session(ws, writer, session, seconds,
                                                 normal_close_exceptions=(ConnectionClosedOK,)):
                        failures.append(f'session {index+1} failed')
                        break
            except Exception as exc:
                processor.abort(f'CONNECTION_FAILED:{type(exc).__name__}')
                failures.append(f'{type(exc).__name__}:{exc}')
                break
    replay_error = None
    try:
        replay = replay_capture(output/'capture.jsonl')
    except Exception as exc:
        replay, replay_error = None, f'{type(exc).__name__}:{exc}'
    # Transport failures before SESSION_START have no raw session envelope.
    # They are captured separately, and prevent a PASS even if replay agrees.
    comparable = lambda p: (p.quotes, p.results, p.sessions, p.sequence)
    replay_matches = replay is not None and comparable(processor) == comparable(replay)
    summary = processor.summary()
    passed = (not failures and not summary['failed'] and not summary['unfinished_session']
              and len(summary['sessions']) == 2 and replay_matches
              and all(s['close_confirmed'] and s['quote_blocked_after_close']
                      and s['first_usable_ns'] >= s['snapshot_processed_ns']
                      and s['state_before_close'] == 'LIVE' for s in summary['sessions']))
    for name, values in [('online_quotes', processor.quotes), ('processing_results', processor.results)]:
        with (output/f'{name}.jsonl').open('x') as stream:
            for value in values:
                stream.write(json.dumps(value, sort_keys=True)+'\n')
    dump(output/'session_summary.json', summary)
    result = dict(status='PASS_SCOPED_PUBLIC_RECONNECT' if passed else 'FAILED_PUBLIC_RECONNECT',
                  started_connections=attempts, completed_sessions=len(processor.sessions),
                  seconds_after_snapshot_per_session=seconds, failures=failures,
                  exact_same_engine_replay=replay_matches, replay_error=replay_error,
                  actual_orders=0, private_requests=0,
                  published_quotes=len(processor.quotes),
                  rest_requests=sum(s['snapshot_requests'] for s in processor.sessions),
                  raw_sha256=hashlib.sha256((output/'capture.jsonl').read_bytes()).hexdigest(),
                  limitations=['Short planned clean close/reopen only, not all transport failures.',
                               'Same-engine deterministic replay, not independent numeric verification.',
                               'Receive clocks are local application observations, not exchange/network latency.',
                               'No queue priority, maker fill, strategy performance or long-run coverage claim.'])
    dump(output/'probe_result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=6)
    args = parser.parse_args()
    result = asyncio.run(run(args.output, args.seconds))
    print(json.dumps(result, indent=2))
    return 0 if result['status'].startswith('PASS_') else 1


if __name__ == '__main__':
    raise SystemExit(main())
