from __future__ import annotations

from datetime import datetime, timezone

from app.core.enums import EntryModel
from app.db.models import Candle, Zone
from app.services.acceptance_rejection_classifier import AcceptanceRejectionResult
from app.services.context_engine import ContextSnapshot
from app.services.strategy_family_router import StrategyFamilyRouter


def _zone(
    *,
    zone_type: str = "LP",
    dir_bias: str = "support",
    width_atr: float = 0.32,
    low: float = 99.2,
    high: float = 100.0,
    mid: float = 99.6,
) -> Zone:
    return Zone(
        zone_id="z_router",
        symbol="BTCUSDC",
        timeframe="15m",
        type=zone_type,
        low=low,
        high=high,
        mid=mid,
        width_atr=width_atr,
        dir_bias=dir_bias,
        created_ts=datetime.now(timezone.utc),
        touch_count=1,
        base_strength=82.0,
        quality=78.0,
        state="active",
        stats={"p1r": 0.72, "p2r": 0.55, "p3r": 0.31, "sample_size": 90},
        strategy_version="v1",
    )


def _trend_candles(*, long_setup: bool = True, protected_break: bool = False) -> list[Candle]:
    base = datetime(2026, 3, 7, tzinfo=timezone.utc)
    if long_setup:
        rows = [
            (100.0, 100.8, 99.7, 100.7),
            (100.7, 101.7, 100.5, 101.6),
            (101.6, 102.8, 101.4, 102.6),
            (102.6, 103.7, 102.3, 103.5),
            (103.5, 103.6, 102.9, 103.1),
            (103.1, 103.2, 102.5, 102.8),
            (102.8, 102.9, 102.4 if not protected_break else 99.0, 102.4),
            (102.4, 102.8, 102.4 if not protected_break else 98.9, 102.7),
        ]
    else:
        rows = [
            (103.5, 103.8, 102.7, 102.9),
            (102.9, 103.1, 101.9, 102.0),
            (102.0, 102.2, 100.9, 101.1),
            (101.1, 101.3, 100.1, 100.2),
            (100.2, 100.9, 100.0, 100.6),
            (100.6, 101.1, 100.4, 100.9),
            (100.9, 101.4 if not protected_break else 104.2, 100.8, 101.2),
            (101.2, 101.3 if not protected_break else 104.1, 100.6, 100.8),
        ]
    candles: list[Candle] = []
    for index, (o, h, l, c) in enumerate(rows):
        candles.append(
            Candle(
                symbol="BTCUSDC",
                timeframe="5m",
                ts=base,
                o=o,
                h=h,
                l=l,
                c=c,
                v=1_000.0,
                source="test",
                is_final=True,
            )
        )
        base = base.replace(minute=(base.minute + 5) % 60)
    return candles


def _context(
    *,
    regime_label: str = "range",
    transition_state: str = "none",
    friction: float = 0.10,
    jump_rate: float = 0.05,
    v: float = 0.4,
    last_price: float = 99.55,
    atr5: float = 0.5,
    regime_15m: float = 0.55,
) -> ContextSnapshot:
    return ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=regime_15m,
        jump_rate_5m=jump_rate,
        friction_5m=friction,
        atr5=atr5,
        atr15=1.0,
        sdir=0.7,
        sevt=-0.2,
        f=0.6,
        v=v,
        a=0.3,
        vz=0.8,
        az=0.4,
        last_price=last_price,
        regime_label=regime_label,
        transition_state=transition_state,
    )


def _reaction(
    *,
    classification: str = "rejection_confirmed",
    rejection_score: float = 86.0,
    acceptance_score: float = 18.0,
    outside_close_count: int = 0,
    session_quality: float = 0.95,
) -> AcceptanceRejectionResult:
    return AcceptanceRejectionResult(
        available=True,
        classification=classification,
        rejection_score=rejection_score,
        acceptance_score=acceptance_score,
        rejection_hard_count=3 if classification == "rejection_confirmed" else 2,
        acceptance_hard_count=0,
        mixed_reasons=[],
        input={"outside_close_count": outside_close_count, "session_quality": session_quality},
    )


