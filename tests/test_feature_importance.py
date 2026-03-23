from __future__ import annotations

from datetime import datetime, timezone

from app.db.models import Zone
from app.services.context_engine import ContextSnapshot
from app.services.feature_importance import FEATURE_KEYS, FeatureImportanceService
from app.services.plan_generator import PlanGenerator


def _zone(
    *,
    zone_id: str,
    zone_type: str,
    dir_bias: str,
    low: float,
    high: float,
    mid: float,
) -> Zone:
    return Zone(
        zone_id=zone_id,
        symbol="BTCUSDC",
        timeframe="15m",
        type=zone_type,
        low=low,
        high=high,
        mid=mid,
        width_atr=0.4,
        dir_bias=dir_bias,
        created_ts=datetime.now(timezone.utc),
        touch_count=1,
        base_strength=78.0,
        quality=74.0,
        state="active",
        stats={"p1r": 0.70, "p2r": 0.52, "p3r": 0.30, "ev_r": 0.40, "sample_size": 90},
        strategy_version="v1",
    )


def _context() -> ContextSnapshot:
    return ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.55,
        jump_rate_5m=0.06,
        friction_5m=0.17,
        atr5=0.5,
        atr15=1.0,
        sdir=0.4,
        sevt=-0.1,
        f=0.3,
        v=0.7,
        a=0.2,
        vz=0.6,
        az=0.3,
        last_price=99.1,
        regime_label="range",
    )


def test_feature_importance_ablation_produces_ranking() -> None:
    generator = PlanGenerator()
    service = FeatureImportanceService(generator)
    zones = [
        _zone(zone_id="z_support", zone_type="OB", dir_bias="support", low=98.8, high=99.2, mid=99.0),
        _zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=101.8, high=102.2, mid=102.0),
    ]

    report = service.analyze(symbol="BTCUSDC", zones=zones, context=_context())

    assert report["available"] is True
    assert report["baseline"]["generated_plans"] >= 1
    assert len(report["ranking"]) == len(FEATURE_KEYS)
    assert set(report["by_feature"].keys()) == set(FEATURE_KEYS)
    assert report["ranking"][0]["importance_score"] >= report["ranking"][-1]["importance_score"]


def test_feature_importance_handles_missing_active_zones() -> None:
    generator = PlanGenerator()
    service = FeatureImportanceService(generator)
    zone = _zone(zone_id="z_expired", zone_type="OB", dir_bias="support", low=98.8, high=99.2, mid=99.0)
    zone.state = "expired"

    report = service.analyze(symbol="BTCUSDC", zones=[zone], context=_context())

    assert report["available"] is False
    assert report["reason"] == "no_active_zones"
