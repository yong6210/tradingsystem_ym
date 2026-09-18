import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from app.research.data.bounded_feed_collector import (
    DurableJsonl, FeedEpoch, RetryBudget, RetryableTransportError, run_bounded, NS,
)
from app.research.data.durable_capture_log import iter_committed
from app.research.foundation.forward_data_contract import load_contract
from tests.test_local_order_book import snapshot, event
from tests.test_durable_market_feed import mark

ROOT = Path(__file__).resolve().parents[1]


class ScriptedSocket:
    def __init__(self, channel, *, disconnect=False, malformed=False):
        self.channel, self.disconnect, self.malformed = channel, disconnect, malformed
        self.closed = asyncio.Event()
        self.count = 0

    async def recv(self):
        try:
            await asyncio.wait_for(self.closed.wait(), timeout=.02)
        except asyncio.TimeoutError:
            pass
        if self.closed.is_set() or (self.disconnect and self.count >= 2):
            raise RetryableTransportError('SCRIPTED_DISCONNECT')
        self.count += 1
        if self.malformed:
            return 'invalid JSON'
        if self.channel == 'public':
            data = event() if self.count == 1 else event(first=11+self.count, last=11+self.count, previous=10+self.count)
            stream = 'btcusdc@depth@100ms'
        else:
            data, stream = mark(E=1000+self.count), 'btcusdc@markPrice@1s'
        return json.dumps(dict(stream=stream, data=data))

    async def close(self):
        self.closed.set()


class ScriptedTransport:
    def __init__(self, *, disconnect_first=False, connect_error=None, malformed=False,
                 hang_channel=None, hang_snapshot=False):
        self.disconnect_first, self.connect_error, self.malformed = disconnect_first, connect_error, malformed
        self.hang_channel, self.hang_snapshot = hang_channel, hang_snapshot
        self.connections, self.sockets = [], []
        self.snapshot_count = self.cancelled_operations = 0

    async def connect(self, channel, url, timeout, *, deadline_ns):
        self.connections.append((channel, time.monotonic_ns()))
        if self.connect_error:
            raise self.connect_error
        if channel == self.hang_channel:
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                self.cancelled_operations += 1
                raise
        socket = ScriptedSocket(channel, disconnect=self.disconnect_first and len(self.connections)==1,
                                malformed=self.malformed and channel=='market')
        self.sockets.append(socket)
        return socket

    async def snapshot(self, timeout, *, deadline_ns):
        self.snapshot_count += 1
        started = time.monotonic_ns()
        if self.hang_snapshot:
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                self.cancelled_operations += 1
                raise
        return dict(request_started_ns=started, received_ns=time.monotonic_ns(),
                    received_utc_ns=time.time_ns(), http_status=200, wire_text=json.dumps(snapshot()))


