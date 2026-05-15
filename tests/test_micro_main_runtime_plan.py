from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.models import Candle
from app.db.session import SessionLocal, init_db
from app.services import strategy_engine as strategy_engine_module
from app.services.micro_main_strategy_research import MicroSignal
from app.services.strategy_engine import StrategyEngine


def _candles(symbol: str, timeframe: str, step_minutes: int, count: int, start: datetime) -> list[Candle]:
    rows: list[Candle] = []
    price = 100.0
    for idx in range(count):
        price += 0.03
        rows.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                ts=start + timedelta(minutes=step_minutes * idx),
                o=price,
                h=price + 0.2,
                l=price - 0.2,
                c=price + 0.05,
                v=1000 + idx,
                source="test",
                is_final=True,
            )
        )
    return rows


def test_session_impulse_retest_runtime_plan_builds_when_signal_is_fresh(monkeypatch) -> None:
    init_db()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles_1m = _candles("BTCUSDC", "1m", 1, 1200, start)
    candles_5m = _candles("BTCUSDC", "5m", 5, 300, start)
    last_ts = candles_1m[-1].ts
    fake_signal = MicroSignal(
        family="session_impulse_retest",
        direction="long",
        signal_ts=last_ts - timedelta(minutes=7),
        setup_ts=last_ts - timedelta(minutes=6),
        entry_ts=last_ts - timedelta(minutes=4),
        entry_price=120.0,
        stop_price=119.0,
        target_price=122.0,
        max_hold_minutes=25,
        regime_hint="trend",
        diagnostics={"reclaim_body_atr": 0.24, "volume_factor": 1.2},
    )

    monkeypatch.setattr(
        strategy_engine_module.SessionImpulseRetestResearch,
        "latest_signal",
        lambda self, freshness_minutes=20: fake_signal,
    )

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        plan = engine._session_impulse_retest_runtime_plan(
            symbol="BTCUSDC",
            candles_1m=candles_1m,
            candles_5m=candles_5m,
            active_thesis_clusters=0,
        )

        assert plan is not None
        assert plan.symbol == "BTCUSDC"
        assert plan.entry_model == "CONFIRM"
        assert plan.state == "ARMED"
        assert plan.validity["strategy_family"] == "session_impulse_retest"
        assert plan.validity["strategy_grade"] == "A"
        assert plan.validity["recommended_risk_r"] > 0
        assert plan.validity["thesis_cluster_id"]
        shadow_filter = plan.validity["session_impulse_retest_shadow_filter"]
        assert shadow_filter["mode"] == "compare_only"
        assert shadow_filter["blocking_live"] is False
        assert shadow_filter["decision"] == "would_block"
        assert plan.validity["session_impulse_retest_signal"]["diagnostics"]["reclaim_body_atr"] == 0.24


def test_session_impulse_retest_runtime_plan_applies_saturday_risk_haircut(monkeypatch) -> None:
    init_db()
    start = datetime(2026, 1, 3, tzinfo=UTC)
    candles_1m = _candles("BTCUSDC", "1m", 1, 1200, start)
    candles_5m = _candles("BTCUSDC", "5m", 5, 300, start)
    last_ts = candles_1m[-1].ts
    fake_signal = MicroSignal(
        family="session_impulse_retest",
        direction="long",
        signal_ts=last_ts - timedelta(minutes=7),
        setup_ts=last_ts - timedelta(minutes=6),
        entry_ts=last_ts - timedelta(minutes=4),
        entry_price=120.0,
        stop_price=119.0,
        target_price=122.0,
        max_hold_minutes=25,
        regime_hint="trend",
    )

    monkeypatch.setattr(
        strategy_engine_module.SessionImpulseRetestResearch,
        "latest_signal",
        lambda self, freshness_minutes=20: fake_signal,
    )

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.settings.session_impulse_retest_saturday_risk_multiplier = 0.75
        plan = engine._session_impulse_retest_runtime_plan(
            symbol="BTCUSDC",
            candles_1m=candles_1m,
            candles_5m=candles_5m,
            active_thesis_clusters=0,
        )

        assert plan is not None
        sizing = dict(plan.validity["strategy_sizing"])
        assert sizing["session_impulse_retest_weekday_utc"] == 5
        assert sizing["session_impulse_retest_saturday_risk_multiplier"] == 0.75
        assert sizing["operational_risk_adjustment_reason"] == "session_impulse_retest_saturday_risk_haircut"
        assert sizing["final_risk_r"] == round(sizing["post_mode_final_risk_r"] * 0.75, 4)
        assert plan.validity["session_impulse_retest_operational_risk_multiplier"] == 0.75
