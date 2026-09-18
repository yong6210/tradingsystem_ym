import asyncio
from pathlib import Path
import tempfile
import time
import unittest

from app.research.data.feed_storage_envelope import rolling_peak, inventory, project_storage, capture_sample
from app.research.data.queued_feed_fixture import QueuedSocket, FixtureOverflow, book
from app.research.data.background_feed_collector import run_bounded
from app.research.foundation.forward_data_contract import load_contract


class CapacityTests(unittest.TestCase):
    def test_sliding_window_detects_burst_across_aligned_boundary(self):
        self.assertEqual(rolling_peak([(999_000_000, 10), (1_001_000_000, 20)]), 30)

    def test_left_edge_is_excluded(self):
        self.assertEqual(rolling_peak([(0, 10), (1_000_000_000, 20)]), 20)

    def test_equal_timestamps_accumulate(self):
        self.assertEqual(rolling_peak([(1, 2), (1, 3)]), 5)

    def test_bad_events_fail(self):
        for rows in [[(2, 1), (1, 2)], [(True, 2)], [(1, -2)]]:
            with self.assertRaises((ValueError, RuntimeError)): rolling_peak(rows)

    def project(self, **changes):
        values = dict(bytes_per_second=10, seconds=10, free_bytes=200,
                      reserve_bytes=50, logical_cap_bytes=500, transient_allowance_bytes=20)
        return project_storage(**(values | changes))

    def test_reserve_and_transient_are_not_spendable(self):
        row = self.project()
        self.assertEqual(row['maximum_seconds_under_assumption'], 13)
        self.assertTrue(row['conditional_space_fit'])
        self.assertFalse(row['full_day_ready'])

    def test_logical_cap_and_free_disk_are_independent(self):
        row = self.project(logical_cap_bytes=100)
        self.assertFalse(row['conditional_space_fit'])
        self.assertEqual(row['logical_cap_shortfall_bytes'], 20)
        self.assertEqual(row['additional_free_bytes_needed'], 0)

    def test_no_negative_maximum_time_when_below_reserve(self):
        row = self.project(free_bytes=1)
        self.assertEqual(row['maximum_seconds_under_assumption'], 0)
        self.assertEqual(row['additional_free_bytes_needed'], 120)

    def test_exact_boundary_and_one_byte_shortfall(self):
        self.assertTrue(self.project(free_bytes=170)['conditional_space_fit'])
        self.assertEqual(self.project(free_bytes=169)['additional_free_bytes_needed'], 1)

    def test_invalid_projection_arguments(self):
        for changes in ({'seconds': 0}, {'free_bytes': -1}, {'bytes_per_second': True}, {'seconds': 1.5}):
            with self.assertRaises(RuntimeError): self.project(**changes)

    def test_inventory_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            (root/'real').write_bytes(b'abc')
            self.assertEqual(inventory(root)['logical_bytes'], 3)
            (root/'link').symlink_to(root/'real')
            with self.assertRaises(ValueError): inventory(root)


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_production_continues_when_event_loop_is_blocked(self):
        socket = QueuedSocket('public', per_tick=2, levels=1, period_ns=10_000_000)
        try:
            time.sleep(.08)  # Deliberate consumer stall; producer thread keeps running.
            self.assertGreaterEqual(socket.produced, 8)
            await socket.recv()
            self.assertGreater(socket.max_residence_ns, 50_000_000)
        finally: await socket.close()
        self.assertFalse(socket.thread.is_alive())

    async def test_overflow_is_terminal_before_old_queue_can_look_healthy(self):
        socket = QueuedSocket('public', per_tick=20, levels=1, capacity=4)
        try:
            await asyncio.sleep(.02)
            self.assertTrue(socket.overflow.is_set())
            with self.assertRaises(FixtureOverflow): await socket.recv()
            self.assertEqual(socket.produced, 4)
            self.assertEqual(socket.attempted, 5)
        finally: await socket.close()

    def test_book_has_ordered_complete_fixture_levels(self):
        row = book(1000)
        self.assertEqual(len(row['bids'])+len(row['asks']), 2000)
        self.assertEqual(row['bids'][0], ['10000', '2'])
        self.assertEqual(row['asks'][0], ['10001', '4'])

    async def test_sample_matches_real_writer_inventory_and_rejects_changed_files(self):
        from app.research.data.queued_feed_fixture import QueuedTransport
        with tempfile.TemporaryDirectory() as d:
            path = Path(d).resolve()/'capture'
            policy = load_contract(Path(__file__).resolve().parents[1]/'configs/research/forward_data_policy_v1.json')
            result = await run_bounded(path, duration_ns=300_000_000,
                                      transport=QueuedTransport(per_tick=2, levels=10), policy=policy)
            sample = capture_sample(path, result)
            self.assertEqual(sample['logical_bytes'], result['storage_after_result']['used_bytes'])
            self.assertGreater(sample['peak_rolling_1s_record_bytes'], 0)
            self.assertGreater(sample['headers_metadata_supervisor_result_bytes'], 0)
            with self.assertRaisesRegex(ValueError, 'record limit'):
                capture_sample(path, result, max_records=1)
            (path/'untracked').write_bytes(b'new')
            with self.assertRaisesRegex(ValueError, 'inventory differs'):
                capture_sample(path, result)


if __name__ == '__main__': unittest.main()
