#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import json
import math
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import CURRENT_MICRO_LIVE_USDT_SYMBOLS, get_settings
from app.db.models import Candle
from app.integrations.binance_futures import BinanceFuturesClient
from app.services.micro_main_strategy_research import MicroTrade, SessionImpulseRetestResearch
from app.services.report_io import atomic_write_text
from scripts.run_micro_main_usdt_proxy_backtest import (
    canonical_symbol_for_proxy,
    _fetch_1m_klines,
    _resample_to_5m,
    session_impulse_retest_profile_for_symbol,
)


@dataclass(slots=True)
class PortfolioReplayTrade:
    symbol: str
    proxy_symbol: str
    entry_ts: datetime
    exit_ts: datetime
    entry_price: float
    stop_price: float
    r_value: float


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay a yearly fixed-equity portfolio using USDT proxy or direct USDT micro-main trades."
    )
    parser.add_argument(
        "--symbols",
        default=CURRENT_MICRO_LIVE_USDT_SYMBOLS,
    )
    parser.add_argument("--days", type=int, default=1095)
    parser.add_argument("--account-equity-usdt", type=float, default=200.0)
    parser.add_argument("--risk-per-trade-pct", type=float, default=0.01)
    parser.add_argument("--usable-margin-fraction", type=float, default=0.85)
    parser.add_argument("--leverage-cap", type=float, default=10.0)
    parser.add_argument("--max-concurrent-positions", type=int, default=2)
    parser.add_argument("--direct-usdt", action="store_true")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _canonical_symbol_for_mode(proxy_symbol: str, *, direct_usdt: bool) -> str | None:
    normalized = str(proxy_symbol or "").strip().upper()
    if not normalized:
        return None
    if direct_usdt:
        return normalized
    return canonical_symbol_for_proxy(normalized)


def _round_down_to_step(value: float, *, step: float) -> float:
    if step <= 0.0:
        return max(value, 0.0)
    return math.floor(max(value, 0.0) / step + 1e-12) * step


def _build_candle_rows(candles: list[Any]) -> list[Candle]:
    rows: list[Candle] = []
    for candle in candles:
        rows.append(
            Candle(
                symbol="",
                timeframe="",
                ts=candle.ts,
                o=float(candle.o),
                h=float(candle.h),
                l=float(candle.l),
                c=float(candle.c),
                v=float(candle.v),
            )
        )
    return rows


