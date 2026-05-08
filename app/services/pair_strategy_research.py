from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.db.models import Candle

Direction = Literal["long", "short"]


@dataclass(frozen=True, slots=True)
class PairTrade:
    family: str
    traded_symbol: str
    reference_symbol: str
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


class PairStrategyResearchEngine:
    _ATR_LOOKBACK = 14
    _FEE_RATE_ROUND_TRIP = 0.0006
    _LOOKBACK = 12
    _MAX_HOLD_BARS = 8

    def __init__(self, *, leader_symbol: str, confirmer_symbol: str, leader_candles: list[Candle], confirmer_candles: list[Candle]):
        aligned = self._align_candles(leader_candles=leader_candles, confirmer_candles=confirmer_candles)
        self.leader_symbol = str(leader_symbol).upper()
        self.confirmer_symbol = str(confirmer_symbol).upper()
        self.leader = aligned["leader"]
        self.confirmer = aligned["confirmer"]
        self.ts = [self._normalize_ts(row.ts) for row in self.leader]
        self.opens = [float(row.o) for row in self.leader]
        self.highs = [float(row.h) for row in self.leader]
        self.lows = [float(row.l) for row in self.leader]
        self.closes = [float(row.c) for row in self.leader]
        self.conf_highs = [float(row.h) for row in self.confirmer]
        self.conf_lows = [float(row.l) for row in self.confirmer]
        self.atr = self._build_atr(self.leader)
        self.conf_atr = self._build_atr(self.confirmer)

    @staticmethod
    def _normalize_ts(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _align_candles(self, *, leader_candles: list[Candle], confirmer_candles: list[Candle]) -> dict[str, list[Candle]]:
        confirmer_by_ts = {self._normalize_ts(row.ts): row for row in confirmer_candles}
        aligned_leader: list[Candle] = []
        aligned_confirmer: list[Candle] = []
        for candle in leader_candles:
            ts = self._normalize_ts(candle.ts)
            other = confirmer_by_ts.get(ts)
            if other is None:
                continue
            aligned_leader.append(candle)
            aligned_confirmer.append(other)
        return {"leader": aligned_leader, "confirmer": aligned_confirmer}

    def _build_atr(self, candles: list[Candle]) -> list[float]:
        if len(candles) < 2:
            return [0.0] * len(candles)
        closes = [float(c.c) for c in candles]
        highs = [float(c.h) for c in candles]
        lows = [float(c.l) for c in candles]
        out = [0.0]
        trs: list[float] = []
        prev_close = closes[0]
        for idx in range(1, len(candles)):
            tr = max(highs[idx] - lows[idx], abs(highs[idx] - prev_close), abs(lows[idx] - prev_close))
            trs.append(float(tr))
            prev_close = closes[idx]
            recent = trs[-self._ATR_LOOKBACK :]
            out.append(float(sum(recent) / len(recent)))
        return out

    @staticmethod
    def _close_position_in_bar(high: float, low: float, close: float) -> float:
        rng = max(high - low, 1e-9)
        return float((close - low) / rng)

    def _simulate_trade(
        self,
        *,
        idx: int,
        direction: Direction,
        stop_price: float,
        target_price: float,
        family: str,
    ) -> PairTrade | None:
        entry_idx = idx + 1
        if entry_idx >= len(self.leader):
            return None
        entry_price = self.opens[entry_idx]
        risk_abs = abs(entry_price - stop_price)
        if risk_abs <= 1e-9:
            return None

        exit_idx = min(entry_idx + self._MAX_HOLD_BARS, len(self.leader) - 1)
        exit_price = self.closes[exit_idx]
        exit_reason = "time_exit"

        for probe in range(entry_idx, min(entry_idx + self._MAX_HOLD_BARS + 1, len(self.leader))):
            hit_target = False
            hit_stop = False
            if direction == "long":
                hit_target = self.highs[probe] >= target_price
                hit_stop = self.lows[probe] <= stop_price
            else:
                hit_target = self.lows[probe] <= target_price
                hit_stop = self.highs[probe] >= stop_price

            if hit_target and hit_stop:
                hit_stop = True
                hit_target = False
            if hit_stop:
                exit_idx = probe
                exit_price = stop_price
                exit_reason = "stop"
                break
            if hit_target:
                exit_idx = probe
                exit_price = target_price
                exit_reason = "target"
                break

        gross_r = (exit_price - entry_price) / risk_abs if direction == "long" else (entry_price - exit_price) / risk_abs
        cost_r = (entry_price * self._FEE_RATE_ROUND_TRIP) / risk_abs
        return PairTrade(
            family=family,
            traded_symbol=self.leader_symbol,
            reference_symbol=self.confirmer_symbol,
            direction=direction,
            signal_ts=self.ts[idx],
            entry_ts=self.ts[entry_idx],
            exit_ts=self.ts[exit_idx],
            entry_price=float(entry_price),
            exit_price=float(exit_price),
            stop_price=float(stop_price),
            target_price=float(target_price),
            r_value=float(gross_r - cost_r),
            gross_r=float(gross_r),
            cost_r=float(cost_r),
            hold_bars=max(exit_idx - entry_idx + 1, 1),
            exit_reason=exit_reason,
        )

    def backtest_smt_divergence(self) -> list[PairTrade]:
        trades: list[PairTrade] = []
        idx = max(self._LOOKBACK + 2, 30)
        while idx < len(self.leader) - 2:
            leader_atr = max(self.atr[idx], 1e-9)
            conf_atr = max(self.conf_atr[idx], 1e-9)

            prior_leader_high = max(self.highs[idx - self._LOOKBACK:idx])
            prior_leader_low = min(self.lows[idx - self._LOOKBACK:idx])
            prior_conf_high = max(self.conf_highs[idx - self._LOOKBACK:idx])
            prior_conf_low = min(self.conf_lows[idx - self._LOOKBACK:idx])

            bullish_divergence = (
                self.lows[idx] < prior_leader_low - 0.05 * leader_atr
                and self.conf_lows[idx] >= prior_conf_low - 0.02 * conf_atr
                and self.closes[idx] > prior_leader_low
                and self._close_position_in_bar(self.highs[idx], self.lows[idx], self.closes[idx]) >= 0.55
            )
            bearish_divergence = (
                self.highs[idx] > prior_leader_high + 0.05 * leader_atr
                and self.conf_highs[idx] <= prior_conf_high + 0.02 * conf_atr
                and self.closes[idx] < prior_leader_high
                and self._close_position_in_bar(self.highs[idx], self.lows[idx], self.closes[idx]) <= 0.45
            )

            if bullish_divergence:
                stop = self.lows[idx] - 0.10 * leader_atr
                entry_price = self.opens[idx + 1]
                risk_abs = entry_price - stop
                if 0.25 * leader_atr <= risk_abs <= 1.5 * leader_atr:
                    trade = self._simulate_trade(
                        idx=idx,
                        direction="long",
                        stop_price=stop,
                        target_price=entry_price + 2.0 * risk_abs,
                        family="smt_divergence_reversal",
                    )
                    if trade is not None:
                        trades.append(trade)
                        idx = max(idx + trade.hold_bars, idx + 1)
                        continue

            if bearish_divergence:
                stop = self.highs[idx] + 0.10 * leader_atr
                entry_price = self.opens[idx + 1]
                risk_abs = stop - entry_price
                if 0.25 * leader_atr <= risk_abs <= 1.5 * leader_atr:
                    trade = self._simulate_trade(
                        idx=idx,
                        direction="short",
                        stop_price=stop,
                        target_price=entry_price - 2.0 * risk_abs,
                        family="smt_divergence_reversal",
                    )
                    if trade is not None:
                        trades.append(trade)
                        idx = max(idx + trade.hold_bars, idx + 1)
                        continue

            idx += 1
        return trades


def summarize_pair_trades(trades: list[PairTrade]) -> dict[str, float | int | dict[str, int]]:
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
    ev_r = float(total_r / closed)
    win_rate = float(sum(1 for item in trades if item.r_value > 0.0) / closed)
    avg_hold = float(sum(item.hold_bars for item in trades) / closed)
    exit_counts: dict[str, int] = {}
    for item in trades:
        exit_counts[item.exit_reason] = exit_counts.get(item.exit_reason, 0) + 1
    return {
        "closed": closed,
        "ev_r": round(ev_r, 4),
        "total_r": round(total_r, 4),
        "win_rate": round(win_rate, 4),
        "avg_hold_bars": round(avg_hold, 2),
        "exit_reason_counts": exit_counts,
    }
