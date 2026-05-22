from __future__ import annotations

from pathlib import Path

from app.services.validation_report import ValidationReportService


def test_validation_approval_strip_manual_review_prefers_playbook_hold_action() -> None:
    strip = ValidationReportService._approval_strip_summary(
        deployment_approval_template={
            "playbook_go_no_go": "MANUAL_REVIEW",
            "playbook_action": "hold_rollout_and_review_alignment_details",
            "playbook_message": "MANUAL REVIEW: alignment warning remains.",
            "template_status": "REVIEW",
            "template_reason": "true_threshold_winner_with_replay_fail_worst_scenario",
        },
        operator_action_priority_summary={
            "top_action": "continue_candidate_review_under_portfolio_caps",
            "top_reason": "runtime gate is open",
            "priority_level": "urgent",
        },
    )

    assert strip is not None
    assert strip["approve_value"] == "manual review first"
    assert strip["act_value"] == "hold_rollout_and_review_alignment_details"
    assert strip["act_reason"] == "MANUAL REVIEW: alignment warning remains."


def _empty_review_followup_ledger(*args, **kwargs) -> dict:
    return {
        "available": False,
        "advisory_only": True,
        "symbol": str(kwargs.get("symbol") or ""),
        "universe": str(kwargs.get("universe") or ""),
        "ledger_path": "reports/operations/split_review_followups/review_ledger.jsonl",
        "total_entry_count": 0,
        "recent_entry_count": 0,
        "summary": "No split review follow-up packets have been recorded yet.",
        "reason_codes": ["recent_entries:0", "ledger:not_recorded"],
        "last_generated_at": "",
        "last_recorded_at": "",
        "last_status": "none",
        "last_action": "none",
        "last_selection_reason": "",
        "last_followup_command": "",
        "last_report_path": "",
        "last_target_contract": {},
        "last_priority_source": "monitor",
        "last_priority_level": "monitor",
        "last_edge_state": "insufficient_edge_measurement",
        "last_true_edge_ratio": 0.0,
        "last_edge_decay_rate": 0.0,
        "last_evolution_state": "insufficient_sample",
        "last_recommended_action": "keep_current_baseline",
        "last_allocation_bias": "hold_current_baseline",
        "recent_status_counts": {},
        "recent_action_counts": [],
    }


