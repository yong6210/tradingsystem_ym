from app.services.promotion_decision_brief import PromotionDecisionBriefService


def test_promotion_decision_brief_marks_reopen_candidate_when_clearance_is_ready() -> None:
    service = PromotionDecisionBriefService()

    payload = service.generate(
        promotion_governance={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "state": "promotable",
            "target_posture": "production",
            "confidence": "high",
            "reason_codes": ["promotion_governance:promotable"],
        },
        promotion_review_queue={
            "available": True,
            "advisory_only": True,
            "headline_family": "trend_continuation",
            "top_review_action": "promote_review",
            "review_queue": [
                {
                    "family": "trend_continuation",
                    "review_action": "promote_review",
                    "promotion_state": "promotable",
                    "confidence": "high",
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
        },
        promotion_reopen_queue={
            "available": True,
            "advisory_only": True,
            "headline_family": "trend_continuation",
            "top_reopen_action": "reopen_review",
            "reopen_queue": [
                {
                    "family": "trend_continuation",
                    "reopen_action": "reopen_review",
                    "clearance_state": "clearance_ready",
                    "promotion_state": "promotable",
                    "confidence": "high",
                }
            ],
        },
        strategy_lifecycle={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "state": "probation",
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
    assert payload["family"] == "trend_continuation"
    assert payload["brief_state"] == "reopen_candidate"
    assert payload["decision_bias"] == "consider_reopen_review"
    assert payload["target_posture"] == "production"


def test_promotion_decision_brief_marks_clearance_required_when_manual_review_remains() -> None:
    service = PromotionDecisionBriefService()

    payload = service.generate(
        promotion_governance={
            "available": True,
            "advisory_only": True,
            "family": "sweep_reversal",
            "state": "defer",
            "target_posture": "keep_current",
            "confidence": "medium",
            "reason_codes": ["promotion_governance:defer", "family_execution:manual_review"],
        },
        promotion_review_queue={
            "available": True,
            "advisory_only": True,
            "headline_family": "sweep_reversal",
            "top_review_action": "defer_review",
            "review_queue": [
                {
                    "family": "sweep_reversal",
                    "review_action": "defer_review",
                    "promotion_state": "defer",
                    "confidence": "medium",
                }
            ],
        },
        promotion_remediation_queue={
            "available": True,
            "advisory_only": True,
            "headline_family": "sweep_reversal",
            "top_remediation_action": "execution_remediation",
            "remediation_queue": [
                {
                    "family": "sweep_reversal",
                    "remediation_action": "execution_remediation",
                    "confidence": "high",
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
        },
        promotion_reopen_queue={
            "available": True,
            "advisory_only": True,
            "headline_family": "sweep_reversal",
            "top_reopen_action": "continue_clearance",
            "reopen_queue": [
                {
                    "family": "sweep_reversal",
                    "reopen_action": "continue_clearance",
                    "clearance_state": "blocked",
                    "promotion_state": "defer",
                    "confidence": "medium",
                }
            ],
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
    assert payload["family"] == "sweep_reversal"
    assert payload["brief_state"] == "clearance_required"
    assert payload["decision_bias"] == "continue_clearance"
    assert payload["target_posture"] == "keep_current"
