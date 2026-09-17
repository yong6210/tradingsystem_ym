"""E007: reproduce 4 old runs, then execute exactly 20 fixed rule comparisons."""
from dataclasses import asdict
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
from app.research.data.btcusdc import load_public_bundle
from app.research.multistrategy_audit import feature_bank
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.comparison.engine import simulate as legacy_simulate
from app.research.comparison.policies import comparison_policies
from app.research.order_comparison.adapter import observations,load_profiles
from app.research.order_comparison.engine import simulate
from scripts.run_btcusdc_comparison import annual
from scripts.run_baseline_account import compare_daily

OLD=ROOT/'reports/validation/e005_btcusdc_comparison_20260917'
OUT=ROOT/'reports/validation/e007_order_rules_20260917'


def save(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def main():
    OUT.mkdir(parents=True,exist_ok=False)
    prior=json.loads((OLD/'registration.json').read_text())
    for path,digest in prior['source_hashes'].items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=digest: raise ValueError('legacy source changed: '+path)
    sources=[Path(__file__),ROOT/'docs/research/experiments/E007_ORDER_RULE_COMPARISON.md',
             ROOT/'configs/research/order_rule_profiles_v1.json',ROOT/'app/research/execution/order_rules.py',
             ROOT/'tests/test_order_comparison.py',ROOT/'scripts/run_baseline_account.py',
             ROOT/'app/research/diagnostics/candidate_screen.py',ROOT/'app/research/diagnostics/entry_information.py']
    sources+=list((ROOT/'app/research/order_comparison').glob('*.py'))
    hashes=dict(prior['source_hashes']);hashes.update({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    profiles=load_profiles(ROOT/'configs/research/order_rule_profiles_v1.json')
    profiles.pop('resting_limit_target')
    start=pd.Timestamp('2024-09-01',tz='UTC');end=pd.Timestamp('2026-09-01',tz='UTC')
    settings=dict(start=start.isoformat(),end=end.isoformat(),models=['R0','F0'],profiles=list(profiles),
                  costs={'base':asdict(Costs()),'stress':asdict(Costs(7,5,1))},risk=asdict(Risk()),
                  runs=20,legacy_reproductions=4,excluded=dict(resting_limit_target='NO_FILL_EVIDENCE'))
    save(OUT/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),settings=settings,source_hashes=hashes))
    save(OUT/'status.json',dict(status='RUNNING',stage='data'))
    try:
        bundle=load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917')
        bundle.require_complete_window(start,end)
        bank=feature_bank(bundle.trade)
        old_decisions=comparison_policies(bundle.trade,bank)
        old_summary=json.loads((OLD/'summary.json').read_text())
        reproductions={}
        for scenario,cost in settings['costs'].items():
            for model in settings['models']:
                key=f'{scenario}_{model}'
                result=legacy_simulate(bundle.trade,old_decisions[model],start,end,Costs(**cost),Risk(),funding=bundle.funding)
                for field in ('events','trades','daily','rejections'):
                    previous=[json.loads(line) for line in (OLD/key/(field+'.jsonl')).read_text().splitlines()]
                    if result[field]!=previous: raise ValueError('legacy mismatch: '+key+'/'+field)
                for k,v in result['metrics'].items():
                    if v!=old_summary['runs'][key][k]: raise ValueError('legacy metric mismatch: '+key+'/'+k)
                reproductions[key]='EXACT_MATCH'
                print('reproduction',key,'EXACT_MATCH',flush=True)
        save(OUT/'legacy_reproduction.json',reproductions)
        signals={m:observations(bundle.trade,bank[60],m) for m in settings['models']}
        summaries={};daily={}
        for scenario,cost in settings['costs'].items():
            for model in settings['models']:
                for profile,rules in profiles.items():
                    key=f'{scenario}_{model}_{profile}'
                    result=simulate(bundle.trade,signals[model],start,end,rules,Costs(**cost),Risk(),funding=bundle.funding,marks=bundle.mark.o)
                    folder=OUT/key;folder.mkdir()
                    for field in ('events','trades','daily','rejections'):
                        with (folder/(field+'.jsonl')).open('w') as stream:
                            for row in result[field]: stream.write(json.dumps(row,allow_nan=False)+'\n')
                    result['metrics']['annual']=annual(result['daily'],1000)
                    save(folder/'metrics.json',result['metrics']);save(folder/'verification.json',result['verification'])
                    summaries[key]=result['metrics'];daily[key]=result['daily']
                    save(OUT/'status.json',dict(status='RUNNING',stage='comparison',completed=len(summaries),total=20))
                    print(key,json.dumps({k:result['metrics'][k] for k in ('return_pct','max_drawdown_pct','cycles','drawdown_halted')}),flush=True)
        paired={}
        for scenario in settings['costs']:
            for model in settings['models']:
                for profile in profiles:
                    if profile=='control': continue
                    key=f'{scenario}_{model}_{profile}'
                    paired[key]=compare_daily(daily[key],daily[f'{scenario}_{model}_control'],start,end)
        screening={}
        for model in settings['models']:
            for profile in profiles:
                key=f'{model}_{profile}'
                a,b=(summaries[f'{s}_{key}'] for s in ('base','stress'))
                checks=dict(base_positive=a['return_pct']>0,stress_positive=b['return_pct']>0,
                            no_halt=not a['drawdown_halted'] and not b['drawdown_halted'],
                            cycles=min(a['cycles'],b['cycles'])>=100,
                            stress_years=all(b['annual'][y]['return_pct']>0 for y in ('2025','2026')))
                if profile!='control':checks['paired_lower_positive']=paired['stress_'+key]['interval']['interval_bps'][0]>0
                screening[key]=dict(checks=checks,status='RESEARCH_ONLY' if all(checks.values()) else 'NO_FORWARD_CANDIDATE')
        save(OUT/'summary.json',dict(settings=settings,runs=summaries,paired=paired,screening=screening))
        save(OUT/'status.json',dict(status='COMPLETE',runs=len(summaries),legacy_reproductions=4))
    except Exception as exc:
        save(OUT/'status.json',dict(status='FAILED',error=str(exc)))
        raise


if __name__=='__main__':main()
