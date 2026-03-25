from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import (
    ApprovalState,
    EntryModel,
    ExecutionFillStage,
    ExecutionMode,
    ExitReason,
    PlanState,
    RiskGateState,
    StrategyMode,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CandleIn(ORMModel):
    symbol: str
    timeframe: str
    ts: datetime
    o: float
    h: float
    l: float
    c: float
    v: float
    source: str = "binance"
    is_final: bool = True


class AlertSubscribeIn(ORMModel):
    symbol: str
    channel: str = Field(pattern="^(telegram|discord|push)$")
    type: str = Field(pattern="^(near|touch|confirm|entry|tp|sl|partial_exit|closed)$")
    plan_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AlertTestIn(ORMModel):
    channel: str = Field(pattern="^(telegram|discord|push|system)$")
    symbol: str = "SYSTEM"
    message: str = Field(min_length=3, max_length=500)
    payload: dict[str, Any] = Field(default_factory=dict)


class TVWebhookIn(ORMModel):
    event: str = Field(pattern="^(near|touch|confirm)$")
    symbol: str
    price: float
    ts: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class ZoneOut(ORMModel):
    zone_id: str
    symbol: str
    timeframe: str
    type: str
    low: float
    high: float
    mid: float
    width_atr: float
    dir_bias: str
    created_ts: datetime
    last_touched_ts: datetime | None
    touch_count: int
    base_strength: float
    quality: float
    state: str
    stats: dict[str, Any]


class PlanOut(ORMModel):
    plan_id: str
    zone_id: str
    symbol: str
    direction: str
    strategy_family: str = "legacy_zone_plan"
    strategy_grade: str | None = None
    entry_model: EntryModel
    state: PlanState
    entry_price: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    split: dict[str, float]
    rr_min: float
    rr_base: float
    rr_opt: float
    ev: float
    cost_est: float
    confidence: float
    expected_win_prob: float = 0.0
    expected_ev_r: float = 0.0
    expected_tp1_prob: float = 0.0
    expected_tp2_prob: float = 0.0
    expected_tp3_prob: float = 0.0
    expected_ev_at_recommended_size_r: float = 0.0
    expected_summary: str = ""
    validity: dict[str, Any]
    valid_from: datetime
    valid_until: datetime
    strategy_version: str


class ScannerItemOut(ORMModel):
    symbol: str
    plan_id: str
    zone_id: str
    direction: str
    strategy_mode: StrategyMode = StrategyMode.A_ONLY
    deployment_go_no_go: str = "GO"
    deployment_code: str = "go_runtime_gate_open"
    deployment_message: str = "GO: runtime gate is open for candidate review."
    risk_reason: str = "normal"
    operating_lock: dict[str, Any] = Field(default_factory=dict)
    session_guidance: dict[str, Any] | None = None
    session_penalty: float = 0.0
    strategy_family: str = "legacy_zone_plan"
    strategy_cluster: str | None = None
    strategy_cluster_status: str | None = None
    multi_strategy_overlay: dict[str, Any] | None = None
    b_continuation_activation: dict[str, Any] | None = None
    strategy_cluster_balance: dict[str, Any] | None = None
    strategy_grade: str | None = None
    strategy_family_reason: str | None = None
    strategy_scorecard: dict[str, Any] | None = None
    strategy_scorecard_buckets: dict[str, Any] = Field(default_factory=dict)
    strategy_scorecard_raw_components: dict[str, Any] = Field(default_factory=dict)
    reaction_evidence: dict[str, Any] | None = None
    location_reference: dict[str, Any] | None = None
    session_liquidity_reference: dict[str, Any] | None = None
    strategy_sizing: dict[str, Any] | None = None
    recommended_risk_r: float = 0.0
    expected_win_prob: float = 0.0
    expected_ev_r: float = 0.0
    expected_tp1_prob: float = 0.0
    expected_tp2_prob: float = 0.0
    expected_tp3_prob: float = 0.0
    expected_ev_at_recommended_size_r: float = 0.0
    expected_summary: str = ""
    entry_condition: str = ""
    why_now: str = ""
    operator_status: str = "none"
    block_reason: str | None = None
    block_reason_message: str | None = None
    entry_model: EntryModel
    regime: str = "range"
    final_rank_score: float
    ev: float
    rr_base: float
    friction_penalty: float
    portfolio_penalty: float = 0.0
    portfolio_high_corr_count: int = 0
    risk_budget_score: float = 100.0
    portfolio_volatility: float = 0.0
    portfolio_total_cap: int = 0
    portfolio_directional_cap: int = 0
    portfolio_cluster_cap: int = 0
    thesis_fingerprint: dict[str, Any] | None = None
    thesis_cluster_id: str | None = None
    thesis_cluster_size: int = 1
    thesis_primary_symbol: str | None = None
    thesis_rejected_reason: str | None = None
    thesis_active_cluster_count: int = 0


class IndicatorContextOut(ORMModel):
    last_price: float = 0.0
    atr5: float = 0.0
    atr15: float = 0.0
    regime_label: str = "range"
    regime_score: float = 0.0
    sdir: float = 0.0
    sevt: float = 0.0
    f: float = 0.0
    v: float = 0.0
    a: float = 0.0
    vz: float = 0.0
    az: float = 0.0
    jump_rate_5m: float = 0.0
    friction_5m: float = 0.0
    transition_score: float = 0.0
    transition_state: str = "none"
    transition_lock_reason: str | None = None


class OperatorSummaryOut(ORMModel):
    trade_now_status: Literal["NO_CANDIDATE", "GO", "MANUAL_REVIEW", "NO_GO"]
    can_trade_now: bool = False
    active_family: str | None = None
    family_reason: str | None = None
    why_now: str = ""
    why_allowed_or_blocked: str = ""
    top_plan_id: str | None = None
    deployment_go_no_go: str = "NO_GO"
    deployment_code: str = "no_active_candidate"
    deployment_message: str = "No active candidate for this symbol."
    strategy_mode: str | None = None
    risk_reason: str = "normal"
    operating_lock: dict[str, Any] = Field(default_factory=dict)
    session_guidance: dict[str, Any] = Field(default_factory=dict)
    block_reason: str | None = None
    block_reason_message: str | None = None
    thesis_cluster_id: str | None = None
    thesis_primary_symbol: str | None = None
    authority_source: str = "scanner_runtime_portfolio_gate"


class IndicatorZoneOut(ORMModel):
    zone_id: str
    type: str
    dir_bias: str
    low: float
    high: float
    mid: float
    width_atr: float
    quality: float
    base_strength: float
    state: str
    touch_count: int
    distance_atr: float


class IndicatorPlanOut(ORMModel):
    plan_id: str
    direction: str
    entry_model: EntryModel
    state: PlanState
    strategy_family: str = "legacy_zone_plan"
    strategy_grade: str | None = None
    entry_condition: str = ""
    strategy_family_reason: str | None = None
    why_now: str = ""
    strategy_scorecard_buckets: dict[str, Any] = Field(default_factory=dict)
    strategy_scorecard_raw_components: dict[str, Any] = Field(default_factory=dict)
    operator_status: str = "none"
    block_reason: str | None = None
    block_reason_message: str | None = None
    entry_price: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    rr_base: float
    rr_opt: float
    ev: float
    confluence_score: float = 0.0
    recommended_risk_r: float = 0.0
    expected_win_prob: float = 0.0
    expected_ev_r: float = 0.0
    expected_tp1_prob: float = 0.0
    expected_tp2_prob: float = 0.0
    expected_tp3_prob: float = 0.0
    expected_ev_at_recommended_size_r: float = 0.0
    expected_summary: str = ""
    distance_to_entry_atr: float = 0.0


class IndicatorSummaryOut(ORMModel):
    available: bool
    reason: str
    symbol: str
    generated_at: str
    refresh: dict[str, Any] = Field(default_factory=dict)
    headline: str = ""
    readable_lines: list[str] = Field(default_factory=list)
    bias_label: str = "unknown"
    momentum_label: str = "unknown"
    risk_label: str = "unknown"
    context: IndicatorContextOut | dict[str, Any] = Field(default_factory=dict)
    operator_summary: OperatorSummaryOut
    top_plan: IndicatorPlanOut | None = None
    top_zones: list[IndicatorZoneOut] = Field(default_factory=list)


class IndicatorChartOut(ORMModel):
    available: bool
    reason: str
    symbol: str
    generated_at: str
    refresh: dict[str, Any] = Field(default_factory=dict)
    price_panel: dict[str, Any] = Field(default_factory=dict)
    indicator_panel: dict[str, Any] = Field(default_factory=dict)
    operator_summary: OperatorSummaryOut
    zones: list[IndicatorZoneOut] = Field(default_factory=list)
    plans: list[IndicatorPlanOut] = Field(default_factory=list)
    annotations: list[str] = Field(default_factory=list)


class IndicatorPineOut(ORMModel):
    available: bool
    reason: str
    symbol: str
    generated_at: str
    refresh: dict[str, Any] = Field(default_factory=dict)
    overlay: dict[str, Any] = Field(default_factory=dict)
    panels: dict[str, Any] = Field(default_factory=dict)
    operator_summary: OperatorSummaryOut
    signals: list[dict[str, Any]] = Field(default_factory=list)
    zones: list[IndicatorZoneOut] = Field(default_factory=list)
    plans: list[IndicatorPlanOut] = Field(default_factory=list)


class ExecutionPlanIn(ORMModel):
    plan_id: str = Field(min_length=4, max_length=50)
    paper_lineage_override: bool = False


class TargetLeg(ORMModel):
    label: str
    price: float
    size_fraction: float = 0.0


class ExpectedSummary(ORMModel):
    expected_win_prob: float = 0.0
    expected_ev_r: float = 0.0
    expected_source: str = "runtime_candidate_overlay"
    expected_summary: str = ""


class ContextSnapshot(ORMModel):
    regime: str = "range"
    risk_label: str = "normal"
    transition_state: str = "none"
    session_guidance: str = "unknown"
    portfolio_headroom_state: str = "open"
    deployment_go_no_go: str = "MANUAL_REVIEW"
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
    thesis_cluster_id: str | None = None
    thesis_primary_symbol: str | None = None
    direction: str
    setup_grade: str
    setup_score: float
    entry_model: EntryModel
    entry_type: str
    entry_semantics: str = ""
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
    expected_summary: ExpectedSummary
    context_snapshot: ContextSnapshot
    kill_if_transition_lock: bool = True
    kill_if_regime_changes: bool = True
    mirror_plan_note: str = ""
    strategy_scorecard_buckets: dict[str, Any] = Field(default_factory=dict)
    strategy_scorecard_raw_components: dict[str, Any] = Field(default_factory=dict)


class ApprovalReason(ORMModel):
    code: str
    message: str
    source: str = "execution_approval"
    blocking: bool = False


class RolloutPolicyOut(ORMModel):
    strategy_family: str
    live_enabled: bool = False
    max_execution_mode: ExecutionMode = ExecutionMode.SHADOW
    max_risk_r: float = 0.0
    allowed_sessions: list[str] = Field(default_factory=list)
    min_quality_score: float = 0.0


class ExecutionApproval(ORMModel):
    plan_id: str
    symbol: str
    approval_state: ApprovalState
    allowed_execution_mode: ExecutionMode
    deployment_go_no_go: str
    deployment_code: str
    deployment_message: str
    playbook_go_no_go: str
    playbook_code: str
    playbook_action: str
    playbook_message: str
    approval_reasons: list[ApprovalReason] = Field(default_factory=list)
    approved_at: datetime | None = None
    expires_at: datetime | None = None
    strategy_mode: str
    execution_mode: ExecutionMode
    validation_grade: str = ""
    validation_recommendation: str = ""
    risk_state: str = ""
    risk_reason: str = ""
    operating_lock: dict[str, Any] = Field(default_factory=dict)
    session_guidance: dict[str, Any] = Field(default_factory=dict)
    block_reason: str | None = None
    block_reason_message: str | None = None
    top_candidate: bool = False
    auto_trading_enabled: bool = False
    rollout_policy: RolloutPolicyOut | None = None
    outcome_approval_penalty: dict[str, Any] | None = None


class PortfolioBudgetPositionOut(ORMModel):
    plan_id: str
    symbol: str
    direction: str
    state: PlanState
    entry_model: EntryModel
    regime: str = "range"
    exposure_kind: str
    ev: float
    rr_base: float
    strategy_version: str
    valid_until: datetime
    portfolio_volatility: float = 0.0
    portfolio_high_corr_count: int = 0
    recommended_risk_r: float = 0.0
    strategy_mode: StrategyMode = StrategyMode.A_ONLY
    thesis_cluster_id: str | None = None
    thesis_primary_symbol: str | None = None
    thesis_cluster_size: int = 1


class PortfolioBudgetCandidateOut(ORMModel):
    symbol: str
    plan_id: str
    zone_id: str
    direction: str
    strategy_mode: StrategyMode = StrategyMode.A_ONLY
    strategy_family: str = "legacy_zone_plan"
    strategy_cluster: str | None = None
    strategy_cluster_status: str | None = None
    multi_strategy_overlay: dict[str, Any] | None = None
    b_continuation_activation: dict[str, Any] | None = None
    strategy_cluster_balance: dict[str, Any] | None = None
    entry_model: EntryModel
    regime: str = "range"
    session_guidance: dict[str, Any] | None = None
    session_penalty: float = 0.0
    accepted: bool
    block_reason: str | None = None
    base_rank_score: float
    adjusted_rank_score: float
    final_rank_score: float
    outcome_bias_score: float = 0.0
    outcome_bias: dict[str, Any] | None = None
    pre_outcome_final_rank_score: float | None = None
    post_outcome_final_rank_score: float | None = None
    capital_allocator: dict[str, Any] | None = None
    allocation_weight: float = 1.0
    allocated_risk_r: float = 0.0
    capital_pressure: str = "neutral"
    portfolio_penalty: float = 0.0
    portfolio_high_corr_count: int = 0
    risk_budget_score: float = 100.0
    portfolio_volatility: float = 0.0
    portfolio_total_cap: int = 0
    portfolio_directional_cap: int = 0
    portfolio_cluster_cap: int = 0
    projected_total_exposure: int = 0
    projected_directional_exposure: int = 0
    projected_cluster_exposure: int = 0
    mode_today_trade_count: int = 0
    mode_daily_trade_limit: int = 0
    mode_current_total_risk_r: float = 0.0
    mode_projected_trade_count: int = 0
    mode_total_risk_cap_r: float = 0.0
    mode_projected_total_risk_r: float = 0.0
    mode_shadow_only: bool = False
    strategy_sizing: dict[str, Any] | None = None
    reaction_evidence: dict[str, Any] | None = None
    location_reference: dict[str, Any] | None = None
    session_liquidity_reference: dict[str, Any] | None = None
    recommended_risk_r: float = 0.0
    expected_win_prob: float = 0.0
    expected_ev_r: float = 0.0
    expected_tp1_prob: float = 0.0
    expected_tp2_prob: float = 0.0
    expected_tp3_prob: float = 0.0
    expected_ev_at_recommended_size_r: float = 0.0
    expected_summary: str = ""
    block_reason_message: str | None = None
    alpha_research_candidate: bool = False
    alpha_research_reason: str | None = None
    alpha_research_reason_message: str | None = None
    alpha_research_softened_risk_r: float = 0.0
    alpha_research_gap: float = 0.0
    thesis_fingerprint: dict[str, Any] | None = None
    thesis_cluster_id: str | None = None
    thesis_cluster_size: int = 1
    thesis_primary_symbol: str | None = None
    thesis_rejected_reason: str | None = None
    thesis_active_cluster_count: int = 0
    edge_experiment_focus: dict[str, Any] | None = None


class PortfolioBudgetReportOut(ORMModel):
    generated_at: str
    universe: str
    symbols_considered: int
    deployment_go_no_go: str
    deployment_code: str
    deployment_message: str
    playbook_go_no_go: str
    playbook_code: str
    playbook_action: str
    playbook_message: str
    approval_strip_summary: dict[str, Any] | None = None
    edge_experiment_review: dict[str, Any] | None = None
    edge_evolution_rule: dict[str, Any] | None = None
    review_followup_ledger: dict[str, Any] | None = None
    risk_state: RiskGateState
    risk_reason: str
    operating_lock: dict[str, Any] = Field(default_factory=dict)
    strategy_mode: StrategyMode = StrategyMode.A_ONLY
    mode_policy: dict[str, Any] = Field(default_factory=dict)
    mode_stats: dict[str, Any] = Field(default_factory=dict)
    include_planned_exposure: bool
    current_exposure: dict[str, Any]
    headroom_by_regime: dict[str, dict[str, Any]]
    current_positions: list[PortfolioBudgetPositionOut]
    candidates_considered: int
    accepted_count: int
    blocked_count: int
    alpha_research_count: int = 0
    blocked_reason_counts: dict[str, int]
    multi_strategy_ab_summary: dict[str, Any] | None = None
    strategy_cluster_balance_summary: dict[str, Any] | None = None
    capital_allocator_summary: dict[str, Any] | None = None
    accepted_candidates: list[PortfolioBudgetCandidateOut]
    blocked_candidates: list[PortfolioBudgetCandidateOut]
    alpha_research_candidates: list[PortfolioBudgetCandidateOut] = Field(default_factory=list)
    report_path: str | None = None


class AlphaResearchOut(ORMModel):
    schema_version: str
    generated_at: str
    universe: str
    focus_symbol: str | None = None
    analysis_symbol: str | None = None
    available: bool
    reason: str
    summary: dict[str, Any] = Field(default_factory=dict)
    priorities: list[dict[str, Any]] = Field(default_factory=list)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    performance_decomposition_summary: dict[str, Any] | None = None
    alpha_research_evidence_summary: dict[str, Any] | None = None
    softening_candidate_review: dict[str, Any] | None = None
    promotion_watchlist: dict[str, Any] | None = None
    research_focus_alignment: dict[str, Any] | None = None
    recommended_action_summary: dict[str, Any] | None = None
    recommended_actions: list[dict[str, Any]] = Field(default_factory=list)
    top_shadow_experiment: dict[str, Any] | None = None
    shadow_experiment_templates: list[dict[str, Any]] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    report_path: str | None = None


class StrategyMetricsOut(ORMModel):
    symbol: str
    version: str
    win_rate: float
    avg_win: float
    avg_loss: float
    ev: float
    p1r: float
    p2r: float
    p3r: float
    sample_size: int = 0
    risk_state: RiskGateState = RiskGateState.OPEN
    risk_reason: str = "normal"
    operating_lock: dict[str, Any] = Field(default_factory=dict)
    total_score: float = 0.0
    grade: str = "F"
    recommendation: str = "insufficient-data"


class OperationalChecklistItemOut(ORMModel):
    item_id: str
    title: str
    category: str
    status: str
    summary: str
    blocking: bool = False
    source: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)


