from __future__ import annotations

import argparse
from collections import Counter
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal, init_db
from app.services.strategy_engine import StrategyEngine
from scripts.operation_report_io import atomic_write_text, display_path, write_latest_aliases


_HARD_STATUSES = {"intent_creation_failed", "submit_error"}
_WATCH_STATUSES = {
    "auto_trading_disabled_or_shadow_mode",
    "family_disabled",
    "family_shadow_only",
    "symbol_not_live_enabled_for_auto_route",
}


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _display_path(path: Path) -> str:
    return display_path(path, ROOT)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize recent session_impulse_retest runtime audits.")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--phase", type=str, default=None)
    parser.add_argument("--status", type=str, default=None)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--report-dir", default="reports/operations/session_impulse_retest_runtime_audit")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--no-fail-exit", action="store_true")
    return parser.parse_args()


def _status_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    phase_counts = Counter(str(row.get("phase") or "unknown") for row in rows)
    status_counts = Counter(str(row.get("status") or "unknown") for row in rows)
    decision_counts = Counter(str(row.get("decision_code") or "none") for row in rows)
    hard = {key: value for key, value in status_counts.items() if key in _HARD_STATUSES or key.endswith("_error")}
    watch = {key: value for key, value in status_counts.items() if key in _WATCH_STATUSES}
    if hard:
        overall_status = "FAIL"
        reason = "runtime_audit_has_hard_route_failures"
    elif not rows:
        overall_status = "WATCH"
        reason = "no_recent_session_impulse_retest_runtime_audits"
    else:
        overall_status = "PASS"
        reason = "runtime_audit_recent_and_no_hard_route_failures"
    return {
        "overall_status": overall_status,
        "reason": reason,
        "audit_count": len(rows),
        "phase_counts": dict(sorted(phase_counts.items())),
        "status_counts": dict(status_counts.most_common()),
        "decision_code_counts": dict(decision_counts.most_common(10)),
        "hard_status_counts": hard,
        "watch_status_counts": watch,
    }


def _compact_audit(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row.get("payload") or {})
    diagnostics = dict(payload.get("plan_generation_diagnostics") or {})
    result_rows = [dict(item) for item in list(payload.get("results") or []) if isinstance(item, dict)]
    return {
        "audit_id": str(row.get("audit_id") or ""),
        "symbol": str(row.get("symbol") or ""),
        "phase": str(row.get("phase") or ""),
        "status": str(row.get("status") or ""),
        "plan_id": str(row.get("plan_id") or ""),
        "decision_code": str(row.get("decision_code") or ""),
        "observed_ts": str(row.get("observed_ts") or ""),
        "payload_summary": {
            "reason": str(payload.get("reason") or ""),
            "requested_mode": str(payload.get("requested_mode") or ""),
            "plans_considered": payload.get("plans_considered"),
            "intents_created": payload.get("intents_created"),
            "submit_calls": payload.get("submit_calls"),
            "session_impulse_retest_generated_count": payload.get("session_impulse_retest_generated_count"),
            "generation_state": str(diagnostics.get("generation_state") or ""),
            "result_statuses": [str(item.get("status") or "") for item in result_rows[:5]],
            "result_decision_codes": [
                str(dict(item.get("intent") or {}).get("decision_reason_code") or "")
                for item in result_rows[:5]
            ],
        },
    }


def build_payload(
    *,
    hours: int,
    symbol: str | None,
    phase: str | None,
    status: str | None,
    limit: int,
) -> dict[str, Any]:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        rows = engine.session_impulse_retest_runtime_audits_recent(
            hours=max(1, int(hours)),
            symbol=symbol,
            phase=phase,
            status=status,
            limit=max(1, int(limit)),
        )
    summary = _status_summary(rows)
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "hours": max(1, int(hours)),
        "symbol": str(symbol or ""),
        "phase_filter": str(phase or ""),
        "status_filter": str(status or ""),
        **summary,
        "recent_audits": [_compact_audit(row) for row in rows[: max(1, int(limit))]],
    }


def _write_report(path: Path, payload: dict[str, Any], *, atomic: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Session Impulse Retest Runtime Audit",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- overall_status: {payload.get('overall_status')}",
        f"- reason: {payload.get('reason')}",
        f"- hours: {payload.get('hours')}",
        f"- audit_count: {payload.get('audit_count')}",
        f"- phase_counts: {payload.get('phase_counts')}",
        f"- status_counts: {payload.get('status_counts')}",
        "",
        "## Recent Audits",
        "",
    ]
    for row in list(payload.get("recent_audits") or [])[:20]:
        lines.append(
            "- "
            f"{row.get('observed_ts')} {row.get('symbol')} "
            f"{row.get('phase')}/{row.get('status')} "
            f"plan={row.get('plan_id') or 'none'} decision={row.get('decision_code') or 'none'}"
        )
    if not payload.get("recent_audits"):
        lines.append("- none")
    lines.extend(["", "```json", json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), "```"])
    content = "\n".join(lines)
    if atomic:
        atomic_write_text(path, content)
    else:
        path.write_text(content, encoding="utf-8")


def main() -> None:
    args = parse_args()
    payload = build_payload(
        hours=max(1, int(args.hours)),
        symbol=args.symbol,
        phase=args.phase,
        status=args.status,
        limit=max(1, int(args.limit)),
    )
    if not args.no_write_report:
        generated = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
        report_dir = ROOT / args.report_dir
        report_path = report_dir / f"session_impulse_retest_runtime_audit_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
        payload["report_path"] = _display_path(report_path)
        payload["latest_report_path"] = _display_path(report_dir / "latest.md")
        payload["latest_json_path"] = _display_path(report_dir / "latest.json")
        _write_report(report_path, payload)
        payload.update(
            write_latest_aliases(
                report_dir=report_dir,
                payload=payload,
                write_markdown_report=_write_report,
                root_dir=ROOT,
                json_default=_json_default,
            )
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    if payload.get("overall_status") == "FAIL" and not bool(args.no_fail_exit):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
