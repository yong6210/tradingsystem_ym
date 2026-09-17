#!/usr/bin/env python3
"""Validate monthly Binance 1m ZIPs and build immutable offline replay inputs."""
from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import io
import json
import math
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

NAME = re.compile(r"(?P<symbol>[A-Z0-9]+)-1m-(?P<year>\d{4})-(?P<month>\d{2})\.zip")
HEADER = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
INTERVALS = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat()


def _parse_row(row: list[str]) -> tuple[int, list[float], str]:
    if len(row) != 12 or any(not value.strip() for value in row):
        raise ValueError("column_count_or_missing_value")
    raw_open, raw_close = int(row[0]), int(row[6])
    divisor = 1000 if raw_open >= 100_000_000_000_000 else 1
    open_ms = raw_open // divisor
    if raw_open % (60_000 * divisor) or raw_close - raw_open != 60_000 * divisor - 1:
        raise ValueError("minute_timestamp_alignment")
    values = [float(row[i]) for i in (1, 2, 3, 4, 5, 7, 9, 10)]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("nonfinite_value")
    o, h, low, c, volume, quote, taker, taker_quote = values
    if min(o, h, low, c) <= 0 or h < max(o, c) or low > min(o, c):
        raise ValueError("invalid_ohlc")
    if min(volume, quote, taker, taker_quote) < 0 or int(row[8]) < 0:
        raise ValueError("negative_volume_or_count")
    if taker > volume + 1e-8 or taker_quote > quote + 1e-6:
        raise ValueError("taker_volume_exceeds_total")
    return open_ms, values[:5], "microseconds" if divisor == 1000 else "milliseconds"


def prepare_archives(paths: list[Path], output_dir: Path) -> dict:
    if not paths:
        raise ValueError("no ZIP archives provided")
    if output_dir.exists():
        raise ValueError("output directory already exists; choose a new dataset directory")
    files = []
    errors = Counter()
    examples = []
    seen = set()
    previous = None
    first = None
    symbol = None
    total = 0
    missing_minutes = 0
    future_limit = int(datetime.now(UTC).timestamp() * 1000)
    pending = {}
    bars = {interval: [] for interval in INTERVALS}

    def fail(reason, path, line):
        errors[reason] += 1
        if len(examples) < 20:
            examples.append({"file": str(path), "line": line, "reason": reason})

    def flush(interval):
        bucket = pending.get(interval)
        if bucket is None:
            return
        if bucket.pop("count") == INTERVALS[interval]:
            bars[interval].append(bucket)
        else:
            errors[f"incomplete_{interval}_bucket"] += 1

    for path in sorted(paths, key=lambda item: item.name):
        match = NAME.fullmatch(path.name)
        if match is None:
            raise ValueError(f"unsupported archive filename: {path.name}")
        current_symbol = match['symbol']
        if symbol is not None and current_symbol != symbol:
            raise ValueError("mixed symbols are not supported in one dataset")
        symbol = current_symbol
        year, month = int(match['year']), int(match['month'])
        expected_rows = calendar.monthrange(year, month)[1] * 1440
        start = int(datetime(year, month, 1, tzinfo=UTC).timestamp() * 1000)
        end = start + expected_rows * 60_000
        with path.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        profile = {"path": str(path.resolve()), "sha256": digest, "rows": 0, "valid_rows": 0,
                   "expected_rows": expected_rows, "first_open": None, "last_open": None,
                   "timestamp_units": [], "price_min": None, "price_max": None}
        with ZipFile(path) as archive:
            members = [entry for entry in archive.infolist() if not entry.is_dir()]
            if len(members) != 1 or Path(members[0].filename).name != path.stem + '.csv':
                raise ValueError(f"unexpected ZIP members: {path.name}")
            with archive.open(members[0]) as raw:
                reader = csv.reader(io.TextIOWrapper(raw, encoding='utf-8-sig'))
                for line, row in enumerate(reader, 1):
                    if line == 1 and row == HEADER:
                        continue
                    total += 1
                    profile['rows'] += 1
                    try:
                        ts, values, unit = _parse_row(row)
                    except (ValueError, OverflowError) as exc:
                        fail(str(exc), path, line)
                        continue
                    if not start <= ts < end:
                        fail('outside_filename_month', path, line)
                        continue
                    if ts + 60_000 > future_limit:
                        fail('future_or_unclosed_minute', path, line)
                        continue
                    if ts in seen:
                        fail('duplicate_open_time', path, line)
                        continue
                    seen.add(ts)
                    if previous is not None:
                        if ts < previous:
                            fail('reverse_open_time', path, line)
                            continue
                        missing_minutes += max(0, (ts - previous) // 60_000 - 1)
                    previous = ts
                    first = ts if first is None else first
                    profile['valid_rows'] += 1
                    profile['first_open'] = profile['first_open'] or _iso(ts)
                    profile['last_open'] = _iso(ts)
                    if unit not in profile['timestamp_units']:
                        profile['timestamp_units'].append(unit)
                    o, h, low, c, volume = values
                    profile['price_min'] = min(profile['price_min'] or low, low)
                    profile['price_max'] = max(profile['price_max'] or h, h)
                    for interval, minutes in INTERVALS.items():
                        bucket_ms = ts // (minutes * 60_000) * minutes * 60_000
                        bucket = pending.get(interval)
                        if bucket is None or bucket['open_ms'] != bucket_ms:
                            flush(interval)
                            pending[interval] = {"ts": _iso(bucket_ms), "open_ms": bucket_ms,
                                "o": o, "h": h, "l": low, "c": c, "v": volume, "count": 1}
                        else:
                            bucket['h'] = max(bucket['h'], h)
                            bucket['l'] = min(bucket['l'], low)
                            bucket['c'] = c
                            bucket['v'] += volume
                            bucket['count'] += 1
        if profile['valid_rows'] != expected_rows:
            errors['incomplete_month'] += 1
        files.append(profile)
    for interval in INTERVALS:
        flush(interval)
    if missing_minutes:
        errors['missing_minutes'] = missing_minutes
    report = {"schema_version": 1, "symbol": symbol, "source_grain": "1m",
        "source_kind": "user_supplied_monthly_zip", "source_authenticity": "not_independently_verified",
        "created_at": datetime.now(UTC).isoformat(), "status": 'FAIL' if errors else 'PASS',
        "file_count": len(files), "row_count": total, "unique_minutes": len(seen),
        "start": _iso(first) if first is not None else None,
        "end_exclusive": _iso(previous + 60_000) if previous is not None else None,
        "errors": dict(errors), "error_examples": examples, "files": files,
        "resampled_rows": {key: len(value) for key, value in bars.items()}}
    output_dir.mkdir(parents=True)
    # Only successful complete datasets can be consumed by the offline replay path.
    report['artifacts'] = {}
    if not errors:
        for interval, rows in bars.items():
            filename = f'{symbol}_{interval}.json'
            content = json.dumps({
                "symbol": symbol, "interval": interval, "rows": rows,
            }, separators=(',', ':')).encode('utf-8')
            (output_dir / filename).write_bytes(content)
            report['artifacts'][filename] = hashlib.sha256(content).hexdigest()
    (output_dir / 'manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archives', type=Path, nargs='+')
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    report = prepare_archives(args.archives, args.output_dir)
    print(json.dumps({k: v for k, v in report.items() if k != 'files'}, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
