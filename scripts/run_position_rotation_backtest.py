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
from typing import Any, Literal

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text
from scripts.run_btc_flip_rotation_search import (
    _INTERVAL_MS,
    _csv,
    _load_bars,
    _year_fraction,
    FeatureSet,
)


Side = Literal["long", "short", "flat"]


@dataclass(frozen=True, slots=True)
class PositionRotationConfig:
    model_id: str
    interval: str
    fast: int
    slow: int
    trend_band_atr: float
    breakout_lookback: int
    trim_atr: float
    pullback_atr: float
    min_active_fraction: float
    max_account_exposure: float
    exchange_leverage: float
    maintenance_margin_pct: float
    rebalance_bars: int
    min_turnover_delta: float
    always_in: bool = True


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only long/short position-rotation backtest with scaling and 10x leverage accounting."
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--days", type=int, default=1825)
    parser.add_argument("--intervals", default="5m,15m,30m,1h")
    parser.add_argument("--exchange-leverage", type=float, default=10.0)
    parser.add_argument(
        "--max-account-exposures",
        default="1,2,3,5,10",
        help="Account-level gross notional caps. 2 means 200%% account notional; with 10x exchange leverage it uses about 20%% margin.",
    )
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument("--maintenance-margin-pct", type=float, default=0.5)
    parser.add_argument(
        "--rebalance-bars",
        default="1",
        help="Comma-separated same-side scale adjustment cadence in bars. Side flips are still immediate.",
    )
    parser.add_argument(
        "--min-turnover-deltas",
        default="0",
        help="Comma-separated minimum same-side weight change required before resizing.",
    )
    parser.add_argument("--min-periods", type=int, default=2000)
    parser.add_argument("--max-models", type=int, default=0)
    parser.add_argument("--cache-dir", default="reports/validation/btc_flip_rotation_search/cache")
    parser.add_argument("--report-dir", default="reports/validation/position_rotation_backtest")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _parse_float_csv(raw: str) -> list[float]:
    out: list[float] = []
    for item in _csv(raw):
        try:
            value = float(item)
        except ValueError:
            continue
        if value > 0.0:
            out.append(value)
    return out or [1.0, 2.0, 3.0]


def _parse_nonnegative_float_csv(raw: str) -> list[float]:
    out: list[float] = []
    for item in _csv(raw):
        try:
            value = float(item)
        except ValueError:
            continue
        if value >= 0.0:
            out.append(value)
    return out or [0.0]


def _parse_int_csv(raw: str, *, minimum: int = 1) -> list[int]:
    out: list[int] = []
    for item in _csv(raw):
        try:
            value = int(item)
        except ValueError:
            continue
        if value >= minimum:
            out.append(value)
    return out or [minimum]


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(float(value), float(low)), float(high))


def _sign(value: float, threshold: float) -> int:
    if not math.isfinite(value):
        return 0
    if value > threshold:
        return 1
    if value < -threshold:
        return -1
    return 0


def _side_name(value: float) -> Side:
    if value > 1e-12:
        return "long"
    if value < -1e-12:
        return "short"
    return "flat"


def _same_sign(left: float, right: float) -> bool:
    return (left > 0.0 and right > 0.0) or (left < 0.0 and right < 0.0)


def build_configs(
    *,
    intervals: list[str],
    max_account_exposures: list[float],
    rebalance_bars_options: list[int],
    min_turnover_deltas: list[float],
    exchange_leverage: float,
    maintenance_margin_pct: float,
) -> list[PositionRotationConfig]:
    configs: list[PositionRotationConfig] = []
    for interval in intervals:
        for fast, slow in ((5, 34), (8, 55), (13, 89), (21, 144)):
            for band in (0.05, 0.15, 0.35):
                for lookback in (12, 24, 48, 96):
                    for trim_atr in (1.2, 2.0):
                        for max_exposure in max_account_exposures:
                            for rebalance_bars in rebalance_bars_options:
                                for min_delta in min_turnover_deltas:
                                    configs.append(
                                        PositionRotationConfig(
                                            model_id=(
                                                f"{interval}:pos_rotation:ema{fast}_{slow}:band{band}:"
                                                f"don{lookback}:trim{trim_atr}:gross{max_exposure:g}:"
                                                f"rb{rebalance_bars}:mind{min_delta:g}:lev{exchange_leverage:g}"
                                            ),
                                            interval=interval,
                                            fast=fast,
                                            slow=slow,
                                            trend_band_atr=band,
                                            breakout_lookback=lookback,
                                            trim_atr=trim_atr,
                                            pullback_atr=0.60,
                                            min_active_fraction=0.25,
                                            max_account_exposure=max_exposure,
                                            exchange_leverage=exchange_leverage,
                                            maintenance_margin_pct=maintenance_margin_pct,
                                            rebalance_bars=rebalance_bars,
                                            min_turnover_delta=min_delta,
                                            always_in=True,
                                        )
                                    )
    return configs


