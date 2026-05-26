#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text
from scripts import run_multi_asset_rotation_search as rot
from scripts.run_btc_flip_rotation_search import _INTERVAL_MS, _csv, _load_bars


DEFAULT_SYMBOLS = "BTCUSDT,ETHUSDT,SOLUSDT"


@dataclass(frozen=True, slots=True)
class DirectionalConfig:
    name: str
    interval: str
    sleeve: str
    symbol_weights: dict[str, float]
    signal_mode: str
    signal_params: dict[str, float | int | str | bool]
    gross_leverage: float
    rebalance_bars: int
    drawdown_guard_pct: float
    drawdown_risk_scale: float
    vol_target_annual_pct: float
    vol_target_mode: str
    vol_lookback_bars: int
    vol_min_scale: float
    vol_max_scale: float


class SymbolFeatureEngine:
    def __init__(self, frame: rot.MarketFrame, symbol: str) -> None:
        self.frame = frame
        self.symbol = symbol
        self.opens = frame.opens[symbol]
        self.highs = frame.highs[symbol]
        self.lows = frame.lows[symbol]
        self.closes = frame.closes[symbol]
        self.returns = frame.returns[symbol]
        self._ema_cache: dict[int, list[float]] = {}
        self._sma_cache: dict[int, list[float]] = {}
        self._atr_cache: dict[int, list[float]] = {}
        self._rsi_cache: dict[int, list[float]] = {}
        self._high_cache: dict[int, list[float]] = {}
        self._low_cache: dict[int, list[float]] = {}
        self._donchian_cache: dict[tuple[int, int, bool], list[int]] = {}
        self._supertrend_cache: dict[tuple[int, float], list[int]] = {}

    def ema(self, length: int) -> list[float]:
        length = max(int(length), 1)
        cached = self._ema_cache.get(length)
        if cached is not None:
            return cached
        alpha = 2.0 / (length + 1.0)
        current = math.nan
        out: list[float] = []
        for value in self.closes:
            if not math.isfinite(value):
                out.append(math.nan)
                continue
            if not math.isfinite(current):
                current = float(value)
            else:
                current = alpha * float(value) + (1.0 - alpha) * current
            out.append(current)
        self._ema_cache[length] = out
        return out

    def sma(self, length: int) -> list[float]:
        length = max(int(length), 1)
        cached = self._sma_cache.get(length)
        if cached is not None:
            return cached
        out = [math.nan] * len(self.closes)
        q: deque[float] = deque()
        total = 0.0
        finite_count = 0
        for idx, value in enumerate(self.closes):
            q.append(value)
            if math.isfinite(value):
                total += value
                finite_count += 1
            if len(q) > length:
                old = q.popleft()
                if math.isfinite(old):
                    total -= old
                    finite_count -= 1
            if finite_count >= length:
                out[idx] = total / max(finite_count, 1)
        self._sma_cache[length] = out
        return out

    def atr(self, length: int) -> list[float]:
        length = max(int(length), 1)
        cached = self._atr_cache.get(length)
        if cached is not None:
            return cached
        out = [math.nan] * len(self.closes)
        q: deque[float] = deque()
        total = 0.0
        prev_close = math.nan
        for idx, close in enumerate(self.closes):
            high = self.highs[idx]
            low = self.lows[idx]
            if not (math.isfinite(high) and math.isfinite(low) and math.isfinite(close)):
                out[idx] = math.nan
                continue
            if math.isfinite(prev_close):
                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            else:
                tr = high - low
            prev_close = close
            if math.isfinite(tr):
                q.append(float(tr))
                total += float(tr)
            if len(q) > length:
                total -= q.popleft()
            if len(q) >= length:
                out[idx] = total / len(q)
        self._atr_cache[length] = out
        return out

    def rolling_high_prev(self, length: int) -> list[float]:
        length = max(int(length), 1)
        cached = self._high_cache.get(length)
        if cached is not None:
            return cached
        out = [math.nan] * len(self.highs)
        q: deque[tuple[int, float]] = deque()
        for idx, value in enumerate(self.highs):
            while q and q[0][0] <= idx - length - 1:
                q.popleft()
            if q:
                out[idx] = q[0][1]
            if math.isfinite(value):
                while q and q[-1][1] <= value:
                    q.pop()
                q.append((idx, float(value)))
        self._high_cache[length] = out
        return out

    def rolling_low_prev(self, length: int) -> list[float]:
        length = max(int(length), 1)
        cached = self._low_cache.get(length)
        if cached is not None:
            return cached
        out = [math.nan] * len(self.lows)
        q: deque[tuple[int, float]] = deque()
        for idx, value in enumerate(self.lows):
            while q and q[0][0] <= idx - length - 1:
                q.popleft()
            if q:
                out[idx] = q[0][1]
            if math.isfinite(value):
                while q and q[-1][1] >= value:
                    q.pop()
                q.append((idx, float(value)))
        self._low_cache[length] = out
        return out

    def rsi(self, length: int) -> list[float]:
        length = max(int(length), 2)
        cached = self._rsi_cache.get(length)
        if cached is not None:
            return cached
        out = [50.0] * len(self.closes)
        gains: deque[float] = deque()
        losses: deque[float] = deque()
        gain_sum = 0.0
        loss_sum = 0.0
        prev = math.nan
        for idx, close in enumerate(self.closes):
            if not (math.isfinite(prev) and math.isfinite(close)):
                prev = close
                continue
            change = close - prev
            prev = close
            gain = max(change, 0.0)
            loss = max(-change, 0.0)
            gains.append(gain)
            losses.append(loss)
            gain_sum += gain
            loss_sum += loss
            if len(gains) > length:
                gain_sum -= gains.popleft()
                loss_sum -= losses.popleft()
            if len(gains) < length:
                continue
            avg_gain = gain_sum / max(len(gains), 1)
            avg_loss = loss_sum / max(len(losses), 1)
            if avg_loss <= 1e-12:
                out[idx] = 100.0
            else:
                rs = avg_gain / avg_loss
                out[idx] = 100.0 - 100.0 / (1.0 + rs)
        self._rsi_cache[length] = out
        return out

    def donchian_state(self, entry_bars: int, exit_bars: int, always_in: bool) -> list[int]:
        key = (max(int(entry_bars), 1), max(int(exit_bars), 1), bool(always_in))
        cached = self._donchian_cache.get(key)
        if cached is not None:
            return cached
        highs = self.rolling_high_prev(key[0])
        lows = self.rolling_low_prev(key[0])
        exit_highs = self.rolling_high_prev(key[1])
        exit_lows = self.rolling_low_prev(key[1])
        state = 0
        out: list[int] = []
        for idx, close in enumerate(self.closes):
            if not math.isfinite(close):
                out.append(0)
                continue
            high = highs[idx]
            low = lows[idx]
            if math.isfinite(high) and close > high:
                state = 1
            elif math.isfinite(low) and close < low:
                state = -1
            elif not key[2]:
                if state > 0 and math.isfinite(exit_lows[idx]) and close < exit_lows[idx]:
                    state = 0
                elif state < 0 and math.isfinite(exit_highs[idx]) and close > exit_highs[idx]:
                    state = 0
            out.append(state)
        self._donchian_cache[key] = out
        return out

    def supertrend_direction(self, atr_bars: int, multiplier: float) -> list[int]:
        key = (max(int(atr_bars), 1), round(float(multiplier), 6))
        cached = self._supertrend_cache.get(key)
        if cached is not None:
            return cached
        atr = self.atr(key[0])
        out: list[int] = []
        upper = math.nan
        lower = math.nan
        direction = 0
        for idx, close in enumerate(self.closes):
            high = self.highs[idx]
            low = self.lows[idx]
            if not (math.isfinite(high) and math.isfinite(low) and math.isfinite(close) and math.isfinite(atr[idx])):
                out.append(0)
                continue
            midpoint = (high + low) / 2.0
            basic_upper = midpoint + key[1] * atr[idx]
            basic_lower = midpoint - key[1] * atr[idx]
            prev_close = self.closes[idx - 1] if idx > 0 else math.nan
            if not math.isfinite(upper) or (math.isfinite(prev_close) and prev_close > upper):
                upper = basic_upper
            else:
                upper = min(basic_upper, upper)
            if not math.isfinite(lower) or (math.isfinite(prev_close) and prev_close < lower):
                lower = basic_lower
            else:
                lower = max(basic_lower, lower)
            if direction >= 0:
                direction = -1 if close < lower else 1
            else:
                direction = 1 if close > upper else -1
            out.append(direction)
        self._supertrend_cache[key] = out
        return out


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only non-rotation directional strategy search for fixed BTC/ETH/SOL sleeves."
    )
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument("--days", type=int, default=1825)
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument("--short-cost-bps-per-day", type=float, default=0.0)
    parser.add_argument("--holding-cost-bps-per-day", type=float, default=0.0)
    parser.add_argument("--apply-funding", action="store_true", default=True)
    parser.add_argument("--funding-cache-dir", default="reports/validation/multi_asset_rotation_search/funding_cache")
    parser.add_argument("--cache-dir", default="reports/validation/multi_asset_rotation_search/cache")
    parser.add_argument("--report-dir", default="reports/validation/non_rotation_directional_search_currentdata_20260526")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    parser.add_argument("--max-configs", type=int, default=0)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _hours_to_bars(interval: str, hours: int) -> int:
    interval_ms = _INTERVAL_MS[interval]
    return max(int(math.ceil(max(int(hours), 1) * 60 * 60 * 1000 / interval_ms)), 1)


