import unittest
from scripts.audit_microstructure_fitness import horizon_bounds, temporal_join_audit, trade_profile


class FitnessBoundaries(unittest.TestCase):
    def test_gaps_are_not_joined_into_long_windows(self):
        self.assertEqual(sum(horizon_bounds(0,12*10**9)['60'] for _ in range(10)),0)
        self.assertEqual(horizon_bounds(0,3*10**9)['3'],1)
        self.assertEqual(horizon_bounds(0,3*10**9-1)['3'],0)

    def test_event_time_does_not_override_later_availability(self):
        trades=[dict(data=dict(a=1,T=100),available_ns=500)]
        quotes=[dict(u=1,T=99,available_ns=400),dict(u=2,T=100,available_ns=600)]
        self.assertEqual(temporal_join_audit(trades,quotes)['later_available_quote_matches'],1)
        quotes[1]['available_ns']=500
        self.assertEqual(temporal_join_audit(trades,quotes)['later_available_quote_matches'],0)

    def test_no_prior_quote_is_not_a_valid_match(self):
        result=temporal_join_audit([dict(data=dict(a=1,T=99),available_ns=900)],
                                  [dict(u=1,T=100,available_ns=100)])
        self.assertEqual(result['event_time_matches'],0)

    def test_duplicate_conflict_and_id_gaps_remain_visible(self):
        rows=[dict(data=dict(a=i,T=t)) for i,t in [(1,0),(1,0),(1,2),(3,3),(2,4)]]
        r=trade_profile(rows)
        self.assertEqual((r['rows'],r['unique_ids'],r['duplicates'],r['conflicts'],r['gap_transitions'],r['backwards']), (5,3,2,1,1,1))
