"""Cancellable public WebSocket/REST transport; no credentials or private URLs."""
import asyncio
import time

from .bounded_feed_collector import RetryableTransportError
from .durable_market_feed import PUBLIC_URL, MARKET_URL, SNAPSHOT_URL


def remaining(timeout, deadline_ns):
    value = min(timeout, (deadline_ns-time.monotonic_ns())/1_000_000_000)
    if value <= 0:
        raise asyncio.TimeoutError('original deadline before network request')
    return value


class PublicSocket:
    def __init__(self, socket):
        self.socket = socket

    async def recv(self):
        from websockets.exceptions import ConnectionClosed
        try:
            return await self.socket.recv()
        except (ConnectionClosed, OSError) as exc:
            raise RetryableTransportError(type(exc).__name__) from exc

    async def close(self):
        await self.socket.close(code=1000)


class PublicFeedTransport:
    def __init__(self):
        self.timings = []

    def trace(self, phase):
        if len(self.timings) < 128:
            self.timings.append(dict(phase=phase, monotonic_ns=time.monotonic_ns()))

    async def connect(self, channel, url, timeout, *, deadline_ns=None):
        deadline_ns = deadline_ns if deadline_ns is not None else time.monotonic_ns()+int(timeout*1_000_000_000)
        from websockets.asyncio.client import connect
        if (channel, url) not in (('public', PUBLIC_URL), ('market', MARKET_URL)):
            raise ValueError('unapproved public endpoint')
        try:
            timeout = remaining(timeout, deadline_ns)
            socket = await connect(url, open_timeout=timeout, close_timeout=1,
                                   max_size=4_000_000, max_queue=32, proxy=None)
            return PublicSocket(socket)
        except (OSError, asyncio.TimeoutError) as exc:
            raise RetryableTransportError(type(exc).__name__) from exc

    async def snapshot(self, timeout, *, deadline_ns=None):
        deadline_ns = deadline_ns if deadline_ns is not None else time.monotonic_ns()+int(timeout*1_000_000_000)
        self.trace('snapshot_enter')
        import httpx
        self.trace('httpx_imported')
        started = time.monotonic_ns()
        try:
            async with httpx.AsyncClient(timeout=remaining(timeout, deadline_ns), trust_env=False, follow_redirects=False) as client:
                self.trace('client_created')
                async with client.stream('GET', SNAPSHOT_URL, timeout=remaining(timeout, deadline_ns)) as response:
                    self.trace('response_headers')
                    if response.status_code != 200:
                        # Includes rate limits: never turn a server rejection
                        # into an automatic stream of repeated snapshot calls.
                        raise ValueError('snapshot HTTP status '+str(response.status_code))
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 4_000_000:
                            raise ValueError('snapshot size bound exceeded')
                    received, wall = time.monotonic_ns(), time.time_ns()
                    self.trace('response_read')
            self.trace('response_closed')
            return dict(request_started_ns=started, received_ns=received, received_utc_ns=wall,
                        http_status=200, wire_text=body.decode('utf-8'))
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            raise RetryableTransportError(type(exc).__name__) from exc
