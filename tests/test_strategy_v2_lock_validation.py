from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.enums import PlanState
from app.db.models import Plan
from app.services.strategy_v2_lock_validation import StrategyV2LockValidationService


def _closed_plan(
    *,
    plan_id: str,
    symbol: str,
    regime: str,
    transition_state: str,
    grade: str,
    family: str,
    reaction_classification: str,
    realized_r: float,
    exit_reason: str,
    held_bars: int,
    closed_ts: datetime,
    version: str = "v1",
) -> Plan:
    return Plan(
        plan_id=plan_id,
        zone_id=f"zone_{plan_id}",
        symbol=symbol,
        timeframe="5m",
        direction="long",
        entry_model="CONFIRM",
        entry_price=100.0,
        entry_condition="touch_then_confirm",
        sl=99.0,
        tp1=101.0,
        tp2=102.0,
        tp3=103.0,
        split={"tp1": 0.4, "tp2": 0.4, "runner": 0.2},
        rr_min=1.0,
        rr_base=1.8,
        rr_opt=2.5,
        ev=0.4,
        cost_est=0.1,
        confidence=0.7,
        validity={
            "regime": regime,
            "transition_state": transition_state,
            "strategy_family": family,
            "strategy_grade": grade,
            "reaction_classification": reaction_classification,
            "final_exit_ts": closed_ts.isoformat(),
            "final_exit_realized_r": realized_r,
            "final_exit_reason": exit_reason,
            "final_exit_held_bars": held_bars,
        },
        state=PlanState.CLOSED.value,
        valid_from=closed_ts - timedelta(hours=4),
        valid_until=closed_ts + timedelta(hours=4),
        strategy_version=version,
    )


def test_strategy_v2_lock_validation_compares_before_and_after() -> None:
    service = StrategyV2LockValidationService()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    plans = [
        _closed_plan(
            plan_id="plain_a",
            symbol="BTCUSDC",
            regime="range",
            transition_state="none",
            grade="A",
            family="sweep_reversal",
            reaction_classification="rejection_confirmed",
            realized_r=1.1,
            exit_reason="target_tp2",
            held_bars=4,
            closed_ts=now - timedelta(days=5),
        ),
        _closed_plan(
            plan_id="transition_watch",
            symbol="BTCUSDC",
            regime="range",
            transition_state="transition_watch",
            grade="A",
            family="sweep_reversal",
            reaction_classification="rejection_confirmed",
            realized_r=0.7,
            exit_reason="target_tp1",
            held_bars=3,
            closed_ts=now - timedelta(days=4),
        ),
        _closed_plan(
            plan_id="shock_clamped",
            symbol="BTCUSDC",
            regime="shock",
            transition_state="none",
            grade="A",
            family="trend_continuation",
            reaction_classification="not_applicable",
            realized_r=-1.0,
            exit_reason="time_failure",
            held_bars=7,
            closed_ts=now - timedelta(days=3),
        ),
        _closed_plan(
            plan_id="shock_blocked",
            symbol="BTCUSDC",
            regime="shock",
            transition_state="none",
            grade="B",
            family="sweep_reversal",
            reaction_classification="rejection_tentative",
            realized_r=-0.8,
            exit_reason="information_failure",
            held_bars=4,
            closed_ts=now - timedelta(days=2),
        ),
        _closed_plan(
            plan_id="plain_loss",
            symbol="BTCUSDC",
            regime="trend",
            transition_state="none",
            grade="A",
            family="trend_continuation",
            reaction_classification="not_applicable",
            realized_r=-0.3,
            exit_reason="stop_loss",
            held_bars=6,
            closed_ts=now - timedelta(days=1),
        ),
    ]

    payload = service.generate(symbol="BTCUSDC", version="v1", plans=plans, write_report=True)

    assert payload["available"] is True
    assert payload["sample_counts"]["eligible_closed_trades"] == 5
    assert payload["sample_counts"]["after_lock_trades"] == 3
    assert payload["sample_counts"]["blocked_transition_trades"] == 1
    assert payload["sample_counts"]["blocked_shock_trades"] == 1
    assert payload["sample_counts"]["shock_clamped_trades"] == 1
    assert payload["impact_counts"]["shock_size_clamp"] == 1
    assert payload["comparison"]["max_drawdown"] < 0.0
    assert payload["deployment_recommendation"]["keep_lock_enabled"] is True
    path = Path(payload["report_path"])
    assert path.exists()
    assert "Comparison Table" in path.read_text(encoding="utf-8")


def test_strategy_v2_lock_validation_handles_empty_input() -> None:
    service = StrategyV2LockValidationService()

    payload = service.generate(symbol="BTCUSDC", version="v1", plans=[], write_report=False)

    assert payload["available"] is False
    assert payload["reason"] == "no_closed_v2_trades"
    assert payload["lock_metrics"]["before_lock"]["trades"] == 0
    assert payload["lock_metrics"]["after_lock"]["trades"] == 0


def test_strategy_v2_lock_validation_tolerates_malformed_shock_factor() -> None:
    service = StrategyV2LockValidationService()
    original = service.settings.sizing_regime_factor_shock
    try:
        service.settings.sizing_regime_factor_shock = float("inf")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        plan = _closed_plan(
            plan_id="shock_clamped_bad_setting",
            symbol="BTCUSDC",
            regime="shock",
            transition_state="none",
            grade="A",
            family="trend_continuation",
            reaction_classification="not_applicable",
            realized_r=-1.0,
            exit_reason="time_failure",
            held_bars=7,
            closed_ts=now,
        )

        payload = service.generate(symbol="BTCUSDC", version="v1", plans=[plan], write_report=False)

        assert payload["available"] is True
        assert payload["lock_metrics"]["after_lock"]["ev"] == -0.4
    finally:
        service.settings.sizing_regime_factor_shock = original
