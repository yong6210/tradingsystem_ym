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


@dataclass(frozen=True, slots=True)
class ScenarioRepairConfig:
    model_id: str
    exec_interval: str
    htf_fast: int
    htf_slow: int
    htf_band_atr: float
    exec_fast: int
    exec_slow: int
    zone_lookback: int
    base_entry_score: int
    rescue_score: int
    opposite_score: int
    max_possible_units: float
    base_max_units: float
    probe_units: float
    base_add_units: float
    rescue_units: float
    chase_units: float
    max_account_exposure: float
    exchange_leverage: float
    maintenance_margin_pct: float
    reaction_usd: float
    reaction_atr: float
    base_spacing_atr: float
    rescue_trigger_usd: float
    rescue_trigger_atr: float
    max_rescue_bars: int
    max_stuck_bars: int
    min_liquidation_buffer_pct: float
    trend_core_units: float
    trend_hold_strength: float
    invalidation_cut_atr: float
    strict_scenario_entry: bool
    switch_enabled: bool = True


@dataclass(frozen=True, slots=True)
class ScenarioState:
    bias: int
    long_score: int
    short_score: int
    trend_strength: float
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ZoneSignal:
    side: int
    mode: str
    score: int
    long_score: int
    short_score: int
    expected_reaction_usd: float
    reasons: tuple[str, ...]


@dataclass(slots=True)
class Tranche:
    side: int
    qty: float
    entry: float
    entry_idx: int
    role: str
    zone_score: int
    zone_id: str
    zone_context: str = ""


@dataclass(frozen=True, slots=True)
class RemovedLot:
    side: int
    qty: float
    entry: float
    exit_price: float
    role: str
    pnl_usd_units: float
    zone_score: int = 0
    zone_id: str = ""
    zone_context: str = ""


