from app.services.research_promotion_operating_loop import ResearchPromotionOperatingLoopService


def test_research_promotion_operating_loop_marks_shadow_test_ready_for_research_candidate() -> None:
    service = ResearchPromotionOperatingLoopService()

    payload = service.generate(
        alpha_research_pipeline={
            "summary": {
                "alpha_research_candidate_count": 2,
                "top_family": "trend_continuation",
            },
            "recommended_action_summary": {
                "recommended_action": "run_shadow_exit_review",
                "recommended_scope": "family",
                "bucket": "trend_continuation",
                "confidence": "medium",
            },
            "top_shadow_experiment": {
                "experiment_id": "shadow_exit_review_family",
                "recommended_action": "run_shadow_exit_review",
                "confidence": "medium",
            },
            "promotion_watchlist": {
                "available": True,
                "watch_items": [
                    {
                        "bucket": "trend_continuation",
                        "confidence": "medium",
                        "not_ready_reason": "thin_sample",
                    }
                ],
            },
        },
        strategy_lifecycle={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "state": "research",
        },
        promotion_governance={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "state": "hold",
            "target_posture": "keep_current",
        },
        promotion_review_queue=None,
        promotion_decision_brief=None,
        auto_promotion_rollout_execution=None,
        promotion_lifecycle_history=None,
        family_execution_degradation_advisory={
            "families": [{"family": "trend_continuation", "status": "healthy"}]
        },
        multi_strategy_ab={
            "raw_family_anchor": "trend_continuation",
            "a_cluster": {"strategy_cluster_status": "current_anchor"},
        },
    )

    assert payload["available"] is True
    assert payload["family"] == "trend_continuation"
    assert payload["loop_state"] == "shadow_test_ready"
    assert payload["loop_bias"] == "queue_shadow_test"
    assert payload["target_stage"] == "tested"
    assert payload["recommended_action"] == "run_shadow_exit_review"
    assert payload["shadow_experiment_id"] == "shadow_exit_review_family"


def test_research_promotion_operating_loop_marks_followthrough_when_promotion_path_is_open() -> None:
    service = ResearchPromotionOperatingLoopService()

    payload = service.generate(
        alpha_research_pipeline={
            "summary": {
                "alpha_research_candidate_count": 3,
                "top_family": "trend_continuation",
            },
            "recommended_action_summary": {
                "recommended_action": "run_shadow_exit_review",
                "recommended_scope": "family",
                "bucket": "trend_continuation",
                "confidence": "high",
            },
            "top_shadow_experiment": {
                "experiment_id": "shadow_exit_review_family",
                "recommended_action": "run_shadow_exit_review",
                "confidence": "high",
            },
            "promotion_watchlist": {
                "available": True,
                "watch_items": [
                    {
                        "bucket": "trend_continuation",
                        "confidence": "high",
                        "not_ready_reason": None,
                    }
                ],
            },
        },
        strategy_lifecycle={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "state": "production",
        },
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
        },
        promotion_decision_brief={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "brief_state": "reopen_candidate",
            "confidence": "high",
        },
        auto_promotion_rollout_execution={
            "available": True,
            "advisory_only": True,
            "execution_stage": "semi_auto_candidate",
            "confidence": "high",
        },
        promotion_lifecycle_history={
            "available": True,
            "advisory_only": True,
            "family": "trend_continuation",
            "history_state": "history_stable",
        },
        family_execution_degradation_advisory={
            "families": [{"family": "trend_continuation", "status": "healthy"}]
        },
        multi_strategy_ab={
            "raw_family_anchor": "trend_continuation",
            "a_cluster": {"strategy_cluster_status": "current_anchor"},
        },
    )

    assert payload["available"] is True
    assert payload["family"] == "trend_continuation"
    assert payload["loop_state"] == "promotion_followthrough"
    assert payload["loop_bias"] == "follow_promotion_path"
    assert payload["target_stage"] == "promoted"
    assert payload["watchlist_ready"] is True
    assert payload["source_summary"]["history_state"] == "history_stable"
