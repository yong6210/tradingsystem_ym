from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from app.research.observation.signal_window import window,admission,require_preclose_arm,audit_rows
from app.research.observation.public_paper import transition
from scripts.run_signal_window import wait_for_launch
from tests.test_public_paper import ready,premium,query
from tests.test_causal_intents import WHEN,clock,row
from tests.test_quote_paper_account import q,funding

TARGET = WHEN+60000


def sequence(include_funding=False):
    initial = ready();state = deepcopy(initial);rows = []
    def add(kind,body,at,params=None):
        nonlocal state
        c = clock(at)
        state,out = transition(state,kind,body,c,'one',params)
        rows.append((str(len(rows)+1),kind,json.dumps(body),json.dumps(c),json.dumps(state),json.dumps(out)))
    add('KLINES',[row()],TARGET+1000)
    add('SERVER_TIME',dict(serverTime=TARGET+57000),TARGET+57000)
    add('PREMIUM',premium(TARGET+58000),TARGET+58000)
    add('FUNDING_HISTORY',[],TARGET+59000,query(state,TARGET+59000))
    add('QUOTE',q(TARGET+60100),TARGET+60100)
    add('END',{},TARGET+65000)
    add('QUOTE',q(TARGET+66100),TARGET+66100)
    if include_funding:
        add('FUNDING_HISTORY',[funding(TARGET+62500)],TARGET+70000,query(state,TARGET+70000))
    return initial,rows


def change_column(rows,index,column,edit):
    result = deepcopy(rows);record = list(result[index]);value = json.loads(record[column])
    edit(value);record[column] = json.dumps(value);result[index] = tuple(record)
    return result


class SignalWindowTests(unittest.TestCase):
    def test_target_requires_utc_four_hour_boundary(self):
        self.assertEqual(window(TARGET)['entry_schedule_ms'],TARGET+60000)
        for value in (TARGET+1,True,-TARGET,0):
            with self.assertRaises(ValueError):window(value)

    def test_early_wait_start_and_missed_are_distinct(self):
        p = window(TARGET)
        for offset,expected in [(-180001,'TOO_EARLY'),(-180000,'WAIT_WITHOUT_NETWORK'),
                                (-60001,'WAIT_WITHOUT_NETWORK'),(-60000,'START'),
                                (-30000,'START'),(-29999,'MISSED_START_WINDOW'),
                                (14400000,'MISSED_START_WINDOW')]:
            self.assertEqual(admission(p,TARGET+offset),expected)

    def test_arm_must_precede_target_and_cannot_backdate_start(self):
        p = window(TARGET)
        require_preclose_arm(p,TARGET-1000)
        for at in (TARGET-60001,TARGET-999,TARGET+1,None):
            with self.assertRaises(ValueError):require_preclose_arm(p,at)

    def test_real_signal_fixture_entry_and_end_exit_independently_audited(self):
        initial,rows = sequence()
        result = audit_rows(initial,rows,TARGET)
        self.assertEqual(result['status'],'TARGET_ENTRY_OBSERVED')
        self.assertEqual(len(result['signals']),1)
        self.assertEqual(len(result['entries']),1)
        self.assertEqual(result['observation_end_exits'],1)
        self.assertEqual(result['other_exits'],0)
        self.assertFalse(result['strategy_performance'])
        self.assertEqual(result['residual_quantity'],'0')

    def test_late_funding_uses_pre_exit_exposure_in_independent_audit(self):
        initial,rows = sequence(True)
        result = audit_rows(initial,rows,TARGET)
        self.assertEqual(result['ledger_events'],3)

    def test_no_signal_and_no_entry_are_not_successful_target_fill(self):
        initial,rows = sequence()
        self.assertEqual(audit_rows(initial,[],TARGET)['status'],'TARGET_SIGNAL_NOT_OBSERVED')
        self.assertEqual(audit_rows(initial,rows[:1],TARGET)['status'],'TARGET_SIGNAL_WITHOUT_ENTRY')

    def test_independent_audit_rejects_wrong_quote_price(self):
        initial,rows = sequence()
        rows = change_column(rows,4,2,lambda x:x.update(askPrice='60200'))
        with self.assertRaises(ValueError):audit_rows(initial,rows,TARGET)

    def test_independent_audit_rejects_backdated_quote(self):
        initial,rows = sequence()
        rows = change_column(rows,4,2,lambda x:x.update(time=TARGET+59000))
        with self.assertRaises(ValueError):audit_rows(initial,rows,TARGET)

    def test_independent_audit_rejects_wrong_signal_lineage(self):
        initial,rows = sequence()
        rows = change_column(rows,3,4,lambda x:x['account']['pending'].update(signal_close_ms=TARGET-14400000))
        with self.assertRaises(ValueError):audit_rows(initial,rows,TARGET)

    def test_independent_audit_rejects_changed_cash(self):
        initial,rows = sequence()
        rows = change_column(rows,4,4,lambda x:x['account'].update(cash=1001))
        with self.assertRaises(ValueError):audit_rows(initial,rows,TARGET)

    def test_wait_has_no_network_and_only_one_second_sleeps(self):
        wall = (TARGET-61000)*1000000
        with patch('scripts.run_signal_window.time.time_ns',side_effect=[wall,wall,wall+1000000000]),\
             patch('scripts.run_signal_window.time.monotonic_ns',side_effect=[0,0,1000000000]),\
             patch('scripts.run_signal_window.time.sleep') as sleep,\
             patch('scripts.run_signal_window.PublicRest') as network:
            self.assertEqual(wait_for_launch(window(TARGET)),'START')
            sleep.assert_called_once_with(1)
            network.assert_not_called()

    def test_clock_jump_rejects_wait(self):
        wall = (TARGET-61000)*1000000
        with patch('scripts.run_signal_window.time.time_ns',side_effect=[wall,wall+3000000000]),\
             patch('scripts.run_signal_window.time.monotonic_ns',side_effect=[0,1000000000]):
            with self.assertRaises(ValueError):wait_for_launch(window(TARGET))


if __name__=='__main__':unittest.main()