def _trailing_sum(values: list[float], idx: int, bars: int) -> float:
    start = max(0, idx - max(int(bars), 1) + 1)
    total = 0.0
    count = 0
    for value in values[start : idx + 1]:
        if math.isfinite(value):
            total += float(value)
            count += 1
    return total if count > 0 else math.nan


def _sign(value: float, threshold: float = 0.0) -> int:
    if not math.isfinite(value):
        return 0
    if value > threshold:
        return 1
    if value < -threshold:
        return -1
    return 0


def _market_regime_scale(
    engines: dict[str, SymbolFeatureEngine],
    idx: int,
    side: float,
    params: dict[str, float | int | str | bool],
) -> float:
    guard = str(params.get("btc_guard") or "none")
    if guard == "none" or side == 0.0 or "BTCUSDT" not in engines:
        return 1.0
    btc = engines["BTCUSDT"]
    length = int(params.get("btc_guard_ema") or 300)
    ema = btc.ema(length)[idx]
    close = btc.closes[idx]
    if not (math.isfinite(close) and math.isfinite(ema)):
        return 1.0
    bull = close >= ema
    if guard == "trend_bias":
        if bull and side < 0.0:
            return float(params.get("short_in_bull_scale") or 0.35)
        if (not bull) and side > 0.0:
            return float(params.get("long_in_bear_scale") or 0.35)
    if guard == "long_only_bull":
        if side > 0.0 and not bull:
            return 0.0
        if side < 0.0 and bull:
            return 0.0
    return 1.0


def _funding_signal(
    funding_period_rates: dict[str, list[float]] | None,
    symbol: str,
    idx: int,
    lookback_bars: int,
    threshold: float,
) -> int:
    if not funding_period_rates:
        return 0
    values = funding_period_rates.get(symbol) or []
    if not values or idx >= len(values):
        return 0
    trailing = _trailing_sum(values, idx, lookback_bars)
    if not math.isfinite(trailing):
        return 0
    if trailing > threshold:
        return -1
    if trailing < -threshold:
        return 1
    return 0


