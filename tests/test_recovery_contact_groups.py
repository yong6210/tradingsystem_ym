import unittest
from copy import deepcopy
from app.research.recovery.contact_groups import group_contacts


def item(key='a',price=100,t=120000,kind='high',close=99):
    return dict(candidate=dict(id=key,price=price,available_ms=60000,kind=kind,timeframe_minutes=15),
                review=dict(first_new_contact=dict(available_ms=t,close=close)))


class ContactGroupTests(unittest.TestCase):
    def test_same_price_time_merge_keep_sources(self):
        a=item();b=item('b',price='100.0')
        result=group_contacts([a,b],asof_ms=120000)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['source_count'],2)
        self.assertEqual(result,group_contacts([b,a,a],asof_ms=120000))

    def test_nearby_prices_or_later_time_remain_separate(self):
        r=group_contacts([item(),item('b',100.1),item('c',t=180000)],asof_ms=180000)
        self.assertEqual(len(r),3)

    def test_future_excluded_and_sources_not_mutated(self):
        data=[item(),item('b',t=180000)];copy=deepcopy(data)
        self.assertEqual(group_contacts(data,asof_ms=120000),group_contacts(data[:1],asof_ms=120000))
        self.assertEqual(data,copy)

    def test_roles_preserved_without_direction_inference(self):
        r=group_contacts([item(),item('b',kind='low')],asof_ms=120000)[0]
        self.assertEqual(r['marker_roles'],['high','low'])
        self.assertEqual(r['independent_evidence'],'unassessed')
        self.assertEqual(r['orders_generated'],0)

    def test_conflict_and_premature_contact_rejected(self):
        for data in ([item(),item('b',close=98)],[item(),item(t=180000)],[item(t=60000)]):
            with self.assertRaises(ValueError):group_contacts(data,asof_ms=180000)


if __name__=='__main__':unittest.main()
