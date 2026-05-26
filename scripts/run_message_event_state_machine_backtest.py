#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import product
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text
from scripts.run_btc_flip_rotation_search import _csv, _load_bars, Bar
from scripts.run_message_event_level_backtest import BAD_SNIPPET_TOKENS, STRICT_SOURCE_KINDS
from scripts.run_message_event_reaction_backtest import (
    ReactionConfig,
    _atr,
    _bar_index,
    _close_position,
    _find_touch,
    _level_from_event,
    _reaction_confirmed,
    _side_label,
    build_orders,
)


ENTRY_ACTIONS = {"entry_plan", "victory_zone", "add_plan", "entry_done"}
MANAGEMENT_ACTIONS = {"bias", "switch", "stop_plan", "take_profit_done", "reduce_done", "wait", "risk"}


@dataclass(frozen=True, slots=True)
class StateConfig:
    model_id: str
    entry_source_kinds: str
    infer_neutral_entry_side: bool
    validity_hours: int
    reaction_wait_bars: int
    close_position_threshold: float
    reclaim_buffer_atr: float
    max_chase_pct: float
    max_hold_hours: int
    signal_max_hold_hours: int
    flip_max_hold_hours: int
    stop_flip_max_hold_hours: int
    partial_tp_pct: float
    full_tp_pct: float
    secondary_tp_pct: float
    stop_pct: float
    trail_pct: float
    post_partial_stop_pct: float
    max_gross_exposure: float
    entry_fraction: float
    add_fraction: float
    reduce_fraction: float
    signal_reduce_fraction: float
    flip_reduce_fraction: float
    stop_flip_reduce_fraction: float
    secondary_reduce_fraction: float
    entry_plan_multiplier: float
    victory_zone_multiplier: float
    add_plan_multiplier: float
    same_side_victory_multiplier: float
    flip_entry_fraction: float
    stop_flip_entry_fraction: float
    message_wait_reduce_fraction: float
    message_risk_reduce_fraction: float
    include_done: bool
    flip_on_opposite_signal: bool
    flip_on_stop: bool
    stop_flip_mode: str
    stop_flip_min_wait_minutes: int
    stop_flip_confirm_minutes: int
    stop_flip_retest_buffer_pct: float
    max_stop_flip_depth: int
    trend_filter_mode: str
    trend_fast_minutes: int
    trend_slow_minutes: int
    min_trend_atr: float
    max_trend_atr: float
    min_atr_pct: float
    max_atr_pct: float
    post_stop_cooldown_hours: int
    use_bias_filter: bool
    risk_cooldown_hours: int
    drawdown_throttle_pct: float
    drawdown_throttle_multiplier: float


@dataclass(frozen=True, slots=True)
class Signal:
    signal_id: str
    message_id: str
    event_id: str
    idx: int
    created_ts: datetime
    side: int
    action: str
    source_kind: str
    level: float
    reaction_reason: str
    snippet: str


@dataclass(frozen=True, slots=True)
class ManagementEvent:
    event_id: str
    message_id: str
    idx: int
    ts: datetime
    side: int
    action: str
    source_kind: str
    confidence: int
    levels: tuple[float, ...]
    snippet: str


@dataclass(slots=True)
class Leg:
    leg_id: str
    side: int
    entry_idx: int
    entry_ts: datetime
    entry_price: float
    notional: float
    action: str
    source_kind: str
    snippet: str


@dataclass(slots=True)
class Position:
    side: int
    legs: list[Leg]
    opened_idx: int
    deadline_idx: int
    best_price: float
    partial_taken: bool = False
    secondary_taken: bool = False
    active_stop: float | None = None
    stop_flip_depth: int = 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="State-machine backtest for message-derived rotation trading.")
    parser.add_argument("--labels", default="reports/research/nanyotti_export/message_event_dataset/message_event_labels.json")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--load-days", type=int, default=1825)
    parser.add_argument("--validity-hours", default="24,72")
    parser.add_argument("--reaction-wait-bars", default="6,12")
    parser.add_argument("--close-position-thresholds", default="0.55,0.75")
    parser.add_argument("--reclaim-buffer-atrs", default="0,0.05")
    parser.add_argument("--max-chase-pcts", default="0.6,1.0")
    parser.add_argument("--entry-source-kinds", default="message,scenario,view")
    parser.add_argument("--management-source-kinds", default="message,scenario,view")
    parser.add_argument("--infer-neutral-entry-side", default="0")
    parser.add_argument("--max-hold-hours", default="4,12")
    parser.add_argument("--signal-max-hold-hours", default="")
    parser.add_argument("--flip-max-hold-hours", default="")
    parser.add_argument("--stop-flip-max-hold-hours", default="")
    parser.add_argument("--partial-tp-pcts", default="0.3")
    parser.add_argument("--full-tp-pcts", default="0.6,1.0")
    parser.add_argument("--secondary-tp-pcts", default="0")
    parser.add_argument("--stop-pcts", default="0.5,0.8")
    parser.add_argument("--trail-pcts", default="0,0.6")
    parser.add_argument("--post-partial-stop-pcts", default="0")
    parser.add_argument("--max-gross-exposures", default="5,10")
    parser.add_argument("--entry-fractions", default="0.4,0.6")
    parser.add_argument("--add-fractions", default="0.25")
    parser.add_argument("--reduce-fractions", default="0,0.5")
    parser.add_argument("--signal-reduce-fractions", default="")
    parser.add_argument("--flip-reduce-fractions", default="")
    parser.add_argument("--stop-flip-reduce-fractions", default="")
    parser.add_argument("--secondary-reduce-fractions", default="0.5")
    parser.add_argument("--entry-plan-multipliers", default="1")
    parser.add_argument("--victory-zone-multipliers", default="1.15")
    parser.add_argument("--add-plan-multipliers", default="0.75")
    parser.add_argument("--same-side-victory-multipliers", default="1.25")
    parser.add_argument("--flip-entry-fractions", default="")
    parser.add_argument("--stop-flip-entry-fractions", default="")
    parser.add_argument("--message-wait-reduce-fractions", default="")
    parser.add_argument("--message-risk-reduce-fractions", default="")
    parser.add_argument("--flip-opposite", default="1")
    parser.add_argument("--flip-stop", default="0,1")
    parser.add_argument("--stop-flip-modes", default="")
    parser.add_argument("--stop-flip-min-wait-minutes", default="15,30")
    parser.add_argument("--stop-flip-confirm-minutes", default="60,180")
    parser.add_argument("--stop-flip-retest-buffers", default="0,0.15")
    parser.add_argument("--max-stop-flip-depths", default="1")
    parser.add_argument("--trend-filters", default="off")
    parser.add_argument("--trend-fast-minutes", default="120")
    parser.add_argument("--trend-slow-minutes", default="720")
    parser.add_argument("--min-trend-atrs", default="0")
    parser.add_argument("--max-trend-atrs", default="0")
    parser.add_argument("--min-atr-pcts", default="0")
    parser.add_argument("--max-atr-pcts", default="0")
    parser.add_argument("--post-stop-cooldown-hours", default="0")
    parser.add_argument("--bias-filter", default="0,1")
    parser.add_argument("--risk-cooldown-hours", default="0,6")
    parser.add_argument("--drawdown-throttle-pcts", default="0")
    parser.add_argument("--drawdown-throttle-multipliers", default="0.5")
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument("--cache-dir", default="reports/validation/btc_flip_rotation_search/cache")
    parser.add_argument("--report-dir", default="reports/research/nanyotti_export/message_event_dataset/state_machine")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    parser.add_argument("--max-configs", type=int, default=0)
    return parser.parse_args()


def _parse_float_csv(raw: str, fallback: list[float], *, allow_zero: bool = False) -> list[float]:
    out: list[float] = []
    for item in _csv(raw):
        try:
            value = float(item)
        except ValueError:
            continue
        if value > 0.0 or (allow_zero and value == 0.0):
            out.append(value)
    return out or fallback


def _parse_int_csv(raw: str, fallback: list[int], *, allow_zero: bool = False) -> list[int]:
    out: list[int] = []
    for item in _csv(raw):
        try:
            value = int(item)
        except ValueError:
            continue
        if value > 0 or (allow_zero and value == 0):
            out.append(value)
    return out or fallback


def _parse_bool_csv(raw: str, fallback: list[bool]) -> list[bool]:
    values: list[bool] = []
    for item in _csv(raw):
        lowered = item.lower()
        if lowered in {"1", "true", "yes", "y"}:
            values.append(True)
        elif lowered in {"0", "false", "no", "n"}:
            values.append(False)
    return values or fallback


def _parse_choice_csv(raw: str, allowed: set[str], fallback: list[str]) -> list[str]:
    values: list[str] = []
    for item in _csv(raw):
        lowered = item.lower()
        if lowered in allowed:
            values.append(lowered)
    return values or fallback


def _source_kinds_from_csv(raw: str, fallback: set[str]) -> set[str]:
    values = {item.strip().lower() for item in str(raw or "").split(",") if item.strip()}
    return values or set(fallback)


def _source_kind_csv(source_kinds: set[str]) -> str:
    return ",".join(sorted(source_kinds))


