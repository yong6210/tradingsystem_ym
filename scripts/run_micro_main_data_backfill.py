#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.repositories import CandleRepository
from app.db.session import SessionLocal, init_db
from app.services.market_data import MarketDataService


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill 1m/5m candles for micro main strategy until a target date.")
    parser.add_argument("--symbols", default="BTCUSDC,ETHUSDC,SOLUSDC,BNBUSDC,XRPUSDC")
    parser.add_argument("--target-date", default="2024-04-23", help="UTC date (YYYY-MM-DD) to backfill toward.")
    parser.add_argument("--limit-1m", type=int, default=1500)
    parser.add_argument("--limit-5m", type=int, default=1500)
    parser.add_argument("--max-steps-1m", type=int, default=900)
    parser.add_argument("--max-steps-5m", type=int, default=180)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _parse_target_date(raw: str) -> datetime:
    text = str(raw or "").strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid --target-date YYYY-MM-DD value: {text}") from exc
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _backfill_timeframe(
    *,
    symbol: str,
    timeframe: str,
    target_ts: datetime,
    limit: int,
    max_steps: int,
    repo: CandleRepository,
    service: MarketDataService,
) -> dict[str, Any]:
    added = 0
    batches = 0
    status = "max_steps_exhausted"
    before_first = repo.get_first_candle(symbol, timeframe)
    before_ts = _as_utc(before_first.ts) if before_first else None
    for _ in range(max(int(max_steps), 0)):
        first = repo.get_first_candle(symbol, timeframe)
        if first is None:
            status = "missing_first"
            break
        first_ts = _as_utc(first.ts)
        if first_ts is None:
            status = "missing_first"
            break
        if first_ts <= target_ts:
            status = "target_reached"
            break
        batch = service.backfill_history_before_latest(
            symbol=symbol,
            timeframe=timeframe,
            limit=max(int(limit), 1),
            batches=1,
        )
        service.candle_repo.db.commit()
        added += int(batch)
        batches += 1
        if batch <= 0:
            status = "stalled"
            break
    after_first = repo.get_first_candle(symbol, timeframe)
    after_ts = _as_utc(after_first.ts) if after_first else None
    reached_target = bool(after_ts and after_ts <= target_ts)
    return {
        "timeframe": timeframe,
        "before_first_ts": before_ts.isoformat() if before_ts else None,
        "after_first_ts": after_ts.isoformat() if after_ts else None,
        "added_rows": added,
        "batches": batches,
        "status": "target_reached" if reached_target else status,
        "reached_target": reached_target,
    }


def main() -> int:
    args = _parse_args()
    init_db()
    settings = get_settings()
    generated_at = datetime.now(UTC)
    try:
        target_ts = _parse_target_date(args.target_date)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    symbols = [item.strip().upper() for item in str(args.symbols or "").split(",") if item.strip()]

    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "symbols": symbols,
        "target_date": target_ts.date().isoformat(),
        "results": {},
    }

    with SessionLocal() as db:
        repo = CandleRepository(db)
        service = MarketDataService(repo)
        for symbol in symbols:
            one_min = _backfill_timeframe(
                symbol=symbol,
                timeframe="1m",
                target_ts=target_ts,
                limit=int(args.limit_1m),
                max_steps=int(args.max_steps_1m),
                repo=repo,
                service=service,
            )
            five_min = _backfill_timeframe(
                symbol=symbol,
                timeframe="5m",
                target_ts=target_ts,
                limit=int(args.limit_5m),
                max_steps=int(args.max_steps_5m),
                repo=repo,
                service=service,
            )
            payload["results"][symbol] = {
                "1m": one_min,
                "5m": five_min,
            }

    if args.write_report:
        out_dir = Path(settings.validation_report_dir) / "micro_main_backfills"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"micro_main_backfill_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["report_path"] = str(out_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
