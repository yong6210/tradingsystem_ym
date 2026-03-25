from __future__ import annotations

from app.services.edge_experiment_review import (
    build_edge_experiment_review,
    summarize_edge_experiment_review,
)


def test_edge_experiment_review_summarizes_true_edge_and_split_preferences() -> None:
    payload = {
        "historical_execution_outcomes": {
            "submitted": 9,
            "filled": 7,
            "closed": 6,
        },
        "money_funnel": {
            "historical_expected_r": {"closed": 0.96},
            "historical_realized_r": {"post_cost_closed": 0.72},
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
            "summary": "expected_closed_r=0.9600, post_cost_closed_r=0.7200, submitted_to_filled_gap_r=0.3300",
        },
        "decomposition": {
            "entry_timing_variant": [
                {
                    "key": "early_limit",
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
            "execution_style": [
                {
                    "key": "passive_limit",
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
            "regime": [
                {
                    "key": "range",
                    "submitted": 5,
                    "filled": 4,
                    "closed": 3,
                    "submitted_expected_r": 0.70,
                    "filled_expected_r": 0.50,
                    "closed_expected_r": 0.40,
                    "baseline_adjusted_r": 0.36,
                    "fill_rate_from_submitted": 0.8,
                },
                {
                    "key": "trend",
                    "submitted": 4,
                    "filled": 3,
                    "closed": 3,
                    "submitted_expected_r": 0.60,
                    "filled_expected_r": 0.36,
                    "closed_expected_r": 0.50,
                    "baseline_adjusted_r": 0.30,
                    "fill_rate_from_submitted": 0.75,
                },
            ],
        },
    }

    review = build_edge_experiment_review(score_to_outcome_funnel=payload)
    assert review is not None
    summary = summarize_edge_experiment_review(review)

    assert summary is not None
    assert summary["edge_state"] == "watch_edge"
    assert summary["true_edge_ratio"] == 0.75
    assert summary["recent_true_edge_ratio"] == 0.7778
    assert summary["prior_true_edge_ratio"] == 0.7143
    assert summary["edge_decay_rate"] == 0.0635
    assert summary["entry_timing_comparison_ready"] is True
    assert summary["entry_timing_preferred_variant"] == "early_limit"
    assert summary["entry_timing_recommendation_reason"] == "higher_post_cost_true_edge_ratio"
    assert summary["execution_style_comparison_ready"] is True
    assert summary["execution_style_preferred_variant"] == "passive_limit"
    assert summary["execution_style_recommendation_reason"] == "higher_post_cost_true_edge_ratio"
    assert summary["sample_maturity_state"] == "review_ready"
    assert summary["next_sample_target_closed_trades"] == 8
    assert summary["remaining_closed_trades_to_next_target"] == 2
    assert summary["edge_proof_goal_closed_trades"] == 100
    assert summary["edge_proof_goal_ready"] is False
    assert summary["remaining_closed_trades_to_edge_proof_goal"] == 94
    assert summary["regime_dependency_state"] == "regime_dependent"
    assert summary["strongest_regime"] == "range"
    assert summary["weakest_regime"] == "trend"
    assert summary["strongest_regime_true_edge_ratio"] == 0.9
    assert summary["weakest_regime_true_edge_ratio"] == 0.6
    assert summary["edge_proof_posture"]["state"] == "sample_building"
    assert summary["edge_proof_posture"]["claim_state"] == "do_not_claim_edge_yet"
    assert summary["operating_discipline"]["discipline_state"] == "research_only_until_edge_proof_goal"
    assert summary["operating_discipline"]["framework_quality_state"] == "framework_ready"
    assert summary["operating_discipline"]["system_mode"] == "operate_and_experiment"
    assert summary["operating_discipline"]["primary_goal"] == "find_first_verified_edge"
    assert summary["operating_discipline"]["evaluation_focus"] == "after_cost_edge_only"
    assert summary["operating_discipline"]["minimum_closed_trades_for_edge_evaluation"] == 100
    assert summary["operating_discipline"]["edge_status"] == "unknown_until_after_cost_proof"
    assert summary["operating_discipline"]["profit_claim_allowed"] is False
    assert summary["operating_discipline"]["structure_change_review_allowed"] is False
    assert summary["operating_discipline"]["early_loss_rewrite_embargo_closed_trades"] == 50
    assert summary["operating_discipline"]["early_loss_rewrite_embargo_active"] is True
    assert summary["operating_discipline"]["loss_driven_rewrite_allowed"] is False
    assert summary["operating_discipline"]["regime_stability_required_for_expansion"] is True
    assert summary["operating_discipline"]["rollout_expansion_allowed"] is False
    assert summary["operating_discipline"]["improvement_priority"] == "prove_single_edge_before_density_or_strategy_expansion"
    assert summary["operating_discipline"]["signal_density_control_review_allowed"] is False
    assert summary["operating_discipline"]["multi_strategy_expansion_review_allowed"] is False
    assert summary["operating_discipline"]["deferred_review_backlog"] == [
        "signal_density_control",
        "multi_strategy_expansion",
    ]
    assert summary["experiment_sequence"]["state"] == "sample_building_before_exit_optimization"
    assert summary["experiment_sequence"]["entry_timing_locked"] is True
    assert summary["experiment_sequence"]["execution_style_locked"] is True
    assert summary["experiment_sequence"]["exit_optimization_allowed"] is False
    assert summary["experiment_sequence"]["current_priority_experiment"] == "sample_building"
    assert summary["experiment_sequence"]["current_priority_action"] == "accumulate_closed_trades"
    assert summary["daily_edge_kpis"]["true_edge_ratio"] == 0.75
    assert summary["daily_edge_kpis"]["regime_dependency_state"] == "regime_dependent"


def test_edge_experiment_review_allows_cautious_expansion_only_after_regime_stability() -> None:
    payload = {
        "historical_execution_outcomes": {
            "submitted": 140,
            "filled": 124,
            "closed": 120,
        },
        "money_funnel": {
            "historical_expected_r": {"closed": 20.0},
            "historical_realized_r": {"post_cost_closed": 23.0},
            "historical_windows": {
                "recent": {
                    "closed": 60,
                    "closed_expected_r": 10.0,
                    "post_cost_closed_realized_r": 11.8,
                    "true_edge_ratio": 1.18,
                },
                "prior": {
                    "closed": 60,
                    "closed_expected_r": 10.0,
                    "post_cost_closed_realized_r": 11.2,
                    "true_edge_ratio": 1.12,
                },
            },
            "summary": "expected_closed_r=20.0000, post_cost_closed_r=23.0000, submitted_to_filled_gap_r=1.2000",
        },
        "decomposition": {
            "entry_timing_variant": [
                {
                    "key": "early_limit",
                    "submitted": 70,
                    "filled": 62,
                    "closed": 60,
                    "submitted_expected_r": 11.2,
                    "filled_expected_r": 10.2,
                    "closed_expected_r": 9.8,
                    "baseline_adjusted_r": 11.8,
                    "fill_rate_from_submitted": 0.8857,
                },
                {
                    "key": "reaction_confirmed",
                    "submitted": 70,
                    "filled": 62,
                    "closed": 60,
                    "submitted_expected_r": 11.4,
                    "filled_expected_r": 10.0,
                    "closed_expected_r": 10.2,
                    "baseline_adjusted_r": 11.2,
                    "fill_rate_from_submitted": 0.8857,
                },
            ],
            "execution_style": [
                {
                    "key": "passive_limit",
                    "submitted": 70,
                    "filled": 62,
                    "closed": 60,
                    "submitted_expected_r": 11.0,
                    "filled_expected_r": 10.1,
                    "closed_expected_r": 9.8,
                    "baseline_adjusted_r": 11.6,
                    "fill_rate_from_submitted": 0.8857,
                },
                {
                    "key": "market",
                    "submitted": 70,
                    "filled": 62,
                    "closed": 60,
                    "submitted_expected_r": 11.6,
                    "filled_expected_r": 10.1,
                    "closed_expected_r": 10.2,
                    "baseline_adjusted_r": 11.4,
                    "fill_rate_from_submitted": 0.8857,
                },
            ],
            "regime": [
                {
                    "key": "range",
                    "submitted": 70,
                    "filled": 62,
                    "closed": 60,
                    "submitted_expected_r": 10.0,
                    "filled_expected_r": 9.0,
                    "closed_expected_r": 8.0,
                    "baseline_adjusted_r": 9.2,
                    "fill_rate_from_submitted": 0.8857,
                },
                {
                    "key": "trend",
                    "submitted": 70,
                    "filled": 62,
                    "closed": 60,
                    "submitted_expected_r": 10.4,
                    "filled_expected_r": 9.1,
                    "closed_expected_r": 8.4,
                    "baseline_adjusted_r": 9.4,
                    "fill_rate_from_submitted": 0.8857,
                },
            ],
        },
    }

    review = build_edge_experiment_review(score_to_outcome_funnel=payload)
    assert review is not None
    summary = summarize_edge_experiment_review(review)

    assert summary is not None
    assert summary["edge_proof_posture"]["state"] == "edge_claim_ready"
    assert summary["regime_dependency_state"] == "stable_across_regimes"
    assert summary["operating_discipline"]["profit_claim_allowed"] is True
    assert summary["operating_discipline"]["structure_change_review_allowed"] is True
    assert summary["operating_discipline"]["early_loss_rewrite_embargo_active"] is False
    assert summary["operating_discipline"]["loss_driven_rewrite_allowed"] is True
    assert summary["operating_discipline"]["rollout_expansion_allowed"] is True
    assert summary["operating_discipline"]["signal_density_control_review_allowed"] is True
    assert summary["operating_discipline"]["multi_strategy_expansion_review_allowed"] is True
    assert summary["operating_discipline"]["deferred_review_backlog"] == []
