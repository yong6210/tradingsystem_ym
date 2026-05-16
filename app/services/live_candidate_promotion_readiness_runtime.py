from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
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


def _csv_symbols(value: Any) -> set[str]:
    return {str(item or "").strip().upper() for item in str(value or "").split(",") if str(item or "").strip()}


def _utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_or_empty(value: Any) -> str:
    parsed = _utc(value)
    if parsed is None:
        return ""
    return parsed.isoformat().replace("+00:00", "Z")


def _freshness(age_seconds: int | None) -> str:
    if age_seconds is None:
        return "no_evidence"
    if age_seconds <= 15 * 60:
        return "fresh"
    if age_seconds <= 60 * 60:
        return "recent"
    if age_seconds <= 6 * 60 * 60:
        return "stale"
    return "old"


def _operator_review_item(row: dict[str, Any]) -> dict[str, Any]:
    state = str(row.get("promotion_state") or "")
    blocker = str(row.get("primary_blocker") or "")
    attention = "observe"
    if state == "NO_FRESH_LIVE_CANDIDATE":
        attention = "wait_for_fresh_setup"
    elif state == "COOLDOWN_WAIT":
        attention = "cooldown_capacity_wait"
    elif state == "OBSERVE_RUNTIME":
        attention = "observe"
    elif blocker == "validation_do_not_deploy":
        attention = "validation_report_required"
    return {
        "symbol": row.get("symbol"),
        "strategy_family": row.get("strategy_family"),
        "promotion_state": row.get("promotion_state"),
        "primary_blocker": row.get("primary_blocker"),
        "secondary_blockers": row.get("secondary_blockers") or {},
        "attention": attention,
        "latest_evidence_at": row.get("latest_evidence_at") or "",
        "evidence_freshness": row.get("evidence_freshness"),
        "next_action": row.get("next_action"),
    }


