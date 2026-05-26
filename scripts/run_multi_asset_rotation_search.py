#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from bisect import bisect_left
from collections import Counter, deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text
from scripts.run_btc_flip_rotation_search import Bar, _INTERVAL_MS, _csv, _load_bars


DEFAULT_SYMBOLS = (
    "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,"
    "LINKUSDT,AVAXUSDT,BCHUSDT,LTCUSDT,NEARUSDT"
)


@dataclass(frozen=True, slots=True)
class RotationPortfolioConfig:
    model_id: str
    interval: str
    mode: str
    lookback_hours: int
    lookback_bars: int
    top_k: int
    rebalance_hours: int
    rebalance_bars: int
    trend_hours: int
    trend_bars: int
    vol_weight: bool
    vol_hours: int
    vol_bars: int
    min_symbol_age_hours: int
    min_symbol_age_bars: int
    gross_leverage: float


@dataclass(slots=True)
class MarketFrame:
    interval: str
    symbols: list[str]
    open_ms: list[int]
    ts: list[datetime]
    opens: dict[str, list[float]]
    highs: dict[str, list[float]]
    lows: dict[str, list[float]]
    closes: dict[str, list[float]]
    volumes: dict[str, list[float]]
    returns: dict[str, list[float]]
    first_valid_index: dict[str, int]


@dataclass(slots=True)
class FeatureBundle:
    momentum: dict[int, dict[str, list[float]]]
    ema: dict[int, dict[str, list[float]]]
    vol: dict[int, dict[str, list[float]]]


@dataclass(frozen=True, slots=True)
class ExchangeRule:
    symbol: str
    min_qty: float
    step_size: float
    min_notional: float
    tick_size: float


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only multi-asset futures rotation search with post-cost portfolio accounting."
    )
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument("--days", type=int, default=1825)
    parser.add_argument("--intervals", default="4h")
    parser.add_argument("--align-mode", choices=("common", "dynamic"), default="common")
    parser.add_argument(
        "--modes",
        default="long_top,directional_ls,relative_ls,regime_switch,best_abs,tsmom_vol,cross_reversal",
    )
    parser.add_argument("--lookback-hours", default="24,72,168,336,720")
    parser.add_argument("--top-k", default="1,2,3")
    parser.add_argument("--rebalance-hours", default="4,12,24")
    parser.add_argument("--trend-hours", default="0,168,720")
    parser.add_argument("--vol-weight", default="false,true")
    parser.add_argument("--min-symbol-age-hours", default="0")
    parser.add_argument("--gross-leverage", default="1.0,1.5,2.0")
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument(
        "--holding-cost-bps-per-day",
        type=float,
        default=0.0,
        help="Conservative continuous drag applied to gross exposure, in bps per day.",
    )
    parser.add_argument(
        "--short-cost-bps-per-day",
        type=float,
        default=0.0,
        help="Conservative continuous drag applied to absolute short exposure, in bps per day.",
    )
    parser.add_argument(
        "--drawdown-guard-pct",
        type=float,
        default=0.0,
        help="Scale down target weights at rebalance when live equity drawdown is at least this percent.",
    )
    parser.add_argument(
        "--drawdown-risk-scale",
        type=float,
        default=1.0,
        help="Weight multiplier used when the drawdown guard is active.",
    )
    parser.add_argument(
        "--vol-target-annual-pct",
        type=float,
        default=0.0,
        help="Annualized realized-volatility target for the strategy return stream. Disabled at zero.",
    )
    parser.add_argument("--vol-lookback-hours", type=int, default=720)
    parser.add_argument("--vol-min-scale", type=float, default=0.0)
    parser.add_argument("--vol-max-scale", type=float, default=1.0)
    parser.add_argument(
        "--dispersion-lookback-rebalances",
        type=int,
        default=0,
        help="Number of prior rebalance dispersions used for a causal high-dispersion guard. Disabled at zero.",
    )
    parser.add_argument("--dispersion-guard-quantile", type=float, default=0.0)
    parser.add_argument("--dispersion-risk-scale", type=float, default=1.0)
    parser.add_argument(
        "--symbol-quality-lookback-hours",
        type=int,
        default=0,
        help="If positive, use trailing realized contribution per exposure to block weak symbols causally.",
    )
    parser.add_argument("--symbol-quality-drop-count", type=int, default=0)
    parser.add_argument("--symbol-quality-min-active-periods", type=int, default=30)
    parser.add_argument("--symbol-quality-min-abs-exposure", type=float, default=1.0)
    parser.add_argument("--symbol-quality-score-threshold", type=float, default=0.0)
    parser.add_argument("--apply-funding", action="store_true")
    parser.add_argument("--funding-cache-dir", default="reports/validation/multi_asset_rotation_search/funding_cache")
    parser.add_argument("--maintenance-margin-pct", type=float, default=0.0)
    parser.add_argument("--assumed-capital-usd", type=float, default=0.0)
    parser.add_argument(
        "--pnl-notional-mode",
        choices=(
            "compounded",
            "starting",
            "profit25",
            "profit50",
            "profit55",
            "profit60",
            "profit65",
            "profit70",
            "profit75",
            "profit80",
            "profit85",
            "profit90",
            "profit95",
        ),
        default="compounded",
        help="Position PnL basis. compounded reinvests the current equity; starting keeps notional anchored to initial capital.",
    )
    parser.add_argument(
        "--liquidity-notional-mode",
        choices=(
            "compounded",
            "starting",
            "profit25",
            "profit50",
            "profit55",
            "profit60",
            "profit65",
            "profit70",
            "profit75",
            "profit80",
            "profit85",
            "profit90",
            "profit95",
        ),
        default="compounded",
        help=(
            "Notional basis for liquidity impact/capacity math. compounded uses equity * assumed capital; "
            "starting keeps trade notional anchored to the starting assumed capital."
        ),
    )
    parser.add_argument("--liquidity-impact-bps-per-1pct-volume", type=float, default=0.0)
    parser.add_argument(
        "--max-symbol-weight",
        type=float,
        default=0.0,
        help="If positive, clip each symbol's absolute target weight after risk scaling.",
    )
    parser.add_argument("--max-trade-volume-pct", type=float, default=1.0)
    parser.add_argument(
        "--capacity-cap-trade-volume-pct",
        type=float,
        default=0.0,
        help="If positive, clip rebalance target deltas so each symbol trades at most this percent of quote volume.",
    )
    parser.add_argument("--apply-exchange-rules", action="store_true")
    parser.add_argument(
        "--exchange-rules-cache",
        default="reports/validation/multi_asset_rotation_search/exchange_rules_cache/exchange_info.json",
    )
    parser.add_argument("--min-common-days", type=int, default=1000)
    parser.add_argument("--max-models", type=int, default=0)
    parser.add_argument("--cache-dir", default="reports/validation/multi_asset_rotation_search/cache")
    parser.add_argument("--report-dir", default="reports/validation/multi_asset_rotation_search")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _parse_int_csv(raw: str, *, minimum: int = 0) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for item in _csv(raw):
        try:
            value = int(float(item))
        except ValueError:
            continue
        if value >= minimum and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _parse_float_csv(raw: str, *, minimum: float = 0.0) -> list[float]:
    out: list[float] = []
    seen: set[float] = set()
    for item in _csv(raw):
        try:
            value = float(item)
        except ValueError:
            continue
        if value >= minimum and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _parse_bool_csv(raw: str) -> list[bool]:
    out: list[bool] = []
    for item in _csv(raw):
        value = item.strip().lower() in {"1", "true", "t", "yes", "y"}
        if value not in out:
            out.append(value)
    return out or [False]


def _interval_hours(interval: str) -> float:
    return _INTERVAL_MS[interval] / (60 * 60 * 1000)


def _hours_to_bars(interval: str, hours: int) -> int:
    return max(int(math.ceil(max(int(hours), 0) / _interval_hours(interval))), 1)


def _ema(values: list[float], length: int) -> list[float]:
    if not values:
        return []
    length = max(int(length), 1)
    alpha = 2.0 / (length + 1.0)
    current = math.nan
    out: list[float] = []
    for value in values:
        if not math.isfinite(value):
            out.append(math.nan)
            continue
        if not math.isfinite(current):
            current = float(value)
        else:
            current = alpha * float(value) + (1.0 - alpha) * current
        out.append(current)
    return out


def _rolling_vol_from_returns(returns: list[float], length: int, output_len: int) -> list[float]:
    length = max(int(length), 2)
    out: list[float] = [math.nan] * output_len
    q: deque[float] = deque()
    total = 0.0
    total_sq = 0.0
    for idx in range(output_len):
        n = len(q)
        if n >= 2:
            mean = total / n
            variance = max(total_sq / n - mean * mean, 0.0)
            out[idx] = math.sqrt(variance)
        else:
            out[idx] = math.nan
        if idx < len(returns):
            value = float(returns[idx])
            if not math.isfinite(value):
                continue
            q.append(value)
            total += value
            total_sq += value * value
            if len(q) > length:
                old = q.popleft()
                total -= old
                total_sq -= old * old
    return out


def _align_frame(interval: str, bars_by_symbol: dict[str, list[Bar]]) -> tuple[MarketFrame | None, dict[str, Any]]:
    usable = {symbol: bars for symbol, bars in bars_by_symbol.items() if bars}
    if len(usable) < 2:
        return None, {"usable_symbols": sorted(usable), "error": "too_few_symbols"}

    open_sets = [set(bar.open_ms for bar in bars) for bars in usable.values()]
    common = sorted(set.intersection(*open_sets))
    if len(common) < 500:
        return None, {
            "usable_symbols": sorted(usable),
            "common_bars": len(common),
            "error": "too_few_common_bars",
        }

    maps = {
        symbol: {bar.open_ms: bar for bar in bars}
        for symbol, bars in usable.items()
    }
    first_symbol = next(iter(usable))
    first_map = maps[first_symbol]
    ts = [first_map[open_ms].ts for open_ms in common]
    opens: dict[str, list[float]] = {}
    highs: dict[str, list[float]] = {}
    lows: dict[str, list[float]] = {}
    closes: dict[str, list[float]] = {}
    volumes: dict[str, list[float]] = {}
    returns: dict[str, list[float]] = {}
    for symbol in sorted(usable):
        series = [maps[symbol][open_ms] for open_ms in common]
        symbol_opens = [float(bar.o) for bar in series]
        symbol_highs = [float(bar.h) for bar in series]
        symbol_lows = [float(bar.l) for bar in series]
        symbol_closes = [float(bar.c) for bar in series]
        symbol_volumes = [float(bar.v) for bar in series]
        opens[symbol] = symbol_opens
        highs[symbol] = symbol_highs
        lows[symbol] = symbol_lows
        closes[symbol] = symbol_closes
        volumes[symbol] = symbol_volumes
        returns[symbol] = [
            symbol_opens[idx + 1] / max(symbol_opens[idx], 1e-12) - 1.0
            for idx in range(len(symbol_opens) - 1)
        ]

    frame = MarketFrame(
        interval=interval,
        symbols=sorted(usable),
        open_ms=common,
        ts=ts,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        volumes=volumes,
        returns=returns,
        first_valid_index={symbol: 0 for symbol in sorted(usable)},
    )
    return frame, {
        "symbols": frame.symbols,
        "common_bars": len(common),
        "first_ts": ts[0].isoformat() if ts else None,
        "last_ts": ts[-1].isoformat() if ts else None,
        "common_days": round((ts[-1] - ts[0]).total_seconds() / 86_400, 2) if len(ts) >= 2 else 0.0,
    }


def _align_dynamic_frame(interval: str, bars_by_symbol: dict[str, list[Bar]]) -> tuple[MarketFrame | None, dict[str, Any]]:
    usable = {symbol: bars for symbol, bars in bars_by_symbol.items() if bars}
    if len(usable) < 2:
        return None, {"usable_symbols": sorted(usable), "error": "too_few_symbols"}

    open_ms_values = sorted({bar.open_ms for bars in usable.values() for bar in bars})
    if len(open_ms_values) < 500:
        return None, {
            "usable_symbols": sorted(usable),
            "dynamic_bars": len(open_ms_values),
            "error": "too_few_dynamic_bars",
        }

    maps = {symbol: {bar.open_ms: bar for bar in bars} for symbol, bars in usable.items()}
    ts = [datetime.fromtimestamp(open_ms / 1000, tz=UTC) for open_ms in open_ms_values]
    opens: dict[str, list[float]] = {}
    highs: dict[str, list[float]] = {}
    lows: dict[str, list[float]] = {}
    closes: dict[str, list[float]] = {}
    volumes: dict[str, list[float]] = {}
    returns: dict[str, list[float]] = {}
    per_symbol_status: dict[str, Any] = {}
    first_valid_index: dict[str, int] = {}
    for symbol in sorted(usable):
        symbol_opens: list[float] = []
        symbol_highs: list[float] = []
        symbol_lows: list[float] = []
        symbol_closes: list[float] = []
        symbol_volumes: list[float] = []
        symbol_map = maps[symbol]
        for open_ms in open_ms_values:
            bar = symbol_map.get(open_ms)
            if bar is None:
                symbol_opens.append(math.nan)
                symbol_highs.append(math.nan)
                symbol_lows.append(math.nan)
                symbol_closes.append(math.nan)
                symbol_volumes.append(math.nan)
            else:
                symbol_opens.append(float(bar.o))
                symbol_highs.append(float(bar.h))
                symbol_lows.append(float(bar.l))
                symbol_closes.append(float(bar.c))
                symbol_volumes.append(float(bar.v))
                first_valid_index.setdefault(symbol, len(symbol_opens) - 1)
        opens[symbol] = symbol_opens
        highs[symbol] = symbol_highs
        lows[symbol] = symbol_lows
        closes[symbol] = symbol_closes
        volumes[symbol] = symbol_volumes
        symbol_returns: list[float] = []
        for idx in range(len(symbol_opens) - 1):
            current_open = symbol_opens[idx]
            next_open = symbol_opens[idx + 1]
            if math.isfinite(current_open) and math.isfinite(next_open) and current_open > 0.0:
                symbol_returns.append(next_open / current_open - 1.0)
            else:
                symbol_returns.append(math.nan)
        returns[symbol] = symbol_returns
        first_bar = usable[symbol][0]
        last_bar = usable[symbol][-1]
        per_symbol_status[symbol] = {
            "bars": len(usable[symbol]),
            "first_ts": first_bar.ts.isoformat(),
            "last_ts": last_bar.ts.isoformat(),
        }

    active_counts = [
        sum(1 for symbol in usable if math.isfinite(closes[symbol][idx]))
        for idx in range(len(open_ms_values))
    ]
    frame = MarketFrame(
        interval=interval,
        symbols=sorted(usable),
        open_ms=open_ms_values,
        ts=ts,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        volumes=volumes,
        returns=returns,
        first_valid_index=first_valid_index,
    )
    return frame, {
        "symbols": frame.symbols,
        "dynamic_bars": len(open_ms_values),
        "first_ts": ts[0].isoformat() if ts else None,
        "last_ts": ts[-1].isoformat() if ts else None,
        "common_days": round((ts[-1] - ts[0]).total_seconds() / 86_400, 2) if len(ts) >= 2 else 0.0,
        "min_active_symbols": min(active_counts) if active_counts else 0,
        "max_active_symbols": max(active_counts) if active_counts else 0,
        "avg_active_symbols": round(sum(active_counts) / max(len(active_counts), 1), 2),
        "per_symbol_status": per_symbol_status,
    }


