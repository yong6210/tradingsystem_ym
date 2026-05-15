from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.config import Settings
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


class _MicroLiveRolloutProvider:
    def get(self, strategy_family: str | None) -> RolloutPolicy:
        return RolloutPolicy(
            strategy_family=str(strategy_family or "legacy_zone_plan").lower(),
            live_enabled=True,
            max_execution_mode=ExecutionMode.MICRO_LIVE,
            max_risk_r=2.0,
            allowed_sessions=("london", "new_york", "unknown"),
            min_quality_score=0.0,
        )


class _DeadSessionMicroLiveRolloutProvider:
    def __init__(self, allowed_sessions: tuple[str, ...] = ("dead_session", "london", "new_york")) -> None:
        self._allowed_sessions = allowed_sessions

    def get(self, strategy_family: str | None) -> RolloutPolicy:
        return RolloutPolicy(
            strategy_family=str(strategy_family or "legacy_zone_plan").lower(),
            live_enabled=True,
            max_execution_mode=ExecutionMode.MICRO_LIVE,
            max_risk_r=2.0,
            allowed_sessions=self._allowed_sessions,
            min_quality_score=0.0,
        )


def test_why_now_mapping_and_fallback() -> None:
    assert why_now_message("sweep_reversal_limit") == "extreme location + rejection + clean limit"
    assert why_now_message("custom_reason_code") == "custom reason code"


def test_scanner_top_assessed_candidate_supports_accepted_blocked_and_none(monkeypatch) -> None:
    settings = Settings(_env_file=None)
    accepted_repo = _PlanRepoStub(
        [
            _plan(
                plan_id="accepted_case",
                validity={
                    "strategy_family": "trend_continuation",
                    "strategy_family_reason": "trend_continuation_limit",
                    "recommended_risk_r": 0.8,
                    "runtime_signal_shadow_tilt": {
                        "classification": "strong_short_sweep",
                        "shadow_size_multiplier": 1.4762,
                        "apply_live": False,
                    },
                },
            )
        ]
    )
    scanner = ScannerService(accepted_repo, _CandleRepoStub())
    monkeypatch.setattr(scanner_module, "get_settings", lambda: settings)
    scanner.overlay.settings = settings
    scanner.overlay.mode.settings = settings

    monkeypatch.setattr(settings, "strategy_mode", StrategyMode.A_ONLY)
    accepted = scanner.top_assessed_candidate(symbol="BTCUSDC")
    assert accepted is not None
    assert accepted["operator_status"] == "accepted"
    assert accepted["why_now"] == "trend regime + pullback held + clean continuation"
    assert accepted["runtime_signal_shadow_tilt"]["classification"] == "strong_short_sweep"

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


def test_execution_plan_builder_tolerates_malformed_numeric_settings() -> None:
    settings = Settings(_env_file=None, auto_trading_execution_mode="PAPER")
    settings.auto_trading_notional_per_r = "bad-notional"
    settings.maker_fee_bps = "nan"
    settings.auto_trading_max_slippage_bps = "inf"
    service = ExecutionPlanningService(settings=settings)
    plan = _plan(
        plan_id="builder_malformed_numeric_inputs",
        validity={
            "strategy_family": "trend_continuation",
            "strategy_grade": "A",
            "strategy_family_score": "bad-score",
            "recommended_risk_r": "bad-risk",
            "strategy_mode": StrategyMode.A_ONLY.value,
        },
    )
    plan.entry_price = "bad-entry"
    plan.sl = "bad-stop"
    plan.tp1 = "bad-tp"
    plan.split = {"tp1": "bad-split", "tp2": "inf", "runner": "nan"}

    payload = service.build_executable_plan(
        plan=plan,
        context=None,
        candidate_row={
            "accepted": True,
            "deployment_go_no_go": "GO",
            "expected_win_prob": "bad-win",
            "expected_ev_r": "inf",
        },
    )

    assert payload["setup_score"] == 0.0
    assert payload["recommended_risk_r"] == 0.0
    assert payload["entry_limit_price"] == 0.0
    assert payload["stop_price"] == 0.0
    assert payload["tp_targets"][0]["price"] == 0.0
    assert payload["tp_targets"][1]["size_fraction"] == 0.0
    assert payload["max_position_notional"] == 0.0
    assert payload["expected_fee_bps"] == 2.0
    assert payload["max_slippage_bps"] == 12.0
    assert payload["expected_summary"]["expected_win_prob"] == 0.0


