from __future__ import annotations

from app.services.kill_condition_automation import KillConditionAutomationService


def test_kill_condition_automation_defers_to_manual_override() -> None:
    payload = KillConditionAutomationService.generate(
        strategy_metrics={"risk_state": "CLOSED", "risk_reason": "api_unhealthy"},
        safety_state={
            "kill_switch_active": True,
            "close_only_active": False,
            "config_close_only_active": False,
            "active_locks": [{"reason_code": "kill_switch_active"}],
            "matching_locks": [{"reason_code": "kill_switch_active"}],
        },
        execution_friction_measurement={"friction_state": "degraded_friction", "weakest_axis": "slippage_state"},
        forward_stress_regime_validation={
            "validation_state": "insufficient_generalization",
            "weakest_axis": "stress_state",
        },
        recent_reconciliation_summary={"highest_severity": "CRITICAL", "critical_count": 1, "lock_required_count": 1},
        execution_degradation_advisory={"status": "manual_review"},
        family_execution_degradation_advisory={"top_family": {"status": "watch"}},
    )

    assert payload["available"] is True
    assert payload["kill_condition_state"] == "observe_only"
    assert payload["automation_bias"] == "observe_only"
    assert payload["write_scope"] == "none"
    assert payload["trigger_axis"] == "manual_override_axis"
    assert payload["active_manual_override"] is True
    assert payload["manual_override_reason"] == "kill_switch_active"
    assert payload["arm_required"] is False
    assert "manual_override:kill_switch_active" in payload["reason_codes"]


def test_kill_condition_automation_escalates_to_kill_switch_review_on_multi_axis_failure() -> None:
    payload = KillConditionAutomationService.generate(
        strategy_metrics={"risk_state": "CLOSED", "risk_reason": "api_unhealthy"},
        safety_state={
            "kill_switch_active": False,
            "close_only_active": False,
            "config_close_only_active": False,
            "active_locks": [],
            "matching_locks": [],
        },
        execution_friction_measurement={"friction_state": "degraded_friction", "weakest_axis": "slippage_state"},
        forward_stress_regime_validation={
            "validation_state": "insufficient_generalization",
            "weakest_axis": "stress_state",
        },
        recent_reconciliation_summary={"highest_severity": "CRITICAL", "critical_count": 1, "lock_required_count": 1},
        execution_degradation_advisory={"status": "manual_review"},
        family_execution_degradation_advisory={"top_family": {"status": "watch"}},
    )

    assert payload["available"] is True
    assert payload["kill_condition_state"] == "kill_switch_review"
    assert payload["automation_bias"] == "propose_kill_switch"
    assert payload["write_scope"] == "proposal_only"
    assert payload["trigger_axis"] == "reconciliation_axis"
    assert payload["active_manual_override"] is False
    assert payload["arm_required"] is True
    assert "kill_condition:kill_switch_review" in payload["reason_codes"]
    assert "risk_gate:closed" in payload["reason_codes"]
    assert "friction:degraded" in payload["reason_codes"]
    assert "generalization:insufficient" in payload["reason_codes"]
    assert "reconciliation:critical" in payload["reason_codes"]
