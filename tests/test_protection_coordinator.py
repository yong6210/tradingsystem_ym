"""Offline fault injection; fake acceptance is durable and separate from the journal."""
from dataclasses import replace
from decimal import Decimal as D
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from app.research.execution.protection_coordinator import ProtectionCoordinator, ProtectiveReceipt
from app.research.execution.protection_supervisor import ProtectionJournal
from tests.test_protection_supervisor import exposure, guard
from tests.test_fallback_preflight import contract_fixture


class PaperTransport:
    """Only scripted outcomes. No matching engine, network, keys or fee estimates."""
    def __init__(self, path, *, lose_response=False, status=None, executed=None):
        self.path = str(path)
        self.lose_response, self.status, self.executed = lose_response, status, executed
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, scope TEXT, status TEXT, executed TEXT, version INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS submissions (id TEXT)')

    def submit(self, command):
        status = self.status or {'STOP': 'ACTIVE', 'EXIT': 'FILLED', 'CANCEL': 'CANCELED'}[command.kind]
        executed = self.executed if self.executed is not None else (command.quantity if status == 'FILLED' else D(0))
        with sqlite3.connect(self.path) as db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('INSERT INTO submissions VALUES (?)', (command.command_id,))
            db.execute('INSERT INTO receipts VALUES (?,?,?,?,?)', (command.command_id, command.scope, status, str(executed), 1))
        if self.lose_response:
            raise TimeoutError('accepted; response lost')
        return self.lookup(command)

    def lookup(self, command):
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT * FROM receipts WHERE id=?', (command.command_id,)).fetchone()
        return ProtectiveReceipt(row[0], row[1], row[2], D(row[3]), row[4]) if row else None

    def set_receipt(self, command, status, executed, version):
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE receipts SET status=?,executed=?,version=? WHERE id=?',
                       (status, str(executed), version, command.command_id))
        return self.lookup(command)

    def submit_count(self):
        with sqlite3.connect(self.path) as db:
            return db.execute('SELECT count(*) FROM submissions').fetchone()[0]


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'journal.sqlite'
        self.exchange = PaperTransport(Path(self.tmp.name) / 'exchange.sqlite')
        self.reopen(first=True)
        self.snapshot = exposure(position=D('.003'), entry_ids=())

    def reopen(self, first=False):
        if not first:
            self.journal.close()
        self.journal = ProtectionJournal(self.path)
        self.coordinator = ProtectionCoordinator(self.journal, contract_fixture())

    def tearDown(self):
        self.journal.close()
        self.tmp.cleanup()

    def plan(self, snapshot=None):
        snapshot = snapshot or self.snapshot
        return self.coordinator.reconcile(snapshot, now_ms=snapshot.observed_ms)

    def queue(self, kind='STOP', snapshot=None):
        snapshot = snapshot or self.snapshot
        self.plan(snapshot)
        return next(c.command_id for c in self.coordinator.commands(snapshot.scope)
                    if c.kind == kind and c.delivery == 'READY')

    def send(self, identity, snapshot=None):
        snapshot = snapshot or self.snapshot
        return self.coordinator.dispatch(identity, self.exchange, snapshot=snapshot, now_ms=snapshot.observed_ms)

    def total_delta(self):
        return sum((D(r[0]) for r in self.journal.db.execute('SELECT quantity FROM protective_fill_deltas')), D(0))

    def test_stop_ack_needs_fresh_actual_coverage_not_receipt_alone(self):
        identity = self.queue()
        self.assertEqual(self.send(identity), 'ACKNOWLEDGED')
        self.assertFalse(self.plan()['cycle_reconciled'])
        snapshot = replace(self.snapshot, version=2, observed_ms=1001,
                           protection=(guard(client_id=identity, quantity=D('.003'), observed_ms=1001),))
        self.assertEqual(self.plan(snapshot)['decision']['phase'], 'PROTECTED')
        self.assertEqual(self.exchange.submit_count(), 1)

    def test_cancel_partial_entry_does_not_count_as_stop_or_fill(self):
        snapshot = replace(self.snapshot, entry_ids=('entry1',))
        cancel = self.queue('CANCEL', snapshot)
        stop = self.queue('STOP', snapshot)
        self.assertEqual(self.send(cancel, snapshot), 'TERMINAL')
        self.assertEqual(self.send(stop, snapshot), 'ACKNOWLEDGED')
        self.assertEqual(self.total_delta(), 0)
        self.assertEqual(self.plan(snapshot)['decision']['covered_quantity'], '0')

    def test_timeout_acceptance_recovery_queries_once_without_resubmit(self):
        identity = self.queue()
        self.exchange.lose_response = True
        self.assertEqual(self.send(identity), 'UNCERTAIN')
        self.reopen()
        self.assertEqual(self.send(identity), 'ACKNOWLEDGED')
        self.assertEqual(self.exchange.submit_count(), 1)

    def test_rejected_stop_latches_and_exits_only_with_new_exposure(self):
        identity = self.queue()
        self.exchange.status = 'REJECTED'
        self.assertEqual(self.send(identity), 'TERMINAL')
        same = self.plan()
        self.assertEqual(same['decision']['halted_reason'], 'PROTECTION_REJECTED')
        self.assertEqual(same['created'], [])
        self.reopen()
        snapshot = replace(self.snapshot, version=2, observed_ms=1001)
        exit_id = self.queue('EXIT', snapshot)
        self.exchange.status = None
        self.assertEqual(self.send(exit_id, snapshot), 'TERMINAL')
        self.assertEqual(self.total_delta(), D('.003'))

    def test_terminal_partial_exit_only_reissues_reconciled_remaining(self):
        snapshot = replace(self.snapshot, risk_breached=True)
        identity = self.queue('EXIT', snapshot)
        self.exchange.status, self.exchange.executed = 'EXPIRED', D('.001')
        self.send(identity, snapshot)
        self.assertEqual(self.plan(snapshot)['created'], [])
        newer = replace(snapshot, version=2, observed_ms=1001, position=D('.002'))
        remainder = self.queue('EXIT', newer)
        self.assertNotEqual(identity, remainder)
        self.assertEqual(self.coordinator.command(remainder).quantity, D('.002'))
        self.exchange.status, self.exchange.executed = None, None
        self.send(remainder, newer)
        self.assertEqual(self.total_delta(), D('.003'))
        flat = replace(newer, version=3, observed_ms=1002, position=D(0))
        self.assertTrue(self.plan(flat)['cycle_reconciled'])

    def test_partial_ack_blocks_second_exit_and_duplicate_receipts_do_not_double_count(self):
        snapshot = replace(self.snapshot, risk_breached=True)
        identity = self.queue('EXIT', snapshot)
        self.exchange.status, self.exchange.executed = 'PARTIALLY_FILLED', D('.001')
        self.send(identity, snapshot)
        receipt = self.exchange.lookup(self.coordinator.command(identity))
        self.coordinator.receipt(receipt)
        self.assertEqual(self.total_delta(), D('.001'))
        newer = replace(snapshot, version=2, observed_ms=1001, position=D('.002'), pending_exit_quantity=D('.002'))
        self.assertEqual(self.plan(newer)['created'], [])
        command = self.coordinator.command(identity)
        done = self.exchange.set_receipt(command, 'FILLED', D('.003'), 2)
        self.coordinator.receipt(done)
        self.coordinator.receipt(done)
        self.assertEqual(self.total_delta(), D('.003'))

    def test_wrong_identity_regression_conflicts_and_terminal_changes_rejected(self):
        snapshot = replace(self.snapshot, risk_breached=True)
        identity = self.queue('EXIT', snapshot)
        self.exchange.status, self.exchange.executed = 'PARTIALLY_FILLED', D('.001')
        self.send(identity, snapshot)
        receipt = self.exchange.lookup(self.coordinator.command(identity))
        for bad in (replace(receipt, scope='other'), replace(receipt, executed=D('.002')),
                    replace(receipt, version=2, executed=D('.0005')),
                    replace(receipt, version=2, status='FILLED', executed=D('.004'))):
            with self.assertRaises(ValueError):
                self.coordinator.receipt(bad)
        done = replace(receipt, version=2, status='FILLED', executed=D('.003'))
        self.coordinator.receipt(done)
        with self.assertRaises(ValueError):
            self.coordinator.receipt(replace(done, version=3, status='CANCELED'))
        self.assertEqual(self.total_delta(), D('.003'))

    def test_ready_quantity_is_superseded_after_position_shrinks(self):
        identity = self.queue()
        newer = replace(self.snapshot, version=2, observed_ms=1001, position=D('.001'))
        self.assertEqual(self.send(identity, newer), 'SUPERSEDED')
        replacement = self.queue('STOP', newer)
        self.assertEqual(self.coordinator.command(replacement).quantity, D('.001'))
        self.assertEqual(self.exchange.submit_count(), 0)

    def test_stale_unreconciled_snapshot_never_sends(self):
        identity = self.queue()
        self.assertEqual(self.coordinator.dispatch(identity, self.exchange, snapshot=self.snapshot, now_ms=2001), 'REFRESH_EXPOSURE')
        snapshot = replace(self.snapshot, version=2, observed_ms=2002, reconciled=False)
        self.assertEqual(self.send(identity, snapshot), 'REFRESH_EXPOSURE')
        self.assertEqual(self.exchange.submit_count(), 0)

    def test_send_rechecks_uncertain_cancel_reserved_after_stop_plan(self):
        snapshot = replace(self.snapshot, entry_ids=('entry1',))
        stop, cancel = self.queue('STOP', snapshot), self.queue('CANCEL', snapshot)
        self.exchange.lose_response = True
        self.send(cancel, snapshot)
        self.assertEqual(self.send(stop, snapshot), 'RECONCILE_SUBMITTED_ORDER')
        self.assertEqual(self.exchange.submit_count(), 1)
        self.send(cancel, snapshot)  # Query restores certainty.
        self.exchange.lose_response = False
        self.assertEqual(self.send(stop, snapshot), 'ACKNOWLEDGED')

    def test_flat_snapshot_cannot_hide_own_unknown_or_active_stop(self):
        identity = self.queue()
        self.exchange.lose_response = True
        self.send(identity)
        flat = replace(self.snapshot, version=2, observed_ms=1001, position=D(0))
        result = self.plan(flat)
        self.assertFalse(result['cycle_reconciled'])
        self.assertEqual(result['execution_phase'], 'FLAT_COMMAND_RECONCILIATION_REQUIRED')
        self.assertIn(identity, result['outstanding_commands'])
        self.send(identity, flat)
        self.assertFalse(self.plan(flat)['cycle_reconciled'])

    def test_terminal_receipt_requires_later_exposure_before_cycle_completion(self):
        identity = self.queue()
        self.send(identity)
        flat = replace(self.snapshot, version=2, observed_ms=1001, position=D(0))
        self.plan(flat)
        receipt = self.exchange.set_receipt(self.coordinator.command(identity), 'CANCELED', D(0), 2)
        self.coordinator.receipt(receipt)
        self.assertFalse(self.plan(flat)['cycle_reconciled'])
        self.assertTrue(self.plan(replace(flat, version=3, observed_ms=1002))['cycle_reconciled'])

    def test_flat_cleanup_requires_confirmed_cancellation_of_original_stop(self):
        identity = self.queue()
        self.send(identity)
        stop = guard(client_id=identity, quantity=D('.003'), observed_ms=1001)
        flat = replace(self.snapshot, version=2, observed_ms=1001, position=D(0), protection=(stop,))
        cancel = self.queue('CANCEL', flat)
        self.send(cancel, flat)
        self.assertFalse(self.plan(flat)['cycle_reconciled'])
        receipt = self.exchange.set_receipt(self.coordinator.command(identity), 'CANCELED', D(0), 2)
        self.coordinator.receipt(receipt)
        done = replace(flat, version=3, observed_ms=1002, protection=())
        self.assertTrue(self.plan(done)['cycle_reconciled'])

    def test_new_pending_stop_is_never_counted_as_active(self):
        identity = self.queue()
        self.exchange.status = 'NEW'
        self.send(identity)
        newer = replace(self.snapshot, version=2, observed_ms=1001,
                        protection=(guard(client_id=identity, quantity=D('.003'), status='PENDING', observed_ms=1001),))
        result = self.plan(newer)
        self.assertEqual(result['decision']['covered_quantity'], '0')
        self.assertEqual(result['created'], [])

    def test_contract_rejects_dust_and_trigger_off_tick_without_send(self):
        for snapshot in (replace(self.snapshot, position=D('.0001')),
                         replace(self.snapshot, fixed_stop=D('59000.01'), scope='paper/offtick')):
            result = self.plan(snapshot)
            self.assertEqual(result['created'], [])
            self.assertTrue(any(b.startswith('CONTRACT:') for b in result['blocked']))
        self.assertEqual(self.exchange.submit_count(), 0)

    def test_short_urgent_exit_is_buy_reduce_only_quantity(self):
        snapshot = replace(self.snapshot, position=D('-.003'), fixed_stop=D(61000), risk_breached=True)
        identity = self.queue('EXIT', snapshot)
        self.assertEqual(self.coordinator.command(identity).side, 1)
        self.assertEqual(self.send(identity, snapshot), 'TERMINAL')

    def test_reservation_rollback_leaves_recoverable_requirement(self):
        def fail(_):
            raise RuntimeError('crash before reservation commit')
        with self.assertRaises(RuntimeError):
            self.coordinator.reconcile(self.snapshot, now_ms=1000, fault=fail)
        self.reopen()
        self.assertEqual(self.coordinator.commands(self.snapshot.scope), [])
        self.assertEqual(len(self.plan()['created']), 1)

    def child_crash(self, identity, stage):
        code = '''
import os, sys
from decimal import Decimal as D
from app.research.execution.protection_coordinator import ProtectionCoordinator
from app.research.execution.protection_supervisor import ProtectionJournal
from tests.test_protection_coordinator import PaperTransport
from tests.test_protection_supervisor import exposure
from tests.test_fallback_preflight import contract_fixture
c = ProtectionCoordinator(ProtectionJournal(sys.argv[1]), contract_fixture())
def die(stage):
    if stage == sys.argv[4]: os._exit(77)
c.dispatch(sys.argv[3], PaperTransport(sys.argv[2]), snapshot=exposure(position=D('.003'), entry_ids=()), now_ms=1000, fault=die)
'''
        result = subprocess.run([sys.executable, '-c', code, str(self.path), self.exchange.path, identity, stage],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 77, result.stderr)
        self.reopen()

    def test_process_death_before_send_never_blindly_resubmits_missing_order(self):
        identity = self.queue()
        self.child_crash(identity, 'after_claim_before_send')
        self.assertEqual(self.send(identity), 'UNRESOLVED_NOT_FOUND')
        self.assertEqual(self.exchange.submit_count(), 0)
        newer = replace(self.snapshot, version=2, observed_ms=1001, risk_breached=True)
        self.assertEqual(self.plan(newer)['created'], [])

    def test_process_death_after_acceptance_recovers_one_durable_submission(self):
        identity = self.queue()
        self.child_crash(identity, 'after_send_before_receipt')
        self.assertEqual(self.send(identity), 'ACKNOWLEDGED')
        self.assertEqual(self.exchange.submit_count(), 1)


if __name__ == '__main__':
    unittest.main()