def test_router_marks_a_grade_sweep_reversal_and_prefers_limit_for_clean_case() -> None:
    router = StrategyFamilyRouter()

    decision = router.route(
        zone=_zone(zone_type="LP", width_atr=0.28),
        context=_context(regime_label="range", friction=0.08, jump_rate=0.04, v=0.3),
        reaction=_reaction(),
        near_lp=True,
        zone_strength=88.0,
        confluence_score=81.0,
        regime_name="range",
        candles_5m=_trend_candles(),
    )

    assert decision.available is True
    assert decision.family == "sweep_reversal"
    assert decision.grade == "A"
    assert decision.entry_model == EntryModel.LIMIT
    assert decision.clean_case is True
    assert decision.split == {"tp1": 0.4, "tp2": 0.4, "runner": 0.2}
    assert decision.scorecard["family"] == "sweep_reversal"
    assert decision.scorecard["buckets"]["location"] == round(
        decision.components["location"] + decision.components["htf_alignment"], 2
    )
    assert decision.scorecard["buckets"]["reaction"] == round(
        decision.components["reaction_quality"] + decision.components["clarity"], 2
    )
    assert decision.scorecard["buckets"]["trendline_bonus"] == 0.0
    assert decision.scorecard["bucket_caps"]["trendline_bonus"] == 2.0


def test_router_blocks_sweep_reversal_in_trend_when_location_is_not_extreme() -> None:
    router = StrategyFamilyRouter()

    decision = router.route(
        zone=_zone(zone_type="OB"),
        context=_context(regime_label="trend", friction=0.09, jump_rate=0.04, v=-0.6),
        reaction=_reaction(rejection_score=84.0, acceptance_score=16.0, outside_close_count=1),
        near_lp=False,
        zone_strength=86.0,
        confluence_score=79.0,
        regime_name="trend",
        candles_5m=_trend_candles(),
    )

    assert decision.available is False
    assert decision.family == "sweep_reversal"
    assert decision.reason == "trend_requires_extreme_location"


def test_router_blocks_b_grade_reversal_during_transition_watch() -> None:
    router = StrategyFamilyRouter()

    decision = router.route(
        zone=_zone(zone_type="LP", width_atr=0.44),
        context=_context(regime_label="transition", transition_state="transition_watch", friction=0.18, jump_rate=0.10, v=0.1),
        reaction=_reaction(classification="rejection_tentative", rejection_score=69.0, acceptance_score=28.0, outside_close_count=1, session_quality=0.72),
        near_lp=True,
        zone_strength=74.0,
        confluence_score=73.0,
        regime_name="transition",
        candles_5m=_trend_candles(),
    )

    assert decision.available is False
    assert decision.grade in {"B", "C"}
    assert decision.reason == "transition_watch_a_only"


def test_router_marks_trend_continuation_a_grade_and_prefers_limit() -> None:
    router = StrategyFamilyRouter()

    decision = router.route(
        zone=_zone(zone_type="OB", dir_bias="support", width_atr=0.34, low=101.9, high=102.2, mid=102.05),
        context=_context(regime_label="trend", friction=0.08, jump_rate=0.04, v=0.9, last_price=102.6, atr5=1.0),
        reaction=AcceptanceRejectionResult(
            available=False,
            classification="not_applicable",
            rejection_score=0.0,
            acceptance_score=0.0,
            rejection_hard_count=0,
            acceptance_hard_count=0,
            mixed_reasons=[],
            input={},
        ),
        near_lp=False,
        zone_strength=87.0,
        confluence_score=82.0,
        regime_name="trend",
        candles_5m=_trend_candles(),
    )

    assert decision.available is True
    assert decision.family == "trend_continuation"
    assert decision.grade == "A"
    assert decision.entry_model == EntryModel.LIMIT
    assert decision.split == {"tp1": 0.3, "tp2": 0.3, "runner": 0.4}
    assert decision.scorecard["family"] == "trend_continuation"
    assert decision.scorecard["buckets"]["location"] == round(
        decision.components["htf_trend_clarity"] + decision.components["protected_level_hold"], 2
    )
    assert decision.scorecard["buckets"]["reaction"] == round(
        decision.components["impulse_quality"] + decision.components["pullback_quality"], 2
    )
    assert decision.scorecard["buckets"]["trendline_bonus"] == 0.0


