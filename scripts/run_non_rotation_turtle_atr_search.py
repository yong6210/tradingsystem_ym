#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.report_io import atomic_write_text
from scripts import run_multi_asset_rotation_search as rot
from scripts.run_non_rotation_directional_search import (
    DEFAULT_SYMBOLS,
    SymbolFeatureEngine,
    _csv,
    _hours_to_bars,
    _load_frame,
    _load_funding,
    _quantile,
    _trailing_sum,
    _vol_scale,
)


@dataclass(frozen=True, slots=True)
class TurtleAtrConfig:
    name: str
    interval: str
    sleeve: str
    symbol_weights: dict[str, float]
    direction_mode: str
    entry_bars: int
    exit_bars: int
    atr_bars: int
    ema_bars: int
    stop_atr: float
    trail_atr: float
    risk_pct: float
    gross_cap: float
    rebalance_bars: int
    funding_lookback_bars: int
    funding_threshold: float
    funding_against_scale: float
    drawdown_guard_pct: float
    drawdown_risk_scale: float
    vol_target_annual_pct: float
    vol_target_mode: str
    vol_lookback_bars: int
    vol_min_scale: float
    vol_max_scale: float


@dataclass(slots=True)
class PositionState:
    side: int
    weight: float
    stop: float
    entry_price: float
    bars_held: int = 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only non-rotation Turtle/Donchian ATR-stop search."
    )
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument("--days", type=int, default=1825)
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument("--short-cost-bps-per-day", type=float, default=0.0)
    parser.add_argument("--holding-cost-bps-per-day", type=float, default=0.0)
    parser.add_argument("--apply-funding", action="store_true", default=True)
    parser.add_argument("--funding-cache-dir", default="reports/validation/multi_asset_rotation_search/funding_cache")
    parser.add_argument("--cache-dir", default="reports/validation/multi_asset_rotation_search/cache")
    parser.add_argument("--report-dir", default="reports/validation/non_rotation_turtle_atr_currentdata_20260526")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    parser.add_argument("--max-configs", type=int, default=0)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _funding_gate_scale(
    funding_period_rates: dict[str, list[float]] | None,
    *,
    symbol: str,
    idx: int,
    side: int,
    lookback_bars: int,
    threshold: float,
    against_scale: float,
) -> float:
    if not funding_period_rates or side == 0:
        return 1.0
    values = funding_period_rates.get(symbol) or []
    if not values or idx >= len(values):
        return 1.0
    trailing = _trailing_sum(values, idx, lookback_bars)
    if not math.isfinite(trailing):
        return 1.0
    if side > 0 and trailing > threshold:
        return max(float(against_scale), 0.0)
    if side < 0 and trailing < -threshold:
        return max(float(against_scale), 0.0)
    return 1.0


def _entry_side(
    engine: SymbolFeatureEngine,
    *,
    idx: int,
    config: TurtleAtrConfig,
) -> int:
    close = engine.closes[idx]
    if not math.isfinite(close):
        return 0
    entry_high = engine.rolling_high_prev(config.entry_bars)[idx]
    entry_low = engine.rolling_low_prev(config.entry_bars)[idx]
    ema = engine.ema(config.ema_bars)[idx]
    trend_up = math.isfinite(ema) and close >= ema
    trend_down = math.isfinite(ema) and close <= ema
    if math.isfinite(entry_high) and close > entry_high and trend_up:
        return 1
    if (
        config.direction_mode == "long_short"
        and math.isfinite(entry_low)
        and close < entry_low
        and trend_down
    ):
        return -1
    return 0


def _exit_signal(
    engine: SymbolFeatureEngine,
    *,
    idx: int,
    side: int,
    config: TurtleAtrConfig,
) -> bool:
    close = engine.closes[idx]
    if not math.isfinite(close) or side == 0:
        return True
    exit_high = engine.rolling_high_prev(config.exit_bars)[idx]
    exit_low = engine.rolling_low_prev(config.exit_bars)[idx]
    ema = engine.ema(config.ema_bars)[idx]
    if side > 0:
        return (math.isfinite(exit_low) and close < exit_low) or (math.isfinite(ema) and close < ema)
    return (math.isfinite(exit_high) and close > exit_high) or (math.isfinite(ema) and close > ema)


