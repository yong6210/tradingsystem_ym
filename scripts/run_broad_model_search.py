#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter, deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import CURRENT_MICRO_LIVE_SYMBOLS, get_settings
from app.services.report_io import atomic_write_text

Direction = Literal["long", "short"]

_INTERVAL_MS = {
    "15m": 15 * 60 * 1000,
    "30m": 30 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "2h": 2 * 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
}

_ROUND_TRIP_FEE_RATE = 0.0006


@dataclass(frozen=True, slots=True)
class Bar:
    ts: datetime
    open_ms: int
    o: float
    h: float
    l: float
    c: float
    v: float


@dataclass(frozen=True, slots=True)
class ModelConfig:
    model_id: str
    family: str
    interval: str
    fast: int = 0
    slow: int = 0
    lookback: int = 0
    stop_lookback: int = 0
    swing_lookback: int = 0
    dev_atr: float = 0.0
    trend_strength_atr: float = 0.0
    pullback_atr: float = 0.0
    stop_buffer_atr: float = 0.0
    rr: float = 2.0
    max_hold_bars: int = 24
    min_stop_pct: float = 0.0015
    max_stop_pct: float = 0.03
    trend_filter: bool = True


@dataclass(slots=True)
class Trade:
    model_id: str
    family: str
    symbol: str
    interval: str
    direction: Direction
    entry_ts: datetime
    exit_ts: datetime
    entry: float
    exit: float
    stop: float
    target: float
    r_value: float
    gross_r: float
    cost_r: float
    stop_pct: float
    hold_bars: int
    exit_reason: str


class SymbolFeatures:
    def __init__(self, bars: list[Bar]):
        self.bars = list(bars)
        self.o = [bar.o for bar in bars]
        self.h = [bar.h for bar in bars]
        self.l = [bar.l for bar in bars]
        self.c = [bar.c for bar in bars]
        self.v = [bar.v for bar in bars]
        self.ts = [bar.ts for bar in bars]
        self.atr = self._atr(14)
        self._ema_cache: dict[int, list[float]] = {}
        self._high_cache: dict[int, list[float]] = {}
        self._low_cache: dict[int, list[float]] = {}
        self._vol_sma_cache: dict[int, list[float]] = {}

    def ema(self, length: int) -> list[float]:
        length = max(int(length), 1)
        cached = self._ema_cache.get(length)
        if cached is not None:
            return cached
        alpha = 2.0 / (length + 1.0)
        out: list[float] = []
        ema = self.c[0] if self.c else 0.0
        for close in self.c:
            ema = alpha * close + (1.0 - alpha) * ema
            out.append(float(ema))
        self._ema_cache[length] = out
        return out

    def rolling_high_prev(self, lookback: int) -> list[float]:
        lookback = max(int(lookback), 1)
        cached = self._high_cache.get(lookback)
        if cached is not None:
            return cached
        out = [0.0] * len(self.h)
        q: deque[int] = deque()
        for idx, value in enumerate(self.h):
            while q and q[0] <= idx - lookback - 1:
                q.popleft()
            out[idx] = self.h[q[0]] if q else value
            while q and self.h[q[-1]] <= value:
                q.pop()
            q.append(idx)
        self._high_cache[lookback] = out
        return out

    def rolling_low_prev(self, lookback: int) -> list[float]:
        lookback = max(int(lookback), 1)
        cached = self._low_cache.get(lookback)
        if cached is not None:
            return cached
        out = [0.0] * len(self.l)
        q: deque[int] = deque()
        for idx, value in enumerate(self.l):
            while q and q[0] <= idx - lookback - 1:
                q.popleft()
            out[idx] = self.l[q[0]] if q else value
            while q and self.l[q[-1]] >= value:
                q.pop()
            q.append(idx)
        self._low_cache[lookback] = out
        return out

    def volume_sma_prev(self, lookback: int) -> list[float]:
        lookback = max(int(lookback), 1)
        cached = self._vol_sma_cache.get(lookback)
        if cached is not None:
            return cached
        out: list[float] = []
        total = 0.0
        q: deque[float] = deque()
        for value in self.v:
            out.append(total / len(q) if q else value)
            q.append(float(value))
            total += float(value)
            if len(q) > lookback:
                total -= q.popleft()
        self._vol_sma_cache[lookback] = out
        return out

    def _atr(self, length: int) -> list[float]:
        if len(self.bars) < 2:
            return [0.0] * len(self.bars)
        out = [0.0]
        trs: list[float] = []
        prev_close = self.c[0]
        for idx in range(1, len(self.bars)):
            tr = max(
                self.h[idx] - self.l[idx],
                abs(self.h[idx] - prev_close),
                abs(self.l[idx] - prev_close),
            )
            trs.append(float(tr))
            prev_close = self.c[idx]
            recent = trs[-length:]
            out.append(float(sum(recent) / len(recent)))
        return out


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only broad model search across slower structural SL/TP variants."
    )
    parser.add_argument("--symbols", default=CURRENT_MICRO_LIVE_SYMBOLS)
    parser.add_argument("--stage1-symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,AVAXUSDT,LINKUSDT,DOGEUSDT")
    parser.add_argument("--stage1-days", type=int, default=365)
    parser.add_argument("--stage2-days", type=int, default=1095)
    parser.add_argument("--stage2-top", type=int, default=160)
    parser.add_argument("--intervals", default="1h,4h")
    parser.add_argument("--cache-dir", default="reports/validation/broad_model_search/cache")
    parser.add_argument("--report-dir", default="reports/validation/broad_model_search")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--max-stage1-models", type=int, default=0)
    parser.add_argument("--min-stage2-trades", type=int, default=80)
    return parser.parse_args()


