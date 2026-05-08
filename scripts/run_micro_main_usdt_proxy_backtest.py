#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gc
import io
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
import zipfile

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.micro_main_strategy_research import (
    SessionImpulseRetestResearch,
    decision_for_micro_summary,
    session_impulse_retest_profile_for_symbol,
    summarize_micro_trades,
)


_INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
}

_USDT_TO_USDC_PROXY = {
    "BTCUSDT": "BTCUSDC",
    "ETHUSDT": "ETHUSDC",
    "SOLUSDT": "SOLUSDC",
    "LINKUSDT": "LINKUSDC",
    "BNBUSDT": "BNBUSDC",
    "XRPUSDT": "XRPUSDC",
    "ADAUSDT": "ADAUSDC",
    "AVAXUSDT": "AVAXUSDC",
    "BCHUSDT": "BCHUSDC",
    "LTCUSDT": "LTCUSDC",
    "NEARUSDT": "NEARUSDC",
}


def canonical_symbol_for_proxy(proxy_symbol: str) -> str | None:
    normalized = str(proxy_symbol or "").strip().upper()
    if not normalized:
        return None
    mapped = _USDT_TO_USDC_PROXY.get(normalized)
    if mapped:
        return mapped
    if normalized.endswith("USDT"):
        return normalized[:-4] + "USDC"
    return None


@dataclass(slots=True)
class MiniCandle:
    ts: datetime
    open_ms: int
    o: float
    h: float
    l: float
    c: float
    v: float


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run long-horizon USDT proxy backtest for micro main strategy.")
    parser.add_argument(
        "--symbols",
        default="BTCUSDT,ETHUSDT,SOLUSDT,LINKUSDT,BNBUSDT,XRPUSDT,ADAUSDT,AVAXUSDT,BCHUSDT,LTCUSDT,NEARUSDT",
    )
    parser.add_argument("--days", type=int, default=1825)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _month_start(ts: datetime) -> datetime:
    return ts.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(ts: datetime) -> datetime:
    base = _month_start(ts)
    if base.month == 12:
        return base.replace(year=base.year + 1, month=1)
    return base.replace(month=base.month + 1)


def _iter_month_starts(start_ts: datetime, end_ts_exclusive: datetime) -> list[datetime]:
    months: list[datetime] = []
    cursor = _month_start(start_ts)
    while cursor < end_ts_exclusive:
        months.append(cursor)
        cursor = _next_month(cursor)
    return months


def _fetch_klines_api(
    client: httpx.Client,
    *,
    symbol: str,
    interval: str,
    start_ts: datetime,
    end_ts: datetime,
) -> list[MiniCandle]:
    interval_ms = _INTERVAL_MS[interval]
    start_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000)
    rows: list[MiniCandle] = []
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
            backoff = retry_after if retry_after > 0 else min(2 ** attempt, 30)
            time.sleep(backoff)
        assert response is not None
        response.raise_for_status()
        payload = response.json()
        if not payload:
            break
        for item in payload:
            open_ms = int(item[0])
            if open_ms < start_ms or open_ms > end_ms:
                continue
            rows.append(
                MiniCandle(
                    ts=datetime.fromtimestamp(open_ms / 1000, tz=UTC),
                    open_ms=open_ms,
                    o=float(item[1]),
                    h=float(item[2]),
                    l=float(item[3]),
                    c=float(item[4]),
                    v=float(item[5]),
                )
            )
        last_open_ms = int(payload[-1][0])
        next_start_ms = last_open_ms + interval_ms
        if next_start_ms <= start_ms:
            break
        start_ms = next_start_ms
        time.sleep(0.05)
    return rows


