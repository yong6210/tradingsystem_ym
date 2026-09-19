import unittest
from app.research.recovery.models import Bar, Zone
from app.research.recovery.zone_observer import ZoneObserver, replay_zone


def bar(n, low=100, high=104, close=103, received=None):
    return Bar(n*60000, close, high, low, close, n*60000 if received is None else received)


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.o = ZoneObserver.start(Zone("s", 1, 99, 101, 0, "fixture"), 1, 1, "fixture", 0)

    def test_touch_needs_later_hold(self):
        first = self.o.observe(bar(1))
        self.assertEqual(first.history.as_of(60000)["state"], "candidate")
        second = first.observe(bar(2, low=103))
        self.assertEqual(second.history.as_of(120000)["state"], "valid")
        self.assertEqual(self.o.history.as_of(120000)["state"], "candidate")

    def test_break_priority_and_reclaim_requires_new_reaction(self):
        o = replay_zone(self.o, [bar(1), bar(2), bar(3, low=96, high=104, close=97)])
        self.assertEqual(o.history.as_of(180000)["state"], "broken")
        o = o.observe(bar(4)).observe(bar(5, low=103))
        self.assertEqual(o.history.as_of(300000)["state"], "candidate")
        o = o.observe(bar(6)).observe(bar(7))
        self.assertEqual(o.history.as_of(420000)["state"], "valid")

    def test_delayed_receipt_does_not_rewrite_past(self):
        o = replay_zone(self.o, [bar(1), bar(2, received=180000)])
        self.assertEqual(o.history.as_of(120000)["state"], "candidate")
        self.assertEqual(o.history.as_of(180000)["state"], "valid")

    def test_gap_rejects_without_mutation(self):
        first = self.o.observe(bar(1))
        with self.assertRaises(ValueError):
            first.observe(bar(3))
        self.assertEqual(first.last_bar.end_ms, 60000)
        self.assertEqual(first.observe(bar(2)).history.as_of(120000)["state"], "valid")

    def test_duplicate_idempotent_revision_rejected(self):
        o = self.o.observe(bar(1))
        self.assertIs(o.observe(bar(1)), o)
        with self.assertRaises(ValueError):
            o.observe(bar(1, close=102))

    def test_no_preformation_bars_or_skipped_initial_bar(self):
        for b in [bar(0), bar(2)]:
            with self.assertRaises(ValueError):
                self.o.observe(b)
        o = ZoneObserver.start(self.o.history.zone, 1, 1, "fixture", 30000)
        with self.assertRaises(ValueError):
            o.observe(bar(1))
        o.observe(bar(2))

    def test_batch_prefix_equals_streaming(self):
        bars = [bar(1), bar(2), bar(3, low=96, high=98, close=97), bar(4)]
        full = replay_zone(self.o, bars)
        stream = self.o
        for b in bars:
            stream = stream.observe(b)
            self.assertEqual(full.history.as_of(b.received_ms), stream.history.as_of(b.received_ms))
        self.assertEqual(full, stream)

    def test_short_symmetry(self):
        o = ZoneObserver.start(self.o.history.zone, -1, 1, "fixture", 0)
        o = replay_zone(o, [bar(1, low=96, high=100, close=97), bar(2, low=96, high=98, close=97)])
        self.assertEqual(o.history.as_of(120000)["state"], "valid")
        o = o.observe(bar(3))
        self.assertEqual(o.history.as_of(180000)["state"], "broken")

    def test_boundary_equality_not_break_or_confirmation(self):
        o = self.o.observe(bar(1, low=98, close=98))
        self.assertEqual(o.history.as_of(60000)["state"], "candidate")
        o = o.observe(bar(2, close=102)).observe(bar(3))
        self.assertEqual(o.history.as_of(180000)["state"], "candidate")

    def test_hold_window_does_not_linger(self):
        o = replay_zone(self.o, [bar(1), bar(2, close=100), bar(3, low=103)])
        self.assertEqual(o.history.as_of(180000)["state"], "candidate")

    def test_receipt_order_rejected(self):
        o = self.o.observe(bar(1, received=180000))
        with self.assertRaises(ValueError):
            o.observe(bar(2))


if __name__ == "__main__":
    unittest.main()
