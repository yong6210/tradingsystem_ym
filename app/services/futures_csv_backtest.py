from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.services.micro_main_strategy_research import (
    SessionImpulseRetestResearch,
    decision_for_micro_summary,
    summarize_micro_trades,
)


_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "timestamp": ("timestamp", "datetime", "time", "date time"),
    "date": ("date", "trading day"),
    "time": ("time",),
    "open": ("open", "o"),
    "high": ("high", "h"),
    "low": ("low", "l"),
    "close": ("close", "c", "last"),
    "volume": ("volume", "vol", "v"),
}

_DATETIME_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%Y%m%d %H%M%S",
    "%Y%m%d %H:%M:%S",
    "%Y%m%d %H:%M",
)


@dataclass(frozen=True, slots=True)
class CsvCandle:
    ts: datetime
    o: float
    h: float
    l: float
    c: float
    v: float


def _normalize_field_name(value: str) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def _resolve_field(fieldnames: list[str], canonical: str) -> str | None:
    normalized = {_normalize_field_name(name): name for name in fieldnames}
    for alias in _FIELD_ALIASES[canonical]:
        candidate = normalized.get(_normalize_field_name(alias))
        if candidate is not None:
            return candidate
    return None


def _parse_float(raw: str | None, *, default: float | None = None) -> float:
    value = str(raw or "").strip().replace(",", "")
    if not value:
        if default is None:
            raise ValueError("missing numeric value")
        return float(default)
    return float(value)


def _parse_timestamp(raw: str, *, timezone_name: str) -> datetime:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("missing timestamp")
    if value.isdigit():
        numeric = int(value)
        if numeric > 1_000_000_000_000:
            return datetime.fromtimestamp(numeric / 1000, tz=UTC)
        if numeric > 1_000_000_000:
            return datetime.fromtimestamp(numeric, tz=UTC)

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
        return parsed.astimezone(UTC)
    except ValueError:
        pass

    for fmt in _DATETIME_FORMATS:
        try:
            parsed = datetime.strptime(value, fmt)
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
            return parsed.astimezone(UTC)
        except ValueError:
            continue
    raise ValueError(f"unsupported timestamp format: {value}")


def load_1m_csv_candles(
    *,
    csv_path: str | Path,
    timezone_name: str,
    start_ts: datetime | None = None,
    end_ts: datetime | None = None,
) -> list[CsvCandle]:
    path = Path(csv_path).expanduser().resolve()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV header is missing")
        fieldnames = list(reader.fieldnames)
        timestamp_field = _resolve_field(fieldnames, "timestamp")
        date_field = _resolve_field(fieldnames, "date")
        time_field = _resolve_field(fieldnames, "time")
        open_field = _resolve_field(fieldnames, "open")
        high_field = _resolve_field(fieldnames, "high")
        low_field = _resolve_field(fieldnames, "low")
        close_field = _resolve_field(fieldnames, "close")
        volume_field = _resolve_field(fieldnames, "volume")

        if timestamp_field is None and not (date_field and time_field):
            raise ValueError("CSV must contain timestamp or date+time columns")
        if open_field is None or high_field is None or low_field is None or close_field is None:
            raise ValueError("CSV must contain open/high/low/close columns")

        normalized_start = start_ts.astimezone(UTC) if start_ts is not None else None
        normalized_end = end_ts.astimezone(UTC) if end_ts is not None else None

        rows: list[CsvCandle] = []
        for raw_row in reader:
            timestamp_raw = ""
            if timestamp_field is not None:
                timestamp_raw = str(raw_row.get(timestamp_field) or "").strip()
            elif date_field is not None and time_field is not None:
                timestamp_raw = f"{str(raw_row.get(date_field) or '').strip()} {str(raw_row.get(time_field) or '').strip()}"
            if not timestamp_raw:
                continue
            ts = _parse_timestamp(timestamp_raw, timezone_name=timezone_name)
            if normalized_start is not None and ts < normalized_start:
                continue
            if normalized_end is not None and ts > normalized_end:
                continue
            rows.append(
                CsvCandle(
                    ts=ts,
                    o=_parse_float(raw_row.get(open_field)),
                    h=_parse_float(raw_row.get(high_field)),
                    l=_parse_float(raw_row.get(low_field)),
                    c=_parse_float(raw_row.get(close_field)),
                    v=_parse_float(raw_row.get(volume_field) if volume_field is not None else None, default=0.0),
                )
            )

    rows.sort(key=lambda candle: candle.ts)
    deduped: list[CsvCandle] = []
    last_ts: datetime | None = None
    for candle in rows:
        if last_ts is not None and candle.ts == last_ts:
            continue
        deduped.append(candle)
        last_ts = candle.ts
    return deduped