class PositionBook:
    def __init__(self) -> None:
        self.tranches: list[Tranche] = []
        self.cycle_realized_pnl_usd_units = 0.0
        self.cycle_id = 0

    @property
    def side(self) -> int:
        if not self.tranches:
            return 0
        return self.tranches[0].side

    @property
    def qty(self) -> float:
        return sum(lot.qty for lot in self.tranches)

    def qty_by_role(self, role: str) -> float:
        return sum(lot.qty for lot in self.tranches if lot.role == role)

    @property
    def rescue_qty(self) -> float:
        return self.qty_by_role("rescue")

    @property
    def first_entry_idx(self) -> int | None:
        if not self.tranches:
            return None
        return min(lot.entry_idx for lot in self.tranches)

    @property
    def last_entry(self) -> float | None:
        if not self.tranches:
            return None
        return max(self.tranches, key=lambda lot: lot.entry_idx).entry

    @property
    def avg_entry(self) -> float:
        qty = self.qty
        if qty <= 1e-12:
            return 0.0
        return sum(lot.qty * lot.entry for lot in self.tranches) / qty

    def effective_breakeven(self) -> float:
        qty = self.qty
        if qty <= 1e-12:
            return 0.0
        loss_to_repair = max(-self.cycle_realized_pnl_usd_units, 0.0)
        if self.side > 0:
            return self.avg_entry + loss_to_repair / qty
        if self.side < 0:
            return self.avg_entry - loss_to_repair / qty
        return 0.0

    def add(
        self,
        *,
        side: int,
        qty: float,
        price: float,
        entry_idx: int,
        role: str,
        zone_score: int,
        zone_id: str,
        zone_context: str = "",
    ) -> None:
        if qty <= 1e-12:
            return
        if self.tranches and self.side != side:
            raise ValueError("cannot_add_opposite_side_without_flattening")
        if not self.tranches:
            self.cycle_id += 1
            self.cycle_realized_pnl_usd_units = 0.0
        self.tranches.append(
            Tranche(
                side=side,
                qty=float(qty),
                entry=float(price),
                entry_idx=int(entry_idx),
                role=role,
                zone_score=int(zone_score),
                zone_id=str(zone_id),
                zone_context=str(zone_context),
            )
        )

    def remove(
        self,
        *,
        qty: float,
        price: float,
        role_priority: tuple[str, ...],
    ) -> list[RemovedLot]:
        remaining = min(max(float(qty), 0.0), self.qty)
        if self.qty - remaining < 0.10:
            remaining = self.qty
        removed: list[RemovedLot] = []
        if remaining <= 1e-12:
            return removed

        ordered_indices: list[int] = []
        seen: set[int] = set()
        for role in role_priority:
            for idx, lot in sorted(enumerate(self.tranches), key=lambda item: -item[1].entry_idx):
                if idx not in seen and lot.role == role:
                    ordered_indices.append(idx)
                    seen.add(idx)
        for idx, _lot in sorted(enumerate(self.tranches), key=lambda item: -item[1].entry_idx):
            if idx not in seen:
                ordered_indices.append(idx)
                seen.add(idx)

        for idx in ordered_indices:
            if remaining <= 1e-12:
                break
            lot = self.tranches[idx]
            if lot.qty <= 1e-12:
                continue
            take = min(lot.qty, remaining)
            pnl = lot.side * take * (float(price) - lot.entry)
            self.cycle_realized_pnl_usd_units += pnl
            removed.append(
                RemovedLot(
                    side=lot.side,
                    qty=take,
                    entry=lot.entry,
                    exit_price=float(price),
                    role=lot.role,
                    pnl_usd_units=pnl,
                    zone_score=lot.zone_score,
                    zone_id=lot.zone_id,
                    zone_context=lot.zone_context,
                )
            )
            lot.qty -= take
            remaining -= take

        self.tranches = [lot for lot in self.tranches if lot.qty > 1e-12]
        if not self.tranches:
            self.cycle_realized_pnl_usd_units = 0.0
        return removed

    def reset(self) -> None:
        self.tranches = []
        self.cycle_realized_pnl_usd_units = 0.0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Research-only scenario/repair rotation backtest. It models base size, rescue "
            "tranches, reaction-first rescue exits, switching, and 10x liquidation pressure."
        )
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--days", type=int, default=365, help="Backtest window after loading cached history.")
    parser.add_argument("--load-days", type=int, default=1825, help="History window used for cache loading.")
    parser.add_argument("--exec-interval", default="5m")
    parser.add_argument("--scenario-intervals", default="1h,4h")
    parser.add_argument("--exchange-leverage", type=float, default=10.0)
    parser.add_argument("--max-account-exposures", default="3,5,10")
    parser.add_argument("--rescue-units", default="3,5")
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument("--maintenance-margin-pct", type=float, default=0.5)
    parser.add_argument("--min-periods", type=int, default=5000)
    parser.add_argument("--max-models", type=int, default=120)
    parser.add_argument("--cache-dir", default="reports/validation/btc_flip_rotation_search/cache")
    parser.add_argument("--report-dir", default="reports/validation/scenario_repair_rotation_backtest")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _parse_float_csv(raw: str, *, fallback: list[float]) -> list[float]:
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


def _slice_last_days(bars: list[Bar], days: int) -> list[Bar]:
    if not bars:
        return []
    cutoff = bars[-1].ts - timedelta(days=max(int(days), 1))
    return [bar for bar in bars if bar.ts >= cutoff]


def _map_closed_indices(exec_bars: list[Bar], scenario_bars: list[Bar], scenario_interval: str) -> list[int]:
    out: list[int] = []
    if not scenario_bars:
        return [0] * len(exec_bars)
    interval_ms = _INTERVAL_MS[scenario_interval]
    ptr = 0
    closed = 0
    for bar in exec_bars:
        asof_ms = bar.open_ms
        while ptr < len(scenario_bars) and scenario_bars[ptr].open_ms + interval_ms <= asof_ms:
            closed = ptr
            ptr += 1
        out.append(closed)
    return out


