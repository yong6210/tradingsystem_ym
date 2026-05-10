from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import OrderIntent, OrderSubmission, SessionImpulseRetestRuntimeAudit
from app.services.live_candidate_promotion_readiness import LiveCandidatePromotionReadinessService


_SESSION_IMPULSE_RETEST_FAMILY = "session_impulse_retest"


def _count(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _filter_symbol(value: str | None) -> str:
    return str(value or "").strip().upper()


def build_live_candidate_promotion_readiness_from_db(
    db: Session,
    *,
    hours: int = 24,
    limit: int = 20,
    symbol: str | None = None,
) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))
    filter_symbol = _filter_symbol(symbol)
    audit_stmt = (
        select(
            SessionImpulseRetestRuntimeAudit.symbol,
            SessionImpulseRetestRuntimeAudit.phase,
            SessionImpulseRetestRuntimeAudit.status,
            func.count(),
            func.max(SessionImpulseRetestRuntimeAudit.observed_ts),
        )
        .where(SessionImpulseRetestRuntimeAudit.observed_ts >= cutoff)
        .group_by(
            SessionImpulseRetestRuntimeAudit.symbol,
            SessionImpulseRetestRuntimeAudit.phase,
            SessionImpulseRetestRuntimeAudit.status,
        )
    )
    if filter_symbol:
        audit_stmt = audit_stmt.where(SessionImpulseRetestRuntimeAudit.symbol == filter_symbol)
    audit_rows = [
        {
            "symbol": symbol,
            "strategy_family": _SESSION_IMPULSE_RETEST_FAMILY,
            "phase": phase,
            "status": status,
            "count": _count(count),
            "latest_observed_ts": latest_observed_ts,
        }
        for symbol, phase, status, count, latest_observed_ts in db.execute(audit_stmt).all()
    ]
    intent_stmt = (
        select(
            OrderIntent.symbol,
            OrderIntent.strategy_family,
            OrderIntent.execution_mode,
            OrderIntent.approval_state,
            OrderIntent.submit_decision,
            OrderIntent.decision_reason_code,
            func.count(),
            func.max(OrderIntent.created_at),
        )
        .where(OrderIntent.created_at >= cutoff)
        .group_by(
            OrderIntent.symbol,
            OrderIntent.strategy_family,
            OrderIntent.execution_mode,
            OrderIntent.approval_state,
            OrderIntent.submit_decision,
            OrderIntent.decision_reason_code,
        )
    )
    if filter_symbol:
        intent_stmt = intent_stmt.where(OrderIntent.symbol == filter_symbol)
    intent_rows = [
        {
            "symbol": symbol,
            "strategy_family": family,
            "execution_mode": mode,
            "approval_state": approval,
            "submit_decision": decision,
            "decision_reason_code": reason,
            "count": _count(count),
            "latest_created_at": latest_created_at,
        }
        for symbol, family, mode, approval, decision, reason, count, latest_created_at in db.execute(intent_stmt).all()
    ]
    submission_stmt = (
        select(
            OrderSubmission.symbol,
            OrderIntent.strategy_family,
            OrderSubmission.state,
            func.count(),
            func.max(OrderSubmission.submitted_at),
        )
        .join(OrderIntent, OrderIntent.intent_id == OrderSubmission.intent_id)
        .where(OrderSubmission.submitted_at >= cutoff, OrderSubmission.requested_live.is_(True))
        .group_by(OrderSubmission.symbol, OrderIntent.strategy_family, OrderSubmission.state)
    )
    if filter_symbol:
        submission_stmt = submission_stmt.where(OrderSubmission.symbol == filter_symbol)
    submission_rows = [
        {
            "symbol": symbol,
            "strategy_family": family,
            "state": state,
            "count": _count(count),
            "latest_submitted_at": latest_submitted_at,
        }
        for symbol, family, state, count, latest_submitted_at in db.execute(submission_stmt).all()
    ]
    readiness = LiveCandidatePromotionReadinessService().build(
        hours=max(1, int(hours)),
        audit_rows=audit_rows,
        intent_rows=intent_rows,
        submission_rows=submission_rows,
        limit=max(1, int(limit)),
    )
    readiness["filter_symbol"] = filter_symbol or None
    return readiness


def build_live_candidate_promotion_readiness_payload(
    db: Session,
    *,
    hours: int = 24,
    limit: int = 20,
    symbol: str | None = None,
) -> dict[str, Any]:
    filter_symbol = _filter_symbol(symbol)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "schema_version": "live_candidate_promotion_readiness_v1",
        "symbol": filter_symbol or None,
        "readiness": build_live_candidate_promotion_readiness_from_db(
            db,
            hours=max(1, int(hours)),
            limit=max(1, int(limit)),
            symbol=filter_symbol or None,
        ),
    }
