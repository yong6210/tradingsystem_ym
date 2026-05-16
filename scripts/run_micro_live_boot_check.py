#!/usr/bin/env python3
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

from app.core.config import get_settings
from scripts import run_binance_rule_drift_snapshot
from scripts import run_live_reconciliation_watchdog
from scripts import run_micro_live_failure_drill
from scripts import run_micro_live_runtime_guard
from scripts import run_micro_live_synthetic_canary
from scripts.operation_report_io import atomic_write_text, display_path, parse_report_generated_at, write_latest_aliases
from scripts.run_micro_live_preflight import _csv_set


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
    return True if value else False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run no-order-sent MICRO_LIVE boot checks before starting the live worker.")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--symbol", default="")
    parser.add_argument("--check-binance-rules", action="store_true")
    parser.add_argument("--canary-network", action="store_true", help="Allow public Binance reads in the synthetic canary.")
    parser.add_argument("--report-dir", default="reports/operations/micro_live_boot_check")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--no-fail-exit", action="store_true")
    parser.add_argument("--quiet", action="store_true", help="Do not print the JSON payload to stdout.")
    return parser.parse_args()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _display_path(path: Path) -> str:
    return display_path(path, ROOT_DIR)


def _csv_items(value: Any) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for item in str(value or "").split(","):
        normalized = item.strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        items.append(normalized)
    return items


def _first_symbol(explicit: str) -> str:
    value = str(explicit or "").strip().upper()
    if value:
        return value
    settings = get_settings()
    allowed_symbols = _csv_items(getattr(settings, "auto_trading_micro_live_allowed_symbols", ""))
    allowed_symbol_set = set(allowed_symbols)
    for priority_symbol in _csv_items(getattr(settings, "auto_trading_micro_live_symbol_priority", "")):
        if not allowed_symbol_set or priority_symbol in allowed_symbol_set:
            return priority_symbol
    return allowed_symbols[0] if allowed_symbols else "BTCUSDC"


def _first_entry_model() -> str:
    settings = get_settings()
    for entry_model in _csv_items(getattr(settings, "auto_trading_micro_live_allowed_entry_models", "")):
        if entry_model:
            return entry_model
    return "LIMIT"


def _component(name: str, status: str, *, blocking: bool, summary: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "blocking": bool(blocking),
        "summary": summary,
        "payload": dict(payload or {}),
    }


def _rule_drift_component() -> dict[str, Any]:
    settings = get_settings()
    symbols = sorted(_csv_set(getattr(settings, "auto_trading_micro_live_allowed_symbols", "")))
    snapshot_dir = ROOT_DIR / "reports/operations/binance_rule_snapshots"
    baseline = run_binance_rule_drift_snapshot._read_json(snapshot_dir / "latest.json")
    current = run_binance_rule_drift_snapshot.build_snapshot(symbols=symbols)
    drift = run_binance_rule_drift_snapshot.compare_rule_snapshots(previous=baseline, current=current) if baseline else []
    payload = {
        "symbols": symbols,
        "baseline_available": bool(baseline),
        "drift_count": len(drift),
        "drift": drift,
    }
    status = "FAIL" if drift else "PASS"
    summary = f"symbols={len(symbols)} drift={len(drift)} baseline={'yes' if baseline else 'no'}"
    return _component("binance_rule_drift", status, blocking=bool(drift), summary=summary, payload=payload)


