from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from app.research.data.durable_capture_log import DurableCaptureLog
from app.research.data.durable_market_feed import MarketFeedProcessor, PUBLIC_URL, MARKET_URL, SNAPSHOT_URL
from app.research.data.feed_coverage_audit import audit_epoch, combine_epochs, subtract
from app.research.foundation.forward_data_contract import load_contract
from tests.test_local_order_book import snapshot, event
from tests.test_durable_market_feed import mark

NS = 1_000_000_000
ROOT = Path(__file__).resolve().parents[1]


class SyntheticEpoch:
    """Explicit synthetic clocks for exact interval arithmetic, not live timing."""
    def __init__(self, root, *, end=10*NS):
        self.root, self.end = root, end
        root.mkdir()
        self.journal = DurableCaptureLog.create(root/'journal', run_id='synthetic', min_free_bytes=0)
        self.processor = MarketFeedProcessor()
        self.pending, self.batches = [], []
        self.closed = False
        self.received = 1
        self.add('RUN_WINDOW', 'system', started_ns=0, deadline_ns=end)
        self.add('OPEN', 'public', url=PUBLIC_URL)
        self.add('OPEN', 'market', url=MARKET_URL)

    def add(self, kind, channel, **fields):
        row = dict(kind=kind, channel=channel, session=channel if channel!='system' else self.journal.epoch,
                   process_epoch=self.journal.epoch, received_ns=self.received,
                   received_utc_ns=1_000_000_000_000+self.received) | fields
        seq = self.journal.append(row)
        self.pending.append((seq, row))

    def fresh(self, at):
        self.received = at
        self.add('REQUEST', 'public', request_id='req', url=SNAPSHOT_URL)
        self.add('SNAPSHOT', 'public', request_id='req', request_started_ns=at,
                 http_status=200, wire_text=json.dumps(snapshot()))
        self.add('WS', 'public', wire_text=json.dumps(dict(stream='btcusdc@depth@100ms', data=event())))
        self.add('WS', 'market', wire_text=json.dumps(dict(stream='btcusdc@markPrice@1s', data=mark())))
        self.add('WATCHDOG', 'system', expected_ns=at)
        self.flush(at)

    def flush(self, at):
        receipt = self.journal.commit()
        for seq, record in self.pending:
            self.processor.apply(seq, record, processed_ns=at)
        observation = self.processor.observe(now_ns=at, committed_ns=at, committed_sequence=receipt.sequence)
        self.batches.append(dict(first_sequence=self.pending[0][0], last_sequence=receipt.sequence,
                                 record_sha256=receipt.record_sha256, committed_ns=at, observation=observation))
        self.pending.clear()
        self.save_audit()

    def tick(self, at):
        self.received = at
        self.add('WATCHDOG', 'system', expected_ns=at)
        self.flush(at)

    def save_audit(self):
        (self.root/'batches.jsonl').write_text(''.join(json.dumps(b)+'\n' for b in self.batches))

    def close(self):
        if not self.closed:
            self.journal.close()
            self.closed = True

    def audit(self):
        self.close()
        return audit_epoch(self.root/'journal', self.root/'batches.jsonl',
                           window_start_ns=0, window_end_ns=self.end, clock_domain='synthetic-domain')


class CoverageAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.e = SyntheticEpoch(Path(self.temp.name)/'epoch')
        self.policy = load_contract(ROOT/'configs/research/forward_data_policy_v1.json')

    def tearDown(self):
        self.e.close()
        self.temp.cleanup()

    def combined(self, *epochs):
        return combine_epochs(self.policy, list(epochs), window_start_ns=0, window_end_ns=10*NS,
                              clock_domain='synthetic-domain')

    def test_intervals_start_after_publication_and_stop_at_last_audited_point(self):
        self.e.fresh(100_000_000)
        self.e.tick(300_000_000)
        result = self.e.audit()
        self.assertEqual(result['intervals']['l2'], [[100_000_000, 300_000_000]])
        combined = self.combined(result)
        self.assertEqual(combined['quality']['calendar_ns'], 10*NS)
        self.assertEqual(combined['quality']['joint_eligible_ns'], 200_000_000)
        self.assertEqual(combined['quality']['longest_unavailable_ns'], 9_700_000_000)

    def test_no_extrapolation_from_only_one_good_observation(self):
        self.e.fresh(100_000_000)
        result = self.e.audit()
        self.assertTrue(all(not value for value in result['intervals'].values()))

    def test_uncommitted_raw_tail_cannot_be_silently_classified_as_clean(self):
        self.e.fresh(100_000_000)
        self.e.tick(300_000_000)
        self.e.received = 500_000_000
        self.e.add('WATCHDOG', 'system', expected_ns=500_000_000)
        result = self.e.audit()
        self.assertTrue(result['raw_prefix_valid'])
        self.assertEqual(result['intervals']['l2'], [[100_000_000, 300_000_000]])
        self.assertIn('UNCOMMITTED_RAW_SUFFIX_PRESENT', result['errors'])
        self.assertIn('EPOCH_AUDIT_OR_PROCESSOR_FAILURE', self.combined(result)['quality']['reasons'])

    def test_mark_and_market_expire_even_with_a_later_observation(self):
        self.e.fresh(100_000_000)
        self.e.tick(4*NS)
        result = self.e.audit()
        for gate in ('mark', 'market_connection'):
            self.assertEqual(result['intervals'][gate], [[100_000_000, 3_100_000_000]])

    def test_watchdog_expiry_breaks_long_gap_without_final_point_extrapolation(self):
        self.e.fresh(100_000_000)
        self.e.tick(2*NS)
        result = self.e.audit()
        self.assertEqual(result['intervals']['clock'], [[100_000_000, 600_000_000]])
        self.assertEqual(result['intervals']['l2'], [[100_000_000, 1_100_000_000]])
        self.assertEqual(self.combined(result)['quality']['joint_eligible_ns'], 500_000_000)

    def test_disconnect_receipt_cuts_before_delayed_processing(self):
        self.e.fresh(100_000_000)
        self.e.received = 200_000_000
        self.e.add('END', 'market')
        self.e.flush(300_000_000)
        result = self.e.audit()
        self.assertEqual(result['intervals']['l2'], [[100_000_000, 200_000_000]])
        self.assertEqual(result['exclusions'], [(1, 100_000_000), (200_000_000, 300_000_000)])

    def test_depth_fault_receipt_cuts_before_delayed_processing(self):
        self.e.fresh(100_000_000)
        self.e.received = 200_000_000
        self.e.add('WS', 'public', wire_text=json.dumps(dict(
            stream='btcusdc@depth@100ms', data=event(first=20, last=22, previous=19))))
        self.e.flush(300_000_000)
        result = self.e.audit()
        self.assertEqual(result['intervals']['l2'], [[100_000_000, 200_000_000]])
        self.assertTrue(result['processor_errors'])
        self.assertIn('EPOCH_AUDIT_OR_PROCESSOR_FAILURE', self.combined(result)['quality']['reasons'])

    def test_audit_loss_keeps_prefix_and_does_not_invent_tail(self):
        self.e.fresh(100_000_000)
        self.e.tick(300_000_000)
        self.e.tick(500_000_000)
        self.e.batches.pop()
        self.e.save_audit()
        result = self.e.audit()
        self.assertEqual(result['status'], 'AUDIT_INCOMPLETE_OR_INVALID')
        self.assertEqual(result['unaudited_committed_records'], 1)
        self.assertEqual(result['last_audited_publication_ns'], 300_000_000)
        combined = self.combined(result)
        self.assertIn('EPOCH_AUDIT_OR_PROCESSOR_FAILURE', combined['quality']['reasons'])

    def test_torn_audit_preserved_and_not_parsed_as_complete(self):
        self.e.fresh(100_000_000)
        path = self.e.root/'batches.jsonl'
        with path.open('ab') as stream:
            stream.write(b'{"first_sequence":')
        before = path.read_bytes()
        result = self.e.audit()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(result['valid_batches'], 1)
        self.assertEqual(result['unaudited_audit_bytes'], len(b'{"first_sequence":'))

    def test_missing_audit_is_unknown_not_zero_failure(self):
        self.e.fresh(100_000_000)
        (self.e.root/'batches.jsonl').unlink()
        result = self.e.audit()
        self.assertTrue(result['raw_prefix_valid'])
        self.assertTrue(result['errors'])
        self.assertEqual(result['valid_batches'], 0)

    def test_tampered_observation_or_fence_cannot_create_coverage(self):
        self.e.fresh(100_000_000)
        self.e.tick(300_000_000)
        for patch in ('hash', 'observation'):
            original = deepcopy(self.e.batches)
            if patch == 'hash':
                self.e.batches[1]['record_sha256'] = '0'*64
            else:
                self.e.batches[1]['observation']['quote']['bid'] = '999'
            self.e.save_audit()
            result = self.e.audit()
            self.assertEqual(result['valid_batches'], 1)
            self.assertEqual(result['intervals']['l2'], [])
            self.e.batches = original

    def test_committed_raw_corruption_rejects_whole_epoch(self):
        self.e.fresh(100_000_000)
        self.e.close()
        path = next((self.e.root/'journal').glob('segment-*.jsonl'))
        path.write_bytes(path.read_bytes()[:-1])
        result = self.e.audit()
        self.assertFalse(result['raw_prefix_valid'])
        self.assertEqual(result['valid_batches'], 0)

    def test_two_epochs_keep_original_calendar_and_restart_gap(self):
        self.e.fresh(100_000_000)
        self.e.tick(300_000_000)
        first = self.e.audit()
        second = SyntheticEpoch(Path(self.temp.name)/'second')
        try:
            second.fresh(5*NS)
            second.tick(5_200_000_000)
            combined = self.combined(first, second.audit())
        finally:
            second.close()
        self.assertEqual(combined['quality']['calendar_ns'], 10*NS)
        self.assertEqual(combined['quality']['joint_eligible_ns'], 400_000_000)
        self.assertEqual(combined['quality']['longest_unavailable_ns'], 4_800_000_000)

    def test_clock_domain_epoch_reuse_and_changed_window_reject(self):
        self.e.fresh(100_000_000)
        original = self.e.audit()
        for key, value in [('clock_domain','different-boot'), ('window_end_ns',11*NS)]:
            with self.assertRaises(ValueError):
                self.combined(original | {key:value})
        with self.assertRaises(ValueError):
            self.combined(original, original)

    def test_changed_raw_window_is_not_accepted_from_caller(self):
        self.e.fresh(100_000_000)
        self.e.close()
        result = audit_epoch(self.e.root/'journal', self.e.root/'batches.jsonl',
                             window_start_ns=0, window_end_ns=9*NS, clock_domain='synthetic-domain')
        self.assertTrue(result['errors'])
        self.assertEqual(result['valid_batches'], 0)

    def test_interval_subtraction_matches_independent_discrete_sets(self):
        original = [[0, 10], [15, 30]]
        cuts = [[2, 5], [8, 16], [20, 23]]
        expected = {x for lo, hi in original for x in range(lo, hi)}-{x for lo, hi in cuts for x in range(lo, hi)}
        actual = {x for lo, hi in subtract(original, cuts) for x in range(lo, hi)}
        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
