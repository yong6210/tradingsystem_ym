from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.events import (
    ENTRY_TRIGGERED,
    OUTCOME_UPDATED,
    PLAN_GENERATED,
    TRADE_CLOSED,
    VALIDATION_FAIL,
    VALIDATION_WARN,
    ZONE_CREATED,
)
from app.core.enums import ExecutionFillStage, ExecutionMode, OrderLifecycleState, PlanState, RiskGateState
from app.db.models import AlertSubscription, Zone, ZoneOutcome
from app.db.session import SessionLocal
from app.db.repositories import (
    AlertRepository,
    AlertRetryQueueRepository,
    CandleRepository,
    MetricsRepository,
    OutcomeRepository,
    ValidationArtifactRepository,
    ZoneRepository,
)
from app.repositories.execution import (
    BinanceOrderLedgerRepository,
    BinancePositionRepository,
    ExecutionFillRepository,
    ExecutionReconciliationEventRepository,
    FamilyRolloutPolicyRepository,
    OrderIntentRepository,
    OrderSubmissionRepository,
    PlanRepository,
    PromotionLifecycleHistoryRepository,
    SafetyLockRepository,
)
from app.services.backtest import BacktestService
from app.services.alert_metrics import AlertMetricsService
from app.services.alert_retry_queue import AlertRetryQueueService
from app.services.alpha_research_pipeline import AlphaResearchPipelineService
from app.services.a_strategy_post_cost_edge_validation import AStrategyPostCostEdgeValidationService
from app.services.auto_promotion_rollout_execution import AutoPromotionRolloutExecutionService
from app.services.b_continuation_activation import BContinuationActivationService
from app.services.b_continuation_edge_validation import BContinuationEdgeValidationService
from app.services.context_engine import ContextEngine, ContextSnapshot
from app.services.deployment_contracts import (
    alert_contract_defaults,
    approval_summary_passthrough,
    validation_alert_contract,
    validation_alert_strip_summary,
)
from app.services.edge_experiment_review import build_edge_experiment_review, summarize_edge_experiment_review
from app.services.edge_evolution_rule import build_edge_evolution_rule, summarize_edge_evolution_rule
from app.services.execution_quality import ExecutionQualityService
from app.services.execution_friction_measurement import ExecutionFrictionMeasurementService
from app.services.execution_operator_dashboard import ExecutionOperatorDashboardService
from app.services.family_execution_degradation_advisory import FamilyExecutionDegradationAdvisoryService
from app.services.forward_stress_regime_validation import ForwardStressRegimeValidationService
from app.services.kill_condition_automation import KillConditionAutomationService
from app.services.mode_advisory import ModeAdvisoryService
from app.services.multi_strategy_ab import MultiStrategyABExpansionService
from app.services.outcome_bucket_granularity import OutcomeBucketGranularityService
from app.services.outcome_control_trace import build_outcome_control_trace, summarize_outcome_control_trace
from app.services.execution.approval import ExecutionPlanningService
from app.services.execution.coordinator import ExecutionCoordinator
from app.services.execution.intents import OrderIntentService
from app.services.execution.reconciliation import ExecutionReconciliationService
from app.services.execution.rollout import RolloutPolicyService
from app.services.execution.safety import SafetyLockService
from app.services.event_bus import EventBus
from app.services.feature_calibration import FeatureCalibrationService
from app.services.feature_importance import FeatureImportanceService
from app.services.learning import LearningService
from app.services.market_data import MarketDataService
from app.services.metrics import summarize_outcomes
from app.services.notification_dispatcher import NotificationDispatcher
from app.services.operational_checklist import OperationalChecklistService
from app.services.operating_lock import OperatingLockSnapshot, OperatingLockService
from app.services.operator_action_priority import OperatorActionPriorityService
from app.services.opportunity_capture import OpportunityCaptureService
from app.services.split_review_followup_ledger import summarize_split_review_followup_ledger
from app.services.parameter_changelog import ParameterChangelogService
from app.services.plan_generator import PlanGenerator, RankedPlan
from app.services.positive_evidence_expansion import PositiveEvidenceExpansionService
from app.services.portfolio_budget_report import PortfolioBudgetReportService
from app.services.position_state_machine import FillApplyInput, PositionStateMachineService
from app.services.promotion_clearance_tracker import PromotionClearanceTrackerService
from app.services.promotion_decision_brief import PromotionDecisionBriefService
from app.services.promotion_governance import PromotionGovernanceService
from app.services.promotion_lifecycle_history import PromotionLifecycleHistoryService
from app.services.promotion_remediation_queue import PromotionRemediationQueueService
from app.services.promotion_reopen_queue import PromotionReopenQueueService
from app.services.promotion_review_queue import PromotionReviewQueueService
from app.services.research_promotion_operating_loop import ResearchPromotionOperatingLoopService
from app.services.risk_gate import RiskGate, RiskGateInput
from app.services.rollout_recommendation import RolloutRecommendationService
from app.services.scanner import ScannerService, _runtime_deployment_language
from app.services.scoring import score_strategy
from app.services.score_to_outcome_funnel import ScoreToOutcomeFunnelService
from app.services.strategy_indicators import StrategyIndicatorsService
from app.services.execution_degradation_advisory import ExecutionDegradationAdvisoryService
from app.services.strategy_v2_scalp_experiment import StrategyV2ScalpExperimentService
from app.services.strategy_lifecycle import StrategyLifecycleService
from app.services.strategy_cluster_balance import StrategyClusterBalanceService
from app.services.strategy_v2_lock_validation import StrategyV2LockValidationService
from app.services.strategy_v2_pbo_dsr_artifact_store import StrategyV2PboDsrArtifactStoreService
from app.services.strategy_v2_pbo_dsr_design import StrategyV2PboDsrDesignService
from app.services.strategy_v2_pbo_dsr_metrics import StrategyV2PboDsrMetricsService
from app.services.strategy_v2_pbo_dsr_threshold_runner import StrategyV2PboDsrThresholdRunnerService
from app.services.strategy_v2_pbo_dsr_trial_writer import StrategyV2PboDsrTrialWriterService
from app.services.strategy_v2_stress_replay_assessment import StrategyV2StressReplayAssessmentService
from app.services.strategy_v2_stress_replay_lineage import StrategyV2StressReplayLineageService
from app.services.strategy_v2_stress_replay_lineage_writer import StrategyV2StressReplayLineageWriterService
from app.services.strategy_v2_stress_replay_output_artifacts import StrategyV2StressReplayOutputArtifactsService
from app.services.strategy_v2_stress_replay_prototype_worker import (
    StrategyV2StressReplayPrototypeWorkerService,
)
from app.services.strategy_v2_stress_replay_runner_contract import StrategyV2StressReplayRunnerContractService
from app.services.strategy_v2_stress_validation import StrategyV2StressValidationService
from app.services.strategy_v2_thesis_validation import StrategyV2ThesisValidationService
from app.services.strategy_v2_validation import StrategyV2ValidationService
from app.services.validation_report import ValidationReportService
from app.services.health_check import HealthCheckService
from app.services.zone_engine import ZoneEngine


