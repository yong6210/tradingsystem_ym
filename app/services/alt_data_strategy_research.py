from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import mean, pstdev
from typing import Callable, Literal

from app.db.models import BasisSnapshot, Candle, CrossAssetBreadthSnapshot, FundingRateSnapshot, LiquidationEvent, MacroEvent, OpenInterestSnapshot

Direction = Literal["long", "short"]


@dataclass(frozen=True, slots=True)
class AltDataResearchSignal:
    family: str
    direction: Direction
    signal_index: int
    entry_index: int
    entry_price: float
    stop_price: float
    target_price: float
    max_hold_bars: int


@dataclass(frozen=True, slots=True)
class AltDataResearchTrade:
    family: str
    symbol: str
    direction: Direction
    signal_ts: datetime
    entry_ts: datetime
    exit_ts: datetime
    r_value: float
    exit_reason: str
    hold_bars: int


@dataclass(frozen=True, slots=True)
class AltDataFamilySpec:
    key: str
    signal_builder: Callable[["AltDataResearchEngine", int], AltDataResearchSignal | None]


class AltDataResearchEngine:
    _FEE_RATE_ROUND_TRIP = 0.0006
    _ATR_LOOKBACK = 14

    def __init__(
        self,
        *,
        symbol: str,
        candles_15m: list[Candle],
        funding_rates: list[FundingRateSnapshot],
        open_interest_rows: list[OpenInterestSnapshot],
        basis_rows: list[BasisSnapshot],
        liquidation_rows: list[LiquidationEvent] | None = None,
        breadth_rows: list[CrossAssetBreadthSnapshot] | None = None,
        macro_events: list[MacroEvent] | None = None,
    ):
        self.symbol = str(symbol).upper()
        self.candles = list(candles_15m)
        self.opens = [float(c.o) for c in self.candles]
        self.highs = [float(c.h) for c in self.candles]
        self.lows = [float(c.l) for c in self.candles]
        self.closes = [float(c.c) for c in self.candles]
        self.ts = [self._utc(c.ts) for c in self.candles]
        self.atr = self._build_atr()

        self.funding_series = self._align_latest(
            [(self._utc(item.ts), float(item.funding_rate)) for item in funding_rates],
            default=0.0,
        )
        self.open_interest_series = self._align_latest(
            [(self._utc(item.ts), float(item.open_interest)) for item in open_interest_rows],
            default=0.0,
        )
        self.basis_series = self._align_latest(
            [(self._utc(item.ts), float(item.basis_bps)) for item in basis_rows],
            default=0.0,
        )
        self.liquidation_notional_series = self._align_liquidations(list(liquidation_rows or []))
        filtered_breadth = [
            item
            for item in list(breadth_rows or [])
            if str(item.leader_symbol).upper() == self.symbol
        ]
        self.breadth_score_series = self._align_latest(
            [(self._utc(item.ts), float(item.breadth_score)) for item in filtered_breadth],
            default=0.0,
        )
        self.breadth_divergence_series = self._align_latest(
            [(self._utc(item.ts), float(item.divergence_bps)) for item in filtered_breadth],
            default=0.0,
        )
        self.macro_event_series = self._align_macro_events(list(macro_events or []))
        self._family_specs = (
            AltDataFamilySpec(
                key="funding_oi_squeeze_reversal",
                signal_builder=self._signal_funding_oi_squeeze_reversal,
            ),
            AltDataFamilySpec(
                key="funding_oi_squeeze_reversal_v2",
                signal_builder=self._signal_funding_oi_squeeze_reversal_v2,
            ),
            AltDataFamilySpec(
                key="basis_dislocation_mean_reversion",
                signal_builder=self._signal_basis_dislocation_mean_reversion,
            ),
            AltDataFamilySpec(
                key="basis_dislocation_mean_reversion_v2",
                signal_builder=self._signal_basis_dislocation_mean_reversion_v2,
            ),
            AltDataFamilySpec(
                key="oi_breakout_confirmation",
                signal_builder=self._signal_oi_breakout_confirmation,
            ),
            AltDataFamilySpec(
                key="oi_breakout_confirmation_v2",
                signal_builder=self._signal_oi_breakout_confirmation_v2,
            ),
            AltDataFamilySpec(
                key="liquidation_cascade_absorption",
                signal_builder=self._signal_liquidation_cascade_absorption,
            ),
            AltDataFamilySpec(
                key="breadth_divergence_rotation",
                signal_builder=self._signal_breadth_divergence_rotation,
            ),
            AltDataFamilySpec(
                key="event_basis_dislocation",
                signal_builder=self._signal_event_basis_dislocation,
            ),
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def family_specs(self) -> tuple[AltDataFamilySpec, ...]:
        return self._family_specs

    def _build_atr(self) -> list[float]:
        if len(self.candles) < 2:
            return [0.0] * len(self.candles)
        out = [0.0]
        prev_close = self.closes[0]
        trs: list[float] = []
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

    def _align_latest(self, rows: list[tuple[datetime, float]], *, default: float) -> list[float]:
        rows = sorted(rows, key=lambda item: item[0])
        out: list[float] = []
        value = float(default)
        pointer = 0
        for ts in self.ts:
            while pointer < len(rows) and rows[pointer][0] <= ts:
                value = float(rows[pointer][1])
                pointer += 1
            out.append(value)
        return out

    def _align_macro_events(self, rows: list[MacroEvent]) -> list[int]:
        event_ts = sorted(self._utc(item.event_ts) for item in rows)
        out = [0] * len(self.ts)
        pointer = 0
        for idx, ts in enumerate(self.ts):
            while pointer < len(event_ts) and event_ts[pointer] < ts - datetime.resolution:
                pointer += 1
            recent = any(abs((ts - evt).total_seconds()) <= 60 * 60 for evt in event_ts[max(0, pointer - 2): pointer + 2])
            out[idx] = 1 if recent else 0
        return out

    def _align_liquidations(self, rows: list[LiquidationEvent]) -> list[float]:
        aggregates: dict[datetime, float] = {}
        for item in rows:
            ts = self._utc(item.ts)
            price = float(item.price or 0.0)
            qty = float(item.qty or 0.0)
            notional = float(item.notional or price * qty)
            sign = -1.0 if str(item.side).upper() == "SELL" else 1.0
            aggregates[ts] = float(aggregates.get(ts, 0.0) + (sign * notional))
        return [float(aggregates.get(ts, 0.0)) for ts in self.ts]

    def _rolling_high(self, start: int, end: int) -> float:
        return float(max(self.highs[max(0, start):max(0, end)]))

    def _rolling_low(self, start: int, end: int) -> float:
        return float(min(self.lows[max(0, start):max(0, end)]))

    def _body_size(self, idx: int) -> float:
        return float(abs(self.closes[idx] - self.opens[idx]))

    def _close_position_in_bar(self, idx: int) -> float:
        rng = max(self.highs[idx] - self.lows[idx], 1e-9)
        return float((self.closes[idx] - self.lows[idx]) / rng)

    def _zscore(self, values: list[float], idx: int, lookback: int) -> float:
        start = max(0, idx - lookback)
        window = values[start:idx]
        if len(window) < max(20, lookback // 3):
            return 0.0
        avg = mean(window)
        std = pstdev(window)
        if std <= 1e-9:
            return 0.0
        return float((values[idx] - avg) / std)

    def _pct_change(self, values: list[float], idx: int, lookback: int) -> float:
        prev_idx = max(idx - lookback, 0)
        prev = float(values[prev_idx])
        current = float(values[idx])
        if abs(prev) <= 1e-9:
            return 0.0
        return float((current - prev) / abs(prev))

    def backtest_family(self, family_key: str) -> list[AltDataResearchTrade]:
        spec = next(item for item in self._family_specs if item.key == family_key)
        trades: list[AltDataResearchTrade] = []
        idx = 120
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

    def _simulate_trade(self, signal: AltDataResearchSignal) -> AltDataResearchTrade | None:
        if signal.entry_index >= len(self.candles):
            return None
        risk_abs = abs(signal.entry_price - signal.stop_price)
        if risk_abs <= 1e-9:
            return None
        exit_idx = min(signal.entry_index + signal.max_hold_bars, len(self.candles) - 1)
        exit_price = self.closes[exit_idx]
        exit_reason = "time_exit"
        for idx in range(signal.entry_index, min(signal.entry_index + signal.max_hold_bars + 1, len(self.candles))):
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
        return AltDataResearchTrade(
            family=signal.family,
            symbol=self.symbol,
            direction=signal.direction,
            signal_ts=self.ts[signal.signal_index],
            entry_ts=self.ts[signal.entry_index],
            exit_ts=self.ts[exit_idx],
            r_value=float(gross_r - cost_r),
            exit_reason=exit_reason,
            hold_bars=max(exit_idx - signal.entry_index + 1, 1),
        )

    def _signal_funding_oi_squeeze_reversal(self, idx: int) -> AltDataResearchSignal | None:
        atr = max(self.atr[idx], 1e-9)
        funding_z = self._zscore(self.funding_series, idx, 96)
        oi_z = self._zscore(self.open_interest_series, idx, 96)
        entry_idx = idx + 1
        if (
            funding_z >= 1.8
            and oi_z >= 1.5
            and self.highs[idx] >= self._rolling_high(idx - 16, idx) - 0.05 * atr
            and self._close_position_in_bar(idx) <= 0.35
            and self._body_size(idx) >= 0.35 * atr
        ):
            entry = self.opens[entry_idx]
            stop = self.highs[idx] + 0.10 * atr
            risk_abs = stop - entry
            if 0.20 * atr <= risk_abs <= 1.5 * atr:
                return AltDataResearchSignal(
                    family="funding_oi_squeeze_reversal",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - 1.8 * risk_abs,
                    max_hold_bars=8,
                )
        if (
            funding_z <= -1.8
            and oi_z >= 1.5
            and self.lows[idx] <= self._rolling_low(idx - 16, idx) + 0.05 * atr
            and self._close_position_in_bar(idx) >= 0.65
            and self._body_size(idx) >= 0.35 * atr
        ):
            entry = self.opens[entry_idx]
            stop = self.lows[idx] - 0.10 * atr
            risk_abs = entry - stop
            if 0.20 * atr <= risk_abs <= 1.5 * atr:
                return AltDataResearchSignal(
                    family="funding_oi_squeeze_reversal",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry + 1.8 * risk_abs,
                    max_hold_bars=8,
                )
        return None

    def _signal_basis_dislocation_mean_reversion(self, idx: int) -> AltDataResearchSignal | None:
        atr = max(self.atr[idx], 1e-9)
        basis_z = self._zscore(self.basis_series, idx, 96)
        entry_idx = idx + 1
        if (
            basis_z >= 2.2
            and self._close_position_in_bar(idx) <= 0.40
            and self._body_size(idx) >= 0.25 * atr
        ):
            entry = self.opens[entry_idx]
            stop = self.highs[idx] + 0.10 * atr
            risk_abs = stop - entry
            if 0.20 * atr <= risk_abs <= 1.5 * atr:
                return AltDataResearchSignal(
                    family="basis_dislocation_mean_reversion",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - 1.6 * risk_abs,
                    max_hold_bars=6,
                )
        if (
            basis_z <= -2.2
            and self._close_position_in_bar(idx) >= 0.60
            and self._body_size(idx) >= 0.25 * atr
        ):
            entry = self.opens[entry_idx]
            stop = self.lows[idx] - 0.10 * atr
            risk_abs = entry - stop
            if 0.20 * atr <= risk_abs <= 1.5 * atr:
                return AltDataResearchSignal(
                    family="basis_dislocation_mean_reversion",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry + 1.6 * risk_abs,
                    max_hold_bars=6,
                )
        return None

    def _signal_funding_oi_squeeze_reversal_v2(self, idx: int) -> AltDataResearchSignal | None:
        if idx < 120:
            return None
        atr = max(self.atr[idx], 1e-9)
        funding = float(self.funding_series[idx])
        oi_change_24h = self._pct_change(self.open_interest_series, idx, 96)
        entry_idx = idx + 1

        short_setup = (
            funding >= 0.00008
            and oi_change_24h >= 0.05
            and self.highs[idx] >= self._rolling_high(idx - 12, idx) - 0.03 * atr
            and self.closes[idx] < self.opens[idx]
            and self._close_position_in_bar(idx) <= 0.42
            and self._body_size(idx) >= 0.25 * atr
        )
        if short_setup:
            entry = self.opens[entry_idx]
            stop = self.highs[idx] + 0.08 * atr
            risk_abs = stop - entry
            if 0.18 * atr <= risk_abs <= 1.4 * atr:
                return AltDataResearchSignal(
                    family="funding_oi_squeeze_reversal_v2",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - 1.6 * risk_abs,
                    max_hold_bars=6,
                )

        long_setup = (
            funding <= -0.00008
            and oi_change_24h >= 0.05
            and self.lows[idx] <= self._rolling_low(idx - 12, idx) + 0.03 * atr
            and self.closes[idx] > self.opens[idx]
            and self._close_position_in_bar(idx) >= 0.58
            and self._body_size(idx) >= 0.25 * atr
        )
        if long_setup:
            entry = self.opens[entry_idx]
            stop = self.lows[idx] - 0.08 * atr
            risk_abs = entry - stop
            if 0.18 * atr <= risk_abs <= 1.4 * atr:
                return AltDataResearchSignal(
                    family="funding_oi_squeeze_reversal_v2",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry + 1.6 * risk_abs,
                    max_hold_bars=6,
                )
        return None

    def _signal_basis_dislocation_mean_reversion_v2(self, idx: int) -> AltDataResearchSignal | None:
        if idx < 120:
            return None
        atr = max(self.atr[idx], 1e-9)
        basis_z = self._zscore(self.basis_series, idx, 192)
        entry_idx = idx + 1
        recent_high = self._rolling_high(idx - 10, idx)
        recent_low = self._rolling_low(idx - 10, idx)

        short_setup = (
            basis_z >= 3.0
            and self.highs[idx] >= recent_high - 0.03 * atr
            and self.closes[idx] < self.opens[idx]
            and self._close_position_in_bar(idx) <= 0.38
            and self._body_size(idx) >= 0.22 * atr
        )
        if short_setup:
            entry = self.opens[entry_idx]
            stop = self.highs[idx] + 0.08 * atr
            risk_abs = stop - entry
            if 0.16 * atr <= risk_abs <= 1.3 * atr:
                return AltDataResearchSignal(
                    family="basis_dislocation_mean_reversion_v2",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - 1.3 * risk_abs,
                    max_hold_bars=4,
                )

        long_setup = (
            basis_z <= -3.0
            and self.lows[idx] <= recent_low + 0.03 * atr
            and self.closes[idx] > self.opens[idx]
            and self._close_position_in_bar(idx) >= 0.62
            and self._body_size(idx) >= 0.22 * atr
        )
        if long_setup:
            entry = self.opens[entry_idx]
            stop = self.lows[idx] - 0.08 * atr
            risk_abs = entry - stop
            if 0.16 * atr <= risk_abs <= 1.3 * atr:
                return AltDataResearchSignal(
                    family="basis_dislocation_mean_reversion_v2",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry + 1.3 * risk_abs,
                    max_hold_bars=4,
                )
        return None

    def _signal_oi_breakout_confirmation(self, idx: int) -> AltDataResearchSignal | None:
        atr = max(self.atr[idx], 1e-9)
        oi_z = self._zscore(self.open_interest_series, idx, 96)
        entry_idx = idx + 1
        if (
            oi_z >= 1.2
            and self.closes[idx] >= self._rolling_high(idx - 12, idx) + 0.05 * atr
            and self._close_position_in_bar(idx) >= 0.70
            and self._body_size(idx) >= 0.45 * atr
        ):
            entry = self.opens[entry_idx]
            stop = min(self.lows[idx], self._rolling_low(idx - 6, idx)) - 0.10 * atr
            risk_abs = entry - stop
            if 0.20 * atr <= risk_abs <= 1.6 * atr:
                return AltDataResearchSignal(
                    family="oi_breakout_confirmation",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry + 1.9 * risk_abs,
                    max_hold_bars=8,
                )
        if (
            oi_z >= 1.2
            and self.closes[idx] <= self._rolling_low(idx - 12, idx) - 0.05 * atr
            and self._close_position_in_bar(idx) <= 0.30
            and self._body_size(idx) >= 0.45 * atr
        ):
            entry = self.opens[entry_idx]
            stop = max(self.highs[idx], self._rolling_high(idx - 6, idx)) + 0.10 * atr
            risk_abs = stop - entry
            if 0.20 * atr <= risk_abs <= 1.6 * atr:
                return AltDataResearchSignal(
                    family="oi_breakout_confirmation",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - 1.9 * risk_abs,
                    max_hold_bars=8,
                )
        return None

    def _signal_oi_breakout_confirmation_v2(self, idx: int) -> AltDataResearchSignal | None:
        if idx < 120:
            return None
        breakout_idx = idx - 1
        atr = max(self.atr[breakout_idx], 1e-9)
        oi_change_4h = self._pct_change(self.open_interest_series, breakout_idx, 16)
        entry_idx = idx + 1

        long_setup = (
            oi_change_4h >= 0.02
            and self.closes[breakout_idx] >= self._rolling_high(breakout_idx - 16, breakout_idx) + 0.04 * atr
            and self._close_position_in_bar(breakout_idx) >= 0.72
            and self._body_size(breakout_idx) >= 0.35 * atr
            and self.lows[idx] >= self.closes[breakout_idx] - 0.45 * atr
            and self.closes[idx] >= self.closes[breakout_idx] - 0.15 * atr
        )
        if long_setup:
            entry = self.opens[entry_idx]
            stop = min(self.lows[idx], self.lows[breakout_idx]) - 0.08 * atr
            risk_abs = entry - stop
            if 0.18 * atr <= risk_abs <= 1.5 * atr:
                return AltDataResearchSignal(
                    family="oi_breakout_confirmation_v2",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry + 1.7 * risk_abs,
                    max_hold_bars=6,
                )

        short_setup = (
            oi_change_4h >= 0.02
            and self.closes[breakout_idx] <= self._rolling_low(breakout_idx - 16, breakout_idx) - 0.04 * atr
            and self._close_position_in_bar(breakout_idx) <= 0.28
            and self._body_size(breakout_idx) >= 0.35 * atr
            and self.highs[idx] <= self.closes[breakout_idx] + 0.45 * atr
            and self.closes[idx] <= self.closes[breakout_idx] + 0.15 * atr
        )
        if short_setup:
            entry = self.opens[entry_idx]
            stop = max(self.highs[idx], self.highs[breakout_idx]) + 0.08 * atr
            risk_abs = stop - entry
            if 0.18 * atr <= risk_abs <= 1.5 * atr:
                return AltDataResearchSignal(
                    family="oi_breakout_confirmation_v2",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - 1.7 * risk_abs,
                    max_hold_bars=6,
                )
        return None

    def _signal_liquidation_cascade_absorption(self, idx: int) -> AltDataResearchSignal | None:
        if idx < 120:
            return None
        atr = max(self.atr[idx], 1e-9)
        liq_z = self._zscore(self.liquidation_notional_series, idx, 192)
        liq_value = float(self.liquidation_notional_series[idx])
        entry_idx = idx + 1
        if entry_idx >= len(self.candles):
            return None

        long_setup = (
            liq_z <= -2.2
            and liq_value < 0.0
            and self.lows[idx] <= self._rolling_low(idx - 12, idx) + 0.03 * atr
            and self._close_position_in_bar(idx) >= 0.68
            and self._body_size(idx) >= 0.25 * atr
        )
        if long_setup:
            entry = self.opens[entry_idx]
            stop = self.lows[idx] - 0.08 * atr
            risk_abs = entry - stop
            if 0.18 * atr <= risk_abs <= 1.4 * atr:
                return AltDataResearchSignal(
                    family="liquidation_cascade_absorption",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry + 1.6 * risk_abs,
                    max_hold_bars=6,
                )

        short_setup = (
            liq_z >= 2.2
            and liq_value > 0.0
            and self.highs[idx] >= self._rolling_high(idx - 12, idx) - 0.03 * atr
            and self._close_position_in_bar(idx) <= 0.32
            and self._body_size(idx) >= 0.25 * atr
        )
        if short_setup:
            entry = self.opens[entry_idx]
            stop = self.highs[idx] + 0.08 * atr
            risk_abs = stop - entry
            if 0.18 * atr <= risk_abs <= 1.4 * atr:
                return AltDataResearchSignal(
                    family="liquidation_cascade_absorption",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - 1.6 * risk_abs,
                    max_hold_bars=6,
                )
        return None

    def _signal_breadth_divergence_rotation(self, idx: int) -> AltDataResearchSignal | None:
        atr = max(self.atr[idx], 1e-9)
        breadth_score = float(self.breadth_score_series[idx])
        divergence_bps = float(self.breadth_divergence_series[idx])
        entry_idx = idx + 1
        if entry_idx >= len(self.candles):
            return None

        if (
            breadth_score >= 1.8
            and divergence_bps >= 12.0
            and self.highs[idx] >= self._rolling_high(idx - 16, idx)
            and self._close_position_in_bar(idx) <= 0.35
            and self._body_size(idx) >= 0.20 * atr
        ):
            entry = self.opens[entry_idx]
            stop = self.highs[idx] + 0.10 * atr
            risk_abs = stop - entry
            if 0.20 * atr <= risk_abs <= 1.5 * atr:
                return AltDataResearchSignal(
                    family="breadth_divergence_rotation",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - (risk_abs * 1.5),
                    max_hold_bars=6,
                )

        if (
            breadth_score <= -1.8
            and divergence_bps <= -12.0
            and self.lows[idx] <= self._rolling_low(idx - 16, idx)
            and self._close_position_in_bar(idx) >= 0.65
            and self._body_size(idx) >= 0.20 * atr
        ):
            entry = self.opens[entry_idx]
            stop = self.lows[idx] - 0.10 * atr
            risk_abs = entry - stop
            if 0.20 * atr <= risk_abs <= 1.5 * atr:
                return AltDataResearchSignal(
                    family="breadth_divergence_rotation",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry + (risk_abs * 1.5),
                    max_hold_bars=6,
                )
        return None

    def _signal_event_basis_dislocation(self, idx: int) -> AltDataResearchSignal | None:
        if idx < 120 or not self.macro_event_series[idx]:
            return None
        entry_idx = idx + 1
        if entry_idx >= len(self.candles):
            return None
        atr = max(self.atr[idx], 1e-9)
        basis_z = self._zscore(self.basis_series, idx, 192)
        funding_z = self._zscore(self.funding_series, idx, 96)

        long_setup = (
            basis_z <= -1.5
            and funding_z <= -0.5
            and self._body_size(idx) >= 0.35 * atr
            and self._close_position_in_bar(idx) >= 0.72
            and self.closes[idx] >= self._rolling_high(idx - 8, idx) + 0.03 * atr
        )
        if long_setup:
            entry = self.opens[entry_idx]
            stop = self.lows[idx] - 0.10 * atr
            risk_abs = entry - stop
            if 0.20 * atr <= risk_abs <= 1.5 * atr:
                return AltDataResearchSignal(
                    family="event_basis_dislocation",
                    direction="long",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry + 1.6 * risk_abs,
                    max_hold_bars=6,
                )

        short_setup = (
            basis_z >= 1.5
            and funding_z >= 0.5
            and self._body_size(idx) >= 0.35 * atr
            and self._close_position_in_bar(idx) <= 0.28
            and self.closes[idx] <= self._rolling_low(idx - 8, idx) - 0.03 * atr
        )
        if short_setup:
            entry = self.opens[entry_idx]
            stop = self.highs[idx] + 0.10 * atr
            risk_abs = stop - entry
            if 0.20 * atr <= risk_abs <= 1.5 * atr:
                return AltDataResearchSignal(
                    family="event_basis_dislocation",
                    direction="short",
                    signal_index=idx,
                    entry_index=entry_idx,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=entry - 1.6 * risk_abs,
                    max_hold_bars=6,
                )
        return None


def summarize_alt_data_research_trades(trades: list[AltDataResearchTrade]) -> dict[str, float | int | dict[str, int]]:
    if not trades:
        return {
            "closed": 0,
            "ev_r": 0.0,
            "total_r": 0.0,
            "win_rate": 0.0,
            "avg_hold_bars": 0.0,
            "exit_reason_counts": {},
        }
    closed = len(trades)
    total_r = float(sum(item.r_value for item in trades))
    win_rate = float(sum(1 for item in trades if item.r_value > 0.0) / closed)
    avg_hold = float(sum(item.hold_bars for item in trades) / closed)
    exit_counts: dict[str, int] = {}
    for item in trades:
        exit_counts[item.exit_reason] = exit_counts.get(item.exit_reason, 0) + 1
    return {
        "closed": closed,
        "ev_r": round(total_r / closed, 4),
        "total_r": round(total_r, 4),
        "win_rate": round(win_rate, 4),
        "avg_hold_bars": round(avg_hold, 2),
        "exit_reason_counts": exit_counts,
    }
