"""E010 fixed funding/basis factorial overlays on the immutable T0 baseline."""
from dataclasses import asdict
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
from app.research.baseline.engine import policies
from app.research.comparison.engine import simulate
from app.research.candidate_accounts.crowding import (
    MODELS, funding_context, basis_context, build_crowding_policies, admission,
)
from scripts.run_btcusdc_comparison import annual
from scripts.run_baseline_account import compare_daily

OUT = ROOT / 'reports/validation/e010_funding_basis_20260917'
PRIOR = ROOT / 'reports/validation/e009_taker_alignment_20260917'
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
    sources = [Path(__file__), ROOT / 'app/research/candidate_accounts/crowding.py',
               ROOT / 'tests/test_crowding.py', ROOT / 'docs/research/experiments/E010_FUNDING_BASIS.md']
    hashes.update({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    settings = dict(start='2024-09-01T00:00:00+00:00', end='2026-09-01T00:00:00+00:00',
                    models=MODELS, runs=8, costs={'base': asdict(Costs()), 'stress': asdict(Costs(7, 5, 1))},
                    risk=asdict(Risk()), funding_lag_ms=60000, funding_max_age_hours=12,
                    funding_history_events=90, basis_history_four_hour_observations=180,
                    lower_quantile=.1, upper_quantile=.9, classification='RETROSPECTIVE_ENTRY_ONLY_OVERLAYS')
    save(OUT / 'registration.json', dict(registered_at=datetime.now(timezone.utc).isoformat(),
                                        settings=settings, source_hashes=hashes))
    save(OUT / 'status.json', dict(status='RUNNING', completed=0))
    try:
        bundle = load_public_bundle(ROOT, DATA)
        start, end = (pd.Timestamp(settings[k]) for k in ('start', 'end'))
        bundle.require_complete_window(start, end)
        bank = feature_bank(bundle.trade)
        times = bank[240].index
        context = funding_context(times, bundle.funding).join(basis_context(times, bundle.mark, bundle.index_price))
        # Keep the full warmup clock so raw-source verification can reconstruct
        # the exact prior 180 observations rather than inventing a sample.
        with (OUT / 'context.jsonl').open('w') as stream:
            for stamp, row in context.iterrows():
                values = {k: (bool(v) if k.endswith('_ready') else int(v) if k == 'funding_ms'
                              else float(v) if np.isfinite(v) else None) for k, v in row.items()}
                stream.write(json.dumps(dict(completed_at=stamp.isoformat(), **values), allow_nan=False) + '\n')
        core = policies(bundle.trade, bank)['T0']
        decisions = build_crowding_policies(bundle.trade, core, context)
        if decisions['T0'] != core:
            raise ValueError('T0 commands changed')
        observations = []
        for i, (side, _, _) in core.items():
            executed = bundle.trade.index[i]
            if start <= executed < end:
                completed = executed - pd.Timedelta(minutes=1)
                row = context.loc[completed]
                observations.append(dict(completed_at=completed.isoformat(), side=side,
                                         funding_ready=bool(row.funding_ready), basis_ready=bool(row.basis_ready),
                                         allowed={m: admission(side, row, m) for m in MODELS}))
        with (OUT / 'observations.jsonl').open('w') as stream:
            for row in observations: stream.write(json.dumps(row) + '\n')
        coverage = dict(observations=len(observations), funding_unready=sum(not r['funding_ready'] for r in observations),
                        basis_unready=sum(not r['basis_ready'] for r in observations), by_model={})
        for m in MODELS:
            selected = [side for i, (side, _, _) in decisions[m].items() if start <= bundle.trade.index[i] < end]
            coverage['by_model'][m] = dict(allowed=sum(r['allowed'][m] for r in observations),
                                          blocked=sum(not r['allowed'][m] for r in observations),
                                          directional_commands=sum(side != 0 for side in selected),
                                          neutral_commands=sum(side == 0 for side in selected))
        save(OUT / 'signal_coverage.json', coverage)
        results, daily, reproduction = {}, {}, {}
        for scenario, params in settings['costs'].items():
            for model in MODELS:
                key = f'{scenario}_{model}'
                result = simulate(bundle.trade, decisions[model], start, end, Costs(**params),
                                  Risk(**settings['risk']), funding=bundle.funding)
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
                save(OUT / 'status.json', dict(status='RUNNING', completed=len(results), total=8))
        paired = {f'{s}_{m}': compare_daily(daily[f'{s}_{m}'], daily[f'{s}_T0'], start, end)
                  for s in settings['costs'] for m in MODELS[1:]}
        screening = {}
        for model in MODELS[1:]:
            a, b = (results[f'{s}_{model}'] for s in ('base', 'stress'))
            checks = dict(base_positive=a['return_pct'] > 0, stress_positive=b['return_pct'] > 0,
                          cycles=min(a['cycles'], b['cycles']) >= 100,
                          no_halt=not a['drawdown_halted'] and not b['drawdown_halted'],
                          stress_years=all(b['annual'][y]['return_pct'] > 0 for y in ('2025', '2026')),
                          incremental_lower_positive=paired[f'stress_{model}']['interval']['interval_bps'][0] > 0)
            screening[model] = dict(checks=checks, status='RESEARCH_ONLY' if all(checks.values()) else 'NO_FORWARD_CANDIDATE')
        save(OUT / 'summary.json', dict(settings=settings, runs=results, paired=paired,
                                       reproduction=reproduction, screening=screening))
        save(OUT / 'status.json', dict(status='COMPLETE', runs=8))
    except Exception as exc:
        save(OUT / 'status.json', dict(status='FAILED', error=str(exc)))
        raise


if __name__ == '__main__':
    main()
