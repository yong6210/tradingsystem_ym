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
