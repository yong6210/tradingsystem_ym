"""E018: streaming signals/account parity with serialized state handoffs."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.baseline.account import Costs
from app.research.baseline.engine import policies
from app.research.multistrategy_audit import frame_features
from app.research.data.btcusdc import load_public_bundle
from app.research.comparison.funding import funding_schedule
from app.research.observation.bar_account import BarAccount
from app.research.observation.t0_signal import T0Signal
from app.research.observation.checkpoint import seal,unseal,canonical
from scripts.run_direction_controls import save,load,lines,digest,test_ids,verify_daily
from scripts.run_btcusdc_comparison import annual
from scripts.report_btcusdc_comparison import verify_run


def main(output):
    previous=ROOT/'reports/validation/e017_concentration_20260919'
    reg=load(previous/'registration.json')
    sources=dict(reg['source_hashes'])
    for name in ('app/research/observation/bar_account.py','app/research/observation/t0_signal.py',
                 'app/research/observation/checkpoint.py','scripts/verify_incremental_bars.py',
                 'tests/test_bar_observation.py','tests/test_intrabar_risk_paths.py',
                 'app/research/diagnostics/intrabar_engine.py',
                 'docs/research/experiments/E018_INCREMENTAL_BAR_PARITY.md'):
        sources[name]=digest(ROOT/name)
    old=dict(reg['prior_artifact_hashes'])
    prior_receipt=load(previous/'verification.json')
    for name,h in prior_receipt['artifact_hashes'].items():
        if digest(previous/name)!=h:raise ValueError('E017 artifact changed')
    for p in previous.rglob('*'):
        if p.is_file():old[str(p.relative_to(ROOT))]=digest(p)
    for name,h in old.items():
        if digest(ROOT/name)!=h:raise ValueError('prior evidence changed: '+name)
    suite=unittest.defaultTestLoader.loadTestsFromNames(('tests.test_bar_observation',
        'tests.test_intrabar_risk_paths','tests.test_baseline_account','tests.test_direction_controls'))
    ids=list(test_ids(suite))
    settings=load(ROOT/'reports/validation/e015_intrabar_risk_paths_20260918/registration.json')['settings']
    binding=dict(source_hashes=sources,risk=settings['risk'],costs=settings['costs'],path='OHLC',
                 evidence_kind='HISTORICAL_REPLAY',receipt_clock='SIMULATED_BAR_CLOSE_NOT_MEASURED_RECEIPT')
    save(output/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
        classification='OFFLINE_INCREMENTAL_PARITY_NOT_FORWARD_EVIDENCE',source_hashes=sources,
        prior_artifact_hashes=old,test_ids=ids,settings=dict(start=settings['start'],end=settings['end'],
            models=['T0'],costs=settings['costs'],path='OHLC',checkpoint='DAILY_AND_FIRST_OPEN_POSITION'),
        automatic_retries=0,binding=binding))
    for name,h in sources.items():
        if digest(ROOT/name)!=h:raise ValueError('source changed: '+name)
        p=output/'source_snapshot'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/name).read_bytes())
    with (output/'tests.log').open('x') as stream:
        tested=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    save(output/'tests.json',dict(registered=len(ids),executed=tested.testsRun,
        failures=len(tested.failures),errors=len(tested.errors),skipped=len(tested.skipped)))
    if not tested.wasSuccessful() or tested.skipped or tested.testsRun!=len(ids):raise ValueError('tests failed')
    print('Registered tests passed; loading pinned bars and batch signal reference.',flush=True)
    bundle=load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917')
    bundle.require_complete_window(settings['start'],settings['end'])
    minutes=bundle.trade
    expected=policies(minutes,{240:frame_features(minutes,240)})['T0']
    lower=int(minutes.index.searchsorted(pd.Timestamp(settings['start'])))
    upper=int(minutes.index.searchsorted(pd.Timestamp(settings['end'])))
    engines={key:BarAccount(costs=Costs(**cost),first_index=lower) for key,cost in settings['costs'].items()}
    output_names=('events','trades','daily','rejections','path_stops')
    results={key:{name:[] for name in output_names} for key in engines}
    signal=T0Signal();pending=None;seen=set();transfers=0;max_checkpoint_bytes=0;max_signal_bytes=0
    first_open_checkpoint=False;checkpoints=[]
    schedule=funding_schedule(minutes.index,bundle.funding)
    def append(key,delta):
        for name in output_names:results[key][name].extend(delta[name])
    arrays=minutes[['o','h','l','c']].to_numpy()
    ms=minutes.index.asi8//1000000
    for i,(op,hi,lo,cl) in enumerate(arrays):
        when=int(ms[i])
        record=dict(open_ms=when,o=float(op),h=float(hi),l=float(lo),c=float(cl),
                    received_ms=when+60000,evidence_kind='HISTORICAL_REPLAY')
        decision=None
        if pending and pending['scheduled_ms']==when:
            decision=(pending['side'],pending['close'],pending['atr']);pending=None
        if lower<=i<upper:
            for key,engine in engines.items():append(key,engine.step(record,decision,schedule.get(i,())))
        found=signal.step(record)
        if found:
            index=int(minutes.index.searchsorted(pd.Timestamp(found['scheduled_ms'],unit='ms',tz='UTC')))
            if index<len(minutes):
                if index not in expected:raise ValueError('unexpected streaming decision')
                side,price,atr=expected[index]
                if found['side']!=side or found['close']!=price or abs(found['atr']-atr)>1e-8:
                    raise ValueError('streaming signal differs from batch')
                seen.add(index)
            pending=found
        is_first_open=not first_open_checkpoint and any(e.account.quantity for e in engines.values())
        if (when+60000)%86400000==0 or is_first_open:
            payload=dict(signal=signal.checkpoint(),pending=pending,
                         accounts={key:e.checkpoint() for key,e in engines.items()},next_source_index=i+1)
            envelope=seal(payload,binding)
            raw=canonical(envelope)
            state=unseal(json.loads(raw),binding)
            max_checkpoint_bytes=max(max_checkpoint_bytes,len(raw))
            max_signal_bytes=max(max_signal_bytes,len(canonical(payload['signal'])))
            signal=T0Signal.restore(state['signal']);pending=state['pending']
            engines={key:BarAccount.restore(value) for key,value in state['accounts'].items()}
            # Store monthly boundaries and the in-position handoff; daily JSON
            # roundtrips are counted but are not separate process crash tests.
            stamp=minutes.index[i]
            if is_first_open or (stamp+pd.Timedelta(minutes=1)).day==1:
                folder=output/'checkpoints';folder.mkdir(exist_ok=True)
                save(folder/f'{i}.json',envelope)
            checkpoints.append(dict(index=i,position_open=any(e.account.quantity for e in engines.values()),
                                    bytes=len(raw),first_open=is_first_open))
            transfers+=1;first_open_checkpoint|=is_first_open
        if i and i%250000==0:print(f'Checked {i:,} source minutes; {len(seen):,} decisions; {transfers} handoffs.',flush=True)
    if seen!=set(expected):raise ValueError('streaming decision coverage mismatch')
    checks={};runs={}
    for key,engine in engines.items():
        final=engine.finish();append(key,final)
        metrics=engine.metrics(final['preclose_equity'])
        metrics['annual']=annual(results[key]['daily'],1000)
        reference=ROOT/'reports/validation/e015_intrabar_risk_paths_20260918'/(key+'_T0_OHLC')
        if metrics!=load(reference/'metrics.json'):raise ValueError('metrics differ: '+key)
        folder=output/key;folder.mkdir()
        for name in output_names:
            if results[key][name]!=lines(reference/(name+'.jsonl')):raise ValueError('output differs: '+key+'/'+name)
            with (folder/(name+'.jsonl')).open('x') as stream:
                for row in results[key][name]:stream.write(json.dumps(row,allow_nan=False)+'\n')
        save(folder/'metrics.json',metrics)
        check=verify_run(folder,metrics,{e['fundingTime']:e for e in bundle.funding})
        check['daily']=verify_daily(results[key],minutes)
        check['exact_e015_ohlc_outputs_and_metrics']=True
        save(folder/'verification.json',check);checks[key]=check;runs[key]=metrics
        print(key+': exact E015 parity, '+str(check),flush=True)
    save(output/'handoffs.json',checkpoints)
    save(output/'summary.json',dict(status='PASS_OFFLINE_INCREMENTAL_PARITY',runs=runs,
        source_minutes=len(minutes),signal_decisions=len(seen),serialized_handoffs=transfers,
        max_checkpoint_bytes=max_checkpoint_bytes,max_signal_bytes=max_signal_bytes,
        first_open_position_handoff=first_open_checkpoint,new_forward_observations=0,
        os_crash_consistency_verified=False,live_execution_supported=False,strategy_adopted=False))
    for name,h in sources.items():
        if digest(ROOT/name)!=h:raise ValueError('source changed: '+name)
    for name,h in old.items():
        if digest(ROOT/name)!=h:raise ValueError('prior evidence changed: '+name)
    save(output/'verification.json',dict(status='PASS_OFFLINE_PARITY_AND_SCOPED_UNIT_TESTS',checks=checks,
        sources_unchanged=len(sources),prior_artifacts_unchanged=len(old),actual_orders=0,
        artifact_hashes={str(p.relative_to(output)):digest(p) for p in sorted(output.rglob('*')) if p.is_file()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    try:main(args.output)
    except Exception as exc:
        save(args.output/'failure.json',dict(status='FAILED',exception=type(exc).__name__,reason=str(exc)))
        raise
