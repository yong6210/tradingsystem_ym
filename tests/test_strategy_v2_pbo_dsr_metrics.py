from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.db.models import ValidationTrialFoldScore, ValidationTrialRun
from app.db.repositories import ValidationArtifactRepository
from app.db.session import SessionLocal, init_db
from app.services.strategy_v2_pbo_dsr_artifact_store import StrategyV2PboDsrArtifactStoreService
from app.services.strategy_v2_pbo_dsr_metrics import StrategyV2PboDsrMetricsService


def _seed_trial(
    repo: ValidationArtifactRepository,
    *,
    symbol: str,
    trial_suffix: str,
    selection_rule: str,
    selected_flag: bool,
    selection_rank: int,
    out_of_sample_metric: float,
    sharpe_like_score: float,
    writer_source: str,
) -> str:
    trial_run_id = f"{symbol}_{trial_suffix}"
    repo.upsert_trial_run(
        ValidationTrialRun(
            trial_run_id=trial_run_id,
            symbol=symbol,
            strategy_version="v1",
            parameter_family="transition_threshold",
            parameter_values={"transition_watch_score": 40.0 + (selection_rank * 5.0)},
            selection_rule=selection_rule,
            selected_flag=selected_flag,
            selection_rank=selection_rank,
            in_sample_metric=round(out_of_sample_metric + 0.08, 4),
            out_of_sample_metric=out_of_sample_metric,
            sharpe_like_score=sharpe_like_score,
            trial_count=18,
            selection_universe_size=3,
            payload={
                "return_skewness": 0.1,
                "return_kurtosis": 3.0,
                "writer_source": writer_source,
                "lineage_namespace": writer_source,
            },
        )
    )
    return trial_run_id


def _seed_fold_scores(
    repo: ValidationArtifactRepository,
    *,
    symbol: str,
    selected_trial_run_id: str,
    second_trial_run_id: str,
    third_trial_run_id: str,
) -> None:
    fold_rows = [
        ("fold_01", selected_trial_run_id, True, 1, 0.41, 0.30),
        ("fold_01", second_trial_run_id, False, 2, 0.35, 0.22),
        ("fold_01", third_trial_run_id, False, 3, 0.24, 0.15),
        ("fold_02", selected_trial_run_id, True, 1, 0.39, 0.28),
        ("fold_02", second_trial_run_id, False, 2, 0.32, 0.20),
        ("fold_02", third_trial_run_id, False, 3, 0.21, 0.11),
        ("fold_03", selected_trial_run_id, True, 1, 0.37, 0.24),
        ("fold_03", second_trial_run_id, False, 2, 0.42, 0.32),
        ("fold_03", third_trial_run_id, False, 3, 0.19, 0.12),
    ]
    for fold_id, trial_run_id, selected_flag, selection_rank, in_sample, out_of_sample in fold_rows:
        repo.add_fold_score(
            ValidationTrialFoldScore(
                trial_run_id=trial_run_id,
                symbol=symbol,
                strategy_version="v1",
                fold_id=fold_id,
                selected_flag=selected_flag,
                selection_rank=selection_rank,
                in_sample_metric=in_sample,
                out_of_sample_metric=out_of_sample,
                payload={"source": "test"},
            )
        )


def test_strategy_v2_pbo_dsr_metrics_reports_unavailable_when_store_is_empty() -> None:
    init_db()
    symbol = f"PBOEMPTY{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"

    with SessionLocal() as db:
        repo = ValidationArtifactRepository(db)
        service = StrategyV2PboDsrMetricsService(repo=repo)

        payload = service.generate(symbol=symbol, version="v1", write_report=True, persist_snapshot=True)

        assert payload["schema_version"] == "strategy_v2_pbo_dsr_metrics_v1"
        assert payload["available"] is False
        assert payload["metrics_complete"] is False
        assert payload["reason"] == "pbo_dsr_trial_runs_missing"
        assert "validation_trial_runs is empty" in payload["blocked_by"]
        path = Path(payload["report_path"])
        assert path.exists()
        body = path.read_text(encoding="utf-8")
        assert "## PBO" in body
        assert "## DSR" in body


