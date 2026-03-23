from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.db.models import ValidationPboDsrSnapshot, ValidationTrialFoldScore, ValidationTrialRun
from app.db.session import SessionLocal, init_db
from app.db.repositories import ValidationArtifactRepository
from app.services.strategy_v2_pbo_dsr_artifact_store import StrategyV2PboDsrArtifactStoreService


def test_strategy_v2_pbo_dsr_artifact_store_reports_empty_schema_ready() -> None:
    init_db()
    symbol = f"PBODSR{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"

    with SessionLocal() as db:
        service = StrategyV2PboDsrArtifactStoreService(repo=ValidationArtifactRepository(db))
        payload = service.generate(symbol=symbol, version="v1", write_report=True)

        assert payload["schema_version"] == "strategy_v2_pbo_dsr_artifact_store_v1"
        assert payload["artifact_store_ready"] is True
        assert payload["available"] is False
        assert payload["metrics_available"] is False
        assert payload["implementation_status"] == "artifact_store_schema_ready_empty"
        assert payload["reason"] == "artifact_store_tables_ready_not_populated"
        assert payload["counts"] == {"trial_runs": 0, "fold_scores": 0, "snapshots": 0}
        assert payload["selection_rule_counts"] == {}
        assert payload["selection_universe_summary"]["combined_artifact_selection_universe_size"] == 0
        assert payload["selection_universe_summary"]["full_parameter_sweep_selection_universe_size"] is None
        path = Path(payload["report_path"])
        assert path.exists()
        body = path.read_text(encoding="utf-8")
        assert "## Counts" in body
        assert "artifact_store_schema_ready_empty" in body


def test_strategy_v2_pbo_dsr_artifact_store_reports_seeded_not_computed() -> None:
    init_db()
    symbol = f"PBODSR{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 1}USDC"

    with SessionLocal() as db:
        repo = ValidationArtifactRepository(db)
        repo.upsert_trial_run(
            ValidationTrialRun(
                trial_run_id=f"{symbol}_trial_1",
                symbol=symbol,
                strategy_version="v1",
                parameter_family="transition_threshold",
                parameter_values={"transition_watch_score": 40.0},
                selection_rule="top_ev",
                selected_flag=True,
                selection_rank=1,
                in_sample_metric=0.24,
                out_of_sample_metric=0.18,
                sharpe_like_score=1.1,
                trial_count=16,
                selection_universe_size=16,
                payload={"source": "test"},
            )
        )
        repo.add_fold_score(
            ValidationTrialFoldScore(
                trial_run_id=f"{symbol}_trial_1",
                symbol=symbol,
                strategy_version="v1",
                fold_id="fold_01",
                selected_flag=True,
                selection_rank=1,
                in_sample_metric=0.28,
                out_of_sample_metric=0.17,
                payload={"source": "test"},
            )
        )
        repo.upsert_snapshot(
            ValidationPboDsrSnapshot(
                snapshot_id=f"{symbol}_snapshot_1",
                symbol=symbol,
                strategy_version="v1",
                selected_trial_run_id=f"{symbol}_trial_1",
                trial_run_count=1,
                fold_score_count=1,
                selection_universe_size=16,
                pbo_available=False,
                dsr_available=False,
                computation_state="seeded_not_computed",
                payload={"source": "test"},
            )
        )
        db.commit()

        service = StrategyV2PboDsrArtifactStoreService(repo=repo)
        payload = service.generate(symbol=symbol, version="v1", write_report=False)

        assert payload["artifact_store_ready"] is True
        assert payload["available"] is True
        assert payload["metrics_available"] is False
        assert payload["implementation_status"] == "artifact_store_seeded_not_computed"
        assert payload["reason"] == "artifact_store_seeded_metrics_pending"
        assert payload["counts"] == {"trial_runs": 1, "fold_scores": 1, "snapshots": 1}
        assert payload["parameter_families_present"] == ["transition_threshold"]
        assert payload["selection_rule_counts"] == {"top_ev": 1}
        assert payload["selection_universe_sizes"] == [16]
        assert payload["selection_universe_summary"]["combined_artifact_selection_universe_size"] == 1
        assert payload["selection_universe_summary"]["true_threshold_selection_universe_size"] == 0
        assert payload["selection_universe_summary"]["snapshot_dsr_selection_universe_size"] == 16
        assert payload["latest_snapshot"]["computation_state"] == "seeded_not_computed"
        assert "compute PBO from selected-vs-oos rank inversions" in payload["next_steps"]
