#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import CURRENT_MICRO_LIVE_USDT_ACTIVE_SYMBOLS, get_settings
from app.services.intraday_compound_scalper import (
    IntradayCompoundScalper,
    IntradayScalpConfig,
    build_intraday_scalp_configs,
    intraday_scalp_decision,
    score_intraday_scalp_summary,
    summarize_intraday_scalp_trades,
    trade_to_dict,
)
from app.services.report_io import atomic_write_text
from scripts.run_btc_flip_rotation_search import _INTERVAL_MS, _csv, _load_bars


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only 15m/30m long-short intraday compound scalper backtest."
    )
    parser.add_argument("--symbols", default=CURRENT_MICRO_LIVE_USDT_ACTIVE_SYMBOLS)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--intervals", default="15m,30m")
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument("--min-trades", type=int, default=80)
    parser.add_argument("--max-models", type=int, default=0)
    parser.add_argument("--include-trades", action="store_true")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument(
        "--cache-dir",
        default="reports/validation/intraday_compound_scalper/cache",
    )
    parser.add_argument(
        "--report-dir",
        default="reports/validation/intraday_compound_scalper",
    )
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    return parser.parse_args()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed == parsed else default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _aggregate_symbol_summaries(trade_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in trade_rows:
        by_symbol.setdefault(str(row.get("symbol") or "unknown"), []).append(row)
    summaries: list[dict[str, Any]] = []
    for symbol, rows in sorted(by_symbol.items()):
        r_values = [_safe_float(row.get("r_value")) for row in rows]
        wins = [value for value in r_values if value > 0.0]
        losses = [value for value in r_values if value <= 0.0]
        summaries.append(
            {
                "symbol": symbol,
                "closed": len(rows),
                "total_r": round(sum(r_values), 4),
                "ev_r": round(sum(r_values) / len(rows), 4) if rows else 0.0,
                "win_rate": round(len(wins) / len(rows), 4) if rows else 0.0,
                "profit_factor": round(sum(wins) / max(abs(sum(losses)), 1e-12), 4) if losses else 999.0,
            }
        )
    summaries.sort(key=lambda row: (_safe_float(row.get("total_r")), _safe_float(row.get("ev_r"))), reverse=True)
    return summaries


def _build_result_row(
    *,
    config: IntradayScalpConfig,
    symbols: list[str],
    bars_by_key: dict[tuple[str, str], list[Any]],
    fee_bps_per_side: float,
    slippage_bps_per_side: float,
    min_trades: int,
    include_trades: bool,
) -> dict[str, Any]:
    trades = []
    for symbol in symbols:
        bars = bars_by_key.get((symbol, config.interval), [])
        if not bars:
            continue
        engine = IntradayCompoundScalper(
            symbol=symbol,
            bars=bars,
            config=config,
            fee_bps_per_side=fee_bps_per_side,
            slippage_bps_per_side=slippage_bps_per_side,
        )
        trades.extend(engine.backtest())

    trade_rows = [trade_to_dict(trade) for trade in trades]
    summary = summarize_intraday_scalp_trades(trades)
    summary["decision"] = intraday_scalp_decision(summary, min_trades=min_trades)
    summary["score"] = score_intraday_scalp_summary(summary)
    summary["by_symbol"] = _aggregate_symbol_summaries(trade_rows)
    row = {
        "model_id": config.model_id,
        "family": config.family,
        "interval": config.interval,
        "config": asdict(config),
        "summary": summary,
    }
    if include_trades:
        row["trades"] = trade_rows
    return row


def run_backtest(args: argparse.Namespace) -> dict[str, Any]:
    generated_at = datetime.now(UTC)
    symbols = [item.upper() for item in _csv(args.symbols)]
    intervals = [item for item in _csv(args.intervals) if item in _INTERVAL_MS and item in {"15m", "30m"}]
    if not symbols:
        raise SystemExit("at least one symbol is required")
    if not intervals:
        raise SystemExit("at least one interval in {15m,30m} is required")

    cache_dir = ROOT_DIR / str(args.cache_dir)
    base_url = str(args.base_url or getattr(get_settings(), "binance_futures_base_url", "https://fapi.binance.com"))
    bars_by_key: dict[tuple[str, str], list[Any]] = {}
    data_status: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        for interval in intervals:
            bars = _load_bars(
                symbol=symbol,
                interval=interval,
                days=max(int(args.days), 1),
                cache_dir=cache_dir,
                base_url=base_url,
                sleep_seconds=max(float(args.sleep_seconds), 0.0),
            )
            bars_by_key[(symbol, interval)] = bars
            data_status[f"{symbol}:{interval}"] = {
                "bars": len(bars),
                "first_ts": bars[0].ts.isoformat() if bars else None,
                "last_ts": bars[-1].ts.isoformat() if bars else None,
            }

    configs = build_intraday_scalp_configs(intervals)
    if int(args.max_models or 0) > 0:
        configs = configs[: int(args.max_models)]

    rows = []
    for idx, config in enumerate(configs, start=1):
        rows.append(
            _build_result_row(
                config=config,
                symbols=symbols,
                bars_by_key=bars_by_key,
                fee_bps_per_side=float(args.fee_bps_per_side),
                slippage_bps_per_side=float(args.slippage_bps_per_side),
                min_trades=max(int(args.min_trades), 1),
                include_trades=bool(args.include_trades),
            )
        )
        if idx % 25 == 0:
            print(json.dumps({"progress_models": idx, "latest_model": config.model_id}), flush=True)

    top = sorted(
        rows,
        key=lambda row: (
            _safe_float(dict(row.get("summary") or {}).get("score")),
            _safe_float(dict(row.get("summary") or {}).get("total_r")),
            _safe_float(dict(row.get("summary") or {}).get("ev_r")),
            -_safe_float(dict(row.get("summary") or {}).get("max_drawdown_r")),
        ),
        reverse=True,
    )[:30]
    decision_counts: dict[str, int] = {}
    for row in rows:
        decision = str(dict(row.get("summary") or {}).get("decision") or "unknown")
        decision_counts[decision] = decision_counts.get(decision, 0) + 1

    output: dict[str, Any] = {
        "schema_version": "intraday_compound_scalper_backtest_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "research_only_no_live_authority_change",
        "scope": {
            "symbols": symbols,
            "days": max(int(args.days), 1),
            "intervals": intervals,
            "model_count": len(rows),
            "min_trades": max(int(args.min_trades), 1),
        },
        "strategy_family": {
            "name": "intraday_compound_scalper",
            "timeframes": ["15m", "30m"],
            "direction": "long_short",
            "entry_timing": "completed_signal_bar_next_bar_open",
            "core_filters": [
                "fast EMA / slow EMA trend alignment",
                "slow EMA slope in trade direction",
                "breakout or pullback-reclaim trigger",
                "volume factor and candle body confirmation",
                "ATR and structure-aware stop-size bounds",
            ],
            "non_claims": [
                "does not change live allowlists",
                "does not bypass validation/report, operations/checklist, safety locks, liquidity, or reconciliation",
                "does not model queue priority, funding, partial fills, or stop gap slippage",
            ],
        },
        "cost_model": {
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": float(args.slippage_bps_per_side),
            "round_trip_cost_bps": 2.0 * (float(args.fee_bps_per_side) + float(args.slippage_bps_per_side)),
        },
        "data_status": data_status,
        "decision_counts": dict(sorted(decision_counts.items())),
        "top": top,
        "all_results": rows,
    }
    return output


def main() -> int:
    args = _parse_args()
    output = run_backtest(args)
    if args.write_report:
        report_dir = ROOT_DIR / str(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.fromisoformat(str(output["generated_at"])).strftime("%Y%m%dT%H%M%SZ")
        out_path = report_dir / f"intraday_compound_scalper_backtest_{stamp}.json"
        latest_path = report_dir / "latest.json"
        output["report_path"] = str(out_path.relative_to(ROOT_DIR))
        output["latest_report_path"] = str(latest_path.relative_to(ROOT_DIR))
        atomic_write_text(out_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(latest_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))
    print(json.dumps({key: value for key, value in output.items() if key != "all_results"}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
