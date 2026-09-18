"""E023/H01: eight preregistered retrospective accounts, one changed policy."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd

from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.baseline.engine import policies
from app.research.data.btcusdc import load_public_bundle
from app.research.multistrategy_audit import frame_features
from app.research.diagnostics.intrabar_engine import simulate
from app.research.diagnostics.time_exit_policy import risk_pair, verify_window, verify_no_time_exit
from app.research.diagnostics.direction_controls import trade_sides, verify_t0_from_minutes
from app.research.diagnostics.review_metrics import calendar_risk
from app.research.diagnostics.economics import close, cost_bridge
from app.research.diagnostics.concentration import (
    concentration, event_costs, cycle_attribution, daily_attribution, calendar_months)
from scripts.run_direction_controls import save, load, digest, lines, verify_daily, test_ids
from scripts.run_intrabar_risk_paths import verify_stops
from scripts.run_btcusdc_comparison import annual
from scripts.report_btcusdc_comparison import verify_run

START = '2024-09-01T00:00:00+00:00'
END = '2026-09-01T00:00:00+00:00'
PRIOR = ROOT/'reports/validation/e015_intrabar_risk_paths_20260918'
SCHEDULED = ROOT/'reports/validation/e022_signal_boundary_20260919'
TESTS = ('tests.test_time_exit_policy', 'tests.test_intrabar_risk_paths',
         'tests.test_direction_controls', 'tests.test_comparison', 'tests.test_baseline_account',
         'tests.test_baseline_engine', 'tests.test_btcusdc_bundle', 'tests.test_review_metrics',
         'tests.test_profit_concentration', 'tests.test_economics_diagnostic')


def check_hashes(hashes):
    for name, expected in hashes.items():
        if digest(ROOT/name) != expected:
            raise ValueError('registered input changed: '+name)


def diagnostics(result, minutes, closes):
    events, trades = result['events'], result['trades']
    stops = {row['event_index']: row for row in result['path_stops']}
    costs = result['metrics']['costs']
    parts = event_costs(events, trades, stops, minutes, costs)
    cycles = cycle_attribution(events, trades, parts)
    days = daily_attribution(events, result['daily'], closes, parts)
    months = calendar_months(days)
    bridge = cost_bridge(events, trades, stops, minutes, costs, 1000)
    close(bridge['net_profit'], result['metrics']['final_equity']-1000)
    close(sum(row['net'] for row in months), bridge['net_profit'])
    if len(days) != 730 or len(months) != 24:
        raise ValueError('calendar coverage differs')
    return dict(calendar_risk=calendar_risk(result['daily']), cost_bridge=bridge,
                trade_sides=trade_sides(trades), concentration=concentration(cycles,(1,5,10)),
                same_side_adjacent_cycles=sum(a['side']==b['side'] for a,b in zip(trades,trades[1:])),
                maximum_held_minutes=max(t['exit_minute']-t['entry_minute'] for t in trades),
                worst_month=min(months,key=lambda m:m['net']),
                negative_months=sum(m['net']<0 for m in months),
                monthly=months, cycles=cycles)


def main(output):
    registration = load(SCHEDULED/'registration.json')
    sources = dict(registration['source_hashes'])
    for name, expected in load(PRIOR/'registration.json')['source_hashes'].items():
        if name in sources and sources[name] != expected:
            raise ValueError('source versions conflict: '+name)
        sources[name] = expected
    names = ('app/research/diagnostics/time_exit_policy.py','scripts/run_time_exit_policy.py',
             'tests/test_time_exit_policy.py','docs/research/experiments/E023_TIME_EXIT_POLICY.md')
    for name in (*names, *(m.replace('.','/')+'.py' for m in TESTS)):
        if name in sources and sources[name] != digest(ROOT/name):
            raise ValueError('frozen source changed: '+name)
        sources[name] = digest(ROOT/name)
    hashes = dict(registration['prior_artifact_hashes'])
    for directory in (SCHEDULED, PRIOR):
        for file in sorted(directory.rglob('*')):
            if file.is_file(): hashes[str(file.relative_to(ROOT))] = digest(file)
    # E015's canonical artifact manifest is checked, not merely snapshotted anew.
    receipt = load(PRIOR/'verification.json')
    for name, expected in receipt['artifact_hashes'].items():
        if digest(PRIOR/name) != expected: raise ValueError('E015 evidence changed: '+name)
    check_hashes(sources); check_hashes(hashes)
    pair = risk_pair(START,END)
    settings = dict(start=START,end=END,initial=1000,model='T0',
                    risk={k:asdict(v) for k,v in pair.items()},
                    costs={'base':asdict(Costs()),'stress':asdict(Costs(7,5,1))},
                    paths=['OHLC','OLHC'],runs=8,
                    operating_cost=None,selection_or_confirmation=False)
    suite = unittest.defaultTestLoader.loadTestsFromNames(TESTS)
    ids = list(test_ids(suite))
    save(output/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
        classification='RETROSPECTIVE_SINGLE_AXIS_POLICY_DIAGNOSTIC',settings=settings,
        source_hashes=sources,prior_artifact_hashes=hashes,test_ids=ids,
        automatic_retries=0,stop_rule='Any test, parity, source, data or accounting failure stops execution',
        primary='variant minus control final cost-net equity, per cost and path',
        no_adaptive_grid=True,actual_orders=0))
    for name in sources:
        path = output/'source_snapshot'/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes((ROOT/name).read_bytes())
    with (output/'tests.log').open('x') as stream:
        tested = unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    save(output/'tests.json',dict(registered=len(ids),executed=tested.testsRun,
        failures=len(tested.failures),errors=len(tested.errors),skipped=len(tested.skipped)))
    if not tested.wasSuccessful() or tested.skipped or tested.testsRun != len(ids):
        raise ValueError('registered tests failed')
    print('Registered tests passed; loading pinned data.',flush=True)
    bundle = load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917')
    bundle.require_complete_window(START,END)
    count = verify_window(bundle.trade.index,START,END)
    t0 = policies(bundle.trade,{240:frame_features(bundle.trade,240)})['T0']
    save(output/'signal_verification.json',verify_t0_from_minutes(bundle.trade,t0))
    closes = {str(stamp.date()):float(price) for stamp,price in bundle.trade.c.resample('1D').last().items()}
    funding = {e['fundingTime']:e for e in bundle.funding}
    runs, checks = {}, {}
    # All four controls must reproduce frozen evidence before any variant runs.
    for policy,risk in pair.items():
        for scenario,params in settings['costs'].items():
            for path in settings['paths']:
                key = '_'.join((scenario,policy,path))
                result = simulate(bundle.trade,t0,pd.Timestamp(START),pd.Timestamp(END),
                                  Costs(**params),risk,funding=bundle.funding,path=path)
                metrics = result['metrics']
                metrics['annual'] = annual(result['daily'],1000)
                folder = output/key; folder.mkdir()
                for name in ('events','trades','daily','rejections','path_stops'):
                    with (folder/(name+'.jsonl')).open('x') as stream:
                        for row in result[name]: stream.write(json.dumps(row,allow_nan=False)+'\n')
                save(folder/'metrics.json',metrics)
                audit = verify_run(folder,metrics,funding)
                audit['daily'] = verify_daily(result,bundle.trade)
                audit['stops'] = verify_stops(result,bundle.trade,path,Costs(**params),risk)
                if policy == 'control':
                    old = PRIOR/(scenario+'_T0_'+path)
                    if metrics != load(old/'metrics.json'): raise ValueError('control metrics differ')
                    for name in ('events','trades','daily','rejections','path_stops'):
                        if result[name] != lines(old/(name+'.jsonl')):
                            raise ValueError('control '+name+' differs')
                    audit['exact_e015_reproduction'] = True
                else:
                    audit['finite_window_policy'] = verify_no_time_exit(result,START,END,risk)
                detail = diagnostics(result,bundle.trade,closes)
                save(folder/'diagnostics.json',detail)
                save(folder/'verification.json',audit)
                runs[key] = dict(metrics=metrics,diagnostics=detail)
                checks[key] = audit
                print(json.dumps(dict(run=key,return_pct=metrics['return_pct'],
                    dd=metrics['max_drawdown_pct'],cycles=metrics['cycles'])),flush=True)
    differences = {}
    for scenario in settings['costs']:
        for path in settings['paths']:
            a,b = (runs['_'.join((scenario,p,path))] for p in pair)
            differences[scenario+'_'+path] = dict(
                final_equity_usdc=b['metrics']['final_equity']-a['metrics']['final_equity'],
                return_percentage_points=b['metrics']['return_pct']-a['metrics']['return_pct'],
                drawdown_percentage_points=b['metrics']['max_drawdown_pct']-a['metrics']['max_drawdown_pct'],
                cost_bridge={k:b['diagnostics']['cost_bridge'][k]-v
                             for k,v in a['diagnostics']['cost_bridge'].items()})
    save(output/'summary.json',dict(settings=settings,minutes=count,runs=runs,differences=differences,
        previously_observed_data=True,operating_cost_included=False,actual_tick_paths=False,
        strategy_adopted=False,public_signal_observation_completed=False))
    check_hashes(sources); check_hashes(hashes)
    save(output/'verification.json',dict(status='PASS_SCOPED_POLICY_LEDGER_DAILY_STOP_AND_ATTRIBUTION_CHECKS',
        runs=checks,completed_runs=len(runs),independent_events=sum(v['events'] for v in checks.values()),
        independent_cycles=sum(v['cycles'] for v in checks.values()),
        sources_unchanged=len(sources),prior_artifacts_unchanged=len(hashes),actual_orders=0,strategy_adopted=False,
        artifact_hashes={str(p.relative_to(output)):digest(p) for p in sorted(output.rglob('*')) if p.is_file()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    try:
        main(args.output)
    except Exception as exc:
        save(args.output/'failure.json',dict(status='FAILED',exception=type(exc).__name__,reason=str(exc)))
        raise
