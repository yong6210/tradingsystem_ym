import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from app.research.data.capture_supervisor_log import CaptureSupervisorLog, reduce_events
from app.research.data.durable_capture_log import JournalError, encoded, file_hash
from app.research.data.restartable_feed_capture import RestartableFeedCapture, boot_identity, clock_sample
from app.research.data.scoped_feed_budget import ScopedFeedBudget
from app.research.data.sealed_feed_pipeline import PipelineLimits
from app.research.data.snapshot_feed_audit import audit_epoch
from tests.incremental_audit_fixture import COMPARABLE
from tests.test_bounded_feed_collector import ScriptedTransport, load_contract, ROOT


class RestartableTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name).resolve()/'run'
        self.policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json')
        self.owners=[]
    def tearDown(self):
        for s in self.owners:
            if not s.running: s.close()
        self.temp.cleanup()
    def create(self,seconds=.45,hook=lambda stage:None):
        s=RestartableFeedCapture.create(self.root,duration_ns=int(seconds*1e9),policy=self.policy,
            pipeline_limits=PipelineLimits(seal_seconds=.1),hook=hook)
        self.owners.append(s);self.initial=s.handle();return s
    def resume(self,handle=None,hook=lambda stage:None):
        s=RestartableFeedCapture.resume(self.root,handle=handle or self.initial,hook=hook)
        self.owners.append(s);return s
    async def interrupt(self,stage,seconds=2.5):
        fired=[]
        def hook(current):
            if current==stage and not fired:
                fired.append(current);raise OSError('injected '+stage)
        s=self.create(seconds,hook)
        with self.assertRaises(Exception): await s.run(ScriptedTransport())
        self.assertEqual(fired,[stage]);s.close();return s

    async def test_normal_full_replay_and_external_receipts_match(self):
        s=self.create();r=await s.run(ScriptedTransport())
        self.assertEqual(r['stop_reason'],'ORIGINAL_DEADLINE');self.assertEqual(r['attempts'],1)
        self.assertEqual(r['storage']['reserved_bytes'],0)
        self.assertTrue(r['results'][0]['pipeline']['closed'])
        baseline=audit_epoch(self.root/'capture-00/epoch-00/journal',self.root/'capture-00/epoch-00/audit',
            **r['original_window'],max_intervals=10000)
        for k in COMPARABLE:self.assertEqual(encoded(baseline[k]),encoded(r['results'][0]['audits'][0][k]),k)
        events=list((self.root/'capture-00/work-ledger').glob('event-*.json'))
        self.assertEqual(s.log.state['attempts'][0]['anchor']['sequence'],len(events)-1)

    async def test_finished_resume_never_opens_network(self):
        s=self.create();r=await s.run(ScriptedTransport());handle=s.handle();s.close()
        transport=ScriptedTransport();resumed=self.resume(handle);again=await resumed.run(transport)
        self.assertEqual(transport.connections,[])
        self.assertEqual({k:v for k,v in r.items() if k!='storage'},{k:v for k,v in again.items() if k!='storage'})
        self.assertEqual(r['storage']['used_bytes'],again['storage']['used_bytes'])

    async def test_interrupted_pipeline_restarts_fresh_without_shrinking_window(self):
        old=await self.interrupt('pipeline:before_audit_receipt')
        s=self.resume();transport=ScriptedTransport();r=await s.run(transport)
        self.assertEqual(r['original_window'],old.scope());self.assertEqual(r['attempts'],2)
        self.assertEqual(r['retries_consumed'],1);self.assertEqual(transport.snapshot_count,1)
        self.assertTrue(r['results'][0]['interrupted']);self.assertFalse(r['live_market_state_restored'])
        self.assertEqual(r['combined']['quality']['status'],'QUALITY_INPUTS_REJECTED')
        left=r['results'][0]['audits'][0];right=r['results'][1]['audits'][0]
        self.assertNotEqual(left['epoch'],right['epoch'])
        lo=left['last_audited_publication_ns'];hi=right['first_audited_publication_ns']
        self.assertGreater(hi-lo,1_000_000_000)
        for spans in r['combined']['intervals'].values():
            self.assertTrue(all(b<=lo or a>=hi for a,b in spans))

    async def test_lost_external_receipt_is_reconstructed(self):
        await self.interrupt('supervisor:RECEIPT:after_checkpoint_replace')
        s=self.resume();r=await s.run(ScriptedTransport())
        self.assertEqual(r['attempts'],2);self.assertTrue(r['results'][0]['interrupted'])

    async def test_first_receipt_temporary_does_not_authorize_old_epoch(self):
        await self.interrupt('supervisor:RECEIPT:after_checkpoint_fsync')
        temps={p:file_hash(p) for p in (self.root/'receipts').glob('*.tmp')}
        s=self.resume();r=await s.run(ScriptedTransport())
        self.assertEqual(r['results'][0]['outcome'],'ABANDONED_BEFORE_RECEIPT')
        self.assertTrue(temps);self.assertTrue(all(file_hash(p)==h for p,h in temps.items()))

    async def test_expired_original_deadline_blocks_network_after_recovery(self):
        await self.interrupt('pipeline:before_unit_admission',seconds=.2)
        await asyncio.sleep(.21)
        s=self.resume();transport=ScriptedTransport();r=await s.run(transport)
        self.assertEqual(r['stop_reason'],'ORIGINAL_DEADLINE');self.assertEqual(r['attempts'],1)
        self.assertEqual(transport.connections,[])
        self.assertEqual(r['empty_audit_attempts'],[0])
        self.assertEqual(r['combined']['quality']['joint_eligible_ns'],0)

    async def test_transport_reconnect_consumes_persisted_retry(self):
        s=self.create(1.7);r=await s.run(ScriptedTransport(disconnect_first=True))
        self.assertEqual(r['attempts'],2);self.assertEqual(r['retries_consumed'],1)
        attempts=s.log.state['attempts']
        self.assertEqual(attempts[1]['wake_ns']-attempts[1]['admitted_ns'],10**9)

    async def test_second_owner_is_rejected(self):
        self.create()
        with self.assertRaisesRegex(JournalError,'busy'):self.resume()

    async def test_boot_change_refuses_resume(self):
        s=self.create();s.close()
        with patch('app.research.data.restartable_feed_capture.boot_identity',return_value={}):
            with self.assertRaisesRegex(JournalError,'boot'):self.resume()

    async def test_wall_clock_jump_refuses_resume(self):
        s=self.create();s.close();sample=clock_sample();sample['wall_ns']+=200_000_000
        with patch('app.research.data.restartable_feed_capture.clock_sample',return_value=sample):
            with self.assertRaisesRegex(JournalError,'drift'):self.resume()

    async def test_monotonic_regression_refuses_resume(self):
        s=self.create();s.close();sample=dict(s.plan['clock_sample']);sample['monotonic_ns']-=1
        with patch('app.research.data.restartable_feed_capture.clock_sample',return_value=sample):
            with self.assertRaisesRegex(JournalError,'regression'):self.resume()

    async def test_changed_sources_refuse_resume(self):
        s=self.create();s.close()
        with patch('app.research.data.restartable_feed_capture.source_hashes',return_value={}):
            with self.assertRaisesRegex(JournalError,'implementation'):self.resume()

    async def test_corrupt_acknowledged_result_refuses_resume(self):
        s=self.create();await s.run(ScriptedTransport());s.close()
        next(self.root.glob('result-*.json')).write_text('{}')
        with self.assertRaisesRegex(JournalError,'result'):self.resume()

    async def test_removed_latest_supervisor_event_detected_by_handle(self):
        s=self.create();await s.run(ScriptedTransport());handle=s.handle();s.close()
        sorted((self.root/'receipts').glob('event-*.json'))[-1].unlink()
        with self.assertRaisesRegex(JournalError,'rollback'):self.resume(handle)

    async def test_event_middle_gap_rejected(self):
        s=self.create();await s.run(ScriptedTransport());s.close()
        sorted((self.root/'receipts').glob('event-*.json'))[2].unlink()
        with self.assertRaisesRegex(JournalError,'gap'):self.resume()

    async def test_cancel_releases_capture_locks_and_shared_reservations(self):
        s=self.create(2.5);task=asyncio.create_task(s.run(ScriptedTransport()))
        await asyncio.sleep(.2);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(s.budget.snapshot()['reserved_bytes'],0);s.close()
        resumed=self.resume();r=await resumed.run(ScriptedTransport())
        self.assertEqual(r['attempts'],2)

    async def test_scopes_share_reservation_pool_and_failure_latch(self):
        s=self.create();a=self.root/'a';b=self.root/'b';a.mkdir();b.mkdir()
        x=ScopedFeedBudget(s.budget,a);y=ScopedFeedBudget(s.budget,b)
        x.reserve('a',1024);y.reserve('b',1024)
        self.assertEqual(s.budget.snapshot()['reserved_bytes'],2048)
        with self.assertRaises(JournalError):y.reserve('c',1024)
        self.assertTrue(x.failed);x.release('a');y.release('b')
        self.assertEqual(s.budget.snapshot()['reserved_bytes'],0)

    async def test_namespace_refuses_sibling_write(self):
        s=self.create();path=self.root/'a';path.mkdir();view=ScopedFeedBudget(s.budget,path)
        with self.assertRaisesRegex(JournalError,'namespace'):view.atomic_json(self.root/'outside.json',{})
        self.assertFalse((self.root/'outside.json').exists())

    async def test_total_duration_limit(self):
        with self.assertRaisesRegex(JournalError,'120 seconds'):self.create(121)

    async def test_unacknowledged_result_is_preserved(self):
        await self.interrupt('after_result_before_end',seconds=.3)
        old={p:file_hash(p) for p in self.root.glob('result-*.json')}
        s=self.resume();r=await s.run(ScriptedTransport())
        self.assertTrue(old);self.assertTrue(all(file_hash(p)==h for p,h in old.items()))
        self.assertTrue(r['results'][0]['interrupted'])