def _source_kind_slug(source_kinds: str) -> str:
    parts = [item.strip() for item in source_kinds.split(",") if item.strip()]
    aliases = {
        "account_update": "acct",
        "education": "edu",
        "message": "msg",
        "review": "rev",
        "scenario": "scn",
        "view": "view",
    }
    return "-".join(aliases.get(item, item) for item in parts)


def _interval_minutes(interval: str) -> int:
    if interval.endswith("m"):
        return max(int(interval[:-1]), 1)
    if interval.endswith("h"):
        return max(int(interval[:-1]) * 60, 1)
    raise ValueError(f"unsupported_interval_for_state_machine: {interval}")


def _ema(values: list[float], length: int) -> list[float]:
    if not values:
        return []
    length = max(int(length), 1)
    alpha = 2.0 / (length + 1.0)
    value = float(values[0])
    out: list[float] = []
    for item in values:
        value = alpha * float(item) + (1.0 - alpha) * value
        out.append(value)
    return out


def _trend_spread_atr(
    *,
    bars: list[Bar],
    atr: list[float],
    interval_minutes: int,
    fast_minutes: int,
    slow_minutes: int,
    feature_cache: dict[tuple[str, int, int], list[float]],
) -> list[float]:
    if fast_minutes <= 0 or slow_minutes <= 0:
        return [0.0] * len(bars)
    fast_bars = max(int(math.ceil(fast_minutes / max(interval_minutes, 1))), 2)
    slow_bars = max(int(math.ceil(slow_minutes / max(interval_minutes, 1))), fast_bars + 1)
    key = ("trend_spread_atr", fast_bars, slow_bars)
    cached = feature_cache.get(key)
    if cached is not None:
        return cached
    closes = [bar.c for bar in bars]
    fast = _ema(closes, fast_bars)
    slow = _ema(closes, slow_bars)
    spread = [(fast[idx] - slow[idx]) / max(atr[idx], 1e-12) for idx in range(len(bars))]
    feature_cache[key] = spread
    return spread


def _entry_context_allowed(
    *,
    config: StateConfig,
    bars: list[Bar],
    atr: list[float],
    trend_spread_atr: list[float],
    idx: int,
    side: int,
    stats: Counter[str],
) -> bool:
    if idx >= len(bars) or side == 0:
        return False
    price = max(bars[idx].c, 1e-12)
    atr_pct = atr[idx] / price * 100.0 if idx < len(atr) else 0.0
    if config.min_atr_pct > 0.0 and atr_pct < config.min_atr_pct:
        stats["blocked_low_atr"] += 1
        return False
    if config.max_atr_pct > 0.0 and atr_pct > config.max_atr_pct:
        stats["blocked_high_atr"] += 1
        return False
    if config.trend_filter_mode == "aligned":
        spread = trend_spread_atr[idx] if idx < len(trend_spread_atr) else 0.0
        aligned_strength = side * spread
        if aligned_strength < config.min_trend_atr:
            stats["blocked_trend_filter"] += 1
            return False
        if config.max_trend_atr > 0.0 and aligned_strength > config.max_trend_atr:
            stats["blocked_overextended_trend"] += 1
            return False
    return True


def _event_ts(event: dict[str, Any]) -> datetime:
    ts = datetime.fromisoformat(str(event["date_utc"]))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def _levels_from_event(event: dict[str, Any]) -> tuple[float, ...]:
    levels = [float(item["value"]) for item in event.get("price_levels") or [] if item.get("value")]
    return tuple(sorted(set(level for level in levels if 1_000.0 < level < 300_000.0)))


def _infer_switch_side(snippet: str, side: int) -> int:
    if side != 0:
        return side
    text = snippet.replace(" ", "")
    short_tokens = ("숏으로전환", "숏스위칭", "숏전환", "롱흐름이순식간에숏")
    long_tokens = ("롱으로전환", "롱스위칭", "롱전환", "숏을보유중이나", "즉시롱")
    if any(token in text for token in short_tokens):
        return -1
    if any(token in text for token in long_tokens):
        return 1
    return 0


def _management_allowed(event: dict[str, Any], *, source_kinds: set[str]) -> bool:
    if event.get("source_kind") not in source_kinds:
        return False
    if event.get("action") not in MANAGEMENT_ACTIONS:
        return False
    snippet = str(event.get("snippet") or "")
    if any(token in snippet for token in ("교육", "자료", "영상", "강의")) and event.get("source_kind") == "education":
        return False
    return not any(token in snippet for token in BAD_SNIPPET_TOKENS if token != "진입하지")


def build_management_events(
    events: list[dict[str, Any]],
    bars: list[Bar],
    open_times: list[int],
    *,
    source_kinds: set[str] | None = None,
) -> list[ManagementEvent]:
    allowed_source_kinds = source_kinds or STRICT_SOURCE_KINDS
    out: list[ManagementEvent] = []
    for event in events:
        if not _management_allowed(event, source_kinds=allowed_source_kinds):
            continue
        ts = _event_ts(event)
        idx = _bar_index(open_times, ts)
        if idx is None:
            continue
        idx = min(idx + 1, len(bars) - 1)
        side = int(event.get("side_value") or 0)
        snippet = str(event.get("snippet") or "")
        if event.get("action") == "switch":
            side = _infer_switch_side(snippet, side)
        out.append(
            ManagementEvent(
                event_id=str(event["event_id"]),
                message_id=str(event["message_id"]),
                idx=idx,
                ts=bars[idx].ts,
                side=side,
                action=str(event["action"]),
                source_kind=str(event["source_kind"]),
                confidence=int(event.get("confidence") or 0),
                levels=_levels_from_event(event),
                snippet=snippet,
            )
        )
    out.sort(key=lambda item: (item.idx, item.event_id))
    return out


def build_signals(
    *,
    labels: list[dict[str, Any]],
    bars: list[Bar],
    open_times: list[int],
    atr: list[float],
    config: StateConfig,
) -> list[Signal]:
    reaction_config = ReactionConfig(
        model_id=config.model_id,
        validity_hours=config.validity_hours,
        reaction_wait_bars=config.reaction_wait_bars,
        close_position_threshold=config.close_position_threshold,
        reclaim_buffer_atr=config.reclaim_buffer_atr,
        max_chase_pct=config.max_chase_pct,
        hold_hours=config.max_hold_hours,
        tp_pct=config.partial_tp_pct,
        sl_pct=config.stop_pct,
        account_exposure=config.max_gross_exposure,
        include_done=config.include_done,
    )
    orders = build_orders(
        labels,
        include_done=config.include_done,
        source_kinds=_source_kinds_from_csv(config.entry_source_kinds, STRICT_SOURCE_KINDS),
        infer_neutral_side=config.infer_neutral_entry_side,
    )
    signals: list[Signal] = []
    for order in orders:
        touch_idx = _find_touch(order, bars, open_times, reaction_config)
        if touch_idx is None:
            continue
        entry = _reaction_confirmed(order=order, bars=bars, atr=atr, touch_idx=touch_idx, config=reaction_config)
        if entry is None or entry.entry_idx >= len(bars):
            continue
        signals.append(
            Signal(
                signal_id=f"{order.order_id}:entry@{entry.entry_idx}",
                message_id=order.message_id,
                event_id=order.event_id,
                idx=entry.entry_idx,
                created_ts=order.created_ts,
                side=order.side,
                action=order.action,
                source_kind=order.source_kind,
                level=entry.level,
                reaction_reason=entry.reaction_reason,
                snippet=order.snippet,
            )
        )
    signals.sort(key=lambda item: (item.idx, item.signal_id))
    return signals


def _weighted_avg_entry(position: Position) -> float:
    total = sum(leg.notional for leg in position.legs)
    if total <= 0.0:
        return 0.0
    return sum(leg.entry_price * leg.notional for leg in position.legs) / total


def _gross_exposure(position: Position | None, equity: float) -> float:
    if position is None or equity <= 0.0:
        return 0.0
    return sum(leg.notional for leg in position.legs) / equity


def _position_mtm_equity(position: Position | None, equity: float, price: float) -> float:
    if position is None:
        return equity
    unrealized = 0.0
    for leg in position.legs:
        unrealized += leg.notional * leg.side * (price / leg.entry_price - 1.0)
    return equity + unrealized


def _same_or_neutral(event_side: int, position_side: int) -> bool:
    return event_side == 0 or event_side == position_side


def _entry_exposure(config: StateConfig, signal: Signal, position: Position | None) -> float:
    if position is None:
        if signal.action == "victory_zone":
            multiplier = config.victory_zone_multiplier
        elif signal.action == "add_plan":
            multiplier = config.add_plan_multiplier
        else:
            multiplier = config.entry_plan_multiplier
        return config.max_gross_exposure * config.entry_fraction * multiplier
    multiplier = config.same_side_victory_multiplier if signal.action == "victory_zone" else 1.0
    return config.max_gross_exposure * config.add_fraction * multiplier


