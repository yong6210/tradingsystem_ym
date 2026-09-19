"""E035: fixed direction controls at user fees with frozen intrabar risk."""
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.baseline.engine import policies
from app.research.data.btcusdc import load_public_bundle
from app.research.multistrategy_audit import frame_features
from app.research.diagnostics.intrabar_engine import simulate
from app.research.diagnostics.account_fee import reported_taker_costs
from app.research.diagnostics.direction_controls import controls,verify_t0_from_minutes,paired_interval,trade_sides
from app.research.diagnostics.review_metrics import calendar_risk
from scripts.run_direction_controls import save,load,lines,digest,verify_daily,test_ids
from scripts.run_intrabar_risk_paths import verify_stops
from scripts.report_btcusdc_comparison import verify_run
from scripts.run_btcusdc_comparison import annual
from scripts.run_time_exit_policy import START,END,diagnostics,verify_window,check_hashes


def main(out):
    parent=ROOT/'reports/validation/e034_stop_reentry_20260919';reg=load(parent/'registration.json')
    sources=dict(reg['source_hashes']);protected=dict(reg['protected_hashes'])
    proof=load(parent/'verification.json')
    for name,h in proof['artifacts'].items():
        if digest(parent/name)!=h:raise ValueError('E034 changed: '+name)
        protected[str((parent/name).relative_to(ROOT))]=h
    protected[str((parent/'verification.json').relative_to(ROOT))]=digest(parent/'verification.json')
    for name in ['scripts/run_direction_fee_parity.py','docs/research/experiments/E035_DIRECTION_FEE_PARITY.md']:
        sources[name]=digest(ROOT/name)
    check_hashes(sources);check_hashes(protected)
    context=load(ROOT/'configs/research/account_cost_context_20260919.json')
    costs={k:reported_taker_costs(context,c) for k,c in [('base',Costs()),('stress',Costs(7,5,1))]}
    settings=dict(start=START,end=END,models=['T0','LONG','SHORT','INVERSE','CASH'],paths=['OHLC','OLHC'],costs={k:asdict(c) for k,c in costs.items()},risk=asdict(Risk()),runs=20,operating_cost=None)
    suite=unittest.defaultTestLoader.loadTestsFromNames(['tests.test_direction_controls','tests.test_intrabar_risk_paths','tests.test_account_fee']);ids=list(test_ids(suite))
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),settings=settings,source_hashes=sources,protected_hashes=protected,test_ids=ids,
        classification='MATCHED_FEE_DIRECTION_POLICY_DIAGNOSTIC_NOT_EQUAL_EXPOSURE',public_requests=0,actual_orders=0,automatic_retries=0,
        stop_rule='Any test, T0 parity, source, input or independent accounting failure stops all remaining runs'))
    for n in sources:
        p=out/'source_snapshot'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/n).read_bytes())
    with (out/'tests.log').open('x') as f,patch('tests.test_direction_controls.simulate',simulate):
        tested=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
    save(out/'tests.json',dict(registered=len(ids),executed=tested.testsRun,failures=len(tested.failures),errors=len(tested.errors),skipped=len(tested.skipped)))
    if not tested.wasSuccessful() or tested.skipped or tested.testsRun!=len(ids):raise ValueError('registered tests failed')
    print('25 registered tests pass; loading pinned data.',flush=True)
    bundle=load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917');bundle.require_complete_window(START,END);verify_window(bundle.trade.index,START,END)
    t0=policies(bundle.trade,{240:frame_features(bundle.trade,240)})['T0'];save(out/'signal_verification.json',verify_t0_from_minutes(bundle.trade,t0))
    signals=controls(t0);save(out/'decision_hashes.json',{k:hashlib.sha256(json.dumps(v,sort_keys=True).encode()).hexdigest() for k,v in signals.items()})
    funding={e['fundingTime']:e for e in bundle.funding};closes={str(t.date()):float(p) for t,p in bundle.trade.c.resample('1D').last().items()}
    runs={};checks={};calendars={}
    for model in settings['models']:
        for scenario,cost in costs.items():
            for path in settings['paths']:
                key=f'{scenario}_{model}_{path}';print('Running',key,flush=True)
                r=simulate(bundle.trade,signals[model],pd.Timestamp(START),pd.Timestamp(END),cost,Risk(),funding=bundle.funding,path=path)
                m=r['metrics'];m['annual']=annual(r['daily'],1000)
                if model=='T0':
                    prior=ROOT/'reports/validation/e024_account_fee_20260919'/f'{scenario}_{path}'
                    if m!=load(prior/'metrics.json'):raise ValueError('T0 metrics differ')
                    for name in ['events','trades','daily','rejections','path_stops']:
                        if r[name]!=lines(prior/(name+'.jsonl')):raise ValueError('T0 parity failed: '+name)
                folder=out/key;folder.mkdir()
                for name in ['events','trades','daily','rejections','path_stops']:
                    (folder/(name+'.jsonl')).write_text(''.join(json.dumps(x,allow_nan=False)+'\n' for x in r[name]))
                save(folder/'metrics.json',m)
                audit=verify_run(folder,m,funding);audit['daily']=verify_daily(r,bundle.trade);audit['stops']=verify_stops(r,bundle.trade,path,cost,Risk())
                audit['exact_e024_parity']=model=='T0'
                if model=='CASH':
                    if r['events'] or r['trades'] or any(m[k]!=0 for k in ['cycles','fees','funding','realized','return_pct','max_drawdown_pct','active_fraction','mean_notional']) or m['final_equity']!=1000:
                        raise ValueError('cash invariant')
                    detail=dict(calendar_risk=calendar_risk(r['daily']),trade_sides=trade_sides([]),concentration=None,cost_bridge=None,scope='ZERO_TRADES_NO_CONCENTRATION_DENOMINATOR')
                    audit['cash_invariants']=True
                else:detail=diagnostics(r,bundle.trade,closes)
                if model=='T0' and detail!=load(prior/'diagnostics.json'):raise ValueError('T0 diagnostics differ')
                save(folder/'diagnostics.json',detail);save(folder/'verification.json',audit)
                runs[key]=dict(metrics=m,diagnostics=detail);checks[key]=audit;calendars[key]=r['daily']
                print(json.dumps(dict(run=key,net=m['final_equity']-1000,dd=m['max_drawdown_pct'],recovery=detail['calendar_risk']['longest_underwater_days'],cycles=m['cycles'])),flush=True)
    paired={}
    for scenario in costs:
        for path in settings['paths']:
            for model in settings['models'][1:]:
                paired[f'{scenario}_{path}_T0_minus_{model}']=paired_interval(calendars[f'{scenario}_T0_{path}'],calendars[f'{scenario}_{model}_{path}'])
    save(out/'summary.json',dict(settings=settings,runs=runs,paired_comparisons=paired,source_data_reused=True,equal_exposure=False,signal_only_causal_effect=False,
        operating_cost_included=False,actual_tick_paths=False,models_adopted=[],combined=False,public_requests=0,actual_orders=0))
    check_hashes(sources);check_hashes(protected)
    save(out/'verification.json',dict(status='PASS_DIRECTION_FEE_PARITY_AND_LEDGER',tests=tested.testsRun,completed_runs=len(runs),
        independent_events=sum(x['events'] for x in checks.values()),independent_cycles=sum(x['cycles'] for x in checks.values()),daily_rows=730*len(runs),
        sources_unchanged=len(sources),protected_unchanged=len(protected),checks=checks,artifacts={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))
    print('All 20 accounts and independent checks complete.',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    try:main(a.output)
    except Exception as exc:
        save(a.output/'failure.json',dict(status='FAILED',type=type(exc).__name__,reason=str(exc)));raise