def _target_weight(
    engine: SymbolFeatureEngine,
    *,
    symbol_weight: float,
    side: int,
    idx: int,
    config: TurtleAtrConfig,
    risk_scale: float,
    funding_scale: float,
) -> tuple[float, float]:
    close = engine.closes[idx]
    atr = engine.atr(config.atr_bars)[idx]
    if side == 0 or not (math.isfinite(close) and close > 0.0 and math.isfinite(atr) and atr > 0.0):
        return 0.0, math.nan
    stop_distance = max(config.stop_atr * atr, close * 0.002)
    stop_return = stop_distance / close
    risk_budget = max(config.risk_pct, 0.0) / 100.0 * max(symbol_weight, 0.0)
    risk_weight = risk_budget / max(stop_return, 1e-9)
    cap = max(symbol_weight, 0.0) * max(config.gross_cap, 0.0)
    abs_weight = min(risk_weight, cap) * max(risk_scale, 0.0) * max(funding_scale, 0.0)
    stop = close - stop_distance if side > 0 else close + stop_distance
    return side * abs_weight, stop


def _scenario_args(args: argparse.Namespace) -> list[dict[str, float | str]]:
    return [
        {
            "name": "default",
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": float(args.slippage_bps_per_side),
            "holding_cost_bps_per_day": float(args.holding_cost_bps_per_day),
            "short_cost_bps_per_day": float(args.short_cost_bps_per_day),
        },
        {
            "name": "slip5",
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": 5.0,
            "holding_cost_bps_per_day": float(args.holding_cost_bps_per_day),
            "short_cost_bps_per_day": float(args.short_cost_bps_per_day),
        },
        {
            "name": "slip10",
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": 10.0,
            "holding_cost_bps_per_day": float(args.holding_cost_bps_per_day),
            "short_cost_bps_per_day": float(args.short_cost_bps_per_day),
        },
        {
            "name": "short5_slip5",
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": 5.0,
            "holding_cost_bps_per_day": float(args.holding_cost_bps_per_day),
            "short_cost_bps_per_day": 5.0,
        },
    ]


def _year_fraction(first: datetime | None, last: datetime | None) -> float:
    if first is None or last is None or last <= first:
        return 0.0
    return (last - first).total_seconds() / (365.25 * 86_400)


