from __future__ import annotations

from datetime import datetime, timezone

from app.core.enums import Direction
from app.db.models import Zone
from app.services.context_engine import ContextSnapshot
from app.services.nanyotti_method_view import NanyottiMethodViewService
from app.services.plan_generator import PlanGenerator


def _zone(
    *,
    zone_id: str = "z_method",
    zone_type: str = "OB",
    dir_bias: str = "support",
    low: float = 99.6,
    high: float = 100.0,
    mid: float = 99.8,
    width_atr: float = 0.40,
    quality: float = 80.0,
    base_strength: float = 80.0,
) -> Zone:
    return Zone(
        zone_id=zone_id,
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
        base_strength=base_strength,
        quality=quality,
        state="active",
        stats={"p1r": 0.68, "p2r": 0.54, "p3r": 0.32, "sample_size": 80},
        strategy_version="v1",
    )


def _context(
    *,
    regime_label: str = "trend",
    regime_15m: float = 0.78,
    jump_rate_5m: float = 0.05,
    friction_5m: float = 0.16,
    sdir: float = 0.72,
    f: float = 0.58,
    v: float = 0.86,
    vz: float = 0.90,
    az: float = 0.45,
    last_price: float = 99.9,
    transition_state: str = "none",
) -> ContextSnapshot:
    return ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=regime_15m,
        jump_rate_5m=jump_rate_5m,
        friction_5m=friction_5m,
        atr5=0.45,
        atr15=1.0,
        sdir=sdir,
        sevt=-0.12,
        f=f,
        v=v,
        a=0.24,
        vz=vz,
        az=az,
        last_price=last_price,
        regime_label=regime_label,
        transition_state=transition_state,
    )


def test_nanyotti_view_allows_base_for_trend_pullback_with_good_repair_capacity() -> None:
    view = NanyottiMethodViewService.evaluate(
        context=_context(),
        zone=_zone(),
        direction=Direction.LONG,
        entry_price=99.8,
        sl=99.45,
        strategy_family="trend_continuation",
        strategy_grade="A",
        reaction_classification="not_applicable",
        runtime_signal_telemetry={"risk_atr": 0.35, "entry_offset_atr": 0.10},
        location_reference={"edge_proximity_atr": 0.20},
        regime_label="trend",
    )

    assert view["authority"] == "shadow_advisory_only"
    assert view["primary_bias"] == "long"
    assert view["side_alignment"] == "with_trend"
    assert view["rotation_role"] == "trend_pullback"
    assert view["entry_quality"] == "A"
    assert view["position_management_bias"] == "base_allowed"
    assert view["battle_permission"] == "battle_candidate"
    assert view["market_state"]["side_alignment"] == "with_trend"
    assert view["scenario_plan"]["stage"] == "battle_candidate"
    assert view["repair_decision"]["repair_action"] == "repairable_hold_or_reduce_battle_on_reaction"
    assert view["execution_policy"]["max_risk_multiplier"] == 1.0
    assert view["switch_policy"]["automatic_reverse_after_exit"] is False
    assert view["no_trade_reasons"] == []


def test_nanyotti_view_blocks_countertrend_battle_in_one_way_market() -> None:
    view = NanyottiMethodViewService.evaluate(
        context=_context(regime_15m=0.90, v=1.05, sdir=0.92, f=0.82, vz=1.60),
        zone=_zone(zone_type="LP", dir_bias="resistance", low=101.8, high=102.2, mid=102.0),
        direction=Direction.SHORT,
        entry_price=102.0,
        sl=102.45,
        strategy_family="sweep_reversal",
        strategy_grade="B",
        reaction_classification="rejection_tentative",
        runtime_signal_telemetry={"risk_atr": 0.45, "entry_offset_atr": 0.25},
        location_reference={"edge_proximity_atr": 0.20},
        regime_label="trend",
    )

    assert view["primary_bias"] == "long"
    assert view["side_alignment"] == "against_trend"
    assert view["one_way_risk"] == "high"
    assert view["rotation_role"] == "one_way_risk"
    assert view["entry_quality"] == "NO_TRADE"
    assert view["position_management_bias"] == "reduce_only"
    assert view["battle_permission"] == "battle_forbidden"
    assert view["scenario_plan"]["stage"] == "watch"
    assert view["execution_policy"]["max_risk_multiplier"] == 0.0
    assert "one_way_opposite_switch_forbidden" in view["switch_policy"]["switch_blockers"]
    assert "one_way_against_trade" in view["no_trade_reasons"]


