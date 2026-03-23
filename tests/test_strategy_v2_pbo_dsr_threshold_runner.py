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