class OperationalChecklistOut(ORMModel):
    generated_at: str
    symbol: str
    universe: str
    strategy_version: str
    overall_status: str
    deployment_go_no_go: str
    deployment_code: str
    deployment_message: str
    playbook_go_no_go: str
    playbook_code: str
    playbook_action: str
    playbook_message: str
    approval_strip_summary: dict[str, Any] | None = None
    blocking_failures: int
    warnings: int
    manual_actions: int
    checks: list[OperationalChecklistItemOut]
    report_path: str | None = None


class ReadyOut(ORMModel):
    status: str
    checks: dict[str, bool]
    details: dict[str, str] = Field(default_factory=dict)


class AlertSubscribeOut(ORMModel):
    alert_id: str
    status: str
    deployment_go_no_go: str = ""
    deployment_code: str = ""
    deployment_message: str = ""
    approval_playbook_go_no_go: str = ""
    approval_playbook_code: str = ""
    approval_playbook_action: str = ""
    approval_playbook_message: str = ""
    approval_strip_summary: dict[str, Any] | None = None


class AlertTestOut(ORMModel):
    alert_id: str
    channel: str
    symbol: str
    deployment_go_no_go: str = ""
    deployment_code: str = ""
    deployment_message: str = ""
    approval_playbook_go_no_go: str = ""
    approval_playbook_code: str = ""
    approval_playbook_action: str = ""
    approval_playbook_message: str = ""
    approval_strip_summary: dict[str, Any] | None = None
    delivery: dict[str, Any]
    retry_queued: int = 0


