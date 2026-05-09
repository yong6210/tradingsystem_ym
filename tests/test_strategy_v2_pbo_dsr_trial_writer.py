from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.enums import PlanState
from app.core.config import get_settings
from app.db.models import Plan
from app.db.repositories import ValidationArtifactRepository
from app.db.session import SessionLocal, init_db
from app.services.strategy_engine import StrategyEngine
from app.services.strategy_v2_pbo_dsr_trial_writer import StrategyV2PboDsrTrialWriterService


def _closed_plan(
    *,
    plan_id: str,
    symbol: str,
    grade: str,
    realized_r: float,
    closed_ts: datetime,
    family: str = "sweep_reversal",
    regime: str = "range",
    transition_state: str = "none",
    transition_score: float = 18.0,
    reaction_classification: str = "rejection_confirmed",
    reaction_rejection_score: float = 82.0,
    reaction_acceptance_score: float = 20.0,
    confluence_score: float = 72.0,
    recommended_risk_r: float = 1.0,
    version: str = "v1",
) -> Plan:
    return Plan(
        plan_id=plan_id,
        zone_id=f"zone_{plan_id}",
        symbol=symbol,
        timeframe="5m",
        direction="long",
        entry_model="CONFIRM",
        entry_price=100.0,
        entry_condition="touch_then_confirm",
        sl=99.0,
        tp1=101.0,
        tp2=102.0,
        tp3=103.0,
        split={"tp1": 0.4, "tp2": 0.4, "runner": 0.2},
        rr_min=1.0,
        rr_base=1.8,
        rr_opt=2.5,
        ev=0.4,
        cost_est=0.1,
        confidence=0.7,
        validity={
            "strategy_family": family,
            "strategy_grade": grade,
            "regime": regime,
            "transition_state": transition_state,
            "transition_score": transition_score,
            "reaction_classification": reaction_classification,
            "reaction_rejection_score": reaction_rejection_score,
            "reaction_acceptance_score": reaction_acceptance_score,
            "confluence_score": confluence_score,
            "recommended_risk_r": recommended_risk_r,
            "final_exit_ts": closed_ts.isoformat(),
            "final_exit_realized_r": realized_r,
            "final_exit_reason": "target_tp2" if realized_r > 0 else "time_failure",
            "final_exit_held_bars": 4,
        },
        state=PlanState.CLOSED.value,
        valid_from=closed_ts - timedelta(hours=4),
        valid_until=closed_ts + timedelta(hours=4),
        strategy_version=version,
    )


def _sample_plans(symbol: str, *, version: str = "v1") -> list[Plan]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return [
        _closed_plan(plan_id=f"{symbol}_a1", symbol=symbol, grade="A", realized_r=1.2, closed_ts=now - timedelta(days=8), version=version),
        _closed_plan(
            plan_id=f"{symbol}_a2",
            symbol=symbol,
            grade="A",
            realized_r=0.8,
            closed_ts=now - timedelta(days=7),
            family="trend_continuation",
            regime="trend",
            confluence_score=68.0,
            recommended_risk_r=0.8,
            reaction_classification="acceptance_confirmed",
            reaction_rejection_score=18.0,
            reaction_acceptance_score=76.0,
            version=version,
        ),
        _closed_plan(
            plan_id=f"{symbol}_a3",
            symbol=symbol,
            grade="A",
            realized_r=-0.3,
            closed_ts=now - timedelta(days=6),
            regime="shock",
            family="sweep_reversal",
            reaction_classification="rejection_confirmed",
            confluence_score=74.0,
            transition_score=28.0,
            recommended_risk_r=1.0,
            version=version,
        ),
        _closed_plan(
            plan_id=f"{symbol}_a4",
            symbol=symbol,
            grade="A",
            realized_r=0.5,
            closed_ts=now - timedelta(days=5),
            confluence_score=63.0,
            transition_score=34.0,
            recommended_risk_r=1.0,
            version=version,
        ),
        _closed_plan(
            plan_id=f"{symbol}_b1",
            symbol=symbol,
            grade="B",
            realized_r=0.3,
            closed_ts=now - timedelta(days=4),
            confluence_score=60.0,
            reaction_classification="rejection_tentative",
            reaction_rejection_score=63.0,
            recommended_risk_r=0.5,
            version=version,
        ),
        _closed_plan(
            plan_id=f"{symbol}_b2",
            symbol=symbol,
            grade="B",
            realized_r=-0.6,
            closed_ts=now - timedelta(days=3),
            regime="shock",
            family="sweep_reversal",
            reaction_classification="rejection_confirmed",
            confluence_score=66.0,
            transition_score=39.0,
            recommended_risk_r=0.5,
            version=version,
        ),
        _closed_plan(
            plan_id=f"{symbol}_b3",
            symbol=symbol,
            grade="B",
            realized_r=-0.5,
            closed_ts=now - timedelta(days=2),
            transition_state="transition_confirmed",
            transition_score=58.0,
            confluence_score=64.0,
            reaction_classification="acceptance_confirmed",
            reaction_rejection_score=12.0,
            reaction_acceptance_score=72.0,
            recommended_risk_r=0.5,
            version=version,
        ),
        _closed_plan(
            plan_id=f"{symbol}_b4",
            symbol=symbol,
            grade="B",
            realized_r=-0.4,
            closed_ts=now - timedelta(days=1),
            transition_state="transition_watch",
            transition_score=44.0,
            confluence_score=59.0,
            reaction_classification="acceptance_tentative",
            reaction_rejection_score=16.0,
            reaction_acceptance_score=58.0,
            recommended_risk_r=0.25,
            version=version,
        ),
    ]