def test_micro_live_approval_tolerates_malformed_numeric_settings() -> None:
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_allowed_symbols="BTCUSDC",
        auto_trading_allowed_families="trend_continuation",
        auto_trading_micro_live_allowed_symbols="BTCUSDC",
        auto_trading_micro_live_allowed_families="trend_continuation",
    )
    settings.auto_trading_micro_live_max_concurrent_positions = "bad-position-cap"
    settings.auto_trading_micro_live_max_daily_new_entries = "bad-daily-cap"
    settings.transition_edge_variant_partial_activation_ratio = "bad-ratio"
    settings.session_impulse_retest_partial_activation_ratio = "inf"
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(plan_id="approve_malformed_numeric_settings")
    candidate = {
        "accepted": True,
        "deployment_go_no_go": "GO",
        "deployment_code": "go_runtime_candidate",
        "deployment_message": "GO",
        "session_guidance": {"state": "unknown"},
    }
    executable_plan = service.build_executable_plan(plan=plan, context=None, candidate_row=candidate)

    payload = service.approve(
        plan=plan,
        executable_plan=executable_plan,
        candidate_row=candidate,
        metrics={
            "grade": "A",
            "recommendation": "deploy",
            "risk_state": "OPEN",
            "operating_lock": {"active": False},
        },
        requested_execution_mode=ExecutionMode.MICRO_LIVE,
        safety_state={"new_entry_allowed": True},
        current_exposure_count=0,
        daily_new_entry_count=0,
    )

    assert payload["approval_state"] == ApprovalState.APPROVED_AUTO.value
    assert payload["transition_edge_variant_partial_activation_ratio"] == 0.0
    assert service._transition_edge_variant_sampling_decision(plan=plan, executable_plan=executable_plan)[2] == 0.3
    assert service._session_impulse_retest_sampling_decision(plan=plan, executable_plan=executable_plan)[2] == 0.3


def test_validation_do_not_deploy_detail_classifies_missing_sample_root_cause() -> None:
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_allowed_symbols="BTCUSDC",
        auto_trading_allowed_families="trend_continuation",
        auto_trading_micro_live_allowed_symbols="BTCUSDC",
        auto_trading_micro_live_allowed_families="trend_continuation",
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(plan_id="validation_detail_missing_sample")
    candidate = {
        "accepted": True,
        "deployment_go_no_go": "GO",
        "deployment_code": "go_runtime_gate_open",
        "deployment_message": "GO: runtime gate is open.",
        "session_guidance": {"session_name": "london"},
    }
    executable_plan = service.build_executable_plan(plan=plan, context=None, candidate_row=candidate)

    payload = service.approve(
        plan=plan,
        executable_plan=executable_plan,
        candidate_row=candidate,
        metrics={
            "grade": "F",
            "recommendation": "do-not-deploy",
            "risk_state": "OPEN",
            "risk_reason": "normal",
            "sample_size": 0,
            "win_rate": 0.0,
            "ev": 0.0,
            "total_score": 28.33,
        },
        requested_execution_mode=ExecutionMode.MICRO_LIVE,
        safety_state={"new_entry_allowed": True},
    )

    detail = payload["validation_block_detail"]
    root_codes = [item["code"] for item in detail["root_causes"]]
    assert payload["approval_state"] == ApprovalState.BLOCKED.value
    assert detail["primary_cause"] == "validation_sample_missing"
    assert "validation_expectancy_non_positive" in root_codes
    assert detail["metrics"]["total_score"] == 28.33


