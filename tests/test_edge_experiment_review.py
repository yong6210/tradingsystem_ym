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
    assert summary["regime_dependency_state"] == "regime_dependent"
    assert summary["strongest_regime"] == "range"
    assert summary["weakest_regime"] == "trend"
    assert summary["strongest_regime_true_edge_ratio"] == 0.9
    assert summary["weakest_regime_true_edge_ratio"] == 0.6