def _symbols_by_scope(
    symbols_by_state: dict[str, Any],
    *,
    live_symbols: set[str],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    live: dict[str, list[str]] = {}
    auxiliary: dict[str, list[str]] = {}
    for state, raw_symbols in symbols_by_state.items():
        state_text = str(state or "")
        if not state_text:
            continue
        live_values: set[str] = set()
        auxiliary_values: set[str] = set()
        for raw_symbol in list(raw_symbols or []):
            symbol = str(raw_symbol or "").strip().upper()
            if not symbol:
                continue
            if symbol in live_symbols:
                live_values.add(symbol)
            else:
                auxiliary_values.add(symbol)
        if live_values:
            live[state_text] = sorted(live_values)
        if auxiliary_values:
            auxiliary[state_text] = sorted(auxiliary_values)
    return live, auxiliary


def _count_symbols_by_state(symbols_by_state: dict[str, list[str]]) -> dict[str, int]:
    return {state: len(symbols) for state, symbols in sorted(symbols_by_state.items()) if symbols}


def _auxiliary_display_state(state: str) -> str:
    if state == "NO_FRESH_LIVE_CANDIDATE":
        return "AUXILIARY_TRACKED_NO_FRESH_SIGNAL"
    if state == "SHADOW_SIGNAL_ONLY":
        return "AUXILIARY_SHADOW_SIGNAL_ONLY"
    return f"AUXILIARY_{state}" if state else "AUXILIARY_UNKNOWN"


def _auxiliary_display_counts(symbols_by_state: dict[str, list[str]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for state, symbols in symbols_by_state.items():
        counts[_auxiliary_display_state(str(state or ""))] += len(symbols)
    return dict(counts.most_common())


def _blocker_counts_by_scope(
    rows: list[dict[str, Any]],
    *,
    live_symbols: set[str],
    symbols_by_blocker: dict[str, Any] | None = None,
) -> tuple[dict[str, int], dict[str, int]]:
    live_counts: Counter[str] = Counter()
    auxiliary_counts: Counter[str] = Counter()
    if symbols_by_blocker:
        for blocker, raw_symbols in symbols_by_blocker.items():
            blocker_text = str(blocker or "").strip()
            if not blocker_text:
                continue
            for raw_symbol in list(raw_symbols or []):
                symbol = str(raw_symbol or "").strip().upper()
                if not symbol:
                    continue
                if symbol in live_symbols:
                    live_counts[blocker_text] += 1
                else:
                    auxiliary_counts[blocker_text] += 1
        return dict(live_counts.most_common(8)), dict(auxiliary_counts.most_common(8))

    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        blocker = str(row.get("primary_blocker") or "").strip()
        if not symbol or not blocker:
            continue
        if symbol in live_symbols:
            live_counts[blocker] += 1
        else:
            auxiliary_counts[blocker] += 1
    return dict(live_counts.most_common(8)), dict(auxiliary_counts.most_common(8))


def _apply_live_headline_scope(
    readiness: dict[str, Any],
    *,
    live_symbols: set[str],
    filter_symbol: str | None = None,
) -> dict[str, Any]:
    normalized_live_symbols = {str(item or "").strip().upper() for item in live_symbols if str(item or "").strip()}
    readiness["live_routable_symbols"] = sorted(normalized_live_symbols)
    if filter_symbol or not normalized_live_symbols:
        return readiness
    headline_state = str(readiness.get("headline_state") or "")
    headline_reason = str(readiness.get("headline_reason") or "")
    live_headline_candidate = headline_state == "WAIT" and headline_reason == "no_promotable_live_candidate"
    shadow_headline_candidate = headline_state == "WATCH" and headline_reason == "shadow_signal_only"
    if not live_headline_candidate and not shadow_headline_candidate:
        return readiness

    rows = [dict(row) for row in list(readiness.get("candidates") or []) if isinstance(row, dict)]
    live_blockers, auxiliary_blockers = _blocker_counts_by_scope(
        rows,
        live_symbols=normalized_live_symbols,
        symbols_by_blocker=dict(readiness.get("symbols_by_blocker") or {}),
    )
    symbols_by_state = dict(readiness.get("symbols_by_state") or {})
    live_symbols_by_state, auxiliary_symbols_by_state = _symbols_by_scope(
        symbols_by_state,
        live_symbols=normalized_live_symbols,
    )
    live_symbol_count = sum(len(symbols) for symbols in live_symbols_by_state.values())
    auxiliary_symbol_count = sum(len(symbols) for symbols in auxiliary_symbols_by_state.values())
    readiness["candidate_scope_counts"] = {
        "total": int(readiness.get("candidate_count") or live_symbol_count + auxiliary_symbol_count),
        "live_routable": live_symbol_count,
        "auxiliary": auxiliary_symbol_count,
    }
    readiness["live_state_counts"] = _count_symbols_by_state(live_symbols_by_state)
    readiness["auxiliary_state_counts"] = _count_symbols_by_state(auxiliary_symbols_by_state)
    readiness["auxiliary_display_state_counts"] = _auxiliary_display_counts(auxiliary_symbols_by_state)
    readiness["top_live_blockers"] = live_blockers
    readiness["top_auxiliary_blockers"] = auxiliary_blockers
    readiness["headline_top_blockers"] = live_blockers
    readiness["top_all_blockers"] = dict(readiness.get("top_blockers") or {})
    readiness["auxiliary_symbols_by_state"] = auxiliary_symbols_by_state
    shadow_symbols = {
        str(symbol or "").strip().upper()
        for symbol in auxiliary_symbols_by_state.get("SHADOW_SIGNAL_ONLY", [])
        if str(symbol or "").strip()
    }
    live_shadow_symbols = sorted(
        str(symbol or "").strip().upper()
        for symbol in live_symbols_by_state.get("SHADOW_SIGNAL_ONLY", [])
        if str(symbol or "").strip()
    )
    shadow_auxiliary_symbols = sorted(shadow_symbols)
    readiness["shadow_only_auxiliary"] = {
        "available": bool(shadow_auxiliary_symbols),
        "symbols": shadow_auxiliary_symbols,
        "action": "Keep shadow-only until validation explicitly approves these symbols for MICRO_LIVE.",
    }
    if shadow_headline_candidate and live_shadow_symbols:
        readiness["shadow_only_auxiliary"]["live_symbol_conflicts"] = live_shadow_symbols
        return readiness

    live_wait_states = {"NO_FRESH_LIVE_CANDIDATE", "COOLDOWN_WAIT", "OBSERVE_RUNTIME", "NO_RECENT_RUNTIME_EVIDENCE"}
    live_wait_symbols_by_state = {
        state: list(live_symbols_by_state.get(state) or [])
        for state in live_wait_states
    }
    live_wait_symbols = sorted(
        {symbol for symbols in live_wait_symbols_by_state.values() for symbol in symbols}
    )
    live_rows = [
        row
        for row in rows
        if str(row.get("symbol") or "").strip().upper() in normalized_live_symbols
        and str(row.get("promotion_state") or "") in live_wait_states
    ]
    if not live_wait_symbols:
        return readiness

    latest = ""
    for row in live_rows:
        candidate_latest = _iso_or_empty(row.get("latest_evidence_at"))
        if _utc(candidate_latest) and (_utc(latest) is None or _utc(candidate_latest) > _utc(latest)):
            latest = candidate_latest
    evaluated_at = _utc(readiness.get("evaluated_at")) or datetime.now(timezone.utc)
    latest_dt = _utc(latest)
    age = max(0, int((evaluated_at - latest_dt).total_seconds())) if latest_dt is not None else None
    state_counts = Counter(
        {
            state: len(symbols)
            for state, symbols in live_wait_symbols_by_state.items()
            if symbols
        }
    )

    readiness["headline_state"] = "WAIT"
    readiness["headline_reason"] = "no_promotable_live_candidate"
    if shadow_auxiliary_symbols:
        readiness["headline_action"] = (
            "Current live symbols have no fresh live-eligible candidate; shadow-only signals remain validation queue."
        )
    else:
        readiness["headline_action"] = "Current live symbols have no fresh live-eligible candidate."
    readiness["promotion_decision"] = "wait_for_fresh_promotable_candidate"
    readiness["headline_evidence_at"] = latest
    readiness["headline_evidence_age_seconds"] = age
    readiness["headline_evidence_freshness"] = _freshness(age)
    readiness["headline_candidate_count"] = len(live_wait_symbols)
    readiness["headline_candidate_symbols"] = live_wait_symbols
    readiness["headline_candidate_state_counts"] = dict(state_counts.most_common())
    readiness["operator_review_items"] = [_operator_review_item(row) for row in live_rows[:5]]
    attention_flags = dict(readiness.get("attention_flags") or {})
    attention_flags["has_auxiliary_shadow_only_signal"] = bool(shadow_auxiliary_symbols)
    attention_flags["headline_requires_operator_review"] = False
    attention_flags["headline_has_stale_or_missing_evidence"] = any(
        str(row.get("evidence_freshness") or "") in {"stale", "old", "no_evidence"} for row in live_rows
    )
    readiness["attention_flags"] = attention_flags
    readiness["headline_scope"] = "live_routable_symbols"
    readiness["headline_shadow_only_downgraded_to_auxiliary"] = bool(shadow_auxiliary_symbols)
    return readiness


def build_live_candidate_promotion_readiness_from_db(
    db: Session,
    *,
    hours: int = 24,
    limit: int = 20,
    symbol: str | None = None,
    start_at: datetime | None = None,
    live_symbols: set[str] | None = None,
) -> dict[str, Any]:
    window_start = _utc(start_at) or datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))
    filter_symbol = _filter_symbol(symbol)
    audit_stmt = (
        select(
            SessionImpulseRetestRuntimeAudit.symbol,
            SessionImpulseRetestRuntimeAudit.phase,
            SessionImpulseRetestRuntimeAudit.status,
            func.count(),
            func.max(SessionImpulseRetestRuntimeAudit.observed_ts),
        )
        .where(SessionImpulseRetestRuntimeAudit.observed_ts >= window_start)
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
        .where(
            OrderIntent.created_at >= window_start,
            OrderIntent.strategy_family == _SESSION_IMPULSE_RETEST_FAMILY,
        )
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
        .where(
            OrderSubmission.submitted_at >= window_start,
            OrderSubmission.requested_live.is_(True),
            OrderIntent.strategy_family == _SESSION_IMPULSE_RETEST_FAMILY,
        )
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
    readiness["filter_strategy_families"] = [_SESSION_IMPULSE_RETEST_FAMILY]
    readiness["window_start"] = window_start.isoformat().replace("+00:00", "Z")
    configured_live_symbols = (
        live_symbols
        if live_symbols is not None
        else _csv_symbols(getattr(get_settings(), "auto_trading_micro_live_allowed_symbols", ""))
    )
    return _apply_live_headline_scope(
        readiness,
        live_symbols=configured_live_symbols,
        filter_symbol=filter_symbol or None,
    )


def build_live_candidate_promotion_readiness_payload(
    db: Session,
    *,
    hours: int = 24,
    limit: int = 20,
    symbol: str | None = None,
    start_at: datetime | None = None,
) -> dict[str, Any]:
    filter_symbol = _filter_symbol(symbol)
    window_start = _utc(start_at)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "schema_version": "live_candidate_promotion_readiness_v1",
        "symbol": filter_symbol or None,
        "strategy_families": [_SESSION_IMPULSE_RETEST_FAMILY],
        "window_start": window_start.isoformat().replace("+00:00", "Z") if window_start else None,
        "readiness": build_live_candidate_promotion_readiness_from_db(
            db,
            hours=max(1, int(hours)),
            limit=max(1, int(limit)),
            symbol=filter_symbol or None,
            start_at=window_start,
        ),
    }