@pytest.mark.parametrize(
    ("settings", "plan", "candidate", "metrics", "expected_state", "expected_code"),
    [
        (
            Settings(
                _env_file=None,
                auto_trading_enabled=True,
                auto_trading_execution_mode="MICRO_LIVE",
                auto_trading_micro_live_allowed_families="",
            ),
            _plan(
                plan_id="manual_review_case",
                validity={
                    "strategy_family": "sweep_reversal",
                    "strategy_mode": StrategyMode.A_ONLY.value,
                    "strategy_grade": "A",
                    "recommended_risk_r": 0.5,
                },
            ),
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
            Settings(
                _env_file=None,
                auto_trading_enabled=True,
                auto_trading_execution_mode="MICRO_LIVE",
                auto_trading_micro_live_allowed_families="",
            ),
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
                auto_trading_micro_live_allowed_families="",
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
            Settings(
                _env_file=None,
                auto_trading_enabled=True,
                auto_trading_execution_mode="MICRO_LIVE",
                auto_trading_micro_live_allowed_families="",
            ),
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
            Settings(
                _env_file=None,
                auto_trading_enabled=True,
                auto_trading_execution_mode="MICRO_LIVE",
                auto_trading_micro_live_allowed_families="",
            ),
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


def test_approval_service_keeps_sir_live_bootstrap_degradation_advisory_without_execution_sample() -> None:
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_symbols="BTCUSDC",
        auto_trading_micro_live_allowed_families="session_impulse_retest",
        auto_trading_micro_live_allowed_entry_models="CONFIRM",
        auto_trading_micro_live_allowed_sessions="london,new_york",
        session_impulse_retest_enabled=True,
        session_impulse_retest_shadow_only=False,
        session_impulse_retest_partial_activation_ratio=1.0,
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(
        plan_id="sir_bootstrap_degradation_advisory_case",
        entry_model="CONFIRM",
        validity={
            "strategy_family": "session_impulse_retest",
            "strategy_grade": "A",
            "strategy_mode": StrategyMode.A_ONLY.value,
            "recommended_risk_r": 0.4,
            "regime": "trend",
        },
    )
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
        requested_execution_mode=ExecutionMode.MICRO_LIVE,
        safety_state={
            "new_entry_allowed": True,
            "session_impulse_retest_rollout_readiness": {
                "status": "live_bootstrap_collecting",
                "blockers": [],
                "advisory_blockers": ["no_recent_closed_sample"],
            },
        },
        outcome_inputs={
            "execution_degradation_advisory_summary": {
                "status": "manual_review",
                "reason_codes": ["execution_quality_low_coverage"],
                "sample_context": {"plans_matured": 0, "fill_events_total": 0, "closed_plans": 0},
            },
            "score_to_outcome_funnel_summary": {
                "historical_execution_outcomes": {"baseline_cost_profitable_rate_from_closed": 0.0},
                "decomposition": {"family": [], "regime": [], "session": []},
            },
            "mode_advisory_summary": {"family": [], "regime": [], "session": []},
        },
    )

    assert payload["approval_state"] == ApprovalState.APPROVED_AUTO.value
    assert payload["outcome_approval_penalty"]["status"] == "watch"
    assert payload["outcome_approval_penalty"]["penalty_tier"] == "reason_only"
    assert (
        payload["outcome_approval_penalty"]["source_summary"]["execution_degradation_policy"]
        == "advisory_until_material_sir_live_execution_sample"
    )
    assert "execution_degradation:manual_review" in payload["outcome_approval_penalty"]["reason_codes"]


def test_approval_service_downgrades_sir_when_execution_degradation_has_material_sample() -> None:
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_symbols="BTCUSDC",
        auto_trading_micro_live_allowed_families="session_impulse_retest",
        auto_trading_micro_live_allowed_entry_models="CONFIRM",
        auto_trading_micro_live_allowed_sessions="london,new_york",
        session_impulse_retest_enabled=True,
        session_impulse_retest_shadow_only=False,
        session_impulse_retest_partial_activation_ratio=1.0,
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(
        plan_id="sir_material_degradation_manual_case",
        entry_model="CONFIRM",
        validity={
            "strategy_family": "session_impulse_retest",
            "strategy_grade": "A",
            "strategy_mode": StrategyMode.A_ONLY.value,
            "recommended_risk_r": 0.4,
            "regime": "trend",
        },
    )
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
        requested_execution_mode=ExecutionMode.MICRO_LIVE,
        safety_state={
            "new_entry_allowed": True,
            "session_impulse_retest_rollout_readiness": {"status": "partial_or_live_running", "blockers": []},
        },
        outcome_inputs={
            "execution_degradation_advisory_summary": {
                "status": "manual_review",
                "reason_codes": ["fill_rate_subscale"],
                "sample_context": {"plans_matured": 8, "fill_events_total": 2, "closed_plans": 2},
            },
            "score_to_outcome_funnel_summary": {
                "historical_execution_outcomes": {"baseline_cost_profitable_rate_from_closed": 0.0},
                "decomposition": {"family": [], "regime": [], "session": []},
            },
            "mode_advisory_summary": {"family": [], "regime": [], "session": []},
        },
    )

    assert payload["approval_state"] == ApprovalState.APPROVED_MANUAL.value
    assert payload["playbook_go_no_go"] == "MANUAL_REVIEW"
    assert payload["outcome_approval_penalty"]["penalty_tier"] == "downgrade_to_manual"


def test_approval_service_maps_inactive_dead_session_to_rollout_bucket() -> None:
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_symbols="BTCUSDC",
        auto_trading_micro_live_allowed_families="session_impulse_retest",
        auto_trading_micro_live_allowed_entry_models="CONFIRM",
        auto_trading_micro_live_allowed_sessions="dead_session,london,new_york",
        session_impulse_retest_enabled=True,
        session_impulse_retest_shadow_only=False,
        session_impulse_retest_partial_activation_ratio=1.0,
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_DeadSessionMicroLiveRolloutProvider())
    plan = _plan(
        plan_id="sir_dead_session_approval_case",
        entry_model="CONFIRM",
        validity={
            "strategy_family": "session_impulse_retest",
            "strategy_grade": "A",
            "strategy_family_score": 90.0,
            "strategy_mode": StrategyMode.A_ONLY.value,
            "recommended_risk_r": 0.4,
            "regime": "trend",
        },
    )
    candidate = {
        "accepted": True,
        "deployment_go_no_go": "GO",
        "deployment_code": "go_runtime_gate_open",
        "deployment_message": "GO: runtime gate is open for candidate review.",
        "session_guidance": {
            "state": "dead_session",
            "current_session": {"name": "inactive", "active": False},
            "dead_session": True,
        },
    }
    executable_plan = service.build_executable_plan(plan=plan, context=None, candidate_row=candidate)

    payload = service.approve(
        plan=plan,
        executable_plan=executable_plan,
        candidate_row=candidate,
        metrics={
            "grade": "A",
            "recommendation": "deploy-small-capital",
            "risk_state": "OPEN",
            "risk_reason": "normal",
            "operating_lock": {"current_session": {"name": "inactive", "active": False}},
        },
        requested_execution_mode=ExecutionMode.MICRO_LIVE,
        safety_state={
            "new_entry_allowed": True,
            "session_impulse_retest_rollout_readiness": {
                "status": "live_bootstrap_collecting",
                "blockers": [],
                "advisory_blockers": ["no_recent_closed_sample"],
            },
        },
    )

    assert payload["approval_state"] == ApprovalState.APPROVED_AUTO.value
    assert payload["safety_state"]["session_name"] == "dead_session"
    assert payload["playbook_go_no_go"] == "GO"


