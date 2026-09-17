"""Execute E004's fixed 30 runs; archive every ledger and never tune parameters."""
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.baseline.engine import policies,simulate
from app.research.data.minutes import load_verified_minutes
from app.research.foundation.validation import load_design
from app.research.diagnostics.entry_information import moving_block_interval
from app.research.diagnostics.candidate_screen import independent_interval


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def compare_daily(first,second,start,end):
    """Paired calendar-day account returns; no averaging trade returns."""
    def series(rows):
        data=pd.DataFrame(rows).set_index('day').equity
        prior=data.shift(1,fill_value=1000)
        if (prior<=0).any():
            raise ValueError('nonpositive daily return denominator')
        return data/prior-1
    a,b=series(first),series(second)
    if not a.index.equals(b.index):
        raise ValueError('paired calendars differ')
    differences=(a-b)*10000
    rows=[dict(decision_time=day+'T00:00:00+00:00',excess_bps=float(value)) for day,value in differences.items()]
    ci=moving_block_interval(rows,start,end,28,2000,17092026)
    independent=independent_interval(rows,start,end,28,2000,17092026)
    if not np.allclose(ci['interval_bps'],independent,rtol=0,atol=1e-9):
        raise ValueError('paired interval check failed')
    return dict(mean_daily_difference_bps=float(differences.mean()),interval=ci,days=len(rows))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    design=load_design(ROOT/'configs/research/e001_entry_information.json',ROOT)
    args.output.mkdir(parents=True,exist_ok=False)
    settings=dict(experiment_id='E004-baseline-account-v1',risk=asdict(Risk()),
                  costs={'base':asdict(Costs()),'stress':asdict(Costs(7,5,1))},
                  models=['T0','T1','T2'],run_limit=30,seed=17092026,block_days=28,repetitions=2000,
                  classification='RETROSPECTIVE_PROXY_ACCOUNT_NOT_LIVE_APPROVAL')
    sources=[Path(__file__),ROOT/'docs/research/experiments/E004_BASELINE_ACCOUNT.md',ROOT/'app/research/multistrategy_audit.py',
             ROOT/'app/research/data/minutes.py',ROOT/'app/research/diagnostics/entry_information.py',
             ROOT/'app/research/diagnostics/candidate_screen.py',ROOT/design.dataset.path,ROOT/'configs/research/e001_entry_information.json',
             ROOT/'configs/research/operating_profile_1000_v1.json',ROOT/'docs/research/BINANCE_BTCUSDC_FILTER_SNAPSHOT.json',
             ROOT/'tests/test_baseline_account.py',ROOT/'tests/test_baseline_engine.py']
    sources+=list((ROOT/'app/research/baseline').glob('*.py'))+list((ROOT/'app/research/foundation').glob('*.py'))
    save(args.output/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),settings=settings,
                                            source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                                            runtime=dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__)))
    save(args.output/'status.json',dict(status='RUNNING'))
    try:
        frame=load_verified_minutes(ROOT/design.dataset.path)
        from app.research.multistrategy_audit import feature_bank
        signals=policies(frame,feature_bank(frame))
        windows=[(w.name,w.start,w.end) for w in design.windows]
        windows.append(('continuous',design.windows[0].start,design.windows[-1].end))
        summaries={}
        daily={}
        completed=0
        for scenario,params in settings['costs'].items():
            for model in settings['models']:
                for window,start,end in windows:
                    key=f'{scenario}_{model}_{window}'
                    run_dir=args.output/key
                    run_dir.mkdir()
                    result=simulate(frame,signals[model],start,end,Costs(**params),Risk())
                    for name in ('events','trades','daily','rejections'):
                        with (run_dir/f'{name}.jsonl').open('w') as output:
                            for row in result[name]:output.write(json.dumps(row,allow_nan=False)+'\n')
                    save(run_dir/'verification.json',result['verification'])
                    save(run_dir/'metrics.json',result['metrics'])
                    summaries[key]=result['metrics']
                    if window=='continuous':daily[f'{scenario}_{model}']=result['daily']
                    completed+=1
                    save(args.output/'progress.json',dict(completed=completed,total=30))
                    print(key,json.dumps({k:result['metrics'][k] for k in ('return_pct','max_drawdown_pct','cycles','drawdown_halted','halt_time')}),flush=True)
        comparisons={scenario:compare_daily(daily[f'{scenario}_T1'],daily[f'{scenario}_T0'],windows[-1][1],windows[-1][2]) for scenario in settings['costs']}
        gate={}
        for model in settings['models']:
            base=summaries[f'base_{model}_continuous'];stress=summaries[f'stress_{model}_continuous']
            positive_years=sum(summaries[f'stress_{model}_{w.name}']['return_pct']>0 for w in design.windows)
            checks=dict(base_profitable=base['return_pct']>0,stress_profitable=stress['return_pct']>0,
                        three_positive_stress_periods=positive_years>=3,no_risk_halt=not base['drawdown_halted'] and not stress['drawdown_halted'],
                        sufficient_cycles=min(base['cycles'],stress['cycles'])>=100)
            if model=='T1':checks['primary_difference_lower_above_zero']=comparisons['stress']['interval']['interval_bps'][0]>0
            gate[model]=dict(checks=checks,positive_stress_periods=positive_years,
                            status='NO_FORWARD_CANDIDATE' if not all(checks.values()) else 'REQUIRES_EXECUTION_DATA_REVIEW',
                            note='T0/T2 are references; only T1 has preregistered incremental-effect primary test.')
        save(args.output/'summary.json',dict(settings=settings,runs=summaries,paired_comparison=comparisons,screening=gate,
                                            limitations=['USD-T historical proxy; no actual USDC fills/fees/funding.',
                                                         'Market fill proxy, no partial fills, latency queue or liquidation engine.',
                                                         'Conservative OHLC risk sample, not actual mark tick drawdown.',
                                                         'Historical selection and counterfactual present contract filters.']))
        save(args.output/'status.json',dict(status='COMPLETE',runs=completed))
    except Exception as exc:
        save(args.output/'status.json',dict(status='FAILED',reason=str(exc)))
        raise


if __name__=='__main__':main()
