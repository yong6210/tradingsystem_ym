"""SQLite transactions and real process-exit fault injection; no real orders."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal as D
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from app.research.execution.market_fallback import State,Snapshot
from app.research.execution.durable_fallback import Journal,Receipt,dispatch_once


class FakeExchange:
    """Durable fake acceptance, independent of the application's journal."""
    def __init__(self,path,lose_response=False):
        self.path=Path(path)
        self.lose_response=lose_response

    def read(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {'submits':0,'orders':{}}

    def submit(self,command):
        saved=self.read();saved['submits']+=1
        quantity=command.action.quantity if command.action.kind=='MARKET_INTENT' else D(saved.get('cancel_fill','0'))
        status='FILLED' if command.action.kind=='MARKET_INTENT' else 'CANCELED'
        row=dict(command_id=command.command_id,original_id=command.original_id,status=status,executed=str(quantity),sequence=1)
        saved['orders'][command.command_id]=row
        with self.path.open('w') as f:
            json.dump(saved,f);f.flush();os.fsync(f.fileno())
        if self.lose_response:raise TimeoutError('accepted but response lost')
        return Receipt(**(row|{'executed':D(row['executed'])}))

    def lookup(self,command):
        row=self.read()['orders'].get(command.command_id)
        return Receipt(**(row|{'executed':D(row['executed'])})) if row else None


class DurableFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'journal.sqlite'
        self.exchange=FakeExchange(Path(self.tmp.name)/'fake_exchange.json')
        self.journal=Journal(self.path)
        self.state=State('original-1',D('.003'),1,'entry',3000)
        self.journal.register(self.state)
        self.context=dict(now_ms=3000,signal_valid=True,approved_market_qty=D('.003'),position_qty=D('0'),context_observed_ms=3000)

    def tearDown(self):
        self.journal.close();self.tmp.cleanup()

    def advance(self,status='CANCELED',fill='.001',**kw):
        return self.journal.advance(Snapshot('original-1',status,D(fill),3000),**self.context,**kw)

    def queue(self):
        self.advance()
        return self.journal.commands()[-1].command_id

    def reopen(self):
        self.journal.close();self.journal=Journal(self.path)

    def test_state_and_outbox_rollback_together(self):
        def fail(_):raise RuntimeError('power loss before commit')
        with self.assertRaises(RuntimeError):self.advance(fault=fail)
        self.reopen()
        self.assertEqual(self.journal.state('original-1').phase,'LIMIT_PENDING')
        self.assertEqual(self.journal.commands(),[])
        self.queue();self.assertEqual(len(self.journal.commands()),1)

    def test_restart_before_claim_sends_one_and_finishes(self):
        key=self.queue();self.reopen()
        self.assertEqual(dispatch_once(self.journal,key,self.exchange,lambda _:True),'TERMINAL')
        self.reopen()
        self.assertEqual(dispatch_once(self.journal,key,self.exchange,lambda _:True),'TERMINAL')
        self.assertEqual(self.exchange.read()['submits'],1)
        self.assertEqual(self.journal.filled_quantity(key),D('.002'))
        self.assertEqual(self.journal.state('original-1').phase,'DONE')

    def test_accepted_timeout_queries_without_resubmit(self):
        key=self.queue();self.exchange.lose_response=True
        self.assertEqual(dispatch_once(self.journal,key,self.exchange,lambda _:True),'UNCERTAIN')
        self.reopen()
        self.assertEqual(dispatch_once(self.journal,key,self.exchange,lambda _:True),'TERMINAL')
        self.assertEqual(self.exchange.read()['submits'],1)

    def test_process_death_after_claim_is_unresolved_not_resubmitted(self):
        key=self.queue()
        self.child_crash(key,'after_claim_before_send')
        self.reopen()
        self.assertEqual(self.journal.command(key).delivery,'SENDING')
        self.assertEqual(dispatch_once(self.journal,key,self.exchange,lambda _:True),'UNRESOLVED_NOT_FOUND')
        self.assertEqual(self.exchange.read()['submits'],0)
        self.assertEqual(self.journal.command(key).delivery,'SENDING')

    def test_process_death_after_acceptance_recovers_from_query(self):
        key=self.queue()
        self.child_crash(key,'after_send_before_receipt_commit')
        self.reopen()
        self.assertEqual(self.exchange.read()['submits'],1)
        self.assertEqual(self.journal.command(key).delivery,'SENDING')
        self.assertEqual(dispatch_once(self.journal,key,self.exchange,lambda _:True),'TERMINAL')
        self.assertEqual(self.exchange.read()['submits'],1)
        self.assertEqual(self.journal.filled_quantity(key),D('.002'))

    def child_crash(self,key,stage):
        code='''
import os,sys
from tests.test_durable_fallback import FakeExchange
from app.research.execution.durable_fallback import Journal,dispatch_once
j=Journal(sys.argv[1]);x=FakeExchange(sys.argv[2])
def crash(stage):
    if stage==sys.argv[4]:os._exit(77)
dispatch_once(j,sys.argv[3],x,lambda _:True,crash)
'''
        result=subprocess.run([sys.executable,'-c',code,str(self.path),str(self.exchange.path),key,stage],capture_output=True,text=True)
        self.assertEqual(result.returncode,77,result.stderr)

    def test_only_one_concurrent_claim(self):
        key=self.queue()
        def claim(_):
            j=Journal(self.path)
            try:return j.claim(key)
            finally:j.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(claim,range(2))),[False,True])

    def test_stale_risk_at_dispatch_blocks_without_send(self):
        key=self.queue()
        self.assertEqual(dispatch_once(self.journal,key,self.exchange,lambda _:False),'BLOCKED')
        self.assertEqual(self.exchange.read()['submits'],0)
        self.reopen()
        self.assertEqual(dispatch_once(self.journal,key,self.exchange,lambda _:True),'BLOCKED')

    def test_fill_deltas_dedup_and_monotonicity(self):
        key=self.queue();self.journal.claim(key)
        first=Receipt(key,'original-1','PARTIALLY_FILLED',D('.001'),1)
        self.journal.receipt(first);self.journal.receipt(first)
        self.assertEqual(self.journal.filled_quantity(key),D('.001'))
        self.journal.receipt(replace(first,status='FILLED',executed=D('.002'),sequence=2))
        self.journal.receipt(first)
        self.assertEqual(self.journal.filled_quantity(key),D('.002'))
        with self.assertRaises(ValueError):self.journal.receipt(replace(first,sequence=3))
        with self.assertRaises(ValueError):self.journal.receipt(replace(first,status='FILLED',executed=D('.003'),sequence=4))

    def test_partial_terminal_does_not_create_another_market_order(self):
        key=self.queue();self.journal.claim(key)
        self.journal.receipt(Receipt(key,'original-1','EXPIRED',D('.001'),1))
        self.assertEqual(self.advance().kind,'RECONCILE_MARKET')
        self.assertEqual(len(self.journal.commands()),1)
        self.assertEqual(dispatch_once(self.journal,key,self.exchange,lambda _:True),'TERMINAL_REMAINDER_REQUIRES_REVIEW')
        self.assertEqual(self.journal.state('original-1').phase,'MARKET_PLANNED')

    def test_original_fill_regression_or_terminal_change_rejected(self):
        self.advance('PARTIALLY_FILLED','.001')
        with self.assertRaises(ValueError):self.advance('PARTIALLY_FILLED','0')
        self.advance('CANCELED','.002')
        with self.assertRaises(ValueError):self.advance('FILLED','.003')
        self.assertEqual(self.journal.commands()[-1].action.quantity,D('.001'))

    def test_duplicate_registration_and_planning(self):
        self.journal.register(self.state)
        self.queue();self.journal.register(self.state)
        self.assertEqual(self.advance().kind,'RECONCILE_MARKET')
        self.assertEqual(len(self.journal.commands()),1)
        with self.assertRaises(ValueError):self.journal.register(replace(self.state,quantity=D('.004')))

    def test_future_snapshot_does_not_poison_record(self):
        self.assertEqual(self.journal.advance(Snapshot('original-1','NEW',D('0'),9999),**self.context).kind,'QUERY_ORIGINAL')
        self.assertEqual(self.advance().kind,'MARKET_INTENT')

    def test_receipt_identity_and_duplicate_conflict_rejected(self):
        key=self.queue();self.journal.claim(key)
        r=Receipt(key,'wrong','NEW',D('0'),0)
        with self.assertRaises(ValueError):self.journal.receipt(r)
        r=replace(r,original_id='original-1');self.journal.receipt(r)
        with self.assertRaises(ValueError):self.journal.receipt(replace(r,status='PARTIALLY_FILLED',executed=D('.001')))

    def test_cancel_command_also_persisted(self):
        self.advance('PARTIALLY_FILLED','.001')
        key=self.journal.commands()[0].command_id
        self.assertEqual(self.journal.commands()[0].action.kind,'CANCEL_ORIGINAL')
        self.assertEqual(dispatch_once(self.journal,key,self.exchange,lambda _:True),'TERMINAL')
        self.assertEqual(self.journal.state('original-1').phase,'CANCEL_REQUESTED')
        # Dispatch receipts do not replace authoritative original reconciliation.
        self.assertEqual(self.advance('CANCELED','.002').quantity,D('.001'))


    def test_cancel_race_timeout_restart_total_fill_never_exceeds_target(self):
        self.exchange.path.write_text(json.dumps({'submits':0,'orders':{},'cancel_fill':'.002'}))
        self.advance('PARTIALLY_FILLED','.001')
        cancel=self.journal.commands()[0].command_id
        dispatch_once(self.journal,cancel,self.exchange,lambda _:True)
        acknowledged=self.exchange.lookup(self.journal.command(cancel))
        self.assertEqual(acknowledged.executed,D('.002'))
        action=self.advance('CANCELED',str(acknowledged.executed))
        self.assertEqual(action.quantity,D('.001'))
        key=self.journal.commands()[-1].command_id
        self.exchange.lose_response=True
        dispatch_once(self.journal,key,self.exchange,lambda _:True)
        self.reopen()
        self.assertEqual(dispatch_once(self.journal,key,self.exchange,lambda _:True),'TERMINAL')
        self.assertEqual(acknowledged.executed+self.journal.filled_quantity(key),D('.003'))
        self.assertEqual(self.exchange.read()['submits'],2)


if __name__=='__main__':unittest.main()