def _raw_signal(
    *,
    engines: dict[str, SymbolFeatureEngine],
    funding_period_rates: dict[str, list[float]] | None,
    symbol: str,
    idx: int,
    mode: str,
    params: dict[str, float | int | str | bool],
) -> float:
    engine = engines[symbol]
    close = engine.closes[idx]
    if not math.isfinite(close):
        return 0.0
    if mode == "ema_ls":
        fast = engine.ema(int(params.get("fast") or 24))[idx]
        slow = engine.ema(int(params.get("slow") or 120))[idx]
        atr = engine.atr(int(params.get("atr") or 21))[idx]
        threshold = float(params.get("threshold") or 0.0)
        spread = (fast - slow) / max(atr, 1e-12) if math.isfinite(fast) and math.isfinite(slow) else math.nan
        return float(_sign(spread, threshold))
    if mode == "donchian_flip":
        state = engine.donchian_state(
            int(params.get("entry") or 55),
            int(params.get("exit") or 20),
            bool(params.get("always_in", False)),
        )[idx]
        return float(state)
    if mode == "supertrend":
        direction = engine.supertrend_direction(
            int(params.get("atr") or 20),
            float(params.get("mult") or 3.0),
        )[idx]
        return float(direction)
    if mode == "trend_funding":
        fast = engine.ema(int(params.get("fast") or 24))[idx]
        slow = engine.ema(int(params.get("slow") or 120))[idx]
        atr = engine.atr(int(params.get("atr") or 21))[idx]
        spread = (fast - slow) / max(atr, 1e-12) if math.isfinite(fast) and math.isfinite(slow) else math.nan
        trend = _sign(spread, float(params.get("trend_threshold") or 0.0))
        carry = _funding_signal(
            funding_period_rates,
            symbol,
            idx,
            int(params.get("funding_lookback") or 42),
            float(params.get("funding_threshold") or 0.0015),
        )
        if trend == 0:
            return float(carry) * float(params.get("carry_only_scale") or 0.35)
        if carry != 0 and carry != trend:
            return float(trend) * float(params.get("against_carry_scale") or 0.35)
        return float(trend)
    if mode == "funding_carry":
        carry = _funding_signal(
            funding_period_rates,
            symbol,
            idx,
            int(params.get("funding_lookback") or 42),
            float(params.get("funding_threshold") or 0.0015),
        )
        return float(carry)
    if mode == "rsi_mr":
        rsi = engine.rsi(int(params.get("rsi") or 14))[idx]
        lower = float(params.get("lower") or 30.0)
        upper = float(params.get("upper") or 70.0)
        if rsi <= lower:
            return 1.0
        if rsi >= upper:
            return -1.0
        return 0.0
    if mode == "ensemble_grade":
        fast = engine.ema(int(params.get("fast") or 24))[idx]
        slow = engine.ema(int(params.get("slow") or 120))[idx]
        atr = engine.atr(int(params.get("atr") or 21))[idx]
        spread = (fast - slow) / max(atr, 1e-12) if math.isfinite(fast) and math.isfinite(slow) else math.nan
        trend = _sign(spread, float(params.get("trend_threshold") or 0.0))
        donchian = engine.donchian_state(
            int(params.get("entry") or 55),
            int(params.get("exit") or 20),
            bool(params.get("always_in", False)),
        )[idx]
        st = engine.supertrend_direction(
            int(params.get("st_atr") or 20),
            float(params.get("st_mult") or 3.0),
        )[idx]
        carry = _funding_signal(
            funding_period_rates,
            symbol,
            idx,
            int(params.get("funding_lookback") or 42),
            float(params.get("funding_threshold") or 0.0015),
        )
        rsi = engine.rsi(int(params.get("rsi") or 14))[idx]
        pullback = 0
        if rsi <= float(params.get("rsi_lower") or 35.0) and trend >= 0:
            pullback = 1
        elif rsi >= float(params.get("rsi_upper") or 65.0) and trend <= 0:
            pullback = -1
        score = (
            float(params.get("trend_weight") or 1.0) * trend
            + float(params.get("breakout_weight") or 1.0) * donchian
            + float(params.get("supertrend_weight") or 1.0) * st
            + float(params.get("carry_weight") or 0.5) * carry
            + float(params.get("pullback_weight") or 0.5) * pullback
        )
        full = float(params.get("full_score") or 2.0)
        half = float(params.get("half_score") or 1.0)
        if score >= full:
            return 1.0
        if score >= half:
            return 0.5
        if score <= -full:
            return -1.0
        if score <= -half:
            return -0.5
        return 0.0
    raise ValueError(f"unknown_signal_mode:{mode}")


def _signal(
    *,
    engines: dict[str, SymbolFeatureEngine],
    funding_period_rates: dict[str, list[float]] | None,
    symbol: str,
    idx: int,
    mode: str,
    params: dict[str, float | int | str | bool],
) -> float:
    raw = _raw_signal(
        engines=engines,
        funding_period_rates=funding_period_rates,
        symbol=symbol,
        idx=idx,
        mode=mode,
        params=params,
    )
    raw *= _market_regime_scale(engines, idx, raw, params)
    max_abs = float(params.get("max_signal_abs") or 1.0)
    return min(max(raw, -max_abs), max_abs)


def _turnover(old: dict[str, float], new: dict[str, float], symbols: list[str]) -> float:
    return sum(abs(new.get(symbol, 0.0) - old.get(symbol, 0.0)) for symbol in symbols)


def _year_fraction(first: datetime | None, last: datetime | None) -> float:
    if first is None or last is None or last <= first:
        return 0.0
    return (last - first).total_seconds() / (365.25 * 86_400)


def _quantile(values: list[float], q: float) -> float:
    clean = sorted(value for value in values if math.isfinite(value))
    if not clean:
        return math.nan
    q = min(max(float(q), 0.0), 1.0)
    pos = q * (len(clean) - 1)
    low = int(math.floor(pos))
    high = int(math.ceil(pos))
    if low == high:
        return clean[low]
    frac = pos - low
    return clean[low] * (1.0 - frac) + clean[high] * frac


def _vol_scale(
    realized_returns: deque[float],
    *,
    interval: str,
    target_annual_pct: float,
    mode: str,
    min_scale: float,
    max_scale: float,
) -> float:
    if target_annual_pct <= 0.0 or len(realized_returns) < max(10, realized_returns.maxlen // 2):
        return 1.0
    values = [float(value) for value in realized_returns if math.isfinite(value)]
    if mode == "downside":
        values = [min(value, 0.0) for value in values]
    if len(values) < 10:
        return 1.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) * (value - mean) for value in values) / len(values)
    period_vol = math.sqrt(max(variance, 0.0))
    bars_per_year = 365.25 * 24.0 / max(_INTERVAL_MS[interval] / (60 * 60 * 1000), 1e-9)
    annual_vol = period_vol * math.sqrt(bars_per_year)
    if annual_vol <= 1e-12:
        return 1.0
    scale = max(float(target_annual_pct), 0.0) / 100.0 / annual_vol
    return min(max(scale, max(min_scale, 0.0)), max(max_scale, 0.0))


