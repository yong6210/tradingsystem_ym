from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.config import Settings, get_settings
from app.core.enums import ApprovalState, ExecutionMode, StrategyMode
from app.db.models import Plan
from app.db.session import SessionLocal, init_db
from app.domain.execution import RolloutPolicy
from app.main import app
from app.services.execution_approval import ExecutionPlanningService
from app.services.operator_text import why_now_message
from app.services import scanner as scanner_module
from app.services.scanner import ScannerService


client = TestClient(app)


class _PlanRepoStub:
    def __init__(self, plans: list[Plan]):
        self._plans = plans

    def list_top(self, symbol: str, timeframe: str = "5m", limit: int = 10) -> list[Plan]:
        rows = [plan for plan in self._plans if plan.symbol == symbol and plan.timeframe == timeframe]
        return rows[:limit]

    def list_active_for_symbol(
        self,
        *,
        symbol: str,
        timeframe: str = "5m",
        states: list[str] | None = None,
        limit: int = 100,
    ) -> list[Plan]:
        rows = [plan for plan in self._plans if plan.symbol == symbol and plan.timeframe == timeframe]
        if states is not None:
            rows = [plan for plan in rows if plan.state in states]
        return rows[:limit]


class _CandleRepoStub:
    def list_recent(self, symbol: str, timeframe: str, limit: int = 300) -> list:
        return []


def _plan(
    *,
    plan_id: str,
    symbol: str = "BTCUSDC",
    entry_model: str = "LIMIT",
    state: str = "PLANNED",
    valid_until: datetime | None = None,
    validity: dict | None = None,
) -> Plan:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return Plan(
        plan_id=plan_id,
        zone_id=f"zone_{plan_id}",
        symbol=symbol,
        timeframe="5m",
        direction="long",
        entry_model=entry_model,
        entry_price=100.0,
        entry_condition="limit_on_touch" if entry_model == "LIMIT" else "touch_then_confirm",
        sl=98.0,
        tp1=101.0,
        tp2=102.0,
        tp3=103.0,
        split={"tp1": 0.5, "tp2": 0.3, "runner": 0.2},
        rr_min=1.2,
        rr_base=2.0,
        rr_opt=3.0,
        ev=0.25,
        cost_est=0.03,
        confidence=0.75,
        validity=validity
        or {
            "strategy_family": "trend_continuation",
            "strategy_grade": "A",
            "strategy_family_reason": "trend_continuation_limit",
            "strategy_scorecard_buckets": {"location": 22.0},
            "strategy_scorecard_raw_components": {"htf_trend_clarity": 18.0},
            "regime": "trend",
            "strategy_mode": StrategyMode.A_ONLY.value,
            "recommended_risk_r": 1.0,
        },
        state=state,
        valid_from=now - timedelta(minutes=15),
        valid_until=valid_until or (now + timedelta(hours=2)),
        strategy_version="v1",
    )


class _OpenRolloutProvider:
    def get(self, strategy_family: str | None) -> RolloutPolicy:
        return RolloutPolicy(
            strategy_family=str(strategy_family or "legacy_zone_plan").lower(),
            live_enabled=True,
            max_execution_mode=ExecutionMode.PAPER,
            max_risk_r=2.0,
            allowed_sessions=("london", "new_york", "unknown"),
            min_quality_score=0.0,
        )


def test_why_now_mapping_and_fallback() -> None:
    assert why_now_message("sweep_reversal_limit") == "extreme location + rejection + clean limit"
    assert why_now_message("custom_reason_code") == "custom reason code"


def test_scanner_top_assessed_candidate_supports_accepted_blocked_and_none(monkeypatch) -> None:
    settings = Settings(_env_file=None)
    accepted_repo = _PlanRepoStub([_plan(plan_id="accepted_case")])
    scanner = ScannerService(accepted_repo, _CandleRepoStub())
    monkeypatch.setattr(scanner_module, "get_settings", lambda: settings)
    scanner.overlay.settings = settings
    scanner.overlay.mode.settings = settings

    monkeypatch.setattr(settings, "strategy_mode", StrategyMode.A_ONLY)
    accepted = scanner.top_assessed_candidate(symbol="BTCUSDC")
    assert accepted is not None
    assert accepted["operator_status"] == "accepted"
    assert accepted["why_now"] == "trend regime + pullback held + clean continuation"

    monkeypatch.setattr(settings, "strategy_mode", StrategyMode.RESEARCH)
    blocked = scanner.top_assessed_candidate(symbol="BTCUSDC")
    assert blocked is not None
    assert blocked["operator_status"] == "blocked"
    assert blocked["block_reason"] == "mode_shadow_only"

    empty_scanner = ScannerService(_PlanRepoStub([]), _CandleRepoStub())
    assert empty_scanner.top_assessed_candidate(symbol="BTCUSDC") is None


