from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import Plan
from app.services.context_engine import ContextSnapshot
from app.services.strategy_indicators import StrategyIndicatorsService


def test_strategy_indicators_top_plan_preserves_runtime_signal_shadow_tilt() -> None:
    service = StrategyIndicatorsService()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    plan = Plan(
        plan_id="plan_shadow_tilt",
        zone_id="zone_shadow_tilt",
        symbol="BTCUSDC",
        timeframe="5m",
        direction="long",
        entry_model="LIMIT",
        entry_price=100.0,
        entry_condition="limit_on_touch",
        sl=99.0,
        tp1=101.0,
        tp2=102.0,
        tp3=103.0,
        split={"tp1": 0.4, "tp2": 0.3, "runner": 0.3},
        rr_min=1.2,
        rr_base=2.0,
        rr_opt=3.0,
        ev=0.35,
        cost_est=0.02,
        confidence=0.7,
        validity={
            "strategy_family": "sweep_reversal",
            "strategy_grade": "A",
            "strategy_family_reason": "sweep_reversal_limit",
            "recommended_risk_r": 0.8,
            "runtime_signal_shadow_tilt": {
                "classification": "weak_long_understretch",
                "shadow_size_multiplier": 0.75,
                "base_recommended_risk_r": 0.8,
                "shadow_recommended_risk_r": 0.6,
                "apply_live": False,
            },
        },
        state="PLANNED",
        valid_from=now,
        valid_until=now + timedelta(minutes=60),
        strategy_version="v1",
    )
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
        last_price=100.2,
    )

    payload = service.build_summary(
        symbol="BTCUSDC",
        context=context,
        plans=[plan],
        zones=[],
        refresh={"requested": False},
        assessed_rows=[],
    )

    assert payload["top_plan"]["runtime_signal_shadow_tilt"]["classification"] == "weak_long_understretch"
    assert payload["top_plan"]["runtime_signal_shadow_tilt"]["shadow_recommended_risk_r"] == 0.6
