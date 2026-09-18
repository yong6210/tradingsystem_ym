"""Coordinator decisions with a modeled clock, real storage/epochs/replay.

No transport requests or wall-clock sleeps. The 60s namespace is a modeled
window, not a 60s capture. Epoch recording uses its actual monotonic clock;
only coordinator retry decisions and sleep completion are controlled.
"""
import asyncio
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.research.data import segmented_feed_collector as collector
from app.research.data.durable_capture_log import file_hash, lock_directory
from tests.test_bounded_feed_collector import load_contract, ROOT


class FixedReconnectAccountingTests(unittest.IsolatedAsyncioTestCase):
    async def case(self, mode):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()/'capture'
            start = time.monotonic_ns(); end = start+60*10**9
            clock = [start]
            created, budgets, persisted, sleeps = [], [], {}, []
            original = collector.SegmentedFeedEpoch
            def construct(*args, **kwargs):
                # The synthetic coordinator clock must not rewrite real raw times.
                with patch.object(collector, 'time', time):
                    epoch = original(*args, **kwargs)
                created.append(kwargs['budget'].used)
                budgets.append(kwargs['budget'])
                if len(created) == 2:
                    self.assertTrue(all(p.is_file() and file_hash(p)==digest for p,digest in persisted.items()))
                return epoch
            async def collect(epoch, transport, **kwargs):
                outcome = 'TRANSPORT_FAILURE' if len(created)==1 else 'ORIGINAL_DEADLINE'
                try: epoch.stop(outcome)
                finally: epoch.close()
                if len(created)==1:
                    persisted.update({p:file_hash(p) for p in (root/'epoch-00').rglob('*') if p.is_file()})
                    clock[0] = end-500_000_000 if mode=='late_failure' else start+100_000_000
                else: clock[0] = end
                return dict(outcome=outcome, public_connection_attempts=0, snapshot_requests=0,
                            latest_received_utc_ns=time.time_ns())
            async def sleep(seconds):
                sleeps.append(seconds)
                clock[0] = end if mode=='late_wake' else clock[0]+round(seconds*10**9)
            policy = load_contract(ROOT/'configs/research/forward_data_policy_v1.json')
            with patch.object(collector, 'time', SimpleNamespace(monotonic_ns=lambda:clock[0], time_ns=time.time_ns)), \
                 patch.object(collector, 'asyncio', SimpleNamespace(sleep=sleep, CancelledError=asyncio.CancelledError)), \
                 patch.object(collector, 'SegmentedFeedEpoch', side_effect=construct), \
                 patch.object(collector, 'collect_epoch', side_effect=collect):
                result = await collector.run_bounded(root, duration_ns=60*10**9, transport=object(), policy=policy)
            self.assertEqual(result['original_window']['window_start_ns'], start)
            self.assertEqual(result['original_window']['window_end_ns'], end)
            self.assertEqual(result['total_public_connection_attempts'], 0)
            self.assertFalse(result['errors'])
            self.assertTrue(all(not row['errors'] for row in result['audits']))
            self.assertEqual(result['storage_after_result']['used_bytes'],
                             sum(p.stat().st_size for p in root.rglob('*') if p.is_file()))
            self.assertTrue(all(p.is_file() and file_hash(p)==digest for p,digest in persisted.items()))
            if mode=='normal':
                self.assertEqual(len(created), 2)
                self.assertIs(budgets[0], budgets[1])
                self.assertGreater(created[1], created[0])
                self.assertEqual(result['stop_reason'], 'ORIGINAL_DEADLINE')
                self.assertEqual(result['retries_used'], 1)
                self.assertEqual(sleeps, [1.0])
            else:
                self.assertEqual(len(created), 1)
                self.assertFalse((root/'epoch-01').exists())
                if mode=='late_failure':
                    self.assertEqual(result['stop_reason'], 'RETRY_WOULD_REACH_DEADLINE')
                    self.assertEqual(result['retries_used'], 0)
                    self.assertEqual(sleeps, [])
                else:
                    self.assertEqual(result['stop_reason'], 'ORIGINAL_DEADLINE')
                    self.assertEqual(result['retries_used'], 1)
                    self.assertEqual(sleeps, [1.0])
            with lock_directory(root): pass

    async def test_second_epoch_preserves_first_files_and_shared_budget(self): await self.case('normal')
    async def test_late_failure_cannot_admit_second_epoch(self): await self.case('late_failure')
    async def test_retry_waking_at_original_deadline_cannot_open_second_epoch(self): await self.case('late_wake')


if __name__ == '__main__': unittest.main()
