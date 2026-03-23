from __future__ import annotations

from pathlib import Path

from app.services.strategy_v2_stress_replay_runner_contract import StrategyV2StressReplayRunnerContractService


def test_stress_replay_runner_contract_blocks_when_lineage_is_incomplete() -> None:
    service = StrategyV2StressReplayRunnerContractService()
    payload = service.generate(
        symbol="BTCUSDC",
        version="v2",
        stress_validation={
            "schema_version": "strategy_v2_stress_validation_v2",
            "deployment_recommendation": {
                "scenario_statuses": {
                    "latency_plus_1_bar": {"status": "WARN", "reason": "negative_ev", "catastrophic_loss_detected": False},
                    "partial_fills_only": {"status": "PASS", "reason": "within_limits", "catastrophic_loss_detected": False},
                    "shock_concentration": {"status": "WARN", "reason": "negative_ev", "catastrophic_loss_detected": False},
                }
            },
            "sample_counts": {"shock_regime_trades": 5},
        },
        stress_replay_lineage={
            "schema_version": "strategy_v2_stress_replay_lineage_v1",
            "available": True,
            "runtime_inputs_ready": False,
            "sample_counts": {
                "eligible_closed_trades": 40,
                "latency_bar_trades": 10,
                "full_fill_path_trades": 12,
            },
            "coverage": {
                "execution_fill_coverage": 0.30,
                "latency_candle_coverage": 0.25,
                "candle_path_coverage": 0.40,
            },
            "fill_path": {"full_fill_path_coverage": 0.30},
            "blocked_by": [
                "execution_fill_coverage_below_threshold",
                "latency_candle_coverage_below_threshold",
            ],
            "next_steps": ["increase execution fill coverage for closed v2 trades"],
        },
        stress_replay_assessment={
            "schema_version": "strategy_v2_stress_replay_assessment_v1",
            "available": True,
            "full_replay_ready": False,
            "replacement_recommended": False,
            "true_runner_readiness": {
                "true_runner_ready": False,
                "stage": "prototype_only",
                "blocked_by": ["true_runner_base_readiness_not_met"],
                "next_steps": ["keep prototype replay worker until base replay readiness is met"],
            },
            "deployment_recommendation": {
                "priority": "low",
            },
        },
        write_report=False,
    )

    assert payload["design_ready"] is True
    assert payload["runtime_job_ready"] is False
    assert payload["implementation_status"] == "runner_contract_defined_inputs_incomplete"
    assert "execution_fill_coverage_below_threshold" in payload["blocked_by"]
    assert payload["scenario_contract"]["latency_plus_1_bar"]["ready"] is False
    assert payload["scenario_contract"]["partial_fills_only"]["ready"] is False
    assert payload["readiness"]["ready_scenarios"] == []
    assert payload["true_runner_readiness"]["true_runner_ready"] is False


def test_stress_replay_runner_contract_reports_ready_scenarios_and_batching() -> None:
    service = StrategyV2StressReplayRunnerContractService()
    payload = service.generate(
        symbol="BTCUSDC",
        version="v2",
        stress_validation={
            "schema_version": "strategy_v2_stress_validation_v2",
            "deployment_recommendation": {
                "scenario_statuses": {
                    "latency_plus_1_bar": {"status": "WARN", "reason": "negative_ev", "catastrophic_loss_detected": False},
                    "partial_fills_only": {"status": "WARN", "reason": "negative_ev", "catastrophic_loss_detected": False},
                    "shock_concentration": {"status": "FAIL", "reason": "catastrophic_loss", "catastrophic_loss_detected": True},
                },
                "priority": "high",
            },
            "sample_counts": {"shock_regime_trades": 18},
        },
        stress_replay_lineage={
            "schema_version": "strategy_v2_stress_replay_lineage_v1",
            "available": True,
            "runtime_inputs_ready": True,
            "sample_counts": {
                "eligible_closed_trades": 60,
                "latency_bar_trades": 52,
                "full_fill_path_trades": 48,
            },
            "coverage": {
                "execution_fill_coverage": 0.88,
                "latency_candle_coverage": 0.86,
                "candle_path_coverage": 0.85,
            },
            "fill_path": {"full_fill_path_coverage": 0.80},
            "blocked_by": [],
            "next_steps": ["runtime lineage is ready enough to prototype replay runner inputs"],
            "report_path": "reports/validation/lineage.md",
        },
        stress_replay_assessment={
            "schema_version": "strategy_v2_stress_replay_assessment_v1",
            "available": True,
            "full_replay_ready": True,
            "replacement_recommended": True,
            "true_runner_readiness": {
                "true_runner_ready": True,
                "stage": "ready_for_true_market_runner",
                "blocked_by": [],
                "next_steps": [],
            },
            "deployment_recommendation": {
                "priority": "high",
            },
            "report_path": "reports/validation/assessment.md",
        },
        write_report=True,
    )

    assert payload["runtime_job_ready"] is True
    assert payload["implementation_status"] == "runner_contract_defined_ready_for_true_market_runner"
    assert payload["readiness"]["ready_scenarios"] == [
        "shock_concentration",
        "latency_plus_1_bar",
        "partial_fills_only",
    ]
    assert payload["true_runner_readiness"]["true_runner_ready"] is True
    assert payload["runner_contract"]["batching"]["suggested_jobs"]["shock_concentration"] == 1
    assert payload["worker_input_contract"]["required_sources"][0] == "closed_v2_plans"
    path = Path(payload["report_path"])
    assert path.exists()
    body = path.read_text(encoding="utf-8")
    assert "# Strategy v2 Stress Replay Runner Contract: BTCUSDC" in body
    assert "## Runner Contract" in body