def backtest_directional_config(
    frame: rot.MarketFrame,
    engines: dict[str, SymbolFeatureEngine],
    config: DirectionalConfig,
    *,
    funding_period_rates: dict[str, list[float]] | None,
    fee_bps_per_side: float,
    slippage_bps_per_side: float,
    holding_cost_bps_per_day: float,
    short_cost_bps_per_day: float,
) -> dict[str, Any]:
    max_param = max(
        int(value)
        for value in config.signal_params.values()
        if isinstance(value, int | float) and math.isfinite(float(value))
    )
    warmup = max(80, max_param + 5, config.vol_lookback_bars + 5)
    if len(frame.ts) < warmup + 20:
        return {"decision": "REJECT_SAMPLE", "periods": 0}

    weights: dict[str, float] = {}
    equity = 1.0
    peak = 1.0
    min_equity = 1.0
    max_dd = 0.0
    wins = 0
    losses = 0
    period_count = 0
    active_periods = 0
    rebalance_count = 0
    turnover_sum = 0.0
    cost_drag = 0.0
    holding_cost_drag = 0.0
    short_cost_drag = 0.0
    funding_pnl = 0.0
    gross_exposure_sum = 0.0
    net_exposure_sum = 0.0
    short_exposure_sum = 0.0
    risk_scale_sum = 0.0
    risk_scale_count = 0
    drawdown_guard_periods = 0
    vol_target_periods = 0
    by_year_start: dict[str, float] = {}
    by_year_end: dict[str, float] = {}
    period_returns: list[float] = []
    realized_returns: deque[float] = deque(maxlen=max(config.vol_lookback_bars, 10))
    direction_periods: Counter[str] = Counter()
    symbol_abs_exposure_sum: dict[str, float] = {symbol: 0.0 for symbol in frame.symbols}
    symbol_long_periods: Counter[str] = Counter()
    symbol_short_periods: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    first_exec_ts: datetime | None = None
    last_period_ts: datetime | None = None
    cost_bps = max(float(fee_bps_per_side), 0.0) + max(float(slippage_bps_per_side), 0.0)

    first_exec_idx = warmup + 1
    last_exec_idx = len(frame.ts) - 2
    for exec_idx in range(first_exec_idx, last_exec_idx + 1):
        if first_exec_ts is None:
            first_exec_ts = frame.ts[exec_idx]
        should_rebalance = (exec_idx - first_exec_idx) % max(config.rebalance_bars, 1) == 0
        turnover = 0.0
        if should_rebalance:
            signal_idx = exec_idx - 1
            raw_weights: dict[str, float] = {}
            for symbol, sleeve_weight in config.symbol_weights.items():
                if symbol not in engines:
                    continue
                signal = _signal(
                    engines=engines,
                    funding_period_rates=funding_period_rates,
                    symbol=symbol,
                    idx=signal_idx,
                    mode=config.signal_mode,
                    params=config.signal_params,
                )
                target = float(sleeve_weight) * float(config.gross_leverage) * signal
                if abs(target) > 1e-12:
                    raw_weights[symbol] = target

            risk_scale = 1.0
            live_drawdown = 1.0 - equity / max(peak, 1e-12)
            if config.drawdown_guard_pct > 0.0 and live_drawdown * 100.0 >= config.drawdown_guard_pct:
                risk_scale *= max(float(config.drawdown_risk_scale), 0.0)
                drawdown_guard_periods += 1
            vol_scale = _vol_scale(
                realized_returns,
                interval=config.interval,
                target_annual_pct=config.vol_target_annual_pct,
                mode=config.vol_target_mode,
                min_scale=config.vol_min_scale,
                max_scale=config.vol_max_scale,
            )
            if vol_scale != 1.0:
                vol_target_periods += 1
            risk_scale *= vol_scale
            new_weights = {
                symbol: value * risk_scale
                for symbol, value in raw_weights.items()
                if abs(value * risk_scale) > 1e-12
            }
            turnover = _turnover(weights, new_weights, frame.symbols)
            if turnover > 1e-12:
                rebalance_count += 1
            if len(samples) < 8:
                samples.append(
                    {
                        "exec_ts": frame.ts[exec_idx].isoformat(),
                        "signal_ts": frame.ts[signal_idx].isoformat(),
                        "turnover": round(turnover, 4),
                        "risk_scale": round(risk_scale, 4),
                        "drawdown_pct": round(live_drawdown * 100.0, 4),
                        "weights": {
                            symbol: round(value, 4)
                            for symbol, value in sorted(new_weights.items())
                            if abs(value) > 1e-9
                        },
                    }
                )
            weights = new_weights
            risk_scale_sum += risk_scale
            risk_scale_count += 1

        gross_exposure = sum(abs(value) for value in weights.values())
        net_exposure = sum(weights.values())
        short_exposure = sum(abs(value) for value in weights.values() if value < 0.0)
        gross_exposure_sum += gross_exposure
        net_exposure_sum += net_exposure
        short_exposure_sum += short_exposure
        turnover_sum += turnover
        cost_period = turnover * cost_bps / 10_000.0
        cost_drag += cost_period
        period_days = max((frame.ts[exec_idx + 1] - frame.ts[exec_idx]).total_seconds() / 86_400, 0.0)
        holding_cost_period = gross_exposure * max(float(holding_cost_bps_per_day), 0.0) / 10_000.0 * period_days
        short_cost_period = short_exposure * max(float(short_cost_bps_per_day), 0.0) / 10_000.0 * period_days
        holding_cost_drag += holding_cost_period
        short_cost_drag += short_cost_period
        funding_period = rot._funding_return_for_period_index(funding_period_rates, weights, exec_idx)
        funding_pnl += funding_period

        portfolio_return = 0.0
        for symbol, weight in weights.items():
            if exec_idx >= len(frame.returns[symbol]):
                continue
            symbol_return = frame.returns[symbol][exec_idx]
            if not math.isfinite(symbol_return):
                continue
            portfolio_return += weight * symbol_return
            symbol_abs_exposure_sum[symbol] += abs(weight)
            if weight > 0.0:
                symbol_long_periods[symbol] += 1
            elif weight < 0.0:
                symbol_short_periods[symbol] += 1

        net_return = portfolio_return + funding_period - cost_period - holding_cost_period - short_cost_period
        if gross_exposure > 1e-9:
            active_periods += 1
        if net_exposure > 0.05:
            direction_periods["net_long"] += 1
        elif net_exposure < -0.05:
            direction_periods["net_short"] += 1
        else:
            direction_periods["market_neutral_or_flat"] += 1

        year = str(frame.ts[exec_idx + 1].year)
        by_year_start.setdefault(year, equity)
        if net_return <= -0.999:
            equity = 1e-9
        else:
            equity *= 1.0 + net_return
        by_year_end[year] = equity
        peak = max(peak, equity)
        min_equity = min(min_equity, equity)
        max_dd = max(max_dd, 1.0 - equity / max(peak, 1e-12))
        if net_return > 0.0:
            wins += 1
        elif net_return < 0.0:
            losses += 1
        period_returns.append(net_return)
        realized_returns.append(net_return)
        period_count += 1
        last_period_ts = frame.ts[exec_idx + 1]
        if equity <= 1e-8:
            break

    years = max(_year_fraction(first_exec_ts, last_period_ts), 1e-9)
    total_return = equity - 1.0
    cagr = (equity ** (1.0 / years) - 1.0) if equity > 0.0 else -1.0
    by_year_return = {
        year: by_year_end[year] / max(by_year_start.get(year, 1.0), 1e-12) - 1.0
        for year in sorted(by_year_end)
    }
    positive_years = sum(1 for value in by_year_return.values() if value > 0.0)
    positive_year_fraction = positive_years / max(len(by_year_return), 1)
    avg_gross = gross_exposure_sum / max(period_count, 1)
    avg_net = net_exposure_sum / max(period_count, 1)
    avg_short = short_exposure_sum / max(period_count, 1)
    common_days = max(years * 365.25, 1e-9)
    win_rate = wins / max(wins + losses, 1)
    returns_clean = [value for value in period_returns if math.isfinite(value)]
    period_mean = sum(returns_clean) / max(len(returns_clean), 1)
    period_var = (
        sum((value - period_mean) * (value - period_mean) for value in returns_clean) / max(len(returns_clean), 1)
        if returns_clean
        else 0.0
    )
    bars_per_year = 365.25 * 24.0 / max(_INTERVAL_MS[config.interval] / (60 * 60 * 1000), 1e-9)
    ann_vol = math.sqrt(max(period_var, 0.0)) * math.sqrt(bars_per_year)
    sharpe = (period_mean * bars_per_year / max(ann_vol, 1e-12)) if ann_vol > 0.0 else 0.0
    return_to_dd = total_return / max(max_dd, 1e-9) if max_dd > 0.0 else 0.0
    calmar = cagr / max(max_dd, 1e-9) if max_dd > 0.0 else 0.0
    worst_year = min(by_year_return.values()) if by_year_return else 0.0
    p05 = _quantile(returns_clean, 0.05)
    p01 = _quantile(returns_clean, 0.01)
    symbol_period_summary = {
        symbol: {
            "avg_abs_exposure": round(symbol_abs_exposure_sum.get(symbol, 0.0) / max(period_count, 1), 4),
            "long_periods": int(symbol_long_periods.get(symbol, 0)),
            "short_periods": int(symbol_short_periods.get(symbol, 0)),
        }
        for symbol in config.symbol_weights
    }
    if period_count <= 0 or years < 1.0:
        decision = "REJECT_SAMPLE"
    elif equity <= 1e-6:
        decision = "REJECT_BANKRUPT"
    elif total_return <= 0.0:
        decision = "REJECT_NEGATIVE"
    elif max_dd > 0.80:
        decision = "REJECT_DRAWDOWN"
    elif cagr >= 0.45 and calmar >= 0.80 and positive_year_fraction >= 0.70:
        decision = "PAPER_RESEARCH"
    elif cagr >= 0.25 and calmar >= 0.45:
        decision = "WATCH"
    else:
        decision = "REJECT_WEAK"
    return {
        "model_id": config.name,
        "decision": decision,
        "periods": period_count,
        "first_exec_ts": first_exec_ts.isoformat() if first_exec_ts else None,
        "last_period_ts": last_period_ts.isoformat() if last_period_ts else None,
        "years": round(years, 4),
        "total_return_pct": round(total_return * 100.0, 4),
        "cagr_pct": round(cagr * 100.0, 4),
        "max_drawdown_pct": round(max_dd * 100.0, 4),
        "return_to_dd": round(return_to_dd, 4),
        "calmar": round(calmar, 4),
        "sharpe_like": round(sharpe, 4),
        "annualized_vol_pct": round(ann_vol * 100.0, 4),
        "min_equity": round(min_equity, 6),
        "worst_year_pct": round(worst_year * 100.0, 4),
        "positive_year_count": positive_years,
        "year_count": len(by_year_return),
        "positive_year_fraction": round(positive_year_fraction, 4),
        "by_year_return_pct": {year: round(value * 100.0, 4) for year, value in by_year_return.items()},
        "rebalance_count": rebalance_count,
        "rebalances_per_year": round(rebalance_count / years, 2),
        "win_rate_period": round(win_rate, 4),
        "active_fraction": round(active_periods / max(period_count, 1), 4),
        "avg_gross_exposure": round(avg_gross, 4),
        "avg_net_exposure": round(avg_net, 4),
        "avg_short_exposure": round(avg_short, 4),
        "turnover_sum": round(turnover_sum, 4),
        "avg_daily_turnover": round(turnover_sum / common_days, 4),
        "cost_drag_pct_simple_sum": round(cost_drag * 100.0, 4),
        "holding_cost_drag_pct_simple_sum": round(holding_cost_drag * 100.0, 4),
        "short_cost_drag_pct_simple_sum": round(short_cost_drag * 100.0, 4),
        "funding_pnl_pct_simple_sum": round(funding_pnl * 100.0, 4),
        "p05_period_return_pct": round(p05 * 100.0, 4) if math.isfinite(p05) else None,
        "p01_period_return_pct": round(p01 * 100.0, 4) if math.isfinite(p01) else None,
        "avg_risk_scale": round(risk_scale_sum / max(risk_scale_count, 1), 4),
        "drawdown_guard_periods": int(drawdown_guard_periods),
        "vol_target_periods": int(vol_target_periods),
        "direction_periods": dict(direction_periods),
        "symbol_period_summary": symbol_period_summary,
        "rebalance_samples": samples,
    }


