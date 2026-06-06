#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
import time
import zipfile
from collections import Counter, deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text


Direction = Literal["long", "short"]
Signal = Literal["long", "short", "flat", "keep"]

_INTERVAL_MS = {
    "1m": 60 * 1000,
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "30m": 30 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "2h": 2 * 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "6h": 6 * 60 * 60 * 1000,
}


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
class RotationConfig:
    model_id: str
    family: str
    interval: str
    fast: int = 0
    slow: int = 0
    lookback: int = 0
    length: int = 0
    band_atr: float = 0.0
    entry_z: float = 0.0
    exit_z: float = 0.0
    rsi_lower: float = 0.0
    rsi_upper: float = 0.0
    confirm_bars: int = 1
    max_hold_bars: int = 0
    always_in: bool = True


@dataclass(frozen=True, slots=True)
class RotationTrade:
    model_id: str
    family: str
    symbol: str
    interval: str
    direction: Direction
    entry_ts: datetime
    exit_ts: datetime
    entry: float
    exit: float
    gross_return: float
    hold_bars: int
    exit_reason: str


class FeatureSet:
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
        self._ema_spread_atr_cache: dict[tuple[int, int], list[float]] = {}
        self._high_cache: dict[int, list[float]] = {}
        self._low_cache: dict[int, list[float]] = {}
        self._volume_mean_cache: dict[int, list[float]] = {}
        self._mean_std_cache: dict[int, tuple[list[float], list[float]]] = {}
        self._rsi_cache: dict[int, list[float]] = {}

    def ema(self, length: int) -> list[float]:
        length = max(int(length), 1)
        cached = self._ema_cache.get(length)
        if cached is not None:
            return cached
        alpha = 2.0 / (length + 1.0)
        ema = self.c[0] if self.c else 0.0
        out: list[float] = []
        for close in self.c:
            ema = alpha * float(close) + (1.0 - alpha) * ema
            out.append(ema)
        self._ema_cache[length] = out
        return out

    def ema_spread_atr(self, fast_length: int, slow_length: int) -> list[float]:
        key = (max(int(fast_length), 1), max(int(slow_length), 1))
        cached = self._ema_spread_atr_cache.get(key)
        if cached is not None:
            return cached
        fast = self.ema(key[0])
        slow = self.ema(key[1])
        out = [
            (fast[idx] - slow[idx]) / max(self.atr[idx], 1e-12)
            for idx in range(len(self.c))
        ]
        self._ema_spread_atr_cache[key] = out
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

    def rolling_volume_mean_prev(self, lookback: int) -> list[float]:
        lookback = max(int(lookback), 1)
        cached = self._volume_mean_cache.get(lookback)
        if cached is not None:
            return cached
        out = [0.0] * len(self.v)
        q: deque[float] = deque()
        total = 0.0
        for idx, value in enumerate(self.v):
            out[idx] = total / len(q) if q else float(value)
            q.append(float(value))
            total += float(value)
            if len(q) > lookback:
                total -= q.popleft()
        self._volume_mean_cache[lookback] = out
        return out

    def rolling_mean_std(self, length: int) -> tuple[list[float], list[float]]:
        length = max(int(length), 2)
        cached = self._mean_std_cache.get(length)
        if cached is not None:
            return cached
        means: list[float] = []
        stds: list[float] = []
        q: deque[float] = deque()
        total = 0.0
        total_sq = 0.0
        for close in self.c:
            value = float(close)
            q.append(value)
            total += value
            total_sq += value * value
            if len(q) > length:
                old = q.popleft()
                total -= old
                total_sq -= old * old
            n = max(len(q), 1)
            mean = total / n
            variance = max(total_sq / n - mean * mean, 0.0)
            means.append(mean)
            stds.append(math.sqrt(variance))
        self._mean_std_cache[length] = (means, stds)
        return means, stds

    def rsi(self, length: int) -> list[float]:
        length = max(int(length), 2)
        cached = self._rsi_cache.get(length)
        if cached is not None:
            return cached
        out = [50.0] * len(self.c)
        gains: deque[float] = deque()
        losses: deque[float] = deque()
        gain_sum = 0.0
        loss_sum = 0.0
        for idx in range(1, len(self.c)):
            change = self.c[idx] - self.c[idx - 1]
            gain = max(change, 0.0)
            loss = max(-change, 0.0)
            gains.append(gain)
            losses.append(loss)
            gain_sum += gain
            loss_sum += loss
            if len(gains) > length:
                gain_sum -= gains.popleft()
                loss_sum -= losses.popleft()
            avg_gain = gain_sum / max(len(gains), 1)
            avg_loss = loss_sum / max(len(losses), 1)
            if avg_loss <= 1e-12:
                out[idx] = 100.0
            else:
                rs = avg_gain / avg_loss
                out[idx] = 100.0 - 100.0 / (1.0 + rs)
        self._rsi_cache[length] = out
        return out

    def _atr(self, length: int) -> list[float]:
        if not self.bars:
            return []
        out = [0.0]
        trs: deque[float] = deque()
        total = 0.0
        prev_close = self.c[0]
        for idx in range(1, len(self.bars)):
            tr = max(
                self.h[idx] - self.l[idx],
                abs(self.h[idx] - prev_close),
                abs(self.l[idx] - prev_close),
            )
            trs.append(float(tr))
            total += float(tr)
            if len(trs) > length:
                total -= trs.popleft()
            out.append(total / max(len(trs), 1))
            prev_close = self.c[idx]
        return out


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only BTC flip/rotation strategy search with post-cost return accounting."
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--days", type=int, default=1825)
    parser.add_argument("--intervals", default="5m,15m,30m,1h")
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument("--min-trades", type=int, default=80)
    parser.add_argument("--max-models", type=int, default=0)
    parser.add_argument("--cache-dir", default="reports/validation/btc_flip_rotation_search/cache")
    parser.add_argument("--report-dir", default="reports/validation/btc_flip_rotation_search")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    parser.add_argument("--max-cache-age-minutes", type=float, default=None)
    parser.add_argument("--data-refresh-only", action="store_true")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _csv(raw: Any) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for item in str(raw or "").split(","):
        value = item.strip()
        if value and value not in seen:
            values.append(value)
            seen.add(value)
    return values


