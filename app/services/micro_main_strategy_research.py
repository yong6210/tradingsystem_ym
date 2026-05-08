from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any, Literal

from app.db.models import Candle

Direction = Literal["long", "short"]


_SESSION_IMPULSE_RETEST_PROFILE_BY_SYMBOL: dict[str, str] = {
    "BTCUSDC": "baseline",
    "BNBUSDC": "baseline",
    "BCHUSDC": "baseline",
    "SUIUSDC": "baseline",
    "LTCUSDC": "baseline",
    "NEARUSDC": "baseline",
    "AAVEUSDC": "baseline",
    "XLMUSDC": "baseline",
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


class SessionImpulseRetestResearch:
    _FEE_RATE_ROUND_TRIP = 0.0006
    _MAX_HOLD_MINUTES = 40
    _TIME_GUARD_10M_MIN_MFE_R = 0.20
    _TIME_GUARD_20M_MIN_MFE_R = 0.35
    _PROFILE_DEFAULTS: dict[str, dict[str, float]] = {
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
            "stop_buffer_atr": 0.13,
            "min_risk_atr": 0.22,
            "max_risk_atr": 1.35,
            "min_risk_pct": 0.0009,
        },
    }
    _PROFILE_SYMBOL_OVERRIDES: dict[str, dict[str, dict[str, float]]] = {
        "baseline": {
            "BTCUSDC": {
                "min_reclaim_body_atr": 0.30,
            },
            "XRPUSDC": {
                "min_reclaim_body_atr": 0.30,
            },
        },
        "relaxed_v1": {
            "BTCUSDC": {
                "min_reclaim_body_atr": 0.28,
            },
            "XRPUSDC": {
                "min_reclaim_body_atr": 0.28,
            },
        },
    }

    def __init__(self, *, symbol: str, candles_1m: list[Candle], candles_5m: list[Candle], profile_name: str = "baseline"):
        self.symbol = str(symbol).upper()
        self.profile_name = str(profile_name or "baseline").strip().lower() or "baseline"
        self.candles_1m = list(candles_1m)
        self.candles_5m = list(candles_5m)
        self.ts_1m = [self._normalize_ts(c.ts) for c in self.candles_1m]
        self.ts_5m = [self._normalize_ts(c.ts) for c in self.candles_5m]
        self.opens_1m = [float(c.o) for c in self.candles_1m]
        self.highs_1m = [float(c.h) for c in self.candles_1m]
        self.lows_1m = [float(c.l) for c in self.candles_1m]
        self.closes_1m = [float(c.c) for c in self.candles_1m]
        self.opens_5m = [float(c.o) for c in self.candles_5m]
        self.highs_5m = [float(c.h) for c in self.candles_5m]
        self.lows_5m = [float(c.l) for c in self.candles_5m]
        self.closes_5m = [float(c.c) for c in self.candles_5m]
        self.volumes_5m = [float(c.v) for c in self.candles_5m]
        self.atr_5m = self._build_atr_5m()
        self.ema_fast_5m = self._build_ema_5m(20)
        self.ema_slow_5m = self._build_ema_5m(50)
        self.session_vwap_5m = self._build_session_vwap_5m()
        self._index_1m_by_ts = {ts: idx for idx, ts in enumerate(self.ts_1m)}

    def _signal_filter_profile(self) -> dict[str, float]:
        profile = dict(self._PROFILE_DEFAULTS.get(self.profile_name) or self._PROFILE_DEFAULTS["baseline"])
        profile.update((self._PROFILE_SYMBOL_OVERRIDES.get(self.profile_name) or {}).get(self.symbol, {}))
        return profile

    def _blocked_signal_hours(self) -> tuple[int, ...]:
        return tuple(
            int(hour)
            for hour in (_PROFILE_SYMBOL_BLOCKED_SIGNAL_HOURS.get(self.profile_name) or {}).get(self.symbol, ())
        )

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
    def _session_anchor_hours() -> tuple[int, ...]:
        return (0, 6, 13)

    def _session_anchor_index(self, idx: int) -> int | None:
        for probe in range(idx, max(-1, idx - 72), -1):
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
    ) -> tuple[datetime, float] | None:
        start_ts = self.ts_5m[setup_idx_5m]
        end_ts = start_ts + timedelta(minutes=15)
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

    @classmethod
    def _time_guard_exit_reason(cls, *, held_minutes: int, best_progress_r: float) -> str | None:
        if held_minutes >= 20 and best_progress_r < cls._TIME_GUARD_20M_MIN_MFE_R:
            return "time_guard_20m"
        if held_minutes >= 10 and best_progress_r < cls._TIME_GUARD_10M_MIN_MFE_R:
            return "time_guard_10m"
        return None

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
            )
            if entry is not None:
                entry_ts, entry_price = entry
                stop = min(self.lows_5m[idx], long_reclaim) - float(profile["stop_buffer_atr"]) * atr
                risk_abs = entry_price - stop
                min_risk_abs = max(float(profile["min_risk_atr"]) * atr, entry_price * float(profile["min_risk_pct"]))
                if min_risk_abs <= risk_abs <= float(profile["max_risk_atr"]) * atr:
                    return MicroSignal(
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
            )
            if entry is not None:
                entry_ts, entry_price = entry
                stop = max(self.highs_5m[idx], short_reclaim) + float(profile["stop_buffer_atr"]) * atr
                risk_abs = stop - entry_price
                min_risk_abs = max(float(profile["min_risk_atr"]) * atr, entry_price * float(profile["min_risk_pct"]))
                if min_risk_abs <= risk_abs <= float(profile["max_risk_atr"]) * atr:
                    return MicroSignal(
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
                    )
        return None

    def _simulate_trade(self, signal: MicroSignal) -> MicroTrade | None:
        entry_idx = self._index_1m_by_ts.get(signal.entry_ts)
        if entry_idx is None:
            return None
        risk_abs = abs(signal.entry_price - signal.stop_price)
        if risk_abs <= 1e-9:
            return None
        end_ts = signal.entry_ts + timedelta(minutes=signal.max_hold_minutes)
        exit_idx = entry_idx
        exit_price = self.closes_1m[entry_idx]
        exit_reason = "time_exit"
        best_progress_r = 0.0

        idx = entry_idx
        while idx < len(self.ts_1m) and self.ts_1m[idx] <= end_ts:
            hit_target = False
            hit_stop = False
            if signal.direction == "long":
                best_progress_r = max(best_progress_r, (self.highs_1m[idx] - signal.entry_price) / risk_abs)
                hit_target = self.highs_1m[idx] >= signal.target_price
                hit_stop = self.lows_1m[idx] <= signal.stop_price
            else:
                best_progress_r = max(best_progress_r, (signal.entry_price - self.lows_1m[idx]) / risk_abs)
                hit_target = self.lows_1m[idx] <= signal.target_price
                hit_stop = self.highs_1m[idx] >= signal.stop_price
            if hit_target and hit_stop:
                hit_stop = True
                hit_target = False
            if hit_stop:
                exit_idx = idx
                exit_price = signal.stop_price
                exit_reason = "stop"
                break
            if hit_target:
                exit_idx = idx
                exit_price = signal.target_price
                exit_reason = "target"
                break
            held_minutes = max(int((self.ts_1m[idx] - signal.entry_ts).total_seconds() // 60), 0)
            time_guard_reason = self._time_guard_exit_reason(
                held_minutes=held_minutes,
                best_progress_r=best_progress_r,
            )
            if time_guard_reason is not None:
                exit_idx = idx
                exit_price = self.closes_1m[idx]
                exit_reason = time_guard_reason
                break
            exit_idx = idx
            exit_price = self.closes_1m[idx]
            idx += 1

        gross_r = (
            (exit_price - signal.entry_price) / risk_abs
            if signal.direction == "long"
            else (signal.entry_price - exit_price) / risk_abs
        )
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


def session_impulse_retest_profile_for_symbol(symbol: str) -> str:
    normalized_symbol = str(symbol or "").upper()
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
    payload: dict[str, Any] = {
        "family": "session_impulse_retest",
        "symbol": normalized_symbol,
        "enabled": bool(enabled),
        "shadow_only": bool(shadow_only),
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