def test_approval_service_blocks_dead_session_when_rollout_contract_excludes_it() -> None:
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_symbols="BTCUSDC",
        auto_trading_micro_live_allowed_families="session_impulse_retest",
        auto_trading_micro_live_allowed_entry_models="CONFIRM",
        auto_trading_micro_live_allowed_sessions="london,new_york",
        session_impulse_retest_enabled=True,
        session_impulse_retest_shadow_only=False,
        session_impulse_retest_partial_activation_ratio=1.0,
    )
    service = ExecutionPlanningService(
        settings=settings,
        rollout_provider=_DeadSessionMicroLiveRolloutProvider(allowed_sessions=("london", "new_york")),
    )
    plan = _plan(
        plan_id="sir_dead_session_rollout_block_case",
        entry_model="CONFIRM",
        validity={
            "strategy_family": "session_impulse_retest",
            "strategy_grade": "A",
            "strategy_family_score": 90.0,
            "strategy_mode": StrategyMode.A_ONLY.value,
            "recommended_risk_r": 0.4,
            "regime": "trend",
        },
    )
    candidate = {
        "accepted": True,
        "deployment_go_no_go": "GO",
        "deployment_code": "go_runtime_gate_open",
        "deployment_message": "GO: runtime gate is open for candidate review.",
        "session_guidance": {
            "state": "dead_session",
            "current_session": {"name": "inactive", "active": False},
            "dead_session": True,
        },
    }
    executable_plan = service.build_executable_plan(plan=plan, context=None, candidate_row=candidate)

    payload = service.approve(
        plan=plan,
        executable_plan=executable_plan,
        candidate_row=candidate,
        metrics={
            "grade": "A",
            "recommendation": "deploy-small-capital",
            "risk_state": "OPEN",
            "risk_reason": "normal",
            "operating_lock": {"current_session": {"name": "inactive", "active": False}},
        },
        requested_execution_mode=ExecutionMode.MICRO_LIVE,
        safety_state={
            "new_entry_allowed": True,
            "session_impulse_retest_rollout_readiness": {
                "status": "live_bootstrap_collecting",
                "blockers": [],
                "advisory_blockers": ["no_recent_closed_sample"],
            },
        },
    )

    assert payload["approval_state"] == ApprovalState.BLOCKED.value
    assert payload["approval_reasons"][0]["code"] == "rollout_session_not_allowed"
    assert "dead_session" in payload["approval_reasons"][0]["message"]


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


def test_approval_service_paper_lineage_override_allows_clean_candidate_outside_live_allowlist() -> None:
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
        plan_id="paper_lineage_clean_allowlist_case",
        symbol="FILUSDC",
        validity={
            "strategy_family": "sweep_reversal",
            "strategy_grade": "A",
            "regime": "range",
            "strategy_mode": StrategyMode.A_ONLY.value,
            "recommended_risk_r": 0.4,
        },
    )
    candidate = {
        "deployment_go_no_go": "GO",
        "deployment_code": "go_runtime_gate_open",
        "deployment_message": "GO: runtime gate is open for candidate review.",
        "session_guidance": {"session_name": "london"},
        "operating_lock": {"active": False, "current_session": {"name": "london", "active": True}},
    }
    executable_plan = service.build_executable_plan(plan=plan, context=None, candidate_row=candidate)
    payload = service.approve(
        plan=plan,
        executable_plan=executable_plan,
        candidate_row=candidate,
        metrics={"grade": "A", "recommendation": "deploy", "risk_state": "OPEN", "risk_reason": "normal"},
        paper_lineage_override=True,
    )

    assert payload["paper_lineage_override_applied"] is True
    assert payload["approval_state"] == ApprovalState.APPROVED_AUTO.value
    assert payload["playbook_go_no_go"] == "GO"
    reason_codes = {reason["code"] for reason in payload["approval_reasons"]}
    assert "paper_lineage_override_bypassed_symbol_allowlist" in reason_codes
    assert "paper_lineage_override_bypassed_family_allowlist" in reason_codes


