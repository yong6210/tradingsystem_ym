"""Q006: fixed descriptive sample feasibility; no future outcomes or fitted models."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal as D,localcontext
import hashlib,json,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.diagnostics.forward_sample import planning,rolling_counts,count_summary
OUT=ROOT/'reports/validation/q006_forward_sample_feasibility_20260919'
SOURCE=ROOT/'reports/validation/e040_daily_flow_forecast_20260919'
Q003=ROOT/'reports/validation/q003_forecast_expectation_audit_20260919'
Q005=ROOT/'reports/validation/q005_carry_capital_ceiling_20260919'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text())
def now():return datetime.now(timezone.utc).isoformat()
def save(p,x):
    with p.open('x') as f:json.dump(x,f,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n')


def main():
    if OUT.exists():raise ValueError('preserve previous Q006 attempt')
    prior=load(Q005/'registration.json')
    protected={**prior['protected_hashes'],**prior['source_hashes']}
    for n,h in protected.items():assert sha(ROOT/n)==h,n
    for folder in (Q003,Q005):
        for p in folder.rglob('*'):
            if p.is_file():protected[str(p.relative_to(ROOT))]=sha(p)
    for n in ['PRICE_signals.json','base_PRICE_events.json','stress_PRICE_events.json']:
        assert sha(SOURCE/n)==load(SOURCE/'verification.json')['artifacts'][n]
        protected[str((SOURCE/n).relative_to(ROOT))]=sha(SOURCE/n)
    names=['app/research/diagnostics/forward_sample.py','scripts/check_forward_sample_feasibility.py',
           'tests/test_forward_sample.py','docs/research/experiments/Q006_FORWARD_SAMPLE_FEASIBILITY.md']
    OUT.mkdir()
    save(OUT/'registration.json',dict(registered_at_utc=now(),scope='REUSED_DATA_DESCRIPTIVE_PLANNING_ONLY',
        horizon_calendar_days=90,selectors=['original_H','exploratory_2H'],costs=['base','stress'],
        inferential_claims=False,future_outcomes_accessed=False,source_hashes={n:sha(ROOT/n) for n in names},
        protected_hashes=protected,new_models=0,new_backtests=0,new_orders=0,new_schedules=0))
    t=subprocess.run([sys.executable,'-m','unittest','tests.test_forward_sample','-v'],cwd=ROOT,capture_output=True,text=True)
    with (OUT/'tests.log').open('x') as f:f.write(t.stdout+t.stderr)
    if t.returncode:raise ValueError(t.stderr)
    signals=load(SOURCE/'PRICE_signals.json');events={c:load(SOURCE/(c+'_PRICE_events.json')) for c in ('base','stress')}
    dates=[datetime.fromisoformat(r['boundary']) for r in signals]
    assert len(dates)==729 and len(set(dates))==729
    assert all(b-a==timedelta(days=1) for a,b in zip(dates,dates[1:]))
    assert dates[0].isoformat()=='2024-09-01T00:00:00+00:00' and dates[-1].isoformat()=='2026-08-30T00:00:00+00:00'
    for row in signals:
        assert row['threshold_bps']>0
        assert row['side']==((1 if row['prediction_bps']>0 else -1) if abs(row['prediction_bps'])>row['threshold_bps'] else 0)
    for cost,entries in events.items():
        for signal,event in zip(signals,entries,strict=True):
            assert event['entry_time']==signal['entry_time'] and event['exit_time']==signal['exit_time']
            assert event['side']==signal['side']
            assert abs(event['gross_bps']-signal['side']*signal['target_bps'])<1e-7
            residual=D(str(event['gross_bps']))-sum(D(str(event[k])) for k in ('execution_bps','fee_bps','funding_bps','net_bps'))
            assert abs(residual)<D('1e-7')
    results={};windows={};moment_checks=0
    for name,multiple in [('original_H',1),('exploratory_2H',2)]:
        selected=[int(abs(r['prediction_bps'])>multiple*r['threshold_bps']) for r in signals]
        counts=rolling_counts(selected,90)
        direct=[sum(selected[i:i+90]) for i in range(640)]
        assert counts==direct
        windows[name]=[dict(start=dates[i].isoformat(),last_boundary=dates[i+89].isoformat(),active_days=n) for i,n in enumerate(counts)]
        result=dict(rolling_90_day_counts=count_summary(counts),costs={})
        old=load(Q003/'summary.json')['selected']['PRICE']
        old=old['active'] if multiple==1 else old['bands']['above_2H']
        assert sum(selected)==old['n']
        for cost in ('base','stress'):
            values=[e['net_bps'] for keep,e in zip(selected,events[cost],strict=True) if keep]
            metrics=planning(values,len(dates),90)
            with localcontext() as context:
                context.prec=45
                exact=[D(str(x)) for x in values];n=len(exact)
                mean=sum(exact)/n
                variance=(sum(x*x for x in exact)-sum(exact)**2/n)/(n-1)
                sd=variance.sqrt();se=sd/D(metrics['rounded_reference_count']).sqrt()
                for key,value in [('historical_mean_bps',mean),('historical_sample_sd_bps',sd),('iid_planning_standard_error_bps',se)]:
                    assert abs(D(str(metrics[key]))-value)<D('1e-8');moment_checks+=1
                assert abs(D(str(metrics['reference_count']))-D(90)*n/729)<D('1e-10')
            assert abs(metrics['historical_mean_bps']-old[cost+'_net_bps'])<1e-8
            result['costs'][cost]=metrics
        results[name]=result
    save(OUT/'rolling_counts.json',windows)
    summary=dict(status='DESCRIPTIVE_PLANNING_LIMITS_NOT_FUTURE_INFERENCE',completed_at_utc=now(),
        historical_calendar_days=729,planning_calendar_days=90,results=results,
        historical_data_reused=True,strong_rule_posthoc_selected=True,independent_future_outcomes=0,
        iid_assumptions_verified=False,q004_policy_changed=False,new_models=0,new_market_requests=0,
        uncertainty_scope='Historical signal clustering and IID standard-error planning scale only; not a future interval or power calculation.',
        method_source='https://www.itl.nist.gov/div898/handbook/eda/section3/eda352.htm')
    save(OUT/'summary.json',summary)
    reg=load(OUT/'registration.json')
    for n,h in {**protected,**reg['source_hashes']}.items():assert sha(ROOT/n)==h,n
    save(OUT/'verification.json',dict(status='PASS_DESCRIPTIVE_CALCULATIONS',tests=5,
        dated_signal_rows=729,cost_event_rows_checked=1458,rolling_counts_checked=1280,decimal_moment_checks=moment_checks,
        protected_hashes_unchanged=len(protected),source_hashes_unchanged=len(names),
        artifacts={p.name:sha(p) for p in OUT.iterdir() if p.is_file()},
        inference_validated=False,future_return_verified=False))
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