class SupervisorStateTests(unittest.TestCase):
    def test_retry_budget_is_global_and_not_replenished(self):
        events=[dict(kind='INIT',payload=dict(retry_delays_seconds=[1,2],window_end_ns=100*10**9))]
        for i in range(3):
            events.append(dict(kind='ATTEMPT',payload=dict(index=i,admitted_ns=i*10**9,wake_ns=(i+(0 if i==0 else i))*10**9)))
            events.append(dict(kind='END',payload=dict(index=i,outcome='PROCESS_INTERRUPTED',
                result_file=f'result-{i:02d}-'+('a'*32)+'.json',result_sha256='a'*64)))
        self.assertEqual(len(reduce_events(events)['attempts']),3)
        events.append(dict(kind='ATTEMPT',payload=dict(index=3,admitted_ns=7*10**9,wake_ns=8*10**9)))
        with self.assertRaisesRegex(JournalError,'budget'):reduce_events(events)

    def test_duplicate_receipt_rejected(self):
        e=[dict(kind='INIT',payload=dict(retry_delays_seconds=[1],window_end_ns=10**9)),
           dict(kind='ATTEMPT',payload=dict(index=0,admitted_ns=0,wake_ns=0)),
           dict(kind='RECEIPT',payload=dict(index=0,anchor=dict(sequence=0,event_sha256='a'*64)))]
        with self.assertRaisesRegex(JournalError,'receipt'):reduce_events(e+[e[-1]])
