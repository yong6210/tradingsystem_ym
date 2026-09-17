"""Retrospective precision feasibility diagnostic; no candidate selection.

Uses the existing T0 stress calendar path. Two fixed block lengths and a fixed
seed; no search for a favorable block length, endpoint, or acceptance threshold.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.foundation.acceptance_contract import load_contract

OUT = ROOT / 'reports/validation/forward_precision_diagnostic_20260917'
DAILY = ROOT / 'reports/validation/e005_btcusdc_comparison_20260917/stress_T0/daily.jsonl'
POLICY = ROOT / 'configs/research/forward_acceptance_policy_v1.json'


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    policy = load_contract(POLICY)
    settings = policy['inference']
    registration = dict(classification='RETROSPECTIVE_PRECISION_FEASIBILITY_NOT_CONFIRMATION',
                        registered_at=datetime.now(timezone.utc).isoformat(),
                        inputs={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (DAILY, POLICY, Path(__file__))},
                        blocks=settings['block_days'], repetitions=settings['repetitions'],
                        seed=settings['seed'], metric=policy['metric'],
                        confidence_per_interval=1 - settings['family_alpha'] / 2)
    (OUT / 'registration.json').write_text(json.dumps(registration, indent=2) + '\n')
    rows = [json.loads(line) for line in DAILY.read_text().splitlines()]
    equity = np.array([1000.] + [row['equity'] for row in rows])
    daily = (equity[1:] / equity[:-1] - 1) * 100
    runs = []
    for block in settings['block_days']:
        rng = np.random.default_rng(settings['seed'])
        samples = []
        checked = 0
        for offset in range(0, settings['repetitions'], 500):
            count = min(500, settings['repetitions'] - offset)
            starts = rng.integers(0, len(daily), size=(count, (len(daily) + block - 1) // block))
            indices = ((starts[:, :, None] + np.arange(block)) % len(daily)).reshape(count, -1)[:, :len(daily)]
            means = daily[indices].mean(axis=1) * 365
            if offset == 0:
                for i in range(20):
                    scalar = []
                    for start in starts[i]:
                        scalar.extend(float(daily[(int(start) + j) % len(daily)]) for j in range(block))
                    reference = sum(scalar[:len(daily)]) / len(daily) * 365
                    if abs(reference - means[i]) > 1e-10:
                        raise ValueError('independent resampling arithmetic mismatch')
                    checked += 1
            samples.extend(means.tolist())
        alpha = settings['family_alpha'] / 2
        lower, upper = np.quantile(samples, [alpha / 2, 1 - alpha / 2])
        width = float((upper - lower) / 2)
        runs.append(dict(block_days=block, annualized_mean_pct=float(daily.mean() * 365),
                         interval_pct=[float(lower), float(upper)], half_width_pp=width,
                         target_pp=policy['economics']['ci_half_width_pp'],
                         meets_precision_target=width <= policy['economics']['ci_half_width_pp'],
                         independent_resample_checks=checked))
    result = dict(status='DIAGNOSTIC_COMPLETE_NOT_A_POWER_ANALYSIS', calendar_days=len(daily), runs=runs,
                  decision='DO_NOT_REGISTER_FORWARD_DURATION_AS_CALIBRATED',
                  limitations=['Existing selected T0 path; future variance and dependence can differ.',
                               'No candidate-minus-control series exists; comparative precision is unassessed.',
                               'Bootstrap approximation and two block lengths do not prove coverage or independence.',
                               'No horizon extrapolation or performance-based extension was performed.'])
    (OUT / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
