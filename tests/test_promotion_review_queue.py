from app.services.promotion_review_queue import PromotionReviewQueueService


def test_promotion_review_queue_orders_promote_before_defer_when_primary_family_is_clear() -> None:
    service = PromotionReviewQueueService()

    payload = service.generate(
        promotion_governance={
            "available": True,
            "advisory_only": True,
            "family": "sweep_reversal",
            "state": "promotable",
            "promotion_bias": "consider_promote",
            "target_posture": "production",
            "confidence": "high",
            "reason_codes": [
                "promotion_governance:promotable",
                "lifecycle:production",
                "positive_expansion:expandable",
            ],
            "source_summary": {
                "family_execution_status": "healthy",
                "capital_pressure": "underallocated_positive",
            },
        },
        strategy_lifecycle={
            "available": True,
            "advisory_only": True,
            "family": "sweep_reversal",
            "state": "production",
            "confidence": "high",
        },
        positive_evidence_expansion={
            "available": True,
            "advisory_only": True,
            "family": "sweep_reversal",
            "state": "expandable",
            "expansion_bias": "consider_expand",
            "confidence": "high",
        },
        capital_allocator={
            "available": True,
            "family_focus": "sweep_reversal",
            "family_weights": [
                {"family": "sweep_reversal", "tier": "boost"},
                {
                    "family": "trend_continuation",
                    "tier": "reduce",
                    "capital_pressure": "overallocated_negative",
                },
            ],
        },
        family_execution_degradation_advisory={
            "families": [
                {"family": "sweep_reversal", "status": "healthy", "confidence": "high"},
                {
                    "family": "trend_continuation",
                    "status": "manual_review",
                    "confidence": "high",
                },
            ]
        },
        score_to_outcome_funnel={
            "decomposition": {
                "family": [
                    {
                        "key": "sweep_reversal",
                        "closed": 12,
                        "baseline_cost_profitable_rate_from_closed": 0.75,
                    },
                    {
                        "key": "trend_continuation",
                        "closed": 8,
                        "baseline_cost_profitable_rate_from_closed": 0.2,
                    },
                ]
            }
        },
    )

    assert payload["available"] is True
    assert payload["queue_state"] == "promotion_ready_queue"
    assert payload["headline_family"] == "sweep_reversal"
    assert payload["top_review_action"] == "promote_review"
    assert payload["review_queue"][0]["family"] == "sweep_reversal"
    assert payload["review_queue"][0]["review_action"] == "promote_review"
    assert payload["review_queue"][1]["family"] == "trend_continuation"
    assert payload["review_queue"][1]["review_action"] == "defer_review"
    assert payload["source_summary"]["promotion_ready_count"] == 1
    assert payload["source_summary"]["defer_count"] == 1
    assert payload["source_summary"]["hold_count"] == 0
    assert payload["source_summary"]["top_allocator_tier"] == "boost"
