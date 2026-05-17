from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import (
    ApprovalState,
    ExecutionMode,
    LockScopeType,
    LockSeverity,
    OrderLifecycleState,
    ReconciliationSeverity,
    SubmitDecision,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TargetLeg(ORMModel):
    label: str
    price: float
    size_fraction: float = 0.0


class ExpectedSummary(ORMModel):
    expected_win_prob: float = 0.0
    expected_ev_r: float = 0.0
    expected_source: str = ""
    expected_summary: str = ""


class ContextSnapshot(ORMModel):
    regime: str = "range"
    risk_label: str = "normal"
    transition_state: str = "none"
    session_guidance: str = "unknown"
    portfolio_headroom_state: str = "open"
    deployment_go_no_go: str = ""
    block_reason: str = ""
    block_reason_message: str = ""


class ExecutablePlan(ORMModel):
    plan_id: str
    symbol: str
    tf: str
    strategy_version: str
    strategy_family: str
    strategy_mode: str
    execution_mode: ExecutionMode
    thesis_fingerprint: dict[str, Any] | None = None
    thesis_cluster_id: str = ""
    thesis_primary_symbol: str = ""
    direction: str
    setup_grade: str = ""
    setup_score: float = 0.0
    entry_model: str
    entry_type: str
    entry_semantics: str
    entry_trigger_price: float | None = None
    entry_limit_price: float | None = None
    entry_timeout_seconds: int = 0
    cancel_if_not_filled: bool = True
    stop_price: float
    tp_targets: list[TargetLeg] = Field(default_factory=list)
    recommended_risk_r: float = 0.0
    max_position_notional: float = 0.0
    expected_fee_bps: float = 0.0
    max_slippage_bps: float = 0.0
    valid_from: datetime
    valid_until: datetime
    kill_if_transition_lock: bool = True
    kill_if_regime_changes: bool = True
    expected_summary: ExpectedSummary
    context_snapshot: ContextSnapshot
    mirror_plan_note: str = ""
    strategy_scorecard_buckets: dict[str, Any] = Field(default_factory=dict)
    strategy_scorecard_raw_components: dict[str, Any] = Field(default_factory=dict)


class ApprovalReason(ORMModel):
    code: str
    message: str
    blocking: bool = False
    submit_blocking: bool = False
    blocking_scope: str = "none"


class RolloutPolicySnapshot(ORMModel):
    strategy_family: str
    live_enabled: bool = False
    max_execution_mode: ExecutionMode = ExecutionMode.SHADOW
    max_risk_r: float = 0.0
    allowed_sessions: list[str] = Field(default_factory=list)
    min_quality_score: float = 0.0


class ExecutionPlanPreviewRequest(ORMModel):
    plan_id: str = Field(min_length=4, max_length=50)


class ExecutionApprovalRequest(ORMModel):
    plan_id: str = Field(min_length=4, max_length=50)


class ExecutionApproval(ORMModel):
    plan_id: str
    symbol: str
    approval_state: ApprovalState
    allowed_execution_mode: ExecutionMode
    strategy_mode: str = ""
    execution_mode: ExecutionMode
    deployment_go_no_go: str = ""
    deployment_code: str = ""
    deployment_message: str = ""
    playbook_go_no_go: str = ""
    playbook_code: str = ""
    playbook_action: str = ""
    playbook_message: str = ""
    approval_reasons: list[ApprovalReason] = Field(default_factory=list)
    approved_at: datetime
    expires_at: datetime
    validation_grade: str = ""
    validation_recommendation: str = ""
    risk_state: str = ""
    risk_reason: str = ""
    operating_lock: dict[str, Any] = Field(default_factory=dict)
    session_guidance: dict[str, Any] = Field(default_factory=dict)
    block_reason: str = ""
    block_reason_message: str = ""
    paper_lineage_override_applied: bool = False
    paper_lineage_override_reason: str = ""
    paper_lineage_override_source: str = ""
    top_candidate: bool = False
    auto_trading_enabled: bool = False
    rollout_policy: RolloutPolicySnapshot
    safety_state: dict[str, Any] = Field(default_factory=dict)
    outcome_approval_penalty: dict[str, Any] | None = None


class QualitySnapshot(ORMModel):
    validation_grade: str = ""
    validation_recommendation: str = ""
    risk_state: str = ""
    risk_reason: str = ""
    setup_grade: str = ""
    setup_score: float = 0.0
    recommended_risk_r: float = 0.0
    expected_ev_r: float = 0.0


class OrderIntentCreateRequest(ORMModel):
    plan_id: str = Field(min_length=4, max_length=50)
    execution_mode: ExecutionMode
    paper_lineage_override: bool = False


class OrderIntentResponse(ORMModel):
    intent_id: str
    plan_id: str
    symbol: str
    strategy_family: str
    execution_mode: ExecutionMode
    approval_state: ApprovalState
    submit_decision: SubmitDecision
    decision_reason_code: str
    decision_reason_message: str
    allowed_execution_mode: ExecutionMode | None = None
    deployment_go_no_go: str = ""
    deployment_code: str = ""
    playbook_go_no_go: str = ""
    playbook_code: str = ""
    playbook_action: str = ""
    playbook_message: str = ""
    source_of_truth_hint: str = ""
    paper_lineage_override_applied: bool = False
    paper_lineage_override_reason: str = ""
    paper_lineage_override_source: str = ""
    self_heal_summary: dict[str, Any] = Field(default_factory=dict)
    thesis_fingerprint: dict[str, Any] | None = None
    dedupe_result: dict[str, Any] = Field(default_factory=dict)
    session_guidance: dict[str, Any] = Field(default_factory=dict)
    quality_snapshot: QualitySnapshot
    approval: ExecutionApproval
    created_at: datetime


class ExecutionSubmitRequest(ORMModel):
    intent_id: str = Field(min_length=8, max_length=80)
    live: bool = False
    paper_scenario: str | None = Field(default=None, max_length=40)


class OrderSubmissionResponse(ORMModel):
    submission_id: str
    intent_id: str
    symbol: str
    execution_mode: ExecutionMode
    state: OrderLifecycleState
    submit_status: str
    message: str
    client_order_id: str
    exchange_order_id: str | None = None
    adapter: str
    requested_live: bool = False
    attachments: dict[str, Any] = Field(default_factory=dict)
    fill_results: list[dict[str, Any]] = Field(default_factory=list)
    submitted_at: datetime
    acknowledged_at: datetime | None = None
    cancelled_at: datetime | None = None
    idempotent_reuse: bool = False


class ReconciliationRequest(ORMModel):
    symbol: str = Field(min_length=3, max_length=30)


class ReconciliationMismatch(ORMModel):
    mismatch_type: str
    severity: ReconciliationSeverity
    message: str
    local_snapshot: dict[str, Any] = Field(default_factory=dict)
    exchange_snapshot: dict[str, Any] = Field(default_factory=dict)


class ReconciliationResponse(ORMModel):
    symbol: str
    mismatches: list[ReconciliationMismatch] = Field(default_factory=list)
    healthy: bool = True
    highest_severity: ReconciliationSeverity = ReconciliationSeverity.INFO
    lock_required: bool = False
    auto_resolve_requested: bool = False
    auto_resolve_applied: bool = False
    apply_lock_requested: bool = False
    events_recorded: int = 0
    generated_at: datetime


class SafetyControlRequest(ORMModel):
    active: bool = True
    reason_message: str = ""
    unlock_at: datetime | None = None
    updated_by: str | None = Field(default=None, max_length=80)


class SafetyLockSnapshot(ORMModel):
    lock_id: str
    scope_type: LockScopeType
    scope_key: str | None = None
    severity: LockSeverity
    reason_code: str
    reason_message: str
    active: bool = True
    allow_closes: bool = True
    lock_metadata: dict[str, Any] = Field(default_factory=dict)
    unlock_at: datetime | None = None
    released_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SafetyStateResponse(ORMModel):
    symbol: str | None = None
    strategy_family: str | None = None
    session_name: str | None = None
    new_entry_allowed: bool = True
    blocking_reason_code: str = ""
    blocking_reason_message: str = ""
    kill_switch_active: bool = False
    close_only_active: bool = False
    config_close_only_active: bool = False
    transition_edge_variant: dict[str, Any] = Field(default_factory=dict)
    session_impulse_retest_universe_policy: dict[str, Any] = Field(default_factory=dict)
    session_impulse_retest_rollout_readiness: dict[str, Any] = Field(default_factory=dict)
    live_account_protection: dict[str, Any] = Field(default_factory=dict)
    matching_locks: list[SafetyLockSnapshot] = Field(default_factory=list)
    active_locks: list[SafetyLockSnapshot] = Field(default_factory=list)
    rollout_policies: list[RolloutPolicySnapshot] = Field(default_factory=list)


class KillConditionAutomationApplyRequest(ORMModel):
    symbol: str | None = Field(default=None, max_length=30)
    universe: str = Field(default="usdt_reliable_balanced_31", max_length=80)
    family: str | None = Field(default=None, max_length=50)
    session_name: str | None = Field(default=None, max_length=50)
    days: int = Field(default=30, ge=1, le=365)
    portfolio_limit: int = Field(default=10, ge=1, le=50)
    intent_limit: int = Field(default=10, ge=1, le=50)
    reconcile_limit: int = Field(default=10, ge=1, le=50)
    dry_run: bool = True
    allow_live_write: bool = False
    arm_token: str | None = Field(default=None, max_length=250)
    updated_by: str | None = Field(default=None, max_length=80)
    unlock_at: datetime | None = None


class KillConditionAutomationApplyResponse(ORMModel):
    generated_at: datetime
    symbol: str | None = None
    universe: str = ""
    dry_run: bool = True
    allow_live_write: bool = False
    arm_valid: bool = False
    explicit_arm_required: bool = True
    eligible_for_live_write: bool = False
    kill_condition_state: str = "observe_only"
    automation_bias: str = "observe_only"
    trigger_axis: str = ""
    effective_write_scope: str = "none"
    action_target: str = "none"
    action_reason_code: str = ""
    action_reason_message: str = ""
    action_applied: bool = False
    kill_condition_automation_summary: dict[str, Any] = Field(default_factory=dict)
    safety_state_before: dict[str, Any] = Field(default_factory=dict)
    safety_state_after: dict[str, Any] = Field(default_factory=dict)


class RolloutPolicyUpdateRequest(ORMModel):
    family: str = Field(min_length=3, max_length=50)
    live_enabled: bool = False
    max_execution_mode: ExecutionMode
    max_risk_r: float = 0.0
    allowed_sessions: list[str] = Field(default_factory=list)
    min_quality_score: float = 0.0
    updated_by: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=250)


