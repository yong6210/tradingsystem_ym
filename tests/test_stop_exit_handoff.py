from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from app.research.execution.account_exit_gate import AccountExitGate, AccountOrder, AccountView
from app.research.execution.account_exit_bridge import AccountExitBridge
from app.research.execution.protection_coordinator import ProtectionCoordinator
from app.research.execution.protection_supervisor import ProtectionJournal
from app.research.execution.stop_exit_handoff import StopExitHandoff, CancelAck
from tests.test_account_exit_gate import ACCOUNT, order, view
from tests.test_fallback_preflight import contract_fixture
from tests.test_protection_supervisor import exposure, guard
from tests.test_protection_coordinator import PaperTransport


class CancelPaper:
    """Durable request outcomes only; cannot fabricate target order fills."""
    def __init__(self, path, *, lose_response=False, accepted=True):
        self.path, self.lose_response, self.accepted = str(path), lose_response, accepted
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS cancel_acks(id TEXT PRIMARY KEY,target TEXT,accepted INTEGER,version INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS cancel_sends(id TEXT)')

    def submit(self, request):
        with sqlite3.connect(self.path) as db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('INSERT INTO cancel_sends VALUES (?)', (request.command_id,))
            db.execute('INSERT INTO cancel_acks VALUES (?,?,?,1)', (request.command_id, request.target, int(self.accepted)))
        if self.lose_response:
            raise TimeoutError('cancel outcome response lost')
        return self.lookup(request)

    def lookup(self, request):
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT * FROM cancel_acks WHERE id=?', (request.command_id,)).fetchone()
        return CancelAck(row[0], row[1], bool(row[2]), row[3]) if row else None

    def count(self):
        with sqlite3.connect(self.path) as db:
            return db.execute('SELECT count(*) FROM cancel_sends').fetchone()[0]


class HandoffFixture:
    def __init__(self, root, *, seed=True, short=False, trigger=True):
        self.root = Path(root)
        self.gate = AccountExitGate(self.root/'account.sqlite', ACCOUNT)
        self.journal = ProtectionJournal(self.root/'protection.sqlite')
        self.coordinator = ProtectionCoordinator(self.journal, contract_fixture())
        self.bridge = AccountExitBridge(self.gate)
        self.paper = PaperTransport(self.root/'orders.sqlite')
        self.cancel = CancelPaper(self.root/'cancels.sqlite')
        self.handoff = StopExitHandoff(self.gate, self.coordinator, self.bridge)
        if seed:
            self.current = view(position=D('-.003') if short else D('.003'))
            self.fixed_stop = D(61000) if short else D(59000)
            self.gate.observe(self.current, now_ms=1000)
            initial = self.snapshot(risk=False)
            self.coordinator.reconcile(initial, now_ms=1000)
            self.stop_id = self.coordinator.commands(initial.scope)[0].command_id
            assert self.bridge.protection(self.coordinator, self.stop_id, self.paper,
                                          account=ACCOUNT, snapshot=initial, now_ms=1000) == 'ACKNOWLEDGED'
            stop = order(self.stop_id, kind='STOP', side=1 if short else -1, status='ACTIVE')
            self.current = replace(self.current, version=2, observed_ms=1001, orders=(stop,))
            result = self.handoff.advance(self.current, self.snapshot(risk=trigger), now_ms=self.current.observed_ms)
            assert result['phase'] == ('CANCEL_AND_RECONCILE' if trigger else 'NOT_REQUIRED')
        else:
            raw = self.gate.view()
            self.current = AccountView(**(raw | dict(position=D(raw['position']), orders=tuple(
                AccountOrder(**(o | dict(quantity=D(o['quantity']), executed=D(o['executed'])))) for o in raw['orders']))))
            self.fixed_stop = D(self.handoff.status()['state']['fixed_stop'])
            self.stop_id = next(o.order_id for o in self.current.orders if o.kind == 'STOP')

    def close(self):
        self.gate.close()
        self.journal.close()

    def snapshot(self, risk=True):
        active = [o for o in self.current.orders if o.status not in ('FILLED','CANCELED','EXPIRED','REJECTED')]
        mapping = {'ACTIVE':'ACTIVE','NEW':'PENDING','PARTIALLY_FILLED':'PENDING','UNKNOWN':'UNKNOWN'}
        return exposure(version=self.current.version, observed_ms=self.current.observed_ms, position=self.current.position,
                        fixed_stop=self.fixed_stop, risk_breached=risk,
                        entry_ids=tuple(o.order_id for o in active if o.kind=='ENTRY'),
                        pending_exit_quantity=sum((o.quantity-o.executed for o in active if o.kind=='EXIT' and o.status!='UNKNOWN'), D(0)),
                        exit_status_unknown=any(o.kind=='EXIT' and o.status=='UNKNOWN' for o in active),
                        protection=tuple(guard(client_id=o.order_id, side=o.side, quantity=o.quantity-o.executed,
                                               trigger=self.fixed_stop, observed_ms=self.current.observed_ms,
                                               status=mapping[o.status]) for o in active if o.kind=='STOP'))

    def advance(self, **kw):
        return self.handoff.advance(self.current, self.snapshot(), now_ms=self.current.observed_ms, **kw)

    def cancel_id(self):
        return next(r.command_id for r in self.handoff.requests() if r.target==self.stop_id)

    def send_cancel(self, **kw):
        return self.handoff.dispatch_cancel(self.cancel_id(), self.cancel, self.current, self.snapshot(), now_ms=self.current.observed_ms, **kw)

    def send_exit(self):
        return self.handoff.dispatch_exit(self.paper, self.current, self.snapshot(), now_ms=self.current.observed_ms)

    def stop_changes(self, status, executed='0', *, at=None):
        old = next(o for o in self.current.orders if o.order_id==self.stop_id)
        changed = replace(old, status=status, executed=D(executed), version=old.version+1)
        self.current = replace(self.current, version=self.current.version+1,
                               observed_ms=at if at is not None else self.current.observed_ms+1,
                               position=self.current.position+old.side*(D(executed)-old.executed),
                               orders=tuple(changed if o.order_id==self.stop_id else o for o in self.current.orders))
        if status != 'UNKNOWN':
            self.paper.set_receipt(self.coordinator.command(self.stop_id), status, D(executed), changed.version)


class StopExitHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = HandoffFixture(self.tmp.name)

    def tearDown(self):
        self.f.close()
        self.tmp.cleanup()

    def test_cancel_ack_does_not_free_capacity_or_send_exit(self):
        self.assertEqual(self.f.send_cancel(), 'ACKNOWLEDGED')
        self.assertEqual(self.f.send_exit(), 'CANCEL_AND_RECONCILE')
        self.assertEqual(self.f.paper.submit_count(), 1)  # Initial protective stop only.
        self.assertEqual(self.f.gate.claims()[0]['released'], 0)

    def test_cancel_with_no_fill_then_close_full_remaining(self):
        self.f.send_cancel()
        self.f.stop_changes('CANCELED')
        self.assertEqual(self.f.send_exit(), 'TERMINAL')
        exits = [c for c in self.f.coordinator.commands(self.f.snapshot().scope) if c.kind=='EXIT' and c.delivery=='TERMINAL']
        self.assertEqual(exits[0].executed, D('.003'))
        self.assertEqual(self.f.paper.submit_count(), 2)

    def test_partial_fill_during_cancel_only_remaining_is_sent(self):
        self.f.send_cancel()
        self.f.stop_changes('CANCELED', '.001')
        self.assertEqual(self.f.send_exit(), 'TERMINAL')
        exits = [c for c in self.f.coordinator.commands(self.f.snapshot().scope) if c.kind=='EXIT' and c.delivery=='TERMINAL']
        self.assertEqual(exits[0].quantity, D('.002'))
        total = sum(D(r[0]) for r in self.f.journal.db.execute('SELECT quantity FROM protective_fill_deltas'))
        self.assertEqual(total, D('.003'))

    def test_full_stop_fill_racing_cancel_sends_no_market_and_retires_ready_exit(self):
        self.f.cancel.lose_response = True
        self.f.send_cancel()
        self.f.stop_changes('FILLED', '.003')
        self.assertEqual(self.f.send_exit(), 'FLAT_HALTED')
        self.assertEqual(self.f.paper.submit_count(), 1)
        self.assertTrue(self.f.gate.status()['flat_reconciled'])
        self.assertTrue(all(c.delivery in ('TERMINAL','SUPERSEDED') for c in self.f.coordinator.commands(self.f.snapshot().scope)))
        self.assertEqual(self.f.send_cancel(), 'SATISFIED_BY_ORDER')

    def test_partial_stop_still_active_does_not_allow_market(self):
        self.f.send_cancel()
        self.f.stop_changes('PARTIALLY_FILLED', '.001')
        self.assertEqual(self.f.send_exit(), 'CANCEL_AND_RECONCILE')
        self.assertEqual(self.f.paper.submit_count(), 1)

    def test_cancel_lost_response_restart_only_queries(self):
        self.f.cancel.lose_response = True
        self.assertEqual(self.f.send_cancel(), 'UNCERTAIN')
        self.f.close()
        self.f = HandoffFixture(self.tmp.name, seed=False)
        self.assertEqual(self.f.send_cancel(), 'QUERIED')
        self.assertEqual(self.f.cancel.count(), 1)
        self.assertEqual(self.f.send_exit(), 'CANCEL_AND_RECONCILE')

    def test_rejected_cancel_never_retries_but_later_terminal_order_can_release(self):
        self.f.cancel.accepted = False
        self.assertEqual(self.f.send_cancel(), 'REJECTED')
        self.assertEqual(self.f.send_cancel(), 'REJECTED')
        self.assertEqual(self.f.send_exit(), 'CANCEL_AND_RECONCILE')
        self.f.stop_changes('CANCELED')
        self.assertEqual(self.f.send_exit(), 'TERMINAL')
        self.assertEqual(self.f.cancel.count(), 1)

    def test_stop_unknown_and_omitted_protection_never_create_exit(self):
        self.f.stop_changes('UNKNOWN')
        self.assertEqual(self.f.send_exit(), 'RECONCILE_ACCOUNT')
        self.assertEqual(self.f.send_cancel(), 'RECONCILE_TARGET')
        wrong = replace(self.f.snapshot(), protection=())
        result = self.f.handoff.advance(self.f.current, wrong, now_ms=self.f.current.observed_ms)
        self.assertEqual(result['phase'], 'ACCOUNT_BLOCKED')
        self.assertEqual(self.f.paper.submit_count(), 1)

    def test_cancel_identity_conflict_rejected_and_duplicates_idempotent(self):
        self.f.send_cancel()
        ack = self.f.cancel.lookup(self.f.handoff.requests()[0])
        self.f.handoff.acknowledge(ack)
        for bad in (replace(ack, target='other'), replace(ack, accepted=False), replace(ack, version=True)):
            with self.assertRaises(ValueError):
                self.f.handoff.acknowledge(bad)

    def test_gap_and_cancel_timeout_alarms_survive_restart_and_do_not_resend(self):
        self.f.send_cancel()
        self.f.stop_changes('PARTIALLY_FILLED', '.001', at=1002)
        self.f.advance()
        self.f.close()
        self.f = HandoffFixture(self.tmp.name, seed=False)
        self.f.current = replace(self.f.current, version=self.f.current.version+1, observed_ms=2002)
        self.assertEqual(self.f.send_exit(), 'CANCEL_AND_RECONCILE')
        self.f.advance()
        alarms = self.f.handoff.status()['alarms']
        self.assertIn('PROTECTION_GAP_TIMEOUT', [a['reason'] for a in alarms])
        self.assertIn('CANCEL_RECONCILIATION_TIMEOUT', [a['reason'] for a in alarms])
        self.assertEqual(len(alarms), len({a['reason'] for a in alarms}))
        self.assertTrue(all(a['delivery']=='PENDING_LOCAL' for a in alarms))
        self.assertEqual(self.f.cancel.count(), 1)

    def test_account_position_mismatch_is_not_repaired_by_cancel_ack(self):
        self.f.send_cancel()
        self.f.stop_changes('CANCELED', '.001')
        self.f.current = replace(self.f.current, position=D('.003'))
        self.assertEqual(self.f.send_exit(), 'ACCOUNT_BLOCKED')
        self.assertEqual(self.f.paper.submit_count(), 1)

    def test_entry_fill_during_handoff_is_accounted_and_remaining_entry_canceled(self):
        entry = order('late-entry', kind='ENTRY', side=1, quantity=D('.002'), executed=D('.001'), status='PARTIALLY_FILLED', reduce_only=False)
        self.f.current = replace(self.f.current, version=3, observed_ms=1002, position=D('.004'), orders=self.f.current.orders+(entry,))
        self.assertEqual(self.f.advance()['phase'], 'CANCEL_AND_RECONCILE')
        self.assertEqual({r.target for r in self.f.handoff.requests()}, {self.f.stop_id, 'late-entry'})
        locals = [c for c in self.f.coordinator.commands(self.f.snapshot().scope) if c.kind=='CANCEL']
        self.assertTrue(locals and all(c.delivery=='SUPERSEDED' for c in locals))
        self.assertEqual(self.f.send_exit(), 'CANCEL_AND_RECONCILE')

    def test_already_submitted_cancel_in_another_journal_is_not_duplicated(self):
        entry = order('entry-owned-elsewhere', kind='ENTRY', side=1, quantity=D('.001'), status='NEW', reduce_only=False)
        self.f.current = replace(self.f.current, version=3, observed_ms=1002, orders=self.f.current.orders+(entry,))
        self.f.coordinator.reconcile(self.f.snapshot(), now_ms=1002)
        cancel = next(c for c in self.f.coordinator.commands(self.f.snapshot().scope) if c.kind=='CANCEL')
        self.f.paper.lose_response = True
        self.f.coordinator.dispatch(cancel.command_id, self.f.paper, snapshot=self.f.snapshot(), now_ms=1002)
        result = self.f.advance()
        self.assertEqual(result['phase'], 'RECONCILE_ACCOUNT')
        self.assertEqual(result['externally_owned_cancels'], ['entry-owned-elsewhere'])
        self.assertNotIn('entry-owned-elsewhere', {r.target for r in self.f.handoff.requests()})

    def test_market_close_lost_response_is_recovered_from_full_account_evidence(self):
        self.f.send_cancel()
        self.f.stop_changes('CANCELED', '.001')
        self.f.paper.lose_response = True
        self.assertEqual(self.f.send_exit(), 'UNCERTAIN')
        self.assertEqual(self.f.send_exit(), 'RECONCILE_ACCOUNT')
        command = next(c for c in self.f.coordinator.commands(self.f.snapshot().scope) if c.kind=='EXIT' and c.delivery=='UNCERTAIN')
        receipt = self.f.paper.lookup(command)
        filled = order(command.command_id, quantity=command.quantity, executed=receipt.executed,
                       status=receipt.status, version=receipt.version)
        self.f.current = replace(self.f.current, version=4, observed_ms=1003, position=D(0),
                                 orders=self.f.current.orders+(filled,))
        self.assertEqual(self.f.send_exit(), 'FLAT_HALTED')
        self.assertEqual(self.f.paper.submit_count(), 2)
        self.assertEqual(self.f.coordinator.command(command.command_id).delivery, 'TERMINAL')

    def test_active_partial_market_close_blocks_new_exit_until_terminal(self):
        self.f.send_cancel()
        self.f.stop_changes('CANCELED', '.001')
        self.f.paper.status, self.f.paper.executed = 'PARTIALLY_FILLED', D('.001')
        self.assertEqual(self.f.send_exit(), 'ACKNOWLEDGED')
        command = next(c for c in self.f.coordinator.commands(self.f.snapshot().scope) if c.kind=='EXIT' and c.delivery=='ACKNOWLEDGED')
        partial = order(command.command_id, quantity=D('.002'), executed=D('.001'), status='PARTIALLY_FILLED')
        self.f.current = replace(self.f.current, version=4, observed_ms=1003, position=D('.001'), orders=self.f.current.orders+(partial,))
        self.assertEqual(self.f.send_exit(), 'RECONCILE_EXISTING_EXIT')
        expired = replace(partial, status='EXPIRED', version=2)
        self.f.paper.set_receipt(command, 'EXPIRED', D('.001'), 2)
        self.f.current = replace(self.f.current, version=5, observed_ms=1004,
                                 orders=tuple(expired if o.order_id==partial.order_id else o for o in self.f.current.orders))
        self.f.paper.status, self.f.paper.executed = None, None
        self.assertEqual(self.f.send_exit(), 'TERMINAL')
        last = self.f.coordinator.commands(self.f.snapshot().scope)[-1]
        self.assertEqual(last.quantity, D('.001'))
        self.assertEqual(self.f.paper.submit_count(), 3)

    def test_new_scope_and_clock_regression_freeze_handoff(self):
        wrong = replace(self.f.snapshot(), scope='another-cycle')
        self.assertEqual(self.f.handoff.advance(self.f.current, wrong, now_ms=1001)['phase'], 'ACCOUNT_BLOCKED')
        self.assertTrue(self.f.handoff.status()['freeze_new_entry'])

    def test_clock_regression_cannot_reset_timeout(self):
        result = self.f.handoff.advance(self.f.current, self.f.snapshot(), now_ms=1000)
        self.assertEqual(result['reason'], 'BINDING_OR_CLOCK_CHANGED')
        self.assertEqual(self.f.handoff.status()['state']['evaluated_ms'], 1001)

    def test_protected_normal_position_is_not_canceled_until_emergency(self):
        with tempfile.TemporaryDirectory() as temp:
            f = HandoffFixture(temp, trigger=False)
            try:
                self.assertEqual(f.handoff.requests(), [])
                self.assertIsNone(f.handoff.status()['state'])
                f.current = replace(f.current, version=3, observed_ms=1002)
                crossed = replace(f.snapshot(risk=False), mark=D(58000))
                result = f.handoff.advance(f.current, crossed, now_ms=1002)
                self.assertEqual(result['phase'], 'CANCEL_AND_RECONCILE')
                self.assertTrue(result['freeze_new_entry'])
                self.assertEqual(f.cancel.count(), 0)
            finally:
                f.close()

    def test_short_stop_partial_race_closes_only_remaining_buy(self):
        with tempfile.TemporaryDirectory() as temp:
            f = HandoffFixture(temp, short=True)
            try:
                f.send_cancel()
                f.stop_changes('CANCELED', '.001')
                self.assertEqual(f.send_exit(), 'TERMINAL')
                done = next(c for c in f.coordinator.commands(f.snapshot().scope) if c.kind=='EXIT' and c.delivery=='TERMINAL')
                self.assertEqual((done.side, done.quantity), (1, D('.002')))
            finally:
                f.close()

    def child_crash(self, stage):
        code = '''
import os,sys
from tests.test_stop_exit_handoff import HandoffFixture
f=HandoffFixture(sys.argv[1],seed=False)
def crash(stage):
    if stage==sys.argv[2]: os._exit(77)
f.send_cancel(fault=crash)
'''
        result = subprocess.run([sys.executable, '-c', code, self.tmp.name, stage],
                                capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(result.returncode, 77, result.stderr)
        self.f.close()
        self.f = HandoffFixture(self.tmp.name, seed=False)

    def test_process_death_after_cancel_claim_keeps_unknown_without_resubmit(self):
        self.child_crash('after_cancel_claim_before_send')
        self.assertEqual(self.f.send_cancel(), 'UNRESOLVED_NOT_FOUND')
        self.assertEqual(self.f.send_exit(), 'CANCEL_AND_RECONCILE')
        self.assertEqual(self.f.cancel.count(), 0)

    def test_process_death_after_cancel_acceptance_recovers_by_lookup(self):
        self.child_crash('after_cancel_accept_before_ack')
        self.assertEqual(self.f.send_cancel(), 'QUERIED')
        self.assertEqual(self.f.cancel.count(), 1)
        self.assertEqual(self.f.send_exit(), 'CANCEL_AND_RECONCILE')


if __name__ == '__main__':
    unittest.main()
