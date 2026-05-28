#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

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
    Bar,
    FeatureSet,
)
from scripts.run_scenario_repair_rotation_backtest import (
    PositionBook,
    RemovedLot,
    _cloud_bands,
    _map_closed_indices,
    _round_levels,
    _slice_last_days,
)


@dataclass(frozen=True, slots=True)
class MarketStateConfig:
    model_id: str
    exec_interval: str
    htf_fast: int
    htf_slow: int
    htf_band_atr: float
    exec_fast: int
    exec_slow: int
    zone_lookback: int
    entry_score: int
    battle_score: int
    opposite_score: int
    max_possible_units: float
    base_max_units: float
    probe_units: float
    base_add_units: float
    battle_units: float
    chase_units: float
    max_account_exposure: float
    exchange_leverage: float
    maintenance_margin_pct: float
    reaction_usd: float
    reaction_atr: float
    base_spacing_atr: float
    battle_trigger_usd: float
    battle_trigger_atr: float
    repair_cut: float
    repair_stop: float
    max_repair_eff_for_add: float
    min_capacity_ratio: float
    bad_rr_atr: float
    one_way_threshold: float
    one_way_window: int
    max_battle_bars: int
    max_stuck_bars: int
    max_hold_bars: int
    min_liquidation_buffer_pct: float
    trend_core_units: float
    strict_scenario_entry: bool
    switch_enabled: bool


@dataclass(frozen=True, slots=True)
class MarketState:
    bias: int
    long_score: int
    short_score: int
    trend_strength: float
    one_way_side: int
    one_way_score: float
    bad_rr: bool
    long_dist_atr: float
    short_dist_atr: float
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ZonePlan:
    side: int
    mode: str
    score: int
    long_score: int
    short_score: int
    long_reasons: tuple[str, ...]
    short_reasons: tuple[str, ...]
    expected_reaction_usd: float
    nearest_long_dist: float
    nearest_short_dist: float


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Market-data-only Nanyotti/Wonyotti-style v4 rotation proxy. Telegram material is "
            "used only as design guidance, never as a trading signal."
        )
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--load-days", type=int, default=1825)
    parser.add_argument("--exec-interval", default="5m")
    parser.add_argument("--scenario-intervals", default="1h,4h")
    parser.add_argument("--exchange-leverage", type=float, default=10.0)
    parser.add_argument("--max-account-exposures", default="1,2,3,5")
    parser.add_argument("--battle-units", default="3,5")
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument("--maintenance-margin-pct", type=float, default=0.5)
    parser.add_argument("--min-periods", type=int, default=5000)
    parser.add_argument("--model-offset", type=int, default=0)
    parser.add_argument("--max-models", type=int, default=160)
    parser.add_argument("--cache-dir", default="reports/validation/btc_flip_rotation_search/cache")
    parser.add_argument("--report-dir", default="reports/validation/market_state_rotation_v4_backtest")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _parse_float_csv(raw: str, fallback: list[float]) -> list[float]:
    values: list[float] = []
    for item in _csv(raw):
        try:
            value = float(item)
        except ValueError:
            continue
        if value > 0.0:
            values.append(value)
    return values or fallback


def _side_label(side: int) -> str:
    if side > 0:
        return "long"
    if side < 0:
        return "short"
    return "flat"


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(float(value), float(low)), float(high))


def _unit_cut_qty(qty: float, fraction: float, *, minimum: float = 1.0) -> float:
    if qty <= minimum + 1e-12:
        return qty
    rounded = round(qty * fraction)
    return min(qty, max(minimum, float(rounded)))


def _role_qty(book: PositionBook, role: str) -> float:
    return sum(lot.qty for lot in book.tranches if lot.role == role)


def _role_avg(book: PositionBook, role: str) -> float:
    lots = [lot for lot in book.tranches if lot.role == role and lot.qty > 1e-12]
    qty = sum(lot.qty for lot in lots)
    if qty <= 1e-12:
        return 0.0
    return sum(lot.qty * lot.entry for lot in lots) / qty


def _book_weight(config: MarketStateConfig, book: PositionBook) -> float:
    if book.side == 0:
        return 0.0
    unit_weight = config.max_account_exposure / max(config.max_possible_units, 1e-12)
    return book.side * book.qty * unit_weight


def _liquidation_price(config: MarketStateConfig, side: int, avg_entry: float) -> float:
    distance = max(1.0 / max(config.exchange_leverage, 1e-12) - config.maintenance_margin_pct / 100.0, 0.005)
    if side > 0:
        return avg_entry * (1.0 - distance)
    if side < 0:
        return avg_entry * (1.0 + distance)
    return 0.0


def _liquidation_buffer_pct(config: MarketStateConfig, book: PositionBook, price: float) -> float:
    if book.side == 0 or price <= 0.0:
        return math.inf
    liq = _liquidation_price(config, book.side, book.avg_entry)
    if book.side > 0:
        return (price - liq) / price
    return (liq - price) / price


def _nearest_round_dist(price: float, side: int) -> float:
    levels = _round_levels(price)
    if side > 0:
        candidates = [abs(price - level) for level in levels if level <= price]
    else:
        candidates = [abs(price - level) for level in levels if level >= price]
    return min(candidates) if candidates else math.inf


def _side_distance_to_major_zone(features: FeatureSet, idx: int, config: MarketStateConfig, side: int) -> float:
    close = features.c[idx]
    atr = max(features.atr[idx], 1e-12)
    prev_high = features.rolling_high_prev(config.zone_lookback)[idx]
    prev_low = features.rolling_low_prev(config.zone_lookback)[idx]
    cloud_low, cloud_high, _cloud_mid = _cloud_bands(features, idx)
    round_dist = _nearest_round_dist(close, side)
    if side > 0:
        raw = min(abs(close - prev_low), abs(close - cloud_high), abs(close - cloud_low), round_dist)
    else:
        raw = min(abs(close - prev_high), abs(close - cloud_high), abs(close - cloud_low), round_dist)
    return raw / atr