def _month_start(ts: datetime) -> datetime:
    return ts.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(ts: datetime) -> datetime:
    base = _month_start(ts)
    if base.month == 12:
        return base.replace(year=base.year + 1, month=1)
    return base.replace(month=base.month + 1)


def _iter_months(start_ts: datetime, end_ts: datetime) -> list[datetime]:
    months: list[datetime] = []
    cursor = _month_start(start_ts)
    while cursor <= end_ts:
        months.append(cursor)
        cursor = _next_month(cursor)
    return months


def _bars_from_csv_rows(rows: list[list[str]], *, start_ms: int, end_ms: int) -> list[Bar]:
    out: list[Bar] = []
    for item in rows:
        if len(item) < 6:
            continue
        try:
            open_ms = int(item[0])
        except ValueError:
            continue
        if open_ms < start_ms or open_ms > end_ms:
            continue
        out.append(
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
    return out


def _fetch_month_zip(
    client: httpx.Client,
    *,
    symbol: str,
    interval: str,
    month: datetime,
    start_ts: datetime,
    end_ts: datetime,
) -> list[Bar]:
    month_label = month.strftime("%Y-%m")
    url = (
        "https://data.binance.vision/data/futures/um/monthly/klines/"
        f"{symbol}/{interval}/{symbol}-{interval}-{month_label}.zip"
    )
    response = client.get(url)
    if response.status_code == 404:
        return []
    response.raise_for_status()
    start_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000)
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        names = [name for name in bundle.namelist() if name.endswith(".csv")]
        if not names:
            return []
        with bundle.open(names[0], "r") as raw_file:
            reader = csv.reader(io.TextIOWrapper(raw_file, encoding="utf-8", newline=""))
            return _bars_from_csv_rows(list(reader), start_ms=start_ms, end_ms=end_ms)


