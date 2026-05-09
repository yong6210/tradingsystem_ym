from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.enums import PlanState, StrategyMode
from app.core.config import get_settings
from app.db.models import Plan
from app.services.operating_lock import OperatingLockService


def _closed_plan(*, plan_id: str, closed_ts: datetime, realized_r: float, grade: str | None = None) -> Plan:
    return Plan(
        plan_id=plan_id,
        zone_id=f"{plan_id}_zone",
        symbol="BTCUSDC",
        timeframe="5m",
        direction="long",
        entry_model="CONFIRM",
        entry_price=100.0,
        entry_condition="touch_then_confirm",
        sl=98.5,
        tp1=101.0,
        tp2=102.0,
        tp3=103.0,
        split={"tp1": 0.4, "tp2": 0.4, "runner": 0.2},
        rr_min=1.4,
        rr_base=2.0,
        rr_opt=3.0,
        ev=0.22,
        cost_est=0.05,
        confidence=0.75,
        validity={
            "strategy_grade": grade,
            "final_exit_ts": closed_ts.isoformat(),
            "final_exit_realized_r": realized_r,
            "final_exit_reason": "stop_loss" if realized_r < 0 else "target_tp2",
        },
        state=PlanState.CLOSED.value,
        valid_from=closed_ts - timedelta(hours=1),
        valid_until=closed_ts + timedelta(hours=2),
        strategy_version="v2",
    )


def test_operating_lock_triggers_daily_loss_limit() -> None:
    settings = get_settings().model_copy(deep=True)
    service = OperatingLockService(settings)
    now = datetime(2026, 3, 7, 9, 0, tzinfo=timezone.utc)
    plans = [
        _closed_plan(plan_id="p1", closed_ts=now - timedelta(hours=2), realized_r=-1.2, grade="A"),
        _closed_plan(plan_id="p2", closed_ts=now - timedelta(hours=1), realized_r=-0.9, grade="B"),
    ]

    snapshot = service.evaluate(plans=plans, now=now, mode=StrategyMode.A_ONLY)

    assert snapshot.active is True
    assert snapshot.reason == "daily_loss_limit_reached"
    assert snapshot.scope == "daily"
    assert snapshot.daily_stats["realized_r"] == -2.1
    assert snapshot.unlock_at == datetime(2026, 3, 8, 0, 0, tzinfo=timezone.utc).isoformat()



def test_operating_lock_triggers_daily_a_grade_failures() -> None:
    settings = get_settings().model_copy(deep=True)
    service = OperatingLockService(settings)
    now = datetime(2026, 3, 7, 10, 0, tzinfo=timezone.utc)
    plans = [
        _closed_plan(plan_id="p1", closed_ts=now - timedelta(hours=2), realized_r=-0.4, grade="A"),
        _closed_plan(plan_id="p2", closed_ts=now - timedelta(hours=1), realized_r=-0.5, grade="A"),
    ]

    snapshot = service.evaluate(plans=plans, now=now, mode=StrategyMode.A_ONLY)

    assert snapshot.active is True
    assert snapshot.reason == "daily_a_grade_failures_reached"
    assert snapshot.daily_stats["a_grade_loss_streak"] == 2



def test_operating_lock_triggers_session_consecutive_losses() -> None:
    settings = get_settings().model_copy(deep=True)
    service = OperatingLockService(settings)
    now = datetime(2026, 3, 7, 14, 0, tzinfo=timezone.utc)
    plans = [
        _closed_plan(plan_id="p1", closed_ts=now - timedelta(minutes=50), realized_r=-0.3, grade="A"),
        _closed_plan(plan_id="p2", closed_ts=now - timedelta(minutes=10), realized_r=-0.4, grade="B"),
    ]

    snapshot = service.evaluate(plans=plans, now=now, mode=StrategyMode.A_ONLY)

    assert snapshot.active is True
    assert snapshot.reason == "session_consecutive_losses_reached"
    assert snapshot.scope == "session"
    assert snapshot.current_session["name"] == "new_york"
    assert snapshot.session_stats["loss_streak"] == 2



def test_operating_lock_research_mode_does_not_block() -> None:
    settings = get_settings().model_copy(deep=True)
    service = OperatingLockService(settings)
    now = datetime(2026, 3, 7, 14, 0, tzinfo=timezone.utc)
    plans = [
        _closed_plan(plan_id="p1", closed_ts=now - timedelta(hours=2), realized_r=-1.4, grade="A"),
        _closed_plan(plan_id="p2", closed_ts=now - timedelta(hours=1), realized_r=-1.1, grade="A"),
    ]

    snapshot = service.evaluate(plans=plans, now=now, mode=StrategyMode.RESEARCH)

    assert snapshot.active is False
    assert snapshot.enforced is False
    assert snapshot.reason == "research_mode_shadow_only"


def test_operating_lock_tolerates_malformed_numeric_settings_and_trade_values() -> None:
    settings = get_settings().model_copy(deep=True)
    settings.trading_session_london_start_hour_utc = "bad-start"
    settings.trading_session_london_end_hour_utc = "bad-end"
    settings.trading_session_new_york_start_hour_utc = "bad-ny-start"
    settings.trading_session_new_york_end_hour_utc = "bad-ny-end"
    settings.operating_lock_daily_loss_limit_r = "bad-daily-limit"
    settings.operating_lock_session_loss_limit_r = "inf"
    settings.operating_lock_daily_consecutive_losses = "bad-daily-streak"
    settings.operating_lock_daily_a_grade_failures = "bad-a-streak"
    settings.operating_lock_session_consecutive_losses = "nan"
    service = OperatingLockService(settings)
    now = datetime(2026, 3, 7, 9, 0, tzinfo=timezone.utc)
    malformed = _closed_plan(plan_id="bad_realized_r", closed_ts=now - timedelta(minutes=30), realized_r=-0.4, grade="A")
    malformed.validity = {**dict(malformed.validity or {}), "final_exit_realized_r": "inf"}

    snapshot = service.evaluate(plans=[malformed], now=now, mode=StrategyMode.A_ONLY)

    assert snapshot.active is False
    assert snapshot.current_session["name"] == "london"
    assert snapshot.daily_stats["trades"] == 0
    assert snapshot.daily_stats["loss_limit_r"] == -2.0
    assert snapshot.session_stats["loss_limit_r"] == -1.5
