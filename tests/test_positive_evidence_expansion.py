from app.services.positive_evidence_expansion import PositiveEvidenceExpansionService


def test_positive_evidence_expansion_marks_family_expandable_only_when_guardrails_clear() -> None:
    service = PositiveEvidenceExpansionService()

    payload = service.generate(
        score_to_outcome_funnel={
            "decomposition": {
                "family": [
                    {
                        "key": "sweep_reversal",
                        "closed": 9,
                        "baseline_cost_profitable_rate_from_closed": 0.6667,
                    }
                ]
            }
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
        rollout_recommendation={
            "available": True,
            "family": "sweep_reversal",
            "recommendation": "expand",
            "maturity": "mature",
            "top_modifier": {"axis": "session", "key": "overlap", "state": "positive"},
        },
        strategy_lifecycle={
            "available": True,
            "family": "sweep_reversal",
            "state": "production",
        },
        capital_allocator={
            "available": True,
            "family_focus": "sweep_reversal",
            "family_weights": [
                {
                    "family": "sweep_reversal",
                    "tier": "boost",
                }
            ],
        },
    )

    assert payload["available"] is True
    assert payload["family"] == "sweep_reversal"
    assert payload["state"] == "expandable"
    assert payload["expansion_bias"] == "consider_expand"
    assert payload["confidence"] == "high"
    assert "positive_expansion:expandable" in payload["reason_codes"]
    assert "allocator:boost" in payload["reason_codes"]
    assert payload["source_summary"]["allocator_tier"] == "boost"