def test_strategy_v2_pbo_dsr_metrics_computes_and_persists_snapshot() -> None:
    init_db()
    symbol = f"PBOREADY{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 1}USDC"

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
                in_sample_metric=0.42,
                out_of_sample_metric=0.31,
                sharpe_like_score=1.65,
                trial_count=18,
                selection_universe_size=3,
                payload={
                    "return_skewness": 0.1,
                    "return_kurtosis": 3.0,
                    "writer_source": "true_threshold_sweep_runner_v1",
                    "lineage_namespace": "true_threshold_sweep_runner_v1",
                },
            )
        )
        repo.upsert_trial_run(
            ValidationTrialRun(
                trial_run_id=f"{symbol}_trial_2",
                symbol=symbol,
                strategy_version="v1",
                parameter_family="transition_threshold",
                parameter_values={"transition_watch_score": 45.0},
                selection_rule="top_ev",
                selected_flag=False,
                selection_rank=2,
                in_sample_metric=0.38,
                out_of_sample_metric=0.27,
                sharpe_like_score=1.1,
                trial_count=18,
                selection_universe_size=3,
                payload={},
            )
        )
        repo.upsert_trial_run(
            ValidationTrialRun(
                trial_run_id=f"{symbol}_trial_3",
                symbol=symbol,
                strategy_version="v1",
                parameter_family="transition_threshold",
                parameter_values={"transition_watch_score": 50.0},
                selection_rule="top_ev",
                selected_flag=False,
                selection_rank=3,
                in_sample_metric=0.21,
                out_of_sample_metric=0.15,
                sharpe_like_score=0.5,
                trial_count=18,
                selection_universe_size=3,
                payload={},
            )
        )

        fold_rows = [
            ("fold_01", True, 1, 0.44, 0.12, f"{symbol}_trial_1"),
            ("fold_01", False, 2, 0.33, 0.28, f"{symbol}_trial_2"),
            ("fold_01", False, 3, 0.25, 0.19, f"{symbol}_trial_3"),
            ("fold_02", True, 1, 0.41, 0.10, f"{symbol}_trial_1"),
            ("fold_02", False, 2, 0.29, 0.18, f"{symbol}_trial_2"),
            ("fold_02", False, 3, 0.19, 0.13, f"{symbol}_trial_3"),
            ("fold_03", True, 1, 0.39, 0.26, f"{symbol}_trial_1"),
            ("fold_03", False, 2, 0.28, 0.21, f"{symbol}_trial_2"),
            ("fold_03", False, 3, 0.17, 0.14, f"{symbol}_trial_3"),
        ]
        for fold_id, selected_flag, selection_rank, in_sample, out_of_sample, trial_run_id in fold_rows:
            repo.add_fold_score(
                ValidationTrialFoldScore(
                    trial_run_id=trial_run_id,
                    symbol=symbol,
                    strategy_version="v1",
                    fold_id=fold_id,
                    selected_flag=selected_flag,
                    selection_rank=selection_rank,
                    in_sample_metric=in_sample,
                    out_of_sample_metric=out_of_sample,
                    payload={"source": "test"},
                )
            )

        service = StrategyV2PboDsrMetricsService(repo=repo)
        payload = service.generate(symbol=symbol, version="v1", write_report=False, persist_snapshot=True)
        db.commit()

        assert payload["available"] is True
        assert payload["metrics_complete"] is True
        assert payload["reason"] == "pbo_dsr_metrics_computed"
        assert payload["pbo"]["available"] is True
        assert payload["pbo"]["status"] == "FAIL"
        assert payload["pbo"]["overfit_folds"] == 2
        assert payload["pbo"]["eligible_folds"] == 3
        assert payload["dsr"]["available"] is True
        assert payload["dsr"]["status"] in {"PASS", "FAIL"}
        assert payload["selection_rule_counts"] == {"top_ev": 3}
        assert payload["selection_universe_summary"]["combined_artifact_selection_universe_size"] == 3
        assert payload["selection_universe_summary"]["true_threshold_selection_universe_size"] == 0
        assert payload["selection_universe_summary"]["full_parameter_sweep_selection_universe_size"] is None
        assert payload["selection_universe_summary"]["dsr_selection_universe_basis"] == "combined_artifact_universe"
        assert payload["selection_universe_summary"]["bias_adjustment_rechecked"] is False
        assert payload["selected_trial"]["writer_source"] == "true_threshold_sweep_runner_v1"
        assert payload["lineage_audit"]["audit_status"] == "PASS"
        assert payload["lineage_audit"]["reason"] == "legacy_or_unclassified_selection_rules_only"
        assert payload["dsr"]["selection_universe_basis"] == "combined_artifact_universe"
        assert payload["dsr"]["legacy_combined_selection_universe_size"] == 3
        assert payload["dsr"]["bias_adjustment_rechecked"] is False
        assert payload["snapshot_summary"]["pbo_available"] is True
        assert payload["snapshot_summary"]["dsr_available"] is True

        artifact_store = StrategyV2PboDsrArtifactStoreService(repo=repo)
        artifact_payload = artifact_store.generate(symbol=symbol, version="v1", write_report=False)
        assert artifact_payload["metrics_available"] is True
        assert artifact_payload["latest_snapshot"]["pbo_available"] is True
        assert artifact_payload["latest_snapshot"]["dsr_available"] is True
        assert artifact_payload["selection_universe_summary"]["combined_artifact_selection_universe_size"] == 3


