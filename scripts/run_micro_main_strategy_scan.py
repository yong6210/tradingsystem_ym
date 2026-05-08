#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.repositories import CandleRepository
from app.db.session import SessionLocal, init_db
from app.services.micro_main_strategy_research import (
    SessionImpulseRetestResearch,
    decision_for_micro_summary,
    summarize_micro_trades,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run 5m setup + 1m execution micro main-strategy scan.")
    parser.add_argument("--symbols", default="BTCUSDC,ETHUSDC")
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    init_db()
    settings = get_settings()
    symbols = [item.strip().upper() for item in str(args.symbols or "").split(",") if item.strip()]
    generated_at = datetime.now(UTC)
    lookback_days = max(int(args.lookback_days), 1)

    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "symbols": symbols,
        "lookback_days": lookback_days,
        "results": {},
    }

    with SessionLocal() as db:
        repo = CandleRepository(db)
        for symbol in symbols:
            last_1m = repo.get_last_candle(symbol, "1m")
            first_1m = repo.get_first_candle(symbol, "1m")
            last_5m = repo.get_last_candle(symbol, "5m")
            if last_1m is None or first_1m is None or last_5m is None:
                payload["results"][symbol] = {"error": "missing_1m_or_5m_candles"}
                continue

            end_ts = last_1m.ts if last_1m.ts.tzinfo is not None else last_1m.ts.replace(tzinfo=UTC)
            start_ts = max(
                first_1m.ts if first_1m.ts.tzinfo is not None else first_1m.ts.replace(tzinfo=UTC),
                end_ts - timedelta(days=lookback_days),
            )
            candles_1m = repo.list_range(symbol=symbol, timeframe="1m", start_ts=start_ts, end_ts=end_ts)
            candles_5m = repo.list_range(symbol=symbol, timeframe="5m", start_ts=start_ts - timedelta(days=2), end_ts=end_ts)
            if len(candles_1m) < 600 or len(candles_5m) < 200:
                payload["results"][symbol] = {
                    "error": "insufficient_candles",
                    "candles_1m": len(candles_1m),
                    "candles_5m": len(candles_5m),
                    "start_ts": start_ts.isoformat(),
                    "end_ts": end_ts.isoformat(),
                }
                continue

            engine = SessionImpulseRetestResearch(symbol=symbol, candles_1m=candles_1m, candles_5m=candles_5m)
            trades = engine.backtest()
            summary = summarize_micro_trades(trades)
            summary["decision"] = decision_for_micro_summary(summary)
            summary["sample_trade_rows"] = [
                {
                    "entry_ts": trade.entry_ts.isoformat(),
                    "exit_ts": trade.exit_ts.isoformat(),
                    "direction": trade.direction,
                    "r_value": round(trade.r_value, 4),
                    "exit_reason": trade.exit_reason,
                }
                for trade in trades[:5]
            ]
            payload["results"][symbol] = {
                "window": {
                    "start_ts": start_ts.isoformat(),
                    "end_ts": end_ts.isoformat(),
                    "candles_1m": len(candles_1m),
                    "candles_5m": len(candles_5m),
                },
                "summary": summary,
            }

    if args.write_report:
        out_dir = Path(settings.validation_report_dir) / "micro_main_strategy_scans"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"micro_main_strategy_scan_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["report_path"] = str(out_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
