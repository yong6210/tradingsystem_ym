from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from app.research.observation.t0_signal import T0Signal
from app.research.observation.quote_paper_account import initial_state,transition
from app.research.observation.paper_store import PaperStore
from tests.test_causal_intents import WHEN,clock,row,quote,seed


def prepared(side=1):
    signal=T0Signal.restore(seed(False)['signal']);signal.completed=80
    signal.ema20=60000.1 if side==1 else 59900
    state=initial_state(signal,'one')
    return transition(state,'ARM',{},clock(WHEN+1000),'one')[0]


def awaiting(side=1):
    return transition(prepared(side),'KLINES',[row()],clock(WHEN+61000),'one')[0]


def entered(side=1):
    return transition(awaiting(side),'QUOTE',quote(),clock(WHEN+120100),'one')[0]


def target(state,side,at=WHEN+125000):
    # Explicit synthetic target-state fixture; not a public/live signal.
    copy=deepcopy(state)
    copy['pending']=dict(id='fixture',side=side,close=60150.,atr=200.,session='one',
        created_ns=(at-1000)*1000000,earliest_observable_ms=at,expires_ms=at+60000)
    return copy


def q(at,bid=60149.,ask=60150.,quantity=1):
    return dict(symbol='BTCUSDC',bidPrice=str(bid),askPrice=str(ask),bidQty=str(quantity),askQty=str(quantity),time=at-1)


def funding(at=WHEN+125000,rate='.001',mark='60000'):
    return dict(symbol='BTCUSDC',fundingTime=at,fundingRate=rate,markPrice=mark)