def _risk_profiles(interval: str) -> list[dict[str, float | int | str]]:
    return [
        {
            "tag": "g1",
            "gross": 1.0,
            "dd": 0.0,
            "dd_scale": 1.0,
            "vt": 0.0,
            "vt_mode": "all",
            "vt_lb": _hours_to_bars(interval, 720),
            "vt_min": 0.0,
            "vt_max": 1.0,
        },
        {
            "tag": "g2",
            "gross": 2.0,
            "dd": 0.0,
            "dd_scale": 1.0,
            "vt": 0.0,
            "vt_mode": "all",
            "vt_lb": _hours_to_bars(interval, 720),
            "vt_min": 0.0,
            "vt_max": 1.0,
        },
        {
            "tag": "g3_dd20",
            "gross": 3.0,
            "dd": 20.0,
            "dd_scale": 0.35,
            "vt": 0.0,
            "vt_mode": "all",
            "vt_lb": _hours_to_bars(interval, 720),
            "vt_min": 0.0,
            "vt_max": 1.0,
        },
        {
            "tag": "g4_dd20_down60",
            "gross": 4.0,
            "dd": 20.0,
            "dd_scale": 0.35,
            "vt": 60.0,
            "vt_mode": "downside",
            "vt_lb": _hours_to_bars(interval, 720),
            "vt_min": 0.0,
            "vt_max": 1.0,
        },
        {
            "tag": "g5_dd20_down60",
            "gross": 5.0,
            "dd": 20.0,
            "dd_scale": 0.30,
            "vt": 60.0,
            "vt_mode": "downside",
            "vt_lb": _hours_to_bars(interval, 720),
            "vt_min": 0.0,
            "vt_max": 1.0,
        },
        {
            "tag": "g5_dd12_down45",
            "gross": 5.0,
            "dd": 12.0,
            "dd_scale": 0.25,
            "vt": 45.0,
            "vt_mode": "downside",
            "vt_lb": _hours_to_bars(interval, 720),
            "vt_min": 0.0,
            "vt_max": 1.0,
        },
        {
            "tag": "g6_dd25_down75",
            "gross": 6.0,
            "dd": 25.0,
            "dd_scale": 0.25,
            "vt": 75.0,
            "vt_mode": "downside",
            "vt_lb": _hours_to_bars(interval, 720),
            "vt_min": 0.0,
            "vt_max": 1.0,
        },
    ]