@pytest.mark.parametrize(
    ("entry_model", "expected_entry_type", "expects_limit"),
    [
        ("LIMIT", "limit", True),
        ("CONFIRM", "stop_market", False),
        ("SWEEP_CONFIRM", "stop_market", False),
    ],
)
def test_execution_plan_builder_maps_entry_models(entry_model: str, expected_entry_type: str, expects_limit: bool) -> None:
    settings = Settings(_env_file=None, auto_trading_execution_mode="PAPER")
    service = ExecutionPlanningService(settings=settings)
    plan = _plan(plan_id=f"builder_{entry_model.lower()}", entry_model=entry_model)

    payload = service.build_executable_plan(
        plan=plan,
        context=None,
        candidate_row={
            "accepted": True,
            "deployment_go_no_go": "GO",
            "expected_summary": "win≈55.0%, EV≈+0.25R",
            "expected_win_prob": 0.55,
            "expected_ev_r": 0.25,
            "recommended_risk_r": 1.0,
        },
    )

    assert payload["entry_type"] == expected_entry_type
    assert payload["execution_mode"] == ExecutionMode.PAPER.value
    assert (payload["entry_limit_price"] is not None) is expects_limit
    assert (payload["entry_trigger_price"] is None) is expects_limit


@pytest.mark.parametrize(
    ("settings", "plan", "candidate", "metrics", "expected_state", "expected_code"),
    [
        (
            Settings(_env_file=None, auto_trading_enabled=True, auto_trading_execution_mode="MICRO_LIVE"),
            _plan(plan_id="manual_review_case"),
                {
                    "accepted": True,
                    "deployment_go_no_go": "MANUAL_REVIEW",
                    "deployment_code": "manual_review_risk_gate_throttled",
                    "deployment_message": "MANUAL_REVIEW: runtime risk gate is throttled.",
                    "session_guidance": {"session_name": "london"},
                    "final_rank_score": 82.0,
                },
            {"grade": "A", "recommendation": "deploy", "risk_state": "THROTTLED", "risk_reason": "jump_rate_warn"},
            ApprovalState.APPROVED_MANUAL,
            "manual_review_required",
        ),
        (
            Settings(_env_file=None, auto_trading_enabled=True, auto_trading_execution_mode="MICRO_LIVE"),
            _plan(plan_id="research_shadow_case", validity={"strategy_mode": "RESEARCH", "strategy_family": "range_rotation"}),
                {
                    "accepted": True,
                    "deployment_go_no_go": "GO",
                    "deployment_code": "go_runtime_gate_open",
                    "deployment_message": "GO: runtime gate is open for candidate review.",
                    "session_guidance": {"session_name": "london"},
                },
            {"grade": "A", "recommendation": "deploy", "risk_state": "OPEN", "risk_reason": "normal"},
            ApprovalState.APPROVED_SHADOW,
            "mode_policy_research_only",
        ),
        (
            Settings(
                _env_file=None,
                auto_trading_enabled=True,
                auto_trading_execution_mode="MICRO_LIVE",
                auto_trading_allowed_symbols="ETHUSDC",
            ),
            _plan(plan_id="allowlist_case"),
                {
                    "accepted": True,
                    "deployment_go_no_go": "GO",
                    "deployment_code": "go_runtime_gate_open",
                    "deployment_message": "GO: runtime gate is open for candidate review.",
                    "session_guidance": {"session_name": "london"},
                },
            {"grade": "A", "recommendation": "deploy", "risk_state": "OPEN", "risk_reason": "normal"},
            ApprovalState.BLOCKED,
            "symbol_not_live_enabled",
        ),
        (
            Settings(_env_file=None, auto_trading_enabled=True, auto_trading_execution_mode="MICRO_LIVE"),
            _plan(
                plan_id="stale_case",
                state="CLOSED",
                valid_until=datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=5),
            ),
                {
                    "accepted": True,
                    "deployment_go_no_go": "GO",
                    "deployment_code": "go_runtime_gate_open",
                    "deployment_message": "GO: runtime gate is open for candidate review.",
                    "session_guidance": {"session_name": "london"},
                },
            {"grade": "A", "recommendation": "deploy", "risk_state": "OPEN", "risk_reason": "normal"},
            ApprovalState.BLOCKED,
            "stale_plan_state",
        ),
        (
            Settings(_env_file=None, auto_trading_enabled=True, auto_trading_execution_mode="MICRO_LIVE"),
            _plan(plan_id="no_go_case"),
                {
                    "accepted": True,
                    "deployment_go_no_go": "NO_GO",
                    "deployment_code": "no_go_operating_lock_active",
                    "deployment_message": "NO_GO: operating lock is active.",
                    "session_guidance": {"session_name": "london"},
                },
            {
                "grade": "A",
                "recommendation": "deploy",
                "risk_state": "OPEN",
                "risk_reason": "normal",
                "operating_lock": {"active": False},
            },
            ApprovalState.BLOCKED,
            "no_go_operating_lock_active",
        ),
    ],
)
def test_approval_service_covers_manual_shadow_allowlist_stale_and_no_go(
    settings: Settings,
    plan: Plan,
    candidate: dict,
    metrics: dict,
    expected_state: ApprovalState,
    expected_code: str,
) -> None:
    service = ExecutionPlanningService(settings=settings)
    executable_plan = service.build_executable_plan(plan=plan, context=None, candidate_row=candidate)

    payload = service.approve(
        plan=plan,
        executable_plan=executable_plan,
        candidate_row=candidate,
        metrics=metrics,
    )

    assert payload["approval_state"] == expected_state.value
    assert payload["approval_reasons"][0]["code"] == expected_code


