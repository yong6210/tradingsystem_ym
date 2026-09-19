import json
import unittest
from dataclasses import replace
from pathlib import Path

from app.research.recovery.models import Quote, Costs, dec, jsonable, Bar
from app.research.recovery.separated_execution import SeparatedReplay, execution_quote
from app.research.recovery.market_adapter_v02 import MarketAdapterV02
from app.research.recovery.market_adapter import MarketAdapter
from tests import test_recovery_add_admission as fixtures


class SeparatedTests(unittest.TestCase):
    def make(self,slip='.001',auto=True,first_response=1):
        f=fixtures.AddAdmissionTests();f.first_response_qty=first_response;f.setUp()
        config=json.loads(json.dumps(f.config));config['costs']['slippage']=slip
        r=SeparatedReplay(config)
        for event in f.r.events:
            event=json.loads(json.dumps(event))
            if event['type']=='start':event['simulate_fills']=auto
            r.process(event)
            if event['type']=='start':break
        self.assertIsNotNone(r.engine.ledger)
        return r,f

    def quote(self,t=48*60000+1,bid='99.05',ask='99.06',liquidity=100,ok=True):
        return Quote(t,bid,ask,100,100,liquidity,ok,True)

    def send(self,r,q,auto=True):
        return r.process(dict(type='quote',**jsonable(q),simulate_fills=auto))

    def test_fill_prices_are_separate_and_limits_reserve_execution_cost(self):
        r,f=self.make()
        initial=next(iter(r.engine.ledger.orders.values()))
        self.assertEqual(r.engine.quote.ask,dec(103))
        self.assertEqual(initial.limit,dec('103.11'))
        self.assertEqual(r.engine.ledger.average,initial.limit)
        self.assertLessEqual(r.engine.ledger.risk_used(),r.engine.budget)
        self.assertEqual(r.engine.ledger.rows[0]['fee'],dec('103.11')*4*dec('.00025'))

    def test_same_market_stop_signal_does_not_depend_on_slippage(self):
        for slip in ('.0002','.001'):
            r,_=self.make(slip)
            self.send(r,self.quote())
            self.assertFalse(r.engine.exit_latched)
            self.assertFalse(any(o.kind=='reduce' for o in r.engine.ledger.orders.values()))
            self.send(r,self.quote(t=48*60000+2,bid='98.99',ask='99.00'))
            self.assertTrue(r.engine.ledger.settled)
            reduce=[o for o in r.engine.ledger.orders.values() if o.kind=='reduce'][0]
            self.assertEqual(reduce.reason,'common_stop')

    def test_add_admission_callback_also_uses_signal_stop_price(self):
        r,f=self.make()
        q=self.quote()
        sub=replace(f.sub,decision_ms=q.time_ms,context=replace(f.sub.context,recorded_ms=f.sub.context.recorded_ms))
        # Rejected stale confirmation must not cause a fabricated price stop.
        r.process(dict(type='add',quote=jsonable(q),submission=jsonable(sub),simulate_fills=False))
        self.assertFalse(r.engine.exit_latched)
        self.assertIsNone(r.engine._admission_signal)
        self.assertEqual(r.engine.quote,q)

    def test_worsened_fill_estimate_respects_original_order_cap(self):
        r,_=self.make(auto=False)
        self.send(r,self.quote(bid='103.10',ask='103.11'))
        self.assertEqual(r.engine.ledger.quantity,0)
        self.send(r,self.quote(t=48*60000+2,bid='102.99',ask='103',liquidity='.5'))
        self.assertEqual(r.engine.ledger.quantity,dec('.5'))
        self.assertEqual(r.engine.ledger.average,dec('103.11'))
        self.send(r,self.quote(t=48*60000+3,bid='102.99',ask='103',liquidity='.5'))
        self.assertEqual(r.engine.ledger.quantity,dec(1))

    def test_partial_exit_fill_cannot_create_residual_price_signal(self):
        r,_=self.make()
        q=self.quote(bid='110',ask='110.01')
        self.send(r,q,False)
        order=next(o for o in r.engine.ledger.orders.values() if o.kind=='reduce')
        r.process(dict(type='fill',fill_id='bad_execution',order_id=order.id,quantity=1,
                       price='99.5',fee='0.024875',time_ms=q.time_ms))
        self.assertTrue(r.engine.residual_armed)
        self.assertFalse(r.engine.exit_latched)
        self.assertEqual(r.engine.ledger.quantity,3)
        self.send(r,self.quote(t=q.time_ms+1,bid='100.01',ask='100.02'),False)
        self.assertFalse(r.engine.exit_latched)
        self.send(r,self.quote(t=q.time_ms+2,bid='99.99',ask='100'),False)
        self.assertTrue(r.engine.exit_latched)
        self.assertEqual(r.engine.execution_exit_reason,'residual_stop')

    def test_untrusted_signal_never_simulates_a_reduction_fill(self):
        r,_=self.make()
        self.send(r,self.quote(bid='98',ask='98.01',ok=False))
        self.assertTrue(r.engine.exit_latched)
        self.assertEqual(r.engine.ledger.quantity,4)

    def test_price_rounding_both_sides_and_zero_slippage(self):
        q=self.quote(bid='100.00',ask='100.01')
        c=Costs(0,'.001','.01','.1','.1',0)
        out=execution_quote(q,c)
        self.assertEqual(out.bid,dec('99.90'))
        self.assertEqual(out.ask,dec('100.12'))
        self.assertEqual(execution_quote(q,replace(c,slippage=0)),q)

    def test_short_stop_uses_ask_signal_not_slipped_buyback(self):
        original,f=self.make()
        r=SeparatedReplay(original.config)
        def mirror_bar(b):
            return {**b,'open':str(210-dec(b['open'])),'close':str(210-dec(b['close'])),
                    'high':str(210-dec(b['low'])),'low':str(210-dec(b['high']))}
        def mirror_zone(z):
            return {**z,'low':str(210-dec(z['high'])),'high':str(210-dec(z['low']))}
        for raw in original.events:
            event=json.loads(json.dumps(raw))
            if event['type']=='bar':event=mirror_bar(event)
            if event['type']=='start':
                p=event['plan'];p['side']=-1;p['stop']=str(210-dec(p['stop']))
                p['support']=mirror_zone(p['support']);p['target']=mirror_zone(p['target'])
                q=event['quote'];q['bid'],q['ask']=str(210-dec(q['ask'])),str(210-dec(q['bid']))
                s=event['submission'];s['market_side']=-1
                for role in ('support','target'):
                    o=s[role];o['side']=-o['side'];o['history']['zone']=mirror_zone(o['history']['zone'])
                    o['last_bar']=mirror_bar(o['last_bar'])
                for c in (s['contract'],s['reach']['target']):
                    c['side']=-1
                    for key in ('reference_price','first_response_price'):c[key]=str(210-dec(c[key]))
                for key in ('reaction_price','residual_stop'):
                    s['execution'][key]=str(210-dec(s['execution'][key]))
            r.process(event)
        self.assertEqual(r.engine.ledger.quantity,4)
        self.send(r,self.quote(bid='110.94',ask='110.95'))
        self.assertFalse(r.engine.exit_latched)
        self.send(r,self.quote(t=48*60000+2,bid='111',ask='111.01'))
        self.assertTrue(r.engine.ledger.settled)

    def test_zero_slippage_preserves_all_fixed_integration_paths(self):
        from scripts.validate_guarded_integration import cases
        for name,original,config,quote in cases():
            with self.subTest(case=name):
                self.assertEqual(dec(config['costs']['slippage']),0)
                replay=SeparatedReplay(config)
                for event in original.events:replay.process(event)
                snapshot=replay.engine.snapshot();snapshot.pop('price_model')
                self.assertEqual(snapshot,original.engine.snapshot())

    def test_checkpoint_replays_prices_and_retains_restart_lock(self):
        r,_=self.make()
        restored=SeparatedReplay.restore(r.config,r.checkpoint(),48*60000+1)
        self.assertEqual(restored.engine.ledger.cash,r.engine.ledger.cash)
        self.assertEqual(restored.engine.quote,r.engine.quote)
        self.assertIn('restart',restored.engine.locks)
        self.assertEqual(restored.binding['controller'],'recovery-separated-v02')

    def test_adapter_v02_checkpoint_cannot_be_loaded_as_v01(self):
        root=Path(__file__).resolve().parents[1]
        config=json.loads((root/'configs/research/recovery_market_v02.json').read_text())
        a=MarketAdapterV02(config)
        a.observe(Bar(60000,100,101,99,100,60000))
        envelope=a.checkpoint()
        restored=MarketAdapterV02.restore(config,envelope,60001)
        self.assertEqual(restored.bars,a.bars)
        self.assertIn('restart',restored.replay.engine.locks)
        with self.assertRaises(ValueError):MarketAdapter.restore(config,envelope,60001)


if __name__=='__main__':unittest.main()
