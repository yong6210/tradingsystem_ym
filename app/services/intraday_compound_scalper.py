from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from math import isfinite
from statistics import mean
from typing import Any, Literal, Sequence


Direction = Literal["long", "short"]
SetupType = Literal["breakout", "pullback_reclaim"]


@dataclass(frozen=True, slots=True)
class IntradayScalpConfig:
    model_id: str
    interval: str = "15m"
    family: str = "intraday_compound_scalper"
    fast_ema: int = 20
    slow_ema: int = 80
    trend_slope_lookback: int = 6
    breakout_lookback: int = 12
    swing_lookback: int = 6
    volume_lookback: int = 20
    atr_period: int = 14
    min_trend_atr: float = 0.18
    min_slow_slope_atr: float = 0.02
    min_volume_factor: float = 1.05
    breakout_buffer_atr: float = 0.05
    min_body_atr: float = 0.28
    min_close_position: float = 0.60
    pullback_touch_atr: float = 0.28
    pullback_min_body_atr: float = 0.18
    stop_atr: float = 1.15
    stop_buffer_atr: float = 0.08
    min_stop_pct: float = 0.0015
    max_stop_pct: float = 0.025
    max_entry_gap_atr: float = 0.85
    target_rr: float = 1.45
    breakeven_rr: float = 1.00
    max_hold_bars: int = 12
    cooldown_bars: int = 2
    conservative_intrabar: bool = True


@dataclass(frozen=True, slots=True)
class IntradayScalpSignal:
    family: str
    symbol: str
    interval: str
    direction: Direction
    setup_type: SetupType
    signal_ts: datetime
    signal_idx: int
    entry_idx: int
    diagnostics: dict[str, Any]


@dataclass(frozen=True, slots=True)
class IntradayScalpTrade:
    family: str
    model_id: str
    symbol: str
    interval: str
    direction: Direction
    setup_type: SetupType
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
    diagnostics: dict[str, Any]


class _FeatureSet:
    def __init__(self, bars: Sequence[Any], *, atr_period: int = 14):
        self.bars = list(bars)
        self.ts = [_bar_ts(bar) for bar in self.bars]
        self.o = [_bar_float(bar, "o") for bar in self.bars]
        self.h = [_bar_float(bar, "h") for bar in self.bars]
        self.l = [_bar_float(bar, "l") for bar in self.bars]
        self.c = [_bar_float(bar, "c") for bar in self.bars]
        self.v = [_bar_float(bar, "v") for bar in self.bars]
        self.atr = self._atr(atr_period)
        self._ema_cache: dict[int, list[float]] = {}
        self._high_prev_cache: dict[int, list[float]] = {}
        self._low_prev_cache: dict[int, list[float]] = {}
        self._volume_mean_prev_cache: dict[int, list[float]] = {}

    def ema(self, length: int) -> list[float]:
        length = max(int(length), 1)
        cached = self._ema_cache.get(length)
        if cached is not None:
            return cached
        if not self.c:
            self._ema_cache[length] = []
            return []
        alpha = 2.0 / (length + 1.0)
        current = self.c[0]
        out: list[float] = []
        for close in self.c:
            current = alpha * close + (1.0 - alpha) * current
            out.append(current)
        self._ema_cache[length] = out
        return out

    def rolling_high_prev(self, lookback: int) -> list[float]:
        lookback = max(int(lookback), 1)
        cached = self._high_prev_cache.get(lookback)
        if cached is not None:
            return cached
        out: list[float] = []
        for idx, high in enumerate(self.h):
            start = max(0, idx - lookback)
            window = self.h[start:idx]
            out.append(max(window) if window else high)
        self._high_prev_cache[lookback] = out
        return out

    def rolling_low_prev(self, lookback: int) -> list[float]:
        lookback = max(int(lookback), 1)
        cached = self._low_prev_cache.get(lookback)
        if cached is not None:
            return cached
        out: list[float] = []
        for idx, low in enumerate(self.l):
            start = max(0, idx - lookback)
            window = self.l[start:idx]
            out.append(min(window) if window else low)
        self._low_prev_cache[lookback] = out
        return out

    def rolling_volume_mean_prev(self, lookback: int) -> list[float]:
        lookback = max(int(lookback), 1)
        cached = self._volume_mean_prev_cache.get(lookback)
        if cached is not None:
            return cached
        out: list[float] = []
        for idx, volume in enumerate(self.v):
            start = max(0, idx - lookback)
            window = self.v[start:idx]
            out.append(sum(window) / len(window) if window else volume)
        self._volume_mean_prev_cache[lookback] = out
        return out

    def _atr(self, length: int) -> list[float]:
        length = max(int(length), 1)
        if not self.c:
            return []
        out = [max(self.h[0] - self.l[0], 0.0)]
        trs: list[float] = []
        prev_close = self.c[0]
        for idx in range(1, len(self.c)):
            tr = max(
                self.h[idx] - self.l[idx],
                abs(self.h[idx] - prev_close),
                abs(self.l[idx] - prev_close),
            )
            trs.append(tr)
            if len(trs) > length:
                trs.pop(0)
            out.append(sum(trs) / max(len(trs), 1))
            prev_close = self.c[idx]
        return out


