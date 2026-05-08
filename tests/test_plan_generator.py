from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import Zone
from app.services.context_engine import ContextSnapshot
from app.services.plan_generator import PlanGenerator


def test_plan_generator_builds_positive_ev_plan() -> None:
    now = datetime.now(timezone.utc)
    zones = [
        Zone(
            zone_id="z_support",
            symbol="BTCUSDC",
            timeframe="15m",
            type="OB",
            low=98.0,
            high=100.0,
            mid=99.0,
            width_atr=0.4,
            dir_bias="support",
            created_ts=now,
            touch_count=1,
            base_strength=80.0,
            quality=78.0,
            state="active",
            stats={"p1r": 0.7, "p2r": 0.5, "p3r": 0.3},
            strategy_version="v1",
        ),
        Zone(
            zone_id="z_resist",
            symbol="BTCUSDC",
            timeframe="15m",
            type="LP",
            low=101.5,
            high=102.5,
            mid=102.0,
            width_atr=0.3,
            dir_bias="resistance",
            created_ts=now,
            touch_count=0,
            base_strength=65.0,
            quality=64.0,
            state="active",
            stats={},
            strategy_version="v1",
        ),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.45,
        jump_rate_5m=0.08,
        friction_5m=0.2,
        atr5=0.5,
        atr15=1.0,
        sdir=0.1,
        sevt=-0.1,
        f=0.1,
        v=0.2,
        a=0.05,
        vz=0.1,
        az=0.05,
        last_price=99.2,
    )

    generator = PlanGenerator()
    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context)

    assert ranked
    assert ranked[0].plan.ev > 0
    assert ranked[0].plan.rr_min >= 1.2
    validity = dict(ranked[0].plan.validity or {})
    assert "expected_win_prob" in validity
    assert "expected_ev_r" in validity
    assert "expected_tp2_prob" in validity
    assert "expected_summary" in validity


def test_plan_generator_attaches_runtime_signal_telemetry() -> None:
    now = datetime.now(timezone.utc)
    zones = [
        Zone(
            zone_id="z_support_runtime_telemetry",
            symbol="BTCUSDC",
            timeframe="15m",
            type="OB",
            low=98.0,
            high=100.0,
            mid=99.0,
            width_atr=0.4,
            dir_bias="support",
            created_ts=now,
            touch_count=1,
            base_strength=80.0,
            quality=78.0,
            state="active",
            stats={"p1r": 0.7, "p2r": 0.5, "p3r": 0.3},
            strategy_version="v1",
        ),
        Zone(
            zone_id="z_resist_runtime_telemetry",
            symbol="BTCUSDC",
            timeframe="15m",
            type="LP",
            low=101.5,
            high=102.5,
            mid=102.0,
            width_atr=0.3,
            dir_bias="resistance",
            created_ts=now,
            touch_count=0,
            base_strength=65.0,
            quality=64.0,
            state="active",
            stats={},
            strategy_version="v1",
        ),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.45,
        jump_rate_5m=0.08,
        friction_5m=0.2,
        atr5=0.5,
        atr15=1.0,
        sdir=0.1,
        sevt=-0.1,
        f=0.1,
        v=0.2,
        a=0.05,
        vz=0.1,
        az=0.05,
        last_price=99.2,
        signal_telemetry={
            "telemetry_source": "context_snapshot",
            "telemetry_version": "v1",
            "prior_window_bars": 24,
            "close_position": 0.74,
            "body_fraction": 0.38,
            "range_atr": 0.92,
            "body_atr": 0.35,
            "prior_range_atr": 2.1,
            "ema_spread_atr": 0.44,
            "close_vs_ema_fast_atr": 0.28,
            "long_sweep_distance_atr": 0.17,
            "short_sweep_distance_atr": 0.03,
            "long_reclaim_distance_atr": 0.41,
            "short_reclaim_distance_atr": 0.06,
        },
    )

    generator = PlanGenerator()
    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context)

    assert ranked
    runtime_signal_telemetry = dict((ranked[0].plan.validity or {}).get("runtime_signal_telemetry") or {})
    assert runtime_signal_telemetry["signal_family"] == "legacy_zone_plan"
    assert runtime_signal_telemetry["direction"] == "long"
    assert runtime_signal_telemetry["close_position"] == 0.74
    assert runtime_signal_telemetry["directional_close_position"] == 0.74
    assert runtime_signal_telemetry["sweep_distance_atr"] == 0.17
    assert runtime_signal_telemetry["reclaim_distance_atr"] == 0.41
    assert runtime_signal_telemetry["directional_close_vs_ema_fast_atr"] == 0.28
    assert "entry_offset_r" in runtime_signal_telemetry
    assert runtime_signal_telemetry["edge_proximity_atr"] >= 0.0


