from dataclasses import replace
import json
import unittest
import pandas as pd
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.baseline.engine import policies
from app.research.multistrategy_audit import frame_features
from app.research.diagnostics.intrabar_engine import simulate
from app.research.observation.bar_account import BarAccount
from app.research.observation.t0_signal import T0Signal
from app.research.observation.checkpoint import seal,unseal


def bar(when=0, price=60000., **extra):
    return dict(open_ms=when,o=price,h=price,l=price,c=price,received_ms=when+60000,
                evidence_kind='HISTORICAL_REPLAY') | extra


class BarObservationTests(unittest.TestCase):
    def test_checkpoint_does_not_close_position(self):
        engine=BarAccount()
        out=engine.step(bar(),(1,60000,500))
        self.assertEqual(len(out['events']),1)
        restored=BarAccount.restore(json.loads(json.dumps(engine.checkpoint())))
        self.assertEqual(restored.account.quantity,engine.account.quantity)
        self.assertEqual(restored.step(bar(60000))['events'],[])
        self.assertEqual(restored.finish()['trades'][0]['reason'],'end_exit')

    def test_duplicate_gap_and_unclosed_rejected_without_state_change(self):
        engine=BarAccount();engine.step(bar())
        saved=engine.checkpoint()
        for invalid in (bar(),bar(120000),bar(60000,received_ms=60000),bar(60000,h=1)):
            with self.assertRaises(ValueError):engine.step(invalid)
            self.assertEqual(engine.checkpoint(),saved)

    def test_closed_bar_cannot_claim_live_execution(self):
        with self.assertRaises(ValueError):BarAccount().step(bar(evidence_kind='FORWARD_LIVE'))

    def test_finished_account_cannot_resume(self):
        engine=BarAccount();engine.step(bar());engine.finish()
        restored=BarAccount.restore(json.loads(json.dumps(engine.checkpoint())))
        with self.assertRaises(ValueError):restored.step(bar(60000))
        with self.assertRaises(ValueError):restored.finish()

    def test_bad_funding_rejected_before_mutation(self):
        engine=BarAccount();engine.step(bar(),(1,60000,500));saved=engine.checkpoint()
        for events in ([dict(fundingTime=0,fundingRate='0.001',markPrice='60000')],
                       [dict(fundingTime=60001,fundingRate='0.001',markPrice='60000')],
                       [dict(fundingTime=1,fundingRate='nan',markPrice='60000')]):
            with self.assertRaises(ValueError):engine.step(bar(60000),funding=events)
            self.assertEqual(engine.checkpoint(),saved)

    def test_generator_funding_is_not_consumed_by_validation(self):
        engine=BarAccount();engine.step(bar(),(1,60000,500))
        out=engine.step(bar(60000),funding=(e for e in [dict(fundingTime=1,fundingRate='.001',markPrice='60000')]))
        self.assertEqual(out['events'][0]['kind'],'funding')

    def test_binding_and_checksum_changes_rejected(self):
        wrapped=seal(BarAccount().checkpoint(),{'engine':'abc'})
        self.assertEqual(unseal(wrapped,{'engine':'abc'})['version'],1)
        with self.assertRaises(ValueError):unseal(wrapped,{'engine':'xyz'})
        wrapped['payload']['state']['state']['peak']=999
        with self.assertRaises(ValueError):unseal(wrapped,{'engine':'abc'})

    def test_stream_and_json_resume_match_batch_path_with_risk_stop(self):
        risk=Risk(initial=1000,cycle_fraction=.1,aggregate_fraction=.1,exposure_multiple=1,
                  daily_stop=.9,warning=.05,halt=.08,minimum_qty=1,step=1,minimum_notional=1,
                  stop_atr=1,maximum_hold_minutes=100)
        costs=Costs(0,0,0,.01)
        frame=pd.DataFrame([(100,100,100,100),(100,200,90,190)],columns=['o','h','l','c'],
            index=pd.date_range('2025-01-01',periods=2,freq='min',tz='UTC'))
        for path in ('OHLC','OLHC'):
            expected=simulate(frame,{0:(1,100,90)},frame.index[0],frame.index[-1]+pd.Timedelta(minutes=1),costs,risk,path=path)
            engine=BarAccount(costs=costs,risk=risk,path=path)
            actual={key:[] for key in ('events','trades','daily','rejections','path_stops')}
            for i,(stamp,row) in enumerate(frame.iterrows()):
                when=int(stamp.value//1000000)
                out=engine.step(bar(when,**row.to_dict()),(1,100,90) if i==0 else None)
                for key in actual:actual[key]+=out[key]
                engine=BarAccount.restore(json.loads(json.dumps(engine.checkpoint())))
            end=engine.finish()
            for key in actual:
                actual[key]+=end[key];self.assertEqual(actual[key],expected[key])
            self.assertEqual(engine.metrics(end['preclose_equity']),expected['metrics'])

    def test_signal_stream_matches_completed_batch_and_bounded_state(self):
        start=1704067200000
        data=[];observed={};signal=T0Signal()
        for i in range(240*82+2):
            price=60000+(i//240)%7*100
            record=bar(start+i*60000,price,h=price+50,l=price-50)
            found=signal.step(record)
            data.append([record[k] for k in ('o','h','l','c')]+[1])
            if found:observed[int((found['scheduled_ms']-start)//60000)]=found
            if i in (100,19200):signal=T0Signal.restore(json.loads(json.dumps(signal.checkpoint())))
        frame=pd.DataFrame(data,columns=['o','h','l','c','v'],index=pd.date_range('2024-01-01',periods=len(data),freq='min',tz='UTC'))
        expected=policies(frame,{240:frame_features(frame,240)})['T0']
        self.assertEqual(set(observed),set(expected))
        for index,row in observed.items():
            side,close,atr=expected[index]
            self.assertEqual(row['side'],side);self.assertEqual(row['close'],close)
            self.assertAlmostEqual(row['atr'],atr,places=8)
        self.assertLess(len(json.dumps(signal.checkpoint())),1200)

    def test_late_signal_receipt_is_not_backdated(self):
        signal=T0Signal();found=None
        for i in range(240*80):
            record=bar(i*60000,60000+i//240,h=60100+i//240,l=59900+i//240)
            if i==240*80-1:record['received_ms']+=600000
            found=signal.step(record)
        self.assertGreater(found['earliest_observable_ms'],found['scheduled_ms'])
        self.assertEqual(found['earliest_observable_ms'],found['received_ms'])

    def test_flat_er_mask_and_initial_partial_bucket(self):
        signal=T0Signal()
        for i in range(1,240*82):self.assertIsNone(signal.step(bar(i*60000)))
        self.assertEqual(signal.completed,81)

    def test_signal_rejects_gap_without_mutating(self):
        signal=T0Signal();signal.step(bar());saved=signal.checkpoint()
        with self.assertRaises(ValueError):signal.step(bar(120000))
        self.assertEqual(signal.checkpoint(),saved)


if __name__=='__main__':unittest.main()
