from __future__ import annotations

from pathlib import Path

from app.services.strategy_v2_stress_replay_assessment import StrategyV2StressReplayAssessmentService


def test_stress_replay_assessment_keeps_approximation_when_lineage_is_insufficient() -> None:
    service = StrategyV2StressReplayAssessmentService()
    payload = service.generate(
        symbol="BTCUSDC",
        version="v1",
        stress_validation={
            "schema_version": "strategy_v2_stress_validation_v2",
            "available": True,
            "sample_counts": {
                "eligible_closed_trades": 40,
                "execution_data_trades": 12,
                "estimate_only_trades": 28,
                "latency_reference_trades": 40,
                "shock_regime_trades": 6,
            },
            "latency_source_counts": {
                "candle_open:2026-03-07T00:05:00+00:00": 8,
                "fallback_slippage:plan_valid_from": 32,
            },
            "deployment_recommendation": {
                "scenario_statuses": {
                    "latency_plus_1_bar": {"status": "WARN", "reason": "negative_ev", "catastrophic_loss_detected": False},
                    "partial_fills_only": {"status": "PASS", "reason": "within_limits", "catastrophic_loss_detected": False},
                    "shock_concentration": {"status": "WARN", "reason": "negative_ev", "catastrophic_loss_detected": False},
                },
                "worst_scenario": "shock_concentration",
            },
        },
        stress_replay_lineage={
            "schema_version": "strategy_v2_stress_replay_lineage_v1",
            "available": True,
            "runtime_inputs_ready": False,
            "sample_counts": {
                "eligible_closed_trades": 40,
                "full_fill_path_trades": 12,
                "estimate_only_trades": 28,
                "latency_bar_trades": 8,
            },
            "coverage": {
                "execution_fill_coverage": 0.30,
                "latency_candle_coverage": 0.20,
                "candle_path_coverage": 0.35,
                "estimate_only_share": 0.70,
            },
            "lineage_contract": {
                "min_execution_fill_coverage": 0.70,
                "min_latency_candle_coverage": 0.70,
            },
            "blocked_by": [
                "execution_fill_coverage_below_threshold",
                "latency_candle_coverage_below_threshold",
            ],
            "next_steps": [
                "increase execution fill coverage for closed v2 trades",
            ],
        },
        write_report=False,
    )

    assert payload["available"] is True
    assert payload["full_replay_ready"] is False
    assert payload["replacement_recommended"] is False
    assert payload["true_runner_readiness"]["true_runner_ready"] is False
    assert "prototype_replay_outputs_unavailable" in payload["true_runner_readiness"]["blocked_by"]
    assert payload["deployment_recommendation"]["decision"] == "keep_approximation"
    assert payload["deployment_recommendation"]["reason"] == "insufficient_runtime_lineage"
    assert "execution_fill_coverage_below_threshold" in payload["blocked_by"]
    assert "latency_candle_coverage_below_threshold" in payload["blocked_by"]


