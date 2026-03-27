from __future__ import annotations

from datetime import datetime, timezone

from app.core.enums import EntryModel
from app.db.models import Candle, Zone
from app.services.acceptance_rejection_classifier import AcceptanceRejectionResult
from app.services.context_engine import ContextSnapshot
from app.services.plan_generator import PlanGenerator
from app.services.strategy_family_router import StrategyFamilyDecision


def _base_zone(
    *,
    zone_id: str,
    zone_type: str,
    dir_bias: str,
    low: float,
    high: float,
    mid: float,
    stats: dict | None = None,
) -> Zone:
    return Zone(
        zone_id=zone_id,
        symbol="BTCUSDC",
        timeframe="15m",
        type=zone_type,
        low=low,
        high=high,
        mid=mid,
        width_atr=0.45,
        dir_bias=dir_bias,
        created_ts=datetime.now(timezone.utc),
        touch_count=1,
        base_strength=78.0,
        quality=76.0,
        state="active",
        stats=stats or {"p1r": 0.68, "p2r": 0.52, "p3r": 0.31, "sample_size": 80},
        strategy_version="v1",
    )


def _trend_candles() -> list[Candle]:
    base = datetime(2026, 3, 7, tzinfo=timezone.utc)
    rows = [
        (100.0, 100.8, 99.7, 100.7),
        (100.7, 101.7, 100.5, 101.6),
        (101.6, 102.8, 101.4, 102.6),
        (102.6, 103.7, 102.3, 103.5),
        (103.5, 103.6, 102.9, 103.1),
        (103.1, 103.2, 102.5, 102.8),
        (102.8, 102.9, 102.1, 102.4),
        (102.4, 102.8, 102.2, 102.7),
    ]
    candles: list[Candle] = []
    for index, (o, h, l, c) in enumerate(rows):
        candles.append(
            Candle(
                symbol="BTCUSDC",
                timeframe="5m",
                ts=base.replace(minute=index * 5),
                o=o,
                h=h,
                l=l,
                c=c,
                v=1_000.0,
                source="test",
                is_final=True,
            )
        )
    return candles


def test_hard_gate_blocks_counter_trend_in_strong_regime() -> None:
    generator = PlanGenerator()
    zones = [
        _base_zone(zone_id="z_counter", zone_type="OB", dir_bias="support", low=98.8, high=99.4, mid=99.1),
        _base_zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=101.7, high=102.3, mid=102.0),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.9,
        jump_rate_5m=0.06,
        friction_5m=0.18,
        atr5=0.5,
        atr15=1.0,
        sdir=-0.6,
        sevt=0.1,
        f=-0.5,
        v=-0.8,
        a=-0.4,
        vz=-1.1,
        az=-0.7,
        last_price=99.2,
    )

    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context)
    blocked_ids = {row.plan.zone_id for row in ranked}
    assert "z_counter" not in blocked_ids


def test_dedupe_keeps_single_plan_for_overlapping_entries() -> None:
    generator = PlanGenerator()
    zones = [
        _base_zone(zone_id="z_ob_a", zone_type="OB", dir_bias="support", low=98.7, high=99.3, mid=99.0),
        _base_zone(zone_id="z_ob_b", zone_type="OB", dir_bias="support", low=98.8, high=99.5, mid=99.15),
        _base_zone(zone_id="z_lp_near", zone_type="LP", dir_bias="support", low=98.7, high=98.9, mid=98.8, stats={}),
        _base_zone(zone_id="z_lp_target", zone_type="LP", dir_bias="resistance", low=101.8, high=102.2, mid=102.0, stats={}),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.55,
        jump_rate_5m=0.07,
        friction_5m=0.16,
        atr5=0.5,
        atr15=1.0,
        sdir=0.8,
        sevt=-0.2,
        f=0.7,
        v=1.0,
        a=0.6,
        vz=1.2,
        az=0.8,
        last_price=99.1,
    )

    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context)
    overlap_ids = {row.plan.zone_id for row in ranked if row.plan.zone_id in {"z_ob_a", "z_ob_b"}}
    assert len(overlap_ids) == 1


