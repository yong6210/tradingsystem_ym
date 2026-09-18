"""E025: fixed common-six then existing complementary implementations, no tuning."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.comparison.engine import simulate
from app.research.comparison.policies import comparison_policies
from app.research.candidate_accounts.policies import build_policy
from app.research.candidate_accounts.flow import build_flow_policy
from app.research.candidate_accounts.crowding import funding_context, basis_context, build_crowding_policies
from app.research.candidate_accounts.pullback import build_pullback_policies
from app.research.candidate_accounts.failed_break import build_failed_break
from app.research.data.btcusdc import load_public_bundle
from app.research.data.taker_flow import load_taker_flow, completed_flow
from app.research.multistrategy_audit import feature_bank
from app.research.diagnostics.account_fee import reported_taker_costs
from app.research.diagnostics.concentration import concentration
from app.research.diagnostics.review_metrics import calendar_risk
from app.research.diagnostics.direction_controls import daily_returns, paired_interval
from scripts.run_direction_controls import save, load, lines, digest, test_ids, verify_daily, legacy_review
from scripts.run_time_exit_policy import check_hashes, START, END
from scripts.run_btcusdc_comparison import annual
from scripts.report_btcusdc_comparison import verify_run

COMMON = ('T0','T1','T2','B0','R0','F0')
EXTENDED = ('S04','S05','S02','S08','S06A','S09F','S09B','S09FB','C4','P4','C15','P15','S07_FADE','S07_CONTINUE')
REFERENCES = {**{m:'e005_btcusdc_comparison_20260917' for m in COMMON},
    **{m:'e008_candidate_accounts_20260917' for m in ('S04','S05','S02','S08')},
    'S06A':'e009_taker_alignment_20260917',
    **{m:'e010_funding_basis_20260917' for m in ('S09F','S09B','S09FB')},
    **{m:'e011_trend_pullback_20260917' for m in ('C4','P4','C15','P15')},
    **{m:'e013_failed_break_direction_20260917' for m in ('S07_FADE','S07_CONTINUE')}}
CONTROLS = dict(S05='S04', S08='S02', S06A='S02', S09F='T0', S09B='T0',
                S09FB='T0', P4='C4', P15='C15', C4='T0', S07_FADE='S07_CONTINUE')
TESTS = ('tests.test_account_fee','tests.test_comparison','tests.test_baseline_account',
    'tests.test_baseline_engine','tests.test_btcusdc_bundle','tests.test_candidate_accounts',
    'tests.test_taker_flow','tests.test_crowding','tests.test_pullback','tests.test_failed_break',
    'tests.test_review_metrics','tests.test_profit_concentration','tests.test_direction_controls',
    'tests.test_matched_fee_review')


def detail(result):
    daily, trades = result['daily'], result['trades']
    monthly = {}
    previous = 1000.
    for row in daily:
        month = row['day'][:7]
        monthly[month] = monthly.get(month, 0.) + row['equity'] - previous
        previous = row['equity']
    return dict(calendar_risk=calendar_risk(daily), monthly_net_usdc=monthly,
        worst_month=min(monthly, key=monthly.get), negative_months=sum(v < 0 for v in monthly.values()),
        concentration=concentration([dict(id=i,net=t['net_pnl']) for i,t in enumerate(trades)],(1,5,10)) if trades else None,
        cagr_pct=100*((result['metrics']['final_equity']/1000)**(365/len(daily))-1),
        monthly_cost_break_even_arithmetic_usdc=(result['metrics']['final_equity']-1000)/len(monthly))


def joint_loss(left, right):
    if [r['day'] for r in left['daily']] != [r['day'] for r in right['daily']]:
        raise ValueError('unaligned calendars')
    a,b = (daily_returns(r['daily'],1000) for r in (left,right))
    def held_days(result):
        days=set()
        for t in result['trades']:
            days.update(str(d.date()) for d in pd.date_range(pd.Timestamp(t['entry_time']).normalize(),
                pd.Timestamp(t['exit_time']).normalize(),freq='D'))
        return days
    active=held_days(left)&held_days(right)
    mask=np.array([r['day'] in active for r in left['daily']])
    both=(a<0)&(b<0)
    return dict(calendar_days=len(a),both_loss_days=int(both.sum()),
        left_loss_days=int((a<0).sum()),right_loss_days=int((b<0).sum()),
        both_loss_given_right_loss=float(both.sum()/(b<0).sum()) if (b<0).any() else None,
        daily_return_correlation=float(np.corrcoef(a,b)[0,1]) if a.std()>0 and b.std()>0 else None,
        joint_holding_days=int(mask.sum()),both_loss_joint_holding_days=int((both&mask).sum()),
        joint_holding_definition='EACH_HELD_AT_SOME_TIME_ON_DATE_NOT_NECESSARILY_SAME_MINUTE',
        jointly_negative_net_usdc=float(sum(left['daily'][i]['equity']-(left['daily'][i-1]['equity'] if i else 1000)
            for i in range(len(a)) if both[i])))


def necessary_checks(base, stress):
    return dict(base_positive=base['return_pct']>0,stress_positive=stress['return_pct']>0,
        no_halt=not base['drawdown_halted'] and not stress['drawdown_halted'],
        cycles_at_least_100=min(base['cycles'],stress['cycles'])>=100,
        stress_2025_2026_positive=all(stress['annual'][y]['return_pct']>0 for y in ('2025','2026')))


def make_policies(bundle, bank, models):
    result=comparison_policies(bundle.trade,bank)
    if not set(models)-set(COMMON): return result
    for m in ('S04','S05','S02','S08'): result[m]=build_policy(bundle.trade,bank,m)[0]
    flow,_=load_taker_flow(ROOT,ROOT/'data/historical/btcusdc_public_20260917')
    pd.testing.assert_frame_equal(flow[['o','h','l','c','v']],bundle.trade,check_dtype=False,check_names=False)
    hourly=completed_flow(flow)
    if build_flow_policy(bundle.trade,bank,hourly,'S02') != result['S02']:
        raise ValueError('flow control differs')
    result['S06A']=build_flow_policy(bundle.trade,bank,hourly,'S06A')
    context=funding_context(bank[240].index,bundle.funding).join(basis_context(bank[240].index,bundle.mark,bundle.index_price))
    result.update(build_crowding_policies(bundle.trade,result['T0'],context))
    pullback,_,_=build_pullback_policies(bundle.trade,bank)
    if pullback['T0'] != result['T0']: raise ValueError('pullback control differs')
    result.update(pullback)
    result.update(build_failed_break(bundle.trade,bank)[0])
    return result


def main(output, stage, common_output):
    models=COMMON if stage=='common' else EXTENDED
    legacy,prior_hashes=legacy_review()
    sources=load(ROOT/'reports/validation/e013_failed_break_direction_20260917/registration.json')['source_hashes']
    names=['scripts/run_matched_fee_review.py','docs/research/experiments/E025_MATCHED_FEE_REVIEW.md',
        'configs/research/account_cost_context_20260919.json','app/research/diagnostics/account_fee.py',
        'app/research/diagnostics/concentration.py','app/research/diagnostics/direction_controls.py',
        'scripts/run_direction_controls.py','scripts/run_time_exit_policy.py']
    names += [m.replace('.','/')+'.py' for m in TESTS]
    sources.update({n:digest(ROOT/n) for n in names})
    e024=ROOT/'reports/validation/e024_account_fee_20260919'
    for n,h in load(e024/'verification.json')['artifact_hashes'].items():
        if digest(e024/n)!=h: raise ValueError('E024 changed: '+n)
        prior_hashes[str((e024/n).relative_to(ROOT))]=h
    for record in legacy['checks']:
        prior_hashes[record['path']]=digest(ROOT/record['path'])
    if stage=='extended':
        receipt=load(common_output/'verification.json')
        for n,h in receipt['artifact_hashes'].items():
            if digest(common_output/n)!=h: raise ValueError('common stage changed')
            prior_hashes[str((common_output/n).relative_to(ROOT))]=h
    check_hashes(sources);check_hashes(prior_hashes)
    context=load(ROOT/'configs/research/account_cost_context_20260919.json')
    costs={s:reported_taker_costs(context,c) for s,c in dict(base=Costs(),stress=Costs(7,5,1)).items()}
    risks={}
    for m in models:
        settings=load(ROOT/'reports/validation'/REFERENCES[m]/'registration.json')['settings']
        risk=settings['risk']
        risks[m]=Risk(**(risk[m] if m in risk else risk))
    suite=unittest.defaultTestLoader.loadTestsFromNames(TESTS)
    ids=list(test_ids(suite))
    save(output/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
        stage=stage,models=models,start=START,end=END,runs=2*len(models),
        costs={s:asdict(c) for s,c in costs.items()},risk={m:asdict(r) for m,r in risks.items()},
        source_hashes=sources,prior_artifact_hashes=prior_hashes,test_ids=ids,automatic_retries=0,
        classification='RETROSPECTIVE_FEE_MATCHED_FIXED_IMPLEMENTATIONS',operating_cost=None,
        bootstrap=dict(block_days=28,repetitions=2000,seed=18092026),controls=CONTROLS))
    for n in sources:
        dest=output/'source_snapshot'/n;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((ROOT/n).read_bytes())
    with (output/'tests.log').open('x') as stream: tested=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    save(output/'tests.json',dict(executed=tested.testsRun,failures=len(tested.failures),errors=len(tested.errors),skipped=len(tested.skipped)))
    if not tested.wasSuccessful() or tested.skipped: raise ValueError('tests failed')
    print('Tests passed; loading pinned inputs.',flush=True)
    bundle=load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917')
    bundle.require_complete_window(START,END)
    decisions=make_policies(bundle,feature_bank(bundle.trade),models)
    funding={e['fundingTime']:e for e in bundle.funding}
    runs,results,checks={},{},{}
    if stage=='extended':
        for s in costs:
            for m in COMMON:
                folder=common_output/(s+'_'+m)
                results[s+'_'+m]={n:lines(folder/(n+'.jsonl')) for n in ('events','trades','daily','rejections')}
                results[s+'_'+m]['metrics']=load(folder/'metrics.json')
    for m in models:
        for s,cost in costs.items():
            key=s+'_'+m
            old_folder=ROOT/'reports/validation'/REFERENCES[m]/key
            old_metrics=load(old_folder/'metrics.json')
            if old_metrics['risk']!=asdict(risks[m]): raise ValueError('risk changed')
            reference=verify_run(old_folder,old_metrics,funding)
            reference['daily']=verify_daily({n:lines(old_folder/(n+'.jsonl')) for n in ('events','daily')},bundle.trade)
            result=simulate(bundle.trade,decisions[m],pd.Timestamp(START),pd.Timestamp(END),cost,risks[m],funding=bundle.funding)
            metrics=result['metrics'];metrics['annual']=annual(result['daily'],1000)
            folder=output/key;folder.mkdir()
            for field in ('events','trades','daily','rejections'):
                with (folder/(field+'.jsonl')).open('x') as stream:
                    for row in result[field]: stream.write(json.dumps(row,allow_nan=False)+'\n')
            save(folder/'metrics.json',metrics)
            audit=verify_run(folder,metrics,funding);audit['daily']=verify_daily(result,bundle.trade)
            if m=='T0':
                for field in ('events','trades','daily','rejections'):
                    if result[field]!=lines(e024/(s+'_OHLC')/(field+'.jsonl')): raise ValueError('E024 T0 differs: '+field)
                audit['e024_ledger_parity']=True
            d=detail(result);save(folder/'diagnostics.json',d);save(folder/'verification.json',audit)
            runs[key]=dict(metrics=metrics,diagnostics=d,old_return_pct=old_metrics['return_pct'],
                fee_change_equity_usdc=metrics['final_equity']-old_metrics['final_equity'])
            results[key]=result;checks[key]=dict(new=audit,reference=reference)
            print(json.dumps(dict(run=key,return_pct=metrics['return_pct'],dd=metrics['max_drawdown_pct'],
                cycles=metrics['cycles'],underwater=d['calendar_risk']['longest_underwater_days'])),flush=True)
    comparisons,screening={},{}
    for m in models:
        screening[m]=necessary_checks(*(results[s+'_'+m]['metrics'] for s in costs))
        if m=='T0': continue
        for s in costs:
            for control in dict.fromkeys(('T0',CONTROLS.get(m,'T0'))):
                a,b=results[s+'_'+m],results[s+'_'+control]
                comparisons[s+'_'+m+'_vs_'+control]=dict(joint_loss=joint_loss(a,b),
                    paired_interval=paired_interval(a['daily'],b['daily']))
    save(output/'summary.json',dict(runs=runs,screening=screening,comparisons=comparisons,
        previously_observed_data=True,strategy_adopted=False,combination_simulated=False,
        operating_cost_included=False,actual_orders=0,dd_scope='FROZEN_COMMON_ENGINE_NOT_TICK_MAXIMUM'))
    check_hashes(sources);check_hashes(prior_hashes)
    save(output/'verification.json',dict(status='PASS_SCOPED_LEDGER_DAILY_AND_FROZEN_INPUTS',
        runs=checks,completed_new_runs=len(runs),sources_unchanged=len(sources),prior_artifacts_unchanged=len(prior_hashes),
        artifact_hashes={str(p.relative_to(output)):digest(p) for p in sorted(output.rglob('*')) if p.is_file()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',choices=('common','extended'),required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--common-output',type=Path)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    try: main(args.output,args.stage,args.common_output)
    except Exception as exc:
        save(args.output/'failure.json',dict(exception=type(exc).__name__,reason=str(exc)));raise