def _csv(raw: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in str(raw or "").split(","):
        value = item.strip().upper()
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _fetch_klines(
    client: httpx.Client,
    *,
    symbol: str,
    interval: str,
    start_ts: datetime,
    end_ts: datetime,
    sleep_seconds: float,
) -> list[Bar]:
    interval_ms = _INTERVAL_MS[interval]
    start_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000)
    rows: list[Bar] = []
    while start_ms <= end_ms:
        response: httpx.Response | None = None
        for attempt in range(6):
            response = client.get(
                "/fapi/v1/klines",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "limit": 1500,
                    "startTime": start_ms,
                    "endTime": end_ms,
                },
            )
            if response.status_code not in {418, 429}:
                break
            retry_after = float(response.headers.get("Retry-After", "0") or 0.0)
            time.sleep(retry_after if retry_after > 0 else min(2 ** attempt, 30))
        if response is None:
            raise RuntimeError("binance_request_missing_response")
        response.raise_for_status()
        payload = response.json()
        if not payload:
            break
        for item in payload:
            open_ms = int(item[0])
            if open_ms < start_ms or open_ms > end_ms:
                continue
            rows.append(
                Bar(
                    ts=datetime.fromtimestamp(open_ms / 1000, tz=UTC),
                    open_ms=open_ms,
                    o=float(item[1]),
                    h=float(item[2]),
                    l=float(item[3]),
                    c=float(item[4]),
                    v=float(item[5]),
                )
            )
        next_start = int(payload[-1][0]) + interval_ms
        if next_start <= start_ms:
            break
        start_ms = next_start
        time.sleep(max(float(sleep_seconds), 0.0))
    return rows