def _fetch_monthly_zip_rows(
    client: httpx.Client,
    *,
    symbol: str,
    interval: str,
    month_start: datetime,
    start_ts: datetime,
    end_ts: datetime,
) -> list[MiniCandle]:
    month_label = month_start.strftime("%Y-%m")
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
    rows: list[MiniCandle] = []
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        names = [name for name in bundle.namelist() if name.endswith(".csv")]
        if not names:
            return rows
        with bundle.open(names[0], "r") as raw_file:
            reader = csv.reader(io.TextIOWrapper(raw_file, encoding="utf-8", newline=""))
            for item in reader:
                if len(item) < 6:
                    continue
                try:
                    open_ms = int(item[0])
                except ValueError:
                    continue
                if open_ms < start_ms or open_ms > end_ms:
                    continue
                rows.append(
                    MiniCandle(
                        ts=datetime.fromtimestamp(open_ms / 1000, tz=UTC),
                        open_ms=open_ms,
                        o=float(item[1]),
                        h=float(item[2]),
                        l=float(item[3]),
                        c=float(item[4]),
                        v=float(item[5]),
                    )
                )
    return rows


def _fetch_1m_klines(
    monthly_client: httpx.Client,
    rest_client: httpx.Client,
    *,
    symbol: str,
    start_ts: datetime,
    end_ts: datetime,
) -> list[MiniCandle]:
    current_month_start = _month_start(end_ts)
    rows: list[MiniCandle] = []
    for month_start in _iter_month_starts(start_ts, current_month_start):
        rows.extend(
            _fetch_monthly_zip_rows(
                monthly_client,
                symbol=symbol,
                interval="1m",
                month_start=month_start,
                start_ts=start_ts,
                end_ts=end_ts,
            )
        )
    api_start_ts = max(start_ts, current_month_start)
    if api_start_ts <= end_ts:
        rows.extend(
            _fetch_klines_api(
                rest_client,
                symbol=symbol,
                interval="1m",
                start_ts=api_start_ts,
                end_ts=end_ts,
            )
        )
    rows.sort(key=lambda candle: candle.open_ms)
    deduped: list[MiniCandle] = []
    last_open_ms: int | None = None
    for candle in rows:
        if candle.open_ms == last_open_ms:
            continue
        deduped.append(candle)
        last_open_ms = candle.open_ms
    return deduped


def _resample_to_5m(candles_1m: list[MiniCandle]) -> list[MiniCandle]:
    rows: list[MiniCandle] = []
    bucket_open_ms: int | None = None
    bucket_open = 0.0
    bucket_high = 0.0
    bucket_low = 0.0
    bucket_close = 0.0
    bucket_volume = 0.0
    for candle in candles_1m:
        open_ms = candle.open_ms - (candle.open_ms % _INTERVAL_MS["5m"])
        if bucket_open_ms is None or open_ms != bucket_open_ms:
            if bucket_open_ms is not None:
                rows.append(
                    MiniCandle(
                        ts=datetime.fromtimestamp(bucket_open_ms / 1000, tz=UTC),
                        open_ms=bucket_open_ms,
                        o=bucket_open,
                        h=bucket_high,
                        l=bucket_low,
                        c=bucket_close,
                        v=bucket_volume,
                    )
                )
            bucket_open_ms = open_ms
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
    if bucket_open_ms is not None:
        rows.append(
            MiniCandle(
                ts=datetime.fromtimestamp(bucket_open_ms / 1000, tz=UTC),
                open_ms=bucket_open_ms,
                o=bucket_open,
                h=bucket_high,
                l=bucket_low,
                c=bucket_close,
                v=bucket_volume,
            )
        )
    return rows