def test_shock_regime_forces_confirm_over_limit() -> None:
    generator = PlanGenerator()
    zones = [
        _base_zone(
            zone_id="z_quality_ob",
            zone_type="OB",
            dir_bias="support",
            low=98.9,
            high=99.1,
            mid=99.0,
            stats={"p1r": 0.72, "p2r": 0.56, "p3r": 0.34, "ev_r": 0.65, "sample_size": 120},
        ),
        _base_zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=101.7, high=102.1, mid=101.9, stats={}),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.78,
        jump_rate_5m=0.11,
        friction_5m=0.22,
        atr5=0.45,
        atr15=0.9,
        sdir=1.1,
        sevt=-0.1,
        f=0.8,
        v=1.2,
        a=0.5,
        vz=1.0,
        az=0.7,
        last_price=99.05,
        regime_label="shock",
    )

    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context)
    assert ranked
    assert ranked[0].plan.entry_model != "LIMIT"


def test_negative_ev_setup_is_auto_disabled() -> None:
    generator = PlanGenerator()
    zones = [
        _base_zone(
            zone_id="z_disabled",
            zone_type="OB",
            dir_bias="support",
            low=98.8,
            high=99.4,
            mid=99.1,
            stats={"p1r": 0.42, "p2r": 0.21, "p3r": 0.08, "ev_r": -0.18, "sample_size": 150},
        ),
        _base_zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=101.8, high=102.3, mid=102.0, stats={}),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.58,
        jump_rate_5m=0.08,
        friction_5m=0.18,
        atr5=0.5,
        atr15=1.0,
        sdir=0.7,
        sevt=-0.2,
        f=0.6,
        v=0.9,
        a=0.4,
        vz=0.9,
        az=0.6,
        last_price=99.2,
        regime_label="range",
    )

    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context)
    zone_ids = {row.plan.zone_id for row in ranked}
    assert "z_disabled" not in zone_ids


def test_transition_confirmed_blocks_all_candidates() -> None:
    generator = PlanGenerator()
    zones = [
        _base_zone(zone_id="z_transition", zone_type="OB", dir_bias="support", low=98.8, high=99.4, mid=99.1),
        _base_zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=101.7, high=102.3, mid=102.0),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.58,
        jump_rate_5m=0.10,
        friction_5m=0.21,
        atr5=0.5,
        atr15=1.0,
        sdir=0.05,
        sevt=0.02,
        f=0.01,
        v=-0.04,
        a=0.03,
        vz=0.1,
        az=0.1,
        last_price=99.0,
        regime_label="transition",
        transition_score=68.0,
        transition_state="transition_confirmed",
        transition_features={"bidirectional_sweep_churn": 1},
        transition_unlock_candidate=False,
        transition_lock_reason="transition_score_confirmed",
    )

    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context)
    assert ranked == []


def test_transition_watch_forces_confirm_only_and_logs_transition_fields() -> None:
    generator = PlanGenerator()
    zones = [
        _base_zone(
            zone_id="z_transition_watch",
            zone_type="OB",
            dir_bias="support",
            low=98.9,
            high=99.1,
            mid=99.0,
            stats={"p1r": 0.72, "p2r": 0.56, "p3r": 0.34, "ev_r": 0.60, "sample_size": 120},
        ),
        _base_zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=101.7, high=102.1, mid=101.9, stats={}),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.57,
        jump_rate_5m=0.08,
        friction_5m=0.16,
        atr5=0.45,
        atr15=0.9,
        sdir=0.9,
        sevt=-0.12,
        f=0.6,
        v=0.8,
        a=0.3,
        vz=0.8,
        az=0.5,
        last_price=99.02,
        regime_label="range",
        transition_score=44.0,
        transition_state="transition_watch",
        transition_features={"reaction_failure_cluster": 1},
        transition_unlock_candidate=False,
        transition_lock_reason="transition_score_watch",
    )

    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context)
    assert ranked
    validity = ranked[0].plan.validity
    assert ranked[0].plan.entry_model != "LIMIT"
    assert validity["transition_state"] == "transition_watch"
    assert validity["transition_score"] == 44.0


def test_mixed_classifier_blocks_candidate(monkeypatch) -> None:
    generator = PlanGenerator()
    zones = [
        _base_zone(zone_id="z_mixed", zone_type="OB", dir_bias="support", low=98.9, high=99.1, mid=99.0),
        _base_zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=101.8, high=102.2, mid=102.0, stats={}),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.55,
        jump_rate_5m=0.07,
        friction_5m=0.16,
        atr5=0.45,
        atr15=0.9,
        sdir=0.8,
        sevt=-0.1,
        f=0.6,
        v=0.9,
        a=0.3,
        vz=0.8,
        az=0.5,
        last_price=99.0,
        regime_label="range",
    )
    monkeypatch.setattr(
        generator.reaction_classifier,
        "classify_zone",
        lambda **kwargs: AcceptanceRejectionResult(
            available=True,
            classification="mixed",
            rejection_score=58.0,
            acceptance_score=57.0,
            rejection_hard_count=2,
            acceptance_hard_count=2,
            mixed_reasons=["conflicting_scores"],
            input={"reclaim_bars": 2},
        ),
    )

    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context)
    assert ranked == []