class AlertMetricsOut(ORMModel):
    generated_at: str
    days: int
    alerts_total: int
    alerts_with_delivery: int
    overall: dict[str, Any]
    channel_metrics: dict[str, dict[str, Any]]
    circuit_state: dict[str, dict[str, Any]]
    latest_validation_alert: dict[str, Any] = Field(default_factory=dict)
    retry_queue: dict[str, Any]
    report_path: str | None = None


class AlertRetryQueueStatusOut(ORMModel):
    counts: dict[str, int]
    backlog_age_seconds: int
    dead_letter_oldest_age_seconds: int
    next_retry_in_seconds: int
    retry_policy: dict[str, Any]


class AlertRetryQueueRunOut(ORMModel):
    scanned: int
    delivered: int = 0
    requeued: int = 0
    dead_lettered: int = 0


class ExecutionFillIn(ORMModel):
    fill_id: str = Field(min_length=6, max_length=80)
    plan_id: str = Field(min_length=4, max_length=50)
    symbol: str = Field(min_length=3, max_length=30)
    stage: ExecutionFillStage
    fill_ts: datetime
    price: float = Field(gt=0)
    qty: float = Field(gt=0)
    fee: float = Field(default=0.0, ge=0.0)
    exit_reason: ExitReason | None = None
    remaining_qty: float | None = Field(default=None, ge=0.0)
    realized_r: float | None = None
    held_bars: int | None = Field(default=None, ge=0)
    classification_before_exit: str | None = Field(default=None, max_length=60)
    classification_after_exit: str | None = Field(default=None, max_length=60)
    trigger_detail: dict[str, Any] = Field(default_factory=dict)
    slippage_bps: float | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=500)
    payload: dict[str, Any] = Field(default_factory=dict)