def test_approval_service_blocks_micro_live_on_same_window_family_cluster() -> None:
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_families="",
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(plan_id="micro_live_cluster_guard_case")
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
        live_cluster_guard={
            "cluster_window_minutes": 60,
            "max_same_family_entries_per_window": 1,
            "recent_family_window_entry_count": 1,
            "recent_family_window_symbols": ["ETHUSDC"],
            "loss_cooldown_minutes": 90,
            "loss_cooldown_trigger_count": 2,
            "recent_family_loss_count": 0,
            "recent_family_loss_symbols": [],
        },
    )

    assert payload["approval_state"] == ApprovalState.BLOCKED.value
    assert payload["approval_reasons"][0]["code"] == "live_family_cluster_window_cap_reached"


def test_approval_service_blocks_micro_live_when_entry_is_not_limit() -> None:
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_families="",
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(plan_id="micro_live_limit_only_case", entry_model="CONFIRM")
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
    )

    assert payload["approval_state"] == ApprovalState.BLOCKED.value
    assert payload["approval_reasons"][0]["code"] == "live_limit_only_entry_required"


def test_approval_service_allows_micro_live_when_entry_model_is_in_allowlist() -> None:
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_families="",
        auto_trading_micro_live_allowed_entry_models="LIMIT,CONFIRM",
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(plan_id="micro_live_confirm_allowed_case", entry_model="CONFIRM")
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
    )

    assert payload["approval_state"] == ApprovalState.APPROVED_AUTO.value


def test_approval_service_blocks_micro_live_on_recent_family_loss_cooldown() -> None:
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_families="",
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(plan_id="micro_live_loss_cooldown_case")
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
        live_cluster_guard={
            "cluster_window_minutes": 60,
            "max_same_family_entries_per_window": 1,
            "recent_family_window_entry_count": 0,
            "recent_family_window_symbols": [],
            "loss_cooldown_minutes": 90,
            "loss_cooldown_trigger_count": 2,
            "recent_family_loss_count": 2,
            "recent_family_loss_symbols": ["ETHUSDC", "ARBUSDC"],
        },
    )

    assert payload["approval_state"] == ApprovalState.BLOCKED.value
    assert payload["approval_reasons"][0]["code"] == "live_family_loss_cooldown_active"


def test_approval_service_blocks_micro_live_on_same_direction_family_exposure_cap() -> None:
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_allowed_symbols="SOLUSDC",
        auto_trading_micro_live_allowed_symbols="SOLUSDC",
        auto_trading_micro_live_allowed_families="",
        auto_trading_live_max_same_family_direction_exposures=1,
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(plan_id="micro_live_direction_cap_case", symbol="SOLUSDC")
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
        live_cluster_guard={
            "cluster_window_minutes": 60,
            "max_same_family_entries_per_window": 1,
            "recent_family_window_entry_count": 0,
            "recent_family_window_symbols": [],
            "direction": "long",
            "max_same_family_direction_exposures": 1,
            "recent_family_direction_exposure_count": 1,
            "recent_family_direction_exposure_symbols": ["ETHUSDC"],
            "loss_cooldown_minutes": 90,
            "loss_cooldown_trigger_count": 2,
            "recent_family_loss_count": 0,
            "recent_family_loss_symbols": [],
        },
    )

    assert payload["approval_state"] == ApprovalState.BLOCKED.value
    assert payload["approval_reasons"][0]["code"] == "live_family_direction_exposure_cap_reached"


def test_approval_service_holds_out_transition_variant_by_stable_partial_gate() -> None:
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_families="",
        transition_edge_variant_partial_activation_ratio=0.0,
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(
        plan_id="variant_partial_holdout_case",
        validity={
            "strategy_family": "sweep_reversal",
            "strategy_mode": StrategyMode.A_ONLY.value,
            "strategy_grade": "A",
            "recommended_risk_r": 0.5,
            "transition_edge_variant_applied": True,
            "transition_edge_variant": {"variant": "exp_6_fvg_relaxed_plus_transition_override", "shadow_only": False},
            "thesis_cluster_id": "cluster_variant_holdout",
        },
    )
    candidate = {
        "accepted": True,
        "deployment_go_no_go": "GO",
        "deployment_code": "go_runtime_gate_open",
        "deployment_message": "GO: runtime gate is open for candidate review.",
        "session_guidance": {"session_name": "london"},
        "transition_edge_variant_applied": True,
        "transition_edge_variant": {"variant": "exp_6_fvg_relaxed_plus_transition_override", "shadow_only": False},
        "thesis_cluster_id": "cluster_variant_holdout",
    }
    executable_plan = service.build_executable_plan(plan=plan, context=None, candidate_row=candidate)

    payload = service.approve(
        plan=plan,
        executable_plan=executable_plan,
        candidate_row=candidate,
        metrics={"grade": "A", "recommendation": "deploy", "risk_state": "OPEN", "risk_reason": "normal"},
    )

    assert payload["approval_state"] == ApprovalState.APPROVED_SHADOW.value
    assert payload["approval_reasons"][0]["code"] == "transition_edge_variant_partial_holdout"
    assert payload["transition_edge_variant_applied"] is True
    assert payload["transition_edge_variant_sampling_selected"] is False


