#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.integrations.binance_futures import BinanceFuturesClient
from scripts.operation_report_io import atomic_write_text, display_path, write_latest_aliases


def _display_path(path: Path) -> str:
    return display_path(path, ROOT_DIR)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync Binance USD-M symbol leverage to the configured live cap.")
    parser.add_argument("--symbols", default="", help="Optional comma-separated symbols. Empty uses current MICRO_LIVE universe.")
    parser.add_argument("--target-leverage", type=int, default=0, help="Target leverage. Default uses AUTO_TRADING_LIVE_LEVERAGE_CAP.")
    parser.add_argument("--apply", action="store_true", help="Apply exchange leverage changes. Without this, only reports planned changes.")
    parser.add_argument("--no-include-open-positions", action="store_true", help="Do not add currently open account positions to the sync scope.")
    parser.add_argument("--report-dir", default="reports/operations/live_leverage_cap_sync")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--no-fail-exit", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _csv_list(raw: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in str(raw or "").split(","):
        symbol = item.strip().upper()
        if symbol and symbol not in seen:
            result.append(symbol)
            seen.add(symbol)
    return result


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if isfinite(parsed) else default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return int(parsed) if isfinite(parsed) else default


def _position_amount(row: dict[str, Any]) -> float:
    return _safe_float(row.get("position_amt", row.get("positionAmt")))


def _position_leverage(row: dict[str, Any]) -> int:
    return _safe_int(row.get("leverage"))


def _append_unique(target: list[str], symbol: str) -> None:
    normalized = str(symbol or "").strip().upper()
    if normalized and normalized not in set(target):
        target.append(normalized)


def _target_symbol_list(
    *,
    explicit_symbols: list[str],
    allowed_symbols: list[str],
    positions: list[dict[str, Any]],
    include_open_positions: bool,
) -> list[str]:
    target_symbols = list(explicit_symbols or allowed_symbols)
    if include_open_positions:
        for position in positions:
            if abs(_position_amount(position)) > 1e-12:
                _append_unique(target_symbols, str(position.get("symbol") or ""))
    return target_symbols


