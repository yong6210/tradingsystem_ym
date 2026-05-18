from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any, ClassVar, Literal, Mapping

from app.db.models import Candle

Direction = Literal["long", "short"]


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
        return False
    return bool(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if parsed == parsed else float(default)


def _clamp_float(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(float(low), min(float(high), float(value)))


_SESSION_IMPULSE_RETEST_PROFILE_BY_SYMBOL: dict[str, str] = {
    "BTCUSDC": "baseline",
    "BNBUSDC": "baseline",
    "BCHUSDC": "baseline",
    "SUIUSDC": "baseline",
    "LTCUSDC": "baseline",
    "NEARUSDC": "baseline",
    "AAVEUSDC": "baseline",
    "HBARUSDC": "baseline",
    "ETHUSDC": "relaxed_v1",
    "SOLUSDC": "relaxed_v1",
    "LINKUSDC": "relaxed_v1",
    "XRPUSDC": "relaxed_v1",
    "ADAUSDC": "relaxed_v1",
    "AVAXUSDC": "relaxed_v1",
}

_PROFILE_SYMBOL_BLOCKED_SIGNAL_HOURS: dict[str, dict[str, tuple[int, ...]]] = {
    "baseline": {
        "BTCUSDC": (0,),
    },
    "relaxed_v1": {
        "ETHUSDC": (1,),
        "LINKUSDC": (8,),
        "ADAUSDC": (7,),
    },
}


def _profile_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    if normalized.endswith("USDT"):
        return f"{normalized[:-4]}USDC"
    return normalized


@dataclass(frozen=True, slots=True)
class MicroSignal:
    family: str
    direction: Direction
    signal_ts: datetime
    setup_ts: datetime
    entry_ts: datetime
    entry_price: float
    stop_price: float
    target_price: float
    max_hold_minutes: int
    regime_hint: str
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MicroTrade:
    family: str
    symbol: str
    direction: Direction
    signal_ts: datetime
    entry_ts: datetime
    exit_ts: datetime
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    r_value: float
    gross_r: float
    cost_r: float
    hold_minutes: int
    exit_reason: str
    regime_hint: str
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StructureZone:
    kind: str
    side: Literal["support", "resistance"]
    low: float
    high: float
    score: float
    timeframe: str
    source_ts: datetime
    source: str

    @property
    def mid(self) -> float:
        return float((self.low + self.high) / 2.0)


@dataclass(frozen=True, slots=True)
class SessionImpulseRetestExitPolicy:
    name: str = "legacy_full_2r"
    stop_mode: Literal["legacy", "floor", "structure_floor"] = "legacy"
    swing_lookback_bars: int = 0
    stop_buffer_atr: float | None = None
    min_stop_pct: float = 0.0
    min_risk_atr: float = 0.0
    max_stop_pct: float = 0.0
    max_risk_atr: float = 0.0
    target_rr: float = 2.0
    max_hold_minutes: int = 40
    time_guard_10m_min_mfe_r: float | None = 0.20
    time_guard_20m_min_mfe_r: float | None = 0.35
    tp1_rr: float = 0.0
    tp1_fraction: float = 0.0
    tp2_rr: float = 0.0
    tp2_fraction: float = 0.0
    tp3_rr: float = 0.0
    tp3_fraction: float = 0.0
    adaptive_targets_enabled: bool = False
    adaptive_strong_target_rr: float = 2.5
    adaptive_normal_target_rr: float = 2.2
    adaptive_defensive_target_rr: float = 2.0
    adaptive_strong_tp1_fraction: float = 0.25
    adaptive_normal_tp1_fraction: float = 0.35
    adaptive_defensive_tp1_fraction: float = 0.45
    adaptive_quality_strong_threshold: float = 0.68
    adaptive_quality_defensive_threshold: float = 0.42
    adaptive_stop_expansion_strong_max: float = 1.4
    adaptive_stop_expansion_defensive_threshold: float = 1.8
    structure_targets_enabled: bool = False
    structure_entry_max_distance_atr: float = 0.45
    structure_target_buffer_atr: float = 0.05
    structure_tp1_min_rr: float = 0.80
    structure_tp2_min_rr: float = 1.60
    structure_tp_max_rr: float = 3.20
    higher_timeframe_structure_enabled: bool = False
    higher_timeframe_entry_min_score: float = 0.0
    higher_timeframe_entry_max_distance_atr: float = 0.80
    higher_timeframe_lookback_days: int = 28
    higher_timeframe_target_enabled: bool = True
    higher_timeframe_stop_enabled: bool = False
    higher_timeframe_stop_buffer_atr: float = 0.08
    stop_after_partial_rr: float | None = None
    adverse_volume_exit_enabled: bool = False
    adverse_volume_exit_after_partial_only: bool = True
    adverse_volume_exit_min_factor: float = 3.0
    adverse_volume_exit_min_body_r: float = 0.35
    adverse_volume_exit_lookback_bars: int = 20
    entry_confirmation_delay_minutes: int = 5

    def tp_levels(self) -> tuple[tuple[str, float, float], ...]:
        return self._normalize_tp_levels(
            (
                ("tp1", float(self.tp1_rr), max(float(self.tp1_fraction), 0.0)),
                ("tp2", float(self.tp2_rr), max(float(self.tp2_fraction), 0.0)),
                ("tp3", float(self.tp3_rr), max(float(self.tp3_fraction), 0.0)),
            )
        )

    def tp_levels_for_diagnostics(self, diagnostics: Mapping[str, Any] | None) -> tuple[tuple[str, float, float], ...]:
        if not diagnostics:
            return ()
        return self._normalize_tp_levels(
            (
                (
                    label,
                    _safe_float(diagnostics.get(f"policy_{label}_rr"), 0.0),
                    _safe_float(diagnostics.get(f"policy_{label}_fraction"), 0.0),
                )
                for label in ("tp1", "tp2", "tp3")
            )
        )

    def tp_levels_for_signal(self, diagnostics: Mapping[str, Any] | None) -> tuple[tuple[str, float, float], ...]:
        return self.tp_levels_for_diagnostics(diagnostics) or self.tp_levels()

    @staticmethod
    def _normalize_tp_levels(
        levels: tuple[tuple[str, float, float], ...] | Any,
    ) -> tuple[tuple[str, float, float], ...]:
        clean = tuple(
            (str(label), float(rr), max(float(fraction), 0.0))
            for label, rr, fraction in levels
            if float(rr) > 0.0 and float(fraction) > 0.0
        )
        total = sum(fraction for _label, _rr, fraction in clean)
        if total <= 1e-9:
            return ()
        return tuple((label, rr, fraction / total) for label, rr, fraction in clean)


class SessionImpulseRetestResearch:
    _FEE_RATE_ROUND_TRIP = 0.0006
    _MAX_HOLD_MINUTES = 40
    _TIME_GUARD_10M_MIN_MFE_R = 0.20
    _TIME_GUARD_20M_MIN_MFE_R = 0.35
    _SESSION_ANCHOR_LOOKBACK_BARS = 180
    _PROFILE_DEFAULTS: ClassVar[dict[str, dict[str, float]]] = {
        "baseline": {
            "min_offset_bars": 5.0,
            "max_offset_bars": 20.0,
            "min_orb_width_atr": 0.70,
            "max_orb_width_atr": 3.20,
            "min_trend_strength": 0.25,
            "breakout_buffer_atr": 0.14,
            "min_breakout_body_atr": 0.45,
            "min_breakout_close_long": 0.60,
            "max_breakout_close_short": 0.40,
            "min_drive_extension_atr": 0.40,
            "reclaim_touch_buffer_atr": 0.08,
            "reclaim_overshoot_atr": 0.30,
            "reclaim_close_buffer_atr": 0.08,
            "min_reclaim_body_atr": 0.25,
            "min_reclaim_close_long": 0.56,
            "max_reclaim_close_short": 0.44,
            "min_volume_factor": 0.95,
            "entry_retest_buffer_atr": 0.04,
            "max_retest_wait_minutes": 3.0,
            "late_retest_high_risk_atr": 1.0,
            "late_retest_high_risk_max_wait_minutes": 2.0,
            "stop_buffer_atr": 0.12,
            "min_risk_atr": 0.25,
            "max_risk_atr": 1.25,
            "min_risk_pct": 0.0010,
        },
        "relaxed_v1": {
            "min_offset_bars": 4.0,
            "max_offset_bars": 24.0,
            "min_orb_width_atr": 0.65,
            "max_orb_width_atr": 3.40,
            "min_trend_strength": 0.20,
            "breakout_buffer_atr": 0.10,
            "min_breakout_body_atr": 0.35,
            "min_breakout_close_long": 0.57,
            "max_breakout_close_short": 0.43,
            "min_drive_extension_atr": 0.30,
            "reclaim_touch_buffer_atr": 0.10,
            "reclaim_overshoot_atr": 0.36,
            "reclaim_close_buffer_atr": 0.04,
            "min_reclaim_body_atr": 0.20,
            "min_reclaim_close_long": 0.53,
            "max_reclaim_close_short": 0.47,
            "min_volume_factor": 0.80,
            "entry_retest_buffer_atr": 0.06,
            "max_retest_wait_minutes": 3.0,
            "late_retest_high_risk_atr": 1.0,
            "late_retest_high_risk_max_wait_minutes": 2.0,
            "stop_buffer_atr": 0.13,
            "min_risk_atr": 0.22,
            "max_risk_atr": 1.35,
            "min_risk_pct": 0.0009,
        },
    }
    _PROFILE_SYMBOL_OVERRIDES: ClassVar[dict[str, dict[str, dict[str, float]]]] = {
        "baseline": {
            "BTCUSDC": {
                "min_reclaim_body_atr": 0.30,
            },
            "XRPUSDC": {
                "min_reclaim_body_atr": 0.30,
            },
        },
        "relaxed_v1": {
            "ETHUSDC": {
                "min_volume_factor": 0.90,
            },
            "BTCUSDC": {
                "min_reclaim_body_atr": 0.28,
            },
            "XRPUSDC": {
                "min_reclaim_body_atr": 0.28,
            },
        },
    }

    def __init__(
        self,
        *,
        symbol: str,
        candles_1m: list[Candle],
        candles_5m: list[Candle],
        profile_name: str = "baseline",
        exit_policy: SessionImpulseRetestExitPolicy | Mapping[str, Any] | None = None,
    ):
        self.symbol = str(symbol).upper()
        self.profile_symbol = _profile_symbol(self.symbol)
        self.profile_name = str(profile_name or "baseline").strip().lower() or "baseline"
        self.candles_1m = list(candles_1m)
        self.candles_5m = list(candles_5m)
        self.ts_1m = [self._normalize_ts(c.ts) for c in self.candles_1m]
        self.ts_5m = [self._normalize_ts(c.ts) for c in self.candles_5m]
        self.opens_1m = [float(c.o) for c in self.candles_1m]
        self.highs_1m = [float(c.h) for c in self.candles_1m]
        self.lows_1m = [float(c.l) for c in self.candles_1m]
        self.closes_1m = [float(c.c) for c in self.candles_1m]
        self.volumes_1m = [float(c.v) for c in self.candles_1m]
        self.opens_5m = [float(c.o) for c in self.candles_5m]
        self.highs_5m = [float(c.h) for c in self.candles_5m]
        self.lows_5m = [float(c.l) for c in self.candles_5m]
        self.closes_5m = [float(c.c) for c in self.candles_5m]
        self.volumes_5m = [float(c.v) for c in self.candles_5m]
        self.atr_5m = self._build_atr_5m()
        self.ema_fast_5m = self._build_ema_5m(20)
        self.ema_slow_5m = self._build_ema_5m(50)
        self.session_vwap_5m = self._build_session_vwap_5m()
        self.htf_4h_bars = self._resample_5m_bars(240)
        self.htf_1d_bars = self._resample_5m_bars(1440)
        self.htf_4h_atr = self._build_resampled_atr(self.htf_4h_bars)
        self.htf_1d_atr = self._build_resampled_atr(self.htf_1d_bars)
        self._index_1m_by_ts = {ts: idx for idx, ts in enumerate(self.ts_1m)}
        self._index_5m_by_ts = {ts: idx for idx, ts in enumerate(self.ts_5m)}
        self.exit_policy = self._normalize_exit_policy(exit_policy)

    @staticmethod
    def _normalize_exit_policy(
        value: SessionImpulseRetestExitPolicy | Mapping[str, Any] | None,
    ) -> SessionImpulseRetestExitPolicy:
        if isinstance(value, SessionImpulseRetestExitPolicy):
            return value
        if isinstance(value, Mapping):
            allowed = set(SessionImpulseRetestExitPolicy.__dataclass_fields__)
            payload = {str(key): item for key, item in value.items() if str(key) in allowed}
            return SessionImpulseRetestExitPolicy(**payload)
        return SessionImpulseRetestExitPolicy()

    def _signal_filter_profile(self) -> dict[str, float]:
        profile = dict(self._PROFILE_DEFAULTS.get(self.profile_name) or self._PROFILE_DEFAULTS["baseline"])
        profile.update((self._PROFILE_SYMBOL_OVERRIDES.get(self.profile_name) or {}).get(self.profile_symbol, {}))
        return profile

    def _blocked_signal_hours(self) -> tuple[int, ...]:
        return tuple(
            int(hour)
            for hour in (_PROFILE_SYMBOL_BLOCKED_SIGNAL_HOURS.get(self.profile_name) or {}).get(self.profile_symbol, ())
        )

    @staticmethod
    def _passes_late_retest_risk_filter(
        profile: dict[str, float],
        *,
        risk_atr: float,
        retest_wait_minutes: float,
    ) -> bool:
        high_risk_atr = float(profile.get("late_retest_high_risk_atr", 0.0) or 0.0)
        high_risk_max_wait = float(profile.get("late_retest_high_risk_max_wait_minutes", 0.0) or 0.0)
        if high_risk_atr <= 0.0 or high_risk_max_wait <= 0.0:
            return True
        return not (float(risk_atr) >= high_risk_atr and float(retest_wait_minutes) > high_risk_max_wait)

    @staticmethod
    def _normalize_ts(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _build_ema_5m(self, length: int) -> list[float]:
        alpha = 2.0 / (max(int(length), 1) + 1.0)
        out: list[float] = []
        ema = self.closes_5m[0] if self.closes_5m else 0.0
        for close in self.closes_5m:
            ema = alpha * float(close) + (1.0 - alpha) * ema
            out.append(float(ema))
        return out

    def _build_atr_5m(self, lookback: int = 14) -> list[float]:
        if len(self.candles_5m) < 2:
            return [0.0] * len(self.candles_5m)
        out = [0.0]
        trs: list[float] = []
        prev_close = self.closes_5m[0]
        for idx in range(1, len(self.candles_5m)):
            tr = max(
                self.highs_5m[idx] - self.lows_5m[idx],
                abs(self.highs_5m[idx] - prev_close),
                abs(self.lows_5m[idx] - prev_close),
            )
            trs.append(float(tr))
            prev_close = self.closes_5m[idx]
            recent = trs[-lookback:]
            out.append(float(sum(recent) / len(recent)))
        return out

    def _build_session_vwap_5m(self) -> list[float]:
        out: list[float] = []
        cumulative_pv = 0.0
        cumulative_volume = 0.0
        last_bucket: tuple[int, int, int] | None = None
        for idx, ts in enumerate(self.ts_5m):
            bucket = (ts.year, ts.month, ts.day)
            if bucket != last_bucket:
                cumulative_pv = 0.0
                cumulative_volume = 0.0
                last_bucket = bucket
            typical = (self.highs_5m[idx] + self.lows_5m[idx] + self.closes_5m[idx]) / 3.0
            volume = max(self.volumes_5m[idx], 1e-9)
            cumulative_pv += typical * volume
            cumulative_volume += volume
            out.append(float(cumulative_pv / max(cumulative_volume, 1e-9)))
        return out

    def _resample_5m_bars(self, interval_minutes: int) -> list[dict[str, Any]]:
        interval = max(int(interval_minutes), 5)
        bars: list[dict[str, Any]] = []
        for idx, ts in enumerate(self.ts_5m):
            minute_of_day = ts.hour * 60 + ts.minute
            bucket_minutes = (minute_of_day // interval) * interval
            bucket_start = ts.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=bucket_minutes)
            bucket_end = bucket_start + timedelta(minutes=interval)
            if not bars or bars[-1]["start_ts"] != bucket_start:
                bars.append(
                    {
                        "start_ts": bucket_start,
                        "end_ts": bucket_end,
                        "o": self.opens_5m[idx],
                        "h": self.highs_5m[idx],
                        "l": self.lows_5m[idx],
                        "c": self.closes_5m[idx],
                        "v": self.volumes_5m[idx],
                    }
                )
                continue
            bar = bars[-1]
            bar["h"] = max(float(bar["h"]), self.highs_5m[idx])
            bar["l"] = min(float(bar["l"]), self.lows_5m[idx])
            bar["c"] = self.closes_5m[idx]
            bar["v"] = float(bar["v"]) + self.volumes_5m[idx]
        return bars

    @staticmethod
    def _build_resampled_atr(bars: list[dict[str, Any]], lookback: int = 14) -> list[float]:
        if len(bars) < 2:
            return [0.0] * len(bars)
        out = [0.0]
        trs: list[float] = []
        prev_close = _safe_float(bars[0].get("c"), 0.0)
        for idx in range(1, len(bars)):
            high = _safe_float(bars[idx].get("h"), 0.0)
            low = _safe_float(bars[idx].get("l"), 0.0)
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(float(tr))
            prev_close = _safe_float(bars[idx].get("c"), prev_close)
            recent = trs[-lookback:]
            out.append(float(sum(recent) / len(recent)))
        return out

    def _volume_median_5m(self, start: int, end: int) -> float:
        values = self.volumes_5m[max(0, start):max(0, end)]
        return float(median(values)) if values else 0.0

    def _bar_range_5m(self, idx: int) -> float:
        return float(self.highs_5m[idx] - self.lows_5m[idx])

    def _body_size_5m(self, idx: int) -> float:
        return float(abs(self.closes_5m[idx] - self.opens_5m[idx]))

    def _close_position_in_bar_5m(self, idx: int) -> float:
        rng = max(self._bar_range_5m(idx), 1e-9)
        return float((self.closes_5m[idx] - self.lows_5m[idx]) / rng)

    @staticmethod
    def _zone_distance(price: float, zone: StructureZone) -> float:
        if zone.low <= price <= zone.high:
            return 0.0
        if price < zone.low:
            return float(zone.low - price)
        return float(price - zone.high)

    @staticmethod
    def _zone_payload(zone: StructureZone, *, distance_atr: float | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": zone.kind,
            "side": zone.side,
            "low": round(float(zone.low), 8),
            "high": round(float(zone.high), 8),
            "mid": round(float(zone.mid), 8),
            "score": round(float(zone.score), 6),
            "timeframe": zone.timeframe,
            "source_ts": zone.source_ts.isoformat(),
            "source": zone.source,
        }
        if distance_atr is not None:
            payload["distance_atr"] = round(float(distance_atr), 6)
        return payload

    @staticmethod
    def _bar_body_zone(bar: Mapping[str, Any], *, side: Literal["support", "resistance"]) -> tuple[float, float]:
        open_price = _safe_float(bar.get("o"), 0.0)
        close_price = _safe_float(bar.get("c"), 0.0)
        low = _safe_float(bar.get("l"), 0.0)
        high = _safe_float(bar.get("h"), 0.0)
        body_low = min(open_price, close_price)
        body_high = max(open_price, close_price)
        if side == "support":
            return float(low), float(max(body_high, low))
        return float(min(body_low, high)), float(high)

    def _htf_order_block_zones(
        self,
        *,
        bars: list[dict[str, Any]],
        atr_values: list[float],
        setup_ts: datetime,
        timeframe: str,
        lookback_days: int,
    ) -> list[StructureZone]:
        completed_pairs = [
            (idx, bar)
            for idx, bar in enumerate(bars)
            if bar["end_ts"] <= setup_ts and bar["start_ts"] >= setup_ts - timedelta(days=lookback_days)
        ]
        completed = [bar for _idx, bar in completed_pairs]
        if len(completed_pairs) < 5:
            return []
        zones: list[StructureZone] = []
        for local_idx in range(0, max(0, len(completed) - 3)):
            idx = completed_pairs[local_idx][0]
            bar = completed[local_idx]
            atr = max(float(atr_values[idx] if idx < len(atr_values) else 0.0), 1e-9)
            open_price = _safe_float(bar.get("o"), 0.0)
            close_price = _safe_float(bar.get("c"), 0.0)
            high = _safe_float(bar.get("h"), 0.0)
            low = _safe_float(bar.get("l"), 0.0)
            future = completed[local_idx + 1:local_idx + 4]
            age_days = max((setup_ts - bar["start_ts"]).total_seconds() / 86400.0, 0.0)
            recency = max(0.25, 1.0 - age_days / max(float(lookback_days) * 1.5, 1.0))
            if close_price < open_price:
                impulse = (max(_safe_float(item.get("h"), high) for item in future) - high) / atr
                if impulse >= 1.15:
                    zone_low, zone_high = self._bar_body_zone(bar, side="support")
                    zones.append(
                        StructureZone(
                            kind="order_block",
                            side="support",
                            low=zone_low,
                            high=zone_high,
                            score=float(min(3.0, impulse) * recency),
                            timeframe=timeframe,
                            source_ts=bar["start_ts"],
                            source=f"{timeframe}_bullish_order_block",
                        )
                    )
            if close_price > open_price:
                impulse = (low - min(_safe_float(item.get("l"), low) for item in future)) / atr
                if impulse >= 1.15:
                    zone_low, zone_high = self._bar_body_zone(bar, side="resistance")
                    zones.append(
                        StructureZone(
                            kind="order_block",
                            side="resistance",
                            low=zone_low,
                            high=zone_high,
                            score=float(min(3.0, impulse) * recency),
                            timeframe=timeframe,
                            source_ts=bar["start_ts"],
                            source=f"{timeframe}_bearish_order_block",
                        )
                    )
        return zones

    def _htf_fvg_zones(
        self,
        *,
        bars: list[dict[str, Any]],
        atr_values: list[float],
        setup_ts: datetime,
        timeframe: str,
        lookback_days: int,
    ) -> list[StructureZone]:
        completed_pairs = [
            (idx, bar)
            for idx, bar in enumerate(bars)
            if bar["end_ts"] <= setup_ts and bar["start_ts"] >= setup_ts - timedelta(days=lookback_days)
        ]
        completed = [bar for _idx, bar in completed_pairs]
        if len(completed_pairs) < 3:
            return []
        zones: list[StructureZone] = []
        for local_idx in range(2, len(completed)):
            idx = completed_pairs[local_idx][0]
            left = completed[local_idx - 2]
            right = completed[local_idx]
            atr = max(float(atr_values[idx] if idx < len(atr_values) else 0.0), 1e-9)
            left_high = _safe_float(left.get("h"), 0.0)
            left_low = _safe_float(left.get("l"), 0.0)
            right_high = _safe_float(right.get("h"), 0.0)
            right_low = _safe_float(right.get("l"), 0.0)
            age_days = max((setup_ts - right["start_ts"]).total_seconds() / 86400.0, 0.0)
            recency = max(0.20, 1.0 - age_days / max(float(lookback_days), 1.0))
            if right_low > left_high:
                gap_atr = (right_low - left_high) / atr
                if gap_atr >= 0.12:
                    zones.append(
                        StructureZone(
                            kind="fvg",
                            side="support",
                            low=float(left_high),
                            high=float(right_low),
                            score=float((1.0 + min(gap_atr, 1.5)) * recency),
                            timeframe=timeframe,
                            source_ts=right["start_ts"],
                            source=f"{timeframe}_bullish_fvg",
                        )
                    )
            if right_high < left_low:
                gap_atr = (left_low - right_high) / atr
                if gap_atr >= 0.12:
                    zones.append(
                        StructureZone(
                            kind="fvg",
                            side="resistance",
                            low=float(right_high),
                            high=float(left_low),
                            score=float((1.0 + min(gap_atr, 1.5)) * recency),
                            timeframe=timeframe,
                            source_ts=right["start_ts"],
                            source=f"{timeframe}_bearish_fvg",
                        )
                    )
        return zones

    def _high_volume_reversal_zones(
        self,
        *,
        setup_idx: int,
        setup_ts: datetime,
        lookback_days: int,
    ) -> list[StructureZone]:
        min_ts = setup_ts - timedelta(days=lookback_days)
        start = max(0, setup_idx - int(lookback_days * 24 * 12))
        zones: list[StructureZone] = []
        for idx in range(start, setup_idx):
            if self.ts_5m[idx] < min_ts:
                continue
            atr = max(self.atr_5m[idx], 1e-9)
            bar_range = max(self._bar_range_5m(idx), 1e-9)
            if bar_range < 0.8 * atr:
                continue
            volume_med = self._volume_median_5m(idx - 96, idx)
            if volume_med <= 0.0:
                continue
            volume_factor = self.volumes_5m[idx] / volume_med
            if volume_factor < 2.0:
                continue
            body_low = min(self.opens_5m[idx], self.closes_5m[idx])
            body_high = max(self.opens_5m[idx], self.closes_5m[idx])
            lower_wick = max(body_low - self.lows_5m[idx], 0.0)
            upper_wick = max(self.highs_5m[idx] - body_high, 0.0)
            close_pos = self._close_position_in_bar_5m(idx)
            age_days = max((setup_ts - self.ts_5m[idx]).total_seconds() / 86400.0, 0.0)
            recency = max(0.20, 1.0 - age_days / max(float(lookback_days), 1.0))
            if lower_wick / bar_range >= 0.40 and close_pos >= 0.55:
                zones.append(
                    StructureZone(
                        kind="high_volume_reversal",
                        side="support",
                        low=float(self.lows_5m[idx]),
                        high=float(body_low),
                        score=float(min(volume_factor / 2.0, 2.5) * recency),
                        timeframe="5m",
                        source_ts=self.ts_5m[idx],
                        source="5m_high_volume_lower_rejection",
                    )
                )
            if upper_wick / bar_range >= 0.40 and close_pos <= 0.45:
                zones.append(
                    StructureZone(
                        kind="high_volume_reversal",
                        side="resistance",
                        low=float(body_high),
                        high=float(self.highs_5m[idx]),
                        score=float(min(volume_factor / 2.0, 2.5) * recency),
                        timeframe="5m",
                        source_ts=self.ts_5m[idx],
                        source="5m_high_volume_upper_rejection",
                    )
                )
        return zones[-80:]

    def _volume_node_zones(
        self,
        *,
        setup_idx: int,
        setup_ts: datetime,
        entry_price: float,
        lookback_days: int,
    ) -> list[StructureZone]:
        start = max(0, setup_idx - int(lookback_days * 24 * 12))
        highs = self.highs_5m[start:setup_idx]
        lows = self.lows_5m[start:setup_idx]
        if len(highs) < 100:
            return []
        low = min(lows)
        high = max(highs)
        if high <= low:
            return []
        bin_count = 64
        width = (high - low) / bin_count
        volumes = [0.0] * bin_count
        for idx in range(start, setup_idx):
            typical = (self.highs_5m[idx] + self.lows_5m[idx] + self.closes_5m[idx]) / 3.0
            bucket = max(0, min(bin_count - 1, int((typical - low) / max(width, 1e-9))))
            volumes[bucket] += self.volumes_5m[idx]
        ranked = sorted(range(bin_count), key=lambda item: volumes[item], reverse=True)[:6]
        max_volume = max(volumes) if volumes else 0.0
        zones: list[StructureZone] = []
        for bucket in ranked:
            if max_volume <= 0.0 or volumes[bucket] <= 0.0:
                continue
            zone_low = low + bucket * width
            zone_high = zone_low + width
            mid = (zone_low + zone_high) / 2.0
            side: Literal["support", "resistance"] = "support" if mid <= entry_price else "resistance"
            zones.append(
                StructureZone(
                    kind="volume_node",
                    side=side,
                    low=float(zone_low),
                    high=float(zone_high),
                    score=float(0.80 * volumes[bucket] / max_volume),
                    timeframe=f"{lookback_days}d",
                    source_ts=setup_ts - timedelta(days=lookback_days),
                    source=f"{lookback_days}d_volume_node",
                )
            )
        return zones

    def _higher_timeframe_structure_context(
        self,
        *,
        setup_idx: int,
        direction: Direction,
        entry_price: float,
        atr: float,
    ) -> dict[str, Any]:
        policy = self.exit_policy
        if not _safe_bool(policy.higher_timeframe_structure_enabled):
            return {}
        setup_ts = self.ts_5m[setup_idx]
        lookback_days = max(int(policy.higher_timeframe_lookback_days), 7)
        zones: list[StructureZone] = []
        zones.extend(
            self._htf_order_block_zones(
                bars=self.htf_1d_bars,
                atr_values=self.htf_1d_atr,
                setup_ts=setup_ts,
                timeframe="1d",
                lookback_days=lookback_days,
            )
        )
        zones.extend(
            self._htf_fvg_zones(
                bars=self.htf_1d_bars,
                atr_values=self.htf_1d_atr,
                setup_ts=setup_ts,
                timeframe="1d",
                lookback_days=lookback_days,
            )
        )
        zones.extend(
            self._htf_order_block_zones(
                bars=self.htf_4h_bars,
                atr_values=self.htf_4h_atr,
                setup_ts=setup_ts,
                timeframe="4h",
                lookback_days=lookback_days,
            )
        )
        zones.extend(
            self._htf_fvg_zones(
                bars=self.htf_4h_bars,
                atr_values=self.htf_4h_atr,
                setup_ts=setup_ts,
                timeframe="4h",
                lookback_days=lookback_days,
            )
        )
        zones.extend(self._high_volume_reversal_zones(setup_idx=setup_idx, setup_ts=setup_ts, lookback_days=lookback_days))
        zones.extend(
            self._volume_node_zones(
                setup_idx=setup_idx,
                setup_ts=setup_ts,
                entry_price=entry_price,
                lookback_days=lookback_days,
            )
        )
        if not zones:
            return {
                "htf_structure_enabled": True,
                "htf_structure_anchor_score": 0.0,
                "htf_structure_zone_count": 0,
            }

        anchor_side: Literal["support", "resistance"] = "support" if direction == "long" else "resistance"
        target_side: Literal["support", "resistance"] = "resistance" if direction == "long" else "support"
        max_distance_atr = max(float(policy.higher_timeframe_entry_max_distance_atr), 0.0)
        anchor_candidates: list[tuple[float, float, StructureZone]] = []
        for zone in zones:
            if zone.side != anchor_side:
                continue
            distance = self._zone_distance(entry_price, zone)
            distance_atr = distance / max(float(atr), 1e-9)
            if max_distance_atr > 0.0 and distance_atr > max_distance_atr:
                continue
            adjusted_score = float(zone.score) / (1.0 + distance_atr)
            anchor_candidates.append((adjusted_score, distance_atr, zone))
        anchor_candidates.sort(key=lambda item: (item[0], -item[1]), reverse=True)
        anchor = anchor_candidates[0] if anchor_candidates else None

        direction_sign = 1.0 if direction == "long" else -1.0
        target_candidates: list[tuple[float, float, StructureZone]] = []
        for zone in zones:
            if zone.side != target_side:
                continue
            target_price = zone.low if direction == "long" else zone.high
            progress_atr = direction_sign * (target_price - entry_price) / max(float(atr), 1e-9)
            if progress_atr <= 0.25:
                continue
            target_candidates.append((progress_atr, zone.score, zone))
        target_candidates.sort(key=lambda item: item[0])

        payload: dict[str, Any] = {
            "htf_structure_enabled": True,
            "htf_structure_zone_count": len(zones),
            "htf_structure_anchor_score": round(float(anchor[0]), 6) if anchor is not None else 0.0,
            "htf_structure_anchor_distance_atr": round(float(anchor[1]), 6) if anchor is not None else None,
            "htf_structure_anchor": self._zone_payload(anchor[2], distance_atr=anchor[1]) if anchor is not None else None,
        }
        if anchor is not None:
            payload.update(
                {
                    "htf_structure_anchor_kind": anchor[2].kind,
                    "htf_structure_anchor_source": anchor[2].source,
                    "htf_structure_anchor_low": float(anchor[2].low),
                    "htf_structure_anchor_high": float(anchor[2].high),
                }
            )
        if _safe_bool(policy.higher_timeframe_target_enabled):
            selected_targets = target_candidates[:6]
            payload["htf_structure_target_prices"] = [
                float(item[2].low if direction == "long" else item[2].high) for item in selected_targets
            ]
            payload["htf_structure_target_sources"] = [str(item[2].source) for item in selected_targets]
            payload["htf_structure_targets"] = [
                self._zone_payload(item[2], distance_atr=item[0]) for item in selected_targets
            ]
        return payload

    @staticmethod
    def _session_anchor_hours() -> tuple[int, ...]:
        return (0, 6, 13)

    def _session_anchor_index(self, idx: int) -> int | None:
        for probe in range(idx, max(-1, idx - self._SESSION_ANCHOR_LOOKBACK_BARS), -1):
            ts = self.ts_5m[probe]
            if ts.minute == 0 and ts.hour in self._session_anchor_hours():
                return probe
        return None

    def _rolling_high_5m(self, start: int, end: int) -> float:
        return float(max(self.highs_5m[max(0, start):max(0, end)]))

    def _rolling_low_5m(self, start: int, end: int) -> float:
        return float(min(self.lows_5m[max(0, start):max(0, end)]))

    def _find_1m_entry(
        self,
        *,
        setup_idx_5m: int,
        direction: Direction,
        reclaim_level: float,
        atr_5m: float,
        retest_buffer_atr: float,
        max_retest_wait_minutes: float,
    ) -> tuple[datetime, float] | None:
        start_ts = self._entry_actionable_ts(setup_idx_5m)
        max_wait = max(int(max_retest_wait_minutes), 0)
        end_ts = start_ts + timedelta(minutes=max_wait + 1)
        start_idx = self._index_1m_by_ts.get(start_ts)
        if start_idx is None:
            return None
        idx = start_idx
        while idx < len(self.ts_1m) and self.ts_1m[idx] < end_ts:
            if direction == "long":
                accepted = (
                    self.lows_1m[idx] <= reclaim_level + float(retest_buffer_atr) * atr_5m
                    and self.closes_1m[idx] >= reclaim_level
                    and self.closes_1m[idx] > self.opens_1m[idx]
                )
            else:
                accepted = (
                    self.highs_1m[idx] >= reclaim_level - float(retest_buffer_atr) * atr_5m
                    and self.closes_1m[idx] <= reclaim_level
                    and self.closes_1m[idx] < self.opens_1m[idx]
                )
            if accepted:
                return self.ts_1m[idx], self.closes_1m[idx]
            idx += 1
        return None

    def _entry_actionable_ts(self, setup_idx_5m: int) -> datetime:
        delay_minutes = max(int(self.exit_policy.entry_confirmation_delay_minutes), 0)
        return self.ts_5m[setup_idx_5m] + timedelta(minutes=delay_minutes)

    @classmethod
    def _time_guard_exit_reason(cls, *, held_minutes: int, best_progress_r: float) -> str | None:
        if held_minutes >= 20 and best_progress_r < cls._TIME_GUARD_20M_MIN_MFE_R:
            return "time_guard_20m"
        if held_minutes >= 10 and best_progress_r < cls._TIME_GUARD_10M_MIN_MFE_R:
            return "time_guard_10m"
        return None

    @staticmethod
    def _policy_time_guard_exit_reason(
        *,
        policy: SessionImpulseRetestExitPolicy,
        held_minutes: int,
        best_progress_r: float,
    ) -> str | None:
        guard_20 = policy.time_guard_20m_min_mfe_r
        guard_10 = policy.time_guard_10m_min_mfe_r
        if guard_20 is not None and held_minutes >= 20 and best_progress_r < float(guard_20):
            return "time_guard_20m"
        if guard_10 is not None and held_minutes >= 10 and best_progress_r < float(guard_10):
            return "time_guard_10m"
        return None

    def _median_1m_volume(self, *, end_idx: int, lookback_bars: int) -> float:
        lookback = max(int(lookback_bars), 1)
        end = max(0, min(int(end_idx), len(self.volumes_1m)))
        start = max(0, end - lookback)
        values = [float(value) for value in self.volumes_1m[start:end] if float(value) > 0.0]
        if not values:
            return 0.0
        return float(median(values))

    def _adverse_volume_exit_details(
        self,
        *,
        policy: SessionImpulseRetestExitPolicy,
        signal: MicroSignal,
        idx: int,
        entry_idx: int,
        risk_abs: float,
        remaining_fraction: float,
    ) -> dict[str, float | str] | None:
        if not _safe_bool(policy.adverse_volume_exit_enabled):
            return None
        if idx <= entry_idx:
            return None
        if _safe_bool(policy.adverse_volume_exit_after_partial_only) and remaining_fraction >= 0.999999:
            return None
        lookback = max(int(policy.adverse_volume_exit_lookback_bars), 1)
        volume_med = self._median_1m_volume(end_idx=idx, lookback_bars=lookback)
        if volume_med <= 0.0:
            return None
        volume_factor = float(self.volumes_1m[idx] / max(volume_med, 1e-9))
        min_factor = max(float(policy.adverse_volume_exit_min_factor), 0.0)
        if volume_factor < min_factor:
            return None
        body = float(self.closes_1m[idx] - self.opens_1m[idx])
        adverse_body_r = -body / risk_abs if signal.direction == "long" else body / risk_abs
        min_body_r = max(float(policy.adverse_volume_exit_min_body_r), 0.0)
        if adverse_body_r < min_body_r:
            return None
        close_r = (
            (self.closes_1m[idx] - signal.entry_price) / risk_abs
            if signal.direction == "long"
            else (signal.entry_price - self.closes_1m[idx]) / risk_abs
        )
        return {
            "volume_factor": round(float(volume_factor), 6),
            "adverse_body_r": round(float(adverse_body_r), 6),
            "close_r": round(float(close_r), 6),
        }

    @staticmethod
    def _exit_policy_quality_score(diagnostics: Mapping[str, Any]) -> float:
        body = _safe_float(diagnostics.get("reclaim_body_atr"), 0.0)
        volume = _safe_float(diagnostics.get("volume_factor"), 0.0)
        trend = _safe_float(diagnostics.get("trend_strength_atr"), 0.0)
        drive = _safe_float(diagnostics.get("drive_extension_atr"), 0.0)
        wait = _safe_float(diagnostics.get("retest_wait_minutes"), 3.0)
        body_score = _clamp_float((body - 0.20) / 0.35)
        volume_score = _clamp_float((volume - 0.80) / 0.70)
        trend_score = _clamp_float((trend - 0.20) / 0.45)
        drive_score = _clamp_float((drive - 0.30) / 0.70)
        wait_score = _clamp_float((3.0 - wait) / 3.0)
        return float(
            0.25 * body_score
            + 0.25 * volume_score
            + 0.20 * trend_score
            + 0.20 * drive_score
            + 0.10 * wait_score
        )

    @staticmethod
    def _adaptive_tp_profile(
        *,
        policy: SessionImpulseRetestExitPolicy,
        diagnostics: Mapping[str, Any],
        stop_expansion_ratio: float,
    ) -> tuple[str, float, tuple[tuple[str, float, float], ...], float]:
        quality_score = SessionImpulseRetestResearch._exit_policy_quality_score(diagnostics)
        strong_target_rr = max(_safe_float(policy.adaptive_strong_target_rr, policy.target_rr), 0.1)
        normal_target_rr = max(min(_safe_float(policy.adaptive_normal_target_rr, 2.2), strong_target_rr), 0.1)
        defensive_target_rr = max(min(_safe_float(policy.adaptive_defensive_target_rr, 2.0), normal_target_rr), 0.1)

        if (
            stop_expansion_ratio >= max(float(policy.adaptive_stop_expansion_defensive_threshold), 1.0)
            or quality_score <= float(policy.adaptive_quality_defensive_threshold)
        ):
            profile = "defensive"
            target_rr = defensive_target_rr
            tp1_fraction = _clamp_float(float(policy.adaptive_defensive_tp1_fraction), 0.05, 0.95)
        elif (
            quality_score >= float(policy.adaptive_quality_strong_threshold)
            and stop_expansion_ratio <= max(float(policy.adaptive_stop_expansion_strong_max), 1.0)
        ):
            profile = "strong"
            target_rr = strong_target_rr
            tp1_fraction = _clamp_float(float(policy.adaptive_strong_tp1_fraction), 0.05, 0.95)
        else:
            profile = "normal"
            target_rr = normal_target_rr
            tp1_fraction = _clamp_float(float(policy.adaptive_normal_tp1_fraction), 0.05, 0.95)

        tp1_rr = max(float(policy.tp1_rr or 1.0), 0.1)
        tp_levels = SessionImpulseRetestExitPolicy._normalize_tp_levels(
            (
                ("tp1", min(tp1_rr, target_rr), tp1_fraction),
                ("tp2", target_rr, 1.0 - tp1_fraction),
            )
        )
        return profile, target_rr, tp_levels, quality_score

    @staticmethod
    def _structure_tp_profile(
        *,
        policy: SessionImpulseRetestExitPolicy,
        signal: MicroSignal,
        entry: float,
        risk_abs: float,
        atr: float,
        target_profile: str,
        tp1_fraction: float,
    ) -> tuple[float, tuple[tuple[str, float, float], ...], dict[str, Any]] | None:
        raw_prices = signal.diagnostics.get("structure_target_prices") if signal.diagnostics else None
        raw_sources = signal.diagnostics.get("structure_target_sources") if signal.diagnostics else None
        if not isinstance(raw_prices, list):
            return None
        sources = raw_sources if isinstance(raw_sources, list) else []
        direction_sign = 1.0 if signal.direction == "long" else -1.0
        buffer_abs = max(float(policy.structure_target_buffer_atr), 0.0) * max(float(atr), 1e-9)
        candidates: list[dict[str, Any]] = []
        for idx, raw_price in enumerate(raw_prices):
            level_price = _safe_float(raw_price, 0.0)
            if level_price <= 0.0:
                continue
            target_price = level_price - direction_sign * buffer_abs
            rr = direction_sign * (target_price - entry) / max(risk_abs, 1e-9)
            if rr <= 0.0:
                continue
            source = str(sources[idx]) if idx < len(sources) else f"structure_target_{idx + 1}"
            candidates.append(
                {
                    "source": source,
                    "level_price": level_price,
                    "target_price": target_price,
                    "rr": rr,
                }
            )
        if not candidates:
            return None

        candidates.sort(key=lambda item: float(item["rr"]))
        tp1_min_rr = max(float(policy.structure_tp1_min_rr), 0.1)
        tp2_min_rr = max(float(policy.structure_tp2_min_rr), tp1_min_rr + 0.25)
        tp_max_rr = max(float(policy.structure_tp_max_rr), tp2_min_rr)
        tp1_candidate = next((item for item in candidates if float(item["rr"]) >= tp1_min_rr), None)
        if tp1_candidate is None:
            return None
        tp2_candidate = next(
            (
                item
                for item in candidates
                if float(item["rr"]) >= max(tp2_min_rr, float(tp1_candidate["rr"]) + 0.25)
                and float(item["rr"]) <= tp_max_rr
            ),
            None,
        )
        if tp2_candidate is None:
            return None

        tp1_rr = float(tp1_candidate["rr"])
        tp2_rr = float(tp2_candidate["rr"])
        levels = SessionImpulseRetestExitPolicy._normalize_tp_levels(
            (
                ("tp1", tp1_rr, tp1_fraction),
                ("tp2", tp2_rr, 1.0 - tp1_fraction),
            )
        )
        return (
            tp2_rr,
            levels,
            {
                "policy_target_profile": f"structure_{target_profile}",
                "policy_structure_tp1_source": tp1_candidate["source"],
                "policy_structure_tp2_source": tp2_candidate["source"],
                "policy_structure_tp1_price": float(tp1_candidate["target_price"]),
                "policy_structure_tp2_price": float(tp2_candidate["target_price"]),
                "policy_structure_tp1_level_price": float(tp1_candidate["level_price"]),
                "policy_structure_tp2_level_price": float(tp2_candidate["level_price"]),
                "policy_structure_candidate_count": len(candidates),
            },
        )

    def _apply_exit_policy(self, signal: MicroSignal) -> MicroSignal | None:
        policy = self.exit_policy
        setup_idx = self._index_5m_by_ts.get(self._normalize_ts(signal.setup_ts))
        if setup_idx is None:
            return signal
        entry = float(signal.entry_price)
        if entry <= 0.0:
            return None
        if _safe_bool(policy.structure_targets_enabled):
            entry_distance_atr = _safe_float((signal.diagnostics or {}).get("entry_distance_atr"), 0.0)
            max_entry_distance_atr = max(float(policy.structure_entry_max_distance_atr), 0.0)
            if max_entry_distance_atr > 0.0 and entry_distance_atr > max_entry_distance_atr:
                return None
        if _safe_bool(policy.higher_timeframe_structure_enabled):
            min_anchor_score = max(float(policy.higher_timeframe_entry_min_score), 0.0)
            anchor_score = _safe_float((signal.diagnostics or {}).get("htf_structure_anchor_score"), 0.0)
            if min_anchor_score > 0.0 and anchor_score < min_anchor_score:
                return None
        direction_sign = 1.0 if signal.direction == "long" else -1.0
        atr = max(float(self.atr_5m[setup_idx]), 1e-9)
        legacy_stop = float(signal.stop_price)
        stop = legacy_stop
        if policy.stop_mode == "structure_floor":
            lookback = max(int(policy.swing_lookback_bars), 1)
            start = max(0, setup_idx - lookback + 1)
            buffer_atr = (
                float(policy.stop_buffer_atr)
                if policy.stop_buffer_atr is not None
                else float(self._signal_filter_profile().get("stop_buffer_atr", 0.0) or 0.0)
            )
            if signal.direction == "long":
                structure_stop = self._rolling_low_5m(start, setup_idx + 1) - buffer_atr * atr
                stop = min(legacy_stop, structure_stop)
            else:
                structure_stop = self._rolling_high_5m(start, setup_idx + 1) + buffer_atr * atr
                stop = max(legacy_stop, structure_stop)
        if _safe_bool(policy.higher_timeframe_structure_enabled) and _safe_bool(policy.higher_timeframe_stop_enabled):
            buffer_abs = max(float(policy.higher_timeframe_stop_buffer_atr), 0.0) * atr
            anchor_low = _safe_float((signal.diagnostics or {}).get("htf_structure_anchor_low"), 0.0)
            anchor_high = _safe_float((signal.diagnostics or {}).get("htf_structure_anchor_high"), 0.0)
            if signal.direction == "long" and anchor_low > 0.0 and anchor_low < entry:
                stop = min(stop, anchor_low - buffer_abs)
            elif signal.direction == "short" and anchor_high > 0.0 and anchor_high > entry:
                stop = max(stop, anchor_high + buffer_abs)

        risk_abs = entry - stop if signal.direction == "long" else stop - entry
        if risk_abs <= 0.0:
            return None
        min_risk_abs = max(float(policy.min_stop_pct) * entry, float(policy.min_risk_atr) * atr)
        if min_risk_abs > 0.0 and risk_abs < min_risk_abs:
            stop = entry - direction_sign * min_risk_abs
            risk_abs = min_risk_abs
        stop_pct = risk_abs / max(entry, 1e-9)
        risk_atr = risk_abs / atr
        if float(policy.max_stop_pct) > 0.0 and stop_pct > float(policy.max_stop_pct):
            return None
        if float(policy.max_risk_atr) > 0.0 and risk_atr > float(policy.max_risk_atr):
            return None

        legacy_risk_pct = abs(entry - legacy_stop) / max(entry, 1e-9)
        stop_expansion_ratio = stop_pct / max(legacy_risk_pct, 1e-9)
        target_profile = "fixed"
        quality_score = self._exit_policy_quality_score(signal.diagnostics or {})
        tp_levels = policy.tp_levels()
        target_rr = max(float(policy.target_rr), 0.1)
        structure_diagnostics: dict[str, Any] = {}
        if _safe_bool(policy.adaptive_targets_enabled):
            target_profile, target_rr, tp_levels, quality_score = self._adaptive_tp_profile(
                policy=policy,
                diagnostics=signal.diagnostics or {},
                stop_expansion_ratio=stop_expansion_ratio,
            )
        if _safe_bool(policy.structure_targets_enabled):
            tp1_fraction = tp_levels[0][2] if tp_levels else float(policy.tp1_fraction or 0.35)
            structure_profile = self._structure_tp_profile(
                policy=policy,
                signal=signal,
                entry=entry,
                risk_abs=risk_abs,
                atr=atr,
                target_profile=target_profile,
                tp1_fraction=tp1_fraction,
            )
            if structure_profile is not None:
                target_rr, tp_levels, structure_diagnostics = structure_profile
                target_profile = str(structure_diagnostics.get("policy_target_profile") or target_profile)
        target = entry + direction_sign * target_rr * risk_abs
        tp_diagnostics: dict[str, float] = {}
        for label, rr, fraction in tp_levels:
            tp_diagnostics[f"policy_{label}_rr"] = float(rr)
            tp_diagnostics[f"policy_{label}_fraction"] = float(fraction)
        diagnostics = {
            **dict(signal.diagnostics or {}),
            "exit_policy_name": policy.name,
            "exit_policy_stop_mode": policy.stop_mode,
            "legacy_stop_price": legacy_stop,
            "legacy_target_price": float(signal.target_price),
            "legacy_risk_pct": legacy_risk_pct,
            "policy_risk_pct": stop_pct,
            "policy_risk_atr": risk_atr,
            "policy_stop_expansion_ratio": stop_expansion_ratio,
            "policy_target_rr": target_rr,
            "policy_target_profile": target_profile,
            "policy_quality_score": quality_score,
            "policy_max_hold_minutes": int(policy.max_hold_minutes),
            **structure_diagnostics,
            **tp_diagnostics,
        }
        return MicroSignal(
            family=signal.family,
            direction=signal.direction,
            signal_ts=signal.signal_ts,
            setup_ts=signal.setup_ts,
            entry_ts=signal.entry_ts,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            max_hold_minutes=max(int(policy.max_hold_minutes), 1),
            regime_hint=signal.regime_hint,
            diagnostics=diagnostics,
        )

    def _build_signal(self, idx: int) -> MicroSignal | None:
        profile = self._signal_filter_profile()
        if self.ts_5m[idx].hour in self._blocked_signal_hours():
            return None
        session_anchor = self._session_anchor_index(idx)
        if session_anchor is None:
            return None
        offset = idx - session_anchor
        if offset < int(profile["min_offset_bars"]) or offset > int(profile["max_offset_bars"]):
            return None

        atr = max(self.atr_5m[idx], 1e-9)
        orb_end = min(session_anchor + 4, len(self.candles_5m))
        if idx <= orb_end:
            return None
        orb_high = self._rolling_high_5m(session_anchor, orb_end)
        orb_low = self._rolling_low_5m(session_anchor, orb_end)
        orb_width = orb_high - orb_low
        if orb_width <= float(profile["min_orb_width_atr"]) * atr or orb_width >= float(profile["max_orb_width_atr"]) * atr:
            return None

        trend_strength = abs(self.ema_fast_5m[idx] - self.ema_slow_5m[idx]) / atr
        if trend_strength < float(profile["min_trend_strength"]):
            return None

        volume_med = self._volume_median_5m(idx - 16, idx)
        drive_high = self._rolling_high_5m(orb_end, idx)
        drive_low = self._rolling_low_5m(orb_end, idx)
        vwap = self.session_vwap_5m[idx]
        volume_factor = float(self.volumes_5m[idx] / max(volume_med, 1e-9))
        base_diagnostics: dict[str, Any] = {
            "setup_hour_utc": self.ts_5m[idx].hour,
            "setup_weekday_utc": self.ts_5m[idx].weekday(),
            "offset_bars": offset,
            "orb_width_atr": float(orb_width / atr),
            "trend_strength_atr": float(trend_strength),
            "volume_factor": volume_factor,
            "reclaim_body_atr": float(self._body_size_5m(idx) / atr),
            "reclaim_close_position": float(self._close_position_in_bar_5m(idx)),
        }

        breakout_long = any(
            self.closes_5m[probe] > orb_high + float(profile["breakout_buffer_atr"]) * max(self.atr_5m[probe], 1e-9)
            and self._body_size_5m(probe) >= float(profile["min_breakout_body_atr"]) * max(self.atr_5m[probe], 1e-9)
            and self._close_position_in_bar_5m(probe) >= float(profile["min_breakout_close_long"])
            for probe in range(orb_end, idx)
        )
        long_reclaim = max(orb_high, vwap)
        if (
            self.ema_fast_5m[idx] > self.ema_slow_5m[idx]
            and drive_high >= orb_high + float(profile["min_drive_extension_atr"]) * atr
            and breakout_long
            and self.lows_5m[idx] <= long_reclaim + float(profile["reclaim_touch_buffer_atr"]) * atr
            and self.lows_5m[idx] >= long_reclaim - float(profile["reclaim_overshoot_atr"]) * atr
            and self.closes_5m[idx] >= long_reclaim + float(profile["reclaim_close_buffer_atr"]) * atr
            and self.closes_5m[idx] > self.opens_5m[idx]
            and self._body_size_5m(idx) >= float(profile["min_reclaim_body_atr"]) * atr
            and self._close_position_in_bar_5m(idx) >= float(profile["min_reclaim_close_long"])
            and self.volumes_5m[idx] >= max(volume_med * float(profile["min_volume_factor"]), 1e-9)
        ):
            entry = self._find_1m_entry(
                setup_idx_5m=idx,
                direction="long",
                reclaim_level=long_reclaim,
                atr_5m=atr,
                retest_buffer_atr=float(profile["entry_retest_buffer_atr"]),
                max_retest_wait_minutes=float(profile["max_retest_wait_minutes"]),
            )
            if entry is not None:
                entry_ts, entry_price = entry
                actionable_ts = self._entry_actionable_ts(idx)
                stop = min(self.lows_5m[idx], long_reclaim) - float(profile["stop_buffer_atr"]) * atr
                risk_abs = entry_price - stop
                min_risk_abs = max(float(profile["min_risk_atr"]) * atr, entry_price * float(profile["min_risk_pct"]))
                risk_atr = float(risk_abs / atr)
                retest_wait_minutes = max(int((entry_ts - actionable_ts).total_seconds() // 60), 0)
                if (
                    min_risk_abs <= risk_abs <= float(profile["max_risk_atr"]) * atr
                    and self._passes_late_retest_risk_filter(
                        profile,
                        risk_atr=risk_atr,
                        retest_wait_minutes=retest_wait_minutes,
                    )
                ):
                    structure_context = self._higher_timeframe_structure_context(
                        setup_idx=idx,
                        direction="long",
                        entry_price=entry_price,
                        atr=atr,
                    )
                    session_target_pairs = [
                        ("drive_high", drive_high),
                        ("opening_range_measured_move_1x", orb_high + orb_width),
                        ("opening_range_measured_move_1_5x", orb_high + 1.5 * orb_width),
                        ("opening_range_measured_move_2x", orb_high + 2.0 * orb_width),
                    ]
                    htf_prices = list(structure_context.get("htf_structure_target_prices") or [])
                    htf_sources = list(structure_context.get("htf_structure_target_sources") or [])
                    structure_target_prices = [
                        float(price)
                        for _source, price in session_target_pairs
                        if float(price) > float(entry_price)
                    ]
                    structure_target_sources = [
                        source
                        for source, price in session_target_pairs
                        if float(price) > float(entry_price)
                    ]
                    for htf_source, htf_price in zip(htf_sources, htf_prices, strict=False):
                        if _safe_float(htf_price, 0.0) > float(entry_price):
                            structure_target_sources.append(f"htf:{htf_source}")
                            structure_target_prices.append(float(htf_price))
                    diagnostics = {
                        **base_diagnostics,
                        "entry_key_level": float(long_reclaim),
                        "entry_actionable_ts": actionable_ts.isoformat(),
                        "entry_confirmation_delay_minutes": max(
                            int(self.exit_policy.entry_confirmation_delay_minutes),
                            0,
                        ),
                        "entry_zone_low": float(long_reclaim - float(profile["entry_retest_buffer_atr"]) * atr),
                        "entry_zone_high": float(long_reclaim + float(profile["entry_retest_buffer_atr"]) * atr),
                        "entry_distance_atr": float(abs(entry_price - long_reclaim) / atr),
                        "stop_key_level": float(min(self.lows_5m[idx], long_reclaim)),
                        "structure_target_prices": structure_target_prices,
                        "structure_target_sources": structure_target_sources,
                        "drive_extension_atr": float((drive_high - orb_high) / atr),
                        "reclaim_overshoot_atr": float((long_reclaim - self.lows_5m[idx]) / atr),
                        "retest_wait_minutes": retest_wait_minutes,
                        "risk_atr": risk_atr,
                        "risk_pct": float(risk_abs / max(entry_price, 1e-9)),
                        **structure_context,
                    }
                    return self._apply_exit_policy(
                        MicroSignal(
                            family="session_impulse_retest",
                            direction="long",
                            signal_ts=self.ts_5m[idx],
                            setup_ts=self.ts_5m[idx],
                            entry_ts=entry_ts,
                            entry_price=entry_price,
                            stop_price=stop,
                            target_price=entry_price + 2.0 * risk_abs,
                            max_hold_minutes=self._MAX_HOLD_MINUTES,
                            regime_hint="session_open",
                            diagnostics=diagnostics,
                        )
                    )

        breakout_short = any(
            self.closes_5m[probe] < orb_low - float(profile["breakout_buffer_atr"]) * max(self.atr_5m[probe], 1e-9)
            and self._body_size_5m(probe) >= float(profile["min_breakout_body_atr"]) * max(self.atr_5m[probe], 1e-9)
            and self._close_position_in_bar_5m(probe) <= float(profile["max_breakout_close_short"])
            for probe in range(orb_end, idx)
        )
        short_reclaim = min(orb_low, vwap)
        if (
            self.ema_fast_5m[idx] < self.ema_slow_5m[idx]
            and drive_low <= orb_low - float(profile["min_drive_extension_atr"]) * atr
            and breakout_short
            and self.highs_5m[idx] >= short_reclaim - float(profile["reclaim_touch_buffer_atr"]) * atr
            and self.highs_5m[idx] <= short_reclaim + float(profile["reclaim_overshoot_atr"]) * atr
            and self.closes_5m[idx] <= short_reclaim - float(profile["reclaim_close_buffer_atr"]) * atr
            and self.closes_5m[idx] < self.opens_5m[idx]
            and self._body_size_5m(idx) >= float(profile["min_reclaim_body_atr"]) * atr
            and self._close_position_in_bar_5m(idx) <= float(profile["max_reclaim_close_short"])
            and self.volumes_5m[idx] >= max(volume_med * float(profile["min_volume_factor"]), 1e-9)
        ):
            entry = self._find_1m_entry(
                setup_idx_5m=idx,
                direction="short",
                reclaim_level=short_reclaim,
                atr_5m=atr,
                retest_buffer_atr=float(profile["entry_retest_buffer_atr"]),
                max_retest_wait_minutes=float(profile["max_retest_wait_minutes"]),
            )
            if entry is not None:
                entry_ts, entry_price = entry
                actionable_ts = self._entry_actionable_ts(idx)
                stop = max(self.highs_5m[idx], short_reclaim) + float(profile["stop_buffer_atr"]) * atr
                risk_abs = stop - entry_price
                min_risk_abs = max(float(profile["min_risk_atr"]) * atr, entry_price * float(profile["min_risk_pct"]))
                risk_atr = float(risk_abs / atr)
                retest_wait_minutes = max(int((entry_ts - actionable_ts).total_seconds() // 60), 0)
                if (
                    min_risk_abs <= risk_abs <= float(profile["max_risk_atr"]) * atr
                    and self._passes_late_retest_risk_filter(
                        profile,
                        risk_atr=risk_atr,
                        retest_wait_minutes=retest_wait_minutes,
                    )
                ):
                    structure_context = self._higher_timeframe_structure_context(
                        setup_idx=idx,
                        direction="short",
                        entry_price=entry_price,
                        atr=atr,
                    )
                    session_target_pairs = [
                        ("drive_low", drive_low),
                        ("opening_range_measured_move_1x", orb_low - orb_width),
                        ("opening_range_measured_move_1_5x", orb_low - 1.5 * orb_width),
                        ("opening_range_measured_move_2x", orb_low - 2.0 * orb_width),
                    ]
                    htf_prices = list(structure_context.get("htf_structure_target_prices") or [])
                    htf_sources = list(structure_context.get("htf_structure_target_sources") or [])
                    structure_target_prices = [
                        float(price)
                        for _source, price in session_target_pairs
                        if float(price) < float(entry_price)
                    ]
                    structure_target_sources = [
                        source
                        for source, price in session_target_pairs
                        if float(price) < float(entry_price)
                    ]
                    for htf_source, htf_price in zip(htf_sources, htf_prices, strict=False):
                        if 0.0 < _safe_float(htf_price, 0.0) < float(entry_price):
                            structure_target_sources.append(f"htf:{htf_source}")
                            structure_target_prices.append(float(htf_price))
                    diagnostics = {
                        **base_diagnostics,
                        "entry_key_level": float(short_reclaim),
                        "entry_actionable_ts": actionable_ts.isoformat(),
                        "entry_confirmation_delay_minutes": max(
                            int(self.exit_policy.entry_confirmation_delay_minutes),
                            0,
                        ),
                        "entry_zone_low": float(short_reclaim - float(profile["entry_retest_buffer_atr"]) * atr),
                        "entry_zone_high": float(short_reclaim + float(profile["entry_retest_buffer_atr"]) * atr),
                        "entry_distance_atr": float(abs(entry_price - short_reclaim) / atr),
                        "stop_key_level": float(max(self.highs_5m[idx], short_reclaim)),
                        "structure_target_prices": structure_target_prices,
                        "structure_target_sources": structure_target_sources,
                        "drive_extension_atr": float((orb_low - drive_low) / atr),
                        "reclaim_overshoot_atr": float((self.highs_5m[idx] - short_reclaim) / atr),
                        "retest_wait_minutes": retest_wait_minutes,
                        "risk_atr": risk_atr,
                        "risk_pct": float(risk_abs / max(entry_price, 1e-9)),
                        **structure_context,
                    }
                    return self._apply_exit_policy(
                        MicroSignal(
                            family="session_impulse_retest",
                            direction="short",
                            signal_ts=self.ts_5m[idx],
                            setup_ts=self.ts_5m[idx],
                            entry_ts=entry_ts,
                            entry_price=entry_price,
                            stop_price=stop,
                            target_price=entry_price - 2.0 * risk_abs,
                            max_hold_minutes=self._MAX_HOLD_MINUTES,
                            regime_hint="session_open",
                            diagnostics=diagnostics,
                        )
                    )
        return None

    @staticmethod
    def _round_metric(value: Any) -> Any:
        if isinstance(value, float):
            return round(value, 6)
        return value

    @staticmethod
    def _failed_conditions(conditions: dict[str, bool]) -> list[str]:
        return [name for name, passed in conditions.items() if not bool(passed)]

    def _signal_rejection_diagnostics(self, idx: int) -> dict[str, Any]:
        profile = self._signal_filter_profile()
        setup_ts = self.ts_5m[idx]
        payload: dict[str, Any] = {
            "setup_ts": setup_ts.isoformat(),
            "setup_hour_utc": setup_ts.hour,
            "setup_weekday_utc": setup_ts.weekday(),
        }
        if setup_ts.hour in self._blocked_signal_hours():
            return {**payload, "reason": "blocked_signal_hour"}
        session_anchor = self._session_anchor_index(idx)
        if session_anchor is None:
            return {**payload, "reason": "no_session_anchor"}
        offset = idx - session_anchor
        payload["offset_bars"] = offset
        if offset < int(profile["min_offset_bars"]):
            return {**payload, "reason": "before_session_signal_window"}
        if offset > int(profile["max_offset_bars"]):
            return {**payload, "reason": "after_session_signal_window"}

        atr = max(self.atr_5m[idx], 1e-9)
        orb_end = min(session_anchor + 4, len(self.candles_5m))
        if idx <= orb_end:
            return {**payload, "reason": "opening_range_not_complete"}
        orb_high = self._rolling_high_5m(session_anchor, orb_end)
        orb_low = self._rolling_low_5m(session_anchor, orb_end)
        orb_width = orb_high - orb_low
        orb_width_atr = float(orb_width / atr)
        payload["orb_width_atr"] = orb_width_atr
        if orb_width <= float(profile["min_orb_width_atr"]) * atr:
            return {**payload, "reason": "opening_range_too_narrow"}
        if orb_width >= float(profile["max_orb_width_atr"]) * atr:
            return {**payload, "reason": "opening_range_too_wide"}

        trend_strength = abs(self.ema_fast_5m[idx] - self.ema_slow_5m[idx]) / atr
        payload["trend_strength_atr"] = float(trend_strength)
        if trend_strength < float(profile["min_trend_strength"]):
            return {**payload, "reason": "trend_strength_too_weak"}

        volume_med = self._volume_median_5m(idx - 16, idx)
        drive_high = self._rolling_high_5m(orb_end, idx)
        drive_low = self._rolling_low_5m(orb_end, idx)
        vwap = self.session_vwap_5m[idx]
        volume_factor = float(self.volumes_5m[idx] / max(volume_med, 1e-9))
        reclaim_body_atr = float(self._body_size_5m(idx) / atr)
        reclaim_close_position = float(self._close_position_in_bar_5m(idx))
        breakout_long = any(
            self.closes_5m[probe] > orb_high + float(profile["breakout_buffer_atr"]) * max(self.atr_5m[probe], 1e-9)
            and self._body_size_5m(probe) >= float(profile["min_breakout_body_atr"]) * max(self.atr_5m[probe], 1e-9)
            and self._close_position_in_bar_5m(probe) >= float(profile["min_breakout_close_long"])
            for probe in range(orb_end, idx)
        )
        breakout_short = any(
            self.closes_5m[probe] < orb_low - float(profile["breakout_buffer_atr"]) * max(self.atr_5m[probe], 1e-9)
            and self._body_size_5m(probe) >= float(profile["min_breakout_body_atr"]) * max(self.atr_5m[probe], 1e-9)
            and self._close_position_in_bar_5m(probe) <= float(profile["max_breakout_close_short"])
            for probe in range(orb_end, idx)
        )
        long_reclaim = max(orb_high, vwap)
        short_reclaim = min(orb_low, vwap)
        long_conditions = {
            "ema_trend": self.ema_fast_5m[idx] > self.ema_slow_5m[idx],
            "drive_extension": drive_high >= orb_high + float(profile["min_drive_extension_atr"]) * atr,
            "breakout": breakout_long,
            "reclaim_touch": self.lows_5m[idx] <= long_reclaim + float(profile["reclaim_touch_buffer_atr"]) * atr,
            "reclaim_overshoot": self.lows_5m[idx] >= long_reclaim - float(profile["reclaim_overshoot_atr"]) * atr,
            "reclaim_close": self.closes_5m[idx] >= long_reclaim + float(profile["reclaim_close_buffer_atr"]) * atr,
            "candle_direction": self.closes_5m[idx] > self.opens_5m[idx],
            "reclaim_body": self._body_size_5m(idx) >= float(profile["min_reclaim_body_atr"]) * atr,
            "reclaim_close_position": reclaim_close_position >= float(profile["min_reclaim_close_long"]),
            "volume": self.volumes_5m[idx] >= max(volume_med * float(profile["min_volume_factor"]), 1e-9),
        }
        short_conditions = {
            "ema_trend": self.ema_fast_5m[idx] < self.ema_slow_5m[idx],
            "drive_extension": drive_low <= orb_low - float(profile["min_drive_extension_atr"]) * atr,
            "breakout": breakout_short,
            "reclaim_touch": self.highs_5m[idx] >= short_reclaim - float(profile["reclaim_touch_buffer_atr"]) * atr,
            "reclaim_overshoot": self.highs_5m[idx] <= short_reclaim + float(profile["reclaim_overshoot_atr"]) * atr,
            "reclaim_close": self.closes_5m[idx] <= short_reclaim - float(profile["reclaim_close_buffer_atr"]) * atr,
            "candle_direction": self.closes_5m[idx] < self.opens_5m[idx],
            "reclaim_body": self._body_size_5m(idx) >= float(profile["min_reclaim_body_atr"]) * atr,
            "reclaim_close_position": reclaim_close_position <= float(profile["max_reclaim_close_short"]),
            "volume": self.volumes_5m[idx] >= max(volume_med * float(profile["min_volume_factor"]), 1e-9),
        }

        long_pass_count = sum(1 for passed in long_conditions.values() if passed)
        short_pass_count = sum(1 for passed in short_conditions.values() if passed)
        direction: Direction = "long" if long_pass_count >= short_pass_count else "short"
        selected_conditions = long_conditions if direction == "long" else short_conditions
        reclaim_level = long_reclaim if direction == "long" else short_reclaim
        if not all(selected_conditions.values()):
            return {
                **payload,
                "reason": "setup_conditions_not_met",
                "closest_direction": direction,
                "long_pass_count": long_pass_count,
                "short_pass_count": short_pass_count,
                "failed_conditions": self._failed_conditions(selected_conditions),
                "volume_factor": volume_factor,
                "reclaim_body_atr": reclaim_body_atr,
                "reclaim_close_position": reclaim_close_position,
            }

        entry = self._find_1m_entry(
            setup_idx_5m=idx,
            direction=direction,
            reclaim_level=reclaim_level,
            atr_5m=atr,
            retest_buffer_atr=float(profile["entry_retest_buffer_atr"]),
            max_retest_wait_minutes=float(profile["max_retest_wait_minutes"]),
        )
        if entry is None:
            return {
                **payload,
                "reason": "no_1m_retest_entry",
                "closest_direction": direction,
                "long_pass_count": long_pass_count,
                "short_pass_count": short_pass_count,
                "volume_factor": volume_factor,
                "reclaim_body_atr": reclaim_body_atr,
                "reclaim_close_position": reclaim_close_position,
            }
        entry_ts, entry_price = entry
        if direction == "long":
            stop = min(self.lows_5m[idx], reclaim_level) - float(profile["stop_buffer_atr"]) * atr
            risk_abs = entry_price - stop
        else:
            stop = max(self.highs_5m[idx], reclaim_level) + float(profile["stop_buffer_atr"]) * atr
            risk_abs = stop - entry_price
        min_risk_abs = max(float(profile["min_risk_atr"]) * atr, entry_price * float(profile["min_risk_pct"]))
        max_risk_abs = float(profile["max_risk_atr"]) * atr
        risk_atr = float(risk_abs / atr)
        retest_wait_minutes = max(int((entry_ts - self.ts_5m[idx]).total_seconds() // 60), 0)
        if risk_abs < min_risk_abs:
            reason = "risk_too_small"
        elif risk_abs > max_risk_abs:
            reason = "risk_too_large"
        elif not self._passes_late_retest_risk_filter(
            profile,
            risk_atr=risk_atr,
            retest_wait_minutes=retest_wait_minutes,
        ):
            reason = "late_retest_risk_filter"
        else:
            reason = "accepted_by_diagnostics"
        return {
            **payload,
            "reason": reason,
            "closest_direction": direction,
            "entry_ts": entry_ts.isoformat(),
            "retest_wait_minutes": retest_wait_minutes,
            "risk_atr": risk_atr,
            "risk_pct": float(risk_abs / max(entry_price, 1e-9)),
            "volume_factor": volume_factor,
            "reclaim_body_atr": reclaim_body_atr,
            "reclaim_close_position": reclaim_close_position,
        }

    def latest_signal_diagnostics(self, *, freshness_minutes: int = 20) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": "session_impulse_retest_latest_signal_diagnostics_v1",
            "symbol": self.symbol,
            "profile_symbol": self.profile_symbol,
            "profile_name": self.profile_name,
            "freshness_minutes": int(freshness_minutes),
            "candles_1m": len(self.candles_1m),
            "candles_5m": len(self.candles_5m),
            "status": "no_fresh_signal",
            "reason": "no_recent_signal",
        }
        if len(self.candles_5m) < 80 or len(self.candles_1m) < 600:
            payload["status"] = "insufficient_candles"
            payload["reason"] = "insufficient_1m_or_5m_candles"
            return payload
        last_ts = self._normalize_ts(self.candles_1m[-1].ts)
        min_ts = last_ts - timedelta(minutes=max(int(freshness_minutes), 1))
        start = max(60, len(self.candles_5m) - 12)
        reason_counts: dict[str, int] = {}
        scanned: list[dict[str, Any]] = []
        stale_candidate: dict[str, Any] | None = None
        future_candidate: dict[str, Any] | None = None
        for idx in range(len(self.candles_5m) - 2, start - 1, -1):
            signal = self._build_signal(idx)
            if signal is not None:
                candidate = {
                    "setup_ts": signal.setup_ts.isoformat(),
                    "entry_ts": signal.entry_ts.isoformat(),
                    "direction": signal.direction,
                    "diagnostics": {
                        key: self._round_metric(value)
                        for key, value in sorted(dict(signal.diagnostics or {}).items())
                    },
                }
                if signal.entry_ts < min_ts:
                    stale_candidate = stale_candidate or candidate
                    reason = "candidate_stale"
                elif signal.entry_ts > last_ts:
                    future_candidate = future_candidate or candidate
                    reason = "candidate_after_latest_candle"
                else:
                    payload.update(
                        {
                            "status": "fresh_signal",
                            "reason": "fresh_signal_available",
                            "last_1m_ts": last_ts.isoformat(),
                            "min_fresh_entry_ts": min_ts.isoformat(),
                            "scan_bars": len(scanned) + 1,
                            "fresh_candidate": candidate,
                        }
                    )
                    return payload
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
                scanned.append({**candidate, "reason": reason})
                continue

            diagnostic = self._signal_rejection_diagnostics(idx)
            reason = str(diagnostic.get("reason") or "unknown")
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            scanned.append({key: self._round_metric(value) for key, value in diagnostic.items()})

        best = max(
            scanned,
            key=lambda item: int(item.get("long_pass_count", 0) or 0) + int(item.get("short_pass_count", 0) or 0),
            default={},
        )
        payload.update(
            {
                "last_1m_ts": last_ts.isoformat(),
                "min_fresh_entry_ts": min_ts.isoformat(),
                "scan_bars": len(scanned),
                "reason_counts": reason_counts,
                "latest_checked": scanned[0] if scanned else {},
                "closest_setup": best,
                "latest_stale_candidate": stale_candidate,
                "latest_future_candidate": future_candidate,
            }
        )
        if stale_candidate is not None:
            payload["reason"] = "latest_candidate_stale"
        elif future_candidate is not None:
            payload["reason"] = "latest_candidate_after_latest_candle"
        elif scanned and str(scanned[0].get("reason") or "").strip():
            payload["reason"] = str(scanned[0].get("reason"))
        elif reason_counts:
            payload["reason"] = max(reason_counts.items(), key=lambda item: item[1])[0]
        return payload

    def _simulate_trade(self, signal: MicroSignal) -> MicroTrade | None:
        entry_idx = self._index_1m_by_ts.get(signal.entry_ts)
        if entry_idx is None:
            return None
        risk_abs = abs(signal.entry_price - signal.stop_price)
        if risk_abs <= 1e-9:
            return None
        policy = self.exit_policy
        signal_target_rr = abs(float(signal.target_price) - float(signal.entry_price)) / risk_abs
        tp_levels = policy.tp_levels_for_signal(signal.diagnostics)
        end_ts = signal.entry_ts + timedelta(minutes=signal.max_hold_minutes)
        exit_idx = entry_idx
        exit_price = self.closes_1m[entry_idx]
        exit_reason = "time_exit"
        best_progress_r = 0.0
        realized_gross_r = 0.0
        remaining_fraction = 1.0
        hit_target_labels: set[str] = set()
        active_stop_price = float(signal.stop_price)
        management_events: list[str] = []
        management_details: dict[str, Any] = {}

        idx = entry_idx
        while idx < len(self.ts_1m) and self.ts_1m[idx] <= end_ts:
            hit_target = False
            hit_stop = False
            if signal.direction == "long":
                best_progress_r = max(best_progress_r, (self.highs_1m[idx] - signal.entry_price) / risk_abs)
                hit_target = self.highs_1m[idx] >= signal.target_price
                hit_stop = self.lows_1m[idx] <= active_stop_price
            else:
                best_progress_r = max(best_progress_r, (signal.entry_price - self.lows_1m[idx]) / risk_abs)
                hit_target = self.lows_1m[idx] <= signal.target_price
                hit_stop = self.highs_1m[idx] >= active_stop_price
            if tp_levels:
                hit_target = any(
                    label not in hit_target_labels
                    and (
                        self.highs_1m[idx] >= signal.entry_price + rr * risk_abs
                        if signal.direction == "long"
                        else self.lows_1m[idx] <= signal.entry_price - rr * risk_abs
                    )
                    for label, rr, _fraction in tp_levels
                )
            if hit_target and hit_stop:
                hit_stop = True
                hit_target = False
            if hit_stop:
                exit_idx = idx
                exit_price = active_stop_price
                exit_reason = "stop"
                if remaining_fraction < 0.999999:
                    exit_reason = "stop_after_partial"
                stop_r = (
                    (active_stop_price - signal.entry_price) / risk_abs
                    if signal.direction == "long"
                    else (signal.entry_price - active_stop_price) / risk_abs
                )
                realized_gross_r += remaining_fraction * stop_r
                remaining_fraction = 0.0
                break
            if hit_target:
                if not tp_levels:
                    exit_idx = idx
                    exit_price = signal.target_price
                    exit_reason = "target"
                    realized_gross_r = float(signal_target_rr)
                    remaining_fraction = 0.0
                    break
                for label, rr, fraction in tp_levels:
                    if label in hit_target_labels or remaining_fraction <= 1e-9:
                        continue
                    target_price = (
                        signal.entry_price + rr * risk_abs
                        if signal.direction == "long"
                        else signal.entry_price - rr * risk_abs
                    )
                    target_hit = (
                        self.highs_1m[idx] >= target_price
                        if signal.direction == "long"
                        else self.lows_1m[idx] <= target_price
                    )
                    if not target_hit:
                        continue
                    qty = min(float(fraction), remaining_fraction)
                    realized_gross_r += qty * float(rr)
                    remaining_fraction = max(0.0, remaining_fraction - qty)
                    hit_target_labels.add(label)
                    exit_idx = idx
                    exit_price = target_price
                    exit_reason = f"target_{label}"
                if remaining_fraction <= 1e-9:
                    break
                if policy.stop_after_partial_rr is not None and remaining_fraction < 0.999999:
                    stop_rr = _safe_float(policy.stop_after_partial_rr, 0.0)
                    desired_stop = signal.entry_price + (1.0 if signal.direction == "long" else -1.0) * stop_rr * risk_abs
                    previous_stop = active_stop_price
                    if signal.direction == "long":
                        active_stop_price = max(active_stop_price, desired_stop)
                        managed_stop_hit = self.lows_1m[idx] <= active_stop_price
                    else:
                        active_stop_price = min(active_stop_price, desired_stop)
                        managed_stop_hit = self.highs_1m[idx] >= active_stop_price
                    if active_stop_price != previous_stop:
                        management_events.append("stop_after_partial_adjusted")
                        management_details["managed_stop_after_partial_rr"] = round(float(stop_rr), 6)
                        management_details["managed_stop_after_partial_price"] = round(float(active_stop_price), 8)
                    if managed_stop_hit:
                        exit_idx = idx
                        exit_price = active_stop_price
                        exit_reason = "stop_after_partial"
                        close_r = (
                            (active_stop_price - signal.entry_price) / risk_abs
                            if signal.direction == "long"
                            else (signal.entry_price - active_stop_price) / risk_abs
                        )
                        realized_gross_r += remaining_fraction * close_r
                        remaining_fraction = 0.0
                        break
            adverse_exit = self._adverse_volume_exit_details(
                policy=policy,
                signal=signal,
                idx=idx,
                entry_idx=entry_idx,
                risk_abs=risk_abs,
                remaining_fraction=remaining_fraction,
            )
            if adverse_exit is not None and remaining_fraction > 1e-9:
                exit_idx = idx
                exit_price = self.closes_1m[idx]
                exit_reason = "adverse_volume_exit"
                realized_gross_r += remaining_fraction * float(adverse_exit["close_r"])
                remaining_fraction = 0.0
                management_events.append("adverse_volume_exit")
                management_details["adverse_volume_exit"] = adverse_exit
                break
            held_minutes = max(int((self.ts_1m[idx] - signal.entry_ts).total_seconds() // 60), 0)
            time_guard_reason = self._policy_time_guard_exit_reason(
                policy=policy,
                held_minutes=held_minutes,
                best_progress_r=best_progress_r,
            )
            if time_guard_reason is not None:
                exit_idx = idx
                exit_price = self.closes_1m[idx]
                exit_reason = time_guard_reason
                close_r = (
                    (exit_price - signal.entry_price) / risk_abs
                    if signal.direction == "long"
                    else (signal.entry_price - exit_price) / risk_abs
                )
                realized_gross_r += remaining_fraction * close_r
                remaining_fraction = 0.0
                break
            exit_idx = idx
            exit_price = self.closes_1m[idx]
            idx += 1

        if remaining_fraction > 1e-9:
            close_r = (
                (exit_price - signal.entry_price) / risk_abs
                if signal.direction == "long"
                else (signal.entry_price - exit_price) / risk_abs
            )
            realized_gross_r += remaining_fraction * close_r
            remaining_fraction = 0.0
        gross_r = float(realized_gross_r)
        fee_abs = abs(signal.entry_price) * self._FEE_RATE_ROUND_TRIP
        cost_r = float(fee_abs / risk_abs)
        net_r = float(gross_r - cost_r)
        hold_minutes = max(int((self.ts_1m[exit_idx] - signal.entry_ts).total_seconds() // 60), 0)
        return MicroTrade(
            family=signal.family,
            symbol=self.symbol,
            direction=signal.direction,
            signal_ts=signal.signal_ts,
            entry_ts=signal.entry_ts,
            exit_ts=self.ts_1m[exit_idx],
            entry_price=signal.entry_price,
            exit_price=exit_price,
            stop_price=signal.stop_price,
            target_price=signal.target_price,
            r_value=net_r,
            gross_r=float(gross_r),
            cost_r=float(cost_r),
            hold_minutes=hold_minutes,
            exit_reason=exit_reason,
            regime_hint=signal.regime_hint,
            diagnostics={
                **dict(signal.diagnostics),
                "entry_hour_utc": signal.entry_ts.hour,
                "entry_weekday_utc": signal.entry_ts.weekday(),
                "hold_minutes": hold_minutes,
                "partial_target_labels": sorted(hit_target_labels),
                "position_management_events": management_events,
                **management_details,
            },
        )

    def backtest(self) -> list[MicroTrade]:
        trades: list[MicroTrade] = []
        if len(self.candles_5m) < 80 or len(self.candles_1m) < 600:
            return trades
        idx = 60
        while idx < len(self.candles_5m) - 2:
            signal = self._build_signal(idx)
            if signal is None:
                idx += 1
                continue
            trade = self._simulate_trade(signal)
            if trade is not None:
                trades.append(trade)
            idx += 1
        return trades

    def latest_signal(self, *, freshness_minutes: int = 20) -> MicroSignal | None:
        if len(self.candles_5m) < 80 or len(self.candles_1m) < 600:
            return None
        last_ts = self._normalize_ts(self.candles_1m[-1].ts)
        min_ts = last_ts - timedelta(minutes=max(int(freshness_minutes), 1))
        start = max(60, len(self.candles_5m) - 12)
        for idx in range(len(self.candles_5m) - 2, start - 1, -1):
            signal = self._build_signal(idx)
            if signal is None:
                continue
            if signal.entry_ts < min_ts:
                continue
            if signal.entry_ts > last_ts:
                continue
            return signal
        return None


def summarize_micro_trades(trades: list[MicroTrade]) -> dict[str, float | int | dict[str, int]]:
    if not trades:
        return {
            "closed": 0,
            "ev_r": 0.0,
            "total_r": 0.0,
            "win_rate": 0.0,
            "avg_hold_minutes": 0.0,
            "regime_hint_counts": {},
            "exit_reason_counts": {},
        }
    closed = len(trades)
    total_r = float(sum(item.r_value for item in trades))
    ev_r = float(total_r / closed)
    win_rate = float(sum(1 for item in trades if item.r_value > 0.0) / closed)
    avg_hold = float(sum(item.hold_minutes for item in trades) / closed)
    regime_counts: dict[str, int] = {}
    exit_counts: dict[str, int] = {}
    for item in trades:
        regime_counts[item.regime_hint] = regime_counts.get(item.regime_hint, 0) + 1
        exit_counts[item.exit_reason] = exit_counts.get(item.exit_reason, 0) + 1
    return {
        "closed": closed,
        "ev_r": round(ev_r, 4),
        "total_r": round(total_r, 4),
        "win_rate": round(win_rate, 4),
        "avg_hold_minutes": round(avg_hold, 2),
        "regime_hint_counts": regime_counts,
        "exit_reason_counts": exit_counts,
    }


def decision_for_micro_summary(summary: dict[str, Any]) -> str:
    ev = float(summary.get("ev_r", 0.0) or 0.0)
    closed = int(summary.get("closed", 0) or 0)
    total_r = float(summary.get("total_r", 0.0) or 0.0)
    if total_r <= 0.0 or ev < 0.20 or closed < 20:
        return "REJECT"
    if ev >= 0.30 and closed >= 40:
        return "PASS"
    return "WATCH"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def evaluate_session_impulse_retest_shadow_filters(*, diagnostics: dict[str, Any] | None) -> dict[str, Any]:
    diagnostics = dict(diagnostics or {})
    reclaim_body_atr = _safe_float(diagnostics.get("reclaim_body_atr"), default=float("nan"))
    threshold = 0.30
    available = reclaim_body_atr == reclaim_body_atr
    passed = bool(available and reclaim_body_atr >= threshold)
    return {
        "schema_version": "session_impulse_retest_shadow_filter_v1",
        "mode": "compare_only",
        "blocking_live": False,
        "decision": "would_pass" if passed else "would_block" if available else "unknown",
        "recommended_action": "record_shadow_only_do_not_block_live",
        "filters": [
            {
                "name": "reclaim_body_atr_min_0_30",
                "metric": "reclaim_body_atr",
                "threshold": threshold,
                "value": round(reclaim_body_atr, 6) if available else None,
                "passed": passed,
                "reason": "reclaim_body_atr_meets_shadow_floor"
                if passed
                else "reclaim_body_atr_below_shadow_floor"
                if available
                else "reclaim_body_atr_unavailable",
            }
        ],
    }


def session_impulse_retest_profile_for_symbol(symbol: str) -> str:
    normalized_symbol = _profile_symbol(str(symbol or "").upper())
    return str(_SESSION_IMPULSE_RETEST_PROFILE_BY_SYMBOL.get(normalized_symbol, "baseline"))


def build_session_impulse_retest_shadow_summary(
    *,
    symbol: str,
    candles_1m: list[Candle],
    candles_5m: list[Candle],
    enabled: bool,
    shadow_only: bool,
    allowed_symbols: list[str] | tuple[str, ...] | set[str],
) -> dict[str, Any]:
    normalized_symbol = str(symbol or "").upper()
    normalized_allowed = {str(item or "").upper() for item in allowed_symbols if str(item or "").strip()}
    enabled = _safe_bool(enabled)
    shadow_only = _safe_bool(shadow_only)
    payload: dict[str, Any] = {
        "family": "session_impulse_retest",
        "symbol": normalized_symbol,
        "enabled": enabled,
        "shadow_only": shadow_only,
        "available": False,
        "status": "disabled",
        "reason": "session_impulse_retest_disabled",
        "decision": "REJECT",
        "recent_closed": 0,
        "ev_r": 0.0,
        "total_r": 0.0,
        "win_rate": 0.0,
        "avg_hold_minutes": 0.0,
        "recent_window_hours": 0.0,
        "latest_trade": None,
        "activation_note": "Compare-only until a dedicated runtime lane is added.",
    }
    if not enabled:
        return payload
    if normalized_allowed and normalized_symbol not in normalized_allowed:
        payload["status"] = "symbol_not_allowed"
        payload["reason"] = "symbol_not_in_session_impulse_retest_contract"
        return payload
    if len(candles_1m) < 600 or len(candles_5m) < 200:
        payload["status"] = "insufficient_candles"
        payload["reason"] = "insufficient_1m_or_5m_candles"
        payload["candles_1m"] = len(candles_1m)
        payload["candles_5m"] = len(candles_5m)
        return payload

    profile_name = session_impulse_retest_profile_for_symbol(normalized_symbol)
    engine = SessionImpulseRetestResearch(
        symbol=normalized_symbol,
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        profile_name=profile_name,
    )
    trades = engine.backtest()
    summary = summarize_micro_trades(trades)
    decision = decision_for_micro_summary(summary)
    latest_trade = trades[-1] if trades else None
    recent_window_hours = 0.0
    if candles_1m:
        first_ts = engine._normalize_ts(candles_1m[0].ts)
        last_ts = engine._normalize_ts(candles_1m[-1].ts)
        recent_window_hours = round(max((last_ts - first_ts).total_seconds() / 3600.0, 0.0), 2)
    payload.update(
        {
            "available": True,
            "status": "shadow_only_compare" if shadow_only else "live_enabled",
            "reason": "ok",
            "profile_name": profile_name,
            "decision": decision,
            "recent_closed": int(summary.get("closed", 0) or 0),
            "ev_r": float(summary.get("ev_r", 0.0) or 0.0),
            "total_r": float(summary.get("total_r", 0.0) or 0.0),
            "win_rate": float(summary.get("win_rate", 0.0) or 0.0),
            "avg_hold_minutes": float(summary.get("avg_hold_minutes", 0.0) or 0.0),
            "recent_window_hours": recent_window_hours,
            "regime_hint_counts": dict(summary.get("regime_hint_counts") or {}),
            "exit_reason_counts": dict(summary.get("exit_reason_counts") or {}),
            "latest_trade": {
                "entry_ts": latest_trade.entry_ts.isoformat(),
                "exit_ts": latest_trade.exit_ts.isoformat(),
                "direction": latest_trade.direction,
                "r_value": round(float(latest_trade.r_value), 4),
                "exit_reason": latest_trade.exit_reason,
                "hold_minutes": int(latest_trade.hold_minutes),
            }
            if latest_trade is not None
            else None,
        }
    )
    return payload