def _drawdown_adjusted_exposure(
    *,
    config: StateConfig,
    requested_exposure: float,
    equity: float,
    peak_state: dict[str, float] | None,
    stats: Counter[str] | None,
) -> float:
    if config.drawdown_throttle_pct <= 0.0 or config.drawdown_throttle_multiplier >= 1.0:
        return requested_exposure
    peak = max((peak_state or {}).get("peak", equity), equity, 1e-12)
    drawdown_pct = max((1.0 - equity / peak) * 100.0, 0.0)
    if drawdown_pct < config.drawdown_throttle_pct:
        return requested_exposure
    if stats is not None:
        stats["drawdown_throttle"] += 1
    return requested_exposure * max(config.drawdown_throttle_multiplier, 0.0)


def _open_leg(
    *,
    config: StateConfig,
    bars: list[Bar],
    idx: int,
    side: int,
    requested_exposure: float,
    equity: float,
    position: Position | None,
    reason: str,
    source_kind: str,
    snippet: str,
    interval_minutes: int,
    ledger: list[dict[str, Any]],
    peak_state: dict[str, float] | None = None,
    stats: Counter[str] | None = None,
    stop_flip_depth: int = 0,
) -> Position | None:
    if idx >= len(bars) or equity <= 0.0 or requested_exposure <= 0.0:
        return position
    requested_exposure = _drawdown_adjusted_exposure(
        config=config,
        requested_exposure=requested_exposure,
        equity=equity,
        peak_state=peak_state,
        stats=stats,
    )
    current_gross = _gross_exposure(position, equity)
    add_exposure = min(requested_exposure, max(config.max_gross_exposure - current_gross, 0.0))
    if add_exposure <= 1e-9:
        return position
    price = bars[idx].o
    notional = equity * add_exposure
    leg = Leg(
        leg_id=f"{reason}:{idx}:{len(ledger)}",
        side=side,
        entry_idx=idx,
        entry_ts=bars[idx].ts,
        entry_price=price,
        notional=notional,
        action=reason,
        source_kind=source_kind,
        snippet=snippet,
    )
    max_hold_hours = _leg_max_hold_hours(config, reason)
    max_hold_bars = max(int(max_hold_hours * 60 / interval_minutes), 1)
    if position is None:
        position = Position(
            side=side,
            legs=[leg],
            opened_idx=idx,
            deadline_idx=min(idx + max_hold_bars, len(bars) - 1),
            best_price=price,
            stop_flip_depth=stop_flip_depth,
        )
    else:
        position.legs.append(leg)
        position.deadline_idx = min(max(position.deadline_idx, idx + max_hold_bars), len(bars) - 1)
        position.partial_taken = False
        position.secondary_taken = False
    ledger.append(
        {
            "ts": bars[idx].ts.isoformat(),
            "kind": "open" if len(position.legs) == 1 else "add",
            "side": _side_label(side),
            "price": round(price, 2),
            "exposure": round(add_exposure, 6),
            "equity": round(equity, 8),
            "reason": reason,
            "stop_flip_depth": stop_flip_depth if reason == "stop_flip" else position.stop_flip_depth,
            "source_kind": source_kind,
            "snippet": snippet,
        }
    )
    return position


def _close_fraction(
    *,
    position: Position,
    bars: list[Bar],
    idx: int,
    price: float,
    fraction: float,
    reason: str,
    round_trip_cost_frac: float,
    equity: float,
    ledger: list[dict[str, Any]],
) -> tuple[float, Position | None]:
    fraction = min(max(fraction, 0.0), 1.0)
    if fraction <= 0.0:
        return equity, position
    realized = 0.0
    closed_notional = 0.0
    closed_legs: list[Leg] = []
    remaining: list[Leg] = []
    for leg in position.legs:
        close_notional = leg.notional * fraction
        if close_notional <= 1e-12:
            remaining.append(leg)
            continue
        closed_notional += close_notional
        realized += close_notional * (leg.side * (price / leg.entry_price - 1.0) - round_trip_cost_frac)
        leg.notional -= close_notional
        closed_legs.append(leg)
        if leg.notional > 1e-9:
            remaining.append(leg)
    before = equity
    equity = max(equity + realized, 1e-12)
    gross_return_pct = realized / max(closed_notional, 1e-12) * 100.0
    ledger.append(
        {
            "ts": bars[idx].ts.isoformat(),
            "kind": "close" if fraction >= 0.999 else "reduce",
            "side": _side_label(position.side),
            "price": round(price, 2),
            "closed_notional": round(closed_notional, 8),
            "realized_pnl": round(realized, 8),
            "notional_return_pct": round(gross_return_pct, 6),
            "equity_before": round(before, 8),
            "equity_return_pct": round((equity / before - 1.0) * 100.0, 6) if before > 0 else 0.0,
            "equity": round(equity, 8),
            "reason": reason,
            "source_kind": ",".join(sorted(set(leg.source_kind for leg in closed_legs))),
            "snippet": closed_legs[-1].snippet if closed_legs else "",
        }
    )
    position.legs = remaining
    if not position.legs:
        return equity, None
    return equity, position


def _protective_stop(position: Position, config: StateConfig) -> float:
    avg = _weighted_avg_entry(position)
    if position.side > 0:
        pct_stop = avg * (1.0 - config.stop_pct / 100.0)
        if position.active_stop is None:
            return pct_stop
        return max(pct_stop, position.active_stop)
    pct_stop = avg * (1.0 + config.stop_pct / 100.0)
    if position.active_stop is None:
        return pct_stop
    return min(pct_stop, position.active_stop)


def _post_partial_stop(position: Position, config: StateConfig, avg_entry: float) -> float:
    lock_pct = min(max(config.post_partial_stop_pct, 0.0), max(config.partial_tp_pct, 0.0))
    return avg_entry * (1.0 + position.side * lock_pct / 100.0)


def _partial_reduce_fraction(config: StateConfig, position: Position) -> float:
    actions = {leg.action for leg in position.legs}
    if position.stop_flip_depth > 0 or "stop_flip" in actions:
        return config.stop_flip_reduce_fraction
    if any(action.startswith("flip_") or action == "message_switch_entry" for action in actions):
        return config.flip_reduce_fraction
    if any(action.startswith("signal_") or action.startswith("add_") for action in actions):
        return config.signal_reduce_fraction
    return config.reduce_fraction


def _leg_max_hold_hours(config: StateConfig, reason: str) -> int:
    if reason == "stop_flip":
        return config.stop_flip_max_hold_hours
    if reason.startswith("flip_") or reason == "message_switch_entry":
        return config.flip_max_hold_hours
    if reason.startswith("signal_") or reason.startswith("add_"):
        return config.signal_max_hold_hours
    return config.max_hold_hours


def _set_message_stop(position: Position, event: ManagementEvent, bar_price: float) -> None:
    if not event.levels:
        return
    if position.side > 0:
        candidates = [level for level in event.levels if level < bar_price]
        if candidates:
            new_stop = max(candidates)
            position.active_stop = max(position.active_stop or new_stop, new_stop)
    else:
        candidates = [level for level in event.levels if level > bar_price]
        if candidates:
            new_stop = min(candidates)
            position.active_stop = min(position.active_stop or new_stop, new_stop)


def _opposite_reaction_bar(bar: Bar, side: int, threshold: float) -> bool:
    close_pos = _close_position(bar)
    if side > 0:
        return bar.c < bar.o and close_pos <= 1.0 - threshold
    return bar.c > bar.o and close_pos >= threshold


def _guarded_stop_flip_entry_idx(
    *,
    bars: list[Bar],
    stop_idx: int,
    limit_idx: int,
    old_side: int,
    stop_price: float,
    config: StateConfig,
    interval_minutes: int,
) -> int | None:
    new_side = -old_side
    min_wait_bars = max(int(math.ceil(config.stop_flip_min_wait_minutes / max(interval_minutes, 1))), 1)
    confirm_bars = max(int(math.ceil(config.stop_flip_confirm_minutes / max(interval_minutes, 1))), min_wait_bars)
    start_idx = stop_idx + min_wait_bars
    end_idx = min(stop_idx + confirm_bars, limit_idx, len(bars) - 2)
    if start_idx > end_idx or stop_price <= 0.0:
        return None

    retest_buffer = max(config.stop_flip_retest_buffer_pct, 0.0) / 100.0
    retested = False
    for confirm_idx in range(start_idx, end_idx + 1):
        bar = bars[confirm_idx]
        prev = bars[max(confirm_idx - 1, 0)]
        close_pos = _close_position(bar)
        if new_side > 0:
            retested = retested or bar.l <= stop_price * (1.0 + retest_buffer)
            reclaimed = bar.c >= stop_price
            strong_close = close_pos >= config.close_position_threshold
            directional = bar.c > bar.o or bar.c > prev.c
            chase_pct = max((bar.c / stop_price - 1.0) * 100.0, 0.0)
            if retested and reclaimed and strong_close and directional and chase_pct <= config.max_chase_pct:
                return confirm_idx + 1
        else:
            retested = retested or bar.h >= stop_price * (1.0 - retest_buffer)
            rejected = bar.c <= stop_price
            strong_close = close_pos <= 1.0 - config.close_position_threshold
            directional = bar.c < bar.o or bar.c < prev.c
            chase_pct = max((stop_price / bar.c - 1.0) * 100.0, 0.0) if bar.c > 0 else math.inf
            if retested and rejected and strong_close and directional and chase_pct <= config.max_chase_pct:
                return confirm_idx + 1
    return None