def resample_candles_5m(candles_1m: list[CsvCandle]) -> list[CsvCandle]:
    if not candles_1m:
        return []
    rows: list[CsvCandle] = []
    bucket_ts: datetime | None = None
    bucket_open = 0.0
    bucket_high = 0.0
    bucket_low = 0.0
    bucket_close = 0.0
    bucket_volume = 0.0

    for candle in candles_1m:
        normalized_ts = candle.ts - timedelta(
            minutes=candle.ts.minute % 5,
            seconds=candle.ts.second,
            microseconds=candle.ts.microsecond,
        )
        if bucket_ts is None or normalized_ts != bucket_ts:
            if bucket_ts is not None:
                rows.append(
                    CsvCandle(
                        ts=bucket_ts,
                        o=bucket_open,
                        h=bucket_high,
                        l=bucket_low,
                        c=bucket_close,
                        v=bucket_volume,
                    )
                )
            bucket_ts = normalized_ts
            bucket_open = candle.o
            bucket_high = candle.h
            bucket_low = candle.l
            bucket_close = candle.c
            bucket_volume = candle.v
            continue
        bucket_high = max(bucket_high, candle.h)
        bucket_low = min(bucket_low, candle.l)
        bucket_close = candle.c
        bucket_volume += candle.v

    if bucket_ts is not None:
        rows.append(
            CsvCandle(
                ts=bucket_ts,
                o=bucket_open,
                h=bucket_high,
                l=bucket_low,
                c=bucket_close,
                v=bucket_volume,
            )
        )
    return rows


def run_futures_csv_backtest(
    *,
    csv_path: str | Path,
    symbol: str,
    profile_name: str,
    timezone_name: str,
    lookback_days: int | None = None,
    start_ts: datetime | None = None,
    end_ts: datetime | None = None,
) -> dict[str, Any]:
    normalized_end = end_ts.astimezone(UTC) if end_ts is not None else None
    normalized_start = start_ts.astimezone(UTC) if start_ts is not None else None
    if normalized_start is None and lookback_days is not None:
        effective_end = normalized_end or datetime.now(UTC)
        normalized_start = effective_end - timedelta(days=max(int(lookback_days), 1))

    candles_1m = load_1m_csv_candles(
        csv_path=csv_path,
        timezone_name=timezone_name,
        start_ts=normalized_start,
        end_ts=normalized_end,
    )
    candles_5m = resample_candles_5m(candles_1m)
    if len(candles_1m) < 600 or len(candles_5m) < 200:
        return {
            "error": "insufficient_candles",
            "symbol": symbol,
            "profile_name": profile_name,
            "window": {
                "requested_start_ts": normalized_start.isoformat() if normalized_start is not None else None,
                "requested_end_ts": normalized_end.isoformat() if normalized_end is not None else None,
                "candles_1m": len(candles_1m),
                "candles_5m": len(candles_5m),
            },
        }

    engine = SessionImpulseRetestResearch(
        symbol=str(symbol).upper(),
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        profile_name=profile_name,
    )
    trades = engine.backtest()
    summary = summarize_micro_trades(trades)
    summary["decision"] = decision_for_micro_summary(summary)
    return {
        "symbol": str(symbol).upper(),
        "profile_name": profile_name,
        "csv_path": str(Path(csv_path).expanduser().resolve()),
        "timezone_name": timezone_name,
        "window": {
            "requested_start_ts": normalized_start.isoformat() if normalized_start is not None else None,
            "requested_end_ts": normalized_end.isoformat() if normalized_end is not None else None,
            "actual_start_1m_ts": candles_1m[0].ts.isoformat(),
            "actual_end_1m_ts": candles_1m[-1].ts.isoformat(),
            "actual_start_5m_ts": candles_5m[0].ts.isoformat(),
            "actual_end_5m_ts": candles_5m[-1].ts.isoformat(),
            "candles_1m": len(candles_1m),
            "candles_5m": len(candles_5m),
        },
        "summary": summary,
    }