def test_stress_replay_assessment_recommends_full_replay_when_coverage_is_good_and_stress_degrades() -> None:
    service = StrategyV2StressReplayAssessmentService()
    payload = service.generate(
        symbol="BTCUSDC",
        version="v1",
        stress_validation={
            "schema_version": "strategy_v2_stress_validation_v2",
            "available": True,
            "sample_counts": {
                "eligible_closed_trades": 60,
                "execution_data_trades": 54,
                "estimate_only_trades": 6,
                "latency_reference_trades": 60,
                "shock_regime_trades": 10,
            },
            "latency_source_counts": {
                "candle_open:2026-03-07T00:05:00+00:00": 30,
                "candle_open:2026-03-07T00:10:00+00:00": 18,
                "fallback_slippage:plan_valid_from": 12,
            },
            "deployment_recommendation": {
                "scenario_statuses": {
                    "latency_plus_1_bar": {"status": "WARN", "reason": "negative_ev", "catastrophic_loss_detected": False},
                    "partial_fills_only": {"status": "WARN", "reason": "negative_ev", "catastrophic_loss_detected": False},
                    "shock_concentration": {"status": "PASS", "reason": "within_limits", "catastrophic_loss_detected": False},
                },
                "worst_scenario": "latency_plus_1_bar",
            },
        },
        stress_replay_lineage={
            "schema_version": "strategy_v2_stress_replay_lineage_v1",
            "available": True,
            "runtime_inputs_ready": True,
            "sample_counts": {
                "eligible_closed_trades": 60,
                "full_fill_path_trades": 54,
                "estimate_only_trades": 6,
                "latency_bar_trades": 48,
            },
            "coverage": {
                "execution_fill_coverage": 0.90,
                "latency_candle_coverage": 0.80,
                "candle_path_coverage": 0.82,
                "estimate_only_share": 0.10,
            },
            "lineage_contract": {
                "min_execution_fill_coverage": 0.70,
                "min_latency_candle_coverage": 0.70,
            },
            "blocked_by": [],
            "next_steps": ["runtime lineage is ready enough to prototype replay runner inputs"],
        },
        write_report=True,
    )

    assert payload["full_replay_ready"] is True
    assert payload["replacement_recommended"] is True
    assert payload["true_runner_readiness"]["true_runner_ready"] is False
    assert "prototype_replay_outputs_unavailable" in payload["true_runner_readiness"]["blocked_by"]
    assert payload["deployment_recommendation"]["decision"] == "prepare_full_replay"
    assert payload["deployment_recommendation"]["priority"] == "medium"
    assert payload["scenario_evidence"]["degraded_scenarios"] == ["latency_plus_1_bar", "partial_fills_only"]
    path = Path(payload["report_path"])
    assert path.exists()
    body = path.read_text(encoding="utf-8")
    assert "# Strategy v2 Stress Replay Assessment: BTCUSDC" in body
    assert "## Deployment Recommendation" in body


