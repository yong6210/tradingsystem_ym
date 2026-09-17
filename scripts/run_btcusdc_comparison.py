"""E005: fixed 12 runs, actual BTCUSDC public data and signed funding."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
from app.research.data.btcusdc import load_public_bundle
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.comparison.engine import simulate
from app.research.comparison.policies import comparison_policies
from app.research.multistrategy_audit import feature_bank


def save(path, value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def annual(rows, initial):
    previous = initial
    first, last = {}, {}
    for row in rows:
        year = row['day'][:4]
        first.setdefault(year,previous)
        last[year] = row['equity']
        previous = row['equity']
    return {year: dict(start_equity=first[year],end_equity=value,return_pct=100*(value/first[year]-1)) for year,value in last.items()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    data=ROOT/'data/historical/btcusdc_public_20260917'
    settings=dict(start='2024-09-01T00:00:00+00:00',end='2026-09-01T00:00:00+00:00',
                  models=['T0','T1','T2','B0','R0','F0'],risk=asdict(Risk()),
                  costs={'base':asdict(Costs()),'stress':asdict(Costs(7,5,1))},runs=12)
    sources=[Path(__file__),ROOT/'app/research/data/btcusdc.py',ROOT/'app/research/data/minutes.py',
             ROOT/'app/research/multistrategy_audit.py',ROOT/'docs/research/experiments/E005_BTCUSDC_COMPARISON.md',
             data/'manifest.json',data/'validated_overlay.json',data/'gap_probe_manifest.json',
             ROOT/'tests/test_comparison.py',ROOT/'tests/test_btcusdc_bundle.py']
    sources+=list((ROOT/'app/research/baseline').glob('*.py'))+list((ROOT/'app/research/comparison').glob('*.py'))
    save(args.output/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),settings=settings,
        classification='RETROSPECTIVE_MARKET_FILL_PROXY_WITH_OBSERVED_FUNDING',
        source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}))
    save(args.output/'status.json',dict(status='RUNNING',completed=0))
    try:
        bundle=load_public_bundle(ROOT,data)
        bundle.require_complete_window(settings['start'],settings['end'])
        save(args.output/'data_validation.json',dict(status='PASS_REQUESTED_WINDOW',trade_rows=len(bundle.trade),
              unresolved_mark_minutes=int(bundle.mark.c.isna().sum()),unresolved_index_minutes=int(bundle.index_price.c.isna().sum()),
              funding_events=len(bundle.funding),start=settings['start'],end=settings['end']))
        decisions=comparison_policies(bundle.trade,feature_bank(bundle.trade))
        summaries={}
        for scenario,params in settings['costs'].items():
            for model in settings['models']:
                key=f'{scenario}_{model}'
                result=simulate(bundle.trade,decisions[model],pd.Timestamp(settings['start']),pd.Timestamp(settings['end']),
                                Costs(**params),Risk(),funding=bundle.funding)
                folder=args.output/key;folder.mkdir()
                for name in ('events','trades','daily','rejections'):
                    with (folder/(name+'.jsonl')).open('w') as stream:
                        for row in result[name]:stream.write(json.dumps(row,allow_nan=False)+'\n')
                metrics=result['metrics'];metrics['annual']=annual(result['daily'],1000)
                save(folder/'metrics.json',metrics);save(folder/'verification.json',result['verification'])
                summaries[key]=metrics
                print(key,json.dumps({k:metrics[k] for k in ('return_pct','max_drawdown_pct','cycles','funding','drawdown_halted','halt_time')}),flush=True)
                save(args.output/'status.json',dict(status='RUNNING',completed=len(summaries)))
        gates={}
        for model in settings['models']:
            base,stress=summaries[f'base_{model}'],summaries[f'stress_{model}']
            checks=dict(base_positive=base['return_pct']>0,stress_positive=stress['return_pct']>0,
                        no_halt=not base['drawdown_halted'] and not stress['drawdown_halted'],
                        cycles_at_least_100=min(base['cycles'],stress['cycles'])>=100,
                        stress_2025_2026_positive=all(stress['annual'][year]['return_pct']>0 for year in ('2025','2026')))
            gates[model]=dict(checks=checks,status='RESEARCH_CANDIDATE_ONLY' if all(checks.values()) else 'NO_FORWARD_CANDIDATE')
        save(args.output/'summary.json',dict(settings=settings,runs=summaries,screening=gates))
        save(args.output/'status.json',dict(status='COMPLETE',completed=len(summaries)))
    except Exception as exc:
        save(args.output/'status.json',dict(status='FAILED',reason=str(exc)))
        raise


if __name__=='__main__': main()
