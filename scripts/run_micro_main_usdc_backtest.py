#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import json
from dataclasses import asdict
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
    session_impulse_retest_profile_for_symbol,
    summarize_micro_trades,
)
from app.services.report_io import atomic_write_text
from scripts.run_micro_main_usdt_proxy_backtest import _build_loss_analysis, _trade_to_row


_DEFAULT_USDC_SYMBOLS = (
    "BTCUSDC,ETHUSDC,SOLUSDC,LINKUSDC,BNBUSDC,XRPUSDC,ADAUSDC,AVAXUSDC,"
    "BCHUSDC,LTCUSDC,NEARUSDC,FILUSDC,DOGEUSDC"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run direct USDC candle backtest for micro main strategy.")
    parser.add_argument("--symbols", default=_DEFAULT_USDC_SYMBOLS)
    parser.add_argument("--days", type=int, default=1825)
    parser.add_argument("--include-trades", action="store_true")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--write-loss-analysis", action="store_true")
    parser.add_argument("--loss-analysis-min-bucket-trades", type=int, default=12)
    parser.add_argument("--loss-analysis-min-negative-years", type=int, default=2)
    return parser.parse_args()


def _to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _run_symbol(
    repo: CandleRepository,
    *,
    symbol: str,
    cutoff: datetime,
    end_ts: datetime,
    include_trades: bool,
) -> dict[str, Any]:
    first_1m = repo.get_first_candle(symbol, "1m")
    last_1m = repo.get_last_candle(symbol, "1m")
    first_5m = repo.get_first_candle(symbol, "5m")
    last_5m = repo.get_last_candle(symbol, "5m")
    profile_name = session_impulse_retest_profile_for_symbol(symbol)
    if first_1m is None or last_1m is None or first_5m is None or last_5m is None:
        return {
            "symbol": symbol,
            "profile_name": profile_name,
            "error": "missing_candles",
            "summary": summarize_micro_trades([]),
        }

    first_1m_ts = _to_utc(first_1m.ts)
    first_5m_ts = _to_utc(first_5m.ts)
    last_1m_ts = _to_utc(last_1m.ts)
    last_5m_ts = _to_utc(last_5m.ts)
    if first_1m_ts is None or first_5m_ts is None or last_1m_ts is None or last_5m_ts is None:
        return {
            "symbol": symbol,
            "profile_name": profile_name,
            "error": "invalid_candle_timestamps",
            "summary": summarize_micro_trades([]),
        }

    bounded_end_ts = min(last_1m_ts, last_5m_ts, end_ts)
    warmup_1m_start = max(first_1m_ts, cutoff - timedelta(hours=12))
    warmup_5m_start = max(first_5m_ts, cutoff - timedelta(days=2))
    candles_1m = repo.list_range(symbol=symbol, timeframe="1m", start_ts=warmup_1m_start, end_ts=bounded_end_ts)
    candles_5m = repo.list_range(symbol=symbol, timeframe="5m", start_ts=warmup_5m_start, end_ts=bounded_end_ts)
    if len(candles_1m) < 600 or len(candles_5m) < 200:
        return {
            "symbol": symbol,
            "profile_name": profile_name,
            "error": "insufficient_candles",
            "window": {
                "requested_start_ts": cutoff.isoformat(),
                "requested_end_ts": end_ts.isoformat(),
                "actual_start_1m_ts": candles_1m[0].ts.isoformat() if candles_1m else None,
                "actual_start_5m_ts": candles_5m[0].ts.isoformat() if candles_5m else None,
                "actual_end_1m_ts": candles_1m[-1].ts.isoformat() if candles_1m else None,
                "actual_end_5m_ts": candles_5m[-1].ts.isoformat() if candles_5m else None,
                "candles_1m": len(candles_1m),
                "candles_5m": len(candles_5m),
            },
            "summary": summarize_micro_trades([]),
        }

    engine = SessionImpulseRetestResearch(
        symbol=symbol,
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        profile_name=profile_name,
    )
    trades = [trade for trade in engine.backtest() if cutoff <= engine._normalize_ts(trade.entry_ts) <= bounded_end_ts]
    summary = summarize_micro_trades(trades)
    summary["decision"] = decision_for_micro_summary(summary)
    payload: dict[str, Any] = {
        "symbol": symbol,
        "profile_name": profile_name,
        "exit_policy": asdict(engine.exit_policy),
        "window": {
            "requested_start_ts": cutoff.isoformat(),
            "requested_end_ts": end_ts.isoformat(),
            "actual_start_1m_ts": candles_1m[0].ts.isoformat(),
            "actual_start_5m_ts": candles_5m[0].ts.isoformat(),
            "actual_end_1m_ts": candles_1m[-1].ts.isoformat(),
            "actual_end_5m_ts": candles_5m[-1].ts.isoformat(),
            "effective_start_ts": max(cutoff, engine._normalize_ts(candles_1m[0].ts)).isoformat(),
            "effective_end_ts": bounded_end_ts.isoformat(),
            "candles_1m": len(candles_1m),
            "candles_5m": len(candles_5m),
        },
        "summary": summary,
    }
    if include_trades:
        payload["trades"] = [
            _trade_to_row(trade=trade, proxy_symbol=symbol, canonical_symbol=symbol, profile_name=profile_name)
            for trade in trades
        ]
    del candles_1m
    del candles_5m
    del trades
    gc.collect()
    return payload


def main() -> int:
    args = _parse_args()
    init_db()
    settings = get_settings()
    generated_at = datetime.now(UTC)
    end_ts = generated_at.replace(second=0, microsecond=0)
    cutoff = end_ts - timedelta(days=max(int(args.days), 1))
    symbols = [item.strip().upper() for item in str(args.symbols or "").split(",") if item.strip()]

    include_trades = bool(args.include_trades or args.write_loss_analysis)
    results: dict[str, Any] = {}
    aggregate_closed = 0
    aggregate_total_r = 0.0
    with SessionLocal() as db:
        repo = CandleRepository(db)
        for symbol in symbols:
            result = _run_symbol(
                repo,
                symbol=symbol,
                cutoff=cutoff,
                end_ts=end_ts,
                include_trades=include_trades,
            )
            results[symbol] = result
            summary = dict(result.get("summary") or {})
            aggregate_closed += int(summary.get("closed", 0) or 0)
            aggregate_total_r += float(summary.get("total_r", 0.0) or 0.0)
            print(
                json.dumps(
                    {
                        "progress": symbol,
                        "closed": int(summary.get("closed", 0) or 0),
                        "ev_r": float(summary.get("ev_r", 0.0) or 0.0),
                        "error": result.get("error"),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "days": max(int(args.days), 1),
        "data_source": "direct_usdc_runtime_candles",
        "symbols": symbols,
        "exit_policy": next(
            (
                dict(result.get("exit_policy") or {})
                for result in results.values()
                if isinstance(result, dict) and isinstance(result.get("exit_policy"), dict)
            ),
            {},
        ),
        "aggregate": {
            "closed": aggregate_closed,
            "total_r": round(aggregate_total_r, 4),
            "ev_r": round(aggregate_total_r / aggregate_closed, 4) if aggregate_closed else 0.0,
        },
        "results": results,
        "report_path": None,
    }
    if args.write_report:
        out_dir = Path(settings.validation_report_dir) / "micro_main_usdc_backtests"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"micro_main_usdc_backtest_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        payload["report_path"] = str(out_path)
        atomic_write_text(out_path, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    if args.write_loss_analysis:
        rows: list[dict[str, Any]] = []
        for result in results.values():
            rows.extend(list(dict(result).get("trades") or []))
        loss_payload = _build_loss_analysis(
            rows,
            min_bucket_trades=int(args.loss_analysis_min_bucket_trades),
            min_negative_years=int(args.loss_analysis_min_negative_years),
        )
        out_dir = Path(settings.validation_report_dir) / "micro_main_usdc_backtests"
        out_dir.mkdir(parents=True, exist_ok=True)
        loss_path = out_dir / f"micro_main_usdc_loss_analysis_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        atomic_write_text(loss_path, json.dumps(loss_payload, ensure_ascii=False, indent=2, default=str))
        payload["loss_analysis_path"] = str(loss_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
