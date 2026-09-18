from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from app.research.observation.t0_signal import T0Signal
from app.research.observation.causal_intents import initial_state,transition,ProbeStore


WHEN=80*14400000-60000


def clock(received, started=None):
    started=received-100 if started is None else started
    return dict(request_started_ns=started*1000000,received_ns=received*1000000,
                request_started_utc_ns=started*1000000,received_utc_ns=received*1000000)


def seed(observe=True):
    signal=T0Signal()
    signal.last_open_ms=WHEN-60000;signal.bucket=WHEN//14400000;signal.count=239
    signal.high=60200;signal.low=60000;signal.completed=79
    signal.ema20=60100;signal.ema80=60000;signal.atr=200
    signal.closes=list(range(60000,60021))
    state=initial_state(signal)
    if observe:state.update(phase='OBSERVE',armed_ms=WHEN-60000)
    return state


def row(when=WHEN):
    return [when,'60100','60200','60000','60150','1',when+59999,'60150',1,'1','60150','0']


def quote(when=WHEN+120001):
    return dict(symbol='BTCUSDC',bidPrice='60149',askPrice='60150',bidQty='1',askQty='1',time=when)


def intent():
    return transition(seed(),'KLINES',[row()],clock(WHEN+61000))[0]


class CausalIntentTests(unittest.TestCase):
    def test_bootstrap_never_creates_trading_intent(self):
        state,out=transition(seed(False),'KLINES',[row()],clock(WHEN+61000))
        self.assertIsNone(state['pending']);self.assertEqual(state['signal_count'],0)

    def test_arm_requires_ready_fresh_history(self):
        state,_=transition(seed(False),'KLINES',[row()],clock(WHEN+61000))
        armed,_=transition(state,'ARM',{},clock(WHEN+62000))
        self.assertEqual(armed['phase'],'OBSERVE')
        with self.assertRaises(ValueError):transition(initial_state(T0Signal()),'ARM',{},clock(WHEN+62000))

    def test_post_intent_quote_uses_ask_not_bar_open(self):
        state,out=transition(intent(),'QUOTE',quote(),clock(WHEN+120100))
        estimate=next(x for x in out if x['kind']=='ENTRY_PROBE_QUOTE_ESTIMATE')
        self.assertEqual(estimate['reference'],60150)
        self.assertGreater(estimate['assumed_price'],60150)
        self.assertLessEqual(estimate['planned_loss'],5)
        self.assertEqual(state['probe_count'],1);self.assertIsNone(state['pending'])

    def test_short_probe_uses_bid(self):
        state=intent();state['pending']['side']=-1
        _,out=transition(state,'QUOTE',quote(),clock(WHEN+120100))
        estimate=next(x for x in out if x['kind']=='ENTRY_PROBE_QUOTE_ESTIMATE')
        self.assertEqual(estimate['reference'],60149)
        self.assertLess(estimate['assumed_price'],60149)

    def test_quote_before_schedule_does_not_estimate(self):
        state,out=transition(intent(),'QUOTE',quote(WHEN+62000),clock(WHEN+62100))
        self.assertEqual(out[-1]['kind'],'BEFORE_SCHEDULE');self.assertIsNotNone(state['pending'])

    def test_stale_or_pre_intent_quote_is_not_used(self):
        for qt in (WHEN+119999,WHEN+110000):
            state,out=transition(intent(),'QUOTE',quote(qt),clock(WHEN+120100))
            self.assertEqual(out[-1]['kind'],'STALE_OR_PRE_INTENT_QUOTE')
            self.assertEqual(state['probe_count'],0)

    def test_late_signal_expires_instead_of_backdating(self):
        state,out=transition(seed(),'KLINES',[row()],clock(WHEN+181000))
        self.assertIsNone(state['pending']);self.assertEqual(out[0]['kind'],'LATE_SIGNAL_EXPIRED')

    def test_pending_probe_expiry(self):
        state,out=transition(intent(),'QUOTE',quote(WHEN+181000),clock(WHEN+181100))
        self.assertEqual(out[-1]['kind'],'PROBE_EXPIRED');self.assertIsNone(state['pending'])

    def test_low_displayed_liquidity_does_not_invent_deeper_fill(self):
        q=quote();q['askQty']='0.0001'
        state,out=transition(intent(),'QUOTE',q,clock(WHEN+120100))
        self.assertEqual(out[-1]['kind'],'INSUFFICIENT_TOP_QUANTITY')
        self.assertEqual(state['probe_count'],0)

    def test_gap_and_conflicting_duplicate_are_rejected_atomically(self):
        original=seed()
        for values in ([row(WHEN+60000)],[row(),row()]):
            with self.assertRaises(ValueError):transition(original,'KLINES',values,clock(WHEN+181000))
            self.assertEqual(original,seed())

    def test_incomplete_bar_does_not_update_signal(self):
        original=seed();state,_=transition(original,'KLINES',[row()],clock(WHEN+60000))
        self.assertEqual(state['signal'],original['signal'])

    def test_clock_jump_and_reordered_request_rejected(self):
        original=intent();bad=clock(WHEN+120100);bad['received_utc_ns']+=2_000_000_000
        with self.assertRaises(ValueError):transition(original,'QUOTE',quote(),bad)
        bad=clock(WHEN+62000,WHEN+60000)
        with self.assertRaises(ValueError):transition(original,'QUOTE',quote(),bad)

    def test_wrong_symbol_or_crossed_quote_rejected(self):
        for patch in (dict(symbol='BTCUSDT'),dict(bidPrice='70000')):
            with self.assertRaises(ValueError):transition(intent(),'QUOTE',quote()|patch,clock(WHEN+120100))

    def test_sqlite_raw_state_output_transaction_and_idempotent_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'probe.db';binding={'source':'fixed'}
            store=ProbeStore(path,binding,seed())
            raw=json.dumps([row()]);received=clock(WHEN+61000)
            def fail():raise RuntimeError('injected after INSERT before COMMIT')
            with self.assertRaises(RuntimeError):store.commit('one','KLINES',raw,received,before_commit=fail)
            self.assertEqual(store.state(),seed());store.close()
            store=ProbeStore(path,binding)
            first=store.commit('one','KLINES',raw,received)
            self.assertEqual(store.commit('one','KLINES',raw,received),first)
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0],1)
            with self.assertRaises(ValueError):store.commit('one','KLINES','[]',received)
            store.close()
            with self.assertRaises(ValueError):ProbeStore(path,{'source':'changed'})


if __name__=='__main__':unittest.main()