def test_nanyotti_view_marks_late_wide_risk_as_bad_rr_no_trade() -> None:
    view = NanyottiMethodViewService.evaluate(
        context=_context(
            regime_label="transition",
            regime_15m=0.52,
            jump_rate_5m=0.22,
            friction_5m=0.50,
            transition_state="transition_watch",
            last_price=101.6,
        ),
        zone=_zone(low=99.1, high=100.4, mid=99.75, width_atr=1.30),
        direction=Direction.LONG,
        entry_price=99.75,
        sl=98.35,
        strategy_family="legacy_zone_plan",
        strategy_grade="C",
        reaction_classification="not_applicable",
        runtime_signal_telemetry={"risk_atr": 1.40, "entry_offset_atr": 1.85, "directional_close_vs_ema_fast_atr": 0.90},
        location_reference={"edge_proximity_atr": 0.65},
        regime_label="transition",
    )

    assert view["bad_rr_state"] == "bad_rr"
    assert view["rotation_role"] == "bad_rr_watch"
    assert view["entry_quality"] == "NO_TRADE"
    assert view["size_bias"] == "observe"
    assert view["repair_decision"]["new_add_allowed"] is False
    assert view["inventory_state"]["available"] is False
    assert view["execution_policy"]["risk_lane"] == "blocked"
    assert "bad_rr_or_chase" in view["no_trade_reasons"]
    assert "unstable_transition_or_shock" in view["no_trade_reasons"]


def test_nanyotti_sizing_overlay_is_shadow_by_default() -> None:
    view = NanyottiMethodViewService.evaluate(
        context=_context(regime_15m=0.90, v=1.05, sdir=0.92, f=0.82, vz=1.60),
        zone=_zone(zone_type="LP", dir_bias="resistance", low=101.8, high=102.2, mid=102.0),
        direction=Direction.SHORT,
        entry_price=102.0,
        sl=102.45,
        strategy_family="sweep_reversal",
        strategy_grade="B",
        reaction_classification="rejection_tentative",
        runtime_signal_telemetry={"risk_atr": 0.45, "entry_offset_atr": 0.25},
        location_reference={"edge_proximity_atr": 0.20},
        regime_label="trend",
    )

    overlay = NanyottiMethodViewService.build_sizing_overlay(
        method_view=view,
        base_recommended_risk_r=0.5,
        expected_ev_r=0.4,
        apply_live=False,
    )

    assert overlay["authority"] == "shadow_advisory_only"
    assert overlay["base_recommended_risk_r"] == 0.5
    assert overlay["shadow_recommended_risk_r"] == 0.0
    assert overlay["live_recommended_risk_r"] == 0.5
    assert overlay["shadow_blocked"] is True


def test_plan_generator_attaches_nanyotti_method_view_to_validity() -> None:
    generator = PlanGenerator()
    ranked = generator.generate(
        symbol="BTCUSDC",
        zones=[
            _zone(zone_id="z_support", zone_type="OB", dir_bias="support", low=98.8, high=99.2, mid=99.0),
            _zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=101.8, high=102.2, mid=102.0),
        ],
        context=_context(regime_label="range", regime_15m=0.55, v=0.70, sdir=0.42, f=0.30, last_price=99.1),
    )

    assert ranked
    view = ranked[0].plan.validity["nanyotti_method_view"]
    assert view["available"] is True
    assert view["source"] == "telegram_messages_as_pattern_sample_not_signal"
    assert view["authority"] == "shadow_advisory_only"
    assert "switch_side_is_not_automatic_after_exit" in view["method_rules"]
    overlay = ranked[0].plan.validity["nanyotti_method_sizing_overlay"]
    strategy_overlay = ranked[0].plan.validity["strategy_sizing"]["nanyotti_method_sizing_overlay"]
    assert overlay["apply_live"] is False
    assert strategy_overlay["policy"] == "nanyotti_rotation_method_sizing_overlay_v1"
