import asyncio
from fractions import Fraction
import json
import tempfile
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from app.research.data import bounded_feed_collector_v2 as collector
from app.research.data.bounded_feed_collector import DurableJsonl, RetryableTransportError
from app.research.data.feed_runtime_diagnostics import GuardedFeedEpoch, PhaseStats, SynchronousStallError, capacity_projection
from tests import test_bounded_feed_collector as legacy


class PhaseTests(unittest.TestCase):
    def test_fixed_histogram_and_bounded_slow_samples(self):
        stats=PhaseStats()
        for i in range(1000):
            stats.record('raw_append',i,50_000_000,5_000_000,False)
        summary=stats.summary()
        row=summary['phases']['raw_append']
        self.assertEqual(sum(row['histogram']),1000)
        self.assertEqual(row['wall_ns'],50_000_000_000)
        self.assertEqual(len(summary['last_slow_samples']),16)
        self.assertEqual(summary['last_slow_samples'][0]['start_ns'],984)

    def test_unknown_phase_cannot_grow_dictionary(self):
        stats=PhaseStats()
        with self.assertRaises(ValueError):
            stats.record('user-controlled-1000',1,1,1,False)
        self.assertEqual(stats.phases,{})

    def test_stall_detected_when_synchronous_call_returns(self):
        stats=PhaseStats(max_block_ns=1_000_000)
        with self.assertRaises(SynchronousStallError):
            with stats.measure('audit_write_and_sync'):
                time.sleep(.005)
        self.assertEqual(stats.phases['audit_write_and_sync']['failures'],1)

    def test_real_error_is_not_masked_by_latency_guard(self):
        stats=PhaseStats(max_block_ns=1)
        with self.assertRaisesRegex(OSError,'disk-full'):
            with stats.measure('raw_append'):
                raise OSError('disk-full')


