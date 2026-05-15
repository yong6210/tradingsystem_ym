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
from app.services.runtime_worker_heartbeat import read_worker_heartbeat
from app.services.strategy_engine import StrategyEngine
from scripts.operation_report_io import atomic_write_text, display_path, parse_report_generated_at, write_latest_aliases


_HARD_STATUSES = {"intent_creation_failed", "submit_error"}
_WATCH_STATUSES = {
    "auto_trading_disabled_or_shadow_mode",
    "family_disabled",
    "family_shadow_only",
    "symbol_not_live_enabled_for_auto_route",
}
_ORDER_BLOCKING_STATUSES = {
    "intent_blocked",
    "intent_creation_failed",
    "submit_error",
}
_NON_BLOCKING_STATUSES = {
    "recent_intent_cooldown_active",
    "ws_stream_active_route_suppressed",
}
_NO_CANDIDATE_STATUSES = {
    "no_fresh_candidates",
    "no_live_route_candidate_plan",
}


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _display_path(path: Path) -> str:
    return display_path(path, ROOT)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize recent session_impulse_retest runtime audits.")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--phase", type=str, default=None)
    parser.add_argument("--status", type=str, default=None)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--since-ws-start", action="store_true", help="Compatibility flag; runtime scope is the default when ws started_at is available.")
    parser.add_argument("--lookback-only", action="store_true", help="Ignore ws started_at and use the full --hours lookback as the active audit window.")
    parser.add_argument("--heartbeat-dir", default="")
    parser.add_argument("--report-dir", default="reports/operations/session_impulse_retest_runtime_audit")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--no-fail-exit", action="store_true")
    parser.add_argument("--quiet", action="store_true", help="Do not print the JSON payload to stdout.")
    return parser.parse_args()


def _parse_utc_ts(value: Any) -> datetime | None:
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


def _ws_runtime_started_at(heartbeat_dir: str = "") -> datetime | None:
    raw_dir = str(heartbeat_dir or "").strip()
    if raw_dir:
        try:
            payload = json.loads((Path(raw_dir).expanduser() / "ws.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    else:
        payload = read_worker_heartbeat("ws")
    details = dict(payload.get("details") or {}) if isinstance(payload, dict) else {}
    return _parse_utc_ts(details.get("started_at"))


def _rows_since(rows: list[dict[str, Any]], start_at: datetime | None) -> list[dict[str, Any]]:
    parsed_start = _parse_utc_ts(start_at)
    if parsed_start is None:
        return list(rows)
    return [
        row
        for row in rows
        if (observed_at := _parse_utc_ts(row.get("observed_ts"))) is not None
        and observed_at >= parsed_start
    ]


def _status_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    phase_counts = Counter(str(row.get("phase") or "unknown") for row in rows)
    status_counts = Counter(str(row.get("status") or "unknown") for row in rows)
    decision_counts = Counter(str(row.get("decision_code") or "none") for row in rows)
    hard = {key: value for key, value in status_counts.items() if key in _HARD_STATUSES or key.endswith("_error")}
    watch = {key: value for key, value in status_counts.items() if key in _WATCH_STATUSES}
    non_blocking: Counter[str] = Counter()
    no_candidate: Counter[str] = Counter()
    order_blocking: Counter[str] = Counter()
    for row in rows:
        row_status = str(row.get("status") or "unknown")
        payload = dict(row.get("payload") or {}) if isinstance(row.get("payload"), dict) else {}
        blocking_live_route = payload.get("blocking_live_route")
        if row_status in _NO_CANDIDATE_STATUSES:
            no_candidate[row_status] += 1
        if row_status in _NON_BLOCKING_STATUSES or blocking_live_route is False:
            non_blocking[row_status] += 1
        if row_status in _ORDER_BLOCKING_STATUSES or blocking_live_route is True:
            order_blocking[row_status] += 1
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
        "order_blocking_status_counts": dict(order_blocking.most_common()),
        "non_blocking_status_counts": dict(non_blocking.most_common()),
        "no_candidate_status_counts": dict(no_candidate.most_common()),
    }


def _compact_audit(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row.get("payload") or {})
    diagnostics = dict(payload.get("plan_generation_diagnostics") or {})
    result_rows = [dict(item) for item in list(payload.get("results") or []) if isinstance(item, dict)]
    legacy_generation_state = str(
        payload.get("legacy_plan_generation_state")
        or diagnostics.get("generation_state")
        or ""
    )
    sir_generation_state = str(payload.get("session_impulse_retest_generation_state") or "").strip()
    if not sir_generation_state:
        sir_count = payload.get("session_impulse_retest_generated_count")
        if sir_count is not None:
            sir_generation_state = "signal_generated" if _safe_int(sir_count) > 0 else "no_fresh_candidates"
        else:
            sir_generation_state = str(row.get("status") or "")
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
            "reason_detail": str(payload.get("reason_detail") or ""),
            "requested_mode": str(payload.get("requested_mode") or ""),
            "route_owner": str(payload.get("route_owner") or ""),
            "suppression_scope": str(payload.get("suppression_scope") or ""),
            "blocking_live_route": payload.get("blocking_live_route"),
            "plans_considered": payload.get("plans_considered"),
            "intents_created": payload.get("intents_created"),
            "submit_calls": payload.get("submit_calls"),
            "session_impulse_retest_generated_count": payload.get("session_impulse_retest_generated_count"),
            "generation_state": sir_generation_state,
            "session_impulse_retest_generation_state": sir_generation_state,
            "legacy_plan_generation_state": legacy_generation_state,
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
    start_at: datetime | None = None,
) -> dict[str, Any]:
    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        lookback_rows = engine.session_impulse_retest_runtime_audits_recent(
            hours=max(1, int(hours)),
            symbol=symbol,
            phase=phase,
            status=status,
            limit=max(1, int(limit)),
        )
    rows = _rows_since(lookback_rows, start_at)
    summary = _status_summary(rows)
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "hours": max(1, int(hours)),
        "audit_scope": "runtime_since_ws_start" if start_at is not None else "lookback_window",
        "runtime_started_at": start_at.isoformat().replace("+00:00", "Z") if start_at is not None else None,
        "symbol": str(symbol or ""),
        "phase_filter": str(phase or ""),
        "status_filter": str(status or ""),
        **summary,
        "lookback_summary": _status_summary(lookback_rows) if start_at is not None else {},
        "recent_audits": [_compact_audit(row) for row in rows[: max(1, int(limit))]],
        "lookback_recent_audits": [_compact_audit(row) for row in lookback_rows[: max(1, int(limit))]] if start_at is not None else [],
    }


