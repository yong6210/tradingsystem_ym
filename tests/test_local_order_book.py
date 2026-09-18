from copy import deepcopy
from decimal import Decimal as D
import unittest

from app.research.data.local_order_book import LocalOrderBook, BookUnavailable


def snapshot(identity=10):
    return dict(lastUpdateId=identity, bids=[['100','2'],['99','3']], asks=[['101','4'],['102','5']])


def event(first=9, last=12, previous=8, bids=None, asks=None):
    return dict(e='depthUpdate', s='BTCUSDC', E=1000, T=999, U=first, u=last, pu=previous,
                b=bids or [], a=asks or [])


class LocalOrderBookTests(unittest.TestCase):
    def setUp(self):
        self.book = LocalOrderBook()
        self.book.begin_session('one', started_ns=0)

    def live(self):
        self.book.install_snapshot(snapshot(), session='one', available_ns=100)
        self.assertEqual(self.book.ingest(event(), session='one', received_ns=101), 'APPLIED')

    def ingest(self, value, at=102):
        return self.book.ingest(value, session='one', received_ns=at)

    def test_snapshot_not_usable_until_bridged_and_buffered_old_events_discarded(self):
        self.ingest(event(1, 8, 0), 50)
        self.ingest(event(bids=[['100','7']]), 60)
        with self.assertRaises(BookUnavailable):
            self.book.quote(now_ns=60)
        self.assertEqual(self.book.install_snapshot(snapshot(), session='one', available_ns=100), 'LIVE')
        self.assertEqual(self.book.quote(now_ns=100)['bid_quantity'], '7')
        with self.assertRaises(BookUnavailable):
            self.book.quote(now_ns=99)

    def test_absolute_replacement_and_zero_unknown_deletion(self):
        self.live()
        self.ingest(event(13, 15, 12, bids=[['100','6'],['98','0']], asks=[['101','0']]))
        q = self.book.quote(now_ns=102)
        self.assertEqual((q['bid_quantity'], q['ask']), ('6', '102'))
        self.assertFalse(q['full_market_depth_known'])

    def test_new_price_and_quantity_change_are_atomic(self):
        self.live()
        previous = self.book.checkpoint()
        self.assertEqual(self.ingest(event(13, 15, 12, bids=[['100','8'],['103','1']])), 'CROSSED_BOOK')
        self.assertEqual(self.book.bids[D(100)], D(2))
        self.assertEqual(previous['bids'], self.book.checkpoint()['bids'])
        with self.assertRaises(BookUnavailable):
            self.book.quote(now_ns=102)

    def test_gap_invalidates_until_new_session_and_new_bridged_snapshot(self):
        self.live()
        self.assertEqual(self.ingest(event(16, 18, 15)), 'UPDATE_CHAIN_GAP')
        self.assertEqual(self.ingest(event(13, 15, 12), 103), 'RESYNC_REQUIRED')
        self.book.begin_session('two', started_ns=104)
        self.assertEqual(self.book.install_snapshot(snapshot(18), session='two', available_ns=105), 'AWAIT_BRIDGE')
        with self.assertRaises(BookUnavailable):
            self.book.quote(now_ns=105)
        self.assertEqual(self.book.ingest(event(17, 20, 16), session='two', received_ns=106), 'APPLIED')
        self.assertEqual(self.book.quote(now_ns=106)['u'], 20)

    def test_old_session_updates_and_snapshots_cannot_contaminate_reconnect(self):
        self.live()
        self.book.begin_session('two', started_ns=104)
        self.assertEqual(self.ingest(event(13, 15, 12), 105), 'OLD_SESSION_IGNORED')
        self.assertEqual(self.book.install_snapshot(snapshot(), session='one', available_ns=106), 'OLD_SESSION_IGNORED')
        self.assertEqual(self.book.state, 'BUFFERING')

    def test_equal_snapshot_end_id_is_valid_bridge(self):
        self.book.install_snapshot(snapshot(), session='one', available_ns=100)
        self.assertEqual(self.ingest(event(9, 10, 8)), 'APPLIED')

    def test_bridge_missing_does_not_treat_later_event_as_snapshot(self):
        self.book.install_snapshot(snapshot(), session='one', available_ns=100)
        self.assertEqual(self.ingest(event(11, 12, 10)), 'SNAPSHOT_BRIDGE_MISSING')

    def test_duplicate_does_not_refresh_freshness_even_with_equivalent_decimals(self):
        self.book.install_snapshot(snapshot(), session='one', available_ns=100)
        self.ingest(event(bids=[['100.0','2.00']]), 101)
        self.assertEqual(self.ingest(event(bids=[['100','2']]), 1000), 'DUPLICATE')
        self.assertEqual(self.book.available_ns, 101)
        with self.assertRaises(BookUnavailable):
            self.book.quote(now_ns=1000, max_age_ns=10)

    def test_conflicting_duplicate_or_older_update_invalidates(self):
        self.live()
        self.assertEqual(self.ingest(event(bids=[['100','3']])), 'OUT_OF_ORDER_OR_CONFLICT')
        other = LocalOrderBook()
        other.begin_session('x', started_ns=0)
        other.install_snapshot(snapshot(), session='x', available_ns=1)
        other.ingest(event(), session='x', received_ns=2)
        self.assertEqual(other.ingest(event(7, 8, 6), session='x', received_ns=3), 'OUT_OF_ORDER_OR_CONFLICT')

    def test_ids_need_not_be_contiguous_if_parent_chain_matches(self):
        self.live()
        self.assertEqual(self.ingest(event(100, 110, 12)), 'APPLIED')

    def test_snapshot_coverage_exhaustion_is_not_filled_from_sparse_outer_updates(self):
        self.live()
        self.assertEqual(self.ingest(event(13, 15, 12, bids=[['100','0'],['99','0'],['97','1']])), 'SNAPSHOT_COVERAGE_EXHAUSTED')
        with self.assertRaises(BookUnavailable):
            self.book.quote(now_ns=102)

    def test_empty_side_rejected(self):
        self.live()
        self.assertEqual(self.ingest(event(13, 15, 12, asks=[['101','0'],['102','0']])), 'EMPTY_BOOK_SIDE')

    def test_bad_types_nonfinite_negative_and_duplicate_prices_rejected(self):
        rows = [[['100', 'NaN']], [['100','-1']], [['0','1']], [[100,'1']], [['100','1'],['100.0','2']], [['100','1e99999']]]
        for i, bids in enumerate(rows):
            book = LocalOrderBook()
            book.begin_session(str(i), started_ns=0)
            book.install_snapshot(snapshot(), session=str(i), available_ns=1)
            self.assertEqual(book.ingest(event(bids=bids), session=str(i), received_ns=2), 'MALFORMED_DEPTH')

    def test_wrong_symbol_boolean_sequence_and_bad_range_rejected(self):
        for i, patch in enumerate((dict(s='BTCUSDT'), dict(u=True), dict(U=20), dict(pu=12))):
            book = LocalOrderBook()
            book.begin_session(str(i), started_ns=0)
            self.assertEqual(book.ingest(event() | patch, session=str(i), received_ns=1), 'MALFORMED_DEPTH')

    def test_snapshot_wrong_sort_duplicate_zero_and_crossed_rejected(self):
        values = [snapshot() | dict(bids=[['99','1'],['100','1']]),
                  snapshot() | dict(bids=[['100','0']]), snapshot() | dict(bids=[['101','1']]),
                  snapshot() | dict(asks=[['101','1'],['101','2']]), snapshot() | dict(lastUpdateId=True)]
        for i, value in enumerate(values):
            book = LocalOrderBook()
            book.begin_session(str(i), started_ns=0)
            self.assertEqual(book.install_snapshot(value, session=str(i), available_ns=1), 'INVALID_SNAPSHOT')

    def test_buffer_overflow_and_receive_clock_regression_fail_closed(self):
        book = LocalOrderBook(max_buffer=1)
        book.begin_session('x', started_ns=0)
        book.ingest(event(), session='x', received_ns=1)
        self.assertEqual(book.ingest(event(), session='x', received_ns=2), 'BUFFER_OVERFLOW')
        self.live()
        self.assertEqual(self.ingest(event(13, 15, 12), 100), 'RECEIVE_CLOCK_REGRESSED')

    def test_disconnect_removes_quote_permission_without_waiting_for_staleness(self):
        self.live()
        self.book.disconnect('one')
        with self.assertRaises(BookUnavailable):
            self.book.quote(now_ns=102)
        self.assertEqual(self.book.install_snapshot(snapshot(), session='one', available_ns=103), 'SNAPSHOT_REQUIRES_NEW_SESSION')

    def test_session_reuse_clock_regression_and_snapshot_regression_rejected(self):
        self.live()
        with self.assertRaises(ValueError):
            self.book.begin_session('one', started_ns=102)
        with self.assertRaises(ValueError):
            self.book.begin_session('two', started_ns=100)
        self.book.begin_session('two', started_ns=102)
        self.assertEqual(self.book.install_snapshot(snapshot(9), session='two', available_ns=103), 'INVALID_SNAPSHOT')


if __name__ == '__main__':
    unittest.main()