class ExecutionFillOut(ORMModel):
    accepted: bool
    duplicate: bool
    fill_id: str
    plan_id: str | None = None
    symbol: str | None = None
    stage: str | None = None
    from_state: str | None = None
    to_state: str | None = None
    state_changed: bool
    reason: str
    exit_reason: str | None = None


class TVWebhookOut(ORMModel):
    status: str
    event: str
    processed_plan_id: str | None = None


class BinanceSyncOut(ORMModel):
    symbol: str
    backfill: dict[str, int]
    refresh: dict[str, Any]


class BinanceOrderSubmitIn(ORMModel):
    symbol: str = Field(min_length=3, max_length=30)
    side: str = Field(pattern="^(BUY|SELL)$")
    order_type: str = Field(pattern="^(MARKET|LIMIT)$")
    quantity: float = Field(gt=0)
    price: float | None = Field(default=None, gt=0)
    time_in_force: str = Field(default="GTC", pattern="^(GTC|IOC|FOK)$")
    reduce_only: bool = False
    client_order_id: str | None = Field(default=None, min_length=4, max_length=36)
    plan_id: str | None = Field(default=None, min_length=4, max_length=50)
    live: bool = False
    new_order_resp_type: str = Field(default="RESULT", pattern="^(ACK|RESULT)$")


