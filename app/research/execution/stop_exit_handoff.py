"""Offline cancel/reconcile/close handoff; no network adapter or live entry path.

A cancel acknowledgement never supplies the target order's fills. Only the
shared account gate's complete, position-conserving view can free capacity.
One handoff writer per account epoch; frozen gate/dispatchers stay unchanged.
"""
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json

from .account_exit_gate import TERMINAL
from .protection_coordinator import ProtectiveReceipt


@dataclass(frozen=True)
class CancelRequest:
    command_id: str
    account: str
    scope: str
    target: str
    delivery: str


@dataclass(frozen=True)
class CancelAck:
    command_id: str
    target: str
    accepted: bool  # Request outcome only, not target order evidence.
    version: int


class NoSubmission:
    def submit(self, command):
        raise RuntimeError('flat cleanup must never submit')

    def lookup(self, command):
        raise RuntimeError('flat cleanup requires supplied account evidence')


class StopExitHandoff:
    def __init__(self, gate, coordinator, bridge):
        if bridge.gate is not gate:
            raise ValueError('one shared gate required')
        self.gate, self.coordinator, self.bridge, self.db = gate, coordinator, bridge, gate.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS handoff_state (
                id INTEGER PRIMARY KEY CHECK(id=1), scope TEXT NOT NULL, fixed_stop TEXT NOT NULL,
                started_ms INTEGER NOT NULL, evaluated_ms INTEGER NOT NULL, phase TEXT NOT NULL,
                uncovered_since INTEGER, original_side INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS handoff_cancels (
                command_id TEXT PRIMARY KEY, scope TEXT NOT NULL, target TEXT UNIQUE NOT NULL,
                delivery TEXT NOT NULL, ack_version INTEGER NOT NULL DEFAULT -1, accepted INTEGER);
            CREATE TABLE IF NOT EXISTS handoff_alarms (
                reason TEXT PRIMARY KEY, first_ms INTEGER NOT NULL, last_ms INTEGER NOT NULL,
                delivery TEXT NOT NULL DEFAULT 'PENDING_LOCAL');
            CREATE TABLE IF NOT EXISTS handoff_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, detail TEXT NOT NULL);
        ''')

    def _audit(self, kind, detail):
        self.db.execute('INSERT INTO handoff_audit(kind,detail) VALUES (?,?)',
                        (kind, json.dumps(detail, default=str, sort_keys=True)))

    def _alarm(self, reason, now):
        self.db.execute('''INSERT INTO handoff_alarms(reason,first_ms,last_ms) VALUES (?,?,?)
            ON CONFLICT(reason) DO UPDATE SET last_ms=max(last_ms,excluded.last_ms)''', (reason, now, now))

    def requests(self):
        return [CancelRequest(r['command_id'], self.gate.account, r['scope'], r['target'], r['delivery'])
                for r in self.db.execute('SELECT * FROM handoff_cancels ORDER BY rowid')]

    def status(self):
        row = self.db.execute('SELECT * FROM handoff_state').fetchone()
        return dict(state=dict(row) if row else None,
                    freeze_new_entry=bool(row) or bool(self.gate.status()['reconciliation_latches']),
                    cancel_requests=[vars(r) for r in self.requests()],
                    alarms=[dict(r) for r in self.db.execute('SELECT * FROM handoff_alarms ORDER BY reason')])

    def _blocked(self, reason, now):
        with self.gate.transaction():
            self.db.execute('INSERT OR IGNORE INTO gate_latches VALUES (?)', ('HANDOFF_' + reason,))
            self.db.execute("UPDATE handoff_state SET phase='ACCOUNT_BLOCKED',evaluated_ms=max(evaluated_ms,?)", (now,))
            self._alarm(reason, now)
            self._audit('BLOCKED', dict(reason=reason))
        return dict(phase='ACCOUNT_BLOCKED', reason=reason, freeze_new_entry=True)

    def _matches(self, view, snapshot):
        if (view.account != self.gate.account or view.version != snapshot.version or
                view.position != snapshot.position or view.observed_ms != snapshot.observed_ms or not snapshot.reconciled):
            return False
        active = [o for o in view.orders if o.status not in TERMINAL]
        entries = {o.order_id for o in active if o.kind == 'ENTRY'}
        if entries != set(snapshot.entry_ids):
            return False
        stops = {o.order_id: o for o in active if o.kind == 'STOP'}
        protection = {p.client_id: p for p in snapshot.protection if p.status in ('ACTIVE', 'PENDING', 'UNKNOWN')}
        if stops.keys() != protection.keys():
            return False
        expected_status = {'ACTIVE': 'ACTIVE', 'NEW': 'PENDING', 'PARTIALLY_FILLED': 'PENDING', 'UNKNOWN': 'UNKNOWN'}
        for key, order in stops.items():
            p = protection[key]
            if (p.side != order.side or p.quantity != order.quantity-order.executed or not p.reduce_only or
                    p.status != expected_status[order.status] or p.observed_ms != view.observed_ms):
                return False
        exits = [o for o in active if o.kind == 'EXIT']
        known_qty = sum((o.quantity-o.executed for o in exits if o.status != 'UNKNOWN'), Decimal(0))
        return (snapshot.pending_exit_quantity == known_qty and
                snapshot.exit_status_unknown == any(o.status == 'UNKNOWN' for o in exits))

    def _sync_local_receipts(self, view):
        commands = {r['command_id']: r for r in self.coordinator.db.execute('SELECT * FROM protective_commands')}
        for order in view.orders:
            row = commands.get(order.order_id)
            if not row or order.status == 'UNKNOWN':
                continue
            if (row['kind'] != order.kind or row['side'] != order.side or Decimal(row['quantity']) != order.quantity or
                    row['delivery'] in ('READY', 'SUPERSEDED')):
                raise ValueError('local/account order identity or submission mismatch')
            self.coordinator.receipt(ProtectiveReceipt(order.order_id, row['scope'], order.status, order.executed, order.version))

    def advance(self, view, snapshot, *, now_ms):
        if type(now_ms) is not int or now_ms < 0:
            raise ValueError('nonnegative clock required')
        state = self.db.execute('SELECT * FROM handoff_state').fetchone()
        if state and (state['scope'] != snapshot.scope or Decimal(state['fixed_stop']) != snapshot.fixed_stop or
                      now_ms < state['evaluated_ms']):
            return self._blocked('BINDING_OR_CLOCK_CHANGED', now_ms)
        if not self._matches(view, snapshot):
            return self._blocked('EXPOSURE_MISMATCH', now_ms)
        result = self.gate.observe(view, now_ms=now_ms)
        if result != 'OBSERVED' or self.gate.status()['reconciliation_latches']:
            return self._blocked('ACCOUNT_RECONCILIATION_REQUIRED', now_ms)
        try:
            # Sync before the newer local exposure, so the frozen receipt barrier
            # is crossed only by a complete subsequent account observation.
            self._sync_local_receipts(view)
            decision = self.coordinator.reconcile(snapshot, now_ms=now_ms)['decision']
        except ValueError:
            return self._blocked('LOCAL_ORDER_RECONCILIATION_REQUIRED', now_ms)
        if not state and not decision['halted_reason']:
            freeze = (any(r['kind'] == 'FREEZE_NEW_ENTRY' for r in decision['requirements']) or
                      bool(self.gate.status()['unresolved_claims']) or
                      any(o.status == 'UNKNOWN' for o in view.orders))
            return dict(phase='NOT_REQUIRED', freeze_new_entry=freeze)
        if state and snapshot.position and state['original_side'] * snapshot.position < 0:
            return self._blocked('POSITION_REVERSED_DURING_HANDOFF', now_ms)
        orders = {o.order_id: o for o in view.orders}
        targets = [o for o in view.orders if o.kind in ('STOP', 'ENTRY') and o.status not in TERMINAL]
        # Transfer only proven-unsent cancellation intents from the local
        # supervisor. Already submitted ones remain its reconciliation work.
        external_cancels = set()
        target_ids = {o.order_id for o in targets}
        self.coordinator.db.execute('BEGIN IMMEDIATE')
        try:
            for c in self.coordinator.commands(snapshot.scope):
                if c.kind != 'CANCEL' or c.target not in target_ids:
                    continue
                if c.delivery == 'READY':
                    self.coordinator.db.execute("UPDATE protective_commands SET delivery='SUPERSEDED' WHERE command_id=? AND delivery='READY'", (c.command_id,))
                    self.coordinator.db.execute('INSERT INTO protective_audit(scope,kind,detail) VALUES (?,?,?)',
                                                (snapshot.scope, 'HANDOFF_CANCEL_OWNER', json.dumps(dict(command_id=c.command_id))))
                elif c.delivery != 'SUPERSEDED':
                    external_cancels.add(c.target)
            self.coordinator.db.execute('COMMIT')
        except BaseException:
            self.coordinator.db.execute('ROLLBACK')
            raise
        if not snapshot.position:
            for c in self.coordinator.commands(snapshot.scope):
                if c.kind in ('STOP', 'EXIT') and c.delivery == 'READY':
                    self.bridge.protection(self.coordinator, c.command_id, NoSubmission(),
                                           account=view.account, snapshot=snapshot, now_ms=now_ms)
        unknown = [o for o in view.orders if o.status == 'UNKNOWN']
        active_exits = [o for o in view.orders if o.kind == 'EXIT' and o.status not in TERMINAL]
        gate_status = self.gate.status()
        if unknown or gate_status['unresolved_claims'] or external_cancels:
            phase = 'RECONCILE_ACCOUNT'
        elif targets:
            phase = 'CANCEL_AND_RECONCILE'
        elif active_exits:
            phase = 'RECONCILE_EXISTING_EXIT'
        elif not snapshot.position:
            phase = 'FLAT_HALTED' if gate_status['flat_reconciled'] else 'RECONCILE_ACCOUNT'
        else:
            phase = 'EXIT_READY'
        with self.gate.transaction():
            if state is None:
                self.db.execute('INSERT INTO handoff_state VALUES (1,?,?,?,?,?,?,?)',
                                (snapshot.scope, str(snapshot.fixed_stop), now_ms, now_ms, phase, None,
                                 1 if snapshot.position >= 0 else -1))
                state = self.db.execute('SELECT * FROM handoff_state').fetchone()
            gap = snapshot.position != 0 and Decimal(decision['covered_quantity']) < abs(snapshot.position)
            since = (state['uncovered_since'] if state['uncovered_since'] is not None else now_ms) if gap else None
            self.db.execute('UPDATE handoff_state SET phase=?,evaluated_ms=?,uncovered_since=?', (phase, now_ms, since))
            for target in targets:
                if target.status == 'UNKNOWN' or target.order_id in external_cancels:
                    continue
                identity = 'hc_' + hashlib.sha256(f'{view.account}|{snapshot.scope}|{target.order_id}'.encode()).hexdigest()[:28]
                self.db.execute('INSERT OR IGNORE INTO handoff_cancels(command_id,scope,target,delivery) VALUES (?,?,?,?)',
                                (identity, snapshot.scope, target.order_id, 'READY'))
            for request in self.requests():
                if orders[request.target].status in TERMINAL:
                    self.db.execute("UPDATE handoff_cancels SET delivery='SATISFIED_BY_ORDER' WHERE command_id=?", (request.command_id,))
            if gap:
                self._alarm('OBSERVED_PROTECTION_GAP', now_ms)
                if now_ms-since >= 1000:
                    self._alarm('PROTECTION_GAP_TIMEOUT', now_ms)
            if targets and now_ms-state['started_ms'] >= 1000:
                self._alarm('CANCEL_RECONCILIATION_TIMEOUT', now_ms)
            if unknown or gate_status['unresolved_claims']:
                self._alarm('ORDER_OUTCOME_UNRESOLVED', now_ms)
            if external_cancels:
                self._alarm('EXISTING_CANCEL_REQUIRES_RECONCILIATION', now_ms)
            self._audit('ADVANCE', dict(phase=phase, version=view.version, position=str(view.position)))
        return dict(phase=phase, freeze_new_entry=True, observed_uncovered_since=since,
                    remaining_position=str(view.position), cancel_targets=[o.order_id for o in targets],
                    externally_owned_cancels=sorted(external_cancels))

    def acknowledge(self, ack):
        if not isinstance(ack, CancelAck) or type(ack.accepted) is not bool or type(ack.version) is not int or ack.version < 0:
            raise ValueError('invalid cancel acknowledgement')
        with self.gate.transaction():
            row = self.db.execute('SELECT * FROM handoff_cancels WHERE command_id=?', (ack.command_id,)).fetchone()
            if row is None or row['target'] != ack.target or row['delivery'] == 'READY':
                raise ValueError('cancel identity/state mismatch')
            if ack.version < row['ack_version']:
                return
            if row['accepted'] is not None and bool(row['accepted']) != ack.accepted:
                raise ValueError('conflicting cancel outcome')
            delivery = 'ACKNOWLEDGED' if ack.accepted else 'REJECTED'
            if row['delivery'] == 'SATISFIED_BY_ORDER':
                delivery = row['delivery']
            self.db.execute('UPDATE handoff_cancels SET delivery=?,ack_version=?,accepted=? WHERE command_id=?',
                            (delivery, ack.version, int(ack.accepted), ack.command_id))
            if not ack.accepted:
                now = self.db.execute('SELECT evaluated_ms FROM handoff_state').fetchone()[0]
                self._alarm('CANCEL_REQUEST_REJECTED', now)
            self._audit('CANCEL_ACK', vars(ack))

    def dispatch_cancel(self, identity, transport, view, snapshot, *, now_ms, fault=None):
        result = self.advance(view, snapshot, now_ms=now_ms)
        if result['phase'] == 'ACCOUNT_BLOCKED':
            return 'ACCOUNT_BLOCKED'
        request = next(r for r in self.requests() if r.command_id == identity)
        if request.delivery in ('ACKNOWLEDGED', 'REJECTED', 'SATISFIED_BY_ORDER'):
            return request.delivery
        if request.delivery != 'READY':
            try:
                ack = transport.lookup(request)
                if ack is None:
                    return 'UNRESOLVED_NOT_FOUND'
                self.acknowledge(ack)
                return 'QUERIED'
            except Exception:
                return 'UNRESOLVED_QUERY'
        target = next(o for o in view.orders if o.order_id == request.target)
        if target.status == 'UNKNOWN':
            return 'RECONCILE_TARGET'
        with self.gate.transaction():
            claimed = self.db.execute("UPDATE handoff_cancels SET delivery='SENDING' WHERE command_id=? AND delivery='READY'", (identity,)).rowcount
            if not claimed:
                return 'CLAIMED_ELSEWHERE'
            self._audit('CANCEL_CLAIMED', dict(command_id=identity))
        if fault:
            fault('after_cancel_claim_before_send')
        try:
            ack = transport.submit(request)
            if fault:
                fault('after_cancel_accept_before_ack')
            self.acknowledge(ack)
            return 'ACKNOWLEDGED' if ack.accepted else 'REJECTED'
        except Exception:
            with self.gate.transaction():
                self.db.execute("UPDATE handoff_cancels SET delivery='UNCERTAIN' WHERE command_id=? AND delivery='SENDING'", (identity,))
                self._alarm('CANCEL_OUTCOME_UNRESOLVED', now_ms)
            return 'UNCERTAIN'

    def dispatch_exit(self, transport, view, snapshot, *, now_ms, fault=None):
        for _ in range(2):  # At most retire one obsolete local READY command.
            result = self.advance(view, snapshot, now_ms=now_ms)
            if result['phase'] != 'EXIT_READY':
                return result['phase']
            commands = self.coordinator.commands(snapshot.scope)
            ready = [c for c in commands if c.kind == 'EXIT' and c.delivery == 'READY']
            if not ready:
                return 'LOCAL_RECONCILIATION_REQUIRED'
            result = self.bridge.protection(self.coordinator, ready[0].command_id, transport,
                                            account=view.account, snapshot=snapshot, now_ms=now_ms, fault=fault)
            if result != 'SUPERSEDED':
                return result
        return 'REPLAN_REQUIRED'
