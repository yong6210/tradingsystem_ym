#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import CURRENT_MICRO_LIVE_USDT_SYMBOLS, get_settings
from app.integrations.binance_futures import BinanceFuturesClient
from app.services.report_io import atomic_write_text
from scripts.run_micro_main_usdt_proxy_portfolio_yearly_replay import (
    PortfolioReplayTrade,
    _replay_window,
    _year_windows,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay a yearly USDT portfolio from a trade-including backtest report.")
    parser.add_argument("--backtest-path", required=True)
    parser.add_argument("--symbols", default=CURRENT_MICRO_LIVE_USDT_SYMBOLS)
    parser.add_argument("--days", type=int, default=1095)
    parser.add_argument("--account-equity-usdt", type=float, default=200.0)
    parser.add_argument("--risk-per-trade-pct", type=float, default=0.01)
    parser.add_argument("--usable-margin-fraction", type=float, default=0.85)
    parser.add_argument("--leverage-cap", type=float, default=10.0)
    parser.add_argument("--max-concurrent-positions", type=int, default=2)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if math.isfinite(parsed) else float(default)


def _parse_dt(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _load_trade_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for item in dict(payload.get("results") or {}).values():
        if not isinstance(item, dict):
            continue
        for row in list(item.get("trades") or []):
            if isinstance(row, dict):
                rows.append(row)
    if not rows:
        raise ValueError(f"Backtest report has no trade rows: {path}")
    return rows


def _symbol_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [_safe_float(row.get("r_value")) for row in rows]
    closed = len(values)
    total_r = sum(values)
    return {
        "closed": closed,
        "total_r": round(total_r, 4),
        "ev_r": round(total_r / max(closed, 1), 4),
        "win_rate": round(sum(1 for value in values if value > 0.0) / max(closed, 1), 4),
    }


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    generated_at = datetime.now(UTC)
    symbols = [item.strip().upper() for item in str(args.symbols or "").split(",") if item.strip()]
    symbol_set = set(symbols)
    end_ts = generated_at.replace(second=0, microsecond=0)
    windows = _year_windows(end_ts=end_ts, days=int(args.days))
    trades_by_window: dict[str, list[PortfolioReplayTrade]] = {label: [] for label, _, _ in windows}
    symbol_summaries: dict[str, dict[str, Any]] = {}

    path = Path(args.backtest_path).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    source_rows = [
        row
        for row in _load_trade_rows(path)
        if str(row.get("proxy_symbol") or row.get("symbol") or "").strip().upper() in symbol_set
    ]

    client = BinanceFuturesClient()
    symbol_rules: dict[str, dict[str, float]] = {}
    for symbol in symbols:
        rules = client.fetch_symbol_trading_rules(symbol)
        symbol_rules[symbol] = {
            "quantity_step": float(rules.quantity_step),
            "min_quantity": float(rules.min_quantity),
        }

    for symbol in symbols:
        symbol_rows = [
            row
            for row in source_rows
            if str(row.get("proxy_symbol") or row.get("symbol") or "").strip().upper() == symbol
        ]
        summary_by_window: dict[str, Any] = {}
        for label, window_start, window_end in windows:
            window_rows = [
                row
                for row in symbol_rows
                if window_start <= _parse_dt(row.get("entry_ts")) < window_end
            ]
            summary_by_window[label] = _symbol_summary(window_rows)
            for row in window_rows:
                trades_by_window[label].append(
                    PortfolioReplayTrade(
                        symbol=symbol,
                        proxy_symbol=symbol,
                        entry_ts=_parse_dt(row.get("entry_ts")),
                        exit_ts=_parse_dt(row.get("exit_ts")),
                        entry_price=_safe_float(row.get("entry_price")),
                        stop_price=_safe_float(row.get("stop_price")),
                        r_value=_safe_float(row.get("r_value")),
                    )
                )
        symbol_summaries[symbol] = summary_by_window

    horizons: dict[str, Any] = {}
    for label, window_start, window_end in windows:
        replay = _replay_window(
            trades=trades_by_window[label],
            symbol_rules=symbol_rules,
            account_equity_usdt=float(args.account_equity_usdt),
            risk_per_trade_pct=float(args.risk_per_trade_pct),
            usable_margin_fraction=float(args.usable_margin_fraction),
            leverage_cap=float(args.leverage_cap),
            max_concurrent_positions=int(args.max_concurrent_positions),
        )
        horizons[label] = {
            "window": {"start_ts": window_start.isoformat(), "end_ts": window_end.isoformat()},
            "1.0%": replay,
        }

    payload: dict[str, Any] = {
        "source": "micro_main_usdt_yearly_portfolio_replay",
        "quote_asset": "USDT",
        "generated_at": generated_at.isoformat(),
        "settings": {
            "symbols": symbols,
            "proxy_symbols": symbols,
            "source_backtest": str(path),
            "days": int(args.days),
            "account_equity_usdt": float(args.account_equity_usdt),
            "risk_per_trade_pct": float(args.risk_per_trade_pct),
            "usable_margin_fraction": float(args.usable_margin_fraction),
            "leverage_cap": float(args.leverage_cap),
            "max_concurrent_positions": int(args.max_concurrent_positions),
            "direct_usdt": True,
            "note": "yearly fixed-equity execution-faithful replay using direct USDT backtest trades and Binance symbol trading rules",
        },
        "horizons": horizons,
        "symbols": symbol_summaries,
    }
    if args.write_report:
        out_dir = Path(settings.validation_report_dir) / "micro_main_risk_sweeps"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"micro_main_usdt_yearly_portfolio_replay_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        payload["report_path"] = str(out_path)
        atomic_write_text(out_path, json.dumps(payload, ensure_ascii=False, indent=2))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
