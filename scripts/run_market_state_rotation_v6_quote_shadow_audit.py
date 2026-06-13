#!/usr/bin/env python3
"""Capture and audit v6 quote/liquidity shadow samples."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

EXPECTED_SYMBOL = "BTCUSDT"
EXPECTED_STRATEGY_FAMILY = "market_state_rotation_v6"
DEFAULT_SAMPLE_PATH = "data/shadow/market_state_rotation_v6_quote_shadow.jsonl"
REQUIRED_FIELDS = (
    "timestamp",
    "symbol",
    "strategy_family",
    "decision_id",
    "side",
    "best_bid",
    "best_ask",
    "spread_bps",
    "market_slippage_bps",
    "depth_notional",
    "latency_ms",
)


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _resolve(path: str) -> Path:
    raw = Path(path)
    return raw if raw.is_absolute() else ROOT_DIR / raw


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _binance_futures_client_cls() -> type:
    from app.integrations.binance_futures import BinanceFuturesClient

    return BinanceFuturesClient


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if isfinite(parsed) else float(default)


def _levels(raw_rows: Any) -> list[tuple[float, float]]:
    levels: list[tuple[float, float]] = []
    for row in list(raw_rows or []):
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        price = _safe_float(row[0])
        qty = _safe_float(row[1])
        if price > 0.0 and qty > 0.0:
            levels.append((price, qty))
    return levels


def _market_slippage_bps(*, levels: list[tuple[float, float]], mid: float, notional: float, side: str) -> float | None:
    if mid <= 0.0 or notional <= 0.0 or not levels:
        return None
    remaining = float(notional)
    cost = 0.0
    quantity = 0.0
    for price, qty in levels:
        level_notional = price * qty
        take_notional = min(remaining, level_notional)
        if take_notional <= 0.0:
            continue
        cost += take_notional
        quantity += take_notional / price
        remaining -= take_notional
        if remaining <= 1e-9:
            break
    if quantity <= 0.0 or remaining > max(1e-6, notional * 0.001):
        return None
    avg_price = cost / quantity
    if side == "long":
        return round(max(0.0, (avg_price - mid) / mid * 10_000.0), 4)
    return round(max(0.0, (mid - avg_price) / mid * 10_000.0), 4)


def build_quote_shadow_row(
    *,
    order_book: dict[str, Any],
    timestamp: datetime,
    symbol: str,
    strategy_family: str,
    decision_id: str,
    side: str,
    order_notional_usdt: float,
    latency_ms: float,
) -> dict[str, Any]:
    normalized_side = str(side or "").lower()
    if normalized_side not in {"long", "short"}:
        raise ValueError("side_must_be_long_or_short")
    bids = _levels(order_book.get("bids"))
    asks = _levels(order_book.get("asks"))
    best_bid = bids[0][0] if bids else 0.0
    best_ask = asks[0][0] if asks else 0.0
    mid = (best_bid + best_ask) / 2.0 if best_bid > 0.0 and best_ask > 0.0 else 0.0
    opposite = asks if normalized_side == "long" else bids
    depth_notional = sum(price * qty for price, qty in opposite)
    spread_bps = ((best_ask - best_bid) / mid * 10_000.0) if mid > 0.0 else None
    return {
        "timestamp": timestamp.astimezone(UTC).isoformat(),
        "symbol": str(symbol or "").upper(),
        "strategy_family": str(strategy_family or ""),
        "decision_id": str(decision_id or ""),
        "side": normalized_side,
        "best_bid": round(best_bid, 8),
        "best_ask": round(best_ask, 8),
        "spread_bps": round(float(spread_bps), 4) if spread_bps is not None else None,
        "market_slippage_bps": _market_slippage_bps(
            levels=opposite,
            mid=mid,
            notional=float(order_notional_usdt),
            side=normalized_side,
        ),
        "depth_notional": round(depth_notional, 4),
        "latency_ms": round(float(latency_ms), 4),
        "order_notional_usdt": round(float(order_notional_usdt), 4),
        "source": "binance_public_order_book",
    }


def capture_quote_shadow_rows(
    *,
    symbol: str = EXPECTED_SYMBOL,
    strategy_family: str = EXPECTED_STRATEGY_FAMILY,
    decision_id: str = "",
    side: str = "both",
    order_notional_usdt: float = 125.0,
    order_book_limit: int = 100,
) -> list[dict[str, Any]]:
    client = _binance_futures_client_cls()()
    started = time.perf_counter()
    book = client.fetch_order_book(symbol=symbol.upper(), limit=max(5, int(order_book_limit)))
    latency_ms = (time.perf_counter() - started) * 1000.0
    timestamp = datetime.now(UTC)
    sides = ["long", "short"] if str(side).lower() == "both" else [str(side).lower()]
    base_id = decision_id or f"quote_shadow_{timestamp.strftime('%Y%m%dT%H%M%S')}"
    return [
        build_quote_shadow_row(
            order_book=book,
            timestamp=timestamp,
            symbol=symbol,
            strategy_family=strategy_family,
            decision_id=f"{base_id}_{row_side}",
            side=row_side,
            order_notional_usdt=float(order_notional_usdt),
            latency_ms=latency_ms,
        )
        for row_side in sides
    ]


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            rows.append({"_invalid_json": text})
            continue
        rows.append(dict(payload) if isinstance(payload, dict) else {"_invalid_type": str(type(payload).__name__)})
    return rows


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n")


def _p95(values: list[float]) -> float | None:
    clean = sorted(value for value in values if isfinite(value))
    if not clean:
        return None
    index = int(0.95 * (len(clean) - 1))
    return round(clean[index], 4)


def _coverage(timestamps: list[datetime | None], *, generated_at: datetime) -> dict[str, Any]:
    clean = sorted(item for item in timestamps if item is not None)
    hour_counts: dict[str, int] = {}
    for item in clean:
        key = f"{item.hour:02d}"
        hour_counts[key] = hour_counts.get(key, 0) + 1
    covered_hours = sorted(hour_counts)
    missing_hours = [f"{hour:02d}" for hour in range(24) if f"{hour:02d}" not in hour_counts]
    first_ts = clean[0] if clean else None
    latest_ts = clean[-1] if clean else None
    latest_age_hours = (
        round(max((generated_at - latest_ts).total_seconds(), 0.0) / 3600.0, 4)
        if latest_ts is not None
        else None
    )
    return {
        "first_sample_ts": first_ts.isoformat() if first_ts is not None else None,
        "latest_sample_ts": latest_ts.isoformat() if latest_ts is not None else None,
        "latest_sample_age_hours": latest_age_hours,
        "utc_hour_of_day_covered_count": len(covered_hours),
        "utc_hour_of_day_covered": covered_hours,
        "utc_hour_of_day_missing": missing_hours,
        "utc_hour_of_day_counts": dict(sorted(hour_counts.items())),
    }


def build_quote_shadow_audit_report(
    rows: list[dict[str, Any]],
    *,
    input_sample_path: str | None = None,
    expected_symbol: str = EXPECTED_SYMBOL,
    expected_strategy_family: str = EXPECTED_STRATEGY_FAMILY,
    required_quote_samples: int = 300,
    min_calendar_days: int = 30,
    min_distinct_hours: int = 24,
    max_p95_spread_bps: float = 4.0,
    max_p95_market_slippage_bps: float = 8.0,
    max_p95_latency_ms: float = 1500.0,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    schema_failures: list[dict[str, Any]] = []
    eligible_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        missing = [field for field in REQUIRED_FIELDS if row.get(field) in {None, ""}]
        if missing:
            schema_failures.append({"row_index": idx, "missing_fields": missing})
            continue
        if str(row.get("symbol") or "").upper() != expected_symbol.upper():
            continue
        if str(row.get("strategy_family") or "") != expected_strategy_family:
            continue
        eligible_rows.append(row)

    timestamps = [_parse_ts(row.get("timestamp")) for row in eligible_rows]
    calendar_days = sorted({item.date().isoformat() for item in timestamps if item is not None})
    distinct_hours = sorted({item.strftime("%Y-%m-%dT%H:00Z") for item in timestamps if item is not None})
    p95_spread = _p95([_safe_float(row.get("spread_bps"), float("nan")) for row in eligible_rows])
    p95_slippage = _p95([_safe_float(row.get("market_slippage_bps"), float("nan")) for row in eligible_rows])
    p95_latency = _p95([_safe_float(row.get("latency_ms"), float("nan")) for row in eligible_rows])

    blockers: list[str] = []
    if schema_failures:
        blockers.append("schema_failures")
    if len(eligible_rows) < int(required_quote_samples):
        blockers.append("quote_samples_missing")
    if len(calendar_days) < int(min_calendar_days):
        blockers.append("calendar_days_missing")
    if len(distinct_hours) < int(min_distinct_hours):
        blockers.append("distinct_hours_missing")
    if p95_spread is None or p95_spread > float(max_p95_spread_bps):
        blockers.append("p95_spread_bps_failed")
    if p95_slippage is None or p95_slippage > float(max_p95_market_slippage_bps):
        blockers.append("p95_market_slippage_bps_failed")
    if p95_latency is None or p95_latency > float(max_p95_latency_ms):
        blockers.append("p95_latency_ms_failed")

    hard_failures = {
        "schema_failures",
        "p95_spread_bps_failed",
        "p95_market_slippage_bps_failed",
        "p95_latency_ms_failed",
    }
    status = "PASS" if not blockers else ("FAIL" if any(item in hard_failures for item in blockers) else "INCOMPLETE")
    return {
        "created_at": generated_at.isoformat(),
        "overall_status": status,
        "input_sample_path": input_sample_path,
        "expected_symbol": expected_symbol.upper(),
        "expected_strategy_family": expected_strategy_family,
        "row_count": len(rows),
        "eligible_row_count": len(eligible_rows),
        "required_quote_samples": int(required_quote_samples),
        "missing_quote_samples": max(int(required_quote_samples) - len(eligible_rows), 0),
        "calendar_day_count": len(calendar_days),
        "min_calendar_days": int(min_calendar_days),
        "calendar_days": calendar_days,
        "distinct_hour_count": len(distinct_hours),
        "min_distinct_hours": int(min_distinct_hours),
        "distinct_hours": distinct_hours[:200],
        "coverage": _coverage(timestamps, generated_at=generated_at),
        "schema_failure_count": len(schema_failures),
        "schema_failures": schema_failures[:20],
        "metrics": {
            "p95_spread_bps": p95_spread,
            "p95_market_slippage_bps": p95_slippage,
            "p95_latency_ms": p95_latency,
        },
        "gates": {
            "min_distinct_hours": int(min_distinct_hours),
            "max_p95_spread_bps": float(max_p95_spread_bps),
            "max_p95_market_slippage_bps": float(max_p95_market_slippage_bps),
            "max_p95_latency_ms": float(max_p95_latency_ms),
        },
        "blockers": blockers,
    }


def _markdown(report: dict[str, Any]) -> str:
    metrics = dict(report.get("metrics") or {})
    return "\n".join(
        [
            "# Market State Rotation V6 Quote Shadow Audit",
            "",
            f"- Status: `{report.get('overall_status')}`",
            f"- Eligible rows: `{report.get('eligible_row_count')}/{report.get('required_quote_samples')}`",
            f"- Calendar days: `{report.get('calendar_day_count')}/{report.get('min_calendar_days')}`",
            f"- Distinct hours: `{report.get('distinct_hour_count')}/{report.get('min_distinct_hours')}`",
            f"- p95 spread bps: `{metrics.get('p95_spread_bps')}`",
            f"- p95 market slippage bps: `{metrics.get('p95_market_slippage_bps')}`",
            f"- p95 latency ms: `{metrics.get('p95_latency_ms')}`",
            f"- Blockers: `{', '.join(report.get('blockers') or [])}`",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture and audit v6 quote/liquidity shadow evidence.")
    parser.add_argument("--sample-jsonl", default=DEFAULT_SAMPLE_PATH)
    parser.add_argument("--capture-current-sample", action="store_true")
    parser.add_argument("--symbol", default=EXPECTED_SYMBOL)
    parser.add_argument("--strategy-family", default=EXPECTED_STRATEGY_FAMILY)
    parser.add_argument("--decision-id", default="")
    parser.add_argument("--side", choices=["long", "short", "both"], default="both")
    parser.add_argument("--order-notional-usdt", type=float, default=125.0)
    parser.add_argument("--order-book-limit", type=int, default=100)
    parser.add_argument("--required-quote-samples", type=int, default=300)
    parser.add_argument("--min-calendar-days", type=int, default=30)
    parser.add_argument("--min-distinct-hours", type=int, default=24)
    parser.add_argument("--max-p95-spread-bps", type=float, default=4.0)
    parser.add_argument("--max-p95-market-slippage-bps", type=float, default=8.0)
    parser.add_argument("--max-p95-latency-ms", type=float, default=1500.0)
    parser.add_argument("--report-dir", default="reports/validation/diagnostics/market_state_rotation_v6_quote_shadow_audit")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sample_path = _resolve(args.sample_jsonl)
    captured_rows: list[dict[str, Any]] = []
    if args.capture_current_sample:
        captured_rows = capture_quote_shadow_rows(
            symbol=str(args.symbol or EXPECTED_SYMBOL),
            strategy_family=str(args.strategy_family or EXPECTED_STRATEGY_FAMILY),
            decision_id=str(args.decision_id or ""),
            side=str(args.side or "both"),
            order_notional_usdt=float(args.order_notional_usdt),
            order_book_limit=max(5, int(args.order_book_limit)),
        )
        _append_jsonl(sample_path, captured_rows)
    rows = _load_jsonl(sample_path)
    report = build_quote_shadow_audit_report(
        rows,
        input_sample_path=_display_path(sample_path),
        expected_symbol=str(args.symbol or EXPECTED_SYMBOL),
        expected_strategy_family=str(args.strategy_family or EXPECTED_STRATEGY_FAMILY),
        required_quote_samples=max(1, int(args.required_quote_samples)),
        min_calendar_days=max(1, int(args.min_calendar_days)),
        min_distinct_hours=max(1, int(args.min_distinct_hours)),
        max_p95_spread_bps=float(args.max_p95_spread_bps),
        max_p95_market_slippage_bps=float(args.max_p95_market_slippage_bps),
        max_p95_latency_ms=float(args.max_p95_latency_ms),
    )
    report["captured_row_count"] = len(captured_rows)
    if args.write_report:
        report_dir = _resolve(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_quote_shadow_audit.json"
        md_path = report_dir / "market_state_rotation_v6_quote_shadow_audit.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    return 0 if report["overall_status"] in {"PASS", "INCOMPLETE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
