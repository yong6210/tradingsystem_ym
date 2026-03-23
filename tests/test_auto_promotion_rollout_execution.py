from app.services.auto_promotion_rollout_execution import AutoPromotionRolloutExecutionService


def test_auto_promotion_rollout_execution_marks_semi_auto_candidate_when_positive_support_is_strong() -> None:
    service = AutoPromotionRolloutExecutionService()

    payload = service.generate(
        promotion_governance={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "state": "promotable",
            "target_posture": "production",
            "confidence": "high",
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
        promotion_decision_brief={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "brief_state": "reopen_candidate",
            "decision_bias": "consider_reopen_review",
            "target_posture": "production",
            "confidence": "high",
        },
        rollout_recommendation={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "recommendation": "expand",
            "confidence": "high",
            "maturity": "mature",
        },
        strategy_lifecycle={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "state": "probation",
        },
        family_execution_degradation_advisory={
            "families": [{"family": "trend_continuation", "status": "healthy", "confidence": "high"}]
        },
        mode_advisory={
            "family": [
                {
                    "bucket": "trend_continuation",
                    "advisory_state": "keep_current_mode",
                    "confidence": "high",
                }
            ]
        },
        outcome_control_trace={
            "available": True,
            "approval_penalty_status": "healthy",
        },
        positive_evidence_expansion={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "state": "expandable",
            "expansion_bias": "consider_expand",
            "confidence": "high",
        },
    )

    assert payload["available"] is True
    assert payload["target_family"] == "trend_continuation"
    assert payload["execution_stage"] == "semi_auto_candidate"
    assert payload["execution_bias"] == "consider_semi_auto"
    assert payload["action_domain"] == "rollout_policy_delta"
    assert payload["write_scope"] == "proposal_only"


def test_auto_promotion_rollout_execution_blocks_when_guardrails_remain_active() -> None:
    service = AutoPromotionRolloutExecutionService()

    payload = service.generate(
        promotion_governance={
            "available": True,
            "advisory_only": True,
            "family": "sweep_reversal",
            "state": "defer",
            "target_posture": "keep_current",
            "confidence": "medium",
            "source_summary": {
                "family_mode_advisory_state": "research_only",
            },
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
        promotion_decision_brief={
            "available": True,
            "advisory_only": True,
            "family": "sweep_reversal",
            "brief_state": "clearance_required",
            "decision_bias": "continue_clearance",
            "target_posture": "keep_current",
            "confidence": "medium",
        },
        rollout_recommendation={
            "available": True,
            "advisory_only": True,
            "family": "sweep_reversal",
            "recommendation": "reduce",
            "confidence": "medium",
            "maturity": "mature",
        },
        strategy_lifecycle={
            "available": True,
            "advisory_only": True,
            "family": "sweep_reversal",
            "state": "degraded",
        },
        family_execution_degradation_advisory={
            "families": [{"family": "sweep_reversal", "status": "manual_review", "confidence": "high"}]
        },
        mode_advisory={
            "family": [
                {
                    "bucket": "sweep_reversal",
                    "advisory_state": "research_only",
                    "confidence": "medium",
                }
            ]
        },
        outcome_control_trace={
            "available": True,
            "approval_penalty_status": "manual_review",
        },
        positive_evidence_expansion={
            "available": True,
            "advisory_only": True,
            "family": "sweep_reversal",
            "state": "not_ready",
            "expansion_bias": "do_not_expand",
            "confidence": "low",
        },
    )

    assert payload["available"] is True
    assert payload["target_family"] == "sweep_reversal"
    assert payload["execution_stage"] == "auto_execution_blocked"
    assert payload["execution_bias"] == "block_auto_execution"
    assert payload["write_scope"] == "none"
    assert "execution_guardrail:manual_review" in payload["reason_codes"]
