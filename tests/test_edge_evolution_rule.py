from __future__ import annotations

from app.services.edge_evolution_rule import build_edge_evolution_rule, summarize_edge_evolution_rule


def test_edge_evolution_rule_recommends_reduction_when_edge_fragility_aligns_with_live_risk() -> None:
    payload = summarize_edge_evolution_rule(
        build_edge_evolution_rule(
            edge_experiment_review={
                "available": True,
                "edge_state": "fragile_edge",
                "true_edge_ratio": 0.68,
                "edge_decay_rate": -0.22,
                "closed_trade_count": 8,
                "entry_timing_comparison_ready": True,
                "entry_timing_preferred_variant": "early_limit",
                "entry_timing_recommendation_reason": "higher_post_cost_true_edge_ratio",
                "execution_style_comparison_ready": True,
                "execution_style_preferred_variant": "passive_limit",
                "execution_style_recommendation_reason": "better_fill_capture_ratio",
            },
            rollout_recommendation={
                "available": True,
                "recommendation": "reduce",
            },
            strategy_lifecycle={
                "available": True,
                "state": "degraded",
            },
            kill_condition_automation={
                "available": True,
                "kill_condition_state": "close_only_review",
            },
        )
    )

    assert payload is not None
    assert payload["available"] is True
    assert payload["evolution_state"] == "edge_kill_review"
    assert payload["recommended_action"] == "review_edge_kill_condition"
    assert payload["allocation_bias"] == "reduce_or_stop"
    assert payload["kill_review_triggered"] is True
    assert payload["promotion_candidate_axis"] == "entry_timing"
    assert payload["promotion_candidate_variant"] == "early_limit"


def test_edge_evolution_rule_escalates_when_reduce_review_is_confirmed_by_new_closes() -> None:
    payload = summarize_edge_evolution_rule(
        build_edge_evolution_rule(
            edge_experiment_review={
                "available": True,
                "edge_state": "fragile_edge",
                "true_edge_ratio": 0.66,
                "recent_true_edge_ratio": 0.62,
                "prior_true_edge_ratio": 0.79,
                "edge_decay_rate": -0.23,
                "closed_trade_count": 9,
                "entry_timing_comparison_ready": True,
                "entry_timing_preferred_variant": "early_limit",
                "entry_timing_recommendation_reason": "higher_post_cost_true_edge_ratio",
            },
            rollout_recommendation={"available": True, "recommendation": "reduce"},
            strategy_lifecycle={"available": True, "state": "degraded"},
            kill_condition_automation={"available": True, "kill_condition_state": "observe_only"},
            review_followup_ledger={
                "available": True,
                "last_action": "reduce_baseline_allocation_review",
                "last_status": "READY",
                "last_closed_trade_count": 6,
                "last_true_edge_ratio": 0.77,
                "last_recent_true_edge_ratio": 0.74,
                "last_target_contract": {
                    "axis": "entry_timing",
                    "preferred_variant": "early_limit",
                    "symbol": "BTCUSDC",
                    "strategy_family": "sweep_reversal",
                },
            },
        )
    )

    assert payload is not None
    assert payload["evolution_state"] == "edge_kill_review"
    assert payload["recommended_action"] == "review_edge_kill_condition"
    assert payload["recommendation_strength"] == "escalated"
    assert payload["closed_loop_confirmation_state"] == "kill_confirmed"
    assert payload["closed_loop_feedback"]["new_closed_trade_count"] == 3


def test_edge_evolution_rule_confirms_promotion_after_split_review_survives_new_closes() -> None:
    payload = summarize_edge_evolution_rule(
        build_edge_evolution_rule(
            edge_experiment_review={
                "available": True,
                "edge_state": "healthy_edge",
                "true_edge_ratio": 1.08,
                "recent_true_edge_ratio": 1.11,
                "prior_true_edge_ratio": 0.99,
                "edge_decay_rate": 0.03,
                "closed_trade_count": 7,
                "entry_timing_comparison_ready": True,
                "entry_timing_preferred_variant": "early_limit",
                "entry_timing_recommendation_reason": "higher_post_cost_true_edge_ratio",
                "entry_timing_experiment": {
                    "comparison_ready": True,
                    "preferred_variant": "early_limit",
                    "recommendation_reason": "higher_post_cost_true_edge_ratio",
                    "true_edge_ratio_gap": 0.14,
                    "capture_ratio_gap": 0.11,
                },
            },
            rollout_recommendation={"available": True, "recommendation": "hold"},
            strategy_lifecycle={"available": True, "state": "production"},
            kill_condition_automation={"available": True, "kill_condition_state": "observe_only"},
            review_followup_ledger={
                "available": True,
                "last_action": "run_entry_timing_split_review",
                "last_status": "READY",
                "last_closed_trade_count": 5,
                "last_true_edge_ratio": 1.0,
                "last_recent_true_edge_ratio": 1.01,
                "last_target_contract": {
                    "axis": "entry_timing",
                    "preferred_variant": "early_limit",
                    "symbol": "BTCUSDC",
                    "strategy_family": "sweep_reversal",
                },
            },
        )
    )

    assert payload is not None
    assert payload["evolution_state"] == "promote_candidate"
    assert payload["recommended_action"] == "promote_entry_timing_branch_review"
    assert payload["recommendation_strength"] == "confirmed"
    assert payload["closed_loop_confirmation_state"] == "promote_confirmed"
    assert payload["confidence"] == "high"


def test_edge_evolution_rule_blocks_promotion_when_edge_is_still_regime_dependent() -> None:
    payload = summarize_edge_evolution_rule(
        build_edge_evolution_rule(
            edge_experiment_review={
                "available": True,
                "edge_state": "healthy_edge",
                "true_edge_ratio": 1.05,
                "recent_true_edge_ratio": 1.08,
                "prior_true_edge_ratio": 0.97,
                "edge_decay_rate": 0.02,
                "closed_trade_count": 7,
                "entry_timing_comparison_ready": True,
                "entry_timing_preferred_variant": "early_limit",
                "entry_timing_recommendation_reason": "higher_post_cost_true_edge_ratio",
                "execution_style_comparison_ready": True,
                "execution_style_preferred_variant": "passive_limit",
                "execution_style_recommendation_reason": "higher_post_cost_true_edge_ratio",
                "regime_dependency_state": "regime_dependent",
                "strongest_regime": "range",
                "weakest_regime": "trend",
                "weakest_regime_true_edge_ratio": 0.82,
            },
            rollout_recommendation={"available": True, "recommendation": "hold"},
            strategy_lifecycle={"available": True, "state": "production"},
            kill_condition_automation={"available": True, "kill_condition_state": "observe_only"},
        )
    )

    assert payload is not None
    assert payload["evolution_state"] == "research_only"
    assert payload["recommended_action"] == "keep_research_only_until_sample_matures"
    assert payload["allocation_bias"] == "keep_research_only"
    assert payload["regime_guard_state"] == "promotion_blocked_by_regime_dependency"
    assert payload["strongest_regime"] == "range"
    assert payload["weakest_regime"] == "trend"
