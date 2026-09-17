"""E008: exactly eight fixed candidate/control account runs."""
from dataclasses import asdict,replace
from datetime import datetime,timezone
import hashlib,json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
from app.research.data.btcusdc import load_public_bundle
from app.research.multistrategy_audit import feature_bank
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.comparison.engine import simulate
from app.research.candidate_accounts.policies import MODELS,build_policy,entry_conditions
from scripts.run_btcusdc_comparison import annual
from scripts.run_baseline_account import compare_daily

OUT=ROOT/'reports/validation/e008_candidate_accounts_20260917'
OLD=ROOT/'reports/validation/e007_order_rules_20260917/registration.json'


def save(path,data):path.write_text(json.dumps(data,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def main():
    OUT.mkdir(parents=True,exist_ok=False)
    hashes=json.loads(OLD.read_text())['source_hashes']
    for name,digest in hashes.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:raise ValueError('previous source changed: '+name)
    sources=[Path(__file__),ROOT/'app/research/candidate_accounts/policies.py',ROOT/'tests/test_candidate_accounts.py',
             ROOT/'docs/research/experiments/E008_CONFIRMATION_SQUEEZE_ACCOUNTS.md']
    hashes.update({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    settings=dict(start='2024-09-01T00:00:00+00:00',end='2026-09-01T00:00:00+00:00',models=MODELS,runs=8,
        costs={'base':asdict(Costs()),'stress':asdict(Costs(7,5,1))},
        risk={m:asdict(replace(Risk(),stop_atr=4 if m in ('S04','S05') else 2.5,
                             maximum_hold_minutes=1440 if m in ('S04','S05') else 10080)) for m in MODELS})
    save(OUT/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),settings=settings,source_hashes=hashes))
    save(OUT/'status.json',dict(status='RUNNING',completed=0))
    try:
        bundle=load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917')
        start,end=(pd.Timestamp(settings[k]) for k in ('start','end'))
        bundle.require_complete_window(start,end)
        bank=feature_bank(bundle.trade)
        decisions={};coverage={}
        for m in MODELS:
            decisions[m],counts=build_policy(bundle.trade,bank,m)
            period=15 if m in ('S04','S05') else 60
            c=entry_conditions(bank,m)
            mask=(c.index+pd.Timedelta(minutes=1)>=start)&(c.index+pd.Timedelta(minutes=1)<end)
            # Count actual eligible entry events and policy commands separately.
            coverage[m]=dict(full_source_policy_counts=counts,evaluation_entry_events=int(c.loc[mask,'event'].sum()),
                evaluation_entry_commands=sum(side!=0 and start<=bundle.trade.index[i]<end for i,(side,_,_) in decisions[m].items()),
                evaluation_exit_commands=sum(side==0 and start<=bundle.trade.index[i]<end for i,(side,_,_) in decisions[m].items()),period_minutes=period)
        save(OUT/'signal_coverage.json',coverage)
        results={};daily={}
        for scenario,params in settings['costs'].items():
            for model in MODELS:
                key=f'{scenario}_{model}'
                result=simulate(bundle.trade,decisions[model],start,end,Costs(**params),Risk(**settings['risk'][model]),funding=bundle.funding)
                folder=OUT/key;folder.mkdir()
                for field in ('events','trades','daily','rejections'):
                    with (folder/(field+'.jsonl')).open('w') as stream:
                        for row in result[field]:stream.write(json.dumps(row,allow_nan=False)+'\n')
                metrics=result['metrics'];metrics['annual']=annual(result['daily'],1000)
                save(folder/'metrics.json',metrics);save(folder/'verification.json',result['verification'])
                results[key]=metrics;daily[key]=result['daily']
                print(key,json.dumps({k:metrics[k] for k in ('return_pct','max_drawdown_pct','cycles','drawdown_halted')}),flush=True)
                save(OUT/'status.json',dict(status='RUNNING',completed=len(results),total=8))
        paired={f'{scenario}_{a}_minus_{b}':compare_daily(daily[f'{scenario}_{a}'],daily[f'{scenario}_{b}'],start,end)
                for scenario in settings['costs'] for a,b in [('S05','S04'),('S08','S02')]}
        screening={}
        for model in MODELS:
            a,b=(results[f'{s}_{model}'] for s in ('base','stress'))
            checks=dict(base_positive=a['return_pct']>0,stress_positive=b['return_pct']>0,cycles=min(a['cycles'],b['cycles'])>=100,
                        no_halt=not a['drawdown_halted'] and not b['drawdown_halted'],
                        stress_years=all(b['annual'][y]['return_pct']>0 for y in ('2025','2026')))
            if model in ('S05','S08'):
                control='S04' if model=='S05' else 'S02'
                checks['incremental_lower_positive']=paired[f'stress_{model}_minus_{control}']['interval']['interval_bps'][0]>0
            screening[model]=dict(checks=checks,status='RESEARCH_ONLY' if all(checks.values()) else 'NO_FORWARD_CANDIDATE')
        save(OUT/'summary.json',dict(settings=settings,runs=results,paired=paired,screening=screening))
        save(OUT/'status.json',dict(status='COMPLETE',runs=8))
    except Exception as exc:
        save(OUT/'status.json',dict(status='FAILED',error=str(exc)));raise


if __name__=='__main__':main()