def _stop_flip_entry_idx(
    *,
    bars: list[Bar],
    stop_idx: int,
    limit_idx: int,
    old_side: int,
    stop_price: float,
    old_depth: int,
    config: StateConfig,
    interval_minutes: int,
) -> int | None:
    if config.stop_flip_mode == "off" or old_depth >= config.max_stop_flip_depth:
        return None
    if config.stop_flip_mode == "immediate":
        entry_idx = stop_idx + 1
        if entry_idx <= min(limit_idx, len(bars) - 1) and _opposite_reaction_bar(bars[stop_idx], old_side, config.close_position_threshold):
            return entry_idx
        return None
    if config.stop_flip_mode == "guarded":
        return _guarded_stop_flip_entry_idx(
            bars=bars,
            stop_idx=stop_idx,
            limit_idx=limit_idx,
            old_side=old_side,
            stop_price=stop_price,
            config=config,
            interval_minutes=interval_minutes,
        )
    return None


def _scan_exits(
    *,
    config: StateConfig,
    bars: list[Bar],
    start_idx: int,
    limit_idx: int,
    position: Position | None,
    equity: float,
    round_trip_cost_frac: float,
    interval_minutes: int,
    atr: list[float],
    trend_spread_atr: list[float],
    cooldown_until_by_side: dict[int, int],
    ledger: list[dict[str, Any]],
    stats: Counter[str],
    peak_state: dict[str, float],
) -> tuple[int, float, Position | None, bool]:
    liquidated = False
    if position is None:
        return limit_idx + 1, equity, None, liquidated
    idx = max(start_idx, position.opened_idx)
    while idx <= min(limit_idx, len(bars) - 1) and position is not None:
        bar = bars[idx]
        adverse_price = bar.l if position.side > 0 else bar.h
        mtm_equity = _position_mtm_equity(position, equity, adverse_price)
        peak_state["peak"] = max(peak_state["peak"], _position_mtm_equity(position, equity, bar.c))
        if peak_state["peak"] > 0.0:
            peak_state["max_dd"] = max(peak_state["max_dd"], 1.0 - mtm_equity / peak_state["peak"])
        if mtm_equity <= 0.0:
            equity, position = _close_fraction(
                position=position,
                bars=bars,
                idx=idx,
                price=adverse_price,
                fraction=1.0,
                reason="liquidation",
                round_trip_cost_frac=round_trip_cost_frac,
                equity=equity,
                ledger=ledger,
            )
            stats["liquidation"] += 1
            liquidated = True
            break

        avg = _weighted_avg_entry(position)
        stop_price = _protective_stop(position, config)
        full_tp = avg * (1.0 + position.side * config.full_tp_pct / 100.0)
        partial_tp = avg * (1.0 + position.side * config.partial_tp_pct / 100.0)
        secondary_tp = avg * (1.0 + position.side * config.secondary_tp_pct / 100.0)
        trailing_price: float | None = None
        if config.trail_pct > 0.0:
            if position.side > 0 and position.best_price > avg:
                trailing_price = position.best_price * (1.0 - config.trail_pct / 100.0)
            elif position.side < 0 and position.best_price < avg:
                trailing_price = position.best_price * (1.0 + config.trail_pct / 100.0)

        if position.side > 0:
            stop_hit = bar.l <= stop_price
            trail_hit = trailing_price is not None and bar.l <= trailing_price
            full_hit = bar.h >= full_tp
            partial_hit = bar.h >= partial_tp
            secondary_hit = config.secondary_tp_pct > config.partial_tp_pct and bar.h >= secondary_tp
        else:
            stop_hit = bar.h >= stop_price
            trail_hit = trailing_price is not None and bar.h >= trailing_price
            full_hit = bar.l <= full_tp
            partial_hit = bar.l <= partial_tp
            secondary_hit = config.secondary_tp_pct > config.partial_tp_pct and bar.l <= secondary_tp

        if stop_hit:
            old_side = position.side
            old_depth = position.stop_flip_depth
            equity, position = _close_fraction(
                position=position,
                bars=bars,
                idx=idx,
                price=stop_price,
                fraction=1.0,
                reason="stop",
                round_trip_cost_frac=round_trip_cost_frac,
                equity=equity,
                ledger=ledger,
            )
            stats["stop"] += 1
            peak_state["peak"] = max(peak_state["peak"], equity)
            cooldown_bars = int(config.post_stop_cooldown_hours * 60 / interval_minutes)
            if cooldown_bars > 0:
                cooldown_until_by_side[old_side] = max(cooldown_until_by_side.get(old_side, -1), idx + cooldown_bars)
                stats["post_stop_cooldown"] += 1
            stop_flip_idx = _stop_flip_entry_idx(
                bars=bars,
                stop_idx=idx,
                limit_idx=limit_idx,
                old_side=old_side,
                stop_price=stop_price,
                old_depth=old_depth,
                config=config,
                interval_minutes=interval_minutes,
            )
            if stop_flip_idx is not None:
                if _entry_context_allowed(
                    config=config,
                    bars=bars,
                    atr=atr,
                    trend_spread_atr=trend_spread_atr,
                    idx=stop_flip_idx,
                    side=-old_side,
                    stats=stats,
                ):
                    position = _open_leg(
                        config=config,
                        bars=bars,
                        idx=stop_flip_idx,
                        side=-old_side,
                        requested_exposure=config.max_gross_exposure * config.stop_flip_entry_fraction,
                        equity=equity,
                        position=position,
                        reason="stop_flip",
                        source_kind="system",
                        snippet="stop flip after opposite reaction bar",
                        interval_minutes=interval_minutes,
                        ledger=ledger,
                        peak_state=peak_state,
                        stats=stats,
                        stop_flip_depth=old_depth + 1,
                    )
                    stats[f"stop_flip_{config.stop_flip_mode}"] += 1
                    idx = stop_flip_idx
                else:
                    stats[f"stop_flip_{config.stop_flip_mode}_context_blocked"] += 1
            elif config.stop_flip_mode != "off":
                stats[f"stop_flip_{config.stop_flip_mode}_miss"] += 1
            continue

        if trail_hit:
            price = float(trailing_price)
            equity, position = _close_fraction(
                position=position,
                bars=bars,
                idx=idx,
                price=price,
                fraction=1.0,
                reason="trailing_stop",
                round_trip_cost_frac=round_trip_cost_frac,
                equity=equity,
                ledger=ledger,
            )
            stats["trailing_stop"] += 1
            peak_state["peak"] = max(peak_state["peak"], equity)
            continue

        if full_hit:
            equity, position = _close_fraction(
                position=position,
                bars=bars,
                idx=idx,
                price=full_tp,
                fraction=1.0,
                reason="full_target",
                round_trip_cost_frac=round_trip_cost_frac,
                equity=equity,
                ledger=ledger,
            )
            stats["full_target"] += 1
            peak_state["peak"] = max(peak_state["peak"], equity)
            continue

        if (
            secondary_hit
            and position is not None
            and position.partial_taken
            and not position.secondary_taken
            and config.secondary_reduce_fraction > 0.0
        ):
            equity, position = _close_fraction(
                position=position,
                bars=bars,
                idx=idx,
                price=secondary_tp,
                fraction=config.secondary_reduce_fraction,
                reason="secondary_target",
                round_trip_cost_frac=round_trip_cost_frac,
                equity=equity,
                ledger=ledger,
            )
            stats["secondary_target"] += 1
            if position is not None:
                position.secondary_taken = True

        partial_reduce_fraction = _partial_reduce_fraction(config, position) if position is not None else 0.0
        if position is not None and partial_hit and not position.partial_taken and partial_reduce_fraction > 0.0:
            equity, position = _close_fraction(
                position=position,
                bars=bars,
                idx=idx,
                price=partial_tp,
                fraction=partial_reduce_fraction,
                reason="partial_target",
                round_trip_cost_frac=round_trip_cost_frac,
                equity=equity,
                ledger=ledger,
            )
            stats["partial_target"] += 1
            if position is not None:
                position.partial_taken = True
                partial_stop = _post_partial_stop(position, config, avg)
                position.active_stop = (
                    max(position.active_stop or partial_stop, partial_stop)
                    if position.side > 0
                    else min(position.active_stop or partial_stop, partial_stop)
                )

        if position is not None:
            if position.side > 0:
                position.best_price = max(position.best_price, bar.h)
            else:
                position.best_price = min(position.best_price, bar.l)
            if idx >= position.deadline_idx:
                equity, position = _close_fraction(
                    position=position,
                    bars=bars,
                    idx=idx,
                    price=bar.c,
                    fraction=1.0,
                    reason="time_exit",
                    round_trip_cost_frac=round_trip_cost_frac,
                    equity=equity,
                    ledger=ledger,
                )
                stats["time_exit"] += 1
                peak_state["peak"] = max(peak_state["peak"], equity)
        idx += 1
    return idx, equity, position, liquidated


