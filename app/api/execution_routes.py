from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.deps import get_engine
from app.db.session import get_db
from app.schemas.api import ExecutionPlanIn, ExecutionQualityOut
from app.schemas.execution import (
    ExecutionApproval,
    KillConditionAutomationApplyRequest,
    KillConditionAutomationApplyResponse,
    ExecutionOperatorDashboardResponse,
    ExecutionSubmitRequest,
    ExecutablePlan,
    OrderIntentCreateRequest,
    OrderIntentResponse,
    OrderSubmissionResponse,
    ReconciliationRequest,
    ReconciliationResponse,
    RolloutPolicySnapshot,
    RolloutPolicyUpdateRequest,
    SafetyControlRequest,
    SafetyStateResponse,
)
from app.services.strategy_engine import StrategyEngine
from app.services.execution_operator_ui import build_execution_operator_ui
from app.services.live_candidate_promotion_readiness_runtime import (
    build_live_candidate_promotion_readiness_payload,
)
from app.services.market_data import configured_usdt_universe_name
from app.services.runtime_worker_heartbeat import read_worker_heartbeat
from app.core.config import get_settings

router = APIRouter()


def _parse_utc_ts(value: object) -> datetime | None:
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


def _ws_started_at() -> datetime | None:
    payload = read_worker_heartbeat("ws", settings=get_settings())
    if not isinstance(payload, dict):
        return None
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    return _parse_utc_ts(details.get("started_at"))


def _readiness_summary(readiness: dict) -> dict:
    return {
        "headline_state": readiness.get("headline_state"),
        "headline_reason": readiness.get("headline_reason"),
        "promotion_decision": readiness.get("promotion_decision"),
        "headline_candidate_symbols": readiness.get("headline_candidate_symbols") or [],
        "candidate_count": readiness.get("candidate_count"),
        "top_live_blockers": readiness.get("top_live_blockers") or {},
        "top_all_blockers": readiness.get("top_all_blockers") or readiness.get("top_blockers") or {},
        "latest_evidence_at": readiness.get("latest_evidence_at") or "",
        "latest_evidence_freshness": readiness.get("latest_evidence_freshness") or "",
    }


@router.get("/execution/operator-ui", response_class=HTMLResponse)
def execution_operator_ui(
    symbol: str | None = Query(default="BTCUSDT"),
    universe: str | None = Query(default=None),
    days: int = Query(default=7, ge=1, le=365),
) -> HTMLResponse:
    html = build_execution_operator_ui(
        symbol=symbol,
        universe=str(universe or configured_usdt_universe_name(get_settings())),
        days=days,
    )
    return HTMLResponse(content=html)


@router.get("/execution/candidates/promotion-readiness")
def execution_candidate_promotion_readiness(
    symbol: str | None = Query(default=None),
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=20, ge=1, le=200),
    since_ws_start: bool = Query(default=True),
    lookback_only: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    start_at = _ws_started_at() if since_ws_start and not lookback_only else None
    payload = build_live_candidate_promotion_readiness_payload(
        db,
        hours=hours,
        limit=limit,
        symbol=symbol,
        start_at=start_at,
    )
    payload["readiness_scope"] = "runtime_since_ws_start" if start_at is not None else "lookback_window"
    payload["runtime_started_at"] = start_at.isoformat().replace("+00:00", "Z") if start_at is not None else None
    if start_at is not None:
        lookback_payload = build_live_candidate_promotion_readiness_payload(
            db,
            hours=hours,
            limit=limit,
            symbol=symbol,
            start_at=None,
        )
        payload["lookback_readiness_summary"] = _readiness_summary(
            dict(lookback_payload.get("readiness") or {})
        )
        payload["lookback_context_scope"] = "historical_reference_not_current_runtime"
    else:
        payload["lookback_readiness_summary"] = {}
        payload["lookback_context_scope"] = ""
    return payload


@router.post("/execution/plans/preview", response_model=ExecutablePlan)
def preview_execution_plan(
    payload: ExecutionPlanIn,
    engine: StrategyEngine = Depends(get_engine),
) -> ExecutablePlan:
    try:
        result = engine.preview_execution_plan(
            plan_id=payload.plan_id,
            paper_lineage_override=payload.paper_lineage_override,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"plan_not_found:{payload.plan_id}") from exc
    except ValueError as exc:
        detail = str(exc)
        if detail == "plan_expired":
            raise HTTPException(status_code=400, detail="plan_expired") from exc
        if detail == "plan_not_previewable":
            raise HTTPException(status_code=400, detail="plan_not_previewable") from exc
        raise
    return ExecutablePlan(**result)


@router.post("/execution/approve-plan", response_model=ExecutionApproval)
def approve_execution_plan(
    payload: ExecutionPlanIn,
    engine: StrategyEngine = Depends(get_engine),
) -> ExecutionApproval:
    try:
        result = engine.approve_execution_plan(
            plan_id=payload.plan_id,
            paper_lineage_override=payload.paper_lineage_override,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"plan_not_found:{payload.plan_id}") from exc
    except ValueError as exc:
        detail = str(exc)
        if detail == "plan_expired":
            raise HTTPException(status_code=400, detail="plan_expired") from exc
        if detail == "plan_not_previewable":
            raise HTTPException(status_code=400, detail="plan_not_previewable") from exc
        raise
    return ExecutionApproval(**result)


@router.get("/execution/quality", response_model=ExecutionQualityOut)
def execution_quality(
    symbol: str,
    days: int = Query(default=30, ge=1, le=365),
    write_report: bool = Query(default=True),
    engine: StrategyEngine = Depends(get_engine),
) -> ExecutionQualityOut:
    payload = engine.execution_quality_report(symbol=symbol, days=days, write_report=write_report)
    return ExecutionQualityOut(**payload)