class BinanceOrderOut(ORMModel):
    action: str
    mode: str
    requested_live: bool = False
    live_enabled: bool = False
    test_order: bool = False
    symbol: str
    plan_id: str | None = None
    order_id: int | None = None
    client_order_id: str = ""
    status: str = ""
    side: str = ""
    order_type: str = ""
    price: float | None = None
    orig_qty: float | None = None
    executed_qty: float | None = None
    reduce_only: bool | None = None
    time_in_force: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class BinanceListenKeyOut(ORMModel):
    action: str
    listen_key: str
    closed: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class BinanceUserStreamProcessIn(ORMModel):
    listen_key: str = Field(min_length=8, max_length=128)
    max_events: int = Field(default=10, ge=1, le=200)
    timeout_seconds: float = Field(default=15.0, gt=0.0, le=120.0)


class BinanceUserStreamEventIn(ORMModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class BinanceUserStreamEventOut(ORMModel):
    accepted: bool
    kind: str
    event_type: str | None = None
    symbol: str | None = None
    plan_id: str | None = None
    client_order_id: str | None = None
    order_id: int | None = None
    reason: str | None = None
    order_snapshot: dict[str, Any] | None = None
    position_sync: dict[str, Any] | None = None
    fill_ingest: dict[str, Any] | None = None


class BinanceUserStreamProcessOut(ORMModel):
    listen_key: str
    processed: int
    order_updates: int
    account_updates: int
    fills_ingested: int
    positions_synced: int
    last_event_ts: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)