def _fetch_klines_api(
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
            raise RuntimeError("binance_kline_request_missing_response")
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
    *,
    symbol: str,
    interval: str,
    days: int,
    cache_dir: Path,
    base_url: str,
    sleep_seconds: float,
    max_cache_age_minutes: float | None = None,
) -> list[Bar]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    end_ts = datetime.now(UTC).replace(second=0, microsecond=0)
    start_ts = end_ts - timedelta(days=max(int(days), 1))
    cache_path = cache_dir / f"{symbol}_{interval}_{int(days)}d.json"
    cache_max_age = timedelta(hours=12)
    if max_cache_age_minutes is not None:
        cache_max_age = timedelta(minutes=max(float(max_cache_age_minutes), 0.0))
    if cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_end = datetime.fromisoformat(str(payload.get("end_ts")).replace("Z", "+00:00"))
            if cached_end.tzinfo is None:
                cached_end = cached_end.replace(tzinfo=UTC)
            if cached_end >= end_ts - cache_max_age:
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

    rows_by_open: dict[int, Bar] = {}
    with httpx.Client(timeout=60.0, follow_redirects=True) as zip_client:
        for month in _iter_months(start_ts, end_ts):
            month_rows = _fetch_month_zip(
                zip_client,
                symbol=symbol,
                interval=interval,
                month=month,
                start_ts=start_ts,
                end_ts=end_ts,
            )
            for row in month_rows:
                rows_by_open[row.open_ms] = row

    expected_min_rows = int(max(int(days), 1) * 24 * 60 * 60 * 1000 / _INTERVAL_MS[interval] * 0.90)
    if len(rows_by_open) < expected_min_rows:
        with httpx.Client(base_url=base_url, timeout=30.0, follow_redirects=True) as api_client:
            for row in _fetch_klines_api(
                api_client,
                symbol=symbol,
                interval=interval,
                start_ts=start_ts,
                end_ts=end_ts,
                sleep_seconds=sleep_seconds,
            ):
                rows_by_open[row.open_ms] = row

    if rows_by_open:
        latest_open_ms = max(rows_by_open)
        latest_ts = datetime.fromtimestamp(latest_open_ms / 1000, tz=UTC)
        tail_start = latest_ts + timedelta(milliseconds=_INTERVAL_MS[interval])
        if tail_start < end_ts - timedelta(milliseconds=_INTERVAL_MS[interval]):
            with httpx.Client(base_url=base_url, timeout=30.0, follow_redirects=True) as api_client:
                for row in _fetch_klines_api(
                    api_client,
                    symbol=symbol,
                    interval=interval,
                    start_ts=tail_start,
                    end_ts=end_ts,
                    sleep_seconds=sleep_seconds,
                ):
                    rows_by_open[row.open_ms] = row

    rows = [rows_by_open[key] for key in sorted(rows_by_open)]
    rows = [row for row in rows if start_ts <= row.ts <= end_ts]
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
    if interval == "5m":
        return (12, 24, 48, 96)
    if interval == "15m":
        return (8, 16, 32, 64)
    if interval == "30m":
        return (8, 16, 32, 48)
    return (6, 12, 24, 48)


def build_configs(intervals: list[str]) -> list[RotationConfig]:
    configs: list[RotationConfig] = []

    def add(config: RotationConfig) -> None:
        configs.append(config)

    for interval in intervals:
        for fast, slow in ((5, 34), (8, 55), (13, 89), (21, 144)):
            for band in (0.0, 0.15, 0.35):
                for confirm in (1, 2, 3):
                    add(
                        RotationConfig(
                            model_id=f"{interval}:ema_flip:ema{fast}_{slow}:band{band}:confirm{confirm}",
                            family="ema_flip",
                            interval=interval,
                            fast=fast,
                            slow=slow,
                            band_atr=band,
                            confirm_bars=confirm,
                            always_in=True,
                        )
                    )

        for lookback in (12, 24, 48, 96, 144):
            for confirm in (1, 2):
                add(
                    RotationConfig(
                        model_id=f"{interval}:donchian_flip:lb{lookback}:confirm{confirm}",
                        family="donchian_flip",
                        interval=interval,
                        lookback=lookback,
                        confirm_bars=confirm,
                        always_in=True,
                    )
                )

        for length in (48, 96, 192):
            for entry_z in (1.5, 2.0, 2.5):
                for exit_z in (0.0, 0.5):
                    for max_hold in _max_hold_options(interval):
                        add(
                            RotationConfig(
                                model_id=(
                                    f"{interval}:rolling_z_reversion:len{length}:entry{entry_z}:"
                                    f"exit{exit_z}:hold{max_hold}"
                                ),
                                family="rolling_z_reversion",
                                interval=interval,
                                length=length,
                                entry_z=entry_z,
                                exit_z=exit_z,
                                max_hold_bars=max_hold,
                                always_in=False,
                            )
                        )

        for length in (7, 14, 21):
            for lower, upper in ((25.0, 75.0), (30.0, 70.0), (35.0, 65.0)):
                for max_hold in _max_hold_options(interval):
                    add(
                        RotationConfig(
                            model_id=f"{interval}:rsi_reversion:rsi{length}:{lower}_{upper}:hold{max_hold}",
                            family="rsi_reversion",
                            interval=interval,
                            length=length,
                            rsi_lower=lower,
                            rsi_upper=upper,
                            max_hold_bars=max_hold,
                            always_in=False,
                        )
                    )
    return configs


