from __future__ import annotations

from datetime import datetime, timezone

from app.db.models import Zone
from app.services.context_engine import ContextSnapshot
from app.services.plan_generator import PlanGenerator


def _setup() -> tuple[list[Zone], ContextSnapshot]:
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
            base_strength=82.0,
            quality=76.0,
            state="active",
            stats={"p1r": 0.72, "p2r": 0.54, "p3r": 0.32, "ev_r": 0.50, "sample_size": 120},
            strategy_version="v1",
        ),
        Zone(
            zone_id="z_resist",
            symbol="BTCUSDC",
            timeframe="15m",
            type="LP",
            low=101.7,
            high=102.3,
            mid=102.0,
            width_atr=0.3,
            dir_bias="resistance",
            created_ts=now,
            touch_count=1,
            base_strength=70.0,
            quality=68.0,
            state="active",
            stats={},
            strategy_version="v1",
        ),
    ]
    context = ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.52,
        jump_rate_5m=0.07,
        friction_5m=0.18,
        atr5=0.5,
        atr15=1.0,
        sdir=0.3,
        sevt=-0.1,
        f=0.2,
        v=0.6,
        a=0.2,
        vz=0.4,
        az=0.2,
        last_price=99.2,
        regime_label="range",
    )
    return zones, context


def test_meta_filter_attaches_meta_fields() -> None:
    zones, context = _setup()
    generator = PlanGenerator()
    ranked = generator.generate(symbol="BTCUSDC", zones=zones, context=context)

    assert ranked
    validity = ranked[0].plan.validity
    assert "meta_score" in validity
    assert "meta_threshold" in validity
    assert "meta_reason" in validity


def test_meta_filter_blocks_when_threshold_is_tightened() -> None:
    zones, context = _setup()
    generator = PlanGenerator()

    baseline = generator.generate(symbol="BTCUSDC", zones=zones, context=context)
    assert baseline

    old_threshold = generator.settings.meta_filter_min_score_range
    generator.settings.meta_filter_min_score_range = 101.0
    try:
        blocked = generator.generate(symbol="BTCUSDC", zones=zones, context=context)
        assert not blocked
    finally:
        generator.settings.meta_filter_min_score_range = old_threshold
