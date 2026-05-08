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
echo "== disk =="
df -h "$ROOT_DIR"
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
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.db.models import OrderIntent, OrderSubmission, SessionImpulseRetestRuntimeAudit
from app.db.session import SessionLocal

cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
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

print(f"submissions_total={int(submission_total)} requested_live={int(live_submission_total)}")
print("intents:")
for mode, approval_state, submit_decision, reason, count in intent_rows:
    print(f"- {count}: mode={mode} approval={approval_state} decision={submit_decision} reason={reason}")
print("session_impulse_retest_audits:")
for phase, status, count in audit_rows:
    print(f"- {count}: phase={phase} status={status}")
PY