def test_approval_service_allows_transition_variant_when_partial_gate_selects_sample() -> None:
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_families="",
        transition_edge_variant_partial_activation_ratio=1.0,
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(
        plan_id="variant_partial_allow_case",
        validity={
            "strategy_family": "sweep_reversal",
            "strategy_mode": StrategyMode.A_ONLY.value,
            "strategy_grade": "A",
            "recommended_risk_r": 0.5,
            "transition_edge_variant_applied": True,
            "transition_edge_variant": {"variant": "exp_6_fvg_relaxed_plus_transition_override", "shadow_only": False},
            "thesis_cluster_id": "cluster_variant_allow",
        },
    )
    candidate = {
        "accepted": True,
        "deployment_go_no_go": "GO",
        "deployment_code": "go_runtime_gate_open",
        "deployment_message": "GO: runtime gate is open for candidate review.",
        "session_guidance": {"session_name": "london"},
        "transition_edge_variant_applied": True,
        "transition_edge_variant": {"variant": "exp_6_fvg_relaxed_plus_transition_override", "shadow_only": False},
        "thesis_cluster_id": "cluster_variant_allow",
    }
    executable_plan = service.build_executable_plan(plan=plan, context=None, candidate_row=candidate)

    payload = service.approve(
        plan=plan,
        executable_plan=executable_plan,
        candidate_row=candidate,
        metrics={"grade": "A", "recommendation": "deploy", "risk_state": "OPEN", "risk_reason": "normal"},
    )

    assert payload["approval_state"] == ApprovalState.APPROVED_AUTO.value
    assert payload["transition_edge_variant_applied"] is True
    assert payload["transition_edge_variant_sampling_selected"] is True


def test_approval_service_ignores_live_cluster_guard_for_paper_mode() -> None:
    settings = Settings(_env_file=None, auto_trading_enabled=True, auto_trading_execution_mode="PAPER")
    service = ExecutionPlanningService(settings=settings, rollout_provider=_OpenRolloutProvider())
    plan = _plan(plan_id="paper_mode_cluster_guard_ignored_case")
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
        live_cluster_guard={
            "cluster_window_minutes": 60,
            "max_same_family_entries_per_window": 1,
            "recent_family_window_entry_count": 5,
            "recent_family_window_symbols": ["ETHUSDC"],
            "loss_cooldown_minutes": 90,
            "loss_cooldown_trigger_count": 2,
            "recent_family_loss_count": 3,
            "recent_family_loss_symbols": ["ETHUSDC", "ARBUSDC"],
        },
    )

    assert payload["approval_state"] == ApprovalState.APPROVED_AUTO.value


def test_approval_service_blocks_micro_live_on_session_direction_hour_contract() -> None:
    current_hour_utc = datetime.now(timezone.utc).hour
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_families="",
        auto_trading_micro_live_session_direction_blocked_hours_utc=f"BTCUSDC:new_york:LONG:{current_hour_utc}",
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(plan_id="micro_live_session_direction_hour_block_case")
    candidate = {
        "accepted": True,
        "deployment_go_no_go": "GO",
        "deployment_code": "go_runtime_gate_open",
        "deployment_message": "GO: runtime gate is open for candidate review.",
        "session_guidance": {"session_name": "new_york"},
    }
    executable_plan = service.build_executable_plan(plan=plan, context=None, candidate_row=candidate)

    payload = service.approve(
        plan=plan,
        executable_plan=executable_plan,
        candidate_row=candidate,
        metrics={"grade": "A", "recommendation": "deploy", "risk_state": "OPEN", "risk_reason": "normal"},
    )

    assert payload["approval_state"] == ApprovalState.BLOCKED.value
    assert payload["approval_reasons"][0]["code"] == "micro_live_session_direction_hour_not_allowed"


def test_approval_service_allows_micro_live_outside_session_direction_hour_contract() -> None:
    current_hour_utc = datetime.now(timezone.utc).hour
    blocked_hour_utc = (current_hour_utc + 1) % 24
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_families="",
        auto_trading_micro_live_session_direction_blocked_hours_utc=f"BTCUSDC:new_york:LONG:{blocked_hour_utc}",
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(plan_id="micro_live_session_direction_hour_allow_case")
    candidate = {
        "accepted": True,
        "deployment_go_no_go": "GO",
        "deployment_code": "go_runtime_gate_open",
        "deployment_message": "GO: runtime gate is open for candidate review.",
        "session_guidance": {"session_name": "new_york"},
    }
    executable_plan = service.build_executable_plan(plan=plan, context=None, candidate_row=candidate)

    payload = service.approve(
        plan=plan,
        executable_plan=executable_plan,
        candidate_row=candidate,
        metrics={"grade": "A", "recommendation": "deploy", "risk_state": "OPEN", "risk_reason": "normal"},
    )

    assert payload["approval_state"] == ApprovalState.APPROVED_AUTO.value


def test_approval_service_ignores_micro_live_daily_entry_cap_when_disabled() -> None:
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_families="",
        auto_trading_micro_live_max_daily_new_entries=0,
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(plan_id="micro_live_daily_entry_cap_disabled_case")
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
        daily_new_entry_count=99,
    )

    assert payload["approval_state"] == ApprovalState.APPROVED_AUTO.value