def test_rejection_tentative_forces_confirm_only(monkeypatch) -> None:
    generator = PlanGenerator()
    old_mode = generator.settings.strategy_mode
    generator.settings.strategy_mode = "A_PLUS_B"
    zones = [
        _base_zone(
            zone_id="z_reject_tentative",
            zone_type="OB",
            dir_bias="support",
            low=98.9,
            high=99.1,
            mid=99.0,
            stats={"p1r": 0.75, "p2r": 0.58, "p3r": 0.36, "ev_r": 0.62, "sample_size": 140},
        ),
        _base_zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=101.7, high=102.1, mid=101.9, stats={}),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.52,
        jump_rate_5m=0.05,
        friction_5m=0.10,
        atr5=0.45,
        atr15=0.9,
        sdir=0.9,
        sevt=-0.12,
        f=0.7,
        v=1.0,
        a=0.4,
        vz=0.9,
        az=0.6,
        last_price=99.01,
        regime_label="range",
    )
    monkeypatch.setattr(
        generator.reaction_classifier,
        "classify_zone",
        lambda **kwargs: AcceptanceRejectionResult(
            available=True,
            classification="rejection_tentative",
            rejection_score=67.0,
            acceptance_score=28.0,
            rejection_hard_count=2,
            acceptance_hard_count=1,
            mixed_reasons=[],
            input={
                "reclaim_bars": 2,
                "outside_close_count": 1,
                "dwell_time_bars": 1,
                "retest_hold": True,
                "inefficiency_created": True,
            },
        ),
    )

    try:
        ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context)
        assert ranked
        assert ranked[0].plan.entry_model == "CONFIRM"
        validity = ranked[0].plan.validity
        assert validity["reaction_classification"] == "rejection_tentative"
        assert validity["reaction_classifier_available"] is True
        assert validity["reaction_evidence"] == {
            "structure_shift_hint": "rejection_bias",
            "reclaim_speed_bucket": "moderate",
            "close_outside_bucket": "single",
            "retest_status": "held",
            "efficiency_state": "inefficiency_created",
        }
    finally:
        generator.settings.strategy_mode = old_mode


def test_sweep_reversal_strategy_family_fields_are_written(monkeypatch) -> None:
    generator = PlanGenerator()
    zones = [
        _base_zone(
            zone_id="z_sr",
            zone_type="OB",
            dir_bias="support",
            low=98.9,
            high=99.1,
            mid=99.0,
            stats={"p1r": 0.76, "p2r": 0.58, "p3r": 0.35, "ev_r": 0.68, "sample_size": 150},
        ),
        _base_zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=101.7, high=102.1, mid=101.9, stats={}),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.50,
        jump_rate_5m=0.04,
        friction_5m=0.08,
        atr5=0.45,
        atr15=0.9,
        sdir=0.8,
        sevt=-0.18,
        f=0.7,
        v=0.9,
        a=0.4,
        vz=0.9,
        az=0.6,
        last_price=99.01,
        regime_label="range",
    )
    monkeypatch.setattr(
        generator.reaction_classifier,
        "classify_zone",
        lambda **kwargs: AcceptanceRejectionResult(
            available=True,
            classification="rejection_confirmed",
            rejection_score=84.0,
            acceptance_score=18.0,
            rejection_hard_count=3,
            acceptance_hard_count=0,
            mixed_reasons=[],
            input={"outside_close_count": 0, "session_quality": 0.95},
        ),
    )
    monkeypatch.setattr(
        generator.strategy_family_router,
        "route",
        lambda **kwargs: StrategyFamilyDecision(
            available=True,
            family="sweep_reversal",
            grade="A",
            score=88.0,
            reason="sweep_reversal_sweep_confirm",
            entry_model=EntryModel.SWEEP_CONFIRM,
            components={"location": 18.0, "reaction_quality": 19.0},
            clean_case=False,
            confirm_only=False,
            split={"tp1": 0.4, "tp2": 0.4, "runner": 0.2},
            time_stop_min_bars=3,
            time_stop_max_bars=5,
            scorecard={
                "family": "sweep_reversal",
                "grade": "A",
                "score": 88.0,
                "buckets": {
                    "location": 28.0,
                    "liquidity": 20.0,
                    "reaction": 35.0,
                    "invalidation": 5.0,
                    "session": 0.0,
                    "trendline_bonus": 0.0,
                },
                "raw_components": {"location": 18.0, "reaction_quality": 19.0},
            },
        ),
    )

    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context)
    assert ranked
    plan = ranked[0].plan
    validity = plan.validity
    assert plan.entry_model == "SWEEP_CONFIRM"
    assert plan.split == {"tp1": 0.4, "tp2": 0.4, "runner": 0.2}
    assert validity["strategy_family"] == "sweep_reversal"
    assert validity["strategy_grade"] == "A"
    assert validity["strategy_family_score"] == 88.0
    assert validity["strategy_family_reason"] == "sweep_reversal_sweep_confirm"
    assert validity["strategy_family_time_stop_min_bars"] == 3
    assert validity["strategy_family_time_stop_max_bars"] == 5
    assert validity["strategy_scorecard"]["family"] == "sweep_reversal"
    assert validity["strategy_scorecard_buckets"]["trendline_bonus"] == 0.0
    assert validity["strategy_scorecard_raw_components"]["location"] == 18.0
    assert validity["strategy_scorecard_trendline_bonus"] == 0.0


