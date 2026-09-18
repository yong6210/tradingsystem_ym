import asyncio
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import time
import unittest

from app.research.data.depth_capture import CaptureWriter, DepthCaptureProcessor, PUBLIC_URL, SNAPSHOT_URL
from app.research.data.local_order_book import BookUnavailable
from scripts.probe_depth_reconnect import capture_session, close_and_drain, replay_capture
from tests.test_local_order_book import snapshot, event


def wire(value):
    return json.dumps(dict(stream='btcusdc@depth@100ms', data=value))


class DepthCaptureTests(unittest.TestCase):
    def setUp(self):
        self.processor = DepthCaptureProcessor()
        self.raw = io.StringIO()
        self.now = 10
        self.writer = CaptureWriter(self.raw, self.processor, monotonic=lambda: self.now, utc=lambda: 'fixture')
        self.emit('SESSION_START', url=PUBLIC_URL)

    def emit(self, kind, session='one', **fields):
        self.now += 10
        return self.writer.emit(kind, session, **fields)

    def request(self, session='one'):
        self.emit('REST_REQUEST', session, url=SNAPSHOT_URL, request_id='request-'+session)

    def install(self, session='one', identity=10, received=None):
        self.emit('REST_SNAPSHOT', session, request_id='request-'+session, http_status=200,
                  request_started_ns=self.processor.current['request_recorded_ns'],
                  received_monotonic_ns=received or self.now, wire_text=json.dumps(snapshot(identity)))

    def depth(self, value=None, session='one'):
        return self.emit('WS_MESSAGE', session, received_monotonic_ns=self.now, wire_text=wire(value or event()))

    def live(self):
        self.request()
        self.depth()
        self.install()

    def test_native_receipt_does_not_backdate_snapshot_publication(self):
        self.request()
        rest_received = self.now
        self.depth()
        self.assertEqual(self.processor.quotes, [])
        self.install(received=rest_received)
        quote = self.processor.quotes[0]
        self.assertEqual(quote['published_monotonic_ns'], self.now)
        self.assertEqual(quote['available_ns'], self.now)
        self.assertGreater(self.now, rest_received)
        with self.assertRaises(BookUnavailable):
            self.processor.book.quote(now_ns=rest_received)

    def test_reconnect_needs_fresh_snapshot_and_bridge(self):
        self.live()
        self.emit('SESSION_END', reason='PLANNED_CLIENT_CLOSE')
        with self.assertRaises(BookUnavailable):
            self.processor.book.quote(now_ns=self.now)
        self.emit('CLOSE_RESULT', close_code=1000)
        self.emit('SESSION_START', 'two', url=PUBLIC_URL)
        self.request('two')
        self.install('two', identity=20)
        self.assertEqual(len(self.processor.quotes), 1)
        with self.assertRaises(BookUnavailable):
            self.processor.book.quote(now_ns=self.now)
        self.depth(event(19, 22, 18), 'two')
        self.assertEqual(self.processor.quotes[-1]['session'], 'two')
        self.assertEqual(len(self.processor.quotes), 2)

    def test_delayed_old_session_event_invalidates_new_session(self):
        self.live()
        self.emit('SESSION_END', reason='close')
        self.emit('SESSION_START', 'two', url=PUBLIC_URL)
        with self.assertRaises(ValueError):
            self.depth(event(13, 15, 12))
        self.assertTrue(self.processor.failed)
        self.assertEqual(self.processor.book.state, 'INVALID')

    def test_exact_raw_roundtrip(self):
        self.live()
        self.depth(event(13, 15, 12, bids=[['100', '7']]))
        self.emit('SESSION_END', reason='close')
        self.emit('CLOSE_RESULT', close_code=1000)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'raw.jsonl'
            path.write_text(self.raw.getvalue())
            replay = replay_capture(path)
        self.assertEqual(replay.summary(), self.processor.summary())
        self.assertEqual(replay.quotes, self.processor.quotes)
        self.assertEqual(replay.results, self.processor.results)

    def test_log_failure_revokes_live_book_before_processing(self):
        self.live()
        original = self.processor.sequence

        class FailingLog:
            def write(self, value):
                return len(value)
            def flush(self):
                raise OSError('disk full')

        self.writer.stream = FailingLog()
        with self.assertRaises(OSError):
            self.depth(event(13, 15, 12))
        self.assertEqual(self.processor.sequence, original)
        self.assertIn('RAW_LOG_WRITE_FAILED', self.processor.current['errors'])
        with self.assertRaises(BookUnavailable):
            self.processor.book.quote(now_ns=self.now)

    def test_bad_envelopes_fail_closed(self):
        self.live()
        base = dict(sequence=self.processor.sequence+1, recorded_monotonic_ns=self.now+10,
                    recorded_utc='fixture', kind='WS_MESSAGE', session='one',
                    received_monotonic_ns=self.now, wire_text=wire(event(13, 15, 12)))
        for patch in [dict(sequence=999), dict(recorded_monotonic_ns=0),
                      dict(received_monotonic_ns=self.now+100), dict(wire_text='{'),
                      dict(wire_text=wire(event() | dict(s='BTCUSDT'))), dict(kind='UNKNOWN')]:
            with self.subTest(patch=patch):
                processor = deepcopy(self.processor)
                with self.assertRaises((ValueError, TypeError, KeyError)):
                    processor.apply(base | patch)
                self.assertTrue(processor.failed)
                with self.assertRaises(BookUnavailable):
                    processor.book.quote(now_ns=self.now+10)

    def test_snapshot_request_mismatch_and_receive_clock_reject(self):
        self.request()
        base = dict(sequence=self.processor.sequence+1, recorded_monotonic_ns=self.now+10,
                    recorded_utc='fixture', kind='REST_SNAPSHOT', session='one',
                    request_id='request-one', request_started_ns=self.now,
                    received_monotonic_ns=self.now, http_status=200, wire_text=json.dumps(snapshot()))
        for patch in [dict(request_id='other'), dict(http_status=429),
                      dict(received_monotonic_ns=0), dict(request_started_ns=0)]:
            with self.subTest(patch=patch):
                processor = deepcopy(self.processor)
                with self.assertRaises(ValueError):
                    processor.apply(base | patch)
                self.assertTrue(processor.failed)

    def test_second_snapshot_cannot_silently_repair_same_session(self):
        self.live()
        with self.assertRaises(ValueError):
            self.install()
        self.assertTrue(self.processor.failed)

    def test_depth_gap_stops_publication(self):
        self.live()
        self.depth(event(16, 18, 15))
        self.assertTrue(self.processor.failed)
        self.assertEqual(len(self.processor.quotes), 1)
        self.assertIn('UPDATE_CHAIN_GAP', self.processor.current['errors'])

    def test_ticker_is_observation_not_depth_repair(self):
        self.emit('WS_MESSAGE', received_monotonic_ns=self.now,
                  wire_text=json.dumps(dict(stream='btcusdc@bookTicker', data=dict(e='bookTicker', s='BTCUSDC'))))
        self.assertEqual(self.processor.current['ticker_events'], 1)
        self.assertEqual(self.processor.quotes, [])
        self.assertEqual(self.processor.book.state, 'BUFFERING')

    def test_session_reuse_and_duplicate_close_reject(self):
        self.live()
        self.emit('SESSION_END', reason='close')
        self.emit('CLOSE_RESULT', close_code=1000)
        with self.assertRaises(ValueError):
            self.emit('CLOSE_RESULT', close_code=1000)
        with self.assertRaises(ValueError):
            self.emit('SESSION_START', url=PUBLIC_URL)

    def test_snapshot_url_is_explicit_and_not_account_endpoint(self):
        with self.assertRaises(ValueError):
            self.emit('REST_REQUEST', url='https://fapi.binance.com/fapi/v1/order', request_id='bad')
        self.assertTrue(self.processor.failed)


class ReceiverFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_drains_backpressured_socket_without_applying_late_depth(self):
        processor = DepthCaptureProcessor()
        raw = io.StringIO()
        writer = CaptureWriter(raw, processor)
        writer.emit('SESSION_START', 'closing', url=PUBLIC_URL)
        writer.emit('SESSION_END', 'closing', reason='PLANNED_CLIENT_CLOSE')
        queue = asyncio.Queue(maxsize=1)
        await queue.put(wire(event()))
        drained = asyncio.Event()

        class Socket:
            close_code = None
            async def recv(self):
                value = await queue.get()
                drained.set()
                return value
            async def close(self, code):
                # Model a bounded receive queue hiding the close response.
                await asyncio.wait_for(drained.wait(), timeout=.1)
                self.close_code = code

        self.assertTrue(await close_and_drain(Socket(), writer, 'closing'))
        self.assertEqual(processor.quotes, [])
        self.assertEqual(processor.book.state, 'INVALID')
        self.assertEqual(processor.sessions[0]['closing_frames'], 1)
        replay = DepthCaptureProcessor()
        for line in raw.getvalue().splitlines():
            replay.apply(json.loads(line))
        self.assertEqual(replay.summary(), processor.summary())

    async def test_abnormal_close_is_not_success_even_with_ended_session(self):
        processor = DepthCaptureProcessor()
        writer = CaptureWriter(io.StringIO(), processor)
        writer.emit('SESSION_START', 'closing', url=PUBLIC_URL)
        writer.emit('SESSION_END', 'closing', reason='PLANNED_CLIENT_CLOSE')

        class Socket:
            close_code = 1006
            async def recv(self):
                await asyncio.Future()
            async def close(self, code):
                pass

        self.assertFalse(await close_and_drain(Socket(), writer, 'closing'))
        self.assertFalse(processor.sessions[0]['close_confirmed'])

    async def test_disconnect_during_snapshot_wait_never_republishes(self):
        processor = DepthCaptureProcessor()
        writer = CaptureWriter(io.StringIO(), processor)
        states_at_close = []

        class Socket:
            close_code = None
            async def recv(self):
                raise ConnectionError('injected disconnect')
            async def close(self, code):
                states_at_close.append(processor.book.state)
                self.close_code = code

        def fetch():
            started = time.monotonic_ns()
            time.sleep(.02)
            return dict(request_started_ns=started, received_monotonic_ns=time.monotonic_ns(),
                        http_status=200, wire_text=json.dumps(snapshot()))

        self.assertFalse(await capture_session(Socket(), writer, 'failure', .02, fetch))
        self.assertEqual(processor.quotes, [])
        self.assertTrue(processor.failed)
        self.assertEqual(states_at_close, ['INVALID'])
        self.assertTrue(processor.sessions[0]['quote_blocked_after_close'])
        self.assertFalse(processor.summary()['unfinished_session'])

    async def test_snapshot_timeout_closes_socket_and_keeps_book_invalid(self):
        processor = DepthCaptureProcessor()
        writer = CaptureWriter(io.StringIO(), processor)

        class Socket:
            close_code = None
            async def recv(self):
                await asyncio.Future()
            async def close(self, code):
                self.close_code = code

        def fetch():
            raise TimeoutError('injected REST timeout')

        self.assertFalse(await capture_session(Socket(), writer, 'timeout', .02, fetch))
        self.assertTrue(processor.failed)
        self.assertEqual(processor.book.state, 'INVALID')
        self.assertEqual(processor.quotes, [])


if __name__ == '__main__':
    unittest.main()