def _positions_by_symbol(positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for position in positions:
        symbol = str(position.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        amount = _position_amount(position)
        leverage = _position_leverage(position)
        row = grouped.setdefault(
            symbol,
            {
                "symbol": symbol,
                "position_amt": 0.0,
                "gross_position_amt": 0.0,
                "has_open_position": False,
                "leverage": 0,
            },
        )
        row["position_amt"] = float(row["position_amt"]) + amount
        row["gross_position_amt"] = float(row["gross_position_amt"]) + abs(amount)
        row["has_open_position"] = bool(row["has_open_position"]) or abs(amount) > 1e-12
        if leverage > int(row["leverage"]):
            row["leverage"] = leverage
    return grouped


def build_payload(
    *,
    symbols: list[str] | None = None,
    target_leverage: int | None = None,
    apply: bool = False,
    include_open_positions: bool = True,
) -> dict[str, Any]:
    settings = get_settings()
    configured_cap = _safe_int(getattr(settings, "auto_trading_live_leverage_cap", 0))
    target = int(target_leverage or configured_cap)
    if target <= 0:
        raise ValueError("target_leverage_must_be_positive")
    if target > 125:
        raise ValueError("target_leverage_too_high")

    client = BinanceFuturesClient()
    raw_positions = client.fetch_position_risk()
    positions = [client.normalize_position_risk_row(row) for row in raw_positions]
    allowed_symbols = _csv_list(getattr(settings, "auto_trading_micro_live_allowed_symbols", ""))
    target_symbols = _target_symbol_list(
        explicit_symbols=list(symbols or []),
        allowed_symbols=allowed_symbols,
        positions=positions,
        include_open_positions=include_open_positions,
    )
    positions_by_symbol = _positions_by_symbol(positions)
    rows: list[dict[str, Any]] = []
    fail_count = 0
    changed_count = 0
    pending_count = 0

    for symbol in target_symbols:
        position = positions_by_symbol.get(symbol)
        current = _position_leverage(position or {})
        amount = _position_amount(position or {})
        row: dict[str, Any] = {
            "symbol": symbol,
            "current_leverage": current,
            "target_leverage": target,
            "position_amt": amount,
            "gross_position_amt": _safe_float((position or {}).get("gross_position_amt")),
            "has_open_position": bool((position or {}).get("has_open_position")) or abs(amount) > 1e-12,
            "action": "already_target",
        }
        if current <= 0:
            row["action"] = "missing_position_risk"
            row["severity"] = "WARN"
            fail_count += 1
        elif current != target:
            if apply:
                try:
                    response = client.change_initial_leverage(symbol=symbol, leverage=target, live=True)
                except Exception as exc:
                    row["action"] = "failed"
                    row["severity"] = "FAIL"
                    row["error"] = f"{exc.__class__.__name__}:{exc}"
                    fail_count += 1
                else:
                    row["action"] = "changed"
                    row["severity"] = "INFO"
                    row["exchange_response"] = response
                    changed_count += 1
            else:
                row["action"] = "change_required"
                row["severity"] = "WARN"
                pending_count += 1
        rows.append(row)

    status = "ALERT" if fail_count else ("WATCH" if pending_count else "OK")
    if apply and changed_count and not fail_count:
        status = "OK"
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "overall_status": status,
        "severity": "FAIL" if fail_count else ("WARN" if pending_count else "INFO"),
        "dry_run": not apply,
        "configured_leverage_cap": configured_cap,
        "target_leverage": target,
        "requested_symbol_count": len(symbols or []),
        "allowed_symbol_count": len(allowed_symbols),
        "target_symbol_count": len(target_symbols),
        "changed_count": changed_count,
        "pending_count": pending_count,
        "fail_count": fail_count,
        "symbols": rows,
    }


def _write_report(path: Path, payload: dict[str, Any], *, atomic: bool = False) -> None:
    lines = [
        "# Live Leverage Cap Sync",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- status: {payload.get('overall_status')}",
        f"- dry_run: {payload.get('dry_run')}",
        f"- target_leverage: {payload.get('target_leverage')}x",
        f"- target_symbols: {payload.get('target_symbol_count')}",
        f"- changed: {payload.get('changed_count')}",
        f"- pending: {payload.get('pending_count')}",
        f"- failed: {payload.get('fail_count')}",
        "",
        "## Symbols",
        "",
    ]
    for row in list(payload.get("symbols") or [])[:80]:
        lines.append(
            f"- {row.get('symbol')}: {row.get('current_leverage')}x -> "
            f"{row.get('target_leverage')}x {row.get('action')}"
        )
    lines.extend(["", "```json", json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), "```"])
    atomic_write_text(path, "\n".join(lines))


def main() -> int:
    args = parse_args()
    try:
        payload = build_payload(
            symbols=_csv_list(args.symbols),
            target_leverage=args.target_leverage or None,
            apply=bool(args.apply),
            include_open_positions=not args.no_include_open_positions,
        )
    except Exception as exc:
        payload = {
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "overall_status": "ALERT",
            "severity": "FAIL",
            "dry_run": not bool(args.apply),
            "fail_count": 1,
            "error": f"{exc.__class__.__name__}:{exc}",
            "symbols": [],
        }
    if not args.no_write_report:
        generated = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
        report_dir = Path(args.report_dir)
        report_path = report_dir / f"live_leverage_cap_sync_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
        _write_report(report_path, payload, atomic=True)
        payload["report_path"] = display_path(report_path, ROOT_DIR)
        payload["latest_paths"] = write_latest_aliases(
            report_dir=report_dir,
            payload=payload,
            write_markdown_report=_write_report,
            root_dir=ROOT_DIR,
            json_default=_json_default,
        )
    if not args.quiet:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 1 if payload.get("overall_status") == "ALERT" and not args.no_fail_exit else 0


if __name__ == "__main__":
    raise SystemExit(main())
