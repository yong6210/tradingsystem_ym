from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.enums import PlanState
from app.db.models import Plan
from app.services.strategy_v2_validation import StrategyV2ValidationService


def _closed_plan(
    *,
    plan_id: str,
    symbol: str,
    grade: str,
    realized_r: float,
    exit_reason: str,
    held_bars: int,
    closed_ts: datetime,
    family: str = "sweep_reversal",
    regime: str = "range",
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
            "strategy_family": family,
            "strategy_grade": grade,
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


def test_strategy_v2_validation_prefers_a_only_when_b_incremental_hurts_downside() -> None:
    service = StrategyV2ValidationService()
    now = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0)
    plans = [
        _closed_plan(
            plan_id="a_win",
            symbol="BTCUSDC",
            grade="A",
            realized_r=1.2,
            exit_reason="target_tp2",
            held_bars=4,
            closed_ts=now - timedelta(days=3),
        ),
        _closed_plan(
            plan_id="a_loss",
            symbol="BTCUSDC",
            grade="A",
            realized_r=-0.4,
            exit_reason="stop_loss",
            held_bars=6,
            closed_ts=(now - timedelta(days=2)).replace(hour=9),
        ),
        _closed_plan(
            plan_id="b_info_fail",
            symbol="BTCUSDC",
            grade="B",
            realized_r=-1.1,
            exit_reason="information_failure",
            held_bars=5,
            closed_ts=(now - timedelta(days=1)).replace(hour=20),
            family="trend_continuation",
            regime="shock",
        ),
    ]

    payload = service.generate(symbol="BTCUSDC", version="v1", plans=plans, write_report=True)

    assert payload["available"] is True
    assert payload["sample_counts"]["a_only_trades"] == 2
    assert payload["sample_counts"]["a_plus_b_trades"] == 3
    assert payload["sample_counts"]["incremental_b_trades"] == 1
    assert payload["family_metrics"]["sweep_reversal"]["trades"] == 2
    assert payload["family_metrics"]["trend_continuation"]["trades"] == 1
    assert payload["family_summary"]["best_ev_family"]["name"] == "sweep_reversal"
    assert payload["regime_metrics"]["range"]["trades"] == 2
    assert payload["regime_metrics"]["shock"]["trades"] == 1
    assert payload["regime_summary"]["best_ev_regime"]["name"] == "range"
    assert payload["session_metrics"]["london"]["trades"] == 2
    assert payload["session_metrics"]["dead_session"]["trades"] == 1
    assert payload["session_summary"]["best_ev_session"]["name"] == "london"
    assert payload["mode_metrics"]["A_ONLY"]["information_failure_ratio"] == 0.0
    assert payload["mode_metrics"]["A_PLUS_B"]["information_failure_ratio"] == round(1 / 3, 4)
    assert payload["comparison"]["max_drawdown"] > 0.0
    assert payload["deployment_recommendation"]["preferred_live_mode"] == "A_ONLY"
    assert payload["deployment_recommendation"]["reason"] == "a_only_downside_better"
    path = Path(payload["report_path"])
    assert path.exists()
    body = path.read_text(encoding="utf-8")
    assert "## Comparison Table" in body
    assert "## Family Breakdown" in body
    assert "## Regime Breakdown" in body
    assert "## Session Breakdown" in body
    assert "A_ONLY" in body
    assert "A_PLUS_B" in body


def test_strategy_v2_validation_handles_no_closed_v2_trades() -> None:
    service = StrategyV2ValidationService()
    payload = service.generate(symbol="BTCUSDC", version="v1", plans=[], write_report=False)

    assert payload["available"] is False
    assert payload["reason"] == "no_closed_v2_trades"
    assert payload["deployment_recommendation"]["preferred_live_mode"] == "A_ONLY"
    assert payload["comparison"]["ev"] == 0.0
