from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from app.research.execution.account_exit_gate import AccountExitGate
from app.research.execution.account_exit_bridge import AccountExitBridge
from app.research.execution.durable_fallback import Journal, Receipt
from app.research.execution.market_fallback import State, Snapshot
from app.research.execution.protection_coordinator import ProtectionCoordinator
from app.research.execution.protection_supervisor import ProtectionJournal
from tests.test_account_exit_gate import ACCOUNT, view, order
from tests.test_fallback_preflight import contract_fixture
from tests.test_protection_supervisor import exposure
from tests.test_protection_coordinator import PaperTransport


class FallbackPaper:
    def __init__(self, paper):
        self.paper = paper

    def translated(self, command):
        return SimpleNamespace(command_id=command.command_id, scope=command.original_id,
                               kind='EXIT', quantity=command.action.quantity)

    def submit(self, command):
        r = self.paper.submit(self.translated(command))
        return Receipt(r.command_id, r.scope, r.status, r.executed, r.version)

    def lookup(self, command):
        r = self.paper.lookup(self.translated(command))
        return Receipt(r.command_id, r.scope, r.status, r.executed, r.version) if r else None


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fallback = Journal(self.root/'fallback.sqlite')
        self.protection = ProtectionJournal(self.root/'protection.sqlite')
        self.coordinator = ProtectionCoordinator(self.protection, contract_fixture())
        self.gate = AccountExitGate(self.root/'account.sqlite', ACCOUNT)
        self.bridge = AccountExitBridge(self.gate)
        self.paper = PaperTransport(self.root/'fake.sqlite')
        self.fallback_transport = FallbackPaper(self.paper)
        self.original = order('original', status='CANCELED')
        self.account_view = view(orders=(self.original,))
        self.gate.observe(self.account_view, now_ms=1000)
        self.snapshot = exposure(position=D('.003'), entry_ids=(), risk_breached=True)
        self.fallback.register(State('original', D('.003'), -1, 'exit', 1000))
        self.fallback.advance(Snapshot('original', 'CANCELED', D(0), 1000), now_ms=1000,
                              signal_valid=False, approved_market_qty=D('.003'), position_qty=D('.003'), context_observed_ms=1000)
        self.fallback_id = self.fallback.commands()[0].command_id
        self.coordinator.reconcile(self.snapshot, now_ms=1000)
        self.protection_id = self.coordinator.commands(self.snapshot.scope)[0].command_id

    def tearDown(self):
        for journal in (self.fallback, self.protection, self.gate):
            journal.close()
        self.tmp.cleanup()

    def send_fallback(self, **updates):
        kwargs = dict(account=ACCOUNT, view_version=self.account_view.version, position=self.account_view.position,
                      observed_ms=self.account_view.observed_ms, now_ms=self.account_view.observed_ms,
                      authorize=lambda _: True)
        return self.bridge.fallback(self.fallback, self.fallback_id, self.fallback_transport, **(kwargs | updates))

    def send_protection(self, identity=None, **updates):
        kwargs = dict(account=ACCOUNT, snapshot=self.snapshot, now_ms=self.snapshot.observed_ms)
        return self.bridge.protection(self.coordinator, identity or self.protection_id, self.paper, **(kwargs | updates))

    def test_fallback_then_urgent_before_account_refresh_sends_only_once(self):
        self.assertEqual(self.send_fallback(), 'TERMINAL')
        self.assertEqual(self.send_protection(), 'ACCOUNT_UNREFLECTED_CLAIM')
        self.assertEqual(self.paper.submit_count(), 1)

    def test_urgent_then_fallback_before_account_refresh_sends_only_once(self):
        self.assertEqual(self.send_protection(), 'TERMINAL')
        self.assertEqual(self.send_fallback(), 'ACCOUNT_UNREFLECTED_CLAIM')
        self.assertEqual(self.paper.submit_count(), 1)

    def test_terminal_partial_fallback_then_only_remaining_protective_close(self):
        self.paper.status, self.paper.executed = 'EXPIRED', D('.001')
        self.assertEqual(self.send_fallback(), 'TERMINAL_REMAINDER_REQUIRES_REVIEW')
        partial = order(self.fallback_id, status='EXPIRED', executed=D('.001'))
        self.account_view = view(version=2, observed_ms=1001, position=D('.002'), orders=(self.original, partial))
        self.assertEqual(self.gate.observe(self.account_view, now_ms=1001), 'OBSERVED')
        self.snapshot = replace(self.snapshot, version=2, observed_ms=1001, position=D('.002'))
        self.assertEqual(self.send_protection(), 'SUPERSEDED')
        result = self.coordinator.reconcile(self.snapshot, now_ms=1001)
        identity = result['created'][0]
        self.assertEqual(self.coordinator.command(identity).quantity, D('.002'))
        self.paper.status, self.paper.executed = None, None
        self.assertEqual(self.send_protection(identity), 'TERMINAL')
        terminal = order(identity, quantity=D('.002'), executed=D('.002'), status='FILLED')
        self.account_view = view(version=3, observed_ms=1002, position=D(0), orders=(self.original, partial, terminal))
        self.assertEqual(self.gate.observe(self.account_view, now_ms=1002), 'OBSERVED')
        total = self.fallback.filled_quantity(self.fallback_id) + sum(D(r[0]) for r in self.protection.db.execute('SELECT quantity FROM protective_fill_deltas'))
        self.assertEqual(total, D('.003'))
        self.assertTrue(all(r['released'] == 1 for r in self.gate.claims()))
        self.assertEqual(self.paper.submit_count(), 2)

    def test_lost_response_queries_original_id_and_blocks_other_lane(self):
        self.paper.lose_response = True
        self.assertEqual(self.send_fallback(), 'UNCERTAIN')
        self.assertEqual(self.send_protection(), 'ACCOUNT_UNREFLECTED_CLAIM')
        self.assertEqual(self.send_fallback(), 'TERMINAL')
        self.assertEqual(self.send_protection(), 'ACCOUNT_UNREFLECTED_CLAIM')
        self.assertEqual(self.paper.submit_count(), 1)

    def test_risk_recheck_rejection_releases_proven_unsent_claim(self):
        answers = iter((True, False))
        self.assertEqual(self.send_fallback(authorize=lambda _: next(answers)), 'BLOCKED')
        self.assertEqual(self.gate.claims()[0]['released'], 2)
        self.assertEqual(self.send_protection(), 'TERMINAL')
        self.assertEqual(self.paper.submit_count(), 1)

    def test_wrong_account_or_position_context_never_sends(self):
        with self.assertRaises(ValueError):
            self.send_protection(account='wrong')
        self.assertEqual(self.send_fallback(position=D('.004')), 'ACCOUNT_CONTEXT_MISMATCH')
        self.assertEqual(self.send_protection(snapshot=replace(self.snapshot, version=2)), 'ACCOUNT_CONTEXT_MISMATCH')
        self.assertEqual(self.paper.submit_count(), 0)

    def test_original_must_be_terminal_and_match_both_account_and_local_journal(self):
        self.gate.close()
        self.gate = AccountExitGate(self.root/'different_epoch_fixture.sqlite', ACCOUNT)
        self.bridge = AccountExitBridge(self.gate)
        self.gate.observe(view(orders=(replace(self.original, status='NEW'),)), now_ms=1000)
        self.assertEqual(self.send_fallback(), 'ORIGINAL_ACCOUNT_EVIDENCE_MISMATCH')
        self.assertEqual(self.paper.submit_count(), 0)
        self.assertEqual(self.gate.claims(), [])

    def test_missing_original_is_not_filled_in_from_the_local_journal(self):
        self.gate.close()
        self.gate = AccountExitGate(self.root/'missing_original_fixture.sqlite', ACCOUNT)
        self.bridge = AccountExitBridge(self.gate)
        self.gate.observe(view(), now_ms=1000)
        self.assertEqual(self.send_fallback(), 'ORIGINAL_ACCOUNT_EVIDENCE_MISMATCH')
        self.assertEqual(self.paper.submit_count(), 0)

    def test_account_latch_blocks_both_lanes(self):
        self.gate.observe(view(version=2, observed_ms=1001, complete=False), now_ms=1001)
        self.assertEqual(self.send_fallback(), 'ACCOUNT_ACCOUNT_RECONCILIATION_LATCHED')
        self.assertEqual(self.send_protection(), 'ACCOUNT_ACCOUNT_RECONCILIATION_LATCHED')
        self.assertEqual(self.paper.submit_count(), 0)

    def child_crash(self, stage):
        code = '''
import os,sys
from pathlib import Path
from decimal import Decimal as D
from app.research.execution.account_exit_gate import AccountExitGate
from app.research.execution.account_exit_bridge import AccountExitBridge
from app.research.execution.durable_fallback import Journal
from tests.test_account_exit_gate import ACCOUNT
from tests.test_account_exit_bridge import FallbackPaper
from tests.test_protection_coordinator import PaperTransport
root=Path(sys.argv[1])
gate=AccountExitGate(root/'account.sqlite', ACCOUNT)
bridge=AccountExitBridge(gate)
journal=Journal(root/'fallback.sqlite')
def crash(stage):
    if stage==sys.argv[3]: os._exit(77)
bridge.fallback(journal,sys.argv[2],FallbackPaper(PaperTransport(root/'fake.sqlite')),account=ACCOUNT,
                view_version=1,position=D('.003'),observed_ms=1000,now_ms=1000,authorize=lambda _:True,fault=crash)
'''
        result = subprocess.run([sys.executable, '-c', code, str(self.root), self.fallback_id, stage],
                                capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(result.returncode, 77, result.stderr)

    def test_process_death_between_shared_and_local_claim_never_resends(self):
        self.child_crash('after_account_claim_before_local_dispatch')
        self.assertEqual(self.send_fallback(), 'ACCOUNT_ALREADY_CLAIMED')
        self.assertEqual(self.send_protection(), 'ACCOUNT_UNREFLECTED_CLAIM')
        self.assertEqual(self.paper.submit_count(), 0)

    def test_process_death_after_exchange_acceptance_queries_without_new_send(self):
        self.child_crash('after_send_before_receipt_commit')
        self.assertEqual(self.send_protection(), 'ACCOUNT_UNREFLECTED_CLAIM')
        self.assertEqual(self.send_fallback(), 'TERMINAL')
        self.assertEqual(self.paper.submit_count(), 1)


if __name__ == '__main__':
    unittest.main()