def test_rejection_candidate_blocked_when_strategy_family_router_rejects(monkeypatch) -> None:
    generator = PlanGenerator()
    zones = [
        _base_zone(zone_id="z_sr_blocked", zone_type="OB", dir_bias="support", low=98.9, high=99.1, mid=99.0),
        _base_zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=101.7, high=102.1, mid=101.9, stats={}),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.78,
        jump_rate_5m=0.06,
        friction_5m=0.11,
        atr5=0.45,
        atr15=0.9,
        sdir=0.5,
        sevt=-0.08,
        f=0.4,
        v=-0.4,
        a=0.2,
        vz=0.5,
        az=0.3,
        last_price=99.02,
        regime_label="trend",
    )
    monkeypatch.setattr(
        generator.reaction_classifier,
        "classify_zone",
        lambda **kwargs: AcceptanceRejectionResult(
            available=True,
            classification="rejection_confirmed",
            rejection_score=81.0,
            acceptance_score=24.0,
            rejection_hard_count=3,
            acceptance_hard_count=0,
            mixed_reasons=[],
            input={"outside_close_count": 1, "session_quality": 0.9},
        ),
    )
    monkeypatch.setattr(
        generator.strategy_family_router,
        "route",
        lambda **kwargs: StrategyFamilyDecision(
            available=False,
            family="sweep_reversal",
            grade="B",
            score=79.0,
            reason="trend_requires_extreme_location",
            entry_model=None,
            components={"location": 8.0},
        ),
    )

    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context)
    assert ranked == []


