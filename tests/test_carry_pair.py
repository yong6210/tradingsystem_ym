"""Durable scripted exchange evidence; no prices or fill odds are inferred."""
from decimal import Decimal as D
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from app.research.execution.carry_pair import CarryPair,encode


def context(now=1000,price='60000',**changes):
    return dict(now_ms=now,observed_ms=now,spot_bid=price,spot_ask=price,
        future_bid=price,future_ask=price,mark=price,funding_confirmed=True)|changes


class PaperExchange:
    def __init__(self,path):
        self.path=str(path);self.lose_submit=False;self.lose_cancel=False
        with sqlite3.connect(self.path) as db:
            db.executescript('CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,payload TEXT,receipt TEXT);'
                'CREATE TABLE IF NOT EXISTS sends(kind TEXT,id TEXT);')
    def submit(self,o):
        r=dict(order_id=o['id'],scope=o['scope'],symbol=o['symbol'],market=o['market'],version=0,status='NEW',cumulative='0',fills=[],observed_ms=o['request_ms'])
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO sends VALUES (?,?)',('submit',o['id']))
            db.execute('INSERT INTO orders VALUES (?,?,?)',(o['id'],encode(o),encode(r)))
        if self.lose_submit:raise TimeoutError('accepted, response lost')
        return r
    def lookup(self,o):
        with sqlite3.connect(self.path) as db:r=db.execute('SELECT receipt FROM orders WHERE id=?',(o['id'],)).fetchone()
        return json.loads(r[0]) if r else None
    def cancel(self,o):
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO sends VALUES (?,?)',('cancel',o['id']))
            r=json.loads(db.execute('SELECT receipt FROM orders WHERE id=?',(o['id'],)).fetchone()[0])
            if r['status'] not in ('FILLED','CANCELED','EXPIRED','REJECTED'):
                r['status']='CANCELED';r['version']+=1
                r['observed_ms']=max(r['observed_ms'],o['request_ms'])
                db.execute('UPDATE orders SET receipt=? WHERE id=?',(encode(r),o['id']))
        if self.lose_cancel:raise TimeoutError('cancel accepted, response lost')
        return r
    def publish(self,order_id,status,*,qty='0',price='60000',fee_usdc='0',fee_btc='0',time_ms=1001):
        with sqlite3.connect(self.path) as db:
            o,r=db.execute('SELECT payload,receipt FROM orders WHERE id=?',(order_id,)).fetchone();r=json.loads(r)
            if D(qty):r['fills'].append(dict(id=order_id+'/t'+str(len(r['fills'])+1),qty=qty,
                quote=str(D(qty)*D(price)),fee_usdc=fee_usdc,fee_btc=fee_btc,time_ms=time_ms))
            r['version']+=1;r['status']=status;r['cumulative']=str(sum((D(f['qty']) for f in r['fills']),D(0)))
            r['observed_ms']=max(r['observed_ms'],time_ms)
            db.execute('UPDATE orders SET receipt=? WHERE id=?',(encode(r),order_id));return r
    def count(self,kind='submit'):
        with sqlite3.connect(self.path) as db:return db.execute('SELECT count(*) FROM sends WHERE kind=?',(kind,)).fetchone()[0]


class PairFixture:
    def __init__(self,root):
        self.root=Path(root);self.pair=CarryPair(self.root/'pair.sqlite');self.paper=PaperExchange(self.root/'exchange.sqlite')
    def submit_next(self,now=1000,**changes):
        c=context(now,**changes);a=self.pair.next(c)
        if a['kind']!='SUBMIT':raise AssertionError(a)
        self.pair.dispatch(a,self.paper,c);return a['order_id']
    def publish(self,identity,status='FILLED',**kwargs):
        r=self.paper.publish(identity,status,**kwargs);self.pair.receive(r);return r
    def open(self):
        s=self.submit_next(1000);self.publish(s,qty='.006',fee_usdc='.36',time_ms=1001)
        f=self.submit_next(1002);self.publish(f,qty='.006',fee_usdc='.09',time_ms=1003)
        assert self.pair.next(context(1005))['kind']=='OPEN'
        return s,f
    def restart(self):self.pair.close();self.pair=CarryPair(self.root/'pair.sqlite')
    def close(self):self.pair.close()


class CarryPairTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.f=PairFixture(self.tmp.name)
    def tearDown(self):self.f.close();self.tmp.cleanup()
    def test_complete_pair_late_funding_operating_cost_and_no_transfers(self):
        f=self.f;f.open();f.pair.request_exit()
        future=f.submit_next(1006,price='61000');f.publish(future,qty='.006',price='61000',fee_usdc='.0915',time_ms=1007)
        spot=f.submit_next(1008,price='61000');f.publish(spot,qty='.006',price='61000',fee_usdc='.366',time_ms=1009)
        self.assertEqual(f.pair.next(context(1010,price='61000'))['kind'],'FLAT_HALTED')
        event=f.pair.funding('settle1',1004,'60000','.0001');self.assertEqual(D(event['receipt']),D('.036'))
        f.pair.funding('settle1',1004,'60000','.0001');f.pair.operating_cost('cost1','.1');f.pair.operating_cost('cost1','.1')
        s=f.pair.state();self.assertEqual(D(s['spot_cash']),D('505.174'));self.assertEqual(D(s['future_cash']),D('493.8545'))
        self.assertEqual(D(s['spot_cash'])+D(s['future_cash']),D('999.0285'));self.assertEqual(f.paper.count(),4)
    def test_no_hedge_before_final_spot_cancel_and_fallback_only_remaining(self):
        f=self.f;s=f.submit_next();f.publish(s,'PARTIALLY_FILLED',qty='.002',time_ms=1001)
        a=f.pair.next(context(4000));self.assertEqual(a['kind'],'CANCEL')
        f.paper.publish(s,'PARTIALLY_FILLED',qty='.001',time_ms=3999)
        f.pair.dispatch(a,f.paper,context(4000))
        fallback=f.submit_next(4001);o=f.pair.state()['orders'][-1]
        self.assertEqual(o['kind'],'MARKET');self.assertEqual(D(o['qty']),D('.003'))
        f.publish(fallback,qty='.003',time_ms=4002)
        f.submit_next(4003);self.assertEqual(D(f.pair.state()['orders'][-1]['qty']),D('.006'))
    def test_cancel_ack_with_unknown_order_never_frees_risk(self):
        f=self.f;s=f.submit_next();f.publish(s,'PARTIALLY_FILLED',qty='.002',time_ms=1001)
        f.paper.lose_cancel=True;a=f.pair.next(context(4000))
        self.assertEqual(f.pair.dispatch(a,f.paper,context(4000)),'UNCERTAIN')
        f.restart();a=f.pair.next(context(4001));self.assertEqual(a['kind'],'QUERY')
        f.pair.dispatch(a,f.paper,context(4001));self.assertEqual(f.paper.count('cancel'),1)
        f.submit_next(4002);self.assertEqual(D(f.pair.state()['orders'][-1]['qty']),D('.004'))
    def test_lost_submit_restart_queries_once_and_not_found_never_resends(self):
        f=self.f;f.paper.lose_submit=True;s=f.submit_next();f.restart()
        a=f.pair.next(context(1001));self.assertEqual(a['kind'],'QUERY')
        f.pair.dispatch(a,f.paper,context(1001));self.assertEqual(f.paper.count(),1)
        with f.pair.tx():
            st=f.pair.state();st['orders'][0]['status']='LOCAL';f.pair.put(st)
        class Empty:
            def lookup(self,o):return None
        for t in (1002,1003):self.assertEqual(f.pair.dispatch(f.pair.next(context(t)),Empty(),context(t)),'UNRESOLVED')
        self.assertEqual(f.paper.count(),1)
    def test_partial_hedge_market_rejected_aborts_then_closes_actual_short_first(self):
        f=self.f;s=f.submit_next();f.publish(s,qty='.006',time_ms=1001)
        h=f.submit_next(1002);f.publish(h,'PARTIALLY_FILLED',qty='.002',time_ms=1003)
        a=f.pair.next(context(4002));f.pair.dispatch(a,f.paper,context(4002))
        market=f.submit_next(4003);f.publish(market,'REJECTED',time_ms=4004)
        self.assertEqual(f.pair.next(context(4005))['kind'],'ABORT_ENTRY')
        close=f.submit_next(4006);o=f.pair.state()['orders'][-1]
        self.assertTrue(o['reduce_only']);self.assertEqual(o['role'],'FUTURE_EXIT');self.assertEqual(D(o['qty']),D('.002'))
        f.publish(close,qty='.002',time_ms=4007);f.submit_next(4008)
        self.assertEqual(f.pair.state()['orders'][-1]['role'],'SPOT_EXIT')
    def test_btc_fee_uses_net_inventory_and_preserves_unsellable_dust(self):
        f=self.f;s=f.submit_next();f.publish(s,qty='.006',fee_btc='.000006',time_ms=1001)
        self.assertEqual(f.pair.next(context(1002))['kind'],'ABORT_ENTRY')
        exit_id=f.submit_next(1003);o=f.pair.state()['orders'][-1]
        self.assertEqual(o['role'],'SPOT_EXIT');self.assertEqual(D(o['qty']),D('.00599'))
        f.publish(exit_id,qty='.00599',time_ms=1004)
        self.assertEqual(f.pair.next(context(1005))['kind'],'RESIDUAL_REVIEW')
        self.assertEqual(D(f.pair.state()['spot_qty']),D('.000004'));self.assertEqual(D(f.pair.state()['future_qty']),0)
    def test_partial_emergency_market_exit_preserves_remainder(self):
        f=self.f;f.open();f.pair.request_exit(emergency=True)
        exit_id=f.submit_next(1006);f.publish(exit_id,'EXPIRED',qty='.002',time_ms=1007)
        self.assertEqual(f.pair.next(context(1008))['kind'],'RESIDUAL_REVIEW')
        self.assertEqual(D(f.pair.state()['future_qty']),D('-.004'));self.assertEqual(D(f.pair.state()['spot_qty']),D('.006'))
        self.assertEqual(f.paper.count(),3)
    def test_cycle_loss_after_operating_charge_halts_and_survives_restart(self):
        f=self.f;f.open();f.pair.operating_cost('server','5');f.restart()
        o=f.submit_next(1006);self.assertEqual(f.pair.state()['orders'][-1]['role'],'FUTURE_EXIT')
        self.assertTrue(f.pair.state()['emergency'])
    def test_stale_quote_can_cancel_cannot_send_new_order(self):
        f=self.f;s=f.submit_next();a=f.pair.next(context(4000,observed_ms=0));self.assertEqual(a['kind'],'CANCEL')
        f.pair.dispatch(a,f.paper,context(4000,observed_ms=0))
        self.assertEqual(f.pair.next(context(4001,observed_ms=0))['kind'],'WAIT_FRESH_QUOTES')
    def test_dispatch_rechecks_entry_price_before_send(self):
        f=self.f;a=f.pair.next(context())
        self.assertEqual(f.pair.dispatch(a,f.paper,context(1001,price='80000')),'ENTRY_REPRICE_REJECTED')
        self.assertEqual(f.paper.count(),0)
    def test_dispatch_rejects_invalid_new_context_without_sending(self):
        f=self.f;a=f.pair.next(context())
        for changes in ({'spot_bid':'-1','spot_ask':'-1'}, {'future_bid':'70000'}, {'mark':'NaN'}, {'now_ms':True}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                f.pair.dispatch(a,f.paper,context(**changes))
        self.assertEqual(f.paper.count(),0)
        self.assertEqual(f.pair.state()['orders'][0]['delivery'],'READY')
    def test_shared_db_claim_prevents_second_send(self):
        f=self.f;a=f.pair.next(context());other=CarryPair(Path(self.tmp.name)/'pair.sqlite')
        try:
            self.assertEqual(f.pair.dispatch(a,f.paper,context()),'OBSERVED')
            self.assertEqual(other.dispatch(a,f.paper,context()),'QUERY_REQUIRED')
        finally:other.close()
        self.assertEqual(f.paper.count(),1)
    def test_funding_unknown_after_spot_causes_unwind_not_naked_wait(self):
        f=self.f;s=f.submit_next();f.publish(s,qty='.006',time_ms=1001)
        self.assertEqual(f.pair.next(context(1002,funding_confirmed=False))['kind'],'ABORT_ENTRY')
        f.submit_next(1003,funding_confirmed=False)
        self.assertEqual(f.pair.state()['orders'][-1]['role'],'SPOT_EXIT')
    def test_initial_futures_margin_cannot_use_spot_gain(self):
        f=self.f;s=f.submit_next();f.publish(s,qty='.006',time_ms=1001)
        a=f.pair.next(context(1002,price='100000'))
        self.assertEqual(a['kind'],'ENTRY_REJECTED');self.assertEqual(a['reason'],'one_times_initial_margin')
        self.assertEqual(f.paper.count(),1)
    def test_dispatch_rechecks_futures_margin(self):
        f=self.f;s=f.submit_next();f.publish(s,qty='.006',time_ms=1001)
        a=f.pair.next(context(1002));self.assertEqual(a['kind'],'SUBMIT')
        self.assertEqual(f.pair.dispatch(a,f.paper,context(1003,price='100000')),'MARGIN_REJECTED')
        self.assertEqual(f.paper.count(),1)
    def test_future_timestamp_fill_is_quarantined(self):
        f=self.f;s=f.submit_next();r=f.paper.publish(s,'FILLED',qty='.006',time_ms=1001)
        r['fills'][0]['time_ms']=1002
        with self.assertRaises(ValueError):f.pair.receive(r)
        self.assertEqual(D(f.pair.state()['spot_qty']),0)
    def test_duplicate_receipt_no_effect_conflict_quarantines(self):
        f=self.f;s=f.submit_next();r=f.publish(s,qty='.006',fee_usdc='.36',time_ms=1001)
        before=f.pair.state();f.pair.receive(r);self.assertEqual(f.pair.state(),before)
        r['fills'][0]['fee_usdc']='.4'
        with self.assertRaises(ValueError):f.pair.receive(r)
        self.assertEqual(D(f.pair.state()['spot_cash']),D('139.64'))
        self.assertEqual(f.pair.next(context(1002))['kind'],'RECONCILIATION_REQUIRED')
    def test_wrong_account_receipt_quarantines_without_applying_fill(self):
        f=self.f;s=f.submit_next();r=f.paper.publish(s,'FILLED',qty='.006',time_ms=1001);r['scope']='other'
        with self.assertRaises(ValueError):f.pair.receive(r)
        self.assertEqual(D(f.pair.state()['spot_qty']),0)
    def test_cumulative_missing_fill_is_not_assumed_executed(self):
        f=self.f;s=f.submit_next();r=f.paper.publish(s,'PARTIALLY_FILLED',qty='.002',time_ms=1001);r['cumulative']='.003'
        with self.assertRaises(ValueError):f.pair.receive(r)
        self.assertEqual(D(f.pair.state()['spot_qty']),0)
    def test_funding_includes_historical_holding_not_flat_receipt_time(self):
        f=self.f;f.open();r=f.pair.funding('f',1003,'60000','.01')
        self.assertEqual(D(r['receipt']),0) # Same timestamp: fill follows settlement.
        with self.assertRaises(ValueError):f.pair.funding('future',10000,'60000','.01')
    def test_no_entry_without_funding_and_clock_regression_persists(self):
        f=self.f;self.assertEqual(f.pair.next(context(funding_confirmed=False))['kind'],'WAIT_FUNDING')
        self.assertEqual(f.pair.next(context(999))['kind'],'RECONCILIATION_REQUIRED')
        f.restart();self.assertEqual(f.pair.next(context(1001))['kind'],'RECONCILIATION_REQUIRED')
    def test_futures_loss_does_not_borrow_spot_profit(self):
        f=self.f;f.open()
        action=f.pair.next(context(1006,price='150000'))
        self.assertEqual(action['kind'],'SUBMIT');self.assertTrue(f.pair.state()['emergency'])
        self.assertEqual(D(f.pair.state()['future_cash']),D('499.91'))
    def test_aborted_unsent_entry_is_canceled_locally(self):
        f=self.f;f.pair.next(context());f.pair.request_exit(emergency=True)
        self.assertEqual(f.pair.next(context(1001))['kind'],'LOCAL_UNSENT_CANCELED')
        self.assertEqual(f.pair.next(context(1002))['kind'],'FLAT_HALTED');self.assertEqual(f.paper.count(),0)
    def test_crash_after_claim_or_after_external_acceptance_never_resends(self):
        for stage in ('claim','accept'):
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as folder:
                code="""import os,sys
from pathlib import Path
from tests.test_carry_pair import PairFixture,context,PaperExchange
f=PairFixture(sys.argv[1]);a=f.pair.next(context())
class Crash(PaperExchange):
 def submit(self,o):
  if sys.argv[2]=='accept':super().submit(o)
  os._exit(73)
f.pair.dispatch(a,Crash(Path(sys.argv[1])/'exchange.sqlite'),context())
"""
                p=subprocess.run([sys.executable,'-c',code,folder,stage],capture_output=True,text=True)
                self.assertEqual(p.returncode,73,p.stderr)
                f=PairFixture(folder)
                try:
                    a=f.pair.next(context(1001));self.assertEqual(a['kind'],'QUERY')
                    result=f.pair.dispatch(a,f.paper,context(1001))
                    self.assertEqual(result,'UNRESOLVED' if stage=='claim' else 'OBSERVED')
                    self.assertEqual(f.paper.count(),0 if stage=='claim' else 1)
                finally:f.close()


if __name__=='__main__':unittest.main()
