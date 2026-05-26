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
from scripts.run_position_rotation_backtest import (
    _liquidation_triggered,
    _quantile,
    _same_sign,
    _side_name,
    _updated_average_entry,
)


Side = Literal["long", "short", "flat"]


@dataclass(frozen=True, slots=True)
class NanyottiZoneConfig:
    model_id: str
    interval: str
    trend_fast: int
    trend_slow: int
    trend_band_atr: float
    zone_lookback: int
    zone_atr: float
    base_fraction: float
    base_cap_fraction: float
    add_spacing_atr: float
    rescue_trigger_atr: float
    rescue_fraction: float
    reaction_atr: float
    stop_atr: float
    one_way_atr: float
    rescue_max_bars: int
    max_hold_bars: int
    max_account_exposure: float
    exchange_leverage: float
    maintenance_margin_pct: float
    flip_on_invalidation: bool = True


@dataclass(slots=True)
class RotationState:
    weight: float = 0.0
    avg_entry: float = 0.0
    rescue_weight: float = 0.0
    rescue_entry: float = 0.0
    rescue_idx: int = -1
    last_base_add_price: float = 0.0
    entry_idx: int = -1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only Nanyotti-style zone rotation backtest with stateful tranches."
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--days", type=int, default=1825)
    parser.add_argument("--intervals", default="15m,30m,1h")
    parser.add_argument("--exchange-leverage", type=float, default=10.0)
    parser.add_argument("--max-account-exposures", default="0.5,1,1.5,2")
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument("--maintenance-margin-pct", type=float, default=0.5)
    parser.add_argument("--min-periods", type=int, default=2000)
    parser.add_argument("--max-models", type=int, default=0)
    parser.add_argument(
        "--max-hold-bars-options",
        default="",
        help="Comma-separated max holding bars to test for every interval. Use 0 to disable time exits.",
    )
    parser.add_argument("--cache-dir", default="reports/validation/btc_flip_rotation_search/cache")
    parser.add_argument("--report-dir", default="reports/validation/nanyotti_zone_rotation_backtest")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _parse_float_csv(raw: str, fallback: list[float]) -> list[float]:
    out: list[float] = []
    for item in _csv(raw):
        try:
            value = float(item)
        except ValueError:
            continue
        if value > 0.0:
            out.append(value)
    return out or list(fallback)


def _parse_int_csv(raw: str, fallback: list[int]) -> list[int]:
    out: list[int] = []
    for item in _csv(raw):
        try:
            value = int(item)
        except ValueError:
            continue
        if value >= 0:
            out.append(value)
    return out or list(fallback)


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(float(value), float(low)), float(high))


def _side_int(weight: float) -> int:
    if weight > 1e-12:
        return 1
    if weight < -1e-12:
        return -1
    return 0


def _side_label(side: int) -> Side:
    if side > 0:
        return "long"
    if side < 0:
        return "short"
    return "flat"


def _favorable_move(side: int, price: float, reference: float) -> float:
    if side > 0:
        return price - reference
    if side < 0:
        return reference - price
    return 0.0


def _round_level(price: float, step: float, direction: int) -> float:
    if step <= 0.0:
        return price
    if direction > 0:
        return math.floor(price / step) * step
    return math.ceil(price / step) * step


def _liquidation_buffer_stop_price(
    *,
    weight: float,
    avg_entry: float,
    bar_high: float,
    bar_low: float,
    exchange_leverage: float,
    maintenance_margin_pct: float,
    buffer_fraction: float = 0.55,
) -> float | None:
    if abs(weight) <= 1e-12 or avg_entry <= 0.0:
        return None
    liquidation_distance = max(1.0 / max(exchange_leverage, 1e-12) - maintenance_margin_pct / 100.0, 0.01)
    stop_distance = liquidation_distance * _clamp(buffer_fraction, 0.10, 0.95)
    if weight > 0.0:
        stop_price = avg_entry * (1.0 - stop_distance)
        return stop_price if bar_low <= stop_price else None
    stop_price = avg_entry * (1.0 + stop_distance)
    return stop_price if bar_high >= stop_price else None


