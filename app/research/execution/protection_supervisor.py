"""Durable post-fill protection supervision; requirements are NOT sent orders.

One cycle per scope, one reconciled writer. No transport, credentials, exchange
client, or market-fallback timer is used. Emergency handling is independent of
the ordinary limit cancellation deadline.
"""
from dataclasses import asdict, dataclass
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3

ZERO = Decimal(0)


def quantity(value: Decimal, *, signed: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or (not signed and value < 0):
        raise ValueError('finite Decimal quantity required')


@dataclass(frozen=True)
class ProtectiveOrder:
    client_id: str
    side: int
    quantity: Decimal
    trigger: Decimal
    reduce_only: bool
    status: str
    observed_ms: int
    working_type: str = 'MARK_PRICE'

    def __post_init__(self):
        quantity(self.quantity)
        quantity(self.trigger)
        if not self.client_id or self.quantity <= 0 or self.trigger <= 0:
            raise ValueError('invalid protective order')
        if type(self.side) is not int or self.side not in (-1, 1) or type(self.reduce_only) is not bool:
            raise ValueError('invalid protective direction')
        if self.status not in ('ACTIVE', 'PENDING', 'UNKNOWN', 'CANCELED', 'FILLED', 'REJECTED'):
            raise ValueError('invalid protection status')
        if type(self.observed_ms) is not int or self.observed_ms < 0:
            raise ValueError('invalid protection observation time')
        if self.working_type not in ('MARK_PRICE', 'CONTRACT_PRICE'):
            raise ValueError('explicit trigger price basis required')


@dataclass(frozen=True)
class Exposure:
    scope: str  # paper-account/symbol/cycle; never shared across accounts or cycles
    version: int  # Reconciler version; not exchange updateTime.
    observed_ms: int
    position: Decimal
    fixed_stop: Decimal
    mark: Decimal
    reconciled: bool
    risk_breached: bool
    pending_exit_quantity: Decimal
    exit_status_unknown: bool
    entry_ids: tuple[str, ...]
    protection: tuple[ProtectiveOrder, ...]

    def __post_init__(self):
        quantity(self.position, signed=True)
        for value in (self.fixed_stop, self.mark, self.pending_exit_quantity):
            quantity(value)
        if not self.scope or self.fixed_stop <= 0 or self.mark <= 0:
            raise ValueError('invalid scope or levels')
        if any(type(v) is not int or v < 0 for v in (self.version, self.observed_ms)):
            raise ValueError('invalid version or observation time')
        if any(type(v) is not bool for v in (self.reconciled, self.risk_breached, self.exit_status_unknown)):
            raise ValueError('explicit reconciled flags required')
        if not isinstance(self.entry_ids, tuple) or any(not isinstance(v, str) or not v for v in self.entry_ids):
            raise ValueError('entry order IDs required')
        if not isinstance(self.protection, tuple) or any(not isinstance(v, ProtectiveOrder) for v in self.protection):
            raise ValueError('protective observations required')
        ids = list(self.entry_ids) + [p.client_id for p in self.protection]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate order identities')
        if self.pending_exit_quantity > abs(self.position):
            raise ValueError('exit reservations exceed reconciled position')


def encode(value) -> str:
    return json.dumps(value, default=str, sort_keys=True)


def assess(exposure: Exposure, *, now_ms: int, uncovered_since: int | None,
           halted_reason: str | None, max_age_ms: int = 1000, grace_ms: int = 1000) -> dict:
    """Pure supervisory decision. A pending stop never counts as protection."""
    if any(type(v) is not int or v < 0 for v in (now_ms, max_age_ms, grace_ms)):
        raise ValueError('invalid clock policy')
    requirements = []
    alarms = []
    def require(kind, **fields):
        requirements.append(dict(kind=kind, **fields))
    fresh = 0 <= now_ms - exposure.observed_ms <= max_age_ms
    if not fresh or not exposure.reconciled:
        require('FREEZE_NEW_ENTRY')
        require('RECONCILE_POSITION_AND_ALL_ORDERS')
        return dict(phase='UNRESOLVED', uncovered_since=uncovered_since,
                    halted_reason=halted_reason, covered_quantity='0', requirements=requirements,
                    alarms=['STALE_OR_UNRECONCILED_EXPOSURE'])
    pos = exposure.position
    active = [p for p in exposure.protection if p.status in ('ACTIVE', 'PENDING', 'UNKNOWN')]
    if not pos:
        require('FREEZE_NEW_ENTRY')
        if exposure.entry_ids or active or exposure.exit_status_unknown:
            require('CLEANUP_AND_RECONCILE_CYCLE_ORDERS')
            alarms.append('FLAT_WITH_UNRESOLVED_ORDERS')
            phase = 'FLAT_CLEANUP_REQUIRED'
        else:
            phase = 'FLAT_HALTED' if halted_reason else 'FLAT_RECONCILED'
        return dict(phase=phase, uncovered_since=None, halted_reason=halted_reason,
                    covered_quantity='0', requirements=requirements, alarms=alarms)
    side = 1 if pos > 0 else -1
    covered = sum((p.quantity for p in active if p.status == 'ACTIVE' and p.reduce_only and
                   p.side == -side and p.trigger == exposure.fixed_stop and p.working_type == 'MARK_PRICE' and
                   0 <= now_ms - p.observed_ms <= max_age_ms), ZERO)
    uncovered = max(ZERO, abs(pos) - covered)
    if uncovered and uncovered_since is None:
        uncovered_since = now_ms
    elif not uncovered:
        uncovered_since = None
    if exposure.risk_breached:
        halted_reason = halted_reason or 'RISK_BREACH'
    invalid = [p.client_id for p in active if p.side != -side or not p.reduce_only or
               p.trigger != exposure.fixed_stop or p.working_type != 'MARK_PRICE']
    if invalid:
        halted_reason = halted_reason or 'PROTECTION_IDENTITY_MISMATCH'
        require('CANCEL_INVALID_PROTECTION', order_ids=invalid)
    if side * (exposure.mark - exposure.fixed_stop) <= 0:
        halted_reason = halted_reason or 'STOP_ALREADY_REACHED'
    if uncovered and now_ms - uncovered_since >= grace_ms:
        halted_reason = halted_reason or 'PROTECTION_TIMEOUT'
    if halted_reason or uncovered:
        require('FREEZE_NEW_ENTRY')
        if exposure.entry_ids:
            require('CANCEL_ENTRY_REMAINDER', order_ids=list(exposure.entry_ids))
    if halted_reason:
        alarms.append(halted_reason)
        if exposure.exit_status_unknown:
            require('RECONCILE_EXISTING_EXIT')
            alarms.append('EXIT_STATUS_UNKNOWN')
        else:
            available = abs(pos) - exposure.pending_exit_quantity
            if available > 0:
                require('URGENT_REDUCE_ONLY_REQUIRED', quantity=str(available), side=-side, reduce_only=True)
            else:
                require('RECONCILE_EXISTING_EXIT')
        phase = 'URGENT_EXIT_REQUIRED'
    elif uncovered:
        alarms.append('PROTECTION_GAP')
        # Unknown or in-flight stop requests must be queried before creating
        # another request. Quantity coverage is checked again on fresh evidence.
        if any(p.status in ('UNKNOWN', 'PENDING') or not 0 <= now_ms - p.observed_ms <= max_age_ms for p in active):
            require('RECONCILE_PROTECTION')
        else:
            require('ENSURE_STOP_REQUIRED', quantity=str(uncovered), side=-side,
                    trigger=str(exposure.fixed_stop), reduce_only=True, working_type='MARK_PRICE')
        phase = 'PROTECTION_REQUIRED'
    else:
        phase = 'PROTECTED'
    return dict(phase=phase, uncovered_since=uncovered_since, halted_reason=halted_reason,
                covered_quantity=str(min(covered, abs(pos))), requirements=requirements, alarms=alarms)


class ProtectionJournal:
    """Atomic observations, current requirements and local alarm outbox.

    Requirements are replaced by the latest complete snapshot, not appended as
    executable orders. Alarm deduplication survives restart. Delivery is separate.
    """
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path), isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS exposure_state (
                scope TEXT PRIMARY KEY, version INTEGER NOT NULL, observed_ms INTEGER NOT NULL,
                evaluated_ms INTEGER NOT NULL, snapshot TEXT NOT NULL, decision TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS requirements (
                scope TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(scope,kind));
            CREATE TABLE IF NOT EXISTS alarms (
                id TEXT PRIMARY KEY, scope TEXT NOT NULL, reason TEXT NOT NULL,
                first_ms INTEGER NOT NULL, last_ms INTEGER NOT NULL, delivery TEXT NOT NULL);
        ''')

    def close(self):
        self.db.close()

    def update(self, exposure: Exposure, *, now_ms: int, fault=None) -> dict:
        payload = encode(asdict(exposure))
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT * FROM exposure_state WHERE scope=?', (exposure.scope,)).fetchone()
            old = json.loads(row['decision']) if row else {}
            if row:
                if exposure.version < row['version'] or exposure.observed_ms < row['observed_ms'] or now_ms < row['evaluated_ms']:
                    raise ValueError('older exposure or evaluation')
                if exposure.version == row['version'] and payload != row['snapshot']:
                    raise ValueError('conflicting same-version exposure')
                if exposure.fixed_stop != Decimal(json.loads(row['snapshot'])['fixed_stop']):
                    raise ValueError('fixed stop changed inside a cycle')
                previous_position = Decimal(json.loads(row['snapshot'])['position'])
                if previous_position * exposure.position < 0:
                    old['halted_reason'] = old.get('halted_reason') or 'POSITION_SIDE_CHANGED'
                if old.get('phase') in ('FLAT_RECONCILED', 'FLAT_HALTED') and exposure.position:
                    old['halted_reason'] = old.get('halted_reason') or 'UNEXPECTED_CYCLE_REOPEN'
            decision = assess(exposure, now_ms=now_ms, uncovered_since=old.get('uncovered_since'),
                              halted_reason=old.get('halted_reason'))
            self.db.execute('INSERT OR REPLACE INTO exposure_state VALUES (?,?,?,?,?,?)',
                            (exposure.scope, exposure.version, exposure.observed_ms, now_ms, payload, encode(decision)))
            if fault:
                fault('after_state_before_requirements')
            self.db.execute('DELETE FROM requirements WHERE scope=?', (exposure.scope,))
            for requirement in decision['requirements']:
                self.db.execute('INSERT INTO requirements VALUES (?,?,?)',
                                (exposure.scope, requirement['kind'], encode(requirement)))
            for reason in decision['alarms']:
                identity = hashlib.sha256(f'{exposure.scope}|{reason}'.encode()).hexdigest()
                self.db.execute('''INSERT INTO alarms VALUES (?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET last_ms=excluded.last_ms''',
                                (identity, exposure.scope, reason, now_ms, now_ms, 'PENDING_LOCAL'))
            self.db.execute('COMMIT')
            return decision
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
