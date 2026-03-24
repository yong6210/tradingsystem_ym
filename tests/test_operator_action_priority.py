from __future__ import annotations

from app.services.operator_action_priority import OperatorActionPriorityService


def test_operator_action_priority_promotes_edge_experiment_when_no_stronger_signal() -> None:
    service = OperatorActionPriorityService()

    payload = service.generate(
        dashboard={
            "signal_funnel": {
                "edge_experiment_review": {
                    "available": True,
                    "edge_state": "watch_edge",
                    "true_edge_ratio": 0.78,
                    "edge_decay_rate": -0.06,
                    "entry_timing_comparison_ready": True,
                    "entry_timing_preferred_variant": "early_limit",
                    "entry_timing_recommendation_reason": "higher_post_cost_true_edge_ratio",
                    "execution_style_comparison_ready": True,
                    "execution_style_preferred_variant": "passive_limit",
                    "execution_style_recommendation_reason": "better_fill_capture_ratio",
                },
                "execution_degradation_advisory": {
                    "available": True,
                    "status": "healthy",
                },
                "family_execution_degradation_advisory": {"available": False},
                "mode_advisory": {"available": False},
                "alpha_research_recommended_action": {"available": False},
            },
            "portfolio_summary": {
                "accepted_candidates": [
                    {
                        "symbol": "BTCUSDC",
                        "strategy_family": "sweep_reversal",
                        "edge_experiment_focus": {
                            "edge_state": "watch_edge",
                            "entry_timing_preferred_variant": "early_limit",
                            "execution_style_preferred_variant": "passive_limit",
                        },
                    }
                ],
                "blocked_candidates": [
                    {
                        "symbol": "ETHUSDC",
                        "strategy_family": "trend_continuation",
                        "block_reason": "mode_shadow_only",
                        "edge_experiment_focus": {
                            "edge_state": "fragile_edge",
                            "entry_timing_preferred_variant": "reaction_confirmed",
                            "execution_style_preferred_variant": "market",
                        },
                    }
                ],
            },
            "new_entries_allowed": True,
        },
        checklist={},
        validation={},
    )

    assert payload["top_action"] == "run_entry_timing_split_review"
    assert payload["priority_level"] == "watch"
    assert payload["priority_source"] == "edge_experiment"
    assert payload["action_family"] == "edge_review"
    assert payload["experiment_context"]["edge_state"] == "watch_edge"
    assert payload["experiment_context"]["entry_timing_preferred_variant"] == "early_limit"
    assert payload["experiment_context"]["execution_style_preferred_variant"] == "passive_limit"
    assert payload["experiment_context"]["accepted_candidate_focus"]["symbol"] == "BTCUSDC"
    assert payload["experiment_context"]["blocked_candidate_focus"]["symbol"] == "ETHUSDC"
    assert payload["experiment_context"]["entry_timing_target"]["symbol"] == "BTCUSDC"
    assert payload["experiment_context"]["entry_timing_target"]["followup_command"].endswith(
        "--symbol BTCUSDC --universe usdc_perp_top30 --days 7 --action run_entry_timing_split_review"
    )
    assert payload["experiment_context"]["execution_style_target"]["symbol"] == "BTCUSDC"
    assert payload["experiment_context"]["execution_style_target"]["focus_source"] == "accepted_candidate_focus"
    assert payload["experiment_context"]["execution_style_target"]["followup_command"].endswith(
        "--symbol BTCUSDC --universe usdc_perp_top30 --days 7 --action run_execution_style_split_review"
    )
    assert payload["top_action_followup_command"].endswith(
        "--symbol BTCUSDC --universe usdc_perp_top30 --days 7 --action run_entry_timing_split_review"
    )
    assert payload["next_actions"][0]["action"] == "run_execution_style_split_review"
    assert payload["next_actions"][0]["target_symbol"] == "BTCUSDC"
    assert payload["next_actions"][0]["target_status"] == "ACTIONABLE_ENTRY"
    assert payload["next_actions"][0]["target_family"] == "sweep_reversal"
    assert payload["next_actions"][0]["followup_command"].endswith(
        "--symbol BTCUSDC --universe usdc_perp_top30 --days 7 --action run_execution_style_split_review"
    )
    assert "edge:watch_edge" in payload["supporting_signals"]
    assert "entry_timing:early_limit" in payload["supporting_signals"]
    assert "execution_style:passive_limit" in payload["supporting_signals"]
    assert "entry_target:BTCUSDC:ACTIONABLE_ENTRY" in payload["supporting_signals"]
    assert "accepted_focus:BTCUSDC:watch_edge" in payload["supporting_signals"]


def test_operator_action_priority_escalates_edge_evolution_reduce_review() -> None:
    service = OperatorActionPriorityService()

    payload = service.generate(
        dashboard={
            "signal_funnel": {
                "edge_experiment_review": {
                    "available": True,
                    "edge_state": "fragile_edge",
                    "true_edge_ratio": 0.74,
                    "edge_decay_rate": -0.18,
                    "entry_timing_comparison_ready": True,
                    "entry_timing_preferred_variant": "early_limit",
                    "entry_timing_recommendation_reason": "higher_post_cost_true_edge_ratio",
                },
                "edge_evolution_rule": {
                    "available": True,
                    "evolution_state": "reduce_candidate",
                    "recommended_action": "reduce_baseline_allocation_review",
                    "allocation_bias": "reduce_baseline",
                    "confidence": "medium",
                    "summary": "Baseline edge is weak enough that allocation should be reduced until the preferred branch proves durable post-cost.",
                    "promotion_candidate": {
                        "axis": "entry_timing",
                        "preferred_variant": "early_limit",
                        "recommendation_reason": "higher_post_cost_true_edge_ratio",
                    },
                },
                "execution_degradation_advisory": {
                    "available": True,
                    "status": "healthy",
                },
                "family_execution_degradation_advisory": {"available": False},
                "mode_advisory": {"available": False},
                "alpha_research_recommended_action": {"available": False},
            },
            "portfolio_summary": {
                "accepted_candidates": [
                    {
                        "symbol": "BTCUSDC",
                        "strategy_family": "sweep_reversal",
                        "edge_experiment_focus": {
                            "edge_state": "fragile_edge",
                            "entry_timing_preferred_variant": "early_limit",
                            "execution_style_preferred_variant": "passive_limit",
                        },
                    }
                ],
            },
            "new_entries_allowed": True,
        },
        checklist={},
        validation={},
    )

    assert payload["top_action"] == "reduce_baseline_allocation_review"
    assert payload["priority_source"] == "edge_evolution"
    assert payload["action_family"] == "allocation_review"
    assert payload["top_action_followup_command"] == ""
    assert "edge_evolution:reduce_candidate" in payload["supporting_signals"]
    assert "promotion_candidate:entry_timing:early_limit" in payload["supporting_signals"]
