from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
import tempfile
import threading
import unittest

from app.research.execution.account_exit_gate import AccountExitGate, AccountOrder, AccountView, ExitIntent

ACCOUNT = 'paper/BTCUSDC/epoch1'


def view(**changes):
    return replace(AccountView(ACCOUNT, 1, 1000, D('.003'), True, ()), **changes)


def intent(identity='exit1', **changes):
    return replace(ExitIntent(ACCOUNT, identity, 'fallback', 'original1', 'EXIT', -1, D('.003')), **changes)


def order(identity='exit1', **changes):
    return replace(AccountOrder(identity, 'EXIT', -1, D('.003'), D(0), 'NEW', 1, True), **changes)


class AccountExitGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'account.sqlite'
        self.gate = AccountExitGate(self.path, ACCOUNT)
        self.assertEqual(self.gate.observe(view(), now_ms=1000), 'OBSERVED')

    def tearDown(self):
        self.gate.close()
        self.tmp.cleanup()

    def claim(self, value=None, version=1, now=1000):
        return self.gate.claim(value or intent(), view_version=version, now_ms=now)

    def test_two_lanes_cannot_spend_same_position(self):
        self.assertEqual(self.claim(), 'CLAIMED')
        self.assertEqual(self.claim(intent('urgent', lane='protection')), 'UNREFLECTED_CLAIM')
        self.assertEqual(len(self.gate.claims()), 1)

    def test_partial_active_exit_counts_remaining_once(self):
        self.claim()
        current = view(version=2, observed_ms=1001, position=D('.002'),
                       orders=(order(status='PARTIALLY_FILLED', executed=D('.001')),))
        self.assertEqual(self.gate.observe(current, now_ms=1001), 'OBSERVED')
        self.assertEqual(self.claim(intent('urgent', quantity=D('.001')), 2, 1001), 'INSUFFICIENT_UNRESERVED_POSITION')

    def test_terminal_partial_fill_releases_only_after_matching_position(self):
        self.claim()
        current = view(version=2, observed_ms=1001, position=D('.002'), orders=(order(status='EXPIRED', executed=D('.001')),))
        self.assertEqual(self.gate.observe(current, now_ms=1001), 'OBSERVED')
        self.assertEqual(self.gate.claims()[0]['released'], 1)
        self.assertEqual(self.claim(intent('urgent', quantity=D('.002')), 2, 1001), 'CLAIMED')

    def test_position_mismatch_latches_and_cannot_reuse_last_good_view(self):
        self.claim()
        bad = view(version=2, observed_ms=1001, orders=(order(status='FILLED', executed=D('.003')),))
        self.assertEqual(self.gate.observe(bad, now_ms=1001), 'POSITION_FILL_MISMATCH')
        self.assertEqual(self.claim(intent('urgent')), 'ACCOUNT_RECONCILIATION_LATCHED')
        self.gate.close()
        self.gate = AccountExitGate(self.path, ACCOUNT)
        self.assertEqual(self.claim(intent('urgent')), 'ACCOUNT_RECONCILIATION_LATCHED')

    def test_known_orders_must_not_disappear_including_terminal(self):
        terminal = order(status='CANCELED')
        self.gate.observe(view(version=2, observed_ms=1001, orders=(terminal,)), now_ms=1001)
        self.assertEqual(self.gate.observe(view(version=3, observed_ms=1002), now_ms=1002), 'KNOWN_ORDER_MISSING')

    def test_unknown_orders_freeze_new_close_but_known_entry_fills_reconcile(self):
        entry = order('entry', kind='ENTRY', side=1, status='UNKNOWN', reduce_only=False)
        self.gate.observe(view(version=2, observed_ms=1001, orders=(entry,)), now_ms=1001)
        self.assertEqual(self.claim(version=2, now=1001), 'UNKNOWN_ACCOUNT_ORDER')
        filled = replace(entry, version=2, status='FILLED', executed=D('.003'))
        self.assertEqual(self.gate.observe(view(version=3, observed_ms=1002, position=D('.006'), orders=(filled,)), now_ms=1002), 'OBSERVED')
        self.assertEqual(self.claim(version=3, now=1002), 'CLAIMED')

    def test_active_conditional_stop_reserves_capacity_until_confirmed_cancel(self):
        stop = order('stop', kind='STOP', status='ACTIVE')
        self.gate.observe(view(version=2, observed_ms=1001, orders=(stop,)), now_ms=1001)
        self.assertEqual(self.claim(version=2, now=1001), 'INSUFFICIENT_UNRESERVED_POSITION')
        canceled = replace(stop, status='CANCELED', version=2)
        self.gate.observe(view(version=3, observed_ms=1002, orders=(canceled,)), now_ms=1002)
        self.assertEqual(self.claim(version=3, now=1002), 'CLAIMED')

    def test_wrong_side_flat_and_oversize_rejected(self):
        self.assertEqual(self.claim(intent(side=1)), 'CLOSE_WOULD_INCREASE_OR_REVERSE')
        self.assertEqual(self.claim(intent(quantity=D('.004'))), 'INSUFFICIENT_UNRESERVED_POSITION')

    def test_short_close_is_buy(self):
        path = Path(self.tmp.name) / 'short.sqlite'
        gate = AccountExitGate(path, ACCOUNT)
        gate.observe(view(position=D('-.003')), now_ms=1000)
        self.assertEqual(gate.claim(intent(side=1), view_version=1, now_ms=1000), 'CLAIMED')
        gate.close()

    def test_snapshot_versions_stale_and_incomplete_rejected(self):
        self.assertEqual(self.claim(version=0), 'REFRESH_ACCOUNT')
        self.assertEqual(self.claim(now=2001), 'REFRESH_ACCOUNT')
        self.assertEqual(self.gate.observe(view(version=2, complete=False), now_ms=1000), 'STALE_OR_INCOMPLETE_ACCOUNT')
        self.assertEqual(self.claim(), 'ACCOUNT_RECONCILIATION_LATCHED')

    def test_identity_collision_between_lanes_and_account_is_rejected(self):
        self.claim()
        with self.assertRaises(ValueError):
            self.claim(intent(lane='protection'))
        with self.assertRaises(ValueError):
            self.claim(intent(account='another'))
        with self.assertRaises(ValueError):
            AccountExitGate(self.path, 'another')

    def test_proven_unsent_claim_can_be_reapproved_not_timeout_released(self):
        self.claim()
        self.assertEqual(self.claim(), 'ALREADY_CLAIMED')
        self.gate.release_unsent(intent())
        self.assertEqual(self.claim(), 'CLAIMED')

    def test_transaction_rollback_does_not_leave_partial_claim(self):
        def fail(_):
            raise RuntimeError('before commit')
        with self.assertRaises(RuntimeError):
            self.gate.claim(intent(), view_version=1, now_ms=1000, fault=fail)
        self.assertEqual(self.gate.claims(), [])
        self.assertEqual(self.claim(), 'CLAIMED')

    def test_two_database_connections_race_only_one_reservation(self):
        barrier = threading.Barrier(2)
        def worker(index):
            gate = AccountExitGate(self.path, ACCOUNT)
            barrier.wait(timeout=3)
            try:
                return gate.claim(intent(str(index)), view_version=1, now_ms=1000)
            finally:
                gate.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, (1, 2)))
        self.assertCountEqual(results, ['CLAIMED', 'UNREFLECTED_CLAIM'])

    def test_duplicate_observation_idempotent_and_order_regression_rejected(self):
        current = view(version=2, observed_ms=1001, orders=(order(),))
        self.assertEqual(self.gate.observe(current, now_ms=1001), 'OBSERVED')
        self.assertEqual(self.gate.observe(current, now_ms=1001), 'OBSERVED')
        bad = replace(current, version=3, observed_ms=1002, orders=(order(status='CANCELED'),))
        self.assertEqual(self.gate.observe(bad, now_ms=1002), 'CONFLICTING_ORDER_VERSION')

    def test_unknown_claim_prevents_flat_completion_and_missing_position_is_not_invented(self):
        self.claim()
        self.assertFalse(self.gate.status()['flat_reconciled'])
        self.assertEqual(self.gate.status()['unresolved_claims'], ['exit1'])
        self.assertEqual(self.gate.observe(view(version=2, observed_ms=1001, position=D(0)), now_ms=1001), 'POSITION_FILL_MISMATCH')

    def test_order_metadata_cannot_hide_reduce_only_under_entry_label(self):
        with self.assertRaises(ValueError):
            order(kind='ENTRY', reduce_only=True)
        with self.assertRaises(ValueError):
            self.claim(version=True)

    def test_cumulative_regression_and_claim_identity_conflict_latch(self):
        self.claim()
        bad = view(version=2, observed_ms=1001, orders=(order(quantity=D('.004')),))
        self.assertEqual(self.gate.observe(bad, now_ms=1001), 'CLAIM_ORDER_IDENTITY_MISMATCH')

    def test_initial_order_terminal_cannot_reopen(self):
        terminal = order(status='CANCELED')
        self.gate.observe(view(version=2, observed_ms=1001, orders=(terminal,)), now_ms=1001)
        self.assertEqual(self.gate.observe(view(version=3, observed_ms=1002, orders=(order(version=2),)), now_ms=1002), 'TERMINAL_ORDER_CHANGED')


if __name__ == '__main__':
    unittest.main()
