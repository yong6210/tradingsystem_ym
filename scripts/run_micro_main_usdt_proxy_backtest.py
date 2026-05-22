#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gc
import io
import json
import sys
import time
from dataclasses import asdict, dataclass
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
from app.services.report_io import atomic_write_text


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
    parser.add_argument("--include-trades", action="store_true")
    parser.add_argument("--write-loss-analysis", action="store_true")
    parser.add_argument("--loss-analysis-min-bucket-trades", type=int, default=12)
    parser.add_argument("--loss-analysis-min-negative-years", type=int, default=2)
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
        if response is None:
            raise RuntimeError("Binance kline request did not produce a response")
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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _round(value: Any, digits: int = 4) -> float:
    return round(_safe_float(value), digits)


def _bucket(value: Any, cuts: tuple[tuple[float, str], ...], default: str) -> str:
    parsed = _safe_float(value, default=float("nan"))
    if parsed != parsed:
        return default
    for threshold, label in cuts:
        if parsed < threshold:
            return label
    return default


def _trade_to_row(*, trade: Any, proxy_symbol: str, canonical_symbol: str, profile_name: str) -> dict[str, Any]:
    diagnostics = dict(getattr(trade, "diagnostics", {}) or {})
    entry_ts = trade.entry_ts.astimezone(UTC)
    signal_ts = trade.signal_ts.astimezone(UTC)
    risk_abs = abs(float(trade.entry_price) - float(trade.stop_price))
    row = {
        "family": str(trade.family),
        "symbol": canonical_symbol,
        "proxy_symbol": proxy_symbol,
        "profile_name": profile_name,
        "direction": str(trade.direction),
        "signal_ts": signal_ts.isoformat(),
        "entry_ts": entry_ts.isoformat(),
        "exit_ts": trade.exit_ts.astimezone(UTC).isoformat(),
        "signal_hour_utc": _safe_int(diagnostics.get("setup_hour_utc"), signal_ts.hour),
        "entry_hour_utc": _safe_int(diagnostics.get("entry_hour_utc"), entry_ts.hour),
        "entry_weekday_utc": _safe_int(diagnostics.get("entry_weekday_utc"), entry_ts.weekday()),
        "entry_year": entry_ts.year,
        "entry_price": _round(trade.entry_price),
        "exit_price": _round(trade.exit_price),
        "stop_price": _round(trade.stop_price),
        "target_price": _round(trade.target_price),
        "stop_distance_pct": _round(risk_abs / max(abs(float(trade.entry_price)), 1e-12), 6),
        "r_value": _round(trade.r_value),
        "gross_r": _round(trade.gross_r),
        "cost_r": _round(trade.cost_r),
        "hold_minutes": int(trade.hold_minutes),
        "exit_reason": str(trade.exit_reason),
        "regime_hint": str(trade.regime_hint),
        "risk_atr_bucket": _bucket(
            diagnostics.get("risk_atr"),
            ((0.40, "risk_atr_lt_0.40"), (0.70, "risk_atr_0.40_0.70"), (1.00, "risk_atr_0.70_1.00")),
            "risk_atr_ge_1.00",
        ),
        "volume_factor_bucket": _bucket(
            diagnostics.get("volume_factor"),
            ((0.90, "volume_lt_0.90"), (1.10, "volume_0.90_1.10"), (1.40, "volume_1.10_1.40")),
            "volume_ge_1.40",
        ),
        "retest_wait_bucket": _bucket(
            diagnostics.get("retest_wait_minutes"),
            ((3.0, "retest_0_2m"), (6.0, "retest_3_5m"), (11.0, "retest_6_10m")),
            "retest_gt_10m",
        ),
        "diagnostics": {
            key: _round(value, 6) if isinstance(value, float) else value
            for key, value in sorted(diagnostics.items())
        },
    }
    return row