def _confirmed(values: list[float], idx: int, bars: int, threshold: float, sign: int) -> bool:
    bars = max(int(bars), 1)
    if idx - bars + 1 < 0:
        return False
    recent = values[idx - bars + 1 : idx + 1]
    if sign > 0:
        return all(value > threshold for value in recent)
    return all(value < -threshold for value in recent)


def signal_for(features: FeatureSet, idx: int, config: RotationConfig) -> Signal:
    close = features.c[idx]
    atr = max(features.atr[idx], 1e-12)

    if config.family == "ema_flip":
        spread_atr = features.ema_spread_atr(config.fast, config.slow)
        threshold = float(config.band_atr)
        if _confirmed(spread_atr, idx, config.confirm_bars, threshold, 1):
            return "long"
        if _confirmed(spread_atr, idx, config.confirm_bars, threshold, -1):
            return "short"
        return "keep" if config.always_in else "flat"

    if config.family == "donchian_flip":
        highs = features.rolling_high_prev(config.lookback)
        lows = features.rolling_low_prev(config.lookback)
        long_breaks: list[float] = []
        short_breaks: list[float] = []
        start = max(0, idx - max(int(config.confirm_bars), 1) + 1)
        for pos in range(start, idx + 1):
            long_breaks.append(1.0 if features.c[pos] > highs[pos] else 0.0)
            short_breaks.append(1.0 if features.c[pos] < lows[pos] else 0.0)
        if long_breaks and all(value > 0.0 for value in long_breaks):
            return "long"
        if short_breaks and all(value > 0.0 for value in short_breaks):
            return "short"
        return "keep" if config.always_in else "flat"

    if config.family == "rolling_z_reversion":
        mean, std = features.rolling_mean_std(config.length)
        z = (close - mean[idx]) / max(std[idx], atr * 0.10, 1e-12)
        if z <= -float(config.entry_z):
            return "long"
        if z >= float(config.entry_z):
            return "short"
        if abs(z) <= float(config.exit_z):
            return "flat"
        return "keep"

    if config.family == "rsi_reversion":
        rsi = features.rsi(config.length)[idx]
        if rsi <= float(config.rsi_lower):
            return "long"
        if rsi >= float(config.rsi_upper):
            return "short"
        if 45.0 <= rsi <= 55.0:
            return "flat"
        return "keep"

    return "keep"