def test_approval_service_blocks_micro_live_on_strategy_hour_contract() -> None:
    current_hour_utc = datetime.now(timezone.utc).hour
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_families="",
        auto_trading_micro_live_allowed_entry_models="LIMIT,SWEEP_CONFIRM",
        auto_trading_micro_live_symbol_family_entry_direction_blocked_hours_utc=(
            f"BTCUSDC:sweep_reversal:SWEEP_CONFIRM:LONG:{current_hour_utc}"
        ),
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(
        plan_id="micro_live_strategy_hour_block_case",
        entry_model="SWEEP_CONFIRM",
        validity={
            "strategy_family": "sweep_reversal",
            "strategy_grade": "A",
            "strategy_family_reason": "sweep_reversal_confirm",
            "regime": "range",
            "strategy_mode": StrategyMode.A_ONLY.value,
            "recommended_risk_r": 1.0,
        },
    )
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
    )

    assert payload["approval_state"] == ApprovalState.BLOCKED.value
    assert payload["approval_reasons"][0]["code"] == "micro_live_strategy_hour_not_allowed"


def test_approval_service_allows_micro_live_outside_strategy_hour_contract() -> None:
    current_hour_utc = datetime.now(timezone.utc).hour
    blocked_hour_utc = (current_hour_utc + 1) % 24
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_families="",
        auto_trading_micro_live_allowed_entry_models="LIMIT,SWEEP_CONFIRM",
        auto_trading_micro_live_symbol_family_entry_direction_blocked_hours_utc=(
            f"BTCUSDC:sweep_reversal:SWEEP_CONFIRM:LONG:{blocked_hour_utc}"
        ),
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(
        plan_id="micro_live_strategy_hour_allow_case",
        entry_model="SWEEP_CONFIRM",
        validity={
            "strategy_family": "sweep_reversal",
            "strategy_grade": "A",
            "strategy_family_reason": "sweep_reversal_confirm",
            "regime": "range",
            "strategy_mode": StrategyMode.A_ONLY.value,
            "recommended_risk_r": 1.0,
        },
    )
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
    )

    assert payload["approval_state"] == ApprovalState.APPROVED_AUTO.value


