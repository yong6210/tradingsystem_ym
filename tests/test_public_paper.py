from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from app.research.observation.public_paper import initial_state, transition, entry_guard
from app.research.observation.public_paper_store import PublicPaperStore
from app.research.observation.t0_signal import T0Signal
from tests.test_causal_intents import WHEN, clock, seed, row
from tests.test_quote_paper_account import q, funding, entered, target


def initial():
    signal = T0Signal.restore(seed(False)['signal'])
    signal.completed = 80; signal.ema20 = 60000.1
    return initial_state(signal,'one',WHEN)


def premium(at, due=WHEN+150000):
    return dict(symbol='BTCUSDC',time=at-100,nextFundingTime=due,
                markPrice='60000',lastFundingRate='0.99')


def query(state, at):
    return dict(symbol='BTCUSDC',startTime=state['scan_start_ms'],endTime=at-1100,limit=100)


def ready():
    state = initial()
    state,_ = transition(state,'SERVER_TIME',dict(serverTime=WHEN+1000),clock(WHEN+1000),'one')
    state,_ = transition(state,'PREMIUM',premium(WHEN+2000),clock(WHEN+2000),'one')
    state,_ = transition(state,'FUNDING_HISTORY',[],clock(WHEN+3000),'one',query(state,WHEN+3000))
    state,_ = transition(state,'ARM',{},clock(WHEN+4000),'one')
    return state


def refreshed(state, at, rows=None, due=WHEN+150000):
    state,_ = transition(state,'SERVER_TIME',dict(serverTime=at),clock(at),'one')
    state,_ = transition(state,'PREMIUM',premium(at+1000,due),clock(at+1000),'one')
    return transition(state,'FUNDING_HISTORY',rows or [],clock(at+2000),'one',query(state,at+2000))[0]


