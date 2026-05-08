from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from app.db.models import Candle, Plan, Zone
from app.services.plan_generator import RankedPlan
from app.services.strategy_v2_scalp_experiment import StrategyV2ScalpExperimentService


def _candle(*, symbol: str, timeframe: str, ts: datetime, price: float) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        ts=ts,
        o=price - 1.0,
        h=price + 2.0,
        l=price - 2.0,
        c=price,
        v=1000.0,
        source="test",
        is_final=True,
    )


def _zone(*, zone_id: str, symbol: str, timeframe: str, zone_type: str, quality: float) -> Zone:
    now = datetime.now(timezone.utc)
    return Zone(
        zone_id=zone_id,
        symbol=symbol,
        timeframe=timeframe,
        type=zone_type,
        low=100.0,
        high=101.0,
        mid=100.5,
        width_atr=0.35,
        dir_bias="support",
        created_ts=now - timedelta(hours=2),
        last_touched_ts=None,
        touch_count=0,
        base_strength=72.0,
        quality=quality,
        state="active",
        merge_group_id=None,
        stats={},
        strategy_version="v1",
    )


def _ranked_plan(*, plan_id: str, symbol: str, timeframe: str, expected_ev: float, risk_r: float) -> RankedPlan:
    plan = Plan(
        plan_id=plan_id,
        zone_id=f"zone_{plan_id}",
        symbol=symbol,
        timeframe=timeframe,
        direction="long",
        entry_model="CONFIRM",
        entry_price=100.0,
        entry_condition="touch_then_confirm",
        sl=99.0,
        tp1=101.0,
        tp2=102.0,
        tp3=103.0,
        split={"tp1": 0.4, "tp2": 0.4, "runner": 0.2},
        rr_min=1.2,
        rr_base=2.0,
        rr_opt=3.0,
        ev=expected_ev,
        cost_est=0.1,
        confidence=0.75,
        validity={
            "strategy_family": "trend_continuation",
            "strategy_grade": "A",
            "recommended_risk_r": risk_r,
        },
        state="PLANNED",
        valid_from=datetime.now(timezone.utc) - timedelta(minutes=30),
        valid_until=datetime.now(timezone.utc) + timedelta(minutes=90),
        strategy_version="v1",
    )
    return RankedPlan(plan=plan, final_rank_score=83.5, friction_penalty=2.0)


class _DummyContextEngine:
    def build_snapshot(self, symbol: str, candles_5m: list[Candle], candles_15m: list[Candle]):
        timeframe = candles_5m[0].timeframe
        if timeframe == "1m":
            return SimpleNamespace(
                regime_label="trend",
                transition_state="none",
                jump_rate_5m=0.08,
                friction_5m=0.04,
            )
        return SimpleNamespace(
            regime_label="trend",
            transition_state="none",
            jump_rate_5m=0.12,
            friction_5m=0.06,
        )


class _DummyZoneEngine:
    def refresh(self, symbol: str, candles_15m: list[Candle], existing: list[Zone]):
        timeframe = candles_15m[0].timeframe
        if timeframe == "5m":
            return [_zone(zone_id="exp_zone", symbol=symbol, timeframe="5m", zone_type="OB", quality=81.0)]
        return [_zone(zone_id="base_zone", symbol=symbol, timeframe="15m", zone_type="LP", quality=72.0)]


class _DummyPlanGenerator:
    def generate(self, symbol: str, zones: list[Zone], context, candles_5m: list[Candle], active_thesis_clusters: int, now):
        timeframe = candles_5m[0].timeframe
        if timeframe == "1m":
            return [_ranked_plan(plan_id="experiment_plan", symbol=symbol, timeframe="1m", expected_ev=0.34, risk_r=0.4)]
        return [_ranked_plan(plan_id="baseline_plan", symbol=symbol, timeframe="5m", expected_ev=0.18, risk_r=0.25)]


def test_strategy_v2_scalp_experiment_prefers_experiment_branch() -> None:
    service = StrategyV2ScalpExperimentService(
        context_engine=_DummyContextEngine(),
        zone_engine=_DummyZoneEngine(),
        plan_generator=_DummyPlanGenerator(),
    )
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    candles_1m = [_candle(symbol="BTCUSDC", timeframe="1m", ts=now - timedelta(minutes=idx), price=100.0 + idx * 0.1) for idx in range(200)]
    candles_5m = [_candle(symbol="BTCUSDC", timeframe="5m", ts=now - timedelta(minutes=5 * idx), price=100.0 + idx * 0.2) for idx in range(150)]
    candles_15m = [_candle(symbol="BTCUSDC", timeframe="15m", ts=now - timedelta(minutes=15 * idx), price=100.0 + idx * 0.4) for idx in range(80)]

    payload = service.generate(
        symbol="BTCUSDC",
        candles_1m=list(reversed(candles_1m)),
        candles_5m=list(reversed(candles_5m)),
        candles_15m=list(reversed(candles_15m)),
        write_report=True,
    )

    assert payload["available"] is True
    assert payload["comparison"]["preferred_branch"] == "experiment"
    assert payload["comparison"]["recommendation_reason"] == "experiment_has_higher_sized_ev"
    assert payload["baseline"]["top_plan"]["plan_id"] == "baseline_plan"
    assert payload["experiment"]["top_plan"]["plan_id"] == "experiment_plan"
    assert payload["comparison"]["delta_top_expected_ev_at_size_r"] > 0.0
    assert "micro_main_shadow" in payload
    path = Path(payload["report_path"])
    assert path.exists()
    body = path.read_text(encoding="utf-8")
    assert "## Baseline (15m zone / 5m execution)" in body
    assert "## Experiment (5m zone / 1m execution)" in body
    assert "## Session Impulse Retest (shadow)" in body
    assert "preferred_branch: experiment" in body


def test_strategy_v2_scalp_experiment_blocks_when_candles_missing() -> None:
    service = StrategyV2ScalpExperimentService(
        context_engine=_DummyContextEngine(),
        zone_engine=_DummyZoneEngine(),
        plan_generator=_DummyPlanGenerator(),
    )
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    candles_1m = [_candle(symbol="BTCUSDC", timeframe="1m", ts=now - timedelta(minutes=idx), price=100.0) for idx in range(30)]
    candles_5m = [_candle(symbol="BTCUSDC", timeframe="5m", ts=now - timedelta(minutes=5 * idx), price=100.0) for idx in range(40)]
    candles_15m = [_candle(symbol="BTCUSDC", timeframe="15m", ts=now - timedelta(minutes=15 * idx), price=100.0) for idx in range(20)]

    payload = service.generate(
        symbol="BTCUSDC",
        candles_1m=list(reversed(candles_1m)),
        candles_5m=list(reversed(candles_5m)),
        candles_15m=list(reversed(candles_15m)),
        write_report=False,
    )

    assert payload["available"] is False
    assert payload["reason"] == "insufficient_candles"
    assert "insufficient_1m_candles" in payload["blocked_by"]
    assert payload["comparison"]["preferred_branch"] == "none"
