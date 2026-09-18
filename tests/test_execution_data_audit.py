import json
from pathlib import Path
import tempfile
import unittest

from scripts.audit_execution_data import quote_profile, sequence_profile


def depth(first, last, previous, **updates):
    return {'message': {'data': dict(e='depthUpdate', s='BTCUSDC', U=first, u=last, pu=previous, **updates)}}


class ExecutionDataAuditTests(unittest.TestCase):
    def test_snapshot_bridge_and_parent_sequence(self):
        result = sequence_profile({'lastUpdateId': 10}, [depth(1, 9, 0), depth(10, 12, 9), depth(13, 15, 12)])
        self.assertTrue(result['continuous'])
        self.assertEqual(result['discarded_before_snapshot'], 1)
        self.assertEqual(result['used_events'], 2)
        self.assertFalse(result['full_book_reconstruction_verified'])

    def test_missing_bridge_or_parent_and_duplicate_never_pass(self):
        streams = [[depth(11, 12, 9)], [depth(10, 12, 9), depth(13, 15, 11)],
                   [depth(10, 12, 9), depth(10, 12, 9)], [], [depth(20, 10, 9)]]
        for events in streams:
            self.assertFalse(sequence_profile({'lastUpdateId': 10}, events)['continuous'])
        self.assertEqual(sequence_profile(None, [])['status'], 'NO_SNAPSHOT')

    def test_directional_rows_share_one_observation_and_do_not_become_fills(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'quotes.jsonl'
            common = dict(timestamp='2026-06-12T00:00:00+00:00', symbol='BTCUSDC', best_bid=60000,
                          best_ask=60000.1, latency_ms=50, market_slippage_bps=.1)
            rows = [common | dict(side='long', decision_id='1'), common | dict(side='short', decision_id='2')]
            path.write_text('\n'.join(json.dumps(row) for row in rows))
            result = quote_profile(path)
            self.assertEqual(result['rows'], 2)
            self.assertEqual(result['unique_book_observations'], 1)
            self.assertEqual(result['directional_pairs'], 1)
            self.assertFalse(result['eligible_for_maker_fill_calibration'])


if __name__ == '__main__':
    unittest.main()
