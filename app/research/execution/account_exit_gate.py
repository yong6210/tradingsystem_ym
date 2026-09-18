"""Offline account-wide close reservations, shared by both frozen dispatchers.

One SQLite file per account/symbol/epoch, never a live exchange adapter. Complete
snapshots must retain all orders observed in this epoch, including terminal ones.
Conditional stops consume capacity conservatively until confirmed canceled.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

ZERO = Decimal(0)
TERMINAL = {'FILLED', 'CANCELED', 'EXPIRED', 'REJECTED'}


def finite(value, *, nonnegative=False):
    if not isinstance(value, Decimal) or not value.is_finite() or (nonnegative and value < 0):
        raise ValueError('finite Decimal required')


def encode(value):
    return json.dumps(asdict(value), default=str, sort_keys=True)


@dataclass(frozen=True)
class AccountOrder:
    order_id: str
    kind: str  # ENTRY, EXIT, STOP
    side: int
    quantity: Decimal
    executed: Decimal
    status: str
    version: int  # Reconciler sequence, not exchange timestamp.
    reduce_only: bool

    def __post_init__(self):
        finite(self.quantity, nonnegative=True)
        finite(self.executed, nonnegative=True)
        if not self.order_id or self.kind not in ('ENTRY', 'EXIT', 'STOP'):
            raise ValueError('invalid order identity')
        if type(self.side) is not int or self.side not in (-1, 1) or type(self.reduce_only) is not bool:
            raise ValueError('invalid side/reduce-only')
        if self.quantity <= 0 or self.executed > self.quantity or type(self.version) is not int or self.version < 0:
            raise ValueError('invalid quantity/version')
        if self.status not in TERMINAL | {'NEW', 'ACTIVE', 'PARTIALLY_FILLED', 'UNKNOWN'}:
            raise ValueError('invalid status')
        if self.kind != 'ENTRY' and not self.reduce_only:
            raise ValueError('all closes must be explicitly reduce-only')
        if self.kind == 'ENTRY' and self.reduce_only:
            raise ValueError('a reducing order cannot be labeled ENTRY')
        if self.status == 'FILLED' and self.executed != self.quantity:
            raise ValueError('FILLED disagrees with quantity')
        if self.status in ('NEW', 'ACTIVE', 'REJECTED') and self.executed:
            raise ValueError('unfilled status carries executions')
        if self.status == 'PARTIALLY_FILLED' and not ZERO < self.executed < self.quantity:
            raise ValueError('invalid partial fill')
        if self.status == 'ACTIVE' and self.kind != 'STOP':
            raise ValueError('ACTIVE is reserved for conditional stops')


@dataclass(frozen=True)
class AccountView:
    account: str  # Exact offline account/symbol/epoch identity.
    version: int
    observed_ms: int
    position: Decimal
    complete: bool
    orders: tuple[AccountOrder, ...]

    def __post_init__(self):
        finite(self.position)
        if not self.account or any(type(v) is not int or v < 0 for v in (self.version, self.observed_ms)):
            raise ValueError('invalid account/version/time')
        if type(self.complete) is not bool or not isinstance(self.orders, tuple):
            raise ValueError('explicit completeness and tuple of orders required')
        if any(not isinstance(o, AccountOrder) for o in self.orders):
            raise ValueError('invalid order observation')
        if len({o.order_id for o in self.orders}) != len(self.orders):
            raise ValueError('duplicate order IDs')


@dataclass(frozen=True)
class ExitIntent:
    account: str
    command_id: str
    lane: str
    source_id: str
    kind: str
    side: int
    quantity: Decimal

    def __post_init__(self):
        finite(self.quantity, nonnegative=True)
        if not all((self.account, self.command_id, self.source_id)) or self.lane not in ('fallback', 'protection'):
            raise ValueError('explicit account/command/source identity required')
        if self.kind not in ('EXIT', 'STOP') or self.quantity <= 0 or type(self.side) is not int or self.side not in (-1, 1):
            raise ValueError('only reducing exit/stop intents supported')


class AccountExitGate:
    def __init__(self, path: str | Path, account: str):
        if not account:
            raise ValueError('account identity required')
        self.account = account
        self.db = sqlite3.connect(str(path), isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS gate_identity (id INTEGER PRIMARY KEY CHECK(id=1), account TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS account_view (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS exit_claims (command_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                view_version INTEGER NOT NULL, released INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS gate_latches (reason TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS gate_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, detail TEXT);
        ''')
        with self.transaction():
            self.db.execute('INSERT OR IGNORE INTO gate_identity VALUES (1,?)', (account,))
            if self.db.execute('SELECT account FROM gate_identity').fetchone()[0] != account:
                raise ValueError('gate database belongs to another account/epoch')

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def view(self):
        row = self.db.execute('SELECT payload FROM account_view').fetchone()
        return json.loads(row[0]) if row else None

    def _audit(self, kind, detail):
        self.db.execute('INSERT INTO gate_audit(kind,detail) VALUES (?,?)', (kind, json.dumps(detail, default=str, sort_keys=True)))

    def _mismatch(self, current: AccountView, previous):
        new = {o.order_id: asdict(o) for o in current.orders}
        old = {o['order_id']: o for o in previous['orders']} if previous else {}
        if not old.keys() <= new.keys():
            return 'KNOWN_ORDER_MISSING'
        change = ZERO
        for identity, order in new.items():
            before = old.get(identity)
            if before:
                for key in ('kind', 'side', 'quantity', 'reduce_only'):
                    a, b = order[key], before[key]
                    if key == 'quantity':
                        b = Decimal(b)
                    if a != b:
                        return 'ORDER_IDENTITY_CHANGED'
                old_fill = Decimal(before['executed'])
                if order['version'] < before['version'] or order['executed'] < old_fill:
                    return 'ORDER_EVIDENCE_REGRESSED'
                if order['version'] == before['version'] and (order['executed'] != old_fill or order['status'] != before['status']):
                    return 'CONFLICTING_ORDER_VERSION'
                if before['status'] in TERMINAL and (order['status'] != before['status'] or order['executed'] != old_fill):
                    return 'TERMINAL_ORDER_CHANGED'
            else:
                old_fill = ZERO
            change += order['side'] * (order['executed'] - old_fill)
        if previous and current.position - Decimal(previous['position']) != change:
            return 'POSITION_FILL_MISMATCH'
        for row in self.db.execute('SELECT * FROM exit_claims'):
            claim = json.loads(row['payload'])
            order = new.get(row['command_id'])
            if order and (order['kind'] != claim['kind'] or order['side'] != claim['side'] or
                          order['quantity'] != Decimal(claim['quantity']) or not order['reduce_only']):
                return 'CLAIM_ORDER_IDENTITY_MISMATCH'
        return None

    def observe(self, current: AccountView, *, now_ms: int):
        if current.account != self.account or type(now_ms) is not int or now_ms < 0:
            raise ValueError('wrong account or clock')
        with self.transaction():
            old = self.view()
            reason = None
            if not current.complete or not 0 <= now_ms - current.observed_ms <= 1000:
                reason = 'STALE_OR_INCOMPLETE_ACCOUNT'
            elif old and (current.version < old['version'] or current.observed_ms < old['observed_ms']):
                reason = 'ACCOUNT_EVIDENCE_REGRESSED'
            elif old and current.version == old['version'] and encode(current) != json.dumps(old, sort_keys=True):
                reason = 'CONFLICTING_ACCOUNT_VERSION'
            if not reason:
                reason = self._mismatch(current, old)
            if reason:
                # A rejected update must invalidate old authorization, even if
                # the last good snapshot is less than one second old.
                self.db.execute('INSERT OR IGNORE INTO gate_latches VALUES (?)', (reason,))
                self._audit('OBSERVATION_BLOCKED', dict(reason=reason, version=current.version))
                return reason
            self.db.execute('INSERT OR REPLACE INTO account_view VALUES (1,?)', (encode(current),))
            orders = {o.order_id: o for o in current.orders}
            for row in self.db.execute('SELECT * FROM exit_claims WHERE released=0').fetchall():
                order = orders.get(row['command_id'])
                if order and order.status in TERMINAL and current.version > row['view_version']:
                    self.db.execute('UPDATE exit_claims SET released=1 WHERE command_id=?', (row['command_id'],))
            self._audit('OBSERVED', dict(version=current.version, position=str(current.position)))
            return 'OBSERVED'

    def claims(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM exit_claims ORDER BY rowid')]

    def status(self):
        view = self.view()
        orders = {o['order_id']: o for o in view['orders']} if view else {}
        active = [o for o in orders.values() if o['status'] not in TERMINAL]
        claims = self.claims()
        unresolved = [r['command_id'] for r in claims if r['released'] == 0 and r['command_id'] not in orders]
        latches = [r[0] for r in self.db.execute('SELECT reason FROM gate_latches ORDER BY reason')]
        return dict(account=self.account, view_version=view['version'] if view else None,
                    position=view['position'] if view else None, unresolved_claims=unresolved,
                    active_order_ids=[o['order_id'] for o in active], reconciliation_latches=latches,
                    conditional_stops_requiring_coordination=[o['order_id'] for o in active if o['kind'] == 'STOP'],
                    flat_reconciled=bool(view and Decimal(view['position']) == 0 and not active and
                                         not unresolved and not latches and all(r['released'] for r in claims)))

    def release_unsent(self, intent: ExitIntent):
        """Bridge-only proof: owning dispatcher rejected before transport invocation.

        Never call on a timeout, not-found query, exception, or crashed worker.
        """
        with self.transaction():
            row = self.db.execute('SELECT payload FROM exit_claims WHERE command_id=?', (intent.command_id,)).fetchone()
            if row is None or row[0] != encode(intent):
                raise ValueError('unsent release identity mismatch')
            self.db.execute('UPDATE exit_claims SET released=2 WHERE command_id=?', (intent.command_id,))
            self._audit('PROVEN_NOT_SENT', dict(command_id=intent.command_id))

    def claim(self, intent: ExitIntent, *, view_version: int, now_ms: int, fault=None):
        if (intent.account != self.account or type(now_ms) is not int or now_ms < 0 or
                type(view_version) is not int or view_version < 0):
            raise ValueError('wrong intent account or clock')
        with self.transaction():
            existing = self.db.execute('SELECT * FROM exit_claims WHERE command_id=?', (intent.command_id,)).fetchone()
            if existing:
                if existing['payload'] != encode(intent):
                    raise ValueError('command ID reused across lanes or quantities')
                if existing['released'] != 2:
                    return 'ALREADY_CLAIMED'
            view = self.view()
            if self.db.execute('SELECT 1 FROM gate_latches LIMIT 1').fetchone():
                reason = 'ACCOUNT_RECONCILIATION_LATCHED'
            elif not view or view['version'] != view_version or not 0 <= now_ms-view['observed_ms'] <= 1000:
                reason = 'REFRESH_ACCOUNT'
            else:
                position = Decimal(view['position'])
                orders = {o['order_id']: o for o in view['orders']}
                pending = [o for o in orders.values() if o['status'] not in TERMINAL]
                reserved = ZERO
                reason = None
                if any(o['status'] == 'UNKNOWN' for o in pending):
                    reason = 'UNKNOWN_ACCOUNT_ORDER'
                for order in pending:
                    if order['kind'] != 'ENTRY':
                        if order['side'] * position >= 0:
                            reason = 'WRONG_SIDE_EXISTING_CLOSE'
                        reserved += Decimal(order['quantity']) - Decimal(order['executed'])
                for row in self.db.execute('SELECT * FROM exit_claims WHERE released=0'):
                    # Count a known order once, not once per journal. Unreflected
                    # durable claims remain barriers; there is no timeout release.
                    if row['command_id'] not in orders:
                        reason = 'UNREFLECTED_CLAIM'
                if not reason and (not position or intent.side * position >= 0):
                    reason = 'CLOSE_WOULD_INCREASE_OR_REVERSE'
                if not reason and intent.command_id in orders:
                    reason = 'ORDER_ID_ALREADY_OBSERVED'
                if not reason and intent.quantity > max(ZERO, abs(position)-reserved):
                    reason = 'INSUFFICIENT_UNRESERVED_POSITION'
            if reason:
                self._audit('CLAIM_BLOCKED', dict(command_id=intent.command_id, reason=reason))
                return reason
            self.db.execute('''INSERT INTO exit_claims(command_id,payload,view_version) VALUES (?,?,?)
                ON CONFLICT(command_id) DO UPDATE SET view_version=excluded.view_version,released=0''',
                            (intent.command_id, encode(intent), view_version))
            self._audit('CLAIMED', dict(command_id=intent.command_id, view_version=view_version))
            if fault:
                fault('after_claim_before_commit')
            return 'CLAIMED'