def _target_exposure(
    features: FeatureSet,
    idx: int,
    config: PositionRotationConfig,
    *,
    previous_side: int,
) -> tuple[float, dict[str, Any]]:
    close = features.c[idx]
    atr = max(features.atr[idx], 1e-12)
    fast_ema = features.ema(config.fast)[idx]
    slow_ema = features.ema(config.slow)[idx]
    spread = (fast_ema - slow_ema) / atr if math.isfinite(fast_ema) and math.isfinite(slow_ema) else math.nan
    trend_side = _sign(spread, config.trend_band_atr)

    highs = features.rolling_high_prev(config.breakout_lookback)
    lows = features.rolling_low_prev(config.breakout_lookback)
    breakout_side = 0
    if close > highs[idx]:
        breakout_side = 1
    elif close < lows[idx]:
        breakout_side = -1

    side = breakout_side or trend_side
    if side == 0 and config.always_in:
        side = previous_side
    if side == 0:
        return 0.0, {
            "side": "flat",
            "trend_side": trend_side,
            "breakout_side": breakout_side,
            "confidence": 0.0,
            "spread_atr": spread,
        }

    confidence = float(config.min_active_fraction)
    if trend_side == side:
        confidence += min(abs(spread) / max(config.trend_band_atr * 3.0, 1e-12), 1.0) * 0.35
    elif trend_side == -side:
        confidence -= 0.25

    if breakout_side == side:
        confidence += 0.25
    elif breakout_side == -side:
        confidence = min(confidence, 0.20)

    rsi = features.rsi(14)[idx]
    dist_fast_atr = (close - fast_ema) / atr * side if math.isfinite(fast_ema) else 0.0
    if side > 0:
        if 40.0 <= rsi <= 62.0 and close >= fast_ema:
            confidence += 0.15
        if rsi >= 75.0:
            confidence -= 0.20
        if close < slow_ema:
            confidence *= 0.50
    else:
        if 38.0 <= rsi <= 60.0 and close <= fast_ema:
            confidence += 0.15
        if rsi <= 25.0:
            confidence -= 0.20
        if close > slow_ema:
            confidence *= 0.50

    if dist_fast_atr > config.trim_atr:
        confidence -= 0.30
    elif -config.pullback_atr <= dist_fast_atr <= 0.25:
        confidence += 0.10

    if abs(spread) < config.trend_band_atr * 0.50 and breakout_side == 0:
        confidence *= 0.50

    fraction = _clamp(confidence, 0.0, 1.0)
    if fraction < config.min_active_fraction * 0.50:
        fraction = 0.0
    target = side * config.max_account_exposure * fraction
    return target, {
        "side": "long" if side > 0 else "short",
        "trend_side": trend_side,
        "breakout_side": breakout_side,
        "confidence": round(fraction, 4),
        "spread_atr": round(spread, 4) if math.isfinite(spread) else None,
        "rsi": round(rsi, 2),
        "dist_fast_atr": round(dist_fast_atr, 4),
    }


def _updated_average_entry(
    *,
    current_weight: float,
    current_avg_entry: float,
    target_weight: float,
    exec_price: float,
) -> float:
    if abs(target_weight) <= 1e-12:
        return 0.0
    if abs(current_weight) <= 1e-12 or not _same_sign(current_weight, target_weight):
        return exec_price
    if abs(target_weight) <= abs(current_weight):
        return current_avg_entry if current_avg_entry > 0.0 else exec_price
    old_notional = abs(current_weight)
    added_notional = abs(target_weight) - old_notional
    return (current_avg_entry * old_notional + exec_price * added_notional) / max(
        old_notional + added_notional,
        1e-12,
    )