class ProjectionTests(unittest.TestCase):
    def projection(self,**kwargs):
        return capacity_projection(**(dict(raw_bytes=1_873_498,audit_bytes=126_393,
            calendar_ns=12_000_000_000,free_bytes=32*1024**3)|kwargs))

    def test_archive_rate_audit_limit_matches_exact_fraction(self):
        result=self.projection()
        expected=Fraction(32*1024**2*12_000_000_000,126_393)
        self.assertEqual(result['single_audit_cap_ns_at_observed_rate'],expected.numerator//expected.denominator)
        self.assertTrue(result['scenarios'][0]['single_audit_cap_exceeded'])
        self.assertFalse(result['full_day_ready'])

    def test_physical_space_and_policy_budget_are_separate(self):
        result=self.projection()
        self.assertFalse(result['scenarios'][0]['raw_budget_exceeded'])
        self.assertTrue(result['scenarios'][1]['free_above_reserve_exceeded'])
        self.assertFalse(result['scenarios'][1]['raw_budget_exceeded'])

    def test_zero_traffic_does_not_invent_audit_capacity_time(self):
        result=self.projection(raw_bytes=0,audit_bytes=0,free_bytes=1)
        self.assertIsNone(result['single_audit_cap_ns_at_observed_rate'])
        self.assertEqual(result['available_above_reserve_bytes'],0)
        self.assertFalse(result['full_day_ready'])

    def test_rounding_up_does_not_drop_fractional_byte_demand(self):
        result=self.projection(raw_bytes=1,audit_bytes=1,calendar_ns=86_400_000_000_001)
        self.assertEqual(result['scenarios'][0]['raw_day_bytes'],1)

    def test_zero_denominator_and_boolean_counts_refused(self):
        for kwargs in (dict(calendar_ns=0),dict(raw_bytes=True),dict(audit_bytes=-1)):
            with self.assertRaises(RuntimeError):
                self.projection(**kwargs)


class GuardedCollectorTests(legacy.CollectorIntegrationTests):
    """Run the existing 15 integration contracts against the new backend too."""
    async def run_case(self,transport,duration=200_000_000,**kwargs):
        return await collector.run_bounded(self.output,duration_ns=duration,
            transport=transport,policy=self.policy,**kwargs)

    async def test_slow_audit_failure_cannot_count_a_successful_observation(self):
        original=DurableJsonl.append
        def delay(writer,value):
            if writer.path.name=='batches.jsonl' and value['last_sequence']>2:
                time.sleep(.55)
            return original(writer,value)
        with patch.object(DurableJsonl,'append',delay):
            result=await self.run_case(legacy.ScriptedTransport(),duration=1_000_000_000)
        self.assertEqual(result['stop_reason'],'FATAL_FAILURE')
        epoch=result['epochs'][0]
        self.assertEqual(epoch['last_audited_sequence'],2)
        self.assertEqual(epoch['eligible_point_observations'],0)
        self.assertGreater(epoch['diagnostics']['phases']['audit_write_and_sync']['max_wall_ns'],500_000_000)

    async def test_failure_drain_yields_to_close_and_tracks_unpersisted_receive_time(self):
        transport=legacy.ScriptedTransport()
        original_append=DurableJsonl.append
        class BurstAfterFailure(legacy.ScriptedSocket):
            async def recv(self):
                if failing[0] and not self.closed.is_set():
                    return json.dumps(dict(stream='btcusdc@markPrice@1s',data=legacy.mark()))
                return await super().recv()
            async def close(self):
                # Frames can continue while a close handshake is in progress.
                await asyncio.sleep(.05)
                self.closed.set()
        async def connect(channel,url,timeout,*,deadline_ns):
            socket=BurstAfterFailure(channel)
            transport.sockets.append(socket)
            return socket
        transport.connect=connect
        failing=[False]
        def fail(writer,value):
            if writer.path.name=='batches.jsonl' and value['last_sequence']>2:
                failing[0]=True
                raise OSError('storage unavailable')
            return original_append(writer,value)
        with patch.object(DurableJsonl,'append',fail):
            result=await asyncio.wait_for(self.run_case(transport),timeout=2)
        self.assertEqual(result['stop_reason'],'FATAL_FAILURE')
        self.assertTrue(all(socket.closed.is_set() for socket in transport.sockets))
        self.assertGreater(result['epochs'][0]['discarded_frames_after_storage_failure'],0)
        self.assertGreaterEqual(result['latest_received_utc_ns'],max(
            row['payload']['received_utc_ns'] for row in self.raw()))

    async def test_combined_raw_and_audit_block_cannot_pass_individual_limits(self):
        from app.research.data.durable_capture_log import DurableCaptureLog
        commit,audit=DurableCaptureLog.commit,DurableJsonl.append
        def delayed_commit(writer):
            if writer.sequence>2:
                time.sleep(.3)
            return commit(writer)
        def delayed_audit(writer,value):
            if writer.path.name=='batches.jsonl' and value['last_sequence']>2:
                time.sleep(.3)
            return audit(writer,value)
        with patch.object(DurableCaptureLog,'commit',delayed_commit),patch.object(DurableJsonl,'append',delayed_audit):
            result=await self.run_case(legacy.ScriptedTransport(),duration=1_000_000_000)
        epoch=result['epochs'][0]
        self.assertEqual(result['stop_reason'],'FATAL_FAILURE')
        self.assertIn('flush_total',epoch['reason'])
        self.assertEqual(epoch['last_audited_sequence'],2)

    async def test_commit_interval_is_checked_after_commit_as_well_as_before(self):
        start=time.monotonic_ns()
        epoch=GuardedFeedEpoch(Path(self.temp.name)/'epoch',
            dict(run_id='synthetic-clock',window_start_ns=start,window_end_ns=start+10_000_000_000),
            self.policy['storage'],raw_bytes_remaining=100_000)
        try:
            epoch.watchdog(time.monotonic_ns())
            original_now,original_commit=time.monotonic_ns,epoch.journal.commit
            offset=[850_000_000]
            def late_commit():
                offset[0]+=300_000_000
                return original_commit()
            with patch('app.research.data.feed_runtime_diagnostics.time.monotonic_ns',side_effect=lambda:original_now()+offset[0]),\
                    patch.object(epoch.journal,'commit',side_effect=late_commit),\
                    patch.object(epoch.bridge,'monotonic',side_effect=lambda:original_now()+offset[0]):
                with self.assertRaisesRegex(SynchronousStallError,'commit interval exceeded during storage'):
                    epoch.flush()
            self.assertEqual(epoch.last_audited_sequence,2)
        finally:
            epoch.close()


if __name__=='__main__':
    unittest.main()
