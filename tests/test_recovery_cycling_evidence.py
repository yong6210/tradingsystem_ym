import unittest,json
from copy import deepcopy
from app.research.recovery.thesis_evidence import ThesisEvidenceRegistry,validated_assessment
from app.research.recovery.cycling_orders import CyclingOrders
import test_recovery_cycling_orders as fixtures
from test_recovery_cycling_thesis import assessment


def records():
    return [dict(id=k,available_ms=100,event_key='same-price-same-bar',source_sha256='a'*64)
            for k in ('structure:v1','zone:v2')]


class EvidenceTests(unittest.TestCase):
    def test_exists_and_available_not_votes(self):
        reg=ThesisEvidenceRegistry(records())
        r=reg.resolve(['structure:v1','zone:v2'],observed_ms=100)
        self.assertEqual(len(r['body']['provenance_groups']),1)
        self.assertFalse(r['body']['market_direction_verified'])
        for ids,time in [(['absent'],100),(['structure:v1'],99),(['structure:v1']*2,100)]:
            with self.assertRaises(ValueError):reg.resolve(ids,observed_ms=time)

    def test_registry_and_result_isolation(self):
        data=records();reg=ThesisEvidenceRegistry(data);data[0]['available_ms']=0
        r=reg.resolve(['structure:v1'],observed_ms=100);r['body']['records'][0]['available_ms']=0
        with self.assertRaises(ValueError):reg.resolve(['structure:v1'],observed_ms=99)

    def test_invalid_evidence_no_state_mutation(self):
        _,o,_,_=fixtures.CyclingOrderTests().setup_case();before=deepcopy(o.checkpoint())
        a=assessment('reversal');a['evidence_ids']=['absent']
        with self.assertRaises(ValueError):o.set_direction_from_evidence(1,registry=ThesisEvidenceRegistry(records()),
            assessment=a,timeframe='multi',observed_ms=101,reason='scenario')
        self.assertEqual(before,o.checkpoint())

    def test_valid_gateway_and_checkpoint(self):
        _,o,_,_=fixtures.CyclingOrderTests().setup_case()
        o.set_direction_from_evidence(-1,registry=ThesisEvidenceRegistry(records()),assessment=assessment('maintain'),
            timeframe='multi',observed_ms=101,reason='scenario')
        restored=CyclingOrders.restore(json.loads(json.dumps(o.checkpoint())))
        self.assertEqual(restored.model.events,o.model.events)
        self.assertTrue(restored.restart_required)

    def test_tampered_snapshot_rejected(self):
        _,o,_,_=fixtures.CyclingOrderTests().setup_case()
        a=validated_assessment(ThesisEvidenceRegistry(records()),assessment('maintain'),observed_ms=101)
        a['evidence_audit']['body']['records'][0]['available_ms']=102
        with self.assertRaises(ValueError):o.set_direction(-1,assessment=a,timeframe='multi',observed_ms=101,reason='scenario')

    def test_duplicate_registry_rejected(self):
        with self.assertRaises(ValueError):ThesisEvidenceRegistry(records()*2)


if __name__=='__main__':unittest.main()