class OperatorIntentSummary(ORMModel):
    intent_id: str
    plan_id: str
    symbol: str
    strategy_family: str
    entry_type: str = ""
    entry_model: str = ""
    execution_mode: ExecutionMode
    approval_state: ApprovalState
    submit_decision: SubmitDecision
    decision_reason_code: str
    decision_reason_message: str
    allowed_execution_mode: ExecutionMode | None = None
    deployment_go_no_go: str = ""
    deployment_code: str = ""
    playbook_go_no_go: str = ""
    playbook_code: str = ""
    playbook_action: str = ""
    outcome_approval_penalty: dict[str, Any] | None = None
    thesis_cluster_id: str = ""
    created_at: datetime


class OperatorOrderSummary(ORMModel):
    submission_id: str
    intent_id: str
    plan_id: str
    symbol: str
    state: OrderLifecycleState
    submit_status: str
    message: str
    adapter: str
    execution_mode: ExecutionMode
    client_order_id: str
    exchange_order_id: str | None = None
    requested_live: bool = False
    submitted_at: datetime
    acknowledged_at: datetime | None = None
    cancelled_at: datetime | None = None


class OperatorPositionSummary(ORMModel):
    position_key: str
    symbol: str
    position_side: str
    position_amt: float = 0.0
    entry_price: float = 0.0
    mark_price: float = 0.0
    unrealized_pnl: float = 0.0
    notional: float = 0.0
    leverage: int = 0
    margin_type: str = ""
    update_ts: datetime


