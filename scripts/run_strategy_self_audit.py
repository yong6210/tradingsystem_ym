"""Fixed, retrospective mechanism ablations; no parameter selection or promotion."""
import hashlib
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.multistrategy_audit import Model, feature_bank, signals, simulate
from scripts.run_multistrategy_research import load_minutes, dump

def main():
    out = ROOT/'reports/validation/strategy_self_audit_20260917'
    out.mkdir(exist_ok=True)
    if (out/'results.json').exists():
        raise SystemExit('Completed audit exists; refusing overwrite')
    old = json.loads((ROOT/'reports/validation/multistrategy_20260917/results.json').read_text())
    selected = old['selected']
    swing, rotation, breakout = (selected[k] for k in ('swing_trend','inventory_rotation','channel_breakout'))
    route = dict(uptrend=swing, downtrend=swing, range=rotation, transition=breakout)
    cases = [
        ('swing_baseline',dict(model_name=swing)),
        ('swing_regime_gate',dict(routing=dict(uptrend=swing,downtrend=swing))),
        ('swing_gate_controls',dict(routing=dict(uptrend=swing,downtrend=swing),final_controls=True)),
        ('combined_baseline',dict(routing=route,final_controls=True)),
        ('rotation_baseline',dict(model_name=rotation)),
        ('rotation_no_add',dict(model_name=rotation,no_add=True)),
        ('rotation_add_priority',dict(model_name=rotation,add_priority=True)),
        ('rotation_frozen_atr',dict(model_name=rotation,frozen_target_atr=True)),
        ('rotation_priority_frozen',dict(model_name=rotation,add_priority=True,frozen_target_atr=True)),
        ('rotation_ttl15',dict(model_name=rotation,ttl=15)),
        ('breakout_baseline',dict(model_name=breakout)),
        ('breakout_own_exit',dict(model_name=breakout,family_exits=True)),
        ('swing_ttl15',dict(model_name=swing,ttl=15)),
        ('combined_dd_audit',dict(routing=route,final_controls=True,conservative_dd=True)),
    ]
    plan = dict(status='RETROSPECTIVE_DIAGNOSTIC_NOT_OUT_OF_SAMPLE',cases=cases,
                periods={k:old['protocol'][k] for k in ('validation','evaluation')},
                caveats=['Previously observed data; no best-case selection.', 'No-add preserves one-third seed risk.',
                         'Add priority cancels profit quote on eligible add decision; not independent simultaneous orders.',
                         'TTL sensitivity is not a market-entry execution test.'],
                hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
                        ['app/research/multistrategy.py','app/research/multistrategy_audit.py', 'scripts/run_strategy_self_audit.py']})
    dump(out/'protocol.json',plan)
    minutes=load_minutes(); bank=feature_bank(minutes)
    models=[Model(n.rsplit('_v',1)[0],int(n.rsplit('_v',1)[1])) for n in selected.values()]
    sets={m.name:signals(minutes,bank,m) for m in models}
    own={m.name:signals(minutes,bank,m,family_exits=True) for m in models}
    results={}
    for period, dates in plan['periods'].items():
        results[period]={}
        for name, arguments in cases:
            args=arguments.copy(); use_own=args.pop('family_exits',False)
            r=simulate(minutes,own if use_own else sets,bank['regime'],*dates,record_events=True,**args)
            results[period][name]=r
            dump(out/'partial.json',results)
            print(period,name,round(r['return_pct'],5),round(r['max_drawdown_pct'],5),r['cycles'],flush=True)
    dump(out/'results.json',dict(protocol=plan,results=results))
if __name__=='__main__': main()
