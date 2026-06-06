#!/usr/bin/env python3
"""Export market-state rotation v6 lifecycle rows as shadow-fill evidence."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.session import SessionLocal, init_db
from app.services.live_order_lifecycle import LiveOrderLifecycleReporter


EXPECTED_STRATEGY_FAMILY = "market_state_rotation_v6"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
        return False
    return default


def _normalize_status(row: dict[str, Any]) -> str:
    lifecycle = str(row.get("lifecycle_status") or "").strip().lower()
    state = str(row.get("state") or row.get("submit_status") or "").strip().lower()
    ledger_status = str(row.get("binance_ledger_status") or "").strip().lower()
    if lifecycle in {"closed", "open_after_entry", "exchange_flat_after_entry"}:
        return "filled"
    if lifecycle == "rejected_or_error" or state in {"rejected", "error", "failed"}:
        return "rejected"
    if ledger_status in {"partially_filled", "partial"}:
        return "partially_filled"
    if ledger_status:
        return ledger_status
    return state or lifecycle or "unknown"


def _normalize_side(row: dict[str, Any]) -> str:
    direction = str(row.get("plan_direction") or "").strip().lower()
    if direction in {"long", "short"}:
        return direction
    side = str(row.get("side") or "").strip().lower()
    if side in {"buy", "long"}:
        return "long"
    if side in {"sell", "short"}:
        return "short"
    return ""


def _order_side(row: dict[str, Any]) -> str:
    side = str(row.get("side") or "").strip().lower()
    if side in {"buy", "sell"}:
        return side
    direction = _normalize_side(row)
    if direction == "long":
        return "buy"
    if direction == "short":
        return "sell"
    return ""


def _fill_ratio(row: dict[str, Any]) -> float | None:
    original = _float(row.get("binance_orig_qty"))
    executed = _float(row.get("binance_executed_qty"))
    if original > 0.0:
        return round(max(0.0, min(executed / original, 1.0)), 6)
    if int(row.get("entry_fill_count") or 0) > 0:
        return 1.0
    return None


def _latency_ms(row: dict[str, Any]) -> float | None:
    fill_latency = row.get("fill_latency_ms")
    if fill_latency not in (None, ""):
        return round(max(_float(fill_latency), 0.0), 4)
    ack_latency = row.get("ack_latency_ms")
    if ack_latency not in (None, ""):
        return round(max(_float(ack_latency), 0.0), 4)
    return None


def lifecycle_rows_to_shadow_fills(
    lifecycle_payload: dict[str, Any],
    *,
    expected_symbol: str = "BTCUSDT",
    expected_strategy_family: str = EXPECTED_STRATEGY_FAMILY,
    include_rejected: bool = True,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    symbol_filter = str(expected_symbol or "").upper()
    for row in list(lifecycle_payload.get("rows") or []):
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        if symbol_filter and symbol != symbol_filter:
            continue
        family = str(row.get("strategy_family") or "")
        if expected_strategy_family and family != expected_strategy_family:
            continue
        status = _normalize_status(row)
        if not include_rejected and status == "rejected":
            continue
        shadow_row = {
            "timestamp": row.get("submitted_at") or row.get("acknowledged_at") or row.get("entry_first_fill_at"),
            "signal_ts": row.get("submitted_at"),
            "executed_at": row.get("entry_first_fill_at") or row.get("acknowledged_at"),
            "symbol": symbol,
            "strategy_family": expected_strategy_family,
            "decision_id": row.get("intent_id") or row.get("client_order_id") or row.get("submission_id"),
            "submission_id": row.get("submission_id"),
            "client_order_id": row.get("client_order_id"),
            "action": "add",
            "side": _normalize_side(row),
            "order_side": _order_side(row),
            "status": status,
            "expected_price": row.get("plan_entry_price") or row.get("binance_order_price"),
            "actual_price": row.get("entry_avg_price"),
            "slippage_bps": row.get("entry_slippage_bps"),
            "spread_bps": row.get("spread_bps") or row.get("top_of_book_spread_bps"),
            "latency_ms": _latency_ms(row),
            "fill_ratio": _fill_ratio(row),
            "executed_qty": row.get("binance_executed_qty"),
            "orig_qty": row.get("binance_orig_qty"),
            "fee_bps": None,
            "fee_total": row.get("fee_total"),
            "execution_mode": row.get("execution_mode"),
            "requested_live": _safe_bool(row.get("requested_live")),
            "source_lifecycle_status": row.get("lifecycle_status"),
            "source_state": row.get("state"),
            "source_submit_status": row.get("submit_status"),
            "source_message": row.get("message"),
        }
        rows.append(shadow_row)
    return rows


def build_shadow_fill_export_report(
    lifecycle_payload: dict[str, Any],
    *,
    input_lifecycle_report: str | None = None,
    expected_symbol: str = "BTCUSDT",
    expected_strategy_family: str = EXPECTED_STRATEGY_FAMILY,
    include_rejected: bool = True,
) -> dict[str, Any]:
    rows = lifecycle_rows_to_shadow_fills(
        lifecycle_payload,
        expected_symbol=expected_symbol,
        expected_strategy_family=expected_strategy_family,
        include_rejected=include_rejected,
    )
    status_counts: dict[str, int] = {}
    missing_counts = {
        "missing_actual_price": 0,
        "missing_slippage_bps": 0,
        "missing_latency_ms": 0,
        "missing_fill_ratio": 0,
    }
    for row in rows:
        status = str(row.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        if status != "rejected":
            if row.get("actual_price") is None:
                missing_counts["missing_actual_price"] += 1
            if row.get("slippage_bps") is None:
                missing_counts["missing_slippage_bps"] += 1
        if row.get("latency_ms") is None:
            missing_counts["missing_latency_ms"] += 1
        if row.get("fill_ratio") is None:
            missing_counts["missing_fill_ratio"] += 1
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "input_lifecycle_report": input_lifecycle_report,
        "expected_symbol": expected_symbol.upper(),
        "expected_strategy_family": expected_strategy_family,
        "row_count": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "missing_counts": missing_counts,
        "rows": rows,
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export market-state rotation v6 lifecycle rows as shadow-fill audit evidence."
    )
    parser.add_argument("--lifecycle-report", default="")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--strategy-family", default=EXPECTED_STRATEGY_FAMILY)
    parser.add_argument("--include-paper", action="store_true")
    parser.add_argument("--exclude-rejected", action="store_true")
    parser.add_argument("--report-dir", default="reports/validation/diagnostics/market_state_rotation_v6_shadow_fill_export")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    lifecycle_path = Path(args.lifecycle_report) if args.lifecycle_report else None
    if lifecycle_path is not None and not lifecycle_path.is_absolute():
        lifecycle_path = ROOT_DIR / lifecycle_path
    if lifecycle_path is not None:
        lifecycle_payload = _load_json(lifecycle_path)
        input_lifecycle_report = _display_path(lifecycle_path)
    else:
        init_db()
        with SessionLocal() as db:
            lifecycle_payload = LiveOrderLifecycleReporter(db).generate(
                days=max(1, int(args.days)),
                symbol=str(args.symbol or "BTCUSDT").upper(),
                live_only=not bool(args.include_paper),
                limit=max(1, int(args.limit)),
                strategy_families=[str(args.strategy_family or EXPECTED_STRATEGY_FAMILY)],
            )
        input_lifecycle_report = "generated_from_db"

    report = build_shadow_fill_export_report(
        lifecycle_payload,
        input_lifecycle_report=input_lifecycle_report,
        expected_symbol=str(args.symbol or "BTCUSDT").upper(),
        expected_strategy_family=str(args.strategy_family or EXPECTED_STRATEGY_FAMILY),
        include_rejected=not bool(args.exclude_rejected),
    )
    if args.write_report:
        report_dir = Path(args.report_dir)
        if not report_dir.is_absolute():
            report_dir = ROOT_DIR / report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_shadow_fill_export.json"
        jsonl_path = report_dir / "market_state_rotation_v6_shadow_fills.jsonl"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _write_jsonl(jsonl_path, list(report.get("rows") or []))
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(jsonl_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