class RetryBudgetTests(unittest.TestCase):
    def budget(self, end=120*NS):
        return RetryBudget(start_ns=0, end_ns=end, delays_ns=[n*NS for n in (1,2,4,8,16,30)])

    def test_six_retries_then_stop_even_after_successful_intervening_sessions(self):
        budget, now, observed = self.budget(), 0, []
        for _ in range(6):
            decision = budget.after_failure(now)
            observed.append((decision['wake_ns']-now)//NS)
            now = decision['wake_ns']+NS  # A healthy second does not replenish budget.
        self.assertEqual(observed, [1,2,4,8,16,30])
        self.assertEqual(budget.after_failure(now), dict(action='STOP',reason='RETRY_EXHAUSTED'))

    def test_retry_at_or_after_deadline_is_not_scheduled(self):
        for now in (4*NS, 5*NS, 6*NS):
            budget = self.budget(5*NS)
            self.assertEqual(budget.after_failure(now)['action'], 'STOP')
            self.assertEqual(budget.used, 0)

    def test_regressed_or_noninteger_clock_rejected(self):
        budget = self.budget()
        budget.after_failure(NS)
        for now in (NS-1, True, 1.2):
            with self.assertRaises((ValueError, RuntimeError)):
                budget.after_failure(now)


class AuditWriterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'audit.jsonl'
        self.writer = DurableJsonl(self.path, max_bytes=1024)

    def tearDown(self):
        self.writer.close()
        self.temp.cleanup()

    def test_acknowledgement_requires_fsync_and_newline(self):
        original = os.fsync
        calls=[]
        def synced(fd):
            self.assertTrue(self.path.read_bytes().endswith(b'\n'))
            calls.append(fd)
            original(fd)
        with patch('app.research.data.bounded_feed_collector.os.fsync', side_effect=synced):
            receipt = self.writer.append(dict(sequence=1))
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.writer.lines, 1)
        self.assertLessEqual(receipt, time.monotonic_ns())

    def test_fsync_failure_latches_and_cannot_be_retried_as_success(self):
        with patch('app.research.data.bounded_feed_collector.os.fsync', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.writer.append(dict(sequence=1))
        self.assertEqual(self.writer.lines, 0)
        self.assertTrue(self.path.read_bytes())  # Visible bytes are not an acknowledged fence.
        with self.assertRaises(OSError):
            self.writer.append(dict(sequence=2))

    def test_capacity_failure_keeps_existing_bytes(self):
        self.writer.append(dict(sequence=1))
        before = self.path.read_bytes()
        with self.assertRaises(OSError):
            self.writer.append(dict(payload='x'*2000))
        self.assertEqual(self.path.read_bytes(), before)

    def test_existing_file_is_not_overwritten(self):
        with self.assertRaises(FileExistsError):
            DurableJsonl(self.path, max_bytes=1024)


class CollectorIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)/'run'
        self.policy = load_contract(ROOT/'configs/research/forward_data_policy_v1.json')

    def tearDown(self):
        self.temp.cleanup()

    async def run_case(self, transport, duration=200_000_000, **kwargs):
        return await run_bounded(self.output, duration_ns=duration, transport=transport, policy=self.policy, **kwargs)

    def raw(self, index=0):
        return list(iter_committed(self.output/f'epoch-{index:02d}'/'journal'))

    async def test_fixed_deadline_stops_healthy_stream_and_preserves_full_denominator(self):
        transport = ScriptedTransport()
        result = await self.run_case(transport)
        self.assertEqual(result['stop_reason'], 'ORIGINAL_DEADLINE')
        self.assertEqual(result['combined']['quality']['calendar_ns'], 200_000_000)
        self.assertTrue(all(socket.closed.is_set() for socket in transport.sockets))
        self.assertEqual(result['retries_used'], 0)
        self.assertGreater(result['epochs'][0]['eligible_point_observations'], 0)
        self.assertFalse(result['audits'][0]['errors'])
        self.assertTrue(result['audits'][0]['clean_stop_audited'])
        self.assertEqual(result['epochs'][0]['last_audited_sequence'], len(self.raw()))

    async def test_real_retry_delay_new_epoch_same_original_deadline(self):
        transport = ScriptedTransport(disconnect_first=True)
        result = await self.run_case(transport, duration=1_600_000_000)
        self.assertEqual(result['retries_used'], 1)
        self.assertEqual(len(result['epochs']), 2)
        self.assertEqual(result['stop_reason'], 'ORIGINAL_DEADLINE')
        self.assertTrue(all(not row['errors'] for row in result['audits']))
        self.assertEqual(result['combined']['quality']['calendar_ns'], 1_600_000_000)
        windows = [self.raw(index)[0]['payload'] for index in (0,1)]
        self.assertNotEqual(windows[0]['process_epoch'], windows[1]['process_epoch'])
        self.assertEqual(windows[0]['deadline_ns'], windows[1]['deadline_ns'])
        self.assertGreaterEqual(transport.connections[2][1]-transport.connections[0][1], NS)
        self.assertGreater(result['epochs'][1]['eligible_point_observations'], 0)
        stopped = next(row['payload'] for row in self.raw() if row['payload']['kind']=='STOP')
        self.assertEqual(stopped['received_ns'], result['epochs'][0]['failure_detected_ns'])

    async def test_no_retry_that_would_cross_end(self):
        transport = ScriptedTransport(connect_error=RetryableTransportError('offline'))
        result = await self.run_case(transport)
        self.assertEqual(result['stop_reason'], 'RETRY_WOULD_REACH_DEADLINE')
        self.assertEqual(len(transport.connections), 1)
        self.assertEqual(result['combined']['quality']['calendar_ns'], 200_000_000)

    async def test_protocol_rejection_does_not_retry(self):
        transport = ScriptedTransport(connect_error=ValueError('HTTP 429'))
        result = await self.run_case(transport)
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
        self.assertEqual(result['retries_used'], 0)
        self.assertIn('COLLECTOR_FAILURE', result['combined']['quality']['reasons'])

    async def test_malformed_feed_stops_without_resetting_processor_errors(self):
        result = await self.run_case(ScriptedTransport(malformed=True))
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
        self.assertEqual(len(result['epochs']), 1)
        self.assertTrue(result['epochs'][0]['processor_errors'])
        self.assertTrue(result['audits'][0]['errors'])

    async def test_pending_connection_is_cancelled_when_other_socket_fails(self):
        transport = ScriptedTransport(disconnect_first=True, hang_channel='market')
        result = await self.run_case(transport)
        self.assertEqual(transport.cancelled_operations, 1)
        self.assertEqual(transport.snapshot_count, 0)
        self.assertEqual(result['stop_reason'], 'RETRY_WOULD_REACH_DEADLINE')
        self.assertTrue(all(socket.closed.is_set() for socket in transport.sockets))

    async def test_pending_rest_is_cancelled_at_original_end(self):
        transport = ScriptedTransport(hang_snapshot=True)
        result = await self.run_case(transport)
        self.assertEqual(transport.cancelled_operations, 1)
        self.assertEqual(result['stop_reason'], 'ORIGINAL_DEADLINE')
        self.assertFalse(any(row['payload']['kind']=='SNAPSHOT' for row in self.raw()))

    async def test_audit_failure_retains_raw_but_prevents_retry(self):
        original = DurableJsonl.append
        def broken(writer, value):
            if writer.path.name=='batches.jsonl' and writer.lines==1:
                raise OSError('injected audit failure')
            return original(writer, value)
        transport = ScriptedTransport()
        with patch.object(DurableJsonl, 'append', broken):
            result = await self.run_case(transport)
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
        self.assertEqual(len(result['epochs']), 1)
        self.assertGreater(result['audits'][0]['unaudited_committed_records'], 0)
        self.assertEqual(result['epochs'][0]['last_audited_sequence'], 2)

    async def test_raw_preflight_failure_opens_no_network(self):
        transport = ScriptedTransport()
        with patch('app.research.data.bounded_feed_collector.DurableCaptureLog.commit', side_effect=OSError('disk')):
            result = await self.run_case(transport)
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
        self.assertEqual(transport.connections, [])
        self.assertGreater(result['total_raw_bytes'], 0)

    async def test_caller_cancellation_closes_sockets_and_records_stop(self):
        transport = ScriptedTransport()
        task = asyncio.create_task(self.run_case(transport, duration=2*NS))
        while len(transport.sockets)<2:
            await asyncio.sleep(.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(all(socket.closed.is_set() for socket in transport.sockets))
        self.assertTrue(any(row['payload']['kind']=='STOP' for row in self.raw()))
        control = [json.loads(line) for line in (self.output/'supervisor.jsonl').read_text().splitlines()]
        self.assertEqual(control[-1]['kind'], 'CANCELLED')

    async def test_live_mode_cannot_start_full_day_or_replace_existing_run(self):
        transport=ScriptedTransport()
        with self.assertRaises(ValueError):
            await self.run_case(transport, duration=86400*NS)
        self.output.mkdir()
        with self.assertRaises(FileExistsError):
            await self.run_case(transport)
        self.assertFalse(transport.connections)

    async def test_forced_local_close_uses_same_retry_path(self):
        transport=ScriptedTransport()
        result=await self.run_case(transport, duration=1_600_000_000, disconnect_once_after_ns=70_000_000)
        self.assertEqual(len(result['epochs']), 2)
        self.assertTrue(result['epochs'][0]['forced_local_disconnect'])
        self.assertFalse(result['epochs'][1]['forced_local_disconnect'])
        self.assertEqual(result['retries_used'], 1)

    async def test_delayed_retry_timer_cannot_start_after_original_end(self):
        transport=ScriptedTransport(connect_error=RetryableTransportError('offline'))
        original_sleep=asyncio.sleep
        async def delayed_timer(delay):
            await original_sleep(delay+.35 if delay>.5 else delay)
        with patch('app.research.data.bounded_feed_collector.asyncio.sleep', side_effect=delayed_timer):
            result=await self.run_case(transport, duration=1_200_000_000)
        self.assertEqual(len(transport.connections), 1)
        self.assertEqual(result['stop_reason'], 'ORIGINAL_DEADLINE')

    async def test_storage_failure_during_disconnect_cleanup_overrides_retry(self):
        original=DurableJsonl.append
        def fail_stop(writer, value):
            if writer.path.name=='batches.jsonl' and value['observation']['stopped']:
                raise OSError('stop audit storage failure')
            return original(writer, value)
        transport=ScriptedTransport(disconnect_first=True)
        with patch.object(DurableJsonl, 'append', fail_stop):
            result=await self.run_case(transport, duration=2*NS)
        self.assertEqual(result['stop_reason'], 'FATAL_FAILURE')
        self.assertEqual(result['retries_used'], 0)
        self.assertEqual(len(result['epochs']), 1)

    async def test_immediately_available_message_burst_cannot_starve_deadline(self):
        class BurstSocket(ScriptedSocket):
            async def recv(self):
                if self.closed.is_set():
                    raise RetryableTransportError('closed')
                self.count+=1
                # Repeated same mark is valid but must not refresh its timestamp.
                # Before explicit receive-loop yielding, this queue never yields.
                if self.channel=='market':
                    return json.dumps(dict(stream='btcusdc@markPrice@1s',data=mark()))
                return json.dumps(dict(stream='btcusdc@bookTicker',data=dict(
                    e='bookTicker',s='BTCUSDC',E=1000,T=999,u=12,b='100',B='2',a='101',A='4')))
        class BurstTransport(ScriptedTransport):
            async def connect(self,channel,url,timeout,*,deadline_ns):
                self.connections.append((channel,time.monotonic_ns()))
                socket=BurstSocket(channel)
                self.sockets.append(socket)
                return socket
        transport=BurstTransport()
        began=time.monotonic()
        result=await self.run_case(transport)
        self.assertEqual(result['stop_reason'],'ORIGINAL_DEADLINE')
        self.assertLess(time.monotonic()-began,2)
        self.assertTrue(all(socket.closed.is_set() for socket in transport.sockets))


if __name__ == '__main__':
    unittest.main()
