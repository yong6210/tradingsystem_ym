"""E011 fixed timing/risk matched pullback study; exactly ten account runs."""
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from app.research.data.btcusdc import load_public_bundle
from app.research.multistrategy_audit import feature_bank
from app.research.baseline.account import Costs
from app.research.baseline.risk import Risk
from app.research.comparison.engine import simulate
from app.research.candidate_accounts.pullback import MODELS, build_pullback_policies
from scripts.run_btcusdc_comparison import annual
from scripts.run_baseline_account import compare_daily

OUT = ROOT / 'reports/validation/e011_trend_pullback_20260917'
PRIOR = ROOT / 'reports/validation/e010_funding_basis_20260917'
CONTROL = ROOT / 'reports/validation/e005_btcusdc_comparison_20260917'
DATA = ROOT / 'data/historical/btcusdc_public_20260917'


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    hashes = json.loads((PRIOR / 'registration.json').read_text())['source_hashes']
    for name, digest in hashes.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise ValueError('previous source changed: ' + name)
    sources = [Path(__file__), ROOT / 'app/research/candidate_accounts/pullback.py',
               ROOT / 'tests/test_pullback.py', ROOT / 'docs/research/experiments/E011_TREND_PULLBACK.md']
    hashes.update({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    settings = dict(start='2024-09-01T00:00:00+00:00', end='2026-09-01T00:00:00+00:00',
                    models=MODELS, runs=10, costs={'base': asdict(Costs()), 'stress': asdict(Costs(7, 5, 1))},
                    risk={m: asdict(replace(Risk(), stop_atr=2, maximum_hold_minutes=360)
                                    if m in ('C15', 'P15') else Risk()) for m in MODELS},
                    displacement_atr=.5, max_wait_bars=8, classification='RETROSPECTIVE_MATCHED_TIMING_AND_RISK')
    save(OUT / 'registration.json', dict(registered_at=datetime.now(timezone.utc).isoformat(), settings=settings, source_hashes=hashes))
    save(OUT / 'status.json', dict(status='RUNNING', completed=0))
    try:
        bundle = load_public_bundle(ROOT, DATA)
        start, end = (pd.Timestamp(settings[k]) for k in ('start', 'end'))
        bundle.require_complete_window(start, end)
        decisions, context, audit = build_pullback_policies(bundle.trade, feature_bank(bundle.trade))
        with (OUT / 'context.jsonl').open('w') as stream:
            for stamp, row in context.iterrows():
                values = {k: bool(v) if k == 'valid' else int(v) if k in ('direction', 'displaced_side')
                          else float(v) if np.isfinite(v) else None for k, v in row.items()}
                stream.write(json.dumps(dict(completed_at=stamp.isoformat(), **values), allow_nan=False) + '\n')
        with (OUT / 'episodes.jsonl').open('w') as stream:
            for row in audit: stream.write(json.dumps(row) + '\n')
        selected = [r for r in audit if start <= pd.Timestamp(r['time'])+pd.Timedelta(minutes=1) < end]
        coverage = dict(episodes=dict(Counter(r['kind'] for r in selected)), by_model={})
        for model in MODELS:
            commands = []
            for i, (side, close, atr) in decisions[model].items():
                if start <= bundle.trade.index[i] < end:
                    commands.append(dict(time=bundle.trade.index[i].isoformat(), side=side, close=close, atr=atr))
            with (OUT / (model+'_commands.jsonl')).open('w') as stream:
                for row in commands: stream.write(json.dumps(row) + '\n')
            coverage['by_model'][model] = dict(directional_commands=sum(r['side'] != 0 for r in commands),
                                              neutral_commands=sum(r['side'] == 0 for r in commands))
        save(OUT / 'signal_coverage.json', coverage)
        results, daily, reproduction = {}, {}, {}
        for scenario, params in settings['costs'].items():
            for model in MODELS:
                key = f'{scenario}_{model}'
                result = simulate(bundle.trade, decisions[model], start, end, Costs(**params),
                                  Risk(**settings['risk'][model]), funding=bundle.funding)
                folder = OUT / key; folder.mkdir()
                for field in ('events', 'trades', 'daily', 'rejections'):
                    with (folder / (field + '.jsonl')).open('w') as stream:
                        for row in result[field]: stream.write(json.dumps(row, allow_nan=False) + '\n')
                metrics = result['metrics']; metrics['annual'] = annual(result['daily'], 1000)
                save(folder / 'metrics.json', metrics); save(folder / 'verification.json', result['verification'])
                results[key], daily[key] = metrics, result['daily']
                if model == 'T0':
                    for name in ('events.jsonl', 'trades.jsonl', 'daily.jsonl', 'rejections.jsonl', 'metrics.json'):
                        if (folder / name).read_bytes() != (CONTROL / key / name).read_bytes():
                            raise ValueError('T0 reproduction failed: ' + name)
                    reproduction[key] = 'EXACT_E005'
                print(key, json.dumps({k: metrics[k] for k in ('return_pct', 'max_drawdown_pct', 'cycles', 'drawdown_halted')}), flush=True)
                save(OUT / 'status.json', dict(status='RUNNING', completed=len(results), total=10))
        paired = {f'{s}_{a}_minus_{b}': compare_daily(daily[f'{s}_{a}'], daily[f'{s}_{b}'], start, end)
                  for s in settings['costs'] for a, b in (('P4', 'C4'), ('P15', 'C15'), ('C4', 'T0'))}
        screening = {}
        for model, control in (('P4', 'C4'), ('P15', 'C15')):
            a, b = (results[f'{s}_{model}'] for s in ('base', 'stress'))
            checks = dict(base_positive=a['return_pct'] > 0, stress_positive=b['return_pct'] > 0,
                          cycles=min(a['cycles'], b['cycles']) >= 100,
                          no_halt=not a['drawdown_halted'] and not b['drawdown_halted'],
                          stress_years=all(b['annual'][y]['return_pct'] > 0 for y in ('2025', '2026')),
                          incremental_lower_positive=paired[f'stress_{model}_minus_{control}']['interval']['interval_bps'][0] > 0)
            screening[model] = dict(checks=checks, status='RESEARCH_ONLY' if all(checks.values()) else 'NO_FORWARD_CANDIDATE')
        save(OUT / 'summary.json', dict(settings=settings, runs=results, paired=paired, reproduction=reproduction, screening=screening))
        save(OUT / 'status.json', dict(status='COMPLETE', runs=10))
    except Exception as exc:
        save(OUT / 'status.json', dict(status='FAILED', error=str(exc)))
        raise


if __name__ == '__main__': main()
