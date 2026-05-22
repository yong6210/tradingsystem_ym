from __future__ import annotations

from app.services.outcome_control_trace import build_outcome_control_trace, summarize_outcome_control_trace


def test_outcome_control_trace_keeps_empty_sample_execution_advisory_reason_only() -> None:
    trace = build_outcome_control_trace(
        execution_degradation_advisory={
            "available": True,
            "status": "manual_review",
            "advisory_only": True,
            "sample_context": {"plans_matured": 0, "fill_events_total": 0, "closed_plans": 0},
        },
        family_execution_degradation_advisory={},
        mode_advisory={},
        score_to_outcome_funnel={},
    )

    summary = summarize_outcome_control_trace(trace)

    assert summary is not None
    assert summary["approval_penalty_status"] == "watch"
    assert summary["approval_penalty_tier"] == "reason_only"
    assert "execution_degradation:manual_review" in summary["top_reason_codes"]


def test_outcome_control_trace_downgrades_material_manual_review_sample() -> None:
    trace = build_outcome_control_trace(
        execution_degradation_advisory={
            "available": True,
            "status": "manual_review",
            "advisory_only": True,
            "sample_context": {"plans_matured": 9, "fill_events_total": 7, "closed_plans": 3},
        },
        family_execution_degradation_advisory={},
        mode_advisory={},
        score_to_outcome_funnel={},
    )

    summary = summarize_outcome_control_trace(trace)

    assert summary is not None
    assert summary["approval_penalty_status"] == "manual_review"
    assert summary["approval_penalty_tier"] == "downgrade_to_manual"
