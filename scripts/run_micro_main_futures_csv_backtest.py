#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.futures_csv_backtest import run_futures_csv_backtest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run session_impulse_retest against external futures 1m CSV data.")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--symbol", required=True, help="Label for the futures symbol, e.g. NQ1! or MNQ.")
    parser.add_argument("--profile", default="baseline", choices=("baseline", "relaxed_v1"))
    parser.add_argument("--timezone", default="America/Chicago", help="Timezone of the CSV timestamps.")
    parser.add_argument("--days", type=int, default=None, help="Optional rolling lookback window.")
    parser.add_argument("--start-ts", default=None, help="Optional inclusive UTC/ISO start timestamp.")
    parser.add_argument("--end-ts", default=None, help="Optional inclusive UTC/ISO end timestamp.")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _parse_optional_ts(raw: str | None) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    generated_at = datetime.now(UTC)
    payload = run_futures_csv_backtest(
        csv_path=args.csv,
        symbol=args.symbol,
        profile_name=str(args.profile or "baseline").strip().lower(),
        timezone_name=str(args.timezone or "America/Chicago").strip() or "America/Chicago",
        lookback_days=int(args.days) if args.days else None,
        start_ts=_parse_optional_ts(args.start_ts),
        end_ts=_parse_optional_ts(args.end_ts),
    )
    payload["generated_at"] = generated_at.isoformat()

    if args.write_report:
        out_dir = Path(settings.validation_report_dir) / "micro_main_futures_csv_backtests"
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(str(args.csv)).stem.replace(" ", "_")
        out_path = out_dir / f"micro_main_futures_csv_backtest_{stem}_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["report_path"] = str(out_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
