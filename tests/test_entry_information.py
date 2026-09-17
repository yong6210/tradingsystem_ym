"""Hand calculations and causal counterexamples for E001."""
import unittest
from dataclasses import replace
try:
    import numpy as np
    import pandas as pd
except ModuleNotFoundError as exc:
    raise unittest.SkipTest('Install requirements-research.txt') from exc

from app.research.data.minutes import validate_minutes
from app.research.diagnostics.entry_information import (
    Decision, HistoricalMatcher, PriceResponses, build_decisions,
    moving_block_interval, control_reuse,
)
from app.research.foundation.contracts import CostAssumptions, MatchingDesign
from app.research.multistrategy_audit import Model, feature_bank, signals


def market(size=12):
    return pd.DataFrame({'o': 100., 'h': 101., 'l': 99., 'c': 100., 'v': 1000.},
                        index=pd.date_range('2023-01-01', periods=size, freq='min', tz='UTC'))


def matching():
    return MatchingDesign(28, 2, 17092026, 4, (0., .1, .2, .25), (0., .0025, .005, .01), True)


class EntryInformationTests(unittest.TestCase):
    def test_long_short_exact_costs(self):
        for side, exit_price, expected in [(1, 110., 985.3001), (-1, 90., 986.7001)]:
            with self.subTest(side=side):
                frame = market()
                frame.loc[frame.index[3], 'o'] = exit_price
                result = PriceResponses(frame, CostAssumptions(5., 2., 'test')).measure(0, side, 1, 2, 12)
                self.assertAlmostEqual(result['gross_bps'], 1000.)
                self.assertAlmostEqual(result['market_net_bps'], expected)

    def test_exact_delay_and_exit_bar_exclusion(self):
        frame = market()
        frame.loc[frame.index[0], 'o'] = 50.
        frame.loc[frame.index[3], ['o', 'h']] = [102., 10000.]
        result = PriceResponses(frame, CostAssumptions(0., 0., 'test')).measure(0, 1, 1, 2, 12)
        self.assertAlmostEqual(result['gross_bps'], 200.)
        self.assertAlmostEqual(result['favorable_bps'], 100.)
        self.assertAlmostEqual(result['adverse_bps'], -100.)

    def test_exit_at_exclusive_boundary_rejected(self):
        calculator = PriceResponses(market(), CostAssumptions(0., 0., 'test'))
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            calculator.measure(0, 1, 1, 2, 3)
        calculator.measure(0, 1, 1, 2, 4)

    def test_matching_uses_only_past_stratum_and_non_signals(self):
        decisions = [Decision(0, 0, (0, 0, 0)), Decision(15, 0, (0, 0, 0)),
                     Decision(30, 1, (0, 0, 0)), Decision(45, 0, (1, 0, 0)),
                     Decision(90, 0, (0, 0, 0)), Decision(100, 1, (0, 0, 0)),
                     Decision(120, 0, (0, 0, 0))]
        first = HistoricalMatcher(decisions, matching(), 60)
        candidates, selected = first.select(decisions[-2])
        self.assertEqual(candidates, [0, 15])
        self.assertEqual(selected, [0, 15])
        self.assertEqual((candidates, selected), HistoricalMatcher(decisions, matching(), 60).select(decisions[-2]))
        self.assertEqual(HistoricalMatcher(decisions[:3], matching(), 60).select(Decision(100, 1, (0, 0, 0))), (candidates, selected))

    def test_matching_does_not_relax_insufficient_pool(self):
        matcher = HistoricalMatcher([Decision(0, 0, (0, 0, 0))], matching(), 60)
        self.assertEqual(matcher.select(Decision(100, 1, (0, 0, 0))), ([0], []))

    def test_duplicate_and_missing_minutes_rejected(self):
        frame = market()
        for invalid in (pd.concat([frame.iloc[:1], frame]), frame.drop(frame.index[5])):
            with self.assertRaisesRegex(ValueError, 'minute'):
                validate_minutes(invalid)
        validate_minutes(frame)

    def test_duplicate_decisions_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unique'):
            HistoricalMatcher([Decision(0, 0, None), Decision(0, 1, None)], matching(), 60)

    def test_future_prices_do_not_change_historical_features_signals_or_matches(self):
        frame = market(32000)
        rng = np.random.default_rng(7)
        close = 100 * np.exp(np.cumsum(rng.normal(0, .001, len(frame))))
        frame['o'] = frame['c'] = close
        frame['h'], frame['l'] = close * 1.002, close * .998
        changed = frame.copy()
        changed.iloc[28000:, :4] *= 1.5
        banks = [feature_bank(value) for value in (frame, changed)]
        arrays = [signals(value, bank, Model('inventory_rotation', 2)) for value, bank in zip((frame, changed), banks)]
        for key in ('side', 'decision', 'atr', 'close'):
            np.testing.assert_array_equal(arrays[0][key][:28000], arrays[1][key][:28000])
        left = [x for x in build_decisions(frame, banks[0], arrays[0], matching()) if x.minute < 28000]
        right = [x for x in build_decisions(changed, banks[1], arrays[1], matching()) if x.minute < 28000]
        self.assertEqual(left, right)

    def test_bootstrap_constant_effect_and_empty_days(self):
        rows = [{'decision_time': f'2023-01-{day:02}T12:00:00Z', 'excess_bps': 5.} for day in range(1, 31)]
        result = moving_block_interval(rows, '2023-01-01T00:00:00Z', '2023-03-01T00:00:00Z', 28, 200, 7)
        self.assertEqual(result['interval_bps'], [5., 5.])
        self.assertEqual(result['event_days'], 30)
        self.assertEqual(result['calendar_days'], 59)

    def test_control_reuse_not_mistaken_for_independent_samples(self):
        result = control_reuse([{'selected': [1, 2]}, {'selected': [1, 2]}])
        self.assertEqual(result['assignments'], 4)
        self.assertEqual(result['concentration_equivalent_count'], 2.)


if __name__ == '__main__':
    unittest.main()
