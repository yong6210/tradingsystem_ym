from __future__ import annotations

from datetime import datetime, timezone

from app.db.models import Plan
from app.db.repositories import ValidationArtifactRepository
from app.db.session import SessionLocal, init_db
from app.services.strategy_v2_pbo_dsr_artifact_store import StrategyV2PboDsrArtifactStoreService
from app.services.strategy_v2_pbo_dsr_threshold_runner import StrategyV2PboDsrThresholdRunnerService
from app.services.strategy_v2_pbo_dsr_trial_writer import StrategyV2PboDsrTrialWriterService
from tests.test_strategy_v2_pbo_dsr_trial_writer import _sample_plans


def test_strategy_v2_pbo_dsr_threshold_runner_seeds_separate_lineage() -> None:
    init_db()
    symbol = f"PBOTHR{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"

    with SessionLocal() as db:
        for plan in _sample_plans(symbol):
            db.add(plan)
        db.commit()

        repo = ValidationArtifactRepository(db)
        plans = db.query(Plan).filter(Plan.symbol == symbol).all()
        proxy_writer = StrategyV2PboDsrTrialWriterService(repo=repo)
        threshold_runner = StrategyV2PboDsrThresholdRunnerService(repo=repo)

        proxy_payload = proxy_writer.generate(symbol=symbol, version="v1", plans=plans, write_report=False)
        threshold_payload = threshold_runner.generate(symbol=symbol, version="v1", plans=plans, write_report=False)
        db.commit()

        assert proxy_payload["available"] is True
        assert threshold_payload["available"] is True
        assert threshold_payload["reason"] == "pbo_dsr_true_threshold_runner_seeded"
        assert threshold_payload["selection_rule"] == "true_threshold_sweep_top_in_sample_ev"
        assert threshold_payload["lineage_namespace"] == "true_threshold_sweep_runner_v1"
        assert threshold_payload["sample_counts"]["candidate_trials"] >= 8
        assert threshold_payload["candidate_trials_by_family"]["scoring_thresholds"] >= 3
        assert threshold_payload["candidate_trials_by_family"]["sizing_clamps"] >= 3

        counts = repo.counts(symbol=symbol, version="v1")
        selection_rule_counts = repo.selection_rule_counts(symbol=symbol, version="v1")
        assert counts["trial_runs"] == (
            proxy_payload["sample_counts"]["trial_runs_written"]
            + threshold_payload["sample_counts"]["trial_runs_written"]
        )
        assert counts["fold_scores"] == (
            proxy_payload["sample_counts"]["fold_scores_written"]
            + threshold_payload["sample_counts"]["fold_scores_written"]
        )
        assert selection_rule_counts == {
            "runtime_validation_proxy_top_in_sample_ev": proxy_payload["sample_counts"]["trial_runs_written"],
            "true_threshold_sweep_top_in_sample_ev": threshold_payload["sample_counts"]["trial_runs_written"],
        }

        artifact_payload = StrategyV2PboDsrArtifactStoreService(repo=repo).generate(
            symbol=symbol,
            version="v1",
            write_report=False,
        )
        assert artifact_payload["selection_rule_counts"] == selection_rule_counts


def test_strategy_v2_pbo_dsr_threshold_runner_tolerates_malformed_numeric_settings() -> None:
    init_db()
    with SessionLocal() as db:
        service = StrategyV2PboDsrThresholdRunnerService(repo=ValidationArtifactRepository(db))
        original_values = {
            "min_confluence_score": service.settings.min_confluence_score,
            "transition_watch_score": service.settings.transition_watch_score,
            "transition_confirmed_score": service.settings.transition_confirmed_score,
            "reaction_classifier_rejection_confirmed_score": service.settings.reaction_classifier_rejection_confirmed_score,
            "reaction_classifier_rejection_tentative_score": service.settings.reaction_classifier_rejection_tentative_score,
            "reaction_classifier_acceptance_confirmed_score": service.settings.reaction_classifier_acceptance_confirmed_score,
            "reaction_classifier_acceptance_tentative_score": service.settings.reaction_classifier_acceptance_tentative_score,
            "sizing_grade_a_r": service.settings.sizing_grade_a_r,
            "sizing_grade_b_r": service.settings.sizing_grade_b_r,
            "sizing_grade_c_r": service.settings.sizing_grade_c_r,
        }
        try:
            for key in original_values:
                setattr(service.settings, key, "bad")
            service.settings.sizing_grade_a_r = float("inf")

            payload = service.generate(symbol="BTCUSDC", version="v1", plans=[], write_report=False)

            assert payload["available"] is False
            assert payload["sweep_grid"]["scoring_thresholds"] == [56.0, 58.0, 60.0, 62.0, 64.0, 66.0, 68.0]
            assert payload["sweep_grid"]["transition_threshold"] == [32.5, 35.0, 37.5, 40.0, 42.5, 45.0, 47.5]
            assert payload["sweep_grid"]["sizing_clamps"] == [0.25, 0.5, 0.75, 1.0]
        finally:
            for key, value in original_values.items():
                setattr(service.settings, key, value)
