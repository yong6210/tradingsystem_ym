from app.services.promotion_remediation_queue import PromotionRemediationQueueService


def test_promotion_remediation_queue_prioritizes_execution_before_condition_when_manual_review_blocks_family() -> None:
    service = PromotionRemediationQueueService()

    payload = service.generate(
        promotion_governance={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "state": "defer",
            "promotion_bias": "defer",
            "target_posture": "keep_current",
            "confidence": "high",
            "reason_codes": [
                "promotion_governance:defer",
                "family_execution:manual_review",
                "lifecycle:degraded",
                "rollout_recommendation:reduce",
            ],
            "source_summary": {
                "family_execution_status": "manual_review",
                "lifecycle_state": "degraded",
                "rollout_recommendation": "reduce",
                "rollout_maturity": "mature",
            },
        },
        promotion_review_queue={
            "available": True,
            "advisory_only": True,
            "queue_state": "defer_first_queue",
            "headline_family": "trend_continuation",
            "top_review_action": "defer_review",
            "review_queue": [
                {
                    "family": "trend_continuation",
                    "review_action": "defer_review",
                    "promotion_state": "defer",
                    "target_posture": "keep_current",
                    "priority_rank": 17,
                    "confidence": "high",
                    "reason_codes": [
                        "promotion_governance:defer",
                        "family_execution:manual_review",
                        "lifecycle:degraded",
                    ],
                },
                {
                    "family": "sweep_reversal",
                    "review_action": "hold_monitor",
                    "promotion_state": "hold",
                    "target_posture": "keep_current",
                    "priority_rank": 31,
                    "confidence": "medium",
                    "reason_codes": [
                        "promotion_governance:hold",
                        "condition_drag:cost_condition",
                    ],
                },
            ],
        },
        strategy_lifecycle={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "state": "degraded",
            "confidence": "high",
        },
        positive_evidence_expansion={
            "available": True,
            "advisory_only": True,
            "family": "sweep_reversal",
            "state": "hold",
            "expansion_bias": "hold",
            "confidence": "medium",
        },
        outcome_bucket_granularity={
            "available": True,
            "advisory_only": True,
            "family_focus": {"key": "sweep_reversal"},
            "top_condition_axis": "cost_condition",
            "confidence": "high",
        },
        family_execution_degradation_advisory={
            "families": [
                {"family": "trend_continuation", "status": "manual_review", "confidence": "high"},
                {"family": "sweep_reversal", "status": "healthy", "confidence": "medium"},
            ]
        },
        rollout_recommendation={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "recommendation": "reduce",
            "maturity": "mature",
        },
        capital_allocator={
            "available": True,
            "family_focus": "trend_continuation",
            "family_weights": [
                {
                    "family": "trend_continuation",
                    "tier": "reduce",
                    "capital_pressure": "overallocated_negative",
                },
                {
                    "family": "sweep_reversal",
                    "tier": "boost",
                    "capital_pressure": "underallocated_positive",
                },
            ],
        },
        alpha_research_pipeline={},
    )

    assert payload["available"] is True
    assert payload["queue_state"] == "execution_first_queue"
    assert payload["headline_family"] == "trend_continuation"
    assert payload["top_remediation_action"] == "execution_remediation"
    assert payload["remediation_queue"][0]["family"] == "trend_continuation"
    assert payload["remediation_queue"][0]["remediation_action"] == "execution_remediation"
    assert payload["remediation_queue"][1]["family"] == "sweep_reversal"
    assert payload["remediation_queue"][1]["remediation_action"] == "condition_remediation"
    assert payload["source_summary"]["execution_first_count"] == 1
    assert payload["source_summary"]["policy_first_count"] == 0
    assert payload["source_summary"]["condition_first_count"] == 1
    assert payload["source_summary"]["observe_count"] == 0
    assert payload["source_summary"]["top_remediation_domain"] == "execution"
