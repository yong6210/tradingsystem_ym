"""Strict offline BTCUSDC diff-depth replay with explicit session boundaries.

Absolute Decimal quantities, bounded pre-snapshot buffering, no silent repair.
This reconstructs observed L2 within snapshot coverage, never queue priority.
"""
from decimal import Decimal, InvalidOperation
import hashlib
import json


class BookUnavailable(RuntimeError):
    pass


def integer(value):
    if type(value) is not int or value < 0:
        raise ValueError('nonnegative integer required')
    return value


def levels(rows, *, snapshot=False):
    if not isinstance(rows, list):
        raise ValueError('level array required')
    result = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != 2 or any(type(v) is not str or len(v) > 64 for v in row):
            raise ValueError('two decimal strings required')
        try:
            price, quantity = map(Decimal, row)
        except InvalidOperation:
            raise ValueError('invalid decimal') from None
        if not price.is_finite() or not quantity.is_finite() or price <= 0 or quantity < 0 or (snapshot and quantity == 0):
            raise ValueError('invalid level bounds')
        if any(abs(v.as_tuple().exponent) > 18 or len(v.as_tuple().digits) > 40 for v in (price, quantity)):
            raise ValueError('decimal representation outside parser bounds')
        if price in result:
            raise ValueError('duplicate price in one side')
        result[price] = quantity
    return result