class IntradayCompoundScalper:
    def __init__(
        self,
        *,
        symbol: str,
        bars: Sequence[Any],
        config: IntradayScalpConfig,
        fee_bps_per_side: float = 4.0,
        slippage_bps_per_side: float = 1.0,
    ):
        self.symbol = str(symbol).strip().upper()
        self.config = config
        self.features = _FeatureSet(bars, atr_period=config.atr_period)
        self.cost_bps_per_side = max(float(fee_bps_per_side), 0.0) + max(float(slippage_bps_per_side), 0.0)

    def backtest(self) -> list[IntradayScalpTrade]:
        features = self.features
        config = self.config
        warmup = max(
            config.slow_ema + config.trend_slope_lookback,
            config.breakout_lookback,
            config.volume_lookback,
            config.atr_period * 2,
            config.swing_lookback,
        )
        trades: list[IntradayScalpTrade] = []
        idx = warmup
        last_exit_idx = -10_000
        while idx < len(features.c) - 2:
            if idx <= last_exit_idx + max(config.cooldown_bars, 0):
                idx += 1
                continue
            signal = self._signal_at(idx)
            if signal is None:
                idx += 1
                continue
            trade, exit_idx = self._simulate_trade(signal)
            if trade is None:
                idx += 1
                continue
            trades.append(trade)
            last_exit_idx = exit_idx
            idx = max(exit_idx + max(config.cooldown_bars, 0), idx + 1)
        return trades

    def _signal_at(self, idx: int) -> IntradayScalpSignal | None:
        f = self.features
        c = self.config
        atr = max(f.atr[idx], 1e-12)
        fast = f.ema(c.fast_ema)
        slow = f.ema(c.slow_ema)
        prev_high = f.rolling_high_prev(c.breakout_lookback)[idx]
        prev_low = f.rolling_low_prev(c.breakout_lookback)[idx]
        volume_mean = max(f.rolling_volume_mean_prev(c.volume_lookback)[idx], 1e-12)

        close = f.c[idx]
        open_ = f.o[idx]
        high = f.h[idx]
        low = f.l[idx]
        candle_range = max(high - low, 1e-12)
        close_position = (close - low) / candle_range
        body_atr = abs(close - open_) / atr
        volume_factor = f.v[idx] / volume_mean
        trend_atr = (fast[idx] - slow[idx]) / atr
        slope_idx = max(0, idx - max(c.trend_slope_lookback, 1))
        slow_slope_atr = (slow[idx] - slow[slope_idx]) / atr

        long_trend = trend_atr >= c.min_trend_atr and slow_slope_atr >= c.min_slow_slope_atr
        short_trend = trend_atr <= -c.min_trend_atr and slow_slope_atr <= -c.min_slow_slope_atr
        long_breakout = (
            long_trend
            and close > prev_high + c.breakout_buffer_atr * atr
            and close > open_
            and close_position >= c.min_close_position
            and body_atr >= c.min_body_atr
            and volume_factor >= c.min_volume_factor
        )
        short_breakout = (
            short_trend
            and close < prev_low - c.breakout_buffer_atr * atr
            and close < open_
            and close_position <= 1.0 - c.min_close_position
            and body_atr >= c.min_body_atr
            and volume_factor >= c.min_volume_factor
        )
        long_pullback = (
            long_trend
            and low <= fast[idx] + c.pullback_touch_atr * atr
            and close > fast[idx]
            and close > open_
            and close_position >= 0.55
            and body_atr >= c.pullback_min_body_atr
            and volume_factor >= max(c.min_volume_factor * 0.85, 0.75)
        )
        short_pullback = (
            short_trend
            and high >= fast[idx] - c.pullback_touch_atr * atr
            and close < fast[idx]
            and close < open_
            and close_position <= 0.45
            and body_atr >= c.pullback_min_body_atr
            and volume_factor >= max(c.min_volume_factor * 0.85, 0.75)
        )

        long_score = (
            (1.0 if long_breakout else 0.0)
            + (0.75 if long_pullback else 0.0)
            + max(trend_atr, 0.0) * 0.10
            + max(volume_factor - 1.0, 0.0) * 0.15
        )
        short_score = (
            (1.0 if short_breakout else 0.0)
            + (0.75 if short_pullback else 0.0)
            + max(-trend_atr, 0.0) * 0.10
            + max(volume_factor - 1.0, 0.0) * 0.15
        )
        direction: Direction | None = None
        setup_type: SetupType | None = None
        if (long_breakout or long_pullback) and long_score > short_score:
            direction = "long"
            setup_type = "breakout" if long_breakout else "pullback_reclaim"
        elif (short_breakout or short_pullback) and short_score > long_score:
            direction = "short"
            setup_type = "breakout" if short_breakout else "pullback_reclaim"
        if direction is None or setup_type is None:
            return None
        return IntradayScalpSignal(
            family=c.family,
            symbol=self.symbol,
            interval=c.interval,
            direction=direction,
            setup_type=setup_type,
            signal_ts=f.ts[idx],
            signal_idx=idx,
            entry_idx=idx + 1,
            diagnostics={
                "trend_atr": round(trend_atr, 6),
                "slow_slope_atr": round(slow_slope_atr, 6),
                "body_atr": round(body_atr, 6),
                "close_position": round(close_position, 6),
                "volume_factor": round(volume_factor, 6),
                "prev_high": round(prev_high, 8),
                "prev_low": round(prev_low, 8),
                "signal_close": round(close, 8),
                "long_score": round(long_score, 6),
                "short_score": round(short_score, 6),
            },
        )

    def _simulate_trade(self, signal: IntradayScalpSignal) -> tuple[IntradayScalpTrade | None, int]:
        f = self.features
        c = self.config
        entry_idx = signal.entry_idx
        signal_idx = signal.signal_idx
        if entry_idx >= len(f.c):
            return None, signal_idx
        atr = max(f.atr[signal_idx], 1e-12)
        entry = f.o[entry_idx]
        signal_close = f.c[signal_idx]
        if abs(entry - signal_close) / atr > c.max_entry_gap_atr:
            return None, signal_idx

        swing_start = max(0, signal_idx - max(c.swing_lookback, 1) + 1)
        if signal.direction == "long":
            swing_stop = min(f.l[swing_start : signal_idx + 1]) - c.stop_buffer_atr * atr
            structure_risk = entry - swing_stop
        else:
            swing_stop = max(f.h[swing_start : signal_idx + 1]) + c.stop_buffer_atr * atr
            structure_risk = swing_stop - entry
        risk_abs = max(c.stop_atr * atr, structure_risk, entry * c.min_stop_pct)
        if risk_abs <= 0.0 or risk_abs / max(abs(entry), 1e-12) > c.max_stop_pct:
            return None, signal_idx

        if signal.direction == "long":
            stop = entry - risk_abs
            target = entry + c.target_rr * risk_abs
        else:
            stop = entry + risk_abs
            target = entry - c.target_rr * risk_abs

        active_stop = stop
        breakeven_armed_next = False
        end_idx = min(len(f.c) - 1, entry_idx + max(c.max_hold_bars, 1))
        exit_idx = end_idx
        exit_price = f.c[end_idx]
        exit_reason = "time_exit"
        breakeven_activated = False

        for idx in range(entry_idx, end_idx + 1):
            if breakeven_armed_next and signal.direction == "long":
                active_stop = max(active_stop, entry)
                breakeven_activated = True
            elif breakeven_armed_next and signal.direction == "short":
                active_stop = min(active_stop, entry)
                breakeven_activated = True

            if signal.direction == "long":
                stop_hit = f.l[idx] <= active_stop
                target_hit = f.h[idx] >= target
                if stop_hit and (c.conservative_intrabar or not target_hit):
                    exit_idx = idx
                    exit_price = active_stop
                    exit_reason = "breakeven_stop" if active_stop >= entry else "stop_loss"
                    break
                if target_hit:
                    exit_idx = idx
                    exit_price = target
                    exit_reason = "target"
                    break
                if f.h[idx] >= entry + c.breakeven_rr * risk_abs:
                    breakeven_armed_next = True
            else:
                stop_hit = f.h[idx] >= active_stop
                target_hit = f.l[idx] <= target
                if stop_hit and (c.conservative_intrabar or not target_hit):
                    exit_idx = idx
                    exit_price = active_stop
                    exit_reason = "breakeven_stop" if active_stop <= entry else "stop_loss"
                    break
                if target_hit:
                    exit_idx = idx
                    exit_price = target
                    exit_reason = "target"
                    break
                if f.l[idx] <= entry - c.breakeven_rr * risk_abs:
                    breakeven_armed_next = True

        gross_r = _directional_r(signal.direction, entry, exit_price, risk_abs)
        cost_r = self._cost_r(entry_price=entry, exit_price=exit_price, risk_abs=risk_abs)
        r_value = gross_r - cost_r
        diagnostics = {
            **signal.diagnostics,
            "risk_abs": round(risk_abs, 8),
            "risk_pct": round(risk_abs / max(abs(entry), 1e-12), 6),
            "entry_gap_atr": round(abs(entry - signal_close) / atr, 6),
            "atr": round(atr, 8),
            "breakeven_activated": breakeven_activated,
        }
        return (
            IntradayScalpTrade(
                family=signal.family,
                model_id=c.model_id,
                symbol=self.symbol,
                interval=c.interval,
                direction=signal.direction,
                setup_type=signal.setup_type,
                signal_ts=signal.signal_ts,
                entry_ts=f.ts[entry_idx],
                exit_ts=f.ts[exit_idx],
                entry_price=entry,
                exit_price=exit_price,
                stop_price=stop,
                target_price=target,
                r_value=r_value,
                gross_r=gross_r,
                cost_r=cost_r,
                hold_bars=max(exit_idx - entry_idx + 1, 1),
                exit_reason=exit_reason,
                diagnostics=diagnostics,
            ),
            exit_idx,
        )

    def _cost_r(self, *, entry_price: float, exit_price: float, risk_abs: float) -> float:
        notional_cost = (abs(entry_price) + abs(exit_price)) * (self.cost_bps_per_side / 10_000.0)
        return notional_cost / max(risk_abs, 1e-12)