def test_strategy_v2_pbo_dsr_metrics_warns_when_proxy_selected_with_true_threshold_lineage_present() -> None:
    init_db()
    symbol = f"PBOLINEAGEWARN{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 2}USDC"

    with SessionLocal() as db:
        repo = ValidationArtifactRepository(db)
        selected_trial_run_id = _seed_trial(
            repo,
            symbol=symbol,
            trial_suffix="trial_proxy",
            selection_rule="runtime_validation_proxy_top_in_sample_ev",
            selected_flag=True,
            selection_rank=1,
            out_of_sample_metric=0.30,
            sharpe_like_score=1.7,
            writer_source="runtime_validation_proxy_v1",
        )
        second_trial_run_id = _seed_trial(
            repo,
            symbol=symbol,
            trial_suffix="trial_threshold_1",
            selection_rule="true_threshold_sweep_top_in_sample_ev",
            selected_flag=False,
            selection_rank=2,
            out_of_sample_metric=0.22,
            sharpe_like_score=1.1,
            writer_source="true_threshold_sweep_runner_v1",
        )
        third_trial_run_id = _seed_trial(
            repo,
            symbol=symbol,
            trial_suffix="trial_threshold_2",
            selection_rule="true_threshold_sweep_top_in_sample_ev",
            selected_flag=False,
            selection_rank=3,
            out_of_sample_metric=0.15,
            sharpe_like_score=0.6,
            writer_source="true_threshold_sweep_runner_v1",
        )
        _seed_fold_scores(
            repo,
            symbol=symbol,
            selected_trial_run_id=selected_trial_run_id,
            second_trial_run_id=second_trial_run_id,
            third_trial_run_id=third_trial_run_id,
        )

        service = StrategyV2PboDsrMetricsService(repo=repo)
        payload = service.generate(symbol=symbol, version="v1", write_report=False, persist_snapshot=False)

        assert payload["metrics_complete"] is True
        assert payload["selection_rule_counts"] == {
            "runtime_validation_proxy_top_in_sample_ev": 1,
            "true_threshold_sweep_top_in_sample_ev": 2,
        }
        assert payload["selection_universe_summary"]["combined_artifact_selection_universe_size"] == 3
        assert payload["selection_universe_summary"]["runtime_proxy_selection_universe_size"] == 1
        assert payload["selection_universe_summary"]["true_threshold_selection_universe_size"] == 2
        assert payload["selection_universe_summary"]["full_parameter_sweep_selection_universe_size"] == 2
        assert payload["selection_universe_summary"]["dsr_selection_universe_size"] == 2
        assert payload["selection_universe_summary"]["dsr_selection_universe_basis"] == "full_parameter_sweep_universe"
        assert payload["selection_universe_summary"]["bias_adjustment_rechecked"] is True
        assert payload["dsr"]["selection_universe_basis"] == "full_parameter_sweep_universe"
        assert payload["dsr"]["selection_universe_size"] == 2
        assert payload["dsr"]["legacy_combined_selection_universe_size"] == 3
        assert payload["dsr"]["bias_adjustment_rechecked"] is True
        assert payload["dsr"]["benchmark_sharpe_delta_vs_legacy_combined"] < 0.0
        assert payload["lineage_audit"]["audit_status"] == "WARN"
        assert payload["lineage_audit"]["lineage_mix_state"] == "dual_lineage"
        assert payload["lineage_audit"]["selected_trial_from_runtime_proxy"] is True
        assert payload["lineage_audit"]["selected_trial_from_true_threshold"] is False
        assert payload["deployment_recommendation"]["decision"] == "warn_lineage_audit"
        assert payload["deployment_recommendation"]["lineage_audit_applied"] is True
        assert (
            payload["deployment_recommendation"]["lineage_audit_reason"]
            == "selected_trial_from_runtime_proxy_while_true_threshold_lineage_exists"
        )
        assert "audit proxy lineage vs true threshold lineage before deployment approval" in payload["next_steps"]


