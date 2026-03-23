from app.services.strategy_lifecycle import StrategyLifecycleService


def test_strategy_lifecycle_marks_live_family_as_degraded_when_rollout_reduces() -> None:
    service = StrategyLifecycleService()

    payload = service.generate(
        alpha_research_pipeline={
            "promotion_watchlist": {
                "available": True,
                "watch_items": [
                    {
                        "focus": "family_information_failure",
                        "bucket": "trend_continuation",
                        "confidence": "medium",
                        "not_ready_reason": "execution_drag_conflict",
                    }
                ],
            }
        },
        score_to_outcome_funnel={
            "decomposition": {
                "family": [
                    {
                        "key": "trend_continuation",
                        "closed": 10,
                        "baseline_cost_profitable_rate_from_closed": 0.2,
                    }
                ]
            }
        },
        family_execution_degradation_advisory={
            "families": [
                {
                    "family": "trend_continuation",
                    "status": "manual_review",
                    "confidence": "high",
                }
            ]
        },
        mode_advisory={
            "family": [
                {
                    "bucket": "trend_continuation",
                    "advisory_state": "watch",
                    "confidence": "high",
                    "sample_note": "repeat evidence is present",
                }
            ]
        },
        rollout_recommendation={
            "available": True,
            "family": "trend_continuation",
            "recommendation": "reduce",
            "maturity": "mature",
            "current_policy": {
                "live_enabled": True,
                "max_execution_mode": "MICRO_LIVE",
                "max_risk_r": 1.0,
            },
            "top_modifier": {"axis": "session", "key": "dead_session", "state": "negative"},
        },
    )

    assert payload["available"] is True
    assert payload["family"] == "trend_continuation"
    assert payload["previous_state"] == "production"
    assert payload["state"] == "degraded"
    assert payload["transition_bias"] == "degrade"
    assert payload["confidence"] == "high"
    assert "lifecycle:degraded" in payload["reason_codes"]
    assert "rollout_recommendation:reduce" in payload["reason_codes"]
    assert payload["source_summary"]["rollout_maturity"] == "mature"
    assert payload["source_summary"]["modifier_state"] == "negative"