def test_strategy_v2_pbo_dsr_trial_writer_seeds_runtime_proxy_trials() -> None:
    init_db()
    symbol = f"PBOSEED{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"

    with SessionLocal() as db:
        for plan in _sample_plans(symbol):
            db.add(plan)
        db.commit()

        repo = ValidationArtifactRepository(db)
        service = StrategyV2PboDsrTrialWriterService(repo=repo)
        payload = service.generate(symbol=symbol, version="v1", plans=db.query(Plan).filter(Plan.symbol == symbol).all(), write_report=False)
        db.commit()

        assert payload["available"] is True
        assert payload["reason"] == "pbo_dsr_runtime_proxy_writer_seeded"
        assert payload["sample_counts"]["eligible_closed_trades"] == 8
        assert payload["sample_counts"]["candidate_trials"] >= 8
        assert payload["sample_counts"]["trial_runs_written"] >= 8
        assert payload["sample_counts"]["fold_scores_written"] == (
            payload["sample_counts"]["trial_runs_written"] * payload["sample_counts"]["fold_count"]
        )
        assert payload["selection_rule"] == "runtime_validation_proxy_top_in_sample_ev"
        assert payload["selected_trial_run_id"] is not None
        assert "mode_policy" in payload["parameter_families_present"]
        assert "lock_policy" in payload["parameter_families_present"]
        assert "stress_policy" in payload["parameter_families_present"]
        assert "scoring_thresholds" in payload["parameter_families_present"]
        assert "transition_threshold" in payload["parameter_families_present"]
        assert "acceptance_rejection_thresholds" in payload["parameter_families_present"]
        assert "sizing_clamps" in payload["parameter_families_present"]
        assert payload["threshold_parameter_families_present"] == [
            "acceptance_rejection_thresholds",
            "scoring_thresholds",
            "sizing_clamps",
            "transition_threshold",
        ]
        assert payload["candidate_trials_by_family"]["scoring_thresholds"] >= 3
        assert payload["candidate_trials_by_family"]["transition_threshold"] >= 3
        assert payload["candidate_trials_by_family"]["acceptance_rejection_thresholds"] >= 3
        assert payload["candidate_trials_by_family"]["sizing_clamps"] >= 3

        counts = repo.counts(symbol=symbol, version="v1")
        assert counts["trial_runs"] == payload["sample_counts"]["trial_runs_written"]
        assert counts["fold_scores"] == payload["sample_counts"]["fold_scores_written"]


