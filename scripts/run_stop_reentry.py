"""E034: fixed reentry policy, four parity controls followed by four variants."""
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from functools import partial
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.baseline.engine import policies
from app.research.data.btcusdc import load_public_bundle
from app.research.multistrategy_audit import frame_features
from app.research.diagnostics.stop_reentry_engine import simulate
from app.research.diagnostics.stop_reentry_audit import verify as verify_lock
from app.research.diagnostics.direction_controls import verify_t0_from_minutes,paired_interval
from scripts.run_direction_controls import save,load,lines,digest,verify_daily,test_ids
from scripts.run_intrabar_risk_paths import verify_stops
from scripts.report_btcusdc_comparison import verify_run
from scripts.run_btcusdc_comparison import annual
from scripts.run_time_exit_policy import START,END,diagnostics,verify_window,check_hashes


def main(out):
    prior=ROOT/'reports/validation/e024_account_fee_20260919';old=load(prior/'registration.json');proof=load(prior/'verification.json')
    sources=dict(old['source_hashes']);protected=dict(old['prior_artifact_hashes'])
    for name,h in proof['artifact_hashes'].items():
        if digest(prior/name)!=h:raise ValueError('E024 evidence changed: '+name)
        protected[str((prior/name).relative_to(ROOT))]=h
    protected[str((prior/'verification.json').relative_to(ROOT))]=digest(prior/'verification.json')
    for folder in ['e032_flow_absorption_20260919','e032_flow_snapshot_repair_20260919','e033_launch_readiness_20260919']:
        base=ROOT/'reports/validation'/folder
        for name,h in load(base/'verification.json')['artifacts'].items():
            if digest(base/name)!=h:raise ValueError('later evidence changed')
            protected[str((base/name).relative_to(ROOT))]=h
    names=['app/research/diagnostics/stop_reentry_engine.py','app/research/diagnostics/stop_reentry_audit.py','scripts/run_stop_reentry.py','tests/test_stop_reentry.py','docs/research/experiments/E034_STOP_REENTRY.md']
    sources.update({n:digest(ROOT/n) for n in names});check_hashes(sources);check_hashes(protected)
    costs={'base':Costs(2.5,2,0),'stress':Costs(2.5,5,1)}
    settings=dict(start=START,end=END,model='T0',policy='BLOCK_PRICE_STOP_SAME_SIDE_UNTIL_OPPOSITE_NONZERO_SIGNAL',costs={k:asdict(c) for k,c in costs.items()},risk=asdict(Risk()),paths=['OHLC','OLHC'],runs=8,operating_cost=None)
    suite=unittest.defaultTestLoader.loadTestsFromNames(['tests.test_stop_reentry','tests.test_intrabar_risk_paths']);ids=list(test_ids(suite))
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),settings=settings,source_hashes=sources,protected_hashes=protected,test_ids=ids,
        classification='RETROSPECTIVE_SINGLE_POLICY_EXPLORATION_REUSED_DATA',automatic_retries=0,actual_orders=0,public_requests=0,
        promotion_allowed=False,stop_rule='Any parity, data, source, test or independent audit mismatch stops all remaining runs'))
    for name in sources:
        p=out/'source_snapshot'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/name).read_bytes())
    with (out/'tests.log').open('x') as f,patch('tests.test_intrabar_risk_paths.simulate',partial(simulate,block_stop_reentry=True)):
        tested=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
    save(out/'tests.json',dict(registered=len(ids),executed=tested.testsRun,failures=len(tested.failures),errors=len(tested.errors),skipped=len(tested.skipped)))
    if not tested.wasSuccessful() or tested.skipped or tested.testsRun!=len(ids):raise ValueError('tests failed')
    print('Registered tests pass; loading pinned data.',flush=True)
    bundle=load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917');bundle.require_complete_window(START,END);count=verify_window(bundle.trade.index,START,END)
    signals=policies(bundle.trade,{240:frame_features(bundle.trade,240)})['T0'];save(out/'signal_verification.json',verify_t0_from_minutes(bundle.trade,signals))
    lower=int(bundle.trade.index.searchsorted(pd.Timestamp(START)));upper=int(bundle.trade.index.searchsorted(pd.Timestamp(END)))
    (out/'signals.jsonl').write_text(''.join(json.dumps(dict(minute=i,side=v[0],close=v[1],atr=v[2]))+'\n' for i,v in signals.items() if lower<=i<upper))
    funding={e['fundingTime']:e for e in bundle.funding};closes={str(t.date()):float(p) for t,p in bundle.trade.c.resample('1D').last().items()}
    runs={};checks={};daily={}
    for enabled,policy in [(False,'control'),(True,'locked')]:
        for scenario,cost in costs.items():
            for path in settings['paths']:
                key=f'{scenario}_{policy}_{path}';print('Running',key,flush=True)
                result=simulate(bundle.trade,signals,pd.Timestamp(START),pd.Timestamp(END),cost,Risk(),funding=bundle.funding,path=path,block_stop_reentry=enabled)
                m=result['metrics'];m['annual']=annual(result['daily'],1000)
                if not enabled:
                    frozen=prior/f'{scenario}_{path}'
                    if m!=load(frozen/'metrics.json'):raise ValueError('control metrics differ')
                    for name in ['events','trades','daily','rejections','path_stops']:
                        if result[name]!=lines(frozen/(name+'.jsonl')):raise ValueError('control differs: '+name)
                folder=out/key;folder.mkdir()
                for name in ['events','trades','daily','rejections','path_stops','reentry_events']:
                    (folder/(name+'.jsonl')).write_text(''.join(json.dumps(x,allow_nan=False)+'\n' for x in result[name]))
                save(folder/'metrics.json',m)
                audit=verify_run(folder,m,funding);audit['daily']=verify_daily(result,bundle.trade);audit['stops']=verify_stops(result,bundle.trade,path,cost,Risk())
                audit['lock_timeline']=verify_lock(result,signals,lower,upper,enabled);audit['e024_exact_parity']=not enabled
                detail=diagnostics(result,bundle.trade,closes)
                if not enabled and detail!=load((prior/f'{scenario}_{path}')/'diagnostics.json'):raise ValueError('control diagnostics differ')
                save(folder/'diagnostics.json',detail);save(folder/'verification.json',audit)
                runs[key]=dict(metrics=m,diagnostics=detail,lock_timeline=audit['lock_timeline']);checks[key]=audit;daily[key]=result['daily']
                print(json.dumps(dict(run=key,net=m['final_equity']-1000,dd=m['max_drawdown_pct'],recovery=detail['calendar_risk']['longest_underwater_days'],cycles=m['cycles'])),flush=True)
    comparisons={}
    for scenario in costs:
        for path in settings['paths']:
            control=f'{scenario}_control_{path}';variant=f'{scenario}_locked_{path}';a,b=runs[control],runs[variant]
            top=lambda r:next(x['positive_profit_share'] for x in r['diagnostics']['concentration']['top'] if x['requested_count']==5)
            delta=dict(net_profit_usdc=b['metrics']['final_equity']-a['metrics']['final_equity'],max_drawdown_percentage_points=b['metrics']['max_drawdown_pct']-a['metrics']['max_drawdown_pct'],
                longest_underwater_days=b['diagnostics']['calendar_risk']['longest_underwater_days']-a['diagnostics']['calendar_risk']['longest_underwater_days'],top5_positive_profit_share=top(b)-top(a))
            comparisons[scenario+'_'+path]=dict(delta=delta,all_three_improve=delta['net_profit_usdc']>0 and delta['longest_underwater_days']<0 and delta['top5_positive_profit_share']<0,
                paired_exploratory=paired_interval(daily[variant],daily[control]))
    save(out/'summary.json',dict(settings=settings,minutes=count,runs=runs,comparisons=comparisons,all_conditions_improve=all(x['all_three_improve'] for x in comparisons.values()),
        source_data_reused=True,operating_cost_included=False,actual_tick_paths=False,strategy_adopted=False,combined=False,actual_orders=0,public_requests=0))
    check_hashes(sources);check_hashes(protected)
    save(out/'verification.json',dict(status='PASS_FIXED_POLICY_PARITY_LEDGER_AND_LOCK_AUDITS',tests=tested.testsRun,completed_runs=len(runs),
        independent_events=sum(x['events'] for x in checks.values()),independent_cycles=sum(x['cycles'] for x in checks.values()),daily_rows=730*len(runs),
        sources_unchanged=len(sources),protected_unchanged=len(protected),checks=checks,artifacts={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))
    print(json.dumps(comparisons,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    try:main(args.output)
    except Exception as exc:
        save(args.output/'failure.json',dict(status='FAILED',type=type(exc).__name__,reason=str(exc)));raise