def _cloud_bands(features: FeatureSet, idx: int) -> tuple[float, float, float]:
    high9 = features.rolling_high_prev(9)[idx]
    low9 = features.rolling_low_prev(9)[idx]
    high26 = features.rolling_high_prev(26)[idx]
    low26 = features.rolling_low_prev(26)[idx]
    high52 = features.rolling_high_prev(52)[idx]
    low52 = features.rolling_low_prev(52)[idx]
    tenkan = (high9 + low9) / 2.0
    kijun = (high26 + low26) / 2.0
    span_a = (tenkan + kijun) / 2.0
    span_b = (high52 + low52) / 2.0
    low = min(span_a, span_b)
    high = max(span_a, span_b)
    return low, high, (span_a + span_b) / 2.0


def _round_levels(price: float, step: float = 1000.0) -> list[float]:
    base = math.floor(price / step) * step
    levels: list[float] = []
    for offset_base in (base - step, base, base + step):
        for frac in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
            level = offset_base + step * frac
            if level > 0.0:
                levels.append(level)
    return sorted(set(levels))


def _near_2468_support(low: float, close: float, atr: float) -> tuple[bool, float]:
    tolerance = max(0.28 * atr, 35.0)
    best_dist = math.inf
    ok = False
    for level in _round_levels(close):
        dist = abs(low - level)
        if dist < best_dist:
            best_dist = dist
        if low <= level + tolerance and close >= level:
            ok = True
    return ok, best_dist


def _near_2468_resistance(high: float, close: float, atr: float) -> tuple[bool, float]:
    tolerance = max(0.28 * atr, 35.0)
    best_dist = math.inf
    ok = False
    for level in _round_levels(close):
        dist = abs(high - level)
        if dist < best_dist:
            best_dist = dist
        if high >= level - tolerance and close <= level:
            ok = True
    return ok, best_dist


def _scenario_at(
    *,
    scenario_features: dict[str, FeatureSet],
    scenario_maps: dict[str, list[int]],
    exec_idx: int,
    config: ScenarioRepairConfig,
) -> ScenarioState:
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
    return ScenarioState(
        bias=bias,
        long_score=long_score,
        short_score=short_score,
        trend_strength=trend_strength,
        reasons=tuple(reasons[:6]),
    )


def _zone_signal(
    *,
    features: FeatureSet,
    idx: int,
    scenario: ScenarioState,
    config: ScenarioRepairConfig,
) -> ZoneSignal:
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

    if scenario.bias > 0:
        long_score += 2
        long_reasons.append("scenario_long")
    elif scenario.bias < 0:
        short_score += 2
        short_reasons.append("scenario_short")

    if low <= prev_low - 0.08 * atr and close > prev_low:
        long_score += 3
        long_reasons.append("range_low_sweep_reclaim")
    elif low <= prev_low + 0.35 * atr and close_position >= 0.58:
        long_score += 2
        long_reasons.append("range_low_reaction")

    if high >= prev_high + 0.08 * atr and close < prev_high:
        short_score += 3
        short_reasons.append("range_high_sweep_reject")
    elif high >= prev_high - 0.35 * atr and close_position <= 0.42:
        short_score += 2
        short_reasons.append("range_high_reaction")

    if low <= cloud_high + 0.20 * atr and close >= cloud_low and scenario.bias >= 0:
        long_score += 1
        long_reasons.append("cloud_support")
    if high >= cloud_low - 0.20 * atr and close <= cloud_high and scenario.bias <= 0:
        short_score += 1
        short_reasons.append("cloud_resistance")

    near_support, support_dist = _near_2468_support(low, close, atr)
    near_resistance, resistance_dist = _near_2468_resistance(high, close, atr)
    if near_support and close_position >= 0.50:
        long_score += 1
        long_reasons.append("2468_support")
    if near_resistance and close_position <= 0.50:
        short_score += 1
        short_reasons.append("2468_resistance")

    if rsi <= 36.0 and body_atr > -0.15:
        long_score += 1
        long_reasons.append("washed_rsi")
    elif rsi >= 64.0 and body_atr < 0.15:
        short_score += 1
        short_reasons.append("heated_rsi")

    mode = "zone"
    if close > prev_high and exec_spread > 0.25 and scenario.bias >= 0:
        long_score += 2
        long_reasons.append("trend_chase_breakout")
        mode = "chase"
    if close < prev_low and exec_spread < -0.25 and scenario.bias <= 0:
        short_score += 2
        short_reasons.append("trend_chase_breakdown")
        mode = "chase"

    side = 0
    score = 0
    reasons: tuple[str, ...] = ()
    if long_score >= short_score + 2 and long_score >= config.base_entry_score:
        side = 1
        score = long_score
        reasons = tuple(long_reasons[:7])
    elif short_score >= long_score + 2 and short_score >= config.base_entry_score:
        side = -1
        score = short_score
        reasons = tuple(short_reasons[:7])
    else:
        if long_score > short_score:
            score = long_score
            reasons = tuple(long_reasons[:7])
        elif short_score > long_score:
            score = short_score
            reasons = tuple(short_reasons[:7])

    expected_reaction_usd = max(config.reaction_usd, config.reaction_atr * atr)
    if min(support_dist, resistance_dist) <= max(0.15 * atr, 20.0):
        expected_reaction_usd *= 1.08
    return ZoneSignal(
        side=side,
        mode=mode,
        score=score,
        long_score=long_score,
        short_score=short_score,
        expected_reaction_usd=expected_reaction_usd,
        reasons=reasons,
    )


