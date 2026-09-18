from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
import tempfile
import unittest

from app.research.execution.protection_supervisor import Exposure, ProtectiveOrder, ProtectionJournal, assess


def exposure(**updates):
    snapshot = Exposure('paper/BTCUSDC/cycle1', 1, 1000, D('.001'), D(59000), D(60000),
                        True, False, D(0), False, ('entry1',), ())
    return replace(snapshot, **updates)


def guard(**updates):
    return replace(ProtectiveOrder('stop1', -1, D('.001'), D(59000), True, 'ACTIVE', 1000), **updates)


def kinds(decision):
    return {r['kind'] for r in decision['requirements']}


class ProtectionTests(unittest.TestCase):
    def evaluate(self, snapshot, **kw):
        return assess(snapshot, **(dict(now_ms=1000, uncovered_since=None, halted_reason=None) | kw))

    def test_first_partial_fill_freezes_remainder_and_requires_actual_stop(self):
        result = self.evaluate(exposure())
        self.assertEqual(result['phase'], 'PROTECTION_REQUIRED')
        self.assertEqual(kinds(result), {'FREEZE_NEW_ENTRY', 'CANCEL_ENTRY_REMAINDER', 'ENSURE_STOP_REQUIRED'})
        self.assertEqual(result['covered_quantity'], '0')

    def test_pending_or_unknown_request_is_never_protected_or_duplicated(self):
        for status in ('PENDING', 'UNKNOWN'):
            result = self.evaluate(exposure(protection=(guard(status=status),)))
            self.assertIn('RECONCILE_PROTECTION', kinds(result))
            self.assertNotIn('ENSURE_STOP_REQUIRED', kinds(result))
            self.assertEqual(result['covered_quantity'], '0')

    def test_extra_fill_leaves_only_new_quantity_uncovered(self):
        result = self.evaluate(exposure(position=D('.003'), protection=(guard(),)))
        required = next(r for r in result['requirements'] if r['kind'] == 'ENSURE_STOP_REQUIRED')
        self.assertEqual(required['quantity'], '0.002')
        self.assertEqual(result['covered_quantity'], '0.001')

    def test_confirmed_full_coverage_clears_gap_timer(self):
        result = self.evaluate(exposure(protection=(guard(),)), uncovered_since=0)
        self.assertEqual(result['phase'], 'PROTECTED')
        self.assertIsNone(result['uncovered_since'])

    def test_timeout_risk_or_crossed_stop_urgently_reduce_without_limit_deadline(self):
        scenarios = [(exposure(), dict(uncovered_since=0)),
                     (exposure(risk_breached=True), {}), (exposure(mark=D(58999)), {})]
        for snapshot, extra in scenarios:
            result = self.evaluate(snapshot, **extra)
            required = next(r for r in result['requirements'] if r['kind'] == 'URGENT_REDUCE_ONLY_REQUIRED')
            self.assertEqual(required['quantity'], '0.001')
            self.assertEqual(required['side'], -1)
            self.assertTrue(required['reduce_only'])

    def test_existing_exit_reservations_prevent_double_close(self):
        result = self.evaluate(exposure(risk_breached=True, pending_exit_quantity=D('.001')))
        self.assertNotIn('URGENT_REDUCE_ONLY_REQUIRED', kinds(result))
        self.assertIn('RECONCILE_EXISTING_EXIT', kinds(result))
        unknown = self.evaluate(exposure(risk_breached=True, exit_status_unknown=True))
        self.assertNotIn('URGENT_REDUCE_ONLY_REQUIRED', kinds(unknown))

    def test_stale_or_unreconciled_position_never_invents_exit_quantity(self):
        for snapshot in (exposure(observed_ms=0), exposure(reconciled=False)):
            result = self.evaluate(snapshot, now_ms=2001)
            self.assertEqual(result['phase'], 'UNRESOLVED')
            self.assertNotIn('URGENT_REDUCE_ONLY_REQUIRED', kinds(result))

    def test_bad_protection_identity_is_urgent_not_coverage(self):
        for stop in (guard(side=1), guard(reduce_only=False), guard(trigger=D(58000)), guard(working_type='CONTRACT_PRICE')):
            result = self.evaluate(exposure(protection=(stop,)))
            self.assertEqual(result['halted_reason'], 'PROTECTION_IDENTITY_MISMATCH')
            self.assertIn('CANCEL_INVALID_PROTECTION', kinds(result))

    def test_short_exit_side_and_flat_cleanup(self):
        result = self.evaluate(exposure(position=D('-.001'), fixed_stop=D(61000), risk_breached=True))
        required = next(r for r in result['requirements'] if r['kind'] == 'URGENT_REDUCE_ONLY_REQUIRED')
        self.assertEqual(required['side'], 1)
        self.assertEqual(self.evaluate(exposure(position=D(0)))['phase'], 'FLAT_CLEANUP_REQUIRED')
        self.assertEqual(self.evaluate(exposure(position=D(0), entry_ids=()))['phase'], 'FLAT_RECONCILED')


class DurableProtectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'protection.sqlite'
        self.journal = ProtectionJournal(self.path)

    def tearDown(self):
        self.journal.close()
        self.tmp.cleanup()

    def test_timeout_and_alarm_survive_restart_without_duplicate_alarm(self):
        self.journal.update(exposure(), now_ms=1000)
        self.journal.close()
        self.journal = ProtectionJournal(self.path)
        current = exposure(version=2, observed_ms=2000)
        result = self.journal.update(current, now_ms=2000)
        self.assertEqual(result['halted_reason'], 'PROTECTION_TIMEOUT')
        self.journal.update(current, now_ms=2000)
        count = self.journal.db.execute("SELECT count(*) FROM alarms WHERE reason='PROTECTION_TIMEOUT'").fetchone()[0]
        self.assertEqual(count, 1)
        recovered = exposure(version=3, observed_ms=2001, protection=(guard(observed_ms=2001),))
        self.assertEqual(self.journal.update(recovered, now_ms=2001)['phase'], 'URGENT_EXIT_REQUIRED')

    def test_state_requirements_and_alarm_rollback_together(self):
        def crash(_):
            raise RuntimeError('interrupted before requirements')
        with self.assertRaises(RuntimeError):
            self.journal.update(exposure(), now_ms=1000, fault=crash)
        for table in ('exposure_state', 'requirements', 'alarms'):
            self.assertEqual(self.journal.db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)

    def test_old_conflicting_or_moved_stop_is_rejected(self):
        self.journal.update(exposure(), now_ms=1000)
        for snapshot in (exposure(version=0), exposure(position=D('.002')),
                         exposure(version=2, fixed_stop=D(58000))):
            with self.assertRaises(ValueError):
                self.journal.update(snapshot, now_ms=1000)

    def test_position_side_change_latches_and_current_requirements_replace_old(self):
        self.journal.update(exposure(), now_ms=1000)
        result = self.journal.update(exposure(version=2, position=D('-.001')), now_ms=1000)
        self.assertEqual(result['halted_reason'], 'POSITION_SIDE_CHANGED')
        stored = {r[0] for r in self.journal.db.execute('SELECT kind FROM requirements')}
        self.assertNotIn('ENSURE_STOP_REQUIRED', stored)
        self.assertIn('URGENT_REDUCE_ONLY_REQUIRED', stored)

    def test_completed_cycle_cannot_silently_reopen(self):
        self.journal.update(exposure(position=D(0), entry_ids=()), now_ms=1000)
        result = self.journal.update(exposure(version=2), now_ms=1000)
        self.assertEqual(result['halted_reason'], 'UNEXPECTED_CYCLE_REOPEN')