def _trade_matches_signal_contract(*, trade: Any, canonical_symbol: str, contract: dict[str, Any]) -> bool:
    symbols = {str(item).strip().upper() for item in list(contract.get("symbols") or []) if str(item).strip()}
    if symbols and str(canonical_symbol or "").strip().upper() not in symbols:
        return False

    filter_contract = dict(contract.get("filter_contract") or {})
    diagnostics = dict(getattr(trade, "diagnostics", {}) or {})

    expected_direction = str(filter_contract.get("direction") or "").strip().lower()
    if expected_direction and expected_direction != "both" and str(getattr(trade, "direction", "")).lower() != expected_direction:
        return False

    allowed_hours = {_safe_int(hour, -1) for hour in list(filter_contract.get("setup_hour_utc") or [])}
    if allowed_hours and _safe_int(diagnostics.get("setup_hour_utc"), -1) not in allowed_hours:
        return False

    min_volume_factor = filter_contract.get("min_volume_factor")
    if min_volume_factor is not None and _safe_float(diagnostics.get("volume_factor")) < _safe_float(min_volume_factor):
        return False

    min_reclaim_body_atr = filter_contract.get("min_reclaim_body_atr")
    if min_reclaim_body_atr is not None and _safe_float(diagnostics.get("reclaim_body_atr")) < _safe_float(min_reclaim_body_atr):
        return False

    min_risk_atr = filter_contract.get("min_risk_atr")
    if min_risk_atr is not None and _safe_float(diagnostics.get("risk_atr")) < _safe_float(min_risk_atr):
        return False

    max_risk_atr = filter_contract.get("max_risk_atr")
    if max_risk_atr is not None and _safe_float(diagnostics.get("risk_atr")) > _safe_float(max_risk_atr):
        return False

    max_entry_distance_atr = filter_contract.get("max_entry_distance_atr")
    if max_entry_distance_atr is not None and _safe_float(diagnostics.get("entry_distance_atr")) > _safe_float(max_entry_distance_atr):
        return False

    return True


def _filter_trades_by_signal_contracts(
    *,
    trades: list[Any],
    canonical_symbol: str,
    signal_contracts: list[dict[str, Any]],
) -> list[Any]:
    if not signal_contracts:
        return list(trades)
    selected = []
    for trade in trades:
        if any(_trade_matches_signal_contract(trade=trade, canonical_symbol=canonical_symbol, contract=contract) for contract in signal_contracts):
            selected.append(trade)
    return selected


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closed = len(rows)
    if closed <= 0:
        return {
            "closed": 0,
            "total_r": 0.0,
            "ev_r": 0.0,
            "win_rate": 0.0,
            "loss_rate": 0.0,
            "loss_count": 0,
            "loss_r": 0.0,
            "avg_loss_r": 0.0,
            "avg_win_r": 0.0,
        }
    r_values = [_safe_float(row.get("r_value")) for row in rows]
    wins = [value for value in r_values if value > 0.0]
    losses = [value for value in r_values if value <= 0.0]
    return {
        "closed": closed,
        "total_r": round(sum(r_values), 4),
        "ev_r": round(sum(r_values) / closed, 4),
        "win_rate": round(len(wins) / closed, 4),
        "loss_rate": round(len(losses) / closed, 4),
        "loss_count": len(losses),
        "loss_r": round(sum(losses), 4),
        "avg_loss_r": round(sum(losses) / len(losses), 4) if losses else 0.0,
        "avg_win_r": round(sum(wins) / len(wins), 4) if wins else 0.0,
    }