def test_router_blocks_trend_continuation_when_protected_level_breaks() -> None:
    router = StrategyFamilyRouter()

    decision = router.route(
        zone=_zone(zone_type="OB", dir_bias="support", width_atr=0.34, low=101.9, high=102.2, mid=102.05),
        context=_context(regime_label="trend", friction=0.09, jump_rate=0.04, v=0.8, last_price=102.3, atr5=1.0),
        reaction=AcceptanceRejectionResult(
            available=False,
            classification="not_applicable",
            rejection_score=0.0,
            acceptance_score=0.0,
            rejection_hard_count=0,
            acceptance_hard_count=0,
            mixed_reasons=[],
            input={},
        ),
        near_lp=False,
        zone_strength=84.0,
        confluence_score=79.0,
        regime_name="trend",
        candles_5m=_trend_candles(protected_break=True),
    )

    assert decision.available is False
    assert decision.family == "trend_continuation"
    assert decision.reason == "trend_continuation_protected_level_broken"


def test_router_marks_range_rotation_as_research_only_when_range_reversal_is_valid() -> None:
    router = StrategyFamilyRouter()

    decision = router.route(
        zone=_zone(zone_type="OB", dir_bias="support", width_atr=0.55, low=99.1, high=99.7, mid=99.4),
        context=_context(regime_label="range", friction=0.08, jump_rate=0.04, v=0.1, last_price=99.45, regime_15m=0.24),
        reaction=_reaction(classification="rejection_tentative", rejection_score=40.0, acceptance_score=20.0, outside_close_count=1, session_quality=0.9),
        near_lp=False,
        zone_strength=20.0,
        confluence_score=71.0,
        regime_name="range",
        candles_5m=_trend_candles(),
    )

    assert decision.available is False
    assert decision.family == "range_rotation"
    assert decision.reason == "range_rotation_research_only"
    assert decision.grade in {"A", "B", "C"}
    assert decision.time_stop_min_bars == 3
    assert decision.time_stop_max_bars == 3
    assert decision.scorecard["family"] == "range_rotation"
    assert decision.scorecard["buckets"]["location"] == round(
        decision.components["range_definition"] + decision.components["edge_proximity"], 2
    )
    assert decision.scorecard["buckets"]["invalidation"] == round(
        decision.components["range_width"] + decision.components["htf_conflict"], 2
    )


def test_router_blocks_range_rotation_when_candidate_is_in_range_center() -> None:
    router = StrategyFamilyRouter()

    decision = router.route(
        zone=_zone(zone_type="OB", dir_bias="support", width_atr=0.55, low=99.1, high=99.7, mid=99.4),
        context=_context(regime_label="range", friction=0.08, jump_rate=0.04, v=0.1, last_price=101.0, regime_15m=0.24),
        reaction=_reaction(classification="rejection_tentative", rejection_score=42.0, acceptance_score=18.0, outside_close_count=1, session_quality=0.9),
        near_lp=False,
        zone_strength=18.0,
        confluence_score=70.0,
        regime_name="range",
        candles_5m=_trend_candles(),
    )

    assert decision.available is False
    assert decision.family == "range_rotation"
    assert decision.reason == "range_rotation_range_center_block"
