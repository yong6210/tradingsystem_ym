"""Synthetic fixtures only; these are not Q004 observations."""
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from app.research.diagnostics.prospective_evaluation import evaluate,aggregate,sha
from app.research.diagnostics.prospective_price import score_unit


def write(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj))


class ProspectiveEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.folder=self.root/'evidence'
        self.b=datetime(2026,1,1,tzinfo=timezone.utc);self.day=self.folder/'2026-01-01'
        self.policy=dict(first_boundary_utc=self.b.isoformat(),calendar_days=3,price_tick='0.1',
            event_selectors={'original_H':1,'exploratory_2H':2},cost_scenarios={
                'base':dict(fee_bps=2.5,slippage_bps=2,extra_funding_bps_per_settlement=0),
                'stress':dict(fee_bps=2.5,slippage_bps=5,extra_funding_bps_per_settlement=1)})
        write(self.folder/'registration.json',dict(policy=self.policy,source_hashes={},protected_hashes={}))
        rh=sha(self.folder/'registration.json')
        write(self.folder/'ready.json',dict(registration_sha256=rh))
        pub=self.day/'publish';write(pub/'input.json',{'synthetic':True})
        self.record=dict(boundary=self.b.isoformat(),prediction_bps=30.,threshold_bps=20.,controls={'MEAN180':10.,'ZERO':0.},
            selectors={'original_H':1,'exploratory_2H':0},created_at_utc=(self.b+timedelta(seconds=8)).isoformat(),
            entry_time=(self.b+timedelta(minutes=1)).isoformat(),exit_time=(self.b+timedelta(days=1)).isoformat(),
            actual_order=False,outcome_observed=False,registration_sha256=rh,input_hashes={'input.json':sha(pub/'input.json')})
        write(pub/'forecast.json',self.record)
        write(pub/'publication_receipt.json',dict(status='PUBLISHED_BEFORE_TARGET',committed_at_utc=(self.b+timedelta(seconds=9)).isoformat(),
            target_start_utc=self.record['entry_time'],forecast_sha256=sha(pub/'forecast.json')))
        write(self.day/'verification.json',dict(status='PASS',boundary=self.b.isoformat(),artifacts={
            'registration':rh,'forecast':sha(pub/'forecast.json'),'publication_receipt':sha(pub/'publication_receipt.json')}))

    def tearDown(self):self.tmp.cleanup()

    def scoring(self):
        folder=self.day/'score';start=int(self.b.timestamp()*1000);entry=start+60000;exit=start+86400000
        t=(self.b+timedelta(days=1,minutes=1,seconds=2)).timestamp()
        def candle(ms,price):return [[ms,str(price),str(price+1),str(price-1),str(price),'1',ms+59999,'0',1,'0','0','0']]
        funding=[dict(symbol='BTCUSDC',fundingTime=start+h*3600000,fundingRate='0.0001',markPrice='10100') for h in (0,8,16,24)]
        payloads=[('/fapi/v1/time',{'serverTime':int((t+.05)*1000)}),
            (f'/fapi/v1/klines?symbol=BTCUSDC&interval=1m&startTime={entry}&endTime={entry+59999}&limit=1500',candle(entry,10000)),
            (f'/fapi/v1/klines?symbol=BTCUSDC&interval=1m&startTime={exit}&endTime={exit+59999}&limit=1500',candle(exit,10100)),
            (f'/fapi/v1/fundingRate?symbol=BTCUSDC&startTime={entry-86400000}&endTime={exit+59999}&limit=1000',funding)]
        for i,(url,data) in enumerate(payloads,1):
            raw=folder/f'{i:03d}.raw.json';write(raw,data)
            write(folder/f'{i:03d}.receipt.json',dict(url='https://fapi.binance.com'+url,status=200,sha256=sha(raw),
                requested_epoch=t,received_epoch=t+.1,elapsed_seconds=.1,wall_monotonic_drift_seconds=0))
        events={name:{cost:score_unit(10000,10100,side,funding,entry,exit,p['fee_bps'],p['slippage_bps'],p['extra_funding_bps_per_settlement'])
            for cost,p in self.policy['cost_scenarios'].items()} for name,side in self.record['selectors'].items()}
        write(folder/'outcome.json',dict(status='UNIT_EVENT_PROXY_NOT_ACCOUNT_OR_REAL_FILL',boundary=self.b.isoformat(),
            scored_at_utc=datetime.fromtimestamp(t+1,timezone.utc).isoformat(),target_bps=100.,
            prediction_errors={'PRICE':-70.,'MEAN180':-90.,'ZERO':-100.},events=events,requests=4,
            forecast_sha256=sha(self.day/'publish/forecast.json'),artifacts={p.name:sha(p) for p in folder.iterdir()}))

    def result(self):return evaluate(self.root,self.folder,self.b+timedelta(days=1,minutes=2))

    def test_no_observation_is_null_not_zero(self):
        r=evaluate(self.root,self.folder,self.b+timedelta(minutes=40))
        self.assertEqual(r['counts'],{'PENDING_OUTCOME':1,'FUTURE':2})
        self.assertEqual(r['observed_scored_days'],0)
        self.assertIsNone(r['metrics']['forecast_metrics']['PRICE']['mse_bps2'])
        self.assertIsNone(r['metrics']['event_metrics']['original_H']['costs']['base']['sum_unit_event_bps'])

    def test_missed_and_unresolved_are_not_calendar_zeros(self):
        r=self.result()
        self.assertEqual(r['counts'],{'UNRESOLVED_OUTCOME':1,'MISSED_PUBLICATION':1,'FUTURE':1})
        self.assertEqual(r['observed_scored_days'],0)

    def test_independent_raw_score_reconstruction_and_flat_denominator(self):
        self.scoring();r=self.result()
        self.assertEqual(r['observed_scored_days'],1)
        self.assertEqual(r['metrics']['forecast_metrics']['PRICE']['mse_bps2'],4900.)
        self.assertEqual(r['metrics']['price_mse_minus_control_bps2'],{'MEAN180':-3200.,'ZERO':-5100.})
        flat=r['metrics']['event_metrics']['exploratory_2H']
        self.assertEqual(flat['flat_days'],1)
        self.assertEqual(flat['costs']['base']['mean_per_scored_day_bps'],0.)
        self.assertIsNone(flat['costs']['base']['mean_per_active_event_bps'])
        self.assertEqual(r['counts']['MISSED_PUBLICATION'],1)

    def test_numeric_outcome_tampering_rejected(self):
        self.scoring();p=self.day/'score/outcome.json';out=json.loads(p.read_text())
        out['events']['original_H']['base']['net_bps']='999';write(p,out)
        r=self.result();self.assertEqual(r['counts']['INVALID_OUTCOME'],1);self.assertEqual(r['observed_scored_days'],0)

    def test_missing_funding_detected_even_when_hashes_rebound(self):
        self.scoring();folder=self.day/'score';p=folder/'004.raw.json';rows=json.loads(p.read_text());write(p,rows[:-1])
        rp=folder/'004.receipt.json';receipt=json.loads(rp.read_text());receipt['sha256']=sha(p);write(rp,receipt)
        op=folder/'outcome.json';out=json.loads(op.read_text());out['artifacts'].update({p.name:sha(p),rp.name:sha(rp)});write(op,out)
        r=self.result();self.assertEqual(r['counts']['INVALID_OUTCOME'],1)
        self.assertIn('funding endpoints',r['states'][0]['reason'])

    def test_late_publication_and_early_outcome_are_not_scored(self):
        self.scoring()
        early=evaluate(self.root,self.folder,self.b+timedelta(hours=2))
        self.assertEqual(early['counts']['INVALID_OUTCOME'],1)
        rp=self.day/'publish/publication_receipt.json';receipt=json.loads(rp.read_text())
        receipt['committed_at_utc']=(self.b+timedelta(seconds=51)).isoformat();write(rp,receipt)
        self.assertEqual(self.result()['counts']['INVALID_PUBLICATION'],1)

    def test_changed_source_and_orphan_score_fail_closed(self):
        write(self.day/'publish/input.json',{'synthetic':'changed'})
        self.assertEqual(self.result()['counts']['INVALID_PUBLICATION'],1)
        write(self.folder/'2026-01-02/score/outcome.json',{})
        self.assertEqual(self.result()['counts']['INVALID_OUTCOME'],1)

    def test_aggregation_uses_paired_days_and_active_denominators(self):
        rows=[dict(target_bps=y,estimates={'PRICE':p,'MEAN180':0.,'ZERO':0.},selectors={'H':side},net_bps={'H':{'base':net}})
              for y,p,side,net in [(10.,20.,1,5.),(-10.,0.,0,0.)]]
        result=aggregate(rows,['H'],['base'])
        self.assertEqual(result['forecast_metrics']['PRICE']['mse_bps2'],100.)
        m=result['event_metrics']['H']['costs']['base']
        self.assertEqual(m,{'sum_unit_event_bps':5.,'mean_per_scored_day_bps':2.5,'mean_per_active_event_bps':5.})


if __name__=='__main__':unittest.main()
