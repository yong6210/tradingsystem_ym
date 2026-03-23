from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.services.strategy_v2_stress_replay_output_artifacts import StrategyV2StressReplayOutputArtifactsService
from app.services.strategy_v2_stress_validation import StrategyV2StressValidationService


def test_stress_replay_output_artifacts_reports_missing_artifacts(tmp_path: Path) -> None:
    service = StrategyV2StressReplayOutputArtifactsService()
    service.settings.validation_report_dir = str(tmp_path)

    payload = service.generate(
        symbol="BTCUSDC",
        version="v2",
        stress_validation={
            "scenario_metrics": {
                "latency_plus_1_bar": {"trades": 4, "ev": -0.1, "p5_ev": -0.6, "max_drawdown": 1.2, "ulcer_index": 0.4},
                "partial_fills_only": {"trades": 4, "ev": 0.0, "p5_ev": -0.4, "max_drawdown": 1.0, "ulcer_index": 0.3},
                "shock_concentration": {"trades": 4, "ev": -0.2, "p5_ev": -0.8, "max_drawdown": 1.5, "ulcer_index": 0.5},
            }
        },
        write_report=False,
    )

    assert payload["available"] is False
    assert payload["comparison_ready"] is False
    assert payload["reason"] == "no_replay_worker_output_artifacts"
    assert "stress_replay_worker_output_artifacts_missing" in payload["blocked_by"]


def test_stress_replay_output_artifacts_loads_latest_scenario_outputs(tmp_path: Path) -> None:
    service = StrategyV2StressReplayOutputArtifactsService()
    service.settings.validation_report_dir = str(tmp_path)
    out_dir = tmp_path / "stress_replay_worker_outputs" / "BTCUSDC" / "v2"
    out_dir.mkdir(parents=True, exist_ok=True)

    old_payload = {
        "schema_version": "strategy_v2_stress_replay_worker_output_v1",
        "generated_at": "2026-03-08T00:00:00+00:00",
        "symbol": "BTCUSDC",
        "version": "v2",
        "scenario": "latency_plus_1_bar",
        "summary": {
            "trades": 5,
            "ev": -0.12,
            "p5_ev": -0.70,
            "p50_ev": -0.08,
            "max_drawdown": 1.90,
            "ulcer_index": 0.62,
        },
    }
    latest_payload = {
        "schema_version": "strategy_v2_stress_replay_worker_output_v1",
        "generated_at": "2026-03-08T02:00:00+00:00",
        "symbol": "BTCUSDC",
        "version": "v2",
        "scenario": "latency_plus_1_bar",
        "worker_mode": "prototype_from_lineage_batches",
        "input_lineage_summary": {
            "input_schema_version": "strategy_v2_stress_replay_lineage_batch_v1",
            "input_batch_count": 1,
            "input_trade_rows": 6,
            "entry_anchor_sources": {"execution_entry_fill": 6},
            "exit_anchor_sources": {"execution_closed_fill": 5, "plan_final_exit_ts": 1},
            "regime_counts": {"trend": 6},
        },
        "summary": {
            "trades": 6,
            "ev": -0.18,
            "p5_ev": -0.82,
            "p50_ev": -0.09,
            "max_drawdown": 2.15,
            "ulcer_index": 0.73,
            "coverage": {"execution_fill_coverage": 0.84},
            "approximation_gap": {"ev": -0.06, "max_drawdown": 0.35},
        },
    }
    shock_payload = {
        "schema_version": "strategy_v2_stress_replay_worker_output_v1",
        "generated_at": "2026-03-08T01:00:00+00:00",
        "symbol": "BTCUSDC",
        "version": "v2",
        "scenario": "shock_concentration",
        "worker_mode": "prototype_from_lineage_batches",
        "input_lineage_summary": {
            "input_schema_version": "strategy_v2_stress_replay_lineage_batch_v1",
            "input_batch_count": 1,
            "input_trade_rows": 4,
            "entry_anchor_sources": {"execution_entry_fill": 3, "plan_valid_from": 1},
            "exit_anchor_sources": {"execution_closed_fill": 4},
            "regime_counts": {"shock": 4},
        },
        "summary": {
            "trades": 4,
            "ev": -0.22,
            "p5_ev": -0.90,
            "p50_ev": -0.11,
            "max_drawdown": 2.40,
            "ulcer_index": 0.80,
        },
    }
    (out_dir / "latency_plus_1_bar_20260308T000000Z.json").write_text(json.dumps(old_payload), encoding="utf-8")
    (out_dir / "latency_plus_1_bar_20260308T020000Z.json").write_text(json.dumps(latest_payload), encoding="utf-8")
    (out_dir / "shock_concentration_20260308T010000Z.json").write_text(json.dumps(shock_payload), encoding="utf-8")

    payload = service.generate(
        symbol="BTCUSDC",
        version="v2",
        stress_validation={
            "scenario_metrics": {
                "latency_plus_1_bar": {"trades": 6, "ev": -0.10, "p5_ev": -0.70, "p50_ev": -0.05, "max_drawdown": 1.80, "ulcer_index": 0.55},
                "partial_fills_only": {"trades": 6, "ev": 0.01, "p5_ev": -0.40, "p50_ev": 0.00, "max_drawdown": 1.20, "ulcer_index": 0.33},
                "shock_concentration": {"trades": 4, "ev": -0.14, "p5_ev": -0.72, "p50_ev": -0.06, "max_drawdown": 1.95, "ulcer_index": 0.60},
            }
        },
        write_report=True,
    )

    assert payload["available"] is True
    assert payload["comparison_ready"] is True
    assert payload["summary_counts"]["scenarios_with_artifacts"] == 2
    assert payload["summary_counts"]["scenarios_compared"] == 2
    assert payload["lineage_summary"]["input_batch_count"] == 2
    assert payload["lineage_summary"]["input_trade_rows"] == 10
    assert payload["lineage_summary"]["worker_modes"] == ["prototype_from_lineage_batches"]
    assert payload["lineage_summary"]["compared_scenarios"] == ["shock_concentration", "latency_plus_1_bar"]
    latency_row = payload["scenario_outputs"]["latency_plus_1_bar"]
    assert latency_row["available"] is True
    assert latency_row["summary"]["ev"] == -0.18
    assert latency_row["comparison_to_approximation"]["ev"] == -0.08
    assert latency_row["input_lineage_summary"]["input_trade_rows"] == 6
    assert "stress_replay_worker_output_artifacts_partial" in payload["blocked_by"]
    report_path = Path(str(payload["report_path"]))
    assert report_path.exists()
    assert "Stress Replay Output Artifacts" in report_path.read_text(encoding="utf-8")