def test_trend_continuation_strategy_family_fields_are_written(monkeypatch) -> None:
    generator = PlanGenerator()
    zones = [
        _base_zone(
            zone_id="z_tc",
            zone_type="OB",
            dir_bias="support",
            low=101.9,
            high=102.2,
            mid=102.05,
            stats={"p1r": 0.73, "p2r": 0.57, "p3r": 0.36, "ev_r": 0.64, "sample_size": 130},
        ),
        _base_zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=104.7, high=105.1, mid=104.9, stats={}),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.82,
        jump_rate_5m=0.05,
        friction_5m=0.09,
        atr5=0.45,
        atr15=0.9,
        sdir=0.9,
        sevt=-0.05,
        f=0.8,
        v=1.0,
        a=0.4,
        vz=0.9,
        az=0.5,
        last_price=102.6,
        regime_label="trend",
    )
    monkeypatch.setattr(
        generator.reaction_classifier,
        "classify_zone",
        lambda **kwargs: AcceptanceRejectionResult(
            available=False,
            classification="not_applicable",
            rejection_score=0.0,
            acceptance_score=0.0,
            rejection_hard_count=0,
            acceptance_hard_count=0,
            mixed_reasons=[],
            input={},
        ),
    )
    monkeypatch.setattr(
        generator.strategy_family_router,
        "route",
        lambda **kwargs: StrategyFamilyDecision(
            available=True,
            family="trend_continuation",
            grade="A",
            score=86.0,
            reason="trend_continuation_limit",
            entry_model=EntryModel.LIMIT,
            components={"htf_trend_clarity": 18.0, "impulse_quality": 19.0},
            clean_case=True,
            confirm_only=False,
            split={"tp1": 0.3, "tp2": 0.3, "runner": 0.4},
            time_stop_min_bars=5,
            time_stop_max_bars=8,
            scorecard={
                "family": "trend_continuation",
                "grade": "A",
                "score": 86.0,
                "buckets": {
                    "location": 32.0,
                    "liquidity": 10.0,
                    "reaction": 39.0,
                    "invalidation": 5.0,
                    "session": 0.0,
                    "trendline_bonus": 0.0,
                },
                "raw_components": {"htf_trend_clarity": 18.0, "impulse_quality": 19.0},
            },
        ),
    )

    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context, candles_5m=_trend_candles())
    assert ranked
    plan = ranked[0].plan
    validity = plan.validity
    assert plan.entry_model == "LIMIT"
    assert plan.split == {"tp1": 0.3, "tp2": 0.3, "runner": 0.4}
    assert validity["strategy_family"] == "trend_continuation"
    assert validity["strategy_grade"] == "A"
    assert validity["strategy_family_reason"] == "trend_continuation_limit"
    assert validity["strategy_family_time_stop_min_bars"] == 5
    assert validity["strategy_family_time_stop_max_bars"] == 8
    assert validity["strategy_scorecard"]["family"] == "trend_continuation"
    assert validity["strategy_scorecard_buckets"]["trendline_bonus"] == 0.0
    assert validity["strategy_scorecard_raw_components"]["htf_trend_clarity"] == 18.0
    assert validity["strategy_scorecard_trendline_bonus"] == 0.0


def test_legacy_plan_preserves_router_reason_when_family_is_none(monkeypatch) -> None:
    generator = PlanGenerator()
    zones = [
        _base_zone(zone_id="z_legacy_reason", zone_type="OB", dir_bias="support", low=98.9, high=99.1, mid=99.0),
        _base_zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=101.7, high=102.1, mid=101.9, stats={}),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.48,
        jump_rate_5m=0.06,
        friction_5m=0.10,
        atr5=0.45,
        atr15=0.9,
        sdir=0.2,
        sevt=-0.05,
        f=0.1,
        v=0.15,
        a=0.04,
        vz=0.2,
        az=0.1,
        last_price=99.02,
        regime_label="range",
    )
    monkeypatch.setattr(
        generator.reaction_classifier,
        "classify_zone",
        lambda **kwargs: AcceptanceRejectionResult(
            available=False,
            classification="not_applicable",
            rejection_score=0.0,
            acceptance_score=0.0,
            rejection_hard_count=0,
            acceptance_hard_count=0,
            mixed_reasons=[],
            input={},
        ),
    )
    monkeypatch.setattr(
        generator.strategy_family_router,
        "route",
        lambda **kwargs: StrategyFamilyDecision(
            available=False,
            family="none",
            grade="F",
            score=0.0,
            reason="trend_continuation_not_applicable",
            entry_model=None,
        ),
    )
    monkeypatch.setattr(
        generator,
        "_meta_filter",
        lambda **kwargs: (True, 60.0, 40.0, "pass"),
    )
    monkeypatch.setattr(
        generator,
        "_generic_setup_block_reason",
        lambda **kwargs: None,
    )

    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context, candles_5m=_trend_candles())
    assert ranked
    validity = dict(ranked[0].plan.validity or {})
    assert validity["strategy_family"] == "legacy_zone_plan"
    assert validity["strategy_family_reason"] == "trend_continuation_not_applicable"


