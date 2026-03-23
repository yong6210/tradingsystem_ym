from app.services.promotion_clearance_tracker import PromotionClearanceTrackerService


def test_promotion_clearance_tracker_marks_family_blocked_when_execution_and_policy_guardrails_remain() -> None:
    service = PromotionClearanceTrackerService()

    payload = service.generate(
        promotion_governance={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "state": "defer",
            "confidence": "high",
            "reason_codes": [
                "promotion_governance:defer",
                "family_execution:manual_review",
                "rollout_recommendation:reduce",
            ],
            "source_summary": {
                "family_execution_status": "manual_review",
                "rollout_recommendation": "reduce",
                "rollout_maturity": "mature",
                "lifecycle_state": "degraded",
            },
        },
        promotion_review_queue={
            "available": True,
            "review_queue": [
                {
                    "family": "trend_continuation",
                    "review_action": "defer_review",
                    "promotion_state": "defer",
                    "confidence": "high",
                }
            ],
        },
        promotion_remediation_queue={
            "available": True,
            "headline_family": "trend_continuation",
            "remediation_queue": [
                {
                    "family": "trend_continuation",
                    "remediation_action": "execution_remediation",
                    "reason_codes": [
                        "family_execution:manual_review",
                        "rollout_recommendation:reduce",
                    ],
                }
            ],
        },
        strategy_lifecycle={
            "available": True,
            "family": "trend_continuation",
            "state": "degraded",
        },
        family_execution_degradation_advisory={
            "families": [
                {"family": "trend_continuation", "status": "manual_review", "confidence": "high"}
            ]
        },
        rollout_recommendation={
            "available": True,
            "family": "trend_continuation",
            "recommendation": "reduce",
            "maturity": "mature",
        },
        outcome_bucket_granularity={
            "available": True,
            "family_focus": {"key": "sweep_reversal"},
            "top_condition_axis": "cost_condition",
            "confidence": "high",
        },
        positive_evidence_expansion={
            "available": True,
            "family": "trend_continuation",
            "state": "not_ready",
        },
        capital_allocator={
            "available": True,
            "family_focus": "trend_continuation",
            "family_weights": [
                {"family": "trend_continuation", "tier": "reduce", "capital_pressure": "overallocated_negative"}
            ],
        },
    )

    assert payload["available"] is True
    assert payload["family"] == "trend_continuation"
    assert payload["clearance_state"] == "blocked"
    assert payload["clearance_bias"] == "continue_remediation"
    assert payload["remaining_guardrail_domains"] == ["execution", "policy"]
    assert payload["cleared_guardrail_domains"] == ["condition"]
    assert payload["source_summary"]["remediation_action"] == "execution_remediation"
    assert payload["source_summary"]["family_execution_status"] == "manual_review"
