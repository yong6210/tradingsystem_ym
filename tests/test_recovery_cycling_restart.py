import copy
import json
from pathlib import Path
import tempfile
import unittest

import test_recovery_cycling_orders as fixtures
from app.research.recovery.cycling_checkpoint import _digest, save_checkpoint, load_checkpoint
from app.research.recovery.cycling_orders import CyclingOrders


class RestartTests(unittest.TestCase):
    def setup_case(self):
        helper = fixtures.CyclingOrderTests()
        model, orders, quote, cap = helper.setup_case()
        model.increase('base', -1, 5, 100000, 20)
        return helper, model, orders, quote, cap

    def restart(self, orders):
        return CyclingOrders.restore(json.loads(json.dumps(orders.checkpoint())))

    def reconcile(self, orders):
        orders.reconcile(side=orders.model.position_side, quantity=orders.model.quantity,
                         average=orders.model.average,
                         open_orders={o.id: dict(filled=o.filled, status=o.status)
                                      for o in orders.orders.values()
                                      if o.status in ('open', 'cancel_pending')})

    def test_restart_restores_half_remainder_costs_funding_and_dedup(self):
        helper, m, orders, q, cap = self.setup_case()
        helper.submit(orders, q, cap)
        orders.fill('addfill', 'add', 5, 102000, 30)
        m.funding('fund', -10)
        orders.retracement('half', 'r', reference_price=101200)
        orders.fill('part', 'half', 2, 101200, 5)
        restored = self.restart(orders)
        self.assertTrue(restored.restart_required)
        self.assertEqual(restored.model.break_evens(), m.break_evens())
        self.assertEqual(restored.model.total_pnl(101200), m.total_pnl(101200))
        self.assertEqual(restored.model.reduction.remaining, 3)
        self.assertFalse(restored.fill('part', 'half', 2, 101200, 5))
        self.reconcile(restored)
        restored.fill('rest', 'half', 3, 101200, 5)
        orders.fill('rest', 'half', 3, 101200, 5)
        self.assertEqual(restored.checkpoint(), orders.checkpoint())

    def test_restart_blocks_new_orders_until_matching_snapshot(self):
        helper, m, orders, q, cap = self.setup_case()
        restored = self.restart(orders)
        with self.assertRaises(ValueError):
            helper.submit(restored, q, cap)
        with self.assertRaises(ValueError):
            restored.reconcile(side=-1, quantity=4, average=100000, open_orders={})
        self.assertTrue(restored.restart_required)
        self.assertEqual(restored.model.quantity, 5)
        self.reconcile(restored)
        self.assertTrue(helper.submit(restored, q, cap)['allowed'])

    def test_order_snapshot_mismatch_cannot_release_restart_lock(self):
        helper, m, orders, q, cap = self.setup_case()
        helper.submit(orders, q, cap)
        restored = self.restart(orders)
        with self.assertRaises(ValueError):
            restored.reconcile(side=-1, quantity=5, average=100000, open_orders={})
        self.assertTrue(restored.restart_required)

    def test_transition_cancels_increase_then_exits_actual_quantity(self):
        helper, m, orders, q, cap = self.setup_case()
        helper.submit(orders, q, cap)
        orders.fill('part', 'add', 2, 102000)
        orders.request_transition(1, timeframe='4h', observed_ms=101, reason='scenario reversal')
        self.assertEqual(orders.active.status, 'cancel_pending')
        self.assertEqual(m.direction, -1)
        with self.assertRaises(ValueError):
            orders.continue_transition('exit', reference_price=103000)
        orders.fill('late', 'add', 1, 102000)
        orders.confirm_cancel('add', 3)
        restored = self.restart(orders)
        self.reconcile(restored)
        exit_order = restored.continue_transition('exit', reference_price=103000)
        self.assertEqual((exit_order.quantity, restored.model.direction), (8, 1))
        restored.fill('exit-part', 'exit', 3, 103000)
        with self.assertRaises(ValueError):
            helper.submit(restored, q, cap, 'opposite', helper.location(1))
        restored.fill('exit-rest', 'exit', 5, 103000)
        self.assertEqual(restored.model.quantity, 0)
        self.assertIsNone(restored.transition)
        # Fresh independent long setup, at a time after the direction assessment.
        from dataclasses import replace
        result = restored.increase('long', helper.location(1, suffix='new', observed=102),
                                   replace(q, time_ms=102), replace(cap, observed_ms=102),
                                   requested=5, now_ms=102, max_age_ms=0)
        self.assertTrue(result['allowed'])
        restored.fill('longfill', 'long', result['quantity'], 102000)
        self.assertEqual(restored.model.position_side, 1)

    def test_transition_supersedes_partial_half_and_retries_full_exit(self):
        helper, m, orders, q, cap = self.setup_case()
        orders.retracement('half', 'r', reference_price=99000)
        orders.fill('part', 'half', 1, 99000)
        orders.request_transition(1, timeframe='4h', observed_ms=101, reason='reversal')
        orders.fill('late', 'half', '.5', 99000)
        orders.confirm_cancel('half', '1.5')
        exit_order = orders.continue_transition('exit', reference_price=103000)
        self.assertEqual(str(exit_order.quantity), '3.5')
        self.assertIsNone(m.reduction)
        orders.fill('exit-part', 'exit', 1, 103000)
        orders.request_cancel('exit')
        orders.confirm_cancel('exit', 1)
        restored = self.restart(orders)
        self.reconcile(restored)
        retry = restored.continue_transition('retry', reference_price=103100)
        self.assertEqual(str(retry.quantity), '2.5')
        restored.fill('exit-rest', 'retry', '2.5', 103100)
        self.assertEqual(restored.model.quantity, 0)
        self.assertIsNone(restored.transition)
        self.restart(restored)  # Replay includes reduction supersession.

    def test_no_fill_transition_clears_after_cancel(self):
        helper = fixtures.CyclingOrderTests()
        m, orders, q, cap = helper.setup_case()
        helper.submit(orders, q, cap)
        orders.request_transition(1, timeframe='4h', observed_ms=101, reason='reversal')
        orders.confirm_cancel('add', 0)
        self.assertIsNone(orders.continue_transition('unused', reference_price=102000))
        self.assertEqual(m.direction, 1)
        self.assertFalse(any(o.kind == 'exit' for o in orders.orders.values()))

    def test_invalid_transition_is_atomic_and_duplicate_is_idempotent(self):
        helper, m, orders, q, cap = self.setup_case()
        helper.submit(orders, q, cap)
        before = orders.checkpoint()
        with self.assertRaises(ValueError):
            orders.request_transition(1, timeframe='1m', observed_ms=101, reason='bounce')
        self.assertEqual(orders.checkpoint(), before)
        kwargs = dict(timeframe='4h', observed_ms=101, reason='reversal')
        orders.request_transition(1, **kwargs)
        before = orders.checkpoint()
        orders.request_transition(1, **kwargs)
        self.assertEqual(orders.checkpoint(), before)

    def test_checksum_and_replayed_state_detect_corruption(self):
        helper, m, orders, q, cap = self.setup_case()
        payload = orders.checkpoint()
        corrupt = copy.deepcopy(payload)
        corrupt['body']['state']['average'] = '99999'
        with self.assertRaises(ValueError):
            CyclingOrders.restore(corrupt)
        corrupt['sha256'] = _digest(corrupt['body'])
        with self.assertRaises(ValueError):
            CyclingOrders.restore(corrupt)

    def test_order_fill_mismatch_rejected_even_with_valid_checksum(self):
        helper, m, orders, q, cap = self.setup_case()
        helper.submit(orders, q, cap)
        orders.fill('part', 'add', 2, 102000)
        payload = orders.checkpoint()
        payload['body']['orders']['add']['filled'] = '1'
        payload['sha256'] = _digest(payload['body'])
        with self.assertRaises(ValueError):
            CyclingOrders.restore(payload)

    def test_atomic_file_save_and_reload(self):
        helper, m, orders, q, cap = self.setup_case()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            save_checkpoint(orders, path)
            restored = load_checkpoint(path)
            self.assertEqual(restored.checkpoint(), orders.checkpoint())
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_failed_save_preserves_previous_checkpoint(self):
        helper, m, orders, q, cap = self.setup_case()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            save_checkpoint(orders, path)
            previous = path.read_bytes()
            m.quantity += 1  # Simulate corrupted in-memory state, absent from journal.
            with self.assertRaises(ValueError):
                save_checkpoint(orders, path)
            self.assertEqual(path.read_bytes(), previous)
            self.assertEqual(load_checkpoint(path).model.quantity, 5)

    def test_restart_while_cancel_pending_accepts_known_late_fill(self):
        helper, m, orders, q, cap = self.setup_case()
        helper.submit(orders, q, cap)
        orders.request_transition(1, timeframe='4h', observed_ms=101, reason='reversal')
        restored = self.restart(orders)
        self.assertEqual(restored.active.status, 'cancel_pending')
        self.assertEqual(restored.model.direction, -1)
        restored.fill('late', 'add', 1, 102000)
        restored.confirm_cancel('add', 1)
        with self.assertRaises(ValueError):
            restored.continue_transition('exit', reference_price=103000)
        self.reconcile(restored)
        self.assertEqual(restored.continue_transition('exit', reference_price=103000).quantity, 6)

    def test_fault_lock_survives_restart_and_matching_position(self):
        helper, m, orders, q, cap = self.setup_case()
        orders.locked = True
        restored = self.restart(orders)
        with self.assertRaises(ValueError):
            self.reconcile(restored)
        self.assertTrue(restored.locked)


if __name__ == '__main__':
    unittest.main()
