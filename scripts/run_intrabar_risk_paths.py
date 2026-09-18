"""E015: fixed two-path risk sensitivity plus exact frozen controls."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.baseline.engine import policies
from app.research.comparison.engine import simulate as legacy
from app.research.diagnostics.intrabar_engine import simulate
from app.research.diagnostics.direction_controls import controls, verify_t0_from_minutes
from app.research.diagnostics.review_metrics import calendar_risk
from app.research.multistrategy_audit import frame_features
from app.research.data.btcusdc import load_public_bundle
from scripts.run_direction_controls import save, load, digest, lines, verify_daily, test_ids
from scripts.run_btcusdc_comparison import annual
from scripts.report_btcusdc_comparison import verify_run, near


def verify_stops(result, minutes, path, costs, risk):
    """Decimal local stop equation and actual bar legs, not a tick-path oracle."""
    for row in result['path_stops']:
        bar=minutes.iloc[row['minute']]
        points=(bar.o,bar.h,bar.l,bar.c) if path=='OHLC' else (bar.o,bar.l,bar.h,bar.c)
        near(points[row['leg']],row['origin']);near(points[row['leg']+1],row['destination'])
        qty=D(str(row['signed_quantity']));side=1 if qty>0 else -1
        threshold=max(D(str(row['peak_before']))*(1-D(str(risk.halt))),
                      D(str(row['day_start']))*(1-D(str(risk.daily_stop))))
        level=D(str(row['average']))+(threshold-D(str(row['balance_before'])))/qty
        line=max(D(str(row['initial_stop'])),level) if side==1 else min(D(str(row['initial_stop'])),level)
        near(row['protective_line'],line)
        origin,destination,reference=(D(str(row[k])) for k in ('origin','destination','reference'))
        if row['breached_at_origin']:
            near(reference,origin)
            if side*(origin-line)>D('.000001'):raise ValueError('false origin breach')
        elif side*(origin-line)<-D('.000001') or side*(destination-line)>D('.000001'):
            raise ValueError('stop not crossed on declared leg')
        else:near(reference,line)
        event=result['events'][row['event_index']]
        if event['kind']!='exit' or event['side']!=-side or event['time']!=row['time']:
            raise ValueError('stop event identity differs')
        tick=D(str(costs.tick))
        slipped=reference*(1-side*D(str(costs.slippage_bps))/10000)
        fill=(slipped/tick).to_integral_value(rounding=ROUND_CEILING if side==-1 else ROUND_FLOOR)*tick
        near(event['price'],fill)
    return dict(status='PASS',local_stops_checked=len(result['path_stops']),
                origin_breaches=sum(r['breached_at_origin'] for r in result['path_stops']),
                complete_peak_path_independently_verified=False)


def main(output):
    output.mkdir(parents=True,exist_ok=False)
    prior=ROOT/'reports/validation/e014_direction_controls_20260918'
    prior_verification=load(prior/'verification.json')
    for name,expected in prior_verification['artifact_hashes'].items():
        if digest(prior/name)!=expected:raise ValueError('E014 artifact changed: '+name)
    registration=load(prior/'registration.json')
    settings=registration['settings'] | dict(models=['T0','LONG'],paths=['LEGACY','OHLC','OLHC'],runs=12)
    settings.pop('bootstrap')
    sources=dict(registration['source_hashes'])
    for name in ('app/research/diagnostics/intrabar_engine.py','tests/test_intrabar_risk_paths.py',
                 'scripts/run_intrabar_risk_paths.py','docs/research/experiments/E015_INTRABAR_RISK_PATHS.md'):
        sources[name]=digest(ROOT/name)
    tests=('tests.test_intrabar_risk_paths','tests.test_direction_controls','tests.test_comparison',
           'tests.test_baseline_account','tests.test_baseline_engine','tests.test_btcusdc_bundle','tests.test_review_metrics')
    suite=unittest.defaultTestLoader.loadTestsFromNames(tests)
    identities=list(test_ids(suite))
    save(output/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),settings=settings,
        source_hashes=sources,test_ids=identities,prior_verification_sha256=digest(prior/'verification.json'),
        classification='RETROSPECTIVE_EXECUTION_ASSUMPTION_SENSITIVITY_NOT_MODEL_SELECTION',automatic_retries=0))
    for name,expected in sources.items():
        if digest(ROOT/name)!=expected:raise ValueError('input source changed: '+name)
        snapshot=output/'source_snapshot'/name;snapshot.parent.mkdir(parents=True,exist_ok=True)
        snapshot.write_bytes((ROOT/name).read_bytes())
    with (output/'tests.log').open('x') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    save(output/'tests.json',dict(registered=len(identities),executed=result.testsRun,failures=len(result.failures),
                                errors=len(result.errors),skipped=len(result.skipped)))
    if not result.wasSuccessful() or result.skipped or result.testsRun!=len(identities):raise ValueError('tests failed')
    print('Registered path tests passed; loading pinned data.',flush=True)
    bundle=load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917')
    bundle.require_complete_window(settings['start'],settings['end'])
    t0=policies(bundle.trade,{240:frame_features(bundle.trade,240)})['T0']
    save(output/'signal_verification.json',verify_t0_from_minutes(bundle.trade,t0))
    decision_sets=controls(t0);risk=Risk();funding={e['fundingTime']:e for e in bundle.funding}
    runs,checks={},{}
    for scenario,params in settings['costs'].items():
        costs=Costs(**params)
        for model in settings['models']:
            reference=load(prior/(scenario+'_'+model)/'metrics.json')
            reference_events=lines(prior/(scenario+'_'+model)/'events.jsonl')
            for path in settings['paths']:
                key='_'.join((scenario,model,path))
                args=(bundle.trade,decision_sets[model],pd.Timestamp(settings['start']),pd.Timestamp(settings['end']),costs,risk)
                result=(legacy(*args,funding=bundle.funding) if path=='LEGACY' else
                        simulate(*args,funding=bundle.funding,path=path))
                folder=output/key;folder.mkdir()
                for name in ('events','trades','daily','rejections','path_stops'):
                    with (folder/(name+'.jsonl')).open('x') as stream:
                        for row in result.get(name,[]):stream.write(json.dumps(row,allow_nan=False)+'\n')
                m=result['metrics'];m['annual']=annual(result['daily'],1000)
                save(folder/'metrics.json',m)
                v=verify_run(folder,m,funding);v['daily']=verify_daily(result,bundle.trade)
                if path=='LEGACY':
                    if m!=reference:raise ValueError('legacy metrics differ')
                    for name in ('events','trades','daily','rejections'):
                        if result[name]!=lines(prior/(scenario+'_'+model)/(name+'.jsonl')):raise ValueError('legacy '+name+' differs')
                    v['exact_legacy_reproduction']=True
                else:v['path_stops']=verify_stops(result,bundle.trade,path,costs,risk)
                supplement=dict(calendar_risk=calendar_risk(result['daily']),
                    path_diagnostics=result.get('path_diagnostics'),
                    origin_breaches=sum(row['breached_at_origin'] for row in result.get('path_stops',[])),
                    events_equal_legacy=result['events']==reference_events,
                    return_change_pp=m['return_pct']-reference['return_pct'],
                    drawdown_change_pp=m['max_drawdown_pct']-reference['max_drawdown_pct'])
                save(folder/'verification.json',v);runs[key]=m|supplement;checks[key]=v
                print(json.dumps(dict(run=key,return_pct=m['return_pct'],dd=m['max_drawdown_pct'],
                    cycles=m['cycles'],events_equal_legacy=supplement['events_equal_legacy'])),flush=True)
    save(output/'summary.json',dict(settings=settings,runs=runs,actual_tick_paths=False,
        exhaustive_best_worst_bounds=False,strategy_adopted=False))
    for name,expected in sources.items():
        if digest(ROOT/name)!=expected:raise ValueError('registered source changed: '+name)
    for name,expected in prior_verification['artifact_hashes'].items():
        if digest(prior/name)!=expected:raise ValueError('prior evidence changed: '+name)
    save(output/'verification.json',dict(status='PASS_SCOPED_PATH_FIXTURES_LEDGER_DAILY_AND_LOCAL_STOPS',
        runs=checks,independent_events=sum(v['events'] for v in checks.values()),
        independent_cycles=sum(v['cycles'] for v in checks.values()),
        independent_local_path_stops=sum(v.get('path_stops',{}).get('local_stops_checked',0) for v in checks.values()),
        all_12_runs_completed=True,prior_e014_artifacts_unchanged=len(prior_verification['artifact_hashes']),
        registered_sources_unchanged=True,actual_orders=0,strategy_adopted=False,
        artifact_hashes={str(p.relative_to(output)):digest(p) for p in sorted(output.rglob('*')) if p.is_file()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:main(args.output)
    except Exception as exc:
        if args.output.is_dir() and not (args.output/'failure.json').exists():
            save(args.output/'failure.json',dict(status='FAILED',exception=type(exc).__name__,reason=str(exc)))
        raise