def test_generation_diagnostics_reports_low_confluence_hard_gate(monkeypatch) -> None:
    generator = PlanGenerator()
    zones = [
        _base_zone(zone_id="z_diag_1", zone_type="LP", dir_bias="support", low=98.9, high=99.1, mid=99.0),
        _base_zone(zone_id="z_diag_2", zone_type="OB", dir_bias="resistance", low=100.9, high=101.1, mid=101.0),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.72,
        jump_rate_5m=0.04,
        friction_5m=0.10,
        atr5=0.45,
        atr15=0.9,
        sdir=0.1,
        sevt=0.0,
        f=0.1,
        v=0.12,
        a=0.03,
        vz=0.2,
        az=0.1,
        last_price=100.0,
        regime_label="transition",
        transition_score=64.0,
        transition_state="transition_confirmed",
        transition_lock_reason="transition_hard_override_state_disagreement",
    )
    monkeypatch.setattr(
        generator,
        "_confluence_score",
        lambda *args, **kwargs: (55.0, {}, {}, {}, 1.0),
    )

    payload = generator.generation_diagnostics(symbol="BTCUSDC", zones=zones, context=context, candles_5m=_trend_candles())

    assert payload["generation_state"] == "diagnosed"
    assert payload["regime_profile"] == "transition"
    assert payload["active_zone_count"] == 2
    assert payload["post_hard_gate_zone_count"] == 0
    assert payload["pre_generation_candidate_count"] == 0
    assert payload["hard_gate_block_counts"] == {"low_confluence": 2}
    assert payload["block_examples"][0]["stage"] == "hard_gate"
    assert payload["block_examples"][0]["reason"] == "low_confluence"


def test_range_rotation_research_only_candidate_is_blocked(monkeypatch) -> None:
    generator = PlanGenerator()
    zones = [
        _base_zone(zone_id="z_rr", zone_type="OB", dir_bias="support", low=99.1, high=99.7, mid=99.4),
        _base_zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=101.7, high=102.1, mid=101.9, stats={}),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.34,
        jump_rate_5m=0.04,
        friction_5m=0.08,
        atr5=0.45,
        atr15=0.9,
        sdir=0.05,
        sevt=-0.06,
        f=0.02,
        v=0.08,
        a=0.03,
        vz=0.1,
        az=0.1,
        last_price=99.42,
        regime_label="range",
    )
    monkeypatch.setattr(
        generator.reaction_classifier,
        "classify_zone",
        lambda **kwargs: AcceptanceRejectionResult(
            available=True,
            classification="rejection_tentative",
            rejection_score=64.0,
            acceptance_score=21.0,
            rejection_hard_count=2,
            acceptance_hard_count=0,
            mixed_reasons=[],
            input={"outside_close_count": 1, "session_quality": 0.92},
        ),
    )
    monkeypatch.setattr(
        generator.strategy_family_router,
        "route",
        lambda **kwargs: StrategyFamilyDecision(
            available=False,
            family="range_rotation",
            grade="A",
            score=85.0,
            reason="range_rotation_research_only",
            entry_model=None,
            components={"range_definition": 18.0, "edge_proximity": 20.0},
            clean_case=False,
            confirm_only=True,
            split={"tp1": 0.5, "tp2": 0.5, "runner": 0.0},
            time_stop_min_bars=3,
            time_stop_max_bars=3,
        ),
    )

    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context, candles_5m=_trend_candles())
    assert ranked == []


def test_ob_only_candidate_is_blocked_when_no_family_or_liquidity_event(monkeypatch) -> None:
    generator = PlanGenerator()
    zones = [
        _base_zone(zone_id="z_ob_only", zone_type="OB", dir_bias="support", low=98.9, high=99.1, mid=99.0),
        _base_zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=101.7, high=102.1, mid=101.9, stats={}),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.44,
        jump_rate_5m=0.05,
        friction_5m=0.10,
        atr5=0.45,
        atr15=0.9,
        sdir=0.25,
        sevt=-0.02,
        f=0.2,
        v=0.25,
        a=0.08,
        vz=0.2,
        az=0.1,
        last_price=99.0,
        regime_label="range",
    )
    monkeypatch.setattr(
        generator.reaction_classifier,
        "classify_zone",
        lambda **kwargs: AcceptanceRejectionResult(
            available=False,
            classification="not_applicable",
            rejection_score=0.0,
            acceptance_score=0.0,
            rejection_hard_count=0,
            acceptance_hard_count=0,
            mixed_reasons=[],
            input={},
        ),
    )

    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context, candles_5m=_trend_candles())
    assert ranked == []