def _signal_blocked(
    *,
    config: StateConfig,
    signal: Signal,
    idx: int,
    active_bias_side: int,
    bias_until_idx: int,
    cooldown_until_by_side: dict[int, int],
) -> bool:
    if config.use_bias_filter and active_bias_side != 0 and idx <= bias_until_idx and signal.side != active_bias_side:
        return True
    if idx <= cooldown_until_by_side.get(0, -1):
        return True
    if idx <= cooldown_until_by_side.get(signal.side, -1):
        return True
    return False


def simulate_config(
    *,
    labels: list[dict[str, Any]],
    management_events: list[ManagementEvent],
    bars: list[Bar],
    open_times: list[int],
    atr: list[float],
    config: StateConfig,
    round_trip_cost_frac: float,
    interval_minutes: int,
    feature_cache: dict[tuple[str, int, int], list[float]],
    capture_ledger: bool = False,
) -> dict[str, Any]:
    signals = build_signals(labels=labels, bars=bars, open_times=open_times, atr=atr, config=config)
    signals_by_idx: dict[int, list[Signal]] = defaultdict(list)
    for signal in signals:
        signals_by_idx[signal.idx].append(signal)
    management_by_idx: dict[int, list[ManagementEvent]] = defaultdict(list)
    for event in management_events:
        management_by_idx[event.idx].append(event)
    timeline = sorted(set(signals_by_idx) | set(management_by_idx))

    equity = 1.0
    position: Position | None = None
    ledger: list[dict[str, Any]] = []
    stats: Counter[str] = Counter()
    peak_state = {"peak": 1.0, "max_dd": 0.0}
    active_bias_side = 0
    bias_until_idx = -1
    cooldown_until_by_side: dict[int, int] = {}
    cursor_idx = timeline[0] if timeline else 0
    liquidated = False
    trend_spread = _trend_spread_atr(
        bars=bars,
        atr=atr,
        interval_minutes=interval_minutes,
        fast_minutes=config.trend_fast_minutes,
        slow_minutes=config.trend_slow_minutes,
        feature_cache=feature_cache,
    )

    def close_all(idx: int, price: float, reason: str) -> None:
        nonlocal equity, position
        if position is None:
            return
        equity, position = _close_fraction(
            position=position,
            bars=bars,
            idx=idx,
            price=price,
            fraction=1.0,
            reason=reason,
            round_trip_cost_frac=round_trip_cost_frac,
            equity=equity,
            ledger=ledger,
        )
        stats[reason] += 1
        peak_state["peak"] = max(peak_state["peak"], equity)

    def reduce_position(idx: int, price: float, fraction: float, reason: str) -> None:
        nonlocal equity, position
        if position is None:
            return
        equity, position = _close_fraction(
            position=position,
            bars=bars,
            idx=idx,
            price=price,
            fraction=fraction,
            reason=reason,
            round_trip_cost_frac=round_trip_cost_frac,
            equity=equity,
            ledger=ledger,
        )
        stats[reason] += 1
        peak_state["peak"] = max(peak_state["peak"], equity)

    def open_signal(signal: Signal) -> None:
        nonlocal position
        if _signal_blocked(
            config=config,
            signal=signal,
            idx=signal.idx,
            active_bias_side=active_bias_side,
            bias_until_idx=bias_until_idx,
            cooldown_until_by_side=cooldown_until_by_side,
        ):
            stats["blocked_signal"] += 1
            return
        if not _entry_context_allowed(
            config=config,
            bars=bars,
            atr=atr,
            trend_spread_atr=trend_spread,
            idx=signal.idx,
            side=signal.side,
            stats=stats,
        ):
            return
        requested = _entry_exposure(config, signal, position if position and position.side == signal.side else None)
        if position is None:
            position = _open_leg(
                config=config,
                bars=bars,
                idx=signal.idx,
                side=signal.side,
                requested_exposure=requested,
                equity=equity,
                position=position,
                reason=f"signal_{signal.action}",
                source_kind=signal.source_kind,
                snippet=signal.snippet,
                interval_minutes=interval_minutes,
                ledger=ledger,
                peak_state=peak_state,
                stats=stats,
            )
            stats["entry"] += 1
        elif position.side == signal.side:
            position = _open_leg(
                config=config,
                bars=bars,
                idx=signal.idx,
                side=signal.side,
                requested_exposure=requested,
                equity=equity,
                position=position,
                reason=f"add_{signal.action}",
                source_kind=signal.source_kind,
                snippet=signal.snippet,
                interval_minutes=interval_minutes,
                ledger=ledger,
                peak_state=peak_state,
                stats=stats,
            )
            stats["add"] += 1
        elif config.flip_on_opposite_signal:
            close_all(signal.idx, bars[signal.idx].o, "opposite_signal_flip")
            position = _open_leg(
                config=config,
                bars=bars,
                idx=signal.idx,
                side=signal.side,
                requested_exposure=config.max_gross_exposure * config.flip_entry_fraction,
                equity=equity,
                position=position,
                reason=f"flip_{signal.action}",
                source_kind=signal.source_kind,
                snippet=signal.snippet,
                interval_minutes=interval_minutes,
                ledger=ledger,
                peak_state=peak_state,
                stats=stats,
            )
            stats["opposite_flip"] += 1
        else:
            stats["opposite_skipped"] += 1

    for next_idx in timeline:
        if position is not None and cursor_idx <= next_idx - 1:
            cursor_idx, equity, position, liquidated = _scan_exits(
                config=config,
                bars=bars,
                start_idx=cursor_idx,
                limit_idx=next_idx - 1,
                position=position,
                equity=equity,
                round_trip_cost_frac=round_trip_cost_frac,
                interval_minutes=interval_minutes,
                atr=atr,
                trend_spread_atr=trend_spread,
                cooldown_until_by_side=cooldown_until_by_side,
                ledger=ledger,
                stats=stats,
                peak_state=peak_state,
            )
            if liquidated:
                break
        if next_idx >= len(bars):
            continue
        for event in management_by_idx.get(next_idx, []):
            price = bars[next_idx].o
            if event.action == "bias" and event.side != 0:
                active_bias_side = event.side
                bias_until_idx = next_idx + int(24 * 60 / interval_minutes)
                stats["bias_update"] += 1
            elif event.action in {"wait", "risk"}:
                cooldown_bars = int(config.risk_cooldown_hours * 60 / interval_minutes)
                if cooldown_bars > 0:
                    cooldown_until_by_side[event.side] = max(cooldown_until_by_side.get(event.side, -1), next_idx + cooldown_bars)
                    stats["cooldown"] += 1
                if position is not None and _same_or_neutral(event.side, position.side):
                    fraction = config.message_risk_reduce_fraction if event.action == "risk" else config.message_wait_reduce_fraction
                    reduce_position(next_idx, price, fraction, f"message_{event.action}_reduce")
            elif event.action in {"take_profit_done", "reduce_done"}:
                if position is not None and _same_or_neutral(event.side, position.side):
                    reduce_position(next_idx, price, config.reduce_fraction, f"message_{event.action}")
            elif event.action == "stop_plan":
                if position is not None and _same_or_neutral(event.side, position.side):
                    _set_message_stop(position, event, price)
                    stats["message_stop_set"] += 1
            elif event.action == "switch":
                if event.side != 0 and position is not None and position.side != event.side:
                    close_all(next_idx, price, "message_switch")
                    if _entry_context_allowed(
                        config=config,
                        bars=bars,
                        atr=atr,
                        trend_spread_atr=trend_spread,
                        idx=next_idx,
                        side=event.side,
                        stats=stats,
                    ):
                        position = _open_leg(
                            config=config,
                            bars=bars,
                            idx=next_idx,
                            side=event.side,
                            requested_exposure=config.max_gross_exposure * config.flip_entry_fraction,
                            equity=equity,
                            position=position,
                            reason="message_switch_entry",
                            source_kind=event.source_kind,
                            snippet=event.snippet,
                            interval_minutes=interval_minutes,
                            ledger=ledger,
                            peak_state=peak_state,
                            stats=stats,
                        )
                        stats["message_switch"] += 1
                    else:
                        stats["message_switch_context_blocked"] += 1
        for signal in signals_by_idx.get(next_idx, []):
            open_signal(signal)
        cursor_idx = next_idx
        peak_state["peak"] = max(peak_state["peak"], equity)

    if not liquidated and position is not None:
        _, equity, position, liquidated = _scan_exits(
            config=config,
            bars=bars,
            start_idx=cursor_idx,
            limit_idx=min(position.deadline_idx, len(bars) - 1),
            position=position,
            equity=equity,
            round_trip_cost_frac=round_trip_cost_frac,
            interval_minutes=interval_minutes,
            atr=atr,
            trend_spread_atr=trend_spread,
            cooldown_until_by_side=cooldown_until_by_side,
            ledger=ledger,
            stats=stats,
            peak_state=peak_state,
        )

    close_returns = [item.get("equity_return_pct", 0.0) for item in ledger if item.get("kind") in {"close", "reduce"}]
    opened = [item for item in ledger if item.get("kind") in {"open", "add"}]
    closed = [item for item in ledger if item.get("kind") in {"close", "reduce"}]
    monthly: dict[str, dict[str, float]] = {}
    for item in closed:
        ts = datetime.fromisoformat(str(item["ts"]))
        key = ts.strftime("%Y-%m")
        if key not in monthly:
            monthly[key] = {"start": float(item.get("equity_before") or item.get("equity") or equity), "end": float(item.get("equity") or equity)}
        monthly[key]["end"] = float(item.get("equity") or monthly[key]["end"])
    doubled = sum(1 for value in monthly.values() if value["start"] > 0.0 and value["end"] / value["start"] - 1.0 >= 1.0)
    signal_months = Counter(bars[signal.idx].ts.strftime("%Y-%m") for signal in signals if 0 <= signal.idx < len(bars))
    open_months = Counter(datetime.fromisoformat(str(item["ts"])).strftime("%Y-%m") for item in opened)
    close_months = Counter(datetime.fromisoformat(str(item["ts"])).strftime("%Y-%m") for item in closed)
    ledger_times = [datetime.fromisoformat(str(item["ts"])) for item in ledger if item.get("ts")]
    first_action_ts = min(ledger_times).isoformat() if ledger_times else None
    last_action_ts = max(ledger_times).isoformat() if ledger_times else None
    active_action_days = 0.0
    if ledger_times:
        active_action_days = (max(ledger_times) - min(ledger_times)).total_seconds() / 86400.0
    result = {
        "model_id": config.model_id,
        "entry_source_kinds": config.entry_source_kinds,
        "infer_neutral_entry_side": config.infer_neutral_entry_side,
        "validity_hours": config.validity_hours,
        "reaction_wait_bars": config.reaction_wait_bars,
        "close_position_threshold": config.close_position_threshold,
        "reclaim_buffer_atr": config.reclaim_buffer_atr,
        "max_chase_pct": config.max_chase_pct,
        "max_hold_hours": config.max_hold_hours,
        "signal_max_hold_hours": config.signal_max_hold_hours,
        "flip_max_hold_hours": config.flip_max_hold_hours,
        "stop_flip_max_hold_hours": config.stop_flip_max_hold_hours,
        "partial_tp_pct": config.partial_tp_pct,
        "full_tp_pct": config.full_tp_pct,
        "secondary_tp_pct": config.secondary_tp_pct,
        "stop_pct": config.stop_pct,
        "trail_pct": config.trail_pct,
        "post_partial_stop_pct": config.post_partial_stop_pct,
        "max_gross_exposure": config.max_gross_exposure,
        "entry_fraction": config.entry_fraction,
        "add_fraction": config.add_fraction,
        "reduce_fraction": config.reduce_fraction,
        "signal_reduce_fraction": config.signal_reduce_fraction,
        "flip_reduce_fraction": config.flip_reduce_fraction,
        "stop_flip_reduce_fraction": config.stop_flip_reduce_fraction,
        "secondary_reduce_fraction": config.secondary_reduce_fraction,
        "entry_plan_multiplier": config.entry_plan_multiplier,
        "victory_zone_multiplier": config.victory_zone_multiplier,
        "add_plan_multiplier": config.add_plan_multiplier,
        "same_side_victory_multiplier": config.same_side_victory_multiplier,
        "flip_entry_fraction": config.flip_entry_fraction,
        "stop_flip_entry_fraction": config.stop_flip_entry_fraction,
        "message_wait_reduce_fraction": config.message_wait_reduce_fraction,
        "message_risk_reduce_fraction": config.message_risk_reduce_fraction,
        "include_done": config.include_done,
        "flip_on_opposite_signal": config.flip_on_opposite_signal,
        "flip_on_stop": config.flip_on_stop,
        "stop_flip_mode": config.stop_flip_mode,
        "stop_flip_min_wait_minutes": config.stop_flip_min_wait_minutes,
        "stop_flip_confirm_minutes": config.stop_flip_confirm_minutes,
        "stop_flip_retest_buffer_pct": config.stop_flip_retest_buffer_pct,
        "max_stop_flip_depth": config.max_stop_flip_depth,
        "trend_filter_mode": config.trend_filter_mode,
        "trend_fast_minutes": config.trend_fast_minutes,
        "trend_slow_minutes": config.trend_slow_minutes,
        "min_trend_atr": config.min_trend_atr,
        "max_trend_atr": config.max_trend_atr,
        "min_atr_pct": config.min_atr_pct,
        "max_atr_pct": config.max_atr_pct,
        "post_stop_cooldown_hours": config.post_stop_cooldown_hours,
        "use_bias_filter": config.use_bias_filter,
        "risk_cooldown_hours": config.risk_cooldown_hours,
        "drawdown_throttle_pct": config.drawdown_throttle_pct,
        "drawdown_throttle_multiplier": config.drawdown_throttle_multiplier,
        "signals": len(signals),
        "open_actions": len(opened),
        "close_actions": len(closed),
        "final_equity": round(equity, 8),
        "total_return_pct": round((equity - 1.0) * 100.0, 6),
        "max_drawdown_pct": round(peak_state["max_dd"] * 100.0, 6),
        "months": len(monthly),
        "months_doubled": doubled,
        "avg_close_equity_return_pct": round(mean(close_returns), 6) if close_returns else 0.0,
        "median_close_equity_return_pct": round(median(close_returns), 6) if close_returns else 0.0,
        "close_win_rate": round(sum(value > 0 for value in close_returns) / len(close_returns), 6) if close_returns else 0.0,
        "liquidated": liquidated,
        "coverage": {
            "first_signal_ts": bars[signals[0].idx].ts.isoformat() if signals and signals[0].idx < len(bars) else None,
            "last_signal_ts": bars[signals[-1].idx].ts.isoformat() if signals and signals[-1].idx < len(bars) else None,
            "first_action_ts": first_action_ts,
            "last_action_ts": last_action_ts,
            "active_action_days": round(active_action_days, 4),
            "signal_months": dict(sorted(signal_months.items())),
            "open_months": dict(sorted(open_months.items())),
            "close_months": dict(sorted(close_months.items())),
        },
        "stats": dict(stats),
        "score": round((equity - 1.0) - 1.25 * peak_state["max_dd"] - (0.5 if liquidated else 0.0), 6),
    }
    if capture_ledger:
        result["sample_ledger"] = ledger[:20] + ledger[-20:] if len(ledger) > 40 else ledger
    return result


