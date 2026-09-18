"""E014: ten frozen retrospective direction-control accounts, no optimization."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
from app.research.baseline.account import Costs
from app.research.baseline.engine import policies
from app.research.baseline.risk import Risk
from app.research.comparison.engine import simulate
from app.research.data.btcusdc import load_public_bundle
from app.research.multistrategy_audit import frame_features
from app.research.diagnostics.direction_controls import MODELS, controls, paired_interval, trade_sides, verify_t0_from_minutes
from app.research.diagnostics.review_metrics import calendar_risk
from scripts.report_btcusdc_comparison import verify_run, near
from scripts.run_btcusdc_comparison import annual

LEGACY = ('e005_btcusdc_comparison_20260917', 'e006_loss_exit_diagnostics_20260917',
    'e007_order_rules_20260917', 'e008_candidate_accounts_20260917', 'e009_taker_alignment_20260917',
    'e010_funding_basis_20260917', 'e011_trend_pullback_20260917', 'e012_account_constraints_20260917',
    'e013_failed_break_direction_20260917')
TESTS = ('tests.test_direction_controls', 'tests.test_comparison', 'tests.test_baseline_account',
         'tests.test_baseline_engine', 'tests.test_btcusdc_bundle', 'tests.test_review_metrics')


def load(path): return json.loads(path.read_text())


def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def lines(path): return [json.loads(row) for row in path.read_text().splitlines()]


def verify_daily(result, minutes):
    """Separate Decimal cash/position walk and original minute closing prices."""
    events, cursor = result['events'], 0
    cash, qty, entry = D(1000), D(0), D(0)
    for row in result['daily']:
        until = pd.Timestamp(row['day'], tz='UTC')+pd.Timedelta(days=1)
        while cursor < len(events) and pd.Timestamp(events[cursor]['time']) < until:
            e = events[cursor]
            if e['kind'] == 'entry':
                qty, entry = D(str(e['qty']))*e['side'], D(str(e['price']))
                cash -= D(str(e['fee']))
            elif e['kind'] == 'exit':
                cash += qty*(D(str(e['price']))-entry)-D(str(e['fee']))
                qty = entry = D(0)
            else: cash -= D(str(e['amount']))
            cursor += 1
        close = D(str(minutes.loc[until-pd.Timedelta(minutes=1), 'c']))
        near(cash+qty*(close-entry), row['equity'])
    if cursor != len(events): raise ValueError('events outside daily calendar')
    if len(result['daily']) != 730: raise ValueError('unexpected evaluation calendar')
    return dict(status='PASS', days=730)


def legacy_review():
    checks, rows, inputs = [], [], {}
    for experiment in LEGACY:
        folder = ROOT/'reports/validation'/experiment
        reg, verify, summary = (load(folder/name) for name in ('registration.json', 'independent_verification.json', 'summary.json'))
        for name in ('registration.json', 'independent_verification.json', 'summary.json', 'status.json'):
            inputs[str((folder/name).relative_to(ROOT))] = digest(folder/name)
        for kind, bindings in (('source', reg['source_hashes']), ('artifact', verify['artifact_hashes'])):
            for path, expected in bindings.items():
                passed = (ROOT/path).is_file() and digest(ROOT/path) == expected
                checks.append(dict(experiment=experiment, kind=kind, path=path, passed=passed))
                if not passed: raise ValueError('legacy evidence changed: '+path)
        for run, m in summary.get('runs', {}).items():
            rows.append(dict(experiment=experiment, run=run, **{key: m.get(key) for key in
                ('return_pct', 'max_drawdown_pct', 'cycles', 'realized', 'fees', 'funding', 'active_fraction',
                 'halt_time', 'drawdown_halted')}, classification='REUSED_DATA_NOT_INDEPENDENT_STRATEGY'))
    return dict(hash_checks=len(checks), unique_paths=len({c['path'] for c in checks}),
                failed_checks=0, rows=rows, checks=checks), inputs


def test_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite): yield from test_ids(item)
        else: yield item.id()


def main(output):
    output.mkdir(parents=True, exist_ok=False)
    legacy, inputs = legacy_review()
    save(output/'legacy_inventory.json', legacy)
    settings = dict(start='2024-09-01T00:00:00+00:00', end='2026-09-01T00:00:00+00:00',
        models=list(MODELS), risk=asdict(Risk()), costs={'base': asdict(Costs()), 'stress': asdict(Costs(7, 5, 1))},
        runs=10, bootstrap=dict(block_days=28, repetitions=2000, seed=18092026))
    source_names = [str(p.relative_to(ROOT)) for pattern in
        ('app/research/baseline/*.py', 'app/research/comparison/*.py') for p in ROOT.glob(pattern)]
    source_names += ['app/research/diagnostics/direction_controls.py', 'app/research/diagnostics/review_metrics.py',
        'app/research/data/btcusdc.py', 'app/research/data/minutes.py', 'app/research/multistrategy_audit.py',
        'scripts/run_direction_controls.py', 'scripts/report_btcusdc_comparison.py', 'scripts/run_btcusdc_comparison.py',
        'docs/research/experiments/E014_DIRECTION_CONTROLS.md']
    source_names += [m.replace('.', '/')+'.py' for m in TESTS]
    data = ROOT/'data/historical/btcusdc_public_20260917'
    source_names += [str((data/p).relative_to(ROOT)) for p in ('manifest.json', 'validated_overlay.json', 'gap_probe_manifest.json')]
    source_hashes = {p: digest(ROOT/p) for p in source_names}
    suite = unittest.defaultTestLoader.loadTestsFromNames(TESTS)
    identities = list(test_ids(suite))
    save(output/'registration.json', dict(registered_at=datetime.now(timezone.utc).isoformat(),
        classification='RETROSPECTIVE_DIRECTION_DIAGNOSTIC_NOT_MODEL_SELECTION', settings=settings,
        source_hashes=source_hashes, legacy_inputs=inputs, test_ids=identities, automatic_retries=0))
    for name in source_names:
        path = output/'source_snapshot'/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT/name).read_bytes())
    with (output/'tests.log').open('x') as stream:
        tested = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    save(output/'tests.json', dict(registered=len(identities), executed=tested.testsRun,
        failures=len(tested.failures), errors=len(tested.errors), skipped=len(tested.skipped)))
    if not tested.wasSuccessful() or tested.skipped or tested.testsRun != len(identities):
        raise ValueError('registered regression failed')
    print('Registered tests passed; loading pinned BTCUSDC sources.', flush=True)
    bundle = load_public_bundle(ROOT, data)
    bundle.require_complete_window(settings['start'], settings['end'])
    t0 = policies(bundle.trade, {240: frame_features(bundle.trade, 240)})['T0']
    save(output/'signal_verification.json', verify_t0_from_minutes(bundle.trade, t0))
    decisions = controls(t0)
    save(output/'decision_hashes.json', {k: hashlib.sha256(json.dumps(v, sort_keys=True).encode()).hexdigest()
                                       for k, v in decisions.items()})
    start, end = pd.Timestamp(settings['start']), pd.Timestamp(settings['end'])
    funding = {e['fundingTime']: e for e in bundle.funding}
    runs, verification, calendars = {}, {}, {}
    for scenario, costs in settings['costs'].items():
        for model in MODELS:
            key = scenario+'_'+model
            result = simulate(bundle.trade, decisions[model], start, end, Costs(**costs), Risk(), funding=bundle.funding)
            folder = output/key; folder.mkdir()
            for name in ('events', 'trades', 'daily', 'rejections'):
                with (folder/(name+'.jsonl')).open('x') as stream:
                    for row in result[name]: stream.write(json.dumps(row, allow_nan=False)+'\n')
            m = result['metrics']; m['annual'] = annual(result['daily'], 1000)
            save(folder/'metrics.json', m)
            checked = verify_run(folder, m, funding)
            checked['daily'] = verify_daily(result, bundle.trade)
            if model == 'T0':
                frozen = ROOT/'reports/validation/e005_btcusdc_comparison_20260917'/key
                for name in ('events', 'trades', 'daily', 'rejections'):
                    if result[name] != lines(frozen/(name+'.jsonl')): raise ValueError('T0 frozen '+name+' differs')
                if m != load(frozen/'metrics.json'): raise ValueError('T0 frozen metrics differ')
                checked['frozen_e005_exactly_reproduced'] = True
            if model == 'CASH' and (result['events'] or m['final_equity'] != 1000):
                raise ValueError('cash control not flat')
            save(folder/'verification.json', checked)
            runs[key] = m | dict(calendar_risk=calendar_risk(result['daily']), trade_sides=trade_sides(result['trades']))
            verification[key] = checked
            calendars[key] = result['daily']
            print(json.dumps(dict(run=key, return_pct=m['return_pct'], dd=m['max_drawdown_pct'], cycles=m['cycles'])), flush=True)
    differences = {s+'_T0_minus_'+model: paired_interval(calendars[s+'_T0'], calendars[s+'_'+model], **settings['bootstrap'])
                   for s in settings['costs'] for model in MODELS if model != 'T0'}
    market_return = 100*(float(bundle.trade.loc[end-pd.Timedelta(minutes=1), 'c'])/float(bundle.trade.loc[start, 'o'])-1)
    save(output/'summary.json', dict(settings=settings, runs=runs, paired_comparisons=differences,
        unlevered_price_return_pct_context_only=market_return,
        interpretation='POLICY_COMPARISON_NOT_EQUAL_EXPOSURE_OR_SIGNAL_ONLY_CAUSAL_EFFECT', strategy_adopted=False))
    for name, expected in source_hashes.items():
        if digest(ROOT/name) != expected: raise ValueError('registered source changed: '+name)
    after, _ = legacy_review()
    if after != legacy: raise ValueError('legacy evidence changed during experiment')
    save(output/'verification.json', dict(status='PASS_SCOPED_SIGNAL_LEDGER_DAILY_AND_REPRODUCTION',
        runs=verification, independent_events=sum(v['events'] for v in verification.values()),
        independent_cycles=sum(v['cycles'] for v in verification.values()),
        legacy_hash_checks=legacy['hash_checks'], legacy_unique_paths=legacy['unique_paths'], legacy_mismatches=0,
        registered_sources_unchanged=True, all_10_runs_completed=True,
        independent_tick_execution_or_intrabar_drawdown=False, strategy_adopted=False, actual_orders=0,
        artifact_hashes={str(p.relative_to(output)): digest(p) for p in sorted(output.rglob('*')) if p.is_file()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try: main(args.output)
    except Exception as exc:
        if args.output.is_dir() and not (args.output/'failure.json').exists():
            save(args.output/'failure.json', dict(status='FAILED', exception=type(exc).__name__, reason=str(exc)))
        raise