def build_configs(interval: str) -> list[DirectionalConfig]:
    sleeves: list[tuple[str, dict[str, float]]] = [
        ("btc100", {"BTCUSDT": 1.0}),
        ("btce6040", {"BTCUSDT": 0.60, "ETHUSDT": 0.40}),
        ("btce5050", {"BTCUSDT": 0.50, "ETHUSDT": 0.50}),
        ("btes503020", {"BTCUSDT": 0.50, "ETHUSDT": 0.30, "SOLUSDT": 0.20}),
        ("btes_equal", {"BTCUSDT": 1.0 / 3.0, "ETHUSDT": 1.0 / 3.0, "SOLUSDT": 1.0 / 3.0}),
    ]
    signal_presets: list[tuple[str, str, dict[str, float | int | str | bool]]] = []
    for fast_h, slow_h, threshold in (
        (48, 240, 0.0),
        (96, 480, 0.0),
        (168, 720, 0.15),
    ):
        signal_presets.append(
            (
                f"ema_f{fast_h}_s{slow_h}_t{str(threshold).replace('.', 'p')}",
                "ema_ls",
                {
                    "fast": _hours_to_bars(interval, fast_h),
                    "slow": _hours_to_bars(interval, slow_h),
                    "atr": _hours_to_bars(interval, 84),
                    "threshold": threshold,
                    "btc_guard": "trend_bias",
                    "btc_guard_ema": _hours_to_bars(interval, 720),
                    "short_in_bull_scale": 0.50,
                    "long_in_bear_scale": 0.35,
                },
            )
        )
    for entry_h, exit_h, always_in in (
        (240, 96, False),
        (480, 168, False),
        (720, 240, True),
    ):
        signal_presets.append(
            (
                f"donchian_e{entry_h}_x{exit_h}_{'ai' if always_in else 'flat'}",
                "donchian_flip",
                {
                    "entry": _hours_to_bars(interval, entry_h),
                    "exit": _hours_to_bars(interval, exit_h),
                    "always_in": always_in,
                    "btc_guard": "trend_bias",
                    "btc_guard_ema": _hours_to_bars(interval, 720),
                    "short_in_bull_scale": 0.50,
                    "long_in_bear_scale": 0.35,
                },
            )
        )
    for atr_h, mult in ((96, 2.5), (168, 3.0), (240, 3.5)):
        signal_presets.append(
            (
                f"supertrend_a{atr_h}_m{str(mult).replace('.', 'p')}",
                "supertrend",
                {
                    "atr": _hours_to_bars(interval, atr_h),
                    "mult": mult,
                    "btc_guard": "trend_bias",
                    "btc_guard_ema": _hours_to_bars(interval, 720),
                    "short_in_bull_scale": 0.50,
                    "long_in_bear_scale": 0.35,
                },
            )
        )
    for fast_h, slow_h, funding_threshold in (
        (96, 480, 0.0010),
        (168, 720, 0.0015),
        (240, 960, 0.0025),
    ):
        signal_presets.append(
            (
                f"trendfund_f{fast_h}_s{slow_h}_ft{str(funding_threshold).replace('.', 'p')}",
                "trend_funding",
                {
                    "fast": _hours_to_bars(interval, fast_h),
                    "slow": _hours_to_bars(interval, slow_h),
                    "atr": _hours_to_bars(interval, 84),
                    "trend_threshold": 0.10,
                    "funding_lookback": _hours_to_bars(interval, 168),
                    "funding_threshold": funding_threshold,
                    "carry_only_scale": 0.35,
                    "against_carry_scale": 0.35,
                    "btc_guard": "trend_bias",
                    "btc_guard_ema": _hours_to_bars(interval, 720),
                    "short_in_bull_scale": 0.50,
                    "long_in_bear_scale": 0.35,
                },
            )
        )
    for funding_threshold in (0.0010, 0.0015, 0.0025):
        signal_presets.append(
            (
                f"funding_carry_ft{str(funding_threshold).replace('.', 'p')}",
                "funding_carry",
                {
                    "funding_lookback": _hours_to_bars(interval, 168),
                    "funding_threshold": funding_threshold,
                    "btc_guard": "none",
                },
            )
        )
    for tag, params in (
        (
            "ensemble_bal",
            {
                "fast": _hours_to_bars(interval, 96),
                "slow": _hours_to_bars(interval, 480),
                "atr": _hours_to_bars(interval, 84),
                "trend_threshold": 0.10,
                "entry": _hours_to_bars(interval, 480),
                "exit": _hours_to_bars(interval, 168),
                "always_in": False,
                "st_atr": _hours_to_bars(interval, 168),
                "st_mult": 3.0,
                "funding_lookback": _hours_to_bars(interval, 168),
                "funding_threshold": 0.0015,
                "rsi": 14,
                "rsi_lower": 35.0,
                "rsi_upper": 65.0,
                "full_score": 2.0,
                "half_score": 1.0,
                "trend_weight": 1.0,
                "breakout_weight": 1.0,
                "supertrend_weight": 1.0,
                "carry_weight": 0.5,
                "pullback_weight": 0.5,
                "btc_guard": "trend_bias",
                "btc_guard_ema": _hours_to_bars(interval, 720),
                "short_in_bull_scale": 0.50,
                "long_in_bear_scale": 0.35,
            },
        ),
        (
            "ensemble_strict",
            {
                "fast": _hours_to_bars(interval, 168),
                "slow": _hours_to_bars(interval, 720),
                "atr": _hours_to_bars(interval, 84),
                "trend_threshold": 0.15,
                "entry": _hours_to_bars(interval, 720),
                "exit": _hours_to_bars(interval, 240),
                "always_in": False,
                "st_atr": _hours_to_bars(interval, 240),
                "st_mult": 3.5,
                "funding_lookback": _hours_to_bars(interval, 168),
                "funding_threshold": 0.0020,
                "rsi": 14,
                "rsi_lower": 33.0,
                "rsi_upper": 67.0,
                "full_score": 2.5,
                "half_score": 1.5,
                "trend_weight": 1.0,
                "breakout_weight": 1.0,
                "supertrend_weight": 1.0,
                "carry_weight": 0.5,
                "pullback_weight": 0.5,
                "btc_guard": "trend_bias",
                "btc_guard_ema": _hours_to_bars(interval, 720),
                "short_in_bull_scale": 0.35,
                "long_in_bear_scale": 0.25,
            },
        ),
        (
            "ensemble_fast",
            {
                "fast": _hours_to_bars(interval, 48),
                "slow": _hours_to_bars(interval, 240),
                "atr": _hours_to_bars(interval, 84),
                "trend_threshold": 0.05,
                "entry": _hours_to_bars(interval, 240),
                "exit": _hours_to_bars(interval, 96),
                "always_in": False,
                "st_atr": _hours_to_bars(interval, 96),
                "st_mult": 2.5,
                "funding_lookback": _hours_to_bars(interval, 168),
                "funding_threshold": 0.0010,
                "rsi": 14,
                "rsi_lower": 37.0,
                "rsi_upper": 63.0,
                "full_score": 2.0,
                "half_score": 1.0,
                "trend_weight": 1.0,
                "breakout_weight": 1.0,
                "supertrend_weight": 1.0,
                "carry_weight": 0.5,
                "pullback_weight": 0.5,
                "btc_guard": "trend_bias",
                "btc_guard_ema": _hours_to_bars(interval, 720),
                "short_in_bull_scale": 0.50,
                "long_in_bear_scale": 0.35,
            },
        ),
    ):
        signal_presets.append((tag, "ensemble_grade", params))

    configs: list[DirectionalConfig] = []
    for sleeve_name, symbol_weights in sleeves:
        for signal_tag, signal_mode, signal_params in signal_presets:
            for risk in _risk_profiles(interval):
                name = f"{sleeve_name}_{signal_tag}_{risk['tag']}"
                configs.append(
                    DirectionalConfig(
                        name=name,
                        interval=interval,
                        sleeve=sleeve_name,
                        symbol_weights=symbol_weights,
                        signal_mode=signal_mode,
                        signal_params=signal_params,
                        gross_leverage=float(risk["gross"]),
                        rebalance_bars=_hours_to_bars(interval, 24),
                        drawdown_guard_pct=float(risk["dd"]),
                        drawdown_risk_scale=float(risk["dd_scale"]),
                        vol_target_annual_pct=float(risk["vt"]),
                        vol_target_mode=str(risk["vt_mode"]),
                        vol_lookback_bars=int(risk["vt_lb"]),
                        vol_min_scale=float(risk["vt_min"]),
                        vol_max_scale=float(risk["vt_max"]),
                    )
                )
    return configs


