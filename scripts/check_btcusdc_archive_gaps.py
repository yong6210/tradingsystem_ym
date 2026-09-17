"""Probe missing official archive bars; preserve responses without filling prices."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/historical/btcusdc_public_20260917'


def probe(job):
    kind, start, end = job
    endpoint = {'markPriceKlines': 'markPriceKlines', 'indexPriceKlines': 'indexPriceKlines', 'klines': 'klines'}[kind]
    params = {'pair' if kind == 'indexPriceKlines' else 'symbol': 'BTCUSDC',
              'interval': '1m', 'startTime': start, 'endTime': end - 1, 'limit': 1500}
    url = 'https://fapi.binance.com/fapi/v1/' + endpoint + '?' + urllib.parse.urlencode(params)
    record = dict(kind=kind, start_ms=start, end_exclusive_ms=end, url=url,
                  retrieved_at=datetime.now(timezone.utc).isoformat())
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            raw = response.read()
        path = DATA / 'gap_probes' / f'{kind}_{start}.json'
        path.write_bytes(raw)
        values = json.loads(raw)
        if not isinstance(values, list):
            raise ValueError('Expected bar list')
        times = [v[0] for v in values]
        expected = list(range(start, end, 60000))
        record.update(path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(raw).hexdigest(),
                      returned_rows=len(values), expected_rows=len(expected),
                      exact_timestamp_coverage=times == expected,
                      status='AVAILABLE_REQUIRES_OHLC_VALIDATION' if times == expected else 'UNRESOLVED')
    except Exception as exc:
        record.update(status='ERROR', error=str(exc))
    return record


def main():
    manifest = json.loads((DATA / 'manifest.json').read_text())
    jobs = [(a['kind'], g['before_ms'] + 60000, g['after_ms'])
            for a in manifest['archives'] for g in a.get('discontinuities', [])]
    contract = json.loads((DATA / 'contract.json').read_text())
    first = min(a['first_ms'] for a in manifest['archives'] if a['kind'] == 'klines')
    jobs.append(('klines', contract['onboardDate'], first))
    (DATA / 'gap_probes').mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(probe, jobs))
    result = dict(status='REVIEW_REQUIRED', probes=records,
                  policy='Raw probes only; archives unchanged. No interpolation or automatic overlay.')
    (DATA / 'gap_probe_manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