def _ichimoku_cloud_proxy(features: FeatureSet, idx: int) -> tuple[float, float, float]:
    high9 = features.rolling_high_prev(9)[idx]
    low9 = features.rolling_low_prev(9)[idx]
    high26 = features.rolling_high_prev(26)[idx]
    low26 = features.rolling_low_prev(26)[idx]
    high52 = features.rolling_high_prev(52)[idx]
    low52 = features.rolling_low_prev(52)[idx]
    tenkan = (high9 + low9) * 0.5
    kijun = (high26 + low26) * 0.5
    span_a = (tenkan + kijun) * 0.5
    span_b = (high52 + low52) * 0.5
    cloud_low = min(span_a, span_b)
    cloud_high = max(span_a, span_b)
    return cloud_low, cloud_high, (cloud_low + cloud_high) * 0.5


def _scenario_side(features: FeatureSet, idx: int, config: NanyottiZoneConfig) -> tuple[int, dict[str, Any]]:
    close = features.c[idx]
    atr = max(features.atr[idx], 1e-12)
    fast = features.ema(config.trend_fast)[idx]
    slow = features.ema(config.trend_slow)[idx]
    spread_atr = (fast - slow) / atr if math.isfinite(fast) and math.isfinite(slow) else 0.0
    cloud_low, cloud_high, cloud_mid = _ichimoku_cloud_proxy(features, idx)
    side = 0
    if spread_atr > config.trend_band_atr and close >= cloud_mid:
        side = 1
    elif spread_atr < -config.trend_band_atr and close <= cloud_mid:
        side = -1
    elif abs(spread_atr) <= config.trend_band_atr * 0.75:
        side = 0
    elif close > slow:
        side = 1
    elif close < slow:
        side = -1
    return side, {
        "scenario": _side_label(side),
        "spread_atr": round(spread_atr, 4),
        "cloud_low": round(cloud_low, 4),
        "cloud_high": round(cloud_high, 4),
        "cloud_mid": round(cloud_mid, 4),
    }


