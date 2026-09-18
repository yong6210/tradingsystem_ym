"""Four-feed observation gate behind a durable raw-log commit boundary.

Single-owner calls only. This emits data-quality observations, not fills,
trading signals, continuous coverage certificates, or restored live state.
"""
from collections import Counter
from decimal import Decimal, InvalidOperation
import json
import time

from .depth_capture import PUBLIC_URL, SNAPSHOT_URL
from .local_order_book import LocalOrderBook, BookUnavailable, integer

MARKET_URL = 'wss://fstream.binance.com/market/stream?streams=btcusdc@aggTrade/btcusdc@markPrice@1s'


def decimal_text(value, *, signed=False):
    if type(value) is not str or len(value) > 64:
        raise ValueError('bounded decimal string required')
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError('malformed decimal') from None
    if (not result.is_finite() or (not signed and result <= 0) or
            abs(result.as_tuple().exponent) > 18 or len(result.as_tuple().digits) > 40):
        raise ValueError('invalid decimal bounds')
    return result


class MarketFeedProcessor:
    def __init__(self):
        self.book = LocalOrderBook()
        self.sessions, self.used_sessions = {}, set()
        self.ended_sessions = set()
        self.sequence, self.processed_ns, self.epoch = 0, -1, None
        self.last_receive = {}
        self.mark = None
        self.last_mark = None
        self.deadline_ns = None
        self.mark_received_ns = self.depth_received_ns = self.market_received_ns = None
        self.watchdog_ns = self.clock_anchor = None
        self.last_trade = None
        self.request_id = self.request_ns = None
        self.counts = Counter()
        self.errors = []
        self.closed = False

    def abort(self, reason):
        if reason not in self.errors:
            self.errors.append(reason)
        if self.book.session is not None:
            self.book.disconnect(self.book.session)

    def apply(self, sequence, record, *, processed_ns):
        try:
            self._apply(sequence, record, processed_ns)
        except (ValueError, KeyError, TypeError) as exc:
            self.abort('INVALID_FEED_RECORD:'+str(exc))
            raise

    def _apply(self, sequence, record, processed_ns):
        integer(sequence)
        integer(processed_ns)
        received = integer(record['received_ns'])
        wall = integer(record['received_utc_ns'])
        if sequence != self.sequence+1 or processed_ns < self.processed_ns or received > processed_ns:
            raise ValueError('sequence or causal processing boundary invalid')
        epoch = record['process_epoch']
        if type(epoch) is not str or not epoch or (self.epoch is not None and epoch != self.epoch):
            raise ValueError('process epoch changed; live replay needs a new session')
        self.epoch = epoch
        channel, session, kind = record['channel'], record['session'], record['kind']
        if channel not in ('public', 'market', 'system'):
            raise ValueError('unknown channel')
        if received < self.last_receive.get(channel, 0):
            # REST native receive can precede a WS receive that was serialized
            # first. Its request/response times are validated separately below.
            if kind != 'SNAPSHOT':
                raise ValueError('channel receive clock regressed')
        self.last_receive[channel] = max(received, self.last_receive.get(channel, 0))
        self.sequence, self.processed_ns = sequence, processed_ns
        if kind == 'RUN_WINDOW':
            start, end = integer(record['started_ns']), integer(record['deadline_ns'])
            if channel != 'system' or session != epoch or sequence != 1 or not start <= received < end:
                raise ValueError('invalid fixed collection window')
            self.deadline_ns = end
        elif kind == 'CLOSING_WS':
            if not self.closed or (channel, session) not in self.ended_sessions or type(record['wire_text']) is not str:
                raise ValueError('invalid closing frame scope')
        elif kind == 'FAULT':
            if type(record['reason']) is not str or not record['reason']:
                raise ValueError('fault reason required')
            self.abort(record['reason'])
        elif kind == 'OPEN':
            if (channel == 'system' or channel in self.sessions or type(session) is not str or
                    not session or session in self.used_sessions):
                raise ValueError('new unique channel session required')
            expected = PUBLIC_URL if channel == 'public' else MARKET_URL
            if record['url'] != expected:
                raise ValueError('unexpected endpoint')
            self.used_sessions.add(session)
            self.sessions[channel] = (session, received)
            if channel == 'public':
                self.book.begin_session(session, started_ns=received)
                self.request_id = self.request_ns = self.depth_received_ns = None
            else:
                self.mark = self.mark_received_ns = self.market_received_ns = self.last_trade = self.last_mark = None
        elif kind == 'WATCHDOG':
            if channel != 'system' or session != epoch or self.closed:
                raise ValueError('watchdog scope invalid')
            expected = integer(record['expected_ns'])
            if expected > received:
                raise ValueError('watchdog ran before its scheduled time')
            if received-expected > 500_000_000:
                self.abort('LOOP_LAG_EXCEEDED')
            if self.clock_anchor is None:
                self.clock_anchor = (received, wall)
            else:
                mono0, wall0 = self.clock_anchor
                if abs((wall-wall0)-(received-mono0)) > 100_000_000:
                    self.abort('WALL_MONOTONIC_DRIFT')
            self.watchdog_ns = received
        elif kind == 'STOP':
            if channel != 'system' or session != epoch:
                raise ValueError('stop scope invalid')
            self.closed = True
            if self.book.session is not None:
                self.book.disconnect(self.book.session)
        else:
            if channel not in self.sessions or self.sessions[channel][0] != session or received < self.sessions[channel][1]:
                raise ValueError('wrong or ended connection session')
            if kind == 'END':
                del self.sessions[channel]
                self.ended_sessions.add((channel, session))
                if channel == 'public':
                    self.book.disconnect(session)
                else:
                    self.mark = self.mark_received_ns = self.market_received_ns = None
            elif kind == 'REQUEST':
                if channel != 'public' or self.request_id is not None or record['url'] != SNAPSHOT_URL:
                    raise ValueError('invalid snapshot request')
                if type(record['request_id']) is not str or not record['request_id']:
                    raise ValueError('request identity required')
                self.request_id, self.request_ns = record['request_id'], received
            elif kind == 'SNAPSHOT':
                if (channel != 'public' or self.request_id is None or record['request_id'] != self.request_id or
                        record['http_status'] != 200 or not self.request_ns <= integer(record['request_started_ns']) <= received):
                    raise ValueError('snapshot identity/status/clock invalid')
                self.book.install_snapshot(json.loads(record['wire_text']), session=session, available_ns=processed_ns)
                if self.book.state == 'INVALID':
                    self.abort('DEPTH:'+str(self.book.reason))
            elif kind == 'WS':
                self._message(channel, session, record['wire_text'], received)
            else:
                raise ValueError('unknown record kind')
        self.counts[kind] += 1

    def _message(self, channel, session, wire, received):
        message = json.loads(wire)
        event, stream = message['data'], message['stream']
        if event['s'] != 'BTCUSDC':
            raise ValueError('wrong symbol')
        integer(event['E'])
        integer(event['T'])
        kind = event['e']
        if channel == 'public' and kind == 'depthUpdate' and stream == 'btcusdc@depth@100ms':
            outcome = self.book.ingest(event, session=session, received_ns=received)
            if outcome in ('APPLIED', 'BUFFERED'):
                self.depth_received_ns = received
            if self.book.state == 'INVALID':
                self.abort('DEPTH:'+str(self.book.reason))
        elif channel == 'public' and kind == 'bookTicker' and stream == 'btcusdc@bookTicker':
            integer(event['u'])
            bid, ask = decimal_text(event['b']), decimal_text(event['a'])
            decimal_text(event['B'])
            decimal_text(event['A'])
            if bid >= ask:
                raise ValueError('crossed ticker')
        elif channel == 'market' and kind == 'aggTrade' and stream == 'btcusdc@aggTrade':
            identity, first, last = (integer(event[k]) for k in ('a', 'f', 'l'))
            if first > last or type(event['m']) is not bool:
                raise ValueError('invalid trade range/side')
            price, quantity = decimal_text(event['p']), decimal_text(event['q'])
            canonical = (identity, first, last, price, quantity, event['m'], event['T'])
            if self.last_trade is not None:
                previous = self.last_trade
                if identity == previous[0] and canonical == previous:
                    self.counts['TRADE_DUPLICATE'] += 1
                    return
                if identity <= previous[0]:
                    raise ValueError('trade ID regressed or duplicate conflicts')
                if identity > previous[0]+1:
                    # A conservative observation gap, not a claim that all
                    # Binance aggregate IDs are universally contiguous.
                    self.abort('AGGREGATE_ID_GAP_UNVERIFIED')
            self.last_trade = canonical
            self.market_received_ns = received
        elif channel == 'market' and kind == 'markPriceUpdate' and stream == 'btcusdc@markPrice@1s':
            price, index, rate = decimal_text(event['p']), decimal_text(event['i']), decimal_text(event['r'], signed=True)
            identity = (event['E'], event['T'], price, index, rate)
            if self.last_mark is not None:
                if identity == self.last_mark:
                    self.counts['MARK_DUPLICATE'] += 1
                    return
                if identity[0] <= self.last_mark[0]:
                    raise ValueError('mark event time regressed or duplicate conflicts')
            self.last_mark = identity
            self.mark = dict(price=event['p'], index=event['i'], funding_indication=event['r'],
                             next_funding_time=event['T'], event_time=event['E'])
            self.mark_received_ns = self.market_received_ns = received
        else:
            raise ValueError('event does not match subscribed channel/stream')
        self.counts[kind] += 1

    def observe(self, *, now_ns, committed_ns, committed_sequence):
        integer(now_ns)
        integer(committed_ns)
        integer(committed_sequence)
        if committed_sequence != self.sequence or not self.processed_ns <= committed_ns <= now_ns:
            raise ValueError('observation is ahead of its durable fence')
        def fresh(stamp, age):
            return stamp is not None and 0 <= now_ns-stamp <= age
        quote = None
        if fresh(self.depth_received_ns, 1_000_000_000):
            try:
                quote = self.book.quote(now_ns=now_ns)
            except BookUnavailable:
                pass
        gates = dict(l2=quote is not None,
                     market_connection='market' in self.sessions and fresh(self.market_received_ns, 3_000_000_000),
                     mark=self.mark is not None and fresh(self.mark_received_ns, 3_000_000_000),
                     clock=fresh(self.watchdog_ns, 500_000_000), durable_log=True)
        within_window = self.deadline_ns is not None and now_ns < self.deadline_ns
        eligible = within_window and not self.closed and not self.errors and all(gates.values())
        return dict(sequence=self.sequence, committed_ns=committed_ns, published_ns=now_ns,
                    eligible=eligible, within_window=within_window, gates=gates, errors=list(self.errors), stopped=self.closed,
                    quote=quote if eligible else None, mark=self.mark if eligible else None,
                    maker_fill_calibrated=False)


