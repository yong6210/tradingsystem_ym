from app.services.promotion_reopen_queue import PromotionReopenQueueService


def test_promotion_reopen_queue_marks_clearance_ready_family_for_reopen_review() -> None:
    service = PromotionReopenQueueService()

    payload = service.generate(
        promotion_governance={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "state": "promotable",
            "confidence": "high",
            "reason_codes": ["promotion_governance:promotable"],
            "source_summary": {"family_execution_status": "healthy", "lifecycle_state": "production"},
        },
        promotion_review_queue={
            "available": True,
            "advisory_only": True,
            "review_queue": [
                {
                    "family": "trend_continuation",
                    "review_action": "promote_review",
                    "promotion_state": "promotable",
                    "priority_rank": 8,
                    "confidence": "high",
                    "reason_codes": ["promotion_governance:promotable"],
                }
            ],
        },
        promotion_remediation_queue={
            "available": True,
            "advisory_only": True,
            "remediation_queue": [],
        },
        promotion_clearance_tracker={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "clearance_state": "clearance_ready",
            "confidence": "high",
            "reason_codes": ["promotion_clearance:clearance_ready"],
            "source_summary": {"family_execution_status": "healthy"},
        },
        strategy_lifecycle={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "state": "production",
        },
        positive_evidence_expansion={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "state": "expandable",
            "confidence": "high",
        },
        capital_allocator={
            "available": True,
            "family_weights": [
                {
                    "family": "trend_continuation",
                    "tier": "boost",
                    "capital_pressure": "underallocated_positive",
                }
            ],
        },
        family_execution_degradation_advisory={
            "families": [{"family": "trend_continuation", "status": "healthy", "confidence": "high"}]
        },
    )

    assert payload["available"] is True
    assert payload["queue_state"] == "reopen_ready_queue"
    assert payload["headline_family"] == "trend_continuation"
    assert payload["top_reopen_action"] == "reopen_review"
    assert payload["reopen_queue"][0]["reopen_action"] == "reopen_review"
    assert payload["reopen_queue"][0]["clearance_state"] == "clearance_ready"
    assert payload["source_summary"]["reopen_ready_count"] == 1
    assert payload["source_summary"]["continue_clearance_count"] == 0


def test_promotion_reopen_queue_keeps_manual_review_family_in_continue_clearance() -> None:
    service = PromotionReopenQueueService()

    payload = service.generate(
        promotion_governance={
            "available": True,
            "advisory_only": True,
            "family": "sweep_reversal",
            "state": "defer",
            "confidence": "medium",
            "reason_codes": ["promotion_governance:defer", "family_execution:manual_review"],
            "source_summary": {"family_execution_status": "manual_review", "lifecycle_state": "degraded"},
        },
        promotion_review_queue={
            "available": True,
            "advisory_only": True,
            "review_queue": [
                {
                    "family": "sweep_reversal",
                    "review_action": "defer_review",
                    "promotion_state": "defer",
                    "priority_rank": 17,
                    "confidence": "medium",
                    "reason_codes": ["promotion_governance:defer", "family_execution:manual_review"],
                }
            ],
        },
        promotion_remediation_queue={
            "available": True,
            "advisory_only": True,
            "remediation_queue": [
                {
                    "family": "sweep_reversal",
                    "remediation_action": "execution_remediation",
                    "priority_rank": 6,
                    "confidence": "high",
                    "reason_codes": ["family_execution:manual_review"],
                }
            ],
        },
        promotion_clearance_tracker={
            "available": True,
            "advisory_only": True,
            "family": "sweep_reversal",
            "clearance_state": "blocked",
            "confidence": "medium",
            "reason_codes": ["promotion_clearance:blocked", "family_execution:manual_review"],
            "source_summary": {"family_execution_status": "manual_review"},
        },
        strategy_lifecycle={
            "available": True,
            "advisory_only": True,
            "family": "sweep_reversal",
            "state": "degraded",
        },
        positive_evidence_expansion={
            "available": True,
            "advisory_only": True,
            "family": "sweep_reversal",
            "state": "not_ready",
            "confidence": "low",
        },
        capital_allocator={
            "available": True,
            "family_weights": [
                {
                    "family": "sweep_reversal",
                    "tier": "reduce",
                    "capital_pressure": "overallocated_negative",
                }
            ],
        },
        family_execution_degradation_advisory={
            "families": [{"family": "sweep_reversal", "status": "manual_review", "confidence": "high"}]
        },
    )

    assert payload["available"] is True
    assert payload["queue_state"] == "clearance_first_queue"
    assert payload["headline_family"] == "sweep_reversal"
    assert payload["top_reopen_action"] == "continue_clearance"
    assert payload["reopen_queue"][0]["reopen_action"] == "continue_clearance"
    assert payload["reopen_queue"][0]["clearance_state"] == "blocked"
    assert payload["source_summary"]["continue_clearance_count"] == 1
    assert payload["source_summary"]["top_remediation_action"] == "execution_remediation"