def test_stress_validation_attach_replay_output_artifacts() -> None:
    service = StrategyV2StressValidationService()
    base_payload = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "scenario_metrics": {
            "latency_plus_1_bar": {"trades": 6, "ev": -0.10, "p5_ev": -0.70, "max_drawdown": 1.80, "ulcer_index": 0.55},
        },
        "scenario_comparison": {},
        "deployment_recommendation": {},
        "sample_counts": {},
        "cost_source_counts": {},
        "latency_source_counts": {},
        "cost_summary": {},
        "scenario_summary": {},
        "stress_metrics": {},
        "comparison": {},
        "schema_version": "strategy_v2_stress_validation_v2",
        "symbol": "BTCUSDC",
        "version": "v2",
        "available": True,
        "reason": "ok",
        "comparison_axis": "baseline_vs_stressed_cost",
        "stress_multipliers": {"cost": 1.5, "slippage": 2.0},
        "report_path": None,
    }
    enriched = service.attach_replay_output_artifacts(
        payload=base_payload,
        stress_replay_output_artifacts={
            "available": True,
            "comparison_ready": True,
            "reason": "replay_worker_output_artifacts_loaded",
            "summary_counts": {"scenarios_compared": 1},
            "lineage_summary": {
                "available": True,
                "worker_modes": ["prototype_from_lineage_batches"],
                "compared_scenarios": ["latency_plus_1_bar"],
                "input_batch_count": 1,
                "input_trade_rows": 1,
            },
            "scenario_outputs": {
                "latency_plus_1_bar": {
                    "available": True,
                    "reason": "artifact_loaded",
                    "summary": {"ev": -0.15, "max_drawdown": 2.1},
                    "comparison_to_approximation": {"ev": -0.05, "max_drawdown": 0.3},
                    "input_lineage_summary": {"input_trade_rows": 1},
                }
            },
            "comparison_to_approximation": {
                "latency_plus_1_bar": {"ev": -0.05, "max_drawdown": 0.3},
            },
            "report_path": None,
        },
        write_report=False,
    )

    assert enriched["replay_output_artifacts"]["available"] is True
    assert enriched["replay_output_artifacts"]["summary_counts"]["scenarios_compared"] == 1
    assert enriched["replay_output_artifacts"]["lineage_summary"]["input_trade_rows"] == 1
    assert enriched["replay_output_comparison"]["latency_plus_1_bar"]["ev"] == -0.05
