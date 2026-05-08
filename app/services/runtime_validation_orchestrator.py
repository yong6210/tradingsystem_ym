from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.core.enums import PlanState
from app.core.events import OUTCOME_UPDATED
from app.db.models import ZoneOutcome
from app.services.deployment_contracts import approval_summary_passthrough
from app.services.metrics import summarize_outcomes


class RuntimeValidationOrchestrator:
    """Coordinates the large runtime validation/report pipeline.

    This is intentionally a behavior-preserving extraction from StrategyEngine.
    The next cleanup pass can split this into smaller phase builders once the
    public engine surface is no longer carrying the whole orchestration body.
    """

    def __init__(self, engine: Any):
        self.engine = engine

    def recompute_learning(self, symbol: str, *, persist_runtime_validation_artifacts: bool = True) -> dict:
        return _run_engine_recompute_learning(
            self.engine,
            symbol,
            persist_runtime_validation_artifacts=persist_runtime_validation_artifacts,
        )


def _run_engine_recompute_learning(
    self: Any,
    symbol: str,
    *,
    persist_runtime_validation_artifacts: bool = True,
) -> dict:
    if not persist_runtime_validation_artifacts:
        cached_payload = self._load_cached_validation_payload(symbol)
        if cached_payload is not None:
            return cached_payload

    outcomes = self.outcome_repo.list_recent(symbol=symbol, days=180)
    by_zone: dict[str, list[ZoneOutcome]] = defaultdict(list)
    for item in outcomes:
        by_zone[item.zone_id].append(item)

    zones = self.zone_repo.list_all(symbol=symbol, timeframe="15m")
    zone_by_id = {z.zone_id: z for z in zones}

    updated = 0
    for zone_id, rows in by_zone.items():
        zone = zone_by_id.get(zone_id)
        if not zone:
            continue
        stats = self.learning.summarize(rows)
        self.learning.update_zone_quality(zone, stats)
        self.db.add(zone)
        updated += 1

    snap = summarize_outcomes(outcomes)
    metric = {
        "win_rate": snap.win_rate,
        "avg_win": snap.avg_win,
        "avg_loss": snap.avg_loss,
        "ev": snap.ev,
        "p1r": snap.p1r,
        "p2r": snap.p2r,
        "p3r": snap.p3r,
    }
    self.metrics_repo.upsert(symbol=symbol, version=self.settings.strategy_version, metric=metric)
    if updated > 0:
        self.events.publish(OUTCOME_UPDATED, {"symbol": symbol, "updated_zones": updated})
    self.db.commit()

    wf = self.backtest.walk_forward(
        outcomes,
        train_months=self.settings.validation_wf_train_months,
        test_months=self.settings.validation_wf_test_months,
    )
    mc = self.backtest.monte_carlo(outcomes, simulations=self.settings.validation_mc_simulations)
    context = self.current_context(symbol)
    feature_importance = self.feature_importance(symbol=symbol, context=context)
    feature_calibration = self.feature_calibration(
        symbol=symbol,
        context=context,
        feature_importance=feature_importance,
        write_report=True,
    )
    recent_plans = self.plan_repo.list_recent(symbol=symbol, days=180)
    recent_global_plans = self.plan_repo.list_recent_global(
        timeframe="5m",
        days=180,
        states=[PlanState.CLOSED.value],
        limit=10000,
    )
    candles_1m = self.market_data.recent_candles(symbol, "1m", limit=900)
    candles_5m = self.market_data.recent_candles(symbol, "5m", limit=300)
    candles_15m = self.market_data.recent_candles(symbol, "15m", limit=300)
    strategy_v2_validation = self.strategy_v2_validation.generate(
        symbol=symbol,
        version=self.settings.strategy_version,
        plans=recent_plans,
        write_report=True,
    )
    strategy_v2_lock_validation = self.strategy_v2_lock_validation.generate(
        symbol=symbol,
        version=self.settings.strategy_version,
        plans=recent_plans,
        write_report=True,
    )
    strategy_v2_pbo_dsr_trial_writer = self.strategy_v2_pbo_dsr_trial_writer.generate(
        symbol=symbol,
        version=self.settings.strategy_version,
        plans=recent_plans,
        write_report=True,
        persist=persist_runtime_validation_artifacts,
    )
    strategy_v2_pbo_dsr_threshold_runner = self.strategy_v2_pbo_dsr_threshold_runner.generate(
        symbol=symbol,
        version=self.settings.strategy_version,
        plans=recent_plans,
        write_report=True,
        persist=persist_runtime_validation_artifacts,
    )
    strategy_v2_pbo_dsr_metrics = self.strategy_v2_pbo_dsr_metrics.generate(
        symbol=symbol,
        version=self.settings.strategy_version,
        write_report=True,
        persist_snapshot=persist_runtime_validation_artifacts,
    )
    strategy_v2_pbo_dsr_metrics = self._merge_global_lineage_pbo_fallback(
        primary=strategy_v2_pbo_dsr_metrics,
        fallback=self._global_lineage_pbo_dsr_metrics(
            version=self.settings.strategy_version,
            write_report=True,
            persist_snapshot=persist_runtime_validation_artifacts,
            persist_runtime_validation_artifacts=persist_runtime_validation_artifacts,
        ),
    )
    strategy_v2_pbo_dsr_artifact_store = self.strategy_v2_pbo_dsr_artifact_store.generate(
        symbol=symbol,
        version=self.settings.strategy_version,
        write_report=True,
    )
    strategy_v2_pbo_dsr_design = self.strategy_v2_pbo_dsr_design.generate(
        symbol=symbol,
        version=self.settings.strategy_version,
        artifact_store=strategy_v2_pbo_dsr_artifact_store,
        write_report=True,
    )
    stress_replay_stack = self._build_stress_replay_runtime_stack(
        symbol=symbol,
        version=self.settings.strategy_version,
        plans=recent_plans,
        pbo_dsr_metrics=strategy_v2_pbo_dsr_metrics,
        write_report=True,
        run_prototype_worker=True,
        persist_runtime_validation_artifacts=persist_runtime_validation_artifacts,
    )
    strategy_v2_stress_validation = stress_replay_stack["stress_validation"]
    strategy_v2_stress_replay_lineage = stress_replay_stack["stress_replay_lineage"]
    strategy_v2_stress_replay_assessment = stress_replay_stack["stress_replay_assessment"]
    strategy_v2_stress_replay_runner_contract = stress_replay_stack["stress_replay_runner_contract"]
    strategy_v2_stress_replay_lineage_writer = stress_replay_stack["stress_replay_lineage_writer"]
    strategy_v2_stress_replay_prototype_worker = stress_replay_stack["stress_replay_prototype_worker"]
    strategy_v2_thesis_validation = self.strategy_v2_thesis_validation.generate(
        symbol=symbol,
        version=self.settings.strategy_version,
        plans=recent_global_plans,
        write_report=True,
    )
    strategy_v2_scalp_experiment = self.strategy_v2_scalp_experiment.generate(
        symbol=symbol,
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        candles_15m=candles_15m,
        write_report=True,
    )
    execution_quality = self.execution_quality.generate(symbol=symbol, days=180, write_report=False)
    recent_reconciliation_summary = self._recent_reconciliation_summary(
        symbol=symbol,
        days=180,
        limit=20,
    )
    safety_state = self._safety_state_payload(symbol=symbol)
    strategy_metrics = self.metrics(symbol=symbol, version=self.settings.strategy_version)
    alpha_research_performance_decomposition = self.validation_report._performance_decomposition_summary(
        execution_quality=execution_quality,
        strategy_v2_validation=strategy_v2_validation,
        strategy_v2_stress_validation=strategy_v2_stress_validation,
    )
    portfolio_budget_for_research = self.portfolio_budget_report(
        universe=self.settings.universe_name,
        limit=max(20, int(self.settings.alpha_research_max_candidates)),
        write_report=False,
    )
    alpha_research_pipeline = self.alpha_research_pipeline.generate(
        universe=self.settings.universe_name,
        portfolio_budget=portfolio_budget_for_research,
        focus_symbol=symbol,
        analysis_symbol=symbol,
        performance_decomposition_summary=alpha_research_performance_decomposition,
        write_report=True,
    )
    score_to_outcome_funnel = self.score_to_outcome_funnel.generate(
        symbol=symbol,
        version=self.settings.strategy_version,
        days=180,
        portfolio_budget=portfolio_budget_for_research,
    )
    execution_degradation_advisory = self.execution_degradation_advisory.generate(
        execution_quality=execution_quality,
        performance_decomposition_summary=alpha_research_performance_decomposition,
        strategy_v2_stress_validation=strategy_v2_stress_validation,
    )
    family_execution_degradation_advisory = self.family_execution_degradation_advisory.generate(
        execution_quality=execution_quality,
        performance_decomposition_summary=alpha_research_performance_decomposition,
        score_to_outcome_funnel=score_to_outcome_funnel,
    )
    mode_advisory = self.mode_advisory.generate(
        score_to_outcome_funnel=score_to_outcome_funnel,
        execution_degradation_advisory=execution_degradation_advisory,
        performance_decomposition_summary=alpha_research_performance_decomposition,
        alpha_research_evidence_summary=dict(
            alpha_research_pipeline.get("alpha_research_evidence_summary") or {}
        ),
        softening_candidate_review=dict(alpha_research_pipeline.get("softening_candidate_review") or {}),
        promotion_watchlist=dict(alpha_research_pipeline.get("promotion_watchlist") or {}),
    )
    operator_action_priority = self.operator_action_priority.generate(
        dashboard={
            "playbook_action": portfolio_budget_for_research.get("playbook_action", ""),
            "playbook_message": portfolio_budget_for_research.get("playbook_message", ""),
            "new_entries_allowed": True,
            "blocking_reason_code": "",
            "signal_funnel": {
                "execution_degradation_advisory": execution_degradation_advisory,
                "family_execution_degradation_advisory": family_execution_degradation_advisory,
                "mode_advisory": mode_advisory,
                "alpha_research_recommended_action": dict(
                    alpha_research_pipeline.get("recommended_action_summary") or {}
                ),
                "alpha_research_softening_review": dict(
                    alpha_research_pipeline.get("softening_candidate_review") or {}
                ),
                "alpha_research_promotion_watchlist": dict(
                    alpha_research_pipeline.get("promotion_watchlist") or {}
                ),
                "opportunity_capture": self._opportunity_capture_summary(
                    score_to_outcome_funnel_summary=score_to_outcome_funnel,
                    portfolio_budget=portfolio_budget_for_research,
                    execution_quality_summary=execution_quality,
                ),
            },
        },
        checklist=None,
        validation=None,
    )
    rollout_recommendation = self._rollout_recommendation_summary(
        score_to_outcome_funnel_summary=score_to_outcome_funnel,
        execution_degradation_advisory_summary=execution_degradation_advisory,
        family_execution_degradation_advisory_summary=family_execution_degradation_advisory,
        mode_advisory_summary=mode_advisory,
    )
    strategy_lifecycle = self._strategy_lifecycle_summary(
        alpha_research_pipeline_summary=alpha_research_pipeline,
        score_to_outcome_funnel_summary=score_to_outcome_funnel,
        family_execution_degradation_advisory_summary=family_execution_degradation_advisory,
        mode_advisory_summary=mode_advisory,
        rollout_recommendation_summary=rollout_recommendation,
    )
    positive_evidence_expansion = self._positive_evidence_expansion_summary(
        score_to_outcome_funnel_summary=score_to_outcome_funnel,
        family_execution_degradation_advisory_summary=family_execution_degradation_advisory,
        mode_advisory_summary=mode_advisory,
        rollout_recommendation_summary=rollout_recommendation,
        strategy_lifecycle_summary=strategy_lifecycle,
        capital_allocator_summary=dict(portfolio_budget_for_research.get("capital_allocator_summary") or {}) or None,
    )
    opportunity_capture = self._opportunity_capture_summary(
        score_to_outcome_funnel_summary=score_to_outcome_funnel,
        portfolio_budget=portfolio_budget_for_research,
        execution_quality_summary=execution_quality,
    )
    capital_allocator = dict(portfolio_budget_for_research.get("capital_allocator_summary") or {}) or None
    outcome_bucket_granularity = self._outcome_bucket_granularity_summary(
        score_to_outcome_funnel_summary=score_to_outcome_funnel,
    )
    a_strategy_post_cost_edge_validation = self._a_strategy_post_cost_edge_validation_summary(
        score_to_outcome_funnel_summary=score_to_outcome_funnel,
        family_execution_degradation_advisory_summary=family_execution_degradation_advisory,
        mode_advisory_summary=mode_advisory,
        outcome_bucket_granularity_summary=outcome_bucket_granularity,
        alpha_research_pipeline_summary=alpha_research_pipeline,
    )
    execution_friction_measurement = self._execution_friction_measurement_summary(
        execution_quality_summary=execution_quality,
        recent_reconciliation_summary=recent_reconciliation_summary,
        strategy_v2_stress_validation=strategy_v2_stress_validation,
    )
    forward_stress_regime_validation = self._forward_stress_regime_validation_summary(
        walk_forward_summary=wf.__dict__,
        strategy_v2_validation_summary=strategy_v2_validation,
        strategy_v2_stress_validation_summary=strategy_v2_stress_validation,
        strategy_v2_stress_replay_assessment_summary=strategy_v2_stress_replay_assessment,
        strategy_v2_stress_replay_lineage_summary=strategy_v2_stress_replay_lineage,
    )
    kill_condition_automation = self._kill_condition_automation_summary(
        strategy_metrics=strategy_metrics,
        safety_state=safety_state,
        execution_friction_measurement_summary=execution_friction_measurement,
        forward_stress_regime_validation_summary=forward_stress_regime_validation,
        recent_reconciliation_summary=recent_reconciliation_summary,
        execution_degradation_advisory_summary=execution_degradation_advisory,
        family_execution_degradation_advisory_summary=family_execution_degradation_advisory,
    )
    promotion_governance = self._promotion_governance_summary(
        strategy_lifecycle_summary=strategy_lifecycle,
        rollout_recommendation_summary=rollout_recommendation,
        positive_evidence_expansion_summary=positive_evidence_expansion,
        outcome_bucket_granularity_summary=outcome_bucket_granularity,
        family_execution_degradation_advisory_summary=family_execution_degradation_advisory,
        mode_advisory_summary=mode_advisory,
        capital_allocator_summary=capital_allocator,
        score_to_outcome_funnel_summary=score_to_outcome_funnel,
    )
    promotion_review_queue = self._promotion_review_queue_summary(
        promotion_governance_summary=promotion_governance,
        strategy_lifecycle_summary=strategy_lifecycle,
        positive_evidence_expansion_summary=positive_evidence_expansion,
        capital_allocator_summary=capital_allocator,
        family_execution_degradation_advisory_summary=family_execution_degradation_advisory,
        score_to_outcome_funnel_summary=score_to_outcome_funnel,
    )
    promotion_remediation_queue = self._promotion_remediation_queue_summary(
        promotion_governance_summary=promotion_governance,
        promotion_review_queue_summary=promotion_review_queue,
        strategy_lifecycle_summary=strategy_lifecycle,
        positive_evidence_expansion_summary=positive_evidence_expansion,
        outcome_bucket_granularity_summary=outcome_bucket_granularity,
        family_execution_degradation_advisory_summary=family_execution_degradation_advisory,
        rollout_recommendation_summary=rollout_recommendation,
        capital_allocator_summary=capital_allocator,
        alpha_research_pipeline_summary=alpha_research_pipeline,
    )
    promotion_clearance_tracker = self._promotion_clearance_tracker_summary(
        promotion_governance_summary=promotion_governance,
        promotion_review_queue_summary=promotion_review_queue,
        promotion_remediation_queue_summary=promotion_remediation_queue,
        strategy_lifecycle_summary=strategy_lifecycle,
        family_execution_degradation_advisory_summary=family_execution_degradation_advisory,
        rollout_recommendation_summary=rollout_recommendation,
        outcome_bucket_granularity_summary=outcome_bucket_granularity,
        positive_evidence_expansion_summary=positive_evidence_expansion,
        capital_allocator_summary=capital_allocator,
    )
    promotion_reopen_queue = self._promotion_reopen_queue_summary(
        promotion_governance_summary=promotion_governance,
        promotion_review_queue_summary=promotion_review_queue,
        promotion_remediation_queue_summary=promotion_remediation_queue,
        promotion_clearance_tracker_summary=promotion_clearance_tracker,
        strategy_lifecycle_summary=strategy_lifecycle,
        positive_evidence_expansion_summary=positive_evidence_expansion,
        capital_allocator_summary=capital_allocator,
        family_execution_degradation_advisory_summary=family_execution_degradation_advisory,
    )
    promotion_decision_brief = self._promotion_decision_brief_summary(
        promotion_governance_summary=promotion_governance,
        promotion_review_queue_summary=promotion_review_queue,
        promotion_remediation_queue_summary=promotion_remediation_queue,
        promotion_clearance_tracker_summary=promotion_clearance_tracker,
        promotion_reopen_queue_summary=promotion_reopen_queue,
        strategy_lifecycle_summary=strategy_lifecycle,
        positive_evidence_expansion_summary=positive_evidence_expansion,
        capital_allocator_summary=capital_allocator,
        family_execution_degradation_advisory_summary=family_execution_degradation_advisory,
    )
    auto_promotion_rollout_execution = self._auto_promotion_rollout_execution_summary(
        promotion_governance_summary=promotion_governance,
        promotion_review_queue_summary=promotion_review_queue,
        promotion_remediation_queue_summary=promotion_remediation_queue,
        promotion_clearance_tracker_summary=promotion_clearance_tracker,
        promotion_reopen_queue_summary=promotion_reopen_queue,
        promotion_decision_brief_summary=promotion_decision_brief,
        rollout_recommendation_summary=rollout_recommendation,
        strategy_lifecycle_summary=strategy_lifecycle,
        family_execution_degradation_advisory_summary=family_execution_degradation_advisory,
        mode_advisory_summary=mode_advisory,
        score_to_outcome_funnel_summary=score_to_outcome_funnel,
        execution_degradation_advisory_summary=execution_degradation_advisory,
        positive_evidence_expansion_summary=positive_evidence_expansion,
    )
    promotion_lifecycle_history = self._promotion_lifecycle_history_summary(
        persist=True,
        strategy_lifecycle_summary=strategy_lifecycle,
        promotion_governance_summary=promotion_governance,
        promotion_review_queue_summary=promotion_review_queue,
        promotion_remediation_queue_summary=promotion_remediation_queue,
        promotion_clearance_tracker_summary=promotion_clearance_tracker,
        promotion_reopen_queue_summary=promotion_reopen_queue,
        promotion_decision_brief_summary=promotion_decision_brief,
        auto_promotion_rollout_execution_summary=auto_promotion_rollout_execution,
    )
    multi_strategy_ab = self._multi_strategy_ab_summary(
        portfolio_budget=portfolio_budget_for_research,
        score_to_outcome_funnel_summary=score_to_outcome_funnel,
        family_execution_degradation_advisory_summary=family_execution_degradation_advisory,
        rollout_recommendation_summary=rollout_recommendation,
        strategy_lifecycle_summary=strategy_lifecycle,
    )
    b_continuation_activation = self._b_continuation_activation_summary(
        multi_strategy_ab_summary=multi_strategy_ab,
        score_to_outcome_funnel_summary=score_to_outcome_funnel,
        family_execution_degradation_advisory_summary=family_execution_degradation_advisory,
        rollout_recommendation_summary=rollout_recommendation,
        strategy_lifecycle_summary=strategy_lifecycle,
        promotion_governance_summary=promotion_governance,
        promotion_clearance_tracker_summary=promotion_clearance_tracker,
        promotion_reopen_queue_summary=promotion_reopen_queue,
        promotion_decision_brief_summary=promotion_decision_brief,
        auto_promotion_rollout_execution_summary=auto_promotion_rollout_execution,
        positive_evidence_expansion_summary=positive_evidence_expansion,
    )
    strategy_cluster_balance = self._strategy_cluster_balance_summary(
        portfolio_budget=portfolio_budget_for_research,
        multi_strategy_ab_summary=multi_strategy_ab,
        b_continuation_activation_summary=b_continuation_activation,
        capital_allocator_summary=capital_allocator,
    )
    b_continuation_edge_validation = self._b_continuation_edge_validation_summary(
        score_to_outcome_funnel_summary=score_to_outcome_funnel,
        outcome_bucket_granularity_summary=outcome_bucket_granularity,
        family_execution_degradation_advisory_summary=family_execution_degradation_advisory,
        alpha_research_pipeline_summary=alpha_research_pipeline,
        b_continuation_activation_summary=b_continuation_activation,
        multi_strategy_ab_summary=multi_strategy_ab,
        strategy_cluster_balance_summary=strategy_cluster_balance,
        capital_allocator_summary=capital_allocator,
    )
    research_promotion_operating_loop = self._research_promotion_operating_loop_summary(
        alpha_research_pipeline_summary=alpha_research_pipeline,
        strategy_lifecycle_summary=strategy_lifecycle,
        promotion_governance_summary=promotion_governance,
        promotion_review_queue_summary=promotion_review_queue,
        promotion_decision_brief_summary=promotion_decision_brief,
        auto_promotion_rollout_execution_summary=auto_promotion_rollout_execution,
        promotion_lifecycle_history_summary=promotion_lifecycle_history,
        family_execution_degradation_advisory_summary=family_execution_degradation_advisory,
        multi_strategy_ab_summary=multi_strategy_ab,
    )
    report = self.validation_report.generate(
        symbol=symbol,
        version=self.settings.strategy_version,
        wf=wf.__dict__,
        mc=mc.__dict__,
        metric=metric,
        execution_quality=execution_quality,
        execution_friction_measurement=execution_friction_measurement,
        forward_stress_regime_validation=forward_stress_regime_validation,
        kill_condition_automation=kill_condition_automation,
        feature_importance=feature_importance,
        feature_calibration=feature_calibration,
        strategy_v2_validation=strategy_v2_validation,
        strategy_v2_lock_validation=strategy_v2_lock_validation,
        strategy_v2_pbo_dsr_trial_writer=strategy_v2_pbo_dsr_trial_writer,
        strategy_v2_pbo_dsr_threshold_runner=strategy_v2_pbo_dsr_threshold_runner,
        strategy_v2_pbo_dsr_artifact_store=strategy_v2_pbo_dsr_artifact_store,
        strategy_v2_pbo_dsr_design=strategy_v2_pbo_dsr_design,
        strategy_v2_pbo_dsr_metrics=strategy_v2_pbo_dsr_metrics,
        strategy_v2_stress_validation=strategy_v2_stress_validation,
        strategy_v2_stress_replay_lineage=strategy_v2_stress_replay_lineage,
        strategy_v2_stress_replay_assessment=strategy_v2_stress_replay_assessment,
        strategy_v2_stress_replay_runner_contract=strategy_v2_stress_replay_runner_contract,
        strategy_v2_stress_replay_lineage_writer=strategy_v2_stress_replay_lineage_writer,
        strategy_v2_stress_replay_prototype_worker=strategy_v2_stress_replay_prototype_worker,
        strategy_v2_thesis_validation=strategy_v2_thesis_validation,
        strategy_v2_scalp_experiment=strategy_v2_scalp_experiment,
        alpha_research_pipeline=alpha_research_pipeline,
        score_to_outcome_funnel=score_to_outcome_funnel,
        execution_degradation_advisory=execution_degradation_advisory,
        family_execution_degradation_advisory=family_execution_degradation_advisory,
        mode_advisory=mode_advisory,
        operator_action_priority=operator_action_priority,
        rollout_recommendation=rollout_recommendation,
        strategy_lifecycle=strategy_lifecycle,
        promotion_governance=promotion_governance,
        promotion_review_queue=promotion_review_queue,
        promotion_remediation_queue=promotion_remediation_queue,
        promotion_clearance_tracker=promotion_clearance_tracker,
        promotion_reopen_queue=promotion_reopen_queue,
        promotion_decision_brief=promotion_decision_brief,
        auto_promotion_rollout_execution=auto_promotion_rollout_execution,
        b_continuation_activation=b_continuation_activation,
        b_continuation_edge_validation=b_continuation_edge_validation,
        strategy_cluster_balance=strategy_cluster_balance,
        a_strategy_post_cost_edge_validation=a_strategy_post_cost_edge_validation,
        promotion_lifecycle_history=promotion_lifecycle_history,
        research_promotion_operating_loop=research_promotion_operating_loop,
        multi_strategy_ab=multi_strategy_ab,
        positive_evidence_expansion=positive_evidence_expansion,
        outcome_bucket_granularity=outcome_bucket_granularity,
        opportunity_capture=opportunity_capture,
        capital_allocator=capital_allocator,
    )
    validation_alert = self._maybe_emit_validation_alert(
        symbol=symbol,
        version=self.settings.strategy_version,
        report=report,
    )
    approval_contract = approval_summary_passthrough(report.get("deployment_approval_summary"))
    parameter_changelog = self.parameter_changelog_service.generate(
        version=self.settings.strategy_version,
        trigger="validation_report",
    )
    self.db.commit()
    payload = {
        "symbol": symbol,
        "updated_zones": updated,
        "metrics": metric,
        "walk_forward": wf.__dict__,
        "monte_carlo": mc.__dict__,
        "validation_report": report,
        **approval_contract,
        "validation_alert": validation_alert,
        "execution_quality": execution_quality,
        "feature_importance": feature_importance,
        "feature_calibration": feature_calibration,
        "strategy_v2_validation": strategy_v2_validation,
        "strategy_v2_lock_validation": strategy_v2_lock_validation,
        "strategy_v2_pbo_dsr_trial_writer": strategy_v2_pbo_dsr_trial_writer,
        "strategy_v2_pbo_dsr_threshold_runner": strategy_v2_pbo_dsr_threshold_runner,
        "strategy_v2_pbo_dsr_artifact_store": strategy_v2_pbo_dsr_artifact_store,
        "strategy_v2_pbo_dsr_design": strategy_v2_pbo_dsr_design,
        "strategy_v2_pbo_dsr_metrics": strategy_v2_pbo_dsr_metrics,
        "strategy_v2_stress_validation": strategy_v2_stress_validation,
        "strategy_v2_stress_replay_lineage": strategy_v2_stress_replay_lineage,
        "strategy_v2_stress_replay_assessment": strategy_v2_stress_replay_assessment,
        "strategy_v2_stress_replay_runner_contract": strategy_v2_stress_replay_runner_contract,
        "strategy_v2_stress_replay_lineage_writer": strategy_v2_stress_replay_lineage_writer,
        "strategy_v2_stress_replay_prototype_worker": strategy_v2_stress_replay_prototype_worker,
        "strategy_v2_thesis_validation": strategy_v2_thesis_validation,
        "strategy_v2_scalp_experiment": strategy_v2_scalp_experiment,
        "alpha_research_pipeline": alpha_research_pipeline,
        "parameter_changelog": parameter_changelog,
        "operator_action_priority_summary": report.get("operator_action_priority_summary"),
        "edge_experiment_review_available": report.get("edge_experiment_review_available"),
        "edge_experiment_review_summary": report.get("edge_experiment_review_summary"),
        "edge_evolution_rule_available": report.get("edge_evolution_rule_available"),
        "edge_evolution_rule_summary": report.get("edge_evolution_rule_summary"),
        "review_followup_ledger_available": report.get("review_followup_ledger_available"),
        "review_followup_ledger_summary": report.get("review_followup_ledger_summary"),
    }
    if not persist_runtime_validation_artifacts and not bool(
        getattr(self, "_suppress_read_only_validation_payload_store", False)
    ):
        self._store_cached_validation_payload(symbol, payload)
    return payload