def _stop_flip_modes_from_args(args: argparse.Namespace) -> list[str]:
    explicit = _parse_choice_csv(str(args.stop_flip_modes), {"off", "immediate", "guarded"}, [])
    if explicit:
        return list(dict.fromkeys(explicit))
    modes = ["immediate" if value else "off" for value in _parse_bool_csv(args.flip_stop, [False, True])]
    return list(dict.fromkeys(modes))


def build_configs(args: argparse.Namespace) -> list[StateConfig]:
    configs: list[StateConfig] = []
    entry_source_kinds = _source_kind_csv(_source_kinds_from_csv(args.entry_source_kinds, STRICT_SOURCE_KINDS))
    infer_neutral_entry_side = _parse_bool_csv(str(args.infer_neutral_entry_side), [False])[0]
    stop_flip_modes = _stop_flip_modes_from_args(args)
    trend_modes = _parse_choice_csv(str(args.trend_filters), {"off", "aligned"}, ["off"])
    min_atr_values = _parse_float_csv(args.min_atr_pcts, [0.0], allow_zero=True)
    max_atr_values = _parse_float_csv(args.max_atr_pcts, [0.0], allow_zero=True)
    base_product = product(
        (False, True),
        _parse_int_csv(args.validity_hours, [24, 72]),
        _parse_int_csv(args.reaction_wait_bars, [6, 12]),
        _parse_float_csv(args.close_position_thresholds, [0.55, 0.75]),
        _parse_float_csv(args.reclaim_buffer_atrs, [0.0, 0.05], allow_zero=True),
        _parse_float_csv(args.max_chase_pcts, [0.6, 1.0]),
        _parse_int_csv(args.max_hold_hours, [4, 12]),
        _parse_float_csv(args.partial_tp_pcts, [0.3]),
        _parse_float_csv(args.full_tp_pcts, [0.6, 1.0]),
        _parse_float_csv(args.secondary_tp_pcts, [0.0], allow_zero=True),
        _parse_float_csv(args.stop_pcts, [0.5, 0.8]),
        _parse_float_csv(args.trail_pcts, [0.0, 0.6], allow_zero=True),
        _parse_float_csv(args.post_partial_stop_pcts, [0.0], allow_zero=True),
        _parse_float_csv(args.max_gross_exposures, [5.0, 10.0]),
        _parse_float_csv(args.entry_fractions, [0.4, 0.6]),
        _parse_float_csv(args.add_fractions, [0.25]),
        _parse_float_csv(args.reduce_fractions, [0.0, 0.5], allow_zero=True),
        _parse_float_csv(args.secondary_reduce_fractions, [0.5], allow_zero=True),
        _parse_bool_csv(args.flip_opposite, [True]),
    )
    for (
        include_done,
        validity,
        wait,
        close_pos,
        buffer_atr,
        max_chase,
        max_hold,
        partial_tp,
        full_tp,
        secondary_tp,
        stop_pct,
        trail_pct,
        post_partial_stop_pct,
        max_gross,
        entry_fraction,
        add_fraction,
        reduce_fraction,
        secondary_reduce_fraction,
        flip_opposite,
    ) in base_product:
        for stop_flip_mode in stop_flip_modes:
            min_wait_values = [0] if stop_flip_mode in {"off", "immediate"} else _parse_int_csv(args.stop_flip_min_wait_minutes, [15, 30], allow_zero=True)
            confirm_values = [0] if stop_flip_mode in {"off", "immediate"} else _parse_int_csv(args.stop_flip_confirm_minutes, [60, 180])
            retest_values = [0.0] if stop_flip_mode in {"off", "immediate"} else _parse_float_csv(args.stop_flip_retest_buffers, [0.0, 0.15], allow_zero=True)
            depth_values = [0] if stop_flip_mode == "off" else _parse_int_csv(args.max_stop_flip_depths, [1])
            entry_plan_values = _parse_float_csv(args.entry_plan_multipliers, [1.0])
            victory_zone_values = _parse_float_csv(args.victory_zone_multipliers, [1.15])
            add_plan_values = _parse_float_csv(args.add_plan_multipliers, [0.75])
            same_side_victory_values = _parse_float_csv(args.same_side_victory_multipliers, [1.25])
            flip_entry_values = _parse_float_csv(args.flip_entry_fractions, [entry_fraction])
            stop_flip_entry_values = [0.0] if stop_flip_mode == "off" else _parse_float_csv(args.stop_flip_entry_fractions, [entry_fraction])
            message_wait_reduce_values = _parse_float_csv(args.message_wait_reduce_fractions, [reduce_fraction * 0.5], allow_zero=True)
            message_risk_reduce_values = _parse_float_csv(args.message_risk_reduce_fractions, [reduce_fraction * 0.5], allow_zero=True)
            signal_reduce_values = _parse_float_csv(args.signal_reduce_fractions, [reduce_fraction], allow_zero=True)
            flip_reduce_values = _parse_float_csv(args.flip_reduce_fractions, [reduce_fraction], allow_zero=True)
            stop_flip_reduce_values = _parse_float_csv(args.stop_flip_reduce_fractions, [reduce_fraction], allow_zero=True)
            signal_hold_values = _parse_int_csv(args.signal_max_hold_hours, [max_hold])
            flip_hold_values = _parse_int_csv(args.flip_max_hold_hours, [max_hold])
            stop_flip_hold_values = [max_hold] if stop_flip_mode == "off" else _parse_int_csv(args.stop_flip_max_hold_hours, [max_hold])
            for trend_mode in trend_modes:
                if trend_mode == "off":
                    trend_fast_values = [0]
                    trend_slow_values = [0]
                    min_trend_values = [0.0]
                    max_trend_values = [0.0]
                else:
                    trend_fast_values = _parse_int_csv(args.trend_fast_minutes, [120])
                    trend_slow_values = _parse_int_csv(args.trend_slow_minutes, [720])
                    min_trend_values = _parse_float_csv(args.min_trend_atrs, [0.0], allow_zero=True)
                    max_trend_values = _parse_float_csv(args.max_trend_atrs, [0.0], allow_zero=True)
                mode_product = product(
                    min_wait_values,
                    confirm_values,
                    retest_values,
                    depth_values,
                    trend_fast_values,
                    trend_slow_values,
                    min_trend_values,
                    max_trend_values,
                    min_atr_values,
                    max_atr_values,
                    entry_plan_values,
                    victory_zone_values,
                    add_plan_values,
                    same_side_victory_values,
                    flip_entry_values,
                    stop_flip_entry_values,
                    signal_reduce_values,
                    flip_reduce_values,
                    stop_flip_reduce_values,
                    signal_hold_values,
                    flip_hold_values,
                    stop_flip_hold_values,
                    message_wait_reduce_values,
                    message_risk_reduce_values,
                    _parse_int_csv(args.post_stop_cooldown_hours, [0], allow_zero=True),
                    _parse_bool_csv(args.bias_filter, [False, True]),
                    _parse_int_csv(args.risk_cooldown_hours, [0, 6], allow_zero=True),
                    _parse_float_csv(args.drawdown_throttle_pcts, [0.0], allow_zero=True),
                    _parse_float_csv(args.drawdown_throttle_multipliers, [0.5], allow_zero=True),
                )
                for (
                    min_wait,
                    confirm_minutes,
                    retest_buffer,
                    max_depth,
                    trend_fast,
                    trend_slow,
                    min_trend,
                    max_trend,
                    min_atr_pct,
                    max_atr_pct,
                    entry_plan_multiplier,
                    victory_zone_multiplier,
                    add_plan_multiplier,
                    same_side_victory_multiplier,
                    flip_entry_fraction,
                    stop_flip_entry_fraction,
                    signal_reduce_fraction,
                    flip_reduce_fraction,
                    stop_flip_reduce_fraction,
                    signal_max_hold_hours,
                    flip_max_hold_hours,
                    stop_flip_max_hold_hours,
                    message_wait_reduce_fraction,
                    message_risk_reduce_fraction,
                    post_stop_cooldown,
                    bias_filter,
                    cooldown,
                    drawdown_throttle_pct,
                    drawdown_throttle_multiplier,
                ) in mode_product:
                    flip_stop = stop_flip_mode != "off"
                    model_id = (
                        f"msg_state:valid{validity}h:wait{wait}:cp{close_pos:g}:"
                        f"src{_source_kind_slug(entry_source_kinds)}:"
                        f"{'inferSide' if infer_neutral_entry_side else 'labelSide'}:"
                        f"buf{buffer_atr:g}:chase{max_chase:g}:hold{max_hold}h:"
                        f"shold{signal_max_hold_hours}h:fhold{flip_max_hold_hours}h:"
                        f"sfhold{stop_flip_max_hold_hours}h:"
                        f"ptp{partial_tp:g}:stp{secondary_tp:g}:ftp{full_tp:g}:sl{stop_pct:g}:"
                        f"trail{trail_pct:g}:ppstop{post_partial_stop_pct:g}:"
                        f"gross{max_gross:g}:entry{entry_fraction:g}:"
                        f"add{add_fraction:g}:red{reduce_fraction:g}:"
                        f"sigred{signal_reduce_fraction:g}:flred{flip_reduce_fraction:g}:"
                        f"sfred{stop_flip_reduce_fraction:g}:sred{secondary_reduce_fraction:g}:"
                        f"epm{entry_plan_multiplier:g}:vzm{victory_zone_multiplier:g}:"
                        f"apm{add_plan_multiplier:g}:svm{same_side_victory_multiplier:g}:"
                        f"flipfrac{flip_entry_fraction:g}:sffrac{stop_flip_entry_fraction:g}:"
                        f"waitred{message_wait_reduce_fraction:g}:riskred{message_risk_reduce_fraction:g}:"
                        f"{'flip' if flip_opposite else 'noflip'}:"
                        f"stop{stop_flip_mode}:sfwait{min_wait}:sfconfirm{confirm_minutes}:"
                        f"sfretest{retest_buffer:g}:sfdepth{max_depth}:"
                        f"trend{trend_mode}:tf{trend_fast}:ts{trend_slow}:"
                        f"mint{min_trend:g}:maxt{max_trend:g}:"
                        f"atr{min_atr_pct:g}-{max_atr_pct:g}:"
                        f"pststop{post_stop_cooldown}:"
                        f"ddthr{drawdown_throttle_pct:g}:ddmul{drawdown_throttle_multiplier:g}:"
                        f"{'bias' if bias_filter else 'nobias'}:cool{cooldown}:"
                        f"{'withDone' if include_done else 'plansOnly'}"
                    )
                    configs.append(
                        StateConfig(
                            model_id=model_id,
                            entry_source_kinds=entry_source_kinds,
                            infer_neutral_entry_side=infer_neutral_entry_side,
                            validity_hours=validity,
                            reaction_wait_bars=wait,
                            close_position_threshold=close_pos,
                            reclaim_buffer_atr=buffer_atr,
                            max_chase_pct=max_chase,
                            max_hold_hours=max_hold,
                            signal_max_hold_hours=signal_max_hold_hours,
                            flip_max_hold_hours=flip_max_hold_hours,
                            stop_flip_max_hold_hours=stop_flip_max_hold_hours,
                            partial_tp_pct=partial_tp,
                            full_tp_pct=full_tp,
                            secondary_tp_pct=secondary_tp,
                            stop_pct=stop_pct,
                            trail_pct=trail_pct,
                            post_partial_stop_pct=post_partial_stop_pct,
                            max_gross_exposure=max_gross,
                            entry_fraction=entry_fraction,
                            add_fraction=add_fraction,
                            reduce_fraction=reduce_fraction,
                            signal_reduce_fraction=signal_reduce_fraction,
                            flip_reduce_fraction=flip_reduce_fraction,
                            stop_flip_reduce_fraction=stop_flip_reduce_fraction,
                            secondary_reduce_fraction=secondary_reduce_fraction,
                            entry_plan_multiplier=entry_plan_multiplier,
                            victory_zone_multiplier=victory_zone_multiplier,
                            add_plan_multiplier=add_plan_multiplier,
                            same_side_victory_multiplier=same_side_victory_multiplier,
                            flip_entry_fraction=flip_entry_fraction,
                            stop_flip_entry_fraction=stop_flip_entry_fraction,
                            message_wait_reduce_fraction=message_wait_reduce_fraction,
                            message_risk_reduce_fraction=message_risk_reduce_fraction,
                            include_done=include_done,
                            flip_on_opposite_signal=flip_opposite,
                            flip_on_stop=flip_stop,
                            stop_flip_mode=stop_flip_mode,
                            stop_flip_min_wait_minutes=min_wait,
                            stop_flip_confirm_minutes=confirm_minutes,
                            stop_flip_retest_buffer_pct=retest_buffer,
                            max_stop_flip_depth=max_depth,
                            trend_filter_mode=trend_mode,
                            trend_fast_minutes=trend_fast,
                            trend_slow_minutes=trend_slow,
                            min_trend_atr=min_trend,
                            max_trend_atr=max_trend,
                            min_atr_pct=min_atr_pct,
                            max_atr_pct=max_atr_pct,
                            post_stop_cooldown_hours=post_stop_cooldown,
                            use_bias_filter=bias_filter,
                            risk_cooldown_hours=cooldown,
                            drawdown_throttle_pct=drawdown_throttle_pct,
                            drawdown_throttle_multiplier=drawdown_throttle_multiplier,
                        )
                    )
    if int(args.max_configs) > 0:
        configs = configs[: int(args.max_configs)]
    return configs