def test_auto_trading_settings_defaults_and_preview_approval_api_paths() -> None:
    init_db()
    settings = Settings(_env_file=None)
    assert settings.auto_trading_enabled is False
    assert settings.auto_trading_execution_mode == "SHADOW"
    assert settings.auto_trading_allowed_symbols == ""
    assert settings.auto_trading_allowed_families == ""

    now = datetime.now(timezone.utc).replace(microsecond=0)
    test_symbol = f"REPOTEST{int(now.timestamp())}USDC"
    active = _plan(plan_id=f"preview_live_{int(now.timestamp())}", symbol=test_symbol)
    expired = _plan(
        plan_id=f"preview_expired_{int(now.timestamp())}",
        symbol=test_symbol,
        valid_until=now - timedelta(minutes=5),
    )
    active_plan_id = active.plan_id
    expired_plan_id = expired.plan_id

    with SessionLocal() as db:
        db.execute(delete(Plan))
        db.add_all([active, expired])
        db.commit()

    preview = client.post("/execution/plans/preview", json={"plan_id": active_plan_id})
    assert preview.status_code == 200
    preview_payload = preview.json()
    assert preview_payload["plan_id"] == active_plan_id
    assert preview_payload["entry_type"] == "limit"
    assert "expected_summary" in preview_payload

    approval = client.post("/execution/approve-plan", json={"plan_id": active_plan_id})
    assert approval.status_code == 200
    approval_payload = approval.json()
    assert approval_payload["plan_id"] == active_plan_id
    assert "approval_state" in approval_payload
    assert "approval_reasons" in approval_payload

    missing = client.post("/execution/plans/preview", json={"plan_id": "missing_plan"})
    assert missing.status_code == 404

    expired_response = client.post("/execution/plans/preview", json={"plan_id": expired_plan_id})
    assert expired_response.status_code == 400
    assert expired_response.json()["detail"] == "plan_expired"


def test_approval_service_downgrades_auto_when_outcome_penalty_requires_manual_review() -> None:
    settings = Settings(_env_file=None, auto_trading_enabled=True, auto_trading_execution_mode="PAPER")
    service = ExecutionPlanningService(settings=settings, rollout_provider=_OpenRolloutProvider())
    plan = _plan(plan_id="outcome_penalty_manual_case")
    candidate = {
        "accepted": True,
        "deployment_go_no_go": "GO",
        "deployment_code": "go_runtime_gate_open",
        "deployment_message": "GO: runtime gate is open for candidate review.",
        "session_guidance": {"session_name": "london"},
    }
    executable_plan = service.build_executable_plan(plan=plan, context=None, candidate_row=candidate)
    payload = service.approve(
        plan=plan,
        executable_plan=executable_plan,
        candidate_row=candidate,
        metrics={"grade": "A", "recommendation": "deploy", "risk_state": "OPEN", "risk_reason": "normal"},
        outcome_inputs={
            "execution_degradation_advisory_summary": {
                "status": "manual_review",
                "reason_codes": ["slippage_p95_exceeds_live_tolerance"],
            },
            "score_to_outcome_funnel_summary": {
                "historical_execution_outcomes": {"baseline_cost_profitable_rate_from_closed": 0.25},
                "decomposition": {
                    "family": [
                        {
                            "key": "trend_continuation",
                            "closed": 5,
                            "baseline_cost_profitable_rate_from_closed": 0.2,
                        }
                    ],
                    "regime": [],
                    "session": [],
                },
            },
            "mode_advisory_summary": {
                "family": [
                    {
                        "bucket": "trend_continuation",
                        "advisory_state": "watch",
                        "confidence": "medium",
                        "sample_note": "usable evidence, but still limited",
                    }
                ],
                "regime": [],
                "session": [],
            },
        },
    )

    assert payload["approval_state"] == ApprovalState.APPROVED_MANUAL.value
    assert payload["playbook_go_no_go"] == "MANUAL_REVIEW"
    assert payload["outcome_approval_penalty"]["status"] == "manual_review"
    assert payload["outcome_approval_penalty"]["penalty_tier"] == "downgrade_to_manual"
    assert "execution_degradation:manual_review" in payload["outcome_approval_penalty"]["reason_codes"]