def test_plan_generator_differentiates_expected_win_prob_for_weaker_context() -> None:
    now = datetime.now(timezone.utc)
    zones = [
        Zone(
            zone_id="z_support_expect",
            symbol="BTCUSDC",
            timeframe="15m",
            type="OB",
            low=98.0,
            high=100.0,
            mid=99.0,
            width_atr=0.4,
            dir_bias="support",
            created_ts=now,
            touch_count=1,
            base_strength=84.0,
            quality=82.0,
            state="active",
            stats={},
            strategy_version="v1",
        ),
        Zone(
            zone_id="z_resist_expect",
            symbol="BTCUSDC",
            timeframe="15m",
            type="LP",
            low=101.5,
            high=102.5,
            mid=102.0,
            width_atr=0.3,
            dir_bias="resistance",
            created_ts=now,
            touch_count=0,
            base_strength=65.0,
            quality=64.0,
            state="active",
            stats={},
            strategy_version="v1",
        ),
    ]
    good = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.45,
        jump_rate_5m=0.05,
        friction_5m=0.08,
        atr5=0.5,
        atr15=1.0,
        sdir=0.2,
        sevt=-0.2,
        f=0.1,
        v=0.22,
        a=0.06,
        vz=0.15,
        az=0.08,
        last_price=99.1,
    )
    weak = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.45,
        jump_rate_5m=0.05,
        friction_5m=0.55,
        atr5=0.5,
        atr15=1.0,
        sdir=0.02,
        sevt=0.1,
        f=0.0,
        v=-0.05,
        a=-0.02,
        vz=0.01,
        az=-0.01,
        last_price=99.7,
        transition_state="transition_watch",
        transition_lock_reason="transition_watch",
    )

    generator = PlanGenerator()
    ranked_good = generator.generate(symbol="BTCUSDC", zones=zones, context=good)
    ranked_weak = generator.generate(symbol="BTCUSDC", zones=zones, context=weak)

    assert ranked_good
    assert ranked_weak

    good_validity = dict(ranked_good[0].plan.validity or {})
    weak_validity = dict(ranked_weak[0].plan.validity or {})

    assert good_validity["expected_win_prob"] > weak_validity["expected_win_prob"]
    assert good_validity["expected_tp2_prob"] > weak_validity["expected_tp2_prob"]
    assert good_validity["expected_win_prob_adjustment"] > weak_validity["expected_win_prob_adjustment"]


def test_plan_generator_blocks_stale_zone_for_scalp() -> None:
    now = datetime(2026, 3, 9, 9, 0, tzinfo=timezone.utc)
    zones = [
        Zone(
            zone_id="z_old_support",
            symbol="BTCUSDC",
            timeframe="15m",
            type="OB",
            low=98.0,
            high=100.0,
            mid=99.0,
            width_atr=0.4,
            dir_bias="support",
            created_ts=now - timedelta(hours=30),
            touch_count=1,
            base_strength=80.0,
            quality=78.0,
            state="active",
            stats={"p1r": 0.7, "p2r": 0.5, "p3r": 0.3},
            strategy_version="v1",
        ),
        Zone(
            zone_id="z_target_support_old",
            symbol="BTCUSDC",
            timeframe="15m",
            type="LP",
            low=101.5,
            high=102.5,
            mid=102.0,
            width_atr=0.3,
            dir_bias="resistance",
            created_ts=now,
            touch_count=0,
            base_strength=65.0,
            quality=64.0,
            state="active",
            stats={},
            strategy_version="v1",
        ),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.45,
        jump_rate_5m=0.08,
        friction_5m=0.2,
        atr5=0.5,
        atr15=1.0,
        sdir=0.1,
        sevt=-0.1,
        f=0.1,
        v=0.2,
        a=0.05,
        vz=0.1,
        az=0.05,
        last_price=99.2,
    )

    generator = PlanGenerator()
    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context, now=now)

    zone_ids = {row.plan.zone_id for row in ranked}
    assert "z_old_support" not in zone_ids


