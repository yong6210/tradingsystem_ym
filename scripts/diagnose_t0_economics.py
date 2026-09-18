"""E016: inspect two frozen ledgers without changing or rerunning a strategy."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.data.btcusdc import load_public_bundle
from app.research.diagnostics.economics import (
    close, cost_bridge, sizing_rows, exposure, recovery_episodes, operating_costs)
from app.research.diagnostics.review_metrics import calendar_risk
from scripts.run_direction_controls import save, load, lines, digest, verify_daily, test_ids
from scripts.report_btcusdc_comparison import verify_run


def prior_hashes():
    result = {}
    for experiment in ('e014_direction_controls_20260918','e015_intrabar_risk_paths_20260918'):
        folder = ROOT/'reports/validation'/experiment
        receipt = folder/'verification.json'
        result[str(receipt.relative_to(ROOT))] = digest(receipt)
        for name, expected in load(receipt)['artifact_hashes'].items():
            path = folder/name
            if digest(path) != expected:
                raise ValueError('prior evidence changed: '+str(path))
            result[str(path.relative_to(ROOT))] = expected
    return result


def main(output):
    # The caller reserves a new folder before entering the failure-recording block.
    old_hashes = prior_hashes()
    prior = ROOT/'reports/validation/e014_direction_controls_20260918'
    settings = load(prior/'registration.json')['settings']
    sources = dict(load(prior/'registration.json')['source_hashes'])
    for name in ('app/research/diagnostics/economics.py','tests/test_economics_diagnostic.py',
                 'scripts/diagnose_t0_economics.py','docs/research/experiments/E016_ECONOMICS_DIAGNOSTIC.md',
                 'app/research/diagnostics/review_metrics.py','scripts/report_btcusdc_comparison.py',
                 'scripts/run_direction_controls.py','tests/test_review_metrics.py','tests/test_baseline_account.py'):
        sources[name] = digest(ROOT/name)
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        ('tests.test_economics_diagnostic','tests.test_review_metrics','tests.test_baseline_account'))
    identities = list(test_ids(suite))
    save(output/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),
        classification='RETROSPECTIVE_FIXED_LEDGER_DIAGNOSTIC_NOT_NEW_BACKTEST',
        settings=dict(start=settings['start'],end=settings['end'],models=['T0'],scenarios=['base','stress'],
                      operating_months=24,monthly_cost_scenarios=[0,1,2,5]),
        source_hashes=sources,prior_artifact_hashes=old_hashes,test_ids=identities,automatic_retries=0))
    for name, expected in sources.items():
        if digest(ROOT/name) != expected:
            raise ValueError('source changed: '+name)
        path = output/'source_snapshot'/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes((ROOT/name).read_bytes())
    with (output/'tests.log').open('x') as stream:
        result = unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    save(output/'tests.json',dict(registered=len(identities),executed=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped)))
    if not result.wasSuccessful() or result.skipped or result.testsRun != len(identities):
        raise ValueError('tests failed')
    print('Diagnostic tests passed; checking pinned BTCUSDC data.',flush=True)
    bundle = load_public_bundle(ROOT,ROOT/'data/historical/btcusdc_public_20260917')
    bundle.require_complete_window(settings['start'],settings['end'])
    minutes = bundle.trade
    lower = int(minutes.index.searchsorted(pd.Timestamp(settings['start'])))
    upper = int(minutes.index.searchsorted(pd.Timestamp(settings['end'])))
    funding = {event['fundingTime']:event for event in bundle.funding}
    summaries, checks = {}, {}
    for scenario in ('base','stress'):
        folder = prior/(scenario+'_T0')
        metrics = load(folder/'metrics.json')
        if metrics['warned']:
            raise ValueError('this sizing diagnostic excludes warning paths')
        data = {name:lines(folder/(name+'.jsonl')) for name in ('events','trades','daily','rejections')}
        path_folder = ROOT/'reports/validation/e015_intrabar_risk_paths_20260918'/(scenario+'_T0_OHLC')
        if lines(path_folder/'events.jsonl') != data['events']:
            raise ValueError('path reference events differ')
        stops = {row['event_index']:row for row in lines(path_folder/'path_stops.jsonl')}
        checks[scenario] = verify_run(folder,metrics,funding)
        checks[scenario]['daily'] = verify_daily(data,minutes)
        bridge = cost_bridge(data['events'],data['trades'],stops,minutes,metrics['costs'],1000)
        close(bridge['net_profit'],metrics['final_equity']-1000)
        close(bridge['fees'],metrics['fees'])
        close(bridge['historical_funding_net']+bridge['stress_funding'],metrics['funding'])
        close(bridge['fill_gross'],metrics['realized'])
        sizes = sizing_rows(data['events'],data['trades'],metrics['costs'],metrics['risk'])
        held = exposure(data['trades'],minutes,lower,upper)
        close(held['active_fraction'],metrics['active_fraction'])
        close(held['mean_notional'],metrics['mean_notional'])
        episodes = recovery_episodes(data['daily'],1000)
        longest = max(episodes,key=lambda e:e['elapsed_days'])
        close(longest['elapsed_days'],calendar_risk(data['daily'])['longest_underwater_days'])
        utilization = [row['budget_utilization'] for row in sizes]
        rejections = data['rejections']
        if any(row['reason'] != 'size_constraint' for row in rejections):
            raise ValueError('unknown rejection type')
        close(len(rejections),metrics['actions']['size_constraint'])
        summaries[scenario] = dict(cost_bridge=bridge, exposure=held,
            sizing=dict(approved_cycles=len(sizes),binding_counts=dict(Counter(row['binding'] for row in sizes)),
                quantity_counts=dict(Counter(str(row['quantity']) for row in sizes)),
                risk_budget_utilization_mean=float(np.mean(utilization)),
                risk_budget_utilization_median=float(np.median(utilization)),
                risk_budget_utilization_min=min(utilization),risk_budget_utilization_max=max(utilization),
                rounding_unused_fraction_mean=float(np.mean([r['rounding_unused_fraction'] for r in sizes])),
                notional_cap_unused_fraction_mean=float(np.mean([r['notional_cap_unused_fraction'] for r in sizes])),
                size_rejections=len(rejections),warned=metrics['warned']),
            longest_daily_recovery=longest, final_episode=episodes[-1],
            operating_costs=operating_costs(bridge['net_profit'],24),
            return_pct=metrics['return_pct'],cagr_pct=100*((metrics['final_equity']/1000)**.5-1))
        target = output/scenario
        target.mkdir()
        save(target/'sizing.json',sizes)
        save(target/'recovery_episodes.json',episodes)
        save(target/'summary.json',summaries[scenario])
        print(f"{scenario}: net={bridge['net_profit']:.6f}, sizing={summaries[scenario]['sizing']}, longest={longest}",flush=True)
    save(output/'summary.json',dict(runs=summaries,new_backtests=0,strategy_adopted=False))
    for name, expected in sources.items():
        if digest(ROOT/name) != expected:
            raise ValueError('source changed: '+name)
    for name, expected in old_hashes.items():
        if digest(ROOT/name) != expected:
            raise ValueError('prior evidence changed: '+name)
    save(output/'verification.json',dict(status='PASS_SCOPED_ECONOMICS_DIAGNOSTIC',
        checks=checks,prior_artifacts_unchanged=len(old_hashes),sources_unchanged=len(sources),
        new_backtests=0,actual_orders=0,strategy_adopted=False,
        artifact_hashes={str(p.relative_to(output)):digest(p) for p in sorted(output.rglob('*')) if p.is_file()}))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    try:
        main(args.output)
    except Exception as exc:
        save(args.output/'failure.json',dict(status='FAILED',exception=type(exc).__name__,reason=str(exc)))
        raise
