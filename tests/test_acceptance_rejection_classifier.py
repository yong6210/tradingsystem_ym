from __future__ import annotations

from app.services.acceptance_rejection_classifier import (
    AcceptanceRejectionClassifierService,
    AcceptanceRejectionInput,
    ReactionBar,
)


def _bars() -> list[ReactionBar]:
    return [
        ReactionBar(o=100.5, h=101.0, l=99.0, c=99.4),
        ReactionBar(o=99.4, h=101.4, l=99.2, c=101.1),
        ReactionBar(o=101.1, h=101.8, l=100.2, c=101.5),
    ]


def test_classifier_marks_rejection_confirmed() -> None:
    service = AcceptanceRejectionClassifierService()
    payload = AcceptanceRejectionInput(
        swept_level=100.0,
        sweep_side="below",
        swept_level_type="LP",
        bars=_bars(),
        atr5=1.0,
        reclaim_bars=2,
        displacement_atr=1.4,
        continuation_displacement_atr=0.5,
        follow_through_atr=0.9,
        outside_close_count=1,
        dwell_time_bars=1,
        inefficiency_created=True,
        retest_hold=True,
        opposite_reclaim_failure=False,
        session_quality=0.9,
        avg_wick_to_body_ratio=1.1,
    )

    result = service.classify(payload)

    assert result.available is True
    assert result.classification == "rejection_confirmed"
    assert result.rejection_hard_count == 3
    assert result.rejection_score >= service.settings.reaction_classifier_rejection_confirmed_score


def test_classifier_marks_acceptance_confirmed() -> None:
    service = AcceptanceRejectionClassifierService()
    payload = AcceptanceRejectionInput(
        swept_level=100.0,
        sweep_side="below",
        swept_level_type="LP",
        bars=_bars(),
        atr5=1.0,
        reclaim_bars=None,
        displacement_atr=0.4,
        continuation_displacement_atr=1.3,
        follow_through_atr=-0.7,
        outside_close_count=3,
        dwell_time_bars=3,
        inefficiency_created=False,
        retest_hold=True,
        opposite_reclaim_failure=True,
        session_quality=0.8,
        avg_wick_to_body_ratio=1.0,
    )

    result = service.classify(payload)

    assert result.available is True
    assert result.classification == "acceptance_confirmed"
    assert result.acceptance_hard_count == 3
    assert result.acceptance_score >= service.settings.reaction_classifier_acceptance_confirmed_score


def test_classifier_marks_mixed_when_scores_conflict_or_follow_through_is_weak() -> None:
    service = AcceptanceRejectionClassifierService()
    payload = AcceptanceRejectionInput(
        swept_level=100.0,
        sweep_side="below",
        swept_level_type="LP",
        bars=_bars(),
        atr5=1.0,
        reclaim_bars=2,
        displacement_atr=1.0,
        continuation_displacement_atr=1.0,
        follow_through_atr=0.1,
        outside_close_count=2,
        dwell_time_bars=2,
        inefficiency_created=False,
        retest_hold=False,
        opposite_reclaim_failure=False,
        session_quality=0.5,
        avg_wick_to_body_ratio=2.4,
    )

    result = service.classify(payload)

    assert result.available is True
    assert result.classification == "mixed"
    assert "reclaim_without_follow_through" in result.mixed_reasons
    assert "wick_noise_dominant" in result.mixed_reasons