def _liquidation_price(config: ScenarioRepairConfig, side: int, avg_entry: float) -> float:
    distance = max(1.0 / max(config.exchange_leverage, 1e-12) - config.maintenance_margin_pct / 100.0, 0.005)
    if side > 0:
        return avg_entry * (1.0 - distance)
    if side < 0:
        return avg_entry * (1.0 + distance)
    return 0.0


def _liquidation_buffer_pct(config: ScenarioRepairConfig, book: PositionBook, price: float) -> float:
    if book.side == 0 or price <= 0.0:
        return math.inf
    liq = _liquidation_price(config, book.side, book.avg_entry)
    if book.side > 0:
        return (price - liq) / price
    return (liq - price) / price


def _book_weight(config: ScenarioRepairConfig, book: PositionBook) -> float:
    if book.side == 0:
        return 0.0
    unit_weight = config.max_account_exposure / max(config.max_possible_units, 1e-12)
    return book.side * book.qty * unit_weight


def _scenario_allows_side(config: ScenarioRepairConfig, scenario: ScenarioState, side: int) -> bool:
    if side == 0:
        return False
    if not config.strict_scenario_entry:
        return True
    return scenario.bias == 0 or scenario.bias == side


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
    stats = {
        "rescue_exits": 0.0,
        "rescue_success": 0.0,
        "rescue_failed": 0.0,
        "removed_qty": 0.0,
    }
    for lot in removed:
        if lot.role == "rescue":
            stats["rescue_exits"] += 1.0
            if lot.pnl_usd_units > 0.0:
                stats["rescue_success"] += 1.0
            else:
                stats["rescue_failed"] += 1.0
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