def _scenario_args(args: argparse.Namespace) -> list[dict[str, float | str]]:
    return [
        {
            "name": "default",
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": float(args.slippage_bps_per_side),
            "holding_cost_bps_per_day": float(args.holding_cost_bps_per_day),
            "short_cost_bps_per_day": float(args.short_cost_bps_per_day),
        },
        {
            "name": "slip5",
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": 5.0,
            "holding_cost_bps_per_day": float(args.holding_cost_bps_per_day),
            "short_cost_bps_per_day": float(args.short_cost_bps_per_day),
        },
        {
            "name": "slip10",
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": 10.0,
            "holding_cost_bps_per_day": float(args.holding_cost_bps_per_day),
            "short_cost_bps_per_day": float(args.short_cost_bps_per_day),
        },
        {
            "name": "short5_slip5",
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": 5.0,
            "holding_cost_bps_per_day": float(args.holding_cost_bps_per_day),
            "short_cost_bps_per_day": 5.0,
        },
    ]


def _load_frame(args: argparse.Namespace) -> tuple[rot.MarketFrame, dict[str, Any]]:
    settings = get_settings()
    base_url = str(args.base_url or settings.binance_rest_base_url)
    symbols = [symbol for symbol in _csv(args.symbols) if symbol]
    bars_by_symbol = {
        symbol: _load_bars(
            symbol=symbol,
            interval=str(args.interval),
            days=int(args.days),
            cache_dir=ROOT_DIR / str(args.cache_dir),
            base_url=base_url,
            sleep_seconds=float(args.sleep_seconds),
        )
        for symbol in symbols
    }
    frame, meta = rot._align_dynamic_frame(str(args.interval), bars_by_symbol)
    if frame is None:
        raise RuntimeError(f"frame_alignment_failed:{meta}")
    return frame, meta