def _load_bars(
    client: httpx.Client,
    *,
    symbol: str,
    interval: str,
    days: int,
    cache_dir: Path,
    sleep_seconds: float,
) -> list[Bar]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    end_ts = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    start_ts = end_ts - timedelta(days=max(int(days), 1) + 5)
    cache_path = cache_dir / f"{symbol}_{interval}_{int(days)}d.json"
    if cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_end = datetime.fromisoformat(str(payload.get("end_ts")).replace("Z", "+00:00"))
            if cached_end.tzinfo is None:
                cached_end = cached_end.replace(tzinfo=UTC)
            if cached_end >= end_ts - timedelta(hours=8):
                return [
                    Bar(
                        ts=datetime.fromisoformat(str(row["ts"]).replace("Z", "+00:00")).astimezone(UTC),
                        open_ms=int(row["open_ms"]),
                        o=float(row["o"]),
                        h=float(row["h"]),
                        l=float(row["l"]),
                        c=float(row["c"]),
                        v=float(row["v"]),
                    )
                    for row in payload.get("rows", [])
                ]
        except Exception:
            pass

    rows = _fetch_klines(
        client,
        symbol=symbol,
        interval=interval,
        start_ts=start_ts,
        end_ts=end_ts,
        sleep_seconds=sleep_seconds,
    )
    rows = [row for row in rows if row.ts >= end_ts - timedelta(days=max(int(days), 1))]
    atomic_write_text(
        cache_path,
        json.dumps(
            {
                "symbol": symbol,
                "interval": interval,
                "days": int(days),
                "start_ts": start_ts.isoformat(),
                "end_ts": end_ts.isoformat(),
                "rows": [
                    {
                        "ts": row.ts.isoformat(),
                        "open_ms": row.open_ms,
                        "o": row.o,
                        "h": row.h,
                        "l": row.l,
                        "c": row.c,
                        "v": row.v,
                    }
                    for row in rows
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )
    return rows


def _max_hold_options(interval: str) -> tuple[int, ...]:
    if interval == "15m":
        return (16, 32, 64, 96)
    if interval == "30m":
        return (12, 24, 48, 96)
    if interval == "2h":
        return (12, 24, 48)
    if interval == "4h":
        return (12, 24, 48)
    return (24, 48, 96)


def _min_stop_options(interval: str) -> tuple[float, ...]:
    if interval in {"15m", "30m"}:
        return (0.003, 0.004, 0.005, 0.0075)
    if interval == "1h":
        return (0.0025, 0.0035, 0.005)
    return (0.0015, 0.0025, 0.004)


def build_model_configs(intervals: list[str]) -> list[ModelConfig]:
    configs: list[ModelConfig] = []

    def add(config: ModelConfig) -> None:
        configs.append(config)

    for interval in intervals:
        for fast, slow in ((20, 100), (34, 150), (50, 200)):
            for trend in (0.25, 0.55):
                for pullback in (0.20, 0.50):
                    for swing in (6, 12, 24):
                        for buffer in (0.10, 0.25):
                            for rr in (1.5, 2.0, 2.5, 3.0):
                                for max_hold in _max_hold_options(interval):
                                    for min_stop in _min_stop_options(interval):
                                        add(
                                            ModelConfig(
                                                model_id=(
                                                    f"{interval}:trend_pullback:"
                                                    f"ema{fast}_{slow}:tr{trend}:pb{pullback}:sw{swing}:"
                                                    f"buf{buffer}:rr{rr}:hold{max_hold}:min{min_stop}"
                                                ),
                                                family="trend_pullback",
                                                interval=interval,
                                                fast=fast,
                                                slow=slow,
                                                trend_strength_atr=trend,
                                                pullback_atr=pullback,
                                                swing_lookback=swing,
                                                stop_buffer_atr=buffer,
                                                rr=rr,
                                                max_hold_bars=max_hold,
                                                min_stop_pct=min_stop,
                                                max_stop_pct=0.035,
                                                trend_filter=True,
                                            )
                                        )

        for lookback in (20, 55, 100):
            for stop_lookback in (10, 20, 40):
                for buffer in (0.10, 0.25, 0.40):
                    for rr in (2.0, 3.0, 4.0):
                        for max_hold in _max_hold_options(interval):
                            for trend_filter in (False, True):
                                for min_stop in _min_stop_options(interval):
                                    fast, slow = (20, 100)
                                    add(
                                        ModelConfig(
                                            model_id=(
                                                f"{interval}:donchian_breakout:lb{lookback}:stop{stop_lookback}:"
                                                f"buf{buffer}:rr{rr}:hold{max_hold}:trend{int(trend_filter)}:min{min_stop}"
                                            ),
                                            family="donchian_breakout",
                                            interval=interval,
                                            fast=fast,
                                            slow=slow,
                                            lookback=lookback,
                                            stop_lookback=stop_lookback,
                                            stop_buffer_atr=buffer,
                                            rr=rr,
                                            max_hold_bars=max_hold,
                                            min_stop_pct=min_stop,
                                            max_stop_pct=0.05,
                                            trend_filter=trend_filter,
                                        )
                                    )

        for slow in (50, 100, 200):
            for dev in (1.5, 2.0, 2.5, 3.0):
                for swing in (6, 12, 24):
                    for buffer in (0.10, 0.25):
                        for rr in (1.0, 1.5, 2.0):
                            for max_hold in _max_hold_options(interval):
                                for trend_filter in (False, True):
                                    for min_stop in _min_stop_options(interval):
                                        add(
                                            ModelConfig(
                                                model_id=(
                                                    f"{interval}:mean_reversion:ema{slow}:dev{dev}:sw{swing}:"
                                                    f"buf{buffer}:rr{rr}:hold{max_hold}:trend{int(trend_filter)}:min{min_stop}"
                                                ),
                                                family="mean_reversion",
                                                interval=interval,
                                                fast=20,
                                                slow=slow,
                                                swing_lookback=swing,
                                                dev_atr=dev,
                                                stop_buffer_atr=buffer,
                                                rr=rr,
                                                max_hold_bars=max_hold,
                                                min_stop_pct=min_stop,
                                                max_stop_pct=0.04,
                                                trend_filter=trend_filter,
                                            )
                                        )
    return configs


def _entry_side_signal(features: SymbolFeatures, idx: int, config: ModelConfig) -> tuple[Direction, float, float] | None:
    close = features.c[idx]
    prev_close = features.c[idx - 1]
    atr = max(features.atr[idx], 1e-12)
    high = features.h[idx]
    low = features.l[idx]

    if config.family == "trend_pullback":
        fast = features.ema(config.fast)
        slow = features.ema(config.slow)
        trend_strength = abs(fast[idx] - slow[idx]) / atr
        if trend_strength < config.trend_strength_atr:
            return None
        swing_low = features.rolling_low_prev(config.swing_lookback)[idx]
        swing_high = features.rolling_high_prev(config.swing_lookback)[idx]
        if fast[idx] > slow[idx] and fast[idx] >= fast[max(idx - 4, 0)]:
            touched = low <= fast[idx] + config.pullback_atr * atr
            reclaimed = close > fast[idx] and close > prev_close
            if touched and reclaimed:
                stop = min(swing_low, low) - config.stop_buffer_atr * atr
                return "long", close, stop
        if fast[idx] < slow[idx] and fast[idx] <= fast[max(idx - 4, 0)]:
            touched = high >= fast[idx] - config.pullback_atr * atr
            reclaimed = close < fast[idx] and close < prev_close
            if touched and reclaimed:
                stop = max(swing_high, high) + config.stop_buffer_atr * atr
                return "short", close, stop
        return None

    if config.family == "donchian_breakout":
        channel_high = features.rolling_high_prev(config.lookback)[idx]
        channel_low = features.rolling_low_prev(config.lookback)[idx]
        stop_low = features.rolling_low_prev(config.stop_lookback)[idx]
        stop_high = features.rolling_high_prev(config.stop_lookback)[idx]
        fast = features.ema(config.fast)
        slow = features.ema(config.slow)
        vol_sma = features.volume_sma_prev(20)[idx]
        volume_ok = features.v[idx] >= max(vol_sma * 0.8, 1e-12)
        long_trend_ok = (not config.trend_filter) or fast[idx] > slow[idx]
        short_trend_ok = (not config.trend_filter) or fast[idx] < slow[idx]
        if volume_ok and close > channel_high and close > prev_close and long_trend_ok:
            stop = min(stop_low, low) - config.stop_buffer_atr * atr
            return "long", close, stop
        if volume_ok and close < channel_low and close < prev_close and short_trend_ok:
            stop = max(stop_high, high) + config.stop_buffer_atr * atr
            return "short", close, stop
        return None

    if config.family == "mean_reversion":
        ema = features.ema(config.slow)
        fast = features.ema(config.fast)
        slow = features.ema(config.slow)
        z = (close - ema[idx]) / atr
        swing_low = features.rolling_low_prev(config.swing_lookback)[idx]
        swing_high = features.rolling_high_prev(config.swing_lookback)[idx]
        range_ok = True
        if config.trend_filter:
            range_ok = abs(fast[idx] - slow[idx]) / atr <= 0.70
        if range_ok and z <= -config.dev_atr and close > prev_close:
            stop = min(swing_low, low) - config.stop_buffer_atr * atr
            return "long", close, stop
        if range_ok and z >= config.dev_atr and close < prev_close:
            stop = max(swing_high, high) + config.stop_buffer_atr * atr
            return "short", close, stop
        return None

    return None


def _simulate_trade(
    *,
    features: SymbolFeatures,
    symbol: str,
    signal_idx: int,
    direction: Direction,
    stop: float,
    config: ModelConfig,
) -> Trade | None:
    entry_idx = signal_idx + 1
    if entry_idx >= len(features.bars):
        return None
    entry = features.o[entry_idx]
    if entry <= 0.0:
        return None
    risk_abs = entry - stop if direction == "long" else stop - entry
    if risk_abs <= 0.0:
        return None
    stop_pct = risk_abs / entry
    if stop_pct < config.min_stop_pct or stop_pct > config.max_stop_pct:
        return None
    target = entry + config.rr * risk_abs if direction == "long" else entry - config.rr * risk_abs
    cost_r = _ROUND_TRIP_FEE_RATE * entry / risk_abs
    exit_idx = min(entry_idx + config.max_hold_bars, len(features.bars) - 1)
    exit_price = features.c[exit_idx]
    exit_reason = "time_exit"
    hit_idx = exit_idx

    for idx in range(entry_idx, min(entry_idx + config.max_hold_bars + 1, len(features.bars))):
        if direction == "long":
            hit_stop = features.l[idx] <= stop
            hit_target = features.h[idx] >= target
            if hit_stop and hit_target:
                exit_price = stop
                exit_reason = "stop_first_same_bar"
                hit_idx = idx
                break
            if hit_stop:
                exit_price = stop
                exit_reason = "stop"
                hit_idx = idx
                break
            if hit_target:
                exit_price = target
                exit_reason = "target"
                hit_idx = idx
                break
        else:
            hit_stop = features.h[idx] >= stop
            hit_target = features.l[idx] <= target
            if hit_stop and hit_target:
                exit_price = stop
                exit_reason = "stop_first_same_bar"
                hit_idx = idx
                break
            if hit_stop:
                exit_price = stop
                exit_reason = "stop"
                hit_idx = idx
                break
            if hit_target:
                exit_price = target
                exit_reason = "target"
                hit_idx = idx
                break

    gross_r = (exit_price - entry) / risk_abs if direction == "long" else (entry - exit_price) / risk_abs
    r_value = gross_r - cost_r
    return Trade(
        model_id=config.model_id,
        family=config.family,
        symbol=symbol,
        interval=config.interval,
        direction=direction,
        entry_ts=features.ts[entry_idx],
        exit_ts=features.ts[hit_idx],
        entry=entry,
        exit=exit_price,
        stop=stop,
        target=target,
        r_value=float(r_value),
        gross_r=float(gross_r),
        cost_r=float(cost_r),
        stop_pct=float(stop_pct),
        hold_bars=max(hit_idx - entry_idx + 1, 1),
        exit_reason=exit_reason,
    )


def backtest_model_for_symbol(symbol: str, features: SymbolFeatures, config: ModelConfig) -> list[Trade]:
    trades: list[Trade] = []
    warmup = max(config.slow, config.lookback, config.stop_lookback, config.swing_lookback, 60) + 2
    idx = warmup
    while idx < len(features.bars) - 2:
        signal = _entry_side_signal(features, idx, config)
        if signal is None:
            idx += 1
            continue
        direction, _, stop = signal
        trade = _simulate_trade(
            features=features,
            symbol=symbol,
            signal_idx=idx,
            direction=direction,
            stop=stop,
            config=config,
        )
        if trade is None:
            idx += 1
            continue
        trades.append(trade)
        idx += max(trade.hold_bars, 1)
    return trades


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(q * (len(ordered) - 1))))
    return float(ordered[idx])


def summarize_trades(trades: list[Trade]) -> dict[str, Any]:
    ordered = sorted(trades, key=lambda trade: (trade.exit_ts, trade.symbol, trade.model_id))
    values = [trade.r_value for trade in ordered]
    gross = [trade.gross_r for trade in ordered]
    costs = [trade.cost_r for trade in ordered]
    stops = [trade.stop_pct for trade in ordered]
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    wins = sum(1 for value in values if value > 0.0)

    by_symbol: dict[str, float] = {}
    by_year: dict[str, float] = {}
    exit_reasons: Counter[str] = Counter()
    for trade in ordered:
        by_symbol[trade.symbol] = by_symbol.get(trade.symbol, 0.0) + trade.r_value
        by_year[str(trade.exit_ts.year)] = by_year.get(str(trade.exit_ts.year), 0.0) + trade.r_value
        exit_reasons[trade.exit_reason] += 1

    closed = len(values)
    positive_symbols = sum(1 for value in by_symbol.values() if value > 0.0)
    positive_years = sum(1 for value in by_year.values() if value > 0.0)
    score = 0.0
    if closed:
        ev = sum(values) / closed
        consistency = (positive_symbols / max(len(by_symbol), 1)) * (positive_years / max(len(by_year), 1))
        score = (sum(values) / max(max_dd, 3.0)) * max(ev, 0.0) * math.log10(closed + 10) * max(consistency, 0.05)
    return {
        "closed": closed,
        "total_r": round(sum(values), 4),
        "gross_r": round(sum(gross), 4),
        "ev_r": round(sum(values) / closed, 4) if closed else 0.0,
        "win_rate": round(wins / closed, 4) if closed else 0.0,
        "max_dd_r": round(max_dd, 4),
        "profit_to_dd": round(sum(values) / max(max_dd, 1e-9), 4) if max_dd > 0.0 else 0.0,
        "avg_cost_r": round(sum(costs) / closed, 4) if closed else 0.0,
        "avg_stop_pct": round(sum(stops) / closed, 6) if closed else 0.0,
        "p25_stop_pct": round(_quantile(stops, 0.25), 6),
        "p50_stop_pct": round(_quantile(stops, 0.50), 6),
        "p75_stop_pct": round(_quantile(stops, 0.75), 6),
        "positive_symbol_count": positive_symbols,
        "symbol_count": len(by_symbol),
        "positive_symbol_fraction": round(positive_symbols / max(len(by_symbol), 1), 4),
        "positive_year_count": positive_years,
        "year_count": len(by_year),
        "positive_year_fraction": round(positive_years / max(len(by_year), 1), 4),
        "by_year_total_r": {key: round(value, 4) for key, value in sorted(by_year.items())},
        "exit_reasons": dict(sorted(exit_reasons.items())),
        "score": round(score, 6),
    }


def _score_stage1(summary: dict[str, Any]) -> float:
    closed = int(summary.get("closed", 0) or 0)
    if closed <= 0:
        return -1e9
    ev = float(summary.get("ev_r", 0.0) or 0.0)
    total = float(summary.get("total_r", 0.0) or 0.0)
    dd = max(float(summary.get("max_dd_r", 0.0) or 0.0), 2.0)
    positive_symbols = float(summary.get("positive_symbol_fraction", 0.0) or 0.0)
    avg_cost = float(summary.get("avg_cost_r", 0.0) or 0.0)
    return (total / dd) * max(ev, -0.1) * math.log10(closed + 10) * max(positive_symbols, 0.05) - max(avg_cost - 0.25, 0.0)


def run_stage(
    *,
    features_by_symbol_interval: dict[tuple[str, str], SymbolFeatures],
    symbols: list[str],
    configs: list[ModelConfig],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for config_idx, config in enumerate(configs, start=1):
        trades: list[Trade] = []
        for symbol in symbols:
            features = features_by_symbol_interval.get((symbol, config.interval))
            if features is None:
                continue
            trades.extend(backtest_model_for_symbol(symbol, features, config))
        summary = summarize_trades(trades)
        rows.append(
            {
                "rank_input_order": config_idx,
                "config": asdict(config),
                "summary": summary,
                "stage1_score": round(_score_stage1(summary), 6),
            }
        )
    return rows


def _top_rows(rows: list[dict[str, Any]], *, limit: int, min_trades: int = 0) -> list[dict[str, Any]]:
    eligible = [
        row
        for row in rows
        if int(dict(row.get("summary") or {}).get("closed", 0) or 0) >= int(min_trades)
    ]
    return sorted(
        eligible,
        key=lambda row: (
            float(dict(row.get("summary") or {}).get("score", 0.0) or 0.0),
            float(row.get("stage1_score", 0.0) or 0.0),
            float(dict(row.get("summary") or {}).get("total_r", 0.0) or 0.0),
        ),
        reverse=True,
    )[: max(int(limit), 0)]


def _config_from_row(row: dict[str, Any]) -> ModelConfig:
    payload = dict(row.get("config") or {})
    return ModelConfig(**payload)


def _load_current_micro_baseline() -> dict[str, Any] | None:
    path = ROOT_DIR / "reports/validation/micro_main_usdt_backtests/micro_main_usdt_backtest_20260517T055009Z_reliable_balanced_31.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    trades: list[dict[str, Any]] = []
    for result in dict(payload.get("results") or {}).values():
        trades.extend(list(dict(result).get("trades") or []))
    values = [float(row.get("r_value") or 0.0) for row in trades]
    costs = [float(row.get("cost_r") or 0.0) for row in trades]
    stops = [float(row.get("stop_distance_pct") or 0.0) for row in trades]
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for row in sorted(trades, key=lambda item: str(item.get("exit_ts") or "")):
        equity += float(row.get("r_value") or 0.0)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "source_path": str(path.relative_to(ROOT_DIR)),
        "summary": {
            "closed": len(values),
            "total_r": round(sum(values), 4),
            "ev_r": round(sum(values) / len(values), 4) if values else 0.0,
            "win_rate": round(sum(1 for value in values if value > 0.0) / len(values), 4) if values else 0.0,
            "max_dd_r": round(max_dd, 4),
            "profit_to_dd": round(sum(values) / max(max_dd, 1e-9), 4) if max_dd > 0.0 else 0.0,
            "avg_cost_r": round(sum(costs) / len(costs), 4) if costs else 0.0,
            "avg_stop_pct": round(sum(stops) / len(stops), 6) if stops else 0.0,
            "p50_stop_pct": round(_quantile(stops, 0.50), 6),
        },
    }


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    generated_at = datetime.now(UTC)
    intervals = [item for item in _csv(args.intervals) if item.lower() in _INTERVAL_MS]
    intervals = [item.lower() for item in intervals] or ["1h", "4h"]
    symbols = _csv(args.symbols)
    stage1_symbols = [symbol for symbol in _csv(args.stage1_symbols) if symbol in set(symbols)] or symbols[:8]
    stage1_days = max(int(args.stage1_days), 30)
    stage2_days = max(int(args.stage2_days), stage1_days)
    cache_dir = ROOT_DIR / str(args.cache_dir)
    base_url = str(args.base_url or settings.binance_rest_base_url or "https://fapi.binance.com").rstrip("/")

    configs = build_model_configs(intervals)
    if int(args.max_stage1_models or 0) > 0:
        configs = configs[: int(args.max_stage1_models)]

    feature_map: dict[tuple[str, str], SymbolFeatures] = {}
    data_status: dict[str, Any] = {}
    with httpx.Client(base_url=base_url, timeout=30.0, follow_redirects=True) as client:
        for symbol in sorted(set(stage1_symbols + symbols)):
            data_status[symbol] = {}
            for interval in intervals:
                days = stage2_days if symbol in symbols else stage1_days
                bars = _load_bars(
                    client,
                    symbol=symbol,
                    interval=interval,
                    days=days,
                    cache_dir=cache_dir,
                    sleep_seconds=float(args.sleep_seconds),
                )
                if symbol in stage1_symbols:
                    stage1_start = datetime.now(UTC) - timedelta(days=stage1_days)
                    stage1_bars = [bar for bar in bars if bar.ts >= stage1_start]
                    feature_map[(symbol, f"stage1:{interval}")] = SymbolFeatures(stage1_bars)
                feature_map[(symbol, interval)] = SymbolFeatures(bars)
                data_status[symbol][interval] = {
                    "bars": len(bars),
                    "first_ts": bars[0].ts.isoformat() if bars else None,
                    "last_ts": bars[-1].ts.isoformat() if bars else None,
                }

    stage1_features = {
        (symbol, interval): feature_map[(symbol, f"stage1:{interval}")]
        for symbol in stage1_symbols
        for interval in intervals
        if (symbol, f"stage1:{interval}") in feature_map
    }
    stage1_rows = run_stage(
        features_by_symbol_interval=stage1_features,
        symbols=stage1_symbols,
        configs=configs,
    )
    stage1_top = sorted(stage1_rows, key=lambda row: float(row.get("stage1_score", 0.0) or 0.0), reverse=True)[
        : max(int(args.stage2_top), 1)
    ]
    stage2_configs = [_config_from_row(row) for row in stage1_top]
    stage2_rows = run_stage(
        features_by_symbol_interval=feature_map,
        symbols=symbols,
        configs=stage2_configs,
    )
    for row in stage2_rows:
        row["stage1_summary"] = dict(next((s for s in stage1_top if dict(s.get("config") or {}).get("model_id") == dict(row.get("config") or {}).get("model_id")), {}).get("summary") or {})

    top_stage2 = _top_rows(stage2_rows, limit=30, min_trades=int(args.min_stage2_trades))
    family_counts = Counter(str(dict(row.get("config") or {}).get("family") or "") for row in stage2_rows)
    interval_counts = Counter(str(dict(row.get("config") or {}).get("interval") or "") for row in stage2_rows)
    current_micro = _load_current_micro_baseline()

    output = {
        "schema_version": "broad_model_search_v1",
        "generated_at": generated_at.isoformat(),
        "search_scope": {
            "symbols": symbols,
            "stage1_symbols": stage1_symbols,
            "intervals": intervals,
            "stage1_days": stage1_days,
            "stage2_days": stage2_days,
            "stage1_model_count": len(configs),
            "stage2_model_count": len(stage2_configs),
            "fees": {"round_trip_fee_rate": _ROUND_TRIP_FEE_RATE},
            "execution_assumptions": [
                "entry uses next candle open after signal",
                "if stop and target touch in the same candle, stop is assumed first",
                "all results are post-fee R",
                "models are research candidates, not live approval",
            ],
        },
        "data_status": data_status,
        "current_micro_baseline": current_micro,
        "stage1_top": sorted(stage1_rows, key=lambda row: float(row.get("stage1_score", 0.0) or 0.0), reverse=True)[:50],
        "stage2_family_counts": dict(sorted(family_counts.items())),
        "stage2_interval_counts": dict(sorted(interval_counts.items())),
        "stage2_top": top_stage2,
        "stage2_all": stage2_rows,
    }

    if args.write_report:
        out_dir = ROOT_DIR / str(args.report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"broad_model_search_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        atomic_write_text(out_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))
        output["report_path"] = str(out_path.relative_to(ROOT_DIR))

    print(json.dumps({k: v for k, v in output.items() if k != "stage2_all"}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