def backtest_config(
    frame: rot.MarketFrame,
    engines: dict[str, SymbolFeatureEngine],
    config: TurtleAtrConfig,
    *,
    funding_period_rates: dict[str, list[float]] | None,
    fee_bps_per_side: float,
    slippage_bps_per_side: float,
    holding_cost_bps_per_day: float,
    short_cost_bps_per_day: float,
) -> dict[str, Any]:
    warmup = max(
        80,
        config.entry_bars + 5,
        config.exit_bars + 5,
        config.atr_bars + 5,
        config.ema_bars + 5,
        config.vol_lookback_bars + 5,
    )
    if len(frame.ts) < warmup + 20:
        return {"decision": "REJECT_SAMPLE", "periods": 0}

    positions: dict[str, PositionState] = {}
    equity = 1.0
    peak = 1.0
    min_equity = 1.0
    max_dd = 0.0
    wins = 0
    losses = 0
    period_count = 0
    active_periods = 0
    turnover_sum = 0.0
    cost_drag = 0.0
    holding_cost_drag = 0.0
    short_cost_drag = 0.0
    funding_pnl = 0.0
    gross_exposure_sum = 0.0
    net_exposure_sum = 0.0
    short_exposure_sum = 0.0
    stop_exit_count = 0
    signal_exit_count = 0
    entry_count = 0
    rebalance_count = 0
    drawdown_guard_periods = 0
    vol_target_periods = 0
    by_year_start: dict[str, float] = {}
    by_year_end: dict[str, float] = {}
    period_returns: list[float] = []
    realized_returns: deque[float] = deque(maxlen=max(config.vol_lookback_bars, 10))
    direction_periods: Counter[str] = Counter()
    symbol_abs_exposure_sum: dict[str, float] = {symbol: 0.0 for symbol in frame.symbols}
    symbol_long_periods: Counter[str] = Counter()
    symbol_short_periods: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    first_exec_ts: datetime | None = None
    last_period_ts: datetime | None = None
    cost_bps = max(float(fee_bps_per_side), 0.0) + max(float(slippage_bps_per_side), 0.0)

    first_exec_idx = warmup + 1
    last_exec_idx = len(frame.ts) - 2
    for exec_idx in range(first_exec_idx, last_exec_idx + 1):
        if first_exec_ts is None:
            first_exec_ts = frame.ts[exec_idx]
        signal_idx = exec_idx - 1
        live_drawdown = 1.0 - equity / max(peak, 1e-12)
        risk_scale = 1.0
        if config.drawdown_guard_pct > 0.0 and live_drawdown * 100.0 >= config.drawdown_guard_pct:
            risk_scale *= max(config.drawdown_risk_scale, 0.0)
            drawdown_guard_periods += 1
        vol_scale = _vol_scale(
            realized_returns,
            interval=config.interval,
            target_annual_pct=config.vol_target_annual_pct,
            mode=config.vol_target_mode,
            min_scale=config.vol_min_scale,
            max_scale=config.vol_max_scale,
        )
        if vol_scale != 1.0:
            vol_target_periods += 1
        risk_scale *= vol_scale

        turnover = 0.0
        should_rebalance = (exec_idx - first_exec_idx) % max(config.rebalance_bars, 1) == 0
        for symbol, sleeve_weight in config.symbol_weights.items():
            engine = engines.get(symbol)
            if engine is None:
                continue
            pos = positions.get(symbol)
            old_weight = pos.weight if pos else 0.0
            if pos is not None and _exit_signal(engine, idx=signal_idx, side=pos.side, config=config):
                turnover += abs(old_weight)
                signal_exit_count += 1
                positions.pop(symbol, None)
                pos = None
            if pos is None:
                side = _entry_side(engine, idx=signal_idx, config=config)
                if side != 0:
                    funding_scale = _funding_gate_scale(
                        funding_period_rates,
                        symbol=symbol,
                        idx=signal_idx,
                        side=side,
                        lookback_bars=config.funding_lookback_bars,
                        threshold=config.funding_threshold,
                        against_scale=config.funding_against_scale,
                    )
                    target, stop = _target_weight(
                        engine,
                        symbol_weight=sleeve_weight,
                        side=side,
                        idx=signal_idx,
                        config=config,
                        risk_scale=risk_scale,
                        funding_scale=funding_scale,
                    )
                    if abs(target) > 1e-12 and math.isfinite(stop):
                        entry_price = frame.opens[symbol][exec_idx]
                        if math.isfinite(entry_price) and entry_price > 0.0:
                            positions[symbol] = PositionState(
                                side=side,
                                weight=target,
                                stop=stop,
                                entry_price=entry_price,
                            )
                            turnover += abs(target)
                            entry_count += 1
            elif should_rebalance:
                funding_scale = _funding_gate_scale(
                    funding_period_rates,
                    symbol=symbol,
                    idx=signal_idx,
                    side=pos.side,
                    lookback_bars=config.funding_lookback_bars,
                    threshold=config.funding_threshold,
                    against_scale=config.funding_against_scale,
                )
                target, new_stop = _target_weight(
                    engine,
                    symbol_weight=sleeve_weight,
                    side=pos.side,
                    idx=signal_idx,
                    config=config,
                    risk_scale=risk_scale,
                    funding_scale=funding_scale,
                )
                if abs(target) <= 1e-12:
                    turnover += abs(pos.weight)
                    positions.pop(symbol, None)
                else:
                    turnover += abs(target - pos.weight)
                    pos.weight = target
                    if pos.side > 0:
                        pos.stop = max(pos.stop, new_stop)
                    else:
                        pos.stop = min(pos.stop, new_stop)
                    rebalance_count += 1

        cost_period = turnover * cost_bps / 10_000.0
        cost_drag += cost_period
        turnover_sum += turnover
        weights = {symbol: pos.weight for symbol, pos in positions.items()}
        gross_exposure = sum(abs(value) for value in weights.values())
        net_exposure = sum(weights.values())
        short_exposure = sum(abs(value) for value in weights.values() if value < 0.0)
        gross_exposure_sum += gross_exposure
        net_exposure_sum += net_exposure
        short_exposure_sum += short_exposure
        period_days = max((frame.ts[exec_idx + 1] - frame.ts[exec_idx]).total_seconds() / 86_400, 0.0)
        holding_cost_period = gross_exposure * max(float(holding_cost_bps_per_day), 0.0) / 10_000.0 * period_days
        short_cost_period = short_exposure * max(float(short_cost_bps_per_day), 0.0) / 10_000.0 * period_days
        holding_cost_drag += holding_cost_period
        short_cost_drag += short_cost_period
        funding_period = rot._funding_return_for_period_index(funding_period_rates, weights, exec_idx)
        funding_pnl += funding_period

        portfolio_return = 0.0
        stopped_symbols: list[str] = []
        for symbol, pos in list(positions.items()):
            open_price = frame.opens[symbol][exec_idx]
            next_open = frame.opens[symbol][exec_idx + 1]
            high = frame.highs[symbol][exec_idx]
            low = frame.lows[symbol][exec_idx]
            if not (math.isfinite(open_price) and open_price > 0.0 and math.isfinite(next_open) and next_open > 0.0):
                continue
            exit_price = next_open
            stopped = False
            if pos.side > 0 and math.isfinite(low) and low <= pos.stop:
                exit_price = min(max(pos.stop, 1e-12), open_price)
                stopped = True
            elif pos.side < 0 and math.isfinite(high) and high >= pos.stop:
                exit_price = max(pos.stop, open_price)
                stopped = True
            symbol_return = exit_price / open_price - 1.0
            portfolio_return += pos.weight * symbol_return
            symbol_abs_exposure_sum[symbol] += abs(pos.weight)
            if pos.weight > 0.0:
                symbol_long_periods[symbol] += 1
            elif pos.weight < 0.0:
                symbol_short_periods[symbol] += 1
            if stopped:
                stopped_symbols.append(symbol)
                turnover_sum += abs(pos.weight)
                stop_exit_count += 1
                cost_drag += abs(pos.weight) * cost_bps / 10_000.0
                portfolio_return -= abs(pos.weight) * cost_bps / 10_000.0
            else:
                atr = engines[symbol].atr(config.atr_bars)[signal_idx]
                close = engines[symbol].closes[signal_idx]
                if math.isfinite(atr) and atr > 0.0 and math.isfinite(close):
                    if pos.side > 0:
                        pos.stop = max(pos.stop, close - config.trail_atr * atr)
                    else:
                        pos.stop = min(pos.stop, close + config.trail_atr * atr)
                pos.bars_held += 1
        for symbol in stopped_symbols:
            positions.pop(symbol, None)

        net_return = portfolio_return + funding_period - cost_period - holding_cost_period - short_cost_period
        if gross_exposure > 1e-9:
            active_periods += 1
        if net_exposure > 0.05:
            direction_periods["net_long"] += 1
        elif net_exposure < -0.05:
            direction_periods["net_short"] += 1
        else:
            direction_periods["market_neutral_or_flat"] += 1
        year = str(frame.ts[exec_idx + 1].year)
        by_year_start.setdefault(year, equity)
        if net_return <= -0.999:
            equity = 1e-9
        else:
            equity *= 1.0 + net_return
        by_year_end[year] = equity
        peak = max(peak, equity)
        min_equity = min(min_equity, equity)
        max_dd = max(max_dd, 1.0 - equity / max(peak, 1e-12))
        if net_return > 0.0:
            wins += 1
        elif net_return < 0.0:
            losses += 1
        period_returns.append(net_return)
        realized_returns.append(net_return)
        period_count += 1
        last_period_ts = frame.ts[exec_idx + 1]
        if len(samples) < 8 and (turnover > 1e-12 or stopped_symbols):
            samples.append(
                {
                    "ts": frame.ts[exec_idx].isoformat(),
                    "turnover": round(turnover, 4),
                    "risk_scale": round(risk_scale, 4),
                    "drawdown_pct": round(live_drawdown * 100.0, 4),
                    "stopped_symbols": stopped_symbols,
                    "weights": {symbol: round(pos.weight, 4) for symbol, pos in sorted(positions.items())},
                }
            )
        if equity <= 1e-8:
            break

    years = max(_year_fraction(first_exec_ts, last_period_ts), 1e-9)
    total_return = equity - 1.0
    cagr = (equity ** (1.0 / years) - 1.0) if equity > 0.0 else -1.0
    by_year_return = {
        year: by_year_end[year] / max(by_year_start.get(year, 1.0), 1e-12) - 1.0
        for year in sorted(by_year_end)
    }
    positive_years = sum(1 for value in by_year_return.values() if value > 0.0)
    worst_year = min(by_year_return.values()) if by_year_return else 0.0
    returns_clean = [value for value in period_returns if math.isfinite(value)]
    period_mean = sum(returns_clean) / max(len(returns_clean), 1)
    period_var = (
        sum((value - period_mean) * (value - period_mean) for value in returns_clean) / max(len(returns_clean), 1)
        if returns_clean
        else 0.0
    )
    bars_per_year = 365.25 * 24.0 / max(rot._interval_hours(config.interval), 1e-9)
    ann_vol = math.sqrt(max(period_var, 0.0)) * math.sqrt(bars_per_year)
    sharpe = period_mean * bars_per_year / max(ann_vol, 1e-12) if ann_vol > 0.0 else 0.0
    avg_gross = gross_exposure_sum / max(period_count, 1)
    avg_net = net_exposure_sum / max(period_count, 1)
    avg_short = short_exposure_sum / max(period_count, 1)
    win_rate = wins / max(wins + losses, 1)
    return_to_dd = total_return / max(max_dd, 1e-9) if max_dd > 0.0 else 0.0
    calmar = cagr / max(max_dd, 1e-9) if max_dd > 0.0 else 0.0
    positive_year_fraction = positive_years / max(len(by_year_return), 1)
    if period_count <= 0 or years < 1.0:
        decision = "REJECT_SAMPLE"
    elif equity <= 1e-6:
        decision = "REJECT_BANKRUPT"
    elif total_return <= 0.0:
        decision = "REJECT_NEGATIVE"
    elif max_dd > 0.80:
        decision = "REJECT_DRAWDOWN"
    elif cagr >= 0.45 and calmar >= 0.80 and positive_year_fraction >= 0.70:
        decision = "PAPER_RESEARCH"
    elif cagr >= 0.25 and calmar >= 0.45:
        decision = "WATCH"
    else:
        decision = "REJECT_WEAK"
    return {
        "model_id": config.name,
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
        "sharpe_like": round(sharpe, 4),
        "annualized_vol_pct": round(ann_vol * 100.0, 4),
        "min_equity": round(min_equity, 6),
        "worst_year_pct": round(worst_year * 100.0, 4),
        "positive_year_count": positive_years,
        "year_count": len(by_year_return),
        "positive_year_fraction": round(positive_year_fraction, 4),
        "by_year_return_pct": {year: round(value * 100.0, 4) for year, value in by_year_return.items()},
        "entry_count": int(entry_count),
        "stop_exit_count": int(stop_exit_count),
        "signal_exit_count": int(signal_exit_count),
        "rebalance_count": int(rebalance_count),
        "win_rate_period": round(win_rate, 4),
        "active_fraction": round(active_periods / max(period_count, 1), 4),
        "avg_gross_exposure": round(avg_gross, 4),
        "avg_net_exposure": round(avg_net, 4),
        "avg_short_exposure": round(avg_short, 4),
        "turnover_sum": round(turnover_sum, 4),
        "avg_daily_turnover": round(turnover_sum / max(years * 365.25, 1e-9), 4),
        "cost_drag_pct_simple_sum": round(cost_drag * 100.0, 4),
        "holding_cost_drag_pct_simple_sum": round(holding_cost_drag * 100.0, 4),
        "short_cost_drag_pct_simple_sum": round(short_cost_drag * 100.0, 4),
        "funding_pnl_pct_simple_sum": round(funding_pnl * 100.0, 4),
        "p05_period_return_pct": round(_quantile(returns_clean, 0.05) * 100.0, 4) if returns_clean else None,
        "p01_period_return_pct": round(_quantile(returns_clean, 0.01) * 100.0, 4) if returns_clean else None,
        "drawdown_guard_periods": int(drawdown_guard_periods),
        "vol_target_periods": int(vol_target_periods),
        "direction_periods": dict(direction_periods),
        "symbol_period_summary": {
            symbol: {
                "avg_abs_exposure": round(symbol_abs_exposure_sum.get(symbol, 0.0) / max(period_count, 1), 4),
                "long_periods": int(symbol_long_periods.get(symbol, 0)),
                "short_periods": int(symbol_short_periods.get(symbol, 0)),
            }
            for symbol in config.symbol_weights
        },
        "samples": samples,
    }