def _run_symbol(
    monthly_client: httpx.Client,
    rest_client: httpx.Client,
    *,
    proxy_symbol: str,
    canonical_symbol: str,
    lookback_days: int,
) -> dict[str, Any]:
    end_ts = datetime.now(UTC).replace(second=0, microsecond=0)
    start_ts = end_ts - timedelta(days=max(int(lookback_days), 1))
    candles_1m = _fetch_1m_klines(
        monthly_client,
        rest_client,
        symbol=proxy_symbol,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    candles_5m = _resample_to_5m(candles_1m)
    if len(candles_1m) < 600 or len(candles_5m) < 200:
        return {
            "proxy_symbol": proxy_symbol,
            "canonical_symbol": canonical_symbol,
            "profile_name": session_impulse_retest_profile_for_symbol(canonical_symbol),
            "error": "insufficient_candles",
            "candles_1m": len(candles_1m),
            "candles_5m": len(candles_5m),
        }

    engine = SessionImpulseRetestResearch(
        symbol=canonical_symbol,
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        profile_name=session_impulse_retest_profile_for_symbol(canonical_symbol),
    )
    trades = engine.backtest()
    summary = summarize_micro_trades(trades)
    summary["decision"] = decision_for_micro_summary(summary)
    payload = {
        "proxy_symbol": proxy_symbol,
        "canonical_symbol": canonical_symbol,
        "profile_name": session_impulse_retest_profile_for_symbol(canonical_symbol),
        "window": {
            "requested_start_ts": start_ts.isoformat(),
            "requested_end_ts": end_ts.isoformat(),
            "actual_start_1m_ts": candles_1m[0].ts.isoformat(),
            "actual_start_5m_ts": candles_5m[0].ts.isoformat(),
            "actual_end_1m_ts": candles_1m[-1].ts.isoformat(),
            "actual_end_5m_ts": candles_5m[-1].ts.isoformat(),
            "candles_1m": len(candles_1m),
            "candles_5m": len(candles_5m),
        },
        "summary": summary,
    }
    del candles_1m
    del candles_5m
    del trades
    gc.collect()
    return payload


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    generated_at = datetime.now(UTC)
    proxy_symbols = [item.strip().upper() for item in str(args.symbols or "").split(",") if item.strip()]
    results: dict[str, Any] = {}
    aggregate_closed = 0
    aggregate_total_r = 0.0

    out_path: Path | None = None
    if args.write_report:
        out_dir = Path(settings.validation_report_dir) / "micro_main_usdt_proxy_backtests"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"micro_main_usdt_proxy_backtest_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"

    with (
        httpx.Client(timeout=120.0, follow_redirects=True) as monthly_client,
        httpx.Client(base_url=settings.binance_rest_base_url, timeout=30.0) as rest_client,
    ):
        for proxy_symbol in proxy_symbols:
            canonical_symbol = canonical_symbol_for_proxy(proxy_symbol)
            if canonical_symbol is None:
                results[proxy_symbol] = {"error": "missing_proxy_mapping"}
                continue
            result = _run_symbol(
                monthly_client,
                rest_client,
                proxy_symbol=proxy_symbol,
                canonical_symbol=canonical_symbol,
                lookback_days=int(args.days),
            )
            results[proxy_symbol] = result
            summary = dict(result.get("summary") or {})
            aggregate_closed += int(summary.get("closed", 0) or 0)
            aggregate_total_r += float(summary.get("total_r", 0.0) or 0.0)
            print(
                json.dumps(
                    {
                        "progress": proxy_symbol,
                        "closed": int(summary.get("closed", 0) or 0),
                        "ev_r": float(summary.get("ev_r", 0.0) or 0.0),
                        "decision": summary.get("decision"),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
                flush=True,
            )
            if out_path is not None:
                partial_payload = {
                    "generated_at": generated_at.isoformat(),
                    "days": int(args.days),
                    "proxy_symbols": proxy_symbols,
                    "results": results,
                    "aggregate": {
                        "closed": aggregate_closed,
                        "total_r": round(aggregate_total_r, 4),
                        "ev_r": round(aggregate_total_r / max(aggregate_closed, 1), 4),
                    },
                    "report_path": str(out_path),
                    "status": "running",
                }
                out_path.write_text(json.dumps(partial_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "days": int(args.days),
        "proxy_symbols": proxy_symbols,
        "results": results,
        "aggregate": {
            "closed": aggregate_closed,
            "total_r": round(aggregate_total_r, 4),
            "ev_r": round(aggregate_total_r / max(aggregate_closed, 1), 4),
        },
    }

    if out_path is not None:
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["report_path"] = str(out_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