def _load_funding(
    args: argparse.Namespace,
    frame: rot.MarketFrame,
) -> dict[str, list[float]]:
    if not bool(args.apply_funding):
        return {}
    settings = get_settings()
    base_url = str(args.base_url or settings.binance_rest_base_url)
    cache_dir = ROOT_DIR / str(args.funding_cache_dir)
    raw = {
        symbol: rot._load_funding_rates(
            symbol=symbol,
            start_ms=int(frame.open_ms[0]),
            end_ms=int(frame.open_ms[-1]),
            cache_dir=cache_dir,
            base_url=base_url,
            sleep_seconds=float(args.sleep_seconds),
        )
        for symbol in frame.symbols
    }
    return rot._build_funding_period_rates(frame, raw)


def _aggregate_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_name.setdefault(str(row["config"]["name"]), []).append(row)
    out: list[dict[str, Any]] = []
    for name, items in by_name.items():
        xs = [1.0 + float(item["summary"]["total_return_pct"]) / 100.0 for item in items]
        if not xs:
            continue
        default = next((item for item in items if item["scenario"] == "default"), items[0])
        out.append(
            {
                "name": name,
                "min_x": round(min(xs), 6),
                "geo_x": round(math.prod(xs) ** (1.0 / len(xs)), 6),
                "max_x": round(max(xs), 6),
                "default_x": round(1.0 + float(default["summary"]["total_return_pct"]) / 100.0, 6),
                "max_drawdown_pct": round(max(float(item["summary"]["max_drawdown_pct"]) for item in items), 4),
                "worst_year_pct": round(min(float(item["summary"]["worst_year_pct"]) for item in items), 4),
                "avg_gross_exposure": float(default["summary"]["avg_gross_exposure"]),
                "turnover_sum": float(default["summary"]["turnover_sum"]),
                "decision_default": str(default["summary"]["decision"]),
                "config": default["config"],
            }
        )
    return sorted(out, key=lambda item: (item["geo_x"], item["min_x"]), reverse=True)


def main() -> int:
    args = _parse_args()
    frame, frame_meta = _load_frame(args)
    print(
        json.dumps(
            {
                "stage": "loaded_frame",
                "symbols": frame.symbols,
                "bars": len(frame.ts),
                "first": frame.ts[0].isoformat(),
                "last": frame.ts[-1].isoformat(),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    funding_period_rates = _load_funding(args, frame)
    engines = {symbol: SymbolFeatureEngine(frame, symbol) for symbol in frame.symbols}
    configs = build_configs(str(args.interval))
    if int(args.max_configs) > 0:
        configs = configs[: int(args.max_configs)]
    scenarios = _scenario_args(args)
    all_results: list[dict[str, Any]] = []
    for cfg_idx, config in enumerate(configs, start=1):
        if cfg_idx % 50 == 0:
            print(json.dumps({"stage": "progress", "config": cfg_idx, "total": len(configs)}), flush=True)
        for scenario in scenarios:
            summary = backtest_directional_config(
                frame,
                engines,
                config,
                funding_period_rates=funding_period_rates,
                fee_bps_per_side=float(scenario["fee_bps_per_side"]),
                slippage_bps_per_side=float(scenario["slippage_bps_per_side"]),
                holding_cost_bps_per_day=float(scenario["holding_cost_bps_per_day"]),
                short_cost_bps_per_day=float(scenario["short_cost_bps_per_day"]),
            )
            all_results.append(
                {
                    "scenario": str(scenario["name"]),
                    "scenario_params": scenario,
                    "config": asdict(config),
                    "summary": summary,
                }
            )
    aggregate = _aggregate_results(all_results)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "research_scope": {
            "rotation_excluded": True,
            "description": "Fixed symbol sleeves; every asset acts only on its own signal. No top-k selection, relative ranking, or capital rotation.",
        },
        "args": vars(args),
        "frame_meta": frame_meta,
        "scenario_count": len(scenarios),
        "config_count": len(configs),
        "all_results": all_results,
        "top_robust": aggregate[:50],
        "top_risk_filtered": [
            item
            for item in aggregate
            if float(item["min_x"]) >= 3.0 and float(item["max_drawdown_pct"]) <= 35.0
        ][:50],
    }
    report_dir = ROOT_DIR / str(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    latest_path = report_dir / "latest.json"
    atomic_write_text(latest_path, json.dumps(payload, ensure_ascii=False, indent=2))
    print(json.dumps({"stage": "done", "report": str(latest_path), "top": aggregate[:10]}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
