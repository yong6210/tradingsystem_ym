"""Independently check review metrics using Decimal and high-water-mark indices."""
from decimal import Decimal
from itertools import accumulate
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/validation/research_review_20260917'


def main():
    metrics = json.loads((OUT / 'calendar_risk.json').read_text())
    for record in metrics:
        path = ROOT / 'reports/validation' / record['experiment'] / record['run'] / 'daily.jsonl'
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        equity = [Decimal(1000)] + [Decimal(str(row['equity'])) for row in rows]
        high_water = list(accumulate(equity, max))
        peaks = [i for i, (value, peak) in enumerate(zip(equity, high_water)) if value == peak]
        spans = [b - a for a, b in zip(peaks, peaks[1:]) if b - a > 1]
        current = len(rows) - peaks[-1]
        integers = dict(longest_underwater_days=max(spans + [current, 0]),
                        longest_completed_recovery_days=max(spans + [0]),
                        current_underwater_days=current, completed_recoveries=len(spans))
        for key, value in integers.items():
            if record[key] != value:
                raise ValueError(f'{record["run"]}: {key} mismatch')
        if record['unrecovered_at_end'] != (current > 0):
            raise ValueError('right censoring mismatch')
        returns = sorted((b / a - 1) * 100 for a, b in zip(equity, equity[1:]))
        count = (len(returns) + 19) // 20
        for key, value in (('worst_daily_return_pct', returns[0]),
                           ('daily_es_5pct', sum(returns[:count]) / count)):
            if abs(Decimal(str(record[key])) - value) > Decimal('1e-10'):
                raise ValueError(f'{record["run"]}: {key} mismatch')
    result = dict(status='PASS', account_rows=len(metrics),
                  method='DECIMAL_RETURNS_AND_HIGH_WATER_INDEX_GAPS',
                  metrics_sha256=hashlib.sha256((OUT / 'calendar_risk.json').read_bytes()).hexdigest(),
                  verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT / 'independent_risk_verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
