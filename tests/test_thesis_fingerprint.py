from __future__ import annotations

from datetime import datetime, timezone

from app.services.thesis_fingerprint import ThesisFingerprintService


def test_same_thesis_allows_adjacent_buckets_and_equivalent_narratives() -> None:
    service = ThesisFingerprintService()
    left = service.build(
        symbol="BTCAUSDC",
        direction="short",
        regime="trend",
        strategy_family="sweep_reversal",
        reaction_classification="rejection_confirmed",
        zone_type="OB",
        near_lp=False,
        at=datetime(2026, 3, 7, 9, 5, tzinfo=timezone.utc),
    )
    right = service.build(
        symbol="BTCBUSDC",
        direction="short",
        regime="trend",
        strategy_family="sweep_reversal",
        reaction_classification="rejection_tentative",
        zone_type="LP",
        near_lp=True,
        at=datetime(2026, 3, 7, 9, 35, tzinfo=timezone.utc),
    )

    assert left["time_bucket"] != right["time_bucket"]
    assert service.liquidity_equivalence(left["liquidity_narrative"]) == "session_high_sweep"
    assert service.liquidity_equivalence(right["liquidity_narrative"]) == "session_high_sweep"
    assert service.event_group(left["event_classification"]) == "rejection"
    assert service.event_group(right["event_classification"]) == "rejection"
    assert service.same_thesis(left, right) is True


def test_same_thesis_rejects_different_event_groups() -> None:
    service = ThesisFingerprintService()
    rejection = service.build(
        symbol="ETHAUSDC",
        direction="long",
        regime="range",
        strategy_family="range_rotation",
        reaction_classification="rejection_confirmed",
        zone_type="LP",
        near_lp=True,
        at=datetime(2026, 3, 7, 10, 5, tzinfo=timezone.utc),
    )
    acceptance = service.build(
        symbol="ETHBUSDC",
        direction="long",
        regime="range",
        strategy_family="range_rotation",
        reaction_classification="acceptance_confirmed",
        zone_type="LP",
        near_lp=True,
        at=datetime(2026, 3, 7, 10, 25, tzinfo=timezone.utc),
    )

    assert service.same_thesis(rejection, acceptance) is False