def test_approval_service_blocks_micro_live_on_strategy_time_contract(tmp_path: Path) -> None:
    current_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    contract_path = tmp_path / "strategy_time_contract.json"
    contract_path.write_text(
        json.dumps(
            {
                "blocked_buckets": [
                    {
                        "symbol": "BTCUSDC",
                        "strategy_family": "sweep_reversal",
                        "entry_model": "SWEEP_CONFIRM",
                        "direction": "LONG",
                        "weekday_utc": current_utc.weekday(),
                        "hour_utc": current_utc.hour,
                        "minute_utc": current_utc.minute,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_families="",
        auto_trading_micro_live_allowed_entry_models="LIMIT,SWEEP_CONFIRM",
        auto_trading_micro_live_strategy_time_contract_path=str(contract_path),
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(
        plan_id="micro_live_strategy_time_block_case",
        entry_model="SWEEP_CONFIRM",
        validity={
            "strategy_family": "sweep_reversal",
            "strategy_grade": "A",
            "strategy_family_reason": "sweep_reversal_confirm",
            "regime": "range",
            "strategy_mode": StrategyMode.A_ONLY.value,
            "recommended_risk_r": 1.0,
        },
    )
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
    )

    assert payload["approval_state"] == ApprovalState.BLOCKED.value
    assert payload["approval_reasons"][0]["code"] == "micro_live_strategy_time_bucket_not_allowed"


def test_approval_service_allows_micro_live_outside_strategy_time_contract(tmp_path: Path) -> None:
    current_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    next_minute = (current_utc + timedelta(minutes=1)).replace(second=0, microsecond=0)
    contract_path = tmp_path / "strategy_time_contract.json"
    contract_path.write_text(
        json.dumps(
            {
                "blocked_buckets": [
                    {
                        "symbol": "BTCUSDC",
                        "strategy_family": "sweep_reversal",
                        "entry_model": "SWEEP_CONFIRM",
                        "direction": "LONG",
                        "weekday_utc": next_minute.weekday(),
                        "hour_utc": next_minute.hour,
                        "minute_utc": next_minute.minute,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_families="",
        auto_trading_micro_live_allowed_entry_models="LIMIT,SWEEP_CONFIRM",
        auto_trading_micro_live_strategy_time_contract_path=str(contract_path),
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(
        plan_id="micro_live_strategy_time_allow_case",
        entry_model="SWEEP_CONFIRM",
        validity={
            "strategy_family": "sweep_reversal",
            "strategy_grade": "A",
            "strategy_family_reason": "sweep_reversal_confirm",
            "regime": "range",
            "strategy_mode": StrategyMode.A_ONLY.value,
            "recommended_risk_r": 1.0,
        },
    )
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
    )

    assert payload["approval_state"] == ApprovalState.APPROVED_AUTO.value


def test_approval_service_blocks_micro_live_on_strategy_time_contract_with_calendar_date(tmp_path: Path) -> None:
    current_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    contract_path = tmp_path / "strategy_time_contract_calendar.json"
    contract_path.write_text(
        json.dumps(
            {
                "blocked_buckets": [
                    {
                        "symbol": "BTCUSDC",
                        "strategy_family": "sweep_reversal",
                        "entry_model": "SWEEP_CONFIRM",
                        "direction": "LONG",
                        "year_utc": current_utc.year,
                        "month_utc": current_utc.month,
                        "day_utc": current_utc.day,
                        "hour_utc": current_utc.hour,
                        "minute_utc": current_utc.minute,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_families="",
        auto_trading_micro_live_allowed_entry_models="LIMIT,SWEEP_CONFIRM",
        auto_trading_micro_live_strategy_time_contract_path=str(contract_path),
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(
        plan_id="micro_live_strategy_time_calendar_block_case",
        entry_model="SWEEP_CONFIRM",
        validity={
            "strategy_family": "sweep_reversal",
            "strategy_grade": "A",
            "strategy_family_reason": "sweep_reversal_confirm",
            "regime": "range",
            "strategy_mode": StrategyMode.A_ONLY.value,
            "recommended_risk_r": 1.0,
        },
    )
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
    )

    assert payload["approval_state"] == ApprovalState.BLOCKED.value
    assert payload["approval_reasons"][0]["code"] == "micro_live_strategy_time_bucket_not_allowed"


def test_approval_service_blocks_micro_live_on_plan_blocklist(tmp_path: Path) -> None:
    blocklist_path = tmp_path / "plan_blocklist.json"
    blocklist_path.write_text(
        json.dumps({"blocked_plan_ids": ["micro_live_plan_block_case"]}),
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_families="",
        auto_trading_micro_live_plan_blocklist_path=str(blocklist_path),
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(plan_id="micro_live_plan_block_case")
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
    )

    assert payload["approval_state"] == ApprovalState.BLOCKED.value
    assert payload["approval_reasons"][0]["code"] == "micro_live_plan_id_blocklisted"


def test_approval_service_blocks_micro_live_on_event_blackout_window(tmp_path: Path) -> None:
    current_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    blackout_path = tmp_path / "event_blackouts.json"
    blackout_path.write_text(
        json.dumps(
            {
                "windows": [
                    {
                        "label": "FOMC_window",
                        "start_utc": (current_utc - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                        "end_utc": (current_utc + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                        "symbols": ["BTCUSDC"],
                        "strategy_families": ["sweep_reversal"],
                        "entry_models": ["LIMIT"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_families="",
        auto_trading_micro_live_event_blackout_path=str(blackout_path),
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(
        plan_id="micro_live_event_blackout_case",
        validity={
            "strategy_family": "sweep_reversal",
            "strategy_grade": "A",
            "strategy_family_reason": "sweep_reversal_limit",
            "strategy_scorecard_buckets": {"location": 22.0},
            "strategy_scorecard_raw_components": {"htf_trend_clarity": 18.0},
            "regime": "range",
            "strategy_mode": StrategyMode.A_ONLY.value,
            "recommended_risk_r": 1.0,
        },
    )
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
    )

    assert payload["approval_state"] == ApprovalState.BLOCKED.value
    assert payload["approval_reasons"][0]["code"] == "micro_live_event_blackout_active"


def test_approval_service_allows_micro_live_outside_event_blackout_scope(tmp_path: Path) -> None:
    current_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    blackout_path = tmp_path / "event_blackouts_scope.json"
    blackout_path.write_text(
        json.dumps(
            {
                "windows": [
                    {
                        "label": "FOMC_window",
                        "start_utc": (current_utc - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                        "end_utc": (current_utc + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                        "symbols": ["BTCUSDC"],
                        "strategy_families": ["sweep_reversal"],
                        "entry_models": ["SWEEP_CONFIRM"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=None,
        auto_trading_enabled=True,
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_families="",
        auto_trading_micro_live_allowed_entry_models="LIMIT,SWEEP_CONFIRM",
        auto_trading_micro_live_event_blackout_path=str(blackout_path),
    )
    service = ExecutionPlanningService(settings=settings, rollout_provider=_MicroLiveRolloutProvider())
    plan = _plan(
        plan_id="micro_live_event_blackout_allow_case",
        entry_model="LIMIT",
        validity={
            "strategy_family": "sweep_reversal",
            "strategy_grade": "A",
            "strategy_family_reason": "sweep_reversal_limit",
            "strategy_scorecard_buckets": {"location": 22.0},
            "strategy_scorecard_raw_components": {"htf_trend_clarity": 18.0},
            "regime": "range",
            "strategy_mode": StrategyMode.A_ONLY.value,
            "recommended_risk_r": 1.0,
        },
    )
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
    )

    assert payload["approval_state"] == ApprovalState.APPROVED_AUTO.value