def _risk_profiles(interval: str) -> list[dict[str, float | int | str]]:
    return [
        {
            "tag": "plain",
            "dd": 0.0,
            "dd_scale": 1.0,
            "vt": 0.0,
            "vt_mode": "all",
            "vt_lb": _hours_to_bars(interval, 720),
            "vt_min": 0.0,
            "vt_max": 1.0,
        },
        {
            "tag": "dd20_down60",
            "dd": 20.0,
            "dd_scale": 0.30,
            "vt": 60.0,
            "vt_mode": "downside",
            "vt_lb": _hours_to_bars(interval, 720),
            "vt_min": 0.0,
            "vt_max": 1.0,
        },
    ]


def build_configs(interval: str) -> list[TurtleAtrConfig]:
    sleeves: list[tuple[str, dict[str, float]]] = [
        ("btc100", {"BTCUSDT": 1.0}),
        ("btce6040", {"BTCUSDT": 0.60, "ETHUSDT": 0.40}),
        ("btes_equal", {"BTCUSDT": 1.0 / 3.0, "ETHUSDT": 1.0 / 3.0, "SOLUSDT": 1.0 / 3.0}),
    ]
    windows = (
        (480, 168),
        (720, 240),
        (1200, 336),
    )
    configs: list[TurtleAtrConfig] = []
    for sleeve_name, symbol_weights in sleeves:
        for direction_mode in ("long_only", "long_short"):
            for entry_h, exit_h in windows:
                for risk_pct in (1.0, 2.0, 3.0):
                    for gross_cap in (2.0, 4.0):
                        for stop_atr, trail_atr in ((3.0, 4.0), (4.0, 5.0)):
                            for risk in _risk_profiles(interval):
                                tag = (
                                    f"{sleeve_name}_{direction_mode}_e{entry_h}_x{exit_h}"
                                    f"_r{str(risk_pct).replace('.', 'p')}"
                                    f"_g{str(gross_cap).replace('.', 'p')}"
                                    f"_s{str(stop_atr).replace('.', 'p')}_{risk['tag']}"
                                )
                                configs.append(
                                    TurtleAtrConfig(
                                        name=tag,
                                        interval=interval,
                                        sleeve=sleeve_name,
                                        symbol_weights=symbol_weights,
                                        direction_mode=direction_mode,
                                        entry_bars=_hours_to_bars(interval, entry_h),
                                        exit_bars=_hours_to_bars(interval, exit_h),
                                        atr_bars=_hours_to_bars(interval, 168),
                                        ema_bars=_hours_to_bars(interval, 720),
                                        stop_atr=float(stop_atr),
                                        trail_atr=float(trail_atr),
                                        risk_pct=float(risk_pct),
                                        gross_cap=float(gross_cap),
                                        rebalance_bars=_hours_to_bars(interval, 24),
                                        funding_lookback_bars=_hours_to_bars(interval, 168),
                                        funding_threshold=0.0015,
                                        funding_against_scale=0.50,
                                        drawdown_guard_pct=float(risk["dd"]),
                                        drawdown_risk_scale=float(risk["dd_scale"]),
                                        vol_target_annual_pct=float(risk["vt"]),
                                        vol_target_mode=str(risk["vt_mode"]),
                                        vol_lookback_bars=int(risk["vt_lb"]),
                                        vol_min_scale=float(risk["vt_min"]),
                                        vol_max_scale=float(risk["vt_max"]),
                                    )
                                )
    return configs


