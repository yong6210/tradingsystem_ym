from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from app.research.data.durable_capture_log import DurableCaptureLog, iter_committed
from app.research.data.durable_market_feed import (
    DurableFeedBridge, MarketFeedProcessor, PUBLIC_URL, MARKET_URL, SNAPSHOT_URL,
)
from tests.test_local_order_book import snapshot, event


def mark(**patches):
    return dict(e='markPriceUpdate', s='BTCUSDC', E=1000, T=2000, p='100', i='100', r='0') | patches


def trade(**patches):
    return dict(e='aggTrade', s='BTCUSDC', E=1000, T=999, a=10, f=20, l=21, p='100', q='2', m=True) | patches


class FeedProcessorTests(unittest.TestCase):
    def setUp(self):
        self.p = MarketFeedProcessor()
        self.now = 100_000_000
        self.rows = []
        self.send('RUN_WINDOW', 'system', started_ns=self.now, deadline_ns=self.now+10_000_000_000)
        self.send('OPEN', 'public', url=PUBLIC_URL)
        self.send('OPEN', 'market', url=MARKET_URL)

    def send(self, kind, channel, **fields):
        self.now += 1_000_000
        record = dict(kind=kind, channel=channel, session=channel if channel != 'system' else 'epoch',
                      process_epoch='epoch', received_ns=self.now, received_utc_ns=1_000_000_000+self.now) | fields
        self.p.apply(self.p.sequence+1, record, processed_ns=self.now)
        self.rows.append(record)
        return record

    def ws(self, channel, stream, data, **fields):
        return self.send('WS', channel, wire_text=json.dumps(dict(stream=stream, data=data)), **fields)

    def live(self):
        self.send('REQUEST', 'public', url=SNAPSHOT_URL, request_id='req')
        self.send('SNAPSHOT', 'public', request_id='req', request_started_ns=self.now, http_status=200,
                  wire_text=json.dumps(snapshot()))
        self.ws('public', 'btcusdc@depth@100ms', event())
        self.ws('market', 'btcusdc@markPrice@1s', mark())
        self.send('WATCHDOG', 'system', expected_ns=self.now)

    def observe(self, delay=0):
        return self.p.observe(now_ns=self.now+delay, committed_ns=self.p.processed_ns, committed_sequence=self.p.sequence)

    def test_four_gate_observation_requires_all_sources_and_watchdog(self):
        self.assertFalse(self.observe()['eligible'])
        self.live()
        self.assertTrue(self.observe()['eligible'])
        self.assertFalse(self.observe()['maker_fill_calibrated'])

    def test_native_depth_age_not_refreshed_by_slow_snapshot_commit(self):
        self.send('REQUEST', 'public', url=SNAPSHOT_URL, request_id='req')
        request_started = self.now
        self.ws('public', 'btcusdc@depth@100ms', event())
        self.now += 2_000_000_000
        self.send('SNAPSHOT', 'public', request_id='req', request_started_ns=request_started,
                  http_status=200, wire_text=json.dumps(snapshot()))
        self.ws('market', 'btcusdc@markPrice@1s', mark())
        self.send('WATCHDOG', 'system', expected_ns=self.now)
        self.assertEqual(self.p.book.state, 'LIVE')
        self.assertFalse(self.observe()['gates']['l2'])

    def test_quiet_trade_feed_is_not_itself_an_error(self):
        self.live()
        self.assertTrue(self.observe()['eligible'])
        self.assertEqual(self.p.counts['aggTrade'], 0)

    def test_duplicate_trade_ignored_conflict_and_regression_fail_closed(self):
        self.live()
        self.ws('market', 'btcusdc@aggTrade', trade())
        self.ws('market', 'btcusdc@aggTrade', trade(p='100.0'))
        self.assertEqual(self.p.counts['aggTrade'], 1)
        self.assertEqual(self.p.counts['TRADE_DUPLICATE'], 1)
        with self.assertRaises(ValueError):
            self.ws('market', 'btcusdc@aggTrade', trade(q='3'))
        self.assertFalse(self.observe()['eligible'])

    def test_trade_id_gap_is_unverified_and_blocks_input_use(self):
        self.live()
        self.ws('market', 'btcusdc@aggTrade', trade())
        self.ws('market', 'btcusdc@aggTrade', trade(a=12))
        self.assertIn('AGGREGATE_ID_GAP_UNVERIFIED', self.p.errors)
        self.assertFalse(self.observe()['eligible'])

    def test_wrong_symbol_nonfinite_values_and_bad_trade_side_reject(self):
        for kind, stream, bad in [('mark', 'btcusdc@markPrice@1s', mark(p='NaN')),
                                  ('mark', 'btcusdc@markPrice@1s', mark(s='BTCUSDT')),
                                  ('trade', 'btcusdc@aggTrade', trade(m=1)),
                                  ('trade', 'btcusdc@aggTrade', trade(q='-1'))]:
            with self.subTest(kind=kind, bad=bad):
                other = deepcopy(self.p)
                row = dict(kind='WS', channel='market', session='market', process_epoch='epoch',
                           received_ns=self.now, received_utc_ns=self.now,
                           wire_text=json.dumps(dict(stream=stream,data=bad)))
                with self.assertRaises(ValueError):
                    other.apply(other.sequence+1, row, processed_ns=self.now)
                self.assertTrue(other.errors)

    def test_market_disconnect_and_global_stop_revoke_publication(self):
        self.live()
        self.send('END', 'market')
        self.assertFalse(self.observe()['eligible'])
        self.assertIsNone(self.observe()['quote'])
        self.send('STOP', 'system')
        self.assertTrue(self.observe()['stopped'])

    def test_stale_watchdog_and_mark_are_not_kept_healthy(self):
        self.live()
        self.assertFalse(self.observe(500_000_001)['gates']['clock'])
        self.assertFalse(self.observe(3_000_000_001)['gates']['mark'])

    def test_loop_stall_and_utc_jump_latch_failure(self):
        self.live()
        self.send('WATCHDOG', 'system', expected_ns=0)
        self.now += 1_000_000_000
        self.send('WATCHDOG', 'system', expected_ns=0, received_utc_ns=99_000_000_000)
        self.assertIn('LOOP_LAG_EXCEEDED', self.p.errors)
        self.assertIn('WALL_MONOTONIC_DRIFT', self.p.errors)

    def test_changed_process_epoch_cannot_reuse_old_clock_domain(self):
        with self.assertRaises(ValueError):
            self.send('WATCHDOG', 'system', expected_ns=0, process_epoch='other')

    def test_processing_before_receipt_or_uncommitted_sequence_rejected(self):
        with self.assertRaises(ValueError):
            self.p.observe(now_ns=self.now, committed_ns=self.now, committed_sequence=999)
        with self.assertRaises(ValueError):
            self.send('WATCHDOG', 'system', expected_ns=0, received_ns=self.now+9999999)

    def test_late_native_rest_receive_can_precede_an_already_serialized_ws(self):
        self.send('REQUEST', 'public', url=SNAPSHOT_URL, request_id='req')
        request = self.now
        self.ws('public', 'btcusdc@depth@100ms', event())
        self.send('SNAPSHOT', 'public', request_id='req', request_started_ns=request, received_ns=request,
                  http_status=200, wire_text=json.dumps(snapshot()))
        self.assertEqual(self.p.book.state, 'LIVE')

    def test_identical_mark_does_not_refresh_freshness_and_old_mark_rejects(self):
        self.live()
        received = self.p.mark_received_ns
        self.ws('market', 'btcusdc@markPrice@1s', mark(p='100.0'))
        self.assertEqual(self.p.mark_received_ns, received)
        self.assertEqual(self.p.counts['MARK_DUPLICATE'], 1)
        with self.assertRaises(ValueError):
            self.ws('market', 'btcusdc@markPrice@1s', mark(E=999))

    def test_deadline_revokes_even_when_all_data_gates_are_fresh(self):
        self.live()
        self.p.deadline_ns = self.now
        observation = self.observe()
        self.assertTrue(all(observation['gates'].values()))
        self.assertFalse(observation['within_window'])
        self.assertFalse(observation['eligible'])

    def test_closing_frames_preserved_without_applying_or_publishing(self):
        self.live()
        prior = self.p.counts['depthUpdate']
        self.send('STOP', 'system')
        self.send('END', 'public')
        self.send('CLOSING_WS', 'public', wire_text='raw closing frame')
        self.assertEqual(self.p.counts['depthUpdate'], prior)
        self.assertFalse(self.observe()['eligible'])


class DurableBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'journal'
        self.journal = DurableCaptureLog.create(self.path, run_id='fixture', min_free_bytes=0)
        self.bridge = DurableFeedBridge(self.journal)

    def tearDown(self):
        self.journal.close()
        self.temp.cleanup()

    def record(self):
        now = time.monotonic_ns()
        return dict(kind='OPEN', channel='public', session='public', received_ns=now,
                    received_utc_ns=time.time_ns(), url=PUBLIC_URL)

    def test_no_processor_effect_until_raw_commit_and_payload_is_owned(self):
        row = self.record()
        self.bridge.append(row)
        row['url'] = 'mutated'
        self.assertEqual(self.bridge.processor.sequence, 0)
        self.assertEqual(self.bridge.batches, [])
        batch = self.bridge.flush()
        self.assertEqual(self.bridge.processor.sequence, 1)
        self.assertGreaterEqual(batch['observation']['published_ns'], batch['committed_ns'])
        self.journal.close()
        self.assertEqual(next(iter_committed(self.path))['payload']['url'], PUBLIC_URL)

    def test_fsync_failure_never_processes_or_publishes_pending_input(self):
        self.bridge.append(self.record())
        with patch('app.research.data.durable_capture_log.os.fsync', side_effect=OSError('injected failure')):
            with self.assertRaises(OSError):
                self.bridge.flush()
        self.assertEqual(self.bridge.processor.sequence, 0)
        self.assertEqual(self.bridge.batches, [])
        self.assertTrue(self.bridge.failed)

    def test_queue_capacity_failure_is_not_silent_drop(self):
        self.bridge.max_pending = 1
        self.bridge.append(self.record())
        with self.assertRaises(ValueError):
            self.bridge.append(self.record())
        self.assertTrue(self.bridge.failed)
        self.assertEqual(self.bridge.processor.sequence, 0)

    def test_replay_reuses_recorded_commit_and_publication_boundaries(self):
        self.bridge.append(self.record())
        batch = self.bridge.flush()
        self.journal.close()
        other = MarketFeedProcessor()
        for row in iter_committed(self.path):
            other.apply(row['sequence'], row['payload'], processed_ns=batch['committed_ns'])
        replayed = other.observe(now_ns=batch['observation']['published_ns'], committed_ns=batch['committed_ns'],
                                 committed_sequence=batch['last_sequence'])
        self.assertEqual(replayed, batch['observation'])


if __name__ == '__main__':
    unittest.main()