def _market_state(
    *,
    exec_features: FeatureSet,
    scenario_features: dict[str, FeatureSet],
    scenario_maps: dict[str, list[int]],
    exec_idx: int,
    sig_idx: int,
    config: MarketStateConfig,
) -> MarketState:
    long_score = 0
    short_score = 0
    strength_parts: list[float] = []
    reasons: list[str] = []

    for interval, features in scenario_features.items():
        idx = scenario_maps[interval][exec_idx]
        if idx <= max(config.htf_slow, 60):
            continue
        close = features.c[idx]
        atr = max(features.atr[idx], 1e-12)
        fast = features.ema(config.htf_fast)[idx]
        slow = features.ema(config.htf_slow)[idx]
        cloud_low, cloud_high, cloud_mid = _cloud_bands(features, idx)
        spread_atr = (fast - slow) / atr
        strength_parts.append(abs(spread_atr))
        weight = 3 if interval == "4h" else 2

        if fast > slow and close > cloud_mid:
            long_score += weight
            reasons.append(f"{interval}_trend_long")
        elif fast < slow and close < cloud_mid:
            short_score += weight
            reasons.append(f"{interval}_trend_short")

        if close > cloud_high:
            long_score += 1
        elif close < cloud_low:
            short_score += 1

        if spread_atr > config.htf_band_atr:
            long_score += 1
        elif spread_atr < -config.htf_band_atr:
            short_score += 1

    diff = long_score - short_score
    bias = 1 if diff >= 2 else -1 if diff <= -2 else 0
    trend_strength = mean(strength_parts) if strength_parts else 0.0

    atr = max(exec_features.atr[sig_idx], 1e-12)
    close = exec_features.c[sig_idx]
    start = max(0, sig_idx - max(config.one_way_window, 3))
    net_move = close - exec_features.c[start]
    move_atr = abs(net_move) / atr
    recent_high = max(exec_features.h[start : sig_idx + 1])
    recent_low = min(exec_features.l[start : sig_idx + 1])
    recent_range = max(recent_high - recent_low, atr)
    pullback_ratio = max((recent_range - abs(net_move)) / recent_range, 0.0)
    exec_slow = exec_features.ema(config.exec_slow)[sig_idx]
    extension_atr = abs(close - exec_slow) / atr
    directional_bars = 0
    direction = 1 if net_move > 0.0 else -1 if net_move < 0.0 else 0
    if direction:
        for pos in range(max(1, start + 1), sig_idx + 1):
            step = exec_features.c[pos] - exec_features.c[pos - 1]
            if step * direction > 0.0:
                directional_bars += 1

    one_way_score = (
        max(move_atr - 1.6, 0.0)
        + max(0.35 - pullback_ratio, 0.0) * 3.0
        + max(extension_atr - 2.0, 0.0) * 0.65
        + max(directional_bars - config.one_way_window * 0.55, 0.0) * 0.08
    )
    one_way_side = direction if direction and one_way_score >= config.one_way_threshold else 0

    long_dist_atr = _side_distance_to_major_zone(exec_features, sig_idx, config, 1)
    short_dist_atr = _side_distance_to_major_zone(exec_features, sig_idx, config, -1)
    bad_rr = min(long_dist_atr, short_dist_atr) > config.bad_rr_atr and abs(diff) <= 3
    if bad_rr:
        reasons.append("bad_rr_center")
    if one_way_side:
        reasons.append(f"one_way_{_side_label(one_way_side)}")

    return MarketState(
        bias=bias,
        long_score=long_score,
        short_score=short_score,
        trend_strength=trend_strength,
        one_way_side=one_way_side,
        one_way_score=one_way_score,
        bad_rr=bad_rr,
        long_dist_atr=long_dist_atr,
        short_dist_atr=short_dist_atr,
        reasons=tuple(reasons[:8]),
    )


def _near_2468_support(low: float, close: float, atr: float) -> bool:
    tolerance = max(0.28 * atr, 35.0)
    return any(low <= level + tolerance and close >= level for level in _round_levels(close))


def _near_2468_resistance(high: float, close: float, atr: float) -> bool:
    tolerance = max(0.28 * atr, 35.0)
    return any(high >= level - tolerance and close <= level for level in _round_levels(close))


def _zone_plan(
    *,
    features: FeatureSet,
    idx: int,
    market: MarketState,
    config: MarketStateConfig,
) -> ZonePlan:
    open_ = features.o[idx]
    high = features.h[idx]
    low = features.l[idx]
    close = features.c[idx]
    atr = max(features.atr[idx], 1e-12)
    span = max(high - low, 1e-12)
    close_position = (close - low) / span
    body_atr = (close - open_) / atr
    prev_high = features.rolling_high_prev(config.zone_lookback)[idx]
    prev_low = features.rolling_low_prev(config.zone_lookback)[idx]
    cloud_low, cloud_high, cloud_mid = _cloud_bands(features, idx)
    rsi = features.rsi(14)[idx]
    exec_spread = (features.ema(config.exec_fast)[idx] - features.ema(config.exec_slow)[idx]) / atr

    long_score = 0
    short_score = 0
    long_reasons: list[str] = []
    short_reasons: list[str] = []

    if market.bias > 0:
        long_score += 2
        long_reasons.append("htf_bias_long")
    elif market.bias < 0:
        short_score += 2
        short_reasons.append("htf_bias_short")

    if low <= prev_low - 0.08 * atr and close > prev_low:
        long_score += 3
        long_reasons.append("low_sweep_reclaim")
    elif low <= prev_low + 0.35 * atr and close_position >= 0.58:
        long_score += 2
        long_reasons.append("range_low_reaction")

    if high >= prev_high + 0.08 * atr and close < prev_high:
        short_score += 3
        short_reasons.append("high_sweep_reject")
    elif high >= prev_high - 0.35 * atr and close_position <= 0.42:
        short_score += 2
        short_reasons.append("range_high_reaction")

    if low <= cloud_high + 0.20 * atr and close >= cloud_low and market.bias >= 0:
        long_score += 1
        long_reasons.append("cloud_support")
    if high >= cloud_low - 0.20 * atr and close <= cloud_high and market.bias <= 0:
        short_score += 1
        short_reasons.append("cloud_resistance")

    if _near_2468_support(low, close, atr) and close_position >= 0.50:
        long_score += 1
        long_reasons.append("2468_support")
    if _near_2468_resistance(high, close, atr) and close_position <= 0.50:
        short_score += 1
        short_reasons.append("2468_resistance")

    if rsi <= 36.0 and body_atr > -0.15:
        long_score += 1
        long_reasons.append("washed_rsi")
    elif rsi >= 64.0 and body_atr < 0.15:
        short_score += 1
        short_reasons.append("heated_rsi")

    mode = "zone"
    if close > prev_high and exec_spread > 0.25 and market.bias >= 0:
        long_score += 2
        long_reasons.append("trend_chase_breakout")
        mode = "chase"
    if close < prev_low and exec_spread < -0.25 and market.bias <= 0:
        short_score += 2
        short_reasons.append("trend_chase_breakdown")
        mode = "chase"

    side = 0
    score = max(long_score, short_score)
    if not market.bad_rr:
        if long_score >= short_score + 2 and long_score >= config.entry_score:
            side = 1
            score = long_score
        elif short_score >= long_score + 2 and short_score >= config.entry_score:
            side = -1
            score = short_score

    expected_reaction_usd = max(config.reaction_usd, config.reaction_atr * atr)
    if abs(close - cloud_mid) <= 0.35 * atr or min(market.long_dist_atr, market.short_dist_atr) <= 0.35:
        expected_reaction_usd *= 1.08

    return ZonePlan(
        side=side,
        mode=mode,
        score=score,
        long_score=long_score,
        short_score=short_score,
        long_reasons=tuple(long_reasons[:8]),
        short_reasons=tuple(short_reasons[:8]),
        expected_reaction_usd=expected_reaction_usd,
        nearest_long_dist=market.long_dist_atr * atr,
        nearest_short_dist=market.short_dist_atr * atr,
    )


def _scenario_allows_side(config: MarketStateConfig, market: MarketState, side: int) -> bool:
    if side == 0:
        return False
    if not config.strict_scenario_entry:
        return True
    return market.bias == 0 or market.bias == side


def _recovery_price(book: PositionBook) -> float:
    return book.effective_breakeven()


def _repair_efficiency(book: PositionBook, price: float, expected_reaction: float) -> float:
    if book.side == 0:
        return 0.0
    recovery = _recovery_price(book)
    distance = abs(recovery - price)
    return distance / max(expected_reaction, 1e-12)