def backtest_config(symbol: str, features: FeatureSet, config: RotationConfig) -> list[RotationTrade]:
    trades: list[RotationTrade] = []
    warmup = max(config.slow, config.lookback, config.length, 60) + 5
    current_side: Direction | None = None
    entry_price = 0.0
    entry_idx = 0
    entry_ts: datetime | None = None

    def close_position(exit_idx: int, exit_price: float, reason: str) -> None:
        nonlocal current_side, entry_price, entry_idx, entry_ts
        if current_side is None or entry_ts is None or entry_price <= 0.0:
            return
        gross = (exit_price / entry_price - 1.0) if current_side == "long" else (entry_price / exit_price - 1.0)
        trades.append(
            RotationTrade(
                model_id=config.model_id,
                family=config.family,
                symbol=symbol,
                interval=config.interval,
                direction=current_side,
                entry_ts=entry_ts,
                exit_ts=features.ts[exit_idx],
                entry=entry_price,
                exit=exit_price,
                gross_return=float(gross),
                hold_bars=max(exit_idx - entry_idx, 1),
                exit_reason=reason,
            )
        )
        current_side = None
        entry_price = 0.0
        entry_idx = 0
        entry_ts = None

    for idx in range(warmup, len(features.bars) - 1):
        exec_idx = idx + 1
        exec_price = features.o[exec_idx]
        if exec_price <= 0.0:
            continue
        sig = signal_for(features, idx, config)

        if (
            current_side is not None
            and config.max_hold_bars > 0
            and exec_idx - entry_idx >= config.max_hold_bars
        ):
            close_position(exec_idx, exec_price, "max_hold")

        if sig == "flat":
            if current_side is not None:
                close_position(exec_idx, exec_price, "flat_signal")
            continue
        if sig == "keep":
            continue
        if sig in {"long", "short"}:
            side = "long" if sig == "long" else "short"
            if current_side == side:
                continue
            if current_side is not None:
                close_position(exec_idx, exec_price, "flip")
            current_side = side
            entry_price = exec_price
            entry_idx = exec_idx
            entry_ts = features.ts[exec_idx]

    if current_side is not None and len(features.bars) >= 1:
        close_position(len(features.bars) - 1, features.c[-1], "end_of_sample")
    return trades


def _year_fraction(first: datetime | None, last: datetime | None) -> float:
    if first is None or last is None:
        return 0.0
    seconds = max((last - first).total_seconds(), 1.0)
    return seconds / (365.25 * 24 * 60 * 60)


def _summarize(trades: list[RotationTrade], *, cost_bps_per_side: float, min_trades: int) -> dict[str, Any]:
    ordered = sorted(trades, key=lambda trade: (trade.exit_ts, trade.model_id))
    per_side_cost = max(float(cost_bps_per_side), 0.0) / 10_000.0
    net_values = [trade.gross_return - 2.0 * per_side_cost for trade in ordered]
    gross_values = [trade.gross_return for trade in ordered]
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    by_year_equity: dict[str, float] = {}
    by_year_start: dict[str, float] = {}
    wins = 0
    exit_reasons: Counter[str] = Counter()
    directions: Counter[str] = Counter()
    for trade, net in zip(ordered, net_values, strict=True):
        year = str(trade.exit_ts.year)
        by_year_start.setdefault(year, by_year_equity.get(year, equity))
        equity *= max(1.0 + net, 1e-9)
        by_year_equity[year] = equity
        peak = max(peak, equity)
        max_dd = max(max_dd, 1.0 - equity / max(peak, 1e-9))
        if net > 0.0:
            wins += 1
        exit_reasons[trade.exit_reason] += 1
        directions[trade.direction] += 1

    closed = len(ordered)
    first = ordered[0].entry_ts if ordered else None
    last = ordered[-1].exit_ts if ordered else None
    years = max(_year_fraction(first, last), 1e-9)
    by_year_return: dict[str, float] = {}
    for year, year_end_equity in sorted(by_year_equity.items()):
        start_equity = by_year_start.get(year, 1.0)
        by_year_return[year] = year_end_equity / max(start_equity, 1e-9) - 1.0
    positive_years = sum(1 for value in by_year_return.values() if value > 0.0)
    gross_sum = sum(gross_values)
    net_sum = sum(net_values)
    total_return = equity - 1.0
    return_to_dd = total_return / max(max_dd, 1e-9) if max_dd > 0.0 else 0.0
    avg_hold = sum(trade.hold_bars for trade in ordered) / closed if closed else 0.0
    profit_factor = (
        sum(value for value in net_values if value > 0.0)
        / max(abs(sum(value for value in net_values if value <= 0.0)), 1e-12)
        if closed
        else 0.0
    )
    positive_year_fraction = positive_years / max(len(by_year_return), 1)
    score = 0.0
    if closed >= min_trades and total_return > 0.0 and max_dd > 0.0:
        score = return_to_dd * max(positive_year_fraction, 0.05) * math.log10(closed + 10)
    if closed < min_trades:
        decision = "REJECT_SAMPLE"
    elif total_return <= 0.0 or net_sum <= 0.0:
        decision = "REJECT_NEGATIVE"
    elif positive_year_fraction < 0.60:
        decision = "REJECT_INCONSISTENT"
    elif return_to_dd < 1.0:
        decision = "REJECT_WEAK_DD"
    elif return_to_dd >= 2.0 and positive_year_fraction >= 0.70:
        decision = "PAPER_RESEARCH"
    else:
        decision = "WATCH"
    return {
        "closed": closed,
        "decision": decision,
        "total_return_pct_1x": round(total_return * 100.0, 4),
        "gross_sum_pct": round(gross_sum * 100.0, 4),
        "net_sum_pct": round(net_sum * 100.0, 4),
        "avg_trade_net_bps": round((net_sum / closed) * 10_000.0, 4) if closed else 0.0,
        "win_rate": round(wins / closed, 4) if closed else 0.0,
        "profit_factor": round(profit_factor, 4),
        "max_drawdown_pct_1x": round(max_dd * 100.0, 4),
        "return_to_dd": round(return_to_dd, 4),
        "trades_per_year": round(closed / years, 2),
        "avg_hold_bars": round(avg_hold, 2),
        "positive_year_count": positive_years,
        "year_count": len(by_year_return),
        "positive_year_fraction": round(positive_year_fraction, 4),
        "by_year_return_pct": {key: round(value * 100.0, 4) for key, value in by_year_return.items()},
        "direction_counts": dict(sorted(directions.items())),
        "exit_reasons": dict(sorted(exit_reasons.items())),
        "cost_bps_per_side": round(per_side_cost * 10_000.0, 4),
        "score": round(score, 6),
    }