def _write_summary_md(path: Path, report: dict[str, Any]) -> None:
    top = report["top_results"][0] if report["top_results"] else {}
    all_results = report["all_results"]
    positive = sum(1 for item in all_results if item["total_return_pct"] > 0.0)
    doubled = sum(1 for item in all_results if item["months_doubled"] > 0)
    lines = [
        "# 메시지 이벤트 상태 머신 백테스트",
        "",
        f"- 생성 시각: {report['created_at']}",
        f"- 테스트 조합: {report['tested_configs']}개",
        f"- 관리 이벤트 소스: {report.get('management_source_kinds', '')}",
        f"- 반응 진입 + 추가/감축 + 반대 신호 플립 + 메시지 리스크 관리 사용",
        f"- 양수 조합: {positive}개",
        f"- 월 2배 달성 조합: {doubled}개",
        f"- 최고 조합: `{top.get('model_id', '')}`",
        f"- 최고 조합 총수익: {top.get('total_return_pct', '')}%",
        f"- 최고 조합 MDD: {top.get('max_drawdown_pct', '')}%",
        f"- 최고 조합 개시 액션 수: {top.get('open_actions', '')}",
        f"- 최고 조합 종료/감축 액션 수: {top.get('close_actions', '')}",
        f"- 최고 조합 실제 액션 기간: {top.get('coverage', {}).get('first_action_ts')} ~ {top.get('coverage', {}).get('last_action_ts')}",
        f"- 최고 조합 실제 액션 일수: {top.get('coverage', {}).get('active_action_days')}",
        f"- 최고 조합 신호 월별 분포: {top.get('coverage', {}).get('signal_months', {})}",
        "",
        "## 상위 10개",
        "",
        "| 순위 | 모델 | 총수익 | MDD | 개시 | 종료/감축 | 승률 | 월2배 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for idx, result in enumerate(report["top_results"][:10], start=1):
        lines.append(
            f"| {idx} | `{result['model_id']}` | {result['total_return_pct']} | "
            f"{result['max_drawdown_pct']} | {result['open_actions']} | {result['close_actions']} | "
            f"{result['close_win_rate']} | {result['months_doubled']} |"
        )
    score_top = max(all_results, key=lambda item: item["score"]) if all_results else {}
    lines.extend(
        [
            "",
            "## 리스크 보정 상위",
            "",
            f"- 모델: `{score_top.get('model_id', '')}`",
            f"- 총수익: {score_top.get('total_return_pct', '')}%",
            f"- MDD: {score_top.get('max_drawdown_pct', '')}%",
            f"- 점수: {score_top.get('score', '')}",
            "",
            "## 해석",
            "",
            "이 버전은 가격대 반응 확인 후 포지션을 열고, 같은 방향 신호는 추가, 반대 신호는 플립, 익절/감축 메시지는 부분 청산, 위험/관망 메시지는 쿨다운 또는 감축으로 처리한다.",
            "손절 후 반대 방향 캔들 반응이 강하면 선택적으로 반대 포지션을 여는 stop-flip을 테스트하며, EMA 추세/ATR 컨텍스트 필터와 손절 방향 재진입 쿨다운으로 진입 가능한 구간도 제한할 수 있다.",
        ]
    )
    atomic_write_text(path, "\n".join(lines) + "\n")


def _write_ledger_csv(path: Path, model_id: str, ledger: list[dict[str, Any]]) -> None:
    fields = [
        "model_id",
        "ts",
        "kind",
        "side",
        "price",
        "exposure",
        "closed_notional",
        "realized_pnl",
        "notional_return_pct",
        "equity_before",
        "equity_return_pct",
        "equity",
        "reason",
        "source_kind",
        "snippet",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for item in ledger:
            row = {field: item.get(field) for field in fields}
            row["model_id"] = model_id
            writer.writerow(row)


def main() -> None:
    args = _parse_args()
    labels_payload = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    labels = labels_payload["events"]
    settings = get_settings()
    base_url = str(args.base_url or settings.binance_rest_base_url or "https://fapi.binance.com").rstrip("/")
    bars = _load_bars(
        symbol=args.symbol,
        interval=args.interval,
        days=int(args.load_days),
        cache_dir=Path(args.cache_dir),
        base_url=base_url,
        sleep_seconds=float(args.sleep_seconds),
    )
    open_times = [bar.open_ms for bar in bars]
    atr = _atr(bars)
    interval_minutes = _interval_minutes(args.interval)
    round_trip_cost_frac = 2.0 * (max(float(args.fee_bps_per_side), 0.0) + max(float(args.slippage_bps_per_side), 0.0)) / 10_000.0
    management_source_kinds = _source_kinds_from_csv(args.management_source_kinds, STRICT_SOURCE_KINDS)
    management_events = build_management_events(labels, bars, open_times, source_kinds=management_source_kinds)
    configs = build_configs(args)
    configs_by_id = {config.model_id: config for config in configs}
    feature_cache: dict[tuple[str, int, int], list[float]] = {}

    results: list[dict[str, Any]] = []
    for idx, config in enumerate(configs, start=1):
        result = simulate_config(
            labels=labels,
            management_events=management_events,
            bars=bars,
            open_times=open_times,
            atr=atr,
            config=config,
            round_trip_cost_frac=round_trip_cost_frac,
            interval_minutes=interval_minutes,
            feature_cache=feature_cache,
        )
        results.append(result)
        if idx % 200 == 0:
            print(f"tested {idx}/{len(configs)} configs", flush=True)

    results.sort(
        key=lambda item: (
            item["total_return_pct"],
            item["score"],
            -item["max_drawdown_pct"],
            item["open_actions"],
        ),
        reverse=True,
    )
    top_results = [dict(item) for item in results[:30]]
    for item in top_results[:5]:
        detailed = simulate_config(
            labels=labels,
            management_events=management_events,
            bars=bars,
            open_times=open_times,
            atr=atr,
            config=configs_by_id[item["model_id"]],
            round_trip_cost_frac=round_trip_cost_frac,
            interval_minutes=interval_minutes,
            feature_cache=feature_cache,
            capture_ledger=True,
        )
        item["sample_ledger"] = detailed.get("sample_ledger", [])

    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "labels": str(args.labels),
        "market_data": {
            "symbol": args.symbol,
            "interval": args.interval,
            "rows": len(bars),
            "start": bars[0].ts.isoformat() if bars else None,
            "end": bars[-1].ts.isoformat() if bars else None,
        },
        "round_trip_cost_pct": round(round_trip_cost_frac * 100.0, 6),
        "management_source_kinds": _source_kind_csv(management_source_kinds),
        "management_events": len(management_events),
        "tested_configs": len(configs),
        "top_results": top_results,
        "all_results": results,
    }

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "message_state_machine_backtest.json"
    md_path = report_dir / "message_state_machine_backtest_summary.md"
    atomic_write_text(json_path, json.dumps(report, ensure_ascii=False, indent=2))
    _write_summary_md(md_path, report)
    if top_results and top_results[0].get("sample_ledger"):
        _write_ledger_csv(
            report_dir / "message_state_machine_top_sample_ledger.csv",
            top_results[0]["model_id"],
            top_results[0]["sample_ledger"],
        )
    print(json.dumps({"json": str(json_path), "md": str(md_path), "top_results": top_results[:5]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
