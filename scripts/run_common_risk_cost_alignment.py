"""E041: unchanged common-six signals under one current risk/cost policy."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.comparison.policies import comparison_policies
from app.research.multistrategy_audit import frame_features
from app.research.data.btcusdc import load_public_bundle
from app.research.diagnostics.operating_engine import simulate
from app.research.diagnostics.operating_audit import verify_run,near
from app.research.diagnostics.review_metrics import calendar_risk
from app.research.diagnostics.concentration import concentration
from scripts.run_direction_controls import save,load,lines,digest,verify_daily
from scripts.run_time_exit_policy import START,END,check_hashes
from scripts.run_intrabar_risk_paths import verify_stops
from scripts.run_btcusdc_comparison import annual
MODELS=('T0','T1','T2','B0','R0','F0')


def main(out):
    prior=ROOT/'reports/validation/e039_weekly_long_operations_20260919'
    old=load(prior/'registration.json');sources=dict(old['source_hashes'])
    for n in ['scripts/run_common_risk_cost_alignment.py','docs/research/experiments/E041_COMMON_RISK_COST_ALIGNMENT.md',
              'app/research/comparison/policies.py','tests/test_comparison.py']:
        sources[n]=digest(ROOT/n)
    check_hashes(sources)
    evidence=load(prior/'verification.json')
    for name,h in evidence['artifacts'].items():
        if digest(prior/name)!=h:raise ValueError('changed E039 artifact')
    e025=ROOT/'reports/validation/e025_matched_fee_common_20260919'
    e025reg=load(e025/'registration.json')
    policy_sources=['app/research/baseline/engine.py','app/research/comparison/policies.py','app/research/multistrategy_audit.py']
    for name in policy_sources:
        if digest(ROOT/name)!=e025reg['source_hashes'][name]:raise ValueError('E025 policy source changed '+name)
    settings=dict(start=START,end=END,models=list(MODELS),costs=old['settings']['costs'],risk=old['settings']['risk'],
                  monthly_operating_costs=[0,2],paths=['OHLC','OLHC'],runs=48,
                  charge_timing=old['settings']['charge_timing'],charges_continue_after_halt=True)
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),settings=settings,
         source_hashes=sources,prior_verification_sha256=digest(prior/'verification.json'),
         e025_registration_sha256=digest(e025/'registration.json'),policy_sources_unchanged=policy_sources,actual_orders=0))
    for name in sources:
        target=out/'source_snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/name).read_bytes())
    with (out/'tests.log').open('x') as f:
        tested=unittest.TextTestRunner(stream=f,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(
            ['tests.test_operating_engine','tests.test_comparison','tests.test_intrabar_risk_paths']))
    if not tested.wasSuccessful() or tested.skipped:raise ValueError('focused tests failed')
    print('Loading frozen bundle and unchanged six policies.',flush=True)
    bundle=load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917');bundle.require_complete_window(START,END)
    decision_sets=comparison_policies(bundle.trade,{p:frame_features(bundle.trade,p) for p in (60,240)})
    if set(decision_sets)!=set(MODELS):raise ValueError('model coverage')
    for model in MODELS:save(out/(model+'_decisions.json'),decision_sets[model])
    risk=Risk(**settings['risk']);months=pd.date_range(START,END,freq='MS',inclusive='left')
    indices=bundle.trade.index.get_indexer(months)
    if len(months)!=24 or min(indices)<0:raise ValueError('charge calendar')
    funding={e['fundingTime']:e for e in bundle.funding};runs={};checks={}
    for model in MODELS:
        for amount in settings['monthly_operating_costs']:
            debits={int(i):amount for i in indices}
            for scenario,params in settings['costs'].items():
                cost=Costs(**params)
                for path in settings['paths']:
                    key=f'{scenario}_{model}_op{amount}_{path}';print(key,flush=True)
                    result=simulate(bundle.trade,decision_sets[model],pd.Timestamp(START),pd.Timestamp(END),cost,risk,
                                    funding=bundle.funding,path=path,operating_debits=debits)
                    m=result['metrics'];m['annual']=annual(result['daily'],1000)
                    folder=out/key;folder.mkdir()
                    for name in ('events','trades','daily','rejections','path_stops'):
                        with (folder/(name+'.jsonl')).open('x') as f:
                            for row in result[name]:f.write(json.dumps(row,allow_nan=False)+'\n')
                    save(folder/'metrics.json',m)
                    audit=verify_run(folder,m,funding);audit['daily']=verify_daily(result,bundle.trade)
                    audit['stops']=verify_stops(result,bundle.trade,path,cost,risk)
                    operating=[e for e in result['events'] if e['kind']=='operating']
                    expected=[dict(time=t.isoformat(),amount=amount) for t in months] if amount else []
                    if [dict(time=e['time'],amount=e['amount']) for e in operating]!=expected:raise ValueError('operating calendar differs')
                    near(m['operating_cost'],24*amount);audit['operating_calendar_verified']=len(expected)
                    monthly={};previous=1000.
                    for day in result['daily']:
                        label=day['day'][:7];monthly[label]=monthly.get(label,0)+day['equity']-previous;previous=day['equity']
                    trades=result['trades'];net=m['final_equity']-1000
                    detail=dict(calendar_risk=calendar_risk(result['daily']),monthly_net_after_operations=monthly,
                        trading_concentration=concentration([dict(id=i,net=t['net_pnl']) for i,t in enumerate(trades)],(1,5)) if trades else None,
                        net_usdc=net,trading_net_before_operations=sum(t['net_pnl'] for t in trades),
                        monthly_cost_assumption_usdc=amount,necessary_conditions_pass=net>0 and m['max_drawdown_pct']<=5)
                    near(sum(monthly.values()),net)
                    save(folder/'diagnostics.json',detail);save(folder/'verification.json',audit)
                    runs[key]=dict(metrics=m,diagnostics=detail);checks[key]=audit
                    print(json.dumps(dict(run=key,net=net,dd=m['max_drawdown_pct'],cycles=m['cycles'],halt=m['halt_time'])),flush=True)
    screening={str(op):{model:all(runs[f'{s}_{model}_op{op}_{p}']['diagnostics']['necessary_conditions_pass']
                 for s in settings['costs'] for p in settings['paths']) for model in MODELS} for op in (0,2)}
    save(out/'summary.json',dict(settings=settings,runs=runs,screening=screening,
         operating_assumption_confirmed_by_user=False,risk_parameters_are_research_assumptions=True,
         source_data_reused=True,future_profit_verified=False,strategy_adopted=False,actual_orders=0))
    check_hashes(sources)
    save(out/'verification.json',dict(status='PASS_WITH_EXECUTION_AND_SELECTION_LIMITATIONS',focused_tests=tested.testsRun,
         checks=checks,source_hashes_unchanged=len(sources),
         artifacts={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    try:main(a.output)
    except Exception as e:save(a.output/'failure.json',dict(type=type(e).__name__,reason=str(e)));raise