def _build_configs(args: argparse.Namespace, intervals: list[str]) -> list[RotationPortfolioConfig]:
    modes = [
        mode
        for mode in _csv(args.modes)
        if mode
        in {
            "long_top",
            "directional_ls",
            "relative_ls",
            "relative_ls_7030",
            "relative_ls_8020",
            "relative_ls_btc_gate",
            "relative_ls_btc_up",
            "relative_ls_btc_guard",
            "relative_ls_btc_cash",
            "liquid_long_top",
            "liquid_relative_ls",
            "liquid_highmom_long",
            "liquid_highmom_ls",
            "lowvol_long_top",
            "lowvol_btc_cash_long",
            "residual_lowvol_btc_cash_long_6535",
            "residual_lowvol_btc_cash_long_5050",
            "residual_lowvol_btc_cash_long_3565",
            "liquid_reversal_ls",
            "illiquid_reversal_ls",
            "illiquid_momentum_ls",
            "residual_long_top",
            "residual_ls",
            "channel_long_top",
            "channel_ls",
            "volume_factor_ls",
            "volume_vol_factor_ls",
            "btc_hedged_long_top",
            "btc_hedged_long_guard",
            "btc_hedged_channel",
            "regime_switch",
            "best_abs",
            "tsmom_vol",
            "cross_reversal",
            "pair_reversion",
            "sharpe_ls",
            "sharpe_ls_7030",
            "sharpe_ls_8020",
            "sharpe_directional_ls",
            "long_sharpe",
            "market_tsmom",
            "market_tsmom_flat",
            "basket_tsmom_equal",
            "basket_tsmom_vol",
            "basket_reversal_equal",
            "basket_reversal_vol",
            "funding_carry_equal",
            "funding_carry_vol",
            "funding_carry_top",
            "residual70_funding30",
            "residual70_funding30_btc_cash",
            "residual70_funding30_btc_cash_mktgt02",
            "residual70_funding30_btc_cash_mktgt05",
            "residual70_funding30_btc_cash_mktgt10",
            "residual70_funding30_btc_guard",
            "residual70_funding30_btc_cash_mix_k2k3_3070",
            "residual70_funding30_btc_cash_mix_k2k3_5050",
            "residual70_funding30_btc_cash_mix_k2k3_7030",
            "residual70_funding30_btc_guard_mix_k2k3_3070",
            "residual70_funding30_btc_guard_mix_k2k3_5050",
            "residual70_funding30_btc_guard_mix_k2k3_7030",
            "residual70_funding30_btc_cash_ls7030",
            "residual70_funding30_btc_cash_ls8020",
            "residual70_funding30_btc_guard_ls7030",
            "residual70_funding30_btc_guard_ls8020",
            "residual50_funding50_btc_cash",
            "residual50_funding50_btc_guard",
            "residual60_funding40_btc_cash",
            "residual75_funding25_btc_cash",
            "residual75_funding25_btc_cash_long",
            "residual75_funding25_btc_cash_ls6040",
            "residual75_funding25_btc_cash_ls7030",
            "residual75_funding25_btc_cash_ls8020",
            "residual80_funding20_btc_cash",
            "residual80_funding20_btc_short25",
            "residual80_funding20_btc_short50",
            "residual80_funding20_btc_short100",
            "residual80_funding20_btc_cash_mktgt02",
            "residual80_funding20_btc_cash_mktgt05",
            "residual80_funding20_btc_cash_mktgt10",
            "residual80_funding20_btc_cash_long",
            "residual80_funding20_btc_cash_mh168336720",
            "residual80_funding20_btc_cash_ls6040",
            "residual80_funding20_btc_cash_ls7030",
            "residual80_funding20_btc_cash_ls8020",
            "residual85_funding15_btc_cash",
            "residual85_funding15_btc_cash_mktgt02",
            "residual85_funding15_btc_cash_mktgt05",
            "residual85_funding15_btc_cash_mktgt10",
            "residual85_funding15_btc_cash_long",
            "residual85_funding15_btc_cash_ls6040",
            "residual85_funding15_btc_cash_ls7030",
            "residual85_funding15_btc_cash_ls8020",
            "residual90_funding10_btc_cash",
            "residual90_funding10_btc_cash_long",
            "residual90_funding10_btc_cash_ls6040",
            "residual90_funding10_btc_cash_ls7030",
            "residual90_funding10_btc_cash_ls8020",
            "residual95_funding05_btc_cash",
            "residual100_btc_cash",
            "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_bottom5_5050",
            "residual70_funding30_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
            "residual70_funding30_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
            "residual75_funding25_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
            "residual75_funding25_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
            "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
            "residual80_funding20_btc_cash_mktgt02_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
            "residual80_funding20_btc_cash_mktgt05_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
            "residual80_funding20_btc_cash_mktgt10_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
            "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_7525",
            "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
            "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_4060",
            "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_2575",
            "residual85_funding15_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
            "residual85_funding15_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
            "residual90_funding10_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
            "residual90_funding10_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
            "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_bottom5_7525",
            "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_bottom5_2575",
            "residual80_funding20_btc_short5_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
            "residual80_funding20_btc_short5_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
            "residual80_funding20_btc_short10_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
            "residual80_funding20_btc_short10_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
            "residual80_funding20_btc_short15_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
            "residual80_funding20_btc_short15_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
            "residual80_funding20_btc_short20_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
            "residual80_funding20_btc_short20_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
            "residual80_funding20_btc_short25_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
            "residual80_funding20_btc_short25_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
            "residual80_funding20_btc_short30_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
            "residual80_funding20_btc_short30_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
            "residual80_funding20_btc_short50_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
            "residual80_funding20_btc_short50_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
            "residual80_funding20_btc_short100_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
            "residual80_funding20_btc_short100_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
            "residual70_funding30_mix_k2k5_3070",
            "residual70_funding30_mix_k2k5_5050",
            "residual70_funding30_mix_k2k5_7030",
            "residual70_funding30_ls7030",
            "residual70_funding30_ls8020",
            "residual50_funding50",
        }
    ] or ["long_top", "regime_switch"]
    lookback_hours_values = _parse_int_csv(args.lookback_hours, minimum=1) or [72, 168, 336]
    top_k_values = _parse_int_csv(args.top_k, minimum=1) or [1, 2, 3]
    rebalance_hours_values = _parse_int_csv(args.rebalance_hours, minimum=1) or [12, 24]
    trend_hours_values = _parse_int_csv(args.trend_hours, minimum=0) or [0, 168]
    vol_weight_values = _parse_bool_csv(args.vol_weight)
    min_symbol_age_values = _parse_int_csv(args.min_symbol_age_hours, minimum=0) or [0]
    gross_values = _parse_float_csv(args.gross_leverage, minimum=0.01) or [1.0]

    configs: list[RotationPortfolioConfig] = []
    for interval in intervals:
        for mode in modes:
            for lookback_hours in lookback_hours_values:
                lookback_bars = _hours_to_bars(interval, lookback_hours)
                for top_k in top_k_values:
                    for rebalance_hours in rebalance_hours_values:
                        rebalance_bars = _hours_to_bars(interval, rebalance_hours)
                        for trend_hours in trend_hours_values:
                            trend_bars = 0 if trend_hours <= 0 else _hours_to_bars(interval, trend_hours)
                            for vol_weight in vol_weight_values:
                                vol_hours = max(168, lookback_hours)
                                vol_bars = _hours_to_bars(interval, vol_hours)
                                for min_symbol_age_hours in min_symbol_age_values:
                                    min_symbol_age_bars = (
                                        0
                                        if min_symbol_age_hours <= 0
                                        else _hours_to_bars(interval, min_symbol_age_hours)
                                    )
                                    for gross in gross_values:
                                        age_suffix = (
                                            ""
                                            if min_symbol_age_hours <= 0
                                            else f":age{min_symbol_age_hours}h"
                                        )
                                        model_id = (
                                            f"{interval}:{mode}:lb{lookback_hours}h:k{top_k}:"
                                            f"rb{rebalance_hours}h:trend{trend_hours}h:"
                                            f"volw{int(vol_weight)}{age_suffix}:gross{gross:g}"
                                        )
                                        configs.append(
                                            RotationPortfolioConfig(
                                                model_id=model_id,
                                                interval=interval,
                                                mode=mode,
                                                lookback_hours=lookback_hours,
                                                lookback_bars=lookback_bars,
                                                top_k=top_k,
                                                rebalance_hours=rebalance_hours,
                                                rebalance_bars=rebalance_bars,
                                                trend_hours=trend_hours,
                                                trend_bars=trend_bars,
                                                vol_weight=vol_weight,
                                                vol_hours=vol_hours,
                                                vol_bars=vol_bars,
                                                min_symbol_age_hours=min_symbol_age_hours,
                                                min_symbol_age_bars=min_symbol_age_bars,
                                                gross_leverage=float(gross),
                                            )
                                        )
    if int(args.max_models or 0) > 0:
        return configs[: int(args.max_models)]
    return configs


def _build_features(frame: MarketFrame, configs: list[RotationPortfolioConfig]) -> FeatureBundle:
    lookbacks = sorted({config.lookback_bars for config in configs if config.interval == frame.interval})
    for config in configs:
        if config.interval != frame.interval:
            continue
        for hours in _multi_horizon_hours_from_mode(config.mode):
            bars = _hours_to_bars(config.interval, hours)
            if bars not in lookbacks:
                lookbacks.append(bars)
    lookbacks = sorted(lookbacks)
    trend_lengths = sorted({config.trend_bars for config in configs if config.interval == frame.interval and config.trend_bars > 0})
    for config in configs:
        if config.interval != frame.interval:
            continue
        pair = _btc_ema_pair_from_mode(config.mode)
        if pair:
            for length in pair:
                if length not in trend_lengths:
                    trend_lengths.append(length)
    trend_lengths = sorted(trend_lengths)
    vol_lengths = sorted({config.vol_bars for config in configs if config.interval == frame.interval})

    momentum: dict[int, dict[str, list[float]]] = {}
    for lookback in lookbacks:
        by_symbol: dict[str, list[float]] = {}
        for symbol in frame.symbols:
            closes = frame.closes[symbol]
            out = [math.nan] * len(closes)
            for idx in range(lookback, len(closes)):
                base = closes[idx - lookback]
                close = closes[idx]
                if math.isfinite(close) and math.isfinite(base) and base > 0.0:
                    out[idx] = close / base - 1.0
            by_symbol[symbol] = out
        momentum[lookback] = by_symbol

    ema: dict[int, dict[str, list[float]]] = {}
    for length in trend_lengths:
        ema[length] = {symbol: _ema(frame.closes[symbol], length) for symbol in frame.symbols}

    vol: dict[int, dict[str, list[float]]] = {}
    for length in vol_lengths:
        vol[length] = {
            symbol: _rolling_vol_from_returns(frame.returns[symbol], length, len(frame.ts))
            for symbol in frame.symbols
        }

    return FeatureBundle(momentum=momentum, ema=ema, vol=vol)


def _multi_horizon_hours_from_mode(mode: str) -> list[int]:
    marker = "_mh"
    if marker not in mode:
        return []
    suffix = mode.rsplit(marker, 1)[-1]
    digits: list[str] = []
    for ch in suffix:
        if not ch.isdigit():
            break
        digits.append(ch)
    raw = "".join(digits)
    if not raw.isdigit() or len(raw) % 3 != 0:
        return []
    horizons: list[int] = []
    for idx in range(0, len(raw), 3):
        value = int(raw[idx : idx + 3])
        if value > 0 and value not in horizons:
            horizons.append(value)
    return horizons


def _short_btc_fraction_from_mode(mode: str) -> float:
    marker = "_btc_short"
    start = mode.find(marker)
    if start >= 0:
        start += len(marker)
        end = start
        while end < len(mode) and (mode[end].isdigit() or mode[end] in {".", "p"}):
            end += 1
        if end > start:
            return max(float(mode[start:end].replace("p", ".")) / 100.0, 0.0)
    return 0.0


def _residual_fraction_from_mode(mode: str) -> float:
    if mode.startswith("residual50_funding50"):
        return 0.50
    if mode.startswith("residual60_funding40"):
        return 0.60
    if mode.startswith("residual70_funding30"):
        return 0.70
    if mode.startswith("residual75_funding25"):
        return 0.75
    if mode.startswith("residual80_funding20"):
        return 0.80
    if mode.startswith("residual85_funding15"):
        return 0.85
    if mode.startswith("residual90_funding10"):
        return 0.90
    if mode.startswith("residual95_funding05"):
        return 0.95
    if mode.startswith("residual100"):
        return 1.0
    return 0.70


def _market_threshold_from_mode(mode: str) -> float:
    if "_mktgt02" in mode:
        return 0.02
    if "_mktgt05" in mode:
        return 0.05
    if "_mktgt10" in mode:
        return 0.10
    return 0.0


def _breadth_threshold_from_mode(mode: str) -> float:
    marker = "_breadthgt"
    if marker not in mode:
        return math.nan
    start = mode.find(marker) + len(marker)
    end = start
    while end < len(mode) and (mode[end].isdigit() or mode[end] in {".", "p"}):
        end += 1
    try:
        return max(min(float(mode[start:end].replace("p", ".")) / 100.0, 1.0), 0.0)
    except ValueError:
        return math.nan


def _cooldown_momentum_threshold_from_mode(mode: str) -> float:
    marker = "_cool"
    if marker not in mode:
        return math.nan
    start = mode.find(marker) + len(marker)
    end = start
    while end < len(mode) and (mode[end].isdigit() or mode[end] in {".", "p"}):
        end += 1
    try:
        return max(float(mode[start:end].replace("p", ".")) / 100.0, 0.0)
    except ValueError:
        return math.nan


def _long_fraction_from_mode(mode: str, default: float = 0.50) -> float:
    marker = "_ls"
    if marker not in mode:
        return default
    raw = mode.rsplit(marker, 1)[-1][:4]
    if len(raw) != 4 or not raw.isdigit():
        return default
    long_part = int(raw[:2])
    short_part = int(raw[2:])
    total = long_part + short_part
    if total <= 0:
        return default
    return min(max(long_part / total, 0.0), 1.0)


def _bear_long_fraction_from_mode(mode: str, default: float = 0.50) -> float:
    marker = "_bear"
    if marker not in mode:
        return default
    raw = mode.rsplit(marker, 1)[-1][:4]
    if len(raw) != 4 or not raw.isdigit():
        return default
    long_part = int(raw[:2])
    short_part = int(raw[2:])
    total = long_part + short_part
    if total <= 0:
        return default
    return min(max(long_part / total, 0.0), 1.0)


def _bull_threshold_from_mode(mode: str) -> float:
    marker = "_bullgt"
    if marker not in mode:
        return 0.0
    start = mode.find(marker) + len(marker)
    end = start
    while end < len(mode) and (mode[end].isdigit() or mode[end] in {".", "p"}):
        end += 1
    try:
        return max(float(mode[start:end].replace("p", ".")) / 100.0, 0.0)
    except ValueError:
        return 0.0


def _btc_ema_pair_from_mode(mode: str) -> tuple[int, int] | None:
    marker = "_btcema"
    if marker not in mode:
        return None
    raw = mode.rsplit(marker, 1)[-1]
    token = []
    for ch in raw:
        if ch.isdigit() or ch.lower() == "x":
            token.append(ch.lower())
        else:
            break
    text = "".join(token)
    if "x" not in text:
        return None
    fast_raw, slow_raw = text.split("x", 1)
    try:
        fast = int(fast_raw)
        slow = int(slow_raw)
    except ValueError:
        return None
    if fast <= 0 or slow <= 0 or fast >= slow:
        return None
    return fast, slow


def _regime_long_fraction_from_mode(mode: str, market_momentum: float, default: float = 0.50) -> float:
    has_bull = "_bull6040" in mode or "_bull5545" in mode
    if not has_bull and "_bear" not in mode:
        return _long_fraction_from_mode(mode, default)
    base_long_fraction = _long_fraction_from_mode(mode, default)
    if not math.isfinite(market_momentum) or market_momentum < _bull_threshold_from_mode(mode):
        return _bear_long_fraction_from_mode(mode, default)
    if "_bull6040" in mode:
        return 0.60
    if "_bull5545" in mode:
        return 0.55
    return base_long_fraction


def _weighted_assign(
    weights: dict[str, float],
    selected: list[tuple[str, float, float]],
    *,
    side: int,
    gross: float,
    vol_weight: bool,
) -> None:
    if not selected or gross <= 0.0:
        return
    if vol_weight:
        raw = [
            (symbol, min(1.0 / max(vol, 1e-5), 100_000.0))
            for symbol, _, vol in selected
            if math.isfinite(vol) and vol > 0.0
        ]
    else:
        raw = [(symbol, 1.0) for symbol, _, _ in selected]
    total = sum(value for _, value in raw)
    if total <= 0.0:
        return
    for symbol, value in raw:
        weights[symbol] = weights.get(symbol, 0.0) + side * gross * value / total


def _mean(values: list[float]) -> float:
    if not values:
        return math.nan
    return sum(values) / len(values)


def _std(values: list[float], mean: float) -> float:
    if not values or not math.isfinite(mean):
        return math.nan
    variance = sum((value - mean) * (value - mean) for value in values) / len(values)
    return math.sqrt(max(variance, 0.0))