def _record_event(
    events: list[dict[str, Any]],
    *,
    ts: datetime,
    action: str,
    side: int,
    qty: float,
    price: float,
    reason: str,
    equity: float,
    extra: dict[str, Any] | None = None,
) -> None:
    item: dict[str, Any] = {
        "ts": ts.isoformat(),
        "action": action,
        "side": _side_label(side),
        "qty": round(float(qty), 6),
        "price": round(float(price), 2),
        "reason": reason,
        "equity": round(float(equity), 6),
    }
    if extra:
        item.update(extra)
    events.append(item)


def _exit_removed_lots(
    *,
    events: list[dict[str, Any]],
    removed: list[RemovedLot],
    ts: datetime,
    action: str,
    reason: str,
    equity: float,
) -> dict[str, float]:
    stats = {"battle_exits": 0.0, "battle_success": 0.0, "battle_failed": 0.0, "removed_qty": 0.0}
    for lot in removed:
        if lot.role == "battle":
            stats["battle_exits"] += 1.0
            if lot.pnl_usd_units > 0.0:
                stats["battle_success"] += 1.0
            else:
                stats["battle_failed"] += 1.0
        stats["removed_qty"] += lot.qty
        _record_event(
            events,
            ts=ts,
            action=action,
            side=lot.side,
            qty=lot.qty,
            price=lot.exit_price,
            reason=reason,
            equity=equity,
            extra={
                "role": lot.role,
                "entry": round(lot.entry, 2),
                "pnl_usd_units": round(lot.pnl_usd_units, 4),
            },
        )
    return stats


def _parse_event_ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _counter_payload(counter: Counter[str]) -> dict[str, int]:
    return {key: int(value) for key, value in sorted(counter.items())}


def _pnl_payload(counter: Counter[str]) -> dict[str, float]:
    return {key: round(float(value), 4) for key, value in sorted(counter.items())}


def _max_share(counter: Counter[str]) -> float:
    total = sum(counter.values())
    if total <= 0:
        return 0.0
    return max(counter.values()) / total


def _max_consecutive_add_side(add_events: list[dict[str, Any]]) -> int:
    max_run = 0
    current_side = ""
    current_run = 0
    for event in add_events:
        side = str(event.get("side") or "")
        if side == current_side:
            current_run += 1
        else:
            current_side = side
            current_run = 1
        max_run = max(max_run, current_run)
    return max_run


def _event_diagnostics(
    *,
    events: list[dict[str, Any]],
    counters: Counter[str],
    exposure_side_bars: Counter[str],
    exposure_bars: int,
    total_months: int,
) -> dict[str, Any]:
    add_events = [event for event in events if event.get("action") == "add"]
    remove_events = [event for event in events if event.get("action") == "remove"]
    add_total = len(add_events)
    remove_total = len(remove_events)

    add_by_side: Counter[str] = Counter(str(event.get("side") or "unknown") for event in add_events)
    add_by_role: Counter[str] = Counter(str(event.get("role") or str(event.get("reason") or "").split("_", 1)[0] or "unknown") for event in add_events)
    add_by_reason: Counter[str] = Counter(str(event.get("reason") or "unknown") for event in add_events)
    remove_by_reason: Counter[str] = Counter(str(event.get("reason") or "unknown") for event in remove_events)
    remove_by_role: Counter[str] = Counter(str(event.get("role") or "unknown") for event in remove_events)
    add_by_month: Counter[str] = Counter()
    add_by_utc_hour: Counter[str] = Counter()
    add_by_kst_hour: Counter[str] = Counter()
    add_by_weekday: Counter[str] = Counter()
    add_by_day: Counter[str] = Counter()
    pnl_by_side: Counter[str] = Counter()
    pnl_by_role: Counter[str] = Counter()
    remove_qty_by_reason: Counter[str] = Counter()

    for event in add_events:
        ts = _parse_event_ts(event.get("ts"))
        if ts is None:
            continue
        add_by_month[ts.strftime("%Y-%m")] += 1
        add_by_day[ts.strftime("%Y-%m-%d")] += 1
        add_by_utc_hour[f"{ts.hour:02d}"] += 1
        add_by_kst_hour[f"{(ts.hour + 9) % 24:02d}"] += 1
        add_by_weekday[ts.strftime("%a")] += 1

    for event in remove_events:
        side = str(event.get("side") or "unknown")
        role = str(event.get("role") or "unknown")
        pnl = float(event.get("pnl_usd_units") or 0.0)
        qty = float(event.get("qty") or 0.0)
        reason = str(event.get("reason") or "unknown")
        pnl_by_side[side] += pnl
        pnl_by_role[role] += pnl
        remove_qty_by_reason[reason] += qty

    long_adds = add_by_side.get("long", 0)
    short_adds = add_by_side.get("short", 0)
    directional_adds = long_adds + short_adds
    long_add_share = long_adds / directional_adds if directional_adds else 0.0
    short_add_share = short_adds / directional_adds if directional_adds else 0.0
    active_months = len(add_by_month)
    active_days = len(add_by_day)
    max_month_share = _max_share(add_by_month)
    max_day_share = _max_share(add_by_day)
    max_hour_share = _max_share(add_by_kst_hour)
    exposure_long_share = exposure_side_bars.get("long", 0) / max(exposure_bars, 1)
    exposure_short_share = exposure_side_bars.get("short", 0) / max(exposure_bars, 1)
    exposure_flat_share = exposure_side_bars.get("flat", 0) / max(exposure_bars, 1)
    repair_stop_ratio = counters.get("repair_stop_trims", 0) / max(add_total, 1)
    one_way_trim_ratio = counters.get("one_way_forced_trims", 0) / max(add_total, 1)
    profit_trim_ratio = counters.get("profit_trims", 0) / max(remove_total, 1)
    battle_add_ratio = counters.get("battle_adds", 0) / max(add_total, 1)
    turnover_per_add = counters.get("turnover_events", 0) / max(add_total, 1)

    flags: list[str] = []
    if add_total < 50:
        flags.append("too_few_orders")
    if add_total > 1500:
        flags.append("overtrading")
    if directional_adds and max(long_add_share, short_add_share) >= 0.70:
        flags.append("side_imbalance")
    if total_months and active_months < max(3, math.ceil(total_months * 0.65)):
        flags.append("poor_month_coverage")
    if max_month_share >= 0.25:
        flags.append("month_concentration")
    if max_day_share >= 0.08:
        flags.append("day_concentration")
    if max_hour_share >= 0.18:
        flags.append("kst_hour_concentration")
    if repair_stop_ratio >= 0.30:
        flags.append("repair_stop_overuse")
    if one_way_trim_ratio >= 0.25:
        flags.append("one_way_forced_trim_overuse")
    if profit_trim_ratio <= 0.03 and remove_total >= 50:
        flags.append("profit_trim_underuse")
    if battle_add_ratio <= 0.015 and add_total >= 100:
        flags.append("battle_underuse")
    if turnover_per_add >= 2.50:
        flags.append("high_turnover_per_add")
    if counters.get("liquidations", 0) > 0:
        flags.append("liquidation_occurred")
    if counters.get("account_ruin_events", 0) > 0:
        flags.append("account_ruin")

    if any(flag in flags for flag in {"liquidation_occurred", "account_ruin", "poor_month_coverage"}):
        health = "fail"
    elif flags:
        health = "watch"
    else:
        health = "ok"

    return {
        "health": health,
        "flags": flags,
        "add_events": add_total,
        "remove_events": remove_total,
        "add_by_side": _counter_payload(add_by_side),
        "add_side_share": {"long": round(long_add_share, 4), "short": round(short_add_share, 4)},
        "add_by_role": _counter_payload(add_by_role),
        "add_by_reason": _counter_payload(add_by_reason),
        "remove_by_reason": _counter_payload(remove_by_reason),
        "remove_by_role": _counter_payload(remove_by_role),
        "realized_pnl_usd_units_by_side": _pnl_payload(pnl_by_side),
        "realized_pnl_usd_units_by_role": _pnl_payload(pnl_by_role),
        "remove_qty_by_reason": _pnl_payload(remove_qty_by_reason),
        "monthly_adds": _counter_payload(add_by_month),
        "active_order_months": int(active_months),
        "total_months": int(total_months),
        "active_order_days": int(active_days),
        "max_month_add_share": round(max_month_share, 4),
        "max_day_add_share": round(max_day_share, 4),
        "add_by_utc_hour": _counter_payload(add_by_utc_hour),
        "add_by_kst_hour": _counter_payload(add_by_kst_hour),
        "max_kst_hour_add_share": round(max_hour_share, 4),
        "add_by_weekday": _counter_payload(add_by_weekday),
        "max_consecutive_same_side_adds": _max_consecutive_add_side(add_events),
        "exposure_side_bars": _counter_payload(exposure_side_bars),
        "exposure_side_share": {
            "long": round(exposure_long_share, 4),
            "short": round(exposure_short_share, 4),
            "flat": round(exposure_flat_share, 4),
        },
        "ratios": {
            "repair_stop_per_add": round(repair_stop_ratio, 4),
            "one_way_forced_trim_per_add": round(one_way_trim_ratio, 4),
            "profit_trim_per_remove": round(profit_trim_ratio, 4),
            "battle_add_per_add": round(battle_add_ratio, 4),
            "turnover_events_per_add": round(turnover_per_add, 4),
        },
    }