class BinancePositionOut(ORMModel):
    position_key: str
    symbol: str
    position_side: str
    position_amt: float
    entry_price: float
    break_even_price: float
    mark_price: float
    liquidation_price: float
    unrealized_pnl: float
    notional: float
    leverage: int
    margin_type: str
    isolated_wallet: float
    update_ts: str
    raw: dict[str, Any] = Field(default_factory=dict)


class BinancePositionsOut(ORMModel):
    symbol: str | None = None
    open_only: bool = False
    count: int
    positions: list[BinancePositionOut] = Field(default_factory=list)


class BinancePositionSyncOut(ORMModel):
    symbol: str | None = None
    synced: int
    open_positions: int
    positions: list[BinancePositionOut] = Field(default_factory=list)


class EventReprocessOut(ORMModel):
    scanned: int
    published: int
    failed: int


class PboDsrArtifactStoreOut(ORMModel):
    schema_version: str
    symbol: str
    version: str
    generated_at: str
    artifact_store_ready: bool
    available: bool
    metrics_available: bool
    implementation_status: str
    reason: str
    counts: dict[str, int]
    parameter_families_present: list[str]
    selection_rule_counts: dict[str, int]
    selection_universe_sizes: list[int]
    selection_universe_summary: dict[str, Any]
    latest_snapshot: dict[str, Any] | None = None
    storage_contract: dict[str, Any]
    blocked_by: list[str]
    next_steps: list[str]
    report_path: str | None = None


class PboDsrTrialWriterOut(ORMModel):
    schema_version: str
    symbol: str
    version: str
    generated_at: str
    available: bool
    implementation_status: str
    reason: str
    evaluation_basis: str
    sample_counts: dict[str, int]
    selection_rule: str
    selected_trial_run_id: str | None = None
    parameter_families_present: list[str]
    threshold_parameter_families_present: list[str]
    candidate_trials_by_family: dict[str, int]
    trial_catalog: list[dict[str, Any]]
    persist_summary: dict[str, int] | None = None
    blocked_by: list[str]
    next_steps: list[str]
    report_path: str | None = None


class PboDsrThresholdRunnerOut(ORMModel):
    schema_version: str
    symbol: str
    version: str
    generated_at: str
    available: bool
    implementation_status: str
    reason: str
    evaluation_basis: str
    lineage_namespace: str
    sample_counts: dict[str, int]
    selection_rule: str
    selected_trial_run_id: str | None = None
    parameter_families_present: list[str]
    candidate_trials_by_family: dict[str, int]
    sweep_grid: dict[str, Any]
    trial_catalog: list[dict[str, Any]]
    persist_summary: dict[str, int] | None = None
    blocked_by: list[str]
    next_steps: list[str]
    report_path: str | None = None


