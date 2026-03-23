from __future__ import annotations

from app.services.b_continuation_activation import BContinuationActivationService


def test_b_continuation_activation_stays_research_only_under_a_only() -> None:
    service = BContinuationActivationService()

    payload = service.generate(
        multi_strategy_ab={
            "mode": "A_ONLY",
            "b_cluster": {
                "cluster": "b_continuation",
                "strategy_cluster_status": "compare_only",
                "live_eligible": False,
                "guardrail_reasons": ["b_guardrail:mode_a_only"],
            },
        },
        score_to_outcome_funnel={
            "decomposition": {
                "family": [
                    {"key": "trend_continuation", "closed": 6},
                ]
            }
        },
        family_execution_degradation_advisory={"families": [{"family": "trend_continuation", "status": "healthy"}]},
        rollout_recommendation={"family": "trend_continuation", "recommendation": "hold"},
        strategy_lifecycle={"family": "trend_continuation", "state": "probation"},
        promotion_governance={},
        promotion_clearance_tracker={},
        promotion_reopen_queue={},
        promotion_decision_brief={},
        auto_promotion_rollout_execution={},
        positive_evidence_expansion={},
    )

    assert payload["available"] is True
    assert payload["activation_state"] == "research_only"
    assert payload["activation_bias"] == "stay_research"
    assert payload["target_mode"] == "A_ONLY"


def test_b_continuation_activation_marks_activation_ready_when_first_wave_guardrails_clear() -> None:
    service = BContinuationActivationService()

    payload = service.generate(
        multi_strategy_ab={
            "mode": "A_PLUS_B",
            "b_cluster": {
                "cluster": "b_continuation",
                "strategy_cluster_status": "probation_ready",
                "live_eligible": True,
                "guardrail_reasons": [],
            },
        },
        score_to_outcome_funnel={
            "decomposition": {
                "family": [
                    {"key": "trend_continuation", "closed": 8},
                ]
            }
        },
        family_execution_degradation_advisory={"families": [{"family": "trend_continuation", "status": "healthy"}]},
        rollout_recommendation={"family": "trend_continuation", "recommendation": "hold"},
        strategy_lifecycle={"family": "trend_continuation", "state": "probation"},
        promotion_governance={"family": "trend_continuation", "state": "hold"},
        promotion_clearance_tracker={"family": "trend_continuation", "clearance_state": "clearance_ready"},
        promotion_reopen_queue={
            "headline_family": "trend_continuation",
            "top_reopen_action": "reopen_review",
            "reopen_queue": [{"family": "trend_continuation", "reopen_action": "reopen_review"}],
        },
        promotion_decision_brief={"family": "trend_continuation", "brief_state": "reopen_candidate"},
        auto_promotion_rollout_execution={
            "target_family": "trend_continuation",
            "execution_stage": "semi_auto_candidate",
        },
        positive_evidence_expansion={"family": "trend_continuation", "state": "expandable"},
    )

    assert payload["available"] is True
    assert payload["activation_state"] == "activation_ready"
    assert payload["activation_bias"] == "consider_first_wave_activation"
    assert payload["source_summary"]["clearance_state"] == "clearance_ready"
    assert payload["source_summary"]["reopen_action"] == "reopen_review"