def _write_report(path: Path, payload: dict[str, Any], *, atomic: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Session Impulse Retest Runtime Audit",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- overall_status: {payload.get('overall_status')}",
        f"- reason: {payload.get('reason')}",
        f"- audit_scope: {payload.get('audit_scope')}",
        f"- runtime_started_at: {payload.get('runtime_started_at') or 'none'}",
        f"- hours: {payload.get('hours')}",
        f"- audit_count: {payload.get('audit_count')}",
        f"- phase_counts: {payload.get('phase_counts')}",
        f"- status_counts: {payload.get('status_counts')}",
        f"- order_blocking_status_counts: {payload.get('order_blocking_status_counts')}",
        f"- non_blocking_status_counts: {payload.get('non_blocking_status_counts')}",
        f"- no_candidate_status_counts: {payload.get('no_candidate_status_counts')}",
        f"- lookback_summary: {payload.get('lookback_summary') or {}}",
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
        atomic_write_text(path, content)


def main() -> None:
    args = parse_args()
    runtime_started_at = None if bool(args.lookback_only) else _ws_runtime_started_at(str(args.heartbeat_dir or ""))
    payload = build_payload(
        hours=max(1, int(args.hours)),
        symbol=args.symbol,
        phase=args.phase,
        status=args.status,
        limit=max(1, int(args.limit)),
        start_at=runtime_started_at,
    )
    if not args.no_write_report:
        generated = parse_report_generated_at(payload.get("generated_at"))
        report_dir = ROOT / args.report_dir
        report_path = report_dir / f"session_impulse_retest_runtime_audit_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
        payload["report_path"] = _display_path(report_path)
        payload["latest_report_path"] = _display_path(report_dir / "latest.md")
        payload["latest_json_path"] = _display_path(report_dir / "latest.json")
        _write_report(report_path, payload, atomic=True)
        payload.update(
            write_latest_aliases(
                report_dir=report_dir,
                payload=payload,
                write_markdown_report=_write_report,
                root_dir=ROOT,
                json_default=_json_default,
            )
        )
    if not bool(args.quiet):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    if payload.get("overall_status") == "FAIL" and not bool(args.no_fail_exit):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