def test_approval_service_keeps_auto_and_adds_reason_only_watch_penalty() -> None:
    settings = Settings(_env_file=None, auto_trading_enabled=True, auto_trading_execution_mode="PAPER")
    service = ExecutionPlanningService(settings=settings, rollout_provider=_OpenRolloutProvider())
    plan = _plan(plan_id="outcome_penalty_watch_case")
    candidate = {
        "accepted": True,
        "deployment_go_no_go": "GO",
        "deployment_code": "go_runtime_gate_open",
        "deployment_message": "GO: runtime gate is open for candidate review.",
        "session_guidance": {"session_name": "london"},
    }
    executable_plan = service.build_executable_plan(plan=plan, context=None, candidate_row=candidate)
    payload = service.approve(
        plan=plan,
        executable_plan=executable_plan,
        candidate_row=candidate,
        metrics={"grade": "A", "recommendation": "deploy", "risk_state": "OPEN", "risk_reason": "normal"},
        outcome_inputs={
            "execution_degradation_advisory_summary": {
                "status": "watch",
                "reason_codes": ["slippage_p95_drift"],
            },
            "score_to_outcome_funnel_summary": {
                "historical_execution_outcomes": {"baseline_cost_profitable_rate_from_closed": 0.45},
                "decomposition": {"family": [], "regime": [], "session": []},
            },
            "mode_advisory_summary": {"family": [], "regime": [], "session": []},
        },
    )

    assert payload["approval_state"] == ApprovalState.APPROVED_AUTO.value
    assert payload["outcome_approval_penalty"]["status"] == "watch"
    assert payload["outcome_approval_penalty"]["penalty_tier"] == "reason_only"
    assert any(reason["code"] == "execution_degradation:watch" for reason in payload["approval_reasons"])


def test_approval_service_paper_lineage_override_bypasses_paper_sampling_gates_only() -> None:
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="PAPER",
        auto_trading_allowed_symbols="BTCUSDC",
        auto_trading_allowed_families="trend_continuation",
        auto_trading_require_validation_go=True,
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_OpenRolloutProvider())
    plan = _plan(
        plan_id="paper_lineage_sampling_override_case",
        symbol="WIFUSDC",
        validity={
            "strategy_family": "sweep_reversal",
            "strategy_grade": "A",
            "regime": "range",
            "strategy_mode": StrategyMode.A_ONLY.value,
            "recommended_risk_r": 0.4,
        },
    )
    candidate = {
        "accepted": False,
        "deployment_go_no_go": "GO",
        "deployment_code": "go_runtime_gate_open",
        "deployment_message": "GO: runtime gate is open for candidate review.",
        "block_reason": "thesis_duplicate_blocked",
        "block_reason_message": "Blocked: an active candidate with the same thesis already exists.",
        "thesis_rejected_reason": "duplicate_active_thesis",
        "session_guidance": {"session_name": "london"},
        "operating_lock": {"active": False, "current_session": {"name": "london", "active": True}},
    }
    executable_plan = service.build_executable_plan(plan=plan, context=None, candidate_row=candidate)
    payload = service.approve(
        plan=plan,
        executable_plan=executable_plan,
        candidate_row=candidate,
        metrics={"grade": "F", "recommendation": "do-not-deploy", "risk_state": "OPEN", "risk_reason": "normal"},
        paper_lineage_override=True,
        outcome_inputs={
            "execution_degradation_advisory_summary": {
                "status": "manual_review",
                "reason_codes": ["slippage_p95_exceeds_live_tolerance"],
            },
            "score_to_outcome_funnel_summary": {
                "historical_execution_outcomes": {"baseline_cost_profitable_rate_from_closed": 0.0},
                "decomposition": {"family": [], "regime": [], "session": []},
            },
            "mode_advisory_summary": {"family": [], "regime": [], "session": []},
        },
    )

    assert payload["paper_lineage_override_applied"] is True
    assert payload["approval_state"] == ApprovalState.APPROVED_AUTO.value
    assert payload["playbook_go_no_go"] == "GO"
    assert payload["allowed_execution_mode"] == "PAPER"
    reason_codes = {reason["code"] for reason in payload["approval_reasons"]}
    assert "paper_lineage_override_bypassed_symbol_allowlist" in reason_codes
    assert "paper_lineage_override_bypassed_family_allowlist" in reason_codes
    assert "paper_lineage_override_bypassed_validation_do_not_deploy" in reason_codes
    assert "paper_lineage_override_retained_paper_auto_submit" in reason_codes
    assert "execution_degradation:manual_review" in reason_codes
