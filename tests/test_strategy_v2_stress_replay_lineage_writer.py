from __future__ import annotations

import json
from pathlib import Path

from app.services.strategy_v2_stress_replay_lineage_writer import StrategyV2StressReplayLineageWriterService


def test_stress_replay_lineage_writer_waits_for_runtime_job_ready(tmp_path: Path) -> None:
    service = StrategyV2StressReplayLineageWriterService()
    service.settings.validation_report_dir = str(tmp_path)
    payload = service.generate(
        symbol="BTCUSDC",
        version="v2",
        stress_replay_lineage={
            "available": True,
            "sample_counts": {"eligible_closed_trades": 12},
            "blocked_by": ["execution_fill_coverage_below_threshold"],
            "next_steps": ["increase execution fill coverage"],
        },
        stress_replay_runner_contract={
            "available": True,
            "runtime_job_ready": False,
            "blocked_by": ["execution_fill_coverage_below_threshold"],
            "next_steps": ["close runtime lineage gaps before creating replay batches"],
        },
        trade_rows=[],
        write_report=False,
    )

    assert payload["available"] is True
    assert payload["artifacts_written"] is False
    assert payload["implementation_status"] == "lineage_writer_waiting_for_runtime_job_ready"
    assert "execution_fill_coverage_below_threshold" in payload["blocked_by"]


def test_stress_replay_lineage_writer_materializes_scenario_batches(tmp_path: Path) -> None:
    service = StrategyV2StressReplayLineageWriterService()
    service.settings.validation_report_dir = str(tmp_path)
    payload = service.generate(
        symbol="BTCUSDC",
        version="v2",
        stress_replay_lineage={
            "available": True,
            "sample_counts": {"eligible_closed_trades": 3},
            "lineage_contract": {
                "required_fill_stages": ["ENTRY", "CLOSED"],
                "required_candle_nodes": ["entry_bar", "latency_plus_1_bar", "exit_bar"],
            },
            "blocked_by": [],
            "next_steps": ["runtime lineage is ready enough to prototype replay runner inputs"],
        },
        stress_replay_runner_contract={
            "available": True,
            "runtime_job_ready": True,
            "scenario_contract": {
                "shock_concentration": {"ready": True, "gating_reason": "ready"},
                "latency_plus_1_bar": {"ready": True, "gating_reason": "ready"},
                "partial_fills_only": {"ready": True, "gating_reason": "ready"},
            },
            "runner_contract": {
                "batching": {
                    "target_trades_per_job": 2,
                }
            },
            "blocked_by": [],
            "next_steps": ["implement prototype worker that writes replay trade rows and scenario summaries"],
        },
        trade_rows=[
            {
                "plan_id": "plan_a",
                "closed_ts": "2026-03-08T10:00:00+00:00",
                "entry_anchor_ts": "2026-03-08T09:40:00+00:00",
                "exit_anchor_ts": "2026-03-08T10:00:00+00:00",
                "entry_anchor_source": "execution_entry_fill",
                "exit_anchor_source": "execution_closed_fill",
                "final_exit_realized_r": 1.2,
                "final_exit_reason": "target_tp1",
                "path_coverage_ratio": 1.0,
                "regime": "shock",
                "latency_bar_exists": True,
                "full_fill_path": True,
            },
            {
                "plan_id": "plan_b",
                "closed_ts": "2026-03-08T10:05:00+00:00",
                "entry_anchor_ts": "2026-03-08T09:45:00+00:00",
                "exit_anchor_ts": "2026-03-08T10:05:00+00:00",
                "entry_anchor_source": "execution_entry_fill",
                "exit_anchor_source": "plan_final_exit_ts",
                "final_exit_realized_r": -0.8,
                "final_exit_reason": "time_failure",
                "path_coverage_ratio": 0.9,
                "regime": "shock",
                "latency_bar_exists": True,
                "full_fill_path": False,
            },
            {
                "plan_id": "plan_c",
                "closed_ts": "2026-03-08T10:10:00+00:00",
                "entry_anchor_ts": "2026-03-08T09:50:00+00:00",
                "exit_anchor_ts": "2026-03-08T10:10:00+00:00",
                "entry_anchor_source": "plan_valid_from",
                "exit_anchor_source": "plan_final_exit_ts",
                "final_exit_realized_r": 0.4,
                "final_exit_reason": "target_tp2",
                "path_coverage_ratio": 0.85,
                "regime": "trend",
                "latency_bar_exists": True,
                "full_fill_path": True,
            },
        ],
        write_report=True,
    )

    assert payload["artifacts_written"] is True
    assert payload["sample_counts"]["batches_written"] == 4
    assert payload["scenario_batches"]["shock_concentration"]["candidate_trades"] == 2
    first_batch = payload["scenario_batches"]["shock_concentration"]["batches"][0]
    artifact_path = Path(first_batch["artifact_path"])
    assert artifact_path.exists()
    body = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert body["schema_version"] == "strategy_v2_stress_replay_lineage_batch_v1"
    assert body["scenario"] == "shock_concentration"
    assert body["trade_rows"][0]["plan_id"] == "plan_a"


def test_stress_replay_lineage_writer_materializes_prototype_ready_batches(tmp_path: Path) -> None:
    service = StrategyV2StressReplayLineageWriterService()
    service.settings.validation_report_dir = str(tmp_path)
    payload = service.generate(
        symbol="BTCUSDC",
        version="v2",
        stress_replay_lineage={
            "available": True,
            "sample_counts": {"eligible_closed_trades": 1},
            "lineage_contract": {},
            "blocked_by": [],
            "next_steps": [],
        },
        stress_replay_runner_contract={
            "available": True,
            "runtime_job_ready": True,
            "scenario_contract": {
                "shock_concentration": {"ready": False, "prototype_ready": True, "gating_reason": "shock_sample_or_candle_path_below_contract"},
                "latency_plus_1_bar": {"ready": False, "prototype_ready": True, "gating_reason": "latency_reference_coverage_below_contract"},
                "partial_fills_only": {"ready": False, "prototype_ready": False, "gating_reason": "execution_fill_path_below_contract"},
            },
            "runner_contract": {"batching": {"target_trades_per_job": 2}},
            "blocked_by": ["full_replay_not_ready"],
            "next_steps": ["materialize prototype replay outputs for currently covered scenarios"],
        },
        trade_rows=[
            {
                "plan_id": "plan_proto",
                "closed_ts": "2026-03-08T10:00:00+00:00",
                "entry_anchor_ts": "2026-03-08T09:40:00+00:00",
                "exit_anchor_ts": "2026-03-08T10:00:00+00:00",
                "entry_anchor_source": "execution_entry_fill",
                "exit_anchor_source": "execution_closed_fill",
                "final_exit_realized_r": 1.2,
                "final_exit_reason": "target_tp1",
                "path_coverage_ratio": 1.0,
                "regime": "shock",
                "latency_bar_exists": True,
                "full_fill_path": False,
            },
        ],
        write_report=False,
    )

    assert payload["artifacts_written"] is True
    assert payload["implementation_status"] == "lineage_writer_seeded_prototype_batches"
    assert payload["reason"] == "stress_replay_lineage_prototype_batches_written"
    assert payload["scenario_batches"]["shock_concentration"]["prototype_ready"] is True
    assert payload["scenario_batches"]["shock_concentration"]["ready"] is False
    assert len(payload["scenario_batches"]["shock_concentration"]["batches"]) == 1