def _one_way_risk(features: FeatureSet, idx: int, config: NanyottiZoneConfig, side: int) -> tuple[bool, dict[str, Any]]:
    if side == 0:
        return False, {"one_way": False}
    close = features.c[idx]
    atr = max(features.atr[idx], 1e-12)
    slow = features.ema(config.trend_slow)[idx]
    extension = (close - slow) / atr
    recent = max(3, min(8, config.zone_lookback // 8))
    start = max(1, idx - recent + 1)
    directional = 0
    for pos in range(start, idx + 1):
        if features.c[pos] > features.c[pos - 1]:
            directional += 1
        elif features.c[pos] < features.c[pos - 1]:
            directional -= 1
    risk = side * extension > config.one_way_atr and abs(directional) >= max(2, recent - 2)
    return risk, {
        "one_way": risk,
        "extension_atr": round(extension, 4),
        "directional_score": directional,
    }


def _zone_signal(features: FeatureSet, idx: int, config: NanyottiZoneConfig) -> tuple[int, dict[str, Any]]:
    close = features.c[idx]
    open_ = features.o[idx]
    high = features.h[idx]
    low = features.l[idx]
    atr = max(features.atr[idx], 1e-12)
    width = max(config.zone_atr * atr, close * 0.0008)
    prev_high = features.rolling_high_prev(config.zone_lookback)[idx]
    prev_low = features.rolling_low_prev(config.zone_lookback)[idx]
    cloud_low, cloud_high, cloud_mid = _ichimoku_cloud_proxy(features, idx)
    slow = features.ema(config.trend_slow)[idx]
    round_down_1000 = _round_level(close, 1000.0, 1)
    round_up_1000 = _round_level(close, 1000.0, -1)

    long_candidates = {
        "prev_low": prev_low,
        "cloud_low": cloud_low,
        "cloud_high": cloud_high,
        "slow_ema": slow,
        "round_1000": round_down_1000,
    }
    short_candidates = {
        "prev_high": prev_high,
        "cloud_low": cloud_low,
        "cloud_high": cloud_high,
        "slow_ema": slow,
        "round_1000": round_up_1000,
    }
    candle_range = max(high - low, 1e-12)
    close_pos = (close - low) / candle_range
    long_reaction = close >= open_ or close_pos >= 0.58
    short_reaction = close <= open_ or close_pos <= 0.42

    long_hits = [
        name
        for name, level in long_candidates.items()
        if math.isfinite(level) and low <= level + width and close >= level - width
    ]
    short_hits = [
        name
        for name, level in short_candidates.items()
        if math.isfinite(level) and high >= level - width and close <= level + width
    ]
    low_break_reclaim = low < prev_low - width * 0.25 and close > prev_low
    high_break_reject = high > prev_high + width * 0.25 and close < prev_high
    if low_break_reclaim:
        long_hits.append("low_break_reclaim")
    if high_break_reject:
        short_hits.append("high_break_reject")

    long_unique = set(long_hits)
    short_unique = set(short_hits)
    long_structural = any(not name.startswith("round_") for name in long_unique)
    short_structural = any(not name.startswith("round_") for name in short_unique)
    long_score = len(long_unique) + (1 if long_reaction else 0)
    short_score = len(short_unique) + (1 if short_reaction else 0)
    zone_side = 0
    if long_structural and long_score >= 2 and long_score > short_score:
        zone_side = 1
    elif short_structural and short_score >= 2 and short_score > long_score:
        zone_side = -1
    return zone_side, {
        "zone_side": _side_label(zone_side),
        "long_hits": sorted(set(long_hits))[:6],
        "short_hits": sorted(set(short_hits))[:6],
        "long_score": long_score,
        "short_score": short_score,
        "width": round(width, 4),
        "prev_high": round(prev_high, 4),
        "prev_low": round(prev_low, 4),
        "cloud_mid": round(cloud_mid, 4),
    }


def build_configs(
    *,
    intervals: list[str],
    max_account_exposures: list[float],
    max_hold_bars_options: list[int] | None = None,
    exchange_leverage: float,
    maintenance_margin_pct: float,
) -> list[NanyottiZoneConfig]:
    configs: list[NanyottiZoneConfig] = []
    for interval in intervals:
        rescue_max_options = {
            "5m": (6, 12),
            "15m": (4, 8),
            "30m": (3, 6),
            "1h": (2, 4),
        }.get(interval, (3, 6))
        interval_max_hold_options = max_hold_bars_options or [
            {
                "5m": 72,
                "15m": 32,
                "30m": 18,
                "1h": 10,
            }.get(interval, 12)
        ]
        for fast, slow in ((13, 89), (21, 144)):
            for lookback in (24, 48, 96):
                for zone_atr in (0.25, 0.45):
                    for base_fraction in (0.12, 0.20):
                        for rescue_fraction in (0.30, 0.45):
                            for reaction_atr in (0.45, 0.75):
                                for max_exposure in max_account_exposures:
                                    for max_hold_bars in interval_max_hold_options:
                                        for rescue_max in rescue_max_options:
                                            hold_label = "off" if max_hold_bars <= 0 else str(max_hold_bars)
                                            model_id = (
                                                f"{interval}:nanyotti_zone:ema{fast}_{slow}:lb{lookback}:"
                                                f"z{zone_atr:g}:base{base_fraction:g}:rescue{rescue_fraction:g}:"
                                                f"react{reaction_atr:g}:gross{max_exposure:g}:rm{rescue_max}:"
                                                f"hold{hold_label}:lev{exchange_leverage:g}"
                                            )
                                            configs.append(
                                                NanyottiZoneConfig(
                                                    model_id=model_id,
                                                    interval=interval,
                                                    trend_fast=fast,
                                                    trend_slow=slow,
                                                    trend_band_atr=0.12,
                                                    zone_lookback=lookback,
                                                    zone_atr=zone_atr,
                                                    base_fraction=base_fraction,
                                                    base_cap_fraction=0.50,
                                                    add_spacing_atr=0.75,
                                                    rescue_trigger_atr=1.00,
                                                    rescue_fraction=rescue_fraction,
                                                    reaction_atr=reaction_atr,
                                                    stop_atr=3.20,
                                                    one_way_atr=3.00,
                                                    rescue_max_bars=rescue_max,
                                                    max_hold_bars=max_hold_bars,
                                                    max_account_exposure=max_exposure,
                                                    exchange_leverage=exchange_leverage,
                                                    maintenance_margin_pct=maintenance_margin_pct,
                                                )
                                            )
    return configs


def _decide_target(
    *,
    features: FeatureSet,
    idx: int,
    state: RotationState,
    config: NanyottiZoneConfig,
) -> tuple[float, dict[str, Any]]:
    close = features.c[idx]
    atr = max(features.atr[idx], 1e-12)
    scenario_side, scenario_meta = _scenario_side(features, idx, config)
    zone_side, zone_meta = _zone_signal(features, idx, config)
    current_side = _side_int(state.weight)
    current_abs = abs(state.weight)
    max_exposure = config.max_account_exposure
    base_unit = max_exposure * config.base_fraction
    base_cap = max_exposure * config.base_cap_fraction
    one_way_scenario, one_way_meta = _one_way_risk(features, idx, config, scenario_side)
    one_way_against_position = current_side != 0 and one_way_scenario and scenario_side == -current_side

    target = state.weight
    reason = "hold"
    event = ""
    side_for_entry = scenario_side
    if side_for_entry == 0 and zone_side != 0:
        side_for_entry = zone_side

    if current_side == 0:
        if side_for_entry != 0 and zone_side == side_for_entry and not one_way_scenario:
            target = side_for_entry * min(base_unit, base_cap)
            reason = "base_entry"
            event = "base_entry"
        return target, {
            **scenario_meta,
            **zone_meta,
            **one_way_meta,
            "reason": reason,
            "event": event,
            "base_unit": round(base_unit, 4),
            "base_cap": round(base_cap, 4),
        }

    unrealized_atr = _favorable_move(current_side, close, state.avg_entry) / atr
    adverse_pct = 0.0
    if state.avg_entry > 0.0:
        adverse_pct = -current_side * (close / state.avg_entry - 1.0)
    liquidation_distance = max(1.0 / max(config.exchange_leverage, 1e-12) - config.maintenance_margin_pct / 100.0, 0.01)
    near_liquidation = adverse_pct >= liquidation_distance * 0.55
    rescue_unrealized_atr = (
        _favorable_move(current_side, close, state.rescue_entry) / atr
        if state.rescue_weight > 1e-12 and state.rescue_entry > 0.0
        else 0.0
    )

    if one_way_against_position or near_liquidation or unrealized_atr <= -config.stop_atr:
        if config.flip_on_invalidation and scenario_side == -current_side and zone_side == scenario_side:
            target = scenario_side * min(base_unit, max_exposure)
            reason = "stop_and_flip"
            event = "flip"
        else:
            target = 0.0
            reason = "stop_or_one_way_or_liq_buffer"
            event = "stop"
        return target, {
            **scenario_meta,
            **zone_meta,
            **one_way_meta,
            "reason": reason,
            "event": event,
            "unrealized_atr": round(unrealized_atr, 4),
            "adverse_pct": round(adverse_pct * 100.0, 4),
            "liq_buffer_stop": near_liquidation,
            "rescue_unrealized_atr": round(rescue_unrealized_atr, 4),
        }

    if scenario_side == -current_side and zone_side == scenario_side and unrealized_atr <= -config.rescue_trigger_atr:
        target = scenario_side * min(base_unit, max_exposure)
        reason = "scenario_invalidation_flip"
        event = "flip"
        return target, {
            **scenario_meta,
            **zone_meta,
            **one_way_meta,
            "reason": reason,
            "event": event,
            "unrealized_atr": round(unrealized_atr, 4),
        }

    if scenario_side == -current_side and zone_side == scenario_side and unrealized_atr >= config.reaction_atr:
        target = 0.0
        reason = "opposite_zone_profit_exit"
        event = "flat"
        return target, {
            **scenario_meta,
            **zone_meta,
            **one_way_meta,
            "reason": reason,
            "event": event,
            "unrealized_atr": round(unrealized_atr, 4),
        }

    if state.rescue_weight > 1e-12:
        rescue_age = max(idx - state.rescue_idx, 0)
        reached_reaction = rescue_unrealized_atr >= config.reaction_atr or unrealized_atr >= -0.10
        failed_reaction = rescue_age >= config.rescue_max_bars and rescue_unrealized_atr < config.reaction_atr * 0.25
        if reached_reaction or failed_reaction:
            reduce_abs = min(state.rescue_weight, current_abs)
            target_abs = max(current_abs - reduce_abs, 0.0)
            target = current_side * target_abs
            reason = "rescue_reaction_exit" if reached_reaction else "rescue_failure_exit"
            event = "rescue_exit" if reached_reaction else "rescue_stop"
            return target, {
                **scenario_meta,
                **zone_meta,
                **one_way_meta,
                "reason": reason,
                "event": event,
                "unrealized_atr": round(unrealized_atr, 4),
                "rescue_unrealized_atr": round(rescue_unrealized_atr, 4),
                "rescue_age": rescue_age,
            }

    position_age = max(idx - state.entry_idx, 0) if state.entry_idx >= 0 else 0
    if config.max_hold_bars > 0 and state.rescue_weight <= 1e-12 and position_age >= config.max_hold_bars:
        target = 0.0
        reason = "time_exit"
        event = "flat"
        return target, {
            **scenario_meta,
            **zone_meta,
            **one_way_meta,
            "reason": reason,
            "event": event,
            "unrealized_atr": round(unrealized_atr, 4),
            "position_age": position_age,
        }

    if (
        zone_side == current_side
        and scenario_side in {0, current_side}
        and current_abs < base_cap - 1e-12
        and _favorable_move(-current_side, close, state.last_base_add_price or state.avg_entry) >= config.add_spacing_atr * atr
    ):
        target_abs = min(current_abs + base_unit, base_cap)
        target = current_side * target_abs
        reason = "base_scale_in"
        event = "base_scale_in"
        return target, {
            **scenario_meta,
            **zone_meta,
            **one_way_meta,
            "reason": reason,
            "event": event,
            "unrealized_atr": round(unrealized_atr, 4),
        }

    if (
        zone_side == current_side
        and scenario_side in {0, current_side}
        and current_abs >= base_cap * 0.75
        and current_abs < max_exposure - 1e-12
        and unrealized_atr <= -config.rescue_trigger_atr
    ):
        add_abs = min(max_exposure * config.rescue_fraction, max_exposure - current_abs)
        if add_abs > 1e-12:
            target = current_side * (current_abs + add_abs)
            reason = "rescue_entry"
            event = "rescue_entry"
            return target, {
                **scenario_meta,
                **zone_meta,
                **one_way_meta,
                "reason": reason,
                "event": event,
                "unrealized_atr": round(unrealized_atr, 4),
                "planned_rescue_add": round(add_abs, 4),
            }

    if current_abs > base_unit and unrealized_atr >= config.reaction_atr * 1.50:
        target_abs = max(base_unit, current_abs * 0.50)
        target = current_side * target_abs
        reason = "profit_risk_trim"
        event = "profit_trim"
        return target, {
            **scenario_meta,
            **zone_meta,
            **one_way_meta,
            "reason": reason,
            "event": event,
            "unrealized_atr": round(unrealized_atr, 4),
        }

    return target, {
        **scenario_meta,
        **zone_meta,
        **one_way_meta,
        "reason": reason,
        "event": event,
        "unrealized_atr": round(unrealized_atr, 4),
        "rescue_unrealized_atr": round(rescue_unrealized_atr, 4),
    }


def _apply_state_after_execution(
    *,
    state: RotationState,
    previous_weight: float,
    target_weight: float,
    exec_price: float,
    exec_idx: int,
    event: str,
) -> None:
    previous_rescue = state.rescue_weight
    previous_side = _side_int(previous_weight)
    target_side = _side_int(target_weight)
    if target_side == 0:
        state.weight = 0.0
        state.avg_entry = 0.0
        state.rescue_weight = 0.0
        state.rescue_entry = 0.0
        state.rescue_idx = -1
        state.last_base_add_price = 0.0
        state.entry_idx = -1
        return
    if previous_side != 0 and target_side != previous_side:
        state.rescue_weight = 0.0
        state.rescue_entry = 0.0
        state.rescue_idx = -1
        state.last_base_add_price = exec_price
        state.entry_idx = exec_idx
    elif previous_side == 0 and target_side != 0:
        state.entry_idx = exec_idx
        state.last_base_add_price = exec_price
    if event == "rescue_entry":
        added = max(abs(target_weight) - abs(previous_weight), 0.0)
        state.rescue_weight += added
        state.rescue_entry = exec_price
        state.rescue_idx = exec_idx
    elif event in {"rescue_exit", "rescue_stop"}:
        reduced = max(abs(previous_weight) - abs(target_weight), 0.0)
        state.rescue_weight = max(previous_rescue - reduced, 0.0)
        if state.rescue_weight <= 1e-12:
            state.rescue_entry = 0.0
            state.rescue_idx = -1
    elif abs(target_weight) > abs(previous_weight) + 1e-12:
        state.last_base_add_price = exec_price
    elif abs(target_weight) < abs(previous_weight) - 1e-12 and previous_rescue > 1e-12:
        reduced = abs(previous_weight) - abs(target_weight)
        state.rescue_weight = max(previous_rescue - reduced, 0.0)
        if state.rescue_weight <= 1e-12:
            state.rescue_entry = 0.0
            state.rescue_idx = -1
    state.avg_entry = _updated_average_entry(
        current_weight=previous_weight,
        current_avg_entry=state.avg_entry,
        target_weight=target_weight,
        exec_price=exec_price,
    )
    state.weight = target_weight


def backtest_config(
    *,
    symbol: str,
    features: FeatureSet,
    config: NanyottiZoneConfig,
    cost_bps_per_side: float,
    min_periods: int,
) -> dict[str, Any]:
    warmup = max(config.trend_slow, config.zone_lookback, 90) + 5
    if len(features.bars) < warmup + 100:
        return {"decision": "REJECT_SAMPLE", "periods": 0}

    state = RotationState()
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
    liquidation_count = 0
    event_reasons: Counter[str] = Counter()
    direction_periods: Counter[str] = Counter()
    by_year_start: dict[str, float] = {}
    by_year_end: dict[str, float] = {}
    period_returns: list[float] = []
    samples: list[dict[str, Any]] = []
    first_exec_ts: datetime | None = None
    last_period_ts: datetime | None = None
    cost_rate = max(float(cost_bps_per_side), 0.0) / 10_000.0

    for signal_idx in range(warmup, len(features.bars) - 2):
        exec_idx = signal_idx + 1
        next_idx = exec_idx + 1
        exec_price = features.o[exec_idx]
        next_price = features.o[next_idx]
        if exec_price <= 0.0 or next_price <= 0.0:
            continue
        if first_exec_ts is None:
            first_exec_ts = features.ts[exec_idx]

        previous_weight = state.weight
        target_weight, meta = _decide_target(
            features=features,
            idx=signal_idx,
            state=state,
            config=config,
        )
        if abs(target_weight) > config.max_account_exposure:
            target_weight = math.copysign(config.max_account_exposure, target_weight)
        turnover = abs(target_weight - previous_weight)
        cost_period = turnover * cost_rate
        turnover_sum += turnover
        cost_drag += cost_period
        event = str(meta.get("event") or "")
        if turnover > 1e-12:
            if event:
                event_reasons[event] += 1
            elif abs(target_weight) <= 1e-12:
                event_reasons["flat"] += 1
            elif previous_weight != 0.0 and not _same_sign(previous_weight, target_weight):
                event_reasons["flip"] += 1
            elif abs(target_weight) > abs(previous_weight):
                event_reasons["scale_in"] += 1
            else:
                event_reasons["scale_out"] += 1
        _apply_state_after_execution(
            state=state,
            previous_weight=previous_weight,
            target_weight=target_weight,
            exec_price=exec_price,
            exec_idx=exec_idx,
            event=event,
        )

        liquidated = False
        buffer_stop_price = _liquidation_buffer_stop_price(
            weight=state.weight,
            avg_entry=state.avg_entry,
            bar_high=features.h[exec_idx],
            bar_low=features.l[exec_idx],
            exchange_leverage=config.exchange_leverage,
            maintenance_margin_pct=config.maintenance_margin_pct,
        )
        if buffer_stop_price is not None:
            underlying_return = buffer_stop_price / exec_price - 1.0
            net_return = state.weight * underlying_return - cost_period
            state = RotationState()
            event_reasons["liq_buffer_intrabar_stop"] += 1
        else:
            liquidated = _liquidation_triggered(
                weight=state.weight,
                avg_entry=state.avg_entry,
                bar_high=features.h[exec_idx],
                bar_low=features.l[exec_idx],
                exchange_leverage=config.exchange_leverage,
                maintenance_margin_pct=config.maintenance_margin_pct,
            )
            if liquidated:
                liquidation_count += 1
                margin_loss = min(abs(state.weight) / max(config.exchange_leverage, 1e-12), 0.999)
                net_return = -margin_loss - cost_period
                state = RotationState()
                event_reasons["liquidation"] += 1
            else:
                underlying_return = next_price / exec_price - 1.0
                net_return = state.weight * underlying_return - cost_period

        gross_exposure = abs(state.weight)
        gross_exposure_sum += gross_exposure
        margin_fraction_sum += gross_exposure / max(config.exchange_leverage, 1e-12)
        if gross_exposure > 1e-12:
            active_periods += 1
        direction_periods[_side_name(state.weight)] += 1

        year = str(features.ts[next_idx].year)
        by_year_start.setdefault(year, equity)
        equity = equity * max(1.0 + net_return, 1e-9)
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

        if len(samples) < 18 and (turnover > 1e-12 or liquidated):
            samples.append(
                {
                    "signal_ts": features.ts[signal_idx].isoformat(),
                    "exec_ts": features.ts[exec_idx].isoformat(),
                    "prev_weight": round(previous_weight, 4),
                    "target_weight": round(target_weight, 4),
                    "turnover": round(turnover, 4),
                    "avg_entry": round(state.avg_entry, 4),
                    "rescue_weight": round(state.rescue_weight, 4),
                    "exec_price": round(exec_price, 4),
                    "net_return_pct": round(net_return * 100.0, 4),
                    "liquidated": liquidated,
                    "buffer_stop_price": round(buffer_stop_price, 4) if buffer_stop_price is not None else None,
                    "meta": meta,
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
    elif max_dd > 0.60:
        decision = "REJECT_DRAWDOWN"
    elif cagr >= 0.35 and calmar >= 0.85 and positive_year_fraction >= 0.70:
        decision = "PAPER_RESEARCH"
    elif cagr >= 0.15 and calmar >= 0.45 and positive_year_fraction >= 0.50:
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
        "liquidation_event_count": liquidation_count,
        "p05_period_return_pct": round(p05 * 100.0, 4) if math.isfinite(p05) else None,
        "p01_period_return_pct": round(p01 * 100.0, 4) if math.isfinite(p01) else None,
        "direction_periods": dict(sorted(direction_periods.items())),
        "event_reasons": dict(sorted(event_reasons.items())),
        "score": round(score, 6),
        "samples": samples,
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
    max_account_exposures = _parse_float_csv(str(args.max_account_exposures), [0.5, 1.0, 1.5, 2.0])
    max_hold_bars_options = _parse_int_csv(str(args.max_hold_bars_options), []) if args.max_hold_bars_options else None

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
        max_hold_bars_options=max_hold_bars_options,
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
        "schema_version": "nanyotti_zone_rotation_backtest_v1",
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
            "description": (
                "Mechanical proxy derived from the Telegram export digest: scenario first, zone-only base entries, "
                "reserved capacity, larger rescue tranches at planned zones, mandatory rescue reduction on reaction, "
                "and one-way/stop invalidation."
            ),
            "explicit_non_claims": [
                "This is not a clone of a private discretionary method.",
                "It does not see the trader's real-time order book, psychology, manual judgment, or private indicator implementation.",
                "It is a falsifiable approximation for research and backtest iteration.",
            ],
            "exchange_leverage": max(float(args.exchange_leverage), 1.0),
            "max_account_exposures": max_account_exposures,
        },
        "cost_model": {
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": float(args.slippage_bps_per_side),
            "base_cost_bps_per_side": cost_bps,
            "maintenance_margin_pct": float(args.maintenance_margin_pct),
            "notes": [
                "signals use completed candles and execute at next candle open",
                "turnover includes base entries, rescue entries/exits, stops, and flips",
                "funding, queue priority, partial fills, and stop order gap slippage are not modeled",
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
        out_path = report_dir / f"nanyotti_zone_rotation_backtest_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        latest_path = report_dir / "latest.json"
        output["report_path"] = str(out_path.relative_to(ROOT_DIR))
        output["latest_report_path"] = str(latest_path.relative_to(ROOT_DIR))
        atomic_write_text(out_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(latest_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))

    print(json.dumps({key: value for key, value in output.items() if key != "all_results"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