def test_plan_generator_shortens_plan_validity_for_scalp() -> None:
    now = datetime(2026, 3, 9, 9, 0, tzinfo=timezone.utc)
    zones = [
        Zone(
            zone_id="z_support_short_validity",
            symbol="BTCUSDC",
            timeframe="15m",
            type="OB",
            low=98.0,
            high=100.0,
            mid=99.0,
            width_atr=0.4,
            dir_bias="support",
            created_ts=now,
            touch_count=1,
            base_strength=80.0,
            quality=78.0,
            state="active",
            stats={"p1r": 0.7, "p2r": 0.5, "p3r": 0.3},
            strategy_version="v1",
        ),
        Zone(
            zone_id="z_resist_short_validity",
            symbol="BTCUSDC",
            timeframe="15m",
            type="LP",
            low=101.5,
            high=102.5,
            mid=102.0,
            width_atr=0.3,
            dir_bias="resistance",
            created_ts=now,
            touch_count=0,
            base_strength=65.0,
            quality=64.0,
            state="active",
            stats={},
            strategy_version="v1",
        ),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.45,
        jump_rate_5m=0.08,
        friction_5m=0.2,
        atr5=0.5,
        atr15=1.0,
        sdir=0.1,
        sevt=-0.1,
        f=0.1,
        v=0.2,
        a=0.05,
        vz=0.1,
        az=0.05,
        last_price=99.2,
    )

    generator = PlanGenerator()
    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context, now=now)

    assert ranked
    plan = ranked[0].plan
    assert (plan.valid_until - plan.valid_from) <= timedelta(minutes=90)
    assert dict(plan.validity or {})["plan_validity_minutes"] <= 90


def test_plan_generator_applies_dead_session_penalty() -> None:
    zone_now = datetime(2026, 3, 9, 8, 0, tzinfo=timezone.utc)
    zones = [
        Zone(
            zone_id="z_support_session_bias",
            symbol="BTCUSDC",
            timeframe="15m",
            type="OB",
            low=98.0,
            high=100.0,
            mid=99.0,
            width_atr=0.4,
            dir_bias="support",
            created_ts=zone_now,
            touch_count=1,
            base_strength=82.0,
            quality=80.0,
            state="active",
            stats={"p1r": 0.72, "p2r": 0.54, "p3r": 0.31, "sample_size": 80},
            strategy_version="v1",
        ),
        Zone(
            zone_id="z_resist_session_bias",
            symbol="BTCUSDC",
            timeframe="15m",
            type="LP",
            low=101.5,
            high=102.5,
            mid=102.0,
            width_atr=0.3,
            dir_bias="resistance",
            created_ts=zone_now,
            touch_count=0,
            base_strength=65.0,
            quality=64.0,
            state="active",
            stats={},
            strategy_version="v1",
        ),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.45,
        jump_rate_5m=0.08,
        friction_5m=0.2,
        atr5=0.5,
        atr15=1.0,
        sdir=0.1,
        sevt=-0.1,
        f=0.1,
        v=0.2,
        a=0.05,
        vz=0.1,
        az=0.05,
        last_price=99.2,
    )

    generator = PlanGenerator()
    london_now = datetime(2026, 3, 9, 8, 0, tzinfo=timezone.utc)
    dead_now = datetime(2026, 3, 9, 2, 0, tzinfo=timezone.utc)
    ranked_live = generator.generate(symbol="BTCUSDC", zones=zones, context=context, now=london_now)
    ranked_dead = generator.generate(symbol="BTCUSDC", zones=zones, context=context, now=dead_now)

    assert ranked_live
    assert ranked_dead

    live_validity = dict(ranked_live[0].plan.validity or {})
    dead_validity = dict(ranked_dead[0].plan.validity or {})
    assert live_validity["session_guidance_state"] == "preferred_live_window"
    assert dead_validity["session_guidance_state"] == "dead_session"
    assert live_validity["expected_win_prob"] > dead_validity["expected_win_prob"]
    assert live_validity["session_score_bias"] > dead_validity["session_score_bias"]
