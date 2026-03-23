from __future__ import annotations

from pathlib import Path

from app.services.strategy_v2_pbo_dsr_design import StrategyV2PboDsrDesignService


def test_strategy_v2_pbo_dsr_design_generates_design_contract() -> None:
    service = StrategyV2PboDsrDesignService()

    payload = service.generate(symbol="BTCUSDC", version="v1", write_report=True)

    assert payload["schema_version"] == "strategy_v2_pbo_dsr_design_v1"
    assert payload["design_ready"] is True
    assert payload["available"] is False
    assert payload["implementation_status"] == "design_ready_not_computed"
    assert payload["reason"] == "pbo_dsr_contract_frozen_runtime_pending"
    assert payload["pbo"]["method"] == "CSCV"
    assert payload["dsr"]["method"] == "deflated_sharpe_ratio"
    assert "parameter sweep result store is not implemented" in payload["blocked_by"]
    assert "compute PBO from selected-vs-oos rank inversions" in payload["next_steps"]
    path = Path(payload["report_path"])
    assert path.exists()
    body = path.read_text(encoding="utf-8")
    assert "## PBO Design" in body
    assert "## DSR Design" in body
    assert "does not compute either metric yet" in body


def test_strategy_v2_pbo_dsr_design_reflects_artifact_store_state() -> None:
    service = StrategyV2PboDsrDesignService()

    payload = service.generate(
        symbol="BTCUSDC",
        version="v1",
        artifact_store={
            "artifact_store_ready": True,
            "available": True,
            "metrics_available": False,
            "implementation_status": "artifact_store_seeded_not_computed",
            "counts": {"trial_runs": 2, "fold_scores": 8, "snapshots": 1},
            "selection_rule_counts": {"runtime_validation_proxy_top_in_sample_ev": 2},
            "latest_snapshot": {"computation_state": "seeded_not_computed"},
        },
        write_report=False,
    )

    assert payload["design_ready"] is True
    assert payload["available"] is False
    assert payload["implementation_status"] == "design_ready_artifact_store_seeded_not_computed"
    assert payload["reason"] == "pbo_dsr_artifact_store_seeded_metrics_pending"
    assert payload["artifact_store"]["artifact_store_ready"] is True
    assert payload["artifact_store"]["counts"]["trial_runs"] == 2


def test_strategy_v2_pbo_dsr_design_reflects_dual_lineage_seeded_state() -> None:
    service = StrategyV2PboDsrDesignService()

    payload = service.generate(
        symbol="BTCUSDC",
        version="v1",
        artifact_store={
            "artifact_store_ready": True,
            "available": True,
            "metrics_available": False,
            "implementation_status": "artifact_store_seeded_not_computed",
            "counts": {"trial_runs": 9, "fold_scores": 27, "snapshots": 0},
            "selection_rule_counts": {
                "runtime_validation_proxy_top_in_sample_ev": 5,
                "true_threshold_sweep_top_in_sample_ev": 4,
            },
            "latest_snapshot": {},
        },
        write_report=False,
    )

    assert payload["available"] is False
    assert payload["implementation_status"] == "design_ready_dual_lineage_seeded_metrics_pending"
    assert payload["reason"] == "pbo_dsr_dual_lineage_seeded_metrics_pending"
    assert payload["artifact_store"]["selection_rule_counts"]["true_threshold_sweep_top_in_sample_ev"] == 4
    assert "audit selected-trial source between runtime proxy and true threshold runner lineages" in payload["next_steps"]


def test_strategy_v2_pbo_dsr_design_marks_available_when_metrics_exist() -> None:
    service = StrategyV2PboDsrDesignService()

    payload = service.generate(
        symbol="BTCUSDC",
        version="v1",
        artifact_store={
            "artifact_store_ready": True,
            "available": True,
            "metrics_available": True,
            "implementation_status": "artifact_store_metrics_available",
            "counts": {"trial_runs": 3, "fold_scores": 9, "snapshots": 2},
            "latest_snapshot": {"computation_state": "metrics_computed", "pbo_available": True, "dsr_available": True},
        },
        write_report=False,
    )

    assert payload["available"] is True
    assert payload["implementation_status"] == "design_ready_metrics_available_runtime"
    assert payload["reason"] == "pbo_dsr_runtime_metrics_available"
