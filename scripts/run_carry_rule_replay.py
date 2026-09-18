"""Registered E028 conditional replay. Historical local inputs, no network."""
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
from scripts.run_carry_pair_drill import save,load,digest,check_hashes,test_ids
from app.research.data.btcusdc import load_public_bundle
from app.research.diagnostics.carry_rule_replay import run,independent_audit,iso
from app.research.diagnostics.review_metrics import calendar_risk


def lines(path):
    import json
    return [json.loads(s) for s in path.read_text().splitlines()]


def jsonlines(path,rows):
    import json
    with path.open('x') as stream:
        for row in rows:stream.write(json.dumps(row,default=str,allow_nan=False)+'\n')


def main():
    out=ROOT/'reports/validation/e028_carry_rule_replay_20260919'
    out.mkdir(parents=True,exist_ok=False)
    names=('scripts/run_carry_rule_replay.py','app/research/diagnostics/carry_rule_replay.py',
        'tests/test_carry_rule_replay.py','docs/research/experiments/E028_CARRY_RULE_REPLAY.md',
        'scripts/run_carry_pair_drill.py','app/research/diagnostics/review_metrics.py')
    sources={n:digest(ROOT/n) for n in names}
    previous=ROOT/'reports/validation/e027_carry_pair_20260919'
    reg=load(previous/'registration.json');proof=load(previous/'verification.json')
    protected=reg['source_hashes']|reg['protected_hashes']
    for n,h in proof['artifacts'].items():protected[str((previous/n).relative_to(ROOT))]=h
    protected[str((previous/'verification.json').relative_to(ROOT))]=digest(previous/'verification.json')
    data=ROOT/'data/historical/btcusdc_public_20260917'
    manifest=load(data/'manifest.json');overlay=load(data/'validated_overlay.json')
    inputs={r['path']:r['sha256'] for r in manifest['archives']+manifest['funding_sources']+overlay['supplements']}
    for n in ('manifest.json','validated_overlay.json','gap_probe_manifest.json'):
        inputs[str((data/n).relative_to(ROOT))]=digest(data/n)
    old=ROOT/'reports/validation/e026_carry_feasibility_20260919'
    for n in ('joined_hourly.jsonl','summary.json'):
        inputs[str((old/n).relative_to(ROOT))]=digest(old/n)
    check_hashes(sources);check_hashes(protected);check_hashes(inputs)
    scenarios={name:dict(slip_bps=slip,extra_funding_bps=extra,monthly_cost=cost)
        for prefix,slip,extra in [('base',2,0),('stress',5,1)]
        for cost in (0,2) for name in [prefix+'_ops'+str(cost)]}
    suite=unittest.defaultTestLoader.loadTestsFromNames(('tests.test_carry_rule_replay','tests.test_carry_pair'))
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
        classification='CONDITIONAL_HOURLY_SINGLE_CYCLE_REPLAY_NOT_EXECUTION_PROOF',
        source_hashes=sources,protected_hashes=protected,input_hashes=inputs,
        test_ids=list(test_ids(suite)),scenarios=scenarios,automatic_retries=0,real_orders=0,public_requests=0))
    for n in sources:
        dest=out/'source_snapshot'/n;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((ROOT/n).read_bytes())
    with (out/'tests.log').open('x') as stream:r=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    save(out/'tests.json',dict(executed=r.testsRun,failures=len(r.failures),errors=len(r.errors),skipped=len(r.skipped)))
    if not r.wasSuccessful() or r.skipped:raise ValueError('registered tests failed')
    print('30 scoped tests passed; loading frozen prices.',flush=True)
    bundle=load_public_bundle(ROOT,data)
    start,end=pd.Timestamp('2024-09-01',tz='UTC'),pd.Timestamp('2026-09-01',tz='UTC')
    bundle.require_complete_window(start,end)
    mark=bundle.mark.loc[(bundle.mark.index>=start)&(bundle.mark.index<end)].resample('h').agg(dict(o='first',c='last'))
    expected=pd.date_range(start,end,freq='h',inclusive='left')
    if not mark.index.equals(expected):raise ValueError('mark hour calendar')
    rows=lines(old/'joined_hourly.jsonl')
    if [pd.Timestamp(row['hour']) for row in rows]!=list(expected):raise ValueError('E026 calendar')
    for row,(t,m) in zip(rows,mark.iterrows(),strict=True):
        row['time_ms']=int(t.value//1_000_000);row['mark_open']=str(m.o);row['mark_close']=str(m.c)
    funding=[dict(time_ms=e['fundingTime'],rate=e['fundingRate'],mark=e['markPrice'])
        for e in bundle.funding if start.value//1_000_000<=e['fundingTime']<end.value//1_000_000]
    jsonlines(out/'hourly_inputs.jsonl',rows);jsonlines(out/'funding_inputs.jsonl',funding)
    save(out/'data_fitness.json',dict(hourly_rows=len(rows),funding_events=len(funding),missing_join_rows=0,
        duplicate_hours=0,execution_quotes_available=False,actual_spot_commission_verified=False,
        risk_clock='hour open and funding event, not intra-hour extremes',
        price_proxy='same-hour opens held constant during scripted 3-second fallback',
        mark_high_used_for_decision=False,close_used_for_decision=False))
    del bundle,mark
    results={}
    for name,config in scenarios.items():
        print('Starting',name,flush=True)
        folder=out/name;result=run(folder,rows,funding,**config)
        audit=independent_audit(folder,rows,result,config['slip_bps'])
        daily=[]
        for p in result['rows']:
            day=p['hour'][:10];point=dict(day=day,equity=float(p['closeout_equity']))
            if daily and daily[-1]['day']==day:daily[-1]=point
            else:daily.append(point)
        risk=calendar_risk(daily);peak=1000.;dd=0.
        for p in daily:
            peak=max(peak,p['equity']);dd=max(dd,1-p['equity']/peak)
        jsonlines(folder/'daily.jsonl',daily)
        old_key=('base' if name.startswith('base') else 'stress')+'_spotfee_10'
        baseline=load(old/'summary.json')['runs'][old_key]['theoretical_terminal_pair_equity']
        summary=dict(**audit,first_exit=result['first_exit'],opened_at=result['opened_at'],
            exit_utc=iso(result['first_exit']['time_ms']) if result['first_exit'] else None,
            calendar_risk=risk,max_daily_drawdown_pct=dd*100,
            no_stop_E026_terminal_equity=baseline,
            change_vs_E026_usdc=float(D(audit['terminal_equity'])-D(str(baseline))),
            comparison_limits='E027 risk rules plus ordered fills, end at last hour open, illustrative monthly costs; not isolated stop causality',
            selected_for_combination=False,actual_orders=0)
        save(folder/'summary.json',summary);results[name]=summary
        print(name,audit['net_usdc'],summary['exit_utc'],flush=True)
    now=datetime.now(timezone.utc);public=ROOT/'reports/validation/e022_signal_boundary_20260919/public'
    save(out/'scheduled_observation.json',dict(checked_at=now.isoformat(),summary_present=(public/'summary.json').exists(),
        failure_present=(public/'failure.json').exists(),target_in_future=now<datetime.fromisoformat('2026-09-18T20:00:00+00:00'),modified=False))
    check_hashes(sources);check_hashes(protected);check_hashes(inputs)
    save(out/'summary.json',dict(scenarios=results,decision='CONDITIONAL_QUESTION_COMPLETE_NO_ADOPTION',
        forward_profitability_ready=False,live_ready=False,actual_orders=0))
    save(out/'verification.json',dict(status='PASS_REGISTERED_CONDITIONAL_REPLAY',tests=r.testsRun,
        scenarios=len(results),hourly_observations=sum(a['hours'] for a in results.values()),
        independent_balance_checks=sum(a['balance_checks'] for a in results.values()),
        source_hashes_unchanged=len(sources),protected_hashes_unchanged=len(protected),input_hashes_unchanged=len(inputs),
        artifacts={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))
    print('Complete:',out,flush=True)


if __name__=='__main__':main()
