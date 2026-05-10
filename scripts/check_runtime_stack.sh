#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE:-$0}"
ROOT_DIR="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
cd "$ROOT_DIR"

export PYDANTIC_DISABLE_PLUGINS="${PYDANTIC_DISABLE_PLUGINS:-1}"
export PYTHONDONTWRITEBYTECODE="${PYTHONDONTWRITEBYTECODE:-1}"

PYTHON_BIN="$ROOT_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "missing python runtime: $PYTHON_BIN" >&2
  exit 1
fi

echo "== processes =="
ps -axo pid,lstart,command | awk '/uvicorn app[.]main:app|run_worker[.]py --mode loop --sync-universe|run_worker[.]py --ws-stream --sync-universe/ && $0 !~ /awk|check_runtime_stack[.]sh/ { print }'
echo
if [[ "$(uname -s)" == "Darwin" ]] && command -v launchctl >/dev/null 2>&1; then
  echo "== launchd api =="
  if launchctl print "gui/$(id -u)/com.yumin.trading.api" >/dev/null 2>&1; then
    echo "loaded"
  else
    echo "not_loaded"
  fi
  echo
fi
echo "== disk =="
df -h "$ROOT_DIR"
echo
echo "== workspace storage =="
du -sh .git trading.db trading.db-wal trading.db-shm 2>/dev/null || true
if git rev-parse --git-dir >/dev/null 2>&1; then
  git count-objects -vH || true
fi
if command -v lsof >/dev/null 2>&1; then
  echo "-- sqlite holders --"
  lsof trading.db trading.db-wal trading.db-shm 2>/dev/null | sed -n '1,40p' || true
fi
echo
echo "== ready =="
curl -sS --max-time 10 http://127.0.0.1:8000/health/ready || true
echo
echo
echo "== heartbeats =="
for f in /tmp/trading_worker_heartbeats/loop.json /tmp/trading_worker_heartbeats/ws.json; do
  if [ -f "$f" ]; then
    echo "-- $f --"
    cat "$f"
    echo
  else
    echo "-- $f missing --"
  fi
done

echo
echo "== candle freshness =="
PYTHONPATH="$ROOT_DIR" "$PYTHON_BIN" - <<'PY'
from app.db.session import SessionLocal
from app.db.repositories import CandleRepository
with SessionLocal() as db:
    repo = CandleRepository(db)
    for sym in ["BTCUSDC", "SOLUSDC", "XRPUSDC"]:
        row1 = repo.get_last_candle(sym, "1m")
        row5 = repo.get_last_candle(sym, "5m")
        print(sym, "1m", row1.ts.isoformat() if row1 else None, "5m", row5.ts.isoformat() if row5 else None)
PY

echo
echo "== miss detector (6h) =="
PYTHONPATH="$ROOT_DIR" "$PYTHON_BIN" "$ROOT_DIR/scripts/run_session_impulse_retest_miss_detector.py" --lookback-hours 6

echo
echo "== execution summary (24h) =="
PYTHONPATH="$ROOT_DIR" "$PYTHON_BIN" - <<'PY'
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from app.db.models import OrderIntent, OrderSubmission, SessionImpulseRetestRuntimeAudit
from app.db.session import SessionLocal


