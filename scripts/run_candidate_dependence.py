"""E048 resumed stored-account diagnostic; no account or portfolio replays."""
from datetime import datetime,timedelta,date,timezone
from decimal import Decimal as D
from itertools import combinations
from collections import defaultdict
from pathlib import Path
import hashlib,json,math,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from app.research.diagnostics.candidate_dependence import account_summary,pair_stats,position_overlap
BASE=ROOT/'reports/validation';OUT=BASE/'e048_positive_candidate_dependence_20260919'
FOLDERS=dict(common=BASE/'e041_common_risk_cost_alignment_20260919',extended=BASE/'e042_extended_risk_cost_alignment_20260919',
    weekly=BASE/'e039_weekly_long_operations_20260919',tail=BASE/'e044_minimum_contract_20260919')
MODELS={'T0':'common','T1':'common','T2':'common','B0':'common','S09F':'extended','S09B':'extended','S09FB':'extended',
    'C4':'extended','P4':'extended','WEEKLY_LONG':'weekly','TAIL':'tail'}

def load(p):return json.loads(p.read_text())
def lines(p):return [json.loads(x) for x in p.read_text().splitlines() if x]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def now():return datetime.now(timezone.utc).isoformat()
def save(p,x):
    with p.open('x') as f:json.dump(x,f,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n')
def key(model,cost,op,path):return f'{cost}_{model}_op{op}_{path}' if model!='WEEKLY_LONG' else f'{cost}_op{op}_{path}'


def sweep_overlap(a,b):
    changes=defaultdict(lambda:[0,0])
    for k,series in enumerate((a,b)):
        for row in series:
            changes[row['entry_minute']][k]+=row['side']
            changes[row['exit_minute']][k]-=row['side']
    times=sorted(changes);state=[0,0];same=opposite=0
    for i,t in enumerate(times):
        state=[state[j]+changes[t][j] for j in range(2)]
        assert all(x in (-1,0,1) for x in state)
        if i+1<len(times) and all(state):
            length=times[i+1]-t
            if state[0]==state[1]:same+=length
            else:opposite+=length
    assert state==[0,0]
    return same,opposite


def main():
    if OUT.exists():raise ValueError('preserve prior E048 attempt')
    prior=load(BASE/'q006_forward_sample_feasibility_20260919/registration.json')
    protected={**prior['protected_hashes'],**prior['source_hashes']}
    for n,h in protected.items():assert sha(ROOT/n)==h,n
    for p in (BASE/'q006_forward_sample_feasibility_20260919').rglob('*'):
        if p.is_file():protected[str(p.relative_to(ROOT))]=sha(p)
    manifest={};sources={};summaries={};verifications={}
    for group,folder in FOLDERS.items():
        v=load(folder/'verification.json');verifications[group]=v;summaries[group]=load(folder/'summary.json')
        for filename in ['summary.json','verification.json']:
            if filename in v['artifacts']:assert sha(folder/filename)==v['artifacts'][filename]
            sources[str((folder/filename).relative_to(ROOT))]=sha(folder/filename)
    for model,group in MODELS.items():
        folder=FOLDERS[group];v=verifications[group]
        for cost in ('base','stress'):
            for op in (0,2):
                for path in ('OHLC','OLHC'):
                    run=key(model,cost,op,path);manifest[f'{model}:{cost}:op{op}:{path}']=str((folder/run).relative_to(ROOT))
                    for filename in ('metrics.json','diagnostics.json','daily.jsonl','trades.jsonl'):
                        name=run+'/'+filename;p=folder/name
                        assert sha(p)==v['artifacts'][name],str(p)
                        sources[str(p.relative_to(ROOT))]=sha(p)
    for name in ['app/research/diagnostics/candidate_dependence.py','scripts/run_candidate_dependence.py','tests/test_candidate_dependence.py',
                 'docs/research/experiments/E048_POSITIVE_CANDIDATE_DEPENDENCE.md','docs/research/experiments/E048_RESUMPTION_2026_09_19.md']:
        sources[name]=sha(ROOT/name)
    OUT.mkdir()
    save(OUT/'registration.json',dict(registered_at_utc=now(),status='RESUMED_STORED_ACCOUNT_DIAGNOSTIC',
        reason='Assess observed profit-source dependence and recovery complementarity before proposing combinations.',
        models=list(MODELS),accounts=88,pairs_per_cost_condition=55,cost_conditions=4,
        source_hashes=sources,protected_hashes=protected,manifest=manifest,
        new_account_runs=0,portfolio_allocation_selected=False,future_profit_verified=False,actual_orders=0,new_schedules=0))
    tests=subprocess.run([sys.executable,'-m','unittest','tests.test_candidate_dependence','-v'],cwd=ROOT,capture_output=True,text=True)
    with (OUT/'tests.log').open('x') as f:f.write(tests.stdout+tests.stderr)
    if tests.returncode:raise ValueError(tests.stderr)
    expected=[(date(2024,9,1)+timedelta(days=i)).isoformat() for i in range(730)]
    outputs={};path_checks=correlation_checks=overlap_checks=recovery_checks=0
    for cost in ('base','stress'):
        for op in (0,2):
            name=f'{cost}_op{op}';account={};pnls={};returns={};positions={};daily_data={}
            for model,group in MODELS.items():
                folder=FOLDERS[group];a=folder/key(model,cost,op,'OHLC');b=folder/key(model,cost,op,'OLHC')
                for filename in ('metrics.json','diagnostics.json','daily.jsonl','trades.jsonl'):
                    reader=lines if filename.endswith('.jsonl') else load
                    assert reader(a/filename)==reader(b/filename),(model,name,filename)
                path_checks+=1
                daily=lines(a/'daily.jsonl');trades=lines(a/'trades.jsonl');metrics=load(a/'metrics.json')
                assert [r['day'] for r in daily]==expected
                assert D(str(metrics['initial']))==1000
                assert D(str(metrics['operating_cost']))==D(24*op)
                assert len({(t['entry_time'],t['exit_time'],t['side']) for t in trades})==len(trades)
                normalized=[]
                for t in trades:
                    start=datetime.fromisoformat(t['entry_time']);end=datetime.fromisoformat(t['exit_time'])
                    assert start<=end and start.second==end.second==0 and t['side'] in (-1,1)
                    normalized.append(dict(entry_minute=int(start.timestamp())//60,exit_minute=int(end.timestamp())//60,side=t['side']))
                assert all(a['exit_minute']<=b['entry_minute'] for a,b in zip(normalized,normalized[1:]))
                metrics_summary=summaries[group]['runs'][key(model,cost,op,'OHLC')]['metrics']
                assert metrics==metrics_summary
                view,pnl,ret=account_summary(daily,trades,metrics)
                assert len(view['monthly_pnl_usdc'])==24
                assert abs(sum(D(str(x)) for x in view['monthly_pnl_usdc'].values())-sum(pnl))<D('1e-7')
                account[model]=view;pnls[model]=pnl;returns[model]=ret;positions[model]=normalized;daily_data[model]=daily
            models=list(MODELS);matrix=np.array([returns[m] for m in models]);pnlmatrix=np.array([[float(x) for x in pnls[m]] for m in models])
            corr=np.corrcoef(matrix);loss=(pnlmatrix < -1e-9).astype(np.int64);co=loss@loss.T;conditional=pnlmatrix@loss.T
            pairs=[]
            for i,j in combinations(range(11),2):
                ma,mb=models[i],models[j]
                values=pair_stats(pnls[ma],pnls[mb],returns[ma],returns[mb])
                if values['daily_return_correlation'] is None:assert not np.isfinite(corr[i,j])
                else:assert abs(values['daily_return_correlation']-corr[i,j])<1e-12
                assert values['simultaneous_loss_days']==int(co[i,j])
                assert abs(values['b_pnl_on_a_loss_days_usdc']-conditional[j,i])<1e-8
                assert abs(values['a_pnl_on_b_loss_days_usdc']-conditional[i,j])<1e-8
                correlation_checks+=1
                holding=position_overlap(positions[ma],positions[mb]);independent=sweep_overlap(positions[ma],positions[mb])
                assert (holding['same_direction_overlap_minutes'],holding['opposite_direction_overlap_minutes'])==independent
                overlap_checks+=1
                pairs.append(dict(a=ma,b=mb,**values,**holding))
            recovery={}
            for anchor in ('T0','WEEKLY_LONG'):
                interval=account[anchor]['longest_underwater'];assert interval is not None
                reference=[]
                for model in models:
                    part=pnls[model][interval['start_index']:interval['end_index']+1]
                    independent=[p for d,p in zip(expected,pnls[model]) if interval['start']<=d<=interval['end']]
                    assert part==independent and len(part)==interval['days']
                    total=sum(part,D(0));recovery_checks+=1
                    reference.append(dict(model=model,pnl_usdc=float(total),positive=total>D('1e-9')))
                recovery[anchor]=dict(interval=interval,candidates=reference)
            outputs[name]=dict(accounts=account,pairs=pairs,recovery_windows=recovery,
                necessary_profit_and_drawdown_pass=[m for m,a in account.items() if a['net_usdc']>0 and a['max_drawdown_pct']<=5])
            save(OUT/(name+'.json'),outputs[name])
    summary=dict(status='COMPLETE_REUSED_ACCOUNT_DEPENDENCE_DIAGNOSTIC',completed_at_utc=now(),models=list(MODELS),
        cost_conditions={k:dict(necessary_profit_and_drawdown_pass=v['necessary_profit_and_drawdown_pass'],
            account_net_usdc={m:a['net_usdc'] for m,a in v['accounts'].items()},
            net_less_top2_months_usdc={m:a['net_less_top2_months_usdc'] for m,a in v['accounts'].items()},
            positive_during_anchor_windows={anchor:[r['model'] for r in z['candidates'] if r['positive']] for anchor,z in v['recovery_windows'].items()}) for k,v in outputs.items()},
        historical_selection_bias=True,shared_capital_portfolio_tested=False,allocation_chosen=False,
        real_world_fills_verified=False,future_profit_verified=False,new_orders=0,new_schedules=0,
        q004='UNCHANGED_FIRST_FORECAST_OUTCOME_PENDING')
    save(OUT/'summary.json',summary)
    for n,h in {**protected,**sources}.items():assert sha(ROOT/n)==h,n
    save(OUT/'verification.json',dict(status='PASS_SCOPED_STORED_ACCOUNT_DIAGNOSTIC',tests=7,source_accounts=88,
        matching_path_pairs=path_checks,unique_calendar_accounts=44,daily_rows=44*730,
        numpy_pair_checks=correlation_checks,event_sweep_overlap_checks=overlap_checks,recovery_window_subtotals=recovery_checks,
        source_hashes_unchanged=len(sources),protected_hashes_unchanged=len(protected),
        artifacts={p.name:sha(p) for p in OUT.iterdir() if p.is_file()},
        excluded_checks=['No new account replay, portfolio execution, raw minute price replay, margin liquidation or future performance test.']))
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
