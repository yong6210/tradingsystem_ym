"""E012: fixed diagnostic factorial, never a live-risk recommendation."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
from app.research.data.btcusdc import load_public_bundle
from app.research.baseline.account import Costs
from app.research.diagnostics.account_constraints import PROFILES, diagnostic_risk, snapshot_choices, terminal_contrasts
from app.research.diagnostics.account_constraints_engine import simulate
from scripts.run_btcusdc_comparison import annual

OUT=ROOT/'reports/validation/e012_account_constraints_20260917'
PRIOR=ROOT/'reports/validation/e011_trend_pullback_20260917'
DATA=ROOT/'data/historical/btcusdc_public_20260917'


def save(path,data):path.write_text(json.dumps(data,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def main():
    OUT.mkdir(parents=True,exist_ok=False)
    hashes=json.loads((PRIOR/'registration.json').read_text())['source_hashes']
    for name,digest in hashes.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:raise ValueError('source changed: '+name)
    sources=[Path(__file__),ROOT/'app/research/diagnostics/account_constraints.py',
             ROOT/'app/research/diagnostics/account_constraints_engine.py',ROOT/'tests/test_account_constraints.py',
             ROOT/'docs/research/experiments/E012_ACCOUNT_CONSTRAINTS.md',PRIOR/'P4_commands.jsonl']
    hashes.update({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    settings=dict(start='2024-09-01T00:00:00+00:00',end='2026-09-01T00:00:00+00:00',profiles=PROFILES,runs=8,
                  risk={p:asdict(diagnostic_risk(p)) for p in PROFILES},
                  costs={'base':asdict(Costs()),'stress':asdict(Costs(7,5,1))},
                  classification='DIAGNOSTIC_COUNTERFACTUAL_NOT_STRATEGY_SELECTION')
    save(OUT/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),settings=settings,source_hashes=hashes))
    save(OUT/'status.json',dict(status='RUNNING',completed=0))
    try:
        bundle=load_public_bundle(ROOT,DATA)
        start,end=(pd.Timestamp(settings[k]) for k in ('start','end'))
        bundle.require_complete_window(start,end)
        commands=[json.loads(line) for line in (PRIOR/'P4_commands.jsonl').read_text().splitlines()]
        decisions={}
        for row in commands:
            i=bundle.trade.index.get_indexer([pd.Timestamp(row['time'])])[0]
            if i<0 or i in decisions:raise ValueError('missing or duplicate command time')
            decisions[int(i)]=(row['side'],row['close'],row['atr'])
        results={};reproduction={};snapshots={}
        for scenario,params in settings['costs'].items():
            costs=Costs(**params)
            for profile in PROFILES:
                key=f'{scenario}_{profile}'
                result=simulate(bundle.trade,decisions,start,end,costs,diagnostic_risk(profile),funding=bundle.funding)
                folder=OUT/key;folder.mkdir()
                for field in ('events','trades','daily','rejections','sizing_attempts','risk_transitions'):
                    with (folder/(field+'.jsonl')).open('w') as stream:
                        for row in result[field]:stream.write(json.dumps(row,allow_nan=False)+'\n')
                metrics=result['metrics'];metrics['annual']=annual(result['daily'],1000)
                save(folder/'metrics.json',metrics);save(folder/'verification.json',result['verification'])
                results[key]=metrics
                if profile=='contract_half':
                    for name in ('events.jsonl','trades.jsonl','daily.jsonl','rejections.jsonl','metrics.json'):
                        if (folder/name).read_bytes()!=(PRIOR/f'{scenario}_P4'/name).read_bytes():raise ValueError('baseline mismatch: '+name)
                    reproduction[key]='EXACT_E011_P4'
                    counts=dict(attempts=len(result['sizing_attempts']),warned_attempts=0,baseline_rejected=0,
                                rescued_by_full=0,rescued_by_fine=0,rescued_by_both=0)
                    with (folder/'snapshot_choices.jsonl').open('w') as stream:
                        for attempt in result['sizing_attempts']:
                            choices=snapshot_choices(attempt,costs)
                            if choices['contract_half']!=attempt['proposal']:raise ValueError('snapshot baseline mismatch')
                            counts['warned_attempts']+=int(attempt['warned'])
                            if not attempt['proposal']['approved']:
                                counts['baseline_rejected']+=1
                                for name,counter in [('contract_full','rescued_by_full'),('fine_half','rescued_by_fine'),('fine_full','rescued_by_both')]:
                                    counts[counter]+=int(choices[name]['approved'])
                            stream.write(json.dumps(dict(time=attempt['time'],choices=choices),allow_nan=False)+'\n')
                    snapshots[scenario]=counts
                print(key,json.dumps({k:metrics[k] for k in ('return_pct','max_drawdown_pct','cycles','drawdown_halted')}),flush=True)
                save(OUT/'status.json',dict(status='RUNNING',completed=len(results),total=8))
        contrasts={s:terminal_contrasts({p:results[f'{s}_{p}'] for p in PROFILES}) for s in settings['costs']}
        if any(abs(v['reconstruction_error_pp'])>1e-12 for v in contrasts.values()):raise ValueError('contrast arithmetic failed')
        save(OUT/'summary.json',dict(settings=settings,runs=results,reproduction=reproduction,snapshot_checks=snapshots,
                                     contrasts=contrasts,decision='NO_STRATEGY_SELECTION_DIAGNOSTIC_ONLY'))
        save(OUT/'status.json',dict(status='COMPLETE',runs=8))
    except Exception as exc:
        save(OUT/'status.json',dict(status='FAILED',error=str(exc)));raise


if __name__=='__main__':main()
