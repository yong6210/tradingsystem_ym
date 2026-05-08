from __future__ import annotations

from types import SimpleNamespace

from app.services.acceptance_rejection_classifier import (
    AcceptanceRejectionClassifierService,
    AcceptanceRejectionInput,
    ReactionBar,
)
from app.services.context_engine import ContextSnapshot


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


def test_build_input_with_reason_reports_missing_recent_sweep() -> None:
    service = AcceptanceRejectionClassifierService()
    zone = SimpleNamespace(low=100.0, high=101.0, dir_bias="support", type="LP")
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.2,
        jump_rate_5m=0.02,
        friction_5m=0.03,
        atr5=1.0,
        atr15=2.0,
        sdir=0.0,
        sevt=0.0,
        f=0.0,
        v=0.0,
        a=0.0,
        vz=0.0,
        az=0.0,
        last_price=100.8,
        regime_label="range",
    )
    candles = [
        SimpleNamespace(o=100.5, h=100.9, l=100.2, c=100.8),
        SimpleNamespace(o=100.8, h=101.0, l=100.4, c=100.7),
        SimpleNamespace(o=100.7, h=100.95, l=100.3, c=100.6),
        SimpleNamespace(o=100.6, h=100.8, l=100.1, c=100.5),
        SimpleNamespace(o=100.5, h=100.7, l=100.15, c=100.4),
    ]

    payload, reason = service.build_input_with_reason(zone=zone, context=context, candles_5m=candles)

    assert payload is None
    assert reason == "no_recent_level_sweep"


def test_build_input_with_reason_supports_zone_band_override() -> None:
    service = AcceptanceRejectionClassifierService()
    zone = SimpleNamespace(low=100.0, high=101.0, dir_bias="support", type="LP")
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.2,
        jump_rate_5m=0.02,
        friction_5m=0.03,
        atr5=1.0,
        atr15=2.0,
        sdir=0.0,
        sevt=0.0,
        f=0.0,
        v=0.0,
        a=0.0,
        vz=0.0,
        az=0.0,
        last_price=100.8,
        regime_label="range",
    )
    candles = [
        SimpleNamespace(o=100.8, h=100.95, l=100.32, c=100.7),
        SimpleNamespace(o=100.7, h=100.9, l=100.28, c=100.62),
        SimpleNamespace(o=100.62, h=100.84, l=100.24, c=100.66),
        SimpleNamespace(o=100.66, h=100.88, l=100.27, c=100.71),
        SimpleNamespace(o=100.71, h=100.92, l=100.26, c=100.74),
    ]

    exact_payload, exact_reason = service.build_input_with_reason(zone=zone, context=context, candles_5m=candles)
    shadow_payload, shadow_reason = service.build_input_with_reason(
        zone=zone,
        context=context,
        candles_5m=candles,
        sweep_level_override=100.25,
        swept_level_type_override="zone_band_shadow",
    )

    assert exact_payload is None
    assert exact_reason == "no_recent_level_sweep"
    assert shadow_payload is not None
    assert shadow_reason == "ok"
    assert shadow_payload.swept_level == 100.25
    assert shadow_payload.swept_level_type == "zone_band_shadow"


def test_build_input_with_reason_supports_one_bar_shadow_override() -> None:
    service = AcceptanceRejectionClassifierService()
    zone = SimpleNamespace(low=100.0, high=101.0, dir_bias="support", type="LP")
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.2,
        jump_rate_5m=0.02,
        friction_5m=0.03,
        atr5=1.0,
        atr15=2.0,
        sdir=0.0,
        sevt=0.0,
        f=0.0,
        v=0.0,
        a=0.0,
        vz=0.0,
        az=0.0,
        last_price=100.8,
        regime_label="range",
    )
    candles = [
        SimpleNamespace(o=100.9, h=101.1, l=100.3, c=100.8),
        SimpleNamespace(o=100.8, h=101.0, l=100.25, c=100.7),
        SimpleNamespace(o=100.7, h=100.9, l=99.8, c=100.25),
    ]

    exact_payload, exact_reason = service.build_input_with_reason(zone=zone, context=context, candles_5m=candles)
    shadow_payload, shadow_reason = service.build_input_with_reason(
        zone=zone,
        context=context,
        candles_5m=candles,
        swept_level_type_override="one_bar_shadow",
        min_event_bars=1,
    )

    assert exact_payload is None
    assert exact_reason == "insufficient_post_sweep_bars"
    assert shadow_payload is not None
    assert shadow_reason == "ok"
    assert shadow_payload.swept_level_type == "one_bar_shadow"