def test_validation_report_generation(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.validation_report.summarize_split_review_followup_ledger",
        _empty_review_followup_ledger,
    )
    service = ValidationReportService()
    result = service.generate(
        symbol="BTCUSDC",
        version="v1",
        wf={"trades": 120, "mean_ev": 0.21, "p5_ev": -0.2, "p50_ev": 0.2, "p95_ev": 0.8},
        mc={"trades": 120, "mean_ev": 0.18, "p5_ev": -0.1, "p50_ev": 0.2, "p95_ev": 0.7},
        metric={"win_rate": 0.56, "avg_win": 1.8, "avg_loss": 1.0, "ev": 0.32, "p1r": 0.56, "p2r": 0.34, "p3r": 0.19},
        execution_quality={
            "target_exit_ratio": 0.57,
            "forced_exit_ratio": 0.43,
            "information_failure_ratio": 0.14,
            "time_failure_ratio": 0.07,
            "final_exit_reasons": {
                "target_tp2": 5,
                "information_failure": 2,
                "time_failure": 1,
            },
            "by_entry_model": {
                "CONFIRM": {
                    "plans": 9,
                    "filled": 7,
                    "fill_rate": 0.7778,
                    "avg_slippage_bps": 8.2,
                    "avg_entry_latency_seconds": 43.0,
                },
                "LIMIT": {
                    "plans": 5,
                    "filled": 2,
                    "fill_rate": 0.4,
                    "avg_slippage_bps": 2.4,
                    "avg_entry_latency_seconds": 15.0,
                },
            },
            "by_strategy_family": {
                "sweep_reversal": {
                    "filled": 8,
                    "closed": 6,
                    "target_exit_rate": 0.6667,
                    "forced_exit_rate": 0.3333,
                    "information_failure_rate": 0.0,
                    "time_failure_rate": 0.1667,
                },
                "trend_continuation": {
                    "filled": 6,
                    "closed": 5,
                    "target_exit_rate": 0.4,
                    "forced_exit_rate": 0.6,
                    "information_failure_rate": 0.4,
                    "time_failure_rate": 0.0,
                },
            },
        },
        execution_friction_measurement={
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
            "fill_rate": 0.62,
            "fills_matched": 9,
            "fill_events_total": 11,
            "execution_fill_coverage": 0.8889,
            "avg_slippage_bps": 6.0,
            "p95_slippage_bps": 7.5,
            "avg_entry_latency_seconds": 180.0,
            "p95_entry_latency_seconds": 480.0,
            "avg_fee_component_r": 0.06,
            "p95_fee_component_r": 0.11,
            "approval_slippage_cap_bps": 12.0,
            "approval_fee_bps_reference": 4.0,
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
                "approval_slippage_cap_bps": 12.0,
                "approval_fee_bps_reference": 4.0,
            },
        },
        forward_stress_regime_validation={
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
        kill_condition_automation={
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
            "summary": (
                "Current evidence is weak enough to review close-only rules before expanding live entries; "
                "this is advisory and does not automatically block the current live route."
            ),
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
        feature_importance={
            "available": True,
            "ranking": [
                {"feature": "liquidity", "importance_score": 12.3, "delta_mean_ev": 0.08, "delta_top_rank_score": 5.2}
            ],
        },
        feature_calibration={
            "available": True,
            "regime_label": "range",
            "matched_samples": 8,
            "applied_runtime": True,
            "baseline_weights": {"liquidity": 0.38, "fvg_displacement": 0.20, "htf_alignment": 0.18, "ob_freshness": 0.19, "trend_proxy": 0.05},
            "recommended_weights": {"liquidity": 0.41, "fvg_displacement": 0.18, "htf_alignment": 0.17, "ob_freshness": 0.19, "trend_proxy": 0.05},
            "by_regime": {
                "range": {
                    "feature_weights_base": {"liquidity": 0.38, "fvg_displacement": 0.20, "htf_alignment": 0.18, "ob_freshness": 0.19, "trend_proxy": 0.05},
                    "feature_weights_active": {"liquidity": 0.41, "fvg_displacement": 0.18, "htf_alignment": 0.17, "ob_freshness": 0.19, "trend_proxy": 0.05},
                }
            },
        },
        strategy_v2_validation={
            "available": True,
            "comparison_axis": "strategy_mode",
            "sample_counts": {
                "eligible_closed_trades": 14,
                "incremental_b_trades": 4,
            },
            "family_metrics": {
                "sweep_reversal": {"trades": 8, "win_rate": 0.75, "ev": 0.32},
                "trend_continuation": {"trades": 6, "win_rate": 0.5, "ev": 0.51},
            },
            "family_summary": {
                "best_ev_family": {"name": "trend_continuation", "ev": 0.51, "trades": 6},
                "best_win_rate_family": {"name": "sweep_reversal", "win_rate": 0.75, "trades": 8},
                "largest_sample_family": {"name": "sweep_reversal", "trades": 8},
            },
            "regime_metrics": {
                "range": {"trades": 9, "win_rate": 0.6667, "ev": 0.41},
                "shock": {"trades": 5, "win_rate": 0.4, "ev": -0.12},
            },
            "regime_summary": {
                "best_ev_regime": {"name": "range", "ev": 0.41, "trades": 9},
                "best_win_rate_regime": {"name": "range", "win_rate": 0.6667, "trades": 9},
                "largest_sample_regime": {"name": "range", "trades": 9},
            },
            "session_metrics": {
                "overlap": {"trades": 5, "win_rate": 0.8, "ev": 0.48},
                "new_york": {"trades": 6, "win_rate": 0.5, "ev": 0.11},
                "dead_session": {"trades": 3, "win_rate": 0.0, "ev": -0.35},
            },
            "session_summary": {
                "best_ev_session": {"name": "overlap", "ev": 0.48, "trades": 5},
                "best_win_rate_session": {"name": "london", "win_rate": 0.7, "trades": 4},
                "largest_sample_session": {"name": "new_york", "trades": 6},
            },
            "mode_metrics": {
                "A_ONLY": {
                    "trades": 10,
                    "ev": 0.42,
                    "p5_ev": -0.2,
                    "max_drawdown": 1.1,
                    "ulcer_index": 0.44,
                    "forced_exit_ratio": 0.3,
                    "information_failure_ratio": 0.1,
                },
                "A_PLUS_B": {
                    "trades": 14,
                    "ev": 0.35,
                    "p5_ev": -0.4,
                    "max_drawdown": 1.8,
                    "ulcer_index": 0.72,
                    "forced_exit_ratio": 0.43,
                    "information_failure_ratio": 0.14,
                },
            },
            "comparison": {
                "ev": -0.07,
                "p5_ev": -0.2,
                "max_drawdown": 0.7,
                "ulcer_index": 0.28,
            },
            "deployment_recommendation": {
                "preferred_live_mode": "A_ONLY",
                "reason": "a_only_downside_better",
            },
        },
        multi_strategy_ab={
            "available": True,
            "advisory_only": True,
            "mode": "A_ONLY",
            "raw_family_anchor": "sweep_reversal",
            "summary": "A reversal remains the current production anchor; B continuation is visible as compare-only guarded flow while range rotation stays research-only sidecar.",
            "reason_codes": [
                "mode:a_only",
                "cluster:a_reversal",
                "cluster:b_continuation",
                "b_guardrail:mode_a_only",
            ],
            "a_cluster": {
                "cluster": "a_reversal",
                "strategy_cluster_status": "current_anchor",
                "live_eligible": True,
                "guarded": False,
            },
            "b_cluster": {
                "cluster": "b_continuation",
                "strategy_cluster_status": "compare_only",
                "live_eligible": False,
                "guarded": True,
                "guardrail_reasons": ["b_guardrail:mode_a_only"],
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
                    "total_candidates": 5,
                    "accepted_candidates": 3,
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
        b_continuation_activation={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "activation_state": "research_only",
            "activation_bias": "stay_research",
            "target_mode": "A_ONLY",
            "confidence": "low",
            "live_eligible": False,
            "summary": "B continuation remains compare-only under the current mode and should stay in research posture.",
            "reason_codes": [
                "b_activation:research_only",
                "mode:a_only",
                "cluster_status:compare_only",
                "b_guardrail:mode_a_only",
            ],
            "source_summary": {
                "cluster_status": "compare_only",
                "family_closed": 6,
                "family_execution_status": "watch",
                "rollout_recommendation": "research_only",
                "lifecycle_state": "research",
                "governance_state": "defer",
                "clearance_state": "blocked",
                "reopen_action": "continue_clearance",
                "brief_state": "clearance_required",
                "execution_stage": "auto_execution_blocked",
                "positive_expansion_state": "not_ready",
                "thin_sample": False,
                "guardrail_reasons": ["b_guardrail:mode_a_only"],
            },
        },
        b_continuation_edge_validation={
            "available": True,
            "advisory_only": True,
            "raw_family": "trend_continuation",
            "strategy_cluster": "b_continuation",
            "edge_state": "fragile_edge",
            "validation_bias": "monitor_diversification",
            "sample_state": "mature_sample",
            "family_post_cost_rate": 0.5,
            "family_post_cost_ev": None,
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
                "raw_family:trend_continuation",
                "diversification:correlation_heavy",
            ],
            "source_summary": {
                "raw_family_anchor": "trend_continuation",
                "strategy_cluster": "b_continuation",
                "family_closed": 8,
                "family_post_cost_rate": 0.5,
                "a_reference_post_cost_rate": 0.55,
                "post_cost_gap_vs_a": -0.05,
                "family_execution_status": "healthy",
                "activation_state": "research_only",
                "balance_state": "research_only_mix",
                "capital_pressure": "neutral",
            },
        },
        strategy_cluster_balance={
            "available": True,
            "advisory_only": True,
            "mode": "A_ONLY",
            "balance_state": "research_only_mix",
            "balance_bias": "stay_a_anchor",
            "headline_cluster": "a_reversal",
            "target_mix": "a_anchor_only",
            "confidence": "low",
            "summary": "A remains the live anchor while B continuation stays compare-only under the current mode.",
            "family_mix": [
                {
                    "raw_family": "sweep_reversal",
                    "cluster": "a_reversal",
                    "total_candidates": 5,
                    "accepted_candidates": 3,
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
                "cluster_balance:research_only_mix",
                "mode:a_only",
                "headline_cluster:a_reversal",
            ],
            "source_summary": {
                "a_total_candidates": 5,
                "a_accepted_candidates": 3,
                "b_total_candidates": 2,
                "b_accepted_candidates": 0,
                "b_alpha_research_candidates": 1,
                "b_activation_state": "research_only",
                "b_activation_bias": "stay_research",
                "b_cluster_status": "compare_only",
                "allocator_focus": "trend_continuation",
                "allocator_state": "active",
            },
        },
        a_strategy_post_cost_edge_validation={
            "available": True,
            "advisory_only": True,
            "family": "sweep_reversal",
            "edge_state": "fragile_edge",
            "validation_bias": "monitor_fragility",
            "sample_state": "mature",
            "family_post_cost_rate": 0.375,
            "family_post_cost_ev": None,
            "weakest_axis": "liquidity_condition",
            "weakest_bucket": "shallow_liquidity",
            "confidence": "medium",
            "summary": "family=sweep_reversal still has usable A-anchor evidence, but fragility is concentrated in liquidity_condition:shallow_liquidity; monitor anchor confidence before treating A as fully stable.",
            "reason_codes": [
                "a_edge:fragile_edge",
                "sample:mature",
                "family:sweep_reversal",
                "weakest_axis:liquidity_condition",
            ],
            "source_summary": {
                "raw_family_anchor": "sweep_reversal",
                "family_closed": 8,
                "family_post_cost_rate": 0.375,
                "historical_anchor_rate": 0.4,
                "family_execution_status": "watch",
                "approval_penalty_status": "healthy",
                "sizing_penalty_tier": "soft_clamp",
            },
        },
        strategy_v2_lock_validation={
            "available": True,
            "comparison_axis": "transition_shock_lock",
            "sample_counts": {
                "blocked_transition_trades": 3,
                "blocked_shock_trades": 2,
                "shock_clamped_trades": 4,
            },
            "lock_metrics": {
                "before_lock": {
                    "trades": 15,
                    "ev": 0.28,
                    "p5_ev": -0.5,
                    "max_drawdown": 2.1,
                    "ulcer_index": 0.9,
                },
                "after_lock": {
                    "trades": 10,
                    "ev": 0.34,
                    "p5_ev": -0.2,
                    "max_drawdown": 1.2,
                    "ulcer_index": 0.5,
                },
            },
            "comparison": {
                "ev": 0.06,
                "p5_ev": 0.3,
                "max_drawdown": -0.9,
                "ulcer_index": -0.4,
            },
            "deployment_recommendation": {
                "keep_lock_enabled": True,
                "reason": "lock_downside_improved",
            },
        },
        strategy_v2_scalp_experiment={
            "available": True,
            "reason": "ok",
            "sample_counts": {
                "candles_1m": 900,
                "candles_5m": 300,
                "candles_15m": 300,
            },
            "comparison": {
                "preferred_branch": "experiment",
                "recommendation_reason": "experiment_has_higher_sized_ev",
                "delta_top_expected_ev_at_size_r": 0.041,
                "delta_top_expected_win_prob": 0.023,
            },
        },
        alpha_research_pipeline={
            "available": True,
            "reason": "ok",
            "analysis_symbol": "BTCUSDC",
            "summary": {
                "alpha_research_candidate_count": 3,
                "focus_symbol_candidate_count": 1,
                "top_reason": "risk_budget_below_min",
                "top_family": "trend_continuation",
                "top_regime": "range",
                "top_session": "dead_session",
                "avg_softened_risk_r": 0.175,
            },
            "research_focus_alignment": {
                "available": True,
                "analysis_symbol": "BTCUSDC",
                "aligned_candidate_count": 2,
                "top_focus": "family_information_failure",
                "top_bucket": "trend_continuation",
            },
            "recommended_action_summary": {
                "analysis_symbol": "BTCUSDC",
                "recommended_action": "run_shadow_exit_review",
                "recommended_scope": "family",
                "recommended_reason": "information_failure_rate is elevated for this family",
                "shadow_experiment_type": "exit_failure_review",
                "bucket": "trend_continuation",
                "focus": "family_information_failure",
                "confidence": "medium",
                "sample_note": "usable evidence, but still limited",
                "aligned_candidates": 2,
                "deferred_by_experiment_sequence": True,
                "experiment_sequence_state": "entry_timing_first",
                "current_priority_experiment": "entry_timing",
                "current_priority_action": "run_entry_timing_split_review",
                "exit_optimization_allowed": False,
                "sequencing_reason": "Lock entry timing first: compare early_limit versus reaction_confirmed before changing execution style or reviewing exit optimization.",
            },
            "recommended_actions": [
                {
                    "recommended_action": "run_shadow_exit_review",
                    "recommended_scope": "family",
                    "recommended_reason": "information_failure_rate is elevated for this family",
                    "shadow_experiment_type": "exit_failure_review",
                    "bucket": "trend_continuation",
                    "focus": "family_information_failure",
                    "confidence": "medium",
                    "sample_note": "usable evidence, but still limited",
                    "aligned_candidates": 2,
                    "observe_metrics": ["information_failure_rate", "forced_exit_rate", "post_cost_ev"],
                    "promotion_guardrails": [
                        "do_not_promote_if_information_failure_persists",
                        "do_not_weaken_safety_or_structural_gates",
                    ],
                    "deferred_by_experiment_sequence": True,
                    "experiment_sequence_state": "entry_timing_first",
                    "current_priority_experiment": "entry_timing",
                    "current_priority_action": "run_entry_timing_split_review",
                    "exit_optimization_allowed": False,
                    "sequencing_reason": "Lock entry timing first: compare early_limit versus reaction_confirmed before changing execution style or reviewing exit optimization.",
                }
            ],
            "top_shadow_experiment": {
                "analysis_symbol": "BTCUSDC",
                "experiment_id": "shadow_exit_review_family",
                "title": "Family Exit Failure Review",
                "objective": "Determine whether elevated information failure in this family is an exit issue or a deeper quality problem.",
                "recommended_action": "run_shadow_exit_review",
                "recommended_scope": "family",
                "shadow_experiment_type": "exit_failure_review",
                "target": "family=trend_continuation",
                "focus": "family_information_failure",
                "bucket": "trend_continuation",
                "confidence": "medium",
                "sample_note": "usable evidence, but still limited",
                "deferred_by_experiment_sequence": True,
                "experiment_sequence_state": "entry_timing_first",
                "current_priority_experiment": "entry_timing",
                "current_priority_action": "run_entry_timing_split_review",
                "exit_optimization_allowed": False,
                "sequencing_reason": "Lock entry timing first: compare early_limit versus reaction_confirmed before changing execution style or reviewing exit optimization.",
                "observe_metrics": ["information_failure_rate", "forced_exit_rate", "post_cost_ev"],
                "success_criteria": [
                    "information failure looks reducible without weakening hard gates",
                    "forced exit overlap trends lower while post-cost EV remains stable",
                ],
                "stop_conditions": [
                    "sample is too thin to separate exit failure from noise",
                    "the same family also shows safety or structural violations",
                ],
            },
            "shadow_experiment_templates": [
                {
                    "experiment_id": "shadow_exit_review_family",
                    "title": "Family Exit Failure Review",
                    "objective": "Determine whether elevated information failure in this family is an exit issue or a deeper quality problem.",
                    "recommended_action": "run_shadow_exit_review",
                    "recommended_scope": "family",
                    "shadow_experiment_type": "exit_failure_review",
                    "analysis_symbol": "BTCUSDC",
                    "target": "family=trend_continuation",
                    "focus": "family_information_failure",
                    "bucket": "trend_continuation",
                    "steps": [
                        "collect recent candidates for the target family in shadow mode",
                        "compare information failure against forced exit and time failure patterns",
                        "review whether the family keeps post-cost EV after filtering obvious failures",
                    ],
                    "observe_metrics": ["information_failure_rate", "forced_exit_rate", "post_cost_ev"],
                    "success_criteria": [
                        "information failure looks reducible without weakening hard gates",
                        "forced exit overlap trends lower while post-cost EV remains stable",
                    ],
                    "stop_conditions": [
                        "sample is too thin to separate exit failure from noise",
                        "the same family also shows safety or structural violations",
                    ],
                    "promotion_guardrails": [
                        "do_not_promote_if_information_failure_persists",
                        "do_not_weaken_safety_or_structural_gates",
                    ],
                    "confidence": "medium",
                    "sample_note": "usable evidence, but still limited",
                }
            ],
            "experiment_sequence": {
                "state": "entry_timing_first",
                "entry_timing_locked": False,
                "execution_style_locked": False,
                "exit_optimization_allowed": False,
                "current_priority_experiment": "entry_timing",
                "current_priority_action": "run_entry_timing_split_review",
                "summary": "Lock entry timing first: compare early_limit versus reaction_confirmed before changing execution style or reviewing exit optimization.",
            },
            "alpha_research_evidence_summary": {
                "available": True,
                "analysis_symbol": "BTCUSDC",
                "coverage_note": "suspects are heuristic only; runtime selection is snapshot and execution outcomes are windowed history.",
                "near_miss_reason_summary": {
                    "candidate_count": 3,
                    "reason_counts": {"risk_budget_below_min": 2, "adjusted_score_non_positive": 1},
                    "top_reason": "risk_budget_below_min",
                    "top_family": "trend_continuation",
                    "top_regime": "range",
                    "top_session": "dead_session",
                    "avg_softened_risk_r": 0.175,
                    "matched_focus_candidate_count": 2,
                },
                "focus_alignment_summary": {
                    "aligned_candidate_count": 2,
                    "top_focus": "family_information_failure",
                    "top_bucket": "trend_continuation",
                    "focus_items": [
                        {
                            "focus": "family_information_failure",
                            "bucket": "trend_continuation",
                            "candidates": 2,
                        }
                    ],
                    "top_focus_share_of_candidates": 0.6667,
                },
                "outcome_alignment_summary": {
                    "available": True,
                    "top_family_bottleneck": {"key": "trend_continuation"},
                    "top_regime_bottleneck": {"key": "range"},
                    "top_session_bottleneck": {"key": "dead_session"},
                    "matching_softening_reasons": ["risk_budget_below_min"],
                    "alignment_signals": [
                        {
                            "axis": "family",
                            "bucket": "trend_continuation",
                            "matched_candidates": 2,
                            "alignment_strength": "high",
                        }
                    ],
                },
                "false_negative_suspects": [
                    {
                        "reason": "risk_budget_below_min",
                        "axis": "family",
                        "bucket": "trend_continuation",
                        "matched_candidates": 2,
                        "top_symbol": "BTCUSDC",
                        "avg_expected_ev_r": 0.18,
                        "avg_softened_risk_r": 0.175,
                        "alignment_strength": "high",
                        "execution_drag_conflict": False,
                        "confidence": "medium",
                        "sample_note": "usable evidence, but still limited",
                        "why_suspected": "repeated near-miss cluster aligns with outcome bottleneck",
                    }
                ],
            },
            "softening_candidate_review": {
                "available": True,
                "top_candidate": {
                    "reason": "risk_budget_below_min",
                    "bucket": "trend_continuation",
                    "axis": "family",
                    "review_priority": "p1",
                    "recommended_research_action": "run_shadow_exit_review",
                    "why_now": "repeated quality near-miss aligns with outcome bottleneck",
                    "blocking_guardrails": [
                        "do_not_weaken_safety_or_structural_gates",
                    ],
                    "required_evidence": ["information_failure_rate", "forced_exit_rate", "post_cost_ev"],
                    "execution_drag_conflict": False,
                    "confidence": "medium",
                    "sample_note": "usable evidence, but still limited",
                },
                "review_items": [
                    {
                        "reason": "risk_budget_below_min",
                        "bucket": "trend_continuation",
                        "axis": "family",
                        "review_priority": "p1",
                        "recommended_research_action": "run_shadow_exit_review",
                        "why_now": "repeated quality near-miss aligns with outcome bottleneck",
                        "blocking_guardrails": [
                            "do_not_weaken_safety_or_structural_gates",
                        ],
                        "required_evidence": ["information_failure_rate", "forced_exit_rate", "post_cost_ev"],
                        "execution_drag_conflict": False,
                        "confidence": "medium",
                        "sample_note": "usable evidence, but still limited",
                    }
                ],
            },
            "promotion_watchlist": {
                "available": True,
                "watchlist_count": 1,
                "watch_items": [
                    {
                        "focus": "family_information_failure",
                        "bucket": "trend_continuation",
                        "matched_candidates": 2,
                        "recent_shadow_template": "shadow_exit_review_family",
                        "post_cost_condition": "baseline_cost_profitable_rate_from_closed is stable",
                        "execution_health_condition": "watch",
                        "confidence": "medium",
                        "sample_note": "usable evidence, but still limited",
                        "why_watch": "aligned near-miss cluster has repeat evidence",
                        "not_ready_reason": None,
                    }
                ],
            },
        },
        score_to_outcome_funnel={
            "available": True,
            "reason": "ok",
            "report_window_days": 30,
            "coverage_note": "snapshot selection is current-state only; execution outcomes are windowed history.",
            "snapshot_selection": {
                "runtime_candidates": 12,
                "accepted_candidates": 5,
                "blocked_candidates": 7,
                "accept_rate": 0.4167,
                "blocked_reason_counts": {"risk_budget_below_min": 3},
                "blocked_gate_group_counts": {"quality": 3, "structural": 2, "rollout": 2},
            },
            "historical_execution_outcomes": {
                "submitted": 9,
                "filled": 7,
                "closed": 6,
                "profitable": 4,
                "baseline_cost_profitable": 3,
                "fill_rate_from_submitted": 0.7778,
                "close_rate_from_filled": 0.8571,
                "profitable_rate_from_closed": 0.6667,
                "baseline_cost_profitable_rate_from_closed": 0.5,
            },
            "money_funnel": {
                "available": True,
                "coverage_note": "expected R uses expected_ev_at_recommended_size_r.",
                "snapshot_expected_r": {
                    "runtime_candidates": 1.42,
                    "accepted_candidates": 0.61,
                    "blocked_candidates": 0.81,
                },
                "historical_expected_r": {
                    "generated": 2.14,
                    "submitted": 1.51,
                    "filled": 1.18,
                    "closed": 0.96,
                },
                "historical_realized_r": {
                    "raw_closed": 0.84,
                    "post_cost_closed": 0.72,
                    "cost_drag": -0.12,
                },
                "historical_windows": {
                    "recent": {
                        "closed": 3,
                        "closed_expected_r": 0.54,
                        "raw_closed_realized_r": 0.5,
                        "post_cost_closed_realized_r": 0.42,
                        "true_edge_ratio": 0.7778,
                    },
                    "prior": {
                        "closed": 3,
                        "closed_expected_r": 0.42,
                        "raw_closed_realized_r": 0.34,
                        "post_cost_closed_realized_r": 0.30,
                        "true_edge_ratio": 0.7143,
                    },
                },
                "historical_gap_r": {
                    "generated_to_submitted": 0.63,
                    "submitted_to_filled": 0.33,
                    "filled_to_closed": 0.22,
                    "closed_expected_to_raw_realized": -0.12,
                    "closed_expected_to_post_cost_realized": -0.24,
                },
                "summary": "expected_closed_r=0.9600, post_cost_closed_r=0.7200, submitted_to_filled_gap_r=0.3300",
            },
            "decomposition": {
                "family": [
                    {
                        "key": "trend_continuation",
                        "runtime_candidates": 6,
                        "accepted_candidates": 2,
                        "blocked_candidates": 4,
                        "submitted": 4,
                        "filled": 3,
                        "closed": 3,
                        "profitable": 2,
                        "baseline_cost_profitable": 1,
                        "profitable_rate_from_closed": 0.6667,
                        "baseline_cost_profitable_rate_from_closed": 0.3333,
                    }
                ],
                "regime": [
                    {
                        "key": "range",
                        "runtime_candidates": 7,
                        "accepted_candidates": 3,
                        "blocked_candidates": 4,
                        "submitted": 5,
                        "filled": 4,
                        "closed": 4,
                        "profitable": 3,
                        "baseline_cost_profitable": 2,
                        "profitable_rate_from_closed": 0.75,
                        "baseline_cost_profitable_rate_from_closed": 0.5,
                    }
                ],
                "session": [
                    {
                        "key": "overlap",
                        "runtime_candidates": 4,
                        "accepted_candidates": 2,
                        "blocked_candidates": 2,
                        "submitted": 3,
                        "filled": 3,
                        "closed": 2,
                        "profitable": 2,
                        "baseline_cost_profitable": 1,
                        "profitable_rate_from_closed": 1.0,
                        "baseline_cost_profitable_rate_from_closed": 0.5,
                    }
                ],
                "entry_model": [
                    {
                        "key": "LIMIT",
                        "runtime_candidates": 5,
                        "accepted_candidates": 2,
                        "blocked_candidates": 3,
                        "submitted": 4,
                        "filled": 3,
                        "closed": 3,
                        "submitted_expected_r": 0.64,
                        "filled_expected_r": 0.48,
                        "closed_expected_r": 0.42,
                        "baseline_adjusted_r": 0.36,
                        "fill_rate_from_submitted": 0.75,
                    },
                    {
                        "key": "CONFIRM",
                        "runtime_candidates": 4,
                        "accepted_candidates": 2,
                        "blocked_candidates": 2,
                        "submitted": 5,
                        "filled": 4,
                        "closed": 3,
                        "submitted_expected_r": 0.87,
                        "filled_expected_r": 0.52,
                        "closed_expected_r": 0.54,
                        "baseline_adjusted_r": 0.36,
                        "fill_rate_from_submitted": 0.6,
                    },
                ],
                "entry_timing_variant": [
                    {
                        "key": "early_limit",
                        "runtime_candidates": 5,
                        "accepted_candidates": 2,
                        "blocked_candidates": 3,
                        "submitted": 4,
                        "filled": 3,
                        "closed": 3,
                        "submitted_expected_r": 0.64,
                        "filled_expected_r": 0.48,
                        "closed_expected_r": 0.42,
                        "baseline_adjusted_r": 0.36,
                        "fill_rate_from_submitted": 0.75,
                    },
                    {
                        "key": "reaction_confirmed",
                        "runtime_candidates": 7,
                        "accepted_candidates": 3,
                        "blocked_candidates": 4,
                        "submitted": 5,
                        "filled": 4,
                        "closed": 3,
                        "submitted_expected_r": 0.87,
                        "filled_expected_r": 0.52,
                        "closed_expected_r": 0.54,
                        "baseline_adjusted_r": 0.36,
                        "fill_rate_from_submitted": 0.6,
                    },
                ],
                "execution_mode": [
                    {
                        "key": "PAPER",
                        "runtime_candidates": 9,
                        "accepted_candidates": 4,
                        "blocked_candidates": 5,
                        "submitted": 9,
                        "filled": 7,
                        "closed": 6,
                        "submitted_expected_r": 1.51,
                        "filled_expected_r": 1.18,
                        "closed_expected_r": 0.96,
                        "baseline_adjusted_r": 0.72,
                        "fill_rate_from_submitted": 0.7778,
                    }
                ],
                "execution_style": [
                    {
                        "key": "passive_limit",
                        "runtime_candidates": 5,
                        "accepted_candidates": 2,
                        "blocked_candidates": 3,
                        "submitted": 4,
                        "filled": 3,
                        "closed": 3,
                        "submitted_expected_r": 0.64,
                        "filled_expected_r": 0.48,
                        "closed_expected_r": 0.42,
                        "baseline_adjusted_r": 0.36,
                        "fill_rate_from_submitted": 0.75,
                    },
                    {
                        "key": "market",
                        "runtime_candidates": 7,
                        "accepted_candidates": 3,
                        "blocked_candidates": 4,
                        "submitted": 5,
                        "filled": 4,
                        "closed": 3,
                        "submitted_expected_r": 0.87,
                        "filled_expected_r": 0.52,
                        "closed_expected_r": 0.54,
                        "baseline_adjusted_r": 0.36,
                        "fill_rate_from_submitted": 0.6,
                    },
                ],
            },
        },
        execution_degradation_advisory={
            "available": True,
            "status": "manual_review",
            "healthy": False,
            "summary": "fill coverage is degrading and stressed post-cost EV is deteriorating.",
            "recommended_action": "review_runtime_execution_drag_before_expansion",
            "reason_codes": ["fill_rate_watch", "stress_cost_deterioration"],
            "sample_context": {"plans_matured": 9, "fill_events_total": 7},
            "reasons": [
                {
                    "code": "fill_rate_watch",
                    "severity": "watch",
                    "message": "fill rate has softened versus the recent baseline",
                    "recommended_action": "review_entry_model_fill_rate",
                    "evidence": {"fill_rate": 0.7778},
                }
            ],
        },
        family_execution_degradation_advisory={
            "available": True,
            "coverage_note": "family execution advisory is advisory-only",
            "families": [
                {
                    "family": "trend_continuation",
                    "status": "watch",
                    "summary": "family execution quality is drifting and should be reviewed before scaling",
                    "reason_codes": ["family_forced_exit_ratio_drift"],
                    "recommended_action": "monitor_family_execution_drag_and_hold_size",
                    "fill_rate": 0.5,
                    "avg_slippage_bps": None,
                    "forced_exit_ratio": 0.35,
                    "information_failure_ratio": 0.1,
                    "time_failure_ratio": 0.2,
                    "post_cost_alignment": "aligned_negative",
                    "confidence": "medium",
                    "sample_note": "family sample is usable, but still limited",
                    "advisory_only": True,
                }
            ],
        },
        mode_advisory={
            "available": True,
            "coverage_note": "mode advisory is evidence-backed but advisory only; it does not change rollout policy, approval semantics, or live execution controls",
            "family": [
                {
                    "axis": "family",
                    "bucket": "trend_continuation",
                    "advisory_state": "research_only",
                    "why": "quality near-miss cluster needs research review before broader use",
                    "supporting_signals": ["softening_review:p1"],
                    "blocking_signals": ["focus:family_information_failure"],
                    "confidence": "medium",
                    "sample_note": "usable evidence, but still limited",
                    "advisory_only": True,
                }
            ],
            "regime": [
                {
                    "axis": "regime",
                    "bucket": "range",
                    "advisory_state": "watch",
                    "why": "execution or post-cost outcome signals are degrading for this bucket",
                    "supporting_signals": ["outcome_alignment:high"],
                    "blocking_signals": ["execution_degradation:manual_review"],
                    "confidence": "medium",
                    "sample_note": "usable evidence, but still limited",
                    "advisory_only": True,
                }
            ],
            "session": [
                {
                    "axis": "session",
                    "bucket": "dead_session",
                    "advisory_state": "watch",
                    "why": "execution or post-cost outcome signals are degrading for this bucket",
                    "supporting_signals": ["outcome_alignment:high"],
                    "blocking_signals": ["execution_degradation:manual_review"],
                    "confidence": "low",
                    "sample_note": "sample is thin; treat this as advisory context only",
                    "advisory_only": True,
                }
            ],
        },
        operator_action_priority={
            "available": True,
            "top_action": "review_runtime_execution_drag_before_expansion",
            "top_reason": "global execution degradation requires manual review",
            "priority_level": "urgent",
            "priority_source": "execution_degradation",
            "action_family": "execution_review",
            "supporting_signals": [
                "execution:manual_review",
                "family:trend_continuation:watch",
                "mode:family=trend_continuation:research_only",
            ],
            "blocking_signals": [
                "research_only:family=trend_continuation",
            ],
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
                "regime_modifier": {"key": "range", "state": "negative"},
                "session_modifier": {"key": "dead_session", "state": "negative"},
            },
            "experiment_context": {
                "available": True,
                "edge_state": "watch_edge",
                "true_edge_ratio": 0.75,
                "edge_decay_rate": 0.0635,
                "entry_timing_preferred_variant": "early_limit",
                "entry_timing_recommendation_reason": "higher_post_cost_true_edge_ratio",
                "entry_timing_comparison_ready": True,
                "execution_style_preferred_variant": "passive_limit",
                "execution_style_recommendation_reason": "better_fill_capture_ratio",
                "execution_style_comparison_ready": True,
                "accepted_candidate_focus": {
                    "symbol": "BTCUSDC",
                    "status": "ACTIONABLE_ENTRY",
                    "strategy_family": "trend_continuation",
                    "edge_state": "watch_edge",
                    "entry_timing_preferred_variant": "early_limit",
                    "execution_style_preferred_variant": "passive_limit",
                    "focus_source": "accepted_candidate_focus",
                },
                "blocked_candidate_focus": {
                    "symbol": "ETHUSDC",
                    "status": "BLOCKED_SETUP",
                    "strategy_family": "trend_continuation",
                    "block_reason": "mode_shadow_only",
                    "edge_state": "fragile_edge",
                    "entry_timing_preferred_variant": "reaction_confirmed",
                    "execution_style_preferred_variant": "market",
                    "focus_source": "blocked_candidate_focus",
                },
                "entry_timing_target": {
                    "symbol": "BTCUSDC",
                    "status": "ACTIONABLE_ENTRY",
                    "strategy_family": "trend_continuation",
                    "edge_state": "watch_edge",
                    "entry_timing_preferred_variant": "early_limit",
                    "execution_style_preferred_variant": "passive_limit",
                    "focus_source": "accepted_candidate_focus",
                },
                "execution_style_target": {
                    "symbol": "BTCUSDC",
                    "status": "ACTIONABLE_ENTRY",
                    "strategy_family": "trend_continuation",
                    "edge_state": "watch_edge",
                    "entry_timing_preferred_variant": "early_limit",
                    "execution_style_preferred_variant": "passive_limit",
                    "focus_source": "accepted_candidate_focus",
                },
            },
            "advisory_only": True,
        },
        rollout_recommendation={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "recommendation": "research_only",
            "confidence": "low",
            "maturity": "thin_sample",
            "summary": "family=trend_continuation should remain compare-only research while evidence matures; keep rollout policy unchanged and collect more outcome data.",
            "reason_codes": [
                "family_execution:watch",
                "mode_advisory:research_only",
                "sample:thin_sample",
                "policy:max_mode_micro_live",
            ],
            "current_policy": {
                "live_enabled": True,
                "max_execution_mode": "MICRO_LIVE",
                "max_risk_r": 1.0,
                "allowed_sessions": ["london", "new_york"],
                "min_quality_score": 75.0,
            },
            "suggested_policy_delta": {
                "action": "keep_research_only",
                "suggested_max_execution_mode": "MICRO_LIVE",
                "suggested_max_risk_r": 1.0,
                "change_hint": "keep_research_bucket_and_collect_evidence",
            },
            "top_modifier": {"axis": "session", "key": "dead_session", "state": "negative"},
            "source_summary": {
                "family_closed": 3,
                "family_baseline_cost_profitable_rate_from_closed": 0.3333,
                "family_execution_status": "watch",
                "family_mode_advisory_state": "research_only",
                "global_execution_status": "manual_review",
            },
        },
        strategy_lifecycle={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "state": "research",
            "previous_state": "production",
            "transition_bias": "observe",
            "confidence": "low",
            "summary": "family=trend_continuation remains research-led and the current window is still too thin to separate promotion from noise.",
            "reason_codes": [
                "lifecycle:research",
                "rollout_recommendation:research_only",
                "family_execution:watch",
                "family_mode:research_only",
                "sample:thin_sample",
                "modifier:negative",
            ],
            "source_summary": {
                "family_closed": 3,
                "family_post_cost_rate": 0.3333,
                "family_execution_status": "watch",
                "family_mode_advisory_state": "research_only",
                "rollout_recommendation": "research_only",
                "rollout_maturity": "thin_sample",
                "previous_state": "production",
                "alpha_research_signal": "research_active",
                "modifier_state": "negative",
            },
        },
        promotion_governance={
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
                "lifecycle:research",
                "rollout_recommendation:research_only",
                "positive_expansion:not_ready",
                "condition_modifier:cost_condition",
                "sample:thin_sample",
            ],
            "source_summary": {
                "lifecycle_state": "research",
                "rollout_recommendation": "research_only",
                "rollout_maturity": "thin_sample",
                "positive_expansion_state": "not_ready",
                "family_execution_status": "watch",
                "condition_modifier_state": "negative",
                "condition_modifier_axis": "cost_condition",
                "allocator_tier": "reduce",
                "capital_pressure": "overallocated_negative",
            },
        },
        promotion_review_queue={
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
                    "reason_codes": [
                        "promotion_governance:defer",
                        "lifecycle:research",
                    ],
                },
                {
                    "family": "sweep_reversal",
                    "review_action": "hold_monitor",
                    "promotion_state": "hold",
                    "target_posture": "keep_current",
                    "priority_rank": 30,
                    "confidence": "low",
                    "summary": "family=sweep_reversal should remain in the monitor queue while evidence accumulates.",
                    "reason_codes": ["promotion_governance:hold"],
                },
            ],
            "source_summary": {
                "promotion_ready_count": 0,
                "defer_count": 1,
                "hold_count": 1,
                "thin_sample_count": 1,
                "top_lifecycle_state": "research",
                "top_promotion_state": "defer",
                "top_allocator_tier": "reduce",
            },
        },
        promotion_remediation_queue={
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
                        "review_queue:defer_review",
                        "family_execution:manual_review",
                        "rollout_recommendation:reduce",
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
        promotion_clearance_tracker={
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
        promotion_reopen_queue={
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
        promotion_decision_brief={
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
        auto_promotion_rollout_execution={
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
        promotion_lifecycle_history={
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
        research_promotion_operating_loop={
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
        positive_evidence_expansion={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "state": "not_ready",
            "expansion_bias": "do_not_expand",
            "confidence": "low",
            "summary": "family=trend_continuation is not ready for positive expansion language because evidence or execution guardrails remain incomplete. The current sample is still too thin.",
            "reason_codes": [
                "positive_expansion:not_ready",
                "family_execution:watch",
                "rollout_recommendation:research_only",
                "lifecycle:research",
                "sample:thin_sample",
            ],
            "source_summary": {
                "family_closed": 3,
                "family_post_cost_rate": 0.3333,
                "family_execution_status": "watch",
                "family_mode_advisory_state": "research_only",
                "rollout_recommendation": "research_only",
                "rollout_maturity": "thin_sample",
                "lifecycle_state": "research",
                "allocator_tier": "reduce",
                "modifier_state": "negative",
            },
        },
        outcome_bucket_granularity={
            "available": True,
            "advisory_only": True,
            "report_window_days": 30,
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
            "reason_codes": [
                "family_focus:trend_continuation",
                "top_axis:cost_condition",
                "top_bucket:high_cost",
                "coverage:usable_condition_split",
            ],
            "condition_axes": [
                {
                    "axis": "volatility_condition",
                    "usable_bucket_count": 2,
                    "mature_bucket_count": 0,
                    "divergence": 0.05,
                },
                {
                    "axis": "cost_condition",
                    "usable_bucket_count": 2,
                    "mature_bucket_count": 0,
                    "divergence": 0.22,
                },
                {
                    "axis": "liquidity_condition",
                    "usable_bucket_count": 1,
                    "mature_bucket_count": 0,
                    "divergence": 0.0,
                    "proxy_note": "liquidity_proxy",
                },
            ],
        },
        opportunity_capture={
            "available": True,
            "advisory_only": True,
            "summary": "throughput is constrained more by blocking than by fill failure; family focus is trend_continuation",
            "report_window_days": 30,
            "trades_per_day": {"submitted": 0.2, "filled": 0.15, "closed": 0.1},
            "capture_rates": {
                "accept_rate": 0.35,
                "submit_rate_from_runtime": 0.2,
                "fill_rate_from_submitted": 0.75,
                "close_rate_from_filled": 0.6667,
            },
            "capture_gap": {
                "runtime_to_submit_gap": 0.8,
                "submit_to_fill_gap": 0.25,
                "fill_to_close_gap": 0.3333,
            },
            "blocked_mix": {"quality": 3, "rollout": 1, "structural": 0, "safety": 0, "unknown": 0},
            "dominant_bottleneck": {"stage": "runtime_to_submit", "reason": "quality_blocking"},
            "family_focus": {
                "key": "trend_continuation",
                "runtime_candidates": 6,
                "accepted_candidates": 2,
                "submitted": 1,
                "filled": 1,
                "closed": 1,
                "accept_rate": 0.3333,
                "submit_rate_from_runtime": 0.1667,
                "fill_rate_from_submitted": 1.0,
            },
            "regime_modifier": {"key": "range", "state": "negative"},
            "session_modifier": {"key": "dead_session", "state": "negative"},
            "maturity": "thin_activity",
        },
        capital_allocator={
            "available": True,
            "advisory_only": False,
            "allocator_state": "active",
            "family_focus": "trend_continuation",
            "capital_pressure": "overallocated_negative",
            "summary": "capital allowance is tilted away from degraded negative families; focus family is already overallocated relative to active risk",
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
        strategy_v2_pbo_dsr_trial_writer={
            "available": True,
            "implementation_status": "runtime_validation_proxy_writer_seeded",
            "reason": "pbo_dsr_runtime_proxy_writer_seeded",
            "sample_counts": {
                "eligible_closed_trades": 14,
                "candidate_trials": 9,
                "trial_runs_written": 9,
                "fold_scores_written": 18,
                "fold_count": 2,
            },
            "selected_trial_run_id": "trial_01",
            "parameter_families_present": ["mode_policy", "lock_policy", "stress_policy"],
        },
        strategy_v2_pbo_dsr_threshold_runner={
            "available": True,
            "implementation_status": "true_threshold_sweep_runner_seeded",
            "reason": "pbo_dsr_true_threshold_runner_seeded",
            "selection_rule": "true_threshold_sweep_top_in_sample_ev",
            "lineage_namespace": "true_threshold_sweep_runner_v1",
            "sample_counts": {
                "eligible_closed_trades": 14,
                "candidate_trials": 12,
                "trial_runs_written": 12,
                "fold_scores_written": 24,
                "fold_count": 2,
            },
            "selected_trial_run_id": "trial_threshold_01",
            "parameter_families_present": [
                "acceptance_rejection_thresholds",
                "scoring_thresholds",
                "sizing_clamps",
                "transition_threshold",
            ],
        },
        strategy_v2_pbo_dsr_artifact_store={
            "artifact_store_ready": True,
            "available": True,
            "metrics_available": True,
            "implementation_status": "artifact_store_metrics_available",
            "reason": "artifact_store_contains_computed_metrics",
            "counts": {"trial_runs": 3, "fold_scores": 9, "snapshots": 2},
            "parameter_families_present": ["transition_threshold", "sizing_clamps"],
            "selection_rule_counts": {
                "runtime_validation_proxy_top_in_sample_ev": 1,
                "true_threshold_sweep_top_in_sample_ev": 2,
            },
            "selection_universe_summary": {
                "combined_artifact_selection_universe_size": 3,
                "runtime_proxy_selection_universe_size": 1,
                "true_threshold_selection_universe_size": 2,
                "full_parameter_sweep_selection_universe_size": 2,
                "snapshot_dsr_selection_universe_size": 2,
                "snapshot_dsr_selection_universe_basis": "full_parameter_sweep_universe",
                "recording_status": "split_recorded",
            },
            "latest_snapshot": {
                "snapshot_id": "snapshot_2",
                "computation_state": "metrics_computed",
                "pbo_available": True,
                "dsr_available": True,
            },
        },
        strategy_v2_pbo_dsr_design={
            "design_ready": True,
            "available": True,
            "implementation_status": "design_ready_metrics_available_runtime",
            "reason": "pbo_dsr_runtime_metrics_available",
            "pbo": {
                "method": "CSCV",
                "objective_metric": "out_of_sample_mean_ev",
                "pass_threshold": 0.20,
                "warn_threshold": 0.35,
                "fail_threshold": 0.35,
            },
            "dsr": {
                "method": "deflated_sharpe_ratio",
                "min_threshold": 0.0,
            },
            "blocked_by": [
                "parameter sweep result store is not implemented",
                "fold-level trial ranking contract is not persisted",
            ],
            "next_steps": [
                "add parameter sweep artifact store",
                "persist CSCV fold scores and selection ranks",
            ],
        },
        strategy_v2_pbo_dsr_metrics={
            "available": True,
            "metrics_complete": True,
            "reason": "pbo_dsr_metrics_computed",
            "selection_rule_counts": {
                "runtime_validation_proxy_top_in_sample_ev": 1,
                "true_threshold_sweep_top_in_sample_ev": 2,
            },
            "selection_universe_summary": {
                "combined_artifact_selection_universe_size": 3,
                "runtime_proxy_selection_universe_size": 1,
                "true_threshold_selection_universe_size": 2,
                "full_parameter_sweep_selection_universe_size": 2,
                "selected_trial_lineage_selection_universe_size": 2,
                "dsr_selection_universe_size": 2,
                "dsr_selection_universe_basis": "full_parameter_sweep_universe",
                "bias_adjustment_rechecked": True,
                "recording_status": "split_recorded",
            },
            "selected_trial": {"trial_run_id": "trial_01", "writer_source": "true_threshold_sweep_runner_v1"},
            "lineage_audit": {
                "audit_status": "PASS",
                "reason": "selected_trial_from_true_threshold_with_dual_lineage",
                "lineage_mix_state": "dual_lineage",
                "selected_trial_from_runtime_proxy": False,
                "selected_trial_from_true_threshold": True,
            },
            "pbo": {
                "available": True,
                "value": 0.333333,
                "status": "WARN",
                "eligible_folds": 6,
                "overfit_folds": 2,
            },
            "dsr": {
                "available": True,
                "value": 0.241,
                "probability": 0.5952,
                "status": "PASS",
                "benchmark_sharpe": 1.11,
                "selection_universe_basis": "full_parameter_sweep_universe",
                "legacy_combined_selection_universe_size": 3,
                "legacy_combined_benchmark_sharpe": 1.23,
                "benchmark_sharpe_delta_vs_legacy_combined": -0.12,
            },
            "deployment_recommendation": {
                "decision": "warn_overfit_risk",
                "meets_protocol_gate": True,
            },
        },
        strategy_v2_stress_validation={
            "available": True,
            "comparison_axis": "baseline_vs_stressed_cost",
            "sample_counts": {
                "execution_data_trades": 6,
                "estimate_only_trades": 3,
                "latency_reference_trades": 9,
                "shock_regime_trades": 2,
            },
            "stress_metrics": {
                "baseline_cost": {
                    "trades": 9,
                    "ev": 0.18,
                    "p5_ev": -0.4,
                    "max_drawdown": 1.8,
                    "ulcer_index": 0.8,
                },
                "stressed_cost": {
                    "trades": 9,
                    "ev": 0.07,
                    "p5_ev": -0.9,
                    "max_drawdown": 2.7,
                    "ulcer_index": 1.2,
                },
            },
            "comparison": {
                "ev": -0.11,
                "p5_ev": -0.5,
                "max_drawdown": 0.9,
                "ulcer_index": 0.4,
            },
            "scenario_metrics": {
                "latency_plus_1_bar": {"trades": 9, "ev": -0.04, "p5_ev": -1.1, "max_drawdown": 3.0},
                "partial_fills_only": {"trades": 9, "ev": 0.02, "p5_ev": -0.8, "max_drawdown": 2.4},
                "shock_concentration": {"trades": 9, "ev": -0.01, "p5_ev": -1.0, "max_drawdown": 3.3},
            },
            "scenario_comparison": {
                "latency_plus_1_bar": {"ev": -0.22, "max_drawdown": 1.2},
                "partial_fills_only": {"ev": -0.16, "max_drawdown": 0.6},
                "shock_concentration": {"ev": -0.19, "max_drawdown": 1.5},
            },
            "deployment_recommendation": {
                "stress_pass": False,
                "reason": "scenario_catastrophic_drawdown:shock_concentration",
                "worst_scenario": "shock_concentration",
                "worst_scenario_source": "replay_output",
                "replay_gate_applied": True,
                "replay_gate_reason": "replay_output_override:latency_plus_1_bar,shock_concentration",
                "divergence_gate_applied": True,
                "divergence_problem_scenarios": ["latency_plus_1_bar", "shock_concentration"],
                "worst_divergence_scenario": "shock_concentration",
                "scenario_statuses": {
                    "latency_plus_1_bar": {
                        "status": "WARN",
                        "reason": "negative_ev:replay_output",
                        "source": "replay_output",
                    },
                    "partial_fills_only": {"status": "PASS", "reason": "within_limits"},
                    "shock_concentration": {
                        "status": "FAIL",
                        "reason": "catastrophic_drawdown:replay_output",
                        "source": "replay_output",
                    },
                },
            },
            "replay_output_artifacts": {
                "available": True,
                "comparison_ready": True,
                "reason": "replay_worker_output_artifacts_loaded",
                "summary_counts": {
                    "scenarios_expected": 3,
                    "scenarios_with_artifacts": 2,
                    "scenarios_compared": 2,
                    "replay_trade_rows": 13,
                },
                "lineage_summary": {
                    "available": True,
                    "worker_modes": ["prototype_from_lineage_batches"],
                    "compared_scenarios": ["latency_plus_1_bar", "shock_concentration"],
                    "input_batch_count": 2,
                    "input_trade_rows": 13,
                },
                "scenario_outputs": {
                    "latency_plus_1_bar": {
                        "available": True,
                        "reason": "artifact_loaded",
                        "summary": {"trades": 9, "ev": -0.09, "max_drawdown": 3.2},
                        "comparison_to_approximation": {"ev": -0.05, "max_drawdown": 0.2},
                        "input_lineage_summary": {"input_trade_rows": 9},
                    },
                    "partial_fills_only": {
                        "available": False,
                        "reason": "artifact_missing",
                        "summary": {},
                        "comparison_to_approximation": {},
                    },
                    "shock_concentration": {
                        "available": True,
                        "reason": "artifact_loaded",
                        "summary": {"trades": 4, "ev": -0.18, "max_drawdown": 3.6},
                        "comparison_to_approximation": {"ev": -0.17, "max_drawdown": 0.3},
                        "input_lineage_summary": {"input_trade_rows": 4},
                    },
                },
            },
            "replay_output_comparison": {
                "latency_plus_1_bar": {"ev": -0.05, "max_drawdown": 0.2},
                "shock_concentration": {"ev": -0.17, "max_drawdown": 0.3},
            },
        },
        strategy_v2_stress_replay_lineage={
            "available": True,
            "runtime_inputs_ready": False,
            "reason": "runtime_lineage_incomplete",
            "coverage": {
                "execution_fill_coverage": 0.66,
                "estimate_only_share": 0.34,
                "latency_candle_coverage": 0.77,
                "candle_path_coverage": 0.72,
            },
            "fill_path": {
                "entry_anchor_sources": {"execution_entry_fill": 6, "plan_valid_from": 3},
                "exit_anchor_sources": {"execution_closed_fill": 5, "plan_final_exit_ts": 4},
            },
            "candle_path": {
                "avg_path_coverage_ratio": 0.81,
            },
            "gap_counts": {
                "missing_entry_fill": 1,
                "missing_close_fill": 4,
            },
        },
        strategy_v2_stress_replay_assessment={
            "available": True,
            "full_replay_ready": True,
            "replacement_recommended": True,
            "true_runner_readiness": {
                "true_runner_ready": False,
                "stage": "prototype_only",
                "critical_scenarios": ["latency_plus_1_bar", "shock_concentration"],
                "critical_scenarios_with_outputs": ["latency_plus_1_bar"],
                "blocked_by": ["critical_replay_scenarios_missing_output"],
            },
            "coverage": {
                "execution_fill_coverage": 0.82,
                "estimate_only_share": 0.18,
                "latency_candle_coverage": 0.76,
                "candle_path_coverage": 0.72,
            },
            "scenario_evidence": {
                "degraded_scenarios": ["latency_plus_1_bar", "shock_concentration"],
                "catastrophic_scenarios": [],
                "worst_scenario": "shock_concentration",
            },
            "deployment_recommendation": {
                "decision": "prepare_full_replay",
                "priority": "medium",
                "reason": "multiple_degraded_scenarios:latency_plus_1_bar,shock_concentration",
                "true_runner_promotion_gate_applied": True,
                "true_runner_promotion_ready": False,
                "true_runner_promotion_status": "BLOCKED",
                "true_runner_promotion_action": "stay_on_prototype",
                "true_runner_promotion_reason": "replay_output_lineage_alignment:selected_trial_from_runtime_proxy_with_replay_output_lineage",
                "threshold_lineage_audit_status": "WARN",
                "threshold_lineage_audit_reason": "selected_trial_from_runtime_proxy_while_true_threshold_lineage_exists",
                "replay_output_lineage_alignment_status": "WARN",
                "replay_output_lineage_alignment_reason": "selected_trial_from_runtime_proxy_with_replay_output_lineage",
                "replay_output_lineage_compared_scenarios": ["latency_plus_1_bar", "shock_concentration"],
                "selected_trial_writer_source": "runtime_validation_proxy_v1",
                "approval_cross_display": {
                    "cross_display_status": "REVIEW",
                    "cross_display_reason": "runtime_proxy_winner_with_replay_worst_scenario",
                    "threshold_lineage_winner_source": "runtime_validation_proxy_v1",
                    "threshold_lineage_winner_selection_rule": "runtime_validation_proxy_top_in_sample_ev",
                    "threshold_lineage_winner_type": "runtime_proxy",
                    "threshold_lineage_audit_status": "WARN",
                    "replay_derived_worst_scenario": "shock_concentration",
                    "replay_derived_worst_scenario_source": "replay_output",
                    "replay_derived_worst_scenario_status": "FAIL",
                    "replay_derived_worst_scenario_reason": "catastrophic_drawdown:replay_output",
                    "replay_derived_worst_scenario_divergence_status": "FAIL",
                    "replay_output_compared_scenarios": ["latency_plus_1_bar", "shock_concentration"],
                    "replay_output_input_trade_rows": 13,
                    "approval_warning_locked": True,
                    "approval_warning_code": "proxy_selected_trial_against_replay_backed_worst_scenario",
                    "approval_warning_message": (
                        "runtime proxy selected-trial remains active while replay-backed worst scenario is driving downside; "
                        "do not treat this approval template as threshold-lineage confirmed"
                    ),
                },
            },
        },
        strategy_v2_stress_replay_runner_contract={
            "available": True,
            "runtime_job_ready": True,
            "implementation_status": "runner_contract_defined_high_priority_prototype",
            "true_runner_readiness": {
                "true_runner_ready": False,
                "stage": "prototype_only",
                "blocked_by": ["critical_replay_scenarios_missing_output"],
            },
            "reason": "stress_replay_runner_contract_recommended",
            "readiness": {
                "priority": "high",
                "ready_scenarios": ["shock_concentration", "latency_plus_1_bar"],
                "blocked_scenarios": ["partial_fills_only"],
                "suggested_total_jobs": 3,
            },
            "runner_contract": {
                "batching": {
                    "target_trades_per_job": 20,
                    "min_trades_per_job": 8,
                    "max_parallel_jobs": 2,
                }
            },
        },
        strategy_v2_stress_replay_lineage_writer={
            "available": True,
            "artifacts_written": True,
            "runtime_job_ready": True,
            "implementation_status": "lineage_writer_seeded_scenario_batches",
            "reason": "stress_replay_lineage_batches_written",
            "sample_counts": {
                "trade_rows_written": 7,
                "batches_written": 3,
                "scenarios_written": 2,
            },
        },
        strategy_v2_stress_replay_prototype_worker={
            "available": True,
            "executed": True,
            "runtime_job_ready": True,
            "reason": "stress_replay_prototype_worker_outputs_written",
            "sample_counts": {
                "ready_scenarios": 3,
                "executed_scenarios": 2,
                "input_batches_read": 3,
                "replay_trade_rows_written": 11,
            },
        },
        strategy_v2_thesis_validation={
            "available": True,
            "comparison_axis": "thesis_dedupe",
            "evaluation_scope": "portfolio_global",
            "sample_counts": {
                "blocked_duplicate_trades": 2,
                "blocked_active_cluster_cap_trades": 1,
            },
            "thesis_metrics": {
                "before_dedupe": {
                    "trades": 12,
                    "ev": 0.21,
                    "p5_ev": -0.6,
                    "max_drawdown": 2.4,
                    "ulcer_index": 1.1,
                },
                "after_dedupe": {
                    "trades": 9,
                    "ev": 0.29,
                    "p5_ev": -0.2,
                    "max_drawdown": 1.3,
                    "ulcer_index": 0.6,
                },
            },
            "comparison": {
                "ev": 0.08,
                "p5_ev": 0.4,
                "max_drawdown": -1.1,
                "ulcer_index": -0.5,
            },
            "deployment_recommendation": {
                "keep_dedupe_enabled": True,
                "reason": "dedupe_downside_improved",
            },
        },
    )

    path = Path(result["path"])
    body = path.read_text(encoding="utf-8")
    assert path.exists()
    assert result["status"] in {"PASS", "WARN", "FAIL"}
    assert "BTCUSDC" in path.name
    assert "## Performance Decomposition" in body
    assert "recommended_action: run_shadow_exit_review" in body
    assert "recommended_action_deferred_by_sequence: True" in body
    assert "recommended_action_current_priority: entry_timing:run_entry_timing_split_review" in body
    assert "shadow_experiment_type: exit_failure_review" in body
    assert "top_shadow_experiment_id: shadow_exit_review_family" in body
    assert "top_shadow_experiment_title: Family Exit Failure Review" in body
    assert "top_shadow_experiment_deferred_by_sequence: True" in body
    assert "experiment_sequence: state=entry_timing_first" in body
    assert "experiment_1: shadow_exit_review_family" in body
    assert "## Score To Outcome Funnel" in body
    assert "snapshot_selection: runtime=12, accepted=5, blocked=7" in body
    assert "historical_execution_outcomes: submitted=9, filled=7, closed=6, profitable=4" in body
    assert "operating_kpis: primary_focus=after_cost_edge_proof" in body
    assert "operating_kpi_summary: runtime_accept=" in body
    assert "## Execution Degradation Advisory" in body
    assert "status: manual_review" in body
    assert "recommended_action: review_runtime_execution_drag_before_expansion" in body
    assert "## Mode Advisory" in body
    assert "top_family: bucket=trend_continuation state=research_only" in body
    assert "## Outcome Control Trace" in body
    assert "## Edge Experiment Review" in body
    assert "operating_discipline: state=research_only_until_edge_proof_goal" in body
    assert "framework=framework_ready" in body
    assert "mode=operate_and_experiment" in body
    assert "identity=edge_proof_engine" in body
    assert "next_stage=post_first_verified_edge" in body
    assert "resilience=harder_to_fail_from_self_deception" in body
    assert "fail_safe_claim=False" in body
    assert "dependencies=market_edge/execution_quality/operating_discipline" in body
    assert "improvement_priority=prove_single_edge_before_density_or_strategy_expansion" in body
    assert "loss_driven_rewrite_allowed=False" in body
    assert "early_loss_embargo_active=True" in body
    assert "rollout_expansion_allowed=False" in body
    assert "alpha_generator_review_allowed=False" in body
    assert "signal_density_review_allowed=False" in body
    assert "execution_strategy_automation_review_allowed=False" in body
    assert "multi_strategy_expansion_review_allowed=False" in body
    assert "experiment_sequence: state=sample_building_before_exit_optimization" in body
    assert "primary_goal=find_first_verified_edge" in body
    assert "evaluation_focus=after_cost_edge_only" in body
    assert "min_closed_trades=100" in body
    assert "## Approval Strip" in body
    assert "## Multi Strategy AB Expansion" in body
    assert "## B Continuation Activation" in body
    assert "## Forward Stress Regime Validation" in body
    assert "## Kill Condition Automation" in body
    assert "## Strategy Cluster Balance" in body
    assert "## Auto Promotion Rollout Execution" in body
    assert "## Promotion Lifecycle History" in body
    assert "## Research Promotion Operating Loop" in body
    assert "## Capital Allocator" in body
    assert result["feature_importance_available"] is True
    assert result["feature_calibration_available"] is True
    assert result["strategy_v2_validation_available"] is True
    assert result["strategy_v2_validation_summary"]["best_ev_family"] == "trend_continuation"
    assert result["strategy_v2_validation_summary"]["best_ev_regime"] == "range"
    assert result["strategy_v2_validation_summary"]["best_ev_session"] == "overlap"
    assert result["performance_decomposition_summary"]["family"]["best_ev"]["name"] == "trend_continuation"
    assert result["performance_decomposition_summary"]["regime"]["worst_ev"]["name"] == "shock"
    assert result["performance_decomposition_summary"]["session"]["worst_ev"]["name"] == "dead_session"
    assert result["performance_decomposition_summary"]["entry_model"]["worst_fill_rate"]["name"] == "LIMIT"
    assert (
        result["performance_decomposition_summary"]["family"]["highest_information_failure_rate"]["name"]
        == "trend_continuation"
    )
    assert (
        result["performance_decomposition_summary"]["cost"]["delta_ev_stressed_minus_baseline"]
        == -0.11
    )
    assert result["strategy_v2_scalp_experiment_available"] is True
    assert result["strategy_v2_scalp_experiment_summary"]["preferred_branch"] == "experiment"
    assert (
        result["strategy_v2_scalp_experiment_summary"]["recommendation_reason"]
        == "experiment_has_higher_sized_ev"
    )
    assert result["alpha_research_pipeline_available"] is True
    assert result["alpha_research_pipeline_summary"]["alpha_research_candidate_count"] == 3
    assert result["alpha_research_pipeline_summary"]["analysis_symbol"] == "BTCUSDC"
    assert result["alpha_research_pipeline_summary"]["aligned_candidate_count"] == 2
    assert result["alpha_research_pipeline_summary"]["top_alignment_focus"] == "family_information_failure"
    assert result["alpha_research_pipeline_summary"]["recommended_action"] == "run_shadow_exit_review"
    assert result["score_to_outcome_funnel"]["available"] is True
    assert result["score_to_outcome_funnel_summary"]["runtime_candidates"] == 12
    assert result["score_to_outcome_funnel_summary"]["submitted"] == 9
    assert result["score_to_outcome_funnel_summary"]["baseline_cost_profitable"] == 3
    assert result["score_to_outcome_funnel_summary"]["money_funnel"]["historical_expected_r"]["closed"] == 0.96
    assert result["score_to_outcome_funnel_summary"]["top_family_bucket"]["key"] == "trend_continuation"
    assert result["score_to_outcome_funnel_summary"]["top_entry_timing_bucket"]["key"] == "early_limit"
    assert result["score_to_outcome_funnel_summary"]["top_execution_style_bucket"]["key"] == "passive_limit"
    assert result["execution_degradation_advisory_available"] is True
    assert result["execution_degradation_advisory_summary"]["status"] == "manual_review"
    assert result["execution_degradation_advisory_summary"]["recommended_action"] == (
        "review_runtime_execution_drag_before_expansion"
    )
    assert result["family_execution_degradation_advisory"]["available"] is True
    assert result["family_execution_degradation_advisory_summary"]["available"] is True
    assert result["family_execution_degradation_advisory_summary"]["family_count"] == 1
    assert result["family_execution_degradation_advisory_summary"]["top_family"]["family"] == "trend_continuation"
    assert result["family_execution_degradation_advisory_summary"]["top_family"]["status"] == "watch"
    assert result["mode_advisory"]["available"] is True
    assert result["mode_advisory_summary"]["available"] is True
    assert result["mode_advisory_summary"]["family_top"]["bucket"] == "trend_continuation"
    assert result["mode_advisory_summary"]["family_top"]["advisory_state"] == "research_only"
    assert result["mode_advisory_summary"]["regime_top"]["bucket"] == "range"
    assert result["mode_advisory_summary"]["session_top"]["bucket"] == "dead_session"
    assert result["operator_action_priority"]["available"] is True
    assert result["operator_action_priority_summary"]["available"] is True
    assert result["operator_action_priority_summary"]["top_action"] == "review_runtime_execution_drag_before_expansion"
    assert result["operator_action_priority_summary"]["priority_level"] == "urgent"
    assert result["operator_action_priority_summary"]["priority_source"] == "execution_degradation"
    assert result["operator_action_priority_summary"]["action_family"] == "execution_review"
    assert result["operator_action_priority_summary"]["top_action_followup_command"] == ""
    assert result["operator_action_priority_summary"]["capture_context"]["dominant_bottleneck"]["reason"] == "quality_blocking"
    assert result["operator_action_priority_summary"]["capture_context"]["family_focus"]["key"] == "trend_continuation"
    assert result["operator_action_priority_summary"]["experiment_context"]["entry_timing_target"]["symbol"] == "BTCUSDC"
    assert result["operator_action_priority_summary"]["experiment_context"]["entry_timing_target"]["followup_command"].endswith(
        "--symbol BTCUSDC --universe micro_live_usdt_12 --days 30 --action run_entry_timing_split_review"
    )
    assert result["operator_action_priority_summary"]["experiment_context"]["execution_style_target"]["symbol"] == "BTCUSDC"
    assert result["operator_action_priority_summary"]["experiment_context"]["execution_style_target"]["followup_command"].endswith(
        "--symbol BTCUSDC --universe micro_live_usdt_12 --days 30 --action run_execution_style_split_review"
    )
    assert result["operator_action_priority_summary"]["advisory_only"] is True
    assert len(result["operator_action_priority_summary"]["next_actions"]) == 1
    assert result["operator_action_priority_summary"]["next_actions"][0]["followup_command"] == ""
    assert result["outcome_control_trace_available"] is True
    assert result["outcome_control_trace_summary"]["approval_penalty_status"] == "manual_review"
    assert result["outcome_control_trace_summary"]["approval_penalty_tier"] == "downgrade_to_manual"
    assert result["outcome_control_trace_summary"]["sizing_penalty_status"] == "watch"
    assert result["outcome_control_trace_summary"]["sizing_penalty_tier"] == "soft_clamp"
    assert result["outcome_control_trace_summary"]["sizing_multiplier"] == 0.75
    assert result["outcome_control_trace_summary"]["portfolio_bias_tier"] == "positive"
    assert result["outcome_control_trace_summary"]["portfolio_bias_score_delta"] == 0.5
    assert "execution_degradation:manual_review" in result["outcome_control_trace_summary"]["top_reason_codes"]
    assert result["outcome_attribution_available"] is True
    assert result["outcome_attribution_summary"]["strongest_drag_source"] == "fill_capture_gap"
    assert result["outcome_attribution_summary"]["strategy_component_r"] == 0.96
    assert result["outcome_attribution_summary"]["execution_component_r"] == -0.12
    assert result["outcome_attribution_summary"]["condition_component_r"] == -0.12
    assert result["outcome_attribution_summary"]["fill_capture_gap_r"] == 0.33
    assert result["edge_experiment_review_available"] is True
    assert result["edge_experiment_review_summary"]["edge_state"] == "watch_edge"
    assert result["edge_experiment_review_summary"]["true_edge_ratio"] == 0.75
    assert result["edge_experiment_review_summary"]["entry_timing_preferred_variant"] == "early_limit"
    assert result["edge_experiment_review_summary"]["execution_style_preferred_variant"] == "passive_limit"
    assert result["edge_experiment_review_summary"]["edge_proof_goal_closed_trades"] == 100
    assert result["edge_experiment_review_summary"]["edge_proof_posture"]["state"] == "sample_building"
    assert result["edge_experiment_review_summary"]["operating_discipline"]["discipline_state"] == "research_only_until_edge_proof_goal"
    assert result["edge_experiment_review_summary"]["operating_discipline"]["system_mode"] == "operate_and_experiment"
    assert result["edge_experiment_review_summary"]["operating_discipline"]["current_system_identity"] == "edge_proof_engine"
    assert result["edge_experiment_review_summary"]["operating_discipline"]["next_system_stage"] == "post_first_verified_edge"
    assert (
        result["edge_experiment_review_summary"]["operating_discipline"]["resilience_claim"]
        == "harder_to_fail_from_self_deception"
    )
    assert result["edge_experiment_review_summary"]["operating_discipline"]["fail_safe_claim"] is False
    assert result["edge_experiment_review_summary"]["operating_discipline"]["realized_edge_dependency_domains"] == [
        "market_edge",
        "execution_quality",
        "operating_discipline",
    ]
    assert result["edge_experiment_review_summary"]["operating_discipline"]["evaluation_focus"] == "after_cost_edge_only"
    assert result["edge_experiment_review_summary"]["operating_discipline"]["profit_claim_allowed"] is False
    assert result["edge_experiment_review_summary"]["operating_discipline"]["early_loss_rewrite_embargo_active"] is True
    assert result["edge_experiment_review_summary"]["operating_discipline"]["loss_driven_rewrite_allowed"] is False
    assert result["edge_experiment_review_summary"]["operating_discipline"]["rollout_expansion_allowed"] is False
    assert (
        result["edge_experiment_review_summary"]["operating_discipline"]["improvement_priority"]
        == "prove_single_edge_before_density_or_strategy_expansion"
    )
    assert result["edge_experiment_review_summary"]["operating_discipline"]["alpha_generator_review_allowed"] is False
    assert result["edge_experiment_review_summary"]["operating_discipline"]["signal_density_control_review_allowed"] is False
    assert result["edge_experiment_review_summary"]["operating_discipline"]["execution_strategy_automation_review_allowed"] is False
    assert result["edge_experiment_review_summary"]["operating_discipline"]["multi_strategy_expansion_review_allowed"] is False
    assert result["edge_experiment_review_summary"]["operating_discipline"]["deferred_system_upgrade_backlog"] == [
        "alpha_generator_layer",
        "capital_scale_curve",
        "signal_density_controller",
        "execution_strategy_automation",
        "multi_strategy_activation",
    ]
    assert result["edge_experiment_review_summary"]["daily_edge_kpis"]["true_edge_ratio"] == 0.75
    assert result["score_to_outcome_funnel_summary"]["operating_kpis"]["primary_focus"] == "after_cost_edge_proof"
    assert result["score_to_outcome_funnel_summary"]["operating_kpis"]["stage_conversion_rates"]["runtime_to_accepted"] == 0.4167
    assert result["score_to_outcome_funnel_summary"]["operating_kpis"]["cost_adjusted_survival_rate"] == 0.5
    assert result["edge_evolution_rule_available"] is True
    assert result["edge_evolution_rule_summary"]["evolution_state"] == "reduce_candidate"
    assert result["edge_evolution_rule_summary"]["recommended_action"] == "reduce_baseline_allocation_review"
    assert result["edge_evolution_rule_summary"]["allocation_bias"] == "reduce_baseline"
    assert result["review_followup_ledger_available"] is False
    assert result["review_followup_ledger_summary"]["available"] is False
    assert result["review_followup_ledger_summary"]["last_status"] == "none"
    assert result["rollout_recommendation_available"] is True
    assert result["rollout_recommendation_summary"]["family"] == "trend_continuation"
    assert result["rollout_recommendation_summary"]["recommendation"] == "research_only"
    assert result["rollout_recommendation_summary"]["suggested_policy_delta"]["action"] == "keep_research_only"
    assert result["strategy_lifecycle_available"] is True
    assert result["strategy_lifecycle_summary"]["family"] == "trend_continuation"
    assert result["strategy_lifecycle_summary"]["state"] == "research"
    assert result["strategy_lifecycle_summary"]["transition_bias"] == "observe"
    assert result["multi_strategy_ab_available"] is True
    assert result["multi_strategy_ab_summary"]["mode"] == "A_ONLY"
    assert result["multi_strategy_ab_summary"]["raw_family_anchor"] == "sweep_reversal"
    assert result["multi_strategy_ab_summary"]["a_cluster"]["cluster"] == "a_reversal"
    assert result["multi_strategy_ab_summary"]["b_cluster"]["cluster"] == "b_continuation"
    assert result["multi_strategy_ab_summary"]["b_cluster"]["strategy_cluster_status"] == "compare_only"
    assert result["b_continuation_activation_available"] is True
    assert result["b_continuation_activation_summary"]["family"] == "trend_continuation"
    assert result["b_continuation_activation_summary"]["activation_state"] == "research_only"
    assert result["b_continuation_activation_summary"]["activation_bias"] == "stay_research"
    assert result["execution_friction_measurement_available"] is True
    assert result["execution_friction_measurement_summary"]["friction_state"] == "watch_friction"
    assert result["execution_friction_measurement_summary"]["friction_bias"] == "monitor_execution_drag"
    assert result["execution_friction_measurement_summary"]["weakest_axis"] == "slippage_state"
    assert result["forward_stress_regime_validation_available"] is True
    assert result["forward_stress_regime_validation_summary"]["validation_state"] == "fragile_generalization"
    assert (
        result["forward_stress_regime_validation_summary"]["validation_bias"]
        == "monitor_regime_stress_fragility"
    )
    assert result["forward_stress_regime_validation_summary"]["weakest_axis"] == "stress_state"
    assert result["kill_condition_automation_available"] is True
    assert result["kill_condition_automation_summary"]["kill_condition_state"] == "close_only_review"
    assert result["kill_condition_automation_summary"]["automation_bias"] == "propose_close_only"
    assert result["kill_condition_automation_summary"]["trigger_axis"] == "reconciliation_axis"
    assert result["b_continuation_edge_validation_available"] is True
    assert result["b_continuation_edge_validation_summary"]["raw_family"] == "trend_continuation"
    assert result["b_continuation_edge_validation_summary"]["edge_state"] == "fragile_edge"
    assert result["b_continuation_edge_validation_summary"]["validation_bias"] == "monitor_diversification"
    assert result["strategy_cluster_balance_available"] is True
    assert result["strategy_cluster_balance_summary"]["mode"] == "A_ONLY"
    assert result["strategy_cluster_balance_summary"]["balance_state"] == "research_only_mix"
    assert result["strategy_cluster_balance_summary"]["balance_bias"] == "stay_a_anchor"
    assert result["a_strategy_post_cost_edge_validation_available"] is True
    assert result["a_strategy_post_cost_edge_validation_summary"]["family"] == "sweep_reversal"
    assert result["a_strategy_post_cost_edge_validation_summary"]["edge_state"] == "fragile_edge"
    assert result["a_strategy_post_cost_edge_validation_summary"]["validation_bias"] == "monitor_fragility"
    assert result["promotion_governance_available"] is True
    assert result["promotion_governance_summary"]["family"] == "trend_continuation"
    assert result["promotion_governance_summary"]["state"] == "defer"
    assert result["promotion_governance_summary"]["promotion_bias"] == "defer"
    assert result["promotion_governance_summary"]["target_posture"] == "keep_current"
    assert result["promotion_review_queue_available"] is True
    assert result["promotion_review_queue_summary"]["queue_state"] == "defer_first_queue"
    assert result["promotion_review_queue_summary"]["headline_family"] == "trend_continuation"
    assert result["promotion_review_queue_summary"]["top_review_action"] == "defer_review"
    assert result["promotion_remediation_queue_available"] is True
    assert result["promotion_remediation_queue_summary"]["queue_state"] == "execution_first_queue"
    assert result["promotion_remediation_queue_summary"]["headline_family"] == "trend_continuation"
    assert result["promotion_remediation_queue_summary"]["top_remediation_action"] == "execution_remediation"
    assert result["promotion_clearance_tracker_available"] is True
    assert result["promotion_clearance_tracker_summary"]["family"] == "trend_continuation"
    assert result["promotion_clearance_tracker_summary"]["clearance_state"] == "blocked"
    assert result["promotion_clearance_tracker_summary"]["clearance_bias"] == "continue_remediation"
    assert result["promotion_reopen_queue_available"] is True
    assert result["promotion_reopen_queue_summary"]["queue_state"] == "clearance_first_queue"
    assert result["promotion_reopen_queue_summary"]["headline_family"] == "trend_continuation"
    assert result["promotion_reopen_queue_summary"]["top_reopen_action"] == "continue_clearance"
    assert result["promotion_decision_brief_available"] is True
    assert result["promotion_decision_brief_summary"]["family"] == "trend_continuation"
    assert result["promotion_decision_brief_summary"]["brief_state"] == "clearance_required"
    assert result["promotion_decision_brief_summary"]["decision_bias"] == "continue_clearance"
    assert result["auto_promotion_rollout_execution_available"] is True
    assert result["auto_promotion_rollout_execution_summary"]["target_family"] == "trend_continuation"
    assert result["auto_promotion_rollout_execution_summary"]["execution_stage"] == "auto_execution_blocked"
    assert result["auto_promotion_rollout_execution_summary"]["execution_bias"] == "block_auto_execution"
    assert result["promotion_lifecycle_history_available"] is True
    assert result["promotion_lifecycle_history_summary"]["family"] == "trend_continuation"
    assert result["promotion_lifecycle_history_summary"]["history_state"] == "history_attention_required"
    assert result["promotion_lifecycle_history_summary"]["latest_event_type"] == "remediation_started"
    assert result["research_promotion_operating_loop_available"] is True
    assert result["research_promotion_operating_loop_summary"]["family"] == "trend_continuation"
    assert result["research_promotion_operating_loop_summary"]["loop_state"] == "shadow_test_ready"
    assert result["research_promotion_operating_loop_summary"]["target_stage"] == "tested"
    assert result["positive_evidence_expansion_available"] is True
    assert result["positive_evidence_expansion_summary"]["family"] == "trend_continuation"
    assert result["positive_evidence_expansion_summary"]["state"] == "not_ready"
    assert result["positive_evidence_expansion_summary"]["expansion_bias"] == "do_not_expand"
    assert result["outcome_bucket_granularity_available"] is True
    assert result["outcome_bucket_granularity_summary"]["family_focus"]["key"] == "trend_continuation"
    assert result["outcome_bucket_granularity_summary"]["top_condition_axis"] == "cost_condition"
    assert result["outcome_bucket_granularity_summary"]["top_condition_bucket"]["key"] == "high_cost"
    assert result["opportunity_capture_available"] is True
    assert result["opportunity_capture_summary"]["dominant_bottleneck"]["reason"] == "quality_blocking"
    assert result["opportunity_capture_summary"]["family_focus"]["key"] == "trend_continuation"
    assert result["opportunity_capture_summary"]["capture_gap"]["runtime_to_submit_gap"] == 0.8
    assert result["capital_allocator_available"] is True
    assert result["capital_allocator_summary"]["allocator_state"] == "active"
    assert result["capital_allocator_summary"]["family_focus"] == "trend_continuation"
    assert result["capital_allocator_summary"]["capital_pressure"] == "overallocated_negative"
    assert result["alpha_research_pipeline_summary"]["recommended_scope"] == "family"
    assert result["alpha_research_pipeline_summary"]["recommended_reason"] == (
        "information_failure_rate is elevated for this family"
    )
    assert result["alpha_research_pipeline_summary"]["shadow_experiment_type"] == "exit_failure_review"
    assert result["alpha_research_pipeline_summary"]["recommended_focus"] == "family_information_failure"
    assert result["alpha_research_pipeline_summary"]["recommended_bucket"] == "trend_continuation"
    assert result["alpha_research_pipeline_summary"]["confidence"] == "medium"
    assert result["alpha_research_pipeline_summary"]["sample_note"] == "usable evidence, but still limited"
    assert result["alpha_research_pipeline_summary"]["recommended_action_deferred_by_sequence"] is True
    assert result["alpha_research_pipeline_summary"]["recommended_action_current_priority_experiment"] == "entry_timing"
    assert result["alpha_research_pipeline_summary"]["recommended_action_current_priority_action"] == (
        "run_entry_timing_split_review"
    )
    assert result["alpha_research_pipeline_summary"]["top_shadow_experiment_id"] == "shadow_exit_review_family"
    assert result["alpha_research_pipeline_summary"]["top_shadow_experiment_title"] == "Family Exit Failure Review"
    assert result["alpha_research_pipeline_summary"]["top_shadow_experiment_target"] == "family=trend_continuation"
    assert (
        result["alpha_research_pipeline_summary"]["top_shadow_experiment_objective"]
        == "Determine whether elevated information failure in this family is an exit issue or a deeper quality problem."
    )
    assert result["alpha_research_pipeline_summary"]["top_shadow_experiment_confidence"] == "medium"
    assert "post_cost_ev" in result["alpha_research_pipeline_summary"]["top_shadow_experiment_observe_metrics"]
    assert len(result["alpha_research_pipeline_summary"]["top_shadow_experiment_success_criteria"]) == 2
    assert len(result["alpha_research_pipeline_summary"]["top_shadow_experiment_stop_conditions"]) == 2
    assert result["alpha_research_pipeline_summary"]["top_shadow_experiment_deferred_by_sequence"] is True
    assert result["alpha_research_pipeline_summary"]["experiment_sequence_state"] == "entry_timing_first"
    assert result["alpha_research_pipeline_summary"]["entry_timing_locked"] is False
    assert result["alpha_research_pipeline_summary"]["execution_style_locked"] is False
    assert result["alpha_research_pipeline_summary"]["exit_optimization_allowed"] is False
    assert result["alpha_research_pipeline_summary"]["current_priority_experiment"] == "entry_timing"
    assert result["alpha_research_pipeline_summary"]["current_priority_action"] == "run_entry_timing_split_review"
    assert (
        result["alpha_research_pipeline_summary"]["improvement_priority"]
        == "prove_single_edge_before_density_or_strategy_expansion"
    )
    assert result["alpha_research_pipeline_summary"]["current_system_identity"] == "edge_proof_engine"
    assert result["alpha_research_pipeline_summary"]["next_system_stage"] == "post_first_verified_edge"
    assert result["alpha_research_pipeline_summary"]["resilience_claim"] == "harder_to_fail_from_self_deception"
    assert result["alpha_research_pipeline_summary"]["fail_safe_claim"] is False
    assert result["alpha_research_pipeline_summary"]["realized_edge_dependency_domains"] == [
        "market_edge",
        "execution_quality",
        "operating_discipline",
    ]
    assert result["alpha_research_pipeline_summary"]["alpha_generator_review_allowed"] is False
    assert result["alpha_research_pipeline_summary"]["signal_density_control_review_allowed"] is False
    assert result["alpha_research_pipeline_summary"]["execution_strategy_automation_review_allowed"] is False
    assert result["alpha_research_pipeline_summary"]["multi_strategy_expansion_review_allowed"] is False
    assert result["alpha_research_pipeline_summary"]["deferred_review_backlog"] == [
        "signal_density_control",
        "multi_strategy_expansion",
    ]
    assert result["alpha_research_pipeline_summary"]["deferred_system_upgrade_backlog"] == [
        "alpha_generator_layer",
        "capital_scale_curve",
        "signal_density_controller",
        "execution_strategy_automation",
        "multi_strategy_activation",
    ]
    assert result["alpha_research_pipeline_summary"]["shadow_experiment_template_count"] == 1
    assert result["alpha_research_pipeline_summary"]["top_reason"] == "risk_budget_below_min"
    assert result["alpha_research_pipeline_summary"]["evidence_available"] is True
    assert result["alpha_research_pipeline_summary"]["evidence_top_reason"] == "risk_budget_below_min"
    assert result["alpha_research_pipeline_summary"]["evidence_focus_aligned_candidates"] == 2
    assert result["alpha_research_pipeline_summary"]["evidence_top_focus"] == "family_information_failure"
    assert result["alpha_research_pipeline_summary"]["evidence_top_bucket"] == "trend_continuation"
    assert result["alpha_research_pipeline_summary"]["evidence_top_family_bottleneck"] == "trend_continuation"
    assert result["alpha_research_pipeline_summary"]["evidence_top_regime_bottleneck"] == "range"
    assert result["alpha_research_pipeline_summary"]["evidence_top_session_bottleneck"] == "dead_session"
    assert result["alpha_research_pipeline_summary"]["false_negative_suspect_count"] == 1
    assert result["alpha_research_pipeline_summary"]["softening_review_available"] is True
    assert result["alpha_research_pipeline_summary"]["softening_top_bucket"] == "trend_continuation"
    assert result["alpha_research_pipeline_summary"]["softening_top_priority"] == "p1"
    assert result["alpha_research_pipeline_summary"]["softening_review_count"] == 1
    assert result["alpha_research_pipeline_summary"]["promotion_watchlist_available"] is True
    assert result["alpha_research_pipeline_summary"]["promotion_watchlist_count"] == 1
    assert result["alpha_research_pipeline_summary"]["promotion_top_bucket"] == "trend_continuation"
    assert result["alpha_research_pipeline_summary"]["promotion_top_not_ready_reason"] is None
    assert result["strategy_v2_lock_validation_available"] is True
    assert result["strategy_v2_pbo_dsr_trial_writer_available"] is True
    assert result["strategy_v2_pbo_dsr_threshold_runner_available"] is True
    assert result["strategy_v2_pbo_dsr_artifact_store_ready"] is True
    assert result["strategy_v2_pbo_dsr_design_ready"] is True
    assert result["strategy_v2_pbo_dsr_metrics_available"] is True
    assert result["strategy_v2_pbo_dsr_threshold_runner_summary"]["selection_rule"] == "true_threshold_sweep_top_in_sample_ev"
    assert result["strategy_v2_pbo_dsr_artifact_store_summary"]["selection_rule_counts"] == {
        "runtime_validation_proxy_top_in_sample_ev": 1,
        "true_threshold_sweep_top_in_sample_ev": 2,
    }
    assert result["strategy_v2_pbo_dsr_artifact_store_summary"]["selection_universe_summary"][
        "full_parameter_sweep_selection_universe_size"
    ] == 2
    assert result["strategy_v2_pbo_dsr_metrics_summary"]["pbo_status"] == "WARN"
    assert result["strategy_v2_pbo_dsr_metrics_summary"]["selected_trial_writer_source"] == "true_threshold_sweep_runner_v1"
    assert result["strategy_v2_pbo_dsr_metrics_summary"]["lineage_audit_status"] == "PASS"
    assert result["strategy_v2_pbo_dsr_metrics_summary"]["selected_trial_from_true_threshold"] is True
    assert result["strategy_v2_pbo_dsr_metrics_summary"]["selection_universe_summary"][
        "full_parameter_sweep_selection_universe_size"
    ] == 2
    assert result["strategy_v2_stress_validation_available"] is True
    assert result["strategy_v2_stress_validation_summary"]["worst_scenario"] == "shock_concentration"
    assert result["strategy_v2_stress_validation_summary"]["worst_scenario_source"] == "replay_output"
    assert result["strategy_v2_stress_validation_summary"]["replay_gate_applied"] is True
    assert result["strategy_v2_stress_validation_summary"]["divergence_gate_applied"] is True
    assert result["strategy_v2_stress_validation_summary"]["worst_divergence_scenario"] == "shock_concentration"
    assert result["strategy_v2_stress_validation_summary"]["replay_output_artifacts_available"] is True
    assert result["strategy_v2_stress_validation_summary"]["replay_output_scenarios_compared"] == 2
    assert result["strategy_v2_stress_validation_summary"]["replay_output_lineage_summary"]["input_trade_rows"] == 13
    assert result["deployment_approval_summary"]["template_status"] == "REVIEW"
    assert result["deployment_approval_summary"]["topline_status"] == "REVIEW"
    assert (
        result["deployment_approval_summary"]["topline_code"]
        == "proxy_selected_trial_against_replay_backed_worst_scenario"
    )
    assert result["deployment_approval_summary"]["topline_message"].startswith("NO_GO:")
    assert (
        result["deployment_approval_summary"]["topline_summary_line"]
        == (
            "validation_lineage=runtime_proxy/runtime_validation_proxy_v1; "
            "worst=shock_concentration/FAIL/replay_output; recommended_action=stay_on_prototype"
        )
    )
    assert result["deployment_approval_summary"]["playbook_go_no_go"] == "NO_GO"
    assert (
        result["deployment_approval_summary"]["playbook_code"]
        == "no_go_proxy_selected_trial_against_replay_backed_worst_scenario"
    )
    assert (
        result["deployment_approval_summary"]["playbook_action"]
        == "hold_live_rollout_and_keep_prototype_path"
    )
    assert result["deployment_approval_summary"]["playbook_message"].startswith("NO-GO:")
    assert result["approval_strip_summary"]["approve_value"] == "validation no_go"
    assert result["approval_strip_summary"]["align_value"] == "playbook_drift"
    assert result["approval_strip_summary"]["act_value"] == "review_runtime_execution_drag_before_expansion"
    assert result["approval_strip_summary"]["act_priority_level"] == "urgent"
    assert result["deployment_approval_summary"]["threshold_lineage_winner_type"] == "runtime_proxy"
    assert result["deployment_approval_summary"]["replay_derived_worst_scenario"] == "shock_concentration"
    assert result["deployment_approval_summary"]["replay_derived_worst_scenario_status"] == "FAIL"
    assert result["deployment_approval_summary"]["approval_warning_locked"] is True
    assert (
        result["deployment_approval_summary"]["approval_warning_code"]
        == "proxy_selected_trial_against_replay_backed_worst_scenario"
    )
    assert "- approve=validation no_go | align=playbook_drift | act=review_runtime_execution_drag_before_expansion | priority=urgent" in body
    assert result["strategy_v2_stress_replay_lineage_available"] is True
    assert result["strategy_v2_stress_replay_lineage_summary"]["runtime_inputs_ready"] is False
    assert result["strategy_v2_stress_replay_assessment_available"] is True
    assert result["strategy_v2_stress_replay_assessment_summary"]["decision"] == "prepare_full_replay"
    assert result["strategy_v2_stress_replay_assessment_summary"]["true_runner_ready"] is False
    assert result["strategy_v2_stress_replay_assessment_summary"]["true_runner_promotion_ready"] is False
    assert result["strategy_v2_stress_replay_assessment_summary"]["true_runner_promotion_status"] == "BLOCKED"
    assert result["strategy_v2_stress_replay_assessment_summary"]["true_runner_promotion_action"] == "stay_on_prototype"
    assert result["strategy_v2_stress_replay_assessment_summary"]["threshold_lineage_audit_status"] == "WARN"
    assert result["strategy_v2_stress_replay_assessment_summary"]["replay_output_lineage_alignment_status"] == "WARN"
    assert result["strategy_v2_stress_replay_assessment_summary"]["replay_output_lineage_compared_scenarios"] == [
        "latency_plus_1_bar",
        "shock_concentration",
    ]
    assert result["strategy_v2_stress_replay_assessment_summary"]["approval_cross_display"]["cross_display_status"] == "REVIEW"
    assert result["strategy_v2_stress_replay_assessment_summary"]["selected_trial_writer_source"] == "runtime_validation_proxy_v1"
    assert result["strategy_v2_stress_replay_runner_contract_available"] is True
    assert result["strategy_v2_stress_replay_runner_contract_summary"]["runtime_job_ready"] is True
    assert result["strategy_v2_stress_replay_runner_contract_summary"]["true_runner_ready"] is False
    assert result["strategy_v2_stress_replay_lineage_writer_available"] is True
    assert result["strategy_v2_stress_replay_lineage_writer_summary"]["artifacts_written"] is True
    assert result["strategy_v2_stress_replay_prototype_worker_available"] is True
    assert result["strategy_v2_stress_replay_prototype_worker_summary"]["executed"] is True
    assert result["strategy_v2_thesis_validation_available"] is True
    body = path.read_text(encoding="utf-8")
    assert "## Feature Importance (Ablation)" in body
    assert "## Feature Calibration" in body
    assert "## Strategy v2 Mode Comparison" in body
    assert "best_ev_family: trend_continuation" in body
    assert "best_ev_session: overlap" in body
    assert "## Scalp Experiment (5m zone / 1m execution)" in body
    assert "preferred_branch: experiment" in body
    assert "recommendation_reason: experiment_has_higher_sized_ev" in body
    assert "## Transition / Shock Lock Comparison" in body
    assert "## PBO / DSR Trial Writer" in body
    assert "## PBO / DSR Threshold Runner" in body
    assert "## PBO / DSR Artifact Store" in body
    assert "selection_universe_summary:" in body
    assert "## PBO / DSR Design Status" in body
    assert "## PBO / DSR Metrics" in body
    assert "lineage_audit_status: PASS" in body
    assert "## Stressed Cost Comparison" in body
    assert "replay_output_artifacts_available: True" in body
    assert "worst_scenario_source: replay_output" in body
    assert "replay_gate_applied: True" in body
    assert "divergence_gate_applied: True" in body
    assert "## Deployment Approval Template" in body
    assert "topline_status: REVIEW" in body
    assert "topline_code: proxy_selected_trial_against_replay_backed_worst_scenario" in body
    assert "topline_message: NO_GO:" in body
    assert (
        "topline_summary_line: validation_lineage=runtime_proxy/runtime_validation_proxy_v1; "
        "worst=shock_concentration/FAIL/replay_output; recommended_action=stay_on_prototype"
    ) in body
    assert "playbook_go_no_go: NO_GO" in body
    assert "playbook_code: no_go_proxy_selected_trial_against_replay_backed_worst_scenario" in body
    assert "playbook_action: hold_live_rollout_and_keep_prototype_path" in body
    assert "playbook_message: NO-GO:" in body
    assert "threshold_lineage_winner_type: runtime_proxy" in body
    assert "replay_derived_worst_scenario: shock_concentration" in body
    assert "replay_derived_worst_scenario_status: FAIL" in body
    assert "approval_warning_locked: True" in body
    assert "approval_warning_code: proxy_selected_trial_against_replay_backed_worst_scenario" in body
    assert "## Stress Replay Lineage" in body
    assert "## Stress Replay Assessment" in body
    assert "true_runner_ready: False" in body
    assert "true_runner_promotion_action: stay_on_prototype" in body
    assert "threshold_lineage_audit_status: WARN" in body
    assert "replay_output_lineage_alignment_status: WARN" in body
    assert "## Stress Replay Runner Contract" in body
    assert "## Stress Replay Lineage Writer" in body
    assert "## Stress Replay Prototype Worker" in body
    assert "## Operator Action Priority" in body
    assert "top_action: review_runtime_execution_drag_before_expansion" in body
    assert "priority_level: urgent" in body
    assert "experiment_context.entry_timing_target: symbol=BTCUSDC" in body
    assert "experiment_context.blocked_candidate_focus: symbol=ETHUSDC" in body
    assert "## Edge Evolution Rule" in body
    assert "recommended_action=reduce_baseline_allocation_review" in body
    assert "latency_plus_1_bar" in body
    assert "## Thesis Dedupe Comparison" in body


def test_deployment_approval_template_playbook_mapping_pass_case() -> None:
    payload = ValidationReportService._deployment_approval_template(
        pbo_dsr_metrics_payload={
            "selected_trial": {
                "trial_run_id": "trial_threshold_01",
                "writer_source": "true_threshold_sweep_runner_v1",
                "selection_rule": "true_threshold_sweep_top_in_sample_ev",
            },
            "lineage_audit": {
                "selected_trial_from_true_threshold": True,
                "selected_trial_from_runtime_proxy": False,
                "audit_status": "PASS",
            },
        },
        stress_payload={
            "deployment_recommendation": {
                "worst_scenario": "shock_concentration",
                "worst_scenario_source": "replay_output",
                "scenario_statuses": {
                    "shock_concentration": {
                        "status": "PASS",
                        "reason": "replay_output_downside_within_limit",
                    }
                },
            }
        },
        stress_replay_payload={
            "deployment_recommendation": {
                "replay_output_lineage_alignment_status": "PASS",
                "replay_output_lineage_alignment_reason": "replay_output_and_selected_trial_source_aligned",
                "true_runner_promotion_action": "promote_true_market_runner",
                "approval_cross_display": {
                    "cross_display_status": "PASS",
                    "cross_display_reason": "true_threshold_winner_cross_displayed_with_replay_worst_scenario",
                    "threshold_lineage_winner_source": "true_threshold_sweep_runner_v1",
                    "threshold_lineage_winner_selection_rule": "true_threshold_sweep_top_in_sample_ev",
                    "threshold_lineage_winner_type": "true_threshold",
                    "threshold_lineage_audit_status": "PASS",
                    "replay_derived_worst_scenario": "shock_concentration",
                    "replay_derived_worst_scenario_source": "replay_output",
                    "replay_derived_worst_scenario_status": "PASS",
                    "replay_derived_worst_scenario_reason": "replay_output_downside_within_limit",
                    "approval_warning_locked": False,
                    "approval_warning_code": "none",
                    "approval_warning_message": "approval_template_cross_display_is_consistent",
                },
            }
        },
    )

    assert payload is not None
    assert payload["topline_status"] == "PASS"
    assert payload["topline_message"].startswith("GO:")
    assert payload["playbook_go_no_go"] == "GO"
    assert payload["playbook_code"] == "go_approval_template_aligned"
    assert payload["playbook_action"] == "proceed_with_configured_rollout"
    assert payload["playbook_message"].startswith("GO:")
    assert payload["replay_output_lineage_alignment_reason"] == "replay_output_and_selected_trial_source_aligned"
    assert payload["threshold_lineage_winner_run_id"] == "trial_threshold_01"
