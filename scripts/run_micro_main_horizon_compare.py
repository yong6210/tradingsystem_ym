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
    parser = argparse.ArgumentParser(description="Compare session_impulse_retest over multiple horizons.")
    parser.add_argument("--symbols", default="BTCUSDC,ETHUSDC,SOLUSDC,LINKUSDC,BNBUSDC,XRPUSDC,ADAUSDC,AVAXUSDC")
    parser.add_argument("--horizons", default="365,730,1095")
    parser.add_argument("--profile", default="baseline")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _run_single(repo: CandleRepository, *, symbol: str, lookback_days: int, profile_name: str) -> dict[str, Any]:
    last_1m = repo.get_last_candle(symbol, "1m")
    first_1m = repo.get_first_candle(symbol, "1m")
    last_5m = repo.get_last_candle(symbol, "5m")
    if last_1m is None or first_1m is None or last_5m is None:
        return {"error": "missing_1m_or_5m_candles"}

    end_ts = last_1m.ts if last_1m.ts.tzinfo is not None else last_1m.ts.replace(tzinfo=UTC)
    start_ts = max(
        first_1m.ts if first_1m.ts.tzinfo is not None else first_1m.ts.replace(tzinfo=UTC),
        end_ts - timedelta(days=max(int(lookback_days), 1)),
    )
    candles_1m = repo.list_range(symbol=symbol, timeframe="1m", start_ts=start_ts, end_ts=end_ts)
    candles_5m = repo.list_range(symbol=symbol, timeframe="5m", start_ts=start_ts - timedelta(days=2), end_ts=end_ts)
    if len(candles_1m) < 600 or len(candles_5m) < 200:
        return {
            "error": "insufficient_candles",
            "candles_1m": len(candles_1m),
            "candles_5m": len(candles_5m),
            "start_ts": start_ts.isoformat(),
            "end_ts": end_ts.isoformat(),
        }

    engine = SessionImpulseRetestResearch(
        symbol=symbol,
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        profile_name=profile_name,
    )
    trades = engine.backtest()
    summary = summarize_micro_trades(trades)
    summary["decision"] = decision_for_micro_summary(summary)
    return {
        "profile": profile_name,
        "window": {
            "start_ts": start_ts.isoformat(),
            "end_ts": end_ts.isoformat(),
            "candles_1m": len(candles_1m),
            "candles_5m": len(candles_5m),
        },
        "summary": summary,
    }


def main() -> int:
    args = _parse_args()
    init_db()
    settings = get_settings()
    generated_at = datetime.now(UTC)
    symbols = [item.strip().upper() for item in str(args.symbols or "").split(",") if item.strip()]
    horizons = [int(item.strip()) for item in str(args.horizons or "").split(",") if item.strip()]

    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "symbols": symbols,
        "horizons": horizons,
        "profile": str(args.profile or "baseline").strip().lower(),
        "results": {},
    }

    with SessionLocal() as db:
        repo = CandleRepository(db)
        for symbol in symbols:
            symbol_payload: dict[str, Any] = {}
            by_horizon: dict[int, dict[str, Any]] = {}
            for horizon in horizons:
                result = _run_single(
                    repo,
                    symbol=symbol,
                    lookback_days=horizon,
                    profile_name=payload["profile"],
                )
                symbol_payload[str(horizon)] = result
                if "summary" in result:
                    by_horizon[horizon] = result["summary"]

            compare: dict[str, Any] = {}
            if 365 in by_horizon and 730 in by_horizon:
                one = by_horizon[365]
                two = by_horizon[730]
                compare = {
                    "ev_ratio_730_vs_365": round(float(two.get("ev_r", 0.0)) / max(float(one.get("ev_r", 0.0)), 1e-9), 4),
                    "total_r_ratio_730_vs_365": round(float(two.get("total_r", 0.0)) / max(float(one.get("total_r", 0.0)), 1e-9), 4),
                    "closed_ratio_730_vs_365": round(float(two.get("closed", 0.0)) / max(float(one.get("closed", 0.0)), 1e-9), 4),
                    "decision_365": one.get("decision"),
                    "decision_730": two.get("decision"),
                }
            if 365 in by_horizon and 1095 in by_horizon:
                one = by_horizon[365]
                three = by_horizon[1095]
                compare.update(
                    {
                        "ev_ratio_1095_vs_365": round(float(three.get("ev_r", 0.0)) / max(float(one.get("ev_r", 0.0)), 1e-9), 4),
                        "total_r_ratio_1095_vs_365": round(float(three.get("total_r", 0.0)) / max(float(one.get("total_r", 0.0)), 1e-9), 4),
                        "closed_ratio_1095_vs_365": round(float(three.get("closed", 0.0)) / max(float(one.get("closed", 0.0)), 1e-9), 4),
                        "decision_1095": three.get("decision"),
                    }
                )
            symbol_payload["comparison"] = compare
            payload["results"][symbol] = symbol_payload

    if args.write_report:
        out_dir = Path(settings.validation_report_dir) / "micro_main_horizon_compares"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"micro_main_horizon_compare_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["report_path"] = str(out_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
