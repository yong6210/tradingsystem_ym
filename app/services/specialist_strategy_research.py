from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Callable, Literal

from app.db.models import Candle

Direction = Literal["long", "short"]


@dataclass(frozen=True, slots=True)
class ResearchSignal:
    family: str
    direction: Direction
    signal_index: int
    entry_index: int
    entry_price: float
    stop_price: float
    target_price: float
    max_hold_bars: int
    regime_hint: str


@dataclass(frozen=True, slots=True)
class ResearchTrade:
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
    hold_bars: int
    exit_reason: str
    regime_hint: str


@dataclass(frozen=True, slots=True)
class SpecialistFamilySpec:
    key: str
    regime_hint: str
    max_hold_bars: int
    signal_builder: Callable[["SpecialistResearchEngine", int], ResearchSignal | None]


class SpecialistResearchEngine:
    _FEE_RATE_ROUND_TRIP = 0.0006
    _ATR_LOOKBACK = 14
    _EMA_FAST = 20
    _EMA_SLOW = 50

    def __init__(self, *, symbol: str, candles_15m: list[Candle]):
        self.symbol = str(symbol).upper()
        self.candles = list(candles_15m)
        self.opens = [float(c.o) for c in self.candles]
        self.highs = [float(c.h) for c in self.candles]
        self.lows = [float(c.l) for c in self.candles]
        self.closes = [float(c.c) for c in self.candles]
        self.volumes = [float(c.v) for c in self.candles]
        self.ts = [self._normalize_ts(c.ts) for c in self.candles]
        self.atr = self._build_atr()
        self.ema_fast = self._build_ema(self._EMA_FAST)
        self.ema_slow = self._build_ema(self._EMA_SLOW)
        self.session_vwap = self._build_session_vwap()
        self._family_specs = self._build_specs()

    @staticmethod
    def _normalize_ts(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _build_ema(self, length: int) -> list[float]:
        alpha = 2.0 / (max(int(length), 1) + 1.0)
        out: list[float] = []
        ema = self.closes[0] if self.closes else 0.0
        for close in self.closes:
            ema = alpha * float(close) + (1.0 - alpha) * ema
            out.append(float(ema))
        return out

    def _build_atr(self) -> list[float]:
        if len(self.candles) < 2:
            return [0.0] * len(self.candles)
        out = [0.0]
        trs: list[float] = []
        prev_close = self.closes[0]
        for idx in range(1, len(self.candles)):
            tr = max(
                self.highs[idx] - self.lows[idx],
                abs(self.highs[idx] - prev_close),
                abs(self.lows[idx] - prev_close),
            )
            trs.append(float(tr))
            prev_close = self.closes[idx]
            recent = trs[-self._ATR_LOOKBACK :]
            out.append(float(sum(recent) / len(recent)))
        return out

    def _build_session_vwap(self) -> list[float]:
        out: list[float] = []
        cumulative_pv = 0.0
        cumulative_volume = 0.0
        last_bucket: tuple[int, int, int] | None = None
        for idx in range(len(self.candles)):
            bucket = self._day_bucket(idx)
            if bucket != last_bucket:
                cumulative_pv = 0.0
                cumulative_volume = 0.0
                last_bucket = bucket
            typical = (self.highs[idx] + self.lows[idx] + self.closes[idx]) / 3.0
            volume = max(self.volumes[idx], 1e-9)
            cumulative_pv += typical * volume
            cumulative_volume += volume
            out.append(float(cumulative_pv / max(cumulative_volume, 1e-9)))
        return out

    def _rolling_high(self, start: int, end: int) -> float:
        if end <= start:
            return self.highs[max(start, 0)]
        return float(max(self.highs[max(0, start):max(0, end)]))

    def _rolling_low(self, start: int, end: int) -> float:
        if end <= start:
            return self.lows[max(start, 0)]
        return float(min(self.lows[max(0, start):max(0, end)]))

    def _rolling_close_high(self, start: int, end: int) -> float:
        return float(max(self.closes[max(0, start):max(0, end)]))

    def _rolling_close_low(self, start: int, end: int) -> float:
        return float(min(self.closes[max(0, start):max(0, end)]))

    def _volume_median(self, start: int, end: int) -> float:
        values = self.volumes[max(0, start):max(0, end)]
        return float(median(values)) if values else 0.0

    def _bar_range(self, idx: int) -> float:
        return float(self.highs[idx] - self.lows[idx])

    def _body_size(self, idx: int) -> float:
        return float(abs(self.closes[idx] - self.opens[idx]))

    def _close_position_in_bar(self, idx: int) -> float:
        rng = max(self._bar_range(idx), 1e-9)
        return float((self.closes[idx] - self.lows[idx]) / rng)

    def _in_uptrend(self, idx: int) -> bool:
        return self.ema_fast[idx] > self.ema_slow[idx] and self.ema_fast[idx] >= self.ema_fast[max(idx - 4, 0)]

    def _in_downtrend(self, idx: int) -> bool:
        return self.ema_fast[idx] < self.ema_slow[idx] and self.ema_fast[idx] <= self.ema_fast[max(idx - 4, 0)]

    def _range_like(self, idx: int) -> bool:
        atr = max(self.atr[idx], 1e-9)
        spread = abs(self.ema_fast[idx] - self.ema_slow[idx]) / atr
        width = (self._rolling_high(idx - 24, idx) - self._rolling_low(idx - 24, idx)) / atr
        return spread <= 0.45 and 3.0 <= width <= 9.0

    def _day_bucket(self, idx: int) -> tuple[int, int, int]:
        ts = self.ts[idx]
        return ts.year, ts.month, ts.day

    def _day_start_index(self, idx: int) -> int:
        current_day = self._day_bucket(idx)
        start = idx
        while start > 0 and self._day_bucket(start - 1) == current_day:
            start -= 1
        return start

    def _session_anchor_index(self, idx: int, *, allowed_hours: tuple[int, ...] = (0, 6, 13)) -> int | None:
        for probe in range(idx, max(-1, idx - 48), -1):
            ts = self.ts[probe]
            if ts.minute == 0 and ts.hour in allowed_hours:
                return probe
        return None

    def _build_specs(self) -> tuple[SpecialistFamilySpec, ...]:
        return (
            SpecialistFamilySpec(
                key="trend_continuation_pullback",
                regime_hint="trend",
                max_hold_bars=12,
                signal_builder=self._signal_trend_continuation_pullback,
            ),
            SpecialistFamilySpec(
                key="choch_displacement_reclaim",
                regime_hint="transition",
                max_hold_bars=10,
                signal_builder=self._signal_choch_displacement_reclaim,
            ),
            SpecialistFamilySpec(
                key="mss_choch_soft_reclaim",
                regime_hint="transition",
                max_hold_bars=8,
                signal_builder=self._signal_mss_choch_soft_reclaim,
            ),
            SpecialistFamilySpec(
                key="judas_swing_reversal",
                regime_hint="session_open",
                max_hold_bars=8,
                signal_builder=self._signal_judas_swing_reversal,
            ),
            SpecialistFamilySpec(
                key="turtle_soup_failed_breakout",
                regime_hint="range",
                max_hold_bars=8,
                signal_builder=self._signal_turtle_soup_failed_breakout,
            ),
            SpecialistFamilySpec(
                key="orb_breakout",
                regime_hint="session_open",
                max_hold_bars=12,
                signal_builder=self._signal_orb_breakout,
            ),
            SpecialistFamilySpec(
                key="orb_breakout_v2",
                regime_hint="session_open",
                max_hold_bars=10,
                signal_builder=self._signal_orb_breakout_v2,
            ),
            SpecialistFamilySpec(
                key="session_auction_reclaim",
                regime_hint="session_open",
                max_hold_bars=10,
                signal_builder=self._signal_session_auction_reclaim,
            ),
            SpecialistFamilySpec(
                key="session_auction_reclaim_v2",
                regime_hint="session_open",
                max_hold_bars=8,
                signal_builder=self._signal_session_auction_reclaim_v2,
            ),
            SpecialistFamilySpec(
                key="volatility_expansion",
                regime_hint="volatility_expansion",
                max_hold_bars=8,
                signal_builder=self._signal_volatility_expansion,
            ),
            SpecialistFamilySpec(
                key="range_rotation",
                regime_hint="range",
                max_hold_bars=12,
                signal_builder=self._signal_range_rotation,
            ),
            SpecialistFamilySpec(
                key="liquidity_run_continuation",
                regime_hint="trend",
                max_hold_bars=8,
                signal_builder=self._signal_liquidity_run_continuation,
            ),
            SpecialistFamilySpec(
                key="event_shock_imbalance",
                regime_hint="event_shock",
                max_hold_bars=4,
                signal_builder=self._signal_event_shock_imbalance,
            ),
            SpecialistFamilySpec(
                key="vwap_deviation_reversion",
                regime_hint="intraday_reversion",
                max_hold_bars=8,
                signal_builder=self._signal_vwap_deviation_reversion,
            ),
            SpecialistFamilySpec(
                key="volume_displacement_continuation",
                regime_hint="trend",
                max_hold_bars=8,
                signal_builder=self._signal_volume_displacement_continuation,
            ),
            SpecialistFamilySpec(
                key="ict_mss_displacement_fvg_reclaim",
                regime_hint="transition",
                max_hold_bars=10,
                signal_builder=self._signal_ict_mss_displacement_fvg_reclaim,
            ),
        )

    def family_specs(self) -> tuple[SpecialistFamilySpec, ...]:
        return self._family_specs

    def backtest_family(self, family_key: str) -> list[ResearchTrade]:
        spec = next(item for item in self._family_specs if item.key == family_key)
        trades: list[ResearchTrade] = []
        idx = 60
        while idx < len(self.candles) - 2:
            signal = spec.signal_builder(idx)
            if signal is None:
                idx += 1
                continue
            trade = self._simulate_trade(signal)
            if trade is None:
                idx += 1
                continue
            trades.append(trade)
            idx = max(signal.entry_index + trade.hold_bars, idx + 1)
        return trades

    def backtest_all(self) -> dict[str, list[ResearchTrade]]:
        return {spec.key: self.backtest_family(spec.key) for spec in self._family_specs}

    def _simulate_trade(self, signal: ResearchSignal) -> ResearchTrade | None:
        if signal.entry_index >= len(self.candles):
            return None
        risk_abs = abs(float(signal.entry_price) - float(signal.stop_price))
        if risk_abs <= 1e-9:
            return None
        exit_idx = min(signal.entry_index + signal.max_hold_bars, len(self.candles) - 1)
        exit_price = self.closes[exit_idx]
        exit_reason = "time_exit"

        for idx in range(signal.entry_index, min(signal.entry_index + signal.max_hold_bars + 1, len(self.candles))):
            hit_target = False
            hit_stop = False
            if signal.direction == "long":
                hit_target = self.highs[idx] >= signal.target_price
                hit_stop = self.lows[idx] <= signal.stop_price
            else:
                hit_target = self.lows[idx] <= signal.target_price
                hit_stop = self.highs[idx] >= signal.stop_price

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

        gross_r = (
            (exit_price - signal.entry_price) / risk_abs
            if signal.direction == "long"
            else (signal.entry_price - exit_price) / risk_abs
        )
        cost_abs = float(signal.entry_price) * self._FEE_RATE_ROUND_TRIP
        cost_r = cost_abs / risk_abs
        r_value = float(gross_r - cost_r)
        return ResearchTrade(
            family=signal.family,
            symbol=self.symbol,
            direction=signal.direction,
            signal_ts=self.ts[signal.signal_index],
            entry_ts=self.ts[signal.entry_index],
            exit_ts=self.ts[exit_idx],
            entry_price=float(signal.entry_price),
            exit_price=float(exit_price),
            stop_price=float(signal.stop_price),
            target_price=float(signal.target_price),
            r_value=r_value,
            gross_r=float(gross_r),
            cost_r=float(cost_r),
            hold_bars=max(exit_idx - signal.entry_index + 1, 1),
            exit_reason=exit_reason,
            regime_hint=signal.regime_hint,
        )

    def _signal_trend_continuation_pullback(self, idx: int) -> ResearchSignal | None:
        atr = max(self.atr[idx], 1e-9)
        entry_idx = idx + 1
        if self._in_uptrend(idx):
            recent_pullback_low = self._rolling_low(idx - 6, idx)
            pullback_depth = self.closes[idx] - recent_pullback_low
            breakout_level = self._rolling_high(idx - 3, idx)
            if (
                recent_pullback_low <= self.ema_fast[idx]
                and recent_pullback_low >= self.ema_slow[idx]
                and 0.35 * atr <= pullback_depth <= 1.2 * atr
                and self.closes[idx] > breakout_level
            ):
                entry = self.opens[entry_idx]
                stop = recent_pullback_low - 0.15 * atr
                if entry > stop:
                    return ResearchSignal(
                        family="trend_continuation_pullback",
                        direction="long",
                        signal_index=idx,
                        entry_index=entry_idx,
                        entry_price=entry,
                        stop_price=stop,
                        target_price=entry + 2.0 * (entry - stop),
                        max_hold_bars=12,
                        regime_hint="trend",
                    )
        if self._in_downtrend(idx):
            recent_pullback_high = self._rolling_high(idx - 6, idx)
            pullback_depth = recent_pullback_high - self.closes[idx]
            breakout_level = self._rolling_low(idx - 3, idx)
            if (
                recent_pullback_high >= self.ema_fast[idx]
                and recent_pullback_high <= self.ema_slow[idx]
                and 0.35 * atr <= pullback_depth <= 1.2 * atr
                and self.closes[idx] < breakout_level
            ):
                entry = self.opens[entry_idx]
                stop = recent_pullback_high + 0.15 * atr
                if entry < stop:
                    return ResearchSignal(
                        family="trend_continuation_pullback",
                        direction="short",
                        signal_index=idx,
                        entry_index=entry_idx,
                        entry_price=entry,
                        stop_price=stop,
                        target_price=entry - 2.0 * (stop - entry),
                        max_hold_bars=12,
                        regime_hint="trend",
                    )
        return None

    def _signal_choch_displacement_reclaim(self, idx: int) -> ResearchSignal | None:
        atr = max(self.atr[idx], 1e-9)
        entry_idx = idx + 1
        if idx < 12:
            return None
        breakout_high = self._rolling_high(idx - 8, idx)
        breakout_low = self._rolling_low(idx - 8, idx)
        if (
            self._in_downtrend(idx - 2)
            and self._body_size(idx) >= 1.2 * atr
            and self.closes[idx] > breakout_high
            and self._close_position_in_bar(idx) >= 0.65
        ):
            entry = self.opens[entry_idx]
            stop = self.lows[idx] - 0.1 * atr
            if entry > stop:
                return ResearchSignal(
                    family="choch_displacement_reclaim",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry + 2.4 * (entry - stop),
                    max_hold_bars=10,
                    regime_hint="transition",
                )
        if (
            self._in_uptrend(idx - 2)
            and self._body_size(idx) >= 1.2 * atr
            and self.closes[idx] < breakout_low
            and self._close_position_in_bar(idx) <= 0.35
        ):
            entry = self.opens[entry_idx]
            stop = self.highs[idx] + 0.1 * atr
            if entry < stop:
                return ResearchSignal(
                    family="choch_displacement_reclaim",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - 2.4 * (stop - entry),
                    max_hold_bars=10,
                    regime_hint="transition",
                )
        return None

    def _signal_mss_choch_soft_reclaim(self, idx: int) -> ResearchSignal | None:
        if idx < 14:
            return None
        signal_idx = idx - 1
        atr = max(self.atr[signal_idx], 1e-9)
        entry_idx = idx + 1
        prior_high = self._rolling_high(signal_idx - 8, signal_idx)
        prior_low = self._rolling_low(signal_idx - 8, signal_idx)
        reclaimed_mid = (self.highs[signal_idx] + self.lows[signal_idx]) / 2.0

        long_setup = (
            self._in_downtrend(signal_idx - 2)
            and self.closes[signal_idx] > prior_high + 0.05 * atr
            and self._body_size(signal_idx) >= 0.75 * atr
            and self.closes[idx] >= prior_high
            and self.lows[idx] >= prior_high - 0.30 * atr
            and self.closes[idx] >= reclaimed_mid
        )
        if long_setup:
            entry = self.opens[entry_idx]
            stop = min(self.lows[idx], self.lows[signal_idx]) - 0.10 * atr
            risk_abs = entry - stop
            if 0.25 * atr <= risk_abs <= 1.4 * atr:
                return ResearchSignal(
                    family="mss_choch_soft_reclaim",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry + 2.0 * risk_abs,
                    max_hold_bars=8,
                    regime_hint="transition",
                )

        short_setup = (
            self._in_uptrend(signal_idx - 2)
            and self.closes[signal_idx] < prior_low - 0.05 * atr
            and self._body_size(signal_idx) >= 0.75 * atr
            and self.closes[idx] <= prior_low
            and self.highs[idx] <= prior_low + 0.30 * atr
            and self.closes[idx] <= reclaimed_mid
        )
        if short_setup:
            entry = self.opens[entry_idx]
            stop = max(self.highs[idx], self.highs[signal_idx]) + 0.10 * atr
            risk_abs = stop - entry
            if 0.25 * atr <= risk_abs <= 1.4 * atr:
                return ResearchSignal(
                    family="mss_choch_soft_reclaim",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - 2.0 * risk_abs,
                    max_hold_bars=8,
                    regime_hint="transition",
                )
        return None

    def _signal_judas_swing_reversal(self, idx: int) -> ResearchSignal | None:
        ts = self.ts[idx]
        # Use early-session raid window only.
        if ts.hour < 6 or ts.hour > 11:
            return None
        day_start = self._day_start_index(idx)
        if idx - day_start < 8:
            return None
        atr = max(self.atr[idx], 1e-9)
        session_high = self._rolling_high(day_start, idx)
        session_low = self._rolling_low(day_start, idx)
        session_mid = (session_high + session_low) / 2.0
        entry_idx = idx + 1

        sweep_high = self.highs[idx] > session_high - 0.05 * atr
        bearish_reclaim = self.closes[idx] < session_high - 0.10 * atr and self._close_position_in_bar(idx) <= 0.35
        if sweep_high and bearish_reclaim:
            entry = self.opens[entry_idx]
            stop = self.highs[idx] + 0.10 * atr
            risk_abs = stop - entry
            target = max(session_mid, entry - 1.8 * max(risk_abs, 1e-9))
            if 0.25 * atr <= risk_abs <= 1.4 * atr and target < entry:
                return ResearchSignal(
                    family="judas_swing_reversal",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=target,
                    max_hold_bars=8,
                    regime_hint="session_open",
                )

        sweep_low = self.lows[idx] < session_low + 0.05 * atr
        bullish_reclaim = self.closes[idx] > session_low + 0.10 * atr and self._close_position_in_bar(idx) >= 0.65
        if sweep_low and bullish_reclaim:
            entry = self.opens[entry_idx]
            stop = self.lows[idx] - 0.10 * atr
            risk_abs = entry - stop
            target = min(session_mid, entry + 1.8 * max(risk_abs, 1e-9))
            if 0.25 * atr <= risk_abs <= 1.4 * atr and target > entry:
                return ResearchSignal(
                    family="judas_swing_reversal",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=target,
                    max_hold_bars=8,
                    regime_hint="session_open",
                )
        return None

    def _signal_turtle_soup_failed_breakout(self, idx: int) -> ResearchSignal | None:
        if idx < 24:
            return None
        atr = max(self.atr[idx], 1e-9)
        range_high = self._rolling_high(idx - 20, idx)
        range_low = self._rolling_low(idx - 20, idx)
        range_width = range_high - range_low
        if range_width <= 2.5 * atr or range_width >= 8.0 * atr:
            return None
        if abs(self.ema_fast[idx] - self.ema_slow[idx]) / atr >= 0.55:
            return None

        entry_idx = idx + 1
        midpoint = (range_high + range_low) / 2.0

        failed_high_break = (
            self.highs[idx] > range_high + 0.08 * atr
            and self.closes[idx] < range_high - 0.03 * atr
            and self._close_position_in_bar(idx) <= 0.40
            and self._body_size(idx) >= 0.35 * atr
        )
        if failed_high_break:
            entry = self.opens[entry_idx]
            stop = self.highs[idx] + 0.10 * atr
            risk_abs = stop - entry
            target = max(midpoint, entry - 1.8 * max(risk_abs, 1e-9))
            if 0.20 * atr <= risk_abs <= 1.5 * atr and target < entry:
                return ResearchSignal(
                    family="turtle_soup_failed_breakout",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=target,
                    max_hold_bars=8,
                    regime_hint="range",
                )

        failed_low_break = (
            self.lows[idx] < range_low - 0.08 * atr
            and self.closes[idx] > range_low + 0.03 * atr
            and self._close_position_in_bar(idx) >= 0.60
            and self._body_size(idx) >= 0.35 * atr
        )
        if failed_low_break:
            entry = self.opens[entry_idx]
            stop = self.lows[idx] - 0.10 * atr
            risk_abs = entry - stop
            target = min(midpoint, entry + 1.8 * max(risk_abs, 1e-9))
            if 0.20 * atr <= risk_abs <= 1.5 * atr and target > entry:
                return ResearchSignal(
                    family="turtle_soup_failed_breakout",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=target,
                    max_hold_bars=8,
                    regime_hint="range",
                )
        return None

    def _signal_orb_breakout(self, idx: int) -> ResearchSignal | None:
        ts = self.ts[idx]
        if ts.hour < 1 or (ts.hour == 1 and ts.minute == 0):
            return None
        day_start = self._day_start_index(idx)
        first_window_end = min(day_start + 4, len(self.candles))
        if idx < first_window_end:
            return None
        orb_high = self._rolling_high(day_start, first_window_end)
        orb_low = self._rolling_low(day_start, first_window_end)
        orb_width = orb_high - orb_low
        atr = max(self.atr[idx], 1e-9)
        if orb_width <= 0.6 * atr or orb_width >= 3.0 * atr:
            return None
        entry_idx = idx + 1
        if self.closes[idx] > orb_high and self.closes[idx - 1] <= orb_high:
            entry = self.opens[entry_idx]
            stop = orb_low
            if entry > stop:
                return ResearchSignal(
                    family="orb_breakout",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry + 1.8 * (entry - stop),
                    max_hold_bars=12,
                    regime_hint="session_open",
                )
        if self.closes[idx] < orb_low and self.closes[idx - 1] >= orb_low:
            entry = self.opens[entry_idx]
            stop = orb_high
            if entry < stop:
                return ResearchSignal(
                    family="orb_breakout",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - 1.8 * (stop - entry),
                    max_hold_bars=12,
                    regime_hint="session_open",
                )
        return None

    def _signal_orb_breakout_v2(self, idx: int) -> ResearchSignal | None:
        day_start = self._day_start_index(idx)
        offset = idx - day_start
        if offset < 5 or offset > 20:
            return None
        orb_end = min(day_start + 4, len(self.candles))
        if idx <= orb_end + 1:
            return None
        orb_high = self._rolling_high(day_start, orb_end)
        orb_low = self._rolling_low(day_start, orb_end)
        atr = max(self.atr[idx], 1e-9)
        orb_width = orb_high - orb_low
        if orb_width <= 0.8 * atr or orb_width >= 2.2 * atr:
            return None

        breakout_idx: int | None = None
        breakout_dir: Direction | None = None
        for probe in range(orb_end, idx):
            probe_atr = max(self.atr[probe], 1e-9)
            probe_volume_med = self._volume_median(probe - 12, probe)
            bullish_break = (
                self.closes[probe] > orb_high + 0.12 * probe_atr
                and self._body_size(probe) >= 0.70 * probe_atr
                and self._close_position_in_bar(probe) >= 0.65
                and self.volumes[probe] >= max(probe_volume_med * 1.15, 1e-9)
            )
            bearish_break = (
                self.closes[probe] < orb_low - 0.12 * probe_atr
                and self._body_size(probe) >= 0.70 * probe_atr
                and self._close_position_in_bar(probe) <= 0.35
                and self.volumes[probe] >= max(probe_volume_med * 1.15, 1e-9)
            )
            if bullish_break:
                breakout_idx = probe
                breakout_dir = "long"
                break
            if bearish_break:
                breakout_idx = probe
                breakout_dir = "short"
                break
        if breakout_idx is None or breakout_dir is None:
            return None
        if idx <= breakout_idx:
            return None
        # Only allow the first clean retest after the opening break.
        if breakout_dir == "long":
            retest_ok = (
                self.lows[idx] <= orb_high + 0.10 * atr
                and self.lows[idx] >= orb_high - 0.35 * atr
                and self.closes[idx] > orb_high
                and self._close_position_in_bar(idx) >= 0.55
            )
            if not retest_ok:
                return None
            entry_idx = idx + 1
            entry = self.opens[entry_idx]
            stop = min(self.lows[idx], orb_low) - 0.10 * atr
            risk_abs = entry - stop
            if risk_abs <= 0.35 * atr or risk_abs >= 1.8 * atr:
                return None
            return ResearchSignal(
                family="orb_breakout_v2",
                direction="long",
                signal_index=idx,
                entry_index=entry_idx,
                entry_price=entry,
                stop_price=stop,
                target_price=entry + 2.0 * risk_abs,
                max_hold_bars=10,
                regime_hint="session_open",
            )
        retest_ok = (
            self.highs[idx] >= orb_low - 0.10 * atr
            and self.highs[idx] <= orb_low + 0.35 * atr
            and self.closes[idx] < orb_low
            and self._close_position_in_bar(idx) <= 0.45
        )
        if not retest_ok:
            return None
        entry_idx = idx + 1
        entry = self.opens[entry_idx]
        stop = max(self.highs[idx], orb_high) + 0.10 * atr
        risk_abs = stop - entry
        if risk_abs <= 0.35 * atr or risk_abs >= 1.8 * atr:
            return None
        return ResearchSignal(
            family="orb_breakout_v2",
            direction="short",
            signal_index=idx,
            entry_index=entry_idx,
            entry_price=entry,
            stop_price=stop,
            target_price=entry - 2.0 * risk_abs,
            max_hold_bars=10,
            regime_hint="session_open",
        )

    def _signal_session_auction_reclaim(self, idx: int) -> ResearchSignal | None:
        day_start = self._day_start_index(idx)
        offset = idx - day_start
        if offset < 5 or offset > 26:
            return None
        orb_end = min(day_start + 4, len(self.candles))
        if idx <= orb_end:
            return None

        atr = max(self.atr[idx], 1e-9)
        orb_high = self._rolling_high(day_start, orb_end)
        orb_low = self._rolling_low(day_start, orb_end)
        orb_width = orb_high - orb_low
        if orb_width <= 0.7 * atr or orb_width >= 3.5 * atr:
            return None

        vwap = self.session_vwap[idx]
        if vwap <= 0.0:
            return None
        volume_med = self._volume_median(idx - 16, idx)
        entry_idx = idx + 1
        drive_high = self._rolling_high(orb_end, idx)
        drive_low = self._rolling_low(orb_end, idx)

        long_reclaim_level = max(orb_high, vwap)
        long_setup = (
            self.ema_fast[idx] > self.ema_slow[idx]
            and drive_high >= orb_high + 0.45 * atr
            and self.lows[idx] <= long_reclaim_level + 0.15 * atr
            and self.lows[idx] >= long_reclaim_level - 0.45 * atr
            and self.closes[idx] >= long_reclaim_level + 0.08 * atr
            and self._close_position_in_bar(idx) >= 0.58
            and self.closes[idx] > self.opens[idx]
            and self.closes[idx] >= self.ema_fast[idx] - 0.10 * atr
            and self.volumes[idx] >= max(volume_med * 0.90, 1e-9)
        )
        if long_setup:
            entry = self.opens[entry_idx]
            stop = min(self.lows[idx], long_reclaim_level) - 0.15 * atr
            risk_abs = entry - stop
            if 0.25 * atr <= risk_abs <= 1.6 * atr:
                return ResearchSignal(
                    family="session_auction_reclaim",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry + 2.2 * risk_abs,
                    max_hold_bars=10,
                    regime_hint="session_open",
                )

        short_reclaim_level = min(orb_low, vwap)
        short_setup = (
            self.ema_fast[idx] < self.ema_slow[idx]
            and drive_low <= orb_low - 0.45 * atr
            and self.highs[idx] >= short_reclaim_level - 0.15 * atr
            and self.highs[idx] <= short_reclaim_level + 0.45 * atr
            and self.closes[idx] <= short_reclaim_level - 0.08 * atr
            and self._close_position_in_bar(idx) <= 0.42
            and self.closes[idx] < self.opens[idx]
            and self.closes[idx] <= self.ema_fast[idx] + 0.10 * atr
            and self.volumes[idx] >= max(volume_med * 0.90, 1e-9)
        )
        if short_setup:
            entry = self.opens[entry_idx]
            stop = max(self.highs[idx], short_reclaim_level) + 0.15 * atr
            risk_abs = stop - entry
            if 0.25 * atr <= risk_abs <= 1.6 * atr:
                return ResearchSignal(
                    family="session_auction_reclaim",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - 2.2 * risk_abs,
                    max_hold_bars=10,
                    regime_hint="session_open",
                )
        return None

    def _signal_session_auction_reclaim_v2(self, idx: int) -> ResearchSignal | None:
        session_anchor = self._session_anchor_index(idx, allowed_hours=(6, 13))
        if session_anchor is None:
            return None
        offset = idx - session_anchor
        if offset < 5 or offset > 18:
            return None

        orb_end = min(session_anchor + 4, len(self.candles))
        if idx <= orb_end:
            return None

        atr = max(self.atr[idx], 1e-9)
        trend_strength = abs(self.ema_fast[idx] - self.ema_slow[idx]) / atr
        if trend_strength < 0.40:
            return None

        orb_high = self._rolling_high(session_anchor, orb_end)
        orb_low = self._rolling_low(session_anchor, orb_end)
        orb_width = orb_high - orb_low
        if orb_width <= 0.8 * atr or orb_width >= 2.5 * atr:
            return None

        vwap = self.session_vwap[idx]
        if vwap <= 0.0:
            return None
        volume_med = self._volume_median(idx - 16, idx)
        drive_high = self._rolling_high(orb_end, idx)
        drive_low = self._rolling_low(orb_end, idx)
        entry_idx = idx + 1

        reclaim_long_level = max(orb_high, vwap)
        breakout_confirmed_long = any(
            self.closes[probe] > orb_high + 0.15 * max(self.atr[probe], 1e-9)
            and self._body_size(probe) >= 0.60 * max(self.atr[probe], 1e-9)
            and self._close_position_in_bar(probe) >= 0.65
            and self.volumes[probe] >= max(self._volume_median(probe - 12, probe) * 1.10, 1e-9)
            for probe in range(orb_end, idx)
        )
        long_setup = (
            self.ema_fast[idx] > self.ema_slow[idx]
            and drive_high >= orb_high + 0.60 * atr
            and breakout_confirmed_long
            and self.lows[idx] <= reclaim_long_level + 0.08 * atr
            and self.lows[idx] >= reclaim_long_level - 0.28 * atr
            and self.closes[idx] >= reclaim_long_level + 0.12 * atr
            and self.closes[idx] > self.opens[idx]
            and self._body_size(idx) >= 0.35 * atr
            and self._close_position_in_bar(idx) >= 0.62
            and self.volumes[idx] >= max(volume_med * 1.05, 1e-9)
        )
        if long_setup:
            entry = self.opens[entry_idx]
            stop = min(self.lows[idx], reclaim_long_level) - 0.12 * atr
            risk_abs = entry - stop
            if 0.20 * atr <= risk_abs <= 1.20 * atr:
                return ResearchSignal(
                    family="session_auction_reclaim_v2",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry + 1.8 * risk_abs,
                    max_hold_bars=8,
                    regime_hint="session_open",
                )

        reclaim_short_level = min(orb_low, vwap)
        breakout_confirmed_short = any(
            self.closes[probe] < orb_low - 0.15 * max(self.atr[probe], 1e-9)
            and self._body_size(probe) >= 0.60 * max(self.atr[probe], 1e-9)
            and self._close_position_in_bar(probe) <= 0.35
            and self.volumes[probe] >= max(self._volume_median(probe - 12, probe) * 1.10, 1e-9)
            for probe in range(orb_end, idx)
        )
        short_setup = (
            self.ema_fast[idx] < self.ema_slow[idx]
            and drive_low <= orb_low - 0.60 * atr
            and breakout_confirmed_short
            and self.highs[idx] >= reclaim_short_level - 0.08 * atr
            and self.highs[idx] <= reclaim_short_level + 0.28 * atr
            and self.closes[idx] <= reclaim_short_level - 0.12 * atr
            and self.closes[idx] < self.opens[idx]
            and self._body_size(idx) >= 0.35 * atr
            and self._close_position_in_bar(idx) <= 0.38
            and self.volumes[idx] >= max(volume_med * 1.05, 1e-9)
        )
        if short_setup:
            entry = self.opens[entry_idx]
            stop = max(self.highs[idx], reclaim_short_level) + 0.12 * atr
            risk_abs = stop - entry
            if 0.20 * atr <= risk_abs <= 1.20 * atr:
                return ResearchSignal(
                    family="session_auction_reclaim_v2",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - 1.8 * risk_abs,
                    max_hold_bars=8,
                    regime_hint="session_open",
                )
        return None

    def _signal_volatility_expansion(self, idx: int) -> ResearchSignal | None:
        if idx < 20:
            return None
        atr = max(self.atr[idx], 1e-9)
        prev_atr_median = median(self.atr[max(0, idx - 20):idx])
        prev_range_high = self._rolling_high(idx - 12, idx)
        prev_range_low = self._rolling_low(idx - 12, idx)
        prev_range_width = prev_range_high - prev_range_low
        entry_idx = idx + 1
        if (
            prev_atr_median > 0.0
            and self.atr[idx] >= prev_atr_median * 1.35
            and prev_range_width <= max(atr * 3.2, 1e-9)
            and self.closes[idx] > prev_range_high
            and self._close_position_in_bar(idx) >= 0.65
        ):
            entry = self.opens[entry_idx]
            stop = self.lows[idx] - 0.1 * atr
            if entry > stop:
                return ResearchSignal(
                    family="volatility_expansion",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry + 2.3 * (entry - stop),
                    max_hold_bars=8,
                    regime_hint="volatility_expansion",
                )
        if (
            prev_atr_median > 0.0
            and self.atr[idx] >= prev_atr_median * 1.35
            and prev_range_width <= max(atr * 3.2, 1e-9)
            and self.closes[idx] < prev_range_low
            and self._close_position_in_bar(idx) <= 0.35
        ):
            entry = self.opens[entry_idx]
            stop = self.highs[idx] + 0.1 * atr
            if entry < stop:
                return ResearchSignal(
                    family="volatility_expansion",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - 2.3 * (stop - entry),
                    max_hold_bars=8,
                    regime_hint="volatility_expansion",
                )
        return None

    def _signal_range_rotation(self, idx: int) -> ResearchSignal | None:
        if idx < 24 or not self._range_like(idx):
            return None
        atr = max(self.atr[idx], 1e-9)
        range_high = self._rolling_high(idx - 24, idx)
        range_low = self._rolling_low(idx - 24, idx)
        entry_idx = idx + 1
        if self.lows[idx] < range_low and self.closes[idx] > range_low:
            entry = self.opens[entry_idx]
            stop = self.lows[idx] - 0.1 * atr
            target = min(range_high, entry + 2.0 * max(entry - stop, 1e-9))
            if entry > stop and target > entry:
                return ResearchSignal(
                    family="range_rotation",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=target,
                    max_hold_bars=12,
                    regime_hint="range",
                )
        if self.highs[idx] > range_high and self.closes[idx] < range_high:
            entry = self.opens[entry_idx]
            stop = self.highs[idx] + 0.1 * atr
            target = max(range_low, entry - 2.0 * max(stop - entry, 1e-9))
            if entry < stop and target < entry:
                return ResearchSignal(
                    family="range_rotation",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=target,
                    max_hold_bars=12,
                    regime_hint="range",
                )
        return None

    def _signal_liquidity_run_continuation(self, idx: int) -> ResearchSignal | None:
        if idx < 12:
            return None
        atr = max(self.atr[idx], 1e-9)
        entry_idx = idx + 1
        pullback_low = self._rolling_low(idx - 10, idx)
        pullback_high = self._rolling_high(idx - 10, idx)
        if (
            self._in_uptrend(idx)
            and self.lows[idx] < pullback_low
            and self.closes[idx] > self.ema_fast[idx]
            and self._close_position_in_bar(idx) >= 0.55
        ):
            entry = self.opens[entry_idx]
            stop = self.lows[idx] - 0.1 * atr
            if entry > stop:
                return ResearchSignal(
                    family="liquidity_run_continuation",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry + 2.0 * (entry - stop),
                    max_hold_bars=8,
                    regime_hint="trend",
                )
        if (
            self._in_downtrend(idx)
            and self.highs[idx] > pullback_high
            and self.closes[idx] < self.ema_fast[idx]
            and self._close_position_in_bar(idx) <= 0.45
        ):
            entry = self.opens[entry_idx]
            stop = self.highs[idx] + 0.1 * atr
            if entry < stop:
                return ResearchSignal(
                    family="liquidity_run_continuation",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - 2.0 * (stop - entry),
                    max_hold_bars=8,
                    regime_hint="trend",
                )
        return None

    def _signal_event_shock_imbalance(self, idx: int) -> ResearchSignal | None:
        if idx < 22:
            return None
        atr = max(self.atr[idx - 1], 1e-9)
        vol_median = self._volume_median(idx - 20, idx)
        shock_range = self._bar_range(idx - 1)
        shock_close_pos = self._close_position_in_bar(idx - 1)
        entry_idx = idx + 1
        if (
            shock_range >= 2.4 * atr
            and self.volumes[idx - 1] >= max(vol_median * 1.8, 1e-9)
            and shock_close_pos >= 0.8
            and self.closes[idx] >= (self.highs[idx - 1] + self.lows[idx - 1]) / 2.0
        ):
            entry = self.opens[entry_idx]
            stop = (self.highs[idx - 1] + self.lows[idx - 1]) / 2.0
            if entry > stop:
                return ResearchSignal(
                    family="event_shock_imbalance",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry + 1.8 * (entry - stop),
                    max_hold_bars=4,
                    regime_hint="event_shock",
                )
        if (
            shock_range >= 2.4 * atr
            and self.volumes[idx - 1] >= max(vol_median * 1.8, 1e-9)
            and shock_close_pos <= 0.2
            and self.closes[idx] <= (self.highs[idx - 1] + self.lows[idx - 1]) / 2.0
        ):
            entry = self.opens[entry_idx]
            stop = (self.highs[idx - 1] + self.lows[idx - 1]) / 2.0
            if entry < stop:
                return ResearchSignal(
                    family="event_shock_imbalance",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - 1.8 * (stop - entry),
                    max_hold_bars=4,
                    regime_hint="event_shock",
                )
        return None

    def _signal_vwap_deviation_reversion(self, idx: int) -> ResearchSignal | None:
        if idx < 24:
            return None
        ts = self.ts[idx]
        # Skip very early bars so session VWAP has formed.
        if ts.hour < 2:
            return None
        atr = max(self.atr[idx], 1e-9)
        vwap = self.session_vwap[idx]
        if vwap <= 0.0:
            return None
        deviation = self.closes[idx] - vwap
        volume_med = self._volume_median(idx - 16, idx)
        entry_idx = idx + 1

        long_setup = (
            deviation <= -1.4 * atr
            and self.lows[idx] <= vwap - 1.8 * atr
            and self._close_position_in_bar(idx) >= 0.62
            and self._body_size(idx) >= 0.30 * atr
            and self.volumes[idx] >= max(volume_med * 1.1, 1e-9)
            and self.closes[idx] > self.opens[idx]
        )
        if long_setup:
            entry = self.opens[entry_idx]
            stop = self.lows[idx] - 0.10 * atr
            risk_abs = entry - stop
            target = min(vwap, entry + 1.8 * max(risk_abs, 1e-9))
            if 0.20 * atr <= risk_abs <= 1.4 * atr and target > entry:
                return ResearchSignal(
                    family="vwap_deviation_reversion",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=target,
                    max_hold_bars=8,
                    regime_hint="intraday_reversion",
                )

        short_setup = (
            deviation >= 1.4 * atr
            and self.highs[idx] >= vwap + 1.8 * atr
            and self._close_position_in_bar(idx) <= 0.38
            and self._body_size(idx) >= 0.30 * atr
            and self.volumes[idx] >= max(volume_med * 1.1, 1e-9)
            and self.closes[idx] < self.opens[idx]
        )
        if short_setup:
            entry = self.opens[entry_idx]
            stop = self.highs[idx] + 0.10 * atr
            risk_abs = stop - entry
            target = max(vwap, entry - 1.8 * max(risk_abs, 1e-9))
            if 0.20 * atr <= risk_abs <= 1.4 * atr and target < entry:
                return ResearchSignal(
                    family="vwap_deviation_reversion",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=target,
                    max_hold_bars=8,
                    regime_hint="intraday_reversion",
                )
        return None

    def _signal_volume_displacement_continuation(self, idx: int) -> ResearchSignal | None:
        if idx < 24:
            return None
        atr = max(self.atr[idx], 1e-9)
        volume_med = self._volume_median(idx - 20, idx)
        entry_idx = idx + 1

        long_setup = (
            self._in_uptrend(idx)
            and self._body_size(idx) >= 0.90 * atr
            and self.closes[idx] >= self._rolling_high(idx - 10, idx) + 0.05 * atr
            and self._close_position_in_bar(idx) >= 0.72
            and self.volumes[idx] >= max(volume_med * 1.4, 1e-9)
            and self.opens[idx] >= self.ema_fast[idx] - 0.20 * atr
        )
        if long_setup:
            entry = self.opens[entry_idx]
            stop = min(self.lows[idx], self.ema_fast[idx]) - 0.10 * atr
            risk_abs = entry - stop
            if 0.25 * atr <= risk_abs <= 1.6 * atr:
                return ResearchSignal(
                    family="volume_displacement_continuation",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry + 1.9 * risk_abs,
                    max_hold_bars=8,
                    regime_hint="trend",
                )

        short_setup = (
            self._in_downtrend(idx)
            and self._body_size(idx) >= 0.90 * atr
            and self.closes[idx] <= self._rolling_low(idx - 10, idx) - 0.05 * atr
            and self._close_position_in_bar(idx) <= 0.28
            and self.volumes[idx] >= max(volume_med * 1.4, 1e-9)
            and self.opens[idx] <= self.ema_fast[idx] + 0.20 * atr
        )
        if short_setup:
            entry = self.opens[entry_idx]
            stop = max(self.highs[idx], self.ema_fast[idx]) + 0.10 * atr
            risk_abs = stop - entry
            if 0.25 * atr <= risk_abs <= 1.6 * atr:
                return ResearchSignal(
                    family="volume_displacement_continuation",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - 1.9 * risk_abs,
                    max_hold_bars=8,
                    regime_hint="trend",
                )
        return None

    def _signal_ict_mss_displacement_fvg_reclaim(self, idx: int) -> ResearchSignal | None:
        if idx < 16:
            return None
        disp_idx = idx - 1
        atr = max(self.atr[disp_idx], 1e-9)
        entry_idx = idx + 1

        prior_swing_high = self._rolling_high(disp_idx - 8, disp_idx)
        prior_swing_low = self._rolling_low(disp_idx - 8, disp_idx)

        bullish_fvg_low = self.highs[disp_idx - 2]
        bullish_fvg_high = self.lows[disp_idx]
        has_bullish_fvg = bullish_fvg_high > bullish_fvg_low + 0.05 * atr

        bearish_fvg_high = self.lows[disp_idx - 2]
        bearish_fvg_low = self.highs[disp_idx]
        has_bearish_fvg = bearish_fvg_low < bearish_fvg_high - 0.05 * atr

        long_setup = (
            self._in_downtrend(disp_idx - 1)
            and self._body_size(disp_idx) >= 1.10 * atr
            and self.closes[disp_idx] > prior_swing_high + 0.10 * atr
            and self._close_position_in_bar(disp_idx) >= 0.70
            and has_bullish_fvg
            and self.lows[idx] <= bullish_fvg_high
            and self.closes[idx] >= (bullish_fvg_low + bullish_fvg_high) / 2.0
            and self.closes[idx] > self.opens[idx]
        )
        if long_setup:
            entry = self.opens[entry_idx]
            stop = min(self.lows[idx], bullish_fvg_low) - 0.10 * atr
            risk_abs = entry - stop
            if 0.30 * atr <= risk_abs <= 1.6 * atr:
                return ResearchSignal(
                    family="ict_mss_displacement_fvg_reclaim",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry + 2.4 * risk_abs,
                    max_hold_bars=10,
                    regime_hint="transition",
                )

        short_setup = (
            self._in_uptrend(disp_idx - 1)
            and self._body_size(disp_idx) >= 1.10 * atr
            and self.closes[disp_idx] < prior_swing_low - 0.10 * atr
            and self._close_position_in_bar(disp_idx) <= 0.30
            and has_bearish_fvg
            and self.highs[idx] >= bearish_fvg_low
            and self.closes[idx] <= (bearish_fvg_low + bearish_fvg_high) / 2.0
            and self.closes[idx] < self.opens[idx]
        )
        if short_setup:
            entry = self.opens[entry_idx]
            stop = max(self.highs[idx], bearish_fvg_high) + 0.10 * atr
            risk_abs = stop - entry
            if 0.30 * atr <= risk_abs <= 1.6 * atr:
                return ResearchSignal(
                    family="ict_mss_displacement_fvg_reclaim",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - 2.4 * risk_abs,
                    max_hold_bars=10,
                    regime_hint="transition",
                )
        return None


def summarize_research_trades(trades: list[ResearchTrade]) -> dict[str, float | int | dict[str, int]]:
    if not trades:
        return {
            "closed": 0,
            "ev_r": 0.0,
            "total_r": 0.0,
            "win_rate": 0.0,
            "avg_hold_bars": 0.0,
            "regime_hint_counts": {},
            "exit_reason_counts": {},
        }
    closed = len(trades)
    total_r = float(sum(item.r_value for item in trades))
    ev_r = float(total_r / closed)
    win_rate = float(sum(1 for item in trades if item.r_value > 0.0) / closed)
    avg_hold = float(sum(item.hold_bars for item in trades) / closed)
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
        "avg_hold_bars": round(avg_hold, 2),
        "regime_hint_counts": regime_counts,
        "exit_reason_counts": exit_counts,
    }