def build_payload(
    *,
    days: int,
    limit: int,
    symbol: str,
    check_binance_rules: bool,
    canary_network: bool,
) -> dict[str, Any]:
    generated_at = datetime.now(UTC)
    components: list[dict[str, Any]] = []

    runtime = run_micro_live_runtime_guard.build_payload(
        days=max(1, int(days)),
        limit=max(1, int(limit)),
        check_binance_rules=bool(check_binance_rules),
    )
    components.append(
        _component(
            "runtime_guard",
            str(runtime.get("overall_status") or "FAIL"),
            blocking=str(runtime.get("overall_status") or "").upper() != "PASS",
            summary=f"blocking_failures={len(runtime.get('blocking_failures') or [])}",
            payload=runtime,
        )
    )

    stale_minutes = run_live_reconciliation_watchdog._default_stale_minutes(0)
    reconciliation = run_live_reconciliation_watchdog.build_payload(
        days=max(1, int(days)),
        symbols=set(),
        limit=max(1, int(limit)),
        stale_minutes=stale_minutes,
        event_lookback_minutes=60,
    )
    reconciliation_eval = dict(reconciliation.get("evaluation") or {})
    components.append(
        _component(
            "reconciliation_watchdog",
            "FAIL" if _safe_bool(reconciliation_eval.get("alert")) else "PASS",
            blocking=_safe_bool(reconciliation_eval.get("alert")),
            summary=str(reconciliation_eval.get("message") or ""),
            payload=reconciliation,
        )
    )

    canary = run_micro_live_synthetic_canary.run_canary(
        symbol=_first_symbol(symbol),
        direction="long",
        entry_model=_first_entry_model(),
        entry_price=0.0,
        stop_bps=50.0,
        use_network=bool(canary_network),
    )
    components.append(
        _component(
            "synthetic_submit_canary",
            str(canary.get("overall_status") or "FAIL"),
            blocking=str(canary.get("overall_status") or "").upper() != "PASS",
            summary=(
                f"symbol={canary.get('symbol')} entry_model={canary.get('entry_model')} "
                f"no_live_order_sent={canary.get('no_live_order_sent')}"
            ),
            payload=canary,
        )
    )

    failure_drill = run_micro_live_failure_drill.build_payload()
    components.append(
        _component(
            "failure_contract_drill",
            str(failure_drill.get("overall_status") or "FAIL"),
            blocking=str(failure_drill.get("overall_status") or "").upper() != "PASS",
            summary=(
                f"scenarios={failure_drill.get('scenario_count')} "
                f"failed={failure_drill.get('failed_count')}"
            ),
            payload=failure_drill,
        )
    )

    if check_binance_rules:
        try:
            components.append(_rule_drift_component())
        except Exception as exc:
            components.append(
                _component(
                    "binance_rule_drift",
                    "FAIL",
                    blocking=True,
                    summary=f"{exc.__class__.__name__}:{exc}",
                    payload={},
                )
            )

    blocking_failures = [item for item in components if _safe_bool(item.get("blocking"))]
    return {
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "overall_status": "FAIL" if blocking_failures else "PASS",
        "blocking_failure_count": len(blocking_failures),
        "components": components,
        "next_actions": [
            f"fix_{item.get('name')}:{item.get('summary')}" for item in blocking_failures[:8]
        ],
    }


def _write_report(path: Path, payload: dict[str, Any], *, atomic: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# MICRO_LIVE Boot Check",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- overall_status: {payload.get('overall_status')}",
        f"- blocking_failure_count: {payload.get('blocking_failure_count')}",
        "",
        "## Components",
        "",
    ]
    for item in payload.get("components") or []:
        lines.append(f"- {item.get('name')}: {item.get('status')} | {item.get('summary')}")
    lines.extend(["", "```json", json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), "```"])
    content = "\n".join(lines)
    if atomic:
        atomic_write_text(path, content)
    else:
        atomic_write_text(path, content)


def main() -> int:
    args = parse_args()
    payload = build_payload(
        days=max(1, int(args.days)),
        limit=max(1, int(args.limit)),
        symbol=str(args.symbol or ""),
        check_binance_rules=bool(args.check_binance_rules),
        canary_network=bool(args.canary_network),
    )
    if not args.no_write_report:
        generated = parse_report_generated_at(payload.get("generated_at"))
        report_dir = ROOT_DIR / args.report_dir
        report_path = report_dir / f"micro_live_boot_check_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
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
    if not bool(args.quiet):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 1 if payload["overall_status"] != "PASS" and not bool(args.no_fail_exit) else 0


if __name__ == "__main__":
    raise SystemExit(main())
