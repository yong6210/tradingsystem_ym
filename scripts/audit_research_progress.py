"""Read-only provenance review and supplemental risk metrics for E005–E012.

This does not rerun strategies, certify live trading, or create acceptance gates.
Writes a fresh review directory; historical experiment artifacts remain immutable.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.diagnostics.review_metrics import calendar_risk

EXPERIMENTS = (
    'e005_btcusdc_comparison_20260917',
    'e006_loss_exit_diagnostics_20260917',
    'e007_order_rules_20260917',
    'e008_candidate_accounts_20260917',
    'e009_taker_alignment_20260917',
    'e010_funding_basis_20260917',
    'e011_trend_pullback_20260917',
    'e012_account_constraints_20260917',
)


def read(path):
    return json.loads(path.read_text())


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'reports/validation/research_review_20260917')
    output = parser.parse_args().output
    output.mkdir(parents=True, exist_ok=False)
    checks, inventory, risks, inputs = [], [], [], {}
    for name in EXPERIMENTS:
        folder = ROOT / 'reports/validation' / name
        registration = read(folder / 'registration.json')
        verification = read(folder / 'independent_verification.json')
        summary = read(folder / 'summary.json')
        status = read(folder / 'status.json')
        for filename in ('registration.json', 'independent_verification.json',
                         'summary.json', 'status.json'):
            path = folder / filename
            inputs[str(path.relative_to(ROOT))] = digest(path)
        for kind, hashes in (('source', registration['source_hashes']),
                             ('artifact', verification['artifact_hashes'])):
            for relative, expected in hashes.items():
                path = ROOT / relative
                actual = digest(path) if path.is_file() else None
                checks.append(dict(experiment=name, kind=kind, path=relative,
                                   expected=expected, actual=actual,
                                   passed=actual == expected))
        runs = summary.get('runs', {})
        inventory.append(dict(experiment=name, recorded_status=status,
                              verification_status=verification['status'],
                              source_count=len(registration['source_hashes']),
                              artifact_count=len(verification['artifact_hashes']),
                              account_runs=len(runs),
                              interpretation='REUSED_DATA_NOT_INDEPENDENT_CONFIRMATION'))
        for run, metrics in runs.items():
            path = folder / run / 'daily.jsonl'
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            supplemental = calendar_risk(rows, metrics['initial'])
            if supplemental['calendar_days'] != 730:
                raise ValueError(f'{name}/{run}: unexpected calendar coverage')
            if abs(rows[-1]['equity'] - metrics['final_equity']) > 1e-6:
                raise ValueError(f'{name}/{run}: final equity mismatch')
            inputs[str(path.relative_to(ROOT))] = digest(path)
            risks.append(dict(experiment=name, run=run,
                              return_pct=metrics['return_pct'],
                              engine_max_drawdown_pct=metrics['max_drawdown_pct'],
                              drawdown_halted=metrics['drawdown_halted'],
                              active_fraction=metrics['active_fraction'],
                              **supplemental))
    for relative in ('scripts/audit_research_progress.py',
                     'app/research/diagnostics/review_metrics.py',
                     'tests/test_review_metrics.py'):
        inputs[relative] = digest(ROOT / relative)
    failed = [c for c in checks if not c['passed']]
    review = dict(status='PASS_RECORDED_HASHES' if not failed else 'FAIL',
                  reviewed_at=datetime.now(timezone.utc).isoformat(),
                  scope='E005_E012_RECORDED_HASHES_AND_DAILY_RISK_ONLY',
                  experiments=inventory, hash_checks=len(checks),
                  unique_hashed_paths=len({c['path'] for c in checks}),
                  failed_checks=failed, account_rows=len(risks),
                  limitation='Hash integrity is not independent validation of every methodology assumption.')
    for filename, value in (('inventory.json', review), ('hash_checks.json', checks),
                            ('calendar_risk.json', risks), ('input_hashes.json', inputs)):
        (output / filename).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    selected = [('e005', 'stress_T0'), ('e010', 'stress_S09FB'),
                ('e011', 'stress_P4'), ('e012', 'stress_contract_full')]
    table = ['| 모델 / 스트레스 | 2년 수익률 | 엔진 최대 DD | 최장 고점 미회복 | 종료 시 미회복 | 최악 일수익 | 일 ES 5% |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for prefix, run in selected:
        r = next(r for r in risks if r['experiment'].startswith(prefix) and r['run'] == run)
        table.append(f"| {prefix.upper()} / {run} | {r['return_pct']:+.2f}% | "
                     f"{r['engine_max_drawdown_pct']:.2f}% | {r['longest_underwater_days']}일 | "
                     f"{r['current_underwater_days']}일 | {r['worst_daily_return_pct']:.3f}% | "
                     f"{r['daily_es_5pct']:.3f}% |")
    (output / 'risk_table.md').write_text('\n'.join(table) + '\n')
    print(json.dumps({k: review[k] for k in ('status', 'hash_checks', 'unique_hashed_paths',
                                            'failed_checks', 'account_rows')}, indent=2))
    print('\n'.join(table))
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
