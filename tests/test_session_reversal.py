import unittest
import numpy as np
import pandas as pd
from app.research.diagnostics.session_reversal import sessions, decisions, verify_signals, event_returns
from app.research.baseline.account import Costs


class SessionReversalTest(unittest.TestCase):
    def setUp(self):
        index = pd.date_range('2026-01-01', periods=8*1440, freq='min', tz='UTC')
        x = 100+np.arange(len(index))*.001+np.sin(np.arange(len(index))/300)
        self.m = pd.DataFrame(dict(o=x, h=x+.2, l=x-.2, c=x+.01, v=1.), index=index)
        self.start, self.end = '2026-01-05T00:00Z', '2026-01-07T00:00Z'

    def test_future_mutation_does_not_change_past_signal(self):
        rows = sessions(self.m, self.start, self.end)
        cut = pd.Timestamp(rows[0]['boundary'])
        changed = self.m.copy()
        changed.loc[changed.index >= cut, ['o','h','l','c']] *= 4
        other = sessions(changed, self.start, self.end)
        self.assertEqual(rows[0], other[0])
        self.assertEqual(verify_signals(self.m, rows)['status'], 'PASS')

    def test_same_session_lag_not_adjacent_session(self):
        b = pd.Timestamp('2026-01-05T08:00Z')
        # Yesterday's same session rises; the immediately preceding session falls.
        self.m.loc[b-pd.Timedelta(hours=24, minutes=1), 'c'] = 100
        self.m.loc[b-pd.Timedelta(hours=12, minutes=1), 'c'] = 120
        self.m.loc[b-pd.Timedelta(minutes=1), 'c'] = 110
        row = sessions(self.m, self.start, self.end)[0]
        self.assertEqual(row['side'], -1)

    def test_flat_boundary_and_no_late_session(self):
        rows = sessions(self.m, self.start, self.end)
        d = decisions(rows, 'REVERSAL')
        for row in rows:
            self.assertEqual(d[row['exit_minute']][0], 0)
            self.assertLess(pd.Timestamp(row['exit_time']), pd.Timestamp(self.end))
            self.assertEqual(row['exit_minute']-row['entry_minute'], 719)
        self.assertEqual(len(rows), 3)
        self.assertNotIn(rows[0]['entry_minute']+1, d)

    def test_funding_at_entry_excluded_exit_included(self):
        row = sessions(self.m, self.start, self.end)[0]
        events = [dict(fundingTime=int(pd.Timestamp(t).timestamp()*1000),
                       fundingRate='.001', markPrice='100')
                  for t in (row['entry_time'], row['exit_time'])]
        result = event_returns(self.m, [row], events, Costs(0,0,0), 'LONG')[0]
        self.assertEqual(len(result['funding_events']), 1)
        self.assertEqual(result['funding_events'][0]['settlement_ms'], events[1]['fundingTime'])
        self.assertAlmostEqual(result['funding_events'][0]['amount_per_btc'], .1)


if __name__ == '__main__':
    unittest.main()
