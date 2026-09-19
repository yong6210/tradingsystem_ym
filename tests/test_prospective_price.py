import copy
from decimal import Decimal as D
import unittest

import numpy as np
import pandas as pd

from app.research.diagnostics.prospective_price import (
    forecast, frame_from_rows, make_panel, publication_window, score_unit, validate_funding_coverage,
)
from app.research.diagnostics.daily_flow_forecast import PRICE, daily_panel


class ProspectivePriceTests(unittest.TestCase):
    def test_publication_window_has_strict_end_before_target(self):
        b = pd.Timestamp('2026-09-19', tz='UTC')
        for seconds, expected in [(-1, 'EARLY'), (4.999, 'EARLY'), (5, 'OPEN'),
                                  (50, 'OPEN'), (50.001, 'MISSED'), (60, 'MISSED')]:
            self.assertEqual(publication_window(b + pd.Timedelta(seconds=seconds), b), expected)

    def test_minute_schema_identity_geometry_and_close(self):
        rows = [[i, '100', '102', '99', '101', '3', i+59999, '0', 1, '1', '0', '0']
                for i in (0, 60000)]
        frame = frame_from_rows(rows, 0, 120000)
        self.assertEqual(len(frame), 2)
        for mutation in ('gap', 'duplicate', 'close', 'geometry', 'nan', 'negative'):
            bad = copy.deepcopy(rows)
            if mutation == 'gap': bad.pop()
            elif mutation == 'duplicate': bad[1][0] = 0
            elif mutation == 'close': bad[0][6] += 1
            elif mutation == 'geometry': bad[0][2] = '100'
            elif mutation == 'nan': bad[0][4] = 'nan'
            else: bad[0][5] = '-1'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                frame_from_rows(bad, 0, 120000)

    def test_minute_panel_matches_original_and_excludes_unavailable_targets(self):
        idx = pd.date_range('2026-08-01', periods=12*1440, freq='min', tz='UTC')
        close = 50000*np.exp(np.arange(len(idx))*1e-7 + np.sin(np.arange(len(idx))*.007)*.001)
        minutes = pd.DataFrame(dict(o=close*.999999, h=close*1.0001,
                                    l=close*.9999, c=close, v=2.), index=idx)
        flow = minutes.assign(taker_buy_volume=1.)
        original = daily_panel(minutes, flow)
        old = original.reset_index(names='open_time').to_dict('records')
        boundary = pd.Timestamp('2026-08-13', tz='UTC')
        panel, checks = make_panel(old, minutes, boundary)
        self.assertGreater(checks, 15)
        for key in PRICE + ['decision_close']:
            self.assertAlmostEqual(panel.at[boundary, key], original.at[boundary, key], places=10)
        self.assertTrue(pd.isna(panel.at[boundary, 'target_bps']))
        self.assertTrue(pd.isna(panel.at[boundary-pd.Timedelta(days=1), 'target_bps']))
        self.assertTrue(np.isfinite(panel.at[boundary-pd.Timedelta(days=2), 'target_bps']))
        with self.assertRaisesRegex(ValueError, 'minute gap'):
            make_panel(old, minutes.drop(minutes.index[200]), boundary)
        with self.assertRaisesRegex(ValueError, 'not complete'):
            make_panel(old, minutes.iloc[:-1], boundary)
        bad = copy.deepcopy(old)
        bad[-2]['return_1d'] += .01
        with self.assertRaisesRegex(ValueError, 'overlap mismatch'):
            make_panel(bad, minutes, boundary)

    def model_fixture(self):
        idx = pd.date_range('2026-02-01', periods=200, freq='D', tz='UTC')
        t = np.arange(len(idx), dtype=float)
        panel = pd.DataFrame(dict(return_1d=np.sin(t)*.01, return_7d=np.cos(t*.1)*.03,
            realized_vol_1d=.01+np.sin(t*.3)*.002, decision_close=80000.,
            target_bps=20*np.sin(t*.2)+4,
            entry_time=idx+pd.Timedelta(minutes=1), exit_time=idx+pd.Timedelta(days=1)), index=idx)
        b = idx[-1]
        funding = [dict(symbol='BTCUSDC', fundingTime=int((b-pd.Timedelta(hours=h)).timestamp()*1000),
                        fundingRate='0.0001') for h in (24, 16, 8)]
        return panel, b, funding

    def test_forecast_uses_only_mature_training_targets_and_train_scaling(self):
        panel, b, funding = self.model_fixture()
        result = forecast(panel, b, funding)
        training = panel.iloc[18:198]
        x = training[PRICE].to_numpy()
        y = training.target_bps.to_numpy()
        mu = x.mean(axis=0); sd = x.std(axis=0)
        z = (x-mu)/sd
        beta = np.linalg.lstsq(np.vstack([z, np.sqrt(180)*np.eye(3)]),
                              np.r_[y-y.mean(), np.zeros(3)], rcond=None)[0]
        expected = y.mean() + ((panel.loc[b, PRICE].to_numpy(dtype=float)-mu)/sd) @ beta
        self.assertAlmostEqual(result['prediction_bps'], expected, places=10)
        self.assertEqual(result['training_last_target_exit'], (b-pd.Timedelta(days=1)).isoformat())
        changed = panel.copy()
        changed.loc[changed.index[-2:], 'target_bps'] = [1e20, np.nan]
        changed.loc[changed.index[-2], PRICE] = 1e20
        # Funding at the decision boundary is not yet usable by this rule.
        extra = funding + [dict(symbol='BTCUSDC', fundingTime=int(b.timestamp()*1000), fundingRate='100')]
        self.assertEqual(forecast(changed, b, extra), result)
        self.assertAlmostEqual(result['threshold_bps'], 21.025)
        self.assertAlmostEqual(result['controls']['MEAN180'], y.mean())

    def test_missing_history_target_or_funding_rejected(self):
        panel, b, funding = self.model_fixture()
        with self.assertRaisesRegex(ValueError, 'training range'):
            forecast(panel.iloc[-180:], b, funding)
        broken = panel.copy(); broken.iloc[40, broken.columns.get_loc('target_bps')] = np.nan
        with self.assertRaisesRegex(ValueError, 'nonfinite'):
            forecast(broken, b, funding)
        with self.assertRaisesRegex(ValueError, 'funding count'):
            forecast(panel, b, funding[:2])
        stale = copy.deepcopy(funding); stale[0]['fundingTime'] -= 7200000
        with self.assertRaisesRegex(ValueError, 'stale funding'):
            forecast(panel, b, stale)

    def test_unit_costs_match_cash_arithmetic_for_long_and_short(self):
        long = score_unit('10000', '10100', 1, [], 0, 60000, 2.5, 0, 0)
        self.assertEqual(D(long['gross_bps']), D(100))
        self.assertEqual(D(long['fees_bps']), D('5.025'))
        self.assertEqual(D(long['net_bps']), D('94.975'))
        short = score_unit('10000', '9900', -1, [], 0, 60000, 2.5, 2, 0)
        # Sell 9998.0; buy ceil(9901.98 / .1) * .1 = 9902.0.
        self.assertEqual(D(short['execution_bps']), D(4))
        self.assertEqual(D(short['net_bps']), D(96) - D('19900')*D('.00025'))
        flat = score_unit('10000', '9900', 0, [], 0, 60000, 2.5, 5, 1)
        self.assertTrue(all(D(x) == 0 for x in flat.values()))

    def test_funding_entry_exit_boundaries_sign_and_extra_charge(self):
        funding = [dict(markPrice='10000', fundingRate='0.0001', fundingTime=t)
                   for t in (60000, 60001, 120000, 120001)]
        long = score_unit(10000, 10000, 1, funding, 60000, 120000, 0, 0, 0)
        short = score_unit(10000, 10000, -1, funding, 60000, 120000, 0, 0, 1)
        self.assertEqual(D(long['funding_bps']), D(2))
        self.assertEqual(D(long['net_bps']), D(-2))
        self.assertEqual(D(short['funding_bps']), D(0))
        self.assertEqual(D(short['net_bps']), D(0))

    def test_bad_unit_inputs_rejected(self):
        for args in [(0, 100, 1, [], 0, 60000, 0, 0, 0),
                     (100, 100, 2, [], 0, 60000, 0, 0, 0),
                     (100, 100, 1, [], 60000, 0, 0, 0, 0),
                     (100, 100, 1, [], 0, 60000, -1, 0, 0)]:
            with self.assertRaises(ValueError): score_unit(*args)

    def test_missing_funding_never_becomes_zero_cost(self):
        h = 3600000
        funding = [dict(symbol='BTCUSDC', markPrice='10000', fundingRate='0.0001', fundingTime=t*h)
                   for t in (0, 8, 16, 24)]
        validate_funding_coverage(funding, h, 24*h)
        for missing in ([], funding[1:], funding[:-1], funding[:1]+funding[2:]):
            with self.assertRaises(ValueError): validate_funding_coverage(missing, h, 24*h)


if __name__ == '__main__': unittest.main()