def test_fvg_only_candidate_is_blocked_when_no_family_or_liquidity_event(monkeypatch) -> None:
    generator = PlanGenerator()
    zones = [
        _base_zone(zone_id="z_fvg_only", zone_type="FVG", dir_bias="support", low=98.9, high=99.1, mid=99.0),
        _base_zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=101.7, high=102.1, mid=101.9, stats={}),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.46,
        jump_rate_5m=0.05,
        friction_5m=0.10,
        atr5=0.45,
        atr15=0.9,
        sdir=0.22,
        sevt=-0.01,
        f=0.18,
        v=0.22,
        a=0.07,
        vz=0.2,
        az=0.1,
        last_price=99.0,
        regime_label="range",
    )
    monkeypatch.setattr(
        generator.reaction_classifier,
        "classify_zone",
        lambda **kwargs: AcceptanceRejectionResult(
            available=False,
            classification="not_applicable",
            rejection_score=0.0,
            acceptance_score=0.0,
            rejection_hard_count=0,
            acceptance_hard_count=0,
            mixed_reasons=[],
            input={},
        ),
    )

    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context, candles_5m=_trend_candles())
    assert ranked == []


def test_trendline_led_generic_candidate_is_blocked(monkeypatch) -> None:
    generator = PlanGenerator()
    zones = [
        _base_zone(zone_id="z_trendline_led", zone_type="FLIP", dir_bias="support", low=98.9, high=99.1, mid=99.0),
        _base_zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=101.7, high=102.1, mid=101.9, stats={}),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.61,
        jump_rate_5m=0.04,
        friction_5m=0.08,
        atr5=0.45,
        atr15=0.9,
        sdir=0.7,
        sevt=0.01,
        f=0.5,
        v=0.95,
        a=0.12,
        vz=0.7,
        az=0.2,
        last_price=99.02,
        regime_label="range",
    )
    monkeypatch.setattr(
        generator.reaction_classifier,
        "classify_zone",
        lambda **kwargs: AcceptanceRejectionResult(
            available=False,
            classification="not_applicable",
            rejection_score=0.0,
            acceptance_score=0.0,
            rejection_hard_count=0,
            acceptance_hard_count=0,
            mixed_reasons=[],
            input={},
        ),
    )

    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context, candles_5m=_trend_candles())
    assert ranked == []


def test_generated_plan_logs_thesis_fingerprint_fields(monkeypatch) -> None:
    generator = PlanGenerator()
    zones = [
        _base_zone(
            zone_id="z_thesis",
            zone_type="OB",
            dir_bias="support",
            low=101.9,
            high=102.2,
            mid=102.05,
            stats={"p1r": 0.73, "p2r": 0.57, "p3r": 0.36, "ev_r": 0.64, "sample_size": 130},
        ),
        _base_zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=104.7, high=105.1, mid=104.9, stats={}),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.82,
        jump_rate_5m=0.05,
        friction_5m=0.09,
        atr5=0.45,
        atr15=0.9,
        sdir=0.9,
        sevt=-0.05,
        f=0.8,
        v=1.0,
        a=0.4,
        vz=0.9,
        az=0.5,
        last_price=102.6,
        regime_label="trend",
    )
    monkeypatch.setattr(
        generator.reaction_classifier,
        "classify_zone",
        lambda **kwargs: AcceptanceRejectionResult(
            available=False,
            classification="not_applicable",
            rejection_score=0.0,
            acceptance_score=0.0,
            rejection_hard_count=0,
            acceptance_hard_count=0,
            mixed_reasons=[],
            input={},
        ),
    )
    monkeypatch.setattr(
        generator.strategy_family_router,
        "route",
        lambda **kwargs: StrategyFamilyDecision(
            available=True,
            family="trend_continuation",
            grade="A",
            score=86.0,
            reason="trend_continuation_limit",
            entry_model=EntryModel.LIMIT,
            components={"htf_trend_clarity": 18.0, "impulse_quality": 19.0},
            clean_case=True,
            confirm_only=False,
            split={"tp1": 0.3, "tp2": 0.3, "runner": 0.4},
            time_stop_min_bars=5,
            time_stop_max_bars=8,
        ),
    )

    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context, candles_5m=_trend_candles())

    assert ranked
    validity = ranked[0].plan.validity
    fingerprint = validity["thesis_fingerprint"]
    assert fingerprint["direction"] == "long"
    assert fingerprint["strategy_family"] == "trend_continuation"
    assert validity["thesis_cluster_id"]
    assert validity["thesis_cluster_size"] == 1
    assert validity["thesis_primary_symbol"] == "BTCUSDC"
    assert validity["thesis_rejected_reason"] is None