def _aggregate_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_name.setdefault(str(row["config"]["name"]), []).append(row)
    out: list[dict[str, Any]] = []
    for name, items in by_name.items():
        xs = [1.0 + float(item["summary"]["total_return_pct"]) / 100.0 for item in items]
        if not xs:
            continue
        default = next((item for item in items if item["scenario"] == "default"), items[0])
        out.append(
            {
                "name": name,
                "min_x": round(min(xs), 6),
                "geo_x": round(math.prod(xs) ** (1.0 / len(xs)), 6),
                "max_x": round(max(xs), 6),
                "default_x": round(1.0 + float(default["summary"]["total_return_pct"]) / 100.0, 6),
                "max_drawdown_pct": round(max(float(item["summary"]["max_drawdown_pct"]) for item in items), 4),
                "worst_year_pct": round(min(float(item["summary"]["worst_year_pct"]) for item in items), 4),
                "avg_gross_exposure": float(default["summary"]["avg_gross_exposure"]),
                "turnover_sum": float(default["summary"]["turnover_sum"]),
                "decision_default": str(default["summary"]["decision"]),
                "config": default["config"],
            }
        )
    return sorted(out, key=lambda item: (item["geo_x"], item["min_x"]), reverse=True)


def main() -> int:
    args = _parse_args()
    frame, frame_meta = _load_frame(args)
    print(
        json.dumps(
            {
                "stage": "loaded_frame",
                "symbols": frame.symbols,
                "bars": len(frame.ts),
                "first": frame.ts[0].isoformat(),
                "last": frame.ts[-1].isoformat(),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    funding_period_rates = _load_funding(args, frame)
    engines = {symbol: SymbolFeatureEngine(frame, symbol) for symbol in frame.symbols}
    configs = build_configs(str(args.interval))
    if int(args.max_configs) > 0:
        configs = configs[: int(args.max_configs)]
    scenarios = _scenario_args(args)
    all_results: list[dict[str, Any]] = []
    for cfg_idx, config in enumerate(configs, start=1):
        if cfg_idx % 100 == 0:
            print(json.dumps({"stage": "progress", "config": cfg_idx, "total": len(configs)}), flush=True)
        for scenario in scenarios:
            summary = backtest_config(
                frame,
                engines,
                config,
                funding_period_rates=funding_period_rates,
                fee_bps_per_side=float(scenario["fee_bps_per_side"]),
                slippage_bps_per_side=float(scenario["slippage_bps_per_side"]),
                holding_cost_bps_per_day=float(scenario["holding_cost_bps_per_day"]),
                short_cost_bps_per_day=float(scenario["short_cost_bps_per_day"]),
            )
            all_results.append(
                {
                    "scenario": str(scenario["name"]),
                    "scenario_params": scenario,
                    "config": asdict(config),
                    "summary": summary,
                }
            )
    aggregate = _aggregate_results(all_results)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "research_scope": {
            "rotation_excluded": True,
            "description": "Fixed symbol sleeves with independent Turtle/Donchian entries, ATR stops, and ATR risk sizing. No top-k, no relative ranking, no capital rotation.",
        },
        "args": vars(args),
        "frame_meta": frame_meta,
        "scenario_count": len(scenarios),
        "config_count": len(configs),
        "all_results": all_results,
        "top_robust": aggregate[:50],
        "top_risk_filtered": [
            item
            for item in aggregate
            if float(item["min_x"]) >= 3.0 and float(item["max_drawdown_pct"]) <= 35.0
        ][:50],
    }
    report_dir = ROOT_DIR / str(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    latest_path = report_dir / "latest.json"
    atomic_write_text(latest_path, json.dumps(payload, ensure_ascii=False, indent=2))
    print(json.dumps({"stage": "done", "report": str(latest_path), "top": aggregate[:10]}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
