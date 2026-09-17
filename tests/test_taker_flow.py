import io
import unittest
from zipfile import ZipFile

import numpy as np
import pandas as pd

from app.research.data.taker_flow import parse_flow, validate_flow, completed_flow
from app.research.candidate_accounts.flow import flow_conditions, build_flow_policy
from app.research.candidate_accounts.policies import build_policy
from app.research.multistrategy_audit import feature_bank


def raw_frame(n=120):
    index = pd.date_range('2025-01-01', periods=n, freq='min', tz='UTC')
    return pd.DataFrame(dict(o=100., h=101., l=99., c=100., v=2., quote_volume=200.,
                             count=2, taker_buy_volume=1.5, taker_buy_quote_volume=150.), index=index)


def policy_fixture():
    minute = raw_frame(301)
    index = pd.date_range('2025-01-01T01:00Z', periods=4, freq='h')
    f = pd.DataFrame(dict(c=[111., 112., 100., 79.], atr=2., high24=110., low24=80.,
                         high12=108., low12=82., volume_ratio=2.), index=index)
    bank = {60: f, 240: pd.DataFrame(dict(er=.2, ema80=100.), index=index)}
    hour = pd.DataFrame(dict(buy_share=[.4, .8, .5, .4]), index=index)
    return minute[['o', 'h', 'l', 'c', 'v']], bank, hour


class TakerFlowTests(unittest.TestCase):
    def test_parser_close_time_and_schema(self):
        def zipped(close):
            data = io.BytesIO()
            with ZipFile(data, 'w') as z:
                z.writestr('x.csv', 'open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume\n'
                           f'1735689600000,100,101,99,100,2,{close},200,2,1.5,150\n')
            return data.getvalue()
        self.assertEqual(len(parse_flow(zipped(1735689659999), 'x.csv')), 1)
        with self.assertRaises(ValueError):
            parse_flow(zipped(1735689660000), 'x.csv')

    def test_invalid_fields_rejected(self):
        for field, value in [('taker_buy_volume', 3), ('taker_buy_quote_volume', 201),
                             ('count', .5), ('count', 0), ('quote_volume', 500), ('v', -1),
                             ('taker_buy_volume', np.nan)]:
            with self.subTest(field=field, value=value):
                f = raw_frame().astype(float); f.loc[f.index[0], field] = value
                with self.assertRaises(ValueError):
                    validate_flow(f)

    def test_missing_duplicate_minutes_rejected(self):
        f = raw_frame()
        for bad in (f.drop(f.index[3]), pd.concat([f.iloc[:2], f.iloc[1:]])):
            with self.assertRaises(ValueError):
                validate_flow(bad)

    def test_zero_volume_is_unknown_not_sell(self):
        f = raw_frame(); f.loc[:, ['v', 'quote_volume', 'count', 'taker_buy_volume', 'taker_buy_quote_volume']] = 0
        self.assertTrue(completed_flow(f).buy_share.isna().all())

    def test_weighted_share_not_mean_of_ratios(self):
        f = raw_frame(61)
        f.loc[f.index[:30], ['v', 'quote_volume', 'taker_buy_volume', 'taker_buy_quote_volume']] = [10., 1000., 2., 200.]
        h = completed_flow(f)
        self.assertEqual(len(h), 1)
        self.assertEqual(h.index[0], pd.Timestamp('2025-01-01T01:00Z'))
        self.assertAlmostEqual(h.buy_share.iloc[0], (30*2+30*1.5)/(30*10+30*2))

    def test_alignment_short_and_neutral(self):
        m, b, h = policy_fixture()
        c = flow_conditions(b, h, 'S06A')
        self.assertFalse(c.event.iloc[0]); self.assertTrue(c.event.iloc[3])
        h.iloc[3, 0] = .5
        self.assertFalse(flow_conditions(b, h, 'S06A').event.iloc[3])
        h.iloc[3, 0] = np.nan
        self.assertFalse(flow_conditions(b, h, 'S06A').event.iloc[3])

    def test_filter_change_does_not_create_new_breakout(self):
        m, b, h = policy_fixture()
        d = build_flow_policy(m, b, h, 'S06A')
        self.assertNotIn(61, d); self.assertNotIn(121, d)
        self.assertEqual(d[241][0], -1)

    def test_exit_does_not_require_flow_alignment(self):
        m, b, h = policy_fixture(); h.iloc[0, 0] = .8
        b[60].iloc[2, b[60].columns.get_loc('c')] = 81.
        d = build_flow_policy(m, b, h, 'S06A')
        self.assertEqual(d[61][0], 1)
        self.assertNotIn(121, d)
        self.assertEqual(d[181][0], 0)

    def test_control_exact_and_index_mismatch_rejected(self):
        m, b, h = policy_fixture()
        self.assertEqual(build_flow_policy(m, b, h, 'S02'), build_policy(m, b, 'S02')[0])
        with self.assertRaises(ValueError):
            flow_conditions(b, h.iloc[1:], 'S06A')

    def test_future_mutation_invariance_and_delay(self):
        n = 30000
        f = raw_frame(n)
        rng = np.random.default_rng(93)
        price = 100*np.exp(np.cumsum(rng.normal(0, .001, n)))
        f['o'] = f['c'] = price; f['h'] = price+.01; f['l'] = price-.01
        f['v'] = rng.uniform(2, 20, n)
        f['taker_buy_volume'] = f.v * (.5 + .3*np.sin(np.arange(n)/1000))
        f['quote_volume'] = f.v * price; f['taker_buy_quote_volume'] = f.taker_buy_volume * price
        altered = f.copy(); altered.iloc[27000:, altered.columns.get_loc('taker_buy_volume')] = .1
        altered['taker_buy_quote_volume'] = altered.taker_buy_volume * altered.c
        m = f[['o', 'h', 'l', 'c', 'v']]; bank = feature_bank(m)
        x = build_flow_policy(m, bank, completed_flow(f), 'S06A')
        y = build_flow_policy(m, bank, completed_flow(altered), 'S06A')
        self.assertGreater(sum(v[0] != 0 for v in x.values()), 0)
        self.assertEqual({i:v for i,v in x.items() if i<=27000}, {i:v for i,v in y.items() if i<=27000})
        self.assertTrue(all(i % 60 == 1 for i in x))
        a = flow_conditions(bank, completed_flow(f), 'S06A')
        b = flow_conditions(bank, completed_flow(f), 'S02')
        self.assertTrue((~a.event | b.event).all())
