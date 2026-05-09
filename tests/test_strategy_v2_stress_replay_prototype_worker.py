from __future__ import annotations

import json
from pathlib import Path

from app.services.strategy_v2_stress_replay_prototype_worker import (
    StrategyV2StressReplayPrototypeWorkerService,
)


def _write_batch(
    path: Path,
    *,
    symbol: str,
    version: str,
    scenario: str,
    rows: list[dict],
) -> None:
    payload = {
        "schema_version": "strategy_v2_stress_replay_lineage_batch_v1",
        "generated_at": "2026-03-08T10:00:00+00:00",
        "symbol": symbol,
        "version": version,
        "scenario": scenario,
        "batch_index": 1,
        "trade_count": len(rows),
        "trade_rows": rows,
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def test_stress_replay_prototype_worker_waits_for_dependencies(tmp_path: Path) -> None:
    service = StrategyV2StressReplayPrototypeWorkerService()
    service.settings.validation_report_dir = str(tmp_path)

    payload = service.generate(
        symbol="BTCUSDC",
        version="v2",
        stress_validation={"scenario_metrics": {}},
        stress_replay_lineage_writer={
            "available": False,
            "runtime_job_ready": False,
            "blocked_by": ["stress_replay_lineage_unavailable"],
            "next_steps": ["generate stress replay lineage before writing batches"],
        },
        stress_replay_runner_contract={
            "available": False,
            "runtime_job_ready": False,
            "blocked_by": ["stress_replay_runner_contract_unavailable"],
            "next_steps": ["define runner contract before executing worker"],
        },
        write_report=False,
    )

    assert payload["available"] is False
    assert payload["executed"] is False
    assert payload["runtime_job_ready"] is False
    assert payload["reason"] == "stress_replay_prototype_worker_not_ready"
    assert "stress_replay_worker_dependencies_unavailable" in payload["blocked_by"]


def test_stress_replay_prototype_worker_skips_rows_with_invalid_closed_ts() -> None:
    service = StrategyV2StressReplayPrototypeWorkerService()

    metrics = service._summary_metrics(
        replay_rows=[
            {
                "plan_id": "bad_ts",
                "closed_ts": "legacy-invalid-timestamp",
                "replayed_realized_r": 1.0,
                "final_exit_held_bars": 3,
                "final_exit_reason": "target_tp1",
                "strategy_family": "sweep_reversal",
                "strategy_grade": "A",
            }
        ],
        symbol="BTCUSDC",
        version="v2",
    )

    assert metrics["trades"] == 0


def test_stress_replay_prototype_worker_reads_batches_and_writes_outputs(tmp_path: Path) -> None:
    service = StrategyV2StressReplayPrototypeWorkerService()
    service.settings.validation_report_dir = str(tmp_path)

    latency_batch = tmp_path / "latency_batch.json"
    shock_batch = tmp_path / "shock_batch.json"
    partial_batch = tmp_path / "partial_batch.json"

    _write_batch(
        latency_batch,
        symbol="BTCUSDC",
        version="v2",
        scenario="latency_plus_1_bar",
        rows=[
            {
                "plan_id": "plan_latency_1",
                "closed_ts": "2026-03-08T10:00:00+00:00",
                "strategy_family": "trend_continuation",
                "strategy_grade": "A",
                "final_exit_realized_r": 1.2,
                "final_exit_reason": "target_tp2",
                "final_exit_held_bars": 4,
                "has_entry_fill": True,
                "has_close_fill": True,
                "has_partial_exit_fill": False,
                "latency_bar_exists": True,
                "full_fill_path": True,
                "complete_candle_path": True,
                "path_coverage_ratio": 1.0,
                "entry_anchor_source": "execution_entry_fill",
                "exit_anchor_source": "execution_closed_fill",
            },
            {
                "plan_id": "plan_latency_2",
                "closed_ts": "2026-03-08T10:05:00+00:00",
                "strategy_family": "sweep_reversal",
                "strategy_grade": "B",
                "final_exit_realized_r": -0.6,
                "final_exit_reason": "time_failure",
                "final_exit_held_bars": 6,
                "has_entry_fill": True,
                "has_close_fill": False,
                "has_partial_exit_fill": False,
                "latency_bar_exists": True,
                "full_fill_path": False,
                "complete_candle_path": True,
                "path_coverage_ratio": 0.9,
                "entry_anchor_source": "execution_entry_fill",
                "exit_anchor_source": "plan_final_exit_ts",
            },
        ],
    )
    _write_batch(
        shock_batch,
        symbol="BTCUSDC",
        version="v2",
        scenario="shock_concentration",
        rows=[
            {
                "plan_id": "plan_shock_1",
                "closed_ts": "2026-03-08T10:10:00+00:00",
                "strategy_family": "sweep_reversal",
                "strategy_grade": "A",
                "final_exit_realized_r": 0.8,
                "final_exit_reason": "target_tp1",
                "final_exit_held_bars": 3,
                "has_entry_fill": True,
                "has_close_fill": True,
                "has_partial_exit_fill": True,
                "latency_bar_exists": True,
                "full_fill_path": True,
                "complete_candle_path": True,
                "path_coverage_ratio": 0.95,
                "entry_anchor_source": "execution_entry_fill",
                "exit_anchor_source": "execution_closed_fill",
            }
        ],
    )
    _write_batch(
        partial_batch,
        symbol="BTCUSDC",
        version="v2",
        scenario="partial_fills_only",
        rows=[
            {
                "plan_id": "plan_partial_1",
                "closed_ts": "2026-03-08T10:15:00+00:00",
                "strategy_family": "trend_continuation",
                "strategy_grade": "B",
                "final_exit_realized_r": 0.5,
                "final_exit_reason": "target_tp1",
                "final_exit_held_bars": 5,
                "has_entry_fill": True,
                "has_close_fill": True,
                "has_partial_exit_fill": True,
                "latency_bar_exists": True,
                "full_fill_path": True,
                "complete_candle_path": False,
                "path_coverage_ratio": 0.85,
                "entry_anchor_source": "execution_entry_fill",
                "exit_anchor_source": "execution_closed_fill",
            }
        ],
    )

    payload = service.generate(
        symbol="BTCUSDC",
        version="v2",
        stress_validation={
            "scenario_metrics": {
                "latency_plus_1_bar": {"trades": 2, "ev": 0.10, "p5_ev": -0.40, "p50_ev": 0.05, "max_drawdown": 0.90, "ulcer_index": 0.30},
                "shock_concentration": {"trades": 1, "ev": 0.05, "p5_ev": -0.20, "p50_ev": 0.05, "max_drawdown": 0.60, "ulcer_index": 0.25},
                "partial_fills_only": {"trades": 1, "ev": 0.02, "p5_ev": -0.15, "p50_ev": 0.02, "max_drawdown": 0.40, "ulcer_index": 0.20},
            }
        },
        stress_replay_lineage_writer={
            "available": True,
            "runtime_job_ready": True,
            "schema_version": "strategy_v2_stress_replay_lineage_writer_v1",
            "scenario_batches": {
                "latency_plus_1_bar": {
                    "ready": True,
                    "gating_reason": "ready",
                    "batches": [{"artifact_path": str(latency_batch)}],
                },
                "shock_concentration": {
                    "ready": True,
                    "gating_reason": "ready",
                    "batches": [{"artifact_path": str(shock_batch)}],
                },
                "partial_fills_only": {
                    "ready": True,
                    "gating_reason": "ready",
                    "batches": [{"artifact_path": str(partial_batch)}],
                },
            },
            "blocked_by": [],
            "next_steps": ["run prototype worker to materialize output artifacts"],
        },
        stress_replay_runner_contract={
            "available": True,
            "runtime_job_ready": True,
            "schema_version": "strategy_v2_stress_replay_runner_contract_v1",
            "scenario_contract": {
                "latency_plus_1_bar": {"ready": True, "gating_reason": "ready"},
                "shock_concentration": {"ready": True, "gating_reason": "ready"},
                "partial_fills_only": {"ready": True, "gating_reason": "ready"},
            },
            "worker_input_contract": {"required_sources": ["lineage_batch_artifact"]},
            "worker_output_contract": {"summary_fields": ["ev", "max_drawdown"]},
            "blocked_by": [],
            "next_steps": ["review prototype replay outputs"],
        },
        write_report=True,
    )

    assert payload["available"] is True
    assert payload["executed"] is True
    assert payload["runtime_job_ready"] is True
    assert payload["reason"] == "stress_replay_prototype_worker_outputs_written"
    assert payload["sample_counts"]["executed_scenarios"] == 3
    assert payload["sample_counts"]["input_batches_read"] == 3
    assert payload["sample_counts"]["replay_trade_rows_written"] == 4
    assert Path(str(payload["report_path"])).exists()

    latency_run = payload["scenario_runs"]["latency_plus_1_bar"]
    assert latency_run["executed"] is True
    latency_output_path = Path(str(latency_run["output_artifact_path"]))
    assert latency_output_path.exists()
    latency_body = json.loads(latency_output_path.read_text(encoding="utf-8"))
    assert latency_body["schema_version"] == "strategy_v2_stress_replay_worker_output_v1"
    assert latency_body["scenario"] == "latency_plus_1_bar"
    assert latency_body["summary"]["trades"] == 2
    assert "coverage" in latency_body["summary"]
    assert "approximation_gap" in latency_body["summary"]
    assert latency_body["input_lineage_summary"]["input_batch_count"] == 1
    assert latency_body["input_lineage_summary"]["input_trade_rows"] == 2
    assert latency_body["input_lineage_summary"]["entry_anchor_sources"]["execution_entry_fill"] == 2


def test_stress_replay_prototype_worker_executes_prototype_ready_batches(tmp_path: Path) -> None:
    service = StrategyV2StressReplayPrototypeWorkerService()
    service.settings.validation_report_dir = str(tmp_path)

    latency_batch = tmp_path / "latency_batch.json"
    _write_batch(
        latency_batch,
        symbol="BTCUSDC",
        version="v2",
        scenario="latency_plus_1_bar",
        rows=[
            {
                "plan_id": "plan_latency_proto",
                "closed_ts": "2026-03-08T10:00:00+00:00",
                "strategy_family": "trend_continuation",
                "strategy_grade": "A",
                "final_exit_realized_r": 1.0,
                "final_exit_reason": "target_tp1",
                "final_exit_held_bars": 4,
                "has_entry_fill": True,
                "has_close_fill": True,
                "has_partial_exit_fill": False,
                "latency_bar_exists": True,
                "full_fill_path": False,
                "complete_candle_path": True,
                "path_coverage_ratio": 1.0,
                "entry_anchor_source": "execution_entry_fill",
                "exit_anchor_source": "execution_closed_fill",
            }
        ],
    )

    payload = service.generate(
        symbol="BTCUSDC",
        version="v2",
        stress_validation={
            "scenario_metrics": {
                "latency_plus_1_bar": {"trades": 1, "ev": 0.10, "p5_ev": -0.20, "p50_ev": 0.10, "max_drawdown": 0.40, "ulcer_index": 0.10},
            }
        },
        stress_replay_lineage_writer={
            "available": True,
            "runtime_job_ready": True,
            "schema_version": "strategy_v2_stress_replay_lineage_writer_v1",
            "scenario_batches": {
                "latency_plus_1_bar": {
                    "ready": False,
                    "prototype_ready": True,
                    "gating_reason": "latency_reference_coverage_below_contract",
                    "batches": [{"artifact_path": str(latency_batch)}],
                },
            },
            "blocked_by": ["full_replay_not_ready"],
            "next_steps": ["materialize prototype replay outputs for currently covered scenarios"],
        },
        stress_replay_runner_contract={
            "available": True,
            "runtime_job_ready": True,
            "schema_version": "strategy_v2_stress_replay_runner_contract_v1",
            "scenario_contract": {
                "latency_plus_1_bar": {
                    "ready": False,
                    "prototype_ready": True,
                    "gating_reason": "latency_reference_coverage_below_contract",
                },
            },
            "worker_input_contract": {"required_sources": ["lineage_batch_artifact"]},
            "worker_output_contract": {"summary_fields": ["ev", "max_drawdown"]},
            "blocked_by": ["full_replay_not_ready"],
            "next_steps": ["keep approximation live while replay-backed downside evidence accumulates"],
        },
        write_report=False,
    )

    assert payload["available"] is True
    assert payload["runtime_job_ready"] is True
    assert payload["executed"] is True
    assert payload["sample_counts"]["executed_scenarios"] == 1
    assert payload["sample_counts"]["ready_scenarios"] == 1
    assert payload["scenario_runs"]["latency_plus_1_bar"]["prototype_ready"] is True
    assert payload["scenario_runs"]["latency_plus_1_bar"]["ready"] is False
    assert payload["scenario_runs"]["latency_plus_1_bar"]["executed"] is True
