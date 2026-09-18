"""Offline protection requirements → durable commands → reconciled fill deltas.

Single account writer per database; all sends require an explicit fake transport.
No network implementation is supplied. Never synthesizes an original-order fill.
"""
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from typing import Protocol

from .binance_contract import Contract, decimal
from .protection_supervisor import Exposure, ProtectionJournal, encode

ZERO = Decimal(0)
TERMINAL = {'FILLED', 'CANCELED', 'REJECTED', 'EXPIRED'}


@dataclass(frozen=True)
class ProtectiveCommand:
    command_id: str
    scope: str
    kind: str  # STOP, EXIT, CANCEL; all quantity orders reduce-only.
    target: str | None
    side: int
    quantity: Decimal
    trigger: Decimal | None
    delivery: str
    status: str | None
    executed: Decimal


@dataclass(frozen=True)
class ProtectiveReceipt:
    command_id: str
    scope: str
    status: str
    executed: Decimal
    version: int


class ProtectionTransport(Protocol):
    def submit(self, command: ProtectiveCommand) -> ProtectiveReceipt: ...
    def lookup(self, command: ProtectiveCommand) -> ProtectiveReceipt | None: ...


class ProtectionCoordinator:
    def __init__(self, journal: ProtectionJournal, contract: Contract):
        self.journal = journal
        self.db = journal.db
        self.contract = contract
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS protective_commands (
                command_id TEXT PRIMARY KEY, scope TEXT NOT NULL, kind TEXT NOT NULL,
                target TEXT, side INTEGER NOT NULL, quantity TEXT NOT NULL, trigger TEXT,
                delivery TEXT NOT NULL, status TEXT, executed TEXT NOT NULL DEFAULT '0',
                receipt_version INTEGER NOT NULL DEFAULT -1, planned_version INTEGER NOT NULL,
                receipt_exposure_version INTEGER NOT NULL DEFAULT -1);
            CREATE TABLE IF NOT EXISTS protective_fill_deltas (
                command_id TEXT NOT NULL, receipt_version INTEGER NOT NULL, quantity TEXT NOT NULL,
                PRIMARY KEY(command_id, receipt_version));
            CREATE TABLE IF NOT EXISTS protective_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL);
        ''')

    def command(self, identity: str) -> ProtectiveCommand:
        row = self.db.execute('SELECT * FROM protective_commands WHERE command_id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError(identity)
        return ProtectiveCommand(row['command_id'], row['scope'], row['kind'], row['target'], row['side'],
                                 Decimal(row['quantity']), Decimal(row['trigger']) if row['trigger'] else None,
                                 row['delivery'], row['status'], Decimal(row['executed']))

    def commands(self, scope: str) -> list[ProtectiveCommand]:
        return [self.command(r[0]) for r in self.db.execute(
            'SELECT command_id FROM protective_commands WHERE scope=? ORDER BY rowid', (scope,)).fetchall()]

    def _audit(self, scope: str, kind: str, detail) -> None:
        self.db.execute('INSERT INTO protective_audit(scope,kind,detail) VALUES (?,?,?)', (scope, kind, encode(detail)))

    def _submission_block(self, command: ProtectiveCommand, snapshot: Exposure) -> str | None:
        if command.kind == 'CANCEL':
            return None
        others = [c for c in self.commands(snapshot.scope) if c.command_id != command.command_id]
        if snapshot.exit_status_unknown or any(c.delivery in ('SENDING', 'UNCERTAIN') for c in others):
            return 'RECONCILE_SUBMITTED_ORDER'
        if self.db.execute('''SELECT 1 FROM protective_commands WHERE scope=?
            AND receipt_exposure_version>=? AND kind IN ('STOP','EXIT') LIMIT 1''',
                           (snapshot.scope, snapshot.version)).fetchone():
            return 'REFRESH_EXPOSURE_AFTER_RECEIPT'
        active = {p.client_id for p in snapshot.protection if p.status == 'ACTIVE'}
        if any(c.kind == 'STOP' and c.delivery == 'ACKNOWLEDGED' and c.command_id not in active for c in others):
            return 'STOP_ACK_NOT_REFLECTED_IN_EXPOSURE'
        if any(c.kind == 'EXIT' and c.delivery == 'ACKNOWLEDGED' for c in others):
            return 'RECONCILE_EXISTING_EXIT'
        return None

    def _quantity_check(self, kind: str, qty: Decimal, side: int, trigger, snapshot: Exposure) -> None:
        self.contract.check(order_type='MARKET', side='BUY' if side == 1 else 'SELL', quantity=qty,
                            mark_price=snapshot.mark, reduce_only=True, position_quantity=snapshot.position)
        if kind == 'STOP':
            price_filter = self.contract.filter('PRICE_FILTER')
            low, high, tick = (decimal(price_filter[k]) for k in ('minPrice', 'maxPrice', 'tickSize'))
            if trigger != snapshot.fixed_stop or trigger <= 0 or tick <= 0 or (trigger - low) % tick:
                raise ValueError('invalid fixed trigger')
            if (low and trigger < low) or (high and trigger > high):
                raise ValueError('trigger outside price bounds')
            if side * (snapshot.mark - trigger) >= 0:
                raise ValueError('stop already reached')

    def reconcile(self, snapshot: Exposure, *, now_ms: int, fault=None) -> dict:
        """Persist supervision first; atomically reserve immutable commands next.

        A crash in between leaves recoverable requirements, not an unrecorded send.
        Any terminal response requires a later full exposure version before a new
        quantity command. This prevents a stale position from refilling a close.
        """
        decision = self.journal.update(snapshot, now_ms=now_ms)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            latest = self.db.execute('SELECT version FROM exposure_state WHERE scope=?', (snapshot.scope,)).fetchone()
            if latest['version'] != snapshot.version:
                raise ValueError('exposure advanced concurrently')
            existing = self.commands(snapshot.scope)
            pending = [c for c in existing if c.delivery in ('SENDING', 'UNCERTAIN')]
            barriers = self.db.execute('''SELECT command_id FROM protective_commands WHERE scope=?
                AND receipt_exposure_version>=? AND kind IN ('STOP','EXIT')''',
                                      (snapshot.scope, snapshot.version)).fetchall()
            created, blocked = [], []
            for requirement in decision['requirements']:
                kind = requirement['kind']
                if kind in ('CANCEL_ENTRY_REMAINDER', 'CANCEL_INVALID_PROTECTION'):
                    candidates = [('CANCEL', target, 0, ZERO, None) for target in requirement['order_ids']]
                elif kind == 'CLEANUP_AND_RECONCILE_CYCLE_ORDERS':
                    targets = list(snapshot.entry_ids) + [p.client_id for p in snapshot.protection if p.status in ('ACTIVE', 'PENDING', 'UNKNOWN')]
                    candidates = [('CANCEL', target, 0, ZERO, None) for target in targets]
                elif kind == 'ENSURE_STOP_REQUIRED':
                    candidates = [('STOP', None, requirement['side'], Decimal(requirement['quantity']), Decimal(requirement['trigger']))]
                elif kind == 'URGENT_REDUCE_ONLY_REQUIRED':
                    candidates = [('EXIT', None, requirement['side'], Decimal(requirement['quantity']), None)]
                else:
                    continue
                for command_kind, target, side, qty, trigger in candidates:
                    same = [c for c in existing if c.kind == command_kind and c.target == target]
                    if command_kind == 'CANCEL':
                        # One cancel intent per target; uncertainty is queried.
                        if same:
                            continue
                    else:
                        if pending or barriers or snapshot.exit_status_unknown:
                            blocked.append('RECONCILE_SUBMITTED_ORDER_AND_NEW_EXPOSURE')
                            continue
                        if any(c.delivery == 'READY' or (command_kind == 'EXIT' and c.delivery == 'ACKNOWLEDGED') for c in same):
                            continue
                        active_stop_ids = {p.client_id for p in snapshot.protection if p.status == 'ACTIVE'}
                        if any(c.kind == 'STOP' and c.delivery == 'ACKNOWLEDGED' and c.command_id not in active_stop_ids for c in existing):
                            blocked.append('STOP_ACK_NOT_REFLECTED_IN_EXPOSURE')
                            continue
                        try:
                            self._quantity_check(command_kind, qty, side, trigger, snapshot)
                        except ValueError as exc:
                            blocked.append('CONTRACT:' + str(exc))
                            continue
                    identity = 'pg_' + hashlib.sha256(f'{snapshot.scope}|{command_kind}|{target}|{len(same)}'.encode()).hexdigest()[:28]
                    self.db.execute('''INSERT INTO protective_commands
                        (command_id,scope,kind,target,side,quantity,trigger,delivery,planned_version)
                        VALUES (?,?,?,?,?,?,?,?,?)''',
                                    (identity, snapshot.scope, command_kind, target, side, str(qty),
                                     str(trigger) if trigger is not None else None, 'READY', snapshot.version))
                    created.append(identity)
                    existing.append(self.command(identity))
                    if fault:
                        fault('after_command_before_commit')
            self._audit(snapshot.scope, 'PLAN', dict(version=snapshot.version, created=created, blocked=blocked))
            self.db.execute('COMMIT')
            outstanding = [c.command_id for c in self.commands(snapshot.scope)
                           if c.delivery not in ('TERMINAL', 'SUPERSEDED')]
            # A flat snapshot cannot erase this coordinator's unresolved sends.
            complete = (decision['phase'] in ('FLAT_RECONCILED', 'FLAT_HALTED') and not outstanding and not barriers)
            active_ids = {p.client_id for p in snapshot.protection if p.status == 'ACTIVE'}
            unreflected = any(c.kind == 'STOP' and c.delivery == 'ACKNOWLEDGED' and
                             c.command_id not in active_ids for c in self.commands(snapshot.scope))
            phase = 'UNRESOLVED_COMMANDS_OR_RECEIPTS' if pending or barriers or unreflected else decision['phase']
            if not snapshot.position and outstanding:
                phase = 'FLAT_COMMAND_RECONCILIATION_REQUIRED'
            return dict(decision=decision, created=created, blocked=blocked,
                        execution_phase=phase, outstanding_commands=outstanding, cycle_reconciled=complete)
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def receipt(self, receipt: ProtectiveReceipt) -> None:
        if (type(receipt.version) is not int or receipt.version < 0 or
                not isinstance(receipt.executed, Decimal) or not receipt.executed.is_finite() or receipt.executed < 0):
            raise ValueError('invalid receipt version/quantity')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            command = self.command(receipt.command_id)
            row = self.db.execute('SELECT * FROM protective_commands WHERE command_id=?', (receipt.command_id,)).fetchone()
            allowed = {'CANCELED', 'REJECTED'} if command.kind == 'CANCEL' else TERMINAL | {'ACTIVE', 'NEW', 'PARTIALLY_FILLED'}
            if receipt.scope != command.scope or receipt.status not in allowed or command.delivery in ('READY', 'SUPERSEDED'):
                raise ValueError('receipt identity/state mismatch')
            if receipt.executed > command.quantity or (receipt.status == 'FILLED' and receipt.executed != command.quantity):
                raise ValueError('receipt exceeds or disagrees with quantity')
            if receipt.status in ('ACTIVE', 'NEW', 'REJECTED') and receipt.executed:
                raise ValueError('unfilled status has executions')
            if receipt.status == 'ACTIVE' and command.kind != 'STOP':
                raise ValueError('only stop can be active')
            if receipt.status == 'PARTIALLY_FILLED' and not ZERO < receipt.executed < command.quantity:
                raise ValueError('invalid partial fill')
            if receipt.version < row['receipt_version']:
                self.db.execute('COMMIT')
                return
            if receipt.version == row['receipt_version']:
                if receipt.executed != command.executed or receipt.status != command.status:
                    raise ValueError('conflicting duplicate receipt')
                self.db.execute('COMMIT')
                return
            if receipt.executed < command.executed or (command.status in TERMINAL and (receipt.executed != command.executed or receipt.status != command.status)):
                raise ValueError('receipt regressed or terminal changed')
            version = self.db.execute('SELECT version FROM exposure_state WHERE scope=?', (command.scope,)).fetchone()[0]
            delivery = 'TERMINAL' if receipt.status in TERMINAL else 'ACKNOWLEDGED'
            self.db.execute('''UPDATE protective_commands SET delivery=?,status=?,executed=?,receipt_version=?,
                receipt_exposure_version=? WHERE command_id=?''',
                            (delivery, receipt.status, str(receipt.executed), receipt.version, version, command.command_id))
            delta = receipt.executed - command.executed
            if delta:
                self.db.execute('INSERT INTO protective_fill_deltas VALUES (?,?,?)', (command.command_id, receipt.version, str(delta)))
            if command.kind == 'STOP' and receipt.status in ('REJECTED', 'EXPIRED'):
                state = self.db.execute('SELECT decision FROM exposure_state WHERE scope=?', (command.scope,)).fetchone()
                decision = json.loads(state['decision'])
                decision['halted_reason'] = decision.get('halted_reason') or 'PROTECTION_REJECTED'
                self.db.execute('UPDATE exposure_state SET decision=? WHERE scope=?', (encode(decision), command.scope))
            self._audit(command.scope, 'RECEIPT', dict(command_id=command.command_id, status=receipt.status,
                                                       executed=str(receipt.executed), version=receipt.version))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def _still_required(self, command: ProtectiveCommand, snapshot: Exposure) -> bool:
        row = self.db.execute('SELECT decision FROM exposure_state WHERE scope=?', (snapshot.scope,)).fetchone()
        requirements = json.loads(row['decision'])['requirements']
        if command.kind == 'CANCEL':
            return command.target in snapshot.entry_ids or command.target in {
                p.client_id for p in snapshot.protection if p.status in ('ACTIVE', 'PENDING', 'UNKNOWN')}
        required_kind = 'ENSURE_STOP_REQUIRED' if command.kind == 'STOP' else 'URGENT_REDUCE_ONLY_REQUIRED'
        for required in requirements:
            if (required['kind'] == required_kind and command.side == required['side'] and
                    command.quantity <= Decimal(required['quantity'])):
                if command.kind == 'STOP' and command.trigger != Decimal(required['trigger']):
                    return False
                self._quantity_check(command.kind, command.quantity, command.side, command.trigger, snapshot)
                return True
        return False

    def dispatch(self, identity: str, transport: ProtectionTransport, *, snapshot: Exposure,
                 now_ms: int, fault=None) -> str:
        command = self.command(identity)
        if command.scope != snapshot.scope:
            raise ValueError('wrong dispatch scope')
        if command.delivery in ('TERMINAL', 'SUPERSEDED'):
            return command.delivery
        if command.delivery != 'READY':
            try:
                receipt = transport.lookup(command)
                if receipt is None:
                    return 'UNRESOLVED_NOT_FOUND'
                self.receipt(receipt)
                return self.command(identity).delivery
            except Exception:
                return 'UNRESOLVED_QUERY'
        self.reconcile(snapshot, now_ms=now_ms)
        if not snapshot.reconciled or not 0 <= now_ms - snapshot.observed_ms <= 1000:
            return 'REFRESH_EXPOSURE'
        self.db.execute('BEGIN IMMEDIATE')
        try:
            command = self.command(identity)
            if command.delivery != 'READY':
                self.db.execute('COMMIT')
                return 'CLAIMED_ELSEWHERE'
            block = self._submission_block(command, snapshot)
            if block:
                self._audit(command.scope, 'SEND_BLOCKED', dict(command_id=identity, reason=block))
                self.db.execute('COMMIT')
                return block
            try:
                needed = self._still_required(command, snapshot)
            except ValueError as exc:
                self._audit(command.scope, 'CONTRACT_BLOCKED', dict(command_id=identity, reason=str(exc)))
                self.db.execute('COMMIT')
                return 'CONTRACT_BLOCKED'
            if not needed:
                self.db.execute("UPDATE protective_commands SET delivery='SUPERSEDED' WHERE command_id=?", (identity,))
                self.db.execute('COMMIT')
                return 'SUPERSEDED'
            self.db.execute("UPDATE protective_commands SET delivery='SENDING' WHERE command_id=?", (identity,))
            self._audit(command.scope, 'CLAIM', dict(command_id=identity, exposure_version=snapshot.version))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        if fault:
            fault('after_claim_before_send')
        try:
            response = transport.submit(self.command(identity))
            if fault:
                fault('after_send_before_receipt')
            self.receipt(response)
            return self.command(identity).delivery
        except Exception as exc:
            self.db.execute("UPDATE protective_commands SET delivery='UNCERTAIN' WHERE command_id=? AND delivery='SENDING'", (identity,))
            self._audit(command.scope, 'UNCERTAIN', dict(command_id=identity, error=type(exc).__name__))
            return 'UNCERTAIN'
