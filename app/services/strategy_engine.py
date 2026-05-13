from __future__ import annotations

import asyncio
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from math import isfinite
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import ROOT_DIR, get_settings
from app.core.events import (
    ENTRY_TRIGGERED,
    PLAN_GENERATED,
    SESSION_IMPULSE_RETEST_MISS,
    TRADE_CLOSED,
    VALIDATION_FAIL,
    VALIDATION_WARN,
    ZONE_CREATED,
)
from app.core.enums import ExecutionFillStage, ExecutionMode, ExitReason, OrderLifecycleState, PlanState, RiskGateState, SubmitDecision
from app.db.models import (
    AlertSubscription,
    ExecutionFill,
    Plan,
    Zone,
    ZoneOutcome,
)
from app.db.session import SessionLocal
from app.db.repositories import (
    AlertRepository,
    AlertRetryQueueRepository,
    CandleRepository,
    MetricsRepository,
    OutcomeRepository,
    SessionImpulseRetestRuntimeAuditRepository,
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
from app.services.fast_failure_guard import fast_failure_hit, fast_failure_trigger_detail, resolve_fast_failure_policy
from app.services.execution_quality import ExecutionQualityService
from app.services.execution_friction_measurement import ExecutionFrictionMeasurementService
from app.services.execution_operator_dashboard import ExecutionOperatorDashboardService
from app.services.family_execution_degradation_advisory import FamilyExecutionDegradationAdvisoryService
from app.services.forward_stress_regime_validation import ForwardStressRegimeValidationService
from app.services.kill_condition_automation import KillConditionAutomationService
from app.services.lane_tracker import get_execution_lane_tracker
from app.services.live_candidate_promotion_readiness_runtime import build_live_candidate_promotion_readiness_from_db
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
from app.services.micro_main_strategy_research import (
    SessionImpulseRetestResearch,
    build_session_impulse_retest_shadow_summary,
    session_impulse_retest_profile_for_symbol,
)
from app.services.micro_main_live_readiness import (
    evaluate_micro_main_live_readiness,
    micro_main_live_readiness_to_dict,
)
from app.services.micro_main_universe_policy import (
    build_micro_main_rollout_contract_snapshot,
    build_micro_main_universe_policy_snapshot,
    micro_main_universe_entry,
)
from app.services.notification_dispatcher import NotificationDispatcher
from app.services.operational_checklist import OperationalChecklistService
from app.services.operating_lock import OperatingLockSnapshot, OperatingLockService
from app.services.operator_action_priority import OperatorActionPriorityService
from app.services.opportunity_capture import OpportunityCaptureService
from app.services.split_review_followup_ledger import summarize_split_review_followup_ledger
from app.services.parameter_changelog import ParameterChangelogService
from app.services.plan_generator import PlanGenerator
from app.services.positive_evidence_expansion import PositiveEvidenceExpansionService
from app.services.portfolio_budget_report import PortfolioBudgetReportService
from app.services.position_sizing import PositionSizingInput
from app.services.position_state_machine import FillApplyInput, PositionStateMachineService
from app.services.promotion_clearance_tracker import PromotionClearanceTrackerService
from app.services.promotion_decision_brief import PromotionDecisionBriefService
from app.services.promotion_governance import PromotionGovernanceService
from app.services.promotion_lifecycle_history import PromotionLifecycleHistoryService
from app.services.promotion_remediation_queue import PromotionRemediationQueueService
from app.services.promotion_reopen_queue import PromotionReopenQueueService
from app.services.promotion_review_queue import PromotionReviewQueueService
from app.services.replay_validation_bridge import UsdtProxyReplayValidationBridge
from app.services.research_promotion_operating_loop import ResearchPromotionOperatingLoopService
from app.services.risk_gate import RiskGate, RiskGateInput
from app.services.rollout_recommendation import RolloutRecommendationService
from app.services.runtime_kline_stream import RuntimeKlineStreamService
from app.services.runtime_worker_heartbeat import read_worker_heartbeat
from app.services.runtime_validation_orchestrator import RuntimeValidationOrchestrator
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
from app.services.thesis_fingerprint import ThesisFingerprintService
from app.services.validation_payload_cache import (
    READ_ONLY_RECOMPUTE_CACHE,
    ValidationPayloadCacheService,
)
from app.services.validation_report import ValidationReportService, validation_report_cache_miss_payload
from app.services.health_check import HealthCheckService
from app.services.zone_engine import ZoneEngine

_AUTO_ROUTE_SESSION_IMPULSE_RETEST_FAMILY = "session_impulse_retest"
_READ_ONLY_RECOMPUTE_CACHE = READ_ONLY_RECOMPUTE_CACHE
_ACTIVE_CONTRACT_REPLAY_BASELINE_FILE = "strategy_proof_contract_live_subset.json"


def _safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


_SAFETY_REASON_PREFIXES = (
    "reconciliation_",
    "kill_switch",
    "close_only",
    "operating_lock",
    "shock",
    "transition",
    "risk_lock",
    "session_lock",
    "validation_fail",
    "user_stream_stale",
)

_STRUCTURAL_REASONS = {
    "total_cap_reached",
    "directional_cap_reached",
    "cluster_cap_reached",
    "thesis_duplicate_blocked",
    "thesis_active_cap_reached",
    "thesis_cluster_cap_zero_risk",
}

_ROLLOUT_REASONS = {
    "mode_shadow_only",
    "mode_daily_trade_limit_reached",
    "mode_total_risk_cap_reached",
    "live_disabled_family",
    "execution_mode_cap_exceeded",
    "micro_live_session_not_allowed",
    "live_limit_only_entry_required",
    "live_entry_model_not_allowed",
    "micro_live_strategy_hour_not_allowed",
    "micro_live_strategy_time_bucket_not_allowed",
    "micro_live_plan_id_blocklisted",
    "live_family_cluster_window_cap_reached",
    "live_family_loss_cooldown_active",
}

_QUALITY_REASONS = {
    "risk_budget_below_min",
    "adjusted_score_non_positive",
    "invalid_candidate",
    "sizing_zero_risk",
}


class StrategyEngine:
    _GLOBAL_LINEAGE_VALIDATION_SYMBOL = "LINEAGE_GLOBAL"
    _GLOBAL_LINEAGE_VALIDATION_FAMILIES = ("sweep_reversal", "trend_continuation")

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
        self.session_impulse_retest_runtime_audit_repo = SessionImpulseRetestRuntimeAuditRepository(db)
        self.metrics_repo = MetricsRepository(db)
        self.replay_validation_bridge = UsdtProxyReplayValidationBridge(self.settings)

        self.market_data = MarketDataService(self.candle_repo)
        self.zone_engine = ZoneEngine()
        self.context_engine = ContextEngine()
        self.plan_generator = PlanGenerator()
        self.thesis = ThesisFingerprintService(self.settings)
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
            submission_repo=self.submission_repo,
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
            approval_loader=self._execution_approval_bundle_for_routing,
            exposure_loader=self._current_exposure_rows,
            settings=self.settings,
        )
        self.execution_coordinator = ExecutionCoordinator(
            plan_repo=self.plan_repo,
            intent_repo=self.intent_repo,
            submission_repo=self.submission_repo,
            approval_loader=self._execution_approval_bundle_for_routing,
            fill_ingest=self.ingest_execution_fill,
            live_submitter=self.submit_binance_order,
            live_symbol_rules_loader=self.load_binance_symbol_trading_rules,
            live_liquidity_loader=self.load_binance_live_liquidity_snapshot,
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
        self.validation_payload_cache = ValidationPayloadCacheService(self.settings)

    def _validation_payload_cache_path(self, symbol: str) -> Path:
        return self.validation_payload_cache.path(symbol)

    def _validation_payload_cache_scope(self) -> str:
        return self.validation_payload_cache.scope()

    def _validation_payload_cache_key(self, symbol: str) -> str:
        return self.validation_payload_cache.key(symbol)

    def _sqlite_database_artifact_paths(self) -> list[Path]:
        return self.validation_payload_cache.sqlite_database_artifact_paths()

    def _validation_payload_cache_stale_for_database(self, cache_mtime: float) -> bool:
        return self.validation_payload_cache.stale_for_database(cache_mtime)

    @staticmethod
    def _valid_cached_validation_payload(symbol: str, payload: Any) -> bool:
        return ValidationPayloadCacheService.valid_payload(symbol, payload)

    def _load_cached_validation_payload(self, symbol: str) -> dict[str, Any] | None:
        return self.validation_payload_cache.load(symbol)

    def _load_stale_conservative_validation_payload(self, symbol: str) -> dict[str, Any] | None:
        return self.validation_payload_cache.load_stale_conservative(symbol)

    def _store_cached_validation_payload(self, symbol: str, payload: dict[str, Any]) -> None:
        self.validation_payload_cache.store(symbol, payload)

    @staticmethod
    def _session_impulse_retest_plan_id_for_entry(*, symbol: str, direction: str, entry_ts: datetime) -> str:
        normalized_symbol = str(symbol or "").upper()
        direction_code = "L" if str(direction or "").lower() == "long" else "S"
        stamp = entry_ts.astimezone(timezone.utc).strftime("%Y%m%dT%H%M")
        return f"sir_{normalized_symbol}_{direction_code}_{stamp}"[:50]

    def _session_impulse_retest_miss_detector_symbols(self, symbols: list[str] | None = None) -> list[str]:
        requested = {
            str(item or "").upper()
            for item in list(symbols or [])
            if str(item or "").strip()
        }
        family_allowed = self._session_impulse_retest_allowed_symbols()
        requested_mode = self._auto_route_requested_mode()
        if requested_mode in {ExecutionMode.MICRO_LIVE, ExecutionMode.LIVE}:
            universe = self._session_impulse_retest_live_routable_symbols(requested_mode)
        else:
            live_allowed = set(self._csv_items(self.settings.auto_trading_allowed_symbols, case="upper"))
            micro_live_allowed = set(
                self._csv_items(getattr(self.settings, "auto_trading_micro_live_allowed_symbols", ""), case="upper")
            )
            configured = live_allowed | micro_live_allowed
            universe = family_allowed & configured
        if requested:
            universe &= requested
        return sorted(universe)

    def _session_impulse_retest_recent_replay_trades(
        self,
        *,
        symbol: str,
        cutoff: datetime,
        end_ts: datetime,
    ) -> list[Any]:
        first_1m = self.candle_repo.get_first_candle(symbol, "1m")
        last_1m = self.candle_repo.get_last_candle(symbol, "1m")
        last_5m = self.candle_repo.get_last_candle(symbol, "5m")
        if first_1m is None or last_1m is None or last_5m is None:
            return []

        first_ts = self._to_utc(first_1m.ts)
        bounded_end_ts = min(self._to_utc(last_1m.ts), end_ts)
        if bounded_end_ts <= cutoff:
            return []

        preload_start = max(first_ts, cutoff - timedelta(hours=12))
        candles_1m = self.candle_repo.list_range(
            symbol=symbol,
            timeframe="1m",
            start_ts=preload_start,
            end_ts=bounded_end_ts,
        )
        candles_5m = self.candle_repo.list_range(
            symbol=symbol,
            timeframe="5m",
            start_ts=preload_start - timedelta(days=2),
            end_ts=bounded_end_ts,
        )
        if len(candles_1m) < 600 or len(candles_5m) < 200:
            return []

        runtime = SessionImpulseRetestResearch(
            symbol=symbol,
            candles_1m=candles_1m,
            candles_5m=candles_5m,
            profile_name=session_impulse_retest_profile_for_symbol(symbol),
        )
        return [
            trade
            for trade in runtime.backtest()
            if cutoff <= self._to_utc(trade.entry_ts) <= bounded_end_ts
        ]

    def _session_impulse_retest_runtime_plan_observation(
        self,
        *,
        symbol: str,
        entry_ts: datetime,
        direction: str,
        lookahead_minutes: int = 12,
    ) -> dict[str, Any]:
        normalized_symbol = str(symbol or "").upper()
        expected_plan_id = self._session_impulse_retest_plan_id_for_entry(
            symbol=normalized_symbol,
            direction=direction,
            entry_ts=entry_ts,
        )
        first_1m = self.candle_repo.get_first_candle(normalized_symbol, "1m")
        last_1m = self.candle_repo.get_last_candle(normalized_symbol, "1m")
        if first_1m is None or last_1m is None:
            return {"seen": False, "plan_id": expected_plan_id, "reason": "missing_candles"}

        first_ts = self._to_utc(first_1m.ts)
        last_ts = self._to_utc(last_1m.ts)
        observation_end = min(last_ts, entry_ts + timedelta(minutes=max(int(lookahead_minutes), 1)))
        preload_start = max(first_ts, entry_ts - timedelta(hours=12))
        candles_1m_all = self.candle_repo.list_range(
            symbol=normalized_symbol,
            timeframe="1m",
            start_ts=preload_start,
            end_ts=observation_end,
        )
        candles_5m_all = self.candle_repo.list_range(
            symbol=normalized_symbol,
            timeframe="5m",
            start_ts=preload_start - timedelta(days=2),
            end_ts=observation_end,
        )
        if len(candles_1m_all) < 600 or len(candles_5m_all) < 200:
            return {"seen": False, "plan_id": expected_plan_id, "reason": "insufficient_candles"}

        exposure_rows = self.plan_repo.list_exposure_candidates(
            timeframe="5m",
            include_planned=self.settings.portfolio_overlay_include_planned_exposure,
            limit=300,
        )
        active_thesis_clusters = self._session_impulse_retest_active_thesis_clusters(exposure_rows)

        minute = 0
        while entry_ts + timedelta(minutes=minute) <= observation_end:
            cutoff_ts = entry_ts + timedelta(minutes=minute)
            candles_1m = [row for row in candles_1m_all if self._to_utc(row.ts) <= cutoff_ts]
            candles_5m = [row for row in candles_5m_all if self._to_utc(row.ts) <= cutoff_ts]
            plan = self._session_impulse_retest_runtime_plan(
                symbol=normalized_symbol,
                candles_1m=candles_1m,
                candles_5m=candles_5m,
                active_thesis_clusters=active_thesis_clusters,
            )
            if plan is not None and str(getattr(plan, "plan_id", "") or "") == expected_plan_id:
                return {
                    "seen": True,
                    "plan_id": expected_plan_id,
                    "observed_at": cutoff_ts.isoformat(),
                    "valid_from": self._to_utc(getattr(plan, "valid_from", cutoff_ts)).isoformat(),
                    "valid_until": self._to_utc(getattr(plan, "valid_until", cutoff_ts)).isoformat(),
                }
            minute += 1

        return {"seen": False, "plan_id": expected_plan_id, "reason": "runtime_plan_not_observed"}

    def _write_session_impulse_retest_miss_detector_report(
        self,
        *,
        payload: dict[str, Any],
        now: datetime,
    ) -> str | None:
        out_dir = Path(self.settings.session_impulse_retest_miss_detector_report_dir)
        if not out_dir.is_absolute():
            out_dir = ROOT_DIR / out_dir
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            out_path = out_dir / f"session_impulse_retest_miss_detector_{ts}.json"
            tmp_path = out_path.with_name(f".{out_path.name}.{uuid4().hex}.tmp")
            try:
                tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                tmp_path.replace(out_path)
            finally:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except OSError:
                    pass
            return str(out_path)
        except OSError:
            return None

    def _session_impulse_retest_runtime_started_at(self) -> datetime | None:
        payload = read_worker_heartbeat("ws", settings=self.settings)
        if not payload:
            return None
        details_payload = payload.get("details") if isinstance(payload.get("details"), dict) else {}
        started_at_raw = str(details_payload.get("started_at") or "").strip()
        if not started_at_raw:
            return None
        return self._maybe_utc(started_at_raw)

    def _ws_stream_auto_route_active(self, *, now: datetime | None = None) -> bool:
        payload = read_worker_heartbeat("ws", settings=self.settings)
        if not isinstance(payload, dict):
            return False
        if str(payload.get("status") or "").lower() != "ok":
            return False
        details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
        phase = str(details.get("phase") or "").lower()
        if not phase.startswith("streaming"):
            return False
        ts_raw = str(payload.get("ts") or "").strip()
        if not ts_raw:
            return False
        try:
            heartbeat_ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except ValueError:
            return False
        if heartbeat_ts.tzinfo is None:
            heartbeat_ts = heartbeat_ts.replace(tzinfo=timezone.utc)
        else:
            heartbeat_ts = heartbeat_ts.astimezone(timezone.utc)
        current = now or datetime.now(timezone.utc)
        max_age = max(1.0, self._maybe_float(self.settings.runtime_worker_ws_heartbeat_max_age_seconds) or 180.0)
        return 0 <= (current - heartbeat_ts).total_seconds() <= max_age

    def detect_session_impulse_retest_recent_misses(
        self,
        *,
        lookback_hours: int | None = None,
        symbols: list[str] | None = None,
        write_report: bool = False,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        if not self._safe_bool(self.settings.session_impulse_retest_miss_detector_enabled):
            return {
                "enabled": False,
                "family": "session_impulse_retest",
                "observation_mode": "replay_runtime_simulation",
                "generated_at": now.isoformat(),
                "lookback_hours": 0,
                "symbols": [],
                "expected_trade_count": 0,
                "runtime_observed_count": 0,
                "miss_count": 0,
                "misses": [],
                "report_path": None,
            }
        requested_mode = self._auto_route_requested_mode()
        if requested_mode is None:
            return {
                "enabled": False,
                "family": "session_impulse_retest",
                "observation_mode": "replay_runtime_simulation",
                "generated_at": now.isoformat(),
                "lookback_hours": 0,
                "symbols": [],
                "expected_trade_count": 0,
                "runtime_observed_count": 0,
                "miss_count": 0,
                "misses": [],
                "report_path": None,
                "disabled_reason": "auto_trading_disabled_or_shadow_mode",
            }
        live_auto_route_allowed, disabled_reason = self._session_impulse_retest_live_auto_route_allowed()
        if not live_auto_route_allowed:
            return {
                "enabled": False,
                "family": "session_impulse_retest",
                "observation_mode": "replay_runtime_simulation",
                "generated_at": now.isoformat(),
                "lookback_hours": 0,
                "symbols": [],
                "expected_trade_count": 0,
                "runtime_observed_count": 0,
                "miss_count": 0,
                "misses": [],
                "report_path": None,
                "disabled_reason": disabled_reason,
            }

        hours = max(1, self._maybe_int(lookback_hours) or self._maybe_int(self.settings.session_impulse_retest_miss_detector_lookback_hours) or 24)
        cutoff = now - timedelta(hours=hours)
        runtime_started_at = self._session_impulse_retest_runtime_started_at()
        effective_window_start = max(cutoff, runtime_started_at) if runtime_started_at is not None else cutoff
        target_symbols = self._session_impulse_retest_miss_detector_symbols(symbols=symbols)
        misses: list[dict[str, Any]] = []
        by_symbol: dict[str, dict[str, Any]] = {}
        expected_trade_count = 0
        runtime_observed_count = 0
        skipped_before_runtime_start_count = 0

        for symbol in target_symbols:
            replay_trades = self._session_impulse_retest_recent_replay_trades(
                symbol=symbol,
                cutoff=cutoff,
                end_ts=now,
            )
            symbol_summary = {
                "expected_trades": len(replay_trades),
                "runtime_observed_trades": 0,
                "misses": 0,
                "skipped_before_runtime_start": 0,
            }
            expected_trade_count += len(replay_trades)
            for trade in replay_trades:
                entry_ts = self._to_utc(trade.entry_ts)
                if runtime_started_at is not None and entry_ts < runtime_started_at:
                    skipped_before_runtime_start_count += 1
                    symbol_summary["skipped_before_runtime_start"] += 1
                    continue
                direction = str(getattr(trade, "direction", "") or "").lower()
                observation = self._session_impulse_retest_runtime_plan_observation(
                    symbol=symbol,
                    entry_ts=entry_ts,
                    direction=direction,
                )
                plan_id = str(observation.get("plan_id") or "")
                intents = self.intent_repo.list_for_plan(plan_id, limit=20) if plan_id else []
                submissions = self.submission_repo.list_for_plan(plan_id, limit=20) if plan_id else []
                if not self._safe_bool(observation.get("seen")):
                    if intents or submissions:
                        runtime_observed_count += 1
                        symbol_summary["runtime_observed_trades"] += 1
                        continue
                    misses.append(
                        {
                            "symbol": symbol,
                            "plan_id": plan_id,
                            "direction": direction,
                            "entry_ts": entry_ts.isoformat(),
                            "runtime_observed_at": "",
                            "valid_from": "",
                            "valid_until": "",
                            "intent_count": 0,
                            "submission_count": 0,
                            "miss_reason": "runtime_plan_not_seen",
                            "trade_r_value": round(float(getattr(trade, "r_value", 0.0) or 0.0), 4),
                            "trade_exit_reason": str(getattr(trade, "exit_reason", "") or ""),
                        }
                    )
                    symbol_summary["misses"] += 1
                    continue
                runtime_observed_count += 1
                symbol_summary["runtime_observed_trades"] += 1
                if intents:
                    continue
                misses.append(
                    {
                        "symbol": symbol,
                        "plan_id": plan_id,
                        "direction": direction,
                        "entry_ts": entry_ts.isoformat(),
                        "runtime_observed_at": str(observation.get("observed_at") or ""),
                        "valid_from": str(observation.get("valid_from") or ""),
                        "valid_until": str(observation.get("valid_until") or ""),
                        "intent_count": len(intents),
                        "submission_count": len(submissions),
                        "miss_reason": "missing_intent",
                        "trade_r_value": round(float(getattr(trade, "r_value", 0.0) or 0.0), 4),
                        "trade_exit_reason": str(getattr(trade, "exit_reason", "") or ""),
                    }
                )
                symbol_summary["misses"] += 1
            by_symbol[symbol] = symbol_summary

        payload: dict[str, Any] = {
            "enabled": True,
            "family": "session_impulse_retest",
            "observation_mode": "replay_runtime_simulation",
            "observation_note": (
                "runtime_observed_count is derived by replaying current runtime plan generation against historical candles; "
                "it is not a persisted runtime event log."
            ),
            "generated_at": now.isoformat(),
            "lookback_hours": hours,
            "window_start": cutoff.isoformat(),
            "requested_window_start": cutoff.isoformat(),
            "effective_window_start": effective_window_start.isoformat(),
            "runtime_started_at": runtime_started_at.isoformat() if runtime_started_at is not None else None,
            "window_end": now.isoformat(),
            "symbols": target_symbols,
            "expected_trade_count": expected_trade_count,
            "runtime_observed_count": runtime_observed_count,
            "skipped_before_runtime_start_count": skipped_before_runtime_start_count,
            "miss_count": len(misses),
            "misses": misses,
            "by_symbol": by_symbol,
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_session_impulse_retest_miss_detector_report(payload=payload, now=now)
        return payload

    def _maybe_emit_session_impulse_retest_miss_alert(self, *, report: dict[str, Any]) -> dict | None:
        if not self._safe_bool(self.settings.session_impulse_retest_miss_alert_enabled):
            return None

        miss_count = self._maybe_int(report.get("miss_count")) or 0
        if miss_count <= 0:
            return None

        alert_type = "session_impulse_retest_miss"
        alert_symbol = "SESSION_IMPULSE_RETEST"
        channel = self.settings.validation_alert_channel
        cooldown_seconds = max(0, self._maybe_int(self.settings.session_impulse_retest_miss_alert_cooldown_seconds) or 0)
        recent = self.alert_repo.find_recent(
            symbol=alert_symbol,
            channel=channel,
            alert_type=alert_type,
            within_seconds=cooldown_seconds,
        )
        symbols_with_misses = sorted(
            {
                str(item.get("symbol") or "").upper()
                for item in list(report.get("misses") or [])
                if str(item.get("symbol") or "").strip()
            }
        )
        if recent:
            return {
                "emitted": False,
                "reason": "cooldown_active",
                "type": alert_type,
                "channel": channel,
                "cooldown_seconds": cooldown_seconds,
                "miss_count": miss_count,
                "symbols_with_misses": symbols_with_misses,
                "report_path": report.get("report_path"),
            }

        now = datetime.now(timezone.utc)
        if not str(report.get("report_path") or "").strip():
            report["report_path"] = self._write_session_impulse_retest_miss_detector_report(payload=report, now=now)

        preview_items: list[str] = []
        for miss in list(report.get("misses") or [])[:4]:
            symbol = str(miss.get("symbol") or "").upper()
            direction = str(miss.get("direction") or "").upper()
            entry_ts = str(miss.get("entry_ts") or "")
            entry_suffix = entry_ts[-9:-3] if len(entry_ts) >= 9 else entry_ts
            preview_items.append(f"{symbol}:{direction}:{entry_suffix}")
        preview = ", ".join(item for item in preview_items if item.strip())
        symbol_clause = ",".join(symbols_with_misses[:8]) if symbols_with_misses else "n/a"
        message = f"miss={miss_count} lookback={int(report.get('lookback_hours') or 0)}h symbols={symbol_clause}"
        if preview:
            message += f" preview={preview}"

        base_payload = {
            "family": "session_impulse_retest",
            "status": "MISS",
            "generated_at": report.get("generated_at"),
            "report_path": report.get("report_path"),
            "lookback_hours": int(report.get("lookback_hours") or 0),
            "window_start": report.get("window_start"),
            "window_end": report.get("window_end"),
            "expected_trade_count": int(report.get("expected_trade_count") or 0),
            "runtime_observed_count": int(report.get("runtime_observed_count") or 0),
            "miss_count": miss_count,
            "symbols_with_misses": symbols_with_misses,
            "miss_preview": list(report.get("misses") or [])[:5],
            "message": message,
        }
        delivery = self.notification_dispatcher.dispatch(
            channel=channel,
            alert_type=alert_type,
            symbol=alert_symbol,
            payload=base_payload,
        )
        alert = AlertSubscription(
            alert_id=self._alert_id(prefix="sir_miss", symbol=alert_symbol),
            plan_id=None,
            symbol=alert_symbol,
            channel=channel,
            type=alert_type,
            payload={**base_payload, "delivery": delivery},
            triggered_ts=now,
        )
        self.alert_repo.add(alert)
        self.db.flush()
        retry_tasks = self.alert_retry_queue.capture_delivery_failure(
            source_alert_id=alert.alert_id,
            symbol=alert_symbol,
            alert_type=alert_type,
            payload=base_payload,
            delivery=delivery,
        )
        self.events.publish(
            SESSION_IMPULSE_RETEST_MISS,
            {
                "family": "session_impulse_retest",
                "generated_at": report.get("generated_at"),
                "report_path": report.get("report_path"),
                "lookback_hours": int(report.get("lookback_hours") or 0),
                "expected_trade_count": int(report.get("expected_trade_count") or 0),
                "runtime_observed_count": int(report.get("runtime_observed_count") or 0),
                "miss_count": miss_count,
                "symbols_with_misses": symbols_with_misses,
                "delivery": delivery,
                "dedupe_key": (
                    f"{SESSION_IMPULSE_RETEST_MISS}:"
                    f"{now.strftime('%Y%m%d%H')}:{miss_count}:{','.join(symbols_with_misses)}"
                ),
            },
        )
        return {
            "emitted": True,
            "type": alert_type,
            "channel": channel,
            "miss_count": miss_count,
            "symbols_with_misses": symbols_with_misses,
            "report_path": report.get("report_path"),
            "delivery": delivery,
            "retry_queued": len(retry_tasks),
        }

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
        submissions = self.submission_repo.list_recent(days=3, limit=10000)
        counted_plan_ids: set[str] = set()
        seen_plan_ids: set[str] = set()
        for row in submissions:
            plan_id = str(getattr(row, "plan_id", "") or "")
            if not plan_id or plan_id in seen_plan_ids:
                continue
            seen_plan_ids.add(plan_id)
            if self._submission_counts_as_live_contract(row):
                counted_plan_ids.add(plan_id)
        filtered_plans = [plan for plan in plans if str(plan.plan_id) in counted_plan_ids]
        return self.operating_lock.evaluate(plans=filtered_plans, now=now)

    @staticmethod
    def _submission_counts_as_live_contract(row: Any) -> bool:
        if str(getattr(row, "adapter", "") or "").lower() == "none":
            return False
        if str(getattr(row, "state", "") or "").upper() not in {
            OrderLifecycleState.CREATED.value,
            OrderLifecycleState.SUBMITTED.value,
            OrderLifecycleState.ACKNOWLEDGED.value,
            OrderLifecycleState.PARTIALLY_FILLED.value,
            OrderLifecycleState.FILLED.value,
        }:
            return False
        execution_mode = str(getattr(row, "execution_mode", "") or "").upper()
        requested_live = StrategyEngine._safe_bool(getattr(row, "requested_live", False))
        return requested_live or execution_mode in {ExecutionMode.MICRO_LIVE.value, ExecutionMode.LIVE.value}

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
        mode_value = str(getattr(self.settings.auto_trading_execution_mode, "value", self.settings.auto_trading_execution_mode) or "").upper()
        tracked_states = [
            PlanState.ARMED.value,
            PlanState.TRIGGERED.value,
            PlanState.ENTERED.value,
            PlanState.PARTIAL_EXIT.value,
            PlanState.CLOSED.value,
        ]
        if mode_value not in {ExecutionMode.MICRO_LIVE.value, ExecutionMode.LIVE.value}:
            return self.plan_repo.count_since(
                timeframe="5m",
                start_ts=start_of_day,
                states=tracked_states,
            )

        recent_live_submission_plan_ids: set[str] = set()
        for row in self.submission_repo.list_recent(days=2, limit=5000):
            plan_id = str(getattr(row, "plan_id", "") or "")
            if not plan_id:
                continue
            submitted_at = self._maybe_utc(getattr(row, "submitted_at", None))
            if submitted_at is None:
                continue
            if submitted_at < start_of_day:
                continue
            if self._submission_counts_as_live_contract(row):
                recent_live_submission_plan_ids.add(plan_id)

        count = len(recent_live_submission_plan_ids)
        counted_plan_ids = set(recent_live_submission_plan_ids)
        recent_plans = self.plan_repo.list_recent_global(
            timeframe="5m",
            days=2,
            states=tracked_states,
            limit=5000,
        )
        for row in recent_plans:
            valid_from = self._maybe_utc(getattr(row, "valid_from", None))
            if valid_from is None:
                continue
            if valid_from < start_of_day:
                continue
            validity = _safe_dict(getattr(row, "validity", None))
            row_mode = str(validity.get("execution_mode") or "").upper()
            plan_id = str(getattr(row, "plan_id", "") or "")
            if plan_id in counted_plan_ids:
                continue
            if row_mode in {ExecutionMode.MICRO_LIVE.value, ExecutionMode.LIVE.value}:
                counted_plan_ids.add(plan_id)
                count += 1
        return count

    def _current_exposure_rows(self) -> list:
        rows = self.plan_repo.list_exposure_candidates(
            timeframe="5m",
            include_planned=self.settings.portfolio_overlay_include_planned_exposure,
            limit=300,
        )
        mode_value = str(getattr(self.settings.auto_trading_execution_mode, "value", self.settings.auto_trading_execution_mode) or "").upper()
        if mode_value not in {ExecutionMode.MICRO_LIVE.value, ExecutionMode.LIVE.value}:
            return rows

        allowed_live_modes = {ExecutionMode.MICRO_LIVE.value, ExecutionMode.LIVE.value}
        recent_live_submission_plan_ids: set[str] = set()
        for submission in self.submission_repo.list_recent(days=7, limit=5000):
            plan_id = str(getattr(submission, "plan_id", "") or "")
            if not plan_id:
                continue
            if self._submission_counts_as_live_contract(submission):
                recent_live_submission_plan_ids.add(plan_id)

        filtered_rows = []
        for row in rows:
            validity = _safe_dict(getattr(row, "validity", None))
            row_mode = str(validity.get("execution_mode") or "").upper()
            if row_mode in allowed_live_modes or str(getattr(row, "plan_id", "") or "") in recent_live_submission_plan_ids:
                filtered_rows.append(row)
        present_plan_ids = {str(getattr(row, "plan_id", "") or "") for row in filtered_rows}
        get_plan = getattr(self.plan_repo, "get", None)
        if callable(get_plan):
            for plan_id in sorted(recent_live_submission_plan_ids - present_plan_ids):
                row = get_plan(plan_id)
                if row is not None:
                    filtered_rows.append(row)
        return filtered_rows

    @staticmethod
    def _submission_live_tranche_payload(submission: Any | None) -> dict[str, Any]:
        if submission is None:
            return {}
        attachments = _safe_dict(getattr(submission, "attachments", None))
        raw = _safe_dict(getattr(submission, "raw", None))
        return _safe_dict(attachments.get("live_tranche") or raw.get("live_tranche"))

    def _plan_allows_live_tranche_continuation(self, plan: Plan) -> bool:
        if not self._safe_bool(getattr(self.settings, "auto_trading_live_liquidity_gate_partial_submit_enabled", False)):
            return False
        latest_intent = self.intent_repo.latest_for_plan(str(plan.plan_id))
        if latest_intent is None:
            return False
        latest_submission = self.submission_repo.latest_for_intent(str(latest_intent.intent_id))
        if latest_submission is None:
            return False
        if str(latest_submission.adapter or "").lower() != "binance" or not self._safe_bool(latest_submission.requested_live):
            return False
        if str(latest_submission.state or "") != OrderLifecycleState.FILLED.value:
            return False
        tranche = self._submission_live_tranche_payload(latest_submission)
        if not self._safe_bool(tranche.get("additive_allowed")):
            return False
        remaining_notional = self._maybe_float(tranche.get("remaining_notional")) or 0.0
        min_tranche_notional = max(
            0.0,
            self._maybe_float(getattr(self.settings, "auto_trading_live_liquidity_gate_min_tranche_notional_usdt", 0.0)) or 0.0,
        )
        tranche_index = max(1, self._maybe_int(tranche.get("tranche_index")) or 1)
        max_tranches = max(
            1,
            self._maybe_int(tranche.get("max_tranches"))
            or self._maybe_int(getattr(self.settings, "auto_trading_live_liquidity_gate_max_tranches", 1))
            or 1,
        )
        return remaining_notional >= min_tranche_notional and tranche_index < max_tranches

    def _is_same_live_tranche_thesis(self, *, plan: Plan, executable_plan: dict[str, Any], exposure: Plan) -> bool:
        requested_fingerprint = _safe_dict(executable_plan.get("thesis_fingerprint"))
        if not requested_fingerprint:
            requested_fingerprint = self.thesis.build_from_plan(plan)
        return self.thesis.same_thesis(requested_fingerprint, self.thesis.build_from_plan(exposure))

    def _has_live_tranche_continuation(
        self,
        *,
        plan: Plan,
        executable_plan: dict[str, Any],
        exposure_rows: list[Plan],
    ) -> bool:
        for row in exposure_rows:
            if str(getattr(row, "plan_id", "") or "") == str(plan.plan_id or ""):
                continue
            if not self._is_same_live_tranche_thesis(plan=plan, executable_plan=executable_plan, exposure=row):
                continue
            if self._plan_allows_live_tranche_continuation(row):
                return True
        return False

    def _candidate_row_with_live_tranche_override(
        self,
        *,
        plan: Plan,
        executable_plan: dict[str, Any],
        candidate_row: dict[str, Any] | None,
        exposure_rows: list[Plan],
    ) -> dict[str, Any] | None:
        if not candidate_row:
            return candidate_row
        block_reason = str(candidate_row.get("block_reason") or "")
        thesis_rejected_reason = str(candidate_row.get("thesis_rejected_reason") or "")
        continuation_overridable_blocks = {
            "thesis_duplicate_blocked",
            "thesis_active_cap_reached",
            "mode_total_risk_cap_reached",
            "total_cap_reached",
            "directional_cap_reached",
            "cluster_cap_reached",
        }
        if block_reason not in continuation_overridable_blocks and thesis_rejected_reason != "duplicate_active_thesis":
            return candidate_row
        if not self._has_live_tranche_continuation(
            plan=plan,
            executable_plan=executable_plan,
            exposure_rows=exposure_rows,
        ):
            return candidate_row

        adjusted = dict(candidate_row)
        adjusted["accepted"] = True
        adjusted["block_reason"] = None
        adjusted["block_reason_message"] = None
        adjusted["thesis_rejected_reason"] = None
        adjusted["live_tranche_continuation_override"] = True
        adjusted["live_tranche_continuation_override_reason"] = (
            "Same-thesis duplicate gate bypassed because the prior live tranche is filled "
            "and explicitly allows a remaining tranche."
        )
        return adjusted

    @staticmethod
    def _replace_candidate_row(
        *,
        candidate_rows: list[dict[str, Any]],
        candidate_row: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if not candidate_row:
            return candidate_rows
        plan_id = str(candidate_row.get("plan_id") or "")
        if not plan_id:
            return candidate_rows
        return [
            dict(candidate_row) if str(row.get("plan_id") or "") == plan_id else row
            for row in candidate_rows
        ]

    def _live_cluster_guard(
        self,
        *,
        plan: Plan,
        executable_plan: dict[str, Any],
        requested_mode: ExecutionMode,
        exposure_rows: list[Plan],
    ) -> dict[str, Any] | None:
        if requested_mode not in {ExecutionMode.MICRO_LIVE, ExecutionMode.LIVE}:
            return None

        plan_validity = _safe_dict(getattr(plan, "validity", None))
        family = str(executable_plan.get("strategy_family") or plan_validity.get("strategy_family") or "legacy_zone_plan").lower()
        requested_direction = str(
            executable_plan.get("direction")
            or plan_validity.get("direction")
            or getattr(plan, "direction", "")
            or ""
        ).lower()
        cluster_window_minutes = max(0, self._maybe_int(self.settings.auto_trading_live_family_cluster_window_minutes) or 0)
        max_same_family_entries = max(0, self._maybe_int(self.settings.auto_trading_live_max_same_family_entries_per_window) or 0)
        max_same_family_direction_exposures = max(
            0,
            self._maybe_int(self.settings.auto_trading_live_max_same_family_direction_exposures) or 0,
        )
        loss_cooldown_minutes = max(0, self._maybe_int(self.settings.auto_trading_live_recent_loss_cooldown_minutes) or 0)
        loss_trigger_count = max(0, self._maybe_int(self.settings.auto_trading_live_recent_loss_trigger_count) or 0)
        now = datetime.now(timezone.utc)

        recent_window_entries: list[dict[str, Any]] = []
        recent_direction_exposures: list[dict[str, Any]] = []
        cluster_cutoff = now - timedelta(minutes=cluster_window_minutes) if cluster_window_minutes > 0 else now
        if cluster_window_minutes > 0 and max_same_family_entries > 0:
            for row in exposure_rows:
                if str(getattr(row, "plan_id", "") or "") == str(plan.plan_id or ""):
                    continue
                if self._is_same_live_tranche_thesis(plan=plan, executable_plan=executable_plan, exposure=row) and self._plan_allows_live_tranche_continuation(row):
                    continue
                validity = _safe_dict(getattr(row, "validity", None))
                row_family = str(validity.get("strategy_family") or "legacy_zone_plan").lower()
                if row_family != family:
                    continue
                opened_ts = self._maybe_utc(validity.get("entry_ts") or getattr(row, "valid_from", None))
                if opened_ts is None:
                    continue
                if opened_ts < cluster_cutoff:
                    continue
                recent_window_entries.append(
                    {
                        "plan_id": str(getattr(row, "plan_id", "") or ""),
                        "symbol": str(getattr(row, "symbol", "") or "").upper(),
                        "state": str(getattr(row, "state", "") or ""),
                        "opened_ts": opened_ts.isoformat(),
                    }
                )

        if max_same_family_direction_exposures > 0 and requested_direction:
            for row in exposure_rows:
                if str(getattr(row, "plan_id", "") or "") == str(plan.plan_id or ""):
                    continue
                if self._is_same_live_tranche_thesis(plan=plan, executable_plan=executable_plan, exposure=row) and self._plan_allows_live_tranche_continuation(row):
                    continue
                validity = _safe_dict(getattr(row, "validity", None))
                row_family = str(validity.get("strategy_family") or "legacy_zone_plan").lower()
                if row_family != family:
                    continue
                row_direction = str(
                    getattr(row, "direction", None)
                    or validity.get("direction")
                    or ""
                ).lower()
                if row_direction != requested_direction:
                    continue
                opened_ts = self._maybe_utc(validity.get("entry_ts") or getattr(row, "valid_from", None))
                recent_direction_exposures.append(
                    {
                        "plan_id": str(getattr(row, "plan_id", "") or ""),
                        "symbol": str(getattr(row, "symbol", "") or "").upper(),
                        "state": str(getattr(row, "state", "") or ""),
                        "direction": row_direction,
                        "opened_ts": opened_ts.isoformat() if opened_ts is not None else "",
                    }
                )

        recent_family_losses: list[dict[str, Any]] = []
        loss_cutoff = now - timedelta(minutes=loss_cooldown_minutes) if loss_cooldown_minutes > 0 else now
        if loss_cooldown_minutes > 0 and loss_trigger_count > 0:
            lookback_days = max(2, int((loss_cooldown_minutes // (24 * 60)) + 2))
            recent_closed_rows = self.plan_repo.list_recent_global(
                timeframe="5m",
                days=lookback_days,
                states=[PlanState.CLOSED.value],
                limit=2000,
            )
            for row in recent_closed_rows:
                if str(getattr(row, "plan_id", "") or "") == str(plan.plan_id or ""):
                    continue
                validity = _safe_dict(getattr(row, "validity", None))
                row_family = str(validity.get("strategy_family") or "legacy_zone_plan").lower()
                if row_family != family:
                    continue
                closed_ts_raw = validity.get("final_exit_ts") or validity.get("last_exit_ts")
                if not closed_ts_raw:
                    continue
                closed_ts = self._maybe_utc(closed_ts_raw)
                if closed_ts is None:
                    continue
                if closed_ts < loss_cutoff:
                    continue
                realized_r = self._maybe_float(validity.get("final_exit_realized_r"))
                if realized_r is None or realized_r >= 0.0:
                    continue
                recent_family_losses.append(
                    {
                        "plan_id": str(getattr(row, "plan_id", "") or ""),
                        "symbol": str(getattr(row, "symbol", "") or "").upper(),
                        "closed_ts": closed_ts.isoformat(),
                        "realized_r": round(float(realized_r), 4),
                        "exit_reason": str(validity.get("final_exit_reason") or ""),
                    }
                )

        recent_family_losses.sort(key=lambda item: str(item.get("closed_ts") or ""), reverse=True)
        return {
            "family": family,
            "cluster_window_minutes": cluster_window_minutes,
            "max_same_family_entries_per_window": max_same_family_entries,
            "recent_family_window_entry_count": len(recent_window_entries),
            "recent_family_window_symbols": [
                str(item.get("symbol") or "").upper()
                for item in recent_window_entries
                if str(item.get("symbol") or "").strip()
            ],
            "recent_family_window_entries": recent_window_entries,
            "direction": requested_direction,
            "max_same_family_direction_exposures": max_same_family_direction_exposures,
            "recent_family_direction_exposure_count": len(recent_direction_exposures),
            "recent_family_direction_exposure_symbols": [
                str(item.get("symbol") or "").upper()
                for item in recent_direction_exposures
                if str(item.get("symbol") or "").strip()
            ],
            "recent_family_direction_exposures": recent_direction_exposures,
            "loss_cooldown_minutes": loss_cooldown_minutes,
            "loss_cooldown_trigger_count": loss_trigger_count,
            "recent_family_loss_count": len(recent_family_losses),
            "recent_family_loss_symbols": [
                str(item.get("symbol") or "").upper()
                for item in recent_family_losses
                if str(item.get("symbol") or "").strip()
            ],
            "recent_family_losses": recent_family_losses,
        }

    def _micro_live_symbol_priority_guard(
        self,
        *,
        plan: Plan,
        executable_plan: dict[str, Any],
        requested_mode: ExecutionMode,
    ) -> dict[str, Any] | None:
        if requested_mode != ExecutionMode.MICRO_LIVE:
            return None

        symbol = str(getattr(plan, "symbol", "") or "").upper()
        if not symbol:
            return None

        entry_type = str(executable_plan.get("entry_type") or "").strip().lower()
        if entry_type and entry_type != "limit":
            return None

        family = str(
            executable_plan.get("strategy_family")
            or _safe_dict(getattr(plan, "validity", None)).get("strategy_family")
            or "legacy_zone_plan"
        ).lower()
        if not family:
            return None

        allowed_symbols = [
            item.strip().upper()
            for item in str(self.settings.auto_trading_micro_live_allowed_symbols or "").split(",")
            if item.strip()
        ]
        priority_symbols = [
            item.strip().upper()
            for item in str(self.settings.auto_trading_micro_live_symbol_priority or "").split(",")
            if item.strip()
        ]
        if not priority_symbols:
            priority_symbols = allowed_symbols
        if allowed_symbols:
            allowed_set = set(allowed_symbols)
            priority_symbols = [item for item in priority_symbols if item in allowed_set]
        if symbol not in priority_symbols:
            return None

        symbol_index = priority_symbols.index(symbol)
        if symbol_index <= 0:
            return {
                "active": True,
                "blocked": False,
                "symbol": symbol,
                "preferred_symbols": priority_symbols,
                "summary": f"{symbol} is currently the top-priority MICRO_LIVE symbol.",
            }

        higher_priority_symbols = set(priority_symbols[:symbol_index])
        lookback_minutes = max(1, self._maybe_int(self.settings.auto_trading_micro_live_priority_submit_ready_lookback_minutes) or 180)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
        lookback_days = max(1, int((lookback_minutes // (24 * 60)) + 2))
        recent_intents = self.intent_repo.list_recent(limit=500, days=lookback_days)

        latest_by_plan: dict[str, tuple[Any, datetime]] = {}
        for row in recent_intents:
            created_at = self._maybe_utc(getattr(row, "created_at", None))
            if created_at is None:
                continue
            if created_at < cutoff:
                continue
            row_symbol = str(getattr(row, "symbol", "") or "").upper()
            if row_symbol not in higher_priority_symbols:
                continue
            row_family = str(getattr(row, "strategy_family", "") or "").lower()
            if row_family != family:
                continue
            plan_id = str(getattr(row, "plan_id", "") or "")
            if not plan_id or plan_id in latest_by_plan:
                continue
            latest_by_plan[plan_id] = (row, created_at)

        preferred_candidates: list[dict[str, Any]] = []
        for row, row_created_at in latest_by_plan.values():
            approval_state = str(getattr(row, "approval_state", "") or "")
            if not approval_state.startswith("APPROVED"):
                continue
            if str(getattr(row, "decision_reason_code", "") or "") != "submit_ready":
                continue
            payload = _safe_dict(getattr(row, "payload", None))
            row_entry_model = str(payload.get("entry_model") or payload.get("entry_type") or "").strip().upper()
            if row_entry_model != "LIMIT":
                continue
            preferred_candidates.append(
                {
                    "symbol": str(getattr(row, "symbol", "") or "").upper(),
                    "plan_id": str(getattr(row, "plan_id", "") or ""),
                    "created_at": row_created_at.isoformat(),
                }
            )

        preferred_candidates.sort(
            key=lambda item: (
                priority_symbols.index(str(item.get("symbol") or "").upper()),
                -self._to_utc(item.get("created_at")).timestamp(),
            )
        )
        if not preferred_candidates:
            return {
                "active": True,
                "blocked": False,
                "symbol": symbol,
                "preferred_symbols": priority_symbols,
                "lookback_minutes": lookback_minutes,
                "summary": f"{symbol} has no higher-priority MICRO_LIVE submit-ready symbol inside the last {lookback_minutes}m.",
            }

        preferred = preferred_candidates[0]
        preferred_symbol = str(preferred.get("symbol") or "")
        preferred_created_at = str(preferred.get("created_at") or "")
        return {
            "active": True,
            "blocked": True,
            "symbol": symbol,
            "preferred_symbols": priority_symbols,
            "preferred_symbol": preferred_symbol,
            "preferred_plan_id": str(preferred.get("plan_id") or ""),
            "preferred_created_at": preferred_created_at,
            "lookback_minutes": lookback_minutes,
            "summary": (
                f"{symbol} is fallback-only while higher-priority {preferred_symbol} has a submit-ready LIMIT candidate "
                f"inside the last {lookback_minutes}m."
            ),
        }

    def _gate_context_for_symbol(
        self,
        *,
        symbol: str,
    ) -> tuple[ContextSnapshot | None, RiskGateState, str, OperatingLockSnapshot]:
        context = self.current_context(symbol)
        jump_rate = context.jump_rate_5m if context else 0.0
        gate_state, _, gate_reason, operating_lock = self._evaluate_gate(symbol=symbol, jump_rate=jump_rate)
        return context, gate_state, gate_reason, operating_lock

    def _max_candidate_plans_per_symbol(self) -> int:
        return max(1, self._maybe_int(self.settings.max_candidate_plans_per_symbol) or 10)

    def _execution_candidate_rows(
        self,
        *,
        symbol: str,
    ) -> tuple[ContextSnapshot | None, list[dict[str, Any]], dict[str, Any]]:
        context, gate_state, gate_reason, operating_lock = self._gate_context_for_symbol(symbol=symbol)
        base_rows = self.scanner.candidate_rows(
            symbols=[symbol],
            risk_state=gate_state,
            plans_per_symbol=max(10, self._max_candidate_plans_per_symbol()),
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

    @staticmethod
    def _csv_items(raw: str | None, *, case: str = "asis") -> list[str]:
        items: list[str] = []
        for value in str(raw or "").split(","):
            item = str(value or "").strip()
            if not item:
                continue
            if case == "upper":
                items.append(item.upper())
            elif case == "lower":
                items.append(item.lower())
            else:
                items.append(item)
        return items

    def _micro_live_direction_contract(self) -> dict[str, list[str]]:
        mapping: dict[str, list[str]] = {}
        raw = str(getattr(self.settings, "auto_trading_micro_live_direction_contract", "") or "")
        for item in raw.split(","):
            token = str(item or "").strip()
            if not token or ":" not in token:
                continue
            symbol, raw_directions = token.split(":", 1)
            normalized_symbol = str(symbol or "").strip().upper()
            if not normalized_symbol:
                continue
            directions: list[str] = []
            for direction in str(raw_directions or "").replace("/", "|").split("|"):
                normalized_direction = str(direction or "").strip().upper()
                if normalized_direction and normalized_direction not in directions:
                    directions.append(normalized_direction)
            if directions:
                mapping[normalized_symbol] = directions
        return mapping

    @staticmethod
    def _gate_group_for_reason(reason: str | None) -> str:
        normalized = str(reason or "").strip().lower()
        if not normalized:
            return "unknown"
        if normalized.startswith(_SAFETY_REASON_PREFIXES):
            return "safety"
        if normalized in _STRUCTURAL_REASONS:
            return "structural"
        if normalized in _ROLLOUT_REASONS:
            return "rollout"
        if normalized in _QUALITY_REASONS:
            return "quality"
        return "unknown"

    @classmethod
    def _gate_group_counts_from_reasons(cls, reason_counts: dict[str, int] | None) -> dict[str, int]:
        counts = {"quality": 0, "rollout": 0, "structural": 0, "safety": 0, "unknown": 0}
        for reason, value in dict(reason_counts or {}).items():
            counts[cls._gate_group_for_reason(reason)] += int(value or 0)
        return counts

    def _active_contract_filters(self, *, symbol: str | None) -> dict[str, Any] | None:
        active_symbol = str(symbol or "").upper()
        if not active_symbol:
            return None
        if str(self.settings.auto_trading_execution_mode or "").upper() != ExecutionMode.MICRO_LIVE.value:
            return None

        allowed_symbols = self._csv_items(self.settings.auto_trading_micro_live_allowed_symbols, case="upper")
        if allowed_symbols and active_symbol not in set(allowed_symbols):
            return None

        strategy_families = self._csv_items(
            getattr(self.settings, "auto_trading_micro_live_allowed_families", ""),
            case="lower",
        )
        entry_models = self._csv_items(
            getattr(self.settings, "auto_trading_micro_live_allowed_entry_models", ""),
            case="upper",
        )
        directions = list(self._micro_live_direction_contract().get(active_symbol) or [])
        if not strategy_families and not entry_models:
            return None

        return {
            "symbol": active_symbol,
            "execution_mode": ExecutionMode.MICRO_LIVE.value,
            "strategy_families": strategy_families,
            "entry_models": entry_models,
            "directions": directions,
        }

    def _active_contract_summary(
        self,
        *,
        symbol: str,
        days: int,
        portfolio_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        filters = self._active_contract_filters(symbol=symbol)
        if not filters:
            return None

        filtered_portfolio_summary = self._filtered_portfolio_summary(
            portfolio_summary=portfolio_summary,
            filters=filters,
        )
        strategy_families = list(filters.get("strategy_families") or [])
        entry_models = list(filters.get("entry_models") or [])
        directions = list(filters.get("directions") or [])
        execution_quality_summary = self.execution_quality_report(
            symbol=symbol,
            days=days,
            write_report=False,
            strategy_families=strategy_families,
            entry_models=entry_models,
            directions=directions,
        )
        score_to_outcome_funnel_summary = self.score_to_outcome_funnel.generate(
            symbol=symbol,
            version=self.settings.strategy_version,
            days=days,
            portfolio_budget=filtered_portfolio_summary,
            strategy_families=strategy_families,
            entry_models=entry_models,
            directions=directions,
        )
        opportunity_capture_summary = self._opportunity_capture_summary(
            score_to_outcome_funnel_summary=score_to_outcome_funnel_summary,
            portfolio_budget=filtered_portfolio_summary,
            execution_quality_summary=execution_quality_summary,
        )
        promotion_shadow_counter = self._active_contract_promotion_shadow_counter(
            symbol=symbol,
            days=days,
            filters=filters,
        )
        eq_summary = dict(execution_quality_summary or {})
        history = dict(dict(score_to_outcome_funnel_summary or {}).get("historical_execution_outcomes") or {})
        return {
            "filters": filters,
            "execution_quality_summary": execution_quality_summary,
            "score_to_outcome_funnel_summary": score_to_outcome_funnel_summary,
            "opportunity_capture_summary": opportunity_capture_summary,
            "promotion_shadow_counter": promotion_shadow_counter,
            "shadow_relaxation_priority": self._active_contract_shadow_relaxation_priority(promotion_shadow_counter),
            "transition_edge_variant_shadow": self._active_contract_transition_edge_variant_shadow(
                symbol=symbol,
                filters=filters,
            ),
            "selection_shortfall_breakdown": self._contract_selection_shortfall_breakdown(
                filtered_portfolio_summary=filtered_portfolio_summary
            ),
            "raw_counts": {
                "plans_total": int(eq_summary.get("plans_total", 0) or 0),
                "matured_plans": int(eq_summary.get("plans_matured", 0) or 0),
                "filled_matured_plans": int(eq_summary.get("fills_matched", 0) or 0),
                "unfilled_matured_plans": max(
                    int(eq_summary.get("plans_matured", 0) or 0) - int(eq_summary.get("fills_matched", 0) or 0),
                    0,
                ),
                "submitted_plans": int(history.get("submitted", 0) or 0),
                "filled_submitted_plans": int(history.get("filled", 0) or 0),
                "closed_filled_plans": int(history.get("closed", 0) or 0),
            },
        }

    def _active_contract_transition_edge_variant_shadow(
        self,
        *,
        symbol: str,
        filters: dict[str, Any],
    ) -> dict[str, Any] | None:
        filter_symbol = str(filters.get("symbol") or "").strip().upper()
        strategy_families = {
            str(item or "").strip().lower()
            for item in list(filters.get("strategy_families") or [])
            if str(item or "").strip()
        }
        entry_models = {
            str(item or "").strip().upper()
            for item in list(filters.get("entry_models") or [])
            if str(item or "").strip()
        }
        directions = {
            str(item or "").strip().upper()
            for item in list(filters.get("directions") or [])
            if str(item or "").strip()
        }
        if filter_symbol and str(symbol or "").strip().upper() != filter_symbol:
            return None
        if strategy_families and "sweep_reversal" not in strategy_families:
            return None
        if entry_models and "LIMIT" not in entry_models:
            return None
        if directions and directions != {"LONG", "SHORT"}:
            return {
                "available": False,
                "enabled": self._safe_bool(self.settings.transition_edge_variant_enabled),
                "shadow_only": self._safe_bool(self.settings.transition_edge_variant_shadow_only),
                "variant": "exp_6_fvg_relaxed_plus_transition_override",
                "status": "direction_contract_not_supported",
                "required_contract_directions": sorted(directions),
                "current_snapshot_only": True,
                "activation_note": "Direction-scoped active contract is narrower than the current symbol-wide transition shadow diagnostics.",
            }

        candles5 = self.market_data.recent_candles(symbol, "5m", limit=300)
        candles15 = self.market_data.recent_candles(symbol, "15m", limit=300)
        if len(candles5) < 60 or len(candles15) < 60:
            return {
                "available": False,
                "enabled": self._safe_bool(self.settings.transition_edge_variant_enabled),
                "shadow_only": self._safe_bool(self.settings.transition_edge_variant_shadow_only),
                "variant": "exp_6_fvg_relaxed_plus_transition_override",
                "status": "insufficient_candles",
                "required_candles": 60,
                "candles_5m": len(candles5),
                "candles_15m": len(candles15),
            }

        context = self.context_engine.build_snapshot(symbol=symbol, candles_5m=candles5, candles_15m=candles15)
        existing = self.zone_repo.list_all(symbol=symbol, timeframe="15m")
        zones = self.zone_engine.refresh(symbol=symbol, candles_15m=candles15, existing=existing)
        active_zones = [zone for zone in zones if zone.state != "expired"]
        gate_state, can_open, gate_reason, _ = self._evaluate_gate(
            symbol=symbol,
            jump_rate=context.jump_rate_5m,
        )
        if not can_open:
            return {
                "available": False,
                "enabled": self._safe_bool(self.settings.transition_edge_variant_enabled),
                "shadow_only": self._safe_bool(self.settings.transition_edge_variant_shadow_only),
                "variant": "exp_6_fvg_relaxed_plus_transition_override",
                "status": "skipped_by_gate",
                "risk_state": str(getattr(gate_state, "value", gate_state) or ""),
                "gate_reason": str(gate_reason or ""),
                "active_zone_count": len(active_zones),
                "regime_profile": self.plan_generator.resolve_regime_label(context),
                "transition_state": context.transition_state,
                "transition_lock_reason": context.transition_lock_reason,
            }

        _, feature_calibration = self._runtime_feature_calibration(symbol=symbol, context=context)
        diagnostics = self.plan_generator.generation_diagnostics(
            symbol=symbol,
            zones=active_zones,
            context=context,
            candles_5m=candles5,
            importance_calibration=feature_calibration,
        )
        shadow_summary = dict(diagnostics.get("transition_edge_variant_shadow_summary") or {})
        low_confluence_block_count = int(
            dict(diagnostics.get("hard_gate_block_counts") or {}).get("low_confluence", 0) or 0
        )
        return {
            "available": bool(shadow_summary) or self._safe_bool(self.settings.transition_edge_variant_enabled),
            "enabled": self._safe_bool(self.settings.transition_edge_variant_enabled),
            "shadow_only": self._safe_bool(self.settings.transition_edge_variant_shadow_only),
            "variant": "exp_6_fvg_relaxed_plus_transition_override",
            "status": "shadow_only_compare" if self._safe_bool(self.settings.transition_edge_variant_shadow_only) else "live_enabled",
            "regime_profile": diagnostics.get("regime_profile"),
            "transition_state": diagnostics.get("transition_state"),
            "transition_lock_reason": diagnostics.get("transition_lock_reason"),
            "generation_state": diagnostics.get("generation_state"),
            "active_zone_count": int(diagnostics.get("active_zone_count", 0) or 0),
            "post_hard_gate_zone_count": int(diagnostics.get("post_hard_gate_zone_count", 0) or 0),
            "pre_generation_candidate_count": int(diagnostics.get("pre_generation_candidate_count", 0) or 0),
            "shadow_evaluated_count": int(shadow_summary.get("evaluated", 0) or 0),
            "shadow_pass_count": int(shadow_summary.get("pass", 0) or 0),
            "shadow_pass_rate": float(shadow_summary.get("pass_rate", 0.0) or 0.0),
            "shadow_rescue_reason_mix": dict(shadow_summary.get("reason_mix") or {}),
            "shadow_candidate_delta": int(shadow_summary.get("shadow_candidate_delta", 0) or 0),
            "candidate_baseline": int(shadow_summary.get("candidate_baseline", 0) or 0),
            "candidate_shadow": int(shadow_summary.get("candidate_shadow", 0) or 0),
            "low_confluence_block_baseline": low_confluence_block_count,
            "low_confluence_block_shadow": int(shadow_summary.get("low_confluence_block_shadow", 0) or 0),
            "low_confluence_block_delta": int(shadow_summary.get("low_confluence_block_delta", 0) or 0),
            "expected_ev_r_proxy": float(shadow_summary.get("expected_ev_r_proxy", 0.0) or 0.0),
            "current_snapshot_only": True,
            "activation_note": "Structure/proxy validation only while shadow_only remains enabled.",
        }

    def _session_impulse_retest_shadow_summary(self, *, symbol: str) -> dict[str, Any]:
        candles_1m = self.market_data.recent_candles(symbol, "1m", limit=900)
        candles_5m = self.market_data.recent_candles(symbol, "5m", limit=300)
        allowed_symbols = [
            item.strip().upper()
            for item in str(self.settings.session_impulse_retest_allowed_symbols or "").split(",")
            if item.strip()
        ]
        return build_session_impulse_retest_shadow_summary(
            symbol=symbol,
            candles_1m=candles_1m,
            candles_5m=candles_5m,
            enabled=self._safe_bool(self.settings.session_impulse_retest_enabled),
            shadow_only=self._safe_bool(self.settings.session_impulse_retest_shadow_only),
            allowed_symbols=allowed_symbols,
        )

    def _session_impulse_retest_rollout_readiness(self, *, symbol: str, shadow_summary: dict[str, Any] | None = None) -> dict[str, Any]:
        universe_policy = build_micro_main_universe_policy_snapshot()
        readiness = evaluate_micro_main_live_readiness(
            symbol=symbol,
            shadow_summary=shadow_summary,
            universe_policy=universe_policy,
            enabled=self._safe_bool(self.settings.session_impulse_retest_enabled),
            shadow_only=self._safe_bool(self.settings.session_impulse_retest_shadow_only),
            partial_ratio=self._maybe_float(self.settings.session_impulse_retest_partial_activation_ratio) or 0.0,
            core_live_slots=self._maybe_int(self.settings.session_impulse_retest_core_live_slots) or 0,
            secondary_live_enabled=self._safe_bool(self.settings.session_impulse_retest_secondary_live_enabled),
        )
        return micro_main_live_readiness_to_dict(readiness)

    def _session_impulse_retest_allowed_symbols(self) -> set[str]:
        return {
            item.strip().upper()
            for item in str(self.settings.session_impulse_retest_allowed_symbols or "").split(",")
            if item.strip()
        }

    def _session_impulse_retest_symbol_tracked(self, symbol: str | None) -> bool:
        normalized_symbol = str(symbol or "").upper().strip()
        if not normalized_symbol:
            return False
        allowed_symbols = self._session_impulse_retest_allowed_symbols()
        if not allowed_symbols:
            return False
        return normalized_symbol in allowed_symbols

    def _session_impulse_retest_live_routable_symbols(self, requested_mode: ExecutionMode | None) -> set[str]:
        tracked = self._session_impulse_retest_allowed_symbols()
        if requested_mode == ExecutionMode.MICRO_LIVE:
            configured = set(self._csv_items(self.settings.auto_trading_micro_live_allowed_symbols, case="upper"))
        elif requested_mode == ExecutionMode.LIVE:
            configured = set(self._csv_items(self.settings.auto_trading_allowed_symbols, case="upper"))
        else:
            configured = set()
        if not configured:
            return set()
        return tracked & configured

    def _session_impulse_retest_symbol_live_routable(
        self,
        *,
        symbol: str | None,
        requested_mode: ExecutionMode | None,
    ) -> bool:
        normalized_symbol = str(symbol or "").upper().strip()
        if not self._session_impulse_retest_symbol_tracked(normalized_symbol):
            return False
        return normalized_symbol in self._session_impulse_retest_live_routable_symbols(requested_mode)

    def _session_impulse_retest_live_routable_families(self, requested_mode: ExecutionMode | None) -> set[str]:
        if requested_mode == ExecutionMode.MICRO_LIVE:
            return set(
                self._csv_items(getattr(self.settings, "auto_trading_micro_live_allowed_families", ""), case="lower")
            )
        if requested_mode == ExecutionMode.LIVE:
            return set(self._csv_items(self.settings.auto_trading_allowed_families, case="lower"))
        live_allowed = set(self._csv_items(self.settings.auto_trading_allowed_families, case="lower"))
        micro_live_allowed = set(
            self._csv_items(getattr(self.settings, "auto_trading_micro_live_allowed_families", ""), case="lower")
        )
        return live_allowed | micro_live_allowed

    def _session_impulse_retest_live_auto_route_allowed(self) -> tuple[bool, str]:
        if not self._safe_bool(self.settings.session_impulse_retest_enabled):
            return False, "family_disabled"
        if self._safe_bool(self.settings.session_impulse_retest_shadow_only):
            return False, "family_shadow_only"
        return True, "ok"

    def runtime_sync_symbols(self, *, limit_symbols: int = 30) -> list[str]:
        explicit_symbols: list[str] = []
        for raw in (
            self.settings.auto_trading_allowed_symbols,
            getattr(self.settings, "auto_trading_micro_live_allowed_symbols", ""),
            self.settings.session_impulse_retest_allowed_symbols,
        ):
            for item in self._csv_items(raw, case="upper"):
                if item and item not in explicit_symbols:
                    explicit_symbols.append(item)

        top_symbols = list(self.market_data.refresh_universe(limit=limit_symbols))
        merged: list[str] = []
        for symbol in explicit_symbols + top_symbols:
            normalized = str(symbol or "").upper().strip()
            if normalized and normalized not in merged:
                merged.append(normalized)
        return merged

    def _session_impulse_retest_live_exposure_rows(self, exposure_rows: list[Plan]) -> list[Plan]:
        requested_mode = self._auto_route_requested_mode()
        if requested_mode not in {ExecutionMode.MICRO_LIVE, ExecutionMode.LIVE}:
            return []
        live_symbols = set(self._session_impulse_retest_miss_detector_symbols())
        live_families = self._session_impulse_retest_live_routable_families(requested_mode)
        if not live_symbols or not live_families:
            return []

        filtered: list[Plan] = []
        for row in list(exposure_rows or []):
            symbol = str(getattr(row, "symbol", "") or "").upper()
            if live_symbols and symbol not in live_symbols:
                continue
            validity = _safe_dict(getattr(row, "validity", None))
            strategy_family = str(validity.get("strategy_family") or "").strip().lower()
            if live_families and strategy_family not in live_families:
                continue
            strategy_sizing = _safe_dict(validity.get("strategy_sizing"))
            recommended_risk_r = self._maybe_float(
                validity.get("recommended_risk_r")
                or strategy_sizing.get("final_risk_r")
                or 0.0
            ) or 0.0
            if recommended_risk_r <= 0.0:
                continue
            filtered.append(row)
        return filtered

    def _session_impulse_retest_active_thesis_clusters(self, exposure_rows: list[Plan]) -> int:
        filtered_rows = self._session_impulse_retest_live_exposure_rows(exposure_rows)
        return len(self.scanner.overlay.thesis_cluster_summary(filtered_rows))

    def _session_impulse_retest_runtime_plan(
        self,
        *,
        symbol: str,
        candles_1m: list[Any],
        candles_5m: list[Any],
        active_thesis_clusters: int,
    ) -> Plan | None:
        normalized_symbol = str(symbol or "").upper()
        if not self._safe_bool(self.settings.session_impulse_retest_enabled):
            return None
        allowed_symbols = self._session_impulse_retest_allowed_symbols()
        if allowed_symbols and normalized_symbol not in allowed_symbols:
            return None
        if len(candles_1m) < 600 or len(candles_5m) < 200:
            return None

        runtime = SessionImpulseRetestResearch(
            symbol=normalized_symbol,
            candles_1m=candles_1m,
            candles_5m=candles_5m,
            profile_name=session_impulse_retest_profile_for_symbol(normalized_symbol),
        )
        signal = runtime.latest_signal(freshness_minutes=20)
        if signal is None:
            return None

        last_ts = runtime._normalize_ts(candles_1m[-1].ts)
        valid_from = signal.entry_ts
        valid_until = signal.entry_ts + timedelta(minutes=12)
        if valid_until <= last_ts:
            return None

        policy_entry = dict(micro_main_universe_entry(normalized_symbol) or {})
        tier = str(policy_entry.get("tier") or "secondary")
        strategy_grade = "A" if tier == "core" else "B"
        allowed_by_mode, _ = self.plan_generator.strategy_mode.allow_candidate(
            strategy_family="session_impulse_retest",
            strategy_grade=strategy_grade,
        )
        if not allowed_by_mode:
            return None

        benchmark_ev_r = float(policy_entry.get("benchmark_ev_r", 0.30) or 0.30)
        benchmark_win_rate = float(policy_entry.get("benchmark_win_rate", 0.55) or 0.55)
        universe_risk_multiplier = float(policy_entry.get("risk_multiplier", 0.50) or 0.50)
        setup_score = min(95.0, max(72.0, 72.0 + benchmark_ev_r * 18.0 + benchmark_win_rate * 8.0))

        strategy_sizing = self.plan_generator.sizing.evaluate(
            PositionSizingInput(
                strategy_family="session_impulse_retest",
                strategy_grade=strategy_grade,
                regime="trend",
                reaction_classification="acceptance_confirmed",
                confirm_only=True,
                entry_model="CONFIRM",
                active_thesis_clusters=active_thesis_clusters,
                transition_state="none",
                symbol=normalized_symbol,
                direction=signal.direction,
            )
        )
        strategy_sizing = dict(strategy_sizing)
        base_final_risk_r = float(strategy_sizing.get("final_risk_r", 0.0) or 0.0)
        strategy_sizing["pre_universe_final_risk_r"] = round(base_final_risk_r, 4)
        strategy_sizing["universe_risk_multiplier"] = round(universe_risk_multiplier, 4)
        strategy_sizing["benchmark_ev_r"] = round(benchmark_ev_r, 4)
        strategy_sizing["benchmark_win_rate"] = round(benchmark_win_rate, 4)
        strategy_sizing["final_risk_r"] = round(base_final_risk_r * universe_risk_multiplier, 4)
        strategy_sizing = self.plan_generator.strategy_mode.apply_to_sizing(
            strategy_sizing,
            mode=self.plan_generator.strategy_mode.current_mode(),
        )
        post_mode_final_risk_r = float(strategy_sizing.get("final_risk_r", 0.0) or 0.0)
        signal_weekday_utc = signal.entry_ts.astimezone(timezone.utc).weekday()
        saturday_risk_multiplier = 1.0
        if signal_weekday_utc == 5:
            saturday_risk_multiplier = max(
                0.0,
                self._maybe_float(self.settings.session_impulse_retest_saturday_risk_multiplier) or 1.0,
            )
        strategy_sizing["post_mode_final_risk_r"] = round(post_mode_final_risk_r, 4)
        strategy_sizing["session_impulse_retest_weekday_utc"] = int(signal_weekday_utc)
        strategy_sizing["session_impulse_retest_saturday_risk_multiplier"] = round(saturday_risk_multiplier, 4)
        strategy_sizing["final_risk_r"] = round(post_mode_final_risk_r * saturday_risk_multiplier, 4)
        if signal_weekday_utc == 5 and saturday_risk_multiplier < 0.9999:
            strategy_sizing["operational_risk_adjustment_reason"] = "session_impulse_retest_saturday_risk_haircut"
        final_risk_r = float(strategy_sizing.get("final_risk_r", 0.0) or 0.0)
        if final_risk_r <= 0.0:
            return None

        risk_abs = max(abs(signal.entry_price - signal.stop_price), 1e-9)
        direction_sign = 1.0 if signal.direction == "long" else -1.0
        tp1 = float(signal.entry_price + direction_sign * risk_abs)
        tp2 = float(signal.target_price)
        tp3 = float(signal.target_price)
        split = {"tp1": 0.35, "tp2": 0.65, "runner": 0.0}
        cost_est = round(abs(signal.entry_price) * 0.0006 / risk_abs, 4)
        expected_ev_at_size_r = round(benchmark_ev_r * final_risk_r, 4)

        thesis_fingerprint = self.thesis.build(
            symbol=normalized_symbol,
            direction=signal.direction,
            regime="trend",
            strategy_family="session_impulse_retest",
            reaction_classification="acceptance_confirmed",
            zone_type="micro",
            near_lp=False,
            at=signal.entry_ts,
        )
        thesis_cluster_id = self.thesis.thesis_cluster_id(thesis_fingerprint)

        validity = {
            "regime": "trend",
            "entry_reason": "session_impulse_retest_confirm",
            "strategy_family": "session_impulse_retest",
            "strategy_grade": strategy_grade,
            "strategy_family_score": round(setup_score, 2),
            "strategy_family_reason": "session_impulse_retest_runtime_signal",
            "strategy_family_confirm_only": True,
            "strategy_mode": self.plan_generator.strategy_mode.current_mode().value,
            "strategy_sizing": strategy_sizing,
            "recommended_risk_r": final_risk_r,
            "expected_win_prob": round(benchmark_win_rate, 4),
            "expected_ev_r": round(benchmark_ev_r, 4),
            "expected_tp1_prob": round(min(0.95, benchmark_win_rate + 0.12), 4),
            "expected_tp2_prob": round(max(0.05, benchmark_win_rate - 0.10), 4),
            "expected_tp3_prob": round(max(0.0, benchmark_win_rate - 0.18), 4),
            "expected_ev_at_recommended_size_r": expected_ev_at_size_r,
            "expected_summary": (
                f"session_impulse_retest benchmark | win≈{benchmark_win_rate * 100.0:.1f}% "
                f"EV≈{benchmark_ev_r:+.2f}R | tier={tier}"
            ),
            "session_impulse_retest_operational_risk_multiplier": round(saturday_risk_multiplier, 4),
            "reaction_classification": "acceptance_confirmed",
            "transition_state": "none",
            "session_impulse_retest_signal": {
                "profile_name": runtime.profile_name,
                "signal_ts": signal.signal_ts.isoformat(),
                "setup_ts": signal.setup_ts.isoformat(),
                "entry_ts": signal.entry_ts.isoformat(),
                "direction": signal.direction,
                "entry_price": round(float(signal.entry_price), 8),
                "stop_price": round(float(signal.stop_price), 8),
                "target_price": round(float(signal.target_price), 8),
                "max_hold_minutes": int(signal.max_hold_minutes),
                "regime_hint": signal.regime_hint,
            },
            "strategy_family_time_stop_max_bars": max(int(signal.max_hold_minutes // 5), 1),
            "thesis_fingerprint": thesis_fingerprint,
            "thesis_cluster_id": thesis_cluster_id,
            "thesis_primary_symbol": normalized_symbol,
        }

        stamp = signal.entry_ts.astimezone(timezone.utc).strftime("%Y%m%dT%H%M")
        direction_code = "L" if signal.direction == "long" else "S"
        plan_id = f"sir_{normalized_symbol}_{direction_code}_{stamp}"[:50]
        zone_id = f"micro:sir:{normalized_symbol}:{stamp}"[:50]
        return Plan(
            plan_id=plan_id,
            zone_id=zone_id,
            symbol=normalized_symbol,
            timeframe="5m",
            direction=signal.direction,
            entry_model="CONFIRM",
            entry_price=float(signal.entry_price),
            entry_condition="session_impulse_retest_confirm",
            sl=float(signal.stop_price),
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            split=split,
            rr_min=1.0,
            rr_base=2.0,
            rr_opt=2.0,
            ev=round(benchmark_ev_r, 4),
            cost_est=cost_est,
            confidence=round(min(max(setup_score / 100.0, 0.0), 1.0), 4),
            validity=validity,
            state=PlanState.ARMED.value,
            valid_from=valid_from,
            valid_until=valid_until,
            strategy_version=str(self.settings.strategy_version),
        )

    def _active_contract_promotion_shadow_counter(
        self,
        *,
        symbol: str,
        days: int,
        filters: dict[str, Any],
    ) -> dict[str, Any] | None:
        cadence_window_days = max(int(days or 1), 1)
        recent_plans = list(self.plan_repo.list_recent(symbol=symbol, timeframe="5m", days=cadence_window_days))
        entry_models = {
            str(item or "").strip().upper()
            for item in list(filters.get("entry_models") or [])
            if str(item or "").strip()
        }
        if not recent_plans:
            return {
                "available": True,
                "comparison_window_days": cadence_window_days,
                "comparison_note": "Window-level shadow comparison only; not a one-to-one replay/runtime candidate match.",
                "runtime_recent_symbol_plans_same_window": 0,
                "runtime_recent_entry_model_plans_same_window": 0,
                "runtime_promoted_contract_plans_same_window": 0,
                "runtime_rejected_same_entry_model_plans_same_window": 0,
                "runtime_rejected_reason_counts": {},
                "runtime_rejected_reaction_counts": {},
                "runtime_rejected_family_counts": {},
                "runtime_promoted_state_counts": {},
                "runtime_rejected_state_counts": {},
                "replay_contract_hits_same_window": 0,
                "promotion_gap_count": 0,
                "runtime_vs_replay_promotion_ratio": None,
                "dominant_rejected_reason": None,
                "shadow_mismatch_state": "no_recent_symbol_plans",
            }

        runtime_recent_symbol_plans_same_window = len(recent_plans)
        runtime_recent_entry_model_plans_same_window = 0
        runtime_promoted_contract_plans_same_window = 0
        runtime_rejected_same_entry_model_plans_same_window = 0
        runtime_rejected_reason_counts: dict[str, int] = {}
        runtime_rejected_reaction_counts: dict[str, int] = {}
        runtime_rejected_family_counts: dict[str, int] = {}
        runtime_promoted_state_counts: dict[str, int] = {}
        runtime_rejected_state_counts: dict[str, int] = {}

        for row in recent_plans:
            payload = {
                "symbol": getattr(row, "symbol", symbol),
                "direction": getattr(row, "direction", ""),
                "entry_model": getattr(row, "entry_model", ""),
                "validity": _safe_dict(getattr(row, "validity", None)),
            }
            entry_model = self._row_entry_model(payload)
            if entry_models and entry_model not in entry_models:
                continue

            runtime_recent_entry_model_plans_same_window += 1
            if self._row_matches_contract_filters(payload, filters):
                runtime_promoted_contract_plans_same_window += 1
                state = str(getattr(row, "state", "") or "unknown")
                runtime_promoted_state_counts[state] = runtime_promoted_state_counts.get(state, 0) + 1
                continue

            runtime_rejected_same_entry_model_plans_same_window += 1
            validity = _safe_dict(getattr(row, "validity", None))
            reason = str(validity.get("strategy_family_reason") or "unknown")
            reaction = str(validity.get("reaction_classification") or "unknown")
            family = str(validity.get("strategy_family") or "unknown")
            state = str(getattr(row, "state", "") or "unknown")
            runtime_rejected_reason_counts[reason] = runtime_rejected_reason_counts.get(reason, 0) + 1
            runtime_rejected_reaction_counts[reaction] = runtime_rejected_reaction_counts.get(reaction, 0) + 1
            runtime_rejected_family_counts[family] = runtime_rejected_family_counts.get(family, 0) + 1
            runtime_rejected_state_counts[state] = runtime_rejected_state_counts.get(state, 0) + 1

        replay_contract_hits_same_window = self._active_contract_replay_hits_same_window(
            filters=filters,
            days=cadence_window_days,
        )
        promotion_gap_count = max(replay_contract_hits_same_window - runtime_promoted_contract_plans_same_window, 0)
        runtime_vs_replay_promotion_ratio = (
            round(runtime_promoted_contract_plans_same_window / replay_contract_hits_same_window, 4)
            if replay_contract_hits_same_window > 0
            else None
        )
        dominant_rejected_reason = None
        if runtime_rejected_reason_counts:
            dominant_rejected_reason = max(
                runtime_rejected_reason_counts.items(),
                key=lambda item: (item[1], item[0]),
            )[0]
        if runtime_recent_entry_model_plans_same_window == 0:
            shadow_mismatch_state = "no_recent_entry_model_plans"
        elif runtime_promoted_contract_plans_same_window == 0 and runtime_rejected_same_entry_model_plans_same_window > 0:
            shadow_mismatch_state = "runtime_entry_model_seen_but_not_promoted"
        elif replay_contract_hits_same_window > runtime_promoted_contract_plans_same_window:
            shadow_mismatch_state = "runtime_below_replay_baseline"
        else:
            shadow_mismatch_state = "runtime_aligned_or_insufficient_replay_gap"

        return {
            "available": True,
            "comparison_window_days": cadence_window_days,
            "comparison_note": "Window-level shadow comparison only; not a one-to-one replay/runtime candidate match.",
            "runtime_recent_symbol_plans_same_window": runtime_recent_symbol_plans_same_window,
            "runtime_recent_entry_model_plans_same_window": runtime_recent_entry_model_plans_same_window,
            "runtime_promoted_contract_plans_same_window": runtime_promoted_contract_plans_same_window,
            "runtime_rejected_same_entry_model_plans_same_window": runtime_rejected_same_entry_model_plans_same_window,
            "runtime_rejected_reason_counts": runtime_rejected_reason_counts,
            "runtime_rejected_reaction_counts": runtime_rejected_reaction_counts,
            "runtime_rejected_family_counts": runtime_rejected_family_counts,
            "runtime_promoted_state_counts": runtime_promoted_state_counts,
            "runtime_rejected_state_counts": runtime_rejected_state_counts,
            "replay_contract_hits_same_window": replay_contract_hits_same_window,
            "promotion_gap_count": promotion_gap_count,
            "runtime_vs_replay_promotion_ratio": runtime_vs_replay_promotion_ratio,
            "dominant_rejected_reason": dominant_rejected_reason,
            "shadow_mismatch_state": shadow_mismatch_state,
        }

    @staticmethod
    def _active_contract_shadow_relaxation_priority(
        promotion_shadow_counter: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        payload = dict(promotion_shadow_counter or {})
        if not payload:
            return None

        comparison_window_days = int(payload.get("comparison_window_days", 0) or 0)
        mismatch_state = str(payload.get("shadow_mismatch_state") or "")
        promoted = int(payload.get("runtime_promoted_contract_plans_same_window", 0) or 0)
        replay_hits = int(payload.get("replay_contract_hits_same_window", 0) or 0)
        rejected = int(payload.get("runtime_rejected_same_entry_model_plans_same_window", 0) or 0)
        reaction_counts = dict(payload.get("runtime_rejected_reaction_counts") or {})
        not_applicable = int(reaction_counts.get("not_applicable", 0) or 0)
        ratio = payload.get("runtime_vs_replay_promotion_ratio")
        try:
            ratio_value = float(ratio) if ratio is not None else None
        except (TypeError, ValueError):
            ratio_value = None

        base = {
            "available": True,
            "apply_live": False,
            "comparison_window_days": comparison_window_days,
            "runtime_promoted_contract_plans_same_window": promoted,
            "runtime_rejected_same_entry_model_plans_same_window": rejected,
            "runtime_rejected_not_applicable_count": not_applicable,
            "replay_contract_hits_same_window": replay_hits,
            "runtime_vs_replay_promotion_ratio": ratio_value,
            "runner_up_shadow_lanes": [],
        }

        if mismatch_state in {"no_recent_symbol_plans", "no_recent_entry_model_plans"}:
            return {
                **base,
                "status": "insufficient_signal",
                "recommended_shadow_lane": None,
                "rationale_code": mismatch_state,
                "operator_headline": "No current shadow relaxation priority because the active entry-model lane has no recent runtime sample.",
            }

        if (
            mismatch_state in {"runtime_entry_model_seen_but_not_promoted", "runtime_below_replay_baseline"}
            and rejected > 0
            and not_applicable > 0
        ):
            return {
                **base,
                "status": "priority_candidate",
                "recommended_shadow_lane": "proof_reclaim_plus_one_bar",
                "runner_up_shadow_lanes": ["proof_reclaim_only", "one_bar_only"],
                "rationale_code": "reaction_not_applicable_promotion_gap",
                "operator_headline": (
                    "Proof reclaim plus one-bar is the current shadow priority because recent runtime LIMIT plans are being rejected as "
                    "`reaction not applicable` while replay still shows contract-faithful hits, and the combined rescue lane has outperformed the strict baseline in future-blind variant sweeps. Keep this compare-only; do not apply live."
                ),
            }

        return {
            **base,
            "status": "monitor_only",
            "recommended_shadow_lane": None,
            "rationale_code": "no_clear_relaxation_priority",
            "operator_headline": "No single relaxation lane has enough evidence to outrank strict runtime behavior yet.",
        }

    def _active_contract_replay_hits_same_window(
        self,
        *,
        filters: dict[str, Any],
        days: int,
    ) -> int:
        cache_path = (
            Path(self.settings.validation_report_dir)
            / "historical_walk_forward_cache"
            / _ACTIVE_CONTRACT_REPLAY_BASELINE_FILE
        )
        if not cache_path.exists():
            return 0
        try:
            payload = json.loads(cache_path.read_text())
        except Exception:
            return 0

        rows = list(payload.get("trade_rows") or [])
        if not rows:
            return 0
        try:
            latest_generated_ts = max(
                datetime.fromisoformat(str(row.get("generated_ts") or "").replace("Z", "+00:00"))
                for row in rows
                if str(row.get("generated_ts") or "").strip()
            )
        except ValueError:
            return 0

        if latest_generated_ts.tzinfo is None:
            latest_generated_ts = latest_generated_ts.replace(tzinfo=timezone.utc)
        start = latest_generated_ts - timedelta(days=max(int(days or 1), 1))

        filter_symbol = str(filters.get("symbol") or "").strip().upper()
        strategy_families = {
            str(item or "").strip().lower()
            for item in list(filters.get("strategy_families") or [])
            if str(item or "").strip()
        }
        entry_models = {
            str(item or "").strip().upper()
            for item in list(filters.get("entry_models") or [])
            if str(item or "").strip()
        }
        directions = {
            str(item or "").strip().upper()
            for item in list(filters.get("directions") or [])
            if str(item or "").strip()
        }

        hits = 0
        for row in rows:
            generated_ts_raw = str(row.get("generated_ts") or "").strip()
            if not generated_ts_raw:
                continue
            try:
                generated_ts = datetime.fromisoformat(generated_ts_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if generated_ts.tzinfo is None:
                generated_ts = generated_ts.replace(tzinfo=timezone.utc)
            if generated_ts < start:
                continue
            symbol_value = str(row.get("symbol") or "").strip().upper()
            family_value = str(row.get("strategy_family") or "").strip().lower()
            entry_model_value = str(row.get("entry_model") or "").strip().upper()
            direction_value = str(row.get("direction") or "").strip().upper()
            if filter_symbol and symbol_value != filter_symbol:
                continue
            if strategy_families and family_value not in strategy_families:
                continue
            if entry_models and entry_model_value not in entry_models:
                continue
            if directions and direction_value not in directions:
                continue
            hits += 1
        return hits

    @staticmethod
    def _row_strategy_family(row: dict[str, Any]) -> str:
        payload = dict(row or {})
        validity = dict(payload.get("validity") or {})
        return str(payload.get("strategy_family") or validity.get("strategy_family") or "").lower()

    @staticmethod
    def _row_entry_model(row: dict[str, Any]) -> str:
        payload = dict(row or {})
        validity = dict(payload.get("validity") or {})
        return str(payload.get("entry_model") or validity.get("entry_model") or "").upper()

    @staticmethod
    def _row_direction(row: dict[str, Any]) -> str:
        payload = dict(row or {})
        validity = dict(payload.get("validity") or {})
        return str(payload.get("direction") or validity.get("direction") or "").upper()

    @classmethod
    def _row_matches_contract_filters(cls, row: dict[str, Any], filters: dict[str, Any]) -> bool:
        symbol_filter = str(filters.get("symbol") or "").upper()
        strategy_families = {str(item or "").strip().lower() for item in list(filters.get("strategy_families") or [])}
        entry_models = {str(item or "").strip().upper() for item in list(filters.get("entry_models") or [])}
        directions = {str(item or "").strip().upper() for item in list(filters.get("directions") or [])}
        row_symbol = str(dict(row or {}).get("symbol") or "").upper()
        if symbol_filter and row_symbol and row_symbol != symbol_filter:
            return False
        if strategy_families and cls._row_strategy_family(row) not in strategy_families:
            return False
        if entry_models and cls._row_entry_model(row) not in entry_models:
            return False
        if directions and cls._row_direction(row) not in directions:
            return False
        return True

    @classmethod
    def _filtered_portfolio_summary(
        cls,
        *,
        portfolio_summary: dict[str, Any] | None,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        payload = dict(portfolio_summary or {})
        accepted_candidates = [
            dict(row)
            for row in list(payload.get("accepted_candidates") or [])
            if cls._row_matches_contract_filters(dict(row), filters)
        ]
        blocked_candidates = [
            dict(row)
            for row in list(payload.get("blocked_candidates") or [])
            if cls._row_matches_contract_filters(dict(row), filters)
        ]
        blocked_reason_counts: dict[str, int] = {}
        for row in blocked_candidates:
            reason = str(
                row.get("block_reason")
                or row.get("blocking_reason_code")
                or row.get("reason_code")
                or ""
            ).strip()
            if not reason:
                continue
            blocked_reason_counts[reason] = blocked_reason_counts.get(reason, 0) + 1
        blocked_gate_group_counts = cls._gate_group_counts_from_reasons(blocked_reason_counts)

        payload["accepted_candidates"] = accepted_candidates
        payload["blocked_candidates"] = blocked_candidates
        payload["blocked_reason_counts"] = blocked_reason_counts
        payload["blocked_gate_group_counts"] = blocked_gate_group_counts
        return payload

    @staticmethod
    def _contract_selection_shortfall_breakdown(
        *,
        filtered_portfolio_summary: dict[str, Any],
    ) -> dict[str, Any]:
        accepted_candidates = [dict(row) for row in list(filtered_portfolio_summary.get("accepted_candidates") or [])]
        blocked_candidates = [dict(row) for row in list(filtered_portfolio_summary.get("blocked_candidates") or [])]
        return {
            "runtime_candidates": len(accepted_candidates) + len(blocked_candidates),
            "accepted_candidates": len(accepted_candidates),
            "blocked_candidates": len(blocked_candidates),
            "blocked_reason_counts": dict(filtered_portfolio_summary.get("blocked_reason_counts") or {}),
            "blocked_gate_group_counts": dict(filtered_portfolio_summary.get("blocked_gate_group_counts") or {}),
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
                "lock_required": self._safe_bool(getattr(row, "lock_required", False)),
                "created_at": getattr(row, "created_at", None),
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
                "expected_fee_bps": self._maybe_float(self.settings.taker_fee_bps) or 0.0,
                "max_slippage_bps": self._maybe_float(self.settings.auto_trading_max_slippage_bps) or 0.0,
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
        limit: int | None = None,
    ) -> list[str]:
        rows = self.scanner.candidate_rows(
            symbols=symbols,
            risk_state=risk_state,
            plans_per_symbol=1,
        )
        if limit is None:
            return sorted({str(row.get("symbol") or "").upper() for row in rows if row.get("symbol")})
        if int(limit) <= 0:
            return []
        selected: list[str] = []
        seen: set[str] = set()
        for row in rows:
            symbol = str(row.get("symbol") or "").upper()
            if not symbol or symbol in seen:
                continue
            selected.append(symbol)
            seen.add(symbol)
            if len(selected) >= max(1, int(limit)):
                break
        return selected

    def _approval_outcome_inputs(
        self,
        *,
        symbol: str,
        candidate_rows: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        portfolio_budget = {
            "accepted_candidates": [dict(row) for row in candidate_rows if self._safe_bool(row.get("accepted"))],
            "blocked_candidates": [dict(row) for row in candidate_rows if not self._safe_bool(row.get("accepted"))],
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
        family = str(_safe_dict(getattr(plan, "validity", None)).get("strategy_family") or "legacy_zone_plan").lower()
        operating_lock = dict((candidate_row or {}).get("operating_lock") or {})
        session_name = ExecutionPlanningService._session_name(candidate_row or {}, operating_lock)
        exposure_rows = self._current_exposure_rows()
        executable_plan = self.execution_planning.build_executable_plan(
            plan=plan,
            context=context,
            candidate_row=candidate_row,
            execution_mode=requested_mode,
        )
        adjusted_candidate_row = self._candidate_row_with_live_tranche_override(
            plan=plan,
            executable_plan=executable_plan,
            candidate_row=candidate_row,
            exposure_rows=exposure_rows,
        )
        if adjusted_candidate_row is not candidate_row:
            candidate_row = adjusted_candidate_row
            candidate_rows = self._replace_candidate_row(
                candidate_rows=candidate_rows,
                candidate_row=candidate_row,
            )
            executable_plan = self.execution_planning.build_executable_plan(
                plan=plan,
                context=context,
                candidate_row=candidate_row,
                execution_mode=requested_mode,
            )
        outcome_inputs = self._approval_outcome_inputs(symbol=plan.symbol, candidate_rows=candidate_rows)
        live_cluster_guard = self._live_cluster_guard(
            plan=plan,
            executable_plan=executable_plan,
            requested_mode=requested_mode,
            exposure_rows=exposure_rows,
        )
        micro_live_symbol_priority_guard = self._micro_live_symbol_priority_guard(
            plan=plan,
            executable_plan=executable_plan,
            requested_mode=requested_mode,
        )
        metrics = self.metrics(symbol=plan.symbol, version=self.settings.strategy_version)
        metrics = self.replay_validation_bridge.apply_to_metrics(
            metrics,
            symbol=plan.symbol,
            family=family,
            requested_mode=requested_mode.value,
            entry_model=str(executable_plan.get("entry_model") or getattr(plan, "entry_model", "") or ""),
        )
        safety_state = self.safety_locks.safety_state(
            symbol=plan.symbol,
            family=family,
            session_name=session_name,
        )
        if family == "session_impulse_retest":
            safety_state = dict(safety_state or {})
            safety_state["session_impulse_retest_rollout_readiness"] = self._session_impulse_retest_rollout_readiness(
                symbol=plan.symbol,
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
            live_cluster_guard=live_cluster_guard,
            micro_live_symbol_priority_guard=micro_live_symbol_priority_guard,
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
            "micro_live_symbol_priority_guard": micro_live_symbol_priority_guard,
            "approval": approval,
        }

    def _execution_approval_bundle_for_routing(
        self,
        plan_id: str,
        requested_execution_mode: ExecutionMode | str | None,
        *,
        paper_lineage_override: bool = False,
    ) -> dict[str, Any]:
        return self._execution_approval_bundle(
            plan_id,
            requested_execution_mode,
            strict_requested_mode=False,
            paper_lineage_override=paper_lineage_override,
        )

    def execution_plan_preview(self, *, plan_id: str, paper_lineage_override: bool = False) -> dict[str, Any]:
        bundle = self._execution_approval_bundle(
            plan_id,
            None,
            strict_requested_mode=False,
            paper_lineage_override=paper_lineage_override,
        )
        return bundle["executable_plan"]

    @staticmethod
    def _order_intent_to_dict(row) -> dict[str, Any]:
        approval = _safe_dict(row.approval_snapshot)
        payload = _safe_dict(row.payload)
        intent_snapshot = _safe_dict(payload.get("intent_snapshot"))
        self_heal_summary = _safe_dict(payload.get("self_heal_summary") or intent_snapshot.get("self_heal_summary"))
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
            "requested_execution_mode": str(payload.get("requested_execution_mode") or row.execution_mode or ""),
            "paper_lineage_override_requested": StrategyEngine._safe_bool(
                payload.get("paper_lineage_override_requested", False)
            ),
            "allowed_execution_mode": approval.get("allowed_execution_mode", ""),
            "deployment_go_no_go": approval.get("deployment_go_no_go", ""),
            "deployment_code": approval.get("deployment_code", ""),
            "playbook_go_no_go": approval.get("playbook_go_no_go", ""),
            "playbook_code": approval.get("playbook_code", ""),
            "playbook_action": approval.get("playbook_action", ""),
            "playbook_message": approval.get("playbook_message", ""),
            "paper_lineage_override_applied": StrategyEngine._safe_bool(
                approval.get("paper_lineage_override_applied")
            ),
            "paper_lineage_override_reason": approval.get("paper_lineage_override_reason", ""),
            "paper_lineage_override_source": approval.get("paper_lineage_override_source", ""),
            "self_heal_summary": self_heal_summary,
            "source_of_truth_hint": "execution_approval_snapshot",
            "thesis_fingerprint": _safe_dict(row.thesis_fingerprint),
            "dedupe_result": _safe_dict(row.dedupe_result),
            "session_guidance": _safe_dict(row.session_guidance),
            "quality_snapshot": _safe_dict(row.quality_snapshot),
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
            "requested_live": StrategyEngine._safe_bool(row.requested_live),
            "attachments": _safe_dict(row.attachments),
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

    def _auto_route_requested_mode(self) -> ExecutionMode | None:
        if not self._safe_bool(self.settings.auto_trading_enabled):
            return None
        requested_mode = ExecutionPlanningService.coerce_execution_mode(
            getattr(self.settings, "auto_trading_execution_mode", None),
            default=self.execution_planning.active_execution_mode(),
        )
        if requested_mode == ExecutionMode.SHADOW:
            return None
        return requested_mode

    def _auto_route_recent_intent_cooldown(
        self,
        *,
        plan_id: str,
        requested_mode: ExecutionMode,
        now: datetime,
    ) -> dict[str, Any] | None:
        latest_intent = self.intent_repo.latest_for_plan(plan_id)
        if latest_intent is None:
            return None
        cooldown_seconds = max(0, self._maybe_int(self.settings.auto_trading_intent_recheck_cooldown_seconds) or 0)
        if cooldown_seconds <= 0:
            return None
        payload = _safe_dict(getattr(latest_intent, "payload", None))
        latest_requested_mode = str(payload.get("requested_execution_mode") or getattr(latest_intent, "execution_mode", "") or "")
        if latest_requested_mode != requested_mode.value:
            return None
        created_at_raw = getattr(latest_intent, "created_at", None)
        if not isinstance(created_at_raw, datetime):
            return None
        created_at = self._to_utc(created_at_raw)
        if created_at < now - timedelta(seconds=cooldown_seconds):
            return None
        return {
            "intent_id": str(getattr(latest_intent, "intent_id", "") or ""),
            "created_at": created_at.isoformat(),
            "submit_decision": str(getattr(latest_intent, "submit_decision", "") or ""),
            "approval_state": str(getattr(latest_intent, "approval_state", "") or ""),
            "decision_reason_code": str(getattr(latest_intent, "decision_reason_code", "") or ""),
            "cooldown_seconds": cooldown_seconds,
            "requested_mode": requested_mode.value,
        }

    def _session_impulse_retest_runtime_audit_json_safe(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, datetime):
            return self._to_utc(value).isoformat()
        if isinstance(value, dict):
            return {
                str(key): self._session_impulse_retest_runtime_audit_json_safe(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [self._session_impulse_retest_runtime_audit_json_safe(item) for item in value]
        return str(value)

    def _record_session_impulse_retest_runtime_audit(
        self,
        *,
        symbol: str,
        phase: str,
        status: str,
        plan_id: str | None = None,
        decision_code: str | None = None,
        observed_ts: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        from app.db.models import SessionImpulseRetestRuntimeAudit

        normalized_symbol = str(symbol or "").upper().strip()
        if not self._session_impulse_retest_symbol_tracked(normalized_symbol):
            return

        normalized_observed_ts = self._to_utc(observed_ts or datetime.now(timezone.utc))
        row = SessionImpulseRetestRuntimeAudit(
            audit_id=self._alert_id(prefix="sir_audit", symbol=normalized_symbol),
            symbol=normalized_symbol,
            phase=str(phase or "").lower(),
            status=str(status or "").lower(),
            plan_id=str(plan_id or "").strip() or None,
            decision_code=str(decision_code or "").strip() or None,
            payload=self._session_impulse_retest_runtime_audit_json_safe(_safe_dict(payload)),
            observed_ts=normalized_observed_ts,
        )
        self.session_impulse_retest_runtime_audit_repo.add(row)

    def _commit_session_impulse_retest_runtime_audit(
        self,
        *,
        symbol: str,
        phase: str,
        status: str,
        plan_id: str | None = None,
        decision_code: str | None = None,
        observed_ts: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str | None:
        try:
            self._record_session_impulse_retest_runtime_audit(
                symbol=symbol,
                phase=phase,
                status=status,
                plan_id=plan_id,
                decision_code=decision_code,
                observed_ts=observed_ts,
                payload=payload,
            )
            self.db.commit()
            return None
        except Exception as exc:
            self.db.rollback()
            return f"{exc.__class__.__name__}:{exc}"

    def _finalize_session_impulse_retest_auto_route_audit(
        self,
        *,
        symbol: str,
        response: dict[str, Any],
        observed_ts: datetime,
    ) -> dict[str, Any]:
        first_result = next(iter(response.get("results") or []), {}) if isinstance(response, dict) else {}
        plan_id = str(first_result.get("plan_id") or response.get("plan_id") or "").strip() or None
        decision_code = None
        intent_payload = first_result.get("intent") or {}
        if isinstance(intent_payload, dict):
            decision_code = str(intent_payload.get("decision_reason_code") or "").strip() or None
        audit_error = self._commit_session_impulse_retest_runtime_audit(
            symbol=symbol,
            phase="auto_route",
            status=str(response.get("reason") or first_result.get("status") or "unknown"),
            plan_id=plan_id,
            decision_code=decision_code,
            observed_ts=observed_ts,
            payload=response,
        )
        if audit_error:
            response["runtime_audit_error"] = audit_error
        return response

    def session_impulse_retest_runtime_audits_recent(
        self,
        *,
        hours: int = 24,
        symbol: str | None = None,
        phase: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        rows = self.session_impulse_retest_runtime_audit_repo.list_recent(
            hours=hours,
            symbol=symbol,
            phase=phase,
            status=status,
            limit=limit,
        )
        return [
            {
                "audit_id": str(getattr(row, "audit_id", "") or ""),
                "symbol": str(getattr(row, "symbol", "") or ""),
                "phase": str(getattr(row, "phase", "") or ""),
                "status": str(getattr(row, "status", "") or ""),
                "plan_id": str(getattr(row, "plan_id", "") or ""),
                "decision_code": str(getattr(row, "decision_code", "") or ""),
                "observed_ts": (
                    observed_ts.isoformat()
                    if (observed_ts := self._maybe_utc(getattr(row, "observed_ts", None))) is not None
                    else ""
                ),
                "payload": self._session_impulse_retest_runtime_audit_json_safe(
                    _safe_dict(getattr(row, "payload", None))
                ),
            }
            for row in rows
        ]

    def _auto_route_live_routable_symbols(self, requested_mode: ExecutionMode | None) -> set[str]:
        if requested_mode == ExecutionMode.MICRO_LIVE:
            return set(self._csv_items(self.settings.auto_trading_micro_live_allowed_symbols, case="upper"))
        if requested_mode == ExecutionMode.LIVE:
            return set(self._csv_items(self.settings.auto_trading_allowed_symbols, case="upper"))
        return set()

    def _auto_route_live_routable_families(self, requested_mode: ExecutionMode | None) -> set[str]:
        if requested_mode == ExecutionMode.MICRO_LIVE:
            return set(
                self._csv_items(getattr(self.settings, "auto_trading_micro_live_allowed_families", ""), case="lower")
            )
        if requested_mode == ExecutionMode.LIVE:
            return set(self._csv_items(self.settings.auto_trading_allowed_families, case="lower"))
        return set()

    def _auto_route_live_entry_models(self, requested_mode: ExecutionMode | None) -> set[str]:
        if requested_mode in {ExecutionMode.MICRO_LIVE, ExecutionMode.LIVE}:
            return set(
                self._csv_items(getattr(self.settings, "auto_trading_micro_live_allowed_entry_models", ""), case="upper")
            )
        return set()

    @staticmethod
    def _plan_strategy_family(plan: Plan) -> str:
        return str(_safe_dict(getattr(plan, "validity", None)).get("strategy_family") or "legacy_zone_plan").lower()

    def _auto_route_live_families_considered(self, requested_mode: ExecutionMode | None) -> list[str]:
        return sorted(self._auto_route_live_routable_families(requested_mode))

    def _plan_live_auto_route_rejection(
        self,
        *,
        symbol: str,
        plan: Plan,
        requested_mode: ExecutionMode,
        now: datetime,
    ) -> str | None:
        normalized_symbol = str(symbol or "").upper().strip()
        if str(getattr(plan, "symbol", "") or "").upper().strip() != normalized_symbol:
            return "symbol_mismatch"
        if str(getattr(plan, "state", "") or "") not in {PlanState.PLANNED.value, PlanState.ARMED.value}:
            return "stale_plan_state"
        valid_until = getattr(plan, "valid_until", None)
        if not isinstance(valid_until, datetime) or self._to_utc(valid_until) <= now:
            return "stale_plan_expired"

        routable_symbols = self._auto_route_live_routable_symbols(requested_mode)
        if not routable_symbols or normalized_symbol not in routable_symbols:
            return "symbol_not_live_enabled_for_auto_route"

        family = self._plan_strategy_family(plan)
        routable_families = self._auto_route_live_routable_families(requested_mode)
        if not routable_families or family not in routable_families:
            return "family_not_live_enabled_for_auto_route"

        if family == _AUTO_ROUTE_SESSION_IMPULSE_RETEST_FAMILY:
            if not self._session_impulse_retest_symbol_tracked(normalized_symbol):
                return "symbol_not_enabled_for_session_impulse_retest"
            live_auto_route_allowed, live_auto_route_reason = self._session_impulse_retest_live_auto_route_allowed()
            if not live_auto_route_allowed:
                return live_auto_route_reason

        allowed_entry_models = self._auto_route_live_entry_models(requested_mode)
        entry_model = str(getattr(plan, "entry_model", "") or "").upper().strip()
        if allowed_entry_models and entry_model not in allowed_entry_models:
            return "entry_model_not_live_enabled_for_auto_route"

        return None

    def _auto_route_live_candidate_plans(
        self,
        *,
        symbol: str,
        requested_mode: ExecutionMode,
        plan_ids: list[str] | None,
        now: datetime,
    ) -> tuple[list[Plan], dict[str, int], list[str]]:
        normalized_symbol = str(symbol or "").upper().strip()
        normalized_plan_ids = [str(plan_id or "").strip() for plan_id in list(plan_ids or []) if str(plan_id or "").strip()]
        candidates: list[Plan] = []
        rejected_counts: dict[str, int] = {}
        inspected_plan_ids: set[str] = set()
        max_candidates = self._max_candidate_plans_per_symbol()

        def _record_rejection(reason: str) -> None:
            rejected_counts[reason] = int(rejected_counts.get(reason, 0) or 0) + 1

        def _consider(plan: Plan | None) -> None:
            if plan is None:
                _record_rejection("plan_not_found")
                return
            plan_id = str(getattr(plan, "plan_id", "") or "")
            if plan_id in inspected_plan_ids:
                return
            inspected_plan_ids.add(plan_id)
            rejection = self._plan_live_auto_route_rejection(
                symbol=normalized_symbol,
                plan=plan,
                requested_mode=requested_mode,
                now=now,
            )
            if rejection is not None:
                _record_rejection(rejection)
                return
            candidates.append(plan)

        for plan_id in normalized_plan_ids:
            _consider(self.plan_repo.get(plan_id))

        active_plans = self.plan_repo.list_active_for_symbol(
            symbol=normalized_symbol,
            timeframe="5m",
            states=[PlanState.PLANNED.value, PlanState.ARMED.value],
            limit=max(20, max_candidates * 4),
        )
        for plan in active_plans:
            if len(candidates) >= max_candidates:
                break
            _consider(plan)

        return candidates[:max_candidates], rejected_counts, normalized_plan_ids

    def _auto_route_no_candidate_reason(
        self,
        *,
        plan_ids: list[str],
        rejected_counts: dict[str, int],
    ) -> str:
        for reason in (
            "family_disabled",
            "family_shadow_only",
            "symbol_not_live_enabled_for_auto_route",
            "symbol_not_enabled_for_session_impulse_retest",
        ):
            if int(rejected_counts.get(reason, 0) or 0) > 0:
                return reason
        if plan_ids:
            return "no_matching_live_route_plan_ids"
        return "no_live_route_candidate_plan"

    def _auto_route_attempt_live_plan(
        self,
        *,
        symbol: str,
        plan: Plan,
        requested_mode: ExecutionMode,
        now: datetime,
    ) -> tuple[dict[str, Any], int, int]:
        result_item: dict[str, Any] = {
            "plan_id": str(plan.plan_id),
            "strategy_family": self._plan_strategy_family(plan),
            "entry_model": str(getattr(plan, "entry_model", "") or ""),
            "status": "intent_attempted",
        }
        recent_intent = self._auto_route_recent_intent_cooldown(
            plan_id=str(plan.plan_id),
            requested_mode=requested_mode,
            now=now,
        )
        if recent_intent is not None:
            result_item["status"] = "skipped_recent_intent"
            result_item["recent_intent"] = recent_intent
            return result_item, 0, 0

        try:
            intent = self.create_order_intent(
                plan_id=str(plan.plan_id),
                execution_mode=requested_mode,
            )
        except Exception as exc:
            self.db.rollback()
            result_item["status"] = "intent_error"
            result_item["error"] = str(exc)
            return result_item, 0, 0

        result_item["intent"] = {
            "intent_id": str(intent.get("intent_id") or ""),
            "approval_state": str(intent.get("approval_state") or ""),
            "submit_decision": str(intent.get("submit_decision") or ""),
            "decision_reason_code": str(intent.get("decision_reason_code") or ""),
            "decision_reason_message": str(intent.get("decision_reason_message") or ""),
        }
        intents_created = 1
        submit_calls = 0

        if str(intent.get("submit_decision") or "") == SubmitDecision.SUBMIT.value:
            live_requested = requested_mode in {ExecutionMode.MICRO_LIVE, ExecutionMode.LIVE}
            try:
                submission = self.submit_order_intent(
                    intent_id=str(intent.get("intent_id") or ""),
                    live=live_requested,
                )
                result_item["status"] = "submitted"
                result_item["submission"] = {
                    "submission_id": str(submission.get("submission_id") or ""),
                    "submit_status": str(submission.get("submit_status") or ""),
                    "state": str(submission.get("state") or ""),
                    "adapter": str(submission.get("adapter") or ""),
                    "requested_live": self._safe_bool(submission.get("requested_live")),
                }
                submit_calls = 1
            except Exception as exc:
                self.db.rollback()
                result_item["status"] = "submit_error"
                result_item["error"] = str(exc)
        else:
            result_item["status"] = "intent_blocked"

        return result_item, intents_created, submit_calls

    @staticmethod
    def _auto_route_reason_from_results(results: list[dict[str, Any]]) -> str:
        statuses = [str(result.get("status") or "") for result in results]
        if "submitted" in statuses:
            return "submitted"
        if "submit_error" in statuses:
            return "submit_error"
        if "intent_error" in statuses:
            return "intent_creation_failed"
        if "intent_blocked" in statuses:
            return "intent_blocked"
        if statuses and all(status == "skipped_recent_intent" for status in statuses):
            return "recent_intent_cooldown_active"
        return "no_live_route_candidate_plan"

    def _finalize_auto_route_audit(
        self,
        *,
        symbol: str,
        response: dict[str, Any],
        observed_ts: datetime,
    ) -> dict[str, Any]:
        if self._session_impulse_retest_symbol_tracked(symbol):
            return self._finalize_session_impulse_retest_auto_route_audit(
                symbol=symbol,
                response=response,
                observed_ts=observed_ts,
            )
        self.db.commit()
        return response

    def _auto_route_session_impulse_retest_plan(
        self,
        *,
        symbol: str,
        plan: Plan,
        requested_mode: ExecutionMode,
        now: datetime,
    ) -> dict[str, Any]:
        result, intents_created, submit_calls = self._auto_route_attempt_live_plan(
            symbol=symbol,
            plan=plan,
            requested_mode=requested_mode,
            now=now,
        )
        return self._finalize_auto_route_audit(
            symbol=symbol,
            observed_ts=now,
            response={
                "symbol": symbol,
                "enabled": True,
                "requested_mode": requested_mode.value,
                "reason": self._auto_route_reason_from_results([result]),
                "families_considered": self._auto_route_live_families_considered(requested_mode),
                "plans_considered": 1,
                "intents_created": intents_created,
                "submit_calls": submit_calls,
                "results": [result],
            },
        )

    def auto_route_live_plans(self, *, symbol: str, plan_ids: list[str] | None = None) -> dict[str, Any]:
        normalized_symbol = str(symbol or "").upper().strip()
        now = datetime.now(timezone.utc)
        requested_mode = self._auto_route_requested_mode()
        families_considered = self._auto_route_live_families_considered(requested_mode)
        if requested_mode is None:
            return self._finalize_auto_route_audit(
                symbol=normalized_symbol,
                observed_ts=now,
                response={
                    "symbol": normalized_symbol,
                    "enabled": False,
                    "reason": "auto_trading_disabled_or_shadow_mode",
                    "families_considered": families_considered,
                    "plans_considered": 0,
                    "intents_created": 0,
                    "submit_calls": 0,
                    "results": [],
                },
            )

        families_considered = self._auto_route_live_families_considered(requested_mode)
        routable_symbols = self._auto_route_live_routable_symbols(requested_mode)
        if not routable_symbols or normalized_symbol not in routable_symbols:
            return self._finalize_auto_route_audit(
                symbol=normalized_symbol,
                observed_ts=now,
                response={
                    "symbol": normalized_symbol,
                    "enabled": False,
                    "requested_mode": requested_mode.value,
                    "reason": "symbol_not_live_enabled_for_auto_route",
                    "families_considered": families_considered,
                    "plans_considered": 0,
                    "intents_created": 0,
                    "submit_calls": 0,
                    "results": [],
                },
            )
        if not families_considered:
            return self._finalize_auto_route_audit(
                symbol=normalized_symbol,
                observed_ts=now,
                response={
                    "symbol": normalized_symbol,
                    "enabled": False,
                    "requested_mode": requested_mode.value,
                    "reason": "live_route_contract_empty",
                    "families_considered": families_considered,
                    "plans_considered": 0,
                    "intents_created": 0,
                    "submit_calls": 0,
                    "results": [],
                },
            )

        candidates, rejected_counts, normalized_plan_ids = self._auto_route_live_candidate_plans(
            symbol=normalized_symbol,
            requested_mode=requested_mode,
            plan_ids=plan_ids,
            now=now,
        )
        if not candidates:
            return self._finalize_auto_route_audit(
                symbol=normalized_symbol,
                observed_ts=now,
                response={
                    "symbol": normalized_symbol,
                    "enabled": True,
                    "requested_mode": requested_mode.value,
                    "reason": self._auto_route_no_candidate_reason(
                        plan_ids=normalized_plan_ids,
                        rejected_counts=rejected_counts,
                    ),
                    "families_considered": families_considered,
                    "plans_considered": 0,
                    "intents_created": 0,
                    "submit_calls": 0,
                    "rejected_plan_counts": rejected_counts,
                    "results": [],
                },
            )

        results: list[dict[str, Any]] = []
        intents_created = 0
        submit_calls = 0
        for plan in candidates:
            result, plan_intents_created, plan_submit_calls = self._auto_route_attempt_live_plan(
                symbol=normalized_symbol,
                plan=plan,
                requested_mode=requested_mode,
                now=now,
            )
            results.append(result)
            intents_created += plan_intents_created
            submit_calls += plan_submit_calls
            if str(result.get("status") or "") in {"submitted", "submit_error", "intent_error"}:
                break

        return self._finalize_auto_route_audit(
            symbol=normalized_symbol,
            observed_ts=now,
            response={
                "symbol": normalized_symbol,
                "enabled": True,
                "requested_mode": requested_mode.value,
                "reason": self._auto_route_reason_from_results(results),
                "families_considered": families_considered,
                "plans_considered": len(candidates),
                "intents_created": intents_created,
                "submit_calls": submit_calls,
                "rejected_plan_counts": rejected_counts,
                "results": results,
            },
        )

    def auto_route_session_impulse_retest_plans(self, *, symbol: str, plan_ids: list[str]) -> dict[str, Any]:
        return self.auto_route_live_plans(symbol=symbol, plan_ids=plan_ids)

    def auto_route_symbol(self, *, symbol: str) -> dict[str, Any]:
        return self.auto_route_live_plans(symbol=symbol)

    @staticmethod
    def _paper_exit_price_tolerance(value: float) -> float:
        return max(abs(float(value)) * 0.0005, 1e-6)

    def _latest_paper_submission_for_plan(self, plan_id: str):
        rows = self.submission_repo.list_for_plan(plan_id, limit=20)
        for row in rows:
            if str(row.adapter or "").lower() == "paper":
                return row
        return None

    @staticmethod
    def _paper_submission_reference_ts(submission: Any) -> datetime | None:
        for attr in ("acknowledged_at", "submitted_at", "updated_at", "created_at"):
            value = getattr(submission, attr, None)
            if isinstance(value, datetime):
                if value.tzinfo is None:
                    return value.replace(tzinfo=timezone.utc)
                return value.astimezone(timezone.utc)
        return None

    def _paper_sample_stale_cleanup_ready(self, *, plan: Any, submission: Any) -> bool:
        if str(getattr(submission, "adapter", "") or "").lower() != "paper":
            return False
        threshold_hours = self._maybe_float(getattr(self.settings, "auto_trading_paper_stale_sample_cleanup_hours", 0)) or 0.0
        if threshold_hours <= 0:
            return False
        reference_ts = self._paper_submission_reference_ts(submission)
        if reference_ts is None:
            return False
        if reference_ts > datetime.now(timezone.utc) - timedelta(hours=threshold_hours):
            return False
        return self.candle_repo.get_last_candle(plan.symbol, "1m") is None and self.candle_repo.get_last_candle(plan.symbol, "5m") is None

    def _latest_paper_exit_candle(
        self,
        *,
        symbol: str,
        sync_candles: bool,
        limit_1m: int,
        limit_5m: int,
    ):
        if sync_candles:
            try:
                self.market_data.backfill_symbol_timeframes(
                    symbol=symbol,
                    limit_1m=max(1, int(limit_1m)),
                    limit_5m=max(1, int(limit_5m)),
                    limit_15m=0,
                )
            except Exception:
                self.db.rollback()
        for timeframe in ("1m", "5m"):
            candles = self.market_data.recent_candles(symbol, timeframe, limit=1)
            if candles:
                return candles[-1], timeframe
        return None, None

    @staticmethod
    def _paper_exit_split_weights(plan) -> dict[str, float]:
        split = dict(plan.split or {})
        weights = {
            "tp1": max(float(split.get("tp1", 0.0) or 0.0), 0.0),
            "tp2": max(float(split.get("tp2", 0.0) or 0.0), 0.0),
            "runner": max(float(split.get("runner", 0.0) or 0.0), 0.0),
        }
        total = sum(weights.values())
        if total <= 1e-9:
            return {"tp1": 0.5, "tp2": 0.5, "runner": 0.0}
        if abs(total - 1.0) <= 1e-6:
            return weights
        return {key: float(value / total) for key, value in weights.items()}

    @staticmethod
    def _paper_exit_effective_state(plan, previous_fills: list[Any]) -> str:
        latest_fill = max(
            previous_fills,
            key=lambda item: item.fill_ts if item.fill_ts.tzinfo else item.fill_ts.replace(tzinfo=timezone.utc),
            default=None,
        )
        if latest_fill is None:
            return str(plan.state or "")
        stage = str(latest_fill.stage or "")
        if stage == ExecutionFillStage.ENTRY.value:
            return PlanState.ENTERED.value
        if stage == ExecutionFillStage.PARTIAL_EXIT.value:
            return PlanState.PARTIAL_EXIT.value
        if stage == ExecutionFillStage.CLOSED.value:
            return PlanState.CLOSED.value
        return str(plan.state or "")

    def _paper_exit_threshold_hits(self, *, plan, candle) -> dict[str, bool]:
        high = float(candle.h)
        low = float(candle.l)
        direction = str(plan.direction or "").lower()
        tolerance = self._paper_exit_price_tolerance
        if direction == "short":
            return {
                "stop": high >= float(plan.sl) - tolerance(plan.sl),
                "tp1": low <= float(plan.tp1) + tolerance(plan.tp1),
                "tp2": low <= float(plan.tp2) + tolerance(plan.tp2),
                "tp3": low <= float(plan.tp3) + tolerance(plan.tp3),
            }
        return {
            "stop": low <= float(plan.sl) + tolerance(plan.sl),
            "tp1": high >= float(plan.tp1) - tolerance(plan.tp1),
            "tp2": high >= float(plan.tp2) - tolerance(plan.tp2),
            "tp3": high >= float(plan.tp3) - tolerance(plan.tp3),
        }

    @staticmethod
    def _paper_exit_bar_seconds(timeframe: str) -> int:
        if str(timeframe or "") == "15m":
            return 15 * 60
        return 5 * 60

    def _paper_exit_held_bars(self, *, plan, fill_ts: datetime, previous_fills: list[Any]) -> int:
        entry_ts = plan.valid_from if getattr(plan, "valid_from", None) else fill_ts
        for fill in previous_fills:
            if str(getattr(fill, "stage", "") or "") == ExecutionFillStage.ENTRY.value:
                fill_entry_ts = fill.fill_ts if fill.fill_ts.tzinfo else fill.fill_ts.replace(tzinfo=timezone.utc)
                entry_ts = fill_entry_ts.astimezone(timezone.utc)
                break
        normalized_fill_ts = fill_ts if fill_ts.tzinfo else fill_ts.replace(tzinfo=timezone.utc)
        normalized_fill_ts = normalized_fill_ts.astimezone(timezone.utc)
        normalized_entry_ts = entry_ts if entry_ts.tzinfo else entry_ts.replace(tzinfo=timezone.utc)
        normalized_entry_ts = normalized_entry_ts.astimezone(timezone.utc)
        delta_seconds = max(0.0, (normalized_fill_ts - normalized_entry_ts).total_seconds())
        bar_seconds = max(1, self._paper_exit_bar_seconds(str(getattr(plan, "timeframe", "") or "5m")))
        if delta_seconds <= 0.0:
            return 0
        return int((delta_seconds + bar_seconds - 1) // bar_seconds)

    @staticmethod
    def _parse_iso_utc(value: Any) -> datetime | None:
        if value in {None, ""}:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _repair_missing_paper_plan_from_submission(
        self,
        *,
        submission: Any,
        intent: Any | None,
    ) -> Any | None:
        if str(getattr(submission, "adapter", "") or "").lower() != "paper":
            return None
        plan_id = str(getattr(submission, "plan_id", "") or getattr(intent, "plan_id", "") or "")
        if not plan_id:
            return None
        existing = self.plan_repo.get(plan_id)
        if existing is not None:
            return existing

        payload = _safe_dict(getattr(intent, "payload", None))
        executable_plan = _safe_dict(payload.get("executable_plan"))
        if not executable_plan:
            return None

        raw = _safe_dict(getattr(submission, "raw", None))
        raw_fill_results = raw.get("fill_results")
        fill_results = list(raw_fill_results) if isinstance(raw_fill_results, list) else []
        raw_tp_targets = executable_plan.get("tp_targets")
        tp_targets = list(raw_tp_targets) if isinstance(raw_tp_targets, list) else []
        tp_by_label = {
            str(item.get("label") or "").upper(): _safe_dict(item)
            for item in tp_targets
            if isinstance(item, Mapping)
        }

        entry_price = executable_plan.get("entry_limit_price")
        if entry_price in {None, ""}:
            entry_price = executable_plan.get("entry_trigger_price")
        if entry_price in {None, ""} and fill_results:
            entry_price = _safe_dict(fill_results[0]).get("price")
        stop_price = executable_plan.get("stop_price")
        if entry_price in {None, ""} or stop_price in {None, ""}:
            return None

        entry_price_parsed = self._maybe_float(entry_price)
        stop_price_parsed = self._maybe_float(stop_price)
        if entry_price_parsed is None or stop_price_parsed is None:
            return None
        entry_price = entry_price_parsed
        stop_price = stop_price_parsed
        risk_distance = max(abs(entry_price - stop_price), 1e-9)
        direction = str(executable_plan.get("direction") or "long").lower()

        def _target_price(label: str, default_rr: float) -> float:
            target = _safe_dict(tp_by_label.get(label))
            price = target.get("price")
            parsed_price = self._maybe_float(price)
            if parsed_price is not None:
                return parsed_price
            sign = 1.0 if direction == "long" else -1.0
            return float(entry_price + sign * risk_distance * default_rr)

        def _target_fraction(label: str, default_fraction: float) -> float:
            target = _safe_dict(tp_by_label.get(label))
            fraction = target.get("size_fraction")
            try:
                return float(fraction if fraction not in {None, ""} else default_fraction)
            except (TypeError, ValueError):
                return float(default_fraction)

        tp1 = _target_price("TP1", 1.0)
        tp2 = _target_price("TP2", 2.0)
        tp3 = _target_price("TP3", 3.0)
        split = {
            "tp1": _target_fraction("TP1", 0.4),
            "tp2": _target_fraction("TP2", 0.4),
            "runner": _target_fraction("TP3", 0.2),
        }

        def _rr(target_price: float) -> float:
            return round(abs(float(target_price) - entry_price) / risk_distance, 4)

        valid_from = self._parse_iso_utc(executable_plan.get("valid_from")) or getattr(submission, "submitted_at", None)
        valid_until = self._parse_iso_utc(executable_plan.get("valid_until")) or getattr(submission, "submitted_at", None)
        if valid_from is None:
            valid_from = datetime.now(timezone.utc)
        if valid_until is None:
            valid_until = valid_from

        setup_score = self._maybe_float(executable_plan.get("setup_score")) or 0.0
        expected_summary = _safe_dict(executable_plan.get("expected_summary"))
        context_snapshot = _safe_dict(executable_plan.get("context_snapshot"))
        strategy_family = str(
            executable_plan.get("strategy_family")
            or getattr(intent, "strategy_family", "")
            or "legacy_zone_plan"
        )
        latest_fill_stage = str(_safe_dict(fill_results[-1]).get("stage") or "").upper() if fill_results else ""
        if latest_fill_stage == ExecutionFillStage.CLOSED.value:
            plan_state = PlanState.CLOSED.value
        elif latest_fill_stage == ExecutionFillStage.PARTIAL_EXIT.value:
            plan_state = PlanState.PARTIAL_EXIT.value
        elif latest_fill_stage == ExecutionFillStage.ENTRY.value:
            plan_state = PlanState.ENTERED.value
        elif str(getattr(submission, "state", "") or "") in {
            OrderLifecycleState.FILLED.value,
            OrderLifecycleState.PARTIALLY_FILLED.value,
        }:
            plan_state = PlanState.ENTERED.value
        else:
            plan_state = PlanState.ARMED.value

        self.plan_repo.upsert_many(
            [
                Plan(
                    plan_id=plan_id,
                    zone_id=f"recovered:{plan_id}"[:50],
                    symbol=str(executable_plan.get("symbol") or getattr(submission, "symbol", "") or ""),
                    timeframe=str(executable_plan.get("tf") or "5m"),
                    direction=direction,
                    entry_model=str(executable_plan.get("entry_model") or "CONFIRM"),
                    entry_price=entry_price,
                    entry_condition=str(executable_plan.get("entry_semantics") or ""),
                    sl=stop_price,
                    tp1=tp1,
                    tp2=tp2,
                    tp3=tp3,
                    split=split,
                    rr_min=_rr(tp1),
                    rr_base=_rr(tp2),
                    rr_opt=_rr(tp3),
                    ev=float(expected_summary.get("expected_ev_r", 0.0) or 0.0),
                    cost_est=0.0,
                    confidence=min(max(setup_score / 100.0, 0.0), 1.0),
                    validity={
                        "strategy_family": strategy_family,
                        "strategy_grade": str(executable_plan.get("setup_grade") or ""),
                        "regime": str(context_snapshot.get("regime") or "unknown"),
                        "strategy_mode": str(executable_plan.get("strategy_mode") or ""),
                        "entry_type": str(executable_plan.get("entry_type") or ""),
                        "expected_summary": expected_summary,
                        "thesis_primary_symbol": str(executable_plan.get("thesis_primary_symbol") or ""),
                        "thesis_cluster_id": str(executable_plan.get("thesis_cluster_id") or ""),
                        "context_snapshot": context_snapshot,
                        "recovered_from_submission_id": str(getattr(submission, "submission_id", "") or ""),
                        "recovered_from_intent_id": str(getattr(intent, "intent_id", "") or ""),
                        "recovered_from_order_payload": True,
                    },
                    state=plan_state,
                    valid_from=valid_from,
                    valid_until=valid_until,
                    strategy_version=str(executable_plan.get("strategy_version") or self.settings.strategy_version),
                )
            ]
        )
        self.db.flush()
        return self.plan_repo.get(plan_id)

    def _repair_closed_plan_exit_metadata_from_fill_payload(
        self,
        *,
        families: set[str] | None = None,
        days: int = 180,
        limit: int = 5000,
    ) -> int:
        target_families = {
            str(item).strip().lower()
            for item in (families or self._GLOBAL_LINEAGE_VALIDATION_FAMILIES)
            if str(item).strip()
        }
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
        closed_fills = list(
            self.db.scalars(
                select(ExecutionFill)
                .where(
                    ExecutionFill.stage == ExecutionFillStage.CLOSED.value,
                    ExecutionFill.fill_ts >= cutoff,
                )
                .order_by(ExecutionFill.fill_ts.asc(), ExecutionFill.created_at.asc())
                .limit(max(100, int(limit)))
            )
        )
        latest_closed_fill_by_plan_id: dict[str, Any] = {}
        for fill in closed_fills:
            plan_id = str(getattr(fill, "plan_id", "") or "")
            if not plan_id:
                continue
            latest_closed_fill_by_plan_id[plan_id] = fill

        if not latest_closed_fill_by_plan_id:
            return 0

        plans = list(
            self.db.scalars(
                select(Plan).where(Plan.plan_id.in_(list(latest_closed_fill_by_plan_id.keys())))
            )
        )
        candidate_plans: list[Any] = []
        for plan in plans:
            validity = _safe_dict(getattr(plan, "validity", None))
            family = str(validity.get("strategy_family") or "").strip().lower()
            if target_families and family not in target_families:
                continue
            if all(
                validity.get(key) not in {None, ""}
                for key in (
                    "final_exit_ts",
                    "final_exit_realized_r",
                    "final_exit_reason",
                    "final_exit_held_bars",
                )
            ):
                continue
            candidate_plans.append(plan)

        if not candidate_plans:
            return 0

        repaired = 0
        for plan in candidate_plans:
            close_fill = latest_closed_fill_by_plan_id.get(str(getattr(plan, "plan_id", "") or ""))
            if close_fill is None:
                continue
            validity = _safe_dict(getattr(plan, "validity", None))
            payload = _safe_dict(getattr(close_fill, "payload", None))
            changed = False

            fill_ts = getattr(close_fill, "fill_ts", None)
            fill_ts_text = self._to_utc(fill_ts).isoformat() if fill_ts is not None else ""
            exit_ts = str(payload.get("exit_ts") or fill_ts_text or "").strip()
            exit_reason = str(payload.get("exit_reason") or "").strip()
            exit_price = self._maybe_float(payload.get("exit_price"))
            if exit_price is None:
                exit_price = self._maybe_float(getattr(close_fill, "price", None))
            realized_r = self._maybe_float(payload.get("realized_r"))
            held_bars = self._maybe_int(payload.get("held_bars"))
            classification_before = payload.get("classification_before_exit")
            classification_after = payload.get("classification_after_exit")
            trigger_detail = _safe_dict(payload.get("trigger_detail"))

            if validity.get("final_exit_ts") in {None, ""} and exit_ts:
                validity["final_exit_ts"] = exit_ts
                changed = True
            if validity.get("final_exit_realized_r") in {None, ""} and realized_r is not None:
                validity["final_exit_realized_r"] = float(realized_r)
                changed = True
            if validity.get("final_exit_reason") in {None, ""} and exit_reason:
                validity["final_exit_reason"] = exit_reason
                changed = True
            if validity.get("final_exit_held_bars") in {None, ""} and held_bars is not None:
                validity["final_exit_held_bars"] = int(held_bars)
                changed = True
            if validity.get("final_exit_price") in {None, ""} and exit_price is not None:
                validity["final_exit_price"] = float(exit_price)
                changed = True
            if validity.get("final_exit_classification_before") in {None, ""} and classification_before not in {None, ""}:
                validity["final_exit_classification_before"] = classification_before
                changed = True
            if validity.get("final_exit_classification_after") in {None, ""} and classification_after not in {None, ""}:
                validity["final_exit_classification_after"] = classification_after
                changed = True
            if not _safe_dict(validity.get("final_exit_trigger_detail")) and trigger_detail:
                validity["final_exit_trigger_detail"] = trigger_detail
                changed = True
            if validity.get("last_exit_ts") in {None, ""} and exit_ts:
                validity["last_exit_ts"] = exit_ts
                changed = True
            if validity.get("last_exit_reason") in {None, ""} and exit_reason:
                validity["last_exit_reason"] = exit_reason
                changed = True
            if validity.get("last_exit_price") in {None, ""} and exit_price is not None:
                validity["last_exit_price"] = float(exit_price)
                changed = True

            if not changed:
                continue
            plan.validity = validity
            self.plan_repo.db.add(plan)
            repaired += 1
        return repaired

    def process_paper_exit_tick(
        self,
        *,
        families: list[str] | None = None,
        days: int = 7,
        limit: int = 200,
        sync_candles: bool = True,
        limit_1m: int = 3,
        limit_5m: int = 3,
        ) -> dict[str, Any]:
        normalized_families = {str(item).strip().lower() for item in (families or []) if str(item).strip()}
        submission_rows = self.submission_repo.list_recent(days=max(1, int(days)), limit=max(50, int(limit) * 5))
        candidate_rows: list[tuple[Any, Any, str]] = []
        seen_plan_ids: set[str] = set()
        plan_repairs = 0
        for submission in submission_rows:
            if str(submission.adapter or "").lower() != "paper":
                continue
            plan_id = str(submission.plan_id or "")
            if not plan_id or plan_id in seen_plan_ids:
                continue
            intent = self.intent_repo.get(str(submission.intent_id or ""))
            plan = self.plan_repo.get(plan_id)
            if plan is None:
                repaired_plan = self._repair_missing_paper_plan_from_submission(submission=submission, intent=intent)
                if repaired_plan is not None:
                    plan = repaired_plan
                    plan_repairs += 1
            if plan is None or str(plan.timeframe or "") != "5m":
                continue
            family = str(
                (
                    getattr(intent, "strategy_family", "")
                    or _safe_dict(getattr(plan, "validity", None)).get("strategy_family")
                    or "legacy_zone_plan"
                )
            ).lower()
            if normalized_families and family not in normalized_families:
                continue
            candidate_rows.append((plan, submission, family))
            seen_plan_ids.add(plan_id)
            if len(candidate_rows) >= max(1, int(limit)):
                break
        summary: dict[str, Any] = {
            "schema_version": "paper_exit_monitor_v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "families": sorted(normalized_families),
            "processed_plans": 0,
            "paper_candidate_plans": 0,
            "entry_states_seen": 0,
            "partial_exit_events": 0,
            "closed_events": 0,
            "skipped": 0,
            "plan_repairs": plan_repairs,
            "fill_repairs": 0,
            "state_repairs": 0,
            "stale_cleanup_events": 0,
            "actions": [],
        }
        summary["closed_validity_repairs"] = self._repair_closed_plan_exit_metadata_from_fill_payload(
            families=normalized_families or set(self._GLOBAL_LINEAGE_VALIDATION_FAMILIES),
            days=max(30, int(days)),
            limit=max(500, int(limit) * 10),
        )
        for plan, submission, family in candidate_rows:
            summary["processed_plans"] += 1

            repaired_fill = self._repair_missing_paper_entry_fill_from_submission(plan=plan, submission=submission)
            if repaired_fill is not None and self._safe_bool(repaired_fill.get("accepted")):
                summary["fill_repairs"] += 1

            previous_fills = sorted(
                self.fill_repo.list_for_plans(plan_ids=[plan.plan_id], symbol=plan.symbol),
                key=lambda item: item.fill_ts,
            )
            effective_state = self._paper_exit_effective_state(plan, previous_fills)
            if effective_state in {PlanState.ENTERED.value, PlanState.PARTIAL_EXIT.value} and str(plan.state or "") != effective_state:
                plan.state = effective_state
                self.plan_repo.db.add(plan)
                summary["state_repairs"] += 1
            if effective_state not in {PlanState.ENTERED.value, PlanState.PARTIAL_EXIT.value}:
                summary["skipped"] += 1
                continue

            summary["paper_candidate_plans"] += 1
            exited_qty = sum(
                max(float(fill.qty or 0.0), 0.0)
                for fill in previous_fills
                if str(fill.stage) == ExecutionFillStage.PARTIAL_EXIT.value
            )
            remaining_qty = max(0.0, 1.0 - exited_qty)
            candle, candle_timeframe = self._latest_paper_exit_candle(
                symbol=plan.symbol,
                sync_candles=sync_candles,
                limit_1m=limit_1m,
                limit_5m=limit_5m,
            )
            if candle is None:
                if self._paper_sample_stale_cleanup_ready(plan=plan, submission=submission):
                    fill_ts = datetime.now(timezone.utc).replace(microsecond=0)
                    latest_fill_ts = max(
                        (
                            fill.fill_ts if fill.fill_ts.tzinfo else fill.fill_ts.replace(tzinfo=timezone.utc)
                            for fill in previous_fills
                        ),
                        default=None,
                    )
                    if latest_fill_ts is not None and fill_ts <= latest_fill_ts.astimezone(timezone.utc):
                        fill_ts = latest_fill_ts.astimezone(timezone.utc) + timedelta(seconds=1)
                    cleanup_qty = remaining_qty if remaining_qty > 1e-10 else 1.0
                    response = self.ingest_execution_fill(
                        fill_id=f"paper_exit_{plan.plan_id}_stale_cleanup",
                        plan_id=plan.plan_id,
                        symbol=plan.symbol,
                        stage=ExecutionFillStage.CLOSED,
                        fill_ts=fill_ts,
                        price=float(plan.entry_price or 0.0),
                        qty=max(float(cleanup_qty), 0.0),
                        fee=0.0,
                        payload={
                            "source": "paper_exit_monitor_stale_cleanup",
                            "client_order_id": submission.client_order_id,
                            "execution_adapter": "paper",
                            "exit_reason": "paper_sample_stale_cleanup",
                            "remaining_qty": 0.0,
                            "notes": {
                                "monitor": "paper_exit_monitor_v1",
                                "cleanup_reason": "stale_no_market_candles",
                            },
                        },
                    )
                    summary["closed_events"] += 1
                    summary["stale_cleanup_events"] += 1
                    summary["actions"].append(
                        {
                            "plan_id": plan.plan_id,
                            "symbol": plan.symbol,
                            "family": family,
                            "status": "stale_cleanup_closed",
                            "stage": ExecutionFillStage.CLOSED.value,
                            "exit_reason": "paper_sample_stale_cleanup",
                            "price": float(plan.entry_price or 0.0),
                            "qty": round(float(cleanup_qty), 4),
                            "accepted": self._safe_bool(response.get("accepted")),
                            "duplicate": self._safe_bool(response.get("duplicate")),
                            "to_state": response.get("to_state"),
                        }
                    )
                    continue
                summary["actions"].append(
                    {
                        "plan_id": plan.plan_id,
                        "symbol": plan.symbol,
                        "family": family,
                        "status": "no_candle",
                    }
                )
                continue

            latest_fill_ts = max(
                (
                    fill.fill_ts if fill.fill_ts.tzinfo else fill.fill_ts.replace(tzinfo=timezone.utc)
                    for fill in previous_fills
                ),
                default=None,
            )
            exited_target_reasons = {
                str((fill.payload or {}).get("exit_reason") or "")
                for fill in previous_fills
                if str(fill.stage) in {ExecutionFillStage.PARTIAL_EXIT.value, ExecutionFillStage.CLOSED.value}
            }
            hits = self._paper_exit_threshold_hits(plan=plan, candle=candle)
            fill_ts = candle.ts
            candle_close = float(candle.c)
            candle_ts_text = fill_ts.isoformat() if hasattr(fill_ts, "isoformat") else str(fill_ts)
            held_bars = self._paper_exit_held_bars(plan=plan, fill_ts=fill_ts, previous_fills=previous_fills)
            max_allowed_bars = self._maybe_int(_safe_dict(getattr(plan, "validity", None)).get("strategy_family_time_stop_max_bars")) or 0
            summary["entry_states_seen"] += 1
            actions_for_plan: list[dict[str, Any]] = []
            if latest_fill_ts is not None:
                normalized_candle_ts = fill_ts if fill_ts.tzinfo else fill_ts.replace(tzinfo=timezone.utc)
                normalized_candle_ts = normalized_candle_ts.astimezone(timezone.utc)
                if normalized_candle_ts <= latest_fill_ts.astimezone(timezone.utc):
                    actions_for_plan.append(
                        {
                            "plan_id": plan.plan_id,
                            "symbol": plan.symbol,
                            "family": family,
                            "status": "await_next_candle_after_last_fill",
                            "candle_timeframe": candle_timeframe,
                            "candle_ts": candle_ts_text,
                            "last_fill_ts": latest_fill_ts.isoformat(),
                        }
                    )
                    summary["actions"].extend(actions_for_plan)
                    continue

            def _record_fill(
                *,
                leg: str,
                stage: ExecutionFillStage,
                price: float,
                qty: float,
                exit_reason: str,
                trigger_detail: dict[str, Any] | None = None,
                _plan: Plan = plan,
                _submission: Any = submission,
                _fill_ts: datetime = fill_ts,
                _candle_timeframe: str = candle_timeframe,
                _candle_ts_text: str = candle_ts_text,
                _family: str = family,
                _actions_for_plan: list[dict[str, Any]] = actions_for_plan,
            ) -> None:
                nonlocal remaining_qty
                response = self.ingest_execution_fill(
                    fill_id=f"paper_exit_{_plan.plan_id}_{leg}",
                    plan_id=_plan.plan_id,
                    symbol=_plan.symbol,
                    stage=stage,
                    fill_ts=_fill_ts,
                    price=price,
                    qty=max(float(qty), 0.0),
                    fee=0.0,
                    payload={
                        "source": "paper_exit_monitor",
                        "client_order_id": _submission.client_order_id,
                        "execution_adapter": "paper",
                        "exit_reason": exit_reason,
                        "remaining_qty": 0.0 if stage == ExecutionFillStage.CLOSED else max(remaining_qty - qty, 0.0),
                        "trigger_detail": dict(trigger_detail or {}),
                        "notes": {
                            "monitor": "paper_exit_monitor_v1",
                            "candle_timeframe": _candle_timeframe,
                            "candle_ts": _candle_ts_text,
                        },
                    },
                )
                remaining_qty = max(0.0, remaining_qty - qty)
                _actions_for_plan.append(
                    {
                        "plan_id": _plan.plan_id,
                        "symbol": _plan.symbol,
                        "family": _family,
                        "leg": leg,
                        "stage": stage.value,
                        "exit_reason": exit_reason,
                        "price": float(price),
                        "qty": round(float(qty), 4),
                        "accepted": self._safe_bool(response.get("accepted")),
                        "duplicate": self._safe_bool(response.get("duplicate")),
                        "to_state": response.get("to_state"),
                    }
                )
                if stage == ExecutionFillStage.CLOSED:
                    summary["closed_events"] += 1
                elif stage == ExecutionFillStage.PARTIAL_EXIT:
                    summary["partial_exit_events"] += 1

            fast_failure_policy = resolve_fast_failure_policy(plan=plan, held_bars=held_bars)
            if (
                remaining_qty > 1e-10
                and fast_failure_policy is not None
                and (not fast_failure_policy.requires_sl_touch or hits["stop"])
                and fast_failure_hit(
                    plan=plan,
                    policy=fast_failure_policy,
                    high=float(candle.h),
                    low=float(candle.l),
                )
            ):
                _record_fill(
                    leg="fast_failure",
                    stage=ExecutionFillStage.CLOSED,
                    price=float(fast_failure_policy.stop_price),
                    qty=remaining_qty,
                    exit_reason=ExitReason.STRUCTURE_FAILURE.value,
                    trigger_detail=fast_failure_trigger_detail(
                        plan=plan,
                        policy=fast_failure_policy,
                        held_bars=held_bars,
                    ),
                )
            elif remaining_qty > 1e-10 and hits["stop"]:
                _record_fill(
                    leg="stop",
                    stage=ExecutionFillStage.CLOSED,
                    price=float(plan.sl),
                    qty=remaining_qty,
                    exit_reason="stop_loss",
                )
            else:
                split = self._paper_exit_split_weights(plan)
                if (
                    remaining_qty > 1e-10
                    and "target_tp1" not in exited_target_reasons
                    and hits["tp1"]
                    and split["tp1"] > 1e-10
                ):
                    tp1_qty = min(remaining_qty, split["tp1"])
                    stage = ExecutionFillStage.CLOSED if remaining_qty - tp1_qty <= 1e-10 else ExecutionFillStage.PARTIAL_EXIT
                    _record_fill(
                        leg="tp1",
                        stage=stage,
                        price=float(plan.tp1),
                        qty=tp1_qty,
                        exit_reason="target_tp1",
                    )
                    exited_target_reasons.add("target_tp1")

                if (
                    remaining_qty > 1e-10
                    and "target_tp2" not in exited_target_reasons
                    and hits["tp2"]
                    and split["tp2"] > 1e-10
                ):
                    tp2_qty = min(remaining_qty, split["tp2"])
                    stage = ExecutionFillStage.CLOSED if remaining_qty - tp2_qty <= 1e-10 else ExecutionFillStage.PARTIAL_EXIT
                    _record_fill(
                        leg="tp2",
                        stage=stage,
                        price=float(plan.tp2),
                        qty=tp2_qty,
                        exit_reason="target_tp2",
                    )
                    exited_target_reasons.add("target_tp2")

                if remaining_qty > 1e-10 and hits["tp3"]:
                    _record_fill(
                        leg="tp3",
                        stage=ExecutionFillStage.CLOSED,
                        price=float(plan.tp3),
                        qty=remaining_qty,
                        exit_reason="target_tp3",
                    )
                elif remaining_qty > 1e-10 and max_allowed_bars > 0 and held_bars > max_allowed_bars:
                    _record_fill(
                        leg="time_stop",
                        stage=ExecutionFillStage.CLOSED,
                        price=candle_close,
                        qty=remaining_qty,
                        exit_reason=ExitReason.TIME_FAILURE.value,
                    )
                elif remaining_qty > 1e-10 and candle.ts >= plan.valid_until:
                    _record_fill(
                        leg="expiry",
                        stage=ExecutionFillStage.CLOSED,
                        price=candle_close,
                        qty=remaining_qty,
                        exit_reason="session_end_flatten",
                    )

            if not actions_for_plan:
                actions_for_plan.append(
                    {
                        "plan_id": plan.plan_id,
                        "symbol": plan.symbol,
                        "family": family,
                        "status": "holding",
                        "candle_timeframe": candle_timeframe,
                        "candle_ts": candle_ts_text,
                    }
                )
            summary["actions"].extend(actions_for_plan)
        if (
            summary["plan_repairs"] > 0
            or summary["fill_repairs"] > 0
            or summary["state_repairs"] > 0
            or int(summary.get("stale_cleanup_events", 0) or 0) > 0
            or summary["partial_exit_events"] > 0
            or summary["closed_events"] > 0
            or int(summary.get("closed_validity_repairs", 0) or 0) > 0
        ):
            self.db.commit()
        return summary

    def _repair_missing_paper_entry_fill_from_submission(
        self,
        *,
        plan: Any,
        submission: Any,
    ) -> dict[str, Any] | None:
        if str(getattr(submission, "adapter", "") or "").lower() != "paper":
            return None
        existing_fills = self.fill_repo.list_for_plans(plan_ids=[str(getattr(plan, "plan_id", "") or "")], symbol=plan.symbol)
        if existing_fills:
            return None
        raw = _safe_dict(getattr(submission, "raw", None))
        raw_fill_results = raw.get("fill_results")
        fill_results = list(raw_fill_results) if isinstance(raw_fill_results, list) else []
        entry_result = None
        for item in fill_results:
            row = _safe_dict(item)
            if not self._safe_bool(row.get("accepted")):
                continue
            if str(row.get("stage") or "") == ExecutionFillStage.ENTRY.value:
                entry_result = row
                break
        if not entry_result:
            return None

        fill_ts = (
            getattr(submission, "acknowledged_at", None)
            or getattr(submission, "submitted_at", None)
            or getattr(submission, "created_at", None)
            or datetime.now(timezone.utc)
        )
        if fill_ts.tzinfo is None:
            fill_ts = fill_ts.replace(tzinfo=timezone.utc)
        else:
            fill_ts = fill_ts.astimezone(timezone.utc)

        payload = {
            "source": "paper_submission_raw_repair",
            "client_order_id": str(getattr(submission, "client_order_id", "") or ""),
            "exchange_order_id": str(getattr(submission, "exchange_order_id", "") or ""),
            "repaired_from_submission_id": str(getattr(submission, "submission_id", "") or ""),
        }
        return self.ingest_execution_fill(
            fill_id=str(entry_result.get("fill_id") or f"paper_repair_{plan.plan_id}_entry"),
            plan_id=str(getattr(plan, "plan_id", "") or ""),
            symbol=str(getattr(plan, "symbol", "") or ""),
            stage=ExecutionFillStage.ENTRY,
            fill_ts=fill_ts,
            price=float(getattr(plan, "entry_price", 0.0) or 0.0),
            qty=1.0,
            fee=0.0,
            payload=payload,
        )

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
        tracker = get_execution_lane_tracker(
            window=max(1, self._maybe_int(self.settings.transition_edge_variant_lane_tracker_window) or 1)
        )
        variant_locks = list(payload.get("transition_edge_variant_matching_locks") or [])
        payload["transition_edge_variant"] = {
            "enabled": self._safe_bool(self.settings.transition_edge_variant_enabled),
            "shadow_only": self._safe_bool(self.settings.transition_edge_variant_shadow_only),
            "killed": self._safe_bool(payload.get("transition_edge_variant_disabled_active", False)),
            "reason": str((variant_locks[0] or {}).get("reason_code") or "") if variant_locks else None,
            "reason_message": str((variant_locks[0] or {}).get("reason_message") or "") if variant_locks else None,
            "partial_ratio": round(self._maybe_float(self.settings.transition_edge_variant_partial_activation_ratio) or 0.0, 4),
            "live_lane": tracker.snapshot(),
        }
        payload["session_impulse_retest_universe_policy"] = build_micro_main_rollout_contract_snapshot(
            enabled=self._safe_bool(self.settings.session_impulse_retest_enabled),
            shadow_only=self._safe_bool(self.settings.session_impulse_retest_shadow_only),
            partial_activation_ratio=self._maybe_float(self.settings.session_impulse_retest_partial_activation_ratio) or 0.0,
            core_live_slots=self._maybe_int(self.settings.session_impulse_retest_core_live_slots) or 0,
            secondary_live_enabled=self._safe_bool(self.settings.session_impulse_retest_secondary_live_enabled),
        )
        if symbol:
            shadow_summary = self._session_impulse_retest_shadow_summary(symbol=symbol)
            payload["session_impulse_retest_rollout_readiness"] = self._session_impulse_retest_rollout_readiness(
                symbol=symbol,
                shadow_summary=shadow_summary,
            )
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
        fast: bool = False,
    ) -> dict[str, Any]:
        safety_state = self._safety_state_payload(symbol=symbol)
        readiness_limit = max(8, int(intent_limit))

        def readiness_error_payload(exc: Exception, *, filter_symbol: str | None, scope: str) -> dict[str, Any]:
            return {
                "available": False,
                "advisory_only": True,
                "authority": "compare_only_no_live_authority_change",
                "filter_symbol": str(filter_symbol or "").strip().upper() or None,
                "scope": scope,
                "headline_state": "WATCH",
                "headline_reason": "live_candidate_readiness_unavailable",
                "headline_action": f"Inspect readiness aggregation error before using this dashboard field: {exc}",
                "promotion_decision": "observe_runtime",
                "error": str(exc),
            }

        try:
            live_candidate_promotion_readiness_summary = build_live_candidate_promotion_readiness_from_db(
                self.db,
                hours=24,
                limit=readiness_limit,
                symbol=symbol,
            )
            live_candidate_promotion_readiness_summary["scope"] = (
                "selected_symbol" if str(symbol or "").strip() else "global_all_symbols"
            )
        except Exception as exc:
            live_candidate_promotion_readiness_summary = readiness_error_payload(
                exc,
                filter_symbol=symbol,
                scope="selected_symbol" if str(symbol or "").strip() else "global_all_symbols",
            )
        if str(symbol or "").strip():
            try:
                live_candidate_promotion_readiness_global_summary = build_live_candidate_promotion_readiness_from_db(
                    self.db,
                    hours=24,
                    limit=readiness_limit,
                    symbol=None,
                )
                live_candidate_promotion_readiness_global_summary["scope"] = "global_all_symbols"
            except Exception as exc:
                live_candidate_promotion_readiness_global_summary = readiness_error_payload(
                    exc,
                    filter_symbol=None,
                    scope="global_all_symbols",
                )
        else:
            live_candidate_promotion_readiness_global_summary = dict(live_candidate_promotion_readiness_summary)
            live_candidate_promotion_readiness_global_summary["scope"] = "global_all_symbols"
        portfolio_summary = self.portfolio_budget_report(
            universe=universe,
            limit=portfolio_limit,
            write_report=False,
            outcome_symbol_limit=0 if bool(fast) else max(1, int(portfolio_limit)),
        )
        alert_summary = self.alert_metrics_report(days=days, write_report=False)
        execution_quality_summary = None
        if symbol:
            execution_quality_summary = self.execution_quality_report(
                symbol=symbol,
                days=days,
                write_report=False,
            )
        active_contract_summary = None
        if symbol:
            active_contract_summary = self._active_contract_summary(
                symbol=symbol,
                days=days,
                portfolio_summary=portfolio_summary,
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
        review_followup_ledger_summary = summarize_split_review_followup_ledger(
            symbol=symbol or "",
            universe=str(portfolio_summary.get("universe") or "usdc_perp_top30"),
        )
        edge_evolution_rule_summary = summarize_edge_evolution_rule(
            build_edge_evolution_rule(
                edge_experiment_review=edge_experiment_summary,
                rollout_recommendation=rollout_recommendation_summary,
                strategy_lifecycle=strategy_lifecycle_summary,
                kill_condition_automation=kill_condition_automation_summary,
                review_followup_ledger=review_followup_ledger_summary,
            )
        )
        operator_action_priority_summary = self.operator_action_priority.generate(
            dashboard={
                "playbook_action": portfolio_summary.get("playbook_action", ""),
                "playbook_message": portfolio_summary.get("playbook_message", ""),
                "new_entries_allowed": self._safe_bool(safety_state.get("new_entry_allowed", False)),
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
        payload = self.execution_operator_dashboard_service.generate(
            symbol=symbol,
            days=days,
            intent_limit=intent_limit,
            reconcile_limit=reconcile_limit,
            safety_state=safety_state,
            portfolio_summary=portfolio_summary,
            alert_summary=alert_summary,
            execution_quality_summary=execution_quality_summary,
            active_contract_summary=active_contract_summary,
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
        if symbol:
            shadow_summary = self._session_impulse_retest_shadow_summary(symbol=symbol)
            payload["session_impulse_retest_shadow"] = shadow_summary
            payload["session_impulse_retest_rollout_readiness"] = self._session_impulse_retest_rollout_readiness(
                symbol=symbol,
                shadow_summary=shadow_summary,
            )
        payload_signal_funnel = dict(payload.get("signal_funnel") or {})
        payload_signal_funnel["live_candidate_promotion_readiness"] = live_candidate_promotion_readiness_summary
        payload_signal_funnel["live_candidate_promotion_readiness_global"] = (
            live_candidate_promotion_readiness_global_summary
        )
        payload["signal_funnel"] = payload_signal_funnel
        payload["session_impulse_retest_universe_policy"] = build_micro_main_rollout_contract_snapshot(
            enabled=self._safe_bool(self.settings.session_impulse_retest_enabled),
            shadow_only=self._safe_bool(self.settings.session_impulse_retest_shadow_only),
            partial_activation_ratio=self._maybe_float(self.settings.session_impulse_retest_partial_activation_ratio) or 0.0,
            core_live_slots=self._maybe_int(self.settings.session_impulse_retest_core_live_slots) or 0,
            secondary_live_enabled=self._safe_bool(self.settings.session_impulse_retest_secondary_live_enabled),
        )
        return payload

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
        active_manual_override = self._safe_bool(summary.get("active_manual_override", False))
        configured_arm_token = str(self.settings.kill_condition_automation_arm_token or "")
        live_enabled = self._safe_bool(self.settings.kill_condition_automation_live_enabled)
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
            "allow_live_write": self._safe_bool(allow_live_write),
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
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if isfinite(parsed) else None

    @staticmethod
    def _maybe_int(value: Any) -> int | None:
        if value in (None, "", "None"):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return int(parsed) if isfinite(parsed) else None

    @staticmethod
    def _safe_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return bool(default)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value) if isfinite(float(value)) else bool(default)
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
        return bool(default)

    @staticmethod
    def _to_utc(value: Any) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return datetime.now(timezone.utc)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        return datetime.now(timezone.utc)

    @staticmethod
    def _maybe_utc(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        return None

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
        raw_payload = _safe_dict(raw)
        live_enabled = self._safe_bool(self.settings.binance_trade_live_enabled)
        status = raw_payload.get("status")
        if not status and action == "submit" and not requested_live:
            status = "TEST_ACCEPTED"
        return {
            "action": action,
            "mode": "live" if requested_live else "test",
            "requested_live": requested_live,
            "live_enabled": live_enabled,
            "test_order": not requested_live,
            "symbol": str(raw_payload.get("symbol") or symbol).upper(),
            "plan_id": plan_id,
            "order_id": self._maybe_int(raw_payload.get("orderId")),
            "client_order_id": str(raw_payload.get("clientOrderId") or client_order_id or ""),
            "status": str(status or ""),
            "side": str(raw_payload.get("side") or side or ""),
            "order_type": str(raw_payload.get("type") or order_type or ""),
            "price": self._maybe_float(raw_payload.get("price")) if raw_payload.get("price") not in (None, "") else price,
            "orig_qty": self._maybe_float(raw_payload.get("origQty")) if raw_payload.get("origQty") not in (None, "") else quantity,
            "executed_qty": self._maybe_float(raw_payload.get("executedQty")),
            "reduce_only": (
                self._safe_bool(raw_payload.get("reduceOnly"))
                if raw_payload.get("reduceOnly") is not None
                else self._safe_bool(reduce_only)
            ),
            "time_in_force": str(raw_payload.get("timeInForce") or time_in_force or ""),
            "raw": raw_payload,
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
            reduce_only=self._safe_bool(payload.get("reduce_only")),
            requested_live=self._safe_bool(payload.get("requested_live")),
            live_enabled=self._safe_bool(payload.get("live_enabled")),
            test_order=self._safe_bool(payload.get("test_order")),
            price=self._maybe_float(payload.get("price")),
            orig_qty=self._maybe_float(payload.get("orig_qty")),
            executed_qty=self._maybe_float(payload.get("executed_qty")),
            time_in_force=str(payload.get("time_in_force") or ""),
            last_event_type=event_type,
            last_trade_id=trade_id,
            last_event_ts=event_ts,
            raw=_safe_dict(payload.get("raw")) or _safe_dict(payload),
        )
        self.db.flush()
        return {
            "client_order_id": row.client_order_id,
            "exchange_order_id": row.exchange_order_id,
            "plan_id": row.plan_id,
            "symbol": row.symbol,
            "status": row.status,
            "reduce_only": self._safe_bool(row.reduce_only),
            "requested_live": self._safe_bool(row.requested_live),
            "test_order": self._safe_bool(row.test_order),
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
            row_payload = _safe_dict(row)
            if not row_payload:
                continue
            try:
                snapshot = BinancePositionSnapshot(**row_payload)
            except TypeError:
                continue
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
        if not self._safe_bool(event.get("reduce_only")):
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
        last_fill_qty = self._maybe_float(event.get("last_fill_qty")) or 0.0
        last_fill_price = self._maybe_float(event.get("last_fill_price")) or 0.0
        if last_fill_qty <= 0.0 or last_fill_price <= 0.0:
            return None
        if not self._safe_bool(event.get("reduce_only")):
            return ExecutionFillStage.ENTRY

        symbol = str(event.get("symbol") or "")
        matching = [row for row in current_positions if row.get("symbol") == symbol]
        remaining_amt = None
        if plan is not None and matching:
            side = "LONG" if str(plan.direction).lower() == "long" else "SHORT"
            side_rows = [row for row in matching if str(row.get("position_side") or "BOTH").upper() in {side, "BOTH"}]
            target_row = side_rows[0] if side_rows else matching[0]
            remaining_amt = abs(self._maybe_float(target_row.get("position_amt")) or 0.0)
        elif matching:
            remaining_amt = abs(self._maybe_float(matching[0].get("position_amt")) or 0.0)

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

    def _matching_submit_response_fill(
        self,
        *,
        plan: Any | None,
        order_id: int | None,
        stage: ExecutionFillStage | None,
        qty: float,
        price: float,
    ) -> Any | None:
        if plan is None or order_id is None or stage != ExecutionFillStage.ENTRY:
            return None
        for fill in self.fill_repo.list_for_plans(plan_ids=[plan.plan_id], symbol=plan.symbol):
            if str(getattr(fill, "stage", "")) != stage.value:
                continue
            payload = _safe_dict(getattr(fill, "payload", None))
            if str(payload.get("source") or "") != "binance_submit_response":
                continue
            if str(payload.get("exchange_order_id") or "") != str(order_id):
                continue
            fill_qty = self._maybe_float(getattr(fill, "qty", 0.0)) or 0.0
            if qty > 0.0 and abs(fill_qty - qty) > 1e-9:
                continue
            fill_price = self._maybe_float(getattr(fill, "price", 0.0)) or 0.0
            if price > 0.0 and abs(fill_price - price) > self._paper_exit_price_tolerance(price):
                continue
            return fill
        return None

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
                **_safe_dict(submission.raw),
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

    def load_binance_symbol_trading_rules(self, symbol: str) -> dict[str, Any]:
        rules = self.market_data.binance.fetch_symbol_trading_rules(symbol)
        return {
            "symbol": rules.symbol,
            "quantity_step": float(rules.quantity_step),
            "min_quantity": float(rules.min_quantity),
            "tick_size": float(rules.tick_size) if rules.tick_size is not None else None,
            "price_precision": rules.price_precision,
            "quantity_precision": rules.quantity_precision,
            "source": "binance_exchange_info",
        }

    def load_binance_live_liquidity_snapshot(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None = None,
        reference_price: float = 0.0,
    ) -> dict[str, Any]:
        normalized_symbol = str(symbol or "").upper()
        normalized_side = str(side or "").upper()
        depth_limit = max(1, self._maybe_int(getattr(self.settings, "auto_trading_live_liquidity_gate_orderbook_limit", 100)) or 100)
        order_book = self.market_data.binance.fetch_order_book(symbol=normalized_symbol, limit=depth_limit)

        def _levels(raw_rows: Any) -> list[tuple[float, float]]:
            levels: list[tuple[float, float]] = []
            for row in list(raw_rows or []):
                if not isinstance(row, (list, tuple)) or len(row) < 2:
                    continue
                level_price = self._maybe_float(row[0])
                level_qty = self._maybe_float(row[1])
                if level_price is None or level_qty is None:
                    continue
                if level_price > 0.0 and level_qty > 0.0:
                    levels.append((level_price, level_qty))
            return levels

        bids = _levels(order_book.get("bids"))
        asks = _levels(order_book.get("asks"))
        best_bid = bids[0][0] if bids else 0.0
        best_ask = asks[0][0] if asks else 0.0
        mid_price = (best_bid + best_ask) / 2.0 if best_bid > 0.0 and best_ask > 0.0 else 0.0
        effective_reference = self._maybe_float(price) or self._maybe_float(reference_price) or mid_price or 0.0
        spread_bps = ((best_ask - best_bid) / mid_price * 10_000.0) if mid_price > 0.0 else None
        normalized_order_type = str(order_type or "").upper()
        is_marketable_now = normalized_order_type != "LIMIT"
        if normalized_order_type == "LIMIT" and price is not None:
            if normalized_side == "BUY":
                limit_price = self._maybe_float(price) or 0.0
                is_marketable_now = best_ask > 0.0 and limit_price >= best_ask
            else:
                limit_price = self._maybe_float(price) or 0.0
                is_marketable_now = best_bid > 0.0 and limit_price <= best_bid

        opposite_levels = asks if normalized_side == "BUY" else bids
        opposite_depth_notional = sum(level_price * level_qty for level_price, level_qty in opposite_levels)

        remaining_qty = max(self._maybe_float(quantity) or 0.0, 0.0)
        simulated_cost = 0.0
        simulated_qty = 0.0
        for level_price, level_qty in opposite_levels:
            if remaining_qty <= 0.0:
                break
            take_qty = min(remaining_qty, level_qty)
            simulated_cost += take_qty * level_price
            simulated_qty += take_qty
            remaining_qty -= take_qty

        market_fill_avg_price = simulated_cost / simulated_qty if simulated_qty > 0.0 else None
        market_slippage_bps = None
        if is_marketable_now and market_fill_avg_price is not None and effective_reference > 0.0:
            if normalized_side == "BUY":
                market_slippage_bps = max(0.0, (market_fill_avg_price - effective_reference) / effective_reference * 10_000.0)
            else:
                market_slippage_bps = max(0.0, (effective_reference - market_fill_avg_price) / effective_reference * 10_000.0)

        klines_1m = self.market_data.binance.fetch_klines(symbol=normalized_symbol, interval="1m", limit=5)
        quote_volumes = []
        for row in klines_1m:
            close_price = self._maybe_float(row.c)
            volume = self._maybe_float(row.v)
            if close_price is not None and volume is not None and close_price > 0.0 and volume >= 0.0:
                quote_volumes.append(close_price * volume)
        recent_1m_quote_volume = quote_volumes[-1] if quote_volumes else None
        recent_5m_quote_volume = sum(quote_volumes) if quote_volumes else None
        order_notional = max(self._maybe_float(quantity) or 0.0, 0.0) * max(effective_reference, 0.0)

        return {
            "source": "binance_public_depth_klines",
            "symbol": normalized_symbol,
            "side": normalized_side,
            "order_type": normalized_order_type,
            "marketable_now": bool(is_marketable_now),
            "orderbook_limit": depth_limit,
            "best_bid": round(best_bid, 8),
            "best_ask": round(best_ask, 8),
            "mid_price": round(mid_price, 8),
            "reference_price": round(effective_reference, 8),
            "order_notional": round(order_notional, 4),
            "spread_bps": round(float(spread_bps), 4) if spread_bps is not None else None,
            "opposite_depth_notional": round(opposite_depth_notional, 4),
            "market_fill_avg_price": round(float(market_fill_avg_price), 8) if market_fill_avg_price is not None else None,
            "market_slippage_bps": round(float(market_slippage_bps), 4) if market_slippage_bps is not None else None,
            "simulated_fill_coverage": round(simulated_qty / max(self._maybe_float(quantity) or 0.0, 1e-12), 6),
            "recent_1m_quote_volume": round(float(recent_1m_quote_volume), 4)
            if recent_1m_quote_volume is not None
            else None,
            "recent_5m_quote_volume": round(float(recent_5m_quote_volume), 4)
            if recent_5m_quote_volume is not None
            else None,
        }

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
            "closed": self._safe_bool(payload.get("closed")),
            "raw": payload.get("raw") or {},
        }

    def sync_binance_positions(self, *, symbol: str | None = None) -> dict[str, Any]:
        rows = [self.market_data.binance.normalize_position_risk_row(row) for row in self.market_data.binance.fetch_position_risk(symbol)]
        normalized = self._upsert_binance_positions(rows)
        self.db.commit()
        open_positions = [row for row in normalized if abs(self._maybe_float(row.get("position_amt")) or 0.0) > 1e-10]
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
        payload_map = _safe_dict(payload)
        normalized = (
            payload_map
            if "kind" in payload_map and "event_type" in payload_map
            else self.market_data.binance.normalize_user_stream_message(payload)
        )
        normalized = _safe_dict(normalized)
        kind = str(normalized.get("kind") or "unknown")
        if kind == "account_update":
            positions_source = normalized.get("positions")
            positions = self._upsert_binance_positions(list(positions_source) if isinstance(positions_source, list) else [])
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
                    "open_positions": len(
                        [row for row in positions if abs(self._maybe_float(row.get("position_amt")) or 0.0) > 1e-10]
                    ),
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
            "live_enabled": self._safe_bool(self.settings.binance_trade_live_enabled),
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
            "reduce_only": self._safe_bool(normalized.get("reduce_only")),
            "time_in_force": str(normalized.get("time_in_force") or ""),
            "raw": _safe_dict(normalized.get("raw")),
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
        duplicate_submit_fill = self._matching_submit_response_fill(
            plan=plan,
            order_id=self._maybe_int(normalized.get("order_id")),
            stage=stage,
            qty=self._maybe_float(normalized.get("last_fill_qty")) or 0.0,
            price=self._maybe_float(normalized.get("last_fill_price")) or self._maybe_float(normalized.get("avg_price")) or 0.0,
        )
        if duplicate_submit_fill is not None:
            payload = _safe_dict(getattr(duplicate_submit_fill, "payload", None))
            self.db.commit()
            fill_ingest = {
                "accepted": True,
                "duplicate": True,
                "fill_id": getattr(duplicate_submit_fill, "fill_id", ""),
                "plan_id": getattr(duplicate_submit_fill, "plan_id", ""),
                "symbol": getattr(duplicate_submit_fill, "symbol", ""),
                "stage": getattr(duplicate_submit_fill, "stage", None),
                "from_state": getattr(duplicate_submit_fill, "from_state", None),
                "to_state": getattr(duplicate_submit_fill, "to_state", None),
                "state_changed": False,
                "reason": "submit_response_fill_already_recorded",
                "exit_reason": payload.get("exit_reason"),
            }
        elif plan is not None and stage is not None:
            fill_payload = {
                "source": "binance_user_stream",
                "client_order_id": normalized.get("client_order_id"),
                "exchange_order_id": normalized.get("order_id"),
                "trade_id": normalized.get("trade_id"),
                "execution_type": normalized.get("execution_type"),
                "status": normalized.get("status"),
                "partial": str(normalized.get("status") or "").upper() == OrderLifecycleState.PARTIALLY_FILLED.value,
                "reduce_only": self._safe_bool(normalized.get("reduce_only")),
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
                price=self._maybe_float(normalized.get("last_fill_price")) or self._maybe_float(normalized.get("avg_price")) or 0.0,
                qty=self._maybe_float(normalized.get("last_fill_qty")) or 0.0,
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
            if result.get("fill_ingest") is not None and self._safe_bool((result.get("fill_ingest") or {}).get("accepted")):
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
        strategy_family = str(payload.get("strategy_family") or "").strip().lower()
        direction = str(payload.get("direction") or "").lower()
        entry_model = str(payload.get("entry_model") or "")
        event_price = payload.get("event_price", payload.get("fill_price"))
        entry_price = payload.get("entry_price")
        distance_bps = payload.get("distance_bps")
        distance_atr = payload.get("distance_atr")
        exit_reason = str(payload.get("exit_reason") or "")
        expected_summary = str(payload.get("expected_summary") or "").strip()
        sl = payload.get("sl")
        tp1 = payload.get("tp1")
        tp2 = payload.get("tp2")
        valid_until = payload.get("valid_until")
        time_stop_bars = payload.get("time_stop_bars")

        if strategy_family == "session_impulse_retest":
            valid_until_text = str(valid_until or "").replace("+00:00", "Z")
            dir_text = direction.upper() if direction else "-"
            levels_text = (
                f"e={self._fmt_number(entry_price)} sl={self._fmt_number(sl)} "
                f"tp1={self._fmt_number(tp1)} tp2={self._fmt_number(tp2)}"
            ).strip()
            expiry_text = f"exp={valid_until_text or 'signal_expiry'}"
            if alert_type == "confirm":
                message = f"{dir_text} {levels_text} {expiry_text}".strip()
                if expected_summary:
                    message = f"{message} | {expected_summary}"
                return message
            if alert_type == "touch":
                message = f"{dir_text} watch {levels_text} {expiry_text}".strip()
                if expected_summary:
                    message = f"{message} | {expected_summary}"
                return message
            if alert_type == "entry":
                time_stop_text = (
                    f"ts≈{int(time_stop_bars) * 5}m"
                    if isinstance(time_stop_bars, (int, float)) and float(time_stop_bars) > 0
                    else "ts=plan"
                )
                return (
                    f"{dir_text} fill={self._fmt_number(payload.get('fill_price'))} "
                    f"qty={self._fmt_number(payload.get('qty'))} {levels_text} {time_stop_text}"
                ).strip()
            if alert_type == "sl":
                return (
                    f"{dir_text} stop fill={self._fmt_number(payload.get('fill_price'))} "
                    f"r={self._fmt_number(payload.get('realized_r'), decimals=2)} "
                    f"reason={exit_reason or 'stop_loss'}"
                ).strip()
            if alert_type == "tp":
                return (
                    f"{dir_text} target fill={self._fmt_number(payload.get('fill_price'))} "
                    f"r={self._fmt_number(payload.get('realized_r'), decimals=2)} "
                    f"reason={exit_reason or 'target'}"
                ).strip()
            if alert_type == "closed":
                return (
                    f"{dir_text} closed fill={self._fmt_number(payload.get('fill_price'))} "
                    f"r={self._fmt_number(payload.get('realized_r'), decimals=2)} "
                    f"reason={exit_reason or 'closed'}"
                ).strip()

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
        near_atr_multiple = self._maybe_float(self.settings.signal_alert_near_atr_multiple) or 0.35
        near_threshold = max(float(atr_reference) * near_atr_multiple, 1e-6)
        for plan in plans:
            validity = _safe_dict(getattr(plan, "validity", None))
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
                "valid_from": getattr(plan, "valid_from", None).isoformat() if getattr(plan, "valid_from", None) else None,
                "valid_until": getattr(plan, "valid_until", None).isoformat() if getattr(plan, "valid_until", None) else None,
                "distance_abs": round(distance_abs, 6),
                "distance_bps": round(distance_bps, 4),
                "distance_atr": round(distance_atr, 4),
                "expected_summary": str(validity.get("expected_summary") or ""),
                "strategy_family": str(validity.get("strategy_family") or "legacy_zone_plan"),
                "strategy_grade": validity.get("strategy_grade"),
                "time_stop_bars": self._maybe_int(validity.get("strategy_family_time_stop_max_bars")) or 0,
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
        validity = _safe_dict(getattr(plan, "validity", None))
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
            "entry_price": float(plan.entry_price),
            "sl": float(plan.sl),
            "tp1": float(plan.tp1),
            "tp2": float(plan.tp2),
            "tp3": float(plan.tp3),
            "valid_from": getattr(plan, "valid_from", None).isoformat() if getattr(plan, "valid_from", None) else None,
            "valid_until": getattr(plan, "valid_until", None).isoformat() if getattr(plan, "valid_until", None) else None,
            "time_stop_bars": self._maybe_int(validity.get("strategy_family_time_stop_max_bars")) or 0,
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

    @classmethod
    def _global_lineage_validation_symbol(cls) -> str:
        return cls._GLOBAL_LINEAGE_VALIDATION_SYMBOL

    def _global_lineage_validation_plans(self, *, version: str) -> list[Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=180)
        closed_fills = list(
            self.db.scalars(
                select(ExecutionFill)
                .where(
                    ExecutionFill.stage == ExecutionFillStage.CLOSED.value,
                    ExecutionFill.fill_ts >= cutoff,
                )
                .order_by(ExecutionFill.fill_ts.asc(), ExecutionFill.created_at.asc())
                .limit(20000)
            )
        )
        family_set = set(self._GLOBAL_LINEAGE_VALIDATION_FAMILIES)
        close_fill_by_plan_id: dict[str, Any] = {}
        for fill in closed_fills:
            plan_id = str(getattr(fill, "plan_id", "") or "")
            if not plan_id:
                continue
            close_fill_by_plan_id[plan_id] = fill
        plans = list(
            self.db.scalars(
                select(Plan).where(Plan.plan_id.in_(list(close_fill_by_plan_id.keys())))
            )
        )
        synthetic_plans: list[Any] = []
        for plan in plans:
            validity = _safe_dict(getattr(plan, "validity", None))
            family = str(validity.get("strategy_family") or "").strip()
            plan_id = str(getattr(plan, "plan_id", "") or "")
            close_fill = close_fill_by_plan_id.get(plan_id)
            if family not in family_set or str(getattr(plan, "strategy_version", "")) != version or close_fill is None:
                continue
            validity.setdefault("lineage_source_symbol", str(getattr(plan, "symbol", "") or ""))
            payload = _safe_dict(getattr(close_fill, "payload", None))
            fill_ts = getattr(close_fill, "fill_ts", None)
            if not validity.get("final_exit_ts"):
                validity["final_exit_ts"] = str(payload.get("exit_ts") or (fill_ts.isoformat() if fill_ts is not None else ""))
            if validity.get("final_exit_realized_r") in {None, ""}:
                realized_r = self._maybe_float(payload.get("realized_r"))
                if realized_r is not None:
                    validity["final_exit_realized_r"] = float(realized_r)
            if validity.get("final_exit_reason") in {None, ""} and payload.get("exit_reason") not in {None, ""}:
                validity["final_exit_reason"] = str(payload.get("exit_reason") or "")
            if validity.get("final_exit_held_bars") in {None, ""}:
                held_bars = self._maybe_int(payload.get("held_bars"))
                if held_bars is not None:
                    validity["final_exit_held_bars"] = int(held_bars)
            synthetic_plans.append(
                SimpleNamespace(
                    plan_id=plan_id,
                    zone_id=str(getattr(plan, "zone_id", "") or ""),
                    symbol=self._global_lineage_validation_symbol(),
                    timeframe=str(getattr(plan, "timeframe", "5m") or "5m"),
                    direction=str(getattr(plan, "direction", "") or ""),
                    entry_model=str(getattr(plan, "entry_model", "") or ""),
                    state=PlanState.CLOSED.value,
                    valid_from=getattr(plan, "valid_from", None),
                    valid_until=getattr(plan, "valid_until", None),
                    strategy_version=str(getattr(plan, "strategy_version", "") or ""),
                    validity=validity,
                )
            )
        return synthetic_plans

    def _global_lineage_pbo_dsr_metrics(
        self,
        *,
        version: str,
        write_report: bool,
        persist_snapshot: bool,
        persist_runtime_validation_artifacts: bool = True,
    ) -> dict[str, Any]:
        symbol = self._global_lineage_validation_symbol()
        plans = self._global_lineage_validation_plans(version=version)
        self.strategy_v2_pbo_dsr_trial_writer.generate(
            symbol=symbol,
            version=version,
            plans=plans,
            write_report=False,
            persist=persist_runtime_validation_artifacts,
        )
        self.strategy_v2_pbo_dsr_threshold_runner.generate(
            symbol=symbol,
            version=version,
            plans=plans,
            write_report=False,
            persist=persist_runtime_validation_artifacts,
        )
        payload = self.strategy_v2_pbo_dsr_metrics.generate(
            symbol=symbol,
            version=version,
            write_report=write_report,
            persist_snapshot=bool(persist_snapshot and persist_runtime_validation_artifacts),
        )
        payload = dict(payload or {})
        payload["validation_scope"] = {
            "scope": "family_global",
            "families": list(self._GLOBAL_LINEAGE_VALIDATION_FAMILIES),
            "symbol_namespace": symbol,
        }
        return payload

    def _merge_global_lineage_pbo_fallback(
        self,
        *,
        primary: dict[str, Any],
        fallback: dict[str, Any] | None,
    ) -> dict[str, Any]:
        primary_payload = dict(primary or {})
        fallback_payload = dict(fallback or {})
        if not fallback_payload:
            return primary_payload

        primary_selected = dict(primary_payload.get("selected_trial") or {})
        primary_lineage = dict(primary_payload.get("lineage_audit") or {})
        fallback_selected = dict(fallback_payload.get("selected_trial") or {})
        fallback_lineage = dict(fallback_payload.get("lineage_audit") or {})
        fallback_trial_run_id = str(fallback_selected.get("trial_run_id") or "")
        primary_trial_run_id = str(primary_selected.get("trial_run_id") or "")
        primary_lineage_reason = str(primary_lineage.get("reason", ""))
        primary_reason = str(primary_payload.get("reason", ""))
        primary_writer_source = str(primary_selected.get("writer_source") or primary_lineage.get("selected_trial_writer_source") or "")
        primary_selection_rule = str(
            primary_selected.get("selection_rule") or primary_lineage.get("selected_trial_selection_rule") or ""
        )
        fallback_writer_source = str(
            fallback_selected.get("writer_source") or fallback_lineage.get("selected_trial_writer_source") or ""
        )
        fallback_selection_rule = str(
            fallback_selected.get("selection_rule") or fallback_lineage.get("selected_trial_selection_rule") or ""
        )
        primary_from_runtime_proxy = (
            self._safe_bool(primary_lineage.get("selected_trial_from_runtime_proxy", False))
            or primary_writer_source == "runtime_validation_proxy_v1"
            or primary_selection_rule.startswith("runtime_validation_proxy")
        )
        fallback_from_true_threshold = (
            self._safe_bool(fallback_lineage.get("selected_trial_from_true_threshold", False))
            or fallback_writer_source == "true_threshold_sweep_runner_v1"
            or fallback_selection_rule.startswith("true_threshold_sweep")
        )
        apply_fallback = (
            bool(fallback_trial_run_id)
            and (
                (
                    not primary_trial_run_id
                    and (
                        primary_lineage_reason
                        in {
                            "selected_trial_missing",
                            "selected_trial_lineage_unresolved",
                            "selection_rule_counts_missing",
                            "",
                        }
                        or primary_reason in {"pbo_dsr_trial_runs_missing", ""}
                        or not self._safe_bool(primary_payload.get("available", False))
                    )
                )
                or (
                    bool(primary_trial_run_id)
                    and primary_from_runtime_proxy
                    and fallback_from_true_threshold
                    and str(fallback_lineage.get("audit_status", "")) == "PASS"
                )
            )
        )

        merged = dict(primary_payload)
        merged["global_lineage_fallback"] = {
            "available": self._safe_bool(fallback_payload.get("available", False)),
            "metrics_complete": self._safe_bool(fallback_payload.get("metrics_complete", False)),
            "reason": fallback_payload.get("reason", "not_available"),
            "validation_scope": dict(fallback_payload.get("validation_scope") or {}),
            "selected_trial": fallback_selected,
            "lineage_audit": fallback_lineage,
            "selection_universe_summary": dict(fallback_payload.get("selection_universe_summary") or {}),
        }
        merged["selected_trial_fallback_applied"] = apply_fallback
        if not apply_fallback:
            return merged

        merged["symbol_scope_selected_trial"] = primary_selected
        merged["symbol_scope_lineage_audit"] = primary_lineage
        merged["selected_trial"] = fallback_selected
        merged["lineage_audit"] = fallback_lineage
        merged["selection_universe_summary"] = dict(fallback_payload.get("selection_universe_summary") or {})
        deployment_recommendation = dict(merged.get("deployment_recommendation") or {})
        deployment_recommendation["selected_trial_scope"] = "family_global_fallback"
        deployment_recommendation["selected_trial_scope_reason"] = (
            "symbol_scope_runtime_proxy_replaced_by_global_true_threshold"
            if primary_trial_run_id and primary_from_runtime_proxy and fallback_from_true_threshold
            else "symbol_scope_selected_trial_missing"
        )
        merged["deployment_recommendation"] = deployment_recommendation
        return merged

    def _refresh_stress_replay_outputs_after_worker(
        self,
        *,
        symbol: str,
        version: str,
        stress_validation: dict[str, Any],
        stress_replay_lineage: dict[str, Any],
        pbo_dsr_metrics: dict[str, Any],
        write_report: bool,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
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
            pbo_dsr_metrics=pbo_dsr_metrics,
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
        return (
            stress_validation,
            stress_replay_output_artifacts,
            stress_replay_assessment,
            stress_replay_runner_contract,
        )

    def _global_lineage_stress_replay_stack(
        self,
        *,
        version: str,
        write_report: bool,
        run_prototype_worker: bool,
        pbo_dsr_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        symbol = self._global_lineage_validation_symbol()
        plans = self._global_lineage_validation_plans(version=version)
        lineage_service = StrategyV2StressReplayLineageService(
            self.settings,
            plan_repo=SimpleNamespace(list_recent=lambda symbol, days=180: plans),
            fill_repo=self.fill_repo,
            candle_repo=self.candle_repo,
        )
        stress_validation = self.strategy_v2_stress_validation.generate(
            symbol=symbol,
            version=version,
            plans=plans,
            write_report=write_report,
        )
        stress_replay_lineage = lineage_service.generate(
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
            pbo_dsr_metrics=pbo_dsr_metrics,
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
            trade_rows=lineage_service.trade_rows(symbol=symbol, version=version),
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
            if self._safe_bool((stress_replay_prototype_worker or {}).get("executed", False)):
                (
                    stress_validation,
                    stress_replay_output_artifacts,
                    stress_replay_assessment,
                    stress_replay_runner_contract,
                ) = self._refresh_stress_replay_outputs_after_worker(
                    symbol=symbol,
                    version=version,
                    stress_validation=stress_validation,
                    stress_replay_lineage=stress_replay_lineage,
                    pbo_dsr_metrics=pbo_dsr_metrics,
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
            "pbo_dsr_metrics": pbo_dsr_metrics,
        }

    def _merge_global_lineage_stress_replay_fallback(
        self,
        *,
        primary_stack: dict[str, Any],
        fallback_stack: dict[str, Any] | None,
    ) -> dict[str, Any]:
        merged = dict(primary_stack or {})
        fallback = dict(fallback_stack or {})
        if not fallback:
            return merged

        primary_assessment = dict(merged.get("stress_replay_assessment") or {})
        fallback_assessment = dict(fallback.get("stress_replay_assessment") or {})
        primary_recommendation = dict(primary_assessment.get("deployment_recommendation") or {})
        fallback_recommendation = dict(fallback_assessment.get("deployment_recommendation") or {})
        primary_cross = dict(primary_recommendation.get("approval_cross_display") or {})
        fallback_cross = dict(fallback_recommendation.get("approval_cross_display") or {})
        fallback_source = str(fallback_cross.get("replay_derived_worst_scenario_source", ""))
        apply_fallback = (
            str(primary_cross.get("approval_warning_code", "")) == "replay_backed_worst_scenario_missing"
            and fallback_source == "replay_output"
        )

        fallback_summary = {
            "available": self._safe_bool(fallback_assessment.get("available", False)),
            "reason": fallback_assessment.get("reason", "not_available"),
            "deployment_recommendation": fallback_recommendation,
            "stress_replay_lineage": dict(fallback.get("stress_replay_lineage") or {}),
            "stress_replay_output_artifacts": dict(fallback.get("stress_replay_output_artifacts") or {}),
        }
        primary_assessment["global_lineage_fallback"] = fallback_summary
        primary_assessment["global_lineage_fallback_applied"] = apply_fallback
        if not apply_fallback:
            merged["stress_replay_assessment"] = primary_assessment
            return merged

        primary_assessment["symbol_scope_deployment_recommendation"] = primary_recommendation
        primary_assessment["deployment_recommendation"] = fallback_recommendation
        merged["stress_replay_assessment"] = primary_assessment
        current_artifacts_available = self._safe_bool(
            dict(merged.get("stress_replay_output_artifacts") or {}).get("available", False)
        )
        fallback_artifacts_available = self._safe_bool(
            dict(fallback.get("stress_replay_output_artifacts") or {}).get("available", False)
        )
        if not current_artifacts_available and fallback_artifacts_available:
            merged["stress_replay_output_artifacts"] = dict(fallback.get("stress_replay_output_artifacts") or {})
        return merged

    def _build_stress_replay_runtime_stack(
        self,
        *,
        symbol: str,
        version: str,
        plans: list | None = None,
        pbo_dsr_metrics: dict | None = None,
        write_report: bool = False,
        run_prototype_worker: bool = False,
        persist_runtime_validation_artifacts: bool = True,
    ) -> dict[str, dict]:
        recent_plans = plans if plans is not None else self.plan_repo.list_recent(symbol=symbol, days=180)
        runtime_pbo_dsr_metrics = pbo_dsr_metrics
        if runtime_pbo_dsr_metrics is None:
            self.strategy_v2_pbo_dsr_trial_writer.generate(
                symbol=symbol,
                version=version,
                plans=recent_plans,
                write_report=False,
                persist=persist_runtime_validation_artifacts,
            )
            self.strategy_v2_pbo_dsr_threshold_runner.generate(
                symbol=symbol,
                version=version,
                plans=recent_plans,
                write_report=False,
                persist=persist_runtime_validation_artifacts,
            )
            runtime_pbo_dsr_metrics = self.strategy_v2_pbo_dsr_metrics.generate(
                symbol=symbol,
                version=version,
                write_report=False,
                persist_snapshot=False,
            )
        global_lineage_pbo_dsr_metrics = self._global_lineage_pbo_dsr_metrics(
            version=version,
            write_report=False,
            persist_snapshot=False,
            persist_runtime_validation_artifacts=persist_runtime_validation_artifacts,
        )
        runtime_pbo_dsr_metrics = self._merge_global_lineage_pbo_fallback(
            primary=runtime_pbo_dsr_metrics or {},
            fallback=global_lineage_pbo_dsr_metrics,
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
            if self._safe_bool((stress_replay_prototype_worker or {}).get("executed", False)):
                (
                    stress_validation,
                    stress_replay_output_artifacts,
                    stress_replay_assessment,
                    stress_replay_runner_contract,
                ) = self._refresh_stress_replay_outputs_after_worker(
                    symbol=symbol,
                    version=version,
                    stress_validation=stress_validation,
                    stress_replay_lineage=stress_replay_lineage,
                    pbo_dsr_metrics=runtime_pbo_dsr_metrics or {},
                    write_report=write_report,
                )
        stack = {
            "stress_validation": stress_validation,
            "stress_replay_lineage": stress_replay_lineage,
            "stress_replay_assessment": stress_replay_assessment,
            "stress_replay_runner_contract": stress_replay_runner_contract,
            "stress_replay_lineage_writer": stress_replay_lineage_writer,
            "stress_replay_prototype_worker": stress_replay_prototype_worker or {},
            "stress_replay_output_artifacts": stress_replay_output_artifacts,
            "pbo_dsr_metrics": runtime_pbo_dsr_metrics or {},
        }
        global_lineage_replay_stack = self._global_lineage_stress_replay_stack(
            version=version,
            write_report=write_report,
            run_prototype_worker=run_prototype_worker,
            pbo_dsr_metrics=global_lineage_pbo_dsr_metrics,
        )
        return self._merge_global_lineage_stress_replay_fallback(
            primary_stack=stack,
            fallback_stack=global_lineage_replay_stack,
        )

    def refresh_symbol(self, symbol: str) -> dict:
        candles1 = self.market_data.recent_candles(symbol, "1m", limit=900)
        candles5 = self.market_data.recent_candles(symbol, "5m", limit=300)
        candles15 = self.market_data.recent_candles(symbol, "15m", limit=300)
        if len(candles5) < 60 or len(candles15) < 60:
            response = {
                "symbol": symbol,
                "updated": False,
                "reason": "insufficient_candles",
                "available_1m": len(candles1),
                "available_5m": len(candles5),
                "available_15m": len(candles15),
            }
            audit_error = self._commit_session_impulse_retest_runtime_audit(
                symbol=symbol,
                phase="refresh",
                status="insufficient_candles",
                decision_code="insufficient_candles",
                observed_ts=datetime.now(timezone.utc),
                payload=response,
            )
            if audit_error:
                response["runtime_audit_error"] = audit_error
            return response

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
        session_impulse_retest_active_thesis_clusters = self._session_impulse_retest_active_thesis_clusters(
            exposure_rows
        )
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
        micro_runtime_plans: list[Plan] = []
        if can_open:
            micro_plan = self._session_impulse_retest_runtime_plan(
                symbol=symbol,
                candles_1m=candles1,
                candles_5m=candles5,
                active_thesis_clusters=session_impulse_retest_active_thesis_clusters,
            )
            if micro_plan is not None:
                micro_runtime_plans.append(micro_plan)
        if can_open:
            if ranked_plans:
                plan_generation_diagnostics = {
                    "schema_version": "plan_generation_diagnostics_v1",
                    "symbol": symbol,
                    "generation_state": "generated",
                    "regime_profile": self.plan_generator.resolve_regime_label(context),
                    "transition_state": context.transition_state,
                    "transition_lock_reason": context.transition_lock_reason,
                    "active_zone_count": len(active_zones),
                    "generated_plan_count": len(ranked_plans) + len(micro_runtime_plans),
                }
            else:
                plan_generation_diagnostics = self.plan_generator.generation_diagnostics(
                    symbol=symbol,
                    zones=active_zones,
                    context=context,
                    candles_5m=candles5,
                    importance_calibration=feature_calibration,
                )
                plan_generation_diagnostics["generation_state"] = (
                    "micro_main_generated" if micro_runtime_plans else "no_fresh_candidates"
                )
                plan_generation_diagnostics["generated_plan_count"] = len(micro_runtime_plans)
        else:
            plan_generation_diagnostics = {
                "schema_version": "plan_generation_diagnostics_v1",
                "symbol": symbol,
                "generation_state": "skipped_by_gate",
                "gate_reason": gate_reason,
                "regime_profile": self.plan_generator.resolve_regime_label(context),
                "transition_state": context.transition_state,
                "transition_lock_reason": context.transition_lock_reason,
                "active_zone_count": len(active_zones),
                "generated_plan_count": 0,
            }
        self.plan_repo.upsert_many([x.plan for x in ranked_plans] + micro_runtime_plans)
        self.plan_repo.invalidate_expired()
        active_signal_plans = self.plan_repo.list_active_for_symbol(
            symbol=symbol,
            timeframe="5m",
            states=[PlanState.PLANNED.value, PlanState.ARMED.value],
            limit=max(20, self._max_candidate_plans_per_symbol() * 4),
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

        response = {
            "symbol": symbol,
            "updated": True,
            "zones": len(zones),
            "active_zone_count": len(active_zones),
            "plans": len(ranked_plans),
            "session_impulse_retest_generated_count": len(micro_runtime_plans),
            "session_impulse_retest_plan_ids": [str(plan.plan_id) for plan in micro_runtime_plans],
            "active_signal_plan_count": len(active_signal_plans),
            "plan_generation_diagnostics": plan_generation_diagnostics,
            "risk_state": gate_state.value,
            "gate_reason": gate_reason,
            "operating_lock": operating_lock.to_dict(),
            "regime_label": regime_label,
            "transition_score": round(context.transition_score, 4),
            "transition_state": context.transition_state,
            "transition_lock_reason": context.transition_lock_reason,
            "active_thesis_clusters": active_thesis_clusters,
            "session_impulse_retest_active_thesis_clusters": session_impulse_retest_active_thesis_clusters,
            "strategy_mode": getattr(self.settings.strategy_mode, "value", str(self.settings.strategy_mode)),
            "feature_calibration_available": self._safe_bool((feature_calibration or {}).get("available")),
            "feature_calibration_samples": int((feature_calibration or {}).get("matched_samples", 0)),
            "signal_alerts": signal_alerts,
        }
        family_enabled = self._safe_bool(self.settings.session_impulse_retest_enabled)
        refresh_status = (
            "family_disabled"
            if not family_enabled
            else (
                "signal_generated"
                if int(response.get("session_impulse_retest_generated_count", 0) or 0) > 0
                else (
                    "skipped_by_gate"
                    if not can_open
                    else "no_fresh_candidates"
                )
            )
        )
        decision_code = str(response.get("gate_reason") or "").strip()
        if refresh_status == "family_disabled":
            decision_code = "family_disabled"
        refresh_plan_ids = list(response.get("session_impulse_retest_plan_ids") or [])
        self.db.commit()
        audit_error = self._commit_session_impulse_retest_runtime_audit(
            symbol=symbol,
            phase="refresh",
            status=refresh_status,
            plan_id=refresh_plan_ids[0] if refresh_plan_ids else None,
            decision_code=decision_code,
            observed_ts=self._to_utc(candles5[-1].ts),
            payload=response,
        )
        if audit_error:
            response["runtime_audit_error"] = audit_error

        return response

    def recompute_learning(
        self,
        symbol: str,
        *,
        persist_runtime_validation_artifacts: bool = True,
        use_read_only_cache: bool = True,
    ) -> dict:
        return RuntimeValidationOrchestrator(self).recompute_learning(
            symbol,
            persist_runtime_validation_artifacts=persist_runtime_validation_artifacts,
            use_read_only_cache=use_read_only_cache,
        )

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
        fill_payload = _safe_dict(fill.payload if fill is not None else None)
        response = asdict(result)
        response["exit_reason"] = fill_payload.get("exit_reason") or result.exit_reason
        plan = self.plan_repo.get(result.plan_id) if result.plan_id else None
        if result.duplicate:
            self.db.commit()
            return response

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
                next_state = (
                    OrderLifecycleState.PARTIALLY_FILLED
                    if self._safe_bool(fill_payload.get("partial"))
                    else OrderLifecycleState.FILLED
                )
                self.submission_repo.transition(
                    submission,
                    state=next_state.value,
                    submit_status=next_state.value,
                    message="Execution fill linked to submission lifecycle.",
                    raw={**_safe_dict(submission.raw), "last_fill_id": fill_id},
                )

        self.db.commit()
        return response

    def scanner_top(self, universe: str, limit: int, *, fast: bool = False) -> list[dict]:
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
            symbols=self._runtime_candidate_symbols(
                symbols=symbols,
                risk_state=gate_state,
                limit=0 if bool(fast) else limit,
            )
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

    def portfolio_budget_report(
        self,
        *,
        universe: str,
        limit: int,
        write_report: bool = True,
        outcome_symbol_limit: int | None = None,
    ) -> dict:
        symbols = self.market_data.default_universe(universe)
        if not symbols and universe == self.settings.universe_name:
            symbols = self.market_data.refresh_universe(limit=30)

        gate_state = RiskGateState.OPEN
        gate_reason = "default_open"
        operating_lock = self._operating_lock_snapshot()
        if symbols:
            _, gate_state, gate_reason, operating_lock = self._gate_context_for_symbol(symbol=symbols[0])
        outcome_inputs_by_symbol = self._outcome_inputs_for_symbols(
            symbols=self._runtime_candidate_symbols(
                symbols=symbols,
                risk_state=gate_state,
                limit=outcome_symbol_limit,
            )
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
            limit=max(20, self._maybe_int(self.settings.alpha_research_max_candidates) or 20),
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
        plan_ids = list(refresh.get("session_impulse_retest_plan_ids") or [])
        auto_route = (
            self.auto_route_session_impulse_retest_plans(symbol=symbol, plan_ids=plan_ids)
            if plan_ids
            else self.auto_route_symbol(symbol=symbol)
        )
        return {
            "symbol": symbol,
            "backfill": summary,
            "refresh": refresh,
            "auto_route": auto_route,
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
        symbols = self.runtime_sync_symbols(limit_symbols=limit_symbols)
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
        miss_detector = self.detect_session_impulse_retest_recent_misses(write_report=False)
        miss_alert = self._maybe_emit_session_impulse_retest_miss_alert(report=miss_detector)
        self.db.commit()

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
            "session_impulse_retest_miss_detector": miss_detector,
            "session_impulse_retest_miss_alert": miss_alert,
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
        plan_ids = list(refresh.get("session_impulse_retest_plan_ids") or [])
        normalized_symbol = str(symbol or "").upper()
        if self._ws_stream_auto_route_active():
            requested_mode = self._auto_route_requested_mode()
            auto_route = {
                "symbol": normalized_symbol,
                "enabled": False,
                "requested_mode": requested_mode.value if requested_mode is not None else "",
                "reason": "ws_stream_active_route_suppressed",
                "families_considered": self._auto_route_live_families_considered(requested_mode),
                "plans_considered": len(plan_ids),
                "intents_created": 0,
                "submit_calls": 0,
                "results": [],
            }
            self._finalize_auto_route_audit(
                symbol=normalized_symbol,
                observed_ts=datetime.now(timezone.utc),
                response=auto_route,
            )
        else:
            auto_route = (
                self.auto_route_session_impulse_retest_plans(symbol=symbol, plan_ids=plan_ids)
                if plan_ids
                else self.auto_route_symbol(symbol=symbol)
            )
        return {
            "symbol": symbol,
            "status": "ok",
            "backfill": backfill,
            "refresh": refresh,
            "auto_route": auto_route,
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
        intervals: list[str] | tuple[str, ...] = ("1m", "5m", "15m"),
        refresh_on_final: bool = True,
        max_messages: int | None = None,
        progress_callback: Any | None = None,
    ) -> dict:
        stream = RuntimeKlineStreamService(
            db=self.db,
            market_data=self.market_data,
            settings=self.settings,
            refresh_symbol=self.refresh_symbol,
            auto_route_symbol=self.auto_route_symbol,
            auto_route_session_impulse_retest_plans=self.auto_route_session_impulse_retest_plans,
        )
        return await stream.stream(
            symbols=symbols,
            intervals=intervals,
            refresh_on_final=refresh_on_final,
            max_messages=max_messages,
            progress_callback=progress_callback,
        )

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
        validation_payload = None
        if not write_report:
            validation_payload = self._load_cached_validation_payload(symbol)
        if validation_payload is None:
            if not write_report:
                validation_payload = (
                    self._load_stale_conservative_validation_payload(symbol)
                    or validation_report_cache_miss_payload(symbol)
                )
            else:
                validation_payload = self.recompute_learning(symbol, persist_runtime_validation_artifacts=False)
        alert_metrics = self.alert_metrics_report(days=days, write_report=False)
        outbox_status = self.outbox_status()
        strategy_metrics = self.metrics(symbol=symbol, version=self.settings.strategy_version)
        portfolio_budget = self.portfolio_budget_report(
            universe=universe,
            limit=limit,
            write_report=False,
            outcome_symbol_limit=0 if not write_report else None,
        )
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

    def execution_quality_report(
        self,
        *,
        symbol: str,
        days: int,
        write_report: bool = True,
        strategy_families: list[str] | None = None,
        entry_models: list[str] | None = None,
        directions: list[str] | None = None,
    ) -> dict:
        return self.execution_quality.generate(
            symbol=symbol,
            days=days,
            write_report=write_report,
            strategy_families=strategy_families,
            entry_models=entry_models,
            directions=directions,
        )

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
        payload = self._merge_global_lineage_pbo_fallback(
            primary=payload,
            fallback=self._global_lineage_pbo_dsr_metrics(
                version=active_version,
                write_report=write_report,
                persist_snapshot=True,
                persist_runtime_validation_artifacts=True,
            ),
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
            persist_runtime_validation_artifacts=False,
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
            persist_runtime_validation_artifacts=False,
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
            persist_runtime_validation_artifacts=False,
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
            persist_runtime_validation_artifacts=False,
        )
        return self.strategy_v2_stress_replay_prototype_worker.generate(
            symbol=symbol,
            version=active_version,
            stress_validation=stack["stress_validation"],
            stress_replay_lineage_writer=stack["stress_replay_lineage_writer"],
            stress_replay_runner_contract=stack["stress_replay_runner_contract"],
            write_report=write_report,
        )
