"""E030 registered four-condition fixed-rule two-futures account replay."""
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
import json
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from scripts.run_carry_pair_drill import save,load,digest,check_hashes,test_ids
from scripts.audit_pair_account import verify,verify_signals
from app.research.diagnostics.pair_account import run,signals
from app.research.diagnostics.review_metrics import calendar_risk
from app.research.diagnostics.concentration import concentration
from app.research.diagnostics.direction_controls import daily_returns


def lines(path):return [json.loads(x) for x in path.read_text().splitlines()]


def write_lines(path,rows):
    with path.open('x') as stream:
        for row in rows:stream.write(json.dumps(row,default=str,allow_nan=False)+'\n')


def metrics(daily):
    peak=1000.;dd=0.;annual={};previous=1000.
    for row in daily:
        e=row['equity'];peak=max(peak,e);dd=max(dd,1-e/peak)
        y=row['day'][:4];annual[y]=annual.get(y,0)+e-previous;previous=e
    return dict(calendar_risk=calendar_risk(daily),max_daily_drawdown_pct=100*dd,annual_net_usdc=annual)


def main():
    out=ROOT/'reports/validation/e030_pair_account_20260919';out.mkdir(exist_ok=False)
    base=ROOT/'reports/validation/e029_pair_mark_supplement_20260919'
    original=ROOT/'reports/validation/e029_pair_feasibility_20260919'
    reg=load(base/'registration.json');protected=reg['source_hashes']|reg['protected_hashes']
    for folder in (base,ROOT/'reports/validation/e029_pair_review_20260919'):
        proof=load(folder/'verification.json')
        for n,h in proof['artifacts'].items():protected[str((folder/n).relative_to(ROOT))]=h
        protected[str((folder/'verification.json').relative_to(ROOT))]=digest(folder/'verification.json')
        if 'report_path' in proof:protected[proof['report_path']]=proof['report_sha256']
    names=('app/research/diagnostics/pair_account.py','scripts/audit_pair_account.py','scripts/run_pair_account.py',
        'tests/test_pair_account.py','docs/research/experiments/E030_PAIR_ACCOUNT.md',
        'app/research/diagnostics/review_metrics.py','app/research/diagnostics/concentration.py',
        'app/research/diagnostics/economics.py','app/research/diagnostics/direction_controls.py')
    sources={n:digest(ROOT/n) for n in names};check_hashes(sources);check_hashes(protected)
    rows=lines(base/'joined_hourly.jsonl')
    if len(rows)!=17520 or any(r['eth_data_missing'] for r in rows):raise ValueError('source coverage')
    if [r['time_ms'] for r in rows]!=list(range(rows[0]['time_ms'],rows[-1]['time_ms']+3600000,3600000)):raise ValueError('source calendar')
    cc=load(original/'current_contracts.json')
    for c in cc.values():
        for k in ('step','min_qty','max_qty','min_notional'):c[k]=D(c[k])
    funding=[dict(e,leg='btc') for e in lines(ROOT/'reports/validation/e028_carry_rule_replay_20260919/funding_inputs.jsonl')]
    funding.extend(dict(leg='eth',time_ms=e['fundingTime'],mark=e['markPrice'],rate=e['fundingRate']) for e in load(original/'eth_funding.json'))
    if len({(e['leg'],e['time_ms']) for e in funding})!=len(funding):raise ValueError('duplicate source funding')
    configs={f'{name}_ops{cost}':dict(slip_bps=slip,extra_funding_bps=extra,monthly_cost=cost)
        for name,slip,extra in [('base',2,0),('stress',5,1)] for cost in (0,2)}
    suite=unittest.defaultTestLoader.loadTestsFromNames(('tests.test_pair_account',))
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
        classification='CONDITIONAL_HOURLY_FIXED_TWO_FUTURES_ACCOUNT_NOT_EXECUTION_PROOF',
        source_hashes=sources,protected_hashes=protected,scenarios=configs,test_ids=list(test_ids(suite)),
        candidate_count=1,automatic_retries=0,new_public_requests=0,actual_orders=0,
        comparison='T0 E025 operations-zero reference only; risk clock, warmup and sizing differ'))
    for n in sources:
        dest=out/'source_snapshot'/n;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((ROOT/n).read_bytes())
    with (out/'tests.log').open('x') as stream:r=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    save(out/'tests.json',dict(executed=r.testsRun,failures=len(r.failures),errors=len(r.errors),skipped=len(r.skipped)))
    if not r.wasSuccessful() or r.skipped:raise ValueError('tests failed')
    z=signals(rows);signal_audit=verify_signals(rows,z);save(out/'signal_audit.json',signal_audit)
    write_lines(out/'signals.jsonl',[dict(time_ms=row['time_ms'],available_ms=row['time_ms']+3600000,z=value) for row,value in zip(rows,z)])
    results={}
    for name,config in configs.items():
        print('Running',name,flush=True);folder=out/name;folder.mkdir()
        result=run(rows,funding,cc,signal_values=z,**config)
        audit=verify(rows,funding,result,config);save(folder/'independent_audit.json',audit)
        for key in ('hourly','ledger','orders','cycles','rejections'):write_lines(folder/(key+'.jsonl'),result[key])
        save(folder/'state.json',result['state'])
        daily=[]
        for h in result['hourly']:
            point=dict(day=h['day'],equity=float(h['equity']),halt=h['halt'])
            if daily and daily[-1]['day']==h['day']:daily[-1]=point
            else:daily.append(point)
        write_lines(folder/'daily.jsonl',daily)
        cash=[];spent=0
        for i,d in enumerate(daily):
            if i==len(daily)-1 or daily[i+1]['day'][:7]!=d['day'][:7]:spent+=config['monthly_cost']
            cash.append(dict(day=d['day'],equity=1000-spent))
        write_lines(folder/'cash_control.jsonl',cash)
        summary=dict(**audit,**metrics(daily),permanent_halt=result['state']['halt'],
            first_halt=next((h['time_ms'] for h in result['hourly'] if h['halt']),None),
            cycle_exit_reasons=dict(Counter(c['reason'] for c in result['cycles'])),
            concentration=concentration([dict(id=c['id'],net=c['net_pnl']) for c in result['cycles']],(1,5,10)) if result['cycles'] else None,
            sizing_or_margin_rejected_intents=len(result['rejections']),
            rejection_reasons=dict(Counter(reason for a in result['rejections'] for reason in a['reasons'])),
            cash_control_terminal=cash[-1]['equity'],active_hours=sum(any(D(q) for q in h['position'].values()) for h in result['hourly']))
        if not config['monthly_cost']:
            prefix=name.split('_')[0];ref=ROOT/'reports/validation/e025_matched_fee_common_20260919'/f'{prefix}_T0'
            t0=lines(ref/'daily.jsonl')
            if [p['day'] for p in daily]!=[p['day'] for p in t0]:raise ValueError('T0 calendar mismatch')
            a,b=daily_returns(daily,1000),daily_returns(t0,1000)
            summary['t0_reference']=dict(terminal_equity=t0[-1]['equity'],**metrics(t0),
                both_loss_days=int(((a<0)&(b<0)).sum()),pair_loss_days=int((a<0).sum()),t0_loss_days=int((b<0).sum()),
                daily_correlation=float(np.corrcoef(a,b)[0,1]) if a.std() and b.std() else None,
                risk_clocks_and_exposure_not_matched=True)
        else:summary['t0_reference']=None
        save(folder/'summary.json',summary);results[name]=summary
        print(name,audit['net_usdc'],'cycles',audit['cycles'],'halt',summary['permanent_halt'],flush=True)
    a,b=results['base_ops0'],results['stress_ops0']
    necessary=dict(base_positive=D(a['net_usdc'])>0,stress_positive=D(b['net_usdc'])>0,
        no_permanent_halt=not a['permanent_halt'] and not b['permanent_halt'],
        cycles_at_least_100=min(a['cycles'],b['cycles'])>=100,
        stress_2025_2026_positive=all(b['annual_net_usdc'][y]>0 for y in ('2025','2026')))
    save(out/'summary.json',dict(scenarios=results,necessary_checks=necessary,
        decision='NECESSARY_SCREEN_PASS_NOT_ADOPTION' if all(necessary.values()) else 'FIXED_CANDIDATE_FAILS_NECESSARY_SCREEN',
        strategy_adopted=False,combination_run=False,actual_orders=0))
    now=datetime.now(timezone.utc);public=ROOT/'reports/validation/e022_signal_boundary_20260919/public'
    save(out/'scheduled_observation.json',dict(checked_at=now.isoformat(),summary_present=(public/'summary.json').exists(),
        failure_present=(public/'failure.json').exists(),target_in_future=now<datetime.fromisoformat('2026-09-18T20:00:00+00:00'),modified=False))
    check_hashes(sources);check_hashes(protected)
    save(out/'verification.json',dict(status='PASS_REGISTERED_CONDITIONAL_ACCOUNT_AUDIT',tests=r.testsRun,
        accounts=4,candidate_hypotheses=1,independent_hourly_checks=sum(s['hourly_checks'] for s in results.values()),
        source_hashes_unchanged=len(sources),protected_hashes_unchanged=len(protected),
        artifacts={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))
    print(json.dumps(necessary),flush=True)


if __name__=='__main__':main()