def test_a_only_mode_blocks_b_grade_candidates(monkeypatch) -> None:
    generator = PlanGenerator()
    old_mode = generator.settings.strategy_mode
    generator.settings.strategy_mode = "A_ONLY"
    zones = [
        _base_zone(
            zone_id="z_mode_b",
            zone_type="OB",
            dir_bias="support",
            low=101.9,
            high=102.2,
            mid=102.05,
            stats={"p1r": 0.73, "p2r": 0.57, "p3r": 0.36, "ev_r": 0.64, "sample_size": 130},
        ),
        _base_zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=104.7, high=105.1, mid=104.9, stats={}),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.82,
        jump_rate_5m=0.05,
        friction_5m=0.09,
        atr5=0.45,
        atr15=0.9,
        sdir=0.9,
        sevt=-0.05,
        f=0.8,
        v=1.0,
        a=0.4,
        vz=0.9,
        az=0.5,
        last_price=102.6,
        regime_label="trend",
    )
    monkeypatch.setattr(
        generator.reaction_classifier,
        "classify_zone",
        lambda **kwargs: AcceptanceRejectionResult(
            available=False,
            classification="not_applicable",
            rejection_score=0.0,
            acceptance_score=0.0,
            rejection_hard_count=0,
            acceptance_hard_count=0,
            mixed_reasons=[],
            input={},
        ),
    )
    monkeypatch.setattr(
        generator.strategy_family_router,
        "route",
        lambda **kwargs: StrategyFamilyDecision(
            available=True,
            family="trend_continuation",
            grade="B",
            score=78.0,
            reason="trend_continuation_confirm_only",
            entry_model=EntryModel.CONFIRM,
            components={"htf_trend_clarity": 15.0, "impulse_quality": 16.0},
            clean_case=False,
            confirm_only=True,
            split={"tp1": 0.3, "tp2": 0.3, "runner": 0.4},
            time_stop_min_bars=5,
            time_stop_max_bars=8,
        ),
    )
    try:
        ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context, candles_5m=_trend_candles())
        assert ranked == []
    finally:
        generator.settings.strategy_mode = old_mode


def test_research_mode_keeps_plan_but_zeroes_recommended_risk(monkeypatch) -> None:
    generator = PlanGenerator()
    old_mode = generator.settings.strategy_mode
    generator.settings.strategy_mode = "RESEARCH"
    zones = [
        _base_zone(
            zone_id="z_mode_research",
            zone_type="OB",
            dir_bias="support",
            low=101.9,
            high=102.2,
            mid=102.05,
            stats={"p1r": 0.73, "p2r": 0.57, "p3r": 0.36, "ev_r": 0.64, "sample_size": 130},
        ),
        _base_zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=104.7, high=105.1, mid=104.9, stats={}),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.82,
        jump_rate_5m=0.05,
        friction_5m=0.09,
        atr5=0.45,
        atr15=0.9,
        sdir=0.9,
        sevt=-0.05,
        f=0.8,
        v=1.0,
        a=0.4,
        vz=0.9,
        az=0.5,
        last_price=102.6,
        regime_label="trend",
    )
    monkeypatch.setattr(
        generator.reaction_classifier,
        "classify_zone",
        lambda **kwargs: AcceptanceRejectionResult(
            available=False,
            classification="not_applicable",
            rejection_score=0.0,
            acceptance_score=0.0,
            rejection_hard_count=0,
            acceptance_hard_count=0,
            mixed_reasons=[],
            input={},
        ),
    )
    monkeypatch.setattr(
        generator.strategy_family_router,
        "route",
        lambda **kwargs: StrategyFamilyDecision(
            available=True,
            family="trend_continuation",
            grade="C",
            score=71.0,
            reason="trend_continuation_confirm_only",
            entry_model=EntryModel.CONFIRM,
            components={"htf_trend_clarity": 14.0, "impulse_quality": 15.0},
            clean_case=False,
            confirm_only=True,
            split={"tp1": 0.3, "tp2": 0.3, "runner": 0.4},
            time_stop_min_bars=5,
            time_stop_max_bars=8,
        ),
    )
    try:
        ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context, candles_5m=_trend_candles())
        assert ranked
        validity = ranked[0].plan.validity
        assert validity["strategy_mode"] == "RESEARCH"
        assert validity["mode_shadow_only"] is True
        assert validity["recommended_risk_r"] == 0.0
        assert validity["strategy_sizing"]["blocked_reason"] == "mode_shadow_only"
    finally:
        generator.settings.strategy_mode = old_mode
