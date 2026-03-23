from app.services.b_continuation_edge_validation import BContinuationEdgeValidationService


def test_b_continuation_edge_validation_marks_validated_edge_when_b_still_diversifies() -> None:
    service = BContinuationEdgeValidationService()

    payload = service.generate(
        score_to_outcome_funnel={
            "decomposition": {
                "family": [
                    {
                        "key": "trend_continuation",
                        "closed": 9,
                        "baseline_cost_profitable_rate_from_closed": 0.6111,
                    },
                    {
                        "key": "sweep_reversal",
                        "closed": 9,
                        "baseline_cost_profitable_rate_from_closed": 0.5556,
                    },
                ],
                "regime": [
                    {
                        "key": "trend",
                        "closed": 5,
                        "baseline_cost_profitable_rate_from_closed": 0.6,
                    }
                ],
                "session": [
                    {
                        "key": "preferred_live_window",
                        "closed": 5,
                        "baseline_cost_profitable_rate_from_closed": 0.58,
                    }
                ],
            }
        },
        outcome_bucket_granularity={
            "available": True,
            "family_focus": {"key": "trend_continuation"},
            "top_condition_axis": "",
            "top_condition_bucket": None,
        },
        family_execution_degradation_advisory={
            "families": [
                {
                    "family": "trend_continuation",
                    "status": "healthy",
                    "confidence": "high",
                }
            ]
        },
        alpha_research_pipeline={
            "recommended_action_summary": {
                "focus": "family_information_failure",
                "bucket": "sweep_reversal",
                "confidence": "medium",
            }
        },
        b_continuation_activation={
            "available": True,
            "family": "trend_continuation",
            "activation_state": "blocked",
            "activation_bias": "clear_guardrails",
            "target_mode": "A_PLUS_B",
        },
        multi_strategy_ab_summary={
            "b_cluster": {
                "cluster": "b_continuation",
                "strategy_cluster_status": "available_but_guarded",
            }
        },
        strategy_cluster_balance={
            "available": True,
            "balance_state": "balanced_mix",
            "balance_bias": "hold_balanced_mix",
        },
        capital_allocator={
            "family_focus": "trend_continuation",
            "capital_pressure": "underallocated_positive",
            "family_weights": [
                {
                    "family": "trend_continuation",
                    "tier": "boost",
                }
            ],
        },
    )

    assert payload is not None
    assert payload["available"] is True
    assert payload["raw_family"] == "trend_continuation"
    assert payload["strategy_cluster"] == "b_continuation"
    assert payload["edge_state"] == "validated_edge"
    assert payload["validation_bias"] == "support_guarded_activation"
    assert payload["sample_state"] == "mature_sample"
    assert payload["diversification_state"] == "diversifying"
    assert payload["a_b_correlation_proxy"] == "low_overlap_proxy"
    assert payload["drawdown_contribution_state"] == "drawdown_buffering"
    assert "activation_state:blocked" in payload["reason_codes"]


def test_b_continuation_edge_validation_keeps_high_overlap_drawdown_as_insufficient_edge() -> None:
    service = BContinuationEdgeValidationService()

    payload = service.generate(
        score_to_outcome_funnel={
            "decomposition": {
                "family": [
                    {
                        "key": "trend_continuation",
                        "closed": 10,
                        "baseline_cost_profitable_rate_from_closed": 0.62,
                    },
                    {
                        "key": "sweep_reversal",
                        "closed": 10,
                        "baseline_cost_profitable_rate_from_closed": 0.59,
                    },
                ],
                "regime": [],
                "session": [],
            }
        },
        outcome_bucket_granularity={
            "available": True,
            "family_focus": {"key": "trend_continuation"},
            "top_condition_axis": "",
            "top_condition_bucket": None,
        },
        family_execution_degradation_advisory={
            "families": [
                {
                    "family": "trend_continuation",
                    "status": "healthy",
                    "confidence": "high",
                }
            ]
        },
        alpha_research_pipeline={
            "recommended_action_summary": {
                "focus": "family_information_failure",
                "bucket": "range_rotation",
                "confidence": "low",
            }
        },
        b_continuation_activation={
            "available": True,
            "family": "trend_continuation",
            "activation_state": "activation_ready",
            "activation_bias": "consider_first_wave_activation",
            "target_mode": "A_PLUS_B",
        },
        multi_strategy_ab_summary={
            "b_cluster": {
                "cluster": "b_continuation",
                "strategy_cluster_status": "probation_ready",
            }
        },
        strategy_cluster_balance={
            "available": True,
            "balance_state": "a_concentrated",
            "balance_bias": "preserve_a_anchor",
        },
        capital_allocator={
            "family_focus": "trend_continuation",
            "capital_pressure": "overallocated_negative",
            "family_weights": [
                {
                    "family": "trend_continuation",
                    "tier": "reduce",
                }
            ],
        },
    )

    assert payload is not None
    assert payload["edge_state"] == "insufficient_edge"
    assert payload["validation_bias"] == "reduce_b_confidence"
    assert payload["sample_state"] == "mature_sample"
    assert payload["diversification_state"] == "drawdown_additive"
    assert payload["a_b_correlation_proxy"] == "high_overlap_proxy"
    assert payload["drawdown_contribution_state"] == "drawdown_additive"
    assert payload["source_summary"]["capital_pressure"] == "overallocated_negative"
    assert "correlation_proxy:high_overlap_proxy" in payload["reason_codes"]