def test_stress_replay_assessment_marks_true_runner_ready_with_strong_lineage_and_outputs() -> None:
    service = StrategyV2StressReplayAssessmentService()
    payload = service.generate(
        symbol="BTCUSDC",
        version="v1",
        stress_validation={
            "schema_version": "strategy_v2_stress_validation_v2",
            "available": True,
            "sample_counts": {
                "eligible_closed_trades": 72,
                "execution_data_trades": 66,
                "estimate_only_trades": 6,
                "latency_reference_trades": 72,
                "shock_regime_trades": 14,
            },
            "latency_source_counts": {
                "candle_open:2026-03-07T00:05:00+00:00": 44,
                "candle_open:2026-03-07T00:10:00+00:00": 20,
                "fallback_slippage:plan_valid_from": 8,
            },
            "deployment_recommendation": {
                "scenario_statuses": {
                    "latency_plus_1_bar": {"status": "WARN", "reason": "negative_ev", "catastrophic_loss_detected": False},
                    "partial_fills_only": {"status": "PASS", "reason": "within_limits", "catastrophic_loss_detected": False},
                    "shock_concentration": {"status": "FAIL", "reason": "catastrophic_drawdown", "catastrophic_loss_detected": True},
                },
                "worst_scenario": "shock_concentration",
            },
        },
        stress_replay_lineage={
            "schema_version": "strategy_v2_stress_replay_lineage_v1",
            "available": True,
            "runtime_inputs_ready": True,
            "sample_counts": {
                "eligible_closed_trades": 72,
                "full_fill_path_trades": 66,
                "estimate_only_trades": 6,
                "latency_bar_trades": 64,
            },
            "coverage": {
                "execution_fill_coverage": 0.9167,
                "latency_candle_coverage": 0.8889,
                "candle_path_coverage": 0.9167,
                "estimate_only_share": 0.0833,
            },
            "lineage_contract": {
                "min_execution_fill_coverage": 0.70,
                "min_latency_candle_coverage": 0.70,
            },
            "blocked_by": [],
            "next_steps": ["runtime lineage is ready enough to prototype replay runner inputs"],
        },
        stress_replay_output_artifacts={
            "available": True,
            "comparison_ready": True,
            "summary_counts": {
                "scenarios_expected": 3,
                "scenarios_with_artifacts": 3,
                "scenarios_compared": 3,
                "replay_trade_rows": 40,
            },
            "lineage_summary": {
                "available": True,
                "worker_modes": ["prototype_from_lineage_batches"],
                "compared_scenarios": ["shock_concentration", "latency_plus_1_bar", "partial_fills_only"],
                "input_batch_count": 3,
                "input_trade_rows": 40,
            },
            "scenario_outputs": {
                "latency_plus_1_bar": {"available": True, "summary": {"ev": -0.2}},
                "shock_concentration": {"available": True, "summary": {"ev": -0.5}},
                "partial_fills_only": {"available": True, "summary": {"ev": 0.02}},
            },
        },
        pbo_dsr_metrics={
            "available": True,
            "metrics_complete": True,
            "selected_trial": {
                "trial_run_id": "trial_threshold_01",
                "writer_source": "true_threshold_sweep_runner_v1",
            },
            "lineage_audit": {
                "audit_status": "PASS",
                "reason": "selected_trial_from_true_threshold_with_dual_lineage",
                "selected_trial_writer_source": "true_threshold_sweep_runner_v1",
                "selected_trial_selection_rule": "true_threshold_sweep_top_in_sample_ev",
                "selected_trial_from_runtime_proxy": False,
                "selected_trial_from_true_threshold": True,
            },
            "deployment_recommendation": {
                "decision": "pass_minimum_gate",
                "meets_protocol_gate": True,
                "reason": "pbo_pass_dsr_positive",
            },
        },
        write_report=False,
    )

    assert payload["full_replay_ready"] is True
    assert payload["replacement_recommended"] is True
    assert payload["true_runner_readiness"]["true_runner_ready"] is True
    assert payload["true_runner_readiness"]["stage"] == "ready_for_true_market_runner"
    assert payload["true_runner_readiness"]["critical_scenarios"] == ["shock_concentration", "latency_plus_1_bar"]
    assert payload["deployment_recommendation"]["true_runner_promotion_gate_applied"] is True
    assert payload["deployment_recommendation"]["true_runner_promotion_ready"] is True
    assert payload["deployment_recommendation"]["true_runner_promotion_action"] == "promote_true_market_runner"
    assert payload["deployment_recommendation"]["threshold_lineage_audit_status"] == "PASS"
    assert payload["deployment_recommendation"]["replay_output_lineage_alignment_status"] == "PASS"
    assert payload["deployment_recommendation"]["replay_output_lineage_compared_scenarios"] == [
        "shock_concentration",
        "latency_plus_1_bar",
        "partial_fills_only",
    ]
    assert payload["deployment_recommendation"]["approval_cross_display"]["cross_display_status"] == "REVIEW"
    assert (
        payload["deployment_recommendation"]["approval_cross_display"]["cross_display_reason"]
        == "true_threshold_winner_with_replay_fail_worst_scenario"
    )
    assert (
        payload["deployment_recommendation"]["approval_cross_display"]["replay_derived_worst_scenario"]
        == "shock_concentration"
    )
    assert (
        payload["deployment_recommendation"]["approval_cross_display"]["threshold_lineage_winner_type"]
        == "true_threshold"
    )
    assert payload["deployment_recommendation"]["approval_cross_display"]["approval_warning_locked"] is False
    assert payload["deployment_recommendation"]["approval_cross_display"]["approval_warning_code"] == "none"


