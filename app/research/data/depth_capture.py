"""Replayable public-depth collection envelope, without any network/account code.

Raw envelopes are flushed before processing. Replay uses identical serialized
ordering, while receive and processing clocks remain separate observations.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import time

from .local_order_book import LocalOrderBook, BookUnavailable, integer

PUBLIC_URL = 'wss://fstream.binance.com/public/stream?streams=btcusdc@depth@100ms/btcusdc@bookTicker'
SNAPSHOT_URL = 'https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDC&limit=1000'


def book_digest(book):
    state = book.checkpoint()
    return hashlib.sha256(json.dumps(dict(bids=state['bids'], asks=state['asks']), sort_keys=True).encode()).hexdigest()


class DepthCaptureProcessor:
    def __init__(self):
        self.book = LocalOrderBook()
        self.sequence, self.clock, self.current = 0, -1, None
        self.sessions, self.quotes, self.results = [], [], []
        self.failed = False

    def abort(self, reason):
        self.failed = True
        if self.current:
            self.current['errors'].append(reason)
            self.book.disconnect(self.current['session'])

    def apply(self, record):
        try:
            return self._apply(record)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.abort('INVALID_CAPTURE_ENVELOPE')
            raise

    def _apply(self, record):
        sequence, now = integer(record['sequence']), integer(record['recorded_monotonic_ns'])
        if sequence != self.sequence+1 or now < self.clock:
            raise ValueError('capture sequence or processing clock regressed')
        kind, session = record['kind'], record['session']
        self.sequence, self.clock = sequence, now
        if kind == 'SESSION_START':
            if self.current is not None or record['url'] != PUBLIC_URL:
                raise ValueError('overlapping session or unexpected public URL')
            self.book.begin_session(session, started_ns=now)
            self.current = dict(session=session, started_ns=now, depth_events=0, ticker_events=0,
                                snapshot_requests=0, snapshot_received_ns=None, snapshot_processed_ns=None,
                                first_usable_ns=None, last_usable_ns=None, quotes=0, outcomes=Counter(),
                                errors=[], request_id=None, request_recorded_ns=None)
            outcome = 'BUFFERING'
        elif kind in ('CLOSE_RESULT', 'CLOSING_WS_MESSAGE'):
            if self.current is not None or not self.sessions or self.sessions[-1]['session'] != session:
                raise ValueError('close result without ended session')
            if 'close_code' in self.sessions[-1]:
                raise ValueError('duplicate close result')
            ended = self.sessions[-1]
            if kind == 'CLOSING_WS_MESSAGE':
                received = integer(record['received_monotonic_ns'])
                if not ended['ended_ns'] <= received <= now or type(record['wire_text']) is not str:
                    raise ValueError('invalid closing receive envelope')
                ended['closing_frames'] = ended.get('closing_frames', 0)+1
                outcome = 'CLOSING_FRAME_NOT_APPLIED'
            else:
                ended['close_code'] = record['close_code']
                ended['close_confirmed'] = record['close_code'] == 1000
                ended['close_error'] = record.get('close_error')
                outcome = 'CLOSE_RECORDED'
        else:
            if self.current is None or self.current['session'] != session:
                raise ValueError('record from wrong/ended session')
            current = self.current
            if kind == 'REST_REQUEST':
                if current['snapshot_requests'] or record['url'] != SNAPSHOT_URL or not record['request_id']:
                    raise ValueError('one explicit snapshot per connection session required')
                current['snapshot_requests'] = 1
                current['request_id'], current['request_recorded_ns'] = record['request_id'], now
                outcome = 'SNAPSHOT_REQUESTED'
            elif kind == 'REST_SNAPSHOT':
                start, received = integer(record['request_started_ns']), integer(record['received_monotonic_ns'])
                if (record['request_id'] != current['request_id'] or current['snapshot_received_ns'] is not None or
                        not current['request_recorded_ns'] <= start <= received <= now or record['http_status'] != 200):
                    raise ValueError('snapshot request identity, timestamps or status invalid')
                current['snapshot_received_ns'], current['snapshot_processed_ns'] = received, now
                current['snapshot_roundtrip_ms'] = (received-start)/1e6
                current['snapshot_processing_delay_ms'] = (now-received)/1e6
                outcome = self.book.install_snapshot(json.loads(record['wire_text']), session=session, available_ns=now)
                self._publish(record)
            elif kind == 'WS_MESSAGE':
                received = integer(record['received_monotonic_ns'])
                if not current['started_ns'] <= received <= now:
                    raise ValueError('websocket receive timestamp invalid')
                message = json.loads(record['wire_text'])
                event = message['data']
                if event['s'] != 'BTCUSDC':
                    raise ValueError('wrong public symbol')
                if event['e'] == 'depthUpdate' and message['stream'] == 'btcusdc@depth@100ms':
                    current['depth_events'] += 1
                    outcome = self.book.ingest(event, session=session, received_ns=received)
                    if outcome == 'APPLIED':
                        self._publish(record)
                elif event['e'] == 'bookTicker' and message['stream'] == 'btcusdc@bookTicker':
                    current['ticker_events'] += 1
                    outcome = 'TICKER_RECORDED_ONLY'
                else:
                    raise ValueError('unexpected public stream')
            elif kind == 'ERROR':
                self.abort(record['reason'])
                outcome = 'ABORTED'
            elif kind == 'SESSION_END':
                current['ended_ns'], current['end_reason'] = now, record['reason']
                current['state_before_close'] = self.book.state
                current['final_book_sha256'] = book_digest(self.book)
                self.book.disconnect(session)
                try:
                    self.book.quote(now_ns=now)
                except BookUnavailable:
                    current['quote_blocked_after_close'] = True
                else:
                    raise AssertionError('disconnected book is publishable')
                current['outcomes'] = dict(current['outcomes'])
                self.sessions.append(current)
                self.current = None
                outcome = 'SESSION_CLOSED_FOR_PUBLICATION'
            else:
                raise ValueError('unknown capture record kind')
            if self.current:
                self.current['outcomes'][outcome] += 1
                if self.book.state == 'INVALID' and not self.current['errors']:
                    self.current['errors'].append(self.book.reason)
                    self.failed = True
        self.results.append(dict(sequence=sequence, kind=kind, session=session, outcome=outcome, state=self.book.state))
        return outcome

    def _publish(self, record):
        try:
            quote = self.book.quote(now_ns=record['recorded_monotonic_ns'])
        except BookUnavailable:
            return
        current = self.current
        now = record['recorded_monotonic_ns']
        current['first_usable_ns'] = current['first_usable_ns'] if current['first_usable_ns'] is not None else now
        current['last_usable_ns'], current['quotes'] = now, current['quotes']+1
        self.quotes.append(quote | dict(input_sequence=record['sequence'], published_monotonic_ns=now,
                                      published_utc=record['recorded_utc']))

    def summary(self):
        return dict(failed=self.failed, sessions=self.sessions, unfinished_session=self.current is not None,
                    records=self.sequence, published_quotes=len(self.quotes),
                    book_publishable_now=False if self.current is None else None)


class CaptureWriter:
    def __init__(self, stream, processor, *, monotonic=time.monotonic_ns,
                 utc=lambda: datetime.now(timezone.utc).isoformat()):
        self.stream, self.processor, self.monotonic, self.utc = stream, processor, monotonic, utc

    def emit(self, kind, session, **fields):
        record = dict(fields, sequence=self.processor.sequence+1, kind=kind, session=session,
                      recorded_monotonic_ns=self.monotonic(), recorded_utc=self.utc())
        try:
            self.stream.write(json.dumps(record, separators=(',', ':'))+'\n')
            self.stream.flush()
        except Exception:
            self.processor.abort('RAW_LOG_WRITE_FAILED')
            raise
        self.processor.apply(record)
        return record
