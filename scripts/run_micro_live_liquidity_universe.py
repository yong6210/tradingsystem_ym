#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.integrations.binance_futures import BinanceFuturesClient
from scripts.operation_report_io import atomic_write_text, display_path, parse_report_generated_at, write_latest_aliases
from scripts.run_micro_live_synthetic_canary import run_canary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run the MICRO_LIVE sizing and liquidity path across the configured live universe."
    )
    parser.add_argument("--symbols", default="", help="Optional comma-separated symbols. Empty uses current MICRO_LIVE universe.")
    parser.add_argument("--directions", default="long,short", help="Comma-separated directions: long,short.")
    parser.add_argument("--entry-model", choices=["LIMIT", "CONFIRM"], default="CONFIRM")
    parser.add_argument("--stop-bps", type=float, default=50.0)
    parser.add_argument("--sleep-seconds", type=float, default=0.35, help="Delay between public API checks to avoid rate limits.")
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--retry-sleep-seconds", type=float, default=3.0)
    parser.add_argument("--report-dir", default="reports/operations/micro_live_liquidity_universe")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--no-network", action="store_true", help="Use synthetic liquidity instead of Binance public market data.")
    parser.add_argument("--use-private-balance", action="store_true", help="Fetch private futures balance once and reuse it for all checks.")
    parser.add_argument("--no-fail-exit", action="store_true")
    parser.add_argument("--quiet", action="store_true", help="Do not print the JSON payload to stdout.")
    return parser.parse_args()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _display_path(path: Path) -> str:
    return display_path(path, ROOT_DIR)


def _csv_list(raw: Any) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for item in str(raw or "").split(","):
        normalized = item.strip().upper()
        if normalized and normalized not in seen:
            values.append(normalized)
            seen.add(normalized)
    return values


def _directions(raw: Any) -> list[str]:
    values: list[str] = []
    for item in str(raw or "").split(","):
        normalized = item.strip().lower()
        if normalized in {"long", "short"} and normalized not in values:
            values.append(normalized)
    return values or ["long", "short"]


def _live_symbols(settings: Any, explicit_symbols: str = "") -> list[str]:
    explicit = _csv_list(explicit_symbols)
    if explicit:
        return explicit
    allowed = _csv_list(getattr(settings, "auto_trading_micro_live_allowed_symbols", ""))
    priority = _csv_list(getattr(settings, "auto_trading_micro_live_symbol_priority", ""))
    allowed_set = set(allowed)
    ordered = [symbol for symbol in priority if not allowed_set or symbol in allowed_set]
    ordered.extend(symbol for symbol in allowed if symbol not in set(ordered))
    return ordered


def _safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _canary_row(
    *,
    symbol: str,
    direction: str,
    entry_model: str,
    stop_bps: float,
    use_network: bool,
    max_retries: int,
    retry_sleep_seconds: float,
    balance_snapshot: Any | None,
) -> dict[str, Any]:
    attempts = max(1, int(max_retries) + 1)
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            payload = run_canary(
                symbol=symbol,
                direction=direction,
                entry_model=entry_model,
                entry_price=0.0,
                stop_bps=stop_bps,
                use_network=use_network,
                use_private_balance=False,
                balance_snapshot=balance_snapshot,
            )
            sizing = _safe_dict(payload.get("live_sizing"))
            gate = _safe_dict(payload.get("liquidity_gate"))
            tranche = _safe_dict(sizing.get("live_tranche"))
            return {
                "symbol": symbol,
                "direction": direction,
                "status": str(payload.get("overall_status") or "FAIL"),
                "decision": str(gate.get("decision") or "NOT_EVALUATED"),
                "reason_codes": list(gate.get("reason_codes") or []),
                "message": str(gate.get("message") or ""),
                "target_notional": sizing.get("target_notional"),
                "normalized_notional": sizing.get("normalized_notional"),
                "actual_risk_pct": sizing.get("actual_risk_pct"),
                "submitted_fraction": tranche.get("submitted_target_fraction")
                or sizing.get("liquidity_tranche_submitted_fraction"),
                "partial_error": gate.get("partial_submit_error"),
                "attempt": attempt,
            }
        except Exception as exc:  # pragma: no cover - exercised by integration/network runs.
            last_error = f"{exc.__class__.__name__}:{exc}"
            if attempt < attempts:
                time.sleep(max(float(retry_sleep_seconds), 0.0))
    return {
        "symbol": symbol,
        "direction": direction,
        "status": "ERROR",
        "decision": "ERROR",
        "reason_codes": ["canary_exception"],
        "message": last_error,
        "target_notional": None,
        "normalized_notional": None,
        "actual_risk_pct": None,
        "submitted_fraction": None,
        "partial_error": last_error,
        "attempt": attempts,
    }


def _direction_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    decision_counts = Counter(str(row.get("decision") or "UNKNOWN") for row in rows)
    reason_counts: Counter[str] = Counter()
    for row in rows:
        for reason in list(row.get("reason_codes") or []):
            reason_counts[str(reason)] += 1
        if row.get("partial_error"):
            reason_counts[str(row.get("partial_error"))] += 1
    return {
        "check_count": len(rows),
        "pass_count": sum(1 for row in rows if str(row.get("status")) == "PASS"),
        "fail_count": sum(1 for row in rows if str(row.get("status")) not in {"PASS"}),
        "by_decision": dict(sorted(decision_counts.items())),
        "by_reason": dict(sorted(reason_counts.items())),
        "blocked_symbols": [row["symbol"] for row in rows if str(row.get("status")) not in {"PASS"}],
        "partial_symbols": [row["symbol"] for row in rows if str(row.get("decision")) == "SPLIT_PARTIAL_SUBMIT"],
    }