def _year_windows(*, end_ts: datetime, days: int) -> list[tuple[str, datetime, datetime]]:
    end_ts = end_ts.astimezone(UTC).replace(second=0, microsecond=0)
    day_count = max(int(days), 1)
    if day_count < 365:
        start_ts = end_ts - timedelta(days=day_count)
        return [("full", start_ts, end_ts)]
    windows: list[tuple[str, datetime, datetime]] = []
    total_years = max(1, day_count // 365)
    start_ts = end_ts - timedelta(days=365 * total_years)
    for idx in range(total_years):
        window_start = start_ts + timedelta(days=365 * idx)
        window_end = start_ts + timedelta(days=365 * (idx + 1))
        windows.append((f"year_{idx + 1}", window_start, window_end))
    return windows


def _fetch_symbol_trades(
    monthly_client: httpx.Client,
    rest_client: httpx.Client,
    *,
    proxy_symbol: str,
    canonical_symbol: str,
    start_ts: datetime,
    end_ts: datetime,
) -> list[MicroTrade]:
    candles_1m = _fetch_1m_klines(
        monthly_client,
        rest_client,
        symbol=proxy_symbol,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    candles_5m = _resample_to_5m(candles_1m)
    rows_1m = _build_candle_rows(candles_1m)
    rows_5m = _build_candle_rows(candles_5m)
    engine = SessionImpulseRetestResearch(
        symbol=canonical_symbol,
        candles_1m=rows_1m,
        candles_5m=rows_5m,
        profile_name=session_impulse_retest_profile_for_symbol(canonical_symbol),
    )
    trades = engine.backtest()
    del candles_1m
    del candles_5m
    del rows_1m
    del rows_5m
    gc.collect()
    return trades


def _replay_window(
    *,
    trades: list[PortfolioReplayTrade],
    symbol_rules: dict[str, dict[str, float]],
    account_equity_usdt: float,
    risk_per_trade_pct: float,
    usable_margin_fraction: float,
    leverage_cap: float,
    max_concurrent_positions: int,
) -> dict[str, Any]:
    target_risk_usdt = account_equity_usdt * risk_per_trade_pct
    leverage_cap_notional = account_equity_usdt * usable_margin_fraction * leverage_cap

    active_positions: list[PortfolioReplayTrade] = []
    accepted: list[tuple[PortfolioReplayTrade, float]] = []
    skipped_trades_concurrent = 0
    rejected_trades_min_qty = 0
    capped_trades = 0
    actual_risk_total = 0.0

    sorted_trades = sorted(trades, key=lambda item: (item.entry_ts, item.exit_ts, item.symbol))
    for trade in sorted_trades:
        active_positions = [item for item in active_positions if item.exit_ts > trade.entry_ts]
        if len(active_positions) >= max_concurrent_positions:
            skipped_trades_concurrent += 1
            continue

        stop_pct = abs(float(trade.entry_price) - float(trade.stop_price)) / max(float(trade.entry_price), 1e-12)
        if stop_pct <= 0.0:
            continue
        target_notional = target_risk_usdt / stop_pct
        capped_notional = min(target_notional, leverage_cap_notional)
        rules = symbol_rules[trade.proxy_symbol]
        step = float(rules["quantity_step"])
        min_quantity = float(rules["min_quantity"])
        raw_qty = capped_notional / max(float(trade.entry_price), 1e-12)
        normalized_qty = _round_down_to_step(raw_qty, step=step)
        if normalized_qty + 1e-12 < min_quantity:
            rejected_trades_min_qty += 1
            continue

        actual_notional = normalized_qty * float(trade.entry_price)
        actual_risk_usdt = actual_notional * stop_pct
        if actual_notional + 1e-12 < target_notional:
            capped_trades += 1
        actual_risk_total += actual_risk_usdt
        accepted.append((trade, actual_risk_usdt))
        active_positions.append(trade)

    equity = account_equity_usdt
    peak_equity = equity
    max_drawdown_pct = 0.0
    for trade, actual_risk_usdt in sorted(accepted, key=lambda item: (item[0].exit_ts, item[0].entry_ts, item[0].symbol)):
        equity += actual_risk_usdt * float(trade.r_value)
        peak_equity = max(peak_equity, equity)
        if peak_equity > 0.0:
            drawdown_pct = max(0.0, (peak_equity - equity) / peak_equity * 100.0)
            max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

    accepted_trades = len(accepted)
    capped_ratio = float(capped_trades / accepted_trades) if accepted_trades > 0 else 0.0
    actual_vs_target_risk_ratio = float(actual_risk_total / (accepted_trades * target_risk_usdt)) if accepted_trades > 0 and target_risk_usdt > 0 else 0.0
    return {
        "accepted_trades": accepted_trades,
        "skipped_trades_concurrent": skipped_trades_concurrent,
        "rejected_trades_min_qty": rejected_trades_min_qty,
        "capped_trades": capped_trades,
        "capped_ratio": round(capped_ratio, 4),
        "ending_equity": round(equity, 2),
        "return_pct": round(((equity / account_equity_usdt) - 1.0) * 100.0, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "actual_vs_target_risk_ratio": round(actual_vs_target_risk_ratio, 4),
    }


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    generated_at = datetime.now(UTC)
    proxy_symbols = [item.strip().upper() for item in str(args.symbols or "").split(",") if item.strip()]
    end_ts = datetime.now(UTC).replace(second=0, microsecond=0)
    start_ts = end_ts - timedelta(days=max(int(args.days), 1))
    windows = _year_windows(end_ts=end_ts, days=int(args.days))

    trades_by_window: dict[str, list[PortfolioReplayTrade]] = {label: [] for label, _, _ in windows}
    symbol_summaries: dict[str, dict[str, Any]] = {}

    client = BinanceFuturesClient()
    symbol_rules: dict[str, dict[str, float]] = {}
    for proxy_symbol in proxy_symbols:
        rules = client.fetch_symbol_trading_rules(proxy_symbol)
        symbol_rules[proxy_symbol] = {
            "quantity_step": float(rules.quantity_step),
            "min_quantity": float(rules.min_quantity),
        }

    with (
        httpx.Client(timeout=120.0, follow_redirects=True) as monthly_client,
        httpx.Client(base_url=settings.binance_rest_base_url, timeout=30.0) as rest_client,
    ):
        for proxy_symbol in proxy_symbols:
            canonical_symbol = _canonical_symbol_for_mode(proxy_symbol, direct_usdt=bool(args.direct_usdt))
            if canonical_symbol is None:
                continue
            trades = _fetch_symbol_trades(
                monthly_client,
                rest_client,
                proxy_symbol=proxy_symbol,
                canonical_symbol=canonical_symbol,
                start_ts=start_ts,
                end_ts=end_ts,
            )
            summary_by_window: dict[str, Any] = {}
            for label, window_start, window_end in windows:
                window_trades = [
                    trade
                    for trade in trades
                    if window_start <= trade.entry_ts.astimezone(UTC) < window_end
                ]
                total_r = sum(float(item.r_value) for item in window_trades)
                closed = len(window_trades)
                summary_by_window[label] = {
                    "closed": closed,
                    "total_r": round(total_r, 4),
                    "ev_r": round(total_r / max(closed, 1), 4),
                    "win_rate": round(
                        sum(1 for item in window_trades if float(item.r_value) > 0.0) / max(closed, 1),
                        4,
                    ),
                }
                for trade in window_trades:
                    trades_by_window[label].append(
                        PortfolioReplayTrade(
                            symbol=canonical_symbol,
                            proxy_symbol=proxy_symbol,
                            entry_ts=trade.entry_ts.astimezone(UTC),
                            exit_ts=trade.exit_ts.astimezone(UTC),
                            entry_price=float(trade.entry_price),
                            stop_price=float(trade.stop_price),
                            r_value=float(trade.r_value),
                        )
                    )
            symbol_summaries[canonical_symbol] = summary_by_window
            print(
                json.dumps(
                    {
                        "progress": proxy_symbol,
                        "windows": {
                            label: summary_by_window[label]["closed"]
                            for label, _, _ in windows
                        },
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
                flush=True,
            )
            del trades
            gc.collect()

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
            "window": {
                "start_ts": window_start.isoformat(),
                "end_ts": window_end.isoformat(),
            },
            "1.0%": replay,
        }

    payload: dict[str, Any] = {
        "source": "micro_main_usdt_yearly_portfolio_replay"
        if args.direct_usdt
        else "micro_main_usdt_proxy_yearly_portfolio_replay",
        "quote_asset": "USDT" if args.direct_usdt else "USDC",
        "generated_at": generated_at.isoformat(),
        "settings": {
            "symbols": [_canonical_symbol_for_mode(item, direct_usdt=bool(args.direct_usdt)) or item for item in proxy_symbols],
            "proxy_symbols": proxy_symbols,
            "days": int(args.days),
            "account_equity_usdt": float(args.account_equity_usdt),
            "risk_per_trade_pct": float(args.risk_per_trade_pct),
            "usable_margin_fraction": float(args.usable_margin_fraction),
            "leverage_cap": float(args.leverage_cap),
            "max_concurrent_positions": int(args.max_concurrent_positions),
            "direct_usdt": bool(args.direct_usdt),
            "note": "yearly fixed-equity execution-faithful replay using direct USDT trades and Binance symbol trading rules"
            if args.direct_usdt
            else "yearly fixed-equity execution-faithful replay using USDT proxy trades and Binance symbol trading rules",
        },
        "horizons": horizons,
        "symbols": symbol_summaries,
    }

    if args.write_report:
        out_dir = Path(settings.validation_report_dir) / "micro_main_risk_sweeps"
        out_dir.mkdir(parents=True, exist_ok=True)
        report_prefix = (
            "micro_main_usdt_yearly_portfolio_replay"
            if args.direct_usdt
            else "micro_main_usdt_proxy_yearly_portfolio_replay"
        )
        out_path = out_dir / f"{report_prefix}_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        payload["report_path"] = str(out_path)
        atomic_write_text(out_path, json.dumps(payload, ensure_ascii=False, indent=2))

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