class LocalOrderBook:
    def __init__(self, *, symbol='BTCUSDC', max_buffer=4096):
        if symbol != 'BTCUSDC' or type(max_buffer) is not int or max_buffer <= 0:
            raise ValueError('explicit BTCUSDC and positive buffer bound required')
        self.symbol, self.max_buffer = symbol, max_buffer
        self.session, self.state = None, 'EMPTY'
        self.sessions = set()
        self.watermark = None
        self.reason = None
        self.bids, self.asks = {}, {}
        self.audit = []

    def _fail(self, reason):
        self.state, self.reason = 'INVALID', reason
        self.buffer = []
        self.audit.append(dict(kind='INVALID', session=self.session, reason=reason))
        return reason

    def begin_session(self, session, *, started_ns):
        integer(started_ns)
        if type(session) is not str or not session or session in self.sessions:
            raise ValueError('new unique connection session required')
        if self.session is not None and started_ns < max(self.started_ns, self.last_receive_ns or 0, self.available_ns or 0):
            raise ValueError('connection clock regressed')
        self.session = session
        self.sessions.add(session)
        self.state, self.reason = 'BUFFERING', None
        self.started_ns = started_ns
        self.last_receive_ns = self.available_ns = self.snapshot_ns = None
        self.snapshot_id = self.last_u = self.last_event_hash = None
        self.bid_floor = self.ask_ceiling = None
        self.bids, self.asks, self.buffer = {}, {}, []
        self.audit.append(dict(kind='SESSION', session=session, started_ns=started_ns))

    def disconnect(self, session):
        if session != self.session:
            return 'OLD_SESSION_IGNORED'
        return self._fail('DISCONNECTED')

    def install_snapshot(self, snapshot, *, session, available_ns):
        if session != self.session:
            return 'OLD_SESSION_IGNORED'
        if self.state != 'BUFFERING':
            return self._fail('SNAPSHOT_REQUIRES_NEW_SESSION')
        try:
            integer(available_ns)
            identity = integer(snapshot['lastUpdateId'])
            if available_ns < self.started_ns or (self.watermark is not None and identity < self.watermark):
                raise ValueError('snapshot clock or update ID regressed')
            if snapshot.get('symbol', self.symbol) != self.symbol:
                raise ValueError('wrong snapshot symbol')
            bids, asks = levels(snapshot['bids'], snapshot=True), levels(snapshot['asks'], snapshot=True)
            if not bids or not asks or list(bids) != sorted(bids, reverse=True) or list(asks) != sorted(asks):
                raise ValueError('nonempty correctly ordered snapshot required')
            if max(bids) >= min(asks):
                raise ValueError('crossed snapshot')
        except (ValueError, KeyError, TypeError):
            return self._fail('INVALID_SNAPSHOT')
        self.bids, self.asks = bids, asks
        self.bid_floor, self.ask_ceiling = min(bids), max(asks)
        self.snapshot_id, self.snapshot_ns = identity, available_ns
        self.available_ns = available_ns
        self.state = 'AWAIT_BRIDGE'
        buffered, self.buffer = self.buffer, []
        for parsed, received_ns in buffered:
            self._apply(parsed, received_ns)
            if self.state == 'INVALID':
                break
        return self.state

    def _parse(self, event):
        if not isinstance(event, dict) or event.get('s') != self.symbol or event.get('e') != 'depthUpdate':
            raise ValueError('wrong depth event identity')
        first, last, previous = (integer(event[k]) for k in ('U', 'u', 'pu'))
        if first > last or previous >= last:
            raise ValueError('invalid update range')
        integer(event['E'])
        integer(event['T'])
        bids, asks = levels(event['b']), levels(event['a'])
        # Market-state equality, not wire JSON whitespace or exchange clock.
        canonical = dict(U=first, u=last, pu=previous,
                         b=[(p.as_integer_ratio(), q.as_integer_ratio()) for p,q in sorted(bids.items())],
                         a=[(p.as_integer_ratio(), q.as_integer_ratio()) for p,q in sorted(asks.items())])
        digest = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
        return first, last, previous, bids, asks, digest

    def ingest(self, event, *, session, received_ns):
        if session != self.session or self.session is None:
            return 'OLD_SESSION_IGNORED'
        if self.state == 'INVALID':
            return 'RESYNC_REQUIRED'
        try:
            integer(received_ns)
            if received_ns < self.started_ns or (self.last_receive_ns is not None and received_ns < self.last_receive_ns):
                return self._fail('RECEIVE_CLOCK_REGRESSED')
            parsed = self._parse(event)
        except (ValueError, KeyError, TypeError):
            return self._fail('MALFORMED_DEPTH')
        self.last_receive_ns = received_ns
        if self.state == 'BUFFERING':
            if len(self.buffer) >= self.max_buffer:
                return self._fail('BUFFER_OVERFLOW')
            self.buffer.append((parsed, received_ns))
            return 'BUFFERED'
        return self._apply(parsed, received_ns)

    def _apply(self, parsed, received_ns):
        first, last, previous, bids, asks, digest = parsed
        if self.state == 'AWAIT_BRIDGE':
            if last < self.snapshot_id:
                return 'BEFORE_SNAPSHOT'
            if not first <= self.snapshot_id <= last:
                return self._fail('SNAPSHOT_BRIDGE_MISSING')
        elif self.state == 'LIVE':
            if last == self.last_u and digest == self.last_event_hash:
                return 'DUPLICATE'
            if last <= self.last_u:
                return self._fail('OUT_OF_ORDER_OR_CONFLICT')
            if previous != self.last_u:
                return self._fail('UPDATE_CHAIN_GAP')
        else:
            return 'RESYNC_REQUIRED'
        next_bids, next_asks = self.bids.copy(), self.asks.copy()
        for side, changes in ((next_bids, bids), (next_asks, asks)):
            for price, quantity in changes.items():
                if quantity == 0:
                    side.pop(price, None)  # Unknown deletions are valid.
                else:
                    side[price] = quantity  # Absolute replacement, never addition.
        if not next_bids or not next_asks:
            return self._fail('EMPTY_BOOK_SIDE')
        best_bid, best_ask = max(next_bids), min(next_asks)
        if best_bid >= best_ask:
            return self._fail('CROSSED_BOOK')
        if best_bid < self.bid_floor or best_ask > self.ask_ceiling:
            return self._fail('SNAPSHOT_COVERAGE_EXHAUSTED')
        self.bids, self.asks = next_bids, next_asks
        self.last_u, self.last_event_hash = last, digest
        self.watermark = max(self.watermark or 0, last)
        self.available_ns = max(self.available_ns, received_ns)
        self.state = 'LIVE'
        return 'APPLIED'

    def quote(self, *, now_ns, max_age_ns=1_000_000_000):
        integer(now_ns)
        integer(max_age_ns)
        if self.state != 'LIVE':
            raise BookUnavailable(self.reason or self.state)
        if not 0 <= now_ns-self.available_ns <= max_age_ns:
            raise BookUnavailable('STALE_OR_FUTURE_BOOK')
        bid, ask = max(self.bids), min(self.asks)
        return dict(session=self.session, u=self.last_u, bid=str(bid), bid_quantity=str(self.bids[bid]),
                    ask=str(ask), ask_quantity=str(self.asks[ask]), available_ns=self.available_ns,
                    complete_bid_floor=str(self.bid_floor), complete_ask_ceiling=str(self.ask_ceiling),
                    full_market_depth_known=False, maker_fill_calibrated=False)

    def checkpoint(self):
        """Audit state, not permission to use a stale or invalid quote."""
        return dict(state=self.state, reason=self.reason, session=self.session, last_u=self.last_u,
                    bids=[[str(p),str(q)] for p,q in sorted(self.bids.items(), reverse=True)],
                    asks=[[str(p),str(q)] for p,q in sorted(self.asks.items())])
