from app.services.promotion_governance import PromotionGovernanceService


def test_promotion_governance_marks_family_promotable_only_when_guardrails_clear() -> None:
    service = PromotionGovernanceService()

    payload = service.generate(
        strategy_lifecycle={
            "available": True,
            "advisory_only": True,
            "family": "sweep_reversal",
            "state": "production",
            "confidence": "high",
            "source_summary": {
                "rollout_maturity": "mature",
                "family_execution_status": "healthy",
                "family_mode_advisory_state": "keep_current_mode",
            },
        },
        rollout_recommendation={
            "available": True,
            "advisory_only": True,
            "family": "sweep_reversal",
            "recommendation": "expand",
            "maturity": "mature",
        },
        positive_evidence_expansion={
            "available": True,
            "advisory_only": True,
            "family": "sweep_reversal",
            "state": "expandable",
            "expansion_bias": "consider_expand",
            "confidence": "high",
            "source_summary": {
                "family_execution_status": "healthy",
                "family_mode_advisory_state": "keep_current_mode",
                "rollout_maturity": "mature",
            },
        },
        outcome_bucket_granularity={
            "available": True,
            "advisory_only": True,
            "top_condition_axis": "",
            "confidence": "low",
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
                }
            ]
        },
        capital_allocator={
            "available": True,
            "family_focus": "sweep_reversal",
            "capital_pressure": "underallocated_positive",
            "family_weights": [
                {
                    "family": "sweep_reversal",
                    "tier": "boost",
                }
            ],
        },
        score_to_outcome_funnel={
            "decomposition": {
                "family": [
                    {
                        "key": "sweep_reversal",
                        "closed": 12,
                        "runtime_candidates": 20,
                    }
                ]
            }
        },
    )

    assert payload["available"] is True
    assert payload["family"] == "sweep_reversal"
    assert payload["state"] == "promotable"
    assert payload["promotion_bias"] == "consider_promote"
    assert payload["target_posture"] == "production"
    assert payload["confidence"] == "high"
    assert "promotion_governance:promotable" in payload["reason_codes"]
    assert "allocator:boost" in payload["reason_codes"]
    assert payload["source_summary"]["allocator_tier"] == "boost"