def _liquidation_triggered(
    *,
    weight: float,
    avg_entry: float,
    bar_high: float,
    bar_low: float,
    exchange_leverage: float,
    maintenance_margin_pct: float,
) -> bool:
    if abs(weight) <= 1e-12 or avg_entry <= 0.0 or exchange_leverage <= 0.0:
        return False
    liquidation_distance = max(1.0 / exchange_leverage - maintenance_margin_pct / 100.0, 0.01)
    if weight > 0.0:
        return bar_low <= avg_entry * (1.0 - liquidation_distance)
    return bar_high >= avg_entry * (1.0 + liquidation_distance)


def _quantile(values: list[float], quantile: float) -> float:
    clean = sorted(value for value in values if math.isfinite(value))
    if not clean:
        return math.nan
    q = _clamp(quantile, 0.0, 1.0)
    pos = q * (len(clean) - 1)
    low = int(math.floor(pos))
    high = int(math.ceil(pos))
    if low == high:
        return clean[low]
    frac = pos - low
    return clean[low] * (1.0 - frac) + clean[high] * frac


def backtest_config(
    *,
    symbol: str,
    features: FeatureSet,
    config: PositionRotationConfig,
    cost_bps_per_side: float,
    min_periods: int,
) -> dict[str, Any]:
    warmup = max(config.slow, config.breakout_lookback, 80) + 5
    if len(features.bars) < warmup + 100:
        return {"decision": "REJECT_SAMPLE", "periods": 0}

    current_weight = 0.0
    avg_entry = 0.0
    equity = 1.0
    peak = 1.0
    min_equity = 1.0
    max_dd = 0.0
    turnover_sum = 0.0
    cost_drag = 0.0
    gross_exposure_sum = 0.0
    margin_fraction_sum = 0.0
    active_periods = 0
    wins = 0
    losses = 0
    period_count = 0
    scale_in_count = 0
    scale_out_count = 0
    flip_count = 0
    flat_count = 0
    adjustment_skipped_count = 0
    liquidation_count = 0
    direction_periods: Counter[str] = Counter()
    event_reasons: Counter[str] = Counter()
    by_year_start: dict[str, float] = {}
    by_year_end: dict[str, float] = {}
    period_returns: list[float] = []
    samples: list[dict[str, Any]] = []
    first_exec_ts: datetime | None = None
    last_period_ts: datetime | None = None
    previous_signal_side = 0
    cost_rate = max(float(cost_bps_per_side), 0.0) / 10_000.0
    first_exec_idx = warmup + 1

    for signal_idx in range(warmup, len(features.bars) - 2):
        exec_idx = signal_idx + 1
        next_idx = exec_idx + 1
        exec_price = features.o[exec_idx]
        next_price = features.o[next_idx]
        if exec_price <= 0.0 or next_price <= 0.0:
            continue
        if first_exec_ts is None:
            first_exec_ts = features.ts[exec_idx]

        target_weight, signal_meta = _target_exposure(
            features,
            signal_idx,
            config,
            previous_side=previous_signal_side,
        )
        target_side = 1 if target_weight > 0.0 else -1 if target_weight < 0.0 else 0
        if target_side != 0:
            previous_signal_side = target_side

        previous_weight = current_weight
        raw_target_weight = target_weight
        previous_side = 1 if current_weight > 0.0 else -1 if current_weight < 0.0 else 0
        side_changed = target_side != 0 and previous_side != 0 and target_side != previous_side
        opening_from_flat = previous_side == 0 and target_side != 0
        target_flat = target_side == 0 and previous_side != 0
        due_same_side_resize = (exec_idx - first_exec_idx) % max(config.rebalance_bars, 1) == 0
        same_side_resize = target_side != 0 and previous_side == target_side
        delta = abs(target_weight - current_weight)
        if same_side_resize and (not due_same_side_resize or delta < config.min_turnover_delta):
            target_weight = current_weight
            target_side = previous_side
            adjustment_skipped_count += 1
        elif target_flat and (not due_same_side_resize or delta < config.min_turnover_delta):
            target_weight = current_weight
            target_side = previous_side
            adjustment_skipped_count += 1
        elif not (side_changed or opening_from_flat or target_flat or same_side_resize):
            target_weight = current_weight
            target_side = previous_side
            adjustment_skipped_count += 1

        turnover = abs(target_weight - current_weight)
        turnover_sum += turnover
        cost_period = turnover * cost_rate
        cost_drag += cost_period

        if abs(target_weight) <= 1e-12:
            if abs(current_weight) > 1e-12:
                flat_count += 1
                event_reasons["flat"] += 1
            current_weight = 0.0
            avg_entry = 0.0
        else:
            if abs(current_weight) > 1e-12 and not _same_sign(current_weight, target_weight):
                flip_count += 1
                event_reasons["flip"] += 1
            elif abs(target_weight) > abs(current_weight) + 1e-9:
                scale_in_count += 1
                event_reasons["scale_in"] += 1
            elif abs(target_weight) < abs(current_weight) - 1e-9:
                scale_out_count += 1
                event_reasons["scale_out"] += 1
            avg_entry = _updated_average_entry(
                current_weight=current_weight,
                current_avg_entry=avg_entry,
                target_weight=target_weight,
                exec_price=exec_price,
            )
            current_weight = target_weight

        liquidated = _liquidation_triggered(
            weight=current_weight,
            avg_entry=avg_entry,
            bar_high=features.h[exec_idx],
            bar_low=features.l[exec_idx],
            exchange_leverage=config.exchange_leverage,
            maintenance_margin_pct=config.maintenance_margin_pct,
        )
        if liquidated:
            liquidation_count += 1
            margin_loss = min(abs(current_weight) / max(config.exchange_leverage, 1e-12), 0.999)
            net_return = -margin_loss - cost_period
            current_weight = 0.0
            avg_entry = 0.0
            event_reasons["liquidation"] += 1
        else:
            underlying_return = next_price / exec_price - 1.0
            net_return = current_weight * underlying_return - cost_period

        gross_exposure = abs(current_weight)
        gross_exposure_sum += gross_exposure
        margin_fraction_sum += gross_exposure / max(config.exchange_leverage, 1e-12)
        if gross_exposure > 1e-12:
            active_periods += 1
        direction_periods[_side_name(current_weight)] += 1

        year = str(features.ts[next_idx].year)
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
        period_count += 1
        last_period_ts = features.ts[next_idx]

        if len(samples) < 12 and (turnover > 1e-9 or liquidated):
            samples.append(
                {
                    "signal_ts": features.ts[signal_idx].isoformat(),
                    "exec_ts": features.ts[exec_idx].isoformat(),
                    "prev_weight": round(previous_weight, 4),
                    "raw_target_weight": round(raw_target_weight, 4),
                    "target_weight": round(target_weight, 4),
                    "turnover": round(turnover, 4),
                    "adjustment_skipped_count": adjustment_skipped_count,
                    "avg_entry": round(avg_entry, 4),
                    "exec_price": round(exec_price, 4),
                    "net_return_pct": round(net_return * 100.0, 4),
                    "liquidated": liquidated,
                    "signal": signal_meta,
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
    positive_year_fraction = positive_years / max(len(by_year_return), 1)
    avg_gross = gross_exposure_sum / max(period_count, 1)
    avg_margin = margin_fraction_sum / max(period_count, 1)
    returns_clean = [value for value in period_returns if math.isfinite(value)]
    period_mean = sum(returns_clean) / max(len(returns_clean), 1)
    period_var = (
        sum((value - period_mean) * (value - period_mean) for value in returns_clean) / max(len(returns_clean), 1)
        if returns_clean
        else 0.0
    )
    bars_per_year = 365.25 * 24.0 / max(_INTERVAL_MS[config.interval] / (60 * 60 * 1000), 1e-9)
    ann_vol = math.sqrt(max(period_var, 0.0)) * math.sqrt(bars_per_year)
    sharpe = period_mean * bars_per_year / max(ann_vol, 1e-12) if ann_vol > 0.0 else 0.0
    calmar = cagr / max(max_dd, 1e-9) if max_dd > 0.0 else 0.0
    return_to_dd = total_return / max(max_dd, 1e-9) if max_dd > 0.0 else 0.0
    worst_year = min(by_year_return.values()) if by_year_return else 0.0
    common_days = max(years * 365.25, 1e-9)
    win_rate = wins / max(wins + losses, 1)
    p05 = _quantile(returns_clean, 0.05)
    p01 = _quantile(returns_clean, 0.01)

    if period_count < min_periods or years < 0.5:
        decision = "REJECT_SAMPLE"
    elif liquidation_count > 0:
        decision = "REJECT_LIQUIDATION"
    elif total_return <= 0.0:
        decision = "REJECT_NEGATIVE"
    elif max_dd > 0.80:
        decision = "REJECT_DRAWDOWN"
    elif cagr >= 0.45 and calmar >= 0.80 and positive_year_fraction >= 0.70:
        decision = "PAPER_RESEARCH"
    elif cagr >= 0.20 and calmar >= 0.40:
        decision = "WATCH"
    else:
        decision = "REJECT_WEAK"

    score = 0.0
    if total_return > 0.0 and max_dd > 0.0 and liquidation_count == 0:
        score = max(calmar, 0.0) * math.log1p(max(total_return, 0.0)) * max(positive_year_fraction, 0.05)

    return {
        "model_id": config.model_id,
        "symbol": symbol,
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
        "win_rate_period": round(win_rate, 4),
        "active_fraction": round(active_periods / max(period_count, 1), 4),
        "avg_gross_exposure": round(avg_gross, 4),
        "avg_margin_fraction_at_exchange_leverage": round(avg_margin, 4),
        "max_account_exposure": round(config.max_account_exposure, 4),
        "exchange_leverage": round(config.exchange_leverage, 4),
        "turnover_sum": round(turnover_sum, 4),
        "avg_daily_turnover": round(turnover_sum / common_days, 4),
        "cost_drag_pct_simple_sum": round(cost_drag * 100.0, 4),
        "scale_in_count": scale_in_count,
        "scale_out_count": scale_out_count,
        "flip_count": flip_count,
        "flat_count": flat_count,
        "adjustment_skipped_count": adjustment_skipped_count,
        "liquidation_event_count": liquidation_count,
        "p05_period_return_pct": round(p05 * 100.0, 4) if math.isfinite(p05) else None,
        "p01_period_return_pct": round(p01 * 100.0, 4) if math.isfinite(p01) else None,
        "direction_periods": dict(sorted(direction_periods.items())),
        "event_reasons": dict(sorted(event_reasons.items())),
        "score": round(score, 6),
        "rebalance_samples": samples,
    }


def _buy_hold_benchmark(features: FeatureSet) -> dict[str, Any]:
    if not features.bars:
        return {"return_pct_1x": 0.0, "first_ts": None, "last_ts": None}
    first = features.bars[0]
    last = features.bars[-1]
    return {
        "first_ts": first.ts.isoformat(),
        "last_ts": last.ts.isoformat(),
        "first_close": first.c,
        "last_close": last.c,
        "return_pct_1x": round((last.c / first.c - 1.0) * 100.0, 4) if first.c > 0.0 else 0.0,
    }


def main() -> int:
    args = _parse_args()
    generated_at = datetime.now(UTC)
    settings = get_settings()
    symbol = str(args.symbol or "BTCUSDT").strip().upper()
    intervals = [item for item in _csv(args.intervals) if item in _INTERVAL_MS] or ["15m", "30m", "1h"]
    days = max(int(args.days), 30)
    base_url = str(args.base_url or settings.binance_rest_base_url or "https://fapi.binance.com").rstrip("/")
    cache_dir = ROOT_DIR / str(args.cache_dir)
    cost_bps = max(float(args.fee_bps_per_side) + float(args.slippage_bps_per_side), 0.0)
    max_account_exposures = _parse_float_csv(str(args.max_account_exposures))
    rebalance_bars_options = _parse_int_csv(str(args.rebalance_bars), minimum=1)
    min_turnover_deltas = _parse_nonnegative_float_csv(str(args.min_turnover_deltas))

    features_by_interval: dict[str, FeatureSet] = {}
    data_status: dict[str, Any] = {}
    for interval in intervals:
        bars = _load_bars(
            symbol=symbol,
            interval=interval,
            days=days,
            cache_dir=cache_dir,
            base_url=base_url,
            sleep_seconds=float(args.sleep_seconds),
        )
        features_by_interval[interval] = FeatureSet(bars)
        data_status[interval] = {
            "bars": len(bars),
            "first_ts": bars[0].ts.isoformat() if bars else None,
            "last_ts": bars[-1].ts.isoformat() if bars else None,
        }

    configs = build_configs(
        intervals=intervals,
        max_account_exposures=max_account_exposures,
        rebalance_bars_options=rebalance_bars_options,
        min_turnover_deltas=min_turnover_deltas,
        exchange_leverage=max(float(args.exchange_leverage), 1.0),
        maintenance_margin_pct=max(float(args.maintenance_margin_pct), 0.0),
    )
    if int(args.max_models or 0) > 0:
        configs = configs[: int(args.max_models)]

    rows: list[dict[str, Any]] = []
    for idx, config in enumerate(configs, start=1):
        features = features_by_interval.get(config.interval)
        if features is None:
            continue
        summary = backtest_config(
            symbol=symbol,
            features=features,
            config=config,
            cost_bps_per_side=cost_bps,
            min_periods=max(int(args.min_periods), 1),
        )
        rows.append({"rank_input_order": idx, "config": asdict(config), "summary": summary})
        if idx % 100 == 0:
            print(json.dumps({"progress_models": idx, "latest_model": config.model_id}), flush=True)

    top = sorted(
        rows,
        key=lambda row: (
            float(dict(row.get("summary") or {}).get("score", 0.0) or 0.0),
            float(dict(row.get("summary") or {}).get("total_return_pct", 0.0) or 0.0),
            -float(dict(row.get("summary") or {}).get("max_drawdown_pct", 100.0) or 100.0),
        ),
        reverse=True,
    )[:30]
    decision_counts = Counter(str(dict(row.get("summary") or {}).get("decision") or "") for row in rows)
    output = {
        "schema_version": "position_rotation_backtest_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "research_only_no_live_authority_change",
        "scope": {
            "symbol": symbol,
            "days": days,
            "intervals": intervals,
            "model_count": len(rows),
            "min_periods": max(int(args.min_periods), 1),
        },
        "strategy_proxy": {
            "description": "Mechanical proxy for position rotation: completed-candle trend/breakout signal, next-open execution, partial scale-in/out by signal confidence, immediate long/short flip when target side changes.",
            "exchange_leverage": max(float(args.exchange_leverage), 1.0),
            "max_account_exposures": max_account_exposures,
            "rebalance_bars_options": rebalance_bars_options,
            "min_turnover_deltas": min_turnover_deltas,
            "notes": [
                "Exchange leverage is separated from account-level exposure.",
                "Example: max_account_exposure=2 with 10x exchange leverage uses roughly 20% isolated margin at full target.",
                "This is not a claim that it matches any trader's private discretionary execution.",
            ],
        },
        "cost_model": {
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": float(args.slippage_bps_per_side),
            "base_cost_bps_per_side": cost_bps,
            "maintenance_margin_pct": float(args.maintenance_margin_pct),
            "notes": [
                "signals use completed candles and execute at next candle open",
                "turnover includes scale-in, scale-out, and full flip notional",
                "funding, queue priority, partial fills, and stop order slippage are not modeled",
            ],
        },
        "data_status": data_status,
        "buy_hold_benchmark_by_interval": {
            interval: _buy_hold_benchmark(features)
            for interval, features in sorted(features_by_interval.items())
        },
        "decision_counts": dict(sorted(decision_counts.items())),
        "top": top,
        "all_results": rows,
    }

    if args.write_report:
        report_dir = ROOT_DIR / str(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        out_path = report_dir / f"position_rotation_backtest_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        latest_path = report_dir / "latest.json"
        output["report_path"] = str(out_path.relative_to(ROOT_DIR))
        output["latest_report_path"] = str(latest_path.relative_to(ROOT_DIR))
        atomic_write_text(out_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(latest_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))

    print(json.dumps({key: value for key, value in output.items() if key != "all_results"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