class QuotePaperTests(unittest.TestCase):
    def test_stale_quote_cannot_fill_or_clear_required_exit(self):
        state=entered();state['exit_required']='price_stop'
        after,out=transition(state,'QUOTE',q(WHEN+125000),clock(WHEN+140000),'one')
        self.assertEqual(after['quantity'],state['quantity'])
        self.assertEqual(after['exit_required'],'price_stop')
        self.assertEqual(out[-1]['kind'],'STALE_QUOTE_NO_ACTION')

    def test_pre_schedule_quote_cannot_enter_and_expired_target_is_dropped(self):
        state=awaiting()
        state,_=transition(state,'QUOTE',q(WHEN+62000),clock(WHEN+62100),'one')
        self.assertEqual(state['entries'],0)
        state,_=transition(state,'QUOTE',q(WHEN+181000),clock(WHEN+181100),'one')
        self.assertEqual(state['entries'],0);self.assertIsNone(state['pending'])

    def test_actual_signal_creates_intent_and_entry_uses_persistent_cash(self):
        state=entered()
        self.assertEqual((state['observed_signals'],state['eligible_intents'],state['entries']),(1,1,1))
        self.assertGreater(state['quantity'],0)
        self.assertLess(state['cash'],1000)
        self.assertAlmostEqual(state['cash'],1000-state['fees'])

    def test_same_direction_does_not_add_position(self):
        state=entered();before=state['quantity']
        after,out=transition(target(state,1),'QUOTE',q(WHEN+130000),clock(WHEN+130100),'one')
        self.assertEqual(after['quantity'],before);self.assertEqual(after['entries'],1)
        self.assertEqual(out[-1]['kind'],'HOLD_EXISTING_POSITION')

    def test_neutral_closes_without_reentry(self):
        state,out=transition(target(entered(),0),'QUOTE',q(WHEN+130000),clock(WHEN+130100),'one')
        self.assertEqual(state['quantity'],0);self.assertIsNone(state['pending'])
        self.assertEqual(out[-1]['reason'],'neutral_exit')

    def test_reversal_closes_then_enters_only_on_next_quote(self):
        state,out=transition(target(entered(),-1),'QUOTE',q(WHEN+130000),clock(WHEN+130100),'one')
        self.assertEqual(state['quantity'],0);self.assertEqual(state['entries'],1)
        self.assertEqual(out[-1]['reason'],'reverse_exit')
        state,out=transition(state,'QUOTE',q(WHEN+131000),clock(WHEN+131100),'one')
        self.assertLess(state['quantity'],0);self.assertEqual(state['entries'],2)
        self.assertEqual(out[-1]['kind'],'PAPER_ENTRY')

    def test_stop_gap_uses_new_quote_and_pending_exit_survives_price_recovery(self):
        state=entered();original=state['quantity']
        state,out=transition(state,'QUOTE',q(WHEN+130000,59000,59001,.0001),clock(WHEN+130100),'one')
        self.assertEqual(state['quantity'],original);self.assertEqual(state['exit_required'],'price_stop')
        state,out=transition(state,'QUOTE',q(WHEN+131000,60000,60001),clock(WHEN+131100),'one')
        fill=out[-1]
        self.assertEqual(state['quantity'],0);self.assertEqual(fill['reason'],'price_stop')
        self.assertLess(fill['price'],60000)

    def test_short_stop_uses_ask(self):
        state=entered(-1)
        state,out=transition(state,'QUOTE',q(WHEN+130000,62000,62001),clock(WHEN+130100),'one')
        self.assertEqual(state['quantity'],0)
        self.assertGreater(out[-1]['price'],62001)

    def test_daily_loss_halts_new_entry(self):
        state=entered()
        state,out=transition(state,'QUOTE',q(WHEN+130000,55000,55001),clock(WHEN+130100),'one')
        self.assertTrue(state['day_halted']);self.assertEqual(state['quantity'],0)
        state,out=transition(target(state,1,WHEN+140000),'QUOTE',q(WHEN+141000),clock(WHEN+141100),'one')
        self.assertEqual(state['entries'],1);self.assertEqual(out[-1]['kind'],'ENTRY_BLOCKED_RISK_OR_PHASE')

    def test_dd_halt_persists_across_restart(self):
        state=entered()
        state,_=transition(state,'QUOTE',q(WHEN+130000,40000,40001),clock(WHEN+130100),'one')
        self.assertTrue(state['halted'])
        c=clock(WHEN+140000);c.update(request_started_ns=0,received_ns=1000000)
        state,_=transition(state,'BEGIN_SESSION',{},c,'two')
        self.assertTrue(state['halted'])

    def test_maximum_hold_uses_elapsed_utc(self):
        state=entered();at=state['entered_ms']+10080*60000+1000
        state,out=transition(state,'QUOTE',q(at),clock(at+100),'one')
        self.assertEqual(out[-1]['reason'],'time_exit');self.assertEqual(state['quantity'],0)

    def test_late_funding_after_exit_posts_historical_quantity_once(self):
        old=entered();qty=old['quantity']
        state,_=transition(target(old,0),'QUOTE',q(WHEN+130000),clock(WHEN+130100),'one')
        cash=state['cash'];f=funding()
        state,out=transition(state,'FUNDING',f,clock(WHEN+140000),'one')
        self.assertAlmostEqual(state['cash'],cash-qty*60000*.001)
        self.assertEqual(out[-1]['settlement_quantity'],qty)
        self.assertEqual(out[-1]['quantity'],0)
        self.assertEqual(out[-1]['received_ms'],WHEN+140000)
        snapshot=state['cash']
        state,out=transition(state,'FUNDING',f,clock(WHEN+141000),'one')
        self.assertEqual(state['cash'],snapshot);self.assertEqual(out[-1]['kind'],'FUNDING_DUPLICATE')

    def test_short_positive_funding_is_credit(self):
        state=entered(-1);before=state['cash'];qty=state['quantity']
        state,_=transition(state,'FUNDING',funding(),clock(WHEN+140000),'one')
        self.assertAlmostEqual(state['cash'],before-qty*60000*.001);self.assertGreater(state['cash'],before)

    def test_funding_before_entry_uses_zero_not_current_quantity(self):
        state=entered();before=state['cash']
        state,out=transition(state,'FUNDING',funding(WHEN+110000),clock(WHEN+140000),'one')
        self.assertEqual(state['cash'],before);self.assertEqual(out[-1]['settlement_quantity'],0)

    def test_conflicting_funding_and_ambiguous_fill_boundary_rejected(self):
        state=entered();original=deepcopy(state)
        with self.assertRaises(ValueError):transition(state,'FUNDING',funding(state['entered_ms']),clock(WHEN+140000),'one')
        self.assertEqual(state,original)
        state,_=transition(state,'FUNDING',funding(),clock(WHEN+140000),'one')
        with self.assertRaises(ValueError):transition(state,'FUNDING',funding(rate='.002'),clock(WHEN+141000),'one')

    def test_funding_before_first_new_day_quote_is_in_daily_risk(self):
        state=entered();tomorrow=(state['day']+1)*86400000
        state,_=transition(state,'FUNDING',funding(rate='.06'),clock(tomorrow+2000),'one')
        state,out=transition(state,'QUOTE',q(tomorrow+3000),clock(tomorrow+3100),'one')
        self.assertTrue(state['day_halted']);self.assertEqual(state['quantity'],0)

    def test_new_session_preserves_position_cancels_pending_and_resets_mono(self):
        state=target(entered(),-1);qty=state['quantity']
        c=clock(WHEN+140000);c.update(request_started_ns=1000,received_ns=2000)
        state,out=transition(state,'BEGIN_SESSION',{},c,'two')
        self.assertEqual(state['quantity'],qty);self.assertIsNone(state['pending'])
        self.assertEqual(state['phase'],'BOOTSTRAP');self.assertEqual(state['exit_required'],'restart_gap_exit')
        next_clock=clock(WHEN+141000)
        next_clock.update(request_started_ns=999902000,received_ns=1000002000)
        with self.assertRaises(ValueError):transition(state,'QUOTE',q(WHEN+141000),next_clock,'one')
        state,out=transition(state,'QUOTE',q(WHEN+141000),next_clock,'two')
        self.assertEqual(state['quantity'],0);self.assertEqual(out[-1]['reason'],'restart_gap_exit')

    def test_backward_utc_and_session_reuse_rejected(self):
        state=entered();c=clock(WHEN+120050,WHEN+120040)
        with self.assertRaises(ValueError):transition(state,'QUOTE',q(WHEN+120050),c,'one')
        with self.assertRaises(ValueError):transition(state,'BEGIN_SESSION',{},clock(WHEN+140000),'one')

    def test_store_failure_reopen_and_retry_do_not_double_fill(self):
        state=awaiting();binding=dict(costs=state['costs'],risk=state['risk'],source_hashes={'fixture':'v1'})
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'paper.sqlite';store=PaperStore(path,binding,state)
            raw=json.dumps(quote());c=clock(WHEN+120100)
            def fault():raise RuntimeError('before commit')
            with self.assertRaises(RuntimeError):store.commit('one','QUOTE',raw,c,'one',before_commit=fault)
            self.assertEqual(store.state(),state);store.close()
            store=PaperStore(path,binding)
            first=store.commit('one','QUOTE',raw,c,'one')
            self.assertEqual(store.commit('one','QUOTE',raw,c,'one'),first)
            self.assertEqual(store.state()['entries'],1);store.close()
            with self.assertRaises(ValueError):PaperStore(path,binding|dict(source_hashes={'fixture':'v2'}))


if __name__=='__main__':unittest.main()
