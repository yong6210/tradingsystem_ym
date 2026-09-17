import unittest

import numpy as np
import pandas as pd

from app.research.candidate_accounts.pullback import episode_events, build_pullback_policies
from app.research.baseline.engine import policies
from app.research.multistrategy_audit import feature_bank


def context(n=12):
    return pd.DataFrame(dict(o=100., h=102., l=98., c=100., valid=True,
                             direction=1, displaced_side=0),
                        index=pd.date_range('2025-01-01', periods=n, freq='15min', tz='UTC'))


class PullbackTests(unittest.TestCase):
    def test_wait_then_confirm_and_consume_once(self):
        f = context(); f.loc[f.index[:3], 'displaced_side'] = 1
        f.loc[f.index[1], 'c'] = 103
        e, a = episode_events(f)
        self.assertEqual(e, {1: 1})
        self.assertEqual([r['kind'] for r in a], ['armed', 'confirmed'])

    def test_no_same_bar_confirmation(self):
        f = context(); f.loc[f.index[0], ['displaced_side', 'c']] = [1, 103]
        e, _ = episode_events(f)
        self.assertNotIn(0, e)

    def test_confirmation_needs_reversal_body_and_prior_extreme(self):
        f = context(); f.loc[f.index[0], 'displaced_side'] = 1
        f.loc[f.index[1], ['o', 'c']] = [104, 103]
        self.assertEqual(episode_events(f)[0], {})

    def test_short_symmetry(self):
        f = context(); f['direction'] = -1; f.loc[f.index[0], 'displaced_side'] = -1
        f.loc[f.index[1], 'c'] = 97
        self.assertEqual(episode_events(f)[0], {1: -1})

    def test_expiry_boundary_and_no_extension(self):
        f = context(); f['displaced_side'] = 1
        f.loc[f.index[8], 'c'] = 103
        self.assertEqual(episode_events(f)[0], {8: 1})
        f['c'] = 100.; f.loc[f.index[9], 'c'] = 103
        e, a = episode_events(f)
        self.assertEqual(e, {})
        self.assertEqual([r['kind'] for r in a], ['armed', 'expired'])

    def test_trend_flip_cancels_pending(self):
        f = context(); f.loc[f.index[0], 'displaced_side'] = 1
        f.loc[f.index[1]:, 'direction'] = -1; f.loc[f.index[1], 'c'] = 103
        e, a = episode_events(f)
        self.assertEqual(e, {})
        self.assertEqual(a[1]['kind'], 'invalidated')

    def test_invalid_data_cancels_pending(self):
        f = context(); f.loc[f.index[0], 'displaced_side'] = 1
        f.loc[f.index[1], ['valid', 'direction']] = [False, 0]
        self.assertEqual(episode_events(f)[1][1]['kind'], 'invalidated')

    def test_new_excursion_after_consumed_episode_can_reenter(self):
        f = context(); f.loc[f.index[[0, 3]], 'displaced_side'] = 1
        f.loc[f.index[[1, 4]], 'c'] = 103
        self.assertEqual(episode_events(f)[0], {1: 1, 4: 1})

    def test_real_signals_delay_reproduction_and_future_invariance(self):
        n = 45000
        index = pd.date_range('2025-01-01', periods=n, freq='min', tz='UTC')
        price = 100*np.exp(np.cumsum(np.random.default_rng(71).normal(0, .001, n)))
        m = pd.DataFrame(dict(o=price, c=price, h=price+.01, l=price-.01, v=1.), index=index)
        bank = feature_bank(m)
        a, c, audit = build_pullback_policies(m, bank)
        self.assertEqual(a['T0'], policies(m, bank)['T0'])
        self.assertGreater(sum(s != 0 for s, _, _ in a['P4'].values()), 0)
        self.assertEqual(a['P4'].keys(), a['P15'].keys())
        self.assertTrue(all(i % 15 == 1 for i in a['P4']))
        changed = m.copy(); changed.iloc[40000:, :4] *= 2
        b, _, _ = build_pullback_policies(changed, feature_bank(changed))
        for name in a:
            self.assertEqual({i:v for i,v in a[name].items() if i<=40000},
                             {i:v for i,v in b[name].items() if i<=40000})
        for k in range(1, len(c)):
            if c.valid.iloc[k] and c.direction.iloc[k] != c.direction.iloc[k-1]:
                pos = m.index.get_indexer([c.index[k]])[0]+1
                if pos < n: self.assertEqual(a['P4'][pos][0], 0)
