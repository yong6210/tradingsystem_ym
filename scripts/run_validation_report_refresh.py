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
from app.db.session import SessionLocal, init_db
from app.services.strategy_engine import StrategyEngine
from scripts.operation_report_io import atomic_write_text, display_path, write_latest_aliases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh the read-only validation/report payload cache for MICRO_LIVE.")
    parser.add_argument("--symbol", default="", help="Symbol to refresh. Empty uses the configured live probe symbol.")
    parser.add_argument("--report-dir", default="reports/operations/validation_report_refresh")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--no-fail-exit", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _display_path(path: Path) -> str:
    return display_path(path, ROOT_DIR)


def _first_csv_value(raw: Any) -> str:
    for item in str(raw or "").split(","):
        text = str(item or "").strip().upper()
        if text:
            return text
    return ""


def _target_symbol(raw_symbol: str) -> str:
    explicit = str(raw_symbol or "").strip().upper()
    if explicit:
        return explicit
    settings = get_settings()
    return (
        str(getattr(settings, "ready_market_data_probe_symbol", "") or "").strip().upper()
        or _first_csv_value(getattr(settings, "auto_trading_micro_live_allowed_symbols", ""))
        or "BTCUSDT"
    )


def _write_markdown_report(path: Path, payload: dict[str, Any], *, atomic: bool = False) -> None:
    lines = [
        "# Validation Report Refresh",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- overall_status: {payload.get('overall_status')}",
        f"- symbol: {payload.get('symbol')}",
        f"- cache_path: {payload.get('cache_path')}",
        f"- validation_status: {payload.get('validation_status')}",
        f"- approval_topline_status: {payload.get('approval_topline_status')}",
        f"- deployment_go_no_go: {payload.get('deployment_go_no_go')}",
        f"- error: {payload.get('error') or ''}",
        "",
        "```json",
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
    ]
    text = "\n".join(lines)
    if atomic:
        atomic_write_text(path, text)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def build_payload(*, symbol: str) -> dict[str, Any]:
    generated_at = datetime.now(UTC)
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        payload = engine.recompute_learning(
            symbol,
            persist_runtime_validation_artifacts=False,
            use_read_only_cache=False,
        )
        cache_path = engine._validation_payload_cache_path(symbol)
        cache_scope = engine._validation_payload_cache_scope()
    report = dict(payload.get("validation_report") or {})
    return {
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "overall_status": "PASS",
        "symbol": symbol,
        "cache_path": _display_path(cache_path),
        "cache_scope": cache_scope,
        "validation_status": str(report.get("status") or ""),
        "approval_topline_status": str(payload.get("approval_topline_status") or report.get("approval_topline_status") or ""),
        "deployment_go_no_go": str(payload.get("deployment_go_no_go") or ""),
        "playbook_go_no_go": str(payload.get("playbook_go_no_go") or ""),
    }


def main() -> int:
    args = parse_args()
    symbol = _target_symbol(str(args.symbol or ""))
    try:
        payload = build_payload(symbol=symbol)
    except Exception as exc:
        payload = {
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "overall_status": "FAIL",
            "symbol": symbol,
            "cache_path": "",
            "cache_scope": "",
            "validation_status": "",
            "approval_topline_status": "",
            "deployment_go_no_go": "",
            "playbook_go_no_go": "",
            "error": str(exc),
        }

    if not bool(args.no_write_report):
        report_dir = (ROOT_DIR / str(args.report_dir)).resolve()
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        json_path = report_dir / f"validation_report_refresh_{stamp}.json"
        md_path = report_dir / f"validation_report_refresh_{stamp}.md"
        atomic_write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
        _write_markdown_report(md_path, payload, atomic=True)
        payload["report_path"] = _display_path(md_path)
        payload["json_path"] = _display_path(json_path)
        payload.update(
            write_latest_aliases(
                report_dir=report_dir,
                payload=payload,
                write_markdown_report=_write_markdown_report,
                root_dir=ROOT_DIR,
                json_default=_json_default,
            )
        )

    if not bool(args.quiet):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    if bool(args.no_fail_exit):
        return 0
    return 0 if str(payload.get("overall_status") or "").upper() == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
