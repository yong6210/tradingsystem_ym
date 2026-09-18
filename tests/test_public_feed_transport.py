import asyncio
import json
import time
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from websockets.exceptions import ConnectionClosedError

from app.research.data.public_feed_transport import PublicFeedTransport, PublicSocket
from app.research.data.bounded_feed_collector import RetryableTransportError
from app.research.data.durable_market_feed import SNAPSHOT_URL


class PublicTransportTests(unittest.IsolatedAsyncioTestCase):
    def client_patch(self, handler):
        original=httpx.AsyncClient
        return patch('httpx.AsyncClient', side_effect=lambda **kwargs: original(
            transport=httpx.MockTransport(handler), **kwargs))

    async def test_fixed_public_snapshot_endpoint_and_native_times(self):
        requests=[]
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=dict(lastUpdateId=10,bids=[],asks=[]))
        with self.client_patch(handler):
            result=await PublicFeedTransport().snapshot(1)
        self.assertEqual(str(requests[0].url), SNAPSHOT_URL)
        self.assertEqual(requests[0].method, 'GET')
        self.assertNotIn('authorization', requests[0].headers)
        self.assertNotIn('x-mbx-apikey', requests[0].headers)
        self.assertLessEqual(result['request_started_ns'],result['received_ns'])
        self.assertLessEqual(result['received_ns'],time.monotonic_ns())
        self.assertEqual(json.loads(result['wire_text'])['lastUpdateId'],10)

    async def test_http_rate_limit_and_redirect_do_not_retry_or_follow(self):
        for status in (418,429,302,503):
            requests=[]
            def handler(request):
                requests.append(request)
                return httpx.Response(status, headers={'Location':'https://example.invalid/'})
            with self.client_patch(handler):
                with self.assertRaises(ValueError):
                    await PublicFeedTransport().snapshot(1)
            self.assertEqual(len(requests),1)

    async def test_snapshot_transport_failure_is_retryable(self):
        def handler(request):
            raise httpx.ConnectError('offline',request=request)
        with self.client_patch(handler):
            with self.assertRaises(RetryableTransportError):
                await PublicFeedTransport().snapshot(1)

    async def test_oversized_snapshot_rejected(self):
        with self.client_patch(lambda request: httpx.Response(200,content=b'x'*4_000_001)):
            with self.assertRaises(ValueError):
                await PublicFeedTransport().snapshot(1)

    async def test_snapshot_cancellation_closes_pending_response(self):
        started=asyncio.Event()
        class HangingBody(httpx.AsyncByteStream):
            closed=False
            async def __aiter__(self):
                started.set()
                await asyncio.sleep(100)
                yield b'{}'
            async def aclose(self):
                self.closed=True
        body=HangingBody()
        with self.client_patch(lambda request: httpx.Response(200,stream=body)):
            task=asyncio.create_task(PublicFeedTransport().snapshot(1))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(body.closed)

    async def test_socket_end_maps_to_transport_failure(self):
        socket=AsyncMock()
        socket.recv.side_effect=ConnectionClosedError(None,None)
        with self.assertRaises(RetryableTransportError):
            await PublicSocket(socket).recv()

    async def test_socket_cancellation_is_not_converted_to_retry(self):
        socket=AsyncMock()
        socket.recv.side_effect=asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await PublicSocket(socket).recv()

    async def test_unapproved_socket_endpoint_is_refused_without_connect(self):
        with patch('websockets.asyncio.client.connect') as connect:
            with self.assertRaises(ValueError):
                await PublicFeedTransport().connect('public','wss://example.invalid',1)
        connect.assert_not_called()

    async def test_late_socket_start_does_not_open_connection(self):
        from app.research.data.durable_market_feed import PUBLIC_URL
        with patch('websockets.asyncio.client.connect') as connect:
            with self.assertRaises(RetryableTransportError):
                await PublicFeedTransport().connect('public',PUBLIC_URL,1,deadline_ns=time.monotonic_ns()-1)
        connect.assert_not_called()

    async def test_client_setup_crossing_deadline_does_not_start_http(self):
        calls=[]
        original=httpx.AsyncClient
        def late_client(**kwargs):
            time.sleep(.02)
            return original(transport=httpx.MockTransport(lambda request: calls.append(request)),**kwargs)
        with patch('httpx.AsyncClient',side_effect=late_client):
            with self.assertRaises(asyncio.TimeoutError):
                await PublicFeedTransport().snapshot(1,deadline_ns=time.monotonic_ns()+5_000_000)
        self.assertEqual(calls,[])


if __name__=='__main__':
    unittest.main()
