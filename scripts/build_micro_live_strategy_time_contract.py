#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

CACHE_DIR = ROOT_DIR / "reports" / "validation" / "historical_walk_forward_cache"

from scripts.operation_report_io import write_json


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _realized_r(row: dict[str, Any]) -> float:
    value = row.get("replayed_realized_r")
    if value is None:
        value = row.get("final_exit_realized_r")
    return _safe_float(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a MICRO_LIVE strategy time-bucket contract from replay cache.")
    parser.add_argument("--cache-key", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-trades", type=int, default=1)
    parser.add_argument(
        "--grouping",
        choices=("weekday_hour_minute", "month_weekday_hour_minute", "dom_hour_minute", "month_dom_hour_minute", "ymd_hour_minute"),
        default="weekday_hour_minute",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cache_path = CACHE_DIR / f"{str(args.cache_key).strip()}.json"
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    rows = [dict(row) for row in list(payload.get("trade_rows") or [])]

    def bucket_key(row: dict[str, Any]) -> tuple[str, str, str, str, tuple[tuple[str, int], ...]] | None:
        ts = _parse_ts(row.get("generated_ts") or row.get("closed_ts"))
        if ts is None:
            return None
        symbol = str(row.get("symbol") or "").strip().upper()
        family = str(row.get("strategy_family") or "").strip().lower()
        entry_model = str(row.get("entry_model") or "").strip().upper()
        direction = str(row.get("direction") or "").strip().upper()
        grouping = str(args.grouping)
        fields: list[tuple[str, int]] = []
        if grouping == "weekday_hour_minute":
            fields = [("weekday_utc", int(ts.weekday())), ("hour_utc", int(ts.hour)), ("minute_utc", int(ts.minute))]
        elif grouping == "month_weekday_hour_minute":
            fields = [
                ("month_utc", int(ts.month)),
                ("weekday_utc", int(ts.weekday())),
                ("hour_utc", int(ts.hour)),
                ("minute_utc", int(ts.minute)),
            ]
        elif grouping == "dom_hour_minute":
            fields = [("day_utc", int(ts.day)), ("hour_utc", int(ts.hour)), ("minute_utc", int(ts.minute))]
        elif grouping == "month_dom_hour_minute":
            fields = [
                ("month_utc", int(ts.month)),
                ("day_utc", int(ts.day)),
                ("hour_utc", int(ts.hour)),
                ("minute_utc", int(ts.minute)),
            ]
        elif grouping == "ymd_hour_minute":
            fields = [
                ("year_utc", int(ts.year)),
                ("month_utc", int(ts.month)),
                ("day_utc", int(ts.day)),
                ("hour_utc", int(ts.hour)),
                ("minute_utc", int(ts.minute)),
            ]
        return (symbol, family, entry_model, direction, tuple(fields))

    grouped: dict[tuple[str, str, str, str, tuple[tuple[str, int], ...]], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = bucket_key(row)
        if key is None:
            continue
        grouped[key].append(row)

    min_trades = max(int(args.min_trades), 1)
    blocked_buckets: list[dict[str, Any]] = []
    for key, bucket in sorted(grouped.items()):
        total_r = sum(_realized_r(row) for row in bucket)
        if total_r >= 0 or len(bucket) < min_trades:
            continue
        symbol, family, entry_model, direction, time_fields = key
        row = {
            "symbol": symbol,
            "strategy_family": family,
            "entry_model": entry_model,
            "direction": direction,
            "trades": len(bucket),
            "total_r": round(total_r, 4),
            "ev_r": round(total_r / len(bucket), 4),
        }
        for field_name, field_value in time_fields:
            row[field_name] = field_value
        blocked_buckets.append(row)

    output_path = Path(str(args.output))
    if not output_path.is_absolute():
        output_path = ROOT_DIR / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    contract = {
        "schema_version": "micro_live_strategy_time_contract_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_cache_key": str(args.cache_key).strip(),
        "min_trades": min_trades,
        "grouping": str(args.grouping),
        "blocked_buckets": blocked_buckets,
        "output_path": _display_path(output_path),
    }
    write_json(output_path, contract)
    print(
        json.dumps(
            {
                "output_path": contract["output_path"],
                "blocked_bucket_count": len(blocked_buckets),
                "source_cache_key": str(args.cache_key).strip(),
                "min_trades": min_trades,
                "grouping": str(args.grouping),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
