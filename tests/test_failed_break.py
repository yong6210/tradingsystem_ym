import unittest
import pandas as pd

from app.research.candidate_accounts.failed_break import build_failed_break


def fixture():
    dates = pd.date_range('2025-01-01T01:00Z', periods=4, freq='h')
    hourly = pd.DataFrame(dict(c=[111., 105., 89., 95.], atr=[2.] * 4,
                              high24=[110., 120., 110., 120.], low24=[90., 80., 90., 80.]), index=dates)
    higher = pd.DataFrame(dict(ema80=[100.] * 4, er=[.2] * 4), index=dates)
    minutes = pd.DataFrame(index=pd.date_range('2025-01-01T00:00Z', periods=300, freq='min'))
    return minutes, {60: hourly, 240: higher}


class FailedBreakTests(unittest.TestCase):
    def test_original_fixed_channel_and_exact_opposite_event_clock(self):
        minutes, bank = fixture()
        policies, events = build_failed_break(minutes, bank)
        self.assertEqual([r['side'] for r in events], [-1, 1])
        self.assertEqual(events[0]['frozen_upper'], 110)
        self.assertEqual(events[0]['entry_at'], '2025-01-01T02:01:00+00:00')
        self.assertEqual(set(policies['S07_FADE']), set(policies['S07_CONTINUE']))
        for i, (side, close, atr) in policies['S07_FADE'].items():
            self.assertEqual(policies['S07_CONTINUE'][i], (-side, close, atr))

    def test_wick_alone_and_crossing_entire_range_are_not_recovery(self):
        minutes, bank = fixture()
        bank[60]['c'] = [109., 105., 111., 89.]
        self.assertEqual(build_failed_break(minutes, bank)[1], [])

    def test_future_values_do_not_change_past_event(self):
        minutes, bank = fixture()
        before = build_failed_break(minutes, bank)[1][0]
        bank[60].iloc[2:] = 777
        after = build_failed_break(minutes, bank)[1][0]
        self.assertEqual(before, after)

    def test_missing_ready_context_and_missing_execution_minute_skip(self):
        minutes, bank = fixture()
        bank[240]['ema80'] = float('nan')
        self.assertEqual(build_failed_break(minutes, bank)[1], [])
        minutes, bank = fixture()
        policies, _ = build_failed_break(minutes.loc[:'2025-01-01T02:00Z'], bank)
        self.assertEqual(policies['S07_FADE'], {})