class PublicPaperTests(unittest.TestCase):
    def test_initial_guard_closed_and_arm_requires_fresh_sources(self):
        state,out = transition(initial(),'ARM',{},clock(WHEN+1000),'one')
        self.assertEqual(state['account']['phase'],'BOOTSTRAP')
        self.assertEqual(out[0]['kind'],'PUBLIC_INPUT_REJECTED')
        state = refreshed(state,WHEN+2000)
        state,_ = transition(state,'ARM',{},clock(WHEN+5000),'one')
        self.assertEqual(state['account']['phase'],'OBSERVE')

    def test_estimated_funding_rate_never_posts_cash(self):
        state = ready()
        self.assertEqual(state['account']['cash'],1000)
        self.assertEqual(state['account']['funding'],0)
        self.assertEqual(state['guard']['status'],'SCOPED_READY')

    def test_actual_t0_signal_can_enter_after_fresh_public_inputs(self):
        state = ready()
        state,_ = transition(state,'KLINES',[row()],clock(WHEN+61000),'one')
        state = refreshed(state,WHEN+117000)
        state,out = transition(state,'QUOTE',q(WHEN+120100),clock(WHEN+120100),'one')
        self.assertGreater(state['account']['quantity'],0)
        self.assertIn('PAPER_ENTRY',[x['kind'] for x in out])

    def test_stale_funding_cancels_pending_entry(self):
        state = ready()
        state,_ = transition(state,'KLINES',[row()],clock(WHEN+61000),'one')
        state,out = transition(state,'QUOTE',q(WHEN+120100),clock(WHEN+120100),'one')
        self.assertEqual(state['account']['entries'],0)
        self.assertIsNone(state['account']['pending'])
        self.assertIn('ENTRY_CANCELLED_DATA_GUARD',[x['kind'] for x in out])

    def test_overdue_old_schedule_survives_new_schedule_and_empty_scan(self):
        state = refreshed(ready(),WHEN+151000,due=WHEN+300000)
        self.assertIn(WHEN+150000,state['expected'])
        self.assertIn('UNRESOLVED_EXPECTED_FUNDING',state['guard']['reasons'])
        state,_ = transition(state,'FUNDING_HISTORY',[funding(WHEN+150000)],
                              clock(WHEN+155000),'one',query(state,WHEN+155000))
        self.assertNotIn('UNRESOLVED_EXPECTED_FUNDING',state['guard']['reasons'])

    def test_funding_due_tolerance_does_not_allow_early_boundary_entry(self):
        state = ready()
        state['account']['settlements'][str(WHEN+149500)] = dict(time=WHEN+149500,rate=.001,mark=60000)
        self.assertIn('FUNDING_BOUNDARY',entry_guard(state,WHEN+150600)['reasons'])

    def test_future_schedule_revision_needs_review(self):
        state,_ = transition(ready(),'PREMIUM',premium(WHEN+5000,WHEN+200000),clock(WHEN+5000),'one')
        self.assertIn('FUTURE_SCHEDULE_CHANGED',state['review_reasons'])

    def test_unhealthy_feed_does_not_block_stop_exit(self):
        state = ready();state['account'] = entered()
        state,out = transition(state,'QUOTE',q(WHEN+130100,59000,59001),clock(WHEN+130100),'one')
        self.assertEqual(state['account']['quantity'],0)
        self.assertIn('PAPER_EXIT',[x['kind'] for x in out])
        self.assertIn('HELD_POSITION_SCHEDULE_GAP',state['review_reasons'])

    def test_reversal_exit_allowed_but_reentry_blocked_by_data_guard(self):
        state = ready();state['account'] = target(entered(),-1)
        state,_ = transition(state,'QUOTE',q(WHEN+130100),clock(WHEN+130100),'one')
        self.assertEqual(state['account']['quantity'],0)
        state,_ = transition(state,'QUOTE',q(WHEN+131100),clock(WHEN+131100),'one')
        self.assertEqual(state['account']['entries'],1)

    def test_late_history_after_exit_posts_once(self):
        state = ready();state['account'] = target(entered(),0)
        qty = state['account']['quantity']
        state,_ = transition(state,'QUOTE',q(WHEN+130100),clock(WHEN+130100),'one')
        before = state['account']['cash']
        for at in (WHEN+140000,WHEN+141000):
            state,_ = transition(state,'FUNDING_HISTORY',[funding()],clock(at),'one',query(state,at))
        self.assertAlmostEqual(state['account']['cash'],before-qty*60000*.001)

    def test_history_batch_conflict_rolls_back_all_new_postings(self):
        state = ready()
        state,_ = transition(state,'FUNDING_HISTORY',[funding(WHEN-5000)],clock(WHEN+5000),'one',query(state,WHEN+5000))
        original = deepcopy(state['account'])
        rows = [funding(WHEN-6000),funding(WHEN-5000,rate='.002')]
        state,out = transition(state,'FUNDING_HISTORY',rows,clock(WHEN+6000),'one',query(state,WHEN+6000))
        self.assertEqual(state['account']['settlements'],original['settlements'])
        self.assertEqual(state['account']['cash'],original['cash'])
        self.assertEqual(out[0]['kind'],'PUBLIC_INPUT_REJECTED')

    def test_empty_scan_cannot_erase_previously_seen_settlement(self):
        state = ready()
        state,_ = transition(state,'FUNDING_HISTORY',[funding(WHEN-5000)],clock(WHEN+5000),'one',query(state,WHEN+5000))
        state,out = transition(state,'FUNDING_HISTORY',[],clock(WHEN+6000),'one',query(state,WHEN+6000))
        self.assertEqual(out[0]['kind'],'PUBLIC_INPUT_REJECTED')

    def test_truncated_out_of_range_wrong_symbol_and_duplicate_scans_rejected(self):
        state = ready();at = WHEN+6000
        for rows in ([funding(WHEN-5000)]*100,[funding(at)],
                     [funding(WHEN-5000)|dict(symbol='ETHUSDC')],
                     [funding(WHEN-5000),funding(WHEN-5000)],
                     [funding(WHEN-5000)|dict(rateType='Special')]):
            with self.subTest(rows=len(rows)):
                after,out = transition(state,'FUNDING_HISTORY',rows,clock(at),'one',query(state,at))
                self.assertEqual(out[0]['kind'],'PUBLIC_INPUT_REJECTED')
                self.assertEqual(after['account']['settlements'],{})

    def test_query_start_cannot_skip_unresolved_history(self):
        state = ready();at = WHEN+6000
        bad = query(state,at);bad['startTime']+=1
        state,out = transition(state,'FUNDING_HISTORY',[],clock(at),'one',bad)
        self.assertEqual(out[0]['kind'],'PUBLIC_INPUT_REJECTED')

    def test_transient_network_failure_recovers_only_after_valid_channel(self):
        state,out = transition(ready(),'FEED_ERROR',dict(channel='FUNDING_HISTORY',error='HTTP_503'),clock(WHEN+5000),'one')
        self.assertEqual(state['guard']['status'],'BLOCK_NEW_ENTRY')
        state,_ = transition(state,'PREMIUM',premium(WHEN+6000),clock(WHEN+6000),'one')
        self.assertIn('FUNDING_HISTORY',state['faults'])
        state,_ = transition(state,'FUNDING_HISTORY',[],clock(WHEN+7000),'one',query(state,WHEN+7000))
        self.assertEqual(state['guard']['status'],'SCOPED_READY')

    def test_held_schedule_gap_stays_blocked_after_refetch(self):
        state = ready();state['account'] = entered()
        state = refreshed(state,WHEN+121000)
        self.assertIn('HELD_POSITION_SCHEDULE_GAP',state['guard']['reasons'])

    def test_restart_resets_freshness_but_preserves_due_and_position(self):
        state = ready();state['account'] = entered()
        c = clock(WHEN+140000);c.update(request_started_ns=0,received_ns=1000000)
        state,_ = transition(state,'BEGIN_SESSION',{},c,'two')
        self.assertGreater(state['account']['quantity'],0)
        self.assertIsNone(state['schedule_received_ms'])
        self.assertEqual(state['expected'],[WHEN+150000])
        self.assertEqual(state['account']['exit_required'],'restart_gap_exit')

    def test_end_cancels_entry_preserves_position_and_flags_exit(self):
        state = ready();state['account'] = target(entered(),-1)
        state,_ = transition(state,'END',{},clock(WHEN+140000),'one')
        self.assertIsNone(state['account']['pending'])
        self.assertEqual(state['account']['exit_required'],'observation_end_exit')
        self.assertGreater(state['account']['quantity'],0)

    def test_store_failed_batch_retry_and_query_identity(self):
        state = ready();binding = {k:state['account'][k] for k in ('costs','risk')}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'public.sqlite';store = PublicPaperStore(path,binding,state)
            c = clock(WHEN+5000);params = query(state,WHEN+5000)
            def fault():raise RuntimeError('before commit')
            with self.assertRaises(RuntimeError):
                store.commit('a','FUNDING_HISTORY','[]',c,'one',params,before_commit=fault)
            self.assertEqual(store.state(),state);store.close()
            store = PublicPaperStore(path,binding)
            out = store.commit('a','FUNDING_HISTORY','[]',c,'one',params)
            self.assertEqual(store.commit('a','FUNDING_HISTORY','[]',c,'one',params),out)
            with self.assertRaises(ValueError):
                store.commit('a','FUNDING_HISTORY','[]',c,'one',params|dict(limit=99))
            rejected = store.commit('b','SERVER_TIME','not json',clock(WHEN+6000),'one')
            self.assertEqual(rejected[0]['kind'],'PUBLIC_INPUT_REJECTED')
            store.close()


if __name__=='__main__':unittest.main()