class StrategyEngine:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.candle_repo = CandleRepository(db)
        self.zone_repo = ZoneRepository(db)
        self.plan_repo = PlanRepository(db)
        self.outcome_repo = OutcomeRepository(db)
        self.fill_repo = ExecutionFillRepository(db)
        self.binance_order_repo = BinanceOrderLedgerRepository(db)
        self.binance_position_repo = BinancePositionRepository(db)
        self.intent_repo = OrderIntentRepository(db)
        self.submission_repo = OrderSubmissionRepository(db)
        self.reconciliation_event_repo = ExecutionReconciliationEventRepository(db)
        self.safety_lock_repo = SafetyLockRepository(db)
        self.family_rollout_repo = FamilyRolloutPolicyRepository(db)
        self.promotion_lifecycle_history_repo = PromotionLifecycleHistoryRepository(db)
        self.validation_artifact_repo = ValidationArtifactRepository(db)
        self.alert_repo = AlertRepository(db)
        self.alert_retry_repo = AlertRetryQueueRepository(db)
        self.metrics_repo = MetricsRepository(db)

        self.market_data = MarketDataService(self.candle_repo)
        self.zone_engine = ZoneEngine()
        self.context_engine = ContextEngine()
        self.plan_generator = PlanGenerator()
        self.feature_importance_service = FeatureImportanceService(self.plan_generator)
        self.feature_calibration_service = FeatureCalibrationService(
            self.plan_generator,
            settings=self.settings,
            plan_repo=self.plan_repo,
            outcome_repo=self.outcome_repo,
        )
        self.parameter_changelog_service = ParameterChangelogService()
        self.notification_dispatcher = NotificationDispatcher(self.settings)
        self.alert_retry_queue = AlertRetryQueueService(
            repo=self.alert_retry_repo,
            alert_repo=self.alert_repo,
            dispatcher=self.notification_dispatcher,
            settings=self.settings,
        )
        self.alert_metrics = AlertMetricsService(
            alert_repo=self.alert_repo,
            retry_repo=self.alert_retry_repo,
            settings=self.settings,
        )
        self.operational_checklist_service = OperationalChecklistService(
            alert_repo=self.alert_repo,
            settings=self.settings,
        )
        self.operating_lock = OperatingLockService(self.settings)
        self.learning = LearningService()
        self.risk_gate = RiskGate()
        self.position_state_machine = PositionStateMachineService(
            plan_repo=self.plan_repo,
            fill_repo=self.fill_repo,
            strategy_version=self.settings.strategy_version,
        )
        self.backtest = BacktestService()
        self.validation_report = ValidationReportService()
        self.strategy_v2_validation = StrategyV2ValidationService(self.settings)
        self.strategy_v2_lock_validation = StrategyV2LockValidationService(self.settings)
        self.strategy_v2_pbo_dsr_artifact_store = StrategyV2PboDsrArtifactStoreService(
            self.settings,
            repo=self.validation_artifact_repo,
        )
        self.strategy_v2_pbo_dsr_design = StrategyV2PboDsrDesignService(self.settings)
        self.strategy_v2_pbo_dsr_trial_writer = StrategyV2PboDsrTrialWriterService(
            self.settings,
            repo=self.validation_artifact_repo,
            fill_repo=self.fill_repo,
            candle_repo=self.candle_repo,
        )
        self.strategy_v2_pbo_dsr_threshold_runner = StrategyV2PboDsrThresholdRunnerService(
            self.settings,
            repo=self.validation_artifact_repo,
            fill_repo=self.fill_repo,
            candle_repo=self.candle_repo,
        )
        self.strategy_v2_pbo_dsr_metrics = StrategyV2PboDsrMetricsService(
            self.settings,
            repo=self.validation_artifact_repo,
        )
        self.strategy_v2_stress_validation = StrategyV2StressValidationService(
            self.settings,
            fill_repo=self.fill_repo,
            candle_repo=self.candle_repo,
        )
        self.strategy_v2_stress_replay_lineage = StrategyV2StressReplayLineageService(
            self.settings,
            plan_repo=self.plan_repo,
            fill_repo=self.fill_repo,
            candle_repo=self.candle_repo,
        )
        self.strategy_v2_stress_replay_assessment = StrategyV2StressReplayAssessmentService(self.settings)
        self.strategy_v2_stress_replay_runner_contract = StrategyV2StressReplayRunnerContractService(self.settings)
        self.strategy_v2_stress_replay_lineage_writer = StrategyV2StressReplayLineageWriterService(
            self.settings,
            plan_repo=self.plan_repo,
            fill_repo=self.fill_repo,
            candle_repo=self.candle_repo,
        )
        self.strategy_v2_stress_replay_prototype_worker = StrategyV2StressReplayPrototypeWorkerService(self.settings)
        self.strategy_v2_stress_replay_output_artifacts = StrategyV2StressReplayOutputArtifactsService(self.settings)
        self.strategy_v2_thesis_validation = StrategyV2ThesisValidationService(
            self.settings,
            fill_repo=self.fill_repo,
        )
        self.execution_quality = ExecutionQualityService(
            plan_repo=self.plan_repo,
            outcome_repo=self.outcome_repo,
            candle_repo=self.candle_repo,
            fill_repo=self.fill_repo,
            settings=self.settings,
        )
        self.execution_friction_measurement = ExecutionFrictionMeasurementService()
        self.forward_stress_regime_validation = ForwardStressRegimeValidationService()
        self.kill_condition_automation = KillConditionAutomationService()
        self.execution_operator_dashboard_service = ExecutionOperatorDashboardService(
            intent_repo=self.intent_repo,
            submission_repo=self.submission_repo,
            reconciliation_repo=self.reconciliation_event_repo,
            position_repo=self.binance_position_repo,
            settings=self.settings,
        )
        self.rollout_policy_service = RolloutPolicyService(
            repo=self.family_rollout_repo,
        )
        self.safety_locks = SafetyLockService(
            repo=self.safety_lock_repo,
            settings=self.settings,
        )
        self.execution_planning = ExecutionPlanningService(
            settings=self.settings,
            rollout_provider=self.rollout_policy_service,
        )
        self.strategy_indicators = StrategyIndicatorsService()
        self.strategy_v2_scalp_experiment = StrategyV2ScalpExperimentService(
            settings=self.settings,
            context_engine=self.context_engine,
            zone_engine=self.zone_engine,
            plan_generator=self.plan_generator,
        )
        self.alpha_research_pipeline = AlphaResearchPipelineService(self.settings)
        self.score_to_outcome_funnel = ScoreToOutcomeFunnelService(
            plan_repo=self.plan_repo,
            outcome_repo=self.outcome_repo,
            fill_repo=self.fill_repo,
            submission_repo=self.submission_repo,
            settings=self.settings,
        )
        self.execution_degradation_advisory = ExecutionDegradationAdvisoryService(self.settings)
        self.family_execution_degradation_advisory = FamilyExecutionDegradationAdvisoryService(self.settings)
        self.mode_advisory = ModeAdvisoryService(self.settings)
        self.multi_strategy_ab = MultiStrategyABExpansionService()
        self.b_continuation_activation = BContinuationActivationService()
        self.strategy_cluster_balance = StrategyClusterBalanceService()
        self.a_strategy_post_cost_edge_validation = AStrategyPostCostEdgeValidationService()
        self.b_continuation_edge_validation = BContinuationEdgeValidationService()
        self.operator_action_priority = OperatorActionPriorityService()
        self.outcome_bucket_granularity = OutcomeBucketGranularityService()
        self.opportunity_capture = OpportunityCaptureService()
        self.positive_evidence_expansion = PositiveEvidenceExpansionService()
        self.auto_promotion_rollout_execution = AutoPromotionRolloutExecutionService()
        self.promotion_governance = PromotionGovernanceService()
        self.promotion_lifecycle_history = PromotionLifecycleHistoryService()
        self.research_promotion_operating_loop = ResearchPromotionOperatingLoopService()
        self.promotion_clearance_tracker = PromotionClearanceTrackerService()
        self.promotion_decision_brief = PromotionDecisionBriefService()
        self.promotion_remediation_queue = PromotionRemediationQueueService()
        self.promotion_reopen_queue = PromotionReopenQueueService()
        self.promotion_review_queue = PromotionReviewQueueService()
        self.rollout_recommendation = RolloutRecommendationService()
        self.strategy_lifecycle = StrategyLifecycleService()
        self.scanner = ScannerService(self.plan_repo, self.candle_repo)
        self.portfolio_budget_report_service = PortfolioBudgetReportService(
            plan_repo=self.plan_repo,
            scanner=self.scanner,
            multi_strategy_ab=self.multi_strategy_ab,
            b_continuation_activation=self.b_continuation_activation,
            strategy_cluster_balance=self.strategy_cluster_balance,
            settings=self.settings,
        )
        self.order_intents = OrderIntentService(
            plan_repo=self.plan_repo,
            intent_repo=self.intent_repo,
            submission_repo=self.submission_repo,
            approval_loader=self._execution_approval_bundle,
            exposure_loader=self._current_exposure_rows,
            settings=self.settings,
        )
        self.execution_coordinator = ExecutionCoordinator(
            plan_repo=self.plan_repo,
            intent_repo=self.intent_repo,
            submission_repo=self.submission_repo,
            approval_loader=self._execution_approval_bundle,
            fill_ingest=self.ingest_execution_fill,
            live_submitter=self.submit_binance_order,
            settings=self.settings,
        )
        self.execution_reconciliation = ExecutionReconciliationService(
            plan_repo=self.plan_repo,
            submission_repo=self.submission_repo,
            binance_order_repo=self.binance_order_repo,
            binance_position_repo=self.binance_position_repo,
            fill_repo=self.fill_repo,
            event_repo=self.reconciliation_event_repo,
            safety_locks=self.safety_locks,
            settings=self.settings,
        )
        self.events = EventBus(db)

    def _consecutive_losses(self, outcomes: list[ZoneOutcome]) -> int:
        losses = 0
        for o in outcomes:
            if o.hit_1r:
                break
            losses += 1
        return losses

    def _operating_lock_snapshot(self, *, now: datetime | None = None) -> OperatingLockSnapshot:
        plans = self.plan_repo.list_recent_global(
            timeframe="5m",
            days=3,
            states=[PlanState.CLOSED.value],
            limit=2000,
        )
        return self.operating_lock.evaluate(plans=plans, now=now)

    def _evaluate_gate(self, *, symbol: str, jump_rate: float) -> tuple[RiskGateState, bool, str, OperatingLockSnapshot]:
        outcomes = self.outcome_repo.list_recent(symbol=symbol, days=30)
        gate = self.risk_gate.evaluate(
            RiskGateInput(
                consecutive_losses=self._consecutive_losses(outcomes),
                jump_rate=jump_rate,
                api_healthy=True,
            )
        )
        operating_lock = self._operating_lock_snapshot()
        if gate.state == RiskGateState.CLOSED:
            return gate.state, gate.can_open_new_trade, gate.reason, operating_lock
        if operating_lock.active and operating_lock.enforced:
            return RiskGateState.CLOSED, False, operating_lock.reason, operating_lock
        return gate.state, gate.can_open_new_trade, gate.reason, operating_lock

    def _today_trade_count(self) -> int:
        start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        return self.plan_repo.count_since(
            timeframe="5m",
            start_ts=start_of_day,
            states=[
                PlanState.ARMED.value,
                PlanState.TRIGGERED.value,
                PlanState.ENTERED.value,
                PlanState.PARTIAL_EXIT.value,
                PlanState.CLOSED.value,
            ],
        )

    def _current_exposure_rows(self) -> list:
        return self.plan_repo.list_exposure_candidates(
            timeframe="5m",
            include_planned=self.settings.portfolio_overlay_include_planned_exposure,
            limit=300,
        )

    def _gate_context_for_symbol(
        self,
        *,
        symbol: str,
    ) -> tuple[ContextSnapshot | None, RiskGateState, str, OperatingLockSnapshot]:
        context = self.current_context(symbol)
        jump_rate = context.jump_rate_5m if context else 0.0
        gate_state, _, gate_reason, operating_lock = self._evaluate_gate(symbol=symbol, jump_rate=jump_rate)
        return context, gate_state, gate_reason, operating_lock

    def _execution_candidate_rows(
        self,
        *,
        symbol: str,
    ) -> tuple[ContextSnapshot | None, list[dict[str, Any]], dict[str, Any]]:
        context, gate_state, gate_reason, operating_lock = self._gate_context_for_symbol(symbol=symbol)
        base_rows = self.scanner.candidate_rows(
            symbols=[symbol],
            risk_state=gate_state,
            plans_per_symbol=max(10, int(self.settings.max_candidate_plans_per_symbol)),
        )
        operating_lock_dict = operating_lock.to_dict()
        deployment_language = _runtime_deployment_language(
            risk_state=gate_state,
            risk_reason=gate_reason,
            operating_lock=operating_lock_dict,
        )
        guidance = self.scanner.session_guidance.snapshot(
            operating_lock=operating_lock_dict,
            strategy_mode=self.scanner.overlay.mode.policy().mode,
        )
        for row in base_rows:
            row["deployment_go_no_go"] = deployment_language["deployment_go_no_go"]
            row["deployment_code"] = deployment_language["deployment_code"]
            row["deployment_message"] = deployment_language["deployment_message"]
            row["risk_reason"] = gate_reason
            row["operating_lock"] = operating_lock_dict
            row["session_guidance"] = dict(guidance)
            row["session_penalty"] = float(guidance.get("soft_penalty", 0.0) or 0.0)
        outcome_inputs_by_symbol = self._outcome_inputs_for_symbols(symbols=[symbol])
        assessed = self.scanner.overlay.assess_rows(
            base_rows,
            existing_exposures=self._current_exposure_rows(),
            today_trade_count=self._today_trade_count(),
            operating_lock=operating_lock_dict,
            outcome_inputs_by_symbol=outcome_inputs_by_symbol,
        )
        return context, assessed, operating_lock_dict

    @staticmethod
    def _empty_runtime_portfolio_budget() -> dict[str, Any]:
        return {
            "accepted_candidates": [],
            "blocked_candidates": [],
            "blocked_reason_counts": {},
            "blocked_gate_group_counts": {},
        }

    def _outcome_inputs_for_symbol(
        self,
        *,
        symbol: str,
        days: int = 180,
        portfolio_budget: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        symbol = str(symbol or "").upper()
        if not symbol:
            return None

        runtime_portfolio_budget = dict(portfolio_budget or self._empty_runtime_portfolio_budget())
        performance_decomposition_summary = self._alpha_research_performance_decomposition(symbol=symbol)
        execution_quality_summary = self.execution_quality.generate(
            symbol=symbol,
            days=days,
            write_report=False,
        )
        score_to_outcome_funnel_summary = self.score_to_outcome_funnel.generate(
            symbol=symbol,
            version=self.settings.strategy_version,
            days=days,
            portfolio_budget=runtime_portfolio_budget,
        )
        execution_degradation_advisory_summary = self.execution_degradation_advisory.generate(
            execution_quality=execution_quality_summary,
            performance_decomposition_summary=performance_decomposition_summary,
            strategy_v2_stress_validation=None,
        )
        family_execution_degradation_advisory_summary = self.family_execution_degradation_advisory.generate(
            execution_quality=execution_quality_summary,
            performance_decomposition_summary=performance_decomposition_summary,
            score_to_outcome_funnel=score_to_outcome_funnel_summary,
        )
        mode_advisory_summary = self.mode_advisory.generate(
            score_to_outcome_funnel=score_to_outcome_funnel_summary,
            execution_degradation_advisory=execution_degradation_advisory_summary,
            performance_decomposition_summary=performance_decomposition_summary,
            alpha_research_evidence_summary={},
            softening_candidate_review={},
            promotion_watchlist={},
        )
        rollout_recommendation_summary = self._rollout_recommendation_summary(
            score_to_outcome_funnel_summary=score_to_outcome_funnel_summary,
            execution_degradation_advisory_summary=execution_degradation_advisory_summary,
            family_execution_degradation_advisory_summary=family_execution_degradation_advisory_summary,
            mode_advisory_summary=mode_advisory_summary,
        )
        return {
            "score_to_outcome_funnel_summary": score_to_outcome_funnel_summary,
            "execution_degradation_advisory_summary": execution_degradation_advisory_summary,
            "family_execution_degradation_advisory_summary": family_execution_degradation_advisory_summary,
            "mode_advisory_summary": mode_advisory_summary,
            "rollout_recommendation_summary": rollout_recommendation_summary,
            "opportunity_capture_summary": self.opportunity_capture.generate(
                score_to_outcome_funnel=score_to_outcome_funnel_summary,
                portfolio_budget=runtime_portfolio_budget,
                execution_quality=execution_quality_summary,
            ),
        }

    def _rollout_recommendation_summary(
        self,
        *,
        score_to_outcome_funnel_summary: dict[str, Any] | None,
        execution_degradation_advisory_summary: dict[str, Any] | None,
        family_execution_degradation_advisory_summary: dict[str, Any] | None,
        mode_advisory_summary: dict[str, Any] | None,
        rollout_policies: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        policies = [dict(item) for item in list(rollout_policies or [])]
        if not policies:
            policies = [item.to_dict() for item in self.rollout_policy_service.list_all()]
        payload = self.rollout_recommendation.generate(
            score_to_outcome_funnel=score_to_outcome_funnel_summary,
            execution_degradation_advisory=execution_degradation_advisory_summary,
            family_execution_degradation_advisory=family_execution_degradation_advisory_summary,
            mode_advisory=mode_advisory_summary,
            rollout_policies=policies,
        )
        return payload if payload else None

    def _opportunity_capture_summary(
        self,
        *,
        score_to_outcome_funnel_summary: dict[str, Any] | None,
        portfolio_budget: dict[str, Any] | None = None,
        execution_quality_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        payload = self.opportunity_capture.generate(
            score_to_outcome_funnel=score_to_outcome_funnel_summary,
            portfolio_budget=portfolio_budget,
            execution_quality=execution_quality_summary,
        )
        return payload if payload else None

    def _outcome_bucket_granularity_summary(
        self,
        *,
        score_to_outcome_funnel_summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = self.outcome_bucket_granularity.generate(
            score_to_outcome_funnel=score_to_outcome_funnel_summary,
        )
        return payload if payload else None

    def _a_strategy_post_cost_edge_validation_summary(
        self,
        *,
        score_to_outcome_funnel_summary: dict[str, Any] | None,
        family_execution_degradation_advisory_summary: dict[str, Any] | None,
        mode_advisory_summary: dict[str, Any] | None,
        outcome_bucket_granularity_summary: dict[str, Any] | None,
        alpha_research_pipeline_summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = self.a_strategy_post_cost_edge_validation.generate(
            score_to_outcome_funnel=score_to_outcome_funnel_summary,
            family_execution_degradation_advisory=family_execution_degradation_advisory_summary,
            mode_advisory=mode_advisory_summary,
            outcome_bucket_granularity=outcome_bucket_granularity_summary,
            alpha_research_pipeline=alpha_research_pipeline_summary,
        )
        return payload if payload else None

    def _recent_reconciliation_summary(
        self,
        *,
        symbol: str | None,
        days: int,
        limit: int = 20,
    ) -> dict[str, Any]:
        events = [
            {
                "severity": getattr(row, "severity", "INFO"),
                "lock_required": bool(getattr(row, "lock_required", False)),
            }
            for row in self.reconciliation_event_repo.list_recent(symbol=symbol, limit=limit, days=days)
        ]
        return self.execution_operator_dashboard_service._reconciliation_summary(events)

    def _execution_friction_measurement_summary(
        self,
        *,
        execution_quality_summary: dict[str, Any] | None,
        recent_reconciliation_summary: dict[str, Any] | None,
        strategy_v2_stress_validation: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = self.execution_friction_measurement.generate(
            execution_quality=execution_quality_summary,
            recent_reconciliation_summary=recent_reconciliation_summary,
            strategy_v2_stress_validation=strategy_v2_stress_validation,
            approval_caps={
                "expected_fee_bps": float(self.settings.taker_fee_bps),
                "max_slippage_bps": float(self.settings.auto_trading_max_slippage_bps),
            },
        )
        return payload if payload else None

    def _b_continuation_edge_validation_summary(
        self,
        *,
        score_to_outcome_funnel_summary: dict[str, Any] | None,
        outcome_bucket_granularity_summary: dict[str, Any] | None,
        family_execution_degradation_advisory_summary: dict[str, Any] | None,
        alpha_research_pipeline_summary: dict[str, Any] | None,
        b_continuation_activation_summary: dict[str, Any] | None,
        multi_strategy_ab_summary: dict[str, Any] | None,
        strategy_cluster_balance_summary: dict[str, Any] | None,
        capital_allocator_summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = self.b_continuation_edge_validation.generate(
            score_to_outcome_funnel=score_to_outcome_funnel_summary,
            outcome_bucket_granularity=outcome_bucket_granularity_summary,
            family_execution_degradation_advisory=family_execution_degradation_advisory_summary,
            alpha_research_pipeline=alpha_research_pipeline_summary,
            b_continuation_activation=b_continuation_activation_summary,
            multi_strategy_ab_summary=multi_strategy_ab_summary,
            strategy_cluster_balance=strategy_cluster_balance_summary,
            capital_allocator=capital_allocator_summary,
        )
        return payload if payload else None

    def _forward_stress_regime_validation_summary(
        self,
        *,
        walk_forward_summary: dict[str, Any] | None,
        strategy_v2_validation_summary: dict[str, Any] | None,
        strategy_v2_stress_validation_summary: dict[str, Any] | None,
        strategy_v2_stress_replay_assessment_summary: dict[str, Any] | None,
        strategy_v2_stress_replay_lineage_summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = self.forward_stress_regime_validation.generate(
            walk_forward=walk_forward_summary,
            strategy_v2_validation=strategy_v2_validation_summary,
            strategy_v2_stress_validation=strategy_v2_stress_validation_summary,
            strategy_v2_stress_replay_assessment=strategy_v2_stress_replay_assessment_summary,
            strategy_v2_stress_replay_lineage=strategy_v2_stress_replay_lineage_summary,
        )
        return payload if payload else None

    def _kill_condition_automation_summary(
        self,
        *,
        strategy_metrics: dict[str, Any] | None,
        safety_state: dict[str, Any] | None,
        execution_friction_measurement_summary: dict[str, Any] | None,
        forward_stress_regime_validation_summary: dict[str, Any] | None,
        recent_reconciliation_summary: dict[str, Any] | None,
        execution_degradation_advisory_summary: dict[str, Any] | None,
        family_execution_degradation_advisory_summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = self.kill_condition_automation.generate(
            strategy_metrics=strategy_metrics,
            safety_state=safety_state,
            execution_friction_measurement=execution_friction_measurement_summary,
            forward_stress_regime_validation=forward_stress_regime_validation_summary,
            recent_reconciliation_summary=recent_reconciliation_summary,
            execution_degradation_advisory=execution_degradation_advisory_summary,
            family_execution_degradation_advisory=family_execution_degradation_advisory_summary,
        )
        return payload if payload else None

    def _strategy_lifecycle_summary(
        self,
        *,
        alpha_research_pipeline_summary: dict[str, Any] | None,
        score_to_outcome_funnel_summary: dict[str, Any] | None,
        family_execution_degradation_advisory_summary: dict[str, Any] | None,
        mode_advisory_summary: dict[str, Any] | None,
        rollout_recommendation_summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = self.strategy_lifecycle.generate(
            alpha_research_pipeline=alpha_research_pipeline_summary,
            score_to_outcome_funnel=score_to_outcome_funnel_summary,
            family_execution_degradation_advisory=family_execution_degradation_advisory_summary,
            mode_advisory=mode_advisory_summary,
            rollout_recommendation=rollout_recommendation_summary,
        )
        return payload if payload else None

    def _positive_evidence_expansion_summary(
        self,
        *,
        score_to_outcome_funnel_summary: dict[str, Any] | None,
        family_execution_degradation_advisory_summary: dict[str, Any] | None,
        mode_advisory_summary: dict[str, Any] | None,
        rollout_recommendation_summary: dict[str, Any] | None,
        strategy_lifecycle_summary: dict[str, Any] | None,
        capital_allocator_summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = self.positive_evidence_expansion.generate(
            score_to_outcome_funnel=score_to_outcome_funnel_summary,
            family_execution_degradation_advisory=family_execution_degradation_advisory_summary,
            mode_advisory=mode_advisory_summary,
            rollout_recommendation=rollout_recommendation_summary,
            strategy_lifecycle=strategy_lifecycle_summary,
            capital_allocator=capital_allocator_summary,
        )
        return payload if payload else None

    def _promotion_governance_summary(
        self,
        *,
        strategy_lifecycle_summary: dict[str, Any] | None,
        rollout_recommendation_summary: dict[str, Any] | None,
        positive_evidence_expansion_summary: dict[str, Any] | None,
        outcome_bucket_granularity_summary: dict[str, Any] | None,
        family_execution_degradation_advisory_summary: dict[str, Any] | None,
        mode_advisory_summary: dict[str, Any] | None,
        capital_allocator_summary: dict[str, Any] | None,
        score_to_outcome_funnel_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        payload = self.promotion_governance.generate(
            strategy_lifecycle=strategy_lifecycle_summary,
            rollout_recommendation=rollout_recommendation_summary,
            positive_evidence_expansion=positive_evidence_expansion_summary,
            outcome_bucket_granularity=outcome_bucket_granularity_summary,
            family_execution_degradation_advisory=family_execution_degradation_advisory_summary,
            mode_advisory=mode_advisory_summary,
            capital_allocator=capital_allocator_summary,
            score_to_outcome_funnel=score_to_outcome_funnel_summary,
        )
        return payload if payload else None

    def _promotion_review_queue_summary(
        self,
        *,
        promotion_governance_summary: dict[str, Any] | None,
        strategy_lifecycle_summary: dict[str, Any] | None,
        positive_evidence_expansion_summary: dict[str, Any] | None,
        capital_allocator_summary: dict[str, Any] | None,
        family_execution_degradation_advisory_summary: dict[str, Any] | None,
        score_to_outcome_funnel_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        payload = self.promotion_review_queue.generate(
            promotion_governance=promotion_governance_summary,
            strategy_lifecycle=strategy_lifecycle_summary,
            positive_evidence_expansion=positive_evidence_expansion_summary,
            capital_allocator=capital_allocator_summary,
            family_execution_degradation_advisory=family_execution_degradation_advisory_summary,
            score_to_outcome_funnel=score_to_outcome_funnel_summary,
        )
        return payload if payload else None

    def _promotion_remediation_queue_summary(
        self,
        *,
        promotion_governance_summary: dict[str, Any] | None,
        promotion_review_queue_summary: dict[str, Any] | None,
        strategy_lifecycle_summary: dict[str, Any] | None,
        positive_evidence_expansion_summary: dict[str, Any] | None,
        outcome_bucket_granularity_summary: dict[str, Any] | None,
        family_execution_degradation_advisory_summary: dict[str, Any] | None,
        rollout_recommendation_summary: dict[str, Any] | None,
        capital_allocator_summary: dict[str, Any] | None,
        alpha_research_pipeline_summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = self.promotion_remediation_queue.generate(
            promotion_governance=promotion_governance_summary,
            promotion_review_queue=promotion_review_queue_summary,
            strategy_lifecycle=strategy_lifecycle_summary,
            positive_evidence_expansion=positive_evidence_expansion_summary,
            outcome_bucket_granularity=outcome_bucket_granularity_summary,
            family_execution_degradation_advisory=family_execution_degradation_advisory_summary,
            rollout_recommendation=rollout_recommendation_summary,
            capital_allocator=capital_allocator_summary,
            alpha_research_pipeline=alpha_research_pipeline_summary,
        )
        return payload if payload else None

    def _promotion_clearance_tracker_summary(
        self,
        *,
        promotion_governance_summary: dict[str, Any] | None,
        promotion_review_queue_summary: dict[str, Any] | None,
        promotion_remediation_queue_summary: dict[str, Any] | None,
        strategy_lifecycle_summary: dict[str, Any] | None,
        family_execution_degradation_advisory_summary: dict[str, Any] | None,
        rollout_recommendation_summary: dict[str, Any] | None,
        outcome_bucket_granularity_summary: dict[str, Any] | None,
        positive_evidence_expansion_summary: dict[str, Any] | None,
        capital_allocator_summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = self.promotion_clearance_tracker.generate(
            promotion_governance=promotion_governance_summary,
            promotion_review_queue=promotion_review_queue_summary,
            promotion_remediation_queue=promotion_remediation_queue_summary,
            strategy_lifecycle=strategy_lifecycle_summary,
            family_execution_degradation_advisory=family_execution_degradation_advisory_summary,
            rollout_recommendation=rollout_recommendation_summary,
            outcome_bucket_granularity=outcome_bucket_granularity_summary,
            positive_evidence_expansion=positive_evidence_expansion_summary,
            capital_allocator=capital_allocator_summary,
        )
        return payload if payload else None

    def _promotion_reopen_queue_summary(
        self,
        *,
        promotion_governance_summary: dict[str, Any] | None,
        promotion_review_queue_summary: dict[str, Any] | None,
        promotion_remediation_queue_summary: dict[str, Any] | None,
        promotion_clearance_tracker_summary: dict[str, Any] | None,
        strategy_lifecycle_summary: dict[str, Any] | None,
        positive_evidence_expansion_summary: dict[str, Any] | None,
        capital_allocator_summary: dict[str, Any] | None,
        family_execution_degradation_advisory_summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = self.promotion_reopen_queue.generate(
            promotion_governance=promotion_governance_summary,
            promotion_review_queue=promotion_review_queue_summary,
            promotion_remediation_queue=promotion_remediation_queue_summary,
            promotion_clearance_tracker=promotion_clearance_tracker_summary,
            strategy_lifecycle=strategy_lifecycle_summary,
            positive_evidence_expansion=positive_evidence_expansion_summary,
            capital_allocator=capital_allocator_summary,
            family_execution_degradation_advisory=family_execution_degradation_advisory_summary,
        )
        return payload if payload else None

    def _promotion_decision_brief_summary(
        self,
        *,
        promotion_governance_summary: dict[str, Any] | None,
        promotion_review_queue_summary: dict[str, Any] | None,
        promotion_remediation_queue_summary: dict[str, Any] | None,
        promotion_clearance_tracker_summary: dict[str, Any] | None,
        promotion_reopen_queue_summary: dict[str, Any] | None,
        strategy_lifecycle_summary: dict[str, Any] | None,
        positive_evidence_expansion_summary: dict[str, Any] | None,
        capital_allocator_summary: dict[str, Any] | None,
        family_execution_degradation_advisory_summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = self.promotion_decision_brief.generate(
            promotion_governance=promotion_governance_summary,
            promotion_review_queue=promotion_review_queue_summary,
            promotion_remediation_queue=promotion_remediation_queue_summary,
            promotion_clearance_tracker=promotion_clearance_tracker_summary,
            promotion_reopen_queue=promotion_reopen_queue_summary,
            strategy_lifecycle=strategy_lifecycle_summary,
            positive_evidence_expansion=positive_evidence_expansion_summary,
            capital_allocator=capital_allocator_summary,
            family_execution_degradation_advisory=family_execution_degradation_advisory_summary,
        )
        return payload if payload else None

    def _multi_strategy_ab_summary(
        self,
        *,
        portfolio_budget: dict[str, Any] | None = None,
        scanner_rows: list[dict[str, Any]] | None = None,
        score_to_outcome_funnel_summary: dict[str, Any] | None = None,
        family_execution_degradation_advisory_summary: dict[str, Any] | None = None,
        rollout_recommendation_summary: dict[str, Any] | None = None,
        strategy_lifecycle_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        payload = self.multi_strategy_ab.generate(
            portfolio_budget=portfolio_budget,
            scanner_rows=scanner_rows,
            score_to_outcome_funnel=score_to_outcome_funnel_summary,
            family_execution_degradation_advisory=family_execution_degradation_advisory_summary,
            rollout_recommendation=rollout_recommendation_summary,
            strategy_lifecycle=strategy_lifecycle_summary,
        )
        return payload if payload else None

    def _b_continuation_activation_summary(
        self,
        *,
        multi_strategy_ab_summary: dict[str, Any] | None,
        score_to_outcome_funnel_summary: dict[str, Any] | None,
        family_execution_degradation_advisory_summary: dict[str, Any] | None,
        rollout_recommendation_summary: dict[str, Any] | None,
        strategy_lifecycle_summary: dict[str, Any] | None,
        promotion_governance_summary: dict[str, Any] | None,
        promotion_clearance_tracker_summary: dict[str, Any] | None,
        promotion_reopen_queue_summary: dict[str, Any] | None,
        promotion_decision_brief_summary: dict[str, Any] | None,
        auto_promotion_rollout_execution_summary: dict[str, Any] | None,
        positive_evidence_expansion_summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = self.b_continuation_activation.generate(
            multi_strategy_ab=multi_strategy_ab_summary,
            score_to_outcome_funnel=score_to_outcome_funnel_summary,
            family_execution_degradation_advisory=family_execution_degradation_advisory_summary,
            rollout_recommendation=rollout_recommendation_summary,
            strategy_lifecycle=strategy_lifecycle_summary,
            promotion_governance=promotion_governance_summary,
            promotion_clearance_tracker=promotion_clearance_tracker_summary,
            promotion_reopen_queue=promotion_reopen_queue_summary,
            promotion_decision_brief=promotion_decision_brief_summary,
            auto_promotion_rollout_execution=auto_promotion_rollout_execution_summary,
            positive_evidence_expansion=positive_evidence_expansion_summary,
        )
        return payload if payload else None

    def _strategy_cluster_balance_summary(
        self,
        *,
        portfolio_budget: dict[str, Any] | None,
        multi_strategy_ab_summary: dict[str, Any] | None,
        b_continuation_activation_summary: dict[str, Any] | None,
        capital_allocator_summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = self.strategy_cluster_balance.generate(
            portfolio_budget=portfolio_budget,
            multi_strategy_ab=multi_strategy_ab_summary,
            b_continuation_activation=b_continuation_activation_summary,
            capital_allocator=capital_allocator_summary,
        )
        return payload if payload else None

    def _promotion_lifecycle_history_summary(
        self,
        *,
        persist: bool,
        strategy_lifecycle_summary: dict[str, Any] | None,
        promotion_governance_summary: dict[str, Any] | None,
        promotion_review_queue_summary: dict[str, Any] | None,
        promotion_remediation_queue_summary: dict[str, Any] | None,
        promotion_clearance_tracker_summary: dict[str, Any] | None,
        promotion_reopen_queue_summary: dict[str, Any] | None,
        promotion_decision_brief_summary: dict[str, Any] | None,
        auto_promotion_rollout_execution_summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        try:
            payload = self.promotion_lifecycle_history.generate(
                repo=self.promotion_lifecycle_history_repo,
                persist=persist,
                strategy_lifecycle=strategy_lifecycle_summary,
                promotion_governance=promotion_governance_summary,
                promotion_review_queue=promotion_review_queue_summary,
                promotion_remediation_queue=promotion_remediation_queue_summary,
                promotion_clearance_tracker=promotion_clearance_tracker_summary,
                promotion_reopen_queue=promotion_reopen_queue_summary,
                promotion_decision_brief=promotion_decision_brief_summary,
                auto_promotion_rollout_execution=auto_promotion_rollout_execution_summary,
            )
        except Exception:
            if persist:
                self.db.rollback()
            payload = self.promotion_lifecycle_history.generate(
                repo=self.promotion_lifecycle_history_repo,
                persist=False,
                strategy_lifecycle=strategy_lifecycle_summary,
                promotion_governance=promotion_governance_summary,
                promotion_review_queue=promotion_review_queue_summary,
                promotion_remediation_queue=promotion_remediation_queue_summary,
                promotion_clearance_tracker=promotion_clearance_tracker_summary,
                promotion_reopen_queue=promotion_reopen_queue_summary,
                promotion_decision_brief=promotion_decision_brief_summary,
                auto_promotion_rollout_execution=auto_promotion_rollout_execution_summary,
            )
        return payload if payload else None

    def _auto_promotion_rollout_execution_summary(
        self,
        *,
        promotion_governance_summary: dict[str, Any] | None,
        promotion_review_queue_summary: dict[str, Any] | None,
        promotion_remediation_queue_summary: dict[str, Any] | None,
        promotion_clearance_tracker_summary: dict[str, Any] | None,
        promotion_reopen_queue_summary: dict[str, Any] | None,
        promotion_decision_brief_summary: dict[str, Any] | None,
        rollout_recommendation_summary: dict[str, Any] | None,
        strategy_lifecycle_summary: dict[str, Any] | None,
        family_execution_degradation_advisory_summary: dict[str, Any] | None,
        mode_advisory_summary: dict[str, Any] | None,
        score_to_outcome_funnel_summary: dict[str, Any] | None,
        execution_degradation_advisory_summary: dict[str, Any] | None,
        positive_evidence_expansion_summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        outcome_control_trace = summarize_outcome_control_trace(
            build_outcome_control_trace(
                execution_degradation_advisory=execution_degradation_advisory_summary,
                family_execution_degradation_advisory=family_execution_degradation_advisory_summary,
                mode_advisory=mode_advisory_summary,
                score_to_outcome_funnel=score_to_outcome_funnel_summary,
            )
        )
        payload = self.auto_promotion_rollout_execution.generate(
            promotion_governance=promotion_governance_summary,
            promotion_review_queue=promotion_review_queue_summary,
            promotion_remediation_queue=promotion_remediation_queue_summary,
            promotion_clearance_tracker=promotion_clearance_tracker_summary,
            promotion_reopen_queue=promotion_reopen_queue_summary,
            promotion_decision_brief=promotion_decision_brief_summary,
            rollout_recommendation=rollout_recommendation_summary,
            strategy_lifecycle=strategy_lifecycle_summary,
            family_execution_degradation_advisory=family_execution_degradation_advisory_summary,
            mode_advisory=mode_advisory_summary,
            outcome_control_trace=outcome_control_trace,
            positive_evidence_expansion=positive_evidence_expansion_summary,
        )
        return payload if payload else None

    def _research_promotion_operating_loop_summary(
        self,
        *,
        alpha_research_pipeline_summary: dict[str, Any] | None,
        strategy_lifecycle_summary: dict[str, Any] | None,
        promotion_governance_summary: dict[str, Any] | None,
        promotion_review_queue_summary: dict[str, Any] | None,
        promotion_decision_brief_summary: dict[str, Any] | None,
        auto_promotion_rollout_execution_summary: dict[str, Any] | None,
        promotion_lifecycle_history_summary: dict[str, Any] | None,
        family_execution_degradation_advisory_summary: dict[str, Any] | None,
        multi_strategy_ab_summary: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = self.research_promotion_operating_loop.generate(
            alpha_research_pipeline=alpha_research_pipeline_summary,
            strategy_lifecycle=strategy_lifecycle_summary,
            promotion_governance=promotion_governance_summary,
            promotion_review_queue=promotion_review_queue_summary,
            promotion_decision_brief=promotion_decision_brief_summary,
            auto_promotion_rollout_execution=auto_promotion_rollout_execution_summary,
            promotion_lifecycle_history=promotion_lifecycle_history_summary,
            family_execution_degradation_advisory=family_execution_degradation_advisory_summary,
            multi_strategy_ab=multi_strategy_ab_summary,
        )
        return payload if payload else None

    def _outcome_inputs_for_symbols(
        self,
        *,
        symbols: list[str],
        days: int = 180,
        portfolio_budget_by_symbol: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        payloads: dict[str, dict[str, Any]] = {}
        normalized_symbols = sorted({str(symbol or "").upper() for symbol in symbols if str(symbol or "").strip()})
        for symbol in normalized_symbols:
            runtime_portfolio_budget = dict((portfolio_budget_by_symbol or {}).get(symbol) or {})
            payload = self._outcome_inputs_for_symbol(
                symbol=symbol,
                days=days,
                portfolio_budget=runtime_portfolio_budget,
            )
            if payload:
                payloads[symbol] = payload
        return payloads

    def _runtime_candidate_symbols(
        self,
        *,
        symbols: list[str],
        risk_state: RiskGateState,
    ) -> list[str]:
        rows = self.scanner.candidate_rows(
            symbols=symbols,
            risk_state=risk_state,
            plans_per_symbol=1,
        )
        return sorted({str(row.get("symbol") or "").upper() for row in rows if row.get("symbol")})

    def _approval_outcome_inputs(
        self,
        *,
        symbol: str,
        candidate_rows: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        portfolio_budget = {
            "accepted_candidates": [dict(row) for row in candidate_rows if bool(row.get("accepted"))],
            "blocked_candidates": [dict(row) for row in candidate_rows if not bool(row.get("accepted"))],
            "blocked_reason_counts": {},
            "blocked_gate_group_counts": {},
        }
        return self._outcome_inputs_for_symbol(
            symbol=symbol,
            days=180,
            portfolio_budget=portfolio_budget,
        )

    def _execution_approval_bundle(
        self,
        plan_id: str,
        requested_execution_mode: ExecutionMode | str | None,
        *,
        strict_requested_mode: bool = True,
        paper_lineage_override: bool = False,
    ) -> dict[str, Any]:
        plan = self.plan_repo.get(plan_id)
        if plan is None:
            raise ValueError("plan_not_found")
        requested_mode = ExecutionPlanningService.coerce_execution_mode(
            requested_execution_mode,
            default=self.execution_planning.active_execution_mode(),
        )
        context, candidate_rows, _ = self._execution_candidate_rows(symbol=plan.symbol)
        candidate_row = next((row for row in candidate_rows if row.get("plan_id") == plan.plan_id), None)
        family = str((plan.validity or {}).get("strategy_family") or "legacy_zone_plan").lower()
        operating_lock = dict((candidate_row or {}).get("operating_lock") or {})
        session_name = ExecutionPlanningService._session_name(candidate_row or {}, operating_lock)
        exposure_rows = self._current_exposure_rows()
        outcome_inputs = self._approval_outcome_inputs(symbol=plan.symbol, candidate_rows=candidate_rows)
        executable_plan = self.execution_planning.build_executable_plan(
            plan=plan,
            context=context,
            candidate_row=candidate_row,
            execution_mode=requested_mode,
        )
        metrics = self.metrics(symbol=plan.symbol, version=self.settings.strategy_version)
        safety_state = self.safety_locks.safety_state(
            symbol=plan.symbol,
            family=family,
            session_name=session_name,
        )
        approval = self.execution_planning.approve(
            plan=plan,
            executable_plan=executable_plan,
            candidate_row=candidate_row,
            metrics=metrics,
            requested_execution_mode=requested_mode,
            strict_requested_mode=strict_requested_mode,
            safety_state=safety_state,
            current_exposure_count=len(exposure_rows),
            daily_new_entry_count=self._today_trade_count(),
            paper_lineage_override=paper_lineage_override,
            outcome_inputs=outcome_inputs,
        )
        return {
            "plan": plan,
            "candidate_row": candidate_row,
            "executable_plan": executable_plan,
            "metrics": metrics,
            "safety_state": safety_state,
            "outcome_inputs": outcome_inputs,
            "approval": approval,
        }

    def execution_plan_preview(self, *, plan_id: str, paper_lineage_override: bool = False) -> dict[str, Any]:
        bundle = self._execution_approval_bundle(
            plan_id,
            None,
            strict_requested_mode=False,
            paper_lineage_override=paper_lineage_override,
        )
        return bundle["executable_plan"]

    def approve_execution_plan(self, *, plan_id: str, paper_lineage_override: bool = False) -> dict[str, Any]:
        bundle = self._execution_approval_bundle(
            plan_id,
            None,
            strict_requested_mode=False,
            paper_lineage_override=paper_lineage_override,
        )
        return bundle["approval"]

    @staticmethod
    def _order_intent_to_dict(row) -> dict[str, Any]:
        approval = dict(row.approval_snapshot or {})
        return {
            "intent_id": row.intent_id,
            "plan_id": row.plan_id,
            "symbol": row.symbol,
            "strategy_family": row.strategy_family,
            "execution_mode": row.execution_mode,
            "approval_state": row.approval_state,
            "submit_decision": row.submit_decision,
            "decision_reason_code": row.decision_reason_code,
            "decision_reason_message": row.decision_reason_message,
            "allowed_execution_mode": approval.get("allowed_execution_mode", ""),
            "deployment_go_no_go": approval.get("deployment_go_no_go", ""),
            "deployment_code": approval.get("deployment_code", ""),
            "playbook_go_no_go": approval.get("playbook_go_no_go", ""),
            "playbook_code": approval.get("playbook_code", ""),
            "playbook_action": approval.get("playbook_action", ""),
            "playbook_message": approval.get("playbook_message", ""),
            "paper_lineage_override_applied": bool(approval.get("paper_lineage_override_applied")),
            "paper_lineage_override_reason": approval.get("paper_lineage_override_reason", ""),
            "paper_lineage_override_source": approval.get("paper_lineage_override_source", ""),
            "source_of_truth_hint": "execution_approval_snapshot",
            "thesis_fingerprint": dict(row.thesis_fingerprint or {}),
            "dedupe_result": dict(row.dedupe_result or {}),
            "session_guidance": dict(row.session_guidance or {}),
            "quality_snapshot": dict(row.quality_snapshot or {}),
            "approval": approval,
            "created_at": row.created_at,
        }

    @staticmethod
    def _submission_to_dict(row, *, fill_results: list[dict[str, Any]], idempotent_reuse: bool) -> dict[str, Any]:
        return {
            "submission_id": row.submission_id,
            "intent_id": row.intent_id,
            "symbol": row.symbol,
            "execution_mode": row.execution_mode,
            "state": row.state,
            "submit_status": row.submit_status,
            "message": row.message,
            "client_order_id": row.client_order_id,
            "exchange_order_id": row.exchange_order_id,
            "adapter": row.adapter,
            "requested_live": bool(row.requested_live),
            "attachments": dict(row.attachments or {}),
            "fill_results": fill_results,
            "submitted_at": row.submitted_at,
            "acknowledged_at": row.acknowledged_at,
            "cancelled_at": row.cancelled_at,
            "idempotent_reuse": bool(idempotent_reuse),
        }

    def create_order_intent(
        self,
        *,
        plan_id: str,
        execution_mode: ExecutionMode | str,
        paper_lineage_override: bool = False,
    ) -> dict[str, Any]:
        requested_mode = ExecutionPlanningService.coerce_execution_mode(
            execution_mode,
            default=self.execution_planning.active_execution_mode(),
        )
        row = self.order_intents.create_intent(
            plan_id=plan_id,
            execution_mode=requested_mode,
            paper_lineage_override=paper_lineage_override,
        )
        self.db.commit()
        self.db.refresh(row)
        return self._order_intent_to_dict(row)

    def submit_order_intent(self, *, intent_id: str, live: bool = False, paper_scenario: str | None = None) -> dict[str, Any]:
        row, fill_results, idempotent_reuse = self.execution_coordinator.submit_intent(
            intent_id=intent_id,
            live=live,
            paper_scenario=paper_scenario,
        )
        self.db.commit()
        self.db.refresh(row)
        return self._submission_to_dict(row, fill_results=fill_results, idempotent_reuse=idempotent_reuse)

    def reconcile_execution(self, *, symbol: str, auto_resolve: bool = False, apply_lock: bool = False) -> dict[str, Any]:
        result = self.execution_reconciliation.reconcile(
            symbol=symbol,
            auto_resolve=auto_resolve,
            apply_lock=apply_lock,
        )
        self.db.commit()
        return {
            "symbol": result.symbol,
            "mismatches": [
                {
                    "mismatch_type": item["mismatch_type"],
                    "severity": item["severity"].value,
                    "message": item["message"],
                    "local_snapshot": item["local_snapshot"],
                    "exchange_snapshot": item["exchange_snapshot"],
                }
                for item in result.mismatches
            ],
            "healthy": not bool(result.mismatches),
            "highest_severity": result.highest_severity.value,
            "lock_required": result.lock_required,
            "auto_resolve_requested": result.auto_resolve_requested,
            "auto_resolve_applied": result.auto_resolve_applied,
            "apply_lock_requested": result.apply_lock_requested,
            "events_recorded": result.events_recorded,
            "generated_at": result.generated_at,
        }

    def _safety_state_payload(
        self,
        *,
        symbol: str | None = None,
        family: str | None = None,
        session_name: str | None = None,
    ) -> dict[str, Any]:
        payload = self.safety_locks.safety_state(
            symbol=symbol,
            family=family,
            session_name=session_name,
        )
        payload["rollout_policies"] = [item.to_dict() for item in self.rollout_policy_service.list_all()]
        return payload

    def safety_state(
        self,
        *,
        symbol: str | None = None,
        family: str | None = None,
        session_name: str | None = None,
    ) -> dict[str, Any]:
        return self._safety_state_payload(symbol=symbol, family=family, session_name=session_name)

    def execution_operator_dashboard(
        self,
        *,
        symbol: str | None = None,
        universe: str,
        portfolio_limit: int = 10,
        intent_limit: int = 10,
        reconcile_limit: int = 10,
        days: int = 7,
    ) -> dict[str, Any]:
        safety_state = self._safety_state_payload(symbol=symbol)
        portfolio_summary = self.portfolio_budget_report(
            universe=universe,
            limit=portfolio_limit,
            write_report=False,
        )
        alert_summary = self.alert_metrics_report(days=days, write_report=False)
        execution_quality_summary = None
        if symbol:
            execution_quality_summary = self.execution_quality_report(
                symbol=symbol,
                days=days,
                write_report=False,
            )
        recent_reconciliation_summary = self._recent_reconciliation_summary(
            symbol=symbol,
            days=days,
            limit=reconcile_limit,
        )
        execution_friction_measurement_summary = self._execution_friction_measurement_summary(
            execution_quality_summary=execution_quality_summary,
            recent_reconciliation_summary=recent_reconciliation_summary,
            strategy_v2_stress_validation=None,
        )
        strategy_metrics_summary = self.metrics(symbol=symbol, version=self.settings.strategy_version) if symbol else None
        analysis_symbol = self._alpha_research_analysis_symbol(
            portfolio_budget=portfolio_summary,
            focus_symbol=symbol,
        )
        performance_decomposition_summary = self._alpha_research_performance_decomposition(symbol=analysis_symbol)
        if not analysis_symbol:
            score_to_outcome_funnel_summary = None
            execution_degradation_advisory_summary = None
            family_execution_degradation_advisory_summary = None
            mode_advisory_summary = None
        else:
            score_to_outcome_funnel_summary = self.score_to_outcome_funnel.generate(
                symbol=analysis_symbol,
                version=self.settings.strategy_version,
                days=days,
                portfolio_budget=portfolio_summary,
            )
            execution_degradation_advisory_summary = self.execution_degradation_advisory.generate(
                execution_quality=execution_quality_summary,
                performance_decomposition_summary=performance_decomposition_summary,
                strategy_v2_stress_validation=None,
            )
            family_execution_degradation_advisory_summary = self.family_execution_degradation_advisory.generate(
                execution_quality=execution_quality_summary,
                performance_decomposition_summary=performance_decomposition_summary,
                score_to_outcome_funnel=score_to_outcome_funnel_summary,
            )
        alpha_research_pipeline_summary = self.alpha_research_pipeline.generate(
            universe=universe,
            portfolio_budget=portfolio_summary,
            focus_symbol=symbol,
            analysis_symbol=analysis_symbol,
            performance_decomposition_summary=performance_decomposition_summary,
            score_to_outcome_funnel=score_to_outcome_funnel_summary,
            execution_degradation_advisory=execution_degradation_advisory_summary,
            write_report=False,
        )
        forward_stress_regime_validation_summary = None
        kill_condition_automation_summary = None
        if analysis_symbol:
            validation_outcomes = self.outcome_repo.list_recent(symbol=analysis_symbol, days=180)
            walk_forward_summary = self.backtest.walk_forward(
                validation_outcomes,
                train_months=self.settings.validation_wf_train_months,
                test_months=self.settings.validation_wf_test_months,
            ).__dict__
            validation_plans = self.plan_repo.list_recent(symbol=analysis_symbol, days=180)
            strategy_v2_validation_for_generalization = self.strategy_v2_validation.generate(
                symbol=analysis_symbol,
                version=self.settings.strategy_version,
                plans=validation_plans,
                write_report=False,
            )
            strategy_v2_stress_validation_for_generalization = self.strategy_v2_stress_validation.generate(
                symbol=analysis_symbol,
                version=self.settings.strategy_version,
                plans=validation_plans,
                write_report=False,
            )
            strategy_v2_stress_replay_lineage_for_generalization = self.strategy_v2_stress_replay_lineage.generate(
                symbol=analysis_symbol,
                version=self.settings.strategy_version,
                write_report=False,
            )
            strategy_v2_stress_replay_assessment_for_generalization = (
                self.strategy_v2_stress_replay_assessment.generate(
                    symbol=analysis_symbol,
                    version=self.settings.strategy_version,
                    stress_validation=strategy_v2_stress_validation_for_generalization,
                    stress_replay_lineage=strategy_v2_stress_replay_lineage_for_generalization,
                    stress_replay_output_artifacts={},
                    pbo_dsr_metrics={},
                    write_report=False,
                )
            )
            forward_stress_regime_validation_summary = self._forward_stress_regime_validation_summary(
                walk_forward_summary=walk_forward_summary,
                strategy_v2_validation_summary=strategy_v2_validation_for_generalization,
                strategy_v2_stress_validation_summary=strategy_v2_stress_validation_for_generalization,
                strategy_v2_stress_replay_assessment_summary=(
                    strategy_v2_stress_replay_assessment_for_generalization
                ),
                strategy_v2_stress_replay_lineage_summary=(
                    strategy_v2_stress_replay_lineage_for_generalization
                ),
            )
        if symbol:
            kill_condition_automation_summary = self._kill_condition_automation_summary(
                strategy_metrics=strategy_metrics_summary,
                safety_state=safety_state,
                execution_friction_measurement_summary=execution_friction_measurement_summary,
                forward_stress_regime_validation_summary=forward_stress_regime_validation_summary,
                recent_reconciliation_summary=recent_reconciliation_summary,
                execution_degradation_advisory_summary=execution_degradation_advisory_summary,
                family_execution_degradation_advisory_summary=family_execution_degradation_advisory_summary,
            )
        if analysis_symbol:
            mode_advisory_summary = self.mode_advisory.generate(
                score_to_outcome_funnel=score_to_outcome_funnel_summary,
                execution_degradation_advisory=execution_degradation_advisory_summary,
                performance_decomposition_summary=performance_decomposition_summary,
                alpha_research_evidence_summary=dict(
                    alpha_research_pipeline_summary.get("alpha_research_evidence_summary") or {}
                ),
                softening_candidate_review=dict(
                    alpha_research_pipeline_summary.get("softening_candidate_review") or {}
                ),
                promotion_watchlist=dict(alpha_research_pipeline_summary.get("promotion_watchlist") or {}),
            )
        rollout_recommendation_summary = self._rollout_recommendation_summary(
            score_to_outcome_funnel_summary=score_to_outcome_funnel_summary,
            execution_degradation_advisory_summary=execution_degradation_advisory_summary,
            family_execution_degradation_advisory_summary=family_execution_degradation_advisory_summary,
            mode_advisory_summary=mode_advisory_summary,
            rollout_policies=list(safety_state.get("rollout_policies") or []),
        )
        strategy_lifecycle_summary = self._strategy_lifecycle_summary(
            alpha_research_pipeline_summary=alpha_research_pipeline_summary,
            score_to_outcome_funnel_summary=score_to_outcome_funnel_summary,
            family_execution_degradation_advisory_summary=family_execution_degradation_advisory_summary,
            mode_advisory_summary=mode_advisory_summary,
            rollout_recommendation_summary=rollout_recommendation_summary,
        )
        positive_evidence_expansion_summary = self._positive_evidence_expansion_summary(
            score_to_outcome_funnel_summary=score_to_outcome_funnel_summary,
            family_execution_degradation_advisory_summary=family_execution_degradation_advisory_summary,
            mode_advisory_summary=mode_advisory_summary,
            rollout_recommendation_summary=rollout_recommendation_summary,
            strategy_lifecycle_summary=strategy_lifecycle_summary,
            capital_allocator_summary=dict(portfolio_summary.get("capital_allocator_summary") or {}) or None,
        )
        multi_strategy_ab_summary = self._multi_strategy_ab_summary(
            portfolio_budget=portfolio_summary,
            score_to_outcome_funnel_summary=score_to_outcome_funnel_summary,
            family_execution_degradation_advisory_summary=family_execution_degradation_advisory_summary,
            rollout_recommendation_summary=rollout_recommendation_summary,
            strategy_lifecycle_summary=strategy_lifecycle_summary,
        )
        opportunity_capture_summary = self._opportunity_capture_summary(
            score_to_outcome_funnel_summary=score_to_outcome_funnel_summary,
            portfolio_budget=portfolio_summary,
            execution_quality_summary=execution_quality_summary,
        )
        edge_experiment_summary = summarize_edge_experiment_review(
            build_edge_experiment_review(score_to_outcome_funnel=score_to_outcome_funnel_summary)
        )
        edge_evolution_rule_summary = summarize_edge_evolution_rule(
            build_edge_evolution_rule(
                edge_experiment_review=edge_experiment_summary,
                rollout_recommendation=rollout_recommendation_summary,
                strategy_lifecycle=strategy_lifecycle_summary,
                kill_condition_automation=kill_condition_automation_summary,
            )
        )
        review_followup_ledger_summary = summarize_split_review_followup_ledger(
            symbol=symbol or "",
            universe=str(portfolio_summary.get("universe") or "usdc_perp_top30"),
        )
        operator_action_priority_summary = self.operator_action_priority.generate(
            dashboard={
                "playbook_action": portfolio_summary.get("playbook_action", ""),
                "playbook_message": portfolio_summary.get("playbook_message", ""),
                "new_entries_allowed": bool(safety_state.get("new_entry_allowed", False)),
                "blocking_reason_code": str(safety_state.get("blocking_reason_code", "")),
                "signal_funnel": {
                    "execution_degradation_advisory": execution_degradation_advisory_summary,
                    "family_execution_degradation_advisory": family_execution_degradation_advisory_summary,
                    "mode_advisory": mode_advisory_summary,
                    "edge_experiment_review": edge_experiment_summary,
                    "edge_evolution_rule": edge_evolution_rule_summary,
                    "review_followup_ledger": review_followup_ledger_summary,
                    "alpha_research_recommended_action": (
                        dict(alpha_research_pipeline_summary.get("recommended_action_summary") or {})
                        if alpha_research_pipeline_summary
                        else {}
                    ),
                    "alpha_research_softening_review": (
                        dict(alpha_research_pipeline_summary.get("softening_candidate_review") or {})
                        if alpha_research_pipeline_summary
                        else {}
                    ),
                    "alpha_research_promotion_watchlist": (
                        dict(alpha_research_pipeline_summary.get("promotion_watchlist") or {})
                        if alpha_research_pipeline_summary
                        else {}
                    ),
                    "opportunity_capture": opportunity_capture_summary,
                },
            },
            checklist=None,
            validation=None,
        )
        outcome_bucket_granularity_summary = self._outcome_bucket_granularity_summary(
            score_to_outcome_funnel_summary=score_to_outcome_funnel_summary,
        )
        a_strategy_post_cost_edge_validation_summary = self._a_strategy_post_cost_edge_validation_summary(
            score_to_outcome_funnel_summary=score_to_outcome_funnel_summary,
            family_execution_degradation_advisory_summary=family_execution_degradation_advisory_summary,
            mode_advisory_summary=mode_advisory_summary,
            outcome_bucket_granularity_summary=outcome_bucket_granularity_summary,
            alpha_research_pipeline_summary=alpha_research_pipeline_summary,
        )
        promotion_governance_summary = self._promotion_governance_summary(
            strategy_lifecycle_summary=strategy_lifecycle_summary,
            rollout_recommendation_summary=rollout_recommendation_summary,
            positive_evidence_expansion_summary=positive_evidence_expansion_summary,
            outcome_bucket_granularity_summary=outcome_bucket_granularity_summary,
            family_execution_degradation_advisory_summary=family_execution_degradation_advisory_summary,
            mode_advisory_summary=mode_advisory_summary,
            capital_allocator_summary=dict(portfolio_summary.get("capital_allocator_summary") or {}) or None,
            score_to_outcome_funnel_summary=score_to_outcome_funnel_summary,
        )
        promotion_review_queue_summary = self._promotion_review_queue_summary(
            promotion_governance_summary=promotion_governance_summary,
            strategy_lifecycle_summary=strategy_lifecycle_summary,
            positive_evidence_expansion_summary=positive_evidence_expansion_summary,
            capital_allocator_summary=dict(portfolio_summary.get("capital_allocator_summary") or {}) or None,
            family_execution_degradation_advisory_summary=family_execution_degradation_advisory_summary,
            score_to_outcome_funnel_summary=score_to_outcome_funnel_summary,
        )
        promotion_remediation_queue_summary = self._promotion_remediation_queue_summary(
            promotion_governance_summary=promotion_governance_summary,
            promotion_review_queue_summary=promotion_review_queue_summary,
            strategy_lifecycle_summary=strategy_lifecycle_summary,
            positive_evidence_expansion_summary=positive_evidence_expansion_summary,
            outcome_bucket_granularity_summary=outcome_bucket_granularity_summary,
            family_execution_degradation_advisory_summary=family_execution_degradation_advisory_summary,
            rollout_recommendation_summary=rollout_recommendation_summary,
            capital_allocator_summary=dict(portfolio_summary.get("capital_allocator_summary") or {}) or None,
            alpha_research_pipeline_summary=alpha_research_pipeline_summary,
        )
        promotion_clearance_tracker_summary = self._promotion_clearance_tracker_summary(
            promotion_governance_summary=promotion_governance_summary,
            promotion_review_queue_summary=promotion_review_queue_summary,
            promotion_remediation_queue_summary=promotion_remediation_queue_summary,
            strategy_lifecycle_summary=strategy_lifecycle_summary,
            family_execution_degradation_advisory_summary=family_execution_degradation_advisory_summary,
            rollout_recommendation_summary=rollout_recommendation_summary,
            outcome_bucket_granularity_summary=outcome_bucket_granularity_summary,
            positive_evidence_expansion_summary=positive_evidence_expansion_summary,
            capital_allocator_summary=dict(portfolio_summary.get("capital_allocator_summary") or {}) or None,
        )
        promotion_reopen_queue_summary = self._promotion_reopen_queue_summary(
            promotion_governance_summary=promotion_governance_summary,
            promotion_review_queue_summary=promotion_review_queue_summary,
            promotion_remediation_queue_summary=promotion_remediation_queue_summary,
            promotion_clearance_tracker_summary=promotion_clearance_tracker_summary,
            strategy_lifecycle_summary=strategy_lifecycle_summary,
            positive_evidence_expansion_summary=positive_evidence_expansion_summary,
            capital_allocator_summary=dict(portfolio_summary.get("capital_allocator_summary") or {}) or None,
            family_execution_degradation_advisory_summary=family_execution_degradation_advisory_summary,
        )
        promotion_decision_brief_summary = self._promotion_decision_brief_summary(
            promotion_governance_summary=promotion_governance_summary,
            promotion_review_queue_summary=promotion_review_queue_summary,
            promotion_remediation_queue_summary=promotion_remediation_queue_summary,
            promotion_clearance_tracker_summary=promotion_clearance_tracker_summary,
            promotion_reopen_queue_summary=promotion_reopen_queue_summary,
            strategy_lifecycle_summary=strategy_lifecycle_summary,
            positive_evidence_expansion_summary=positive_evidence_expansion_summary,
            capital_allocator_summary=dict(portfolio_summary.get("capital_allocator_summary") or {}) or None,
            family_execution_degradation_advisory_summary=family_execution_degradation_advisory_summary,
        )
        auto_promotion_rollout_execution_summary = self._auto_promotion_rollout_execution_summary(
            promotion_governance_summary=promotion_governance_summary,
            promotion_review_queue_summary=promotion_review_queue_summary,
            promotion_remediation_queue_summary=promotion_remediation_queue_summary,
            promotion_clearance_tracker_summary=promotion_clearance_tracker_summary,
            promotion_reopen_queue_summary=promotion_reopen_queue_summary,
            promotion_decision_brief_summary=promotion_decision_brief_summary,
            rollout_recommendation_summary=rollout_recommendation_summary,
            strategy_lifecycle_summary=strategy_lifecycle_summary,
            family_execution_degradation_advisory_summary=family_execution_degradation_advisory_summary,
            mode_advisory_summary=mode_advisory_summary,
            score_to_outcome_funnel_summary=score_to_outcome_funnel_summary,
            execution_degradation_advisory_summary=execution_degradation_advisory_summary,
            positive_evidence_expansion_summary=positive_evidence_expansion_summary,
        )
        b_continuation_activation_summary = self._b_continuation_activation_summary(
            multi_strategy_ab_summary=multi_strategy_ab_summary,
            score_to_outcome_funnel_summary=score_to_outcome_funnel_summary,
            family_execution_degradation_advisory_summary=family_execution_degradation_advisory_summary,
            rollout_recommendation_summary=rollout_recommendation_summary,
            strategy_lifecycle_summary=strategy_lifecycle_summary,
            promotion_governance_summary=promotion_governance_summary,
            promotion_clearance_tracker_summary=promotion_clearance_tracker_summary,
            promotion_reopen_queue_summary=promotion_reopen_queue_summary,
            promotion_decision_brief_summary=promotion_decision_brief_summary,
            auto_promotion_rollout_execution_summary=auto_promotion_rollout_execution_summary,
            positive_evidence_expansion_summary=positive_evidence_expansion_summary,
        )
        strategy_cluster_balance_summary = self._strategy_cluster_balance_summary(
            portfolio_budget=portfolio_summary,
            multi_strategy_ab_summary=multi_strategy_ab_summary,
            b_continuation_activation_summary=b_continuation_activation_summary,
            capital_allocator_summary=dict(portfolio_summary.get("capital_allocator_summary") or {}) or None,
        )
        b_continuation_edge_validation_summary = self._b_continuation_edge_validation_summary(
            score_to_outcome_funnel_summary=score_to_outcome_funnel_summary,
            outcome_bucket_granularity_summary=outcome_bucket_granularity_summary,
            family_execution_degradation_advisory_summary=family_execution_degradation_advisory_summary,
            alpha_research_pipeline_summary=alpha_research_pipeline_summary,
            b_continuation_activation_summary=b_continuation_activation_summary,
            multi_strategy_ab_summary=multi_strategy_ab_summary,
            strategy_cluster_balance_summary=strategy_cluster_balance_summary,
            capital_allocator_summary=dict(portfolio_summary.get("capital_allocator_summary") or {}) or None,
        )
        promotion_lifecycle_history_summary = self._promotion_lifecycle_history_summary(
            persist=False,
            strategy_lifecycle_summary=strategy_lifecycle_summary,
            promotion_governance_summary=promotion_governance_summary,
            promotion_review_queue_summary=promotion_review_queue_summary,
            promotion_remediation_queue_summary=promotion_remediation_queue_summary,
            promotion_clearance_tracker_summary=promotion_clearance_tracker_summary,
            promotion_reopen_queue_summary=promotion_reopen_queue_summary,
            promotion_decision_brief_summary=promotion_decision_brief_summary,
            auto_promotion_rollout_execution_summary=auto_promotion_rollout_execution_summary,
        )
        research_promotion_operating_loop_summary = self._research_promotion_operating_loop_summary(
            alpha_research_pipeline_summary=alpha_research_pipeline_summary,
            strategy_lifecycle_summary=strategy_lifecycle_summary,
            promotion_governance_summary=promotion_governance_summary,
            promotion_review_queue_summary=promotion_review_queue_summary,
            promotion_decision_brief_summary=promotion_decision_brief_summary,
            auto_promotion_rollout_execution_summary=auto_promotion_rollout_execution_summary,
            promotion_lifecycle_history_summary=promotion_lifecycle_history_summary,
            family_execution_degradation_advisory_summary=family_execution_degradation_advisory_summary,
            multi_strategy_ab_summary=multi_strategy_ab_summary,
        )
        return self.execution_operator_dashboard_service.generate(
            symbol=symbol,
            days=days,
            intent_limit=intent_limit,
            reconcile_limit=reconcile_limit,
            safety_state=safety_state,
            portfolio_summary=portfolio_summary,
            alert_summary=alert_summary,
            execution_quality_summary=execution_quality_summary,
            alpha_research_pipeline_summary=alpha_research_pipeline_summary,
            score_to_outcome_funnel_summary=score_to_outcome_funnel_summary,
            execution_degradation_advisory_summary=execution_degradation_advisory_summary,
            family_execution_degradation_advisory_summary=family_execution_degradation_advisory_summary,
            mode_advisory_summary=mode_advisory_summary,
            operator_action_priority_summary=operator_action_priority_summary,
            rollout_recommendation_summary=rollout_recommendation_summary,
            strategy_lifecycle_summary=strategy_lifecycle_summary,
            promotion_governance_summary=promotion_governance_summary,
            promotion_review_queue_summary=promotion_review_queue_summary,
            promotion_remediation_queue_summary=promotion_remediation_queue_summary,
            promotion_clearance_tracker_summary=promotion_clearance_tracker_summary,
            promotion_reopen_queue_summary=promotion_reopen_queue_summary,
            promotion_decision_brief_summary=promotion_decision_brief_summary,
            auto_promotion_rollout_execution_summary=auto_promotion_rollout_execution_summary,
            performance_decomposition_summary=performance_decomposition_summary,
            b_continuation_activation_summary=b_continuation_activation_summary,
            b_continuation_edge_validation_summary=b_continuation_edge_validation_summary,
            strategy_cluster_balance_summary=strategy_cluster_balance_summary,
            a_strategy_post_cost_edge_validation_summary=a_strategy_post_cost_edge_validation_summary,
            promotion_lifecycle_history_summary=promotion_lifecycle_history_summary,
            research_promotion_operating_loop_summary=research_promotion_operating_loop_summary,
            multi_strategy_ab_summary=multi_strategy_ab_summary,
            positive_evidence_expansion_summary=positive_evidence_expansion_summary,
            outcome_bucket_granularity_summary=outcome_bucket_granularity_summary,
            opportunity_capture_summary=opportunity_capture_summary,
            execution_friction_measurement_summary=execution_friction_measurement_summary,
            forward_stress_regime_validation_summary=forward_stress_regime_validation_summary,
            kill_condition_automation_summary=kill_condition_automation_summary,
        )

    def set_kill_switch(
        self,
        *,
        active: bool,
        reason_message: str,
        unlock_at: datetime | None = None,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        self.safety_locks.set_kill_switch(
            active=active,
            reason_message=reason_message or "Manual kill switch updated from control plane.",
            unlock_at=unlock_at,
            metadata={"updated_by": updated_by or "control_plane"},
        )
        self.db.commit()
        return self._safety_state_payload()

    def apply_kill_condition_automation(
        self,
        *,
        symbol: str | None,
        universe: str,
        family: str | None = None,
        session_name: str | None = None,
        days: int = 30,
        portfolio_limit: int = 10,
        intent_limit: int = 10,
        reconcile_limit: int = 10,
        dry_run: bool = True,
        allow_live_write: bool = False,
        arm_token: str | None = None,
        updated_by: str | None = None,
        unlock_at: datetime | None = None,
    ) -> dict[str, Any]:
        safety_state_before = self._safety_state_payload(symbol=symbol, family=family, session_name=session_name)
        dashboard = self.execution_operator_dashboard(
            symbol=symbol,
            universe=universe,
            portfolio_limit=portfolio_limit,
            intent_limit=intent_limit,
            reconcile_limit=reconcile_limit,
            days=days,
        )
        summary = dict(((dashboard.get("signal_funnel") or {}).get("kill_condition_automation")) or {})
        kill_condition_state = str(summary.get("kill_condition_state") or "observe_only")
        automation_bias = str(summary.get("automation_bias") or "observe_only")
        trigger_axis = str(summary.get("trigger_axis") or "")
        active_manual_override = bool(summary.get("active_manual_override", False))
        configured_arm_token = str(self.settings.kill_condition_automation_arm_token or "")
        live_enabled = bool(self.settings.kill_condition_automation_live_enabled)
        arm_valid = bool(configured_arm_token and arm_token and arm_token == configured_arm_token)

        action_target = "none"
        if kill_condition_state == "throttle_review":
            action_target = "auto_throttle"
        elif kill_condition_state == "close_only_review":
            action_target = "close_only"
        elif kill_condition_state == "kill_switch_review":
            action_target = "kill_switch"

        eligible_for_live_write = bool(
            allow_live_write
            and not dry_run
            and live_enabled
            and arm_valid
            and not active_manual_override
            and action_target in {"close_only", "kill_switch"}
        )
        effective_write_scope = "armed_live_write" if eligible_for_live_write else str(
            summary.get("write_scope") or ("none" if active_manual_override else "proposal_only")
        )
        action_reason_code = ""
        action_reason_message = ""
        action_applied = False
        safety_state_after = dict(safety_state_before)

        if action_target != "none":
            action_reason_code = f"auto_kill_condition_{action_target}"
            action_reason_message = (
                f"Auto kill-condition {action_target} review applied: "
                f"trigger_axis={trigger_axis or 'none'}; state={kill_condition_state}; "
                f"summary={summary.get('summary') or 'n/a'}"
            )

        if eligible_for_live_write and action_target == "close_only":
            self.safety_locks.set_close_only(
                active=True,
                reason_message=action_reason_message,
                unlock_at=unlock_at,
                metadata={
                    "updated_by": updated_by or "kill_condition_automation",
                    "auto_reason_code": action_reason_code,
                    "kill_condition_state": kill_condition_state,
                    "trigger_axis": trigger_axis,
                },
            )
            self.db.commit()
            action_applied = True
            safety_state_after = self._safety_state_payload(symbol=symbol, family=family, session_name=session_name)
        elif eligible_for_live_write and action_target == "kill_switch":
            self.safety_locks.set_kill_switch(
                active=True,
                reason_message=action_reason_message,
                unlock_at=unlock_at,
                metadata={
                    "updated_by": updated_by or "kill_condition_automation",
                    "auto_reason_code": action_reason_code,
                    "kill_condition_state": kill_condition_state,
                    "trigger_axis": trigger_axis,
                },
            )
            self.db.commit()
            action_applied = True
            safety_state_after = self._safety_state_payload(symbol=symbol, family=family, session_name=session_name)

        return {
            "generated_at": datetime.now(timezone.utc),
            "symbol": symbol.upper() if symbol else None,
            "universe": universe,
            "dry_run": bool(dry_run),
            "allow_live_write": bool(allow_live_write),
            "arm_valid": bool(arm_valid),
            "explicit_arm_required": True,
            "eligible_for_live_write": eligible_for_live_write,
            "kill_condition_state": kill_condition_state,
            "automation_bias": automation_bias,
            "trigger_axis": trigger_axis,
            "effective_write_scope": effective_write_scope,
            "action_target": action_target,
            "action_reason_code": action_reason_code,
            "action_reason_message": action_reason_message,
            "action_applied": action_applied,
            "kill_condition_automation_summary": summary,
            "safety_state_before": safety_state_before,
            "safety_state_after": safety_state_after,
        }

    def set_close_only(
        self,
        *,
        active: bool,
        reason_message: str,
        unlock_at: datetime | None = None,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        self.safety_locks.set_close_only(
            active=active,
            reason_message=reason_message or "Manual close-only mode updated from control plane.",
            unlock_at=unlock_at,
            metadata={"updated_by": updated_by or "control_plane"},
        )
        self.db.commit()
        return self._safety_state_payload()

    def upsert_rollout_policy(
        self,
        *,
        family: str,
        live_enabled: bool,
        max_execution_mode: ExecutionMode | str,
        max_risk_r: float,
        allowed_sessions: list[str],
        min_quality_score: float,
        updated_by: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        policy = self.rollout_policy_service.upsert(
            family=family,
            live_enabled=live_enabled,
            max_execution_mode=max_execution_mode,
            max_risk_r=max_risk_r,
            allowed_sessions=allowed_sessions,
            min_quality_score=min_quality_score,
            updated_by=updated_by,
            notes=notes,
        )
        self.db.commit()
        return policy.to_dict()

    @staticmethod
    def _fmt_number(value: Any, *, decimals: int = 4) -> str:
        try:
            return f"{float(value):.{decimals}f}"
        except (TypeError, ValueError):
            return str(value or "")

    @staticmethod
    def _maybe_float(value: Any) -> float | None:
        if value in (None, "", "None"):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _maybe_int(value: Any) -> int | None:
        if value in (None, "", "None"):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_utc(value: Any) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        return datetime.now(timezone.utc)

    @staticmethod
    def _default_binance_client_order_id(plan_id: str | None = None) -> str:
        prefix = "te"
        if plan_id:
            prefix = plan_id.replace("plan_", "")[:18] or "te"
        return f"{prefix}-{uuid4().hex[:8]}"

    def _normalize_binance_order_payload(
        self,
        *,
        action: str,
        symbol: str,
        requested_live: bool,
        raw: dict[str, Any],
        side: str | None = None,
        order_type: str | None = None,
        price: float | None = None,
        quantity: float | None = None,
        time_in_force: str | None = None,
        reduce_only: bool | None = None,
        client_order_id: str | None = None,
        plan_id: str | None = None,
    ) -> dict[str, Any]:
        live_enabled = bool(self.settings.binance_trade_live_enabled)
        status = raw.get("status")
        if not status and action == "submit" and not requested_live:
            status = "TEST_ACCEPTED"
        return {
            "action": action,
            "mode": "live" if requested_live else "test",
            "requested_live": requested_live,
            "live_enabled": live_enabled,
            "test_order": not requested_live,
            "symbol": str(raw.get("symbol") or symbol).upper(),
            "plan_id": plan_id,
            "order_id": self._maybe_int(raw.get("orderId")),
            "client_order_id": str(raw.get("clientOrderId") or client_order_id or ""),
            "status": str(status or ""),
            "side": str(raw.get("side") or side or ""),
            "order_type": str(raw.get("type") or order_type or ""),
            "price": self._maybe_float(raw.get("price")) if raw.get("price") not in (None, "") else price,
            "orig_qty": self._maybe_float(raw.get("origQty")) if raw.get("origQty") not in (None, "") else quantity,
            "executed_qty": self._maybe_float(raw.get("executedQty")),
            "reduce_only": bool(raw.get("reduceOnly")) if raw.get("reduceOnly") is not None else reduce_only,
            "time_in_force": str(raw.get("timeInForce") or time_in_force or ""),
            "raw": raw,
        }

    def _persist_binance_order_payload(
        self,
        *,
        payload: dict[str, Any],
        event_type: str | None = None,
        event_ts: datetime | None = None,
        trade_id: int | None = None,
    ) -> dict[str, Any]:
        client_order_id = str(payload.get("client_order_id") or "")
        if not client_order_id:
            return {}
        row = self.binance_order_repo.upsert(
            client_order_id=client_order_id,
            exchange_order_id=self._maybe_int(payload.get("order_id")),
            plan_id=payload.get("plan_id"),
            symbol=str(payload.get("symbol") or ""),
            side=str(payload.get("side") or ""),
            order_type=str(payload.get("order_type") or ""),
            status=str(payload.get("status") or ""),
            reduce_only=bool(payload.get("reduce_only")),
            requested_live=bool(payload.get("requested_live")),
            live_enabled=bool(payload.get("live_enabled")),
            test_order=bool(payload.get("test_order")),
            price=self._maybe_float(payload.get("price")),
            orig_qty=self._maybe_float(payload.get("orig_qty")),
            executed_qty=self._maybe_float(payload.get("executed_qty")),
            time_in_force=str(payload.get("time_in_force") or ""),
            last_event_type=event_type,
            last_trade_id=trade_id,
            last_event_ts=event_ts,
            raw=dict(payload.get("raw") or payload),
        )
        self.db.flush()
        return {
            "client_order_id": row.client_order_id,
            "exchange_order_id": row.exchange_order_id,
            "plan_id": row.plan_id,
            "symbol": row.symbol,
            "status": row.status,
            "reduce_only": bool(row.reduce_only),
            "requested_live": bool(row.requested_live),
            "test_order": bool(row.test_order),
            "last_event_type": row.last_event_type,
            "last_trade_id": row.last_trade_id,
        }

    def _resolve_plan_id_from_binance_order(self, *, client_order_id: str | None, order_id: int | None) -> str | None:
        row = None
        if client_order_id:
            row = self.binance_order_repo.get(client_order_id)
        if row is None and order_id is not None:
            row = self.binance_order_repo.get_by_exchange_order_id(order_id)
        return row.plan_id if row is not None else None

    @staticmethod
    def _position_row_to_dict(row: Any) -> dict[str, Any]:
        return {
            "position_key": row.position_key,
            "symbol": row.symbol,
            "position_side": row.position_side,
            "position_amt": float(row.position_amt),
            "entry_price": float(row.entry_price),
            "break_even_price": float(row.break_even_price),
            "mark_price": float(row.mark_price),
            "liquidation_price": float(row.liquidation_price),
            "unrealized_pnl": float(row.unrealized_pnl),
            "notional": float(row.notional),
            "leverage": int(row.leverage),
            "margin_type": row.margin_type,
            "isolated_wallet": float(row.isolated_wallet),
            "update_ts": row.update_ts.isoformat(),
            "raw": dict(row.raw or {}),
        }

    def _upsert_binance_positions(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        model_rows = []
        from app.db.models import BinancePositionSnapshot

        for row in rows:
            snapshot = BinancePositionSnapshot(**row)
            model_rows.append(snapshot)
            normalized.append(self._position_row_to_dict(snapshot))
        self.binance_position_repo.upsert_many(model_rows)
        self.db.flush()
        return normalized

    @staticmethod
    def _infer_binance_fill_id(event: dict[str, Any]) -> str:
        trade_id = event.get("trade_id")
        order_id = event.get("order_id")
        execution_type = str(event.get("execution_type") or "event").lower()
        if trade_id is not None:
            return f"binance_trade_{trade_id}"
        return f"binance_order_{order_id}_{execution_type}"

    def _infer_exit_reason_from_binance_event(self, event: dict[str, Any]) -> str | None:
        if not bool(event.get("reduce_only")):
            return None
        order_type = str(event.get("order_type") or "").upper()
        if "TAKE_PROFIT" in order_type:
            return "target_tp1"
        if "STOP" in order_type:
            return "stop_loss"
        return "manual_flatten"

    def _infer_fill_stage_from_binance_event(
        self,
        *,
        event: dict[str, Any],
        plan: Any | None,
        current_positions: list[dict[str, Any]],
    ) -> ExecutionFillStage | None:
        last_fill_qty = float(event.get("last_fill_qty") or 0.0)
        last_fill_price = float(event.get("last_fill_price") or 0.0)
        if last_fill_qty <= 0.0 or last_fill_price <= 0.0:
            return None
        if not bool(event.get("reduce_only")):
            return ExecutionFillStage.ENTRY

        symbol = str(event.get("symbol") or "")
        matching = [row for row in current_positions if row.get("symbol") == symbol]
        remaining_amt = None
        if plan is not None and matching:
            side = "LONG" if str(plan.direction).lower() == "long" else "SHORT"
            side_rows = [row for row in matching if str(row.get("position_side") or "BOTH").upper() in {side, "BOTH"}]
            target_row = side_rows[0] if side_rows else matching[0]
            remaining_amt = abs(float(target_row.get("position_amt") or 0.0))
        elif matching:
            remaining_amt = abs(float(matching[0].get("position_amt") or 0.0))

        if remaining_amt is not None:
            return ExecutionFillStage.CLOSED if remaining_amt <= 1e-10 else ExecutionFillStage.PARTIAL_EXIT
        return ExecutionFillStage.PARTIAL_EXIT

    @staticmethod
    def _submission_state_from_binance_status(status: str | None) -> OrderLifecycleState:
        mapping = {
            "PARTIALLY_FILLED": OrderLifecycleState.PARTIALLY_FILLED,
            "FILLED": OrderLifecycleState.FILLED,
            "CANCELED": OrderLifecycleState.CANCELLED,
            "CANCELLED": OrderLifecycleState.CANCELLED,
            "REJECTED": OrderLifecycleState.REJECTED,
            "EXPIRED": OrderLifecycleState.CANCELLED,
        }
        return mapping.get(str(status or "").upper(), OrderLifecycleState.ACKNOWLEDGED)

    def _sync_submission_from_binance_event(self, *, normalized: dict[str, Any]) -> dict[str, Any] | None:
        client_order_id = str(normalized.get("client_order_id") or "")
        if not client_order_id:
            return None

        submission = self.submission_repo.get_by_client_order_id(client_order_id)
        if submission is None:
            return None

        status = str(normalized.get("status") or "").upper()
        next_state = self._submission_state_from_binance_status(status)
        event_ts = self._to_utc(normalized.get("event_ts"))
        message = {
            OrderLifecycleState.ACKNOWLEDGED: "Binance user-stream acknowledged submission state.",
            OrderLifecycleState.PARTIALLY_FILLED: "Binance user-stream marked submission as partially filled.",
            OrderLifecycleState.FILLED: "Binance user-stream marked submission as filled.",
            OrderLifecycleState.CANCELLED: "Binance user-stream marked submission as cancelled.",
            OrderLifecycleState.REJECTED: "Binance user-stream marked submission as rejected.",
        }[next_state]
        self.submission_repo.transition(
            submission,
            state=next_state.value,
            submit_status=status or next_state.value,
            message=message,
            raw={
                **dict(submission.raw or {}),
                "binance_user_stream_status": status,
                "binance_execution_type": str(normalized.get("execution_type") or ""),
                "binance_event_ts": event_ts.isoformat(),
            },
            acknowledged_at=event_ts if next_state in {
                OrderLifecycleState.ACKNOWLEDGED,
                OrderLifecycleState.PARTIALLY_FILLED,
                OrderLifecycleState.FILLED,
            } else submission.acknowledged_at,
            cancelled_at=event_ts if next_state in {
                OrderLifecycleState.CANCELLED,
                OrderLifecycleState.REJECTED,
            } else submission.cancelled_at,
            exchange_order_id=str(normalized.get("order_id") or submission.exchange_order_id or ""),
        )
        return {
            "submission_id": submission.submission_id,
            "client_order_id": client_order_id,
            "state": next_state.value,
            "submit_status": status or next_state.value,
            "terminal": next_state in {
                OrderLifecycleState.CANCELLED,
                OrderLifecycleState.REJECTED,
                OrderLifecycleState.FILLED,
            },
        }

    def submit_binance_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
        client_order_id: str | None = None,
        plan_id: str | None = None,
        live: bool = False,
        new_order_resp_type: str = "RESULT",
    ) -> dict[str, Any]:
        effective_client_order_id = client_order_id or self._default_binance_client_order_id(plan_id)
        raw = self.market_data.binance.submit_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            time_in_force=time_in_force,
            reduce_only=reduce_only,
            client_order_id=effective_client_order_id,
            live=live,
            new_order_resp_type=new_order_resp_type,
        )
        normalized = self._normalize_binance_order_payload(
            action="submit",
            symbol=symbol,
            requested_live=live,
            raw=raw,
            side=side,
            order_type=order_type,
            price=price,
            quantity=quantity,
            time_in_force=time_in_force,
            reduce_only=reduce_only,
            client_order_id=effective_client_order_id,
            plan_id=plan_id,
        )
        self._persist_binance_order_payload(payload=normalized, event_type="submit")
        self.db.commit()
        return normalized
        

    def query_binance_order(
        self,
        *,
        symbol: str,
        order_id: int | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        raw = self.market_data.binance.query_order(
            symbol=symbol,
            order_id=order_id,
            client_order_id=client_order_id,
        )
        normalized = self._normalize_binance_order_payload(
            action="query",
            symbol=symbol,
            requested_live=True,
            raw=raw,
            client_order_id=client_order_id,
        )
        self._persist_binance_order_payload(payload=normalized, event_type="query")
        self.db.commit()
        return normalized

    def cancel_binance_order(
        self,
        *,
        symbol: str,
        order_id: int | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        raw = self.market_data.binance.cancel_order(
            symbol=symbol,
            order_id=order_id,
            client_order_id=client_order_id,
        )
        normalized = self._normalize_binance_order_payload(
            action="cancel",
            symbol=symbol,
            requested_live=True,
            raw=raw,
            client_order_id=client_order_id,
        )
        self._persist_binance_order_payload(payload=normalized, event_type="cancel")
        self.db.commit()
        return normalized

    def create_binance_user_stream_listen_key(self) -> dict[str, Any]:
        payload = self.market_data.binance.create_user_stream_listen_key()
        return {
            "action": "create",
            "listen_key": payload["listen_key"],
            "raw": payload.get("raw") or {},
        }

    def keepalive_binance_user_stream_listen_key(self, *, listen_key: str) -> dict[str, Any]:
        payload = self.market_data.binance.keepalive_user_stream_listen_key(listen_key)
        return {
            "action": "keepalive",
            "listen_key": payload["listen_key"],
            "raw": payload.get("raw") or {},
        }

    def close_binance_user_stream_listen_key(self, *, listen_key: str) -> dict[str, Any]:
        payload = self.market_data.binance.close_user_stream_listen_key(listen_key)
        return {
            "action": "close",
            "listen_key": payload["listen_key"],
            "closed": bool(payload.get("closed")),
            "raw": payload.get("raw") or {},
        }

    def sync_binance_positions(self, *, symbol: str | None = None) -> dict[str, Any]:
        rows = [self.market_data.binance.normalize_position_risk_row(row) for row in self.market_data.binance.fetch_position_risk(symbol)]
        normalized = self._upsert_binance_positions(rows)
        self.db.commit()
        open_positions = [row for row in normalized if abs(float(row.get("position_amt") or 0.0)) > 1e-10]
        return {
            "symbol": symbol.upper() if symbol else None,
            "synced": len(normalized),
            "open_positions": len(open_positions),
            "positions": normalized,
        }

    def list_binance_positions(self, *, symbol: str | None = None, open_only: bool = False) -> dict[str, Any]:
        rows = self.binance_position_repo.list_open(symbol=symbol) if open_only else self.binance_position_repo.list_all(symbol=symbol)
        payload = [self._position_row_to_dict(row) for row in rows]
        return {
            "symbol": symbol.upper() if symbol else None,
            "open_only": bool(open_only),
            "count": len(payload),
            "positions": payload,
        }

    def ingest_binance_user_stream_event(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = (
            dict(payload)
            if "kind" in payload and "event_type" in payload
            else self.market_data.binance.normalize_user_stream_message(payload)
        )
        kind = str(normalized.get("kind") or "unknown")
        if kind == "account_update":
            positions = self._upsert_binance_positions(list(normalized.get("positions") or []))
            self.db.commit()
            return {
                "accepted": True,
                "kind": kind,
                "event_type": normalized.get("event_type"),
                "symbol": None,
                "plan_id": None,
                "client_order_id": "",
                "order_id": None,
                "fill_ingest": None,
                "position_sync": {
                    "synced": len(positions),
                    "open_positions": len([row for row in positions if abs(float(row.get("position_amt") or 0.0)) > 1e-10]),
                    "positions": positions,
                },
            }

        if kind != "order_trade_update":
            return {
                "accepted": False,
                "kind": kind,
                "event_type": normalized.get("event_type"),
                "reason": "unsupported_user_stream_event",
            }

        plan_id = self._resolve_plan_id_from_binance_order(
            client_order_id=str(normalized.get("client_order_id") or ""),
            order_id=self._maybe_int(normalized.get("order_id")),
        )
        order_payload = {
            "action": "user_stream",
            "mode": "live",
            "requested_live": True,
            "live_enabled": bool(self.settings.binance_trade_live_enabled),
            "test_order": False,
            "symbol": str(normalized.get("symbol") or ""),
            "plan_id": plan_id,
            "order_id": normalized.get("order_id"),
            "client_order_id": str(normalized.get("client_order_id") or ""),
            "status": str(normalized.get("status") or ""),
            "side": str(normalized.get("side") or ""),
            "order_type": str(normalized.get("order_type") or ""),
            "price": self._maybe_float(normalized.get("avg_price")) or self._maybe_float(normalized.get("last_fill_price")),
            "orig_qty": self._maybe_float(normalized.get("original_qty")),
            "executed_qty": self._maybe_float(normalized.get("cumulative_fill_qty")),
            "reduce_only": bool(normalized.get("reduce_only")),
            "time_in_force": str(normalized.get("time_in_force") or ""),
            "raw": dict(normalized.get("raw") or {}),
        }
        order_snapshot = self._persist_binance_order_payload(
            payload=order_payload,
            event_type=str(normalized.get("event_type") or ""),
            event_ts=self._to_utc(normalized.get("event_ts")),
            trade_id=self._maybe_int(normalized.get("trade_id")),
        )
        submission_sync = self._sync_submission_from_binance_event(normalized=normalized)

        position_rows: list[dict[str, Any]] = []
        try:
            position_sync = self.sync_binance_positions(symbol=str(normalized.get("symbol") or ""))
            position_rows = list(position_sync.get("positions") or [])
        except Exception:
            position_rows = []
            position_sync = {
                "synced": 0,
                "open_positions": 0,
                "positions": [],
                "reason": "position_sync_failed",
            }

        fill_ingest = None
        plan = self.plan_repo.get(plan_id) if plan_id else None
        stage = self._infer_fill_stage_from_binance_event(event=normalized, plan=plan, current_positions=position_rows)
        if plan is not None and stage is not None:
            fill_payload = {
                "source": "binance_user_stream",
                "client_order_id": normalized.get("client_order_id"),
                "exchange_order_id": normalized.get("order_id"),
                "trade_id": normalized.get("trade_id"),
                "execution_type": normalized.get("execution_type"),
                "status": normalized.get("status"),
                "reduce_only": bool(normalized.get("reduce_only")),
                "position_side": normalized.get("position_side"),
                "realized_pnl": normalized.get("realized_pnl"),
                "notes": {"binance_event_type": normalized.get("event_type")},
            }
            exit_reason = self._infer_exit_reason_from_binance_event(normalized)
            if exit_reason:
                fill_payload["exit_reason"] = exit_reason
            fill_ingest = self.ingest_execution_fill(
                fill_id=self._infer_binance_fill_id(normalized),
                plan_id=plan.plan_id,
                symbol=plan.symbol,
                stage=stage,
                fill_ts=self._to_utc(normalized.get("event_ts")),
                price=float(normalized.get("last_fill_price") or normalized.get("avg_price") or 0.0),
                qty=float(normalized.get("last_fill_qty") or 0.0),
                fee=0.0,
                payload=fill_payload,
            )
        else:
            self.db.commit()

        return {
            "accepted": True,
            "kind": kind,
            "event_type": normalized.get("event_type"),
            "symbol": normalized.get("symbol"),
            "plan_id": plan_id,
            "client_order_id": normalized.get("client_order_id"),
            "order_id": normalized.get("order_id"),
            "order_snapshot": order_snapshot,
            "submission_sync": submission_sync,
            "position_sync": position_sync,
            "fill_ingest": fill_ingest,
        }

    def process_binance_user_stream(
        self,
        *,
        listen_key: str,
        max_events: int = 10,
        timeout_seconds: float = 15.0,
    ) -> dict[str, Any]:
        async def _collect() -> list[dict[str, Any]]:
            items: list[dict[str, Any]] = []
            async for item in self.market_data.binance.stream_user_events(
                listen_key,
                max_events=max_events,
                timeout_seconds=timeout_seconds,
            ):
                items.append(item)
            return items

        events = asyncio.run(_collect())
        processed: list[dict[str, Any]] = []
        order_updates = 0
        account_updates = 0
        fills_ingested = 0
        positions_synced = 0
        for event in events:
            result = self.ingest_binance_user_stream_event(payload=event)
            processed.append(result)
            if result.get("kind") == "order_trade_update":
                order_updates += 1
            if result.get("kind") == "account_update":
                account_updates += 1
            if result.get("fill_ingest") is not None and bool((result.get("fill_ingest") or {}).get("accepted")):
                fills_ingested += 1
            positions_synced += int(((result.get("position_sync") or {}).get("synced") or 0))

        last_event_ts = events[-1].get("event_ts") if events else None
        return {
            "listen_key": listen_key,
            "processed": len(processed),
            "order_updates": order_updates,
            "account_updates": account_updates,
            "fills_ingested": fills_ingested,
            "positions_synced": positions_synced,
            "last_event_ts": last_event_ts,
            "events": processed,
        }

    def _signal_message(self, *, alert_type: str, payload: dict[str, Any]) -> str:
        plan_id = str(payload.get("plan_id") or "")
        direction = str(payload.get("direction") or "").lower()
        entry_model = str(payload.get("entry_model") or "")
        event_price = payload.get("event_price", payload.get("fill_price"))
        entry_price = payload.get("entry_price")
        distance_bps = payload.get("distance_bps")
        distance_atr = payload.get("distance_atr")
        exit_reason = str(payload.get("exit_reason") or "")
        expected_summary = str(payload.get("expected_summary") or "").strip()

        if alert_type == "near":
            message = (
                f"near entry window: {direction} {entry_model} plan={plan_id} "
                f"current={self._fmt_number(event_price)} entry={self._fmt_number(entry_price)} "
                f"dist={self._fmt_number(distance_bps, decimals=1)}bps/{self._fmt_number(distance_atr, decimals=2)}ATR"
            )
        elif alert_type == "touch":
            message = (
                f"entry touched: {direction} {entry_model} plan={plan_id} "
                f"price={self._fmt_number(event_price)} entry={self._fmt_number(entry_price)}"
            )
        elif alert_type == "confirm":
            message = (
                f"confirm window open: {direction} {entry_model} plan={plan_id} "
                f"price={self._fmt_number(event_price)} entry={self._fmt_number(entry_price)}"
            )
        elif alert_type == "entry":
            message = (
                f"entry filled: {direction} {entry_model} plan={plan_id} "
                f"fill={self._fmt_number(payload.get('fill_price'))} qty={self._fmt_number(payload.get('qty'))}"
            )
        elif alert_type == "partial_exit":
            message = (
                f"partial exit: {direction} {entry_model} plan={plan_id} "
                f"fill={self._fmt_number(payload.get('fill_price'))} realized_r={self._fmt_number(payload.get('realized_r'), decimals=2)}"
            )
        elif alert_type == "tp":
            message = (
                f"target exit: {direction} {entry_model} plan={plan_id} "
                f"reason={exit_reason} fill={self._fmt_number(payload.get('fill_price'))} "
                f"realized_r={self._fmt_number(payload.get('realized_r'), decimals=2)}"
            )
        elif alert_type == "sl":
            message = (
                f"stop exit: {direction} {entry_model} plan={plan_id} "
                f"reason={exit_reason} fill={self._fmt_number(payload.get('fill_price'))} "
                f"realized_r={self._fmt_number(payload.get('realized_r'), decimals=2)}"
            )
        else:
            message = (
                f"position closed: {direction} {entry_model} plan={plan_id} "
                f"reason={exit_reason or 'closed'} fill={self._fmt_number(payload.get('fill_price'))} "
                f"realized_r={self._fmt_number(payload.get('realized_r'), decimals=2)}"
            )

        if expected_summary:
            message = f"{message} | {expected_summary}"
        return message.strip()

    def _matching_signal_subscriptions(
        self,
        *,
        symbol: str,
        alert_type: str,
        plan_id: str | None,
    ) -> list[AlertSubscription]:
        rows = self.alert_repo.list_matching_subscriptions(symbol=symbol, alert_type=alert_type, plan_id=plan_id)
        selected: dict[str, AlertSubscription] = {}
        for row in rows:
            current = selected.get(row.channel)
            if current is None:
                selected[row.channel] = row
                continue
            if current.plan_id is None and row.plan_id is not None:
                selected[row.channel] = row
        return list(selected.values())

    def _emit_subscription_alerts(
        self,
        *,
        symbol: str,
        plan_id: str | None,
        alert_type: str,
        event_ts: datetime,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.db.flush()
        subscriptions = self._matching_signal_subscriptions(symbol=symbol, alert_type=alert_type, plan_id=plan_id)
        if not subscriptions:
            return {"matched": 0, "emitted": 0, "cooldown": 0, "retry_queued": 0, "channels": []}

        emitted = 0
        cooldown = 0
        retry_queued = 0
        channels: list[str] = []
        for subscription in subscriptions:
            recent = self.alert_repo.find_recent_emitted(
                symbol=symbol,
                channel=subscription.channel,
                alert_type=alert_type,
                plan_id=plan_id,
                within_seconds=self.settings.signal_alert_cooldown_seconds,
            )
            if recent is not None:
                cooldown += 1
                continue

            base_payload = {
                **dict(payload or {}),
                "message": str(payload.get("message") or self._signal_message(alert_type=alert_type, payload=payload)),
                "subscription_alert": True,
                "subscription_source_alert_id": subscription.alert_id,
                "event_ts": event_ts.isoformat(),
            }
            delivery = self.notification_dispatcher.dispatch(
                channel=subscription.channel,
                alert_type=alert_type,
                symbol=symbol,
                payload=base_payload,
            )
            alert = AlertSubscription(
                alert_id=self._alert_id(prefix=f"sig_{alert_type}", symbol=symbol),
                plan_id=plan_id,
                symbol=symbol,
                channel=subscription.channel,
                type=alert_type,
                payload={**base_payload, "delivery": delivery},
                triggered_ts=event_ts,
            )
            self.alert_repo.add(alert)
            retry_tasks = self.alert_retry_queue.capture_delivery_failure(
                source_alert_id=alert.alert_id,
                symbol=symbol,
                alert_type=alert_type,
                payload=base_payload,
                delivery=delivery,
            )
            emitted += 1
            retry_queued += len(retry_tasks)
            channels.append(subscription.channel)

        return {
            "matched": len(subscriptions),
            "emitted": emitted,
            "cooldown": cooldown,
            "retry_queued": retry_queued,
            "channels": channels,
        }

    def _emit_pre_entry_plan_alerts(
        self,
        *,
        symbol: str,
        plans: list,
        current_price: float,
        candle_low: float,
        candle_high: float,
        atr_reference: float,
        event_ts: datetime,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {"near": 0, "touch": 0, "confirm": 0, "emitted_total": 0}
        near_threshold = max(float(atr_reference) * float(self.settings.signal_alert_near_atr_multiple), 1e-6)
        for plan in plans:
            entry_price = float(plan.entry_price)
            distance_abs = abs(float(current_price) - entry_price)
            distance_bps = (distance_abs / max(entry_price, 1e-9)) * 10_000.0
            distance_atr = distance_abs / max(float(atr_reference), 1e-9)
            touched = float(candle_low) <= entry_price <= float(candle_high)
            payload = {
                "symbol": symbol,
                "plan_id": plan.plan_id,
                "zone_id": plan.zone_id,
                "direction": plan.direction,
                "entry_model": plan.entry_model,
                "event_price": float(current_price),
                "entry_price": entry_price,
                "sl": float(plan.sl),
                "tp1": float(plan.tp1),
                "tp2": float(plan.tp2),
                "tp3": float(plan.tp3),
                "distance_abs": round(distance_abs, 6),
                "distance_bps": round(distance_bps, 4),
                "distance_atr": round(distance_atr, 4),
                "expected_summary": str((plan.validity or {}).get("expected_summary") or ""),
                "strategy_family": str((plan.validity or {}).get("strategy_family") or "legacy_zone_plan"),
                "strategy_grade": (plan.validity or {}).get("strategy_grade"),
            }
            if touched:
                touch_result = self._emit_subscription_alerts(
                    symbol=symbol,
                    plan_id=plan.plan_id,
                    alert_type="touch",
                    event_ts=event_ts,
                    payload={**payload, "signal_reason": "entry_price_touched"},
                )
                summary["touch"] += 1
                summary["emitted_total"] += int(touch_result["emitted"])
                if str(plan.entry_model).upper() != "LIMIT":
                    confirm_result = self._emit_subscription_alerts(
                        symbol=symbol,
                        plan_id=plan.plan_id,
                        alert_type="confirm",
                        event_ts=event_ts,
                        payload={**payload, "signal_reason": "confirm_window_open"},
                    )
                    summary["confirm"] += 1
                    summary["emitted_total"] += int(confirm_result["emitted"])
                continue

            if distance_abs <= near_threshold:
                near_result = self._emit_subscription_alerts(
                    symbol=symbol,
                    plan_id=plan.plan_id,
                    alert_type="near",
                    event_ts=event_ts,
                    payload={
                        **payload,
                        "signal_reason": "entry_within_near_threshold",
                        "near_threshold": round(near_threshold, 6),
                    },
                )
                summary["near"] += 1
                summary["emitted_total"] += int(near_result["emitted"])
        return summary

    def _emit_fill_stage_alerts(
        self,
        *,
        plan,
        stage: ExecutionFillStage,
        fill_id: str,
        fill_ts: datetime,
        price: float,
        qty: float,
        fee: float,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        validity = dict(plan.validity or {})
        base_payload = {
            "symbol": plan.symbol,
            "plan_id": plan.plan_id,
            "zone_id": plan.zone_id,
            "direction": plan.direction,
            "entry_model": plan.entry_model,
            "fill_id": fill_id,
            "fill_price": float(price),
            "qty": float(qty),
            "fee": float(fee),
            "exit_reason": payload.get("exit_reason"),
            "realized_r": payload.get("realized_r"),
            "expected_summary": str(validity.get("expected_summary") or ""),
            "strategy_family": str(validity.get("strategy_family") or "legacy_zone_plan"),
            "strategy_grade": validity.get("strategy_grade"),
        }

        alert_types: list[str] = []
        if stage == ExecutionFillStage.ENTRY:
            alert_types.append("entry")
        elif stage == ExecutionFillStage.PARTIAL_EXIT:
            alert_types.append("partial_exit")
            if str(payload.get("exit_reason") or "").startswith("target_tp"):
                alert_types.append("tp")
        elif stage == ExecutionFillStage.CLOSED:
            alert_types.append("closed")
            exit_reason = str(payload.get("exit_reason") or "")
            if exit_reason.startswith("target_tp"):
                alert_types.append("tp")
            elif exit_reason == "stop_loss":
                alert_types.append("sl")

        summary: dict[str, Any] = {"emitted_total": 0}
        for alert_type in alert_types:
            result = self._emit_subscription_alerts(
                symbol=plan.symbol,
                plan_id=plan.plan_id,
                alert_type=alert_type,
                event_ts=fill_ts,
                payload=base_payload,
            )
            summary[alert_type] = result
            summary["emitted_total"] += int(result["emitted"])
        return summary

    def current_context(self, symbol: str) -> ContextSnapshot | None:
        candles5 = self.market_data.recent_candles(symbol, "5m", limit=300)
        candles15 = self.market_data.recent_candles(symbol, "15m", limit=300)
        if not candles5 or not candles15:
            return None
        return self.context_engine.build_snapshot(symbol=symbol, candles_5m=candles5, candles_15m=candles15)

    def _runtime_feature_calibration(self, *, symbol: str, context: ContextSnapshot) -> tuple[str, dict | None]:
        regime_label = self.plan_generator.resolve_regime_label(context)
        calibration = self.feature_calibration_service.runtime_payload(
            symbol=symbol,
            regime_label=regime_label,
        )
        return regime_label, calibration

    def _build_stress_replay_runtime_stack(
        self,
        *,
        symbol: str,
        version: str,
        plans: list | None = None,
        pbo_dsr_metrics: dict | None = None,
        write_report: bool = False,
        run_prototype_worker: bool = False,
    ) -> dict[str, dict]:
        recent_plans = plans if plans is not None else self.plan_repo.list_recent(symbol=symbol, days=180)
        runtime_pbo_dsr_metrics = pbo_dsr_metrics
        if runtime_pbo_dsr_metrics is None:
            self.strategy_v2_pbo_dsr_trial_writer.generate(
                symbol=symbol,
                version=version,
                plans=recent_plans,
                write_report=False,
                persist=True,
            )
            self.strategy_v2_pbo_dsr_threshold_runner.generate(
                symbol=symbol,
                version=version,
                plans=recent_plans,
                write_report=False,
                persist=True,
            )
            runtime_pbo_dsr_metrics = self.strategy_v2_pbo_dsr_metrics.generate(
                symbol=symbol,
                version=version,
                write_report=False,
                persist_snapshot=False,
            )
        stress_validation = self.strategy_v2_stress_validation.generate(
            symbol=symbol,
            version=version,
            plans=recent_plans,
            write_report=False,
        )
        stress_replay_lineage = self.strategy_v2_stress_replay_lineage.generate(
            symbol=symbol,
            version=version,
            write_report=write_report,
        )
        stress_replay_output_artifacts = self.strategy_v2_stress_replay_output_artifacts.generate(
            symbol=symbol,
            version=version,
            stress_validation=stress_validation,
            write_report=write_report,
        )
        stress_validation = self.strategy_v2_stress_validation.attach_replay_output_artifacts(
            payload=stress_validation,
            stress_replay_output_artifacts=stress_replay_output_artifacts,
            write_report=write_report,
        )
        stress_replay_assessment = self.strategy_v2_stress_replay_assessment.generate(
            symbol=symbol,
            version=version,
            stress_validation=stress_validation,
            stress_replay_lineage=stress_replay_lineage,
            stress_replay_output_artifacts=stress_replay_output_artifacts,
            pbo_dsr_metrics=runtime_pbo_dsr_metrics,
            write_report=write_report,
        )
        stress_replay_runner_contract = self.strategy_v2_stress_replay_runner_contract.generate(
            symbol=symbol,
            version=version,
            stress_validation=stress_validation,
            stress_replay_lineage=stress_replay_lineage,
            stress_replay_assessment=stress_replay_assessment,
            write_report=write_report,
        )
        stress_replay_lineage_writer = self.strategy_v2_stress_replay_lineage_writer.generate(
            symbol=symbol,
            version=version,
            stress_replay_lineage=stress_replay_lineage,
            stress_replay_runner_contract=stress_replay_runner_contract,
            write_report=write_report,
        )
        stress_replay_prototype_worker: dict[str, object] | None = None
        if run_prototype_worker:
            stress_replay_prototype_worker = self.strategy_v2_stress_replay_prototype_worker.generate(
                symbol=symbol,
                version=version,
                stress_validation=stress_validation,
                stress_replay_lineage_writer=stress_replay_lineage_writer,
                stress_replay_runner_contract=stress_replay_runner_contract,
                write_report=write_report,
            )
        return {
            "stress_validation": stress_validation,
            "stress_replay_lineage": stress_replay_lineage,
            "stress_replay_assessment": stress_replay_assessment,
            "stress_replay_runner_contract": stress_replay_runner_contract,
            "stress_replay_lineage_writer": stress_replay_lineage_writer,
            "stress_replay_prototype_worker": stress_replay_prototype_worker or {},
            "stress_replay_output_artifacts": stress_replay_output_artifacts,
            "pbo_dsr_metrics": runtime_pbo_dsr_metrics or {},
        }

    def refresh_symbol(self, symbol: str) -> dict:
        candles5 = self.market_data.recent_candles(symbol, "5m", limit=300)
        candles15 = self.market_data.recent_candles(symbol, "15m", limit=300)
        if len(candles5) < 60 or len(candles15) < 60:
            return {"symbol": symbol, "updated": False, "reason": "insufficient_candles"}

        context = self.context_engine.build_snapshot(symbol=symbol, candles_5m=candles5, candles_15m=candles15)
        existing = self.zone_repo.list_all(symbol=symbol, timeframe="15m")
        zones = self.zone_engine.refresh(symbol=symbol, candles_15m=candles15, existing=existing)
        self.zone_repo.upsert_many(zones)

        active_zones = [z for z in zones if z.state != "expired"]
        gate_state, can_open, gate_reason, operating_lock = self._evaluate_gate(
            symbol=symbol,
            jump_rate=context.jump_rate_5m,
        )
        regime_label, feature_calibration = self._runtime_feature_calibration(symbol=symbol, context=context)
        exposure_rows = self.plan_repo.list_exposure_candidates(
            timeframe="5m",
            include_planned=self.settings.portfolio_overlay_include_planned_exposure,
            limit=300,
        )
        active_thesis_clusters = len(self.scanner.overlay.thesis_cluster_summary(exposure_rows))
        ranked_plans = (
            self.plan_generator.generate(
                symbol=symbol,
                zones=active_zones,
                context=context,
                candles_5m=candles5,
                importance_calibration=feature_calibration,
                active_thesis_clusters=active_thesis_clusters,
            )
            if can_open
            else []
        )
        self.plan_repo.upsert_many([x.plan for x in ranked_plans])
        self.plan_repo.invalidate_expired()
        active_signal_plans = self.plan_repo.list_active_for_symbol(
            symbol=symbol,
            timeframe="5m",
            states=[PlanState.PLANNED.value, PlanState.ARMED.value],
            limit=max(20, int(self.settings.max_candidate_plans_per_symbol) * 4),
        )
        signal_alerts = self._emit_pre_entry_plan_alerts(
            symbol=symbol,
            plans=active_signal_plans,
            current_price=float(candles5[-1].c),
            candle_low=float(candles5[-1].l),
            candle_high=float(candles5[-1].h),
            atr_reference=float(context.atr5),
            event_ts=candles5[-1].ts if candles5[-1].ts.tzinfo else candles5[-1].ts.replace(tzinfo=timezone.utc),
        )

        self.events.publish(ZONE_CREATED, {"symbol": symbol, "count": len(zones)})
        self.events.publish(PLAN_GENERATED, {"symbol": symbol, "count": len(ranked_plans)})
        self.db.commit()

        return {
            "symbol": symbol,
            "updated": True,
            "zones": len(zones),
            "plans": len(ranked_plans),
            "risk_state": gate_state.value,
            "gate_reason": gate_reason,
            "operating_lock": operating_lock.to_dict(),
            "regime_label": regime_label,
            "transition_score": round(context.transition_score, 4),
            "transition_state": context.transition_state,
            "transition_lock_reason": context.transition_lock_reason,
            "active_thesis_clusters": active_thesis_clusters,
            "strategy_mode": getattr(self.settings.strategy_mode, "value", str(self.settings.strategy_mode)),
            "feature_calibration_available": bool(feature_calibration and feature_calibration.get("available")),
            "feature_calibration_samples": int((feature_calibration or {}).get("matched_samples", 0)),
            "signal_alerts": signal_alerts,
        }

    def recompute_learning(self, symbol: str) -> dict:
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
            persist=True,
        )
        strategy_v2_pbo_dsr_threshold_runner = self.strategy_v2_pbo_dsr_threshold_runner.generate(
            symbol=symbol,
            version=self.settings.strategy_version,
            plans=recent_plans,
            write_report=True,
            persist=True,
        )
        strategy_v2_pbo_dsr_metrics = self.strategy_v2_pbo_dsr_metrics.generate(
            symbol=symbol,
            version=self.settings.strategy_version,
            write_report=True,
            persist_snapshot=True,
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
        return {
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
        }

    def feature_importance(
        self,
        symbol: str,
        *,
        context: ContextSnapshot | None = None,
        feature_calibration: dict | None = None,
    ) -> dict:
        if not self.settings.feature_importance_enabled:
            return {
                "symbol": symbol,
                "available": False,
                "reason": "feature_importance_disabled",
                "baseline": {},
                "by_feature": {},
                "ranking": [],
            }

        context = context or self.current_context(symbol)
        if context is None:
            return {
                "symbol": symbol,
                "available": False,
                "reason": "insufficient_candles",
                "baseline": {},
                "by_feature": {},
                "ranking": [],
            }

        if feature_calibration is None:
            _, feature_calibration = self._runtime_feature_calibration(symbol=symbol, context=context)

        zones = self.zone_repo.list_all(symbol=symbol, timeframe="15m")
        candles_5m = self.market_data.recent_candles(symbol, "5m", limit=20)
        return self.feature_importance_service.analyze(
            symbol=symbol,
            zones=zones,
            context=context,
            candles_5m=candles_5m,
            importance_calibration=feature_calibration,
        )

    def feature_calibration(
        self,
        symbol: str,
        *,
        context: ContextSnapshot | None = None,
        feature_importance: dict | None = None,
        write_report: bool = True,
    ) -> dict:
        context = context or self.current_context(symbol)
        if context is None:
            return self.feature_calibration_service.generate(
                symbol=symbol,
                regime_label="range",
                feature_importance={
                    "available": False,
                    "reason": "insufficient_candles",
                    "baseline": {},
                    "by_feature": {},
                    "ranking": [],
                },
                write_report=write_report,
            )

        regime_label, runtime_calibration = self._runtime_feature_calibration(symbol=symbol, context=context)
        report = feature_importance or self.feature_importance(
            symbol=symbol,
            context=context,
            feature_calibration=runtime_calibration,
        )
        return self.feature_calibration_service.generate(
            symbol=symbol,
            regime_label=regime_label,
            feature_importance=report,
            write_report=write_report,
        )

    @staticmethod
    def _alert_id(*, prefix: str, symbol: str, suffix: str | None = None) -> str:
        token = uuid4().hex[:10]
        tail = f"_{suffix}" if suffix else ""
        return f"{prefix}_{token}_{symbol}{tail}"

    def _maybe_emit_validation_alert(self, *, symbol: str, version: str, report: dict) -> dict | None:
        status = str(report.get("status", "")).upper()
        if status not in {"WARN", "FAIL"}:
            return None
        approval_contract = approval_summary_passthrough(report.get("deployment_approval_summary"))
        alert_contract = alert_contract_defaults(approval_contract)
        approval_strip_summary = validation_alert_strip_summary({**approval_contract})

        alert_type = "validation_warn" if status == "WARN" else "validation_fail"
        event_type = VALIDATION_WARN if status == "WARN" else VALIDATION_FAIL

        recent = self.alert_repo.find_recent(
            symbol=symbol,
            channel=self.settings.validation_alert_channel,
            alert_type=alert_type,
            within_seconds=self.settings.validation_alert_cooldown_seconds,
        )
        if recent:
            return {
                "emitted": False,
                "reason": "cooldown_active",
                "type": alert_type,
                "status": status,
                "cooldown_seconds": self.settings.validation_alert_cooldown_seconds,
                "approval_strip_summary": approval_strip_summary,
                **alert_contract,
            }

        now = datetime.now(timezone.utc)
        base_payload = {
            "symbol": symbol,
            "version": version,
            "status": status,
            "report_path": report.get("path"),
            "generated_at": report.get("generated_at"),
            "approval_strip_summary": approval_strip_summary,
            **alert_contract,
        }
        delivery = self.notification_dispatcher.dispatch(
            channel=self.settings.validation_alert_channel,
            alert_type=alert_type,
            symbol=symbol,
            payload=base_payload,
        )
        alert = AlertSubscription(
            alert_id=self._alert_id(prefix=f"val_{status.lower()}", symbol=symbol),
            plan_id=None,
            symbol=symbol,
            channel=self.settings.validation_alert_channel,
            type=alert_type,
            payload={**base_payload, "delivery": delivery},
            triggered_ts=now,
        )
        self.alert_repo.add(alert)
        retry_tasks = self.alert_retry_queue.capture_delivery_failure(
            source_alert_id=alert.alert_id,
            symbol=symbol,
            alert_type=alert_type,
            payload=base_payload,
            delivery=delivery,
        )
        self.events.publish(
            event_type,
            {
                "symbol": symbol,
                "version": version,
                "status": status,
                "report_path": report.get("path"),
                "generated_at": report.get("generated_at"),
                "approval_strip_summary": approval_strip_summary,
                **alert_contract,
                "dedupe_key": f"{event_type}:{symbol}:{version}:{now.strftime('%Y%m%d%H')}",
            },
        )
        return {
            "emitted": True,
            "type": alert_type,
            "status": status,
            "channel": self.settings.validation_alert_channel,
            "approval_strip_summary": approval_strip_summary,
            **alert_contract,
            "delivery": delivery,
            "retry_queued": len(retry_tasks),
        }

    def risk_state(self, symbol: str) -> dict:
        context = self.current_context(symbol)
        jump_rate = context.jump_rate_5m if context else 0.0
        state, can_open_new_trade, reason, operating_lock = self._evaluate_gate(symbol=symbol, jump_rate=jump_rate)
        return {
            "state": state.value,
            "can_open_new_trade": can_open_new_trade,
            "reason": reason,
            "operating_lock": operating_lock.to_dict(),
        }

    def subscribe_alert(self, symbol: str, channel: str, alert_type: str, plan_id: str | None, payload: dict) -> AlertSubscription:
        normalized_payload = {
            **dict(payload or {}),
            "subscription_active": True,
            "subscription_status": "active",
            "subscription_created_at": datetime.now(timezone.utc).isoformat(),
        }
        if any(
            normalized_payload.get(key)
            for key in (
                "deployment_go_no_go",
                "approval_playbook_go_no_go",
                "playbook_go_no_go",
                "approval_playbook_action",
                "playbook_action",
            )
        ):
            normalized_payload["approval_strip_summary"] = validation_alert_strip_summary(normalized_payload)
        alert = AlertSubscription(
            alert_id=self._alert_id(prefix="alert", symbol=symbol),
            plan_id=plan_id,
            symbol=symbol,
            channel=channel,
            type=alert_type,
            payload=normalized_payload,
        )
        self.alert_repo.add(alert)
        self.db.commit()
        return alert

    def tv_webhook(self, event: str, symbol: str, price: float, ts: datetime, payload: dict) -> dict:
        normalized_ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        normalized_ts = normalized_ts.astimezone(timezone.utc)
        alert = AlertSubscription(
            alert_id=self._alert_id(prefix="tv", symbol=symbol, suffix=event),
            plan_id=payload.get("plan_id"),
            symbol=symbol,
            channel="webhook",
            type=event,
            payload={"price": price, **payload},
        )
        self.alert_repo.add(alert)
        subscription_alerts = self._emit_subscription_alerts(
            symbol=symbol,
            plan_id=payload.get("plan_id"),
            alert_type=event,
            event_ts=normalized_ts,
            payload={
                "symbol": symbol,
                "plan_id": payload.get("plan_id"),
                "event_price": float(price),
                "entry_price": payload.get("entry_price"),
                "direction": payload.get("direction"),
                "entry_model": payload.get("entry_model"),
                "expected_summary": payload.get("expected_summary"),
                "message": str(payload.get("message") or f"tv webhook {event}: plan={payload.get('plan_id') or '-'} price={self._fmt_number(price)}"),
            },
        )
        self.db.commit()
        return {"accepted": True, "event": event, "symbol": symbol, "subscription_alerts": subscription_alerts}

    def send_test_alert(self, *, channel: str, symbol: str, message: str, payload: dict) -> dict:
        now = datetime.now(timezone.utc)
        approval_strip_summary = validation_alert_strip_summary(payload)
        base_payload = {
            "symbol": symbol,
            "message": message,
            "approval_strip_summary": approval_strip_summary,
            **payload,
        }
        alert_contract = validation_alert_contract(base_payload)
        delivery = self.notification_dispatcher.dispatch(
            channel=channel,
            alert_type="test",
            symbol=symbol,
            payload=base_payload,
        )
        alert = AlertSubscription(
            alert_id=self._alert_id(prefix="alert_test", symbol=symbol),
            plan_id=None,
            symbol=symbol,
            channel=channel,
            type="test",
            payload={**base_payload, "delivery": delivery},
            triggered_ts=now,
        )
        self.alert_repo.add(alert)
        retry_tasks = self.alert_retry_queue.capture_delivery_failure(
            source_alert_id=alert.alert_id,
            symbol=symbol,
            alert_type="test",
            payload=base_payload,
            delivery=delivery,
        )
        self.db.commit()
        return {
            "alert_id": alert.alert_id,
            "channel": channel,
            "symbol": symbol,
            "approval_strip_summary": approval_strip_summary,
            **alert_contract,
            "delivery": delivery,
            "retry_queued": len(retry_tasks),
        }

    def alert_metrics_report(self, *, days: int, write_report: bool = True) -> dict:
        return self.alert_metrics.generate(days=days, write_report=write_report)

    def alert_retry_queue_status(self) -> dict:
        return self.alert_retry_queue.status_snapshot()

    def process_alert_retry_queue(self, *, limit: int) -> dict:
        result = self.alert_retry_queue.process_due(limit=limit)
        self.db.commit()
        return result

    def requeue_dead_letter_alerts(self, *, limit: int) -> dict:
        result = self.alert_retry_queue.requeue_dead_letters(limit=limit)
        self.db.commit()
        return result

    def ingest_execution_fill(
        self,
        *,
        fill_id: str,
        plan_id: str,
        symbol: str,
        stage: ExecutionFillStage,
        fill_ts: datetime,
        price: float,
        qty: float,
        fee: float = 0.0,
        payload: dict | None = None,
    ) -> dict:
        normalized_fill_ts = fill_ts if fill_ts.tzinfo else fill_ts.replace(tzinfo=timezone.utc)
        normalized_fill_ts = normalized_fill_ts.astimezone(timezone.utc)
        result = self.position_state_machine.apply(
            FillApplyInput(
                fill_id=fill_id,
                plan_id=plan_id,
                symbol=symbol,
                stage=stage,
                fill_ts=normalized_fill_ts,
                price=price,
                qty=qty,
                fee=fee,
                payload=payload,
            )
        )
        if not result.accepted:
            self.db.rollback()
            return asdict(result)

        self.db.flush()
        fill = self.fill_repo.get(fill_id)
        fill_payload = dict((fill.payload if fill is not None else {}) or {})
        response = asdict(result)
        response["exit_reason"] = fill_payload.get("exit_reason") or result.exit_reason
        plan = self.plan_repo.get(result.plan_id) if result.plan_id else None

        if result.state_changed and result.to_state == PlanState.TRIGGERED.value:
            self.events.publish(
                ENTRY_TRIGGERED,
                {
                    "symbol": result.symbol,
                    "plan_id": result.plan_id,
                    "fill_id": result.fill_id,
                    "stage": result.stage,
                    "event_ts": normalized_fill_ts.isoformat(),
                    "dedupe_key": f"{ENTRY_TRIGGERED}:{result.plan_id}:{result.fill_id}",
                },
            )
        if result.state_changed and result.to_state == PlanState.CLOSED.value:
            self.events.publish(
                TRADE_CLOSED,
                {
                    "symbol": result.symbol,
                    "plan_id": result.plan_id,
                    "fill_id": result.fill_id,
                    "stage": result.stage,
                    "exit_reason": fill_payload.get("exit_reason"),
                    "strategy_family": fill_payload.get("strategy_family"),
                    "held_bars": fill_payload.get("held_bars"),
                    "classification_before_exit": fill_payload.get("classification_before_exit"),
                    "classification_after_exit": fill_payload.get("classification_after_exit"),
                    "trigger_detail": fill_payload.get("trigger_detail"),
                    "event_ts": normalized_fill_ts.isoformat(),
                    "dedupe_key": f"{TRADE_CLOSED}:{result.plan_id}:{result.fill_id}",
                },
            )
        if plan is not None and stage in {
            ExecutionFillStage.ENTRY,
            ExecutionFillStage.PARTIAL_EXIT,
            ExecutionFillStage.CLOSED,
        }:
            self._emit_fill_stage_alerts(
                plan=plan,
                stage=stage,
                fill_id=fill_id,
                fill_ts=normalized_fill_ts,
                price=price,
                qty=qty,
                fee=fee,
                payload=fill_payload,
            )

        client_order_id = str(fill_payload.get("client_order_id") or "")
        if client_order_id:
            submission = self.submission_repo.get_by_client_order_id(client_order_id)
            if submission is not None and stage == ExecutionFillStage.ENTRY:
                next_state = OrderLifecycleState.PARTIALLY_FILLED if bool(fill_payload.get("partial")) else OrderLifecycleState.FILLED
                self.submission_repo.transition(
                    submission,
                    state=next_state.value,
                    submit_status=next_state.value,
                    message="Execution fill linked to submission lifecycle.",
                    raw={**dict(submission.raw or {}), "last_fill_id": fill_id},
                )

        self.db.commit()
        return response

    def scanner_top(self, universe: str, limit: int) -> list[dict]:
        symbols = self.market_data.default_universe(universe)
        if not symbols and universe == self.settings.universe_name:
            symbols = self.market_data.refresh_universe(limit=30)
        today_trade_count = self._today_trade_count()
        exposure_rows = self._current_exposure_rows()
        gate_state = RiskGateState.OPEN
        gate_reason = "normal"
        operating_lock = self._operating_lock_snapshot()
        if symbols:
            _, gate_state, gate_reason, operating_lock = self._gate_context_for_symbol(symbol=symbols[0])
        outcome_inputs_by_symbol = self._outcome_inputs_for_symbols(
            symbols=self._runtime_candidate_symbols(symbols=symbols, risk_state=gate_state)
        )
        return self.scanner.top_opportunities(
            # Overlay fields are added inside scanner service, but keep the same engine-facing contract here.
            symbols=symbols,
            limit=limit,
            risk_state=gate_state,
            existing_exposures=exposure_rows,
            today_trade_count=today_trade_count,
            risk_reason=gate_reason,
            operating_lock=operating_lock.to_dict(),
            outcome_inputs_by_symbol=outcome_inputs_by_symbol,
        )

    def portfolio_budget_report(self, *, universe: str, limit: int, write_report: bool = True) -> dict:
        symbols = self.market_data.default_universe(universe)
        if not symbols and universe == self.settings.universe_name:
            symbols = self.market_data.refresh_universe(limit=30)

        gate_state = RiskGateState.OPEN
        gate_reason = "default_open"
        operating_lock = self._operating_lock_snapshot()
        if symbols:
            _, gate_state, gate_reason, operating_lock = self._gate_context_for_symbol(symbol=symbols[0])
        outcome_inputs_by_symbol = self._outcome_inputs_for_symbols(
            symbols=self._runtime_candidate_symbols(symbols=symbols, risk_state=gate_state)
        )

        return self.portfolio_budget_report_service.generate(
            universe=universe,
            symbols=symbols,
            limit=limit,
            risk_state=gate_state,
            risk_reason=gate_reason,
            today_trade_count=self._today_trade_count(),
            operating_lock=operating_lock.to_dict(),
            outcome_inputs_by_symbol=outcome_inputs_by_symbol,
            write_report=write_report,
        )

    def indicator_summary(self, *, symbol: str, refresh: bool = True, plan_limit: int = 3, zone_limit: int = 5) -> dict:
        refresh_result = self.refresh_symbol(symbol) if refresh else {"symbol": symbol, "updated": False, "reason": "refresh_skipped"}
        context, gate_state, gate_reason, operating_lock = self._gate_context_for_symbol(symbol=symbol)
        assessed_rows = self.scanner.assessed_symbol_candidates(
            symbol=symbol,
            risk_state=gate_state,
            risk_reason=gate_reason,
            operating_lock=operating_lock.to_dict(),
            existing_exposures=self._current_exposure_rows(),
            today_trade_count=self._today_trade_count(),
            limit=max(plan_limit, 20),
        )
        plans = self.top_plans(symbol=symbol, limit=plan_limit)
        zones = [zone for zone in self.zones(symbol=symbol, tf="15m", state=None) if zone.state != "expired"][:zone_limit]
        return self.strategy_indicators.build_summary(
            symbol=symbol,
            context=context,
            plans=plans,
            zones=zones,
            refresh=refresh_result,
            assessed_rows=assessed_rows,
        )

    def indicator_chart(self, *, symbol: str, refresh: bool = True, plan_limit: int = 5, zone_limit: int = 8) -> dict:
        refresh_result = self.refresh_symbol(symbol) if refresh else {"symbol": symbol, "updated": False, "reason": "refresh_skipped"}
        context, gate_state, gate_reason, operating_lock = self._gate_context_for_symbol(symbol=symbol)
        assessed_rows = self.scanner.assessed_symbol_candidates(
            symbol=symbol,
            risk_state=gate_state,
            risk_reason=gate_reason,
            operating_lock=operating_lock.to_dict(),
            existing_exposures=self._current_exposure_rows(),
            today_trade_count=self._today_trade_count(),
            limit=max(plan_limit, 20),
        )
        plans = self.top_plans(symbol=symbol, limit=plan_limit)
        zones = [zone for zone in self.zones(symbol=symbol, tf="15m", state=None) if zone.state != "expired"][:zone_limit]
        return self.strategy_indicators.build_chart_payload(
            symbol=symbol,
            context=context,
            plans=plans,
            zones=zones,
            refresh=refresh_result,
            assessed_rows=assessed_rows,
        )

    def indicator_pine(self, *, symbol: str, refresh: bool = True, plan_limit: int = 5, zone_limit: int = 8) -> dict:
        refresh_result = self.refresh_symbol(symbol) if refresh else {"symbol": symbol, "updated": False, "reason": "refresh_skipped"}
        context, gate_state, gate_reason, operating_lock = self._gate_context_for_symbol(symbol=symbol)
        assessed_rows = self.scanner.assessed_symbol_candidates(
            symbol=symbol,
            risk_state=gate_state,
            risk_reason=gate_reason,
            operating_lock=operating_lock.to_dict(),
            existing_exposures=self._current_exposure_rows(),
            today_trade_count=self._today_trade_count(),
            limit=max(plan_limit, 20),
        )
        plans = self.top_plans(symbol=symbol, limit=plan_limit)
        zones = [zone for zone in self.zones(symbol=symbol, tf="15m", state=None) if zone.state != "expired"][:zone_limit]
        return self.strategy_indicators.build_pine_payload(
            symbol=symbol,
            context=context,
            plans=plans,
            zones=zones,
            refresh=refresh_result,
            assessed_rows=assessed_rows,
        )

    def preview_execution_plan(self, *, plan_id: str, paper_lineage_override: bool = False) -> dict[str, Any]:
        plan = self.plan_repo.get(plan_id)
        if plan is None:
            raise KeyError(plan_id)
        if self._to_utc(plan.valid_until) <= datetime.now(timezone.utc):
            raise ValueError("plan_expired")
        if plan.state not in {PlanState.PLANNED.value, PlanState.ARMED.value}:
            raise ValueError("plan_not_previewable")
        return dict(
            self._execution_approval_bundle(
                plan_id,
                None,
                strict_requested_mode=False,
                paper_lineage_override=paper_lineage_override,
            )["executable_plan"]
        )

    def approve_execution_plan(self, *, plan_id: str, paper_lineage_override: bool = False) -> dict[str, Any]:
        plan = self.plan_repo.get(plan_id)
        if plan is None:
            raise KeyError(plan_id)
        if self._to_utc(plan.valid_until) <= datetime.now(timezone.utc):
            raise ValueError("plan_expired")
        if plan.state not in {PlanState.PLANNED.value, PlanState.ARMED.value}:
            raise ValueError("plan_not_previewable")
        return dict(
            self._execution_approval_bundle(
                plan_id,
                None,
                strict_requested_mode=False,
                paper_lineage_override=paper_lineage_override,
            )["approval"]
        )

    def scalp_experiment_report(self, *, symbol: str, write_report: bool = True) -> dict:
        candles_1m = self.market_data.recent_candles(symbol, "1m", limit=900)
        candles_5m = self.market_data.recent_candles(symbol, "5m", limit=300)
        candles_15m = self.market_data.recent_candles(symbol, "15m", limit=300)
        return self.strategy_v2_scalp_experiment.generate(
            symbol=symbol,
            candles_1m=candles_1m,
            candles_5m=candles_5m,
            candles_15m=candles_15m,
            write_report=write_report,
        )

    @staticmethod
    def _alpha_research_analysis_symbol(
        *,
        portfolio_budget: dict[str, Any],
        focus_symbol: str | None,
    ) -> str | None:
        focus = str(focus_symbol or "").upper() or None
        if focus:
            return focus
        rows = [
            dict(row)
            for row in (portfolio_budget.get("alpha_research_candidates") or [])
            if row.get("alpha_research_candidate")
        ]
        if not rows:
            return None
        best = max(
            rows,
            key=lambda row: (
                float(row.get("expected_ev_at_recommended_size_r", row.get("expected_ev_r", 0.0)) or 0.0),
                float(row.get("alpha_research_softened_risk_r", 0.0) or 0.0),
                -float(row.get("alpha_research_gap", 0.0) or 0.0),
                str(row.get("symbol") or ""),
            ),
        )
        symbol = str(best.get("symbol") or "").upper()
        return symbol or None

    def _alpha_research_performance_decomposition(self, *, symbol: str | None) -> dict[str, Any] | None:
        if not symbol:
            return None
        recent_plans = self.plan_repo.list_recent(symbol=symbol, days=180)
        strategy_v2_validation = self.strategy_v2_validation.generate(
            symbol=symbol,
            version=self.settings.strategy_version,
            plans=recent_plans,
            write_report=False,
        )
        execution_quality = self.execution_quality.generate(symbol=symbol, days=180, write_report=False)
        return self.validation_report._performance_decomposition_summary(
            execution_quality=execution_quality,
            strategy_v2_validation=strategy_v2_validation,
            strategy_v2_stress_validation=None,
        )

    def alpha_research_report(
        self,
        *,
        universe: str,
        focus_symbol: str | None = None,
        write_report: bool = True,
    ) -> dict:
        portfolio_budget = self.portfolio_budget_report(
            universe=universe,
            limit=max(20, int(self.settings.alpha_research_max_candidates)),
            write_report=False,
        )
        analysis_symbol = self._alpha_research_analysis_symbol(
            portfolio_budget=portfolio_budget,
            focus_symbol=focus_symbol,
        )
        performance_decomposition_summary = self._alpha_research_performance_decomposition(symbol=analysis_symbol)
        score_to_outcome_funnel = None
        execution_degradation_advisory = None
        if analysis_symbol:
            score_to_outcome_funnel = self.score_to_outcome_funnel.generate(
                symbol=analysis_symbol,
                version=self.settings.strategy_version,
                days=180,
                portfolio_budget=portfolio_budget,
            )
            execution_degradation_advisory = self.execution_degradation_advisory.generate(
                execution_quality=self.execution_quality_report(
                    symbol=analysis_symbol,
                    days=180,
                    write_report=False,
                ),
                performance_decomposition_summary=performance_decomposition_summary,
                strategy_v2_stress_validation=None,
            )
        return self.alpha_research_pipeline.generate(
            universe=universe,
            portfolio_budget=portfolio_budget,
            focus_symbol=focus_symbol,
            analysis_symbol=analysis_symbol,
            performance_decomposition_summary=performance_decomposition_summary,
            score_to_outcome_funnel=score_to_outcome_funnel,
            execution_degradation_advisory=execution_degradation_advisory,
            write_report=write_report,
        )

    def sync_symbol_from_binance(
        self,
        symbol: str,
        limit_1m: int = 0,
        limit_5m: int = 500,
        limit_15m: int = 500,
    ) -> dict:
        summary = self.market_data.backfill_symbol_timeframes(
            symbol=symbol,
            limit_1m=limit_1m,
            limit_5m=limit_5m,
            limit_15m=limit_15m,
        )
        self.db.commit()
        refresh = self.refresh_symbol(symbol)
        return {
            "symbol": symbol,
            "backfill": summary,
            "refresh": refresh,
        }

    def sync_universe_from_binance(
        self,
        *,
        limit_symbols: int = 30,
        limit_1m: int = 0,
        limit_5m: int = 500,
        limit_15m: int = 500,
        symbol_concurrency: int = 1,
    ) -> dict:
        symbols = self.market_data.refresh_universe(limit=limit_symbols)
        results: list[dict] = []
        success = 0
        failed = 0
        requested_concurrency = max(1, int(symbol_concurrency))
        effective_concurrency = min(requested_concurrency, len(symbols)) if symbols else 1
        symbol_order = {symbol: index for index, symbol in enumerate(symbols)}

        if effective_concurrency <= 1:
            for symbol in symbols:
                try:
                    result = self._sync_universe_symbol_local(
                        symbol=symbol,
                        limit_1m=limit_1m,
                        limit_5m=limit_5m,
                        limit_15m=limit_15m,
                    )
                    success += 1
                    results.append(result)
                except Exception as exc:
                    self.db.rollback()
                    failed += 1
                    results.append(
                        {
                            "symbol": symbol,
                            "status": "error",
                            "error": str(exc),
                        }
                    )
        else:
            with ThreadPoolExecutor(max_workers=effective_concurrency, thread_name_prefix="sync-universe") as executor:
                futures = {
                    executor.submit(
                        self._sync_universe_symbol_isolated,
                        symbol=symbol,
                        limit_1m=limit_1m,
                        limit_5m=limit_5m,
                        limit_15m=limit_15m,
                    ): symbol
                    for symbol in symbols
                }
                for future in as_completed(futures):
                    symbol = futures[future]
                    try:
                        result = future.result()
                        success += 1
                        results.append(result)
                    except Exception as exc:
                        failed += 1
                        results.append(
                            {
                                "symbol": symbol,
                                "status": "error",
                                "error": str(exc),
                            }
                        )

        results.sort(key=lambda item: symbol_order.get(item.get("symbol", ""), len(symbol_order)))

        return {
            "universe": self.settings.universe_name,
            "requested_symbols": limit_symbols,
            "processed_symbols": len(symbols),
            "symbol_concurrency_requested": requested_concurrency,
            "symbol_concurrency": effective_concurrency,
            "execution_mode": "parallel" if effective_concurrency > 1 else "sequential",
            "success": success,
            "failed": failed,
            "results": results,
        }

    def _sync_universe_symbol_local(self, *, symbol: str, limit_1m: int, limit_5m: int, limit_15m: int) -> dict:
        backfill = self.market_data.backfill_symbol_timeframes(
            symbol=symbol,
            limit_1m=limit_1m,
            limit_5m=limit_5m,
            limit_15m=limit_15m,
        )
        self.db.commit()
        refresh = self.refresh_symbol(symbol)
        return {
            "symbol": symbol,
            "status": "ok",
            "backfill": backfill,
            "refresh": refresh,
        }

    @staticmethod
    def _sync_universe_symbol_isolated(*, symbol: str, limit_1m: int, limit_5m: int, limit_15m: int) -> dict:
        with SessionLocal() as db:
            engine = StrategyEngine(db)
            try:
                return engine._sync_universe_symbol_local(
                    symbol=symbol,
                    limit_1m=limit_1m,
                    limit_5m=limit_5m,
                    limit_15m=limit_15m,
                )
            except Exception:
                db.rollback()
                raise

    async def stream_binance_klines(
        self,
        *,
        symbols: list[str],
        intervals: list[str] | tuple[str, ...] = ("5m", "15m"),
        refresh_on_final: bool = True,
        max_messages: int | None = None,
    ) -> dict:
        symbols = sorted({s.upper() for s in symbols if s})
        selected_intervals = [iv for iv in intervals if iv in {"5m", "15m"}]
        if not symbols or not selected_intervals:
            return {
                "running": False,
                "reason": "empty_symbols_or_intervals",
                "symbols": symbols,
                "intervals": selected_intervals,
            }

        stats: dict = {
            "running": True,
            "symbols": symbols,
            "intervals": selected_intervals,
            "processed_messages": 0,
            "committed_candles": 0,
            "ingest_errors": 0,
            "refresh_calls": 0,
            "refresh_errors": 0,
            "reconnects": 0,
            "per_interval": {iv: 0 for iv in selected_intervals},
            "per_symbol": {symbol: 0 for symbol in symbols},
        }
        stop = False
        refresh_guard: dict[str, datetime] = {}

        async def _stream_one_interval(interval: str) -> None:
            nonlocal stop
            backoff = self.settings.ws_reconnect_base_seconds
            while not stop:
                try:
                    async for kline in self.market_data.binance.stream_klines(symbols=symbols, interval=interval):
                        if stop:
                            break

                        payload = {
                            "symbol": kline.symbol,
                            "timeframe": interval,
                            "ts": kline.open_time,
                            "o": kline.o,
                            "h": kline.h,
                            "l": kline.l,
                            "c": kline.c,
                            "v": kline.v,
                            "source": "binance_ws",
                            "is_final": kline.is_final,
                        }

                        try:
                            self.market_data.ingest_candle(payload)
                            self.db.commit()
                            stats["committed_candles"] += 1
                        except Exception:
                            self.db.rollback()
                            stats["ingest_errors"] += 1
                            continue

                        stats["processed_messages"] += 1
                        stats["per_interval"][interval] = int(stats["per_interval"][interval]) + 1
                        stats["per_symbol"][kline.symbol] = int(stats["per_symbol"].get(kline.symbol, 0)) + 1

                        if refresh_on_final and kline.is_final:
                            now = datetime.now(timezone.utc)
                            last = refresh_guard.get(kline.symbol)
                            if last is None or (
                                now - last
                            ).total_seconds() >= self.settings.ws_refresh_cooldown_seconds:
                                try:
                                    self.refresh_symbol(kline.symbol)
                                    stats["refresh_calls"] += 1
                                except Exception:
                                    self.db.rollback()
                                    stats["refresh_errors"] += 1
                                finally:
                                    refresh_guard[kline.symbol] = now

                        if max_messages and stats["processed_messages"] >= max_messages:
                            stop = True
                            break

                    if stop:
                        break

                    stats["reconnects"] += 1
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2.0, self.settings.ws_reconnect_max_seconds)
                except asyncio.CancelledError:
                    break
                except Exception:
                    self.db.rollback()
                    stats["reconnects"] += 1
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2.0, self.settings.ws_reconnect_max_seconds)

        tasks = [asyncio.create_task(_stream_one_interval(interval)) for interval in selected_intervals]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            stats["running"] = False

        return stats

    def reprocess_events(self, limit: int | None = None) -> dict:
        result = self.events.reprocess_pending(limit=limit)
        self.db.commit()
        return result

    def outbox_status(self) -> dict:
        return self.events.status_snapshot()

    def operational_checklist(
        self,
        *,
        symbol: str,
        universe: str,
        limit: int,
        days: int,
        alert_test_lookback_hours: int = 24,
        write_report: bool = True,
    ) -> dict:
        ready = HealthCheckService().evaluate()
        validation_payload = self.recompute_learning(symbol)
        alert_metrics = self.alert_metrics_report(days=days, write_report=False)
        outbox_status = self.outbox_status()
        strategy_metrics = self.metrics(symbol=symbol, version=self.settings.strategy_version)
        portfolio_budget = self.portfolio_budget_report(universe=universe, limit=limit, write_report=False)
        execution_quality = validation_payload.get("execution_quality") or self.execution_quality_report(
            symbol=symbol,
            days=days,
            write_report=False,
        )
        return self.operational_checklist_service.generate(
            symbol=symbol,
            universe=universe,
            strategy_version=self.settings.strategy_version,
            ready=ready,
            validation_payload=validation_payload,
            alert_metrics=alert_metrics,
            outbox_status=outbox_status,
            strategy_metrics=strategy_metrics,
            portfolio_budget=portfolio_budget,
            execution_quality=execution_quality,
            alert_test_lookback_hours=alert_test_lookback_hours,
            write_report=write_report,
        )

    def top_plans(self, symbol: str, limit: int) -> list:
        return self.plan_repo.list_top(symbol=symbol, timeframe="5m", limit=limit)

    def zones(self, symbol: str, tf: str, state: str | None = None) -> list[Zone]:
        return self.zone_repo.list_all(symbol=symbol, timeframe=tf, state=state)

    def metrics(self, symbol: str, version: str) -> dict:
        outcomes = self.outcome_repo.list_recent(symbol=symbol, days=180)
        snapshot = summarize_outcomes(outcomes)

        risk_gate = self.risk_gate.evaluate(
            RiskGateInput(
                consecutive_losses=snapshot.consecutive_losses,
                jump_rate=snapshot.jump_rate,
                api_healthy=True,
            )
        )
        operating_lock = self._operating_lock_snapshot()
        effective_risk_state = risk_gate.state
        risk_reason = risk_gate.reason
        if risk_gate.state != RiskGateState.CLOSED and operating_lock.active and operating_lock.enforced:
            effective_risk_state = RiskGateState.CLOSED
            risk_reason = operating_lock.reason
        score = score_strategy(snapshot, effective_risk_state)

        metric = self.metrics_repo.get(symbol=symbol, version=version)
        if not metric:
            return {
                "symbol": symbol,
                "version": version,
                "win_rate": snapshot.win_rate,
                "avg_win": snapshot.avg_win,
                "avg_loss": snapshot.avg_loss,
                "ev": snapshot.ev,
                "p1r": snapshot.p1r,
                "p2r": snapshot.p2r,
                "p3r": snapshot.p3r,
                "sample_size": snapshot.sample_size,
                "risk_state": effective_risk_state.value,
                "risk_reason": risk_reason,
                "operating_lock": operating_lock.to_dict(),
                "total_score": score.total_score,
                "grade": score.grade,
                "recommendation": score.recommendation,
            }
        return {
            "symbol": metric.symbol,
            "version": metric.version,
            "win_rate": metric.win_rate,
            "avg_win": metric.avg_win,
            "avg_loss": metric.avg_loss,
            "ev": metric.ev,
            "p1r": metric.p1r,
            "p2r": metric.p2r,
            "p3r": metric.p3r,
            "sample_size": snapshot.sample_size,
            "risk_state": effective_risk_state.value,
            "risk_reason": risk_reason,
            "operating_lock": operating_lock.to_dict(),
            "total_score": score.total_score,
            "grade": score.grade,
            "recommendation": score.recommendation,
        }

    def execution_quality_report(self, *, symbol: str, days: int, write_report: bool = True) -> dict:
        return self.execution_quality.generate(symbol=symbol, days=days, write_report=write_report)

    def pbo_dsr_artifact_store_report(
        self,
        *,
        symbol: str,
        version: str | None = None,
        write_report: bool = True,
    ) -> dict:
        active_version = version or self.settings.strategy_version
        recent_plans = self.plan_repo.list_recent(symbol=symbol, days=180)
        self.strategy_v2_pbo_dsr_trial_writer.generate(
            symbol=symbol,
            version=active_version,
            plans=recent_plans,
            write_report=False,
            persist=True,
        )
        self.strategy_v2_pbo_dsr_threshold_runner.generate(
            symbol=symbol,
            version=active_version,
            plans=recent_plans,
            write_report=False,
            persist=True,
        )
        payload = self.strategy_v2_pbo_dsr_artifact_store.generate(
            symbol=symbol,
            version=active_version,
            write_report=write_report,
        )
        self.db.commit()
        return payload

    def pbo_dsr_metrics_report(
        self,
        *,
        symbol: str,
        version: str | None = None,
        write_report: bool = True,
    ) -> dict:
        active_version = version or self.settings.strategy_version
        recent_plans = self.plan_repo.list_recent(symbol=symbol, days=180)
        self.strategy_v2_pbo_dsr_trial_writer.generate(
            symbol=symbol,
            version=active_version,
            plans=recent_plans,
            write_report=False,
            persist=True,
        )
        self.strategy_v2_pbo_dsr_threshold_runner.generate(
            symbol=symbol,
            version=active_version,
            plans=recent_plans,
            write_report=False,
            persist=True,
        )
        payload = self.strategy_v2_pbo_dsr_metrics.generate(
            symbol=symbol,
            version=active_version,
            write_report=write_report,
            persist_snapshot=True,
        )
        self.db.commit()
        return payload

    def pbo_dsr_trial_writer_report(
        self,
        *,
        symbol: str,
        version: str | None = None,
        write_report: bool = True,
    ) -> dict:
        active_version = version or self.settings.strategy_version
        recent_plans = self.plan_repo.list_recent(symbol=symbol, days=180)
        payload = self.strategy_v2_pbo_dsr_trial_writer.generate(
            symbol=symbol,
            version=active_version,
            plans=recent_plans,
            write_report=write_report,
            persist=True,
        )
        self.db.commit()
        return payload

    def pbo_dsr_threshold_runner_report(
        self,
        *,
        symbol: str,
        version: str | None = None,
        write_report: bool = True,
    ) -> dict:
        active_version = version or self.settings.strategy_version
        recent_plans = self.plan_repo.list_recent(symbol=symbol, days=180)
        payload = self.strategy_v2_pbo_dsr_threshold_runner.generate(
            symbol=symbol,
            version=active_version,
            plans=recent_plans,
            write_report=write_report,
            persist=True,
        )
        self.db.commit()
        return payload

    def stress_replay_assessment_report(
        self,
        *,
        symbol: str,
        version: str | None = None,
        write_report: bool = True,
    ) -> dict:
        active_version = version or self.settings.strategy_version
        stack = self._build_stress_replay_runtime_stack(
            symbol=symbol,
            version=active_version,
            write_report=False,
            run_prototype_worker=False,
        )
        return self.strategy_v2_stress_replay_assessment.generate(
            symbol=symbol,
            version=active_version,
            stress_validation=stack["stress_validation"],
            stress_replay_lineage=stack["stress_replay_lineage"],
            stress_replay_output_artifacts=stack["stress_replay_output_artifacts"],
            pbo_dsr_metrics=stack["pbo_dsr_metrics"],
            write_report=write_report,
        )

    def stress_replay_lineage_report(
        self,
        *,
        symbol: str,
        version: str | None = None,
        write_report: bool = True,
    ) -> dict:
        active_version = version or self.settings.strategy_version
        return self.strategy_v2_stress_replay_lineage.generate(
            symbol=symbol,
            version=active_version,
            write_report=write_report,
        )

    def stress_replay_runner_contract_report(
        self,
        *,
        symbol: str,
        version: str | None = None,
        write_report: bool = True,
    ) -> dict:
        active_version = version or self.settings.strategy_version
        stack = self._build_stress_replay_runtime_stack(
            symbol=symbol,
            version=active_version,
            write_report=False,
            run_prototype_worker=False,
        )
        return self.strategy_v2_stress_replay_runner_contract.generate(
            symbol=symbol,
            version=active_version,
            stress_validation=stack["stress_validation"],
            stress_replay_lineage=stack["stress_replay_lineage"],
            stress_replay_assessment=stack["stress_replay_assessment"],
            write_report=write_report,
        )

    def stress_replay_lineage_writer_report(
        self,
        *,
        symbol: str,
        version: str | None = None,
        write_report: bool = True,
    ) -> dict:
        active_version = version or self.settings.strategy_version
        stack = self._build_stress_replay_runtime_stack(
            symbol=symbol,
            version=active_version,
            write_report=False,
            run_prototype_worker=False,
        )
        return self.strategy_v2_stress_replay_lineage_writer.generate(
            symbol=symbol,
            version=active_version,
            stress_replay_lineage=stack["stress_replay_lineage"],
            stress_replay_runner_contract=stack["stress_replay_runner_contract"],
            write_report=write_report,
        )

    def stress_replay_output_artifacts_report(
        self,
        *,
        symbol: str,
        version: str | None = None,
        write_report: bool = True,
    ) -> dict:
        active_version = version or self.settings.strategy_version
        stress_validation = self.strategy_v2_stress_validation.generate(
            symbol=symbol,
            version=active_version,
            plans=self.plan_repo.list_recent(symbol=symbol, days=180),
            write_report=False,
        )
        return self.strategy_v2_stress_replay_output_artifacts.generate(
            symbol=symbol,
            version=active_version,
            stress_validation=stress_validation,
            write_report=write_report,
        )

    def stress_replay_prototype_worker_report(
        self,
        *,
        symbol: str,
        version: str | None = None,
        write_report: bool = True,
    ) -> dict:
        active_version = version or self.settings.strategy_version
        stack = self._build_stress_replay_runtime_stack(
            symbol=symbol,
            version=active_version,
            write_report=False,
            run_prototype_worker=False,
        )
        return self.strategy_v2_stress_replay_prototype_worker.generate(
            symbol=symbol,
            version=active_version,
            stress_validation=stack["stress_validation"],
            stress_replay_lineage_writer=stack["stress_replay_lineage_writer"],
            stress_replay_runner_contract=stack["stress_replay_runner_contract"],
            write_report=write_report,
        )
