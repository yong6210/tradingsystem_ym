#!/usr/bin/env python3
"""Run non-live manual safety drills for market-state rotation v6.

The drills create reproducible evidence for controls that cannot be proven
from passive operation reports alone.  They do not submit exchange orders and
use an isolated in-memory database where a repository is needed.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.core.enums import ApprovalState, ExecutionMode, PlanState, RiskGateState, StrategyMode
from app.db.base import Base
from app.db.models import Plan
from app.domain.execution import RolloutPolicy
from app.repositories.execution import (
    BinanceOrderLedgerRepository,
    BinancePositionRepository,
    ExecutionFillRepository,
    ExecutionReconciliationEventRepository,
    OrderSubmissionRepository,
    PlanRepository,
    SafetyLockRepository,
)
from app.services.execution_approval import ExecutionPlanningService
from app.services.execution_coordinator import ExecutionCoordinator, PaperExecutionAdapter
from app.services.execution_reconciliation import ExecutionReconciliationService
from app.services.operating_lock import OperatingLockService
from app.services.safety_locks import SafetyLockService


CONTROL_NAMES = (
    "kill_switch_verified",
    "max_daily_loss_verified",
    "position_sync_verified",
    "partial_fill_handling_verified",
    "exchange_reject_handling_verified",
    "reduce_only_exit_verified",
    "leverage_cap_verified",
    "idempotent_client_order_id_verified",
    "stale_signal_block_verified",
    "maintenance_window_block_verified",
)


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _closed_plan(*, plan_id: str, closed_ts: datetime, realized_r: float, grade: str | None = None) -> Plan:
    return Plan(
        plan_id=plan_id,
        zone_id=f"{plan_id}_zone",
        symbol="BTCUSDT",
        timeframe="5m",
        direction="long",
        entry_model="CONFIRM",
        entry_price=100.0,
        entry_condition="touch_then_confirm",
        sl=98.5,
        tp1=101.0,
        tp2=102.0,
        tp3=103.0,
        split={"tp1": 0.4, "tp2": 0.4, "runner": 0.2},
        rr_min=1.4,
        rr_base=2.0,
        rr_opt=3.0,
        ev=0.22,
        cost_est=0.05,
        confidence=0.75,
        validity={
            "strategy_grade": grade,
            "final_exit_ts": closed_ts.isoformat(),
            "final_exit_realized_r": realized_r,
            "final_exit_reason": "stop_loss" if realized_r < 0 else "target_tp2",
        },
        state=PlanState.CLOSED.value,
        valid_from=closed_ts - timedelta(hours=1),
        valid_until=closed_ts + timedelta(hours=2),
        strategy_version="market_state_rotation_v6",
    )


def _active_plan(
    *,
    plan_id: str,
    now: datetime,
    state: PlanState = PlanState.PLANNED,
    valid_until_delta: timedelta = timedelta(hours=2),
    direction: str = "long",
    entry_model: str = "CONFIRM",
) -> Plan:
    return Plan(
        plan_id=plan_id,
        zone_id=f"{plan_id}_zone",
        symbol="BTCUSDT",
        timeframe="5m",
        direction=direction,
        entry_model=entry_model,
        entry_price=100.0,
        entry_condition="touch_then_confirm",
        sl=95.0,
        tp1=102.0,
        tp2=104.0,
        tp3=106.0,
        split={"tp1": 0.4, "tp2": 0.4, "runner": 0.2},
        rr_min=1.4,
        rr_base=2.0,
        rr_opt=3.0,
        ev=0.25,
        cost_est=0.05,
        confidence=0.8,
        validity={
            "strategy_family": "market_state_rotation_v6",
            "strategy_mode": "A_ONLY",
            "strategy_grade": "A",
            "strategy_family_score": 86.0,
            "recommended_risk_r": 0.5,
            "thesis_cluster_id": "manual_safety_drill",
        },
        state=state.value,
        valid_from=now - timedelta(minutes=5),
        valid_until=now + valid_until_delta,
        strategy_version="market_state_rotation_v6",
    )


def _control(*, verified: bool, verified_at: datetime, evidence: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "verified": bool(verified),
        "verified_at": verified_at.isoformat(),
        "evidence": evidence,
        "details": details,
    }


def _sqlite_sessionmaker() -> sessionmaker:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _drill_coordinator(
    *,
    settings: Any | None = None,
    live_submitter: Any | None = None,
    fill_ingest: Any | None = None,
) -> ExecutionCoordinator:
    return ExecutionCoordinator(
        plan_repo=SimpleNamespace(),
        intent_repo=SimpleNamespace(),
        submission_repo=SimpleNamespace(),
        approval_loader=lambda *_args, **_kwargs: {},
        fill_ingest=fill_ingest or (lambda **_kwargs: {"accepted": True}),
        live_submitter=live_submitter or (lambda **_kwargs: {}),
        settings=settings or get_settings().model_copy(deep=True),
    )


def run_kill_switch_drill(*, now: datetime) -> dict[str, Any]:
    Session = _sqlite_sessionmaker()
    settings = get_settings().model_copy(deep=True)
    settings.auto_trading_close_only = False
    with Session() as db:
        service = SafetyLockService(repo=SafetyLockRepository(db), settings=settings)
        before = service.safety_state(symbol="BTCUSDT", family="market_state_rotation_v6", now=now)
        service.set_kill_switch(
            active=True,
            reason_message="market_state_rotation_v6 non-live kill switch drill",
            metadata={"drill": "market_state_rotation_v6_manual_safety"},
        )
        after = service.safety_state(symbol="BTCUSDT", family="market_state_rotation_v6", now=now)
        service.set_kill_switch(active=False, reason_message="release non-live drill")
        final = service.safety_state(symbol="BTCUSDT", family="market_state_rotation_v6", now=now)

    verified = (
        before.get("new_entry_allowed") is True
        and after.get("kill_switch_active") is True
        and after.get("new_entry_allowed") is False
        and after.get("blocking_reason_code") == SafetyLockService.KILL_SWITCH_REASON
        and final.get("kill_switch_active") is False
        and final.get("new_entry_allowed") is True
    )
    return _control(
        verified=verified,
        verified_at=now,
        evidence="non-live safety lock drill proves kill switch blocks new entries and can be released",
        details={
            "before": before,
            "after": after,
            "final": final,
            "database": "sqlite:///:memory:",
        },
    )


def run_daily_loss_drill(*, now: datetime) -> dict[str, Any]:
    settings = get_settings().model_copy(deep=True)
    service = OperatingLockService(settings)
    plans = [
        _closed_plan(plan_id="msrv6_loss_drill_1", closed_ts=now - timedelta(hours=2), realized_r=-1.2, grade="A"),
        _closed_plan(plan_id="msrv6_loss_drill_2", closed_ts=now - timedelta(hours=1), realized_r=-0.9, grade="B"),
    ]
    snapshot = service.evaluate(plans=plans, now=now, mode=StrategyMode.A_ONLY)
    payload = snapshot.to_dict()
    verified = (
        snapshot.state == RiskGateState.CLOSED
        and snapshot.active is True
        and snapshot.enforced is True
        and snapshot.reason == "daily_loss_limit_reached"
        and float(snapshot.daily_stats.get("realized_r") or 0.0) <= float(snapshot.daily_stats.get("loss_limit_r") or 0.0)
    )
    return _control(
        verified=verified,
        verified_at=now,
        evidence="non-live operating lock drill proves daily loss cap closes the entry gate",
        details={"snapshot": payload, "input_realized_r": [-1.2, -0.9]},
    )


def run_position_sync_drill(*, now: datetime) -> dict[str, Any]:
    Session = _sqlite_sessionmaker()
    settings = get_settings().model_copy(deep=True)
    with Session() as db:
        safety = SafetyLockService(repo=SafetyLockRepository(db), settings=settings)
        service = ExecutionReconciliationService(
            plan_repo=PlanRepository(db),
            submission_repo=OrderSubmissionRepository(db),
            binance_order_repo=BinanceOrderLedgerRepository(db),
            binance_position_repo=BinancePositionRepository(db),
            fill_repo=ExecutionFillRepository(db),
            event_repo=ExecutionReconciliationEventRepository(db),
            safety_locks=safety,
            settings=settings,
        )
        result = service.reconcile(symbol="BTCUSDT", auto_resolve=False, apply_lock=False)

    verified = (
        result.symbol == "BTCUSDT"
        and result.mismatches == []
        and result.lock_required is False
        and result.events_recorded == 0
    )
    return _control(
        verified=verified,
        verified_at=now,
        evidence="non-live reconciliation drill proves flat local state and flat exchange snapshot produce zero mismatches",
        details={
            "symbol": result.symbol,
            "mismatch_count": len(result.mismatches),
            "highest_severity": result.highest_severity.value,
            "lock_required": result.lock_required,
            "auto_resolve_requested": result.auto_resolve_requested,
            "apply_lock_requested": result.apply_lock_requested,
        },
    )


def run_partial_fill_handling_drill(*, now: datetime) -> dict[str, Any]:
    plan = _active_plan(plan_id="msrv6_partial_fill_drill", now=now)
    result = PaperExecutionAdapter().submit(
        intent=SimpleNamespace(intent_id="intent_msrv6_partial_fill"),
        plan=plan,
        client_order_id="intent-msrv6-partial-fill",
        scenario="partial_fill",
    )
    fill_events = list(result.fill_events or [])
    payload = dict(fill_events[0].get("payload") or {}) if fill_events else {}
    verified = (
        result.state.value == "PARTIALLY_FILLED"
        and result.submit_status == "PARTIALLY_FILLED"
        and len(fill_events) == 1
        and float(fill_events[0].get("qty") or 0.0) == 0.5
        and payload.get("partial") is True
        and dict(result.attachments or {}).get("status") == "reserved"
    )
    return _control(
        verified=verified,
        verified_at=now,
        evidence="non-live paper adapter drill proves partial fills are represented as partial entry events without marking a full fill",
        details={
            "submit_status": result.submit_status,
            "state": result.state.value,
            "fill_event_count": len(fill_events),
            "first_fill_qty": fill_events[0].get("qty") if fill_events else None,
            "first_fill_payload": payload,
            "attachments": dict(result.attachments or {}),
        },
    )


def run_exchange_reject_handling_drill(*, now: datetime) -> dict[str, Any]:
    plan = _active_plan(plan_id="msrv6_reject_drill", now=now)
    result = PaperExecutionAdapter().submit(
        intent=SimpleNamespace(intent_id="intent_msrv6_reject"),
        plan=plan,
        client_order_id="intent-msrv6-reject",
        scenario="reject",
    )
    verified = (
        result.state.value == "REJECTED"
        and result.submit_status == "REJECTED"
        and result.fill_events == []
        and dict(result.raw or {}).get("status") == "REJECTED"
        and str(result.message or "")
    )
    return _control(
        verified=verified,
        verified_at=now,
        evidence="non-live paper adapter drill proves exchange/API rejects are terminal and do not create fill events",
        details={
            "submit_status": result.submit_status,
            "state": result.state.value,
            "message": result.message,
            "fill_event_count": len(result.fill_events or []),
            "raw": dict(result.raw or {}),
        },
    )


def run_reduce_only_exit_drill(*, now: datetime) -> dict[str, Any]:
    settings = get_settings().model_copy(deep=True)
    settings.binance_live_position_side_mode = "ONE_WAY"
    settings.auto_trading_live_protection_orders_enabled = True
    settings.auto_trading_live_tp_limit_attach_enabled = True
    settings.auto_trading_live_protection_verify_sleep_seconds = 0.0
    settings.binance_live_quantity_step = 0.001
    settings.binance_live_min_quantity = 0.001
    submitter_calls: list[dict[str, Any]] = []

    def _fake_submitter(**kwargs: Any) -> dict[str, Any]:
        submitter_calls.append(dict(kwargs))
        return {
            "status": "ACK",
            "client_order_id": kwargs.get("client_order_id"),
            "reduce_only": kwargs.get("reduce_only"),
            "close_position": kwargs.get("close_position"),
            "order_type": kwargs.get("order_type"),
            "side": kwargs.get("side"),
        }

    coordinator = _drill_coordinator(settings=settings, live_submitter=_fake_submitter)
    plan = _active_plan(plan_id="msrv6_reduce_only_drill", now=now, direction="long")
    result = coordinator.attach_live_protection_orders(
        plan=plan,
        entry_quantity=1.0,
        entry_price=100.0,
        position_side=None,
        parent_client_order_id="intent-msrv6-entry-parent",
        live=False,
    )
    stop_calls = [row for row in submitter_calls if row.get("order_purpose") == "live_protection:stop_loss"]
    tp_calls = [row for row in submitter_calls if str(row.get("order_purpose") or "").startswith("live_protection:tp")]
    verified = (
        result.get("status") == "ATTACHED"
        and not result.get("errors")
        and bool(stop_calls)
        and bool(tp_calls)
        and all(row.get("live") is False for row in submitter_calls)
        and all(row.get("close_position") is True for row in stop_calls)
        and all(row.get("reduce_only") is True for row in tp_calls)
    )
    return _control(
        verified=verified,
        verified_at=now,
        evidence="non-live protection attach drill proves stop exits use close-position semantics and TP exits use reduce-only",
        details={
            "result_status": result.get("status"),
            "order_count": len(submitter_calls),
            "stop_order_count": len(stop_calls),
            "tp_order_count": len(tp_calls),
            "stop_calls": stop_calls,
            "tp_calls": tp_calls,
            "requires_reconciliation": result.get("requires_reconciliation"),
        },
    )


def run_leverage_cap_drill(*, now: datetime) -> dict[str, Any]:
    settings = get_settings().model_copy(deep=True)
    settings.auto_trading_live_sizing_mode = "RISK_PCT"
    settings.auto_trading_live_account_equity_usdt = 1_000.0
    settings.auto_trading_live_balance_sync_enabled = False
    settings.auto_trading_live_strategy_equity_cap_usdt = 0.0
    settings.auto_trading_live_risk_per_trade_pct = 0.10
    settings.auto_trading_live_usable_margin_fraction = 0.10
    settings.auto_trading_live_leverage_cap = 2.0
    settings.binance_live_quantity_step = 0.001
    settings.binance_live_min_quantity = 0.001
    coordinator = _drill_coordinator(settings=settings)
    plan = _active_plan(plan_id="msrv6_leverage_cap_drill", now=now)
    intent = SimpleNamespace(
        payload={"executable_plan": {"entry_trigger_price": 100.0, "stop_price": 95.0}},
        quality_snapshot={"recommended_risk_r": 1.0, "risk_sizing_r": 1.0},
        dedupe_result={},
    )
    quantity, sizing, error = coordinator._live_order_sizing(intent=intent, plan=plan)
    verified = (
        error is None
        and quantity is not None
        and sizing.get("leverage_capped") is True
        and float(sizing.get("leverage_cap") or 0.0) == 2.0
        and float(sizing.get("max_position_notional") or 0.0)
        <= float(sizing.get("leverage_cap_notional") or 0.0) + 1e-9
    )
    return _control(
        verified=verified,
        verified_at=now,
        evidence="non-live sizing drill proves target notional is capped by configured leverage before submit",
        details={
            "quantity": quantity,
            "error": error,
            "sizing": sizing,
        },
    )


class _ExistingSubmissionRepo:
    def __init__(self, existing: Any):
        self.existing = existing
        self.latest_for_intent_calls = 0

    def latest_for_intent(self, intent_id: str) -> Any:
        self.latest_for_intent_calls += 1
        return self.existing if intent_id == self.existing.intent_id else None


def run_idempotent_client_order_id_drill(*, now: datetime) -> dict[str, Any]:
    intent_id = "intent_market_state_rotation_v6_duplicate_replay"
    expected_client_order_id = ExecutionCoordinator._client_order_id(intent_id)
    existing_submission = SimpleNamespace(
        submission_id="sub_existing_duplicate_replay",
        intent_id=intent_id,
        client_order_id=expected_client_order_id,
        raw={"fill_results": [{"status": "existing_fill_result"}]},
    )
    submission_repo = _ExistingSubmissionRepo(existing_submission)
    submitter_calls = {"count": 0}

    def _live_submitter(**_kwargs: Any) -> dict[str, Any]:
        submitter_calls["count"] += 1
        return {"status": "SHOULD_NOT_BE_CALLED"}

    coordinator = ExecutionCoordinator(
        plan_repo=SimpleNamespace(),
        intent_repo=SimpleNamespace(),
        submission_repo=submission_repo,
        approval_loader=lambda *_args, **_kwargs: {},
        fill_ingest=lambda **_kwargs: {},
        live_submitter=_live_submitter,
        settings=get_settings().model_copy(deep=True),
    )
    returned, fill_results, duplicate = coordinator.submit_intent(intent_id=intent_id, live=True)
    verified = (
        duplicate is True
        and returned is existing_submission
        and returned.client_order_id == expected_client_order_id
        and fill_results == [{"status": "existing_fill_result"}]
        and submission_repo.latest_for_intent_calls == 1
        and submitter_calls["count"] == 0
        and ExecutionCoordinator._client_order_id(intent_id) == expected_client_order_id
    )
    return _control(
        verified=verified,
        verified_at=now,
        evidence="non-live coordinator drill proves repeated intent submission returns existing order without calling submitter",
        details={
            "intent_id": intent_id,
            "expected_client_order_id": expected_client_order_id,
            "returned_submission_id": returned.submission_id,
            "duplicate": duplicate,
            "submitter_calls": submitter_calls["count"],
            "latest_for_intent_calls": submission_repo.latest_for_intent_calls,
        },
    )


class _LiveEnabledRolloutProvider:
    def get(self, strategy_family: str | None) -> RolloutPolicy:
        family = str(strategy_family or "market_state_rotation_v6").strip().lower()
        return RolloutPolicy(
            strategy_family=family,
            live_enabled=True,
            max_execution_mode=ExecutionMode.MICRO_LIVE,
            max_risk_r=1.0,
            allowed_sessions=(),
            min_quality_score=0.0,
        )


def _approval_drill_service(settings: Any | None = None) -> ExecutionPlanningService:
    return ExecutionPlanningService(
        settings=settings or get_settings().model_copy(deep=True),
        rollout_provider=_LiveEnabledRolloutProvider(),
    )


def _approval_good_candidate() -> dict[str, Any]:
    return {
        "accepted": True,
        "deployment_go_no_go": "GO",
        "deployment_code": "runtime_go",
        "deployment_message": "GO: non-live manual safety drill candidate",
        "session_guidance": {"session_name": "london", "state": "active"},
        "expected_win_prob": 0.55,
        "expected_ev_r": 0.25,
    }


def _approval_good_metrics() -> dict[str, Any]:
    return {
        "grade": "A",
        "recommendation": "go",
        "risk_state": "OPEN",
        "risk_reason": "normal",
        "operating_lock": {"active": False, "current_session": {"name": "london"}},
    }


def run_stale_signal_block_drill(*, now: datetime) -> dict[str, Any]:
    runtime_now = datetime.now(UTC)
    settings = get_settings().model_copy(deep=True)
    settings.auto_trading_enabled = True
    service = _approval_drill_service(settings)
    plan = _active_plan(
        plan_id="msrv6_stale_signal_drill",
        now=runtime_now,
        valid_until_delta=timedelta(hours=-1),
    )
    executable = {
        "execution_mode": ExecutionMode.MICRO_LIVE.value,
        "strategy_family": "market_state_rotation_v6",
        "strategy_mode": "A_ONLY",
        "direction": "long",
        "entry_model": "CONFIRM",
        "setup_grade": "A",
        "setup_score": 86.0,
        "recommended_risk_r": 0.5,
    }
    approval = service.approve(
        plan=plan,
        executable_plan=executable,
        candidate_row=_approval_good_candidate(),
        metrics=_approval_good_metrics(),
        requested_execution_mode=ExecutionMode.MICRO_LIVE,
        strict_requested_mode=True,
        safety_state={"new_entry_allowed": True},
    )
    verified = (
        approval.get("approval_state") == ApprovalState.BLOCKED.value
        and approval.get("playbook_code") == "stale_plan_expired"
    )
    return _control(
        verified=verified,
        verified_at=now,
        evidence="non-live approval drill proves expired plan validity blocks MICRO_LIVE before submit",
        details={
            "approval_state": approval.get("approval_state"),
            "playbook_code": approval.get("playbook_code"),
            "playbook_message": approval.get("playbook_message"),
            "plan_valid_until": plan.valid_until.isoformat(),
        },
    )


def run_maintenance_window_block_drill(*, now: datetime) -> dict[str, Any]:
    runtime_now = datetime.now(UTC)
    settings = get_settings().model_copy(deep=True)
    current_utc_hour = datetime.now(UTC).hour
    settings.auto_trading_enabled = True
    settings.auto_trading_require_validation_go = True
    settings.auto_trading_allowed_symbols = "BTCUSDT"
    settings.auto_trading_allowed_families = "market_state_rotation_v6"
    settings.auto_trading_micro_live_allowed_symbols = "BTCUSDT"
    settings.auto_trading_micro_live_allowed_families = "market_state_rotation_v6"
    settings.auto_trading_micro_live_allowed_entry_models = "CONFIRM"
    settings.auto_trading_micro_live_allowed_sessions = "london"
    settings.auto_trading_micro_live_session_direction_blocked_hours_utc = f"BTCUSDT:london:LONG:{current_utc_hour}"
    service = _approval_drill_service(settings)
    plan = _active_plan(plan_id="msrv6_maintenance_window_drill", now=runtime_now)
    executable = service.build_executable_plan(
        plan=plan,
        context=None,
        candidate_row=_approval_good_candidate(),
        execution_mode=ExecutionMode.MICRO_LIVE,
    )
    approval = service.approve(
        plan=plan,
        executable_plan=executable,
        candidate_row=_approval_good_candidate(),
        metrics=_approval_good_metrics(),
        requested_execution_mode=ExecutionMode.MICRO_LIVE,
        strict_requested_mode=True,
        safety_state={"new_entry_allowed": True},
    )
    verified = (
        approval.get("approval_state") == ApprovalState.BLOCKED.value
        and approval.get("playbook_code") == "micro_live_session_direction_hour_not_allowed"
    )
    return _control(
        verified=verified,
        verified_at=now,
        evidence="non-live approval drill proves configured MICRO_LIVE blocked hours prevent entry before submit",
        details={
            "blocked_hour_utc": current_utc_hour,
            "blocked_contract": settings.auto_trading_micro_live_session_direction_blocked_hours_utc,
            "approval_state": approval.get("approval_state"),
            "playbook_code": approval.get("playbook_code"),
            "playbook_message": approval.get("playbook_message"),
        },
    )


def build_manual_safety_drill_report(*, now: datetime | None = None) -> dict[str, Any]:
    generated_at = now or datetime.now(UTC)
    controls = {
        "kill_switch_verified": run_kill_switch_drill(now=generated_at),
        "max_daily_loss_verified": run_daily_loss_drill(now=generated_at),
        "position_sync_verified": run_position_sync_drill(now=generated_at),
        "partial_fill_handling_verified": run_partial_fill_handling_drill(now=generated_at),
        "exchange_reject_handling_verified": run_exchange_reject_handling_drill(now=generated_at),
        "reduce_only_exit_verified": run_reduce_only_exit_drill(now=generated_at),
        "leverage_cap_verified": run_leverage_cap_drill(now=generated_at),
        "idempotent_client_order_id_verified": run_idempotent_client_order_id_drill(now=generated_at),
        "stale_signal_block_verified": run_stale_signal_block_drill(now=generated_at),
        "maintenance_window_block_verified": run_maintenance_window_block_drill(now=generated_at),
    }
    failed = [name for name in CONTROL_NAMES if not bool(controls[name].get("verified"))]
    return {
        "generated_at": generated_at.isoformat(),
        "overall_status": "PASS" if not failed else "FAIL",
        "drill_mode": "non_live_isolated",
        "no_live_order_sent": True,
        "controls": controls,
        "verified_count": len(CONTROL_NAMES) - len(failed),
        "required_count": len(CONTROL_NAMES),
        "missing_or_failed": failed,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Market State Rotation V6 Manual Safety Drills",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- overall_status: `{report.get('overall_status')}`",
        f"- no_live_order_sent: `{report.get('no_live_order_sent')}`",
        f"- verified: `{report.get('verified_count')}/{report.get('required_count')}`",
        "",
        "## Controls",
        "",
    ]
    for name, control in dict(report.get("controls") or {}).items():
        lines.append(f"- {name}: `{control.get('verified')}` - {control.get('evidence')}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run non-live v6 manual safety drills.")
    parser.add_argument("--report-dir", default="reports/validation/diagnostics/market_state_rotation_v6_manual_safety_drills")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_manual_safety_drill_report()
    if args.write_report:
        report_dir = Path(args.report_dir)
        if not report_dir.is_absolute():
            report_dir = ROOT_DIR / report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_manual_safety_evidence.json"
        md_path = report_dir / "market_state_rotation_v6_manual_safety_drills.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    return 0 if report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
