"""E038: fixed weekly momentum, explicit user risk policy."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal as D, ROUND_FLOOR, ROUND_CEILING
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.data.btcusdc import load_public_bundle
from app.research.diagnostics.intrabar_engine import simulate
from app.research.diagnostics.weekly_momentum import sessions, decisions, verify_signals, event_returns, event_summary, bootstrap
from scripts.run_direction_controls import save, load, digest, verify_daily
from scripts.run_intrabar_risk_paths import verify_stops
from scripts.report_btcusdc_comparison import verify_run
from scripts.run_btcusdc_comparison import annual
from scripts.run_time_exit_policy import diagnostics, START, END, check_hashes


def verify_event_costs(minutes, signals, rows, funding, costs, model):
    """Separate Decimal formulas without fill/funding helper reuse."""
    rate, slip, stress, tick = map(lambda x:D(str(x)),
                                  [costs.fee_bps/10000, costs.slippage_bps/10000, costs.funding_bps_8h/10000, costs.tick])
    for sig, row in zip(signals, rows, strict=True):
        side = sig['side'] if model == 'MOMENTUM' else 1
        a, b = (D(str(minutes.iloc[sig[k]].o)) for k in ('entry_minute','exit_minute'))
        def fill(p, s):
            return ((p*(1+D(s)*slip)/tick).to_integral_value(rounding=ROUND_CEILING if s==1 else ROUND_FLOOR))*tick
        entry, exit_price = (fill(a,side),fill(b,-side)) if side else (a,b)
        fee = (entry+exit_price)*rate if side else D(0)
        entry_ms, exit_ms = (int(pd.Timestamp(sig[k]).timestamp()*1000) for k in ('entry_time','exit_time'))
        paid = D(0)
        for event in funding:
            processing_ms = ((event['fundingTime']+59999)//60000)*60000
            if entry_ms < processing_ms <= exit_ms:
                paid += D(str(event['markPrice']))*(D(side)*D(str(event['fundingRate']))+D(abs(side))*stress)
        expected = (D(side)*(exit_price-entry)-fee-paid)/a*10000
        if abs(float(expected)-row['net_bps']) > 1e-7:
            raise ValueError('independent event cost mismatch')
    return dict(status='PASS', events=len(rows), implementation='DECIMAL_PRICES_FEES_FUNDING')


def main(out):
    risk = Risk(cycle_fraction=.0025, aggregate_fraction=.005, daily_stop=.01,
                warning=.025, halt=.04, maximum_hold_minutes=10080)
    assert risk.warning < risk.halt < .05
    costs = {'base':Costs(2.5,2,0), 'stress':Costs(2.5,5,1)}
    prior = load(ROOT/'reports/validation/e036_session_reversal_20260919/registration.json')
    sources = dict(prior['source_hashes'])
    for name in ['app/research/diagnostics/weekly_momentum.py','scripts/run_weekly_momentum.py',
                 'tests/test_weekly_momentum.py','docs/research/experiments/E038_WEEKLY_MOMENTUM.md',
                 'configs/research/user_profit_risk_context_20260919.json']:
        sources[name] = digest(ROOT/name)
    check_hashes(sources)
    context = load(ROOT/'configs/research/user_profit_risk_context_20260919.json')
    assert context['risk_preference']['maximum_drawdown_fraction'] == .05
    settings = dict(start=START,end=END,risk=asdict(risk),costs={k:asdict(v) for k,v in costs.items()},
                    models=['MOMENTUM','LONG'],paths=['OHLC','OLHC'],account_runs=8, operating_cost=None)
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),settings=settings,
                                     source_hashes=sources,source_data_reused=True,actual_orders=0))
    for name in sources:
        p=out/'source_snapshot'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/name).read_bytes())
    suite = unittest.defaultTestLoader.loadTestsFromNames(['tests.test_weekly_momentum','tests.test_intrabar_risk_paths'])
    with (out/'tests.log').open('x') as f:
        tested=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
    if not tested.wasSuccessful() or tested.skipped:
        raise ValueError('registered focused tests failed')
    print('Loading verified BTCUSDC bundle.', flush=True)
    bundle=load_public_bundle(ROOT, ROOT/'data/historical/btcusdc_public_20260917')
    bundle.require_complete_window(START,END)
    signal_rows=sessions(bundle.trade, START, END)
    if len(signal_rows)!=104:
        raise ValueError('unexpected full-week count')
    save(out/'signals.json', signal_rows)
    save(out/'signal_verification.json',verify_signals(bundle.trade,signal_rows))
    event_results={};event_checks={};event_rows={}
    for model in settings['models']:
        for scenario,cost in costs.items():
            key=f'{scenario}_{model}'
            values=event_returns(bundle.trade,signal_rows,bundle.funding,cost,model)
            save(out/f'{key}_events_without_stops.json',values)
            event_rows[key]=values
            event_checks[key]=verify_event_costs(bundle.trade,signal_rows,values,bundle.funding,cost,model)
            event_results[key]=event_summary(values)
            print('Event economics',key,json.dumps(event_results[key]),flush=True)
    save(out/'event_summary.json',event_results)
    paired={s:bootstrap([a['net_bps']-b['net_bps'] for a,b in zip(event_rows[s+'_MOMENTUM'],event_rows[s+'_LONG'],strict=True)]) for s in costs}
    save(out/'paired_signal_comparisons.json',paired)
    funding={e['fundingTime']:e for e in bundle.funding}
    closes={str(t.date()):float(p) for t,p in bundle.trade.c.resample('1D').last().items()}
    runs={};checks={}
    for model in settings['models']:
        signal=decisions(signal_rows,model)
        for scenario,cost in costs.items():
            for path in settings['paths']:
                key=f'{scenario}_{model}_{path}';print('Account',key,flush=True)
                result=simulate(bundle.trade,signal,pd.Timestamp(START),pd.Timestamp(END),cost,risk,funding=bundle.funding,path=path)
                m=result['metrics'];m['annual']=annual(result['daily'],1000)
                folder=out/key;folder.mkdir()
                for name in ['events','trades','daily','rejections','path_stops']:
                    with (folder/(name+'.jsonl')).open('x') as f:
                        for row in result[name]:f.write(json.dumps(row,allow_nan=False)+'\n')
                save(folder/'metrics.json',m)
                audit=verify_run(folder,m,funding)
                audit['daily']=verify_daily(result,bundle.trade)
                audit['stops']=verify_stops(result,bundle.trade,path,cost,risk)
                allowed={r['entry_minute']:r for r in signal_rows}
                for trade in result['trades']:
                    row=allowed[trade['entry_minute']]
                    assert trade['exit_minute']<=row['exit_minute']
                    assert trade['side']==(row['side'] if model=='MOMENTUM' else 1)
                    assert trade['planned_loss']<=trade['budget']+1e-7
                assert len({t['entry_minute'] for t in result['trades']})==len(result['trades'])
                detail=diagnostics(result,bundle.trade,closes)
                save(folder/'diagnostics.json',detail);save(folder/'verification.json',audit)
                net=m['final_equity']-1000
                runs[key]=dict(metrics=m,net_usdc=net,cagr_pct=((m['final_equity']/1000)**(365.25/730)-1)*100,
                               monthly_operating_cost_break_even_same_path=net/24,
                               risk_preference_pass=m['max_drawdown_pct']<=5,
                               necessary_profit_risk_pass=net>0 and m['max_drawdown_pct']<=5,
                               longest_underwater_days=detail['calendar_risk']['longest_underwater_days'],
                               negative_months=detail['negative_months'],worst_month=detail['worst_month'],
                               concentration=detail['concentration'])
                checks[key]=audit
                print(json.dumps(dict(run=key,net=net,dd=m['max_drawdown_pct'],cycles=m['cycles'],halt=m['halt_time'])),flush=True)
    necessary=all(runs[f'{s}_MOMENTUM_{p}']['necessary_profit_risk_pass'] for s in costs for p in settings['paths'])
    save(out/'summary.json',dict(settings=settings,event_economics=event_results,paired_signal_comparisons=paired,runs=runs,
                               candidate_necessary_conditions_pass=necessary,
                               decision='RETAIN_FOR_FURTHER_VALIDATION_NOT_ADOPTED' if necessary else 'REJECT_FIXED_RULE',
                               models_adopted=[],operating_cost_integrated=False,source_data_reused=True,
                               future_profit_verified=False,real_world_5pct_guarantee=False))
    check_hashes(sources)
    save(out/'verification.json',dict(status='PASS_WITH_MODEL_LIMITATIONS',focused_tests=tested.testsRun,
                                     event_checks=event_checks,account_checks=checks,source_hashes_unchanged=len(sources),
                                     artifacts={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    try:main(args.output)
    except Exception as e:
        save(args.output/'failure.json',dict(type=type(e).__name__,reason=str(e)));raise