def _apply_decision(
    *,
    book: PositionBook,
    features: FeatureSet,
    sig_idx: int,
    exec_idx: int,
    exec_price: float,
    config: ScenarioRepairConfig,
    scenario: ScenarioState,
    zone: ZoneSignal,
    events: list[dict[str, Any]],
    equity: float,
    counters: Counter[str],
) -> None:
    ts = features.ts[exec_idx]
    atr = max(features.atr[sig_idx], 1e-12)
    close = features.c[sig_idx]

    if book.side != 0 and book.rescue_qty > 0.0:
        rescue_entries = [lot.entry for lot in book.tranches if lot.role == "rescue"]
        rescue_avg = sum(rescue_entries) / max(len(rescue_entries), 1)
        target_distance = max(config.reaction_usd, config.reaction_atr * atr)
        target = rescue_avg + book.side * target_distance
        reaction_hit = features.h[sig_idx] >= target if book.side > 0 else features.l[sig_idx] <= target
        if reaction_hit:
            removed = book.remove(qty=book.rescue_qty, price=exec_price, role_priority=("rescue",))
            stats = _exit_removed_lots(
                events=events,
                removed=removed,
                ts=ts,
                action="remove",
                reason="rescue_reaction_first",
                equity=equity,
            )
            counters["rescue_reaction_exits"] += int(stats["rescue_exits"])
            counters["rescue_success"] += int(stats["rescue_success"])
            counters["rescue_failed"] += int(stats["rescue_failed"])

    if book.side != 0:
        buffer_pct = _liquidation_buffer_pct(config, book, close)
        if buffer_pct < config.min_liquidation_buffer_pct:
            cut_qty = book.qty if buffer_pct < config.min_liquidation_buffer_pct * 0.55 else book.qty * 0.50
            removed = book.remove(qty=cut_qty, price=exec_price, role_priority=("rescue", "chase", "base", "probe"))
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
            and zone.score >= config.base_entry_score
            and _scenario_allows_side(config, scenario, zone.side)
        ):
            role = "chase" if zone.mode == "chase" else "probe"
            qty = config.chase_units if role == "chase" else config.probe_units
            qty = min(qty, config.max_possible_units)
            book.add(
                side=zone.side,
                qty=qty,
                price=exec_price,
                entry_idx=exec_idx,
                role=role,
                zone_score=zone.score,
                zone_id="|".join(zone.reasons[:3]),
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
                extra={"zone_score": zone.score, "zone_reasons": ",".join(zone.reasons[:4])},
            )
        return

    side = book.side
    avg = book.avg_entry
    eff_be = book.effective_breakeven()
    adverse_usd = max(-side * (close - avg), 0.0)
    favorable_from_be = side * (close - eff_be)
    capacity = max(config.max_possible_units - book.qty, 0.0)
    last_entry = book.last_entry or avg
    adverse_from_last = side * (last_entry - close)
    spacing_ok = adverse_from_last >= config.base_spacing_atr * atr
    same_zone = zone.side == side and zone.score >= config.base_entry_score
    scenario_allows_current = _scenario_allows_side(config, scenario, side)

    if scenario.bias == -side and adverse_usd >= max(config.reaction_usd, config.invalidation_cut_atr * atr):
        cut_qty = book.qty
        removed = book.remove(qty=cut_qty, price=exec_price, role_priority=("rescue", "chase", "base", "probe"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=ts,
            action="remove",
            reason="scenario_invalidation_flatten",
            equity=equity,
        )
        counters["scenario_invalidation_flattens"] += 1
        if config.switch_enabled and zone.side == -side and zone.score >= config.opposite_score:
            qty = min(config.probe_units, config.max_possible_units)
            book.add(
                side=-side,
                qty=qty,
                price=exec_price,
                entry_idx=exec_idx,
                role="probe",
                zone_score=zone.score,
                zone_id="|".join(zone.reasons[:3]),
            )
            counters["switches"] += 1
            _record_event(
                events,
                ts=ts,
                action="add",
                side=-side,
                qty=qty,
                price=exec_price,
                reason="scenario_invalidation_switch_probe",
                equity=equity,
                extra={"zone_score": zone.score},
            )
        return

    rescue_ready = (
        capacity > 1e-12
        and book.rescue_qty <= 1e-12
        and same_zone
        and scenario_allows_current
        and zone.score >= config.rescue_score
        and adverse_usd >= max(config.rescue_trigger_usd, config.rescue_trigger_atr * atr)
    )

    if rescue_ready:
        qty = min(config.rescue_units, capacity)
        book.add(
            side=side,
            qty=qty,
            price=exec_price,
            entry_idx=exec_idx,
            role="rescue",
            zone_score=zone.score,
            zone_id="|".join(zone.reasons[:3]),
        )
        counters["rescue_adds"] += 1
        _record_event(
            events,
            ts=ts,
            action="add",
            side=side,
            qty=qty,
            price=exec_price,
            reason="rescue_add",
            equity=equity,
            extra={
                "avg_entry": round(avg, 2),
                "adverse_usd": round(adverse_usd, 2),
                "zone_score": zone.score,
            },
        )
        return

    if (
        same_zone
        and scenario_allows_current
        and book.qty < config.base_max_units - 1e-12
        and spacing_ok
        and capacity > 1e-12
    ):
        qty = min(config.base_add_units, config.base_max_units - book.qty, capacity)
        if qty > 1e-12:
            book.add(
                side=side,
                qty=qty,
                price=exec_price,
                entry_idx=exec_idx,
                role="base",
                zone_score=zone.score,
                zone_id="|".join(zone.reasons[:3]),
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
                extra={"zone_score": zone.score},
            )
            return

    if book.rescue_qty > 0.0:
        rescue_age = max(exec_idx - lot.entry_idx for lot in book.tranches if lot.role == "rescue")
        if rescue_age >= config.max_rescue_bars and favorable_from_be < 0.0:
            removed = book.remove(qty=book.rescue_qty, price=exec_price, role_priority=("rescue",))
            stats = _exit_removed_lots(
                events=events,
                removed=removed,
                ts=ts,
                action="remove",
                reason="rescue_timeout_no_reaction",
                equity=equity,
            )
            counters["rescue_timeouts"] += 1
            counters["rescue_failed"] += int(stats["rescue_failed"])
            return

    first_idx = book.first_entry_idx
    trend_hold_floor = max(config.probe_units, min(config.trend_core_units, config.base_max_units))
    trend_is_alive = scenario.bias == side and scenario.trend_strength >= config.trend_hold_strength
    stuck_limit = config.max_stuck_bars * (2 if trend_is_alive else 1)
    if first_idx is not None and exec_idx - first_idx >= stuck_limit and favorable_from_be < 0.0:
        cut_qty = _unit_cut_qty(book.qty, 0.35)
        removed = book.remove(qty=cut_qty, price=exec_price, role_priority=("rescue", "chase", "base", "probe"))
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

    opposite_pressure = (
        zone.side == -side
        and zone.score >= config.opposite_score
        and (not config.strict_scenario_entry or scenario.bias == -side)
    )
    scenario_flip = scenario.bias == -side and zone.side == -side and zone.score >= config.base_entry_score
    if opposite_pressure or scenario_flip:
        if config.switch_enabled and (opposite_pressure or adverse_usd >= max(config.reaction_usd, atr)):
            old_qty = book.qty
            removed = book.remove(qty=book.qty, price=exec_price, role_priority=("rescue", "chase", "base", "probe"))
            _exit_removed_lots(
                events=events,
                removed=removed,
                ts=ts,
                action="remove",
                reason="opposite_switch_flatten",
                equity=equity,
            )
            qty = min(config.probe_units, config.max_possible_units)
            book.add(
                side=-side,
                qty=qty,
                price=exec_price,
                entry_idx=exec_idx,
                role="probe",
                zone_score=zone.score,
                zone_id="|".join(zone.reasons[:3]),
            )
            counters["switches"] += 1
            _record_event(
                events,
                ts=ts,
                action="add",
                side=-side,
                qty=qty,
                price=exec_price,
                reason="opposite_switch_probe",
                equity=equity,
                extra={"old_qty": round(old_qty, 4), "zone_score": zone.score},
            )
        else:
            cut_qty = _unit_cut_qty(book.qty, 0.50, minimum=max(config.probe_units, 1.0))
            removed = book.remove(qty=cut_qty, price=exec_price, role_priority=("rescue", "chase", "base", "probe"))
            _exit_removed_lots(
                events=events,
                removed=removed,
                ts=ts,
                action="remove",
                reason="opposite_pressure_trim",
                equity=equity,
            )
            counters["opposite_trims"] += 1
        return

    profit_floor = trend_hold_floor if trend_is_alive else config.probe_units
    if favorable_from_be >= zone.expected_reaction_usd and book.qty > profit_floor:
        trim_qty = min(book.qty - profit_floor, _unit_cut_qty(book.qty, 0.35))
        if book.qty - trim_qty < profit_floor:
            trim_qty = book.qty
        removed = book.remove(qty=trim_qty, price=exec_price, role_priority=("chase", "base", "probe"))
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
    config: ScenarioRepairConfig,
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

    for exec_idx in range(warmup + 1, len(features.bars) - 1):
        sig_idx = exec_idx - 1
        exec_price = features.o[exec_idx]
        next_open = features.o[exec_idx + 1]
        if exec_price <= 0.0 or next_open <= 0.0:
            continue

        bar_start_equity = equity
        old_weight = _book_weight(config, book)
        scenario = _scenario_at(
            scenario_features=scenario_features,
            scenario_maps=scenario_maps,
            exec_idx=exec_idx,
            config=config,
        )
        zone = _zone_signal(features=features, idx=sig_idx, scenario=scenario, config=config)
        _apply_decision(
            book=book,
            features=features,
            sig_idx=sig_idx,
            exec_idx=exec_idx,
            exec_price=exec_price,
            config=config,
            scenario=scenario,
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
                if book.rescue_qty > 0.0:
                    counters["rescue_failed"] += 1
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

        period_return = 0.0
        if not liquidated and new_weight != 0.0:
            raw_price_return = next_open / exec_price - 1.0
            period_return = new_weight * raw_price_return
            equity *= max(1.0 + period_return, 1e-12)

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

        if equity <= 0.02:
            counters["account_ruin_events"] += 1
            break

    if book.side != 0:
        removed = book.remove(qty=book.qty, price=features.c[-1], role_priority=("rescue", "chase", "base", "probe"))
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
    rescue_adds = counters.get("rescue_adds", 0)
    rescue_success = counters.get("rescue_success", 0)
    rescue_failed = counters.get("rescue_failed", 0)
    rescue_resolved = rescue_success + rescue_failed
    rescue_success_rate = rescue_success / rescue_resolved if rescue_resolved else 0.0
    avg_abs_weight = exposure_sum / max(exposure_bars, 1)
    score = (
        cagr
        - 1.35 * max_drawdown
        + 0.25 * sharpe
        + 0.20 * monthly["monthly_double_rate"]
        + 0.15 * rescue_success_rate
        - 2.0 * counters.get("liquidations", 0)
        - 3.0 * counters.get("account_ruin_events", 0)
    )

    trade_like_events = (
        counters.get("probe_adds", 0)
        + counters.get("base_adds", 0)
        + counters.get("rescue_adds", 0)
        + counters.get("chase_adds", 0)
        + counters.get("switches", 0)
    )
    if len(events) <= 24:
        sample_events = events
    else:
        sample_events = events[:12] + [{"omitted_events": len(events) - 24}] + events[-12:]

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
        "rescue_adds": int(rescue_adds),
        "rescue_success_rate": round(rescue_success_rate, 6),
        "monthly": monthly,
        "config": asdict(config),
        "sample_events": sample_events,
    }


def build_configs(
    *,
    exec_interval: str,
    exchange_leverage: float,
    maintenance_margin_pct: float,
    max_account_exposures: list[float],
    rescue_units_options: list[float],
) -> list[ScenarioRepairConfig]:
    configs: list[ScenarioRepairConfig] = []
    profiles = (
        # Baseline zone/repair profile. This keeps the older behavior available so stricter
        # trend guards have to earn their place in the ranking instead of replacing it.
        ("legacy_zone_repair", 1.0, 999.0, 999.0, False),
        ("strict_trend_guard", 2.0, 0.45, 1.15, True),
    )
    for zone_lookback in (48, 96, 144):
        for base_entry_score in (5, 6):
            for rescue_score in (7, 8):
                for base_max_units in (3.0, 5.0):
                    for rescue_units in rescue_units_options:
                        for max_exposure in max_account_exposures:
                            for reaction_usd in (150.0, 300.0):
                                for max_rescue_bars in (3, 6, 12):
                                    for (
                                        profile_name,
                                        trend_core_units,
                                        trend_hold_strength,
                                        invalidation_cut_atr,
                                        strict_scenario_entry,
                                    ) in profiles:
                                        max_possible_units = 10.0
                                        if base_max_units + rescue_units > max_possible_units:
                                            continue
                                        model_id = (
                                            f"{exec_interval}:scenario_repair_v3:{profile_name}:"
                                            f"lb{zone_lookback}:base{base_entry_score}:rescue{rescue_score}:"
                                            f"baseMax{base_max_units:g}:rescueU{rescue_units:g}:"
                                            f"gross{max_exposure:g}:react{reaction_usd:g}:"
                                            f"rBars{max_rescue_bars}:lev{exchange_leverage:g}"
                                        )
                                        configs.append(
                                            ScenarioRepairConfig(
                                                model_id=model_id,
                                                exec_interval=exec_interval,
                                                htf_fast=21,
                                                htf_slow=89,
                                                htf_band_atr=0.12,
                                                exec_fast=13,
                                                exec_slow=55,
                                                zone_lookback=zone_lookback,
                                                base_entry_score=base_entry_score,
                                                rescue_score=rescue_score,
                                                opposite_score=max(base_entry_score + 1, 7),
                                                max_possible_units=max_possible_units,
                                                base_max_units=base_max_units,
                                                probe_units=1.0,
                                                base_add_units=1.0,
                                                rescue_units=rescue_units,
                                                chase_units=2.0,
                                                max_account_exposure=max_exposure,
                                                exchange_leverage=exchange_leverage,
                                                maintenance_margin_pct=maintenance_margin_pct,
                                                reaction_usd=reaction_usd,
                                                reaction_atr=1.15,
                                                base_spacing_atr=0.75,
                                                rescue_trigger_usd=max(180.0, reaction_usd),
                                                rescue_trigger_atr=1.30,
                                                max_rescue_bars=max_rescue_bars,
                                                max_stuck_bars=96,
                                                min_liquidation_buffer_pct=0.018,
                                                trend_core_units=trend_core_units,
                                                trend_hold_strength=trend_hold_strength,
                                                invalidation_cut_atr=invalidation_cut_atr,
                                                strict_scenario_entry=strict_scenario_entry,
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

    max_account_exposures = _parse_float_csv(args.max_account_exposures, fallback=[3.0, 5.0, 10.0])
    rescue_units_options = _parse_float_csv(args.rescue_units, fallback=[3.0, 5.0])
    configs = build_configs(
        exec_interval=args.exec_interval,
        exchange_leverage=float(args.exchange_leverage),
        maintenance_margin_pct=float(args.maintenance_margin_pct),
        max_account_exposures=max_account_exposures,
        rescue_units_options=rescue_units_options,
    )
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
            item["rescue_success_rate"],
        ),
        reverse=True,
    )

    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "strategy_note": (
            "Scenario repair rotation V2 proxy: HTF scenario map, execution-zone score, base units, "
            "separate rescue tranches, reaction-first rescue exits, damage cuts, and optional switching. "
            "Dual-side hedge module is disabled in this run."
        ),
        "risk_note": (
            "Liquidation is approximated with isolated 10x distance and account loss equals used margin fraction. "
            "This is a research proxy, not an execution-ready live model."
        ),
        "args": vars(args),
        "data": data_meta,
        "tested_configs": len(configs),
        "result_count": len(results),
        "top_results": results[:30],
        "all_results": results,
    }

    if args.write_report:
        report_dir = Path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = report_dir / f"scenario_repair_rotation_backtest_{args.symbol}_{args.exec_interval}_{args.days}d_{stamp}.json"
        latest = report_dir / f"scenario_repair_rotation_backtest_{args.symbol}_{args.exec_interval}_{args.days}d_latest.json"
        text = json.dumps(report, ensure_ascii=False, indent=2)
        atomic_write_text(path, text)
        atomic_write_text(latest, text)
        print(f"wrote {path}")
        print(f"wrote {latest}")

    print(json.dumps({"data": data_meta, "tested": len(configs), "top_results": results[:5]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
