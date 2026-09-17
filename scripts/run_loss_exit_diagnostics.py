"""E006: immutable-ledger diagnostics and 24 preregistered paired time caps."""
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from app.research.baseline.account import Costs
from app.research.data.btcusdc import load_public_bundle
from app.research.multistrategy_audit import feature_bank
from app.research.comparison.policies import comparison_policies
from app.research.diagnostics.loss_attribution import cycles_from_events,describe_cycle,group_summary,early_exit,block_total_interval

SOURCE=ROOT/'reports/validation/e005_btcusdc_comparison_20260917'
OUT=ROOT/'reports/validation/e006_loss_exit_diagnostics_20260917'


def save(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def main():
    OUT.mkdir(parents=True,exist_ok=False)
    evidence=json.loads((SOURCE/'independent_verification.json').read_text())
    for name,digest in evidence['artifact_hashes'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest: raise ValueError('E005 artifact changed: '+name)
    registration=json.loads((SOURCE/'registration.json').read_text())
    for name,digest in registration['source_hashes'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest: raise ValueError('E005 code changed: '+name)
    sources=[Path(__file__),ROOT/'app/research/diagnostics/loss_attribution.py',ROOT/'tests/test_loss_attribution.py',
             ROOT/'docs/research/experiments/E006_LOSS_AND_EXIT_DIAGNOSTICS.md',SOURCE/'independent_verification.json']
    save(OUT/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
         classification='POST_HOC_FIXED_TRADE_DIAGNOSTIC_NOT_PORTFOLIO_BACKTEST',
         source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
         caps_minutes={'T0':[1440,4320],'T1':[1440,4320],'T2':[1440,4320],'B0':[360,1440],'R0':[360,1440],'F0':[360,1440]}))
    save(OUT/'status.json',dict(status='RUNNING'))
    try:
        bundle=load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917')
        source_summary=json.loads((SOURCE/'summary.json').read_text())
        start,end=(source_summary['settings'][key] for key in ('start','end'))
        bundle.require_complete_window(start,end)
        bank=feature_bank(bundle.trade)
        decisions=comparison_policies(bundle.trade,bank)
        summaries={};comparisons={}
        for key,metrics in source_summary['runs'].items():
            model=key.split('_')[1]
            cycles=cycles_from_events(lines(SOURCE/key/'events.jsonl'),lines(SOURCE/key/'trades.jsonl'))
            descriptions=[]
            indices=np.array(sorted(decisions[model]))
            sides=np.array([decisions[model][int(i)][0] for i in indices])
            previous=None
            for cycle in cycles:
                row=describe_cycle(cycle,bundle.trade,bank['regime'])
                trade=cycle['trade']
                retained=False
                if previous and previous['side']==trade['side'] and previous['reason'] in ('price_stop','price_stop_gap','time_exit','risk_stop','risk_stop_gap'):
                    mask=(indices>=previous['entry_minute'])&(indices<=trade['entry_minute'])
                    retained=bool(mask.any() and np.all(sides[mask]==trade['side']))
                row['retained_direction_reentry']=retained
                row['net_R']=cycle['net']/trade['planned_loss']
                descriptions.append(row)
                previous=trade
            folder=OUT/key;folder.mkdir()
            with (folder/'cycles.jsonl').open('w') as output:
                for row in descriptions: output.write(json.dumps(row,allow_nan=False)+'\n')
            gross=sum(r['gross'] for r in descriptions);fees=sum(r['fees'] for r in descriptions);funding=sum(r['funding_paid'] for r in descriptions)
            net=sum(r['net'] for r in descriptions)
            if not np.isclose(net,metrics['final_equity']-1000,rtol=0,atol=1e-7): raise ValueError('aggregate net mismatch')
            summaries[key]=dict(cycles=len(cycles),gross=gross,fees=fees,funding=funding,net=net,
                    net_wins=sum(r['net']>0 for r in descriptions),gross_positive_net_negative=sum(r['gross_positive_net_negative'] for r in descriptions),
                    positive_close_then_net_loss=sum(r['positive_close_then_net_loss'] for r in descriptions),
                    median_hold_minutes=float(np.median([r['holding_minutes'] for r in descriptions])),
                    mean_net_R=float(np.mean([r['net_R'] for r in descriptions])),
                    groups={field:group_summary(descriptions,field) for field in ('reason','side','holding_bucket','entry_regime','retained_direction_reentry')})
            costs=Costs(**metrics['costs'])
            caps=(1440,4320) if model.startswith('T') else (360,1440)
            comparisons[key]={}
            for cap in caps:
                pairs=[dict(entry_time=c['trade']['entry_time'],**early_exit(c,bundle.trade,costs,cap)) for c in cycles]
                stats=block_total_interval(pairs,start,end)
                yearly={}
                for year in ('2024','2025','2026'):
                    selected=[r for r in pairs if r['entry_time'].startswith(year)]
                    yearly[year]=dict(trades=len(selected),changed=sum(r['changed'] for r in selected),delta=sum(r['delta'] for r in selected))
                stats.update(changed=sum(r['changed'] for r in pairs),improved=sum(r['delta']>1e-8 for r in pairs),
                             worsened=sum(r['delta']< -1e-8 for r in pairs),yearly=yearly)
                comparisons[key][str(cap)]=stats
                save(folder/f'cap_{cap}.json',dict(stats=stats,pairs=pairs))
            print(key,json.dumps(dict(net=net,gross=gross,fees=fees,funding=funding,caps=comparisons[key])),flush=True)
        gates={}
        for model in source_summary['settings']['models']:
            gates[model]={}
            for cap in comparisons['base_'+model]:
                values=[comparisons[s+'_'+model][cap] for s in ('base','stress')]
                gates[model][cap]=all(v['total']>0 and v['interval95'][0]>0 for v in values)
        save(OUT/'summary.json',dict(attribution=summaries,paired_caps=comparisons,followup_screen=gates,
                                    interpretation='Arithmetic on frozen entries, not a new account return or causal evidence.'))
        save(OUT/'status.json',dict(status='COMPLETE',ledgers=12,paired_comparisons=24,cycles=sum(s['cycles'] for s in summaries.values())))
    except Exception as exc:
        save(OUT/'status.json',dict(status='FAILED',error=str(exc)))
        raise


if __name__=='__main__':main()
