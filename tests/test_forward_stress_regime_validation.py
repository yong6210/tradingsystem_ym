from app.services.forward_stress_regime_validation import ForwardStressRegimeValidationService


def test_forward_stress_regime_validation_marks_validated_generalization_when_axes_are_stable() -> None:
    service = ForwardStressRegimeValidationService()

    payload = service.generate(
        walk_forward={"trades": 24, "mean_ev": 0.12, "p5_ev": -0.2},
        strategy_v2_validation={
            "available": True,
            "sample_counts": {"eligible_closed_trades": 24},
            "deployment_recommendation": {"preferred_live_mode": "A_ONLY"},
            "regime_summary": {"best_ev_regime": {"name": "range"}},
            "session_summary": {"best_ev_session": {"name": "overlap"}},
            "regime_metrics": {
                "range": {"trades": 12, "ev": 0.14, "p5_ev": -0.2, "time_failure_ratio": 0.10},
                "trend": {"trades": 10, "ev": 0.09, "p5_ev": -0.3, "time_failure_ratio": 0.12},
            },
            "session_metrics": {
                "overlap": {"trades": 11, "ev": 0.13, "p5_ev": -0.2, "time_failure_ratio": 0.09},
                "london": {"trades": 9, "ev": 0.08, "p5_ev": -0.3, "time_failure_ratio": 0.11},
            },
        },
        strategy_v2_stress_validation={
            "available": True,
            "sample_counts": {"eligible_closed_trades": 24, "execution_data_trades": 16},
            "deployment_recommendation": {
                "stress_pass": True,
                "reason": "keep_current_validation",
                "worst_scenario": "stressed_cost",
                "replay_gate_applied": False,
                "divergence_gate_applied": False,
            },
        },
        strategy_v2_stress_replay_assessment={
            "available": True,
            "reason": "runtime_lineage_ready",
            "replacement_recommended": False,
            "deployment_recommendation": {
                "decision": "keep_approximation",
                "true_runner_promotion_ready": False,
            },
        },
        strategy_v2_stress_replay_lineage={
            "available": True,
            "runtime_inputs_ready": True,
            "reason": "runtime_lineage_ready",
        },
    )

    assert payload is not None
    assert payload["validation_state"] == "validated_generalization"
    assert payload["validation_bias"] == "support_current_validation"
    assert payload["coverage_state"] == "mature_validation"
    assert payload["walk_forward_state"] == "validated_walk_forward"
    assert payload["stress_state"] == "validated_stress"
    assert payload["replay_state"] == "approximation_confirmed"
    assert payload["regime_split_state"] == "validated_regime_split"
    assert payload["session_split_state"] == "validated_session_split"
    assert payload["weakest_axis"] == ""


def test_forward_stress_regime_validation_marks_insufficient_generalization_when_stress_breaks() -> None:
    service = ForwardStressRegimeValidationService()

    payload = service.generate(
        walk_forward={"trades": 24, "mean_ev": 0.08, "p5_ev": -0.2},
        strategy_v2_validation={
            "available": True,
            "sample_counts": {"eligible_closed_trades": 24},
            "deployment_recommendation": {"preferred_live_mode": "A_ONLY"},
            "regime_summary": {"best_ev_regime": {"name": "range"}},
            "session_summary": {"best_ev_session": {"name": "overlap"}},
            "regime_metrics": {
                "range": {"trades": 12, "ev": 0.11, "p5_ev": -0.2, "time_failure_ratio": 0.12},
                "trend": {"trades": 9, "ev": 0.06, "p5_ev": -0.3, "time_failure_ratio": 0.14},
            },
            "session_metrics": {
                "overlap": {"trades": 10, "ev": 0.10, "p5_ev": -0.2, "time_failure_ratio": 0.10},
                "london": {"trades": 8, "ev": 0.05, "p5_ev": -0.3, "time_failure_ratio": 0.11},
            },
        },
        strategy_v2_stress_validation={
            "available": True,
            "sample_counts": {"eligible_closed_trades": 24, "execution_data_trades": 16},
            "deployment_recommendation": {
                "stress_pass": False,
                "reason": "scenario_catastrophic_drawdown:shock_concentration",
                "worst_scenario": "shock_concentration",
                "replay_gate_applied": True,
                "divergence_gate_applied": True,
            },
        },
        strategy_v2_stress_replay_assessment={
            "available": True,
            "reason": "runtime_lineage_ready",
            "replacement_recommended": False,
            "deployment_recommendation": {
                "decision": "keep_approximation",
                "true_runner_promotion_ready": False,
            },
        },
        strategy_v2_stress_replay_lineage={
            "available": True,
            "runtime_inputs_ready": True,
            "reason": "runtime_lineage_ready",
        },
    )

    assert payload is not None
    assert payload["validation_state"] == "insufficient_generalization"
    assert payload["validation_bias"] == "reduce_deployment_confidence"
    assert payload["stress_state"] == "fragile_stress"
    assert payload["weakest_axis"] == "stress_state"
    assert "stress_catastrophic_drawdown" in payload["reason_codes"]
