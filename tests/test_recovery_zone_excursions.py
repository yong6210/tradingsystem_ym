import unittest
from app.research.recovery.zone_excursions import observe_excursions


def rows(values):return [dict(end_ms=(i+1)*60000,low=l,high=h,close=c) for i,(l,h,c) in enumerate(values)]
def run(data):return observe_excursions(data,low=100,high=110)


class ExcursionTests(unittest.TestCase):
    def test_departure_return_extremes_exclude_return_bar(self):
        r=run(rows([(105,112,111),(112,115,114),(114,120,116),(99,130,108)]))
        leg=r['completed_legs'][0]
        self.assertEqual(leg['outside_high'],120)
        self.assertEqual(leg['outside_minutes'],2)
        self.assertEqual(leg['return_position'],'inside')

    def test_initial_outside_does_not_invent_departure(self):
        self.assertEqual(run(rows([(112,115,114),(105,112,111)]))['events'],[])

    def test_gap_not_return_and_prefix_immutable(self):
        data=rows([(105,112,111),(112,115,114),(90,95,92)])
        self.assertEqual(run(data)['completed_legs'][0]['status'],'gap_across_without_observed_contact')
        self.assertEqual(run(data[:2])['events'],run(data)['events'][:1])

    def test_invalid_gap_rejected(self):
        with self.assertRaises(ValueError):run(rows([(105,112,111)]*3)[::2])


if __name__=='__main__':unittest.main()
