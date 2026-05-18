from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any, Literal, Mapping

from app.db.models import Candle
from app.services.micro_main_strategy_research import (
    Direction,
    MicroSignal,
    MicroTrade,
    SessionImpulseRetestExitPolicy,
    SessionImpulseRetestResearch,
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if parsed == parsed else float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


@dataclass(frozen=True, slots=True)
class StructureReactionPolicy:
    name: str = "structure_reaction_balanced"
    lookback_days: int = 28
    max_entry_distance_atr: float = 0.70
    min_anchor_score: float = 0.10
    entry_tolerance_atr: float = 0.12
    min_volume_factor: float = 0.85
    min_body_atr: float = 0.08
    min_wick_fraction: float = 0.30
    long_min_close_position: float = 0.55
    short_max_close_position: float = 0.45
    min_stop_pct: float = 0.003
    min_risk_atr: float = 0.35
    max_stop_pct: float = 0.025
    max_risk_atr: float = 2.20
    stop_buffer_atr: float = 0.12
    target_buffer_atr: float = 0.08
    min_target_count: int = 2
    require_anchor_sweep: bool = False
    sweep_buffer_atr: float = 0.03
    require_anchor_reclaim_close: bool = False
    tp1_min_rr: float = 0.80
    tp2_min_rr: float = 1.60
    tp_max_rr: float = 3.40
    target_rr: float = 2.40
    max_hold_minutes: int = 240
    tp1_fraction: float = 0.35
    stop_after_partial_rr: float | None = 0.0
    adverse_volume_exit_enabled: bool = True
    adverse_volume_exit_after_partial_only: bool = True
    adverse_volume_exit_min_factor: float = 3.0
    adverse_volume_exit_min_body_r: float = 0.35
    adverse_volume_exit_lookback_bars: int = 20
    min_signal_spacing_minutes: int = 30
    trend_filter: Literal["none", "with_ema", "against_ema_only"] = "none"
    allowed_directions: tuple[Direction, ...] = ("long", "short")
    allowed_anchor_timeframes: tuple[str, ...] = ("1d", "4h", "5m", "28d")
    allowed_anchor_kinds: tuple[str, ...] = ("order_block", "fvg", "high_volume_reversal", "volume_node")
    confirmation_minutes: int = 5
    confirmation_mode: Literal["none", "hold", "followthrough"] = "none"
    confirmation_tolerance_atr: float = 0.05
    confirmation_min_progress_atr: float = 0.10

    def exit_policy(self) -> SessionImpulseRetestExitPolicy:
        return SessionImpulseRetestExitPolicy(
            name=self.name,
            stop_mode="floor",
            min_stop_pct=float(self.min_stop_pct),
            min_risk_atr=float(self.min_risk_atr),
            max_stop_pct=float(self.max_stop_pct),
            max_risk_atr=float(self.max_risk_atr),
            target_rr=float(self.target_rr),
            max_hold_minutes=max(int(self.max_hold_minutes), 1),
            time_guard_10m_min_mfe_r=None,
            time_guard_20m_min_mfe_r=None,
            tp1_rr=1.0,
            tp1_fraction=float(self.tp1_fraction),
            tp2_rr=float(self.target_rr),
            tp2_fraction=1.0 - float(self.tp1_fraction),
            adaptive_targets_enabled=False,
            structure_targets_enabled=True,
            structure_entry_max_distance_atr=float(self.max_entry_distance_atr),
            structure_target_buffer_atr=float(self.target_buffer_atr),
            structure_tp1_min_rr=float(self.tp1_min_rr),
            structure_tp2_min_rr=float(self.tp2_min_rr),
            structure_tp_max_rr=float(self.tp_max_rr),
            higher_timeframe_structure_enabled=True,
            higher_timeframe_entry_min_score=float(self.min_anchor_score),
            higher_timeframe_entry_max_distance_atr=float(self.max_entry_distance_atr),
            higher_timeframe_lookback_days=max(int(self.lookback_days), 7),
            higher_timeframe_target_enabled=True,
            higher_timeframe_stop_enabled=False,
            stop_after_partial_rr=self.stop_after_partial_rr,
            adverse_volume_exit_enabled=bool(self.adverse_volume_exit_enabled),
            adverse_volume_exit_after_partial_only=bool(self.adverse_volume_exit_after_partial_only),
            adverse_volume_exit_min_factor=float(self.adverse_volume_exit_min_factor),
            adverse_volume_exit_min_body_r=float(self.adverse_volume_exit_min_body_r),
            adverse_volume_exit_lookback_bars=max(int(self.adverse_volume_exit_lookback_bars), 1),
            entry_confirmation_delay_minutes=0,
        )


class StructureReactionResearch(SessionImpulseRetestResearch):
    family = "htf_structure_reaction"

    def __init__(
        self,
        *,
        symbol: str,
        candles_1m: list[Candle],
        candles_5m: list[Candle],
        policy: StructureReactionPolicy | Mapping[str, Any] | None = None,
    ):
        self.structure_policy = self._normalize_structure_policy(policy)
        super().__init__(
            symbol=symbol,
            candles_1m=candles_1m,
            candles_5m=candles_5m,
            profile_name="baseline",
            exit_policy=self.structure_policy.exit_policy(),
        )

    @staticmethod
    def _normalize_structure_policy(value: StructureReactionPolicy | Mapping[str, Any] | None) -> StructureReactionPolicy:
        if isinstance(value, StructureReactionPolicy):
            return value
        if isinstance(value, Mapping):
            allowed = set(StructureReactionPolicy.__dataclass_fields__)
            payload = {str(key): item for key, item in value.items() if str(key) in allowed}
            return StructureReactionPolicy(**payload)
        return StructureReactionPolicy()

    @staticmethod
    def _bar_range(high: float, low: float) -> float:
        return float(max(float(high) - float(low), 1e-9))

    @classmethod
    def _close_position(cls, *, high: float, low: float, close: float) -> float:
        return float((float(close) - float(low)) / cls._bar_range(high, low))

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _entry_index_after_setup(self, setup_idx: int) -> int | None:
        entry_ts = self.ts_5m[setup_idx] + timedelta(minutes=max(int(self.structure_policy.confirmation_minutes), 5))
        return self._index_1m_by_ts.get(entry_ts)

    def _median_volume_factor_5m(self, idx: int, lookback: int = 96) -> float:
        values = [float(value) for value in self.volumes_5m[max(0, idx - lookback):idx] if float(value) > 0.0]
        if not values:
            return 0.0
        return float(self.volumes_5m[idx] / max(float(median(values)), 1e-9))

    def _direction_allowed_by_trend(self, *, idx: int, direction: Direction) -> bool:
        allowed = {str(item).strip().lower() for item in self.structure_policy.allowed_directions}
        if allowed and str(direction) not in allowed:
            return False
        mode = str(self.structure_policy.trend_filter or "none")
        if mode == "none":
            return True
        trend_long = self.ema_fast_5m[idx] >= self.ema_slow_5m[idx]
        if mode == "with_ema":
            return trend_long if direction == "long" else not trend_long
        if mode == "against_ema_only":
            return not trend_long if direction == "long" else trend_long
        return True

    def _anchor_allowed(self, anchor: Mapping[str, Any]) -> bool:
        timeframe = str(anchor.get("timeframe") or "").strip().lower()
        kind = str(anchor.get("kind") or "").strip().lower()
        allowed_timeframes = {str(item).strip().lower() for item in self.structure_policy.allowed_anchor_timeframes}
        allowed_kinds = {str(item).strip().lower() for item in self.structure_policy.allowed_anchor_kinds}
        return (not allowed_timeframes or timeframe in allowed_timeframes) and (not allowed_kinds or kind in allowed_kinds)

    def _confirmation_passes(
        self,
        *,
        setup_idx: int,
        direction: Direction,
        anchor_low: float,
        anchor_high: float,
        atr: float,
    ) -> bool:
        policy = self.structure_policy
        mode = str(policy.confirmation_mode or "none")
        confirmation_minutes = max(int(policy.confirmation_minutes), 5)
        extra_5m_bars = max(confirmation_minutes // 5 - 1, 0)
        if mode == "none" or extra_5m_bars <= 0:
            return True
        start = setup_idx + 1
        end = setup_idx + 1 + extra_5m_bars
        if end > len(self.candles_5m):
            return False
        tolerance = max(float(policy.confirmation_tolerance_atr), 0.0) * atr
        progress = max(float(policy.confirmation_min_progress_atr), 0.0) * atr
        midpoint = (float(anchor_low) + float(anchor_high)) / 2.0
        last_close = self.closes_5m[end - 1]
        if direction == "long":
            if min(self.lows_5m[start:end]) < float(anchor_low) - tolerance:
                return False
            if mode == "hold":
                return last_close >= midpoint
            if mode == "followthrough":
                return last_close >= max(midpoint, self.closes_5m[setup_idx] + progress)
        else:
            if max(self.highs_5m[start:end]) > float(anchor_high) + tolerance:
                return False
            if mode == "hold":
                return last_close <= midpoint
            if mode == "followthrough":
                return last_close <= min(midpoint, self.closes_5m[setup_idx] - progress)
        return True

    def _reaction_direction_candidates(self, idx: int, atr: float) -> list[Direction]:
        policy = self.structure_policy
        high = self.highs_5m[idx]
        low = self.lows_5m[idx]
        open_price = self.opens_5m[idx]
        close_price = self.closes_5m[idx]
        bar_range = self._bar_range(high, low)
        body_atr = abs(close_price - open_price) / max(float(atr), 1e-9)
        close_pos = self._close_position(high=high, low=low, close=close_price)
        body_low = min(open_price, close_price)
        body_high = max(open_price, close_price)
        lower_wick_fraction = max(body_low - low, 0.0) / bar_range
        upper_wick_fraction = max(high - body_high, 0.0) / bar_range
        volume_factor = self._median_volume_factor_5m(idx)
        if volume_factor < float(policy.min_volume_factor):
            return []

        candidates: list[Direction] = []
        long_rejection = (
            close_price > open_price
            and body_atr >= float(policy.min_body_atr)
            and close_pos >= float(policy.long_min_close_position)
            and lower_wick_fraction >= float(policy.min_wick_fraction)
            and self._direction_allowed_by_trend(idx=idx, direction="long")
        )
        short_rejection = (
            close_price < open_price
            and body_atr >= float(policy.min_body_atr)
            and close_pos <= float(policy.short_max_close_position)
            and upper_wick_fraction >= float(policy.min_wick_fraction)
            and self._direction_allowed_by_trend(idx=idx, direction="short")
        )
        if long_rejection:
            candidates.append("long")
        if short_rejection:
            candidates.append("short")
        return candidates

    def _recent_structure_targets(self, *, idx: int, direction: Direction, entry_price: float) -> tuple[list[float], list[str]]:
        targets: list[float] = []
        sources: list[str] = []
        for lookback in (12, 36, 96, 288):
            start = max(0, idx - lookback)
            if idx <= start:
                continue
            if direction == "long":
                level = max(self.highs_5m[start:idx + 1])
                if float(level) > float(entry_price):
                    targets.append(float(level))
                    sources.append(f"recent_{lookback}_bar_high")
            else:
                level = min(self.lows_5m[start:idx + 1])
                if 0.0 < float(level) < float(entry_price):
                    targets.append(float(level))
                    sources.append(f"recent_{lookback}_bar_low")
        return targets, sources

    @staticmethod
    def _dedupe_targets(
        *,
        direction: Direction,
        entry_price: float,
        prices: list[float],
        sources: list[str],
    ) -> tuple[list[float], list[str]]:
        pairs: list[tuple[float, str]] = []
        seen: set[int] = set()
        for raw_price, raw_source in zip(prices, sources, strict=False):
            price = _safe_float(raw_price, 0.0)
            if direction == "long" and price <= entry_price:
                continue
            if direction == "short" and not (0.0 < price < entry_price):
                continue
            key = int(round(price * 100_000_000))
            if key in seen:
                continue
            seen.add(key)
            pairs.append((price, str(raw_source or "structure_target")))
        pairs.sort(key=lambda item: item[0], reverse=direction == "short")
        return [price for price, _source in pairs], [source for _price, source in pairs]

    def _build_signal(self, idx: int) -> MicroSignal | None:
        policy = self.structure_policy
        if idx < 300 or idx >= len(self.candles_5m) - 2:
            return None
        entry_idx = self._entry_index_after_setup(idx)
        if entry_idx is None or entry_idx >= len(self.candles_1m):
            return None
        atr = max(float(self.atr_5m[max(idx - 1, 0)]), 1e-9)
        directions = self._reaction_direction_candidates(idx, atr)
        if not directions:
            return None

        entry_ts = self.ts_1m[entry_idx]
        entry_price = float(self.opens_1m[entry_idx])
        volume_factor = self._median_volume_factor_5m(idx)
        high = self.highs_5m[idx]
        low = self.lows_5m[idx]
        open_price = self.opens_5m[idx]
        close_price = self.closes_5m[idx]
        bar_range = self._bar_range(high, low)
        body_low = min(open_price, close_price)
        body_high = max(open_price, close_price)
        close_pos = self._close_position(high=high, low=low, close=close_price)
        lower_wick_fraction = max(body_low - low, 0.0) / bar_range
        upper_wick_fraction = max(high - body_high, 0.0) / bar_range

        for direction in directions:
            structure_context = self._higher_timeframe_structure_context(
                setup_idx=idx,
                direction=direction,
                entry_price=entry_price,
                atr=atr,
            )
            anchor = structure_context.get("htf_structure_anchor") if isinstance(structure_context, dict) else None
            if not isinstance(anchor, dict):
                continue
            if not self._anchor_allowed(anchor):
                continue
            anchor_low = _safe_float(anchor.get("low"), 0.0)
            anchor_high = _safe_float(anchor.get("high"), 0.0)
            anchor_score = _safe_float(structure_context.get("htf_structure_anchor_score"), 0.0)
            anchor_distance_atr = _safe_float(structure_context.get("htf_structure_anchor_distance_atr"), 999.0)
            if anchor_low <= 0.0 or anchor_high <= 0.0 or anchor_high < anchor_low:
                continue
            if anchor_score < float(policy.min_anchor_score):
                continue
            if anchor_distance_atr > float(policy.max_entry_distance_atr):
                continue

            tolerance = max(float(policy.entry_tolerance_atr), 0.0) * atr
            if direction == "long":
                touched_anchor = low <= anchor_high + tolerance and close_price >= anchor_low
                if touched_anchor and bool(policy.require_anchor_sweep):
                    swept_anchor = low <= anchor_low - max(float(policy.sweep_buffer_atr), 0.0) * atr
                    reclaimed_anchor = close_price >= (anchor_high if bool(policy.require_anchor_reclaim_close) else (anchor_low + anchor_high) / 2.0)
                    touched_anchor = bool(swept_anchor and reclaimed_anchor)
                stop = min(anchor_low, low) - float(policy.stop_buffer_atr) * atr
                risk_abs = entry_price - stop
            else:
                touched_anchor = high >= anchor_low - tolerance and close_price <= anchor_high
                if touched_anchor and bool(policy.require_anchor_sweep):
                    swept_anchor = high >= anchor_high + max(float(policy.sweep_buffer_atr), 0.0) * atr
                    reclaimed_anchor = close_price <= (anchor_low if bool(policy.require_anchor_reclaim_close) else (anchor_low + anchor_high) / 2.0)
                    touched_anchor = bool(swept_anchor and reclaimed_anchor)
                stop = max(anchor_high, high) + float(policy.stop_buffer_atr) * atr
                risk_abs = stop - entry_price
            if not touched_anchor or risk_abs <= 0.0:
                continue
            if not self._confirmation_passes(
                setup_idx=idx,
                direction=direction,
                anchor_low=anchor_low,
                anchor_high=anchor_high,
                atr=atr,
            ):
                continue
            risk_atr = risk_abs / atr
            risk_pct = risk_abs / max(abs(entry_price), 1e-9)
            if risk_abs < max(float(policy.min_risk_atr) * atr, float(policy.min_stop_pct) * entry_price):
                continue
            if float(policy.max_risk_atr) > 0.0 and risk_atr > float(policy.max_risk_atr):
                continue
            if float(policy.max_stop_pct) > 0.0 and risk_pct > float(policy.max_stop_pct):
                continue

            htf_prices = list(structure_context.get("htf_structure_target_prices") or [])
            htf_sources = [f"htf:{source}" for source in list(structure_context.get("htf_structure_target_sources") or [])]
            recent_prices, recent_sources = self._recent_structure_targets(idx=idx, direction=direction, entry_price=entry_price)
            target_prices, target_sources = self._dedupe_targets(
                direction=direction,
                entry_price=entry_price,
                prices=[*_safe_target_prices(htf_prices), *recent_prices],
                sources=[*htf_sources, *recent_sources],
            )
            if len(target_prices) < max(int(policy.min_target_count), 0):
                continue

            target_price = (
                entry_price + float(policy.target_rr) * risk_abs
                if direction == "long"
                else entry_price - float(policy.target_rr) * risk_abs
            )
            diagnostics = {
                "entry_timing_model": "after_completed_5m_reaction_next_1m_open",
                "setup_ts": self.ts_5m[idx].isoformat(),
                "setup_hour_utc": self.ts_5m[idx].hour,
                "setup_weekday_utc": self.ts_5m[idx].weekday(),
                "signal_5m_close_ts": (self.ts_5m[idx] + timedelta(minutes=5)).isoformat(),
                "entry_actionable_ts": entry_ts.isoformat(),
                "entry_confirmation_delay_minutes": 0,
                "entry_key_level": float(anchor_high if direction == "long" else anchor_low),
                "entry_zone_low": float(anchor_low),
                "entry_zone_high": float(anchor_high),
                "entry_distance_atr": float(anchor_distance_atr),
                "stop_key_level": float(anchor_low if direction == "long" else anchor_high),
                "structure_target_prices": target_prices,
                "structure_target_sources": target_sources,
                "reaction_body_atr": float(abs(close_price - open_price) / atr),
                "reclaim_body_atr": float(abs(close_price - open_price) / atr),
                "reclaim_close_position": float(close_pos),
                "volume_factor": float(volume_factor),
                "lower_wick_fraction": float(lower_wick_fraction),
                "upper_wick_fraction": float(upper_wick_fraction),
                "require_anchor_sweep": bool(policy.require_anchor_sweep),
                "require_anchor_reclaim_close": bool(policy.require_anchor_reclaim_close),
                "confirmation_minutes": int(policy.confirmation_minutes),
                "confirmation_mode": str(policy.confirmation_mode),
                "risk_atr": float(risk_atr),
                "risk_pct": float(risk_pct),
                **structure_context,
            }
            signal = MicroSignal(
                family=self.family,
                direction=direction,
                signal_ts=self.ts_5m[idx] + timedelta(minutes=5),
                setup_ts=self.ts_5m[idx],
                entry_ts=entry_ts,
                entry_price=entry_price,
                stop_price=stop,
                target_price=target_price,
                max_hold_minutes=max(int(policy.max_hold_minutes), 1),
                regime_hint="htf_structure_reaction",
                diagnostics=diagnostics,
            )
            adjusted = self._apply_exit_policy(signal)
            if adjusted is None:
                continue
            if int(policy.min_target_count) > 0 and not adjusted.diagnostics.get("policy_structure_tp2_price"):
                continue
            return adjusted
        return None

    def backtest(self) -> list[MicroTrade]:
        trades: list[MicroTrade] = []
        if len(self.candles_5m) < 300 or len(self.candles_1m) < 1500:
            return trades
        next_allowed_ts = self.ts_5m[300]
        idx = 300
        while idx < len(self.candles_5m) - 2:
            if self.ts_5m[idx] < next_allowed_ts:
                idx += 1
                continue
            signal = self._build_signal(idx)
            if signal is None:
                idx += 1
                continue
            trade = self._simulate_trade(signal)
            next_allowed_ts = signal.entry_ts + timedelta(minutes=max(int(self.structure_policy.min_signal_spacing_minutes), 0))
            if trade is not None:
                trades.append(trade)
            idx += 1
        return trades


def _safe_target_prices(values: list[Any]) -> list[float]:
    out: list[float] = []
    for value in values:
        parsed = _safe_float(value, 0.0)
        if parsed > 0.0:
            out.append(parsed)
    return out


def build_structure_reaction_policies() -> list[StructureReactionPolicy]:
    return [
        StructureReactionPolicy(name="structure_reaction_balanced"),
        StructureReactionPolicy(
            name="structure_reaction_strict",
            max_entry_distance_atr=0.45,
            min_anchor_score=0.20,
            min_volume_factor=1.0,
            min_body_atr=0.10,
            min_wick_fraction=0.35,
            max_risk_atr=1.80,
        ),
        StructureReactionPolicy(
            name="structure_reaction_swing_6h",
            max_hold_minutes=360,
            min_signal_spacing_minutes=60,
            target_rr=2.8,
            tp2_min_rr=1.8,
            tp_max_rr=4.0,
            max_risk_atr=2.60,
        ),
        StructureReactionPolicy(
            name="structure_reaction_with_ema",
            trend_filter="with_ema",
            min_anchor_score=0.15,
            min_volume_factor=0.90,
        ),
        StructureReactionPolicy(
            name="structure_reaction_counter_ema",
            trend_filter="against_ema_only",
            min_anchor_score=0.15,
            min_volume_factor=0.95,
            max_hold_minutes=180,
        ),
        StructureReactionPolicy(
            name="structure_reaction_wide_stop",
            min_stop_pct=0.006,
            min_risk_atr=0.65,
            max_stop_pct=0.035,
            max_risk_atr=3.20,
            stop_buffer_atr=0.24,
            target_rr=2.8,
            tp2_min_rr=1.8,
            tp_max_rr=4.2,
            max_hold_minutes=360,
            min_signal_spacing_minutes=60,
            adverse_volume_exit_enabled=True,
        ),
        StructureReactionPolicy(
            name="structure_reaction_wide_no_breakeven",
            min_stop_pct=0.006,
            min_risk_atr=0.65,
            max_stop_pct=0.035,
            max_risk_atr=3.20,
            stop_buffer_atr=0.24,
            target_rr=2.8,
            tp2_min_rr=1.8,
            tp_max_rr=4.2,
            max_hold_minutes=360,
            stop_after_partial_rr=None,
            min_signal_spacing_minutes=60,
            adverse_volume_exit_enabled=True,
        ),
        StructureReactionPolicy(
            name="structure_reaction_wide_no_adverse_exit",
            min_stop_pct=0.006,
            min_risk_atr=0.65,
            max_stop_pct=0.035,
            max_risk_atr=3.20,
            stop_buffer_atr=0.24,
            target_rr=2.8,
            tp2_min_rr=1.8,
            tp_max_rr=4.2,
            max_hold_minutes=360,
            min_signal_spacing_minutes=60,
            adverse_volume_exit_enabled=False,
        ),
        StructureReactionPolicy(
            name="structure_reaction_sweep_reclaim",
            require_anchor_sweep=True,
            sweep_buffer_atr=0.03,
            require_anchor_reclaim_close=False,
            min_volume_factor=0.90,
            min_wick_fraction=0.35,
            min_anchor_score=0.15,
            min_signal_spacing_minutes=45,
        ),
        StructureReactionPolicy(
            name="structure_reaction_sweep_reclaim_strict",
            require_anchor_sweep=True,
            sweep_buffer_atr=0.03,
            require_anchor_reclaim_close=True,
            min_volume_factor=1.00,
            min_wick_fraction=0.35,
            min_anchor_score=0.20,
            max_entry_distance_atr=0.55,
            min_signal_spacing_minutes=60,
        ),
        StructureReactionPolicy(
            name="structure_reaction_htf_only_15m_hold",
            allowed_anchor_timeframes=("1d", "4h"),
            allowed_anchor_kinds=("order_block", "fvg"),
            confirmation_minutes=15,
            confirmation_mode="hold",
            min_anchor_score=0.20,
            max_entry_distance_atr=0.55,
            min_volume_factor=1.00,
            min_wick_fraction=0.35,
            min_signal_spacing_minutes=120,
            max_hold_minutes=360,
        ),
        StructureReactionPolicy(
            name="structure_reaction_htf_only_15m_follow",
            allowed_anchor_timeframes=("1d", "4h"),
            allowed_anchor_kinds=("order_block", "fvg"),
            confirmation_minutes=15,
            confirmation_mode="followthrough",
            min_anchor_score=0.20,
            max_entry_distance_atr=0.55,
            min_volume_factor=1.00,
            min_wick_fraction=0.35,
            min_signal_spacing_minutes=120,
            max_hold_minutes=360,
        ),
        StructureReactionPolicy(
            name="structure_reaction_htf_sweep_15m_hold",
            allowed_anchor_timeframes=("1d", "4h"),
            allowed_anchor_kinds=("order_block", "fvg"),
            require_anchor_sweep=True,
            sweep_buffer_atr=0.03,
            confirmation_minutes=15,
            confirmation_mode="hold",
            min_anchor_score=0.20,
            max_entry_distance_atr=0.60,
            min_volume_factor=0.95,
            min_wick_fraction=0.35,
            min_signal_spacing_minutes=120,
            max_hold_minutes=360,
        ),
        StructureReactionPolicy(
            name="structure_reaction_order_block_only",
            allowed_anchor_timeframes=("1d", "4h"),
            allowed_anchor_kinds=("order_block",),
            min_anchor_score=0.10,
            max_entry_distance_atr=0.70,
            min_volume_factor=0.85,
            min_signal_spacing_minutes=45,
        ),
        StructureReactionPolicy(
            name="structure_reaction_order_block_strict",
            allowed_anchor_timeframes=("1d", "4h"),
            allowed_anchor_kinds=("order_block",),
            min_anchor_score=0.20,
            max_entry_distance_atr=0.55,
            min_volume_factor=0.95,
            min_wick_fraction=0.35,
            min_signal_spacing_minutes=60,
        ),
        StructureReactionPolicy(
            name="structure_reaction_order_block_short",
            allowed_directions=("short",),
            allowed_anchor_timeframes=("1d", "4h"),
            allowed_anchor_kinds=("order_block",),
            min_anchor_score=0.10,
            max_entry_distance_atr=0.70,
            min_volume_factor=0.85,
            min_signal_spacing_minutes=45,
        ),
        StructureReactionPolicy(
            name="structure_reaction_order_block_counter_short",
            allowed_directions=("short",),
            allowed_anchor_timeframes=("1d", "4h"),
            allowed_anchor_kinds=("order_block",),
            trend_filter="against_ema_only",
            min_anchor_score=0.10,
            max_entry_distance_atr=0.70,
            min_volume_factor=0.85,
            min_signal_spacing_minutes=45,
        ),
        StructureReactionPolicy(
            name="structure_reaction_ob_counter_short_quality",
            allowed_directions=("short",),
            allowed_anchor_timeframes=("1d", "4h"),
            allowed_anchor_kinds=("order_block",),
            trend_filter="against_ema_only",
            min_anchor_score=0.20,
            max_entry_distance_atr=0.55,
            min_volume_factor=1.20,
            min_body_atr=0.12,
            min_wick_fraction=0.40,
            min_signal_spacing_minutes=90,
        ),
        StructureReactionPolicy(
            name="structure_reaction_ob_counter_short_high_quality",
            allowed_directions=("short",),
            allowed_anchor_timeframes=("1d", "4h"),
            allowed_anchor_kinds=("order_block",),
            trend_filter="against_ema_only",
            min_anchor_score=0.30,
            max_entry_distance_atr=0.45,
            min_volume_factor=1.50,
            min_body_atr=0.16,
            min_wick_fraction=0.45,
            min_signal_spacing_minutes=120,
        ),
        StructureReactionPolicy(
            name="structure_reaction_ob_counter_short_wide",
            allowed_directions=("short",),
            allowed_anchor_timeframes=("1d", "4h"),
            allowed_anchor_kinds=("order_block",),
            trend_filter="against_ema_only",
            min_anchor_score=0.15,
            max_entry_distance_atr=0.70,
            min_volume_factor=0.95,
            min_stop_pct=0.006,
            min_risk_atr=0.65,
            max_stop_pct=0.035,
            max_risk_atr=3.20,
            stop_buffer_atr=0.24,
            target_rr=2.80,
            tp2_min_rr=1.80,
            tp_max_rr=4.20,
            max_hold_minutes=360,
            min_signal_spacing_minutes=90,
        ),
        StructureReactionPolicy(
            name="structure_reaction_ob_counter_short_wide_no_be",
            allowed_directions=("short",),
            allowed_anchor_timeframes=("1d", "4h"),
            allowed_anchor_kinds=("order_block",),
            trend_filter="against_ema_only",
            min_anchor_score=0.15,
            max_entry_distance_atr=0.70,
            min_volume_factor=0.95,
            min_stop_pct=0.006,
            min_risk_atr=0.65,
            max_stop_pct=0.035,
            max_risk_atr=3.20,
            stop_buffer_atr=0.24,
            target_rr=2.80,
            tp2_min_rr=1.80,
            tp_max_rr=4.20,
            max_hold_minutes=360,
            stop_after_partial_rr=None,
            min_signal_spacing_minutes=90,
        ),
        StructureReactionPolicy(
            name="structure_reaction_ob_counter_short_no_adverse",
            allowed_directions=("short",),
            allowed_anchor_timeframes=("1d", "4h"),
            allowed_anchor_kinds=("order_block",),
            trend_filter="against_ema_only",
            min_anchor_score=0.10,
            max_entry_distance_atr=0.70,
            min_volume_factor=0.85,
            adverse_volume_exit_enabled=False,
            min_signal_spacing_minutes=45,
        ),
        StructureReactionPolicy(
            name="structure_reaction_ob_counter_short_4h_only",
            allowed_directions=("short",),
            allowed_anchor_timeframes=("4h",),
            allowed_anchor_kinds=("order_block",),
            trend_filter="against_ema_only",
            min_anchor_score=0.15,
            max_entry_distance_atr=0.60,
            min_volume_factor=1.00,
            min_signal_spacing_minutes=90,
        ),
        StructureReactionPolicy(
            name="structure_reaction_ob_counter_short_confirm10",
            allowed_directions=("short",),
            allowed_anchor_timeframes=("1d", "4h"),
            allowed_anchor_kinds=("order_block",),
            trend_filter="against_ema_only",
            min_anchor_score=0.15,
            max_entry_distance_atr=0.60,
            min_volume_factor=1.00,
            confirmation_minutes=10,
            confirmation_mode="hold",
            min_signal_spacing_minutes=90,
        ),
    ]