def _trade_sample(trades: list[RotationTrade], limit: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "direction": trade.direction,
            "entry_ts": trade.entry_ts.isoformat(),
            "exit_ts": trade.exit_ts.isoformat(),
            "entry": round(trade.entry, 4),
            "exit": round(trade.exit, 4),
            "gross_return_pct": round(trade.gross_return * 100.0, 4),
            "hold_bars": trade.hold_bars,
            "exit_reason": trade.exit_reason,
        }
        for trade in trades[:limit]
    ]


def _buy_hold_benchmark(features: FeatureSet) -> dict[str, Any]:
    if not features.bars:
        return {"return_pct_1x": 0.0, "first_ts": None, "last_ts": None}
    first = features.bars[0]
    last = features.bars[-1]
    return {
        "first_ts": first.ts.isoformat(),
        "last_ts": last.ts.isoformat(),
        "first_close": first.c,
        "last_close": last.c,
        "return_pct_1x": round((last.c / first.c - 1.0) * 100.0, 4) if first.c > 0.0 else 0.0,
    }


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    generated_at = datetime.now(UTC)
    symbol = str(args.symbol or "BTCUSDT").strip().upper()
    intervals = [item for item in _csv(args.intervals) if item in _INTERVAL_MS] or ["15m", "30m", "1h"]
    days = max(int(args.days), 30)
    cache_dir = ROOT_DIR / str(args.cache_dir)
    base_url = str(args.base_url or settings.binance_rest_base_url or "https://fapi.binance.com").rstrip("/")
    base_cost = max(float(args.fee_bps_per_side) + float(args.slippage_bps_per_side), 0.0)
    min_trades = max(int(args.min_trades), 1)

    data_status: dict[str, Any] = {}
    features_by_interval: dict[str, FeatureSet] = {}
    for interval in intervals:
        bars = _load_bars(
            symbol=symbol,
            interval=interval,
            days=days,
            cache_dir=cache_dir,
            base_url=base_url,
            sleep_seconds=float(args.sleep_seconds),
            max_cache_age_minutes=args.max_cache_age_minutes,
        )
        features_by_interval[interval] = FeatureSet(bars)
        data_status[interval] = {
            "bars": len(bars),
            "first_ts": bars[0].ts.isoformat() if bars else None,
            "last_ts": bars[-1].ts.isoformat() if bars else None,
        }
    if args.data_refresh_only:
        output = {
            "schema_version": "btc_flip_rotation_data_refresh_v1",
            "generated_at": generated_at.isoformat(),
            "authority": "data_cache_refresh_only_no_strategy_selection_change",
            "scope": {
                "symbol": symbol,
                "days": days,
                "intervals": intervals,
                "cache_dir": str(cache_dir.relative_to(ROOT_DIR)) if cache_dir.is_relative_to(ROOT_DIR) else str(cache_dir),
                "max_cache_age_minutes": args.max_cache_age_minutes,
            },
            "data_status": data_status,
            "latest_strategy_report_not_modified": True,
            "no_live_order_sent": True,
        }
        if args.write_report:
            report_dir = ROOT_DIR / str(args.report_dir)
            report_dir.mkdir(parents=True, exist_ok=True)
            out_path = report_dir / f"btc_flip_rotation_data_refresh_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
            latest_path = report_dir / "data_refresh_latest.json"
            output["report_path"] = str(out_path.relative_to(ROOT_DIR))
            output["latest_report_path"] = str(latest_path.relative_to(ROOT_DIR))
            atomic_write_text(out_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))
            atomic_write_text(latest_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
        return 0

    configs = build_configs(intervals)
    if int(args.max_models or 0) > 0:
        configs = configs[: int(args.max_models)]

    rows: list[dict[str, Any]] = []
    for index, config in enumerate(configs, start=1):
        features = features_by_interval.get(config.interval)
        if features is None or len(features.bars) < 500:
            continue
        trades = backtest_config(symbol, features, config)
        summary = _summarize(trades, cost_bps_per_side=base_cost, min_trades=min_trades)
        stress = {
            "makerish_2fee_0_5slip": _summarize(trades, cost_bps_per_side=2.5, min_trades=min_trades),
            "base": summary,
            "harsh_6fee_2slip": _summarize(trades, cost_bps_per_side=8.0, min_trades=min_trades),
        }
        rows.append(
            {
                "rank_input_order": index,
                "config": asdict(config),
                "summary": summary,
                "cost_stress": {
                    key: {
                        "decision": value["decision"],
                        "total_return_pct_1x": value["total_return_pct_1x"],
                        "net_sum_pct": value["net_sum_pct"],
                        "avg_trade_net_bps": value["avg_trade_net_bps"],
                        "max_drawdown_pct_1x": value["max_drawdown_pct_1x"],
                        "return_to_dd": value["return_to_dd"],
                    }
                    for key, value in stress.items()
                },
                "sample_trades": _trade_sample(trades),
            }
        )
        if index % 100 == 0:
            print(json.dumps({"progress_models": index, "latest_model": config.model_id}, ensure_ascii=False), flush=True)

    top = sorted(
        rows,
        key=lambda row: (
            float(dict(row.get("summary") or {}).get("score", 0.0) or 0.0),
            float(dict(row.get("summary") or {}).get("total_return_pct_1x", 0.0) or 0.0),
            float(dict(row.get("summary") or {}).get("net_sum_pct", 0.0) or 0.0),
        ),
        reverse=True,
    )[:30]
    family_counts = Counter(str(dict(row.get("config") or {}).get("family") or "") for row in rows)
    decision_counts = Counter(str(dict(row.get("summary") or {}).get("decision") or "") for row in rows)
    output = {
        "schema_version": "btc_flip_rotation_search_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "research_only_no_live_authority_change",
        "scope": {
            "symbol": symbol,
            "days": days,
            "intervals": intervals,
            "model_count": len(rows),
            "min_trades": min_trades,
        },
        "cost_model": {
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": float(args.slippage_bps_per_side),
            "base_cost_bps_per_side": base_cost,
            "notes": [
                "signals use completed candles and execute at next candle open",
                "flip closes the old side and opens the new side at the same next-open price",
                "returns are 1x notional returns after modeled fee and slippage",
                "funding, borrow cost, liquidation, and queue priority are not modeled",
            ],
        },
        "data_status": data_status,
        "buy_hold_benchmark_by_interval": {
            interval: _buy_hold_benchmark(features)
            for interval, features in sorted(features_by_interval.items())
        },
        "family_counts": dict(sorted(family_counts.items())),
        "decision_counts": dict(sorted(decision_counts.items())),
        "top": top,
        "all_results": rows,
    }
    if args.write_report:
        report_dir = ROOT_DIR / str(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        out_path = report_dir / f"btc_flip_rotation_search_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        latest_path = report_dir / "latest.json"
        output["report_path"] = str(out_path.relative_to(ROOT_DIR))
        output["latest_report_path"] = str(latest_path.relative_to(ROOT_DIR))
        atomic_write_text(out_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(latest_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))

    print(json.dumps({key: value for key, value in output.items() if key != "all_results"}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