def _group_rows(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        grouped.setdefault(value, []).append(row)
    return grouped


def _compound_group_rows(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        value = "|".join(str(row.get(key) or "unknown") for key in keys)
        grouped.setdefault(value, []).append(row)
    return grouped


def _ranked_group_stats(grouped: dict[str, list[dict[str, Any]]], *, limit: int = 12) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for key, group_rows in grouped.items():
        item = {"bucket": key, **_stats(group_rows)}
        ranked.append(item)
    ranked.sort(key=lambda item: (_safe_float(item.get("loss_r")), -_safe_int(item.get("loss_count"))))
    return ranked[:limit]


def _recommended_symbol_hour_blocks(
    rows: list[dict[str, Any]],
    *,
    min_bucket_trades: int,
    min_negative_years: int,
) -> list[dict[str, Any]]:
    by_symbol = _group_rows(rows, "symbol")
    grouped = _compound_group_rows(rows, ("symbol", "profile_name", "signal_hour_utc"))
    candidates: list[dict[str, Any]] = []
    for key, bucket_rows in grouped.items():
        if len(bucket_rows) < max(int(min_bucket_trades), 1):
            continue
        symbol, profile_name, hour_text = key.split("|", 2)
        symbol_rows = by_symbol.get(symbol, [])
        kept_rows = [row for row in symbol_rows if row not in bucket_rows]
        if len(kept_rows) < max(40, int(len(symbol_rows) * 0.50)):
            continue
        before = _stats(symbol_rows)
        bucket = _stats(bucket_rows)
        after = _stats(kept_rows)
        if _safe_float(bucket.get("total_r")) >= -1.0 or _safe_float(bucket.get("ev_r")) >= -0.05:
            continue
        if _safe_float(bucket.get("loss_rate")) < 0.55:
            continue
        by_year = _group_rows(bucket_rows, "entry_year")
        year_rows = [{"year": year, **_stats(year_bucket)} for year, year_bucket in sorted(by_year.items())]
        years_with_trades = len(year_rows)
        negative_years = sum(1 for item in year_rows if _safe_float(item.get("total_r")) < 0.0)
        required_negative_years = min(max(int(min_negative_years), 1), max(years_with_trades, 1))
        if negative_years < required_negative_years:
            continue
        total_r_delta = _safe_float(after.get("total_r")) - _safe_float(before.get("total_r"))
        ev_delta = _safe_float(after.get("ev_r")) - _safe_float(before.get("ev_r"))
        if total_r_delta <= 0.0 and ev_delta <= 0.0:
            continue
        candidates.append(
            {
                "action": "block_symbol_signal_hour",
                "symbol": symbol,
                "profile_name": profile_name,
                "signal_hour_utc": _safe_int(hour_text),
                "bucket": bucket,
                "symbol_before": before,
                "symbol_after": after,
                "delta": {
                    "total_r": round(total_r_delta, 4),
                    "ev_r": round(ev_delta, 4),
                    "removed_trade_share": round(len(bucket_rows) / max(len(symbol_rows), 1), 4),
                },
                "year_consistency": {
                    "years_with_trades": years_with_trades,
                    "negative_years": negative_years,
                    "required_negative_years": required_negative_years,
                    "years": year_rows,
                },
            }
        )
    candidates.sort(
        key=lambda item: (
            -_safe_float(dict(item.get("delta") or {}).get("total_r")),
            -_safe_float(dict(item.get("delta") or {}).get("ev_r")),
        )
    )
    return candidates


def _build_loss_analysis(
    rows: list[dict[str, Any]],
    *,
    min_bucket_trades: int,
    min_negative_years: int,
) -> dict[str, Any]:
    losing_rows = [row for row in rows if _safe_float(row.get("r_value")) <= 0.0]
    return {
        "schema_version": "micro_main_loss_analysis_v1",
        "summary": _stats(rows),
        "loss_summary": _stats(losing_rows),
        "top_loss_buckets": {
            "by_symbol": _ranked_group_stats(_group_rows(rows, "symbol")),
            "by_exit_reason": _ranked_group_stats(_group_rows(rows, "exit_reason")),
            "by_direction": _ranked_group_stats(_group_rows(rows, "direction")),
            "by_signal_hour_utc": _ranked_group_stats(_group_rows(rows, "signal_hour_utc")),
            "by_entry_weekday_utc": _ranked_group_stats(_group_rows(rows, "entry_weekday_utc")),
            "by_symbol_signal_hour": _ranked_group_stats(_compound_group_rows(rows, ("symbol", "signal_hour_utc")), limit=20),
            "by_risk_atr_bucket": _ranked_group_stats(_group_rows(rows, "risk_atr_bucket")),
            "by_volume_factor_bucket": _ranked_group_stats(_group_rows(rows, "volume_factor_bucket")),
            "by_retest_wait_bucket": _ranked_group_stats(_group_rows(rows, "retest_wait_bucket")),
        },
        "recommended_filters": {
            "symbol_signal_hour_blocks": _recommended_symbol_hour_blocks(
                rows,
                min_bucket_trades=min_bucket_trades,
                min_negative_years=min_negative_years,
            )
        },
    }


def _run_symbol(
    monthly_client: httpx.Client,
    rest_client: httpx.Client,
    *,
    proxy_symbol: str,
    canonical_symbol: str,
    lookback_days: int,
    exit_policy: Any | None = None,
    entry_timing_model: str = "confirmed_5m_retest",
    signal_contracts: list[dict[str, Any]] | None = None,
    include_trades: bool = False,
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
        exit_policy=exit_policy,
    )
    normalized_entry_timing = str(entry_timing_model or "confirmed_5m_retest").strip().lower()
    if normalized_entry_timing in {"intrabar", "intrabar_1m", "intrabar_1m_confirm_next_open"}:
        normalized_entry_timing = "intrabar_1m_confirm_next_open"
        trades = engine.intrabar_backtest()
    else:
        normalized_entry_timing = "confirmed_5m_retest"
        trades = engine.backtest()
    raw_trade_count = len(trades)
    trades = _filter_trades_by_signal_contracts(
        trades=trades,
        canonical_symbol=canonical_symbol,
        signal_contracts=list(signal_contracts or []),
    )
    summary = summarize_micro_trades(trades)
    summary["decision"] = decision_for_micro_summary(summary)
    payload = {
        "proxy_symbol": proxy_symbol,
        "canonical_symbol": canonical_symbol,
        "profile_name": session_impulse_retest_profile_for_symbol(canonical_symbol),
        "entry_timing_model": normalized_entry_timing,
        "raw_trade_count_before_signal_contract": raw_trade_count,
        "signal_contracts": list(signal_contracts or []),
        "exit_policy": asdict(engine.exit_policy),
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
    if include_trades:
        profile_name = session_impulse_retest_profile_for_symbol(canonical_symbol)
        payload["trades"] = [
            _trade_to_row(
                trade=trade,
                proxy_symbol=proxy_symbol,
                canonical_symbol=canonical_symbol,
                profile_name=profile_name,
            )
            for trade in trades
        ]
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
                include_trades=bool(args.include_trades or args.write_loss_analysis),
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
                    "loss_analysis": _build_loss_analysis(
                        [
                            row
                            for item in results.values()
                            for row in list(dict(item or {}).get("trades") or [])
                        ],
                        min_bucket_trades=int(args.loss_analysis_min_bucket_trades),
                        min_negative_years=int(args.loss_analysis_min_negative_years),
                    )
                    if args.write_loss_analysis
                    else None,
                    "report_path": str(out_path),
                    "status": "running",
                }
                atomic_write_text(out_path, json.dumps(partial_payload, ensure_ascii=False, indent=2))

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
    if args.write_loss_analysis:
        trade_rows = [
            row
            for item in results.values()
            for row in list(dict(item or {}).get("trades") or [])
        ]
        payload["loss_analysis"] = _build_loss_analysis(
            trade_rows,
            min_bucket_trades=int(args.loss_analysis_min_bucket_trades),
            min_negative_years=int(args.loss_analysis_min_negative_years),
        )

    if out_path is not None:
        payload["report_path"] = str(out_path)
        atomic_write_text(out_path, json.dumps(payload, ensure_ascii=False, indent=2))

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
