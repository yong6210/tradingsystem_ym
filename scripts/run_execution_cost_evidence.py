"""Freeze then run Q001; outputs are exclusive-create and old evidence read-only."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from app.research.diagnostics.execution_cost_evidence import diagnose, summarize
from audit_execution_cost_evidence import audit, audit_summary

SOURCE = ROOT / 'reports/validation/e032_flow_snapshot_repair_20260919'
OUT = ROOT / 'reports/validation/q001_execution_cost_evidence_20260919'
DATES = ['2024-10-01', '2025-01-01', '2025-04-01', '2025-07-01',
         '2025-10-01', '2026-01-01', '2026-04-01', '2026-07-01']


def load(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open('x') as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
        f.write('\n')


def now():
    return datetime.now(timezone.utc).isoformat()


def check_hashes(mapping):
    for name, expected in mapping.items():
        assert sha(ROOT / name) == expected, name


def preserved():
    reset = load(ROOT / 'reports/validation/research_method_reset_v2_20260919/verification.json')
    hashes = {**reset['preserved_files'], **reset['new_artifact_hashes']}
    previous = load(SOURCE / 'verification.json')
    hashes.update({str((SOURCE / k).relative_to(ROOT)): v for k, v in previous['artifacts'].items()})
    check_hashes(hashes)
    return hashes


def register():
    assert not OUT.exists(), 'registration/output already exists'
    old = preserved()
    names = [
        'docs/research/experiments/Q001_EXECUTION_COST_EVIDENCE.md',
        'app/research/diagnostics/execution_cost_evidence.py',
        'scripts/run_execution_cost_evidence.py',
        'scripts/audit_execution_cost_evidence.py',
        'tests/test_execution_cost_evidence.py',
        'app/research/diagnostics/flow_absorption_v2.py',
        'app/research/baseline/account.py',
        'reports/validation/e032_flow_snapshot_repair_20260919/verification.json',
        'reports/validation/research_method_reset_v2_20260919/verification.json',
    ]
    hashes = {**old, **{name: sha(ROOT / name) for name in names}}
    OUT.mkdir()
    save(OUT / 'registration.json', dict(id='Q001', registered_at_utc=now(),
        type='DISPLAYED_COST_EVIDENCE_DIAGNOSTIC_NOT_STRATEGY_PERFORMANCE',
        dates=DATES, qty_btc='0.001', hypothetical_delay_seconds=3,
        exposure='REUSED_E032_80_MINUTES_NOT_FORWARD_OR_UNSEEN',
        quantile='NEAREST_RANK', frozen_hashes=hashes,
        performance_runs=0, new_market_requests=0, actual_orders=0,
        cost_calibration_or_old_candidate_reclassification_authorized=False))
    print('Registered Q001 before aggregate run:', OUT)


def run():
    registration = load(OUT / 'registration.json')
    check_hashes(registration['frozen_hashes'])
    assert not (OUT / 'summary.json').exists(), 'do not overwrite results'
    test = subprocess.run([sys.executable, '-m', 'unittest', 'tests.test_execution_cost_evidence', '-v'],
                          cwd=ROOT, text=True, capture_output=True)
    with (OUT / 'tests.log').open('x') as f:
        f.write(test.stdout + test.stderr)
    assert test.returncode == 0, test.stderr
    all_rows, by_date, audits = [], {}, {}
    for date in DATES:
        grid = [json.loads(line) for line in (SOURCE / date / 'grid.jsonl').read_text().splitlines()]
        start = int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp()) * 10**9
        assert len(grid) == 600 and grid[0]['time_ns'] == start
        assert grid[-1]['time_ns'] == start + 599 * 10**9
        rows = diagnose(grid)
        summary = summarize(rows)
        audits[date] = audit(grid, rows)
        audit_summary(rows, summary)
        by_date[date] = dict(grid_points=len(grid), valid_points=sum(p['valid'] for p in grid),
                             results=summary)
        all_rows.extend(dict(date=date, **row) for row in rows)
    overall = summarize(all_rows)
    audit_summary(all_rows, overall)
    with (OUT / 'displayed_costs.jsonl').open('x') as f:
        for row in all_rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    save(OUT / 'summary.json', dict(completed_at_utc=now(), status='DISPLAYED_COMPONENTS_ONLY',
        decision='ACTUAL_EXECUTION_COST_CALIBRATION_UNIDENTIFIED_NO_COST_CHANGE',
        quantity_btc='0.001', per_date=by_date, overall=overall,
        grid_points=sum(d['grid_points'] for d in by_date.values()),
        valid_points=sum(d['valid_points'] for d in by_date.values()),
        observations_are_overlapping_and_directions_paired=True,
        independent_profit_validation=False, original_scenario_costs_unchanged=True,
        new_strategy_backtests=0, new_market_requests=0, actual_orders=0))
    check_hashes(registration['frozen_hashes'])
    save(OUT / 'verification.json', dict(status='PASS_SCOPED_DISPLAYED_COST_ARITHMETIC',
        checked_frozen_hashes=len(registration['frozen_hashes']), by_date=audits,
        independent_method='Fraction cumulative-level intervals vs Decimal remaining-quantity walk; all rows and all summary statistics',
        original_raw_l2_reconstruction_independently_repeated=False,
        strategy_profit_or_real_fill_verified=False,
        artifacts={p.name: sha(p) for p in sorted(OUT.iterdir()) if p.is_file()}))
    print(json.dumps(dict(output=str(OUT), grid_points=4800,
        valid_points=sum(d['valid_points'] for d in by_date.values()), overall=overall), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['register', 'run'])
    args = parser.parse_args()
    register() if args.mode == 'register' else run()