class DurableFeedBridge:
    """A serialized owner connects fsync receipts to parsing and publication."""
    def __init__(self, journal, *, max_pending=2048, monotonic=time.monotonic_ns):
        if journal.sequence != 0:
            raise ValueError('this bounded probe requires a new journal and live sessions')
        self.journal, self.monotonic, self.max_pending = journal, monotonic, integer(max_pending)
        if not max_pending:
            raise ValueError('positive pending bound required')
        self.processor = MarketFeedProcessor()
        self.pending, self.batches = [], []
        self.failed = False

    def append(self, record):
        if self.failed:
            raise ValueError('bridge failed')
        try:
            if len(self.pending) >= self.max_pending:
                raise ValueError('pending record limit exceeded')
            # Own an immutable serialized copy; callers cannot mutate a queued
            # payload to differ from the raw bytes already written.
            payload = json.loads(json.dumps(record | dict(process_epoch=self.journal.epoch), allow_nan=False))
            sequence = self.journal.append(payload)
            self.pending.append((sequence, payload))
            return sequence
        except Exception:
            self.failed = True
            self.processor.abort('RAW_APPEND_FAILED')
            raise

    def flush(self):
        if self.failed:
            raise ValueError('bridge failed')
        if not self.pending:
            return None
        try:
            receipt = self.journal.commit()
            for sequence, record in self.pending:
                if sequence > receipt.sequence:
                    raise ValueError('uncommitted input')
                self.processor.apply(sequence, record, processed_ns=receipt.available_monotonic_ns)
            observation = self.processor.observe(now_ns=self.monotonic(), committed_ns=receipt.available_monotonic_ns,
                                                committed_sequence=receipt.sequence)
            batch = dict(first_sequence=self.pending[0][0], last_sequence=receipt.sequence,
                         record_sha256=receipt.record_sha256, committed_ns=receipt.available_monotonic_ns,
                         observation=observation)
            self.batches.append(batch)
            self.pending.clear()
            return batch
        except Exception:
            self.failed = True
            self.processor.abort('COMMIT_OR_PROCESSING_FAILED')
            raise