def test_stress_replay_assessment_holds_true_runner_when_threshold_lineage_audit_warns() -> None:
    service = StrategyV2StressReplayAssessmentService()
    payload = service.generate(
        symbol="BTCUSDC",
        version="v1",
        stress_validation={
            "schema_version": "strategy_v2_stress_validation_v2",
            "available": True,
            "sample_counts": {
                "eligible_closed_trades": 72,
                "execution_data_trades": 66,
                "estimate_only_trades": 6,
                "latency_reference_trades": 72,
                "shock_regime_trades": 14,
            },
            "latency_source_counts": {
                "candle_open:2026-03-07T00:05:00+00:00": 44,
                "candle_open:2026-03-07T00:10:00+00:00": 20,
                "fallback_slippage:plan_valid_from": 8,
            },
            "deployment_recommendation": {
                "scenario_statuses": {
                    "latency_plus_1_bar": {"status": "WARN", "reason": "negative_ev", "catastrophic_loss_detected": False},
                    "partial_fills_only": {"status": "PASS", "reason": "within_limits", "catastrophic_loss_detected": False},
                    "shock_concentration": {"status": "FAIL", "reason": "catastrophic_drawdown", "catastrophic_loss_detected": True},
                },
                "worst_scenario": "shock_concentration",
            },
        },
        stress_replay_lineage={
            "schema_version": "strategy_v2_stress_replay_lineage_v1",
            "available": True,
            "runtime_inputs_ready": True,
            "sample_counts": {
                "eligible_closed_trades": 72,
                "full_fill_path_trades": 66,
                "estimate_only_trades": 6,
                "latency_bar_trades": 64,
            },
            "coverage": {
                "execution_fill_coverage": 0.9167,
                "latency_candle_coverage": 0.8889,
                "candle_path_coverage": 0.9167,
                "estimate_only_share": 0.0833,
            },
            "lineage_contract": {
                "min_execution_fill_coverage": 0.70,
                "min_latency_candle_coverage": 0.70,
            },
            "blocked_by": [],
            "next_steps": ["runtime lineage is ready enough to prototype replay runner inputs"],
        },
        stress_replay_output_artifacts={
            "available": True,
            "comparison_ready": True,
            "summary_counts": {
                "scenarios_expected": 3,
                "scenarios_with_artifacts": 3,
                "scenarios_compared": 3,
                "replay_trade_rows": 40,
            },
            "lineage_summary": {
                "available": True,
                "worker_modes": ["prototype_from_lineage_batches"],
                "compared_scenarios": ["shock_concentration", "latency_plus_1_bar", "partial_fills_only"],
                "input_batch_count": 3,
                "input_trade_rows": 40,
            },
            "scenario_outputs": {
                "latency_plus_1_bar": {"available": True, "summary": {"ev": -0.2}},
                "shock_concentration": {"available": True, "summary": {"ev": -0.5}},
                "partial_fills_only": {"available": True, "summary": {"ev": 0.02}},
            },
        },
        pbo_dsr_metrics={
            "available": True,
            "metrics_complete": True,
            "selected_trial": {
                "trial_run_id": "trial_proxy_01",
                "writer_source": "runtime_validation_proxy_v1",
            },
            "lineage_audit": {
                "audit_status": "WARN",
                "reason": "selected_trial_from_runtime_proxy_while_true_threshold_lineage_exists",
                "selected_trial_writer_source": "runtime_validation_proxy_v1",
                "selected_trial_selection_rule": "runtime_validation_proxy_top_in_sample_ev",
                "selected_trial_from_runtime_proxy": True,
                "selected_trial_from_true_threshold": False,
            },
            "deployment_recommendation": {
                "decision": "warn_lineage_audit",
                "meets_protocol_gate": True,
                "reason": "selected_trial_from_runtime_proxy_while_true_threshold_lineage_exists",
            },
        },
        write_report=False,
    )

    assert payload["true_runner_readiness"]["true_runner_ready"] is True
    assert payload["deployment_recommendation"]["true_runner_promotion_gate_applied"] is True
    assert payload["deployment_recommendation"]["true_runner_promotion_ready"] is False
    assert payload["deployment_recommendation"]["true_runner_promotion_action"] == "stay_on_prototype"
    assert payload["deployment_recommendation"]["true_runner_promotion_reason"].startswith("replay_output_lineage_alignment:")
    assert payload["deployment_recommendation"]["selected_trial_from_runtime_proxy"] is True
    assert payload["deployment_recommendation"]["replay_output_lineage_alignment_status"] == "WARN"
    assert payload["deployment_recommendation"]["replay_output_lineage_alignment_reason"] == (
        "selected_trial_from_runtime_proxy_with_replay_output_lineage"
    )
    assert payload["deployment_recommendation"]["approval_cross_display"]["cross_display_status"] == "REVIEW"
    assert (
        payload["deployment_recommendation"]["approval_cross_display"]["cross_display_reason"]
        == "runtime_proxy_winner_with_replay_worst_scenario"
    )
    assert (
        payload["deployment_recommendation"]["approval_cross_display"]["threshold_lineage_winner_type"]
        == "runtime_proxy"
    )
    assert payload["deployment_recommendation"]["approval_cross_display"]["approval_warning_locked"] is True
    assert (
        payload["deployment_recommendation"]["approval_cross_display"]["approval_warning_code"]
        == "proxy_selected_trial_against_replay_backed_worst_scenario"
    )