class PboDsrMetricsOut(ORMModel):
    schema_version: str
    symbol: str
    version: str
    generated_at: str
    available: bool
    metrics_complete: bool
    reason: str
    evaluation_basis: str
    sample_counts: dict[str, int]
    selection_rule_counts: dict[str, int]
    selection_universe_summary: dict[str, Any]
    selected_trial: dict[str, Any] | None = None
    lineage_audit: dict[str, Any]
    pbo: dict[str, Any]
    dsr: dict[str, Any]
    snapshot_summary: dict[str, Any] | None = None
    blocked_by: list[str]
    next_steps: list[str]
    deployment_recommendation: dict[str, Any]
    report_path: str | None = None


class StressReplayAssessmentOut(ORMModel):
    schema_version: str
    symbol: str
    version: str
    generated_at: str
    available: bool
    reason: str
    evaluation_basis: str
    full_replay_ready: bool
    replacement_recommended: bool
    sample_counts: dict[str, int]
    coverage: dict[str, float]
    readiness_gates: dict[str, float | int]
    scenario_evidence: dict[str, Any]
    approximation_limits: list[str]
    blocked_by: list[str]
    next_steps: list[str]
    true_runner_readiness: dict[str, Any]
    deployment_recommendation: dict[str, Any]
    report_path: str | None = None


class StressReplayLineageOut(ORMModel):
    schema_version: str
    symbol: str
    version: str
    generated_at: str
    available: bool
    runtime_inputs_ready: bool
    reason: str
    evaluation_basis: str
    sample_counts: dict[str, int]
    coverage: dict[str, float]
    fill_path: dict[str, Any]
    candle_path: dict[str, Any]
    gap_counts: dict[str, int]
    lineage_contract: dict[str, Any]
    blocked_by: list[str]
    next_steps: list[str]
    report_path: str | None = None


class StressReplayRunnerContractOut(ORMModel):
    schema_version: str
    symbol: str
    version: str
    generated_at: str
    design_ready: bool
    available: bool
    runtime_job_ready: bool
    implementation_status: str
    reason: str
    evaluation_basis: str
    readiness: dict[str, Any]
    true_runner_readiness: dict[str, Any]
    dependencies: dict[str, Any]
    scenario_contract: dict[str, Any]
    runner_contract: dict[str, Any]
    worker_input_contract: dict[str, Any]
    worker_output_contract: dict[str, Any]
    blocked_by: list[str]
    next_steps: list[str]
    report_path: str | None = None


class StressReplayLineageWriterOut(ORMModel):
    schema_version: str
    symbol: str
    version: str
    generated_at: str
    available: bool
    artifacts_written: bool
    runtime_job_ready: bool
    implementation_status: str
    reason: str
    evaluation_basis: str
    sample_counts: dict[str, Any]
    writer_contract: dict[str, Any]
    scenario_batches: dict[str, Any]
    blocked_by: list[str]
    next_steps: list[str]
    report_path: str | None = None


class StressReplayOutputArtifactsOut(ORMModel):
    schema_version: str
    symbol: str
    version: str
    generated_at: str
    available: bool
    comparison_ready: bool
    reason: str
    evaluation_basis: str
    summary_counts: dict[str, int]
    artifact_contract: dict[str, Any]
    lineage_summary: dict[str, Any]
    scenario_outputs: dict[str, Any]
    comparison_to_approximation: dict[str, dict[str, float]]
    blocked_by: list[str]
    next_steps: list[str]
    report_path: str | None = None


class StressReplayPrototypeWorkerOut(ORMModel):
    schema_version: str
    symbol: str
    version: str
    generated_at: str
    available: bool
    executed: bool
    runtime_job_ready: bool
    reason: str
    evaluation_basis: str
    dependencies: dict[str, Any]
    sample_counts: dict[str, int]
    worker_contract: dict[str, Any]
    scenario_runs: dict[str, Any]
    blocked_by: list[str]
    next_steps: list[str]
    report_path: str | None = None


class ScalpExperimentOut(ORMModel):
    schema_version: str
    symbol: str
    generated_at: str
    available: bool
    reason: str
    evaluation_basis: str
    sample_counts: dict[str, int]
    baseline: dict[str, Any]
    experiment: dict[str, Any]
    comparison: dict[str, Any]
    blocked_by: list[str]
    next_steps: list[str]
    report_path: str | None = None


