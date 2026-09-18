import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from app.research.data.closed_capture_retirement import (
    register_retention_policy,prepare_retirement,retire_raw,replay_retired_capture,load_plan)
from app.research.data.durable_capture_log import JournalError,file_hash,lock_directory
from app.research.data.durable_sealed_pipeline import DurableSealedPipeline
from app.research.data.pipelined_feed_collector import run_bounded
from app.research.data.reserved_feed_storage import ReservedStorageBudget
from app.research.data.sealed_feed_pipeline import PipelineLimits
from tests.test_bounded_feed_collector import ScriptedTransport,load_contract,ROOT


class RetirementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()/'capture'
        self.policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json');self.budgets=[]
    def tearDown(self):
        for b in self.budgets:b.close()
        self.temp.cleanup()
    async def collect(self,*,opt_in=True):
        def factory(budget,**kw):
            if opt_in:register_retention_policy(budget)
            return DurableSealedPipeline(budget,**kw)
        result=await run_bounded(self.root,duration_ns=350_000_000,transport=ScriptedTransport(),policy=self.policy,
            pipeline_limits=PipelineLimits(seal_seconds=.1),_pipeline_factory=factory)
        self.assertEqual(result['stop_reason'],'ORIGINAL_DEADLINE',result['errors'])
        self.work_anchor=result['pipeline']['work_ledger_anchor'];return result
    def budget(self):
        c=json.loads((self.root/'storage.json').read_text())
        b=ReservedStorageBudget.resume(self.root,**{k:v for k,v in c.items() if k!='version'})
        self.budgets.append(b);return b
    async def prepared(self):
        await self.collect();b=self.budget();anchor=prepare_retirement(b,work_anchor=self.work_anchor)
        return b,anchor,load_plan(b,anchor)
    def raw_files(self):return sorted(self.root.glob('epoch-*/*/segment-*.jsonl'))
    def fault_hook(self,wanted):
        def hook(stage):
            if stage==wanted:raise OSError('injected '+stage)
        return hook

    async def test_full_retirement_and_gzip_only_replay(self):
        b,a,p=await self.prepared();before={str(x):file_hash(x) for x in self.root.glob('epoch-*/*-archives/*')}
        result=retire_raw(b,anchor=a)
        self.assertEqual(result['entries'],len(p['entries']));self.assertFalse(self.raw_files())
        proof=replay_retired_capture(b,anchor=a)
        self.assertEqual(proof['fields_each'],17);self.assertEqual(proof['epochs'],1)
        self.assertEqual(before,{str(x):file_hash(x) for x in self.root.glob('epoch-*/*-archives/*')})

    async def test_repeated_retirement_is_idempotent(self):
        b,a,p=await self.prepared();retire_raw(b,anchor=a)
        before={str(x):file_hash(x) for x in self.root.rglob('*') if x.is_file()}
        r=retire_raw(b,anchor=a)
        self.assertEqual(r['logical_raw_bytes_removed_this_call'],0)
        self.assertEqual(before,{str(x):file_hash(x) for x in self.root.rglob('*') if x.is_file()})

    async def test_historical_capture_without_prior_policy_cannot_retire(self):
        await self.collect(opt_in=False);b=self.budget();before=self.raw_files()
        with self.assertRaisesRegex(JournalError,'policy missing'):prepare_retirement(b,work_anchor=self.work_anchor)
        self.assertEqual(before,self.raw_files())
        with self.assertRaisesRegex(JournalError,'precede'):register_retention_policy(b)

    async def test_raw_corruption_rejects_before_any_unlink(self):
        b,a,p=await self.prepared();last=self.root/p['entries'][-1]['source'];last.write_bytes(last.read_bytes()+b' ')
        before=self.raw_files()
        with self.assertRaisesRegex(JournalError,'raw source changed'):retire_raw(b,anchor=a)
        self.assertEqual(before,self.raw_files())

    async def test_corrupt_archive_rejects_without_raw_fallback(self):
        b,a,p=await self.prepared();gz=next(self.root.glob('epoch-*/*-archives/*.gz'));gz.write_bytes(gz.read_bytes()[:-1])
        before=self.raw_files()
        with self.assertRaisesRegex(JournalError,'archive mismatch'):retire_raw(b,anchor=a)
        self.assertEqual(before,self.raw_files())

    async def test_missing_raw_without_intent_rejected(self):
        b,a,p=await self.prepared();(self.root/p['entries'][-1]['source']).unlink();before=self.raw_files()
        with self.assertRaisesRegex(JournalError,'without durable'):retire_raw(b,anchor=a)
        self.assertEqual(before,self.raw_files())

    async def test_changed_plan_anchor_rejected(self):
        b,a,p=await self.prepared()
        with self.assertRaisesRegex(JournalError,'external anchor'):retire_raw(b,anchor={'plan_sha256':'0'*64})

    async def test_changed_replay_proof_rejected(self):
        b,a,p=await self.prepared();(self.root/p['proof']['path']).write_text('{}')
        with self.assertRaisesRegex(JournalError,'proof'):retire_raw(b,anchor=a)

    async def test_journal_checkpoint_change_rejected(self):
        b,a,p=await self.prepared();next(self.root.glob('epoch-*/journal/checkpoint.json')).write_text('{}')
        with self.assertRaisesRegex(JournalError,'metadata changed'):retire_raw(b,anchor=a)

    async def test_active_writer_lock_blocks_retirement(self):
        b,a,p=await self.prepared();lock=lock_directory(self.root/next(iter(p['journals'])))
        try:
            with self.assertRaisesRegex(JournalError,'busy'):retire_raw(b,anchor=a)
        finally:lock.close()

    async def test_pending_reservation_blocks_retirement(self):
        b,a,p=await self.prepared();b.reserve('work',10)
        with self.assertRaisesRegex(JournalError,'active worker'):retire_raw(b,anchor=a)
        b.release('work')

    async def recover_stage(self,stage):
        b,a,p=await self.prepared()
        with self.assertRaises(OSError):retire_raw(b,anchor=a,hook=self.fault_hook(stage))
        b.close();b=self.budget();result=retire_raw(b,anchor=a)
        self.assertFalse(self.raw_files());self.assertEqual(result['entries'],len(p['entries']))
        replay_retired_capture(b,anchor=a)

    async def test_intent_temporary_recovery(self):await self.recover_stage('intent:after_checkpoint_fsync')
    async def test_intent_rename_recovery(self):await self.recover_stage('intent:after_checkpoint_replace')
    async def test_intent_directory_fsync_recovery(self):await self.recover_stage('intent:after_directory_fsync')
    async def test_after_unlink_recovery(self):await self.recover_stage('after_unlink')
    async def test_after_source_directory_fsync_recovery(self):await self.recover_stage('after_source_directory_fsync')
    async def test_done_temporary_recovery(self):await self.recover_stage('done:after_checkpoint_fsync')
    async def test_done_rename_recovery(self):await self.recover_stage('done:after_checkpoint_replace')

    async def test_reappeared_retired_source_is_not_deleted(self):
        b,a,p=await self.prepared();source=self.root/p['entries'][0]['source'];saved=source.read_bytes()
        retire_raw(b,anchor=a);source.write_bytes(saved)
        with self.assertRaisesRegex(JournalError,'reappeared'):retire_raw(b,anchor=a)
        self.assertEqual(source.read_bytes(),saved)

    async def test_unrelated_orphan_is_preserved(self):
        b,a,p=await self.prepared();orphan=self.root/'unrelated.bin';orphan.write_bytes(b'not a source')
        b.reconcile();retire_raw(b,anchor=a);self.assertEqual(orphan.read_bytes(),b'not a source')

    async def test_corruption_after_retirement_cannot_restore_eligibility(self):
        b,a,p=await self.prepared();retire_raw(b,anchor=a)
        gz=next(self.root.glob('epoch-*/*-archives/*.gz'));gz.write_bytes(gz.read_bytes()[:-1])
        with self.assertRaises(JournalError):replay_retired_capture(b,anchor=a)

    async def test_unknown_intent_contents_rejected(self):
        b,a,p=await self.prepared();(self.root/'retirement/intent-0000.json').write_text('{}')
        with self.assertRaisesRegex(JournalError,'receipt binding'):retire_raw(b,anchor=a)
