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

from app.db.session import SessionLocal, init_db
from app.services.live_order_lifecycle import LiveOrderLifecycleReporter
from scripts.operation_report_io import atomic_write_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a live order lifecycle report from intent/submission/fill/ledger rows.")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--symbol", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--include-paper", action="store_true", help="Include paper/test submissions instead of live-only rows.")
    parser.add_argument("--report-dir", default="reports/operations/live_order_lifecycle")
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _parse_generated_at(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = dict(payload.get("summary") or {})
    live_intents = dict(summary.get("live_intents") or {})
    rows = list(payload.get("rows") or [])

    lines = [
        "# Live Order Lifecycle Report",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- window_start: {payload.get('window_start')}",
        f"- window_days: {payload.get('window_days')}",
        f"- symbol: {payload.get('symbol') or 'ALL'}",
        f"- live_only: {payload.get('live_only')}",
        "",
        "## Summary",
        "",
        f"- submissions: {summary.get('submission_count', 0)}",
        f"- requested_live: {summary.get('requested_live_count', 0)}",
        f"- entry_fills: {summary.get('entry_fill_count', 0)}",
        f"- closed: {summary.get('closed_count', 0)}",
        f"- open_after_entry: {summary.get('open_after_entry_count', 0)}",
        f"- submitted_without_entry_fill: {summary.get('submitted_without_entry_fill_count', 0)}",
        f"- rejected_or_error: {summary.get('rejected_or_error_count', 0)}",
        f"- avg_entry_slippage_bps: {summary.get('avg_entry_slippage_bps')}",
        f"- avg_realized_r: {summary.get('avg_realized_r')}",
        f"- total_fee: {summary.get('total_fee', 0.0)}",
        "",
        "## Live Intent Funnel",
        "",
        f"- intents: {live_intents.get('total', 0)}",
        f"- submit_ready: {live_intents.get('submit_ready', 0)}",
        f"- blocked: {live_intents.get('blocked', 0)}",
    ]
    top_reasons = dict(live_intents.get("top_block_reasons") or {})
    if top_reasons:
        lines.append("- top_reasons: " + ", ".join(f"{key}={value}" for key, value in list(top_reasons.items())[:8]))

    lines.extend(["", "## Recent Rows", ""])
    if not rows:
        lines.append("- none")
    for row in rows[:20]:
        lines.append(
            "- "
            f"{row.get('symbol')} {row.get('lifecycle_status')} "
            f"mode={row.get('execution_mode')} state={row.get('state')} submit={row.get('submit_status')} "
            f"entry={row.get('entry_avg_price')} slip_bps={row.get('entry_slippage_bps')} "
            f"r={row.get('realized_r')} reason={row.get('exit_reason') or row.get('decision_reason_code')}"
        )

    lines.extend(["", "## Raw Payload", "", "```json"])
    lines.append(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    lines.append("```")
    atomic_write_text(path, "\n".join(lines))


def main() -> int:
    args = parse_args()
    init_db()
    with SessionLocal() as db:
        payload = LiveOrderLifecycleReporter(db).generate(
            days=max(1, int(args.days)),
            symbol=str(args.symbol or "").strip().upper() or None,
            live_only=not bool(args.include_paper),
            limit=max(1, int(args.limit)),
        )
    if not args.no_write_report:
        generated = _parse_generated_at(payload["generated_at"])
        symbol = str(payload.get("symbol") or "ALL")
        report_path = ROOT_DIR / args.report_dir / f"live_order_lifecycle_{symbol}_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
        _write_report(report_path, payload)
        payload["report_path"] = _display_path(report_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
