"""Explicit offline integration of frozen fallback and protection dispatchers.

Only close arbitration is integrated. Entry risk budgeting, a live snapshot
producer, account-wide leadership and network transports are deliberately absent.
Do not bypass this bridge for closes belonging to its account epoch.
"""
from decimal import Decimal
import json

from .account_exit_gate import ExitIntent
from .durable_fallback import dispatch_once


class SendWitness:
    def __init__(self, transport):
        self.transport = transport
        self.invoked = False

    def submit(self, command):
        # Set before invoking: an exception may mean accepted-but-response-lost.
        self.invoked = True
        return self.transport.submit(command)

    def lookup(self, command):
        return self.transport.lookup(command)


class AccountExitBridge:
    def __init__(self, gate):
        self.gate = gate

    def _context(self, account, view_version, position, observed_ms):
        if account != self.gate.account:
            raise ValueError('wrong bridge account')
        view = self.gate.view()
        return (view is not None and view['version'] == view_version and
                Decimal(view['position']) == position and view['observed_ms'] == observed_ms)

    def fallback(self, journal, identity, transport, *, account, view_version, position,
                 observed_ms, now_ms, authorize, fault=None):
        command = journal.command(identity)
        if account != self.gate.account:
            raise ValueError('wrong bridge account')
        if command.action.kind == 'MARKET_INTENT' and not command.action.reduce_only:
            return 'ENTRY_RISK_RESERVATION_NOT_IMPLEMENTED'
        if command.delivery != 'READY' or command.action.kind == 'CANCEL_ORIGINAL':
            return dispatch_once(journal, identity, transport, authorize)
        if command.action.kind != 'MARKET_INTENT':
            return 'UNSUPPORTED_COMMAND'
        if not self._context(account, view_version, position, observed_ms):
            return 'ACCOUNT_CONTEXT_MISMATCH'
        original = next((o for o in self.gate.view()['orders'] if o['order_id'] == command.original_id), None)
        state = journal.state(command.original_id)
        local = journal.db.execute('SELECT original_status,original_fill FROM intents WHERE original_id=?',
                                   (command.original_id,)).fetchone()
        if (not original or original['status'] not in ('CANCELED', 'EXPIRED', 'REJECTED') or
                original['status'] != local['original_status'] or Decimal(original['executed']) != Decimal(local['original_fill']) or
                original['kind'] != 'EXIT' or not original['reduce_only'] or original['side'] != state.side or
                Decimal(original['quantity']) != state.quantity):
            return 'ORIGINAL_ACCOUNT_EVIDENCE_MISMATCH'
        if not authorize(command):
            return 'PREFLIGHT_REJECTED'
        intent = ExitIntent(account, identity, 'fallback', command.original_id, 'EXIT',
                            command.action.side, command.action.quantity)
        result = self.gate.claim(intent, view_version=view_version, now_ms=now_ms)
        if result != 'CLAIMED':
            return 'ACCOUNT_' + result
        if fault:
            fault('after_account_claim_before_local_dispatch')
        witness = SendWitness(transport)
        result = dispatch_once(journal, identity, witness, authorize, fault=fault)
        if result == 'BLOCKED' and not witness.invoked:
            self.gate.release_unsent(intent)
        return result

    def protection(self, coordinator, identity, transport, *, account, snapshot, now_ms, fault=None):
        command = coordinator.command(identity)
        if account != self.gate.account or command.scope != snapshot.scope:
            raise ValueError('wrong protection account/scope')
        if command.delivery != 'READY' or command.kind == 'CANCEL':
            return coordinator.dispatch(identity, transport, snapshot=snapshot, now_ms=now_ms)
        if not self._context(account, snapshot.version, snapshot.position, snapshot.observed_ms):
            return 'ACCOUNT_CONTEXT_MISMATCH'
        current = coordinator.reconcile(snapshot, now_ms=now_ms)
        required_kind = 'ENSURE_STOP_REQUIRED' if command.kind == 'STOP' else 'URGENT_REDUCE_ONLY_REQUIRED'
        needed = any(r['kind'] == required_kind and r['side'] == command.side and
                     command.quantity <= Decimal(r['quantity']) and
                     (command.kind != 'STOP' or command.trigger == Decimal(r['trigger']))
                     for r in current['decision']['requirements'])
        if not needed and snapshot.reconciled and 0 <= now_ms-snapshot.observed_ms <= 1000:
            # Retire an obsolete local READY intent before requesting shared
            # capacity. Otherwise an oversized READY intent would block replan.
            coordinator.db.execute('BEGIN IMMEDIATE')
            try:
                version = coordinator.db.execute('SELECT version FROM exposure_state WHERE scope=?', (snapshot.scope,)).fetchone()[0]
                if version != snapshot.version:
                    raise ValueError('local exposure changed during replan')
                changed = coordinator.db.execute("UPDATE protective_commands SET delivery='SUPERSEDED' WHERE command_id=? AND delivery='READY'", (identity,)).rowcount
                coordinator.db.execute('INSERT INTO protective_audit(scope,kind,detail) VALUES (?,?,?)',
                                       (snapshot.scope, 'ACCOUNT_REPLAN', json.dumps(dict(command_id=identity, version=version))))
                coordinator.db.execute('COMMIT')
                return 'SUPERSEDED' if changed else 'CLAIMED_ELSEWHERE'
            except BaseException:
                coordinator.db.execute('ROLLBACK')
                raise
        intent = ExitIntent(account, identity, 'protection', command.scope, command.kind, command.side, command.quantity)
        result = self.gate.claim(intent, view_version=snapshot.version, now_ms=now_ms)
        if result != 'CLAIMED':
            return 'ACCOUNT_' + result
        if fault:
            fault('after_account_claim_before_local_dispatch')
        witness = SendWitness(transport)
        result = coordinator.dispatch(identity, witness, snapshot=snapshot, now_ms=now_ms, fault=fault)
        # These return paths provably precede the frozen dispatcher's submit.
        unsent = {'SUPERSEDED', 'REFRESH_EXPOSURE', 'CONTRACT_BLOCKED', 'RECONCILE_SUBMITTED_ORDER',
                  'REFRESH_EXPOSURE_AFTER_RECEIPT', 'STOP_ACK_NOT_REFLECTED_IN_EXPOSURE', 'RECONCILE_EXISTING_EXIT'}
        if result in unsent and not witness.invoked:
            self.gate.release_unsent(intent)
        return result