def test_strategy_v2_pbo_dsr_metrics_passes_lineage_audit_when_true_threshold_selected_in_dual_lineage() -> None:
    init_db()
    symbol = f"PBOLINEAGEPASS{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 3}USDC"

    with SessionLocal() as db:
        repo = ValidationArtifactRepository(db)
        selected_trial_run_id = _seed_trial(
            repo,
            symbol=symbol,
            trial_suffix="trial_threshold_selected",
            selection_rule="true_threshold_sweep_top_in_sample_ev",
            selected_flag=True,
            selection_rank=1,
            out_of_sample_metric=0.30,
            sharpe_like_score=1.7,
            writer_source="true_threshold_sweep_runner_v1",
        )
        second_trial_run_id = _seed_trial(
            repo,
            symbol=symbol,
            trial_suffix="trial_proxy_other",
            selection_rule="runtime_validation_proxy_top_in_sample_ev",
            selected_flag=False,
            selection_rank=2,
            out_of_sample_metric=0.22,
            sharpe_like_score=1.1,
            writer_source="runtime_validation_proxy_v1",
        )
        third_trial_run_id = _seed_trial(
            repo,
            symbol=symbol,
            trial_suffix="trial_threshold_other",
            selection_rule="true_threshold_sweep_top_in_sample_ev",
            selected_flag=False,
            selection_rank=3,
            out_of_sample_metric=0.15,
            sharpe_like_score=0.6,
            writer_source="true_threshold_sweep_runner_v1",
        )
        _seed_fold_scores(
            repo,
            symbol=symbol,
            selected_trial_run_id=selected_trial_run_id,
            second_trial_run_id=second_trial_run_id,
            third_trial_run_id=third_trial_run_id,
        )

        service = StrategyV2PboDsrMetricsService(repo=repo)
        payload = service.generate(symbol=symbol, version="v1", write_report=False, persist_snapshot=False)

        assert payload["metrics_complete"] is True
        assert payload["lineage_audit"]["audit_status"] == "PASS"
        assert payload["lineage_audit"]["lineage_mix_state"] == "dual_lineage"
        assert payload["selection_universe_summary"]["full_parameter_sweep_selection_universe_size"] == 2
        assert payload["selection_universe_summary"]["dsr_selection_universe_size"] == 2
        assert payload["selection_universe_summary"]["dsr_selection_universe_basis"] == "full_parameter_sweep_universe"
        assert payload["lineage_audit"]["selected_trial_from_runtime_proxy"] is False
        assert payload["lineage_audit"]["selected_trial_from_true_threshold"] is True
        assert payload["dsr"]["selection_universe_basis"] == "full_parameter_sweep_universe"
        assert payload["dsr"]["selection_universe_size"] == 2
        assert payload["dsr"]["legacy_combined_selection_universe_size"] == 3
        assert payload["dsr"]["bias_adjustment_rechecked"] is True
        assert payload["deployment_recommendation"]["decision"] == "pass_minimum_gate"
        assert payload["deployment_recommendation"]["lineage_audit_applied"] is False