def _corr(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 10:
        return math.nan
    mean_x = _mean(xs)
    mean_y = _mean(ys)
    if not (math.isfinite(mean_x) and math.isfinite(mean_y)):
        return math.nan
    cov = 0.0
    var_x = 0.0
    var_y = 0.0
    for x_value, y_value in zip(xs, ys, strict=True):
        dx = x_value - mean_x
        dy = y_value - mean_y
        cov += dx * dy
        var_x += dx * dx
        var_y += dy * dy
    denom = math.sqrt(max(var_x, 0.0) * max(var_y, 0.0))
    if denom <= 1e-12:
        return math.nan
    return cov / denom


def _avg_quote_volume(frame: MarketFrame, symbol: str, signal_idx: int, bars: int) -> float:
    start_idx = max(signal_idx - max(int(bars), 1) + 1, 0)
    values: list[float] = []
    for idx in range(start_idx, signal_idx + 1):
        close = frame.closes[symbol][idx]
        volume = frame.volumes[symbol][idx]
        if math.isfinite(close) and math.isfinite(volume) and close > 0.0 and volume >= 0.0:
            values.append(close * volume)
    return _mean(values)


def _quote_volume_std(frame: MarketFrame, symbol: str, signal_idx: int, bars: int) -> float:
    start_idx = max(signal_idx - max(int(bars), 1) + 1, 0)
    values: list[float] = []
    for idx in range(start_idx, signal_idx + 1):
        close = frame.closes[symbol][idx]
        volume = frame.volumes[symbol][idx]
        if math.isfinite(close) and math.isfinite(volume) and close > 0.0 and volume >= 0.0:
            values.append(close * volume)
    if len(values) < 2:
        return math.nan
    return _std(values, _mean(values))


def _high_momentum_score(frame: MarketFrame, symbol: str, config: RotationPortfolioConfig, signal_idx: int) -> float:
    start_idx = signal_idx - config.lookback_bars + 1
    if start_idx < 0:
        return math.nan
    highs = [
        value
        for value in frame.highs[symbol][start_idx : signal_idx + 1]
        if math.isfinite(value) and value > 0.0
    ]
    close = frame.closes[symbol][signal_idx]
    if not highs or not math.isfinite(close) or close <= 0.0:
        return math.nan
    rolling_high = max(highs)
    if rolling_high <= 0.0:
        return math.nan
    return close / rolling_high - 1.0


def _channel_position_score(frame: MarketFrame, symbol: str, config: RotationPortfolioConfig, signal_idx: int) -> float:
    start_idx = signal_idx - config.lookback_bars + 1
    if start_idx < 0:
        return math.nan
    highs = [
        value
        for value in frame.highs[symbol][start_idx : signal_idx + 1]
        if math.isfinite(value) and value > 0.0
    ]
    lows = [
        value
        for value in frame.lows[symbol][start_idx : signal_idx + 1]
        if math.isfinite(value) and value > 0.0
    ]
    close = frame.closes[symbol][signal_idx]
    if not highs or not lows or not math.isfinite(close) or close <= 0.0:
        return math.nan
    rolling_high = max(highs)
    rolling_low = min(lows)
    span = rolling_high - rolling_low
    if span <= 1e-12:
        return math.nan
    return (close - rolling_low) / span


def _residual_momentum_score(
    frame: MarketFrame,
    symbol: str,
    market_symbol: str,
    config: RotationPortfolioConfig,
    signal_idx: int,
    momentum: float,
    market_momentum: float,
) -> float:
    start_idx = max(signal_idx - config.lookback_bars, 0)
    end_idx = min(signal_idx, len(frame.returns.get(symbol, [])) - 1)
    if end_idx - start_idx < 10:
        return math.nan
    symbol_returns: list[float] = []
    market_returns: list[float] = []
    for idx in range(start_idx, end_idx + 1):
        symbol_return = frame.returns[symbol][idx]
        market_return = frame.returns[market_symbol][idx]
        if math.isfinite(symbol_return) and math.isfinite(market_return):
            symbol_returns.append(symbol_return)
            market_returns.append(market_return)
    if len(symbol_returns) < 10:
        return math.nan
    market_mean = _mean(market_returns)
    symbol_mean = _mean(symbol_returns)
    market_var = sum((value - market_mean) * (value - market_mean) for value in market_returns)
    if market_var <= 1e-12:
        return math.nan
    cov = sum(
        (symbol_value - symbol_mean) * (market_value - market_mean)
        for symbol_value, market_value in zip(symbol_returns, market_returns, strict=True)
    )
    beta = cov / market_var
    if not (math.isfinite(beta) and math.isfinite(momentum) and math.isfinite(market_momentum)):
        return math.nan
    return momentum - beta * market_momentum


def _pair_reversion_weights(
    frame: MarketFrame,
    config: RotationPortfolioConfig,
    signal_idx: int,
    eligible_symbols: list[str],
) -> dict[str, float]:
    weights: dict[str, float] = {}
    gross = max(float(config.gross_leverage), 0.0)
    if gross <= 0.0 or len(eligible_symbols) < 2:
        return weights

    start_idx = signal_idx - config.lookback_bars + 1
    if start_idx < 0:
        return weights

    close_logs: dict[str, list[float]] = {}
    return_windows: dict[str, list[float]] = {}
    for symbol in eligible_symbols:
        closes = frame.closes[symbol][start_idx : signal_idx + 1]
        if len(closes) != config.lookback_bars or any(not math.isfinite(value) or value <= 0.0 for value in closes):
            continue
        close_logs[symbol] = [math.log(value) for value in closes]
        symbol_returns = [
            closes[idx + 1] / max(closes[idx], 1e-12) - 1.0
            for idx in range(len(closes) - 1)
        ]
        if all(math.isfinite(value) for value in symbol_returns):
            return_windows[symbol] = symbol_returns

    symbols = sorted(set(close_logs) & set(return_windows))
    if len(symbols) < 2:
        return weights

    candidates: list[tuple[float, str, str, float, float, float]] = []
    for left_idx, left in enumerate(symbols):
        left_logs = close_logs[left]
        left_returns = return_windows[left]
        for right in symbols[left_idx + 1 :]:
            right_logs = close_logs[right]
            right_returns = return_windows[right]
            corr = _corr(left_returns, right_returns)
            if not math.isfinite(corr) or corr < 0.60:
                continue
            mean_right = _mean(right_logs)
            mean_left = _mean(left_logs)
            var_right = sum((value - mean_right) * (value - mean_right) for value in right_logs)
            if var_right <= 1e-12:
                continue
            cov = sum(
                (right_value - mean_right) * (left_value - mean_left)
                for left_value, right_value in zip(left_logs, right_logs, strict=True)
            )
            beta = cov / var_right
            if not math.isfinite(beta) or beta <= 0.20 or beta >= 5.00:
                continue
            spread = [
                left_value - beta * right_value
                for left_value, right_value in zip(left_logs, right_logs, strict=True)
            ]
            spread_mean = _mean(spread)
            spread_std = _std(spread, spread_mean)
            if not math.isfinite(spread_std) or spread_std <= 1e-5:
                continue
            zscore = (spread[-1] - spread_mean) / spread_std
            if not math.isfinite(zscore) or abs(zscore) < 1.50:
                continue
            candidates.append((abs(zscore), left, right, zscore, beta, corr))

    selected: list[tuple[float, str, str, float, float, float]] = []
    used_symbols: set[str] = set()
    for candidate in sorted(candidates, reverse=True):
        _, left, right, _, _, _ = candidate
        if left in used_symbols or right in used_symbols:
            continue
        selected.append(candidate)
        used_symbols.add(left)
        used_symbols.add(right)
        if len(selected) >= max(int(config.top_k), 1):
            break

    if not selected:
        return weights

    pair_gross = gross / len(selected)
    for _, left, right, zscore, beta, _ in selected:
        if zscore > 0.0:
            left_raw = -1.0
            right_raw = beta
        else:
            left_raw = 1.0
            right_raw = -beta
        normalizer = abs(left_raw) + abs(right_raw)
        if normalizer <= 1e-12:
            continue
        weights[left] = weights.get(left, 0.0) + pair_gross * left_raw / normalizer
        weights[right] = weights.get(right, 0.0) + pair_gross * right_raw / normalizer
    return weights


def _target_weights(
    frame: MarketFrame,
    features: FeatureBundle,
    config: RotationPortfolioConfig,
    signal_idx: int,
    funding_period_rates: dict[str, list[float]] | None = None,
    blocked_symbols: set[str] | None = None,
) -> dict[str, float]:
    mom_by_symbol = features.momentum[config.lookback_bars]
    vol_by_symbol = features.vol[config.vol_bars]
    ema_by_symbol = features.ema.get(config.trend_bars, {})
    market_symbol = "BTCUSDT" if "BTCUSDT" in frame.symbols else frame.symbols[0]
    rows: list[tuple[str, float, float, bool, bool]] = []
    for symbol in frame.symbols:
        first_valid = frame.first_valid_index.get(symbol)
        if first_valid is None or signal_idx - first_valid < config.min_symbol_age_bars:
            continue
        momentum = mom_by_symbol[symbol][signal_idx]
        close = frame.closes[symbol][signal_idx]
        vol = vol_by_symbol[symbol][signal_idx]
        if not (math.isfinite(momentum) and math.isfinite(close) and math.isfinite(vol)):
            continue
        if config.trend_bars > 0:
            trend = ema_by_symbol[symbol][signal_idx]
            if not math.isfinite(trend):
                continue
            trend_up = close > trend
            trend_down = close < trend
        else:
            trend_up = True
            trend_down = True
        rows.append((symbol, momentum, max(vol, 1e-5), trend_up, trend_down))

    if blocked_symbols:
        blocked = {symbol for symbol in blocked_symbols if symbol != market_symbol}
        if blocked:
            rows = [row for row in rows if row[0] not in blocked]

    if (config.mode.startswith("liquid_") or config.mode.startswith("illiquid_")) and rows:
        liquidity_values = [
            (symbol, _avg_quote_volume(frame, symbol, signal_idx, config.lookback_bars))
            for symbol, _, _, _, _ in rows
        ]
        ranked_liquidity = sorted(
            ((symbol, value) for symbol, value in liquidity_values if math.isfinite(value)),
            key=lambda item: item[1],
            reverse=True,
        )
        select_count = max(len(rows) // 2, min(len(rows), 2))
        if config.mode.startswith("illiquid_"):
            selected_symbols = {symbol for symbol, _ in ranked_liquidity[-select_count:]}
        else:
            selected_symbols = {symbol for symbol, _ in ranked_liquidity[:select_count]}
        rows = [row for row in rows if row[0] in selected_symbols]

    market_momentum = mom_by_symbol[market_symbol][signal_idx] if market_symbol in mom_by_symbol else math.nan
    btc_ema_pair = _btc_ema_pair_from_mode(config.mode)
    if btc_ema_pair and market_symbol in frame.closes:
        fast_len, slow_len = btc_ema_pair
        fast_series = features.ema.get(fast_len, {}).get(market_symbol, [])
        slow_series = features.ema.get(slow_len, {}).get(market_symbol, [])
        if signal_idx < len(fast_series) and signal_idx < len(slow_series):
            fast_value = fast_series[signal_idx]
            slow_value = slow_series[signal_idx]
            if math.isfinite(fast_value) and math.isfinite(slow_value) and slow_value > 0.0:
                market_momentum = fast_value / slow_value - 1.0

    if config.mode in {
        "sharpe_ls",
        "sharpe_ls_7030",
        "sharpe_ls_8020",
        "sharpe_directional_ls",
        "long_sharpe",
    }:
        rank_rows = [
            (symbol, momentum / max(vol, 1e-5), vol, up, down)
            for symbol, momentum, vol, up, down in rows
        ]
    elif config.mode in {"liquid_highmom_long", "liquid_highmom_ls"}:
        rank_rows = [
            (symbol, score, vol, up, down)
            for symbol, _, vol, up, down in rows
            if math.isfinite((score := _high_momentum_score(frame, symbol, config, signal_idx)))
        ]
    elif config.mode in {"channel_long_top", "channel_ls", "btc_hedged_channel"}:
        rank_rows = [
            (symbol, score, vol, up, down)
            for symbol, _, vol, up, down in rows
            if math.isfinite((score := _channel_position_score(frame, symbol, config, signal_idx)))
        ]
    elif config.mode == "volume_factor_ls":
        rank_rows = [
            (symbol, -score, vol, up, down)
            for symbol, _, vol, up, down in rows
            if math.isfinite((score := _avg_quote_volume(frame, symbol, signal_idx, config.lookback_bars)))
        ]
    elif config.mode == "volume_vol_factor_ls":
        rank_rows = [
            (symbol, -score, vol, up, down)
            for symbol, _, vol, up, down in rows
            if math.isfinite((score := _quote_volume_std(frame, symbol, signal_idx, config.lookback_bars)))
        ]
    elif (
        config.mode.startswith("residual80_funding20_btc_short") and "_blend_" in config.mode
    ) or config.mode in {
        "residual_long_top",
        "residual_ls",
        "residual_lowvol_btc_cash_long_6535",
        "residual_lowvol_btc_cash_long_5050",
        "residual_lowvol_btc_cash_long_3565",
        "residual70_funding30",
        "residual70_funding30_btc_cash",
        "residual70_funding30_btc_cash_mktgt02",
        "residual70_funding30_btc_cash_mktgt05",
        "residual70_funding30_btc_cash_mktgt10",
        "residual70_funding30_btc_guard",
        "residual70_funding30_btc_cash_mix_k2k3_3070",
        "residual70_funding30_btc_cash_mix_k2k3_5050",
        "residual70_funding30_btc_cash_mix_k2k3_7030",
        "residual70_funding30_btc_guard_mix_k2k3_3070",
        "residual70_funding30_btc_guard_mix_k2k3_5050",
        "residual70_funding30_btc_guard_mix_k2k3_7030",
        "residual70_funding30_btc_cash_ls7030",
        "residual70_funding30_btc_cash_ls8020",
        "residual70_funding30_btc_guard_ls7030",
        "residual70_funding30_btc_guard_ls8020",
        "residual50_funding50_btc_cash",
        "residual50_funding50_btc_guard",
        "residual60_funding40_btc_cash",
        "residual75_funding25_btc_cash",
        "residual75_funding25_btc_cash_long",
        "residual75_funding25_btc_cash_ls6040",
        "residual75_funding25_btc_cash_ls7030",
        "residual75_funding25_btc_cash_ls8020",
        "residual80_funding20_btc_cash",
        "residual80_funding20_btc_short25",
        "residual80_funding20_btc_short50",
        "residual80_funding20_btc_short100",
        "residual80_funding20_btc_cash_mktgt02",
        "residual80_funding20_btc_cash_mktgt05",
        "residual80_funding20_btc_cash_mktgt10",
        "residual80_funding20_btc_cash_long",
        "residual80_funding20_btc_cash_mh168336720",
        "residual80_funding20_btc_cash_ls6040",
        "residual80_funding20_btc_cash_ls7030",
        "residual80_funding20_btc_cash_ls8020",
        "residual85_funding15_btc_cash",
        "residual85_funding15_btc_cash_mktgt02",
        "residual85_funding15_btc_cash_mktgt05",
        "residual85_funding15_btc_cash_mktgt10",
        "residual85_funding15_btc_cash_long",
        "residual85_funding15_btc_cash_ls6040",
        "residual85_funding15_btc_cash_ls7030",
        "residual85_funding15_btc_cash_ls8020",
        "residual90_funding10_btc_cash",
        "residual90_funding10_btc_cash_long",
        "residual90_funding10_btc_cash_ls6040",
        "residual90_funding10_btc_cash_ls7030",
        "residual90_funding10_btc_cash_ls8020",
        "residual95_funding05_btc_cash",
        "residual100_btc_cash",
        "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_bottom5_5050",
        "residual70_funding30_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual70_funding30_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual75_funding25_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual75_funding25_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_cash_mktgt02_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_cash_mktgt05_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_cash_mktgt10_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_7525",
        "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_4060",
        "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_2575",
        "residual85_funding15_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual85_funding15_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual90_funding10_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual90_funding10_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_bottom5_7525",
        "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_bottom5_2575",
        "residual80_funding20_btc_short5_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_short5_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual80_funding20_btc_short10_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_short10_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual80_funding20_btc_short15_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_short15_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual80_funding20_btc_short20_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_short20_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual80_funding20_btc_short25_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_short25_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual80_funding20_btc_short30_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_short30_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual80_funding20_btc_short50_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_short50_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual80_funding20_btc_short100_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_short100_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual70_funding30_mix_k2k5_3070",
        "residual70_funding30_mix_k2k5_5050",
        "residual70_funding30_mix_k2k5_7030",
        "residual70_funding30_ls7030",
        "residual70_funding30_ls8020",
        "residual50_funding50",
    }:
        multi_horizon_hours = _multi_horizon_hours_from_mode(config.mode)
        if multi_horizon_hours:
            horizon_bars = [_hours_to_bars(config.interval, hours) for hours in multi_horizon_hours]
            rank_rows = []
            for symbol, _, vol, up, down in rows:
                scores: list[float] = []
                for bars in horizon_bars:
                    horizon_momentum = features.momentum.get(bars, {}).get(symbol, [])
                    horizon_market = features.momentum.get(bars, {}).get(market_symbol, [])
                    if signal_idx >= len(horizon_momentum) or signal_idx >= len(horizon_market):
                        scores = []
                        break
                    score = _residual_momentum_score(
                        frame,
                        symbol,
                        market_symbol,
                        config,
                        signal_idx,
                        horizon_momentum[signal_idx],
                        horizon_market[signal_idx],
                    )
                    if not math.isfinite(score):
                        scores = []
                        break
                    scores.append(score)
                if scores:
                    rank_rows.append((symbol, sum(scores) / len(scores), vol, up, down))
        else:
            rank_rows = [
                (symbol, score, vol, up, down)
                for symbol, momentum, vol, up, down in rows
                if math.isfinite(
                    (
                        score := _residual_momentum_score(
                            frame,
                            symbol,
                            market_symbol,
                            config,
                            signal_idx,
                            momentum,
                            market_momentum,
                        )
                    )
                )
            ]
    else:
        rank_rows = rows

    desc = sorted(rank_rows, key=lambda row: row[1], reverse=True)
    asc = sorted(rank_rows, key=lambda row: row[1])
    weights: dict[str, float] = {}
    gross = max(float(config.gross_leverage), 0.0)
    k = max(int(config.top_k), 1)

    def residual_funding_weights(
        *,
        component_k: int,
        component_gross: float,
        residual_fraction: float = 0.70,
        long_fraction: float = 0.50,
        exclude_symbols: set[str] | None = None,
    ) -> dict[str, float]:
        component_weights: dict[str, float] = {}
        component_k = max(int(component_k), 1)
        excluded = {symbol for symbol in (exclude_symbols or set()) if symbol != market_symbol}
        component_desc = [row for row in desc if row[0] not in excluded]
        component_asc = [row for row in asc if row[0] not in excluded]
        component_rows = [row for row in rows if row[0] not in excluded]
        longs = [(symbol, score, vol) for symbol, score, vol, up, _ in component_desc if up][:component_k]
        long_symbols = {symbol for symbol, _, _ in longs}
        shorts = [
            (symbol, score, vol)
            for symbol, score, vol, _, down in component_asc
            if down and symbol not in long_symbols
        ][:component_k]
        _weighted_assign(
            component_weights,
            longs,
            side=1,
            gross=component_gross * residual_fraction * long_fraction,
            vol_weight=config.vol_weight,
        )
        _weighted_assign(
            component_weights,
            shorts,
            side=-1,
            gross=component_gross * residual_fraction * (1.0 - long_fraction),
            vol_weight=config.vol_weight,
        )
        carry_fraction = 1.0 - residual_fraction
        if funding_period_rates and carry_fraction > 0.0:
            start_idx = max(0, signal_idx - config.lookback_bars + 1)
            carry_candidates: list[tuple[str, float, float]] = []
            for symbol, _, vol, up, down in component_rows:
                rates = funding_period_rates.get(symbol)
                if not rates:
                    continue
                carry_score = sum(rates[start_idx : signal_idx + 1])
                if not math.isfinite(carry_score) or abs(carry_score) <= 1e-12:
                    continue
                side = -1.0 if carry_score > 0.0 else 1.0
                if side > 0.0 and not up:
                    continue
                if side < 0.0 and not down:
                    continue
                carry_candidates.append((symbol, abs(carry_score), side))
            carry_selected = sorted(carry_candidates, key=lambda row: row[1], reverse=True)[:component_k]
            if carry_selected:
                carry_unit = component_gross * carry_fraction / len(carry_selected)
                for symbol, _, side in carry_selected:
                    component_weights[symbol] = component_weights.get(symbol, 0.0) + side * carry_unit
        return {
            symbol: value
            for symbol, value in component_weights.items()
            if abs(value) > 1e-12
        }

    if config.mode == "pair_reversion":
        return _pair_reversion_weights(
            frame,
            config,
            signal_idx,
            [symbol for symbol, _, _, _, _ in rows],
        )

    if config.mode in {"market_tsmom", "market_tsmom_flat"}:
        if not math.isfinite(market_momentum):
            return weights
        if market_momentum > 0.0:
            weights[market_symbol] = gross
        elif market_momentum < 0.0 and config.mode == "market_tsmom":
            weights[market_symbol] = -gross
        return weights

    if (
        config.mode.startswith(
            (
                "residual70_funding30_btc_short",
                "residual75_funding25_btc_short",
                "residual80_funding20_btc_short",
                "residual85_funding15_btc_short",
                "residual90_funding10_btc_short",
            )
        )
        and "_blend_" in config.mode
    ):
        if not math.isfinite(market_momentum):
            return weights
        short_btc_fraction = _short_btc_fraction_from_mode(config.mode)
        breadth_threshold = _breadth_threshold_from_mode(config.mode)
        if math.isfinite(breadth_threshold):
            eligible_count = len(rows)
            positive_count = sum(
                1
                for _, momentum, _, up, _ in rows
                if up and math.isfinite(momentum) and momentum > 0.0
            )
            breadth = positive_count / eligible_count if eligible_count > 0 else math.nan
            if not math.isfinite(breadth) or breadth < breadth_threshold:
                if short_btc_fraction > 0.0:
                    weights[market_symbol] = -gross * short_btc_fraction
                return weights
        market_threshold = _market_threshold_from_mode(config.mode)
        if market_momentum < market_threshold:
            if short_btc_fraction > 0.0:
                weights[market_symbol] = -gross * short_btc_fraction
            return weights
        exclusion_sets = {
            "ex_icp_near_ltc": {"ICPUSDT", "NEARUSDT", "LTCUSDT"},
            "ex_icp_near_link": {"ICPUSDT", "NEARUSDT", "LINKUSDT"},
        }
        cooldown_threshold = _cooldown_momentum_threshold_from_mode(config.mode)
        cooldown_excluded = {
            symbol
            for symbol, momentum, _, _, _ in rows
            if math.isfinite(cooldown_threshold)
            and math.isfinite(momentum)
            and momentum > cooldown_threshold
        }
        if "_6040" in config.mode:
            component_specs = (("ex_icp_near_ltc", 0.60), ("ex_icp_near_link", 0.40))
        else:
            component_specs = (("ex_icp_near_ltc", 0.50), ("ex_icp_near_link", 0.50))
        for set_name, component_fraction in component_specs:
            component = residual_funding_weights(
                component_k=k,
                component_gross=gross * component_fraction,
                residual_fraction=_residual_fraction_from_mode(config.mode),
                long_fraction=_regime_long_fraction_from_mode(config.mode, market_momentum, 0.50),
                exclude_symbols=exclusion_sets[set_name] | cooldown_excluded,
            )
            for symbol, value in component.items():
                weights[symbol] = weights.get(symbol, 0.0) + value
        return {symbol: value for symbol, value in weights.items() if abs(value) > 1e-12}

    if (
        "_btc_cash_blend_" in config.mode
        or ("_btc_cash_mktgt" in config.mode and "_blend_" in config.mode)
    ):
        market_threshold = _market_threshold_from_mode(config.mode)
        if not math.isfinite(market_momentum) or market_momentum < market_threshold:
            return weights
        exclusion_sets = {
            "ex_icp_near_ltc": {"ICPUSDT", "NEARUSDT", "LTCUSDT"},
            "ex_bottom5": {"ICPUSDT", "NEARUSDT", "BNBUSDT", "LTCUSDT", "APTUSDT"},
            "ex_icp_near_link": {"ICPUSDT", "NEARUSDT", "LINKUSDT"},
        }
        secondary_set = "ex_icp_near_link" if "_ex_icp_near_link_" in config.mode else "ex_bottom5"
        if "_7525" in config.mode:
            component_specs = (("ex_icp_near_ltc", 0.75), (secondary_set, 0.25))
        elif "_6040" in config.mode:
            component_specs = (("ex_icp_near_ltc", 0.60), (secondary_set, 0.40))
        elif "_4060" in config.mode:
            component_specs = (("ex_icp_near_ltc", 0.40), (secondary_set, 0.60))
        elif "_2575" in config.mode:
            component_specs = (("ex_icp_near_ltc", 0.25), (secondary_set, 0.75))
        elif "_ex_icp_near_link_" in config.mode:
            component_specs = (("ex_icp_near_ltc", 0.50), (secondary_set, 0.50))
        else:
            component_specs = (("ex_icp_near_ltc", 0.50), ("ex_bottom5", 0.50))
        for set_name, component_fraction in component_specs:
            component = residual_funding_weights(
                component_k=k,
                component_gross=gross * component_fraction,
                residual_fraction=_residual_fraction_from_mode(config.mode),
                long_fraction=_regime_long_fraction_from_mode(config.mode, market_momentum, 0.50),
                exclude_symbols=exclusion_sets[set_name],
            )
            for symbol, value in component.items():
                weights[symbol] = weights.get(symbol, 0.0) + value
        return {symbol: value for symbol, value in weights.items() if abs(value) > 1e-12}

    if config.mode in {
        "basket_tsmom_equal",
        "basket_tsmom_vol",
        "basket_reversal_equal",
        "basket_reversal_vol",
    }:
        raw_weights: list[tuple[str, float]] = []
        is_reversal = config.mode.startswith("basket_reversal")
        use_vol = config.mode.endswith("_vol")
        for symbol, score, vol, up, down in rows:
            if score > 0.0:
                side = -1.0 if is_reversal else 1.0
            elif score < 0.0:
                side = 1.0 if is_reversal else -1.0
            else:
                continue
            if side > 0.0 and not up:
                continue
            if side < 0.0 and not down:
                continue
            unit = min(1.0 / max(vol, 1e-5), 100_000.0) if use_vol else 1.0
            raw_weights.append((symbol, side * unit))
        total_abs = sum(abs(value) for _, value in raw_weights)
        if total_abs <= 0.0:
            return weights
        for symbol, value in raw_weights:
            weights[symbol] = gross * value / total_abs
        return weights

    if config.mode in {"funding_carry_equal", "funding_carry_vol", "funding_carry_top"}:
        if not funding_period_rates:
            return weights
        candidates: list[tuple[str, float, float, bool, bool]] = []
        start_idx = max(0, signal_idx - config.lookback_bars + 1)
        for symbol, _, vol, up, down in rows:
            rates = funding_period_rates.get(symbol)
            if not rates:
                continue
            carry_score = sum(rates[start_idx : signal_idx + 1])
            if not math.isfinite(carry_score) or abs(carry_score) <= 1e-12:
                continue
            candidates.append((symbol, carry_score, vol, up, down))
        if config.mode == "funding_carry_top":
            candidates = sorted(candidates, key=lambda row: abs(row[1]), reverse=True)[:k]
        raw_weights = []
        use_vol = config.mode == "funding_carry_vol"
        for symbol, carry_score, vol, up, down in candidates:
            side = -1.0 if carry_score > 0.0 else 1.0
            if side > 0.0 and not up:
                continue
            if side < 0.0 and not down:
                continue
            unit = min(1.0 / max(vol, 1e-5), 100_000.0) if use_vol else 1.0
            raw_weights.append((symbol, side * unit))
        total_abs = sum(abs(value) for _, value in raw_weights)
        if total_abs <= 0.0:
            return weights
        for symbol, value in raw_weights:
            weights[symbol] = gross * value / total_abs
        return weights

    if config.mode in {
        "residual70_funding30",
        "residual70_funding30_ls7030",
        "residual70_funding30_ls8020",
        "residual50_funding50",
    }:
        residual_fraction = 0.70 if config.mode == "residual70_funding30" else 0.50
        if config.mode.startswith("residual70_funding30"):
            residual_fraction = 0.70
        long_fraction = 0.5
        if config.mode.endswith("_ls7030"):
            long_fraction = 0.7
        elif config.mode.endswith("_ls8020"):
            long_fraction = 0.8
        carry_fraction = 1.0 - residual_fraction
        longs = [(symbol, score, vol) for symbol, score, vol, up, _ in desc if up][:k]
        long_symbols = {symbol for symbol, _, _ in longs}
        shorts = [
            (symbol, score, vol)
            for symbol, score, vol, _, down in asc
            if down and symbol not in long_symbols
        ][:k]
        _weighted_assign(
            weights,
            longs,
            side=1,
            gross=gross * residual_fraction * long_fraction,
            vol_weight=config.vol_weight,
        )
        _weighted_assign(
            weights,
            shorts,
            side=-1,
            gross=gross * residual_fraction * (1.0 - long_fraction),
            vol_weight=config.vol_weight,
        )
        if funding_period_rates:
            start_idx = max(0, signal_idx - config.lookback_bars + 1)
            carry_candidates: list[tuple[str, float, float]] = []
            for symbol, _, vol, up, down in rows:
                rates = funding_period_rates.get(symbol)
                if not rates:
                    continue
                carry_score = sum(rates[start_idx : signal_idx + 1])
                if not math.isfinite(carry_score) or abs(carry_score) <= 1e-12:
                    continue
                side = -1.0 if carry_score > 0.0 else 1.0
                if side > 0.0 and not up:
                    continue
                if side < 0.0 and not down:
                    continue
                carry_candidates.append((symbol, abs(carry_score), side))
            carry_selected = sorted(carry_candidates, key=lambda row: row[1], reverse=True)[:k]
            if carry_selected:
                carry_unit = gross * carry_fraction / len(carry_selected)
                for symbol, _, side in carry_selected:
                    weights[symbol] = weights.get(symbol, 0.0) + side * carry_unit
        return {symbol: value for symbol, value in weights.items() if abs(value) > 1e-12}

    if config.mode in {
        "residual70_funding30_btc_cash",
        "residual70_funding30_btc_cash_mktgt02",
        "residual70_funding30_btc_cash_mktgt05",
        "residual70_funding30_btc_cash_mktgt10",
        "residual70_funding30_btc_guard",
        "residual70_funding30_btc_cash_ls7030",
        "residual70_funding30_btc_cash_ls8020",
        "residual70_funding30_btc_guard_ls7030",
        "residual70_funding30_btc_guard_ls8020",
        "residual50_funding50_btc_cash",
        "residual50_funding50_btc_guard",
        "residual60_funding40_btc_cash",
        "residual75_funding25_btc_cash",
        "residual75_funding25_btc_cash_long",
        "residual75_funding25_btc_cash_ls6040",
        "residual75_funding25_btc_cash_ls7030",
        "residual75_funding25_btc_cash_ls8020",
        "residual80_funding20_btc_cash",
        "residual80_funding20_btc_short25",
        "residual80_funding20_btc_short50",
        "residual80_funding20_btc_short100",
        "residual80_funding20_btc_cash_mktgt02",
        "residual80_funding20_btc_cash_mktgt05",
        "residual80_funding20_btc_cash_mktgt10",
        "residual80_funding20_btc_cash_long",
        "residual80_funding20_btc_cash_mh168336720",
        "residual80_funding20_btc_cash_ls6040",
        "residual80_funding20_btc_cash_ls7030",
        "residual80_funding20_btc_cash_ls8020",
        "residual85_funding15_btc_cash",
        "residual85_funding15_btc_cash_mktgt02",
        "residual85_funding15_btc_cash_mktgt05",
        "residual85_funding15_btc_cash_mktgt10",
        "residual85_funding15_btc_cash_long",
        "residual85_funding15_btc_cash_ls6040",
        "residual85_funding15_btc_cash_ls7030",
        "residual85_funding15_btc_cash_ls8020",
        "residual90_funding10_btc_cash",
        "residual90_funding10_btc_cash_long",
        "residual90_funding10_btc_cash_ls6040",
        "residual90_funding10_btc_cash_ls7030",
        "residual90_funding10_btc_cash_ls8020",
        "residual95_funding05_btc_cash",
        "residual100_btc_cash",
        "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_bottom5_5050",
        "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_cash_mktgt02_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_cash_mktgt05_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_cash_mktgt10_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_7525",
        "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_4060",
        "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_2575",
        "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_bottom5_7525",
        "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_bottom5_2575",
        "residual80_funding20_btc_short5_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_short5_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual80_funding20_btc_short10_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_short10_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual80_funding20_btc_short15_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_short15_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual80_funding20_btc_short20_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_short20_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual80_funding20_btc_short25_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_short25_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual80_funding20_btc_short30_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_short30_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual80_funding20_btc_short50_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_short50_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
        "residual80_funding20_btc_short100_blend_ex_icp_near_ltc_ex_icp_near_link_5050",
        "residual80_funding20_btc_short100_blend_ex_icp_near_ltc_ex_icp_near_link_6040",
    }:
        if not math.isfinite(market_momentum):
            return weights
        is_cash_mode = "_btc_cash" in config.mode
        short_btc_fraction = _short_btc_fraction_from_mode(config.mode)
        market_threshold = _market_threshold_from_mode(config.mode)
        if market_momentum < market_threshold and short_btc_fraction > 0.0:
            weights[market_symbol] = -gross * short_btc_fraction
            return weights
        if market_momentum < market_threshold and is_cash_mode:
            return weights
        is_guard_mode = "_btc_guard" in config.mode
        effective_gross = gross * 0.5 if market_momentum < 0.0 and is_guard_mode else gross
        residual_fraction = _residual_fraction_from_mode(config.mode)
        long_fraction = 0.5
        if config.mode.endswith("_long"):
            long_fraction = 1.0
        elif config.mode.endswith("_ls6040"):
            long_fraction = 0.6
        elif config.mode.endswith("_ls7030"):
            long_fraction = 0.7
        elif config.mode.endswith("_ls8020"):
            long_fraction = 0.8
        return residual_funding_weights(
            component_k=k,
            component_gross=effective_gross,
            residual_fraction=residual_fraction,
            long_fraction=long_fraction,
        )

    if config.mode in {
        "residual70_funding30_btc_cash_mix_k2k3_3070",
        "residual70_funding30_btc_cash_mix_k2k3_5050",
        "residual70_funding30_btc_cash_mix_k2k3_7030",
        "residual70_funding30_btc_guard_mix_k2k3_3070",
        "residual70_funding30_btc_guard_mix_k2k3_5050",
        "residual70_funding30_btc_guard_mix_k2k3_7030",
    }:
        if not math.isfinite(market_momentum):
            return weights
        if market_momentum < 0.0 and "_btc_cash" in config.mode:
            return weights
        effective_gross = gross * 0.5 if market_momentum < 0.0 and "_btc_guard" in config.mode else gross
        if config.mode.endswith("_3070"):
            component_specs = ((2, 0.30), (3, 0.70))
        elif config.mode.endswith("_7030"):
            component_specs = ((2, 0.70), (3, 0.30))
        else:
            component_specs = ((2, 0.50), (3, 0.50))
        for component_k, component_fraction in component_specs:
            component = residual_funding_weights(
                component_k=component_k,
                component_gross=effective_gross * component_fraction,
            )
            for symbol, value in component.items():
                weights[symbol] = weights.get(symbol, 0.0) + value
        return {symbol: value for symbol, value in weights.items() if abs(value) > 1e-12}

    if config.mode in {
        "residual70_funding30_mix_k2k5_3070",
        "residual70_funding30_mix_k2k5_5050",
        "residual70_funding30_mix_k2k5_7030",
    }:
        if config.mode.endswith("_3070"):
            component_specs = ((2, 0.30), (5, 0.70))
        elif config.mode.endswith("_7030"):
            component_specs = ((2, 0.70), (5, 0.30))
        else:
            component_specs = ((2, 0.50), (5, 0.50))
        for component_k, component_fraction in component_specs:
            component = residual_funding_weights(
                component_k=component_k,
                component_gross=gross * component_fraction,
            )
            for symbol, value in component.items():
                weights[symbol] = weights.get(symbol, 0.0) + value
        return {symbol: value for symbol, value in weights.items() if abs(value) > 1e-12}

    if config.mode in {"lowvol_long_top", "lowvol_btc_cash_long"}:
        if config.mode == "lowvol_btc_cash_long" and (
            not math.isfinite(market_momentum) or market_momentum < 0.0
        ):
            return weights
        low_vol_rows = sorted(rows, key=lambda row: row[2])
        longs = [
            (symbol, 1.0 / max(vol, 1e-5), vol)
            for symbol, _, vol, up, _ in low_vol_rows
            if up
        ][:k]
        _weighted_assign(weights, longs, side=1, gross=gross, vol_weight=config.vol_weight)
        return weights

    if config.mode.startswith("residual_lowvol_btc_cash_long_"):
        if not math.isfinite(market_momentum) or market_momentum < 0.0:
            return weights
        candidates = [
            (symbol, score, vol)
            for symbol, score, vol, up, _ in rank_rows
            if up and math.isfinite(score) and score > 0.0
        ]
        if not candidates:
            return weights
        denom = max(len(candidates) - 1, 1)
        residual_ranks = {
            symbol: 1.0 - rank / denom
            for rank, (symbol, _, _) in enumerate(
                sorted(candidates, key=lambda row: row[1], reverse=True)
            )
        }
        lowvol_ranks = {
            symbol: 1.0 - rank / denom
            for rank, (symbol, _, _) in enumerate(sorted(candidates, key=lambda row: row[2]))
        }
        residual_weight = 0.65
        if config.mode.endswith("_5050"):
            residual_weight = 0.50
        elif config.mode.endswith("_3565"):
            residual_weight = 0.35
        scored = sorted(
            (
                (
                    symbol,
                    residual_weight * residual_ranks[symbol]
                    + (1.0 - residual_weight) * lowvol_ranks[symbol],
                    vol,
                )
                for symbol, _, vol in candidates
            ),
            key=lambda row: row[1],
            reverse=True,
        )
        _weighted_assign(weights, scored[:k], side=1, gross=gross, vol_weight=config.vol_weight)
        return weights

    if config.mode in {"long_top", "liquid_long_top", "residual_long_top", "channel_long_top"}:
        longs = [(symbol, score, vol) for symbol, score, vol, up, _ in desc if score > 0.0 and up][:k]
        _weighted_assign(weights, longs, side=1, gross=gross, vol_weight=config.vol_weight)
        return weights

    if config.mode == "liquid_highmom_long":
        longs = [(symbol, score, vol) for symbol, score, vol, up, _ in desc if up][:k]
        _weighted_assign(weights, longs, side=1, gross=gross, vol_weight=config.vol_weight)
        return weights

    if config.mode in {
        "relative_ls",
        "liquid_relative_ls",
        "liquid_highmom_ls",
        "illiquid_momentum_ls",
        "residual_ls",
        "channel_ls",
        "volume_factor_ls",
        "volume_vol_factor_ls",
    }:
        longs = [(symbol, score, vol) for symbol, score, vol, up, _ in desc if up][:k]
        long_symbols = {symbol for symbol, _, _ in longs}
        shorts = [
            (symbol, score, vol)
            for symbol, score, vol, _, down in asc
            if down and symbol not in long_symbols
        ][:k]
        _weighted_assign(weights, longs, side=1, gross=gross * 0.5, vol_weight=config.vol_weight)
        _weighted_assign(weights, shorts, side=-1, gross=gross * 0.5, vol_weight=config.vol_weight)
        return weights

    if config.mode in {"btc_hedged_long_top", "btc_hedged_long_guard", "btc_hedged_channel"}:
        if not math.isfinite(market_momentum):
            return weights
        if config.mode == "btc_hedged_long_guard" and market_momentum < 0.0:
            effective_gross = gross * 0.5
            hedge_fraction = 0.5
        else:
            effective_gross = gross
            hedge_fraction = 0.25
        long_gross = effective_gross * (1.0 - hedge_fraction)
        hedge_gross = effective_gross * hedge_fraction
        longs = [
            (symbol, score, vol)
            for symbol, score, vol, up, _ in desc
            if symbol != market_symbol and score > 0.0 and up
        ][:k]
        _weighted_assign(weights, longs, side=1, gross=long_gross, vol_weight=config.vol_weight)
        if hedge_gross > 0.0 and market_symbol not in {symbol for symbol, _, _ in longs}:
            weights[market_symbol] = weights.get(market_symbol, 0.0) - hedge_gross
        return weights

    if config.mode in {"relative_ls_7030", "relative_ls_8020", "sharpe_ls_7030", "sharpe_ls_8020"}:
        long_fraction = 0.8 if config.mode.endswith("_8020") else 0.7
        longs = [(symbol, score, vol) for symbol, score, vol, up, _ in desc if up][:k]
        long_symbols = {symbol for symbol, _, _ in longs}
        shorts = [
            (symbol, score, vol)
            for symbol, score, vol, _, down in asc
            if down and symbol not in long_symbols
        ][:k]
        _weighted_assign(weights, longs, side=1, gross=gross * long_fraction, vol_weight=config.vol_weight)
        _weighted_assign(weights, shorts, side=-1, gross=gross * (1.0 - long_fraction), vol_weight=config.vol_weight)
        return weights

    if config.mode in {
        "relative_ls_btc_gate",
        "relative_ls_btc_up",
        "relative_ls_btc_guard",
        "relative_ls_btc_cash",
        "sharpe_ls",
    }:
        long_fraction = 0.5
        effective_gross = gross
        if config.mode.startswith("relative_ls_btc"):
            if not math.isfinite(market_momentum):
                return weights
            if config.mode == "relative_ls_btc_gate":
                long_fraction = 0.7 if market_momentum >= 0.0 else 0.3
            elif config.mode == "relative_ls_btc_up":
                long_fraction = 0.7 if market_momentum >= 0.0 else 0.5
            elif config.mode == "relative_ls_btc_guard":
                long_fraction = 0.7 if market_momentum >= 0.0 else 0.5
                effective_gross = gross if market_momentum >= 0.0 else gross * 0.5
            elif config.mode == "relative_ls_btc_cash":
                if market_momentum < 0.0:
                    return weights
                long_fraction = 0.8
        longs = [(symbol, score, vol) for symbol, score, vol, up, _ in desc if up][:k]
        long_symbols = {symbol for symbol, _, _ in longs}
        shorts = [
            (symbol, score, vol)
            for symbol, score, vol, _, down in asc
            if down and symbol not in long_symbols
        ][:k]
        _weighted_assign(weights, longs, side=1, gross=effective_gross * long_fraction, vol_weight=config.vol_weight)
        _weighted_assign(
            weights,
            shorts,
            side=-1,
            gross=effective_gross * (1.0 - long_fraction),
            vol_weight=config.vol_weight,
        )
        return weights

    if config.mode == "long_sharpe":
        longs = [(symbol, score, vol) for symbol, score, vol, up, _ in desc if score > 0.0 and up][:k]
        _weighted_assign(weights, longs, side=1, gross=gross, vol_weight=config.vol_weight)
        return weights

    if config.mode == "sharpe_directional_ls":
        longs = [(symbol, score, vol) for symbol, score, vol, up, _ in desc if score > 0.0 and up][:k]
        long_symbols = {symbol for symbol, _, _ in longs}
        shorts = [
            (symbol, score, vol)
            for symbol, score, vol, _, down in asc
            if score < 0.0 and down and symbol not in long_symbols
        ][:k]
        if longs and shorts:
            long_gross = gross * 0.5
            short_gross = gross * 0.5
        elif longs:
            long_gross = gross
            short_gross = 0.0
        else:
            long_gross = 0.0
            short_gross = gross
        _weighted_assign(weights, longs, side=1, gross=long_gross, vol_weight=config.vol_weight)
        _weighted_assign(weights, shorts, side=-1, gross=short_gross, vol_weight=config.vol_weight)
        return weights

    if config.mode in {"cross_reversal", "liquid_reversal_ls", "illiquid_reversal_ls"}:
        longs = [(symbol, score, vol) for symbol, score, vol, up, _ in asc if up][:k]
        long_symbols = {symbol for symbol, _, _ in longs}
        shorts = [
            (symbol, score, vol)
            for symbol, score, vol, _, down in desc
            if down and symbol not in long_symbols
        ][:k]
        _weighted_assign(weights, longs, side=1, gross=gross * 0.5, vol_weight=config.vol_weight)
        _weighted_assign(weights, shorts, side=-1, gross=gross * 0.5, vol_weight=config.vol_weight)
        return weights

    if config.mode == "directional_ls":
        longs = [(symbol, score, vol) for symbol, score, vol, up, _ in desc if score > 0.0 and up][:k]
        long_symbols = {symbol for symbol, _, _ in longs}
        shorts = [
            (symbol, score, vol)
            for symbol, score, vol, _, down in asc
            if score < 0.0 and down and symbol not in long_symbols
        ][:k]
        if longs and shorts:
            long_gross = gross * 0.5
            short_gross = gross * 0.5
        elif longs:
            long_gross = gross
            short_gross = 0.0
        else:
            long_gross = 0.0
            short_gross = gross
        _weighted_assign(weights, longs, side=1, gross=long_gross, vol_weight=config.vol_weight)
        _weighted_assign(weights, shorts, side=-1, gross=short_gross, vol_weight=config.vol_weight)
        return weights

    if config.mode == "regime_switch":
        market_symbol = "BTCUSDT" if "BTCUSDT" in frame.symbols else frame.symbols[0]
        market_momentum = mom_by_symbol[market_symbol][signal_idx]
        if not math.isfinite(market_momentum):
            return weights
        if market_momentum >= 0.0:
            longs = [(symbol, score, vol) for symbol, score, vol, up, _ in desc if score > 0.0 and up][:k]
            _weighted_assign(weights, longs, side=1, gross=gross, vol_weight=config.vol_weight)
        else:
            shorts = [(symbol, score, vol) for symbol, score, vol, _, down in asc if score < 0.0 and down][:k]
            _weighted_assign(weights, shorts, side=-1, gross=gross, vol_weight=config.vol_weight)
        return weights

    if config.mode == "best_abs":
        candidates: list[tuple[str, float, float, int]] = []
        for symbol, score, vol, up, down in rows:
            if score > 0.0 and up:
                candidates.append((symbol, abs(score), vol, 1))
            elif score < 0.0 and down:
                candidates.append((symbol, abs(score), vol, -1))
        selected = sorted(candidates, key=lambda row: row[1], reverse=True)[:k]
        longs = [(symbol, score, vol) for symbol, score, vol, side in selected if side > 0]
        shorts = [(symbol, score, vol) for symbol, score, vol, side in selected if side < 0]
        selected_count = max(len(selected), 1)
        _weighted_assign(
            weights,
            longs,
            side=1,
            gross=gross * len(longs) / selected_count,
            vol_weight=config.vol_weight,
        )
        _weighted_assign(
            weights,
            shorts,
            side=-1,
            gross=gross * len(shorts) / selected_count,
            vol_weight=config.vol_weight,
        )
        return weights

    if config.mode == "tsmom_vol":
        candidates: list[tuple[str, float, float, int]] = []
        for symbol, score, vol, up, down in rows:
            if score > 0.0 and up:
                candidates.append((symbol, abs(score), vol, 1))
            elif score < 0.0 and down:
                candidates.append((symbol, abs(score), vol, -1))
        selected = sorted(candidates, key=lambda row: row[1], reverse=True)[:k]
        if not selected:
            return weights
        if config.vol_weight:
            raw = [
                (symbol, side * min(1.0 / max(vol, 1e-5), 100_000.0))
                for symbol, _, vol, side in selected
                if math.isfinite(vol) and vol > 0.0
            ]
        else:
            raw = [(symbol, float(side)) for symbol, _, _, side in selected]
        total_abs = sum(abs(value) for _, value in raw)
        if total_abs <= 0.0:
            return weights
        for symbol, value in raw:
            weights[symbol] = gross * value / total_abs
        return weights

    return weights


def _portfolio_return(frame: MarketFrame, weights: dict[str, float], period_idx: int) -> float:
    total = 0.0
    for symbol, weight in weights.items():
        symbol_return = frame.returns[symbol][period_idx]
        if math.isfinite(symbol_return):
            total += weight * symbol_return
    return total


def _turnover(old: dict[str, float], new: dict[str, float], symbols: list[str]) -> float:
    return sum(abs(new.get(symbol, 0.0) - old.get(symbol, 0.0)) for symbol in symbols)


def _scale_weights(weights: dict[str, float], scale: float) -> dict[str, float]:
    scale = max(float(scale), 0.0)
    if abs(scale - 1.0) <= 1e-12:
        return weights
    return {symbol: weight * scale for symbol, weight in weights.items()}


def _clip_symbol_weights(weights: dict[str, float], max_abs_weight: float) -> tuple[dict[str, float], int]:
    cap = max(float(max_abs_weight), 0.0)
    if cap <= 0.0:
        return weights, 0
    clipped: dict[str, float] = {}
    clip_count = 0
    for symbol, weight in weights.items():
        if abs(weight) > cap:
            clipped[symbol] = math.copysign(cap, weight)
            clip_count += 1
        else:
            clipped[symbol] = weight
    return clipped, clip_count


def _quote_volume_at(frame: MarketFrame, symbol: str, idx: int) -> float:
    close = frame.closes[symbol][idx]
    volume = frame.volumes[symbol][idx]
    if not (math.isfinite(close) and math.isfinite(volume) and close > 0.0 and volume > 0.0):
        return math.nan
    return close * volume


def _notional_account_multiplier(equity: float, mode: str) -> float:
    equity = max(float(equity), 0.0)
    if mode == "starting":
        return 1.0
    profit_reinvest_fractions = {
        "profit25": 0.25,
        "profit50": 0.50,
        "profit55": 0.55,
        "profit60": 0.60,
        "profit65": 0.65,
        "profit70": 0.70,
        "profit75": 0.75,
        "profit80": 0.80,
        "profit85": 0.85,
        "profit90": 0.90,
        "profit95": 0.95,
    }
    if mode in profit_reinvest_fractions:
        if equity <= 1.0:
            return equity
        return 1.0 + profit_reinvest_fractions[mode] * (equity - 1.0)
    return equity


def _basis_return_to_equity_return(value: float, *, equity: float, pnl_notional_mode: str) -> float:
    pnl_multiplier = _notional_account_multiplier(equity, pnl_notional_mode)
    return float(value) * pnl_multiplier / max(float(equity), 1e-12)


def _execution_to_pnl_basis_multiplier(
    *,
    equity: float,
    execution_notional_mode: str,
    pnl_notional_mode: str,
) -> float:
    execution_multiplier = _notional_account_multiplier(equity, execution_notional_mode)
    pnl_multiplier = _notional_account_multiplier(equity, pnl_notional_mode)
    return execution_multiplier / max(pnl_multiplier, 1e-12)


def _trade_volume_pct_for_delta(
    *,
    delta_weight: float,
    equity: float,
    assumed_capital_usd: float,
    quote_volume: float,
    liquidity_notional_mode: str,
) -> float:
    if assumed_capital_usd <= 0.0 or quote_volume <= 0.0:
        return 0.0
    account_multiplier = _notional_account_multiplier(equity, liquidity_notional_mode)
    return abs(float(delta_weight)) * account_multiplier * assumed_capital_usd / quote_volume * 100.0


def _floor_to_step(value: float, step: float) -> float:
    if step <= 0.0:
        return max(float(value), 0.0)
    return math.floor(max(float(value), 0.0) / step + 1e-12) * step


def _load_exchange_rules(*, base_url: str, cache_path: Path) -> dict[str, ExchangeRule]:
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text())
        except Exception:
            data = {}
    else:
        data = {}
    if not data:
        url = f"{base_url.rstrip('/')}/fapi/v1/exchangeInfo"
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(cache_path, json.dumps(data, ensure_ascii=False, indent=2))

    rules: dict[str, ExchangeRule] = {}
    for symbol_info in list(data.get("symbols") or []):
        symbol = str(symbol_info.get("symbol") or "").upper()
        if not symbol:
            continue
        min_qty = 0.0
        step_size = 0.0
        min_notional = 0.0
        tick_size = 0.0
        for filter_info in list(symbol_info.get("filters") or []):
            filter_type = str(filter_info.get("filterType") or "")
            if filter_type == "LOT_SIZE":
                min_qty = float(filter_info.get("minQty") or 0.0)
                step_size = float(filter_info.get("stepSize") or 0.0)
            elif filter_type == "PRICE_FILTER":
                tick_size = float(filter_info.get("tickSize") or 0.0)
            elif filter_type in {"MIN_NOTIONAL", "NOTIONAL"}:
                min_notional = float(
                    filter_info.get("notional")
                    or filter_info.get("minNotional")
                    or 0.0
                )
        rules[symbol] = ExchangeRule(
            symbol=symbol,
            min_qty=min_qty,
            step_size=step_size,
            min_notional=min_notional,
            tick_size=tick_size,
        )
    return rules


def _apply_exchange_rules(
    frame: MarketFrame,
    *,
    weights: dict[str, float],
    signal_idx: int,
    equity: float,
    assumed_capital_usd: float,
    pnl_notional_mode: str,
    exchange_rules: dict[str, ExchangeRule],
) -> tuple[dict[str, float], int, int]:
    if assumed_capital_usd <= 0.0 or not exchange_rules:
        return weights, 0, 0

    adjusted: dict[str, float] = {}
    adjustment_count = 0
    dropped_count = 0
    account_multiplier = _notional_account_multiplier(equity, pnl_notional_mode)
    basis_notional = max(account_multiplier * assumed_capital_usd, 1e-12)
    for symbol, target_weight in weights.items():
        if abs(target_weight) <= 1e-12:
            continue
        rule = exchange_rules.get(symbol)
        price = frame.closes[symbol][signal_idx]
        if rule is None or not math.isfinite(price) or price <= 0.0:
            adjusted[symbol] = target_weight
            continue
        target_notional = abs(target_weight) * basis_notional
        raw_qty = target_notional / price
        qty = _floor_to_step(raw_qty, rule.step_size)
        notional = qty * price
        if qty < max(rule.min_qty, 0.0) or notional < max(rule.min_notional, 0.0):
            dropped_count += 1
            adjustment_count += 1
            continue
        quantized_weight = math.copysign(notional / basis_notional, target_weight)
        if abs(quantized_weight - target_weight) > 1e-10:
            adjustment_count += 1
        adjusted[symbol] = quantized_weight
    return adjusted, adjustment_count, dropped_count


def _apply_capacity_cap(
    frame: MarketFrame,
    *,
    old_weights: dict[str, float],
    new_weights: dict[str, float],
    signal_idx: int,
    equity: float,
    assumed_capital_usd: float,
    max_trade_volume_pct: float,
    liquidity_notional_mode: str,
) -> tuple[dict[str, float], int, float]:
    if assumed_capital_usd <= 0.0 or max_trade_volume_pct <= 0.0:
        return new_weights, 0, 0.0

    capped: dict[str, float] = {}
    cap_events = 0
    max_requested_pct = 0.0
    account_multiplier = _notional_account_multiplier(equity, liquidity_notional_mode)
    for symbol in frame.symbols:
        old_weight = old_weights.get(symbol, 0.0)
        target_weight = new_weights.get(symbol, 0.0)
        delta = target_weight - old_weight
        if abs(delta) <= 1e-12:
            if abs(old_weight) > 1e-12:
                capped[symbol] = old_weight
            continue
        quote_volume = _quote_volume_at(frame, symbol, signal_idx)
        if not math.isfinite(quote_volume) or quote_volume <= 0.0:
            if abs(old_weight) > 1e-12:
                capped[symbol] = old_weight
            cap_events += 1
            continue
        requested_pct = _trade_volume_pct_for_delta(
            delta_weight=delta,
            equity=equity,
            assumed_capital_usd=assumed_capital_usd,
            quote_volume=quote_volume,
            liquidity_notional_mode=liquidity_notional_mode,
        )
        max_requested_pct = max(max_requested_pct, requested_pct)
        max_delta = (
            quote_volume
            * max_trade_volume_pct
            / 100.0
            / max(account_multiplier * assumed_capital_usd, 1e-12)
        )
        if abs(delta) > max_delta:
            cap_events += 1
            target_weight = old_weight + math.copysign(max_delta, delta)
        if abs(target_weight) > 1e-12:
            capped[symbol] = target_weight
    return capped, cap_events, max_requested_pct


def _load_funding_rates(
    *,
    symbol: str,
    start_ms: int,
    end_ms: int,
    cache_dir: Path,
    base_url: str,
    sleep_seconds: float,
) -> dict[int, float]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{symbol}_{start_ms}_{end_ms}.json"
    if cache_path.exists():
        raw = json.loads(cache_path.read_text())
        return {int(ts): float(rate) for ts, rate in raw.items()}

    url = f"{base_url.rstrip('/')}/fapi/v1/fundingRate"
    out: dict[int, float] = {}
    cursor = int(start_ms)
    while cursor <= end_ms:
        query = urllib.parse.urlencode(
            {
                "symbol": symbol,
                "startTime": cursor,
                "endTime": int(end_ms),
                "limit": 1000,
            }
        )
        with urllib.request.urlopen(f"{url}?{query}", timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        if not data:
            break
        for row in data:
            ts = int(row.get("fundingTime") or 0)
            if start_ms <= ts <= end_ms:
                out[ts] = float(row.get("fundingRate") or 0.0)
        next_cursor = int(data[-1].get("fundingTime") or cursor) + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if sleep_seconds > 0.0:
            time.sleep(float(sleep_seconds))

    atomic_write_text(cache_path, json.dumps({str(ts): rate for ts, rate in sorted(out.items())}, indent=2))
    return out


def _funding_return_for_period(
    funding_rates: dict[str, dict[int, float]] | None,
    weights: dict[str, float],
    start_ms: int,
    end_ms: int,
) -> float:
    if not funding_rates or not weights:
        return 0.0
    total = 0.0
    for symbol, weight in weights.items():
        symbol_rates = funding_rates.get(symbol) or {}
        for ts, rate in symbol_rates.items():
            if start_ms < ts <= end_ms and math.isfinite(rate):
                total += -weight * rate
    return total


def _build_funding_period_rates(
    frame: MarketFrame,
    funding_rates: dict[str, dict[int, float]] | None,
) -> dict[str, list[float]]:
    if not funding_rates:
        return {}
    out: dict[str, list[float]] = {}
    for symbol in frame.symbols:
        per_period = [0.0 for _ in frame.open_ms]
        for ts, rate in sorted(dict(funding_rates.get(symbol) or {}).items()):
            if not math.isfinite(rate):
                continue
            period_idx = bisect_left(frame.open_ms, int(ts)) - 1
            if 0 <= period_idx < len(per_period) - 1:
                per_period[period_idx] += float(rate)
        out[symbol] = per_period
    return out


def _funding_return_for_period_index(
    funding_period_rates: dict[str, list[float]] | None,
    weights: dict[str, float],
    period_idx: int,
) -> float:
    if not funding_period_rates or not weights:
        return 0.0
    total = 0.0
    for symbol, weight in weights.items():
        values = funding_period_rates.get(symbol)
        if values and 0 <= period_idx < len(values):
            rate = values[period_idx]
            if math.isfinite(rate):
                total += -weight * rate
    return total


def _intrabar_adverse_return(frame: MarketFrame, weights: dict[str, float], period_idx: int) -> float:
    adverse = 0.0
    for symbol, weight in weights.items():
        open_price = frame.opens[symbol][period_idx]
        if not math.isfinite(open_price) or open_price <= 0.0:
            continue
        if weight > 0.0:
            low = frame.lows[symbol][period_idx]
            if math.isfinite(low) and low > 0.0:
                adverse += weight * (low / open_price - 1.0)
        elif weight < 0.0:
            high = frame.highs[symbol][period_idx]
            if math.isfinite(high) and high > 0.0:
                adverse += weight * (high / open_price - 1.0)
    return adverse


def _weights_sample(weights: dict[str, float], limit: int = 6) -> dict[str, float]:
    ordered = sorted(weights.items(), key=lambda item: abs(item[1]), reverse=True)[:limit]
    return {symbol: round(weight, 4) for symbol, weight in ordered if abs(weight) > 1e-9}


def _top_float_items(values: dict[str, float], *, reverse: bool, limit: int = 10) -> dict[str, float]:
    ordered = sorted(values.items(), key=lambda item: item[1], reverse=reverse)[:limit]
    return {key: round(value, 4) for key, value in ordered}


def _year_fraction(first: datetime | None, last: datetime | None) -> float:
    if first is None or last is None:
        return 0.0
    return max((last - first).total_seconds(), 1.0) / (365.25 * 24 * 60 * 60)


def _cross_sectional_momentum_dispersion(
    frame: MarketFrame,
    features: FeatureBundle,
    config: RotationPortfolioConfig,
    signal_idx: int,
) -> float:
    mom_by_symbol = features.momentum[config.lookback_bars]
    values: list[float] = []
    for symbol in frame.symbols:
        first_valid = frame.first_valid_index.get(symbol)
        if first_valid is None or signal_idx - first_valid < config.min_symbol_age_bars:
            continue
        value = mom_by_symbol[symbol][signal_idx]
        if math.isfinite(value):
            values.append(value)
    if len(values) < 4:
        return math.nan
    mean = _mean(values)
    return _std(values, mean)


def _empirical_quantile(values: list[float], quantile: float) -> float:
    finite = sorted(value for value in values if math.isfinite(value))
    if not finite:
        return math.nan
    q = min(max(float(quantile), 0.0), 1.0)
    idx = min(int(math.floor(q * (len(finite) - 1))), len(finite) - 1)
    return finite[idx]


def _symbol_quality_blocklist(
    frame: MarketFrame,
    *,
    contribution_history: dict[str, deque[float]],
    exposure_history: dict[str, deque[float]],
    active_history: dict[str, deque[int]],
    drop_count: int,
    min_active_periods: int,
    min_abs_exposure: float,
    score_threshold: float,
) -> set[str]:
    if drop_count <= 0:
        return set()
    market_symbol = "BTCUSDT" if "BTCUSDT" in frame.symbols else frame.symbols[0]
    scored: list[tuple[float, str]] = []
    for symbol in frame.symbols:
        if symbol == market_symbol:
            continue
        active_periods = sum(active_history.get(symbol) or [])
        if active_periods < min_active_periods:
            continue
        abs_exposure = sum(exposure_history.get(symbol) or [])
        if abs_exposure < min_abs_exposure:
            continue
        contribution = sum(contribution_history.get(symbol) or [])
        score = contribution / max(abs_exposure, 1e-12)
        if score <= score_threshold:
            scored.append((score, symbol))
    return {symbol for _, symbol in sorted(scored)[:drop_count]}


def backtest_config(
    frame: MarketFrame,
    features: FeatureBundle,
    config: RotationPortfolioConfig,
    *,
    cost_bps_per_turnover: float,
    holding_cost_bps_per_day: float = 0.0,
    short_cost_bps_per_day: float = 0.0,
    drawdown_guard_pct: float = 0.0,
    drawdown_risk_scale: float = 1.0,
    vol_target_annual_pct: float = 0.0,
    vol_lookback_hours: int = 720,
    vol_min_scale: float = 0.0,
    vol_max_scale: float = 1.0,
    dispersion_lookback_rebalances: int = 0,
    dispersion_guard_quantile: float = 0.0,
    dispersion_risk_scale: float = 1.0,
    symbol_quality_lookback_hours: int = 0,
    symbol_quality_drop_count: int = 0,
    symbol_quality_min_active_periods: int = 30,
    symbol_quality_min_abs_exposure: float = 1.0,
    symbol_quality_score_threshold: float = 0.0,
    funding_rates: dict[str, dict[int, float]] | None = None,
    funding_period_rates: dict[str, list[float]] | None = None,
    maintenance_margin_pct: float = 0.0,
    assumed_capital_usd: float = 0.0,
    pnl_notional_mode: str = "compounded",
    liquidity_notional_mode: str = "compounded",
    liquidity_impact_bps_per_1pct_volume: float = 0.0,
    max_symbol_weight: float = 0.0,
    max_trade_volume_pct: float = 1.0,
    capacity_cap_trade_volume_pct: float = 0.0,
    exchange_rules: dict[str, ExchangeRule] | None = None,
) -> dict[str, Any]:
    warmup = max(config.lookback_bars, config.trend_bars, config.vol_bars, 10) + 2
    if len(frame.ts) < warmup + 10:
        return {"decision": "REJECT_SAMPLE", "model_id": config.model_id, "periods": 0}

    cost = max(float(cost_bps_per_turnover), 0.0) / 10_000.0
    weights: dict[str, float] = {}
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    min_equity = 1.0
    gross_exposure_sum = 0.0
    net_exposure_sum = 0.0
    short_exposure_sum = 0.0
    turnover_sum = 0.0
    rebalance_count = 0
    active_periods = 0
    wins = 0
    losses = 0
    period_count = 0
    cost_drag = 0.0
    holding_cost_drag = 0.0
    short_cost_drag = 0.0
    funding_pnl = 0.0
    liquidity_impact_drag = 0.0
    max_trade_volume_pct_seen = 0.0
    capacity_violation_count = 0
    capacity_violation_tolerance_pct = 1.0
    capacity_cap_event_count = 0
    max_capacity_cap_requested_trade_volume_pct = 0.0
    exchange_rule_adjustment_count = 0
    exchange_rule_drop_count = 0
    symbol_weight_cap_event_count = 0
    worst_intrabar_adverse_return = 0.0
    liquidation_event_count = 0
    first_exec_ts: datetime | None = None
    last_period_ts: datetime | None = None
    by_year_start: dict[str, float] = {}
    by_year_end: dict[str, float] = {}
    by_month_start: dict[str, float] = {}
    by_month_end: dict[str, float] = {}
    by_quarter_start: dict[str, float] = {}
    by_quarter_end: dict[str, float] = {}
    rebalance_samples: list[dict[str, Any]] = []
    direction_periods: Counter[str] = Counter()
    symbol_contribution_sum: dict[str, float] = {symbol: 0.0 for symbol in frame.symbols}
    symbol_abs_exposure_sum: dict[str, float] = {symbol: 0.0 for symbol in frame.symbols}
    symbol_long_periods: Counter[str] = Counter()
    symbol_short_periods: Counter[str] = Counter()
    realized_returns: deque[float] = deque(maxlen=_hours_to_bars(config.interval, max(int(vol_lookback_hours), 1)))
    risk_scale_sum = 0.0
    risk_scale_count = 0
    min_risk_scale = math.inf
    max_risk_scale = 0.0
    drawdown_guard_periods = 0
    vol_target_periods = 0
    dispersion_guard_periods = 0
    dispersion_history: deque[float] = deque(maxlen=max(int(dispersion_lookback_rebalances), 0))
    symbol_quality_bars = _hours_to_bars(config.interval, int(symbol_quality_lookback_hours)) if symbol_quality_lookback_hours > 0 else 0
    symbol_quality_enabled = symbol_quality_bars > 0 and int(symbol_quality_drop_count) > 0
    symbol_quality_contribution_history: dict[str, deque[float]] = {
        symbol: deque(maxlen=symbol_quality_bars) for symbol in frame.symbols
    }
    symbol_quality_exposure_history: dict[str, deque[float]] = {
        symbol: deque(maxlen=symbol_quality_bars) for symbol in frame.symbols
    }
    symbol_quality_active_history: dict[str, deque[int]] = {
        symbol: deque(maxlen=symbol_quality_bars) for symbol in frame.symbols
    }
    symbol_quality_block_rebalance_count = 0
    symbol_quality_block_symbol_events = 0
    symbol_quality_block_counts: Counter[str] = Counter()

    first_exec_idx = warmup + 1
    last_exec_idx = len(frame.ts) - 2
    for exec_idx in range(first_exec_idx, last_exec_idx + 1):
        if first_exec_ts is None:
            first_exec_ts = frame.ts[exec_idx]
        should_rebalance = (exec_idx - first_exec_idx) % max(config.rebalance_bars, 1) == 0
        turnover = 0.0
        if should_rebalance:
            signal_idx = exec_idx - 1
            blocked_symbols: set[str] = set()
            if symbol_quality_enabled:
                blocked_symbols = _symbol_quality_blocklist(
                    frame,
                    contribution_history=symbol_quality_contribution_history,
                    exposure_history=symbol_quality_exposure_history,
                    active_history=symbol_quality_active_history,
                    drop_count=int(symbol_quality_drop_count),
                    min_active_periods=max(int(symbol_quality_min_active_periods), 0),
                    min_abs_exposure=max(float(symbol_quality_min_abs_exposure), 0.0),
                    score_threshold=float(symbol_quality_score_threshold),
                )
                if blocked_symbols:
                    symbol_quality_block_rebalance_count += 1
                    symbol_quality_block_symbol_events += len(blocked_symbols)
                    symbol_quality_block_counts.update(blocked_symbols)
            new_weights = _target_weights(
                frame,
                features,
                config,
                signal_idx,
                funding_period_rates=funding_period_rates,
                blocked_symbols=blocked_symbols,
            )
            raw_gross = sum(abs(value) for value in new_weights.values())
            risk_scale = 1.0
            guard_active = False
            live_drawdown = 1.0 - equity / max(peak, 1e-12)
            if drawdown_guard_pct > 0.0 and live_drawdown * 100.0 >= drawdown_guard_pct:
                risk_scale *= max(float(drawdown_risk_scale), 0.0)
                guard_active = True

            vol_scale = 1.0
            if (
                vol_target_annual_pct > 0.0
                and len(realized_returns) >= max(10, realized_returns.maxlen // 2)
            ):
                mean_return = sum(realized_returns) / len(realized_returns)
                variance = sum(
                    (value - mean_return) * (value - mean_return)
                    for value in realized_returns
                ) / len(realized_returns)
                period_vol = math.sqrt(max(variance, 0.0))
                bars_per_year = 365.25 * 24.0 / max(_interval_hours(config.interval), 1e-9)
                realized_vol = period_vol * math.sqrt(bars_per_year)
                target_vol = max(float(vol_target_annual_pct), 0.0) / 100.0
                if realized_vol > 1e-9:
                    vol_scale = target_vol / realized_vol
                    vol_scale = min(max(vol_scale, max(float(vol_min_scale), 0.0)), max(float(vol_max_scale), 0.0))
                    risk_scale *= vol_scale
                    vol_target_periods += 1

            dispersion_scale = 1.0
            dispersion_value = _cross_sectional_momentum_dispersion(frame, features, config, signal_idx)
            if (
                dispersion_history.maxlen
                and math.isfinite(dispersion_value)
                and len(dispersion_history) >= max(10, dispersion_history.maxlen // 2)
                and dispersion_guard_quantile > 0.0
            ):
                threshold = _empirical_quantile(list(dispersion_history), dispersion_guard_quantile)
                if math.isfinite(threshold) and dispersion_value >= threshold:
                    dispersion_scale = max(float(dispersion_risk_scale), 0.0)
                    risk_scale *= dispersion_scale
                    dispersion_guard_periods += 1
            if dispersion_history.maxlen and math.isfinite(dispersion_value):
                dispersion_history.append(dispersion_value)

            new_weights = _scale_weights(new_weights, risk_scale)
            if max_symbol_weight > 0.0:
                new_weights, symbol_cap_events = _clip_symbol_weights(
                    new_weights,
                    max_abs_weight=max_symbol_weight,
                )
                symbol_weight_cap_event_count += symbol_cap_events
            else:
                symbol_cap_events = 0
            if capacity_cap_trade_volume_pct > 0.0:
                new_weights, cap_events, cap_requested_pct = _apply_capacity_cap(
                    frame,
                    old_weights=weights,
                    new_weights=new_weights,
                    signal_idx=signal_idx,
                    equity=equity,
                    assumed_capital_usd=assumed_capital_usd,
                    max_trade_volume_pct=max(float(capacity_cap_trade_volume_pct), 0.0),
                    liquidity_notional_mode=liquidity_notional_mode,
                )
                capacity_cap_event_count += cap_events
                max_capacity_cap_requested_trade_volume_pct = max(
                    max_capacity_cap_requested_trade_volume_pct,
                    cap_requested_pct,
                )
            if exchange_rules:
                new_weights, exchange_adjustments, exchange_drops = _apply_exchange_rules(
                    frame,
                    weights=new_weights,
                    signal_idx=signal_idx,
                    equity=equity,
                    assumed_capital_usd=assumed_capital_usd,
                    pnl_notional_mode=pnl_notional_mode,
                    exchange_rules=exchange_rules,
                )
                exchange_rule_adjustment_count += exchange_adjustments
                exchange_rule_drop_count += exchange_drops
            else:
                exchange_adjustments = 0
                exchange_drops = 0
            risk_scale_sum += risk_scale
            risk_scale_count += 1
            min_risk_scale = min(min_risk_scale, risk_scale)
            max_risk_scale = max(max_risk_scale, risk_scale)
            if guard_active:
                drawdown_guard_periods += 1
            turnover = _turnover(weights, new_weights, frame.symbols)
            liquidity_cost_period = 0.0
            if (
                turnover > 1e-9
                and assumed_capital_usd > 0.0
                and liquidity_impact_bps_per_1pct_volume > 0.0
            ):
                for symbol in frame.symbols:
                    delta_weight = abs(new_weights.get(symbol, 0.0) - weights.get(symbol, 0.0))
                    if delta_weight <= 1e-12:
                        continue
                    quote_volume = _quote_volume_at(frame, symbol, signal_idx)
                    if not math.isfinite(quote_volume) or quote_volume <= 0.0:
                        continue
                    trade_volume_pct = _trade_volume_pct_for_delta(
                        delta_weight=delta_weight,
                        equity=equity,
                        assumed_capital_usd=assumed_capital_usd,
                        quote_volume=quote_volume,
                        liquidity_notional_mode=liquidity_notional_mode,
                    )
                    max_trade_volume_pct_seen = max(max_trade_volume_pct_seen, trade_volume_pct)
                    capacity_limit = max(float(max_trade_volume_pct), 0.0)
                    capacity_tolerance = 1.0 + capacity_violation_tolerance_pct / 100.0
                    if trade_volume_pct > capacity_limit * capacity_tolerance + 1e-12:
                        capacity_violation_count += 1
                    liquidity_cost_period += (
                        delta_weight
                        * _execution_to_pnl_basis_multiplier(
                            equity=equity,
                            execution_notional_mode=liquidity_notional_mode,
                            pnl_notional_mode=pnl_notional_mode,
                        )
                        * max(float(liquidity_impact_bps_per_1pct_volume), 0.0)
                        * trade_volume_pct
                        / 10_000.0
                    )
            if turnover > 1e-9:
                rebalance_count += 1
                if len(rebalance_samples) < 8:
                    rebalance_samples.append(
                        {
                            "exec_ts": frame.ts[exec_idx].isoformat(),
                            "signal_ts": frame.ts[signal_idx].isoformat(),
                            "turnover": round(turnover, 4),
                            "raw_gross": round(raw_gross, 4),
                            "risk_scale": round(risk_scale, 4),
                            "drawdown_pct": round(live_drawdown * 100.0, 4),
                            "vol_scale": round(vol_scale, 4),
                            "dispersion": round(dispersion_value, 6) if math.isfinite(dispersion_value) else None,
                            "dispersion_scale": round(dispersion_scale, 4),
                            "symbol_weight_cap_events": int(symbol_cap_events),
                            "capacity_cap_events": int(cap_events) if capacity_cap_trade_volume_pct > 0.0 else 0,
                            "exchange_rule_adjustments": int(exchange_adjustments),
                            "exchange_rule_drops": int(exchange_drops),
                            "symbol_quality_blocked": sorted(blocked_symbols),
                            "weights": _weights_sample(new_weights),
                        }
                    )
            weights = new_weights
        else:
            liquidity_cost_period = 0.0

        gross_exposure = sum(abs(value) for value in weights.values())
        net_exposure = sum(weights.values())
        short_exposure = sum(abs(value) for value in weights.values() if value < 0.0)
        gross_exposure_sum += gross_exposure
        net_exposure_sum += net_exposure
        short_exposure_sum += short_exposure
        turnover_sum += turnover
        cost_period = turnover * cost
        cost_drag += cost_period
        liquidity_impact_drag += liquidity_cost_period
        period_days = max(
            (frame.ts[exec_idx + 1] - frame.ts[exec_idx]).total_seconds() / 86_400,
            0.0,
        )
        holding_cost_period = (
            gross_exposure
            * max(float(holding_cost_bps_per_day), 0.0)
            / 10_000.0
            * period_days
        )
        short_cost_period = (
            short_exposure
            * max(float(short_cost_bps_per_day), 0.0)
            / 10_000.0
            * period_days
        )
        holding_cost_drag += holding_cost_period
        short_cost_drag += short_cost_period
        if funding_period_rates is not None:
            funding_period = _funding_return_for_period_index(
                funding_period_rates,
                weights,
                exec_idx,
            )
        else:
            funding_period = _funding_return_for_period(
                funding_rates,
                weights,
                frame.open_ms[exec_idx],
                frame.open_ms[exec_idx + 1],
            )
        funding_pnl += funding_period
        intrabar_adverse = _intrabar_adverse_return(frame, weights, exec_idx)
        intrabar_adverse_equity_return = _basis_return_to_equity_return(
            intrabar_adverse,
            equity=equity,
            pnl_notional_mode=pnl_notional_mode,
        )
        worst_intrabar_adverse_return = min(worst_intrabar_adverse_return, intrabar_adverse_equity_return)
        if (
            maintenance_margin_pct > 0.0
            and intrabar_adverse_equity_return <= -(1.0 - max(float(maintenance_margin_pct), 0.0) / 100.0)
        ):
            liquidation_event_count += 1
        portfolio_return = 0.0
        period_symbol_contribution: dict[str, float] = {}
        period_symbol_abs_exposure: dict[str, float] = {}
        for symbol, weight in weights.items():
            symbol_return = frame.returns[symbol][exec_idx]
            if not math.isfinite(symbol_return):
                continue
            contribution = weight * symbol_return
            portfolio_return += contribution
            period_symbol_contribution[symbol] = period_symbol_contribution.get(symbol, 0.0) + contribution
            period_symbol_abs_exposure[symbol] = period_symbol_abs_exposure.get(symbol, 0.0) + abs(weight)
            symbol_contribution_sum[symbol] = symbol_contribution_sum.get(symbol, 0.0) + contribution
            symbol_abs_exposure_sum[symbol] = symbol_abs_exposure_sum.get(symbol, 0.0) + abs(weight)
            if weight > 0.0:
                symbol_long_periods[symbol] += 1
            elif weight < 0.0:
                symbol_short_periods[symbol] += 1
        if symbol_quality_enabled:
            for symbol in frame.symbols:
                abs_exposure = period_symbol_abs_exposure.get(symbol, 0.0)
                symbol_quality_contribution_history[symbol].append(
                    period_symbol_contribution.get(symbol, 0.0)
                )
                symbol_quality_exposure_history[symbol].append(abs_exposure)
                symbol_quality_active_history[symbol].append(1 if abs_exposure > 1e-12 else 0)
        basis_return = (
            portfolio_return
            + funding_period
            - cost_period
            - liquidity_cost_period
            - holding_cost_period
            - short_cost_period
        )
        net_return = _basis_return_to_equity_return(
            basis_return,
            equity=equity,
            pnl_notional_mode=pnl_notional_mode,
        )
        if gross_exposure > 1e-9:
            active_periods += 1
        if net_exposure > 0.05:
            direction_periods["net_long"] += 1
        elif net_exposure < -0.05:
            direction_periods["net_short"] += 1
        else:
            direction_periods["market_neutral_or_flat"] += 1

        year = str(frame.ts[exec_idx + 1].year)
        month = frame.ts[exec_idx + 1].strftime("%Y-%m")
        quarter = f"{frame.ts[exec_idx + 1].year}Q{((frame.ts[exec_idx + 1].month - 1) // 3) + 1}"
        by_year_start.setdefault(year, equity)
        by_month_start.setdefault(month, equity)
        by_quarter_start.setdefault(quarter, equity)
        if net_return <= -0.999:
            equity = 1e-9
        else:
            equity *= 1.0 + net_return
        by_year_end[year] = equity
        by_month_end[month] = equity
        by_quarter_end[quarter] = equity
        peak = max(peak, equity)
        min_equity = min(min_equity, equity)
        max_dd = max(max_dd, 1.0 - equity / max(peak, 1e-12))
        if net_return > 0.0:
            wins += 1
        elif net_return < 0.0:
            losses += 1
        realized_returns.append(net_return)
        period_count += 1
        last_period_ts = frame.ts[exec_idx + 1]
        if equity <= 1e-8:
            break

    years = max(_year_fraction(first_exec_ts, last_period_ts), 1e-9)
    total_return = equity - 1.0
    cagr = (equity ** (1.0 / years) - 1.0) if equity > 0.0 else -1.0
    by_year_return = {
        year: by_year_end[year] / max(by_year_start.get(year, 1.0), 1e-12) - 1.0
        for year in sorted(by_year_end)
    }
    by_month_return = {
        month: by_month_end[month] / max(by_month_start.get(month, 1.0), 1e-12) - 1.0
        for month in sorted(by_month_end)
    }
    by_quarter_return = {
        quarter: by_quarter_end[quarter] / max(by_quarter_start.get(quarter, 1.0), 1e-12) - 1.0
        for quarter in sorted(by_quarter_end)
    }
    positive_years = sum(1 for value in by_year_return.values() if value > 0.0)
    positive_year_fraction = positive_years / max(len(by_year_return), 1)
    return_to_dd = total_return / max(max_dd, 1e-9) if max_dd > 0.0 else 0.0
    calmar = cagr / max(max_dd, 1e-9) if max_dd > 0.0 else 0.0
    avg_gross = gross_exposure_sum / max(period_count, 1)
    avg_net = net_exposure_sum / max(period_count, 1)
    avg_short = short_exposure_sum / max(period_count, 1)
    common_days = max(_year_fraction(first_exec_ts, last_period_ts) * 365.25, 1e-9)
    avg_daily_turnover = turnover_sum / common_days
    active_fraction = active_periods / max(period_count, 1)
    win_rate = wins / max(wins + losses, 1)
    avg_abs_exposure_by_symbol = {
        symbol: value / max(period_count, 1)
        for symbol, value in symbol_abs_exposure_sum.items()
        if abs(value) > 1e-12
    }
    symbol_period_summary = {
        symbol: {
            "avg_abs_exposure": round(avg_abs_exposure_by_symbol.get(symbol, 0.0), 4),
            "long_periods": int(symbol_long_periods.get(symbol, 0)),
            "short_periods": int(symbol_short_periods.get(symbol, 0)),
        }
        for symbol, _ in sorted(
            avg_abs_exposure_by_symbol.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:10]
    }
    score = 0.0
    if total_return > 0.0 and max_dd > 0.0:
        consistency = max(positive_year_fraction, 0.05)
        risk_penalty = 0.35 if max_dd > 0.80 else 1.0
        score = max(calmar, 0.0) * math.log1p(max(total_return, 0.0)) * consistency * risk_penalty

    if period_count <= 0 or years < 1.0:
        decision = "REJECT_SAMPLE"
    elif equity <= 1e-6:
        decision = "REJECT_BANKRUPT"
    elif total_return <= 0.0:
        decision = "REJECT_NEGATIVE"
    elif positive_year_fraction < 0.60:
        decision = "REJECT_INCONSISTENT"
    elif max_dd > 0.90:
        decision = "REJECT_DRAWDOWN"
    elif cagr >= 0.35 and calmar >= 0.60 and positive_year_fraction >= 0.70:
        decision = "PAPER_RESEARCH"
    elif cagr >= 0.20 and calmar >= 0.35:
        decision = "WATCH"
    else:
        decision = "REJECT_WEAK"

    return {
        "model_id": config.model_id,
        "decision": decision,
        "periods": period_count,
        "first_exec_ts": first_exec_ts.isoformat() if first_exec_ts else None,
        "last_period_ts": last_period_ts.isoformat() if last_period_ts else None,
        "years": round(years, 4),
        "total_return_pct": round(total_return * 100.0, 4),
        "cagr_pct": round(cagr * 100.0, 4),
        "max_drawdown_pct": round(max_dd * 100.0, 4),
        "return_to_dd": round(return_to_dd, 4),
        "calmar": round(calmar, 4),
        "min_equity": round(min_equity, 6),
        "rebalance_count": rebalance_count,
        "rebalances_per_year": round(rebalance_count / years, 2),
        "win_rate_period": round(win_rate, 4),
        "active_fraction": round(active_fraction, 4),
        "avg_gross_exposure": round(avg_gross, 4),
        "avg_net_exposure": round(avg_net, 4),
        "avg_short_exposure": round(avg_short, 4),
        "turnover_sum": round(turnover_sum, 4),
        "avg_daily_turnover": round(avg_daily_turnover, 4),
        "cost_drag_pct_simple_sum": round(cost_drag * 100.0, 4),
        "liquidity_impact_drag_pct_simple_sum": round(liquidity_impact_drag * 100.0, 4),
        "holding_cost_drag_pct_simple_sum": round(holding_cost_drag * 100.0, 4),
        "short_cost_drag_pct_simple_sum": round(short_cost_drag * 100.0, 4),
        "funding_pnl_pct_simple_sum": round(funding_pnl * 100.0, 4),
        "max_trade_volume_pct_seen": round(max_trade_volume_pct_seen, 6),
        "max_symbol_weight": float(max_symbol_weight),
        "symbol_weight_cap_event_count": int(symbol_weight_cap_event_count),
        "capacity_violation_count": int(capacity_violation_count),
        "capacity_violation_tolerance_pct": round(capacity_violation_tolerance_pct, 4),
        "capacity_cap_event_count": int(capacity_cap_event_count),
        "capacity_cap_trade_volume_pct": float(capacity_cap_trade_volume_pct),
        "max_capacity_cap_requested_trade_volume_pct": round(max_capacity_cap_requested_trade_volume_pct, 6),
        "exchange_rule_adjustment_count": int(exchange_rule_adjustment_count),
        "exchange_rule_drop_count": int(exchange_rule_drop_count),
        "apply_exchange_rules": bool(exchange_rules),
        "pnl_notional_mode": str(pnl_notional_mode),
        "liquidity_notional_mode": str(liquidity_notional_mode),
        "worst_intrabar_adverse_return_pct": round(worst_intrabar_adverse_return * 100.0, 4),
        "liquidation_event_count": int(liquidation_event_count),
        "maintenance_margin_pct": float(maintenance_margin_pct),
        "positive_year_count": positive_years,
        "year_count": len(by_year_return),
        "positive_year_fraction": round(positive_year_fraction, 4),
        "by_year_return_pct": {year: round(value * 100.0, 4) for year, value in by_year_return.items()},
        "by_quarter_return_pct": {quarter: round(value * 100.0, 4) for quarter, value in by_quarter_return.items()},
        "by_month_return_pct": {month: round(value * 100.0, 4) for month, value in by_month_return.items()},
        "best_year_pct": round(max(by_year_return.values()) * 100.0, 4) if by_year_return else 0.0,
        "worst_year_pct": round(min(by_year_return.values()) * 100.0, 4) if by_year_return else 0.0,
        "direction_period_counts": dict(sorted(direction_periods.items())),
        "risk_overlay": {
            "drawdown_guard_pct": float(drawdown_guard_pct),
            "drawdown_risk_scale": float(drawdown_risk_scale),
            "vol_target_annual_pct": float(vol_target_annual_pct),
            "vol_lookback_hours": int(vol_lookback_hours),
            "vol_min_scale": float(vol_min_scale),
            "vol_max_scale": float(vol_max_scale),
            "dispersion_lookback_rebalances": int(dispersion_lookback_rebalances),
            "dispersion_guard_quantile": float(dispersion_guard_quantile),
            "dispersion_risk_scale": float(dispersion_risk_scale),
            "symbol_quality_lookback_hours": int(symbol_quality_lookback_hours),
            "symbol_quality_drop_count": int(symbol_quality_drop_count),
            "symbol_quality_min_active_periods": int(symbol_quality_min_active_periods),
            "symbol_quality_min_abs_exposure": float(symbol_quality_min_abs_exposure),
            "symbol_quality_score_threshold": float(symbol_quality_score_threshold),
            "symbol_quality_block_rebalance_count": int(symbol_quality_block_rebalance_count),
            "symbol_quality_block_symbol_events": int(symbol_quality_block_symbol_events),
            "symbol_quality_top_block_counts": dict(symbol_quality_block_counts.most_common(10)),
            "avg_risk_scale_at_rebalance": round(risk_scale_sum / max(risk_scale_count, 1), 4),
            "min_risk_scale_at_rebalance": round(min_risk_scale if math.isfinite(min_risk_scale) else 1.0, 4),
            "max_risk_scale_at_rebalance": round(max_risk_scale if risk_scale_count else 1.0, 4),
            "drawdown_guard_rebalance_count": drawdown_guard_periods,
            "vol_target_rebalance_count": vol_target_periods,
            "dispersion_guard_rebalance_count": dispersion_guard_periods,
        },
        "top_symbol_contribution_pct_simple_sum": _top_float_items(
            {symbol: value * 100.0 for symbol, value in symbol_contribution_sum.items()},
            reverse=True,
        ),
        "bottom_symbol_contribution_pct_simple_sum": _top_float_items(
            {symbol: value * 100.0 for symbol, value in symbol_contribution_sum.items()},
            reverse=False,
        ),
        "top_symbol_exposure": symbol_period_summary,
        "rebalance_samples": rebalance_samples,
        "score": round(score, 8),
    }


def _benchmark_frame(frame: MarketFrame, *, cost_bps_per_turnover: float) -> dict[str, Any]:
    if len(frame.ts) < 3:
        return {}
    per_symbol = {}
    for symbol in frame.symbols:
        finite_closes = [value for value in frame.closes[symbol] if math.isfinite(value) and value > 0.0]
        if len(finite_closes) < 2:
            continue
        first = finite_closes[0]
        last = finite_closes[-1]
        per_symbol[symbol] = last / max(first, 1e-12) - 1.0

    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    n = len(frame.symbols)
    for idx in range(len(frame.ts) - 1):
        finite_returns = [
            frame.returns[symbol][idx]
            for symbol in frame.symbols
            if math.isfinite(frame.returns[symbol][idx])
        ]
        if not finite_returns:
            continue
        ret = sum(finite_returns) / len(finite_returns)
        equity *= 1.0 + ret
        peak = max(peak, equity)
        max_dd = max(max_dd, 1.0 - equity / max(peak, 1e-12))

    years = max(_year_fraction(frame.ts[0], frame.ts[-1]), 1e-9)
    cagr = equity ** (1.0 / years) - 1.0 if equity > 0.0 else -1.0
    best_symbol, best_ret = max(per_symbol.items(), key=lambda item: item[1]) if per_symbol else ("", 0.0)
    worst_symbol, worst_ret = min(per_symbol.items(), key=lambda item: item[1]) if per_symbol else ("", 0.0)
    btc_return = per_symbol.get("BTCUSDT")
    initial_turnover_cost = max(float(cost_bps_per_turnover), 0.0) / 10_000.0
    equal_hold_return = sum(per_symbol.values()) / max(n, 1) - initial_turnover_cost
    return {
        "first_ts": frame.ts[0].isoformat(),
        "last_ts": frame.ts[-1].isoformat(),
        "years": round(years, 4),
        "btc_hold_return_pct": round(btc_return * 100.0, 4) if btc_return is not None else None,
        "equal_weight_hold_return_pct_after_initial_cost": round(equal_hold_return * 100.0, 4),
        "equal_weight_rebalanced_return_pct_no_cost": round((equity - 1.0) * 100.0, 4),
        "equal_weight_rebalanced_cagr_pct_no_cost": round(cagr * 100.0, 4),
        "equal_weight_rebalanced_max_dd_pct_no_cost": round(max_dd * 100.0, 4),
        "best_symbol_hold": {"symbol": best_symbol, "return_pct": round(best_ret * 100.0, 4)},
        "worst_symbol_hold": {"symbol": worst_symbol, "return_pct": round(worst_ret * 100.0, 4)},
        "per_symbol_hold_return_pct": {
            symbol: round(value * 100.0, 4)
            for symbol, value in sorted(per_symbol.items(), key=lambda item: item[1], reverse=True)
        },
    }


def _rank_rows(rows: list[dict[str, Any]], key: str, limit: int = 30) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            float(dict(row.get("summary") or {}).get(key, 0.0) or 0.0),
            float(dict(row.get("summary") or {}).get("score", 0.0) or 0.0),
        ),
        reverse=True,
    )[:limit]


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    generated_at = datetime.now(UTC)
    symbols = [symbol.upper() for symbol in _csv(args.symbols)]
    intervals = [interval for interval in _csv(args.intervals) if interval in _INTERVAL_MS] or ["4h"]
    days = max(int(args.days), 30)
    cache_dir = ROOT_DIR / str(args.cache_dir)
    base_url = str(args.base_url or settings.binance_rest_base_url or "https://fapi.binance.com").rstrip("/")
    cost_bps = max(float(args.fee_bps_per_side) + float(args.slippage_bps_per_side), 0.0)
    holding_cost_bps_per_day = max(float(args.holding_cost_bps_per_day), 0.0)
    short_cost_bps_per_day = max(float(args.short_cost_bps_per_day), 0.0)
    drawdown_guard_pct = max(float(args.drawdown_guard_pct), 0.0)
    drawdown_risk_scale = max(float(args.drawdown_risk_scale), 0.0)
    vol_target_annual_pct = max(float(args.vol_target_annual_pct), 0.0)
    vol_lookback_hours = max(int(args.vol_lookback_hours), 1)
    vol_min_scale = max(float(args.vol_min_scale), 0.0)
    vol_max_scale = max(float(args.vol_max_scale), 0.0)
    dispersion_lookback_rebalances = max(int(args.dispersion_lookback_rebalances), 0)
    dispersion_guard_quantile = min(max(float(args.dispersion_guard_quantile), 0.0), 1.0)
    dispersion_risk_scale = max(float(args.dispersion_risk_scale), 0.0)
    symbol_quality_lookback_hours = max(int(args.symbol_quality_lookback_hours), 0)
    symbol_quality_drop_count = max(int(args.symbol_quality_drop_count), 0)
    symbol_quality_min_active_periods = max(int(args.symbol_quality_min_active_periods), 0)
    symbol_quality_min_abs_exposure = max(float(args.symbol_quality_min_abs_exposure), 0.0)
    symbol_quality_score_threshold = float(args.symbol_quality_score_threshold)
    maintenance_margin_pct = max(float(args.maintenance_margin_pct), 0.0)
    assumed_capital_usd = max(float(args.assumed_capital_usd), 0.0)
    pnl_notional_mode = str(args.pnl_notional_mode)
    liquidity_notional_mode = str(args.liquidity_notional_mode)
    liquidity_impact_bps_per_1pct_volume = max(float(args.liquidity_impact_bps_per_1pct_volume), 0.0)
    max_symbol_weight = max(float(args.max_symbol_weight), 0.0)
    max_trade_volume_pct = max(float(args.max_trade_volume_pct), 0.0)
    capacity_cap_trade_volume_pct = max(float(args.capacity_cap_trade_volume_pct), 0.0)
    exchange_rules = (
        _load_exchange_rules(
            base_url=base_url,
            cache_path=ROOT_DIR / str(args.exchange_rules_cache),
        )
        if bool(args.apply_exchange_rules)
        else {}
    )
    configs = _build_configs(args, intervals)
    configs_by_interval: dict[str, list[RotationPortfolioConfig]] = {
        interval: [config for config in configs if config.interval == interval]
        for interval in intervals
    }

    frames: dict[str, MarketFrame] = {}
    data_status: dict[str, Any] = {}
    for interval in intervals:
        bars_by_symbol: dict[str, list[Bar]] = {}
        for symbol in symbols:
            bars_by_symbol[symbol] = _load_bars(
                symbol=symbol,
                interval=interval,
                days=days,
                cache_dir=cache_dir,
                base_url=base_url,
                sleep_seconds=float(args.sleep_seconds),
            )
            print(
                json.dumps(
                    {
                        "loaded": symbol,
                        "interval": interval,
                        "bars": len(bars_by_symbol[symbol]),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        if args.align_mode == "dynamic":
            frame, status = _align_dynamic_frame(interval, bars_by_symbol)
        else:
            frame, status = _align_frame(interval, bars_by_symbol)
        data_status[interval] = status
        if frame is None:
            continue
        common_days = float(status.get("common_days") or 0.0)
        if common_days < float(args.min_common_days):
            status["error"] = "common_history_shorter_than_min_common_days"
            status["min_common_days"] = int(args.min_common_days)
            continue
        frames[interval] = frame

    rows: list[dict[str, Any]] = []
    benchmarks = {
        interval: _benchmark_frame(frame, cost_bps_per_turnover=cost_bps)
        for interval, frame in sorted(frames.items())
    }
    funding_by_interval: dict[str, dict[str, dict[int, float]]] = {}
    funding_period_rates_by_interval: dict[str, dict[str, list[float]]] = {}
    if bool(args.apply_funding):
        funding_cache_dir = ROOT_DIR / str(args.funding_cache_dir)
        for interval, frame in sorted(frames.items()):
            start_ms = int(frame.open_ms[0])
            end_ms = int(frame.open_ms[-1])
            funding_by_interval[interval] = {}
            for symbol in frame.symbols:
                funding_by_interval[interval][symbol] = _load_funding_rates(
                    symbol=symbol,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    cache_dir=funding_cache_dir,
                    base_url=base_url,
                    sleep_seconds=float(args.sleep_seconds),
                )
            funding_period_rates_by_interval[interval] = _build_funding_period_rates(
                frame,
                funding_by_interval[interval],
            )
    for interval, frame in sorted(frames.items()):
        interval_configs = configs_by_interval.get(interval, [])
        features = _build_features(frame, interval_configs)
        for index, config in enumerate(interval_configs, start=1):
            summary = backtest_config(
                frame,
                features,
                config,
                cost_bps_per_turnover=cost_bps,
                holding_cost_bps_per_day=holding_cost_bps_per_day,
                short_cost_bps_per_day=short_cost_bps_per_day,
                drawdown_guard_pct=drawdown_guard_pct,
                drawdown_risk_scale=drawdown_risk_scale,
                vol_target_annual_pct=vol_target_annual_pct,
                vol_lookback_hours=vol_lookback_hours,
                vol_min_scale=vol_min_scale,
                vol_max_scale=vol_max_scale,
                dispersion_lookback_rebalances=dispersion_lookback_rebalances,
                dispersion_guard_quantile=dispersion_guard_quantile,
                dispersion_risk_scale=dispersion_risk_scale,
                symbol_quality_lookback_hours=symbol_quality_lookback_hours,
                symbol_quality_drop_count=symbol_quality_drop_count,
                symbol_quality_min_active_periods=symbol_quality_min_active_periods,
                symbol_quality_min_abs_exposure=symbol_quality_min_abs_exposure,
                symbol_quality_score_threshold=symbol_quality_score_threshold,
                funding_rates=funding_by_interval.get(interval),
                funding_period_rates=funding_period_rates_by_interval.get(interval),
                maintenance_margin_pct=maintenance_margin_pct,
                assumed_capital_usd=assumed_capital_usd,
                pnl_notional_mode=pnl_notional_mode,
                liquidity_notional_mode=liquidity_notional_mode,
                liquidity_impact_bps_per_1pct_volume=liquidity_impact_bps_per_1pct_volume,
                max_symbol_weight=max_symbol_weight,
                max_trade_volume_pct=max_trade_volume_pct,
                capacity_cap_trade_volume_pct=capacity_cap_trade_volume_pct,
                exchange_rules=exchange_rules,
            )
            rows.append({"config": asdict(config), "summary": summary})
            if index % 250 == 0:
                print(
                    json.dumps(
                        {
                            "progress_interval": interval,
                            "models_done": index,
                            "models_total": len(interval_configs),
                            "latest_model": config.model_id,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

    decision_counts = Counter(str(dict(row.get("summary") or {}).get("decision") or "") for row in rows)
    mode_counts = Counter(str(dict(row.get("config") or {}).get("mode") or "") for row in rows)
    output = {
        "schema_version": "multi_asset_rotation_search_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "research_only_no_live_authority_change",
        "scope": {
            "symbols": symbols,
            "days": days,
            "intervals": intervals,
            "align_mode": str(args.align_mode),
            "model_count": len(rows),
            "min_common_days": int(args.min_common_days),
        },
        "cost_model": {
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": float(args.slippage_bps_per_side),
            "cost_bps_per_turnover": cost_bps,
            "holding_cost_bps_per_day": holding_cost_bps_per_day,
            "short_cost_bps_per_day": short_cost_bps_per_day,
            "drawdown_guard_pct": drawdown_guard_pct,
            "drawdown_risk_scale": drawdown_risk_scale,
            "vol_target_annual_pct": vol_target_annual_pct,
            "vol_lookback_hours": vol_lookback_hours,
            "vol_min_scale": vol_min_scale,
            "vol_max_scale": vol_max_scale,
            "dispersion_lookback_rebalances": dispersion_lookback_rebalances,
            "dispersion_guard_quantile": dispersion_guard_quantile,
            "dispersion_risk_scale": dispersion_risk_scale,
            "symbol_quality_lookback_hours": symbol_quality_lookback_hours,
            "symbol_quality_drop_count": symbol_quality_drop_count,
            "symbol_quality_min_active_periods": symbol_quality_min_active_periods,
            "symbol_quality_min_abs_exposure": symbol_quality_min_abs_exposure,
            "symbol_quality_score_threshold": symbol_quality_score_threshold,
            "apply_funding": bool(args.apply_funding),
            "maintenance_margin_pct": maintenance_margin_pct,
            "assumed_capital_usd": assumed_capital_usd,
            "pnl_notional_mode": pnl_notional_mode,
            "liquidity_notional_mode": liquidity_notional_mode,
            "liquidity_impact_bps_per_1pct_volume": liquidity_impact_bps_per_1pct_volume,
            "max_symbol_weight": max_symbol_weight,
            "max_trade_volume_pct": max_trade_volume_pct,
            "capacity_cap_trade_volume_pct": capacity_cap_trade_volume_pct,
            "apply_exchange_rules": bool(args.apply_exchange_rules),
            "exchange_rule_symbol_count": len(exchange_rules),
            "notes": [
                "signals use completed candles and execute at the next candle open",
                "portfolio returns are open-to-open and include turnover cost",
                "gross_leverage scales target notional and turnover cost",
                "pnl_notional_mode=starting disables reinvestment by measuring PnL against starting capital",
                "optional holding and short costs are conservative continuous drags",
                "optional symbol-quality blocking uses only trailing realized contribution before each rebalance",
                "exchange-reported funding is applied only when apply_funding is true",
                "maintenance margin is an approximate intrabar adverse-move check, not exchange bracket liquidation math",
                "queue priority, exact order book depth, and symbol delisting risk are not modeled",
            ],
        },
        "data_status": data_status,
        "benchmarks": benchmarks,
        "decision_counts": dict(sorted(decision_counts.items())),
        "mode_counts": dict(sorted(mode_counts.items())),
        "top_by_score": sorted(
            rows,
            key=lambda row: (
                float(dict(row.get("summary") or {}).get("score", 0.0) or 0.0),
                float(dict(row.get("summary") or {}).get("cagr_pct", 0.0) or 0.0),
                float(dict(row.get("summary") or {}).get("total_return_pct", 0.0) or 0.0),
            ),
            reverse=True,
        )[:30],
        "top_by_return": _rank_rows(rows, "total_return_pct"),
        "top_by_calmar": _rank_rows(rows, "calmar"),
        "all_results": rows,
    }
    if args.write_report:
        report_dir = ROOT_DIR / str(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        out_path = report_dir / f"multi_asset_rotation_search_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        latest_path = report_dir / "latest.json"
        output["report_path"] = str(out_path.relative_to(ROOT_DIR))
        output["latest_report_path"] = str(latest_path.relative_to(ROOT_DIR))
        atomic_write_text(out_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(latest_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))

    printed = {key: value for key, value in output.items() if key != "all_results"}
    print(json.dumps(printed, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