class OperatorReconciliationSummary(ORMModel):
    event_id: str
    symbol: str
    mismatch_type: str
    severity: ReconciliationSeverity
    message: str
    lock_required: bool = False
    lock_applied: bool = False
    lock_scope: str | None = None
    created_at: datetime


class ExecutionOperatorDashboardResponse(ORMModel):
    generated_at: datetime
    symbol: str | None = None
    report_window_days: int = 7
    execution_mode: ExecutionMode
    auto_trading_enabled: bool = False
    source_of_truth_hint: str = ""
    new_entries_allowed: bool = False
    blocking_reason_code: str = ""
    blocking_reason_message: str = ""
    deployment_go_no_go: str = ""
    deployment_code: str = ""
    deployment_message: str = ""
    playbook_go_no_go: str = ""
    playbook_code: str = ""
    playbook_action: str = ""
    playbook_message: str = ""
    approval_strip_summary: dict[str, Any] | None = None
    kill_switch_active: bool = False
    close_only_active: bool = False
    config_close_only_active: bool = False
    active_locks: list[SafetyLockSnapshot] = Field(default_factory=list)
    matching_locks: list[SafetyLockSnapshot] = Field(default_factory=list)
    rollout_policies: list[RolloutPolicySnapshot] = Field(default_factory=list)
    recent_intent_count: int = 0
    recent_intents: list[OperatorIntentSummary] = Field(default_factory=list)
    open_order_count: int = 0
    open_orders: list[OperatorOrderSummary] = Field(default_factory=list)
    open_position_count: int = 0
    open_positions: list[OperatorPositionSummary] = Field(default_factory=list)
    recent_reconciliation_count: int = 0
    recent_reconciliation_summary: dict[str, Any] = Field(default_factory=dict)
    recent_reconciliation_events: list[OperatorReconciliationSummary] = Field(default_factory=list)
    transition_edge_variant: dict[str, Any] | None = None
    session_impulse_retest_shadow: dict[str, Any] | None = None
    session_impulse_retest_universe_policy: dict[str, Any] | None = None
    session_impulse_retest_rollout_readiness: dict[str, Any] | None = None
    live_account_protection: dict[str, Any] | None = None
    portfolio_summary: dict[str, Any] = Field(default_factory=dict)
    active_contract: dict[str, Any] | None = None
    signal_funnel: dict[str, Any] = Field(default_factory=dict)
    alert_summary: dict[str, Any] = Field(default_factory=dict)
    execution_quality_summary: dict[str, Any] | None = None