def test_recompute_learning_seeds_trial_writer_and_pbo_dsr_metrics() -> None:
    init_db()
    symbol = f"PBOENGINE{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 1}USDC"
    runtime_version = get_settings().strategy_version

    with SessionLocal() as db:
        for plan in _sample_plans(symbol, version=runtime_version):
            db.add(plan)
        db.commit()

        engine = StrategyEngine(db)
        payload = engine.recompute_learning(symbol)

        writer_payload = payload["strategy_v2_pbo_dsr_trial_writer"]
        assert writer_payload["available"] is True
        assert writer_payload["sample_counts"]["trial_runs_written"] >= 20
        assert writer_payload["sample_counts"]["fold_scores_written"] >= 40
        assert "transition_threshold" in writer_payload["threshold_parameter_families_present"]
        assert writer_payload["candidate_trials_by_family"]["sizing_clamps"] >= 3

        threshold_payload = payload["strategy_v2_pbo_dsr_threshold_runner"]
        assert threshold_payload["available"] is True
        assert threshold_payload["selection_rule"] == "true_threshold_sweep_top_in_sample_ev"
        assert threshold_payload["lineage_namespace"] == "true_threshold_sweep_runner_v1"
        assert threshold_payload["sample_counts"]["trial_runs_written"] >= 10
        assert threshold_payload["candidate_trials_by_family"]["transition_threshold"] >= 3

        artifact_payload = payload["strategy_v2_pbo_dsr_artifact_store"]
        assert artifact_payload["available"] is True
        assert artifact_payload["counts"]["trial_runs"] == (
            writer_payload["sample_counts"]["trial_runs_written"]
            + threshold_payload["sample_counts"]["trial_runs_written"]
        )
        assert artifact_payload["selection_rule_counts"]["runtime_validation_proxy_top_in_sample_ev"] == (
            writer_payload["sample_counts"]["trial_runs_written"]
        )
        assert artifact_payload["selection_rule_counts"]["true_threshold_sweep_top_in_sample_ev"] == (
            threshold_payload["sample_counts"]["trial_runs_written"]
        )
        assert artifact_payload["selection_universe_summary"]["combined_artifact_selection_universe_size"] == (
            artifact_payload["counts"]["trial_runs"]
        )
        assert artifact_payload["selection_universe_summary"]["full_parameter_sweep_selection_universe_size"] == (
            threshold_payload["sample_counts"]["trial_runs_written"]
        )

        metrics_payload = payload["strategy_v2_pbo_dsr_metrics"]
        assert metrics_payload["available"] is True
        assert metrics_payload["sample_counts"]["trial_runs"] == artifact_payload["counts"]["trial_runs"]
        assert metrics_payload["sample_counts"]["fold_scores"] == artifact_payload["counts"]["fold_scores"]
        assert metrics_payload["selection_rule_counts"] == artifact_payload["selection_rule_counts"]
        assert metrics_payload["selection_universe_summary"]["combined_artifact_selection_universe_size"] == (
            artifact_payload["counts"]["trial_runs"]
        )
        assert metrics_payload["selection_universe_summary"]["full_parameter_sweep_selection_universe_size"] == (
            threshold_payload["sample_counts"]["trial_runs_written"]
        )
        assert metrics_payload["selection_universe_summary"]["dsr_selection_universe_basis"] == "full_parameter_sweep_universe"
        assert metrics_payload["selection_universe_summary"]["dsr_selection_universe_size"] == (
            threshold_payload["sample_counts"]["trial_runs_written"]
        )
        assert metrics_payload["selected_trial"]["selection_rule"] in {
            writer_payload["selection_rule"],
            threshold_payload["selection_rule"],
        }
        assert payload["edge_experiment_review_summary"] is not None
        assert payload["edge_evolution_rule_summary"] is not None
        assert payload["review_followup_ledger_summary"] is not None
        assert metrics_payload["selected_trial"]["writer_source"] in {
            "runtime_validation_proxy_v1",
            "true_threshold_sweep_runner_v1",
        }


def test_strategy_v2_pbo_dsr_trial_writer_tolerates_malformed_numeric_settings() -> None:
    service = StrategyV2PboDsrTrialWriterService()
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
        plans = _sample_plans("PBOWRITERBADUSDC")
        plan_pairs = service._closed_plan_pairs(plans=plans, symbol="PBOWRITERBADUSDC", version="v1")

        trials = [
            *service._scoring_threshold_trials(plan_pairs=plan_pairs),
            *service._transition_threshold_trials(plan_pairs=plan_pairs),
            *service._acceptance_rejection_threshold_trials(plan_pairs=plan_pairs),
            *service._sizing_clamp_trials(plan_pairs=plan_pairs),
        ]

        assert trials
        assert {trial.parameter_family for trial in trials} >= {
            "scoring_thresholds",
            "transition_threshold",
            "acceptance_rejection_thresholds",
            "sizing_clamps",
        }
    finally:
        for key, value in original_values.items():
            setattr(service.settings, key, value)
