import unittest

from scripts.replay_public_depth import replay
from tests.test_local_order_book import event, snapshot


def wrapper(data, at):
    return dict(received_monotonic_ns=at, received_utc='2026-09-17T00:00:00+00:00', message=dict(data=data))


class PublicDepthReplayTests(unittest.TestCase):
    def test_reference_includes_changes_buffered_before_snapshot_publication(self):
        rows = [wrapper(event(bids=[['100','7']]), 1), wrapper(event(13, 15, 12, asks=[['101','6']]), 3)]
        result, quotes, _ = replay(snapshot(), rows, 2, independent=True)
        self.assertEqual(result['independent_full_book_comparisons'], 1)
        self.assertEqual(quotes[0]['bid_quantity'], '7')
        self.assertEqual(quotes[0]['ask_quantity'], '6')

    def test_ticker_comparison_requires_exact_update_id_and_all_four_fields(self):
        rows = [wrapper(event(), 1)]
        ticker = dict(u=12, b='100', B='2', a='101', A='99')
        result, _, _ = replay(snapshot(), rows, 1, independent=True, tickers={11:[ticker], 12:[ticker]})
        self.assertEqual(result['ticker_matched_observations'], 1)
        self.assertEqual(len(result['ticker_mismatches']), 1)

    def test_invalid_book_never_emits_quotes_after_gap(self):
        rows = [wrapper(event(), 1), wrapper(event(16, 18, 15), 2), wrapper(event(19, 20, 18), 3)]
        result, quotes, _ = replay(snapshot(), rows, 1)
        self.assertEqual(result['published_quotes'], 1)
        self.assertIsNone(result['final_quote'])
        self.assertEqual(result['final_state'], 'INVALID')


if __name__ == '__main__':
    unittest.main()
