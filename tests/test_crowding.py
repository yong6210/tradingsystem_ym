from copy import deepcopy
from types import SimpleNamespace
import unittest

import numpy as np
import pandas as pd

from app.research.candidate_accounts.crowding import (
    funding_context, basis_context, admission, build_crowding_policies,
)


def events(n=100):
    first = pd.Timestamp('2025-01-01T00:00Z').value // 1_000_000
    return [dict(symbol='BTCUSDC', fundingTime=int(first+i*8*3600_000),
                 fundingRate=str(.0001+i*.000001), markPrice='100') for i in range(n)]


def ready(**kwargs):
    values = dict(funding_ready=True, funding_rate=0., funding_low=-.001, funding_high=.001,
                  basis_ready=True, basis=0., basis_low=-.01, basis_high=.01)
    values.update(kwargs)
    return SimpleNamespace(**values)


class CrowdingTests(unittest.TestCase):
    def test_funding_lag_and_millisecond_boundary(self):
        e = events(); stamp = e[91]['fundingTime'] + 1; e[91]['fundingTime'] = stamp
        times = pd.to_datetime([stamp+59999, stamp+60000], unit='ms', utc=True)
        f = funding_context(times, e)
        self.assertEqual(f.funding_ms.iloc[0], e[90]['fundingTime'])
        self.assertEqual(f.funding_ms.iloc[1], stamp)

    def test_funding_history_excludes_current(self):
        e = events(); e[91]['fundingRate'] = '1'
        t = pd.to_datetime([e[91]['fundingTime']+60000], unit='ms', utc=True)
        f = funding_context(t, e).iloc[0]
        self.assertLess(f.funding_high, .001)
        self.assertFalse(admission(1, f, 'S09F'))

    def test_future_funding_and_settlement_mark_are_not_features(self):
        e = events(); changed = deepcopy(e)
        for row in changed[95:]: row['fundingRate'] = '9'
        for row in changed: row['markPrice'] = '999999'
        t = pd.to_datetime([e[94]['fundingTime']+60000], unit='ms', utc=True)
        pd.testing.assert_frame_equal(funding_context(t, e), funding_context(t, changed))

    def test_before_history_and_stale_fail_closed(self):
        e = events(92)
        t = pd.to_datetime([e[0]['fundingTime']-1, e[89]['fundingTime']+60000,
                            e[-1]['fundingTime']+12*3600_000+1], unit='ms', utc=True)
        f = funding_context(t, e)
        self.assertFalse(f.funding_ready.any())
        self.assertTrue(all(not admission(1, row, 'S09F') for row in f.itertuples()))

    def test_invalid_funding_order_rejected(self):
        e = events(); e[3] = e[2]
        with self.assertRaises(ValueError):
            funding_context(pd.date_range('2025-02-01', periods=1, tz='UTC'), e)

    def test_basis_last_closed_minute_and_future_invariance(self):
        times = pd.date_range('2025-01-01T04:00Z', periods=182, freq='4h')
        index = pd.date_range('2025-01-01', periods=182*240+1, freq='min', tz='UTC')
        p = pd.DataFrame(dict(c=100.), index=index); m = p.copy()
        m.loc[times[-1]-pd.Timedelta(minutes=1), 'c'] = 102
        a = basis_context(times, m, p)
        self.assertAlmostEqual(a.basis.iloc[-1], .02)
        self.assertEqual(a.basis_high.iloc[-1], 0.)
        self.assertTrue(a.basis_ready.iloc[-1])
        self.assertFalse(admission(1, a.iloc[-1], 'S09B'))
        m.loc[times[-1]:, 'c'] = 500
        pd.testing.assert_frame_equal(a, basis_context(times, m, p))

    def test_basis_gap_and_invalid_price_not_filled(self):
        times = pd.date_range('2025-01-01T04:00Z', periods=182, freq='4h')
        index = times-pd.Timedelta(minutes=1)
        p = pd.DataFrame(dict(c=100.), index=index); m = p.copy()
        m.iloc[-2, 0] = np.nan
        self.assertFalse(basis_context(times, m, p).basis_ready.iloc[-1])
        m.iloc[-1, 0] = -1
        self.assertTrue(np.isnan(basis_context(times, m, p).basis.iloc[-1]))

    def test_signed_crowding_and_equal_boundary(self):
        self.assertFalse(admission(1, ready(funding_rate=.002), 'S09F'))
        self.assertTrue(admission(-1, ready(funding_rate=.002), 'S09F'))
        self.assertFalse(admission(-1, ready(funding_rate=-.002), 'S09F'))
        self.assertTrue(admission(1, ready(funding_rate=.001), 'S09F'))
        self.assertFalse(admission(-1, ready(basis=-.02), 'S09B'))
        self.assertTrue(admission(1, ready(basis=-.02), 'S09B'))

    def test_combination_and_independent_missingness(self):
        row = ready(funding_ready=False)
        self.assertTrue(admission(1, row, 'S09B'))
        self.assertFalse(admission(1, row, 'S09FB'))
        self.assertTrue(admission(0, row, 'S09FB'))
        self.assertFalse(admission(1, ready(basis=.02), 'S09FB'))
        self.assertFalse(admission(1, ready(funding_rate=.002), 'S09FB'))

    def test_entry_only_veto_preserves_exit_and_control(self):
        minute = pd.DataFrame(index=pd.date_range('2025-01-01', periods=963, freq='min', tz='UTC'))
        core = {1: (1, 100., 1.), 241: (1, 100., 1.), 481: (-1, 100., 1.),
                721: (-1, 100., 1.), 961: (0, 100., 1.)}
        context = pd.DataFrame([vars(ready(funding_rate=x)) for x in (0., .002, -.002, 0., 0.)],
                               index=minute.index[[0, 240, 480, 720, 960]])
        result = build_crowding_policies(minute, core, context)
        self.assertEqual(result['T0'], core)
        self.assertEqual(result['S09F'][1][0], 1)
        self.assertNotIn(241, result['S09F'])
        self.assertEqual(result['S09F'][481][0], 0)
        self.assertEqual(result['S09F'][721][0], -1)
        self.assertEqual(result['S09F'][961][0], 0)