def build_intraday_scalp_configs(intervals: Sequence[str] = ("15m", "30m")) -> list[IntradayScalpConfig]:
    configs: list[IntradayScalpConfig] = []
    for interval in intervals:
        normalized = str(interval).strip()
        if normalized not in {"15m", "30m"}:
            continue
        for fast, slow in ((13, 55), (20, 80), (21, 89)):
            for lookback in (10, 16, 24):
                for target_rr in (1.25, 1.45, 1.70):
                    max_hold = 10 if normalized == "15m" else 8
                    model_id = (
                        f"{normalized}:intraday_compound_scalper:"
                        f"ema{fast}_{slow}:br{lookback}:rr{target_rr:g}:hold{max_hold}"
                    )
                    configs.append(
                        IntradayScalpConfig(
                            model_id=model_id,
                            interval=normalized,
                            fast_ema=fast,
                            slow_ema=slow,
                            breakout_lookback=lookback,
                            swing_lookback=max(4, lookback // 3),
                            target_rr=target_rr,
                            max_hold_bars=max_hold,
                        )
                    )
    return configs


def summarize_intraday_scalp_trades(trades: Sequence[IntradayScalpTrade]) -> dict[str, Any]:
    rows = list(trades)
    if not rows:
        return {
            "closed": 0,
            "total_r": 0.0,
            "ev_r": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_r": 0.0,
            "avg_hold_bars": 0.0,
            "trades_per_day": 0.0,
            "by_direction": {},
            "by_interval": {},
            "by_setup_type": {},
            "exit_reason_counts": {},
        }
    r_values = [float(row.r_value) for row in rows]
    wins = [value for value in r_values if value > 0.0]
    losses = [value for value in r_values if value <= 0.0]
    first_ts = min(row.entry_ts for row in rows)
    last_ts = max(row.exit_ts for row in rows)
    days = max((last_ts - first_ts).total_seconds() / 86_400.0, 1.0)
    return {
        "closed": len(rows),
        "total_r": round(sum(r_values), 4),
        "ev_r": round(sum(r_values) / len(rows), 4),
        "win_rate": round(len(wins) / len(rows), 4),
        "profit_factor": round(sum(wins) / max(abs(sum(losses)), 1e-12), 4) if losses else 999.0,
        "max_drawdown_r": round(_max_drawdown(r_values), 4),
        "avg_hold_bars": round(mean(row.hold_bars for row in rows), 4),
        "trades_per_day": round(len(rows) / days, 4),
        "by_direction": _group_summary(rows, "direction"),
        "by_interval": _group_summary(rows, "interval"),
        "by_setup_type": _group_summary(rows, "setup_type"),
        "exit_reason_counts": dict(sorted(Counter(row.exit_reason for row in rows).items())),
    }


def intraday_scalp_decision(summary: dict[str, Any], *, min_trades: int = 80) -> str:
    closed = int(summary.get("closed") or 0)
    ev_r = float(summary.get("ev_r") or 0.0)
    total_r = float(summary.get("total_r") or 0.0)
    max_dd = float(summary.get("max_drawdown_r") or 0.0)
    profit_factor = float(summary.get("profit_factor") or 0.0)
    trades_per_day = float(summary.get("trades_per_day") or 0.0)
    if closed < max(int(min_trades), 1):
        return "INSUFFICIENT_SAMPLE"
    if total_r <= 0.0 or ev_r < 0.05:
        return "REJECT_NEGATIVE_OR_WEAK_EDGE"
    if profit_factor < 1.15:
        return "REJECT_WEAK_PROFIT_FACTOR"
    if max_dd > max(total_r * 0.55, 18.0):
        return "REJECT_DRAWDOWN_HEAVY"
    if trades_per_day < 0.20:
        return "WATCH_TOO_SPARSE_FOR_INTRADAY_COMPOUNDING"
    if ev_r >= 0.12 and profit_factor >= 1.35 and max_dd <= max(total_r * 0.35, 12.0):
        return "RESEARCH_CANDIDATE_STRONG"
    return "RESEARCH_CANDIDATE_WATCH"


def score_intraday_scalp_summary(summary: dict[str, Any]) -> float:
    closed = int(summary.get("closed") or 0)
    if closed <= 0:
        return -1_000_000.0
    total_r = float(summary.get("total_r") or 0.0)
    ev_r = float(summary.get("ev_r") or 0.0)
    max_dd = float(summary.get("max_drawdown_r") or 0.0)
    profit_factor = min(float(summary.get("profit_factor") or 0.0), 5.0)
    trades_per_day = min(float(summary.get("trades_per_day") or 0.0), 4.0)
    return round(total_r + ev_r * 80.0 + profit_factor * 8.0 + trades_per_day * 4.0 - max_dd * 2.2, 4)


def trade_to_dict(trade: IntradayScalpTrade) -> dict[str, Any]:
    row = asdict(trade)
    for key in ("signal_ts", "entry_ts", "exit_ts"):
        row[key] = getattr(trade, key).isoformat()
    row["entry_price"] = round(trade.entry_price, 8)
    row["exit_price"] = round(trade.exit_price, 8)
    row["stop_price"] = round(trade.stop_price, 8)
    row["target_price"] = round(trade.target_price, 8)
    row["r_value"] = round(trade.r_value, 6)
    row["gross_r"] = round(trade.gross_r, 6)
    row["cost_r"] = round(trade.cost_r, 6)
    return row


def _group_summary(rows: Sequence[IntradayScalpTrade], attr: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[IntradayScalpTrade]] = {}
    for row in rows:
        key = str(getattr(row, attr))
        groups.setdefault(key, []).append(row)
    return {
        key: {
            "closed": len(group),
            "total_r": round(sum(item.r_value for item in group), 4),
            "ev_r": round(sum(item.r_value for item in group) / len(group), 4),
            "win_rate": round(sum(1 for item in group if item.r_value > 0.0) / len(group), 4),
        }
        for key, group in sorted(groups.items())
    }


def _max_drawdown(values: Sequence[float]) -> float:
    peak = 0.0
    equity = 0.0
    max_dd = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _directional_r(direction: Direction, entry: float, exit_price: float, risk_abs: float) -> float:
    if direction == "long":
        return (exit_price - entry) / max(risk_abs, 1e-12)
    return (entry - exit_price) / max(risk_abs, 1e-12)


def _bar_float(bar: Any, attr: str) -> float:
    value = getattr(bar, attr, None)
    if value is None and isinstance(bar, dict):
        value = bar.get(attr)
    parsed = float(value)
    return parsed if isfinite(parsed) else 0.0


def _bar_ts(bar: Any) -> datetime:
    value = getattr(bar, "ts", None)
    if value is None and isinstance(bar, dict):
        value = bar.get("ts")
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError("bar timestamp is required")
