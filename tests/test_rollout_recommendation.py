from app.core.enums import ExecutionMode
from app.services.rollout_recommendation import RolloutRecommendationService


def test_rollout_recommendation_expands_mature_positive_family() -> None:
    service = RolloutRecommendationService()

    payload = service.generate(
        score_to_outcome_funnel={
            "decomposition": {
                "family": [
                    {
                        "key": "sweep_reversal",
                        "closed": 9,
                        "baseline_cost_profitable_rate_from_closed": 0.66,
                    }
                ],
                "regime": [],
                "session": [],
            }
        },
        execution_degradation_advisory={"status": "healthy"},
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
            ],
            "regime": [],
            "session": [],
        },
        rollout_policies=[
            {
                "strategy_family": "sweep_reversal",
                "live_enabled": False,
                "max_execution_mode": ExecutionMode.PAPER.value,
                "max_risk_r": 0.5,
                "allowed_sessions": ["london", "new_york"],
                "min_quality_score": 70.0,
            }
        ],
    )

    assert payload["available"] is True
    assert payload["family"] == "sweep_reversal"
    assert payload["recommendation"] == "expand"
    assert payload["confidence"] == "high"
    assert payload["maturity"] == "mature"
    assert payload["suggested_policy_delta"]["action"] == "expand_consideration"
    assert payload["suggested_policy_delta"]["suggested_max_execution_mode"] == ExecutionMode.MICRO_LIVE.value


def test_rollout_recommendation_reduces_live_family_when_outcome_and_execution_are_weak() -> None:
    service = RolloutRecommendationService()

    payload = service.generate(
        score_to_outcome_funnel={
            "decomposition": {
                "family": [
                    {
                        "key": "trend_continuation",
                        "closed": 10,
                        "baseline_cost_profitable_rate_from_closed": 0.2,
                    }
                ],
                "regime": [],
                "session": [],
            }
        },
        execution_degradation_advisory={"status": "watch"},
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
            ],
            "regime": [],
            "session": [],
        },
        rollout_policies=[
            {
                "strategy_family": "trend_continuation",
                "live_enabled": True,
                "max_execution_mode": ExecutionMode.MICRO_LIVE.value,
                "max_risk_r": 1.0,
                "allowed_sessions": ["london", "new_york"],
                "min_quality_score": 75.0,
            }
        ],
    )

    assert payload["family"] == "trend_continuation"
    assert payload["recommendation"] == "reduce"
    assert payload["suggested_policy_delta"]["action"] == "reduce_consideration"
    assert payload["suggested_policy_delta"]["suggested_max_execution_mode"] == ExecutionMode.PAPER.value
    assert payload["suggested_policy_delta"]["suggested_max_risk_r"] == 0.5


def test_rollout_recommendation_keeps_thin_watch_family_in_research_only() -> None:
    service = RolloutRecommendationService()

    payload = service.generate(
        score_to_outcome_funnel={
            "decomposition": {
                "family": [
                    {
                        "key": "range_rotation",
                        "closed": 2,
                        "baseline_cost_profitable_rate_from_closed": 0.0,
                    }
                ],
                "regime": [],
                "session": [],
            }
        },
        execution_degradation_advisory={"status": "healthy"},
        family_execution_degradation_advisory={
            "families": [
                {
                    "family": "range_rotation",
                    "status": "watch",
                    "confidence": "low",
                }
            ]
        },
        mode_advisory={
            "family": [
                {
                    "bucket": "range_rotation",
                    "advisory_state": "watch",
                    "confidence": "low",
                    "sample_note": "sample is thin; treat this as advisory context only",
                }
            ],
            "regime": [],
            "session": [],
        },
        rollout_policies=[
            {
                "strategy_family": "range_rotation",
                "live_enabled": False,
                "max_execution_mode": ExecutionMode.SHADOW.value,
                "max_risk_r": 0.25,
                "allowed_sessions": ["london", "new_york"],
                "min_quality_score": 68.0,
            }
        ],
    )

    assert payload["family"] == "range_rotation"
    assert payload["recommendation"] == "research_only"
    assert payload["confidence"] == "low"
    assert payload["suggested_policy_delta"]["action"] == "keep_research_only"
