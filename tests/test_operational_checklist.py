from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import Settings
from app.db.models import AlertSubscription
from app.services.health_check import ReadySnapshot
from app.services.operational_checklist import OperationalChecklistService


class _AlertRepoStub:
    def __init__(self, alerts: list[AlertSubscription]):
        self._alerts = alerts

    def list_recent(self, *, days: int = 30, limit: int = 5000) -> list[AlertSubscription]:
        return list(self._alerts)[:limit]


def test_operational_checklist_generates_report_and_statuses(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    settings = Settings(
        operations_checklist_report_dir=str(tmp_path),
        alert_discord_webhook_url="https://discord.example/webhook",
    )
    alerts = [
        AlertSubscription(
            alert_id="alert_test_discord",
            plan_id=None,
            symbol="BTCUSDC",
            channel="discord",
            type="test",
            payload={
                "delivery": {
                    "channel": "discord",
                    "delivered": True,
                    "skipped": False,
                    "reason": "ok",
                    "attempts": 1,
                    "latency_ms": 120.0,
                }
            },
            triggered_ts=now - timedelta(hours=1),
        )
    ]
    service = OperationalChecklistService(alert_repo=_AlertRepoStub(alerts), settings=settings)

    payload = service.generate(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        strategy_version="v1",
        ready=ReadySnapshot(
            status="ready",
            checks={"db": True, "binance_rest": True, "event_backend": True},
            details={"db": "ok", "binance_rest": "ok", "event_backend": "ok"},
        ),
        validation_payload={
            "validation_report": {
                "status": "PASS",
                "path": "reports/validation/test.md",
                "generated_at": now.isoformat(),
                "execution_degradation_advisory_available": True,
                "execution_degradation_advisory_summary": {
                    "status": "healthy",
                    "summary": "execution degradation advisory is healthy",
                    "recommended_action": "continue_runtime_monitoring",
                    "reason_codes": [],
                    "sample_context": {"plans_matured": 4, "fill_events_total": 2},
                },
                "operator_action_priority_summary": {
                    "available": True,
                    "top_action": "review_runtime_execution_drag_before_expansion",
                    "top_reason": "global execution degradation requires manual review",
                    "priority_level": "urgent",
                    "priority_source": "execution_degradation",
                    "action_family": "execution_review",
                    "supporting_signals": ["execution:manual_review"],
                    "blocking_signals": [],
                    "next_actions": [
                        {
                            "action": "run_shadow_exit_review",
                            "reason": "information_failure_rate is elevated for this family",
                            "priority_level": "research",
                            "source": "alpha_research",
                            "advisory_only": True,
                        }
                    ],
                    "capture_context": {
                        "available": True,
                        "dominant_bottleneck": {"stage": "runtime_to_submit", "reason": "quality_blocking"},
                        "family_focus": {"key": "trend_continuation"},
                        "maturity": "thin_activity",
                    },
                    "experiment_context": {
                        "available": True,
                        "edge_state": "watch_edge",
                        "entry_timing_preferred_variant": "early_limit",
                        "execution_style_preferred_variant": "passive_limit",
                        "entry_timing_target": {
                            "symbol": "BTCUSDC",
                            "status": "ACTIONABLE_ENTRY",
                            "strategy_family": "trend_continuation",
                        },
                        "execution_style_target": {
                            "symbol": "BTCUSDC",
                            "status": "ACTIONABLE_ENTRY",
                            "strategy_family": "trend_continuation",
                        },
                    },
                    "advisory_only": True,
                },
                "outcome_control_trace_available": True,
                "outcome_control_trace_summary": {
                    "available": True,
                    "summary": "approval downgraded; risk allowance reduced; portfolio ordering bias stayed negative",
                    "approval_penalty_status": "manual_review",
                    "approval_penalty_tier": "downgrade_to_manual",
                    "sizing_penalty_status": "watch",
                    "sizing_penalty_tier": "soft_clamp",
                    "sizing_multiplier": 0.75,
                    "portfolio_bias_tier": "negative",
                    "portfolio_bias_score_delta": -2.5,
                    "top_reason_codes": ["execution_degradation:manual_review", "family_outcome:negative"],
                },
                "score_to_outcome_funnel_summary": {
                    "available": True,
                    "money_funnel": {
                        "available": True,
                        "snapshot_expected_r": {
                            "runtime_candidates": 1.42,
                            "accepted_candidates": 0.56,
                            "blocked_candidates": 0.86,
                        },
                        "historical_expected_r": {
                            "generated": 1.84,
                            "submitted": 1.29,
                            "filled": 0.96,
                            "closed": 0.96,
                        },
                        "historical_realized_r": {
                            "raw_closed": 0.84,
                            "post_cost_closed": 0.72,
                            "cost_drag": -0.12,
                        },
                        "historical_gap_r": {
                            "generated_to_submitted": 0.55,
                            "submitted_to_filled": 0.33,
                            "filled_to_closed": 0.0,
                            "closed_expected_to_raw_realized": -0.12,
                            "closed_expected_to_post_cost_realized": -0.24,
                        },
                        "summary": "expected_closed_r=0.9600, post_cost_closed_r=0.7200, submitted_to_filled_gap_r=0.3300",
                    },
                },
                "outcome_attribution_available": True,
                "outcome_attribution_summary": {
                    "available": True,
                    "advisory_only": True,
                    "confidence": "medium",
                    "closed_trade_count": 6,
                    "strategy_component_r": 0.96,
                    "execution_component_r": -0.12,
                    "condition_component_r": -0.12,
                    "fill_capture_gap_r": 0.33,
                    "closed_expected_r": 0.96,
                    "closed_post_cost_realized_r": 0.72,
                    "closed_post_cost_delta_r": -0.24,
                    "strongest_drag_source": "fill_capture_gap",
                    "summary": "The largest current money leak is expected edge that never converted from submit to fill; treat execution conversion and missed-fill impact as the first review axis.",
                    "reason_codes": [
                        "closed_trades:6",
                        "strongest_drag:fill_capture_gap",
                        "friction:watch_friction",
                        "execution_axis:slippage_state",
                        "condition_focus:session",
                        "condition_bucket:dead_session",
                    ],
                    "source_summary": {
                        "friction_state": "watch_friction",
                        "weakest_execution_axis": "slippage_state",
                        "condition_focus": "session",
                        "condition_bucket": "dead_session",
                        "money_funnel_summary": "expected_closed_r=0.9600, post_cost_closed_r=0.7200, submitted_to_filled_gap_r=0.3300",
                    },
                },
                "edge_experiment_review_available": True,
                "edge_experiment_review_summary": {
                    "available": True,
                    "advisory_only": True,
                    "edge_state": "watch_edge",
                    "closed_trade_count": 6,
                    "true_edge_ratio": 0.75,
                    "recent_true_edge_ratio": 0.7778,
                    "prior_true_edge_ratio": 0.7143,
                    "edge_decay_rate": 0.0635,
                    "edge_stability": 0.0635,
                    "entry_timing_available": True,
                    "entry_timing_comparison_ready": True,
                    "entry_timing_preferred_variant": "early_limit",
                    "entry_timing_recommendation_reason": "better_fill_capture_ratio",
                    "execution_style_available": True,
                    "execution_style_comparison_ready": True,
                    "execution_style_preferred_variant": "passive_limit",
                    "execution_style_recommendation_reason": "better_fill_capture_ratio",
                    "summary": "Post-cost true edge is positive but unstable; prefer controlled split tests over structural rewrites.",
                    "reason_codes": [
                        "edge_state:watch_edge",
                        "true_edge_ratio:0.7500",
                        "entry_timing:better_fill_capture_ratio",
                        "execution_style:better_fill_capture_ratio",
                    ],
                    "source_summary": {
                        "recent_window_closed": 3,
                        "prior_window_closed": 3,
                        "entry_timing_preferred_variant": "early_limit",
                        "execution_style_preferred_variant": "passive_limit",
                    },
                },
                "edge_evolution_rule_available": True,
                "edge_evolution_rule_summary": {
                    "available": True,
                    "advisory_only": True,
                    "evolution_state": "reduce_candidate",
                    "recommended_action": "reduce_baseline_allocation_review",
                    "allocation_bias": "reduce_baseline",
                    "confidence": "medium",
                    "kill_review_triggered": False,
                    "true_edge_ratio": 0.75,
                    "edge_decay_rate": 0.0635,
                    "closed_trade_count": 6,
                    "promotion_candidate_axis": "entry_timing",
                    "promotion_candidate_variant": "early_limit",
                    "promotion_candidate_reason": "better_fill_capture_ratio",
                    "summary": "Baseline edge is weak enough that allocation should be reduced until the preferred branch proves durable post-cost.",
                    "reason_codes": [
                        "evolution_state:reduce_candidate",
                        "recommended_action:reduce_baseline_allocation_review",
                    ],
                    "source_summary": {
                        "edge_state": "watch_edge",
                        "rollout_recommendation": "reduce",
                        "strategy_lifecycle_state": "degraded",
                        "kill_condition_state": "close_only_review",
                    },
                },
                "rollout_recommendation_available": True,
                "rollout_recommendation_summary": {
                    "available": True,
                    "advisory_only": True,
                    "family": "trend_continuation",
                    "recommendation": "reduce",
                    "confidence": "medium",
                    "maturity": "mature",
                    "summary": "family=trend_continuation shows execution or post-cost weakness; review current rollout policy and consider lowering mode or risk.",
                    "reason_codes": ["family_outcome:negative", "family_execution:manual_review"],
                    "current_policy": {
                        "live_enabled": True,
                        "max_execution_mode": "MICRO_LIVE",
                        "max_risk_r": 1.0,
                    },
                    "suggested_policy_delta": {
                        "action": "reduce_consideration",
                        "suggested_max_execution_mode": "PAPER",
                        "suggested_max_risk_r": 0.5,
                        "change_hint": "reduce_mode_or_risk_after_operator_review",
                    },
                },
                "strategy_lifecycle_available": True,
                "strategy_lifecycle_summary": {
                    "available": True,
                    "advisory_only": True,
                    "family": "trend_continuation",
                    "state": "degraded",
                    "previous_state": "production",
                    "transition_bias": "degrade",
                    "confidence": "high",
                    "summary": "family=trend_continuation has weakened from live-ready posture and should be reviewed in degraded mode before further rollout.",
                    "reason_codes": [
                        "lifecycle:degraded",
                        "rollout_recommendation:reduce",
                        "family_outcome:negative",
                    ],
                    "source_summary": {
                        "family_closed": 10,
                        "family_post_cost_rate": 0.2,
                        "family_execution_status": "manual_review",
                        "family_mode_advisory_state": "watch",
                        "rollout_recommendation": "reduce",
                        "rollout_maturity": "mature",
                        "previous_state": "production",
                        "alpha_research_signal": "research_active",
                        "modifier_state": "negative",
                    },
                },
                "multi_strategy_ab_available": True,
                "multi_strategy_ab_summary": {
                    "available": True,
                    "advisory_only": True,
                    "mode": "A_PLUS_B",
                    "raw_family_anchor": "sweep_reversal",
                    "summary": "A reversal remains the current production anchor while B continuation stays available but guarded under first-wave activation rules; range rotation remains research-only sidecar.",
                    "reason_codes": [
                        "mode:a_plus_b",
                        "cluster:a_reversal",
                        "cluster:b_continuation",
                        "b_guardrail:thin_sample",
                    ],
                    "a_cluster": {
                        "cluster": "a_reversal",
                        "strategy_cluster_status": "current_anchor",
                        "live_eligible": True,
                        "guarded": False,
                    },
                    "b_cluster": {
                        "cluster": "b_continuation",
                        "strategy_cluster_status": "available_but_guarded",
                        "live_eligible": False,
                        "guarded": True,
                        "guardrail_reasons": ["b_guardrail:thin_sample"],
                    },
                    "research_sidecar": {
                        "cluster": "research_only_sidecar",
                        "strategy_cluster_status": "research_only_sidecar",
                        "guarded": True,
                    },
                    "family_mix": [
                        {
                            "raw_family": "sweep_reversal",
                            "cluster": "a_reversal",
                            "total_candidates": 4,
                            "accepted_candidates": 2,
                            "blocked_candidates": 2,
                            "alpha_research_candidates": 0,
                        },
                        {
                            "raw_family": "trend_continuation",
                            "cluster": "b_continuation",
                            "total_candidates": 2,
                            "accepted_candidates": 0,
                            "blocked_candidates": 1,
                            "alpha_research_candidates": 1,
                        },
                    ],
                },
                "b_continuation_activation_available": True,
                "b_continuation_activation_summary": {
                    "available": True,
                    "advisory_only": True,
                    "family": "trend_continuation",
                    "activation_state": "blocked",
                    "activation_bias": "clear_guardrails",
                    "target_mode": "A_PLUS_B",
                    "confidence": "medium",
                    "live_eligible": False,
                    "summary": "B continuation still has hard first-wave blockers; clear execution, policy, or clearance guardrails before activation review.",
                    "reason_codes": [
                        "b_activation:blocked",
                        "mode:a_plus_b",
                        "cluster_status:available_but_guarded",
                        "b_activation_block:family_execution_manual_review",
                    ],
                    "source_summary": {
                        "cluster_status": "available_but_guarded",
                        "family_closed": 10,
                        "family_execution_status": "manual_review",
                        "rollout_recommendation": "reduce",
                        "lifecycle_state": "degraded",
                        "governance_state": "defer",
                        "clearance_state": "blocked",
                        "reopen_action": "continue_clearance",
                        "brief_state": "clearance_required",
                        "execution_stage": "auto_execution_blocked",
                        "positive_expansion_state": "not_ready",
                        "thin_sample": False,
                        "guardrail_reasons": ["b_guardrail:thin_sample"],
                    },
                },
                "execution_friction_measurement_available": True,
                "execution_friction_measurement_summary": {
                    "available": True,
                    "advisory_only": True,
                    "friction_state": "watch_friction",
                    "friction_bias": "monitor_execution_drag",
                    "fill_conversion_state": "healthy_fill_conversion",
                    "slippage_state": "watch_slippage",
                    "latency_state": "healthy_latency",
                    "fee_state": "watch_fee_drag",
                    "reconciliation_state": "healthy_reconciliation",
                    "measurement_coverage_state": "mature_measurement",
                    "stress_drag_state": "watch_stress_drag",
                    "weakest_axis": "slippage_state",
                    "confidence": "medium",
                    "summary": "Execution drag is still manageable, but slippage is softening current post-cost confidence.",
                    "reason_codes": [
                        "coverage:mature_measurement",
                        "slippage:watch_slippage",
                        "fee:watch_fee_drag",
                        "stress:watch_stress_drag",
                    ],
                    "source_summary": {
                        "execution_quality_report_path": "reports/execution/execution_quality.md",
                        "stress_validation_report_path": "reports/validation/stress_validation.md",
                        "stress_available": True,
                        "fill_sources": {"execution_fills": 8, "zone_outcomes_fallback": 1},
                        "reconciliation_highest_severity": "INFO",
                    },
                },
                "forward_stress_regime_validation_available": True,
                "forward_stress_regime_validation_summary": {
                    "available": True,
                    "advisory_only": True,
                    "validation_state": "fragile_generalization",
                    "validation_bias": "monitor_regime_stress_fragility",
                    "coverage_state": "usable_validation",
                    "walk_forward_state": "validated_walk_forward",
                    "stress_state": "fragile_stress",
                    "replay_state": "replay_followup_required",
                    "regime_split_state": "validated_regime_split",
                    "session_split_state": "fragile_session_split",
                    "preferred_live_mode": "A_ONLY",
                    "worst_scenario": "shock_concentration",
                    "best_regime": "range",
                    "best_session": "overlap",
                    "weakest_axis": "stress_state",
                    "summary": "Generalization still holds directionally, but stress evidence is fragile around shock_concentration; monitor deployment confidence before trusting current validation.",
                    "reason_codes": [
                        "usable_validation_coverage",
                        "stress_catastrophic_drawdown",
                        "replay_followup_required",
                        "fragile_session_bucket",
                    ],
                    "source_summary": {
                        "walk_forward": {"trades": 14, "mean_ev": 0.08, "p5_ev": -0.25},
                        "strategy_v2_validation": {
                            "available": True,
                            "eligible_closed_trades": 14,
                            "preferred_live_mode": "A_ONLY",
                            "best_regime": "range",
                            "best_session": "overlap",
                            "fragile_regime_bucket": "",
                            "fragile_session_bucket": "dead_session",
                        },
                        "strategy_v2_stress_validation": {
                            "available": True,
                            "stress_pass": False,
                            "reason": "scenario_catastrophic_drawdown:shock_concentration",
                            "worst_scenario": "shock_concentration",
                            "replay_gate_applied": True,
                            "divergence_gate_applied": True,
                            "execution_data_trades": 9,
                        },
                        "strategy_v2_stress_replay_assessment": {
                            "available": True,
                            "decision": "prepare_full_replay",
                            "replacement_recommended": True,
                            "true_runner_promotion_ready": False,
                            "reason": "multiple_degraded_scenarios:shock_concentration",
                        },
                        "strategy_v2_stress_replay_lineage": {
                            "available": True,
                            "runtime_inputs_ready": True,
                            "reason": "runtime_lineage_ready",
                        },
                    },
                },
                "kill_condition_automation_available": True,
                "kill_condition_automation_summary": {
                    "available": True,
                    "advisory_only": True,
                    "kill_condition_state": "close_only_review",
                    "automation_bias": "propose_close_only",
                    "write_scope": "proposal_only",
                    "trigger_axis": "reconciliation_axis",
                    "trigger_reason_codes": [
                        "kill_condition:close_only_review",
                        "risk_gate:closed",
                        "friction:degraded",
                        "generalization:insufficient",
                        "reconciliation:critical",
                    ],
                    "active_manual_override": False,
                    "manual_override_reason": "",
                    "arm_required": True,
                    "summary": "Current evidence is weak enough that close-only review should happen before new entries continue.",
                    "reason_codes": [
                        "kill_condition:close_only_review",
                        "risk_gate:closed",
                        "friction:degraded",
                        "generalization:insufficient",
                        "reconciliation:critical",
                        "execution_degradation:manual_review",
                    ],
                    "source_summary": {
                        "risk_gate_state": "closed",
                        "risk_gate_reason": "max_consecutive_losses",
                        "friction_state": "degraded",
                        "generalization_state": "insufficient",
                        "reconciliation_state": "critical",
                        "execution_degradation_state": "manual_review",
                        "family_execution_degradation_state": "watch",
                        "kill_switch_active": False,
                        "close_only_active": False,
                        "active_lock_count": 0,
                        "available_source_count": 7,
                    },
                },
                "b_continuation_edge_validation_available": True,
                "b_continuation_edge_validation_summary": {
                    "available": True,
                    "advisory_only": True,
                    "raw_family": "trend_continuation",
                    "strategy_cluster": "b_continuation",
                    "edge_state": "fragile_edge",
                    "validation_bias": "monitor_diversification",
                    "sample_state": "mature_sample",
                    "family_post_cost_rate": 0.5,
                    "diversification_state": "correlation_heavy",
                    "drawdown_contribution_state": "drawdown_neutral",
                    "a_b_correlation_proxy": "high_overlap_proxy",
                    "weakest_axis": "cost_condition",
                    "weakest_bucket": "high_cost",
                    "confidence": "medium",
                    "summary": "family=trend_continuation still has usable B evidence, but diversification remains fragile because the current A/B overlap proxy is still heavy.",
                    "reason_codes": [
                        "b_edge:fragile_edge",
                        "sample:mature_sample",
                        "diversification:correlation_heavy",
                    ],
                    "source_summary": {
                        "raw_family_anchor": "trend_continuation",
                        "strategy_cluster": "b_continuation",
                        "family_execution_status": "healthy",
                        "activation_state": "blocked",
                        "balance_state": "a_concentrated",
                        "capital_pressure": "neutral",
                    },
                },
                "strategy_cluster_balance_available": True,
                "strategy_cluster_balance_summary": {
                    "available": True,
                    "advisory_only": True,
                    "mode": "A_PLUS_B",
                    "balance_state": "a_concentrated",
                    "balance_bias": "preserve_a_anchor",
                    "headline_cluster": "a_reversal",
                    "target_mix": "a_anchor_with_b_underweight",
                    "confidence": "low",
                    "summary": "The current mix remains concentrated in A while B continuation is still underweight or blocked.",
                    "family_mix": [
                        {
                            "raw_family": "sweep_reversal",
                            "cluster": "a_reversal",
                            "total_candidates": 4,
                            "accepted_candidates": 2,
                            "blocked_candidates": 2,
                            "alpha_research_candidates": 0,
                        },
                        {
                            "raw_family": "trend_continuation",
                            "cluster": "b_continuation",
                            "total_candidates": 2,
                            "accepted_candidates": 0,
                            "blocked_candidates": 1,
                            "alpha_research_candidates": 1,
                        },
                    ],
                    "reason_codes": [
                        "cluster_balance:a_concentrated",
                        "mode:a_plus_b",
                        "headline_cluster:a_reversal",
                    ],
                    "source_summary": {
                        "a_total_candidates": 4,
                        "a_accepted_candidates": 2,
                        "b_total_candidates": 2,
                        "b_accepted_candidates": 0,
                        "b_alpha_research_candidates": 1,
                        "b_activation_state": "blocked",
                        "b_activation_bias": "clear_guardrails",
                        "b_cluster_status": "available_but_guarded",
                        "allocator_focus": "trend_continuation",
                        "allocator_state": "active",
                    },
                },
                "a_strategy_post_cost_edge_validation_available": True,
                "a_strategy_post_cost_edge_validation_summary": {
                    "available": True,
                    "advisory_only": True,
                    "family": "sweep_reversal",
                    "edge_state": "fragile_edge",
                    "validation_bias": "monitor_fragility",
                    "sample_state": "mature",
                    "family_post_cost_rate": 0.375,
                    "weakest_axis": "cost_condition",
                    "weakest_bucket": "high_cost",
                    "confidence": "medium",
                    "summary": "family=sweep_reversal still has usable A-anchor evidence, but fragility is concentrated in cost_condition:high_cost; monitor anchor confidence before treating A as fully stable.",
                    "reason_codes": [
                        "a_edge:fragile_edge",
                        "sample:mature",
                        "weakest_axis:cost_condition",
                    ],
                    "source_summary": {
                        "raw_family_anchor": "sweep_reversal",
                        "family_execution_status": "watch",
                        "sizing_penalty_tier": "soft_clamp",
                    },
                },
                "promotion_governance_available": True,
                "promotion_governance_summary": {
                    "available": True,
                    "advisory_only": True,
                    "family": "trend_continuation",
                    "state": "defer",
                    "promotion_bias": "defer",
                    "target_posture": "keep_current",
                    "confidence": "low",
                    "summary": "family=trend_continuation promotion review should be deferred while guardrails remain active.",
                    "reason_codes": [
                        "promotion_governance:defer",
                        "lifecycle:degraded",
                        "rollout_recommendation:reduce",
                    ],
                    "source_summary": {
                        "lifecycle_state": "degraded",
                        "rollout_recommendation": "reduce",
                        "rollout_maturity": "mature",
                        "positive_expansion_state": "not_ready",
                        "family_execution_status": "manual_review",
                        "condition_modifier_state": "negative",
                        "condition_modifier_axis": "cost_condition",
                        "allocator_tier": "reduce",
                        "capital_pressure": "overallocated_negative",
                    },
                },
                "promotion_review_queue_available": True,
                "promotion_review_queue_summary": {
                    "available": True,
                    "advisory_only": True,
                    "queue_state": "defer_first_queue",
                    "headline_family": "trend_continuation",
                    "top_review_action": "defer_review",
                    "summary": "family=trend_continuation should be reviewed first for defer causes before broader promotion review resumes.",
                    "reason_codes": [
                        "promotion_review_queue:defer_first_queue",
                        "headline_family:trend_continuation",
                        "top_review_action:defer_review",
                    ],
                    "review_queue": [
                        {
                            "family": "trend_continuation",
                            "review_action": "defer_review",
                            "promotion_state": "defer",
                            "target_posture": "keep_current",
                            "priority_rank": 17,
                            "confidence": "low",
                            "summary": "family=trend_continuation should be reviewed for guardrail causes before any promotion discussion.",
                            "reason_codes": ["promotion_governance:defer", "lifecycle:degraded"],
                        }
                    ],
                    "source_summary": {
                        "promotion_ready_count": 0,
                        "defer_count": 1,
                        "hold_count": 0,
                        "thin_sample_count": 0,
                        "top_lifecycle_state": "degraded",
                        "top_promotion_state": "defer",
                        "top_allocator_tier": "reduce",
                    },
                },
                "promotion_remediation_queue_available": True,
                "promotion_remediation_queue_summary": {
                    "available": True,
                    "advisory_only": True,
                    "queue_state": "execution_first_queue",
                    "headline_family": "trend_continuation",
                    "top_remediation_action": "execution_remediation",
                    "summary": "family=trend_continuation should be reviewed first for execution drag and exit or fill guardrails before promotion review resumes.",
                    "reason_codes": [
                        "promotion_remediation_queue:execution_first_queue",
                        "headline_family:trend_continuation",
                        "top_remediation_action:execution_remediation",
                    ],
                    "remediation_queue": [
                        {
                            "family": "trend_continuation",
                            "remediation_action": "execution_remediation",
                            "promotion_state": "defer",
                            "remediation_domain": "execution",
                            "priority_rank": 6,
                            "confidence": "high",
                            "summary": "family=trend_continuation should review execution drag and exit or fill guardrails before reopening promotion review.",
                            "reason_codes": [
                                "promotion_governance:defer",
                                "family_execution:manual_review",
                                "lifecycle:degraded",
                            ],
                        }
                    ],
                    "source_summary": {
                        "execution_first_count": 1,
                        "policy_first_count": 0,
                        "condition_first_count": 0,
                        "observe_count": 0,
                        "thin_sample_count": 0,
                        "top_promotion_state": "defer",
                        "top_review_action": "defer_review",
                        "top_remediation_domain": "execution",
                    },
                },
                "promotion_clearance_tracker_available": True,
                "promotion_clearance_tracker_summary": {
                    "available": True,
                    "advisory_only": True,
                    "family": "trend_continuation",
                    "clearance_state": "blocked",
                    "clearance_bias": "continue_remediation",
                    "confidence": "medium",
                    "summary": "family=trend_continuation clearance remains blocked while active guardrail domains remain unresolved.",
                    "reason_codes": [
                        "promotion_clearance:blocked",
                        "promotion_governance:defer",
                        "remediation_queue:execution_remediation",
                    ],
                    "remaining_guardrail_domains": ["execution", "policy"],
                    "cleared_guardrail_domains": ["condition"],
                    "source_summary": {
                        "promotion_state": "defer",
                        "review_action": "defer_review",
                        "remediation_action": "execution_remediation",
                        "family_execution_status": "manual_review",
                        "rollout_recommendation": "reduce",
                        "lifecycle_state": "degraded",
                        "top_condition_axis": "",
                        "allocator_tier": "reduce",
                    },
                },
                "promotion_reopen_queue_available": True,
                "promotion_reopen_queue_summary": {
                    "available": True,
                    "advisory_only": True,
                    "queue_state": "clearance_first_queue",
                    "headline_family": "trend_continuation",
                    "top_reopen_action": "continue_clearance",
                    "summary": "family=trend_continuation should continue guardrail clearing before promotion review re-opens.",
                    "reason_codes": [
                        "promotion_reopen_queue:clearance_first_queue",
                        "headline_family:trend_continuation",
                        "top_reopen_action:continue_clearance",
                    ],
                    "reopen_queue": [
                        {
                            "family": "trend_continuation",
                            "reopen_action": "continue_clearance",
                            "clearance_state": "blocked",
                            "promotion_state": "defer",
                            "priority_rank": 16,
                            "confidence": "medium",
                            "summary": "family=trend_continuation should continue guardrail clearing before promotion review re-opens.",
                            "reason_codes": [
                                "promotion_reopen_queue:continue_clearance",
                                "promotion_clearance:blocked",
                                "remediation_queue:execution_remediation",
                            ],
                        }
                    ],
                    "source_summary": {
                        "reopen_ready_count": 0,
                        "continue_clearance_count": 1,
                        "observe_count": 0,
                        "thin_sample_count": 0,
                        "top_clearance_state": "blocked",
                        "top_promotion_state": "defer",
                        "top_remediation_action": "execution_remediation",
                    },
                },
                "promotion_decision_brief_available": True,
                "promotion_decision_brief_summary": {
                    "available": True,
                    "advisory_only": True,
                    "family": "trend_continuation",
                    "brief_state": "clearance_required",
                    "decision_bias": "continue_clearance",
                    "target_posture": "keep_current",
                    "confidence": "medium",
                    "summary": "family=trend_continuation still needs guardrail clearing before promotion review should be reopened.",
                    "reason_codes": [
                        "promotion_decision_brief:clearance_required",
                        "promotion_clearance:blocked",
                        "promotion_reopen_queue:continue_clearance",
                    ],
                    "source_summary": {
                        "governance_state": "defer",
                        "review_action": "defer_review",
                        "remediation_action": "execution_remediation",
                        "clearance_state": "blocked",
                        "reopen_action": "continue_clearance",
                        "family_execution_status": "manual_review",
                        "lifecycle_state": "degraded",
                        "positive_expansion_state": "not_ready",
                        "allocator_tier": "reduce",
                    },
                },
                "auto_promotion_rollout_execution_available": True,
                "auto_promotion_rollout_execution_summary": {
                    "available": True,
                    "advisory_only": True,
                    "execution_stage": "auto_execution_blocked",
                    "execution_bias": "block_auto_execution",
                    "action_domain": "no_write_observe",
                    "target_family": "trend_continuation",
                    "target_posture": "keep_current",
                    "write_scope": "none",
                    "dry_run_only": False,
                    "confidence": "low",
                    "summary": "family=trend_continuation auto execution remains blocked; keep governance changes advisory-only until guardrails clear.",
                    "reason_codes": [
                        "auto_execution:auto_execution_blocked",
                        "promotion_decision_brief:clearance_required",
                        "promotion_reopen_queue:continue_clearance",
                        "execution_guardrail:manual_review",
                    ],
                    "source_summary": {
                        "promotion_state": "defer",
                        "brief_state": "clearance_required",
                        "reopen_action": "continue_clearance",
                        "clearance_state": "blocked",
                        "remediation_action": "execution_remediation",
                        "rollout_recommendation": "reduce",
                        "lifecycle_state": "degraded",
                        "family_execution_status": "manual_review",
                        "mode_state": "watch",
                        "approval_penalty_status": "manual_review",
                        "positive_expansion_state": "not_ready",
                        "governance_target_posture": "keep_current",
                    },
                },
                "promotion_lifecycle_history_available": True,
                "promotion_lifecycle_history_summary": {
                    "available": True,
                    "advisory_only": True,
                    "family": "trend_continuation",
                    "history_state": "history_attention_required",
                    "latest_event_type": "remediation_started",
                    "latest_event_ts": "2026-03-23T00:00:00+00:00",
                    "event_count_30d": 3,
                    "recent_transitions": [
                        "defer -> execution_remediation",
                        "defer -> blocked",
                        "blocked -> continue_clearance",
                    ],
                    "summary": "family=trend_continuation history still points to active remediation or blocked clearance before promotion can progress.",
                    "reason_codes": [
                        "history:history_attention_required",
                        "latest_event:remediation_started",
                        "history_event:remediation_started",
                    ],
                    "source_summary": {
                        "latest_source_key": "promotion_remediation_queue",
                        "latest_bias": "continue_remediation",
                        "latest_state_from": "defer",
                        "latest_state_to": "execution_remediation",
                    },
                },
                "research_promotion_operating_loop_available": True,
                "research_promotion_operating_loop_summary": {
                    "available": True,
                    "advisory_only": True,
                    "family": "trend_continuation",
                    "loop_state": "shadow_test_ready",
                    "loop_bias": "queue_shadow_test",
                    "target_stage": "tested",
                    "recommended_action": "run_shadow_exit_review",
                    "shadow_experiment_id": "shadow_exit_review_family",
                    "watchlist_ready": False,
                    "confidence": "medium",
                    "summary": "family=trend_continuation has a concrete shadow-test path; queue the research test before any probation or promotion move.",
                    "reason_codes": [
                        "research_loop:shadow_test_ready",
                        "target_stage:tested",
                        "governance:defer",
                    ],
                    "source_summary": {
                        "recommended_scope": "family",
                        "recommended_bucket": "trend_continuation",
                        "watchlist_not_ready_reason": "thin_sample",
                        "governance_state": "defer",
                        "governance_target_posture": "keep_current",
                        "brief_state": "clearance_required",
                        "execution_stage": "auto_execution_blocked",
                        "history_state": "history_attention_required",
                        "family_execution_status": "manual_review",
                        "strategy_cluster_status": "available_but_guarded",
                    },
                },
                "positive_evidence_expansion_available": True,
                "positive_evidence_expansion_summary": {
                    "available": True,
                    "advisory_only": True,
                    "family": "trend_continuation",
                    "state": "not_ready",
                    "expansion_bias": "do_not_expand",
                    "confidence": "low",
                    "summary": "family=trend_continuation is not ready for positive expansion language because evidence or execution guardrails remain incomplete.",
                    "reason_codes": [
                        "positive_expansion:not_ready",
                        "family_execution:manual_review",
                        "rollout_recommendation:reduce",
                        "lifecycle:degraded",
                    ],
                    "source_summary": {
                        "family_closed": 10,
                        "family_post_cost_rate": 0.2,
                        "family_execution_status": "manual_review",
                        "family_mode_advisory_state": "watch",
                        "rollout_recommendation": "reduce",
                        "rollout_maturity": "mature",
                        "lifecycle_state": "degraded",
                        "allocator_tier": "reduce",
                        "modifier_state": "negative",
                    },
                },
                "outcome_bucket_granularity_available": True,
                "outcome_bucket_granularity_summary": {
                    "available": True,
                    "advisory_only": True,
                    "family_focus": {
                        "key": "trend_continuation",
                        "closed": 8,
                        "baseline_cost_profitable_rate_from_closed": 0.25,
                    },
                    "top_condition_axis": "cost_condition",
                    "top_condition_bucket": {
                        "key": "high_cost",
                        "closed": 4,
                        "baseline_cost_profitable_rate_from_closed": 0.25,
                    },
                    "confidence": "medium",
                    "summary": "family=trend_continuation shows the largest post-cost split in high_cost; review cost-sensitive buckets before changing thresholds.",
                    "condition_axes": [
                        {"axis": "cost_condition", "divergence": 0.22},
                        {"axis": "liquidity_condition", "divergence": 0.05, "proxy_note": "liquidity_proxy"},
                    ],
                },
                "opportunity_capture_available": True,
                "opportunity_capture_summary": {
                    "available": True,
                    "advisory_only": True,
                    "summary": "throughput is constrained more by blocking than by fill failure; family focus is trend_continuation",
                    "capture_gap": {
                        "runtime_to_submit_gap": 0.8,
                        "submit_to_fill_gap": 0.2,
                        "fill_to_close_gap": 0.1,
                    },
                    "dominant_bottleneck": {
                        "stage": "runtime_to_submit",
                        "reason": "quality_blocking",
                    },
                    "family_focus": {
                        "key": "trend_continuation",
                        "runtime_candidates": 6,
                        "submitted": 1,
                    },
                    "blocked_mix": {"quality": 3, "rollout": 1, "structural": 0, "safety": 0, "unknown": 0},
                },
                "capital_allocator_available": True,
                "capital_allocator_summary": {
                    "available": True,
                    "advisory_only": False,
                    "allocator_state": "active",
                    "family_focus": "trend_continuation",
                    "capital_pressure": "overallocated_negative",
                    "summary": "negative family concentration is already high; review capital allocation before adding more risk",
                    "family_weights": [
                        {
                            "family": "trend_continuation",
                            "tier": "reduce",
                            "allocation_weight": 0.7,
                            "allocated_risk_r": 0.375,
                            "capital_pressure": "overallocated_negative",
                        }
                    ],
                },
            },
            "validation_alert": None,
            "strategy_v2_pbo_dsr_design": {
                "design_ready": True,
                "available": False,
                "implementation_status": "design_ready_not_computed",
            },
        },
        alert_metrics={
            "overall": {
                "slo": {"status": "PASS"},
                "error_budget": {"status": "PASS"},
            },
            "channel_metrics": {
                "discord": {
                    "slo": {"status": "PASS"},
                    "error_budget": {"status": "PASS"},
                }
            },
            "circuit_state": {
                "discord": {
                    "open_targets": 0,
                }
            },
            "retry_queue": {
                "counts": {"queued": 0, "dead_letter": 0},
                "backlog_age_seconds": 0,
            },
        },
        outbox_status={
            "counts": {"pending": 0, "failed": 0},
            "backlog_age_seconds": 0,
            "retry_policy": {},
        },
        strategy_metrics={
            "risk_state": "OPEN",
            "risk_reason": "normal",
            "operating_lock": {
                "active": False,
                "current_session": {"name": "london", "active": True},
            },
        },
        portfolio_budget={
            "deployment_go_no_go": "GO",
            "deployment_code": "go_runtime_gate_open",
            "deployment_message": "GO: runtime gate is open for candidate review.",
            "playbook_go_no_go": "GO",
            "playbook_code": "go_portfolio_runtime_ready",
            "playbook_action": "continue_candidate_review_under_portfolio_caps",
            "playbook_message": "GO: runtime gate is open and portfolio headroom review can proceed under current caps.",
            "current_exposure": {"active_thesis_clusters": 0},
            "blocked_reason_counts": {},
            "strategy_mode": "A_ONLY",
        },
        execution_quality={
            "plans_matured": 4,
            "fill_events_total": 2,
            "fill_rate": 0.5,
            "report_path": "reports/execution/test.md",
        },
        alert_test_lookback_hours=24,
        write_report=True,
    )

    assert payload["overall_status"] == "FAIL"
    assert payload["deployment_go_no_go"] == "NO_GO"
    assert payload["deployment_code"] == "no_go_operational_checklist_blocking_items"
    assert payload["playbook_go_no_go"] == "NO_GO"
    assert payload["playbook_code"] == "no_go_operational_checklist_blocking_items"
    assert payload["playbook_action"] == "clear_blocking_operational_items_before_rollout"
    assert payload["blocking_failures"] == 0
    assert payload["manual_actions"] == 1
    path = Path(payload["report_path"])
    assert path.exists()
    body = path.read_text(encoding="utf-8")
    assert "Operational Checklist" in body
    assert "deployment_go_no_go: NO_GO" in body
    assert "## Approval Strip" in body
    assert "- approve=validation/checklist no_go | align=aligned | act=clear_blocking_operational_items_before_rollout | priority=urgent" in body
    assert payload["approval_strip_summary"]["approve_value"] == "validation/checklist no_go"
    assert payload["approval_strip_summary"]["align_value"] == "aligned"
    assert payload["approval_strip_summary"]["act_value"] == "clear_blocking_operational_items_before_rollout"
    assert payload["approval_strip_summary"]["act_priority_level"] == "urgent"
    assert any(item["item_id"] == "alert_test_recent" and item["status"] == "PASS" for item in payload["checks"])
    assert any(item["item_id"] == "session_guidance" and item["status"] == "PASS" for item in payload["checks"])
    assert any(
        item["item_id"] == "execution_degradation_advisory" and item["status"] == "PASS"
        for item in payload["checks"]
    )
    operator_action_item = next(item for item in payload["checks"] if item["item_id"] == "operator_action_priority")
    assert operator_action_item["status"] == "WARN"
    assert operator_action_item["blocking"] is False
    assert operator_action_item["evidence"]["top_action"] == "review_runtime_execution_drag_before_expansion"
    assert operator_action_item["evidence"]["top_action_followup_command"] == ""
    assert operator_action_item["evidence"]["priority_source"] == "execution_degradation"
    assert operator_action_item["evidence"]["action_family"] == "execution_review"
    assert operator_action_item["evidence"]["capture_context"]["family_focus"]["key"] == "trend_continuation"
    assert operator_action_item["evidence"]["experiment_context"]["entry_timing_target"]["symbol"] == "BTCUSDC"
    assert operator_action_item["evidence"]["experiment_context"]["entry_timing_target"]["followup_command"].endswith(
        "--symbol BTCUSDC --universe usdc_perp_top30 --days 7 --action run_entry_timing_split_review"
    )
    assert operator_action_item["evidence"]["experiment_context"]["execution_style_target"]["symbol"] == "BTCUSDC"
    assert operator_action_item["evidence"]["experiment_context"]["execution_style_target"]["followup_command"].endswith(
        "--symbol BTCUSDC --universe usdc_perp_top30 --days 7 --action run_execution_style_split_review"
    )
    assert operator_action_item["evidence"]["next_actions"][0]["followup_command"] == ""
    outcome_control_item = next(item for item in payload["checks"] if item["item_id"] == "outcome_control_trace")
    assert outcome_control_item["status"] == "WARN"
    assert outcome_control_item["blocking"] is False
    assert outcome_control_item["evidence"]["approval_penalty_tier"] == "downgrade_to_manual"
    money_funnel_item = next(item for item in payload["checks"] if item["item_id"] == "money_funnel")
    assert money_funnel_item["status"] == "WARN"
    assert money_funnel_item["blocking"] is False
    assert money_funnel_item["evidence"]["historical_gap_r"]["submitted_to_filled"] == 0.33
    assert money_funnel_item["evidence"]["historical_gap_r"]["closed_expected_to_post_cost_realized"] == -0.24
    outcome_attribution_item = next(item for item in payload["checks"] if item["item_id"] == "outcome_attribution")
    assert outcome_attribution_item["status"] == "WARN"
    assert outcome_attribution_item["blocking"] is False
    assert outcome_attribution_item["evidence"]["strongest_drag_source"] == "fill_capture_gap"
    assert outcome_attribution_item["evidence"]["fill_capture_gap_r"] == 0.33
    assert outcome_attribution_item["evidence"]["closed_post_cost_delta_r"] == -0.24
    edge_experiment_item = next(item for item in payload["checks"] if item["item_id"] == "edge_experiment_review")
    assert edge_experiment_item["status"] == "WARN"
    assert edge_experiment_item["blocking"] is False
    assert edge_experiment_item["evidence"]["edge_state"] == "watch_edge"
    assert edge_experiment_item["evidence"]["true_edge_ratio"] == 0.75
    assert edge_experiment_item["evidence"]["entry_timing_preferred_variant"] == "early_limit"
    assert edge_experiment_item["evidence"]["execution_style_preferred_variant"] == "passive_limit"
    edge_evolution_item = next(item for item in payload["checks"] if item["item_id"] == "edge_evolution_rule")
    assert edge_evolution_item["status"] == "WARN"
    assert edge_evolution_item["blocking"] is False
    assert edge_evolution_item["evidence"]["recommended_action"] == "reduce_baseline_allocation_review"
    assert edge_evolution_item["evidence"]["allocation_bias"] == "reduce_baseline"
    review_followup_item = next(item for item in payload["checks"] if item["item_id"] == "review_followup_ledger")
    assert review_followup_item["status"] == "PASS"
    assert review_followup_item["blocking"] is False
    assert review_followup_item["evidence"]["available"] is False
    assert review_followup_item["evidence"]["last_status"] == "none"
    rollout_item = next(item for item in payload["checks"] if item["item_id"] == "rollout_recommendation")
    assert rollout_item["status"] == "MANUAL"
    assert rollout_item["blocking"] is True
    assert rollout_item["evidence"]["recommendation"] == "reduce"
    lifecycle_item = next(item for item in payload["checks"] if item["item_id"] == "strategy_lifecycle")
    assert lifecycle_item["status"] == "WARN"
    assert lifecycle_item["blocking"] is False
    assert lifecycle_item["evidence"]["state"] == "degraded"
    assert lifecycle_item["evidence"]["transition_bias"] == "degrade"
    multi_strategy_item = next(item for item in payload["checks"] if item["item_id"] == "multi_strategy_ab_expansion")
    assert multi_strategy_item["status"] == "WARN"
    assert multi_strategy_item["blocking"] is False
    assert multi_strategy_item["evidence"]["mode"] == "A_PLUS_B"
    assert multi_strategy_item["evidence"]["b_cluster"]["strategy_cluster_status"] == "available_but_guarded"
    b_activation_item = next(item for item in payload["checks"] if item["item_id"] == "b_continuation_activation")
    assert b_activation_item["status"] == "WARN"
    assert b_activation_item["blocking"] is False
    assert b_activation_item["evidence"]["family"] == "trend_continuation"
    assert b_activation_item["evidence"]["activation_state"] == "blocked"
    assert b_activation_item["evidence"]["activation_bias"] == "clear_guardrails"
    friction_item = next(item for item in payload["checks"] if item["item_id"] == "execution_friction_measurement")
    assert friction_item["status"] == "WARN"
    assert friction_item["blocking"] is False
    assert friction_item["evidence"]["friction_state"] == "watch_friction"
    assert friction_item["evidence"]["friction_bias"] == "monitor_execution_drag"
    assert friction_item["evidence"]["weakest_axis"] == "slippage_state"
    generalization_item = next(
        item for item in payload["checks"] if item["item_id"] == "forward_stress_regime_validation"
    )
    assert generalization_item["status"] == "WARN"
    assert generalization_item["blocking"] is False
    assert generalization_item["evidence"]["validation_state"] == "fragile_generalization"
    assert generalization_item["evidence"]["validation_bias"] == "monitor_regime_stress_fragility"
    assert generalization_item["evidence"]["weakest_axis"] == "stress_state"
    kill_condition_item = next(item for item in payload["checks"] if item["item_id"] == "kill_condition_automation")
    assert kill_condition_item["status"] == "WARN"
    assert kill_condition_item["blocking"] is False
    assert kill_condition_item["evidence"]["kill_condition_state"] == "close_only_review"
    assert kill_condition_item["evidence"]["automation_bias"] == "propose_close_only"
    assert kill_condition_item["evidence"]["trigger_axis"] == "reconciliation_axis"
    b_edge_item = next(item for item in payload["checks"] if item["item_id"] == "b_continuation_edge_validation")
    assert b_edge_item["status"] == "WARN"
    assert b_edge_item["blocking"] is False
    assert b_edge_item["evidence"]["raw_family"] == "trend_continuation"
    assert b_edge_item["evidence"]["edge_state"] == "fragile_edge"
    assert b_edge_item["evidence"]["validation_bias"] == "monitor_diversification"
    cluster_balance_item = next(item for item in payload["checks"] if item["item_id"] == "strategy_cluster_balance")
    assert cluster_balance_item["status"] == "WARN"
    assert cluster_balance_item["blocking"] is False
    assert cluster_balance_item["evidence"]["mode"] == "A_PLUS_B"
    assert cluster_balance_item["evidence"]["balance_state"] == "a_concentrated"
    assert cluster_balance_item["evidence"]["balance_bias"] == "preserve_a_anchor"
    a_edge_item = next(item for item in payload["checks"] if item["item_id"] == "a_strategy_post_cost_edge_validation")
    assert a_edge_item["status"] == "WARN"
    assert a_edge_item["blocking"] is False
    assert a_edge_item["evidence"]["family"] == "sweep_reversal"
    assert a_edge_item["evidence"]["edge_state"] == "fragile_edge"
    assert a_edge_item["evidence"]["validation_bias"] == "monitor_fragility"
    promotion_item = next(item for item in payload["checks"] if item["item_id"] == "promotion_governance")
    assert promotion_item["status"] == "WARN"
    assert promotion_item["blocking"] is False
    assert promotion_item["evidence"]["state"] == "defer"
    assert promotion_item["evidence"]["promotion_bias"] == "defer"
    assert promotion_item["evidence"]["target_posture"] == "keep_current"
    promotion_queue_item = next(item for item in payload["checks"] if item["item_id"] == "promotion_review_queue")
    assert promotion_queue_item["status"] == "WARN"
    assert promotion_queue_item["blocking"] is False
    assert promotion_queue_item["evidence"]["queue_state"] == "defer_first_queue"
    assert promotion_queue_item["evidence"]["headline_family"] == "trend_continuation"
    assert promotion_queue_item["evidence"]["top_review_action"] == "defer_review"
    remediation_queue_item = next(
        item for item in payload["checks"] if item["item_id"] == "promotion_remediation_queue"
    )
    assert remediation_queue_item["status"] == "WARN"
    assert remediation_queue_item["blocking"] is False
    assert remediation_queue_item["evidence"]["queue_state"] == "execution_first_queue"
    assert remediation_queue_item["evidence"]["headline_family"] == "trend_continuation"
    assert remediation_queue_item["evidence"]["top_remediation_action"] == "execution_remediation"
    clearance_item = next(item for item in payload["checks"] if item["item_id"] == "promotion_clearance_tracker")
    assert clearance_item["status"] == "WARN"
    assert clearance_item["blocking"] is False
    assert clearance_item["evidence"]["family"] == "trend_continuation"
    assert clearance_item["evidence"]["clearance_state"] == "blocked"
    assert clearance_item["evidence"]["clearance_bias"] == "continue_remediation"
    reopen_item = next(item for item in payload["checks"] if item["item_id"] == "promotion_reopen_queue")
    assert reopen_item["status"] == "WARN"
    assert reopen_item["blocking"] is False
    assert reopen_item["evidence"]["queue_state"] == "clearance_first_queue"
    assert reopen_item["evidence"]["headline_family"] == "trend_continuation"
    assert reopen_item["evidence"]["top_reopen_action"] == "continue_clearance"
    brief_item = next(item for item in payload["checks"] if item["item_id"] == "promotion_decision_brief")
    assert brief_item["status"] == "WARN"
    assert brief_item["blocking"] is False
    assert brief_item["evidence"]["family"] == "trend_continuation"
    assert brief_item["evidence"]["brief_state"] == "clearance_required"
    assert brief_item["evidence"]["decision_bias"] == "continue_clearance"
    auto_execution_item = next(
        item for item in payload["checks"] if item["item_id"] == "auto_promotion_rollout_execution"
    )
    assert auto_execution_item["status"] == "WARN"
    assert auto_execution_item["blocking"] is False
    assert auto_execution_item["evidence"]["execution_stage"] == "auto_execution_blocked"
    assert auto_execution_item["evidence"]["execution_bias"] == "block_auto_execution"
    assert auto_execution_item["evidence"]["target_family"] == "trend_continuation"
    history_item = next(item for item in payload["checks"] if item["item_id"] == "promotion_lifecycle_history")
    assert history_item["status"] == "WARN"
    assert history_item["blocking"] is False
    assert history_item["evidence"]["family"] == "trend_continuation"
    assert history_item["evidence"]["history_state"] == "history_attention_required"
    assert history_item["evidence"]["latest_event_type"] == "remediation_started"
    research_loop_item = next(
        item for item in payload["checks"] if item["item_id"] == "research_promotion_operating_loop"
    )
    assert research_loop_item["status"] == "WARN"
    assert research_loop_item["blocking"] is False
    assert research_loop_item["evidence"]["family"] == "trend_continuation"
    assert research_loop_item["evidence"]["loop_state"] == "shadow_test_ready"
    assert research_loop_item["evidence"]["target_stage"] == "tested"
    positive_expansion_item = next(
        item for item in payload["checks"] if item["item_id"] == "positive_evidence_expansion"
    )
    assert positive_expansion_item["status"] == "WARN"
    assert positive_expansion_item["blocking"] is False
    assert positive_expansion_item["evidence"]["state"] == "not_ready"
    assert positive_expansion_item["evidence"]["expansion_bias"] == "do_not_expand"
    granularity_item = next(item for item in payload["checks"] if item["item_id"] == "outcome_bucket_granularity")
    assert granularity_item["status"] == "WARN"
    assert granularity_item["blocking"] is False
    assert granularity_item["evidence"]["top_condition_axis"] == "cost_condition"
    assert granularity_item["evidence"]["top_condition_bucket"]["key"] == "high_cost"
    opportunity_item = next(item for item in payload["checks"] if item["item_id"] == "opportunity_capture")
    assert opportunity_item["status"] == "WARN"
    assert opportunity_item["blocking"] is False
    assert opportunity_item["evidence"]["dominant_bottleneck"]["reason"] == "quality_blocking"
    capital_allocator_item = next(item for item in payload["checks"] if item["item_id"] == "capital_allocator")
    assert capital_allocator_item["status"] == "WARN"
    assert capital_allocator_item["blocking"] is False
    assert capital_allocator_item["evidence"]["family_focus"] == "trend_continuation"
    assert capital_allocator_item["evidence"]["capital_pressure"] == "overallocated_negative"
    portfolio_item = next(item for item in payload["checks"] if item["item_id"] == "portfolio_headroom")
    assert portfolio_item["evidence"]["deployment_go_no_go"] == "GO"
    assert portfolio_item["evidence"]["deployment_code"] == "go_runtime_gate_open"
    assert portfolio_item["evidence"]["playbook_go_no_go"] == "GO"
    assert portfolio_item["evidence"]["playbook_code"] == "go_portfolio_runtime_ready"
    assert portfolio_item["evidence"]["playbook_action"] == "continue_candidate_review_under_portfolio_caps"


def test_operational_checklist_marks_missing_alert_test_as_manual() -> None:
    settings = Settings(alert_discord_webhook_url="https://discord.example/webhook")
    service = OperationalChecklistService(alert_repo=_AlertRepoStub([]), settings=settings)

    payload = service.generate(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        strategy_version="v1",
        ready=ReadySnapshot(status="ready", checks={"db": True}, details={"db": "ok"}),
        validation_payload={
            "validation_report": {
                "status": "PASS",
                "operator_action_priority_summary": {
                    "available": False,
                },
            },
            "validation_alert": None,
            "strategy_v2_pbo_dsr_design": {"design_ready": True, "available": False},
        },
        alert_metrics={
            "overall": {"slo": {"status": "INSUFFICIENT_DATA"}, "error_budget": {"status": "INSUFFICIENT_DATA"}},
            "channel_metrics": {},
            "circuit_state": {},
            "retry_queue": {"counts": {"queued": 0, "dead_letter": 0}, "backlog_age_seconds": 0},
        },
        outbox_status={"counts": {"pending": 0, "failed": 0}, "backlog_age_seconds": 0, "retry_policy": {}},
        strategy_metrics={"risk_state": "OPEN", "risk_reason": "normal", "operating_lock": {"active": False}},
        portfolio_budget={
            "deployment_go_no_go": "GO",
            "deployment_code": "go_runtime_gate_open",
            "deployment_message": "GO: runtime gate is open for candidate review.",
            "current_exposure": {"active_thesis_clusters": 0},
            "blocked_reason_counts": {},
            "strategy_mode": "A_ONLY",
        },
        execution_quality={"plans_matured": 0, "fill_events_total": 0},
        alert_test_lookback_hours=24,
        write_report=False,
    )

    alert_test_item = next(item for item in payload["checks"] if item["item_id"] == "alert_test_recent")
    assert alert_test_item["status"] == "MANUAL"
    assert payload["overall_status"] == "FAIL"
    assert payload["deployment_go_no_go"] == "NO_GO"
    assert payload["deployment_code"] == "no_go_operational_checklist_blocking_items"
    assert payload["playbook_go_no_go"] == "NO_GO"
    assert payload["playbook_code"] == "no_go_operational_checklist_blocking_items"
    assert payload["playbook_action"] == "clear_blocking_operational_items_before_rollout"


def test_operational_checklist_downgrades_missing_alert_test_when_recent_validation_alert_delivered() -> None:
    settings = Settings(alert_discord_webhook_url="https://discord.example/webhook")
    service = OperationalChecklistService(alert_repo=_AlertRepoStub([]), settings=settings)
    now = datetime.now(timezone.utc).replace(microsecond=0)

    payload = service.generate(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        strategy_version="v1",
        ready=ReadySnapshot(status="ready", checks={"db": True}, details={"db": "ok"}),
        validation_payload={
            "validation_report": {
                "status": "WARN",
                "approval_strip_summary": {
                    "approve_value": "manual review first",
                    "approve_reason": "alignment warning remains",
                    "align_value": "playbook_drift",
                    "align_reason": "template warning",
                    "act_value": "continue_candidate_review_under_portfolio_caps",
                    "act_reason": "continue under caps",
                    "act_priority_level": "urgent",
                },
                "operator_action_priority_summary": {
                    "available": False,
                },
            },
            "deployment_go_no_go": "MANUAL_REVIEW",
            "deployment_code": "manual_review_alignment_warning",
            "deployment_message": "MANUAL REVIEW: alignment warning remains.",
            "playbook_go_no_go": "MANUAL_REVIEW",
            "playbook_code": "manual_review_alignment_warning",
            "playbook_action": "hold_rollout_and_review_alignment_details",
            "playbook_message": "MANUAL REVIEW: alignment warning remains.",
            "validation_alert": {
                "emitted": True,
                "delivery": {
                    "channel": "discord",
                    "delivered": True,
                    "skipped": False,
                    "reason": "ok",
                },
            },
            "strategy_v2_pbo_dsr_design": {"design_ready": True, "available": False},
        },
        alert_metrics={
            "overall": {"slo": {"status": "PASS"}, "error_budget": {"status": "PASS"}},
            "channel_metrics": {},
            "circuit_state": {},
            "retry_queue": {"counts": {"queued": 0, "dead_letter": 0}, "backlog_age_seconds": 0},
            "latest_validation_alert": {
                "available": True,
                "alert_id": "val_warn_test",
                "channel": "discord",
                "delivery_channel": "discord",
                "triggered_ts": now.isoformat(),
                "status": "WARN",
                "delivered": True,
                "skipped": False,
                "failed": False,
            },
        },
        outbox_status={"counts": {"pending": 0, "failed": 0}, "backlog_age_seconds": 0, "retry_policy": {}},
        strategy_metrics={"risk_state": "OPEN", "risk_reason": "normal", "operating_lock": {"active": False}},
        portfolio_budget={
            "deployment_go_no_go": "GO",
            "deployment_code": "go_runtime_gate_open",
            "deployment_message": "GO: runtime gate is open for candidate review.",
            "current_exposure": {"active_thesis_clusters": 0},
            "blocked_reason_counts": {},
            "strategy_mode": "A_ONLY",
        },
        execution_quality={"plans_matured": 0, "fill_events_total": 0},
        alert_test_lookback_hours=24,
        write_report=False,
    )

    alert_test_item = next(item for item in payload["checks"] if item["item_id"] == "alert_test_recent")
    assert alert_test_item["status"] == "WARN"
    assert alert_test_item["blocking"] is False
    assert alert_test_item["evidence"]["recent_live_delivery"]["discord"]["source"] == "recent_validation_alert_delivery"
    assert payload["manual_actions"] == 0
    assert payload["deployment_go_no_go"] == "MANUAL_REVIEW"
    assert payload["approval_strip_summary"]["approve_value"] == "manual review first"


def test_operational_checklist_marks_dead_session_as_warn_non_blocking() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    settings = Settings(alert_discord_webhook_url="https://discord.example/webhook")
    alerts = [
        AlertSubscription(
            alert_id="alert_test_discord_dead_session",
            plan_id=None,
            symbol="BTCUSDC",
            channel="discord",
            type="test",
            payload={
                "delivery": {
                    "channel": "discord",
                    "delivered": True,
                    "skipped": False,
                    "reason": "ok",
                    "attempts": 1,
                    "latency_ms": 110.0,
                }
            },
            triggered_ts=now - timedelta(hours=1),
        )
    ]
    service = OperationalChecklistService(alert_repo=_AlertRepoStub(alerts), settings=settings)

    payload = service.generate(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        strategy_version="v1",
        ready=ReadySnapshot(status="ready", checks={"db": True}, details={"db": "ok"}),
        validation_payload={
            "validation_report": {
                "status": "PASS",
                "operator_action_priority_summary": {
                    "available": True,
                    "top_action": "softening_review",
                    "top_reason": "research-only next step",
                    "priority_level": "research",
                    "supporting_signals": [],
                    "blocking_signals": [],
                    "next_actions": [],
                    "advisory_only": True,
                },
            },
            "validation_alert": None,
            "strategy_v2_pbo_dsr_design": {"design_ready": True, "available": False},
            "strategy_v2_pbo_dsr_artifact_store": {"artifact_store_ready": True, "available": False},
        },
        alert_metrics={
            "overall": {"slo": {"status": "PASS"}, "error_budget": {"status": "PASS"}},
            "channel_metrics": {"discord": {"slo": {"status": "PASS"}, "error_budget": {"status": "PASS"}}},
            "circuit_state": {"discord": {"open_targets": 0}},
            "retry_queue": {"counts": {"queued": 0, "dead_letter": 0}, "backlog_age_seconds": 0},
        },
        outbox_status={"counts": {"pending": 0, "failed": 0}, "backlog_age_seconds": 0, "retry_policy": {}},
        strategy_metrics={
            "risk_state": "OPEN",
            "risk_reason": "normal",
            "operating_lock": {
                "active": False,
                "scope": "none",
                "strategy_mode": "A_ONLY",
                "current_session": {"name": "inactive", "active": False, "start": "", "end": ""},
            },
        },
        portfolio_budget={
            "deployment_go_no_go": "MANUAL_REVIEW",
            "deployment_code": "manual_review_risk_gate_throttled",
            "deployment_message": "MANUAL_REVIEW: runtime risk gate is throttled (jump_guard_active). Reduce size and review before acting.",
            "playbook_go_no_go": "MANUAL_REVIEW",
            "playbook_code": "manual_review_portfolio_risk_gate_throttled",
            "playbook_action": "review_throttled_gate_and_reduce_size",
            "playbook_message": "MANUAL_REVIEW: runtime risk gate is throttled. Review headroom and reduce size before acting.",
            "current_exposure": {"active_thesis_clusters": 0},
            "blocked_reason_counts": {},
            "strategy_mode": "A_ONLY",
        },
        execution_quality={"plans_matured": 2, "fill_events_total": 1},
        alert_test_lookback_hours=24,
        write_report=False,
    )

    session_item = next(item for item in payload["checks"] if item["item_id"] == "session_guidance")
    assert session_item["status"] == "WARN"
    assert session_item["blocking"] is False
    assert session_item["evidence"]["dead_session"] is True
    assert payload["deployment_go_no_go"] == "MANUAL_REVIEW"


def test_operational_checklist_surfaces_validation_alert_deployment_evidence() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    settings = Settings(alert_discord_webhook_url="https://discord.example/webhook")
    service = OperationalChecklistService(alert_repo=_AlertRepoStub([]), settings=settings)

    validation_alert = {
        "emitted": True,
        "type": "validation_warn",
        "status": "WARN",
        "channel": "discord",
        "deployment_go_no_go": "NO_GO",
        "deployment_code": "no_go_proxy_selected_trial_against_replay_backed_worst_scenario",
        "deployment_message": (
            "NO-GO: runtime proxy selected-trial is still active while replay-backed downside is worse."
        ),
        "approval_playbook_go_no_go": "NO_GO",
        "approval_playbook_code": "no_go_proxy_selected_trial_against_replay_backed_worst_scenario",
        "approval_playbook_action": "hold_live_rollout_and_keep_prototype_path",
        "approval_playbook_message": (
            "NO-GO: runtime proxy selected-trial is still active while replay-backed downside is worse. "
            "Keep rollout blocked and do not treat this setup as threshold-lineage confirmed."
        ),
        "approval_topline_summary_line": (
            "winner=runtime_proxy/runtime_validation_proxy_v1; "
            "worst=shock_concentration/FAIL/replay_output; promotion=stay_on_prototype"
        ),
        "delivery": {
            "channel": "discord",
            "delivered": True,
            "skipped": False,
            "reason": "delivered",
            "attempts": 1,
            "latency_ms": 110.0,
        },
        "retry_queued": 0,
    }

    payload = service.generate(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        strategy_version="v2",
        ready=ReadySnapshot(status="ready", checks={"db": True}, details={"db": "ok"}),
        validation_payload={
            "validation_report": {"status": "WARN", "path": "reports/validation/test.md", "generated_at": now.isoformat()},
            "validation_alert": validation_alert,
            "strategy_v2_pbo_dsr_design": {"design_ready": True, "available": False},
        },
        alert_metrics={
            "overall": {"slo": {"status": "PASS"}, "error_budget": {"status": "PASS"}},
            "channel_metrics": {"discord": {"slo": {"status": "PASS"}, "error_budget": {"status": "PASS"}}},
            "circuit_state": {"discord": {"open_targets": 0}},
            "latest_validation_alert": {
                "available": True,
                "deployment_go_no_go": "NO_GO",
                "deployment_code": "no_go_proxy_selected_trial_against_replay_backed_worst_scenario",
                "deployment_message": (
                    "NO-GO: runtime proxy selected-trial is still active while replay-backed downside is worse."
                ),
                "approval_playbook_go_no_go": "NO_GO",
                "approval_playbook_code": "no_go_proxy_selected_trial_against_replay_backed_worst_scenario",
                "approval_playbook_action": "hold_live_rollout_and_keep_prototype_path",
            },
            "retry_queue": {"counts": {"queued": 0, "dead_letter": 0}, "backlog_age_seconds": 0},
        },
        outbox_status={"counts": {"pending": 0, "failed": 0}, "backlog_age_seconds": 0, "retry_policy": {}},
        strategy_metrics={
            "risk_state": "OPEN",
            "risk_reason": "normal",
            "operating_lock": {
                "active": False,
                "scope": "none",
                "strategy_mode": "A_ONLY",
                "current_session": {
                    "name": "london",
                    "active": True,
                    "start": (now - timedelta(hours=1)).isoformat(),
                    "end": (now + timedelta(hours=1)).isoformat(),
                },
            },
        },
        portfolio_budget={"current_exposure": {"active_thesis_clusters": 0}, "blocked_reason_counts": {}, "strategy_mode": "A_ONLY"},
        execution_quality={"plans_matured": 2, "fill_events_total": 1},
        alert_test_lookback_hours=24,
        write_report=False,
    )

    validation_item = next(item for item in payload["checks"] if item["item_id"] == "validation_alert_delivery")
    assert validation_item["evidence"]["deployment_go_no_go"] == "NO_GO"
    assert validation_item["evidence"]["deployment_code"] == "no_go_proxy_selected_trial_against_replay_backed_worst_scenario"
    assert validation_item["evidence"]["approval_playbook_go_no_go"] == "NO_GO"
    assert (
        validation_item["evidence"]["approval_playbook_code"]
        == "no_go_proxy_selected_trial_against_replay_backed_worst_scenario"
    )
    assert validation_item["evidence"]["approval_playbook_action"] == "hold_live_rollout_and_keep_prototype_path"

    slo_item = next(item for item in payload["checks"] if item["item_id"] == "alert_channel_slo")
    assert slo_item["evidence"]["latest_validation_alert"]["deployment_go_no_go"] == "NO_GO"
    assert (
        slo_item["evidence"]["latest_validation_alert"]["deployment_code"]
        == "no_go_proxy_selected_trial_against_replay_backed_worst_scenario"
    )
    assert slo_item["evidence"]["latest_validation_alert"]["approval_playbook_go_no_go"] == "NO_GO"
    assert (
        slo_item["evidence"]["latest_validation_alert"]["approval_playbook_code"]
        == "no_go_proxy_selected_trial_against_replay_backed_worst_scenario"
    )


def test_operational_checklist_uses_validation_top_level_deployment_contract() -> None:
    settings = Settings(alert_discord_webhook_url="https://discord.example/webhook")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    alerts = [
        AlertSubscription(
            alert_id="alert_test_discord_top_level_validation_contract",
            plan_id=None,
            symbol="BTCUSDC",
            channel="discord",
            type="test",
            payload={
                "delivery": {
                    "channel": "discord",
                    "delivered": True,
                    "skipped": False,
                    "reason": "ok",
                    "attempts": 1,
                    "latency_ms": 95.0,
                }
            },
            triggered_ts=now - timedelta(hours=1),
        )
    ]
    service = OperationalChecklistService(alert_repo=_AlertRepoStub(alerts), settings=settings)

    payload = service.generate(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        strategy_version="v2",
        ready=ReadySnapshot(status="ready", checks={"db": True}, details={"db": "ok"}),
        validation_payload={
            "validation_report": {
                "status": "PASS",
                "path": "reports/validation/test.md",
                "execution_degradation_advisory_available": True,
                "execution_degradation_advisory_summary": {
                    "status": "healthy",
                    "summary": "execution degradation advisory is healthy",
                    "recommended_action": "continue_runtime_monitoring",
                    "reason_codes": [],
                    "sample_context": {"plans_matured": 1, "fill_events_total": 1},
                },
                "operator_action_priority_summary": {
                    "available": True,
                    "top_action": "continue_runtime_monitoring",
                    "top_reason": "no stronger operator action is currently implied by playbook, execution, family, mode, or research signals",
                    "priority_level": "monitor",
                    "supporting_signals": [],
                    "blocking_signals": [],
                    "next_actions": [],
                    "advisory_only": True,
                },
                "outcome_control_trace_available": True,
                "outcome_control_trace_summary": {
                    "available": True,
                    "summary": "approval unchanged; risk allowance unchanged; portfolio ordering bias stayed neutral",
                    "approval_penalty_status": "healthy",
                    "approval_penalty_tier": "none",
                    "sizing_penalty_status": "healthy",
                    "sizing_penalty_tier": "none",
                    "sizing_multiplier": 1.0,
                    "portfolio_bias_tier": "neutral",
                    "portfolio_bias_score_delta": 0.0,
                    "top_reason_codes": [],
                },
            },
            "deployment_go_no_go": "GO",
            "deployment_code": "go_approval_template_aligned",
            "deployment_message": "GO: approval template is aligned for rollout.",
            "approval_topline_status": "PASS",
            "approval_topline_code": "approval_template_aligned",
            "approval_topline_message": (
                "GO: GO: approval template is aligned with replay-backed downside and the current threshold-lineage winner. "
                "winner=true_threshold/v2; worst=stressed_cost/PASS/stressed_cost; promotion=promote_true_market_runner."
            ),
            "playbook_go_no_go": "GO",
            "playbook_code": "go_approval_template_aligned",
            "playbook_action": "proceed_with_configured_rollout",
            "playbook_message": "GO: approval template is aligned with replay-backed downside and the current threshold-lineage winner.",
            "approval_topline_summary_line": "winner=true_threshold/v2; worst=stressed_cost/PASS/stressed_cost; promotion=promote_true_market_runner",
            "validation_alert": None,
            "strategy_v2_pbo_dsr_design": {"design_ready": True, "available": False},
        },
        alert_metrics={
            "overall": {"slo": {"status": "PASS"}, "error_budget": {"status": "PASS"}},
            "channel_metrics": {"discord": {"slo": {"status": "PASS"}, "error_budget": {"status": "PASS"}}},
            "circuit_state": {"discord": {"open_targets": 0}},
            "retry_queue": {"counts": {"queued": 0, "dead_letter": 0}, "backlog_age_seconds": 0},
        },
        outbox_status={"counts": {"pending": 0, "failed": 0}, "backlog_age_seconds": 0, "retry_policy": {}},
        strategy_metrics={
            "risk_state": "OPEN",
            "risk_reason": "normal",
            "operating_lock": {
                "active": False,
                "scope": "none",
                "strategy_mode": "A_ONLY",
                "current_session": {
                    "name": "london",
                    "active": True,
                    "start": (now - timedelta(hours=1)).isoformat(),
                    "end": (now + timedelta(hours=1)).isoformat(),
                },
            },
        },
        portfolio_budget={
            "deployment_go_no_go": "GO",
            "deployment_code": "go_runtime_gate_open",
            "deployment_message": "GO: runtime gate is open for candidate review.",
            "current_exposure": {"active_thesis_clusters": 0},
            "blocked_reason_counts": {},
            "strategy_mode": "A_ONLY",
        },
        execution_quality={"plans_matured": 1, "fill_events_total": 1},
        alert_test_lookback_hours=24,
        write_report=False,
    )

    assert payload["deployment_go_no_go"] == "GO"
    assert payload["deployment_code"] == "go_operational_checklist_ready"
    assert payload["playbook_go_no_go"] == "GO"
    validation_item = next(item for item in payload["checks"] if item["item_id"] == "validation_report")
    assert validation_item["evidence"]["deployment_go_no_go"] == "GO"
    assert validation_item["evidence"]["deployment_code"] == "go_approval_template_aligned"
    assert validation_item["evidence"]["deployment_message"] == "GO: approval template is aligned for rollout."
    assert validation_item["evidence"]["approval_topline_status"] == "PASS"
    assert validation_item["evidence"]["playbook_go_no_go"] == "GO"
    assert validation_item["evidence"]["playbook_code"] == "go_approval_template_aligned"
    assert validation_item["evidence"]["playbook_action"] == "proceed_with_configured_rollout"
    assert validation_item["evidence"]["approval_topline_summary_line"].startswith("winner=true_threshold/")


def test_operational_checklist_surfaces_portfolio_deployment_language_evidence() -> None:
    settings = Settings(alert_discord_webhook_url="https://discord.example/webhook")
    service = OperationalChecklistService(alert_repo=_AlertRepoStub([]), settings=settings)

    payload = service.generate(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        strategy_version="v2",
        ready=ReadySnapshot(status="ready", checks={"db": True}, details={"db": "ok"}),
        validation_payload={
            "validation_report": {"status": "PASS"},
            "validation_alert": None,
            "strategy_v2_pbo_dsr_design": {"design_ready": True, "available": False},
        },
        alert_metrics={
            "overall": {"slo": {"status": "PASS"}, "error_budget": {"status": "PASS"}},
            "channel_metrics": {},
            "circuit_state": {},
            "retry_queue": {"counts": {"queued": 0, "dead_letter": 0}, "backlog_age_seconds": 0},
        },
        outbox_status={"counts": {"pending": 0, "failed": 0}, "backlog_age_seconds": 0, "retry_policy": {}},
        strategy_metrics={"risk_state": "OPEN", "risk_reason": "normal", "operating_lock": {"active": False}},
        portfolio_budget={
            "deployment_go_no_go": "MANUAL_REVIEW",
            "deployment_code": "manual_review_risk_gate_throttled",
            "deployment_message": "MANUAL_REVIEW: runtime risk gate is throttled (jump_guard_active). Reduce size and review before acting.",
            "playbook_go_no_go": "MANUAL_REVIEW",
            "playbook_code": "manual_review_portfolio_risk_gate_throttled",
            "playbook_action": "review_throttled_gate_and_reduce_size",
            "playbook_message": "MANUAL_REVIEW: runtime risk gate is throttled. Review headroom and reduce size before acting.",
            "current_exposure": {"active_thesis_clusters": 0},
            "blocked_reason_counts": {},
            "strategy_mode": "A_ONLY",
        },
        execution_quality={"plans_matured": 2, "fill_events_total": 1},
        alert_test_lookback_hours=24,
        write_report=False,
    )

    portfolio_item = next(item for item in payload["checks"] if item["item_id"] == "portfolio_headroom")
    assert portfolio_item["evidence"]["deployment_go_no_go"] == "MANUAL_REVIEW"
    assert portfolio_item["evidence"]["deployment_code"] == "manual_review_risk_gate_throttled"
    assert portfolio_item["evidence"]["deployment_message"].startswith("MANUAL_REVIEW:")
    assert portfolio_item["evidence"]["playbook_go_no_go"] == "MANUAL_REVIEW"
    assert portfolio_item["evidence"]["playbook_code"] == "manual_review_portfolio_risk_gate_throttled"
    assert portfolio_item["evidence"]["playbook_action"] == "review_throttled_gate_and_reduce_size"


def test_operational_checklist_maps_execution_degradation_manual_review_to_warn_non_blocking() -> None:
    settings = Settings(alert_discord_webhook_url="https://discord.example/webhook")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    alerts = [
        AlertSubscription(
            alert_id="alert_test_discord_execution_degradation_manual_review",
            plan_id=None,
            symbol="BTCUSDC",
            channel="discord",
            type="test",
            payload={
                "delivery": {
                    "channel": "discord",
                    "delivered": True,
                    "skipped": False,
                    "reason": "ok",
                    "attempts": 1,
                    "latency_ms": 101.0,
                }
            },
            triggered_ts=now - timedelta(hours=1),
        )
    ]
    service = OperationalChecklistService(alert_repo=_AlertRepoStub(alerts), settings=settings)

    payload = service.generate(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        strategy_version="v2",
        ready=ReadySnapshot(status="ready", checks={"db": True}, details={"db": "ok"}),
        validation_payload={
            "validation_report": {
                "status": "PASS",
                "path": "reports/validation/test.md",
                "execution_degradation_advisory_available": True,
                "execution_degradation_advisory_summary": {
                    "status": "manual_review",
                    "summary": "runtime execution drag warrants manual review before expansion",
                    "recommended_action": "review_runtime_execution_drag_before_expansion",
                    "reason_codes": ["fill_rate_watch"],
                    "sample_context": {"plans_matured": 6, "fill_events_total": 4},
                },
                "outcome_control_trace_available": True,
                "outcome_control_trace_summary": {
                    "available": True,
                    "summary": "approval downgraded; risk allowance reduced; portfolio ordering bias stayed negative",
                    "approval_penalty_status": "manual_review",
                    "approval_penalty_tier": "downgrade_to_manual",
                    "sizing_penalty_status": "manual_review",
                    "sizing_penalty_tier": "hard_clamp",
                    "sizing_multiplier": 0.5,
                    "portfolio_bias_tier": "negative",
                    "portfolio_bias_score_delta": -2.5,
                    "top_reason_codes": ["execution_degradation:manual_review", "post_cost_conversion:weak_family_alignment"],
                },
            },
            "validation_alert": None,
            "strategy_v2_pbo_dsr_design": {"design_ready": True, "available": False},
            "deployment_go_no_go": "GO",
            "deployment_code": "go_approval_template_aligned",
            "deployment_message": "GO: approval template is aligned for rollout.",
            "playbook_go_no_go": "GO",
            "playbook_code": "go_approval_template_aligned",
            "playbook_action": "proceed_with_configured_rollout",
            "playbook_message": "GO: approval template is aligned with current evidence.",
        },
        alert_metrics={
            "overall": {"slo": {"status": "PASS"}, "error_budget": {"status": "PASS"}},
            "channel_metrics": {"discord": {"slo": {"status": "PASS"}, "error_budget": {"status": "PASS"}}},
            "circuit_state": {"discord": {"open_targets": 0}},
            "retry_queue": {"counts": {"queued": 0, "dead_letter": 0}, "backlog_age_seconds": 0},
        },
        outbox_status={"counts": {"pending": 0, "failed": 0}, "backlog_age_seconds": 0, "retry_policy": {}},
        strategy_metrics={"risk_state": "OPEN", "risk_reason": "normal", "operating_lock": {"active": False}},
        portfolio_budget={
            "deployment_go_no_go": "GO",
            "deployment_code": "go_runtime_gate_open",
            "deployment_message": "GO: runtime gate is open for candidate review.",
            "current_exposure": {"active_thesis_clusters": 0},
            "blocked_reason_counts": {},
            "strategy_mode": "A_ONLY",
        },
        execution_quality={"plans_matured": 2, "fill_events_total": 1},
        alert_test_lookback_hours=24,
        write_report=False,
    )

    advisory_item = next(item for item in payload["checks"] if item["item_id"] == "execution_degradation_advisory")
    assert advisory_item["status"] == "WARN"
    assert advisory_item["blocking"] is False
    assert advisory_item["evidence"]["recommended_action"] == "review_runtime_execution_drag_before_expansion"
    outcome_control_item = next(item for item in payload["checks"] if item["item_id"] == "outcome_control_trace")
    assert outcome_control_item["status"] == "WARN"
    assert outcome_control_item["evidence"]["sizing_penalty_tier"] == "hard_clamp"
    assert payload["overall_status"] == "WARN"


def test_operational_checklist_tolerates_malformed_numeric_settings() -> None:
    settings = Settings(alert_discord_webhook_url="https://discord.example/webhook")
    settings.event_late_seconds = "bad"
    settings.thesis_max_active_clusters = float("inf")
    service = OperationalChecklistService(alert_repo=_AlertRepoStub([]), settings=settings)

    outbox_item = service._outbox_item(
        outbox_status={"counts": {"pending": 0, "failed": 0}, "backlog_age_seconds": 91}
    )
    portfolio_item = service._portfolio_item(
        portfolio_budget={"current_exposure": {"active_thesis_clusters": 2}, "blocked_reason_counts": {}}
    )

    assert outbox_item["status"] == "FAIL"
    assert portfolio_item["status"] == "WARN"