def test_stress_replay_assessment_tolerates_malformed_threshold_settings_and_counts() -> None:
    service = StrategyV2StressReplayAssessmentService()
    original_values = {
        "stress_true_replay_min_execution_fill_coverage": service.settings.stress_true_replay_min_execution_fill_coverage,
        "stress_true_replay_min_latency_candle_coverage": service.settings.stress_true_replay_min_latency_candle_coverage,
        "stress_true_replay_min_candle_path_coverage": service.settings.stress_true_replay_min_candle_path_coverage,
        "stress_true_replay_min_scenarios_compared": service.settings.stress_true_replay_min_scenarios_compared,
        "stress_replay_lineage_min_execution_fill_coverage": service.settings.stress_replay_lineage_min_execution_fill_coverage,
        "stress_replay_lineage_min_latency_candle_coverage": service.settings.stress_replay_lineage_min_latency_candle_coverage,
    }
    try:
        service.settings.stress_true_replay_min_execution_fill_coverage = float("inf")
        service.settings.stress_true_replay_min_latency_candle_coverage = "bad"
        service.settings.stress_true_replay_min_candle_path_coverage = "bad"
        service.settings.stress_true_replay_min_scenarios_compared = "bad"
        service.settings.stress_replay_lineage_min_execution_fill_coverage = "bad"
        service.settings.stress_replay_lineage_min_latency_candle_coverage = float("inf")

        payload = service.generate(
            symbol="BTCUSDC",
            version="v2",
            stress_validation={
                "sample_counts": {"eligible_closed_trades": "bad", "shock_regime_trades": float("inf")},
                "latency_source_counts": {"candle_open:1": "bad", "fallback_slippage:1": float("inf")},
                "deployment_recommendation": {"scenario_statuses": {}},
            },
            stress_replay_lineage={
                "available": True,
                "sample_counts": {"eligible_closed_trades": "bad", "full_fill_path_trades": float("inf")},
                "coverage": {"execution_fill_coverage": "bad", "latency_candle_coverage": float("inf")},
                "lineage_contract": {"min_execution_fill_coverage": "bad", "min_latency_candle_coverage": float("inf")},
            },
            stress_replay_output_artifacts={"available": True, "comparison_ready": True, "summary_counts": {"scenarios_compared": "bad"}},
            write_report=False,
        )

        assert payload["available"] is False
        assert payload["readiness_gates"]["min_execution_fill_coverage"] == 0.7
        assert payload["readiness_gates"]["min_latency_candle_coverage"] == 0.7
        assert payload["true_runner_readiness"]["gates"]["min_execution_fill_coverage"] == 0.85
        assert payload["true_runner_readiness"]["gates"]["min_latency_candle_coverage"] == 0.8
        assert payload["true_runner_readiness"]["gates"]["min_candle_path_coverage"] == 0.9
        assert payload["true_runner_readiness"]["gates"]["min_scenarios_compared"] == 2
    finally:
        for key, value in original_values.items():
            setattr(service.settings, key, value)
