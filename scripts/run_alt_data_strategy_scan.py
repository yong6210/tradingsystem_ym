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
from app.db.repositories import BasisSnapshotRepository, CandleRepository, CrossAssetBreadthRepository, FundingRateRepository, LiquidationEventRepository, MacroEventRepository, OpenInterestRepository
from app.db.session import SessionLocal, init_db
from app.services.alt_data_strategy_research import AltDataResearchEngine, summarize_alt_data_research_trades


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run alt-data specialist strategy scans.")
    parser.add_argument("--symbols", default="BTCUSDC,ETHUSDC")
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument("--oi-period", default="15m")
    parser.add_argument("--basis-timeframe", default="15m")
    parser.add_argument("--breadth-timeframe", default="15m")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _decision(summary: dict[str, Any]) -> str:
    ev = float(summary.get("ev_r", 0.0) or 0.0)
    closed = int(summary.get("closed", 0) or 0)
    total_r = float(summary.get("total_r", 0.0) or 0.0)
    if total_r <= 0.0 or ev < 0.20 or closed < 20:
        return "REJECT"
    if ev >= 0.30 and closed >= 40:
        return "PASS"
    return "WATCH"


def main() -> int:
    args = _parse_args()
    init_db()
    settings = get_settings()
    symbols = [item.strip().upper() for item in str(args.symbols or "").split(",") if item.strip()]
    lookback_days = max(int(args.lookback_days), 1)
    generated_at = datetime.now(UTC)
    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "symbols": symbols,
        "lookback_days": lookback_days,
        "families": {},
    }

    with SessionLocal() as db:
        candle_repo = CandleRepository(db)
        funding_repo = FundingRateRepository(db)
        oi_repo = OpenInterestRepository(db)
        basis_repo = BasisSnapshotRepository(db)
        liquidation_repo = LiquidationEventRepository(db)
        breadth_repo = CrossAssetBreadthRepository(db)
        macro_repo = MacroEventRepository(db)

        for symbol in symbols:
            last_candle = candle_repo.get_last_candle(symbol, "15m")
            first_candle = candle_repo.get_first_candle(symbol, "15m")
            if last_candle is None or first_candle is None:
                payload["families"][symbol] = {"error": "missing_15m_candles"}
                continue
            end_ts = last_candle.ts if last_candle.ts.tzinfo is not None else last_candle.ts.replace(tzinfo=UTC)
            first_ts = first_candle.ts if first_candle.ts.tzinfo is not None else first_candle.ts.replace(tzinfo=UTC)
            start_ts = max(first_ts, end_ts - timedelta(days=lookback_days))
            candles = candle_repo.list_range(symbol=symbol, timeframe="15m", start_ts=start_ts, end_ts=end_ts)
            funding = funding_repo.list_range(symbol=symbol, start_ts=start_ts - timedelta(days=5), end_ts=end_ts)
            oi_rows = oi_repo.list_range(symbol=symbol, period=str(args.oi_period), start_ts=start_ts - timedelta(days=5), end_ts=end_ts)
            basis = basis_repo.list_range(symbol=symbol, timeframe=str(args.basis_timeframe), start_ts=start_ts - timedelta(days=5), end_ts=end_ts)
            liquidations = liquidation_repo.list_range(symbol=symbol, start_ts=start_ts - timedelta(days=5), end_ts=end_ts)
            breadth = breadth_repo.list_range(
                leader_symbol=symbol,
                timeframe=str(args.breadth_timeframe),
                start_ts=start_ts - timedelta(days=5),
                end_ts=end_ts,
            )
            macro_events = macro_repo.list_range(start_ts=start_ts - timedelta(days=5), end_ts=end_ts)
            if len(candles) < 100:
                payload["families"][symbol] = {"error": "insufficient_15m_candles", "candle_count": len(candles)}
                continue
            engine = AltDataResearchEngine(
                symbol=symbol,
                candles_15m=candles,
                funding_rates=funding,
                open_interest_rows=oi_rows,
                basis_rows=basis,
                liquidation_rows=liquidations,
                breadth_rows=breadth,
                macro_events=macro_events,
            )
            symbol_payload: dict[str, Any] = {
                "window": {
                    "start_ts": start_ts.isoformat(),
                    "end_ts": end_ts.isoformat(),
                    "candle_count": len(candles),
                    "funding_rows": len(funding),
                    "open_interest_rows": len(oi_rows),
                    "basis_rows": len(basis),
                    "liquidation_rows": len(liquidations),
                    "breadth_rows": len(breadth),
                    "macro_event_rows": len(macro_events),
                },
                "results": {},
            }
            for spec in engine.family_specs():
                trades = engine.backtest_family(spec.key)
                summary = summarize_alt_data_research_trades(trades)
                summary["decision"] = _decision(summary)
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
                symbol_payload["results"][spec.key] = summary
            payload["families"][symbol] = symbol_payload

    if args.write_report:
        out_dir = Path(settings.validation_report_dir) / "alt_data_strategy_scans"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"alt_data_strategy_scan_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["report_path"] = str(out_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