def _add_lot(
    *,
    book: PositionBook,
    side: int,
    qty: float,
    price: float,
    exec_idx: int,
    role: str,
    zone_score: int,
    zone_reasons: tuple[str, ...],
) -> None:
    book.add(
        side=side,
        qty=qty,
        price=price,
        entry_idx=exec_idx,
        role=role,
        zone_score=zone_score,
        zone_id="|".join(zone_reasons[:3]),
    )


def _apply_decision(
    *,
    book: PositionBook,
    features: FeatureSet,
    sig_idx: int,
    exec_idx: int,
    exec_price: float,
    config: MarketStateConfig,
    market: MarketState,
    zone: ZonePlan,
    events: list[dict[str, Any]],
    equity: float,
    counters: Counter[str],
) -> None:
    ts = features.ts[exec_idx]
    atr = max(features.atr[sig_idx], 1e-12)
    close = features.c[sig_idx]
    expected_reaction = zone.expected_reaction_usd

    if book.side != 0 and _role_qty(book, "battle") > 0.0:
        battle_avg = _role_avg(book, "battle")
        target = battle_avg + book.side * expected_reaction
        reaction_hit = features.h[sig_idx] >= target if book.side > 0 else features.l[sig_idx] <= target
        if reaction_hit:
            removed = book.remove(qty=_role_qty(book, "battle"), price=exec_price, role_priority=("battle",))
            stats = _exit_removed_lots(
                events=events,
                removed=removed,
                ts=ts,
                action="remove",
                reason="battle_reaction_first",
                equity=equity,
            )
            counters["battle_reaction_exits"] += int(stats["battle_exits"])
            counters["battle_success"] += int(stats["battle_success"])
            counters["battle_failed"] += int(stats["battle_failed"])

    if book.side != 0:
        buffer_pct = _liquidation_buffer_pct(config, book, close)
        if buffer_pct < config.min_liquidation_buffer_pct:
            cut_qty = book.qty if buffer_pct < config.min_liquidation_buffer_pct * 0.55 else book.qty * 0.50
            removed = book.remove(qty=cut_qty, price=exec_price, role_priority=("battle", "chase", "base", "probe"))
            _exit_removed_lots(
                events=events,
                removed=removed,
                ts=ts,
                action="remove",
                reason="liquidation_buffer_cut",
                equity=equity,
            )
            counters["buffer_cuts"] += 1

    if book.side == 0:
        if (
            zone.side != 0
            and zone.score >= config.entry_score
            and not market.bad_rr
            and _scenario_allows_side(config, market, zone.side)
            and market.one_way_side != -zone.side
        ):
            role = "chase" if zone.mode == "chase" and market.bias == zone.side else "probe"
            qty = min(config.chase_units if role == "chase" else config.probe_units, config.max_possible_units)
            reasons = zone.long_reasons if zone.side > 0 else zone.short_reasons
            _add_lot(
                book=book,
                side=zone.side,
                qty=qty,
                price=exec_price,
                exec_idx=exec_idx,
                role=role,
                zone_score=zone.score,
                zone_reasons=reasons,
            )
            counters[f"{role}_adds"] += 1
            _record_event(
                events,
                ts=ts,
                action="add",
                side=zone.side,
                qty=qty,
                price=exec_price,
                reason=f"{role}_entry",
                equity=equity,
                extra={
                    "zone_score": zone.score,
                    "market": ",".join(market.reasons[:4]),
                    "zone": ",".join(reasons[:4]),
                },
            )
        return

    side = book.side
    avg = book.avg_entry
    recovery = _recovery_price(book)
    repair_eff = _repair_efficiency(book, close, expected_reaction)
    adverse_usd = max(-side * (close - avg), 0.0)
    favorable_from_recovery = side * (close - recovery)
    capacity = max(config.max_possible_units - book.qty, 0.0)
    remaining_capacity_ratio = capacity / max(book.qty, 1e-12)
    last_entry = book.last_entry or avg
    adverse_from_last = side * (last_entry - close)
    spacing_ok = adverse_from_last >= config.base_spacing_atr * atr
    same_score = zone.long_score if side > 0 else zone.short_score
    opposite_score = zone.short_score if side > 0 else zone.long_score
    same_reasons = zone.long_reasons if side > 0 else zone.short_reasons
    opposite_side = -side
    opposite_zone_side = zone.side == opposite_side
    scenario_allows_current = _scenario_allows_side(config, market, side)
    one_way_against = market.one_way_side == opposite_side

    if one_way_against and book.qty > config.probe_units:
        fraction = 0.65 if repair_eff > 1.0 else 0.50
        cut_qty = _unit_cut_qty(book.qty, fraction, minimum=config.probe_units)
        removed = book.remove(qty=cut_qty, price=exec_price, role_priority=("battle", "chase", "base", "probe"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=ts,
            action="remove",
            reason="one_way_against_forced_trim",
            equity=equity,
        )
        counters["one_way_forced_trims"] += 1
        return

    invalidated = market.bias == opposite_side and adverse_usd >= max(config.reaction_usd, config.battle_trigger_atr * atr)
    if invalidated and repair_eff >= config.repair_cut:
        removed = book.remove(qty=book.qty, price=exec_price, role_priority=("battle", "chase", "base", "probe"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=ts,
            action="remove",
            reason="scenario_invalidated_by_repair_math",
            equity=equity,
        )
        counters["repair_invalidations"] += 1
        if (
            config.switch_enabled
            and opposite_zone_side
            and opposite_score >= config.opposite_score
            and not market.bad_rr
            and market.one_way_side != side
        ):
            reasons = zone.short_reasons if opposite_side < 0 else zone.long_reasons
            qty = min(config.probe_units, config.max_possible_units)
            _add_lot(
                book=book,
                side=opposite_side,
                qty=qty,
                price=exec_price,
                exec_idx=exec_idx,
                role="probe",
                zone_score=opposite_score,
                zone_reasons=reasons,
            )
            counters["switches"] += 1
            _record_event(
                events,
                ts=ts,
                action="add",
                side=opposite_side,
                qty=qty,
                price=exec_price,
                reason="repair_invalidation_switch_probe",
                equity=equity,
                extra={"repair_efficiency": round(repair_eff, 4), "zone_score": opposite_score},
            )
        return

    if repair_eff >= config.repair_stop and adverse_usd > 0.0:
        cut_qty = book.qty if book.qty <= config.probe_units + 1e-12 else _unit_cut_qty(
            book.qty,
            0.50,
            minimum=config.probe_units,
        )
        removed = book.remove(qty=cut_qty, price=exec_price, role_priority=("battle", "chase", "base", "probe"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=ts,
            action="remove",
            reason="repair_efficiency_stop_trim",
            equity=equity,
        )
        counters["repair_stop_trims"] += 1
        return

    battle_ready = (
        capacity > 1e-12
        and _role_qty(book, "battle") <= 1e-12
        and same_score >= config.battle_score
        and scenario_allows_current
        and not market.bad_rr
        and not one_way_against
        and remaining_capacity_ratio >= config.min_capacity_ratio
        and repair_eff <= config.max_repair_eff_for_add
        and adverse_usd >= max(config.battle_trigger_usd, config.battle_trigger_atr * atr)
    )
    if battle_ready:
        qty = min(config.battle_units, capacity)
        _add_lot(
            book=book,
            side=side,
            qty=qty,
            price=exec_price,
            exec_idx=exec_idx,
            role="battle",
            zone_score=same_score,
            zone_reasons=same_reasons,
        )
        counters["battle_adds"] += 1
        _record_event(
            events,
            ts=ts,
            action="add",
            side=side,
            qty=qty,
            price=exec_price,
            reason="battle_add_with_repair_capacity",
            equity=equity,
            extra={
                "avg_entry": round(avg, 2),
                "recovery_price": round(recovery, 2),
                "repair_efficiency": round(repair_eff, 4),
                "capacity_ratio": round(remaining_capacity_ratio, 4),
                "zone_score": same_score,
            },
        )
        return

    if (
        same_score >= config.entry_score
        and scenario_allows_current
        and not market.bad_rr
        and not one_way_against
        and repair_eff <= config.max_repair_eff_for_add
        and book.qty < config.base_max_units - 1e-12
        and spacing_ok
        and capacity > 1e-12
    ):
        qty = min(config.base_add_units, config.base_max_units - book.qty, capacity)
        if qty > 1e-12:
            _add_lot(
                book=book,
                side=side,
                qty=qty,
                price=exec_price,
                exec_idx=exec_idx,
                role="base",
                zone_score=same_score,
                zone_reasons=same_reasons,
            )
            counters["base_adds"] += 1
            _record_event(
                events,
                ts=ts,
                action="add",
                side=side,
                qty=qty,
                price=exec_price,
                reason="base_add_on_better_zone",
                equity=equity,
                extra={"zone_score": same_score, "repair_efficiency": round(repair_eff, 4)},
            )
            return

    if _role_qty(book, "battle") > 0.0:
        battle_age = max(exec_idx - lot.entry_idx for lot in book.tranches if lot.role == "battle")
        if battle_age >= config.max_battle_bars and favorable_from_recovery < 0.0:
            removed = book.remove(qty=_role_qty(book, "battle"), price=exec_price, role_priority=("battle",))
            stats = _exit_removed_lots(
                events=events,
                removed=removed,
                ts=ts,
                action="remove",
                reason="battle_timeout_no_reaction",
                equity=equity,
            )
            counters["battle_timeouts"] += 1
            counters["battle_failed"] += int(stats["battle_failed"])
            return

    if repair_eff >= config.repair_cut and adverse_usd > 0.0 and book.qty > config.probe_units:
        cut_qty = _unit_cut_qty(book.qty, 0.30, minimum=config.probe_units)
        removed = book.remove(qty=cut_qty, price=exec_price, role_priority=("battle", "chase", "base", "probe"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=ts,
            action="remove",
            reason="loss_rotation_repair_trim",
            equity=equity,
        )
        counters["loss_rotation_trims"] += 1
        return

    first_idx = book.first_entry_idx
    if first_idx is not None and exec_idx - first_idx >= config.max_hold_bars:
        removed = book.remove(qty=book.qty, price=exec_price, role_priority=("battle", "chase", "base", "probe"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=ts,
            action="remove",
            reason="hard_intraday_time_exit",
            equity=equity,
        )
        counters["hard_time_exits"] += 1
        return

    if first_idx is not None and exec_idx - first_idx >= config.max_stuck_bars and favorable_from_recovery < 0.0:
        cut_qty = _unit_cut_qty(book.qty, 0.35, minimum=config.probe_units)
        removed = book.remove(qty=cut_qty, price=exec_price, role_priority=("battle", "chase", "base", "probe"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=ts,
            action="remove",
            reason="stuck_position_trim",
            equity=equity,
        )
        counters["stuck_trims"] += 1
        return

    if (
        config.switch_enabled
        and opposite_zone_side
        and opposite_score >= config.opposite_score
        and market.bias == opposite_side
        and repair_eff >= config.repair_cut
        and favorable_from_recovery < 0.0
        and not market.bad_rr
    ):
        old_qty = book.qty
        removed = book.remove(qty=book.qty, price=exec_price, role_priority=("battle", "chase", "base", "probe"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=ts,
            action="remove",
            reason="opposite_switch_after_repair_failure",
            equity=equity,
        )
        reasons = zone.short_reasons if opposite_side < 0 else zone.long_reasons
        qty = min(config.probe_units, config.max_possible_units)
        _add_lot(
            book=book,
            side=opposite_side,
            qty=qty,
            price=exec_price,
            exec_idx=exec_idx,
            role="probe",
            zone_score=opposite_score,
            zone_reasons=reasons,
        )
        counters["switches"] += 1
        _record_event(
            events,
            ts=ts,
            action="add",
            side=opposite_side,
            qty=qty,
            price=exec_price,
            reason="opposite_switch_probe",
            equity=equity,
            extra={"old_qty": round(old_qty, 4), "repair_efficiency": round(repair_eff, 4)},
        )
        return

    trend_core = config.trend_core_units if market.bias == side else config.probe_units
    if favorable_from_recovery >= expected_reaction and book.qty > trend_core:
        trim_qty = min(book.qty - trend_core, _unit_cut_qty(book.qty, 0.35, minimum=config.probe_units))
        if book.qty - trim_qty < trend_core:
            trim_qty = book.qty
        removed = book.remove(qty=trim_qty, price=exec_price, role_priority=("chase", "battle", "base", "probe"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=ts,
            action="remove",
            reason="reaction_profit_trim",
            equity=equity,
        )
        counters["profit_trims"] += 1


def _monthly_stats(month_equity: dict[str, dict[str, float]]) -> dict[str, Any]:
    returns: dict[str, float] = {}
    doubled = 0
    losing = 0
    for month, values in sorted(month_equity.items()):
        start = values.get("start", 0.0)
        end = values.get("end", start)
        if start <= 0.0:
            continue
        ret = end / start - 1.0
        returns[month] = ret
        if ret >= 1.0:
            doubled += 1
        if ret < 0.0:
            losing += 1
    months = len(returns)
    return {
        "months": months,
        "monthly_returns": {key: round(value, 6) for key, value in returns.items()},
        "months_doubled": doubled,
        "monthly_double_rate": doubled / months if months else 0.0,
        "losing_months": losing,
    }


def backtest_config(
    *,
    symbol: str,
    features: FeatureSet,
    scenario_features: dict[str, FeatureSet],
    scenario_maps: dict[str, list[int]],
    config: MarketStateConfig,
    cost_rate: float,
    min_periods: int,
) -> dict[str, Any] | None:
    warmup = max(config.zone_lookback + 60, config.exec_slow + 30, 260)
    if len(features.bars) < max(min_periods, warmup + 10):
        return None

    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    min_equity = equity
    book = PositionBook()
    counters: Counter[str] = Counter()
    events: list[dict[str, Any]] = []
    bar_returns: list[float] = []
    month_equity: dict[str, dict[str, float]] = {}
    exposure_sum = 0.0
    exposure_bars = 0
    max_abs_weight = 0.0
    exposure_side_bars: Counter[str] = Counter()

    for exec_idx in range(warmup + 1, len(features.bars) - 1):
        sig_idx = exec_idx - 1
        exec_price = features.o[exec_idx]
        next_open = features.o[exec_idx + 1]
        if exec_price <= 0.0 or next_open <= 0.0:
            continue

        bar_start_equity = equity
        old_weight = _book_weight(config, book)
        market = _market_state(
            exec_features=features,
            scenario_features=scenario_features,
            scenario_maps=scenario_maps,
            exec_idx=exec_idx,
            sig_idx=sig_idx,
            config=config,
        )
        zone = _zone_plan(features=features, idx=sig_idx, market=market, config=config)
        if market.bad_rr:
            counters["bad_rr_bars"] += 1
        if market.one_way_side:
            counters[f"one_way_{_side_label(market.one_way_side)}_bars"] += 1

        _apply_decision(
            book=book,
            features=features,
            sig_idx=sig_idx,
            exec_idx=exec_idx,
            exec_price=exec_price,
            config=config,
            market=market,
            zone=zone,
            events=events,
            equity=equity,
            counters=counters,
        )

        new_weight = _book_weight(config, book)
        turnover = abs(new_weight - old_weight)
        trade_cost = turnover * cost_rate
        if trade_cost > 0.0:
            equity *= max(1.0 - trade_cost, 0.0)
            counters["turnover_events"] += 1

        liquidated = False
        if book.side != 0:
            liq_price = _liquidation_price(config, book.side, book.avg_entry)
            if (book.side > 0 and features.l[exec_idx] <= liq_price) or (
                book.side < 0 and features.h[exec_idx] >= liq_price
            ):
                margin_fraction = min(abs(new_weight) / max(config.exchange_leverage, 1e-12), 1.0)
                liquidation_loss = min(equity * margin_fraction, equity * 0.995)
                counters["liquidations"] += 1
                _record_event(
                    events,
                    ts=features.ts[exec_idx],
                    action="liquidation",
                    side=book.side,
                    qty=book.qty,
                    price=liq_price,
                    reason="exchange_liquidation_proxy",
                    equity=equity,
                    extra={
                        "avg_entry": round(book.avg_entry, 2),
                        "weight": round(new_weight, 4),
                        "loss_fraction": round(margin_fraction, 6),
                    },
                )
                equity = max(equity - liquidation_loss, 1e-12)
                book.reset()
                new_weight = 0.0
                liquidated = True

        if not liquidated and new_weight != 0.0:
            raw_price_return = next_open / exec_price - 1.0
            equity *= max(1.0 + new_weight * raw_price_return, 1e-12)

        bar_return = equity / max(bar_start_equity, 1e-12) - 1.0
        if math.isfinite(bar_return):
            bar_returns.append(bar_return)

        month = features.ts[exec_idx].strftime("%Y-%m")
        if month not in month_equity:
            month_equity[month] = {"start": equity, "end": equity}
        month_equity[month]["end"] = equity

        peak = max(peak, equity)
        min_equity = min(min_equity, equity)
        if peak > 0.0:
            max_drawdown = max(max_drawdown, 1.0 - equity / peak)
        exposure_sum += abs(new_weight)
        max_abs_weight = max(max_abs_weight, abs(new_weight))
        exposure_bars += 1
        if new_weight > 1e-12:
            exposure_side_bars["long"] += 1
        elif new_weight < -1e-12:
            exposure_side_bars["short"] += 1
        else:
            exposure_side_bars["flat"] += 1

        if equity <= 0.02:
            counters["account_ruin_events"] += 1
            break

    if book.side != 0:
        removed = book.remove(qty=book.qty, price=features.c[-1], role_priority=("battle", "chase", "base", "probe"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=features.ts[-1],
            action="remove",
            reason="end_of_sample",
            equity=equity,
        )

    first_ts = features.ts[warmup + 1] if len(features.ts) > warmup + 1 else features.ts[0]
    last_ts = features.ts[min(len(features.ts) - 1, warmup + 1 + exposure_bars)] if exposure_bars else features.ts[-1]
    years = max(_year_fraction(first_ts, last_ts), 1e-12)
    final_return = equity - 1.0
    cagr = equity ** (1.0 / years) - 1.0 if equity > 0.0 else -1.0
    periods_per_year = 365.25 * 24.0 * 60.0 * 60.0 * 1000.0 / _INTERVAL_MS[config.exec_interval]
    if len(bar_returns) >= 5:
        avg_ret = mean(bar_returns)
        vol = pstdev(bar_returns)
        sharpe = avg_ret / vol * math.sqrt(periods_per_year) if vol > 1e-12 else 0.0
    else:
        sharpe = 0.0

    monthly = _monthly_stats(month_equity)
    battle_success = counters.get("battle_success", 0)
    battle_failed = counters.get("battle_failed", 0)
    battle_resolved = battle_success + battle_failed
    battle_success_rate = battle_success / battle_resolved if battle_resolved else 0.0
    avg_abs_weight = exposure_sum / max(exposure_bars, 1)
    score = (
        cagr
        - 1.45 * max_drawdown
        + 0.25 * sharpe
        + 0.20 * monthly["monthly_double_rate"]
        + 0.18 * battle_success_rate
        - 1.75 * counters.get("liquidations", 0)
        - 2.50 * counters.get("account_ruin_events", 0)
    )

    trade_like_events = (
        counters.get("probe_adds", 0)
        + counters.get("base_adds", 0)
        + counters.get("battle_adds", 0)
        + counters.get("chase_adds", 0)
        + counters.get("switches", 0)
    )
    if len(events) <= 24:
        sample_events = events
    else:
        sample_events = events[:12] + [{"omitted_events": len(events) - 24}] + events[-12:]
    event_diagnostics = _event_diagnostics(
        events=events,
        counters=counters,
        exposure_side_bars=exposure_side_bars,
        exposure_bars=exposure_bars,
        total_months=int(monthly["months"]),
    )

    return {
        "model_id": config.model_id,
        "symbol": symbol,
        "exec_interval": config.exec_interval,
        "scenario_intervals": list(scenario_features),
        "final_equity": round(equity, 8),
        "total_return_pct": round(final_return * 100.0, 4),
        "cagr_pct": round(cagr * 100.0, 4),
        "max_drawdown_pct": round(max_drawdown * 100.0, 4),
        "min_equity": round(min_equity, 8),
        "sharpe_proxy": round(sharpe, 4),
        "years": round(years, 4),
        "score": round(score, 6),
        "avg_abs_account_exposure": round(avg_abs_weight, 4),
        "max_abs_account_exposure": round(max_abs_weight, 4),
        "trade_like_events": int(trade_like_events),
        "event_counts": dict(counters),
        "battle_adds": int(counters.get("battle_adds", 0)),
        "battle_success_rate": round(battle_success_rate, 6),
        "monthly": monthly,
        "event_diagnostics": event_diagnostics,
        "config": asdict(config),
        "sample_events": sample_events,
    }


def build_configs(
    *,
    exec_interval: str,
    exchange_leverage: float,
    maintenance_margin_pct: float,
    max_account_exposures: list[float],
    battle_units_options: list[float],
) -> list[MarketStateConfig]:
    configs: list[MarketStateConfig] = []
    profiles = (
        ("balanced", False, 1.10, 1.55, 1.25, 0.45, 2.8),
        ("strict_sample_generalized", True, 1.05, 1.45, 1.15, 0.55, 2.5),
    )
    for zone_lookback in (48, 96):
        for entry_score in (5, 6):
            for battle_score in (7, 8):
                for base_max_units in (3.0, 5.0):
                    for battle_units in battle_units_options:
                        for max_exposure in max_account_exposures:
                            for reaction_usd in (200.0, 350.0):
                                for max_battle_bars in (3, 6):
                                    for max_hold_bars in (144, 288):
                                        for (
                                            profile_name,
                                            strict_scenario_entry,
                                            repair_cut,
                                            repair_stop,
                                            max_repair_eff_for_add,
                                            min_capacity_ratio,
                                            bad_rr_atr,
                                        ) in profiles:
                                            max_possible_units = 10.0
                                            if base_max_units + battle_units > max_possible_units:
                                                continue
                                            model_id = (
                                                f"{exec_interval}:market_state_rotation_v4:{profile_name}:"
                                                f"lb{zone_lookback}:entry{entry_score}:battle{battle_score}:"
                                                f"baseMax{base_max_units:g}:battleU{battle_units:g}:"
                                                f"gross{max_exposure:g}:react{reaction_usd:g}:"
                                                f"bBars{max_battle_bars}:hold{max_hold_bars}:lev{exchange_leverage:g}"
                                            )
                                            configs.append(
                                                MarketStateConfig(
                                                    model_id=model_id,
                                                    exec_interval=exec_interval,
                                                    htf_fast=21,
                                                    htf_slow=89,
                                                    htf_band_atr=0.12,
                                                    exec_fast=13,
                                                    exec_slow=55,
                                                    zone_lookback=zone_lookback,
                                                    entry_score=entry_score,
                                                    battle_score=battle_score,
                                                    opposite_score=max(entry_score + 1, 7),
                                                    max_possible_units=max_possible_units,
                                                    base_max_units=base_max_units,
                                                    probe_units=1.0,
                                                    base_add_units=1.0,
                                                    battle_units=battle_units,
                                                    chase_units=2.0,
                                                    max_account_exposure=max_exposure,
                                                    exchange_leverage=exchange_leverage,
                                                    maintenance_margin_pct=maintenance_margin_pct,
                                                    reaction_usd=reaction_usd,
                                                    reaction_atr=1.15,
                                                    base_spacing_atr=0.75,
                                                    battle_trigger_usd=max(180.0, reaction_usd),
                                                    battle_trigger_atr=1.30,
                                                    repair_cut=repair_cut,
                                                    repair_stop=repair_stop,
                                                    max_repair_eff_for_add=max_repair_eff_for_add,
                                                    min_capacity_ratio=min_capacity_ratio,
                                                    bad_rr_atr=bad_rr_atr,
                                                    one_way_threshold=1.85,
                                                    one_way_window=12,
                                                    max_battle_bars=max_battle_bars,
                                                    max_stuck_bars=96,
                                                    max_hold_bars=max_hold_bars,
                                                    min_liquidation_buffer_pct=0.018,
                                                    trend_core_units=1.0 if strict_scenario_entry else 2.0,
                                                    strict_scenario_entry=strict_scenario_entry,
                                                    switch_enabled=True,
                                                )
                                            )
    return configs


def _load_feature_sets(args: argparse.Namespace) -> tuple[FeatureSet, dict[str, FeatureSet], dict[str, list[int]], dict[str, Any]]:
    settings = get_settings()
    base_url = str(args.base_url or settings.binance_rest_base_url or "https://fapi.binance.com").rstrip("/")
    cache_dir = Path(args.cache_dir)
    load_days = max(int(args.load_days), int(args.days))

    exec_bars = _load_bars(
        symbol=args.symbol,
        interval=args.exec_interval,
        days=load_days,
        cache_dir=cache_dir,
        base_url=base_url,
        sleep_seconds=float(args.sleep_seconds),
    )
    exec_bars = _slice_last_days(exec_bars, int(args.days))
    features = FeatureSet(exec_bars)

    scenario_features: dict[str, FeatureSet] = {}
    scenario_maps: dict[str, list[int]] = {}
    for interval in _csv(args.scenario_intervals):
        bars = _load_bars(
            symbol=args.symbol,
            interval=interval,
            days=load_days,
            cache_dir=cache_dir,
            base_url=base_url,
            sleep_seconds=float(args.sleep_seconds),
        )
        if exec_bars:
            start_ms = exec_bars[0].open_ms - _INTERVAL_MS[interval] * 300
            end_ms = exec_bars[-1].open_ms
            bars = [bar for bar in bars if start_ms <= bar.open_ms <= end_ms]
        scenario_features[interval] = FeatureSet(bars)
        scenario_maps[interval] = _map_closed_indices(exec_bars, bars, interval)

    meta = {
        "base_url": base_url,
        "exec_rows": len(exec_bars),
        "exec_start": exec_bars[0].ts.isoformat() if exec_bars else None,
        "exec_end": exec_bars[-1].ts.isoformat() if exec_bars else None,
        "scenario_rows": {interval: len(fs.bars) for interval, fs in scenario_features.items()},
    }
    return features, scenario_features, scenario_maps, meta


def _write_markdown_summary(report: dict[str, Any], path: Path) -> None:
    top = report.get("top_results", [])
    best = top[0] if top else {}
    best_diag = dict(best.get("event_diagnostics") or {}) if best else {}
    lines = [
        "# Market-State Rotation V4 Backtest Summary",
        "",
        f"- Created at: `{report.get('created_at')}`",
        f"- Symbol: `{report.get('args', {}).get('symbol')}`",
        f"- Execution interval: `{report.get('args', {}).get('exec_interval')}`",
        f"- Days: `{report.get('args', {}).get('days')}`",
        f"- Tested configs: `{report.get('tested_configs')}`",
        f"- Data: `{report.get('data', {}).get('exec_start')}` to `{report.get('data', {}).get('exec_end')}`",
        "",
        "## Best Result",
        "",
    ]
    if best:
        lines.extend(
            [
                f"- Model: `{best.get('model_id')}`",
                f"- Total return: `{best.get('total_return_pct')}%`",
                f"- CAGR: `{best.get('cagr_pct')}%`",
                f"- Max drawdown: `{best.get('max_drawdown_pct')}%`",
                f"- Max account exposure: `{best.get('max_abs_account_exposure')}x`",
                f"- Trade-like events: `{best.get('trade_like_events')}`",
                f"- Battle adds: `{best.get('battle_adds')}`",
                f"- Battle success rate: `{best.get('battle_success_rate')}`",
                f"- Order distribution health: `{best_diag.get('health')}`",
                f"- Distribution flags: `{', '.join(best_diag.get('flags') or []) or 'none'}`",
                f"- Event counts: `{json.dumps(best.get('event_counts', {}), ensure_ascii=False)}`",
                "",
            ]
        )
        lines.extend(
            [
                "## Best Result Order Distribution",
                "",
                f"- Adds by side: `{json.dumps(best_diag.get('add_by_side', {}), ensure_ascii=False)}`",
                f"- Add side share: `{json.dumps(best_diag.get('add_side_share', {}), ensure_ascii=False)}`",
                f"- Adds by role: `{json.dumps(best_diag.get('add_by_role', {}), ensure_ascii=False)}`",
                f"- Monthly adds: `{json.dumps(best_diag.get('monthly_adds', {}), ensure_ascii=False)}`",
                f"- Active order months: `{best_diag.get('active_order_months')}/{best_diag.get('total_months')}`",
                f"- Max month add share: `{best_diag.get('max_month_add_share')}`",
                f"- KST hour max share: `{best_diag.get('max_kst_hour_add_share')}`",
                f"- Exposure side share: `{json.dumps(best_diag.get('exposure_side_share', {}), ensure_ascii=False)}`",
                f"- Ratios: `{json.dumps(best_diag.get('ratios', {}), ensure_ascii=False)}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Interpretation",
            "",
            "This run treats the Telegram/PDF/video material as strategy samples only.",
            "No message price level is used as an entry signal. All entries, trims, battle adds, and switches are generated from market bars.",
            "The v4-specific mechanics are repair efficiency, bad-RR no-trade filtering, battle-first reduction, and one-way forced trimming.",
            "",
            "## Top 10",
            "",
            "| rank | return % | CAGR % | MDD % | exposure | events | battle adds | dist | model |",
            "|---:|---:|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for idx, result in enumerate(top[:10], start=1):
        diagnostics = dict(result.get("event_diagnostics") or {})
        lines.append(
            f"| {idx} | {result.get('total_return_pct')} | {result.get('cagr_pct')} | "
            f"{result.get('max_drawdown_pct')} | {result.get('max_abs_account_exposure')} | "
            f"{result.get('trade_like_events')} | {result.get('battle_adds')} | "
            f"{diagnostics.get('health', 'n/a')} | `{result.get('model_id')}` |"
        )
    lines.append("")
    atomic_write_text(path, "\n".join(lines))


def main() -> None:
    args = _parse_args()
    if args.exec_interval not in _INTERVAL_MS:
        raise SystemExit(f"unsupported exec interval: {args.exec_interval}")
    for interval in _csv(args.scenario_intervals):
        if interval not in _INTERVAL_MS:
            raise SystemExit(f"unsupported scenario interval: {interval}")

    features, scenario_features, scenario_maps, data_meta = _load_feature_sets(args)
    if len(features.bars) < int(args.min_periods):
        raise SystemExit(f"not enough execution bars: {len(features.bars)} < {args.min_periods}")

    max_account_exposures = _parse_float_csv(args.max_account_exposures, [1.0, 2.0, 3.0, 5.0])
    battle_units_options = _parse_float_csv(args.battle_units, [3.0, 5.0])
    configs = build_configs(
        exec_interval=args.exec_interval,
        exchange_leverage=float(args.exchange_leverage),
        maintenance_margin_pct=float(args.maintenance_margin_pct),
        max_account_exposures=max_account_exposures,
        battle_units_options=battle_units_options,
    )
    if int(args.model_offset) > 0:
        configs = configs[int(args.model_offset) :]
    if int(args.max_models) > 0:
        configs = configs[: int(args.max_models)]

    cost_rate = (max(float(args.fee_bps_per_side), 0.0) + max(float(args.slippage_bps_per_side), 0.0)) / 10_000.0
    results: list[dict[str, Any]] = []
    for idx, config in enumerate(configs, start=1):
        result = backtest_config(
            symbol=args.symbol,
            features=features,
            scenario_features=scenario_features,
            scenario_maps=scenario_maps,
            config=config,
            cost_rate=cost_rate,
            min_periods=int(args.min_periods),
        )
        if result is not None:
            results.append(result)
        if idx % 25 == 0:
            print(f"tested {idx}/{len(configs)} configs", flush=True)

    results.sort(
        key=lambda item: (
            item["score"],
            item["cagr_pct"],
            -item["max_drawdown_pct"],
            item["battle_success_rate"],
        ),
        reverse=True,
    )

    positive = sum(1 for item in results if item["total_return_pct"] > 0.0)
    monthly_double = sum(1 for item in results if item["monthly"]["months_doubled"] > 0)
    distribution_health_counts = Counter(
        str(dict(item.get("event_diagnostics") or {}).get("health") or "unknown")
        for item in results
    )
    distribution_flag_counts: Counter[str] = Counter()
    for item in results:
        for flag in dict(item.get("event_diagnostics") or {}).get("flags") or []:
            distribution_flag_counts[str(flag)] += 1
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "strategy_note": (
            "Market-state rotation v4 proxy. Telegram/PDF/video material is used only to design "
            "the state machine. Trading decisions use market bars only."
        ),
        "risk_note": (
            "This is a research proxy with simplified liquidation, fee, slippage, and open-to-open execution. "
            "It is not an execution-ready live strategy."
        ),
        "args": vars(args),
        "data": data_meta,
        "tested_configs": len(configs),
        "result_count": len(results),
        "positive_result_count": positive,
        "monthly_double_candidate_count": monthly_double,
        "distribution_health_counts": _counter_payload(distribution_health_counts),
        "distribution_flag_counts": _counter_payload(distribution_flag_counts),
        "top_results": results[:30],
        "all_results": results,
    }

    if args.write_report:
        report_dir = Path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        json_path = report_dir / f"market_state_rotation_v4_{args.symbol}_{args.exec_interval}_{args.days}d_{stamp}.json"
        latest_json = report_dir / f"market_state_rotation_v4_{args.symbol}_{args.exec_interval}_{args.days}d_latest.json"
        summary_md = report_dir / "summary_v4.md"
        text = json.dumps(report, ensure_ascii=False, indent=2)
        atomic_write_text(json_path, text)
        atomic_write_text(latest_json, text)
        _write_markdown_summary(report, summary_md)
        print(f"wrote {json_path}")
        print(f"wrote {latest_json}")
        print(f"wrote {summary_md}")

    print(
        json.dumps(
            {
                "data": data_meta,
                "tested": len(configs),
                "positive": positive,
                "monthly_double_candidates": monthly_double,
                "top_results": results[:5],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
