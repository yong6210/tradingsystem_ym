import asyncio
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.research.data.durable_capture_log import JournalError,decoded,encoded,file_hash
from app.research.data.queued_feed_fixture import QueuedTransport
from app.research.data.rolling_capture_log import reduce_events
from app.research.data.rolling_retained_capture import RollingRetainedCapture,validate_rotation
from app.research.data.sealed_feed_pipeline import PipelineLimits
from tests.test_bounded_feed_collector import ScriptedTransport,load_contract,ROOT
from tests.test_retained_feed_collector import inventory,cold_replay
from tests.incremental_audit_fixture import COMPARABLE


class RotationContractTests(unittest.TestCase):
    def test_preflight_accounts_for_final_seal_and_manifest(self):
        r=validate_rotation(120_000_000_000,10_000_000_000,PipelineLimits(seal_seconds=.5))
        self.assertEqual(r['max_planned_shards'],12)
        self.assertEqual(r['conservative_units_per_shard'],22)
        self.assertFalse(r['adaptive_cadence'])

    def test_rejects_unqualified_fast_sealing(self):
        with self.assertRaisesRegex(JournalError,'cadence'):
            validate_rotation(10**9,10**9,PipelineLimits(seal_seconds=.1))

    def test_rejects_per_shard_overflow_instead_of_raising_limit(self):
        with self.assertRaisesRegex(JournalError,'work budget'):
            validate_rotation(10*10**9,10*10**9,PipelineLimits(seal_seconds=.5,max_units=10))

    def test_rejects_longer_or_excessive_shards(self):
        for duration,rotation in ((121,10),(120,1),(2,0),(2,31)):
            with self.assertRaises((JournalError,ValueError)):
                validate_rotation(duration*10**9,rotation*10**9,PipelineLimits(seal_seconds=.5))


class RollingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()/'run'
        self.policy=load_contract(ROOT/'configs/research/forward_data_policy_v1.json');self.owners=[]

    def tearDown(self):
        for owner in self.owners:
            if not owner.running:owner.close()
        self.temp.cleanup()

    def create(self,seconds=2.5,hook=lambda stage:None):
        owner=RollingRetainedCapture.create(self.root,duration_ns=int(seconds*1e9),rotation_ns=10**9,
            policy=self.policy,hook=hook);self.owners.append(owner);self.initial=owner.handle();return owner

    def resume(self,handle=None):
        owner=RollingRetainedCapture.resume(self.root,handle=handle or self.initial);self.owners.append(owner);return owner

    async def interrupted(self,stage):
        fired=[]
        def hook(current):
            if current==stage and not fired:fired.append(current);raise OSError('injected '+stage)
        owner=self.create(hook=hook)
        with self.assertRaises(Exception):await owner.run(QueuedTransport(per_tick=20))
        self.assertEqual(fired,[stage]);owner.close();return owner

    async def test_rollover_reinitializes_metadata_and_preserves_calendar_gaps(self):
        owner=self.create();transport=QueuedTransport(per_tick=20);result=await owner.run(transport)
        self.assertEqual(result['stop_reason'],'ORIGINAL_DEADLINE')
        self.assertGreaterEqual(result['shards'],2)
        self.assertEqual(transport.snapshots,result['shards'])
        self.assertEqual(len(transport.connections),2*result['shards'])
        self.assertLessEqual(result['max_units_in_one_shard'],4)
        self.assertEqual(result['storage']['reserved_bytes'],0)
        previous=None;identities=[]
        for row in result['results']:
            self.assertTrue(row['pipeline']['closed']);self.assertTrue(row['pipeline']['work_ledger_complete'])
            self.assertEqual(row['pipeline']['units'][0]['index'],0)
            summary,=row['audits'];identities.append(summary['epoch'])
            cold,=cold_replay(owner.shard_root(row['index']))
            for field in COMPARABLE:self.assertEqual(encoded(summary[field]),encoded(cold[field]),field)
            for field in ('window_start_ns','window_end_ns','clock_domain'):
                self.assertEqual(summary[field],result['original_window'][field])
            if previous is not None:
                left=previous['last_audited_publication_ns'];right=summary['first_audited_publication_ns']
                self.assertGreater(right,left)
                for spans in result['combined']['intervals'].values():
                    self.assertTrue(all(b<=left or a>=right for a,b in spans))
            previous=summary
        self.assertEqual(len(identities),len(set(identities)))
        self.assertTrue(all(s.summary()['producer_thread_joined'] for s in transport.sockets))

    async def test_completed_resume_is_read_only_and_opens_no_connections(self):
        owner=self.create(1.5);result=await owner.run(ScriptedTransport());handle=owner.handle();owner.close()
        before=inventory(self.root);resumed=self.resume(handle);transport=ScriptedTransport()
        again=await resumed.run(transport)
        self.assertEqual(transport.connections,[]);self.assertEqual(before,inventory(self.root))
        self.assertEqual(result['combined'],again['combined'])

    async def test_interrupted_retirement_recovers_without_new_live_session(self):
        old=await self.interrupted('pipeline:custody_after_unlink')
        owner=self.resume();transport=ScriptedTransport();result=await owner.run(transport)
        self.assertEqual(transport.connections,[])
        self.assertEqual(result['stop_reason'],'PROCESS_INTERRUPTED')
        self.assertEqual(result['original_window'],old.scope())
        self.assertEqual(result['combined']['quality']['status'],'QUALITY_INPUTS_REJECTED')
        self.assertGreater(result['results'][0]['recovery']['gzip_source_reads'],0)
        self.assertFalse(result['live_market_state_restored'])

    async def test_begin_ack_loss_preserves_empty_attempt(self):
        await self.interrupted('rolling:BEGIN:after_checkpoint_replace')
        transport=ScriptedTransport();result=await self.resume().run(transport)
        self.assertEqual(transport.connections,[])
        self.assertEqual(result['results'][0]['outcome'],'ABANDONED_BEFORE_READY')

    async def test_ready_rename_loss_does_not_create_late_epoch(self):
        await self.interrupted('rolling:READY:after_checkpoint_replace')
        transport=ScriptedTransport();result=await self.resume().run(transport)
        self.assertEqual(transport.connections,[]);self.assertEqual(result['stop_reason'],'PROCESS_INTERRUPTED')
        self.assertEqual(result['results'][0]['audits'],[])

    async def test_result_without_end_not_adopted_and_preserved(self):
        await self.interrupted('rolling:result_before_end')
        orphan={p:p.read_bytes() for p in self.root.glob('result-*.json')}
        result=await self.resume().run(ScriptedTransport())
        self.assertEqual(result['stop_reason'],'PROCESS_INTERRUPTED')
        self.assertTrue(all(p.read_bytes()==v for p,v in orphan.items()))
        self.assertEqual(len(list(self.root.glob('result-*.json'))),len(orphan)+1)

    async def test_end_rename_loss_validates_previous_before_next_shard(self):
        await self.interrupted('rolling:END:after_checkpoint_replace')
        owner=self.resume();transport=ScriptedTransport();result=await owner.run(transport)
        self.assertEqual(result['stop_reason'],'ORIGINAL_DEADLINE')
        self.assertGreaterEqual(result['shards'],2)
        self.assertEqual(result['results'][0]['outcome'],'PLANNED_ROLLOVER')

    async def test_corrupt_completed_gzip_blocks_new_network(self):
        await self.interrupted('rolling:END:acknowledged')
        path=next(self.root.glob('shard-*/*/raw-archives/*.gz'));path.write_bytes(path.read_bytes()[:-1])
        owner=self.resume();transport=ScriptedTransport()
        with self.assertRaises(JournalError):await owner.run(transport)
        self.assertEqual(transport.connections,[])

    async def test_manifest_rollback_detected_by_latest_handle(self):
        owner=self.create(.3);await owner.run(ScriptedTransport());handle=owner.handle();owner.close()
        sorted((self.root/'rolling-log').glob('event-*.json'))[-1].unlink()
        with self.assertRaisesRegex(JournalError,'rollback'):self.resume(handle)

    async def test_result_corruption_detected_before_network(self):
        owner=self.create(.3);await owner.run(ScriptedTransport());handle=owner.handle();owner.close()
        next(self.root.glob('result-*.json')).write_text('{}')
        transport=ScriptedTransport()
        with self.assertRaisesRegex(JournalError,'result'):await self.resume(handle).run(transport)
        self.assertEqual(transport.connections,[])

    async def test_changed_boot_and_sources_are_rejected(self):
        owner=self.create();owner.close()
        with patch('app.research.data.restartable_feed_capture.boot_identity',return_value={}):
            with self.assertRaisesRegex(JournalError,'boot'):self.resume()
        with patch('app.research.data.rolling_retained_capture.source_hashes',return_value={}):
            with self.assertRaisesRegex(JournalError,'implementation'):self.resume()

    async def test_cancel_releases_shared_reservations_and_locks(self):
        owner=self.create();task=asyncio.create_task(owner.run(ScriptedTransport()))
        await asyncio.sleep(.2);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(owner.budget.snapshot()['reserved_bytes'],0);owner.close()
        result=await self.resume().run(ScriptedTransport());self.assertEqual(result['stop_reason'],'PROCESS_INTERRUPTED')

    async def test_transport_error_is_terminal_and_does_not_reset_retry_budget(self):
        owner=self.create();transport=ScriptedTransport(disconnect_first=True);result=await owner.run(transport)
        self.assertEqual(result['stop_reason'],'TRANSPORT_FAILURE');self.assertEqual(result['shards'],1)
        self.assertEqual(transport.snapshot_count,1)

    async def test_rejected_plan_creates_no_files(self):
        with self.assertRaisesRegex(JournalError,'cadence'):
            RollingRetainedCapture.create(self.root,duration_ns=10**9,policy=self.policy,
                pipeline_limits=PipelineLimits(seal_seconds=.1))
        self.assertFalse(self.root.exists())

    async def test_all_namespaces_and_results_share_one_measured_budget(self):
        owner=self.create(1.8);result=await owner.run(QueuedTransport(per_tick=20))
        files=inventory(self.root)
        self.assertEqual(result['storage']['used_bytes'],sum(value[0] for value in files.values()))
        for root in self.root.glob('shard-*'):
            self.assertEqual(decoded((root/'storage.json').read_bytes()),owner.budget.contract)
        self.assertGreater(result['total_units'],result['max_units_in_one_shard'])

    async def test_retired_sources_remain_reported_after_interrupted_recovery(self):
        await self.interrupted('pipeline:custody_after_unlink')
        result=await self.resume().run(ScriptedTransport())
        self.assertTrue(result['original_deletion'])
        self.assertGreater(result['total_units'],0)

    async def test_expired_deadline_between_shards_opens_no_new_connections(self):
        await self.interrupted('rolling:END:acknowledged')
        await asyncio.sleep(1.6)
        transport=ScriptedTransport();result=await self.resume().run(transport)
        self.assertEqual(transport.connections,[])
        self.assertEqual(result['stop_reason'],'ORIGINAL_DEADLINE')
        self.assertEqual(result['shards'],1)