def build_payload(
    *,
    symbols: str = "",
    directions: str = "long,short",
    entry_model: str = "CONFIRM",
    stop_bps: float = 50.0,
    sleep_seconds: float = 0.35,
    max_retries: int = 1,
    retry_sleep_seconds: float = 3.0,
    use_network: bool = True,
    use_private_balance: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    symbol_list = _live_symbols(settings, symbols)
    direction_list = _directions(directions)
    balance_snapshot: Any | None = None
    balance_error = ""
    if use_network and use_private_balance:
        try:
            balance_snapshot = {"source": "binance_futures_balance_once", "balances": BinanceFuturesClient().fetch_futures_balances()}
        except Exception as exc:
            balance_error = f"{exc.__class__.__name__}:{exc}"
    rows: list[dict[str, Any]] = []
    for direction in direction_list:
        for index, symbol in enumerate(symbol_list):
            if rows and sleep_seconds > 0.0:
                time.sleep(max(float(sleep_seconds), 0.0))
            rows.append(
                _canary_row(
                    symbol=symbol,
                    direction=direction,
                    entry_model=str(entry_model or "CONFIRM").upper(),
                    stop_bps=float(stop_bps or 50.0),
                    use_network=bool(use_network),
                    max_retries=max_retries,
                    retry_sleep_seconds=retry_sleep_seconds,
                    balance_snapshot=balance_snapshot,
                )
            )

    by_direction = {
        direction: _direction_summary([row for row in rows if str(row.get("direction")) == direction])
        for direction in direction_list
    }
    symbols_with_any_pass = sorted({row["symbol"] for row in rows if str(row.get("status")) == "PASS"})
    symbols_with_all_pass = [
        symbol
        for symbol in symbol_list
        if all(
            str(row.get("status")) == "PASS"
            for row in rows
            if row.get("symbol") == symbol and row.get("direction") in direction_list
        )
    ]
    error_count = sum(1 for row in rows if str(row.get("status")) == "ERROR")
    pass_count = sum(1 for row in rows if str(row.get("status")) == "PASS")
    check_count = len(rows)
    overall_status = "PASS" if pass_count == check_count else "WATCH" if pass_count > 0 and error_count == 0 else "FAIL"
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "overall_status": overall_status,
        "no_live_order_sent": True,
        "use_network": bool(use_network),
        "use_private_balance": bool(use_private_balance),
        "balance_source": "binance_futures_balance_once" if balance_snapshot is not None else "configured_or_synthetic",
        "balance_error": balance_error,
        "entry_model": str(entry_model or "CONFIRM").upper(),
        "stop_bps": float(stop_bps or 50.0),
        "symbol_count": len(symbol_list),
        "direction_count": len(direction_list),
        "check_count": check_count,
        "pass_count": pass_count,
        "fail_count": check_count - pass_count,
        "error_count": error_count,
        "executable_symbol_count": len(symbols_with_any_pass),
        "fully_executable_symbol_count": len(symbols_with_all_pass),
        "blocked_symbol_count": len(symbol_list) - len(symbols_with_any_pass),
        "symbols_with_any_pass": symbols_with_any_pass,
        "symbols_with_all_directions_pass": symbols_with_all_pass,
        "directions": direction_list,
        "by_direction": by_direction,
        "rows": rows,
    }


def _write_report(path: Path, payload: dict[str, Any], *, atomic: bool = False) -> None:
    lines = [
        "# MICRO_LIVE Liquidity Universe",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- overall_status: {payload.get('overall_status')}",
        f"- no_live_order_sent: {payload.get('no_live_order_sent')}",
        f"- symbols: {payload.get('symbol_count')}",
        f"- checks: {payload.get('pass_count')}/{payload.get('check_count')} pass",
        f"- executable_symbols: {payload.get('executable_symbol_count')}",
        f"- fully_executable_symbols: {payload.get('fully_executable_symbol_count')}",
        "",
    ]
    for direction, summary in dict(payload.get("by_direction") or {}).items():
        lines.append(
            f"- {direction}: pass={summary.get('pass_count')}/{summary.get('check_count')} "
            f"blocked={','.join(summary.get('blocked_symbols') or []) or 'none'} "
            f"partial={','.join(summary.get('partial_symbols') or []) or 'none'}"
        )
    lines.extend(["", "```json", json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), "```"])
    atomic_write_text(path, "\n".join(lines))


def main() -> int:
    args = parse_args()
    payload = build_payload(
        symbols=str(args.symbols or ""),
        directions=str(args.directions or "long,short"),
        entry_model=str(args.entry_model or "CONFIRM"),
        stop_bps=float(args.stop_bps or 50.0),
        sleep_seconds=float(args.sleep_seconds or 0.0),
        max_retries=int(args.max_retries or 0),
        retry_sleep_seconds=float(args.retry_sleep_seconds or 0.0),
        use_network=not bool(args.no_network),
        use_private_balance=bool(args.use_private_balance),
    )
    if not args.no_write_report:
        generated = parse_report_generated_at(payload.get("generated_at"))
        report_dir = ROOT_DIR / args.report_dir
        report_path = report_dir / f"micro_live_liquidity_universe_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
        payload["report_path"] = _display_path(report_path)
        payload["latest_report_path"] = _display_path(report_dir / "latest.md")
        payload["latest_json_path"] = _display_path(report_dir / "latest.json")
        _write_report(report_path, payload, atomic=True)
        payload.update(
            write_latest_aliases(
                report_dir=report_dir,
                payload=payload,
                write_markdown_report=_write_report,
                root_dir=ROOT_DIR,
                json_default=_json_default,
            )
        )
    if not args.quiet:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 1 if payload["overall_status"] == "FAIL" and not bool(args.no_fail_exit) else 0


if __name__ == "__main__":
    raise SystemExit(main())
