import unittest
from app.research.recovery.structure_lineage import candidate_lineage


def c(key,price=105,available=30,start=0):
    return dict(id=key,kind='low',price=price,available_ms=available,
                evidence_start_ms=start,pivot_bar_end_ms=available-10)


class LineageTests(unittest.TestCase):
    def test_future_not_used_and_prefix_stable(self):
        a=c('a');b=c('b',available=60,start=30)
        prefix=candidate_lineage([a,b],[],asof_ms=30)
        full=candidate_lineage([a,b],[],asof_ms=60)
        self.assertEqual(prefix,full[:1])
        self.assertEqual(full[1]['same_price_known_ids'],['a'])
        self.assertEqual(full[1]['overlapping_evidence_ids'],[])

    def test_simultaneous_candidates_not_input_order_dependent(self):
        a=c('a');b=c('b')
        first=candidate_lineage([a,b],[],asof_ms=30)
        self.assertEqual(first,candidate_lineage([b,a],[],asof_ms=30))
        self.assertEqual(first[0]['overlapping_evidence_ids'],['b'])

    def test_future_band_excluded_outside_not_approved(self):
        bands=[dict(id='old',low=90,high=100,available_ms=0),dict(id='future',low=100,high=110,available_ms=40)]
        row=candidate_lineage([c('a')],bands,asof_ms=100)[0]
        self.assertEqual(row['band_relations'],[dict(basis_id='old',location='above')])
        self.assertEqual(row['independent_basis'],'unassessed')
        self.assertFalse(row['entry_approved'])

    def test_duplicate_and_bad_chronology_rejected(self):
        with self.assertRaises(ValueError):candidate_lineage([c('a'),c('a')],[],asof_ms=30)
        with self.assertRaises(ValueError):candidate_lineage([c('a',start=25)],[],asof_ms=30)


if __name__=='__main__': unittest.main()
