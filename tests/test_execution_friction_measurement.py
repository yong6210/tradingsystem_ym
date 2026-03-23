from app.services.execution_friction_measurement import ExecutionFrictionMeasurementService


def test_execution_friction_measurement_marks_healthy_friction_when_measured_drag_is_stable() -> None:
    service = ExecutionFrictionMeasurementService()

    payload = service.generate(
        execution_quality={
            "fills_matched": 10,
            "fill_events_total": 12,
            "fill_rate": 0.72,
            "fill_sources": {"execution_fills": 10, "zone_outcomes_fallback": 0},
            "slippage_bps": {"avg": 2.0, "p95": 5.0},
            "entry_latency_seconds": {"avg": 120.0, "p95": 300.0},
            "information_failure_ratio": 0.05,
            "time_failure_ratio": 0.10,
            "report_path": "reports/execution/execution_quality.md",
        },
        recent_reconciliation_summary={
            "healthy": True,
            "highest_severity": "INFO",
            "degraded": False,
            "critical_count": 0,
            "lock_required_count": 0,
        },
        strategy_v2_stress_validation={
            "available": True,
            "report_path": "reports/validation/stress_validation.md",
            "comparison": {"ev": 0.01, "p5_ev": 0.0},
            "cost_summary": {"fee_component_r": {"avg": 0.02, "p95": 0.04}},
            "scenario_summary": {"latency_penalty_r": {"avg": 0.03, "p95": 0.05}},
            "deployment_recommendation": {
                "stress_pass": True,
                "reason": "keep",
                "replay_gate_applied": False,
                "divergence_gate_applied": False,
                "worst_scenario": "stressed_cost",
            },
        },
        approval_caps={"expected_fee_bps": 4.0, "max_slippage_bps": 12.0},
    )

    assert payload is not None
    assert payload["friction_state"] == "healthy_friction"
    assert payload["friction_bias"] == "keep_execution_confidence"
    assert payload["measurement_coverage_state"] == "mature_measurement"
    assert payload["fill_conversion_state"] == "healthy_fill_conversion"
    assert payload["slippage_state"] == "healthy_slippage"
    assert payload["latency_state"] == "healthy_latency"
    assert payload["fee_state"] == "healthy_fee_drag"
    assert payload["reconciliation_state"] == "healthy_reconciliation"
    assert payload["stress_drag_state"] == "healthy_stress_drag"
    assert payload["confidence"] == "high"
    assert payload["weakest_axis"] == ""


def test_execution_friction_measurement_keeps_reconciliation_break_as_degraded_friction() -> None:
    service = ExecutionFrictionMeasurementService()

    payload = service.generate(
        execution_quality={
            "fills_matched": 12,
            "fill_events_total": 15,
            "fill_rate": 0.68,
            "fill_sources": {"execution_fills": 10, "zone_outcomes_fallback": 2},
            "slippage_bps": {"avg": 3.0, "p95": 6.0},
            "entry_latency_seconds": {"avg": 180.0, "p95": 360.0},
            "information_failure_ratio": 0.08,
            "time_failure_ratio": 0.12,
            "report_path": "reports/execution/execution_quality.md",
        },
        recent_reconciliation_summary={
            "healthy": False,
            "highest_severity": "CRITICAL",
            "degraded": True,
            "critical_count": 1,
            "lock_required_count": 1,
        },
        strategy_v2_stress_validation={
            "available": True,
            "report_path": "reports/validation/stress_validation.md",
            "comparison": {"ev": 0.0, "p5_ev": 0.0},
            "cost_summary": {"fee_component_r": {"avg": 0.03, "p95": 0.05}},
            "scenario_summary": {"latency_penalty_r": {"avg": 0.04, "p95": 0.06}},
            "deployment_recommendation": {
                "stress_pass": True,
                "reason": "keep",
                "replay_gate_applied": False,
                "divergence_gate_applied": False,
                "worst_scenario": "stressed_cost",
            },
        },
        approval_caps={"expected_fee_bps": 4.0, "max_slippage_bps": 12.0},
    )

    assert payload is not None
    assert payload["friction_state"] == "degraded_friction"
    assert payload["friction_bias"] == "reduce_execution_confidence"
    assert payload["measurement_coverage_state"] == "mature_measurement"
    assert payload["reconciliation_state"] == "degraded_reconciliation"
    assert payload["slippage_state"] == "watch_slippage"
    assert payload["weakest_axis"] == "reconciliation_state"
    assert payload["confidence"] == "medium"
    assert payload["source_summary"]["reconciliation_highest_severity"] == "CRITICAL"
    assert "reconciliation:degraded_reconciliation" in payload["reason_codes"]
