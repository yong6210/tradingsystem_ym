"""Offline independent producer threads; bounded queues reveal consumer lag.

Synthetic prices/sequence clocks. Not an exchange simulator or public transport.
Threads share the Python GIL, so scheduled/produced/dequeued counts and producer
lateness are reported separately. Any overflow is terminal, never a silent drop.
"""
import asyncio
import json
from queue import Queue, Empty, Full
import threading
import time


class FixtureOverflow(RuntimeError):
    pass


def book(levels):
    if type(levels) is not int or not 1 <= levels <= 1000: raise ValueError('fixture levels 1..1000')
    return dict(lastUpdateId=10, bids=[[str(10000-i), '2'] for i in range(levels)],
                asks=[[str(10001+i), '4'] for i in range(levels)])


class QueuedSocket:
    def __init__(self, channel, *, per_tick, levels=1000, capacity=1024, period_ns=100_000_000):
        if channel not in ('public', 'market'): raise ValueError('channel')
        if type(per_tick) is not int or not 1 <= per_tick <= 2048: raise ValueError('burst size')
        if type(capacity) is not int or not 1 <= capacity <= 2048: raise ValueError('queue capacity')
        if type(period_ns) is not int or period_ns < 1_000_000: raise ValueError('period')
        self.channel, self.per_tick, self.levels, self.period_ns = channel, per_tick, levels, period_ns
        self.snapshot = book(levels)
        self.queue = Queue(maxsize=capacity)
        self.closed, self.overflow = threading.Event(), threading.Event()
        self.produced = self.received = self.attempted = self.peak_queue = 0
        self.produced_bytes = self.max_residence_ns = self.max_producer_lateness_ns = 0
        self.tick = 0
        self.first_produced_ns = self.last_produced_ns = None
        self.started_ns = time.monotonic_ns()
        self.stopped_ns = None
        self.thread = threading.Thread(target=self._produce, name='offline-feed-'+channel, daemon=True)
        self.thread.start()

    def _frame(self, offset):
        stamp = 1_600_000_000_000+self.tick*100+offset
        if self.channel == 'market':
            stream = 'btcusdc@markPrice@1s'
            data = dict(e='markPriceUpdate', s='BTCUSDC', E=stamp, T=stamp+1000, p='10000', i='10000', r='0')
        elif offset == 0:
            stream = 'btcusdc@depth@100ms'
            last = 12+self.tick
            data = dict(e='depthUpdate', s='BTCUSDC', E=stamp, T=stamp,
                        U=9 if self.tick == 0 else last, u=last, pu=8 if self.tick == 0 else last-1,
                        b=self.snapshot['bids'], a=self.snapshot['asks'])
        else:
            stream = 'btcusdc@bookTicker'
            data = dict(e='bookTicker', s='BTCUSDC', E=stamp, T=stamp, u=12+self.tick,
                        b='10000', B='2', a='10001', A='4')
        return json.dumps(dict(stream=stream, data=data), separators=(',', ':'))

    def _produce(self):
        try:
            while not self.closed.is_set():
                due = self.started_ns+self.tick*self.period_ns
                if self.closed.wait(max(0, (due-time.monotonic_ns())/1e9)): break
                self.max_producer_lateness_ns = max(self.max_producer_lateness_ns, time.monotonic_ns()-due)
                for offset in range(self.per_tick):
                    if self.closed.is_set(): return
                    wire = self._frame(offset)
                    created = time.monotonic_ns()
                    self.attempted += 1
                    try:
                        self.queue.put_nowait((created, wire))
                    except Full:
                        self.overflow.set()
                        return
                    self.produced += 1
                    self.produced_bytes += len(wire.encode())
                    self.first_produced_ns = self.first_produced_ns or created
                    self.last_produced_ns = created
                    self.peak_queue = max(self.peak_queue, self.queue.qsize())
                self.tick += 1
        finally:
            self.stopped_ns = time.monotonic_ns()

    async def recv(self):
        while not self.closed.is_set():
            if self.overflow.is_set(): raise FixtureOverflow('EXTERNAL_PRODUCER_QUEUE_OVERFLOW')
            try:
                created, wire = self.queue.get_nowait()
            except Empty:
                await asyncio.sleep(.001)
                continue
            self.received += 1
            self.max_residence_ns = max(self.max_residence_ns, time.monotonic_ns()-created)
            return wire
        raise RuntimeError('fixture closed')

    async def close(self):
        self.closed.set()
        # Producer never waits for consumer capacity; it observes closed even
        # within a burst. Joining keeps thread ownership explicit on all exits.
        await asyncio.to_thread(self.thread.join, 1)
        if self.thread.is_alive(): raise RuntimeError('producer failed to join')

    def summary(self):
        return dict(channel=self.channel, configured_frames_per_tick=self.per_tick,
            period_ns=self.period_ns, produced=self.produced, received=self.received,
            attempted=self.attempted, queued_at_stop=self.queue.qsize(), peak_queue=self.peak_queue,
            capacity=self.queue.maxsize, overflow=self.overflow.is_set(), produced_wire_bytes=self.produced_bytes,
            max_residence_ns=self.max_residence_ns, max_producer_lateness_ns=self.max_producer_lateness_ns,
            scheduled_by_stop=((self.stopped_ns or time.monotonic_ns())-self.started_ns)//self.period_ns*self.per_tick,
            first_produced_ns=self.first_produced_ns, last_produced_ns=self.last_produced_ns,
            producer_thread_joined=not self.thread.is_alive())


class QueuedTransport:
    def __init__(self, *, per_tick=20, levels=1000, capacity=1024, on_second_snapshot=lambda: None):
        self.per_tick, self.levels, self.capacity = per_tick, levels, capacity
        self.on_second_snapshot = on_second_snapshot
        self.sockets, self.connections = [], []
        self.snapshots = 0

    async def connect(self, channel, url, timeout, *, deadline_ns):
        self.connections.append(dict(channel=channel, started_ns=time.monotonic_ns()))
        socket = QueuedSocket(channel, per_tick=self.per_tick if channel == 'public' else 1,
            period_ns=100_000_000 if channel == 'public' else 1_000_000_000,
            levels=self.levels, capacity=self.capacity)
        self.sockets.append(socket)
        return socket

    async def snapshot(self, timeout, *, deadline_ns):
        self.snapshots += 1
        if self.snapshots == 2: self.on_second_snapshot()
        began = time.monotonic_ns()
        wire = json.dumps(book(self.levels))
        return dict(request_started_ns=began, received_ns=time.monotonic_ns(),
                    received_utc_ns=time.time_ns(), http_status=200, wire_text=wire)