class ValidationReportOut(ORMModel):
    symbol: str
    updated_zones: int
    metrics: dict[str, Any]
    walk_forward: dict[str, Any]
    monte_carlo: dict[str, Any]
    validation_report: dict[str, Any]
    deployment_go_no_go: str = ""
    deployment_code: str = ""
    deployment_message: str = ""
    approval_topline_status: str = ""
    approval_topline_code: str = ""
    approval_topline_message: str = ""
    approval_topline_summary_line: str = ""
    playbook_go_no_go: str = ""
    playbook_code: str = ""
    playbook_action: str = ""
    playbook_message: str = ""
    validation_alert: dict[str, Any] | None = None
    execution_quality: dict[str, Any] | None = None
    feature_importance: dict[str, Any] | None = None
    feature_calibration: dict[str, Any] | None = None
    strategy_v2_validation: dict[str, Any] | None = None
    strategy_v2_lock_validation: dict[str, Any] | None = None
    strategy_v2_pbo_dsr_trial_writer: dict[str, Any] | None = None
    strategy_v2_pbo_dsr_threshold_runner: dict[str, Any] | None = None
    strategy_v2_pbo_dsr_artifact_store: dict[str, Any] | None = None
    strategy_v2_pbo_dsr_design: dict[str, Any] | None = None
    strategy_v2_pbo_dsr_metrics: dict[str, Any] | None = None
    strategy_v2_stress_validation: dict[str, Any] | None = None
    strategy_v2_stress_replay_lineage: dict[str, Any] | None = None
    strategy_v2_stress_replay_assessment: dict[str, Any] | None = None
    strategy_v2_stress_replay_runner_contract: dict[str, Any] | None = None
    strategy_v2_stress_replay_lineage_writer: dict[str, Any] | None = None
    strategy_v2_stress_replay_prototype_worker: dict[str, Any] | None = None
    strategy_v2_thesis_validation: dict[str, Any] | None = None
    strategy_v2_scalp_experiment: dict[str, Any] | None = None
    alpha_research_pipeline: dict[str, Any] | None = None
    parameter_changelog: dict[str, Any] | None = None
    operator_action_priority_summary: dict[str, Any] | None = None
    edge_experiment_review_available: bool | None = None
    edge_experiment_review_summary: dict[str, Any] | None = None
    edge_evolution_rule_available: bool | None = None
    edge_evolution_rule_summary: dict[str, Any] | None = None
    review_followup_ledger_available: bool | None = None
    review_followup_ledger_summary: dict[str, Any] | None = None


class ExecutionQualityOut(ORMModel):
    symbol: str
    days: int
    generated_at: str
    comparison_axis: str
    versions_compared: int
    plans_total: int
    plans_matured: int
    fills_matched: int
    fill_events_total: int
    fill_rate: float
    fill_sources: dict[str, int]
    stage_counts: dict[str, int]
    slippage_bps: dict[str, float]
    entry_latency_seconds: dict[str, float]
    fees: dict[str, float]
    unfilled_reasons: dict[str, int]
    unfilled_reason_details: dict[str, int]
    exit_reasons: dict[str, int]
    final_exit_reasons: dict[str, int]
    target_exit_ratio: float
    forced_exit_ratio: float
    information_failure_ratio: float
    time_failure_ratio: float
    by_entry_model: dict[str, dict[str, float]]
    by_strategy_family: dict[str, dict[str, Any]]
    by_strategy_version: dict[str, dict[str, Any]]
    version_comparison: list[dict[str, Any]]
    report_path: str | None = None


class FeatureCalibrationOut(ORMModel):
    schema_version: str
    symbol: str
    available: bool
    reason: str | None = None
    regime_label: str
    baseline_generated_plans: int
    matched_samples: int
    alpha: float
    baseline_weights: dict[str, float]
    previous_weights: dict[str, float]
    current_scores: dict[str, float]
    ewma_scores: dict[str, float]
    recommended_weights: dict[str, float]
    by_regime: dict[str, dict[str, Any]]
    zone_type_multipliers: dict[str, dict[str, float]]
    applied_runtime: bool
    snapshot_path: str | None = None
    report_path: str | None = None
    generated_at: str


class UniverseSyncOut(ORMModel):
    universe: str
    requested_symbols: int
    processed_symbols: int
    symbol_concurrency_requested: int = 1
    symbol_concurrency: int = 1
    execution_mode: str = "sequential"
    success: int
    failed: int
    results: list[dict[str, Any]]


class OutboxStatusOut(ORMModel):
    backend: str
    counts: dict[str, int]
    backlog_age_seconds: int
    retry_policy: dict[str, int]