@router.post("/execution/order-intents", response_model=OrderIntentResponse)
def create_order_intent(
    payload: OrderIntentCreateRequest,
    engine: StrategyEngine = Depends(get_engine),
) -> OrderIntentResponse:
    try:
        result = engine.create_order_intent(
            plan_id=payload.plan_id,
            execution_mode=payload.execution_mode,
            paper_lineage_override=payload.paper_lineage_override,
        )
    except ValueError as exc:
        if str(exc) == "plan_not_found":
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OrderIntentResponse(**result)


@router.post("/execution/submit", response_model=OrderSubmissionResponse)
def submit_execution_intent(
    payload: ExecutionSubmitRequest,
    engine: StrategyEngine = Depends(get_engine),
) -> OrderSubmissionResponse:
    try:
        result = engine.submit_order_intent(
            intent_id=payload.intent_id,
            live=payload.live,
            paper_scenario=payload.paper_scenario,
        )
    except ValueError as exc:
        if str(exc) in {"intent_not_found", "plan_not_found"}:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OrderSubmissionResponse(**result)


@router.post("/execution/reconcile", response_model=ReconciliationResponse)
def execution_reconcile(
    payload: ReconciliationRequest,
    auto_resolve: bool = Query(default=False),
    apply_lock: bool = Query(default=False),
    engine: StrategyEngine = Depends(get_engine),
) -> ReconciliationResponse:
    result = engine.reconcile_execution(
        symbol=payload.symbol,
        auto_resolve=auto_resolve,
        apply_lock=apply_lock,
    )
    return ReconciliationResponse(**result)


@router.post("/execution/control/kill-switch", response_model=SafetyStateResponse)
def execution_control_kill_switch(
    payload: SafetyControlRequest,
    engine: StrategyEngine = Depends(get_engine),
) -> SafetyStateResponse:
    result = engine.set_kill_switch(
        active=payload.active,
        reason_message=payload.reason_message,
        unlock_at=payload.unlock_at,
        updated_by=payload.updated_by,
    )
    return SafetyStateResponse(**result)


@router.post("/execution/control/close-only", response_model=SafetyStateResponse)
def execution_control_close_only(
    payload: SafetyControlRequest,
    engine: StrategyEngine = Depends(get_engine),
) -> SafetyStateResponse:
    result = engine.set_close_only(
        active=payload.active,
        reason_message=payload.reason_message,
        unlock_at=payload.unlock_at,
        updated_by=payload.updated_by,
    )
    return SafetyStateResponse(**result)


@router.post(
    "/execution/control/kill-condition/apply",
    response_model=KillConditionAutomationApplyResponse,
)
def execution_control_kill_condition_apply(
    payload: KillConditionAutomationApplyRequest,
    engine: StrategyEngine = Depends(get_engine),
) -> KillConditionAutomationApplyResponse:
    result = engine.apply_kill_condition_automation(
        symbol=payload.symbol,
        universe=payload.universe or configured_usdt_universe_name(get_settings()),
        family=payload.family,
        session_name=payload.session_name,
        days=payload.days,
        portfolio_limit=payload.portfolio_limit,
        intent_limit=payload.intent_limit,
        reconcile_limit=payload.reconcile_limit,
        dry_run=payload.dry_run,
        allow_live_write=payload.allow_live_write,
        arm_token=payload.arm_token,
        updated_by=payload.updated_by,
        unlock_at=payload.unlock_at,
    )
    return KillConditionAutomationApplyResponse(**result)


@router.post("/execution/control/rollout-policy", response_model=RolloutPolicySnapshot)
def execution_control_rollout_policy(
    payload: RolloutPolicyUpdateRequest,
    engine: StrategyEngine = Depends(get_engine),
) -> RolloutPolicySnapshot:
    result = engine.upsert_rollout_policy(
        family=payload.family,
        live_enabled=payload.live_enabled,
        max_execution_mode=payload.max_execution_mode,
        max_risk_r=payload.max_risk_r,
        allowed_sessions=payload.allowed_sessions,
        min_quality_score=payload.min_quality_score,
        updated_by=payload.updated_by,
        notes=payload.notes,
    )
    return RolloutPolicySnapshot(**result)


@router.get("/execution/safety-state", response_model=SafetyStateResponse)
def execution_safety_state(
    symbol: str | None = Query(default=None),
    family: str | None = Query(default=None),
    session_name: str | None = Query(default=None),
    engine: StrategyEngine = Depends(get_engine),
) -> SafetyStateResponse:
    result = engine.safety_state(symbol=symbol, family=family, session_name=session_name)
    return SafetyStateResponse(**result)


@router.get("/execution/operator-dashboard", response_model=ExecutionOperatorDashboardResponse)
def execution_operator_dashboard(
    symbol: str | None = Query(default=None),
    universe: str | None = Query(default=None),
    portfolio_limit: int = Query(default=10, ge=1, le=50),
    intent_limit: int = Query(default=10, ge=1, le=50),
    reconcile_limit: int = Query(default=10, ge=1, le=50),
    days: int = Query(default=7, ge=1, le=365),
    fast: bool = Query(default=False),
    engine: StrategyEngine = Depends(get_engine),
) -> ExecutionOperatorDashboardResponse:
    result = engine.execution_operator_dashboard(
        symbol=symbol,
        universe=str(universe or configured_usdt_universe_name(get_settings())),
        portfolio_limit=portfolio_limit,
        intent_limit=intent_limit,
        reconcile_limit=reconcile_limit,
        days=days,
        fast=fast,
    )
    return ExecutionOperatorDashboardResponse(**result)
