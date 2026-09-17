"""Validate saved REST gap responses; publish only exact, valid supplements."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/historical/btcusdc_public_20260917'


def validate_bars(rows, start, end):
    if [r[0] for r in rows] != list(range(start, end, 60000)):
        raise ValueError('incomplete, duplicate, or out-of-order timestamps')
    for r in rows:
        if len(r) != 12 or r[6] != r[0] + 59999:
            raise ValueError('invalid schema or close time')
        o, h, l, c = map(Decimal, r[1:5])
        if not all(v.is_finite() and v > 0 for v in (o, h, l, c)):
            raise ValueError('invalid price')
        if not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError('invalid OHLC geometry')
    return len(rows)


def main():
    probe_path = DATA / 'gap_probe_manifest.json'
    probes = json.loads(probe_path.read_text())['probes']
    accepted, unresolved = [], []
    for record in probes:
        if not record.get('exact_timestamp_coverage'):
            unresolved.append(record)
            continue
        raw = (ROOT / record['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != record['sha256']:
            raise ValueError('supplement hash changed')
        count = validate_bars(json.loads(raw), record['start_ms'], record['end_exclusive_ms'])
        accepted.append(dict(record, validated_rows=count, status='VALIDATED_SUPPLEMENT'))
    result = dict(status='PARTIAL_COVERAGE', supplements=accepted, unresolved=unresolved,
                  source_manifest_sha256=hashlib.sha256(probe_path.read_bytes()).hexdigest(),
                  policy='Read validated supplements alongside immutable archives. Never forward-fill unresolved prices. No performance results implied.')
    (DATA / 'validated_overlay.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(status=result['status'], supplements=len(accepted), unresolved=len(unresolved))))


if __name__ == '__main__':
    main()
