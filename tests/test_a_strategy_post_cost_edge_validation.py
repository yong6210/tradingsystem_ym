from app.services.a_strategy_post_cost_edge_validation import AStrategyPostCostEdgeValidationService


def test_a_strategy_post_cost_edge_validation_marks_validated_edge_when_anchor_is_healthy() -> None:
    service = AStrategyPostCostEdgeValidationService()

    payload = service.generate(
        score_to_outcome_funnel={
            "decomposition": {
                "family": [
                    {
                        "key": "sweep_reversal",
                        "closed": 9,
                        "baseline_cost_profitable_rate_from_closed": 0.6667,
                    }
                ],
                "regime": [
                    {
                        "key": "trend",
                        "closed": 5,
                        "baseline_cost_profitable_rate_from_closed": 0.55,
                    }
                ],
                "session": [
                    {
                        "key": "preferred_live_window",
                        "closed": 5,
                        "baseline_cost_profitable_rate_from_closed": 0.6,
                    }
                ],
            },
            "historical_execution_outcomes": {
                "baseline_cost_profitable_rate_from_closed": 0.6111,
            },
        },
        family_execution_degradation_advisory={
            "families": [
                {
                    "family": "sweep_reversal",
                    "status": "healthy",
                    "confidence": "high",
                }
            ]
        },
        mode_advisory={
            "family": [
                {
                    "bucket": "sweep_reversal",
                    "advisory_state": "keep_current_mode",
                    "confidence": "high",
                    "sample_note": "repeat evidence is present",
                }
            ]
        },
        outcome_bucket_granularity={
            "available": True,
            "top_condition_axis": "",
            "top_condition_bucket": None,
        },
        alpha_research_pipeline={
            "recommended_action_summary": {
                "focus": "family_information_failure",
                "bucket": "trend_continuation",
                "confidence": "medium",
            }
        },
    )

    assert payload is not None
    assert payload["available"] is True
    assert payload["family"] == "sweep_reversal"
    assert payload["edge_state"] == "validated_edge"
    assert payload["validation_bias"] == "keep_anchor"
    assert payload["sample_state"] == "mature"
    assert payload["confidence"] == "high"
    assert "a_edge:validated_edge" in payload["reason_codes"]


def test_a_strategy_post_cost_edge_validation_keeps_manual_review_as_insufficient_edge() -> None:
    service = AStrategyPostCostEdgeValidationService()

    payload = service.generate(
        score_to_outcome_funnel={
            "decomposition": {
                "family": [
                    {
                        "key": "sweep_reversal",
                        "closed": 10,
                        "baseline_cost_profitable_rate_from_closed": 0.6,
                    }
                ],
                "regime": [],
                "session": [],
            },
            "historical_execution_outcomes": {
                "baseline_cost_profitable_rate_from_closed": 0.58,
            },
        },
        family_execution_degradation_advisory={
            "families": [
                {
                    "family": "sweep_reversal",
                    "status": "manual_review",
                    "confidence": "high",
                }
            ]
        },
        mode_advisory={
            "family": [
                {
                    "bucket": "sweep_reversal",
                    "advisory_state": "watch",
                    "confidence": "high",
                    "sample_note": "repeat evidence is present",
                }
            ]
        },
        outcome_bucket_granularity={
            "available": True,
            "top_condition_axis": "cost_condition",
            "top_condition_bucket": {"key": "high_cost"},
            "confidence": "medium",
        },
        alpha_research_pipeline={
            "recommended_action_summary": {
                "focus": "post_cost_ev_deterioration",
                "bucket": "global",
                "confidence": "high",
            }
        },
    )

    assert payload is not None
    assert payload["edge_state"] == "insufficient_edge"
    assert payload["validation_bias"] == "reduce_anchor_confidence"
    assert payload["sample_state"] == "mature"
    assert payload["source_summary"]["family_execution_status"] == "manual_review"
    assert payload["source_summary"]["sizing_penalty_tier"] == "hard_clamp"
    assert "family_execution:manual_review" in payload["reason_codes"]