def _parse_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ws_started_at() -> datetime | None:
    try:
        payload = json.loads(Path("/tmp/trading_worker_heartbeats/ws.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    return _parse_utc(str(details.get("started_at") or ""))


def _ws_stats() -> dict:
    try:
        payload = json.loads(Path("/tmp/trading_worker_heartbeats/ws.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    details = payload.get("details")
    return details if isinstance(details, dict) else {}


def _as_int(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _format_symbol_counts(
    rows: list,
    *,
    phase: str | None = None,
    status: str | None = None,
    limit: int = 6,
) -> str:
    parts = []
    for symbol, row_phase, row_status, count in rows:
        if phase is not None and str(row_phase or "") != phase:
            continue
        if status is not None and str(row_status or "") != status:
            continue
        parts.append(f"{str(symbol or '?')}={_as_int(count)}")
        if len(parts) >= limit:
            break
    return ", ".join(parts)


def _diagnose_live_route(
    *,
    live_submission_total: int,
    runtime_audit_rows: list,
    runtime_symbol_status_rows: list,
    ws_stats: dict,
    runtime_cutoff: datetime | None,
) -> tuple[str, str, str]:
    auto_route_calls = _as_int(ws_stats.get("auto_route_calls"))
    auto_route_submit_calls = _as_int(ws_stats.get("auto_route_submit_calls"))
    auto_route_errors = _as_int(ws_stats.get("auto_route_errors"))
    refresh_errors = _as_int(ws_stats.get("refresh_errors"))
    ingest_errors = _as_int(ws_stats.get("ingest_errors"))
    progress_errors = _as_int(ws_stats.get("progress_callback_errors"))
    if auto_route_errors or refresh_errors or ingest_errors or progress_errors:
        return (
            "ERROR",
            "runtime_errors_present",
            f"auto_route_errors={auto_route_errors} refresh_errors={refresh_errors} ingest_errors={ingest_errors} progress_errors={progress_errors}",
        )
    if live_submission_total > 0 or auto_route_submit_calls > 0:
        return ("OK", "live_route_submitted", f"requested_live_24h={live_submission_total} auto_route_submit_calls={auto_route_submit_calls}")
    if not ws_stats:
        return ("WATCH", "ws_heartbeat_missing", "cannot classify live route without ws heartbeat")
    if auto_route_calls <= 0:
        return ("WATCH", "auto_route_not_called_since_ws_start", "ws is alive but no auto-route cycle has completed yet")

    status_counts: dict[tuple[str, str], int] = {
        (str(phase or ""), str(status or "")): _as_int(count)
        for phase, status, count in runtime_audit_rows
    }
    if not status_counts:
        return (
            "WATCH",
            "no_route_audits_since_ws_start",
            f"auto_route_calls={auto_route_calls} started_at={runtime_cutoff.isoformat() if runtime_cutoff else 'unknown'}",
        )

    auto_route_statuses = {
        status: count
        for (phase, status), count in status_counts.items()
        if phase == "auto_route" and count > 0
    }
    refresh_statuses = {
        status: count
        for (phase, status), count in status_counts.items()
        if phase == "refresh" and count > 0
    }
    if auto_route_statuses.get("intent_blocked", 0) > 0:
        symbols = _format_symbol_counts(
            runtime_symbol_status_rows,
            phase="auto_route",
            status="intent_blocked",
        )
        suffix = f"; symbols={symbols}" if symbols else ""
        return ("BLOCKED", "approval_or_safety_blocked", f"auto_route status intent_blocked; inspect latest order-intent decision_reason_code{suffix}")
    if auto_route_statuses.get("symbol_not_live_enabled_for_auto_route", 0) > 0:
        symbols = _format_symbol_counts(
            runtime_symbol_status_rows,
            phase="auto_route",
            status="symbol_not_live_enabled_for_auto_route",
        )
        suffix = f"; symbols={symbols}" if symbols else ""
        return (
            "WATCH",
            "non_live_symbol_signal_only",
            f"signal existed only outside the current live allowlist{suffix}; add only after validation, otherwise this is expected shadow observation",
        )
    if auto_route_statuses.get("recent_intent_cooldown_active", 0) > 0:
        return ("WAIT", "recent_intent_cooldown_active", "auto-route is intentionally cooling down a recent intent")
    if (
        auto_route_statuses.get("no_matching_session_impulse_retest_plan_ids", 0) > 0
        or auto_route_statuses.get("no_matching_live_route_plan_ids", 0) > 0
    ):
        return ("WAIT", "no_matching_plan_for_signal", "signal/audit existed but no currently routable plan id matched")
    if (
        auto_route_statuses.get("no_session_impulse_retest_plan", 0) > 0
        or auto_route_statuses.get("no_live_route_candidate_plan", 0) > 0
        or refresh_statuses.get("no_fresh_candidates", 0) > 0
    ):
        return ("WAIT", "no_fresh_live_signal", "runtime is healthy; current market has no fresh routable signal")
    if auto_route_statuses.get("live_route_contract_empty", 0) > 0:
        return ("BLOCKED", "live_route_contract_empty", "auto-route has no configured live strategy-family contract")
    if refresh_statuses.get("signal_generated", 0) > 0 and not auto_route_statuses:
        return ("WATCH", "signal_generated_without_route_audit", "signal refresh occurred but no auto-route classification followed")
    top = sorted(status_counts.items(), key=lambda item: item[1], reverse=True)[:3]
    top_text = ", ".join(f"{phase}:{status}={count}" for (phase, status), count in top)
    return ("WATCH", "unclassified_live_route_state", top_text or "no dominant status")


cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
runtime_cutoff = _ws_started_at()
ws_stats = _ws_stats()
with SessionLocal() as db:
    intent_rows = db.execute(
        select(
            OrderIntent.execution_mode,
            OrderIntent.approval_state,
            OrderIntent.submit_decision,
            OrderIntent.decision_reason_code,
            func.count(),
        )
        .where(OrderIntent.created_at >= cutoff)
        .group_by(
            OrderIntent.execution_mode,
            OrderIntent.approval_state,
            OrderIntent.submit_decision,
            OrderIntent.decision_reason_code,
        )
        .order_by(func.count().desc())
    ).all()
    submission_total = db.scalar(
        select(func.count()).select_from(OrderSubmission).where(OrderSubmission.submitted_at >= cutoff)
    ) or 0
    live_submission_total = db.scalar(
        select(func.count())
        .select_from(OrderSubmission)
        .where(OrderSubmission.submitted_at >= cutoff, OrderSubmission.requested_live.is_(True))
    ) or 0
    audit_rows = db.execute(
        select(
            SessionImpulseRetestRuntimeAudit.phase,
            SessionImpulseRetestRuntimeAudit.status,
            func.count(),
        )
        .where(SessionImpulseRetestRuntimeAudit.observed_ts >= cutoff)
        .group_by(SessionImpulseRetestRuntimeAudit.phase, SessionImpulseRetestRuntimeAudit.status)
        .order_by(SessionImpulseRetestRuntimeAudit.phase, SessionImpulseRetestRuntimeAudit.status)
    ).all()
    runtime_audit_rows = []
    runtime_symbol_status_rows = []
    if runtime_cutoff is not None:
        runtime_audit_rows = db.execute(
            select(
                SessionImpulseRetestRuntimeAudit.phase,
                SessionImpulseRetestRuntimeAudit.status,
                func.count(),
            )
            .where(SessionImpulseRetestRuntimeAudit.observed_ts >= runtime_cutoff)
            .group_by(SessionImpulseRetestRuntimeAudit.phase, SessionImpulseRetestRuntimeAudit.status)
            .order_by(SessionImpulseRetestRuntimeAudit.phase, SessionImpulseRetestRuntimeAudit.status)
        ).all()
        runtime_symbol_status_rows = db.execute(
            select(
                SessionImpulseRetestRuntimeAudit.symbol,
                SessionImpulseRetestRuntimeAudit.phase,
                SessionImpulseRetestRuntimeAudit.status,
                func.count(),
            )
            .where(SessionImpulseRetestRuntimeAudit.observed_ts >= runtime_cutoff)
            .group_by(
                SessionImpulseRetestRuntimeAudit.symbol,
                SessionImpulseRetestRuntimeAudit.phase,
                SessionImpulseRetestRuntimeAudit.status,
            )
            .order_by(func.count().desc(), SessionImpulseRetestRuntimeAudit.symbol.asc())
        ).all()

print(f"submissions_total={int(submission_total)} requested_live={int(live_submission_total)}")
print("intents:")
for mode, approval_state, submit_decision, reason, count in intent_rows:
    print(f"- {count}: mode={mode} approval={approval_state} decision={submit_decision} reason={reason}")
print("session_impulse_retest_audits:")
for phase, status, count in audit_rows:
    print(f"- {count}: phase={phase} status={status}")
if runtime_cutoff is not None:
    print(f"session_impulse_retest_audits_since_ws_start ({runtime_cutoff.isoformat()}):")
    if runtime_audit_rows:
        for phase, status, count in runtime_audit_rows:
            print(f"- {count}: phase={phase} status={status}")
    else:
        print("- none")
route_status, route_reason, route_detail = _diagnose_live_route(
    live_submission_total=int(live_submission_total),
    runtime_audit_rows=runtime_audit_rows,
    runtime_symbol_status_rows=runtime_symbol_status_rows,
    ws_stats=ws_stats,
    runtime_cutoff=runtime_cutoff,
)
print("live_route_diagnosis:")
print(f"- status={route_status} reason={route_reason}")
print(f"- detail={route_detail}")
print(
    "- ws_stats="
    f"auto_route_calls={_as_int(ws_stats.get('auto_route_calls'))} "
    f"auto_route_submit_calls={_as_int(ws_stats.get('auto_route_submit_calls'))} "
    f"refresh_errors={_as_int(ws_stats.get('refresh_errors'))} "
    f"auto_route_errors={_as_int(ws_stats.get('auto_route_errors'))} "
    f"ingest_errors={_as_int(ws_stats.get('ingest_errors'))}"
)
if runtime_cutoff is not None:
    print("live_route_symbol_breakdown_since_ws_start:")
    important_statuses = {
        "intent_blocked",
        "symbol_not_live_enabled_for_auto_route",
        "recent_intent_cooldown_active",
        "no_matching_session_impulse_retest_plan_ids",
        "no_matching_live_route_plan_ids",
        "no_live_route_candidate_plan",
        "live_route_contract_empty",
        "signal_generated",
    }
    visible_rows = [
        row for row in runtime_symbol_status_rows if str(row[2] or "") in important_statuses
    ] or runtime_symbol_status_rows[:12]
    if visible_rows:
        for symbol, phase, status, count in visible_rows[:20]:
            print(f"- {count}: {symbol} phase={phase} status={status}")
    else:
        print("- none")
PY
