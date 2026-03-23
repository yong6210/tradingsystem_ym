from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.enums import PlanState
from app.db.models import Plan
from app.services.strategy_v2_thesis_validation import StrategyV2ThesisValidationService
from app.services.thesis_fingerprint import ThesisFingerprintService


_THESIS = ThesisFingerprintService()


def _closed_plan(
    *,
    plan_id: str,
    symbol: str,
    valid_from: datetime,
    closed_ts: datetime,
    direction: str,
    regime: str,
    family: str,
    reaction_classification: str,
    zone_type: str,
    near_lp: bool,
    realized_r: float,
    version: str = "v1",
) -> Plan:
    fingerprint = _THESIS.build(
        symbol=symbol,
        direction=direction,
        regime=regime,
        strategy_family=family,
        reaction_classification=reaction_classification,
        zone_type=zone_type,
        near_lp=near_lp,
        at=valid_from,
    )
    return Plan(
        plan_id=plan_id,
        zone_id=f"zone_{plan_id}",
        symbol=symbol,
        timeframe="5m",
        direction=direction,
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
            "strategy_grade": "A",
            "reaction_classification": reaction_classification,
            "thesis_fingerprint": fingerprint,
            "thesis_cluster_id": _THESIS.thesis_cluster_id(fingerprint),
            "final_exit_ts": closed_ts.isoformat(),
            "final_exit_realized_r": realized_r,
            "final_exit_reason": "target_tp2" if realized_r > 0 else "stop_loss",
            "final_exit_held_bars": 5,
        },
        state=PlanState.CLOSED.value,
        valid_from=valid_from,
        valid_until=closed_ts + timedelta(hours=4),
        strategy_version=version,
    )


def test_strategy_v2_thesis_validation_compares_before_and_after() -> None:
    service = StrategyV2ThesisValidationService()
    base = datetime(2026, 3, 7, 9, 0, tzinfo=timezone.utc)
    plans = [
        _closed_plan(
            plan_id="primary_a",
            symbol="BTCAUSDC",
            valid_from=base,
            closed_ts=base + timedelta(minutes=60),
            direction="long",
            regime="trend",
            family="trend_continuation",
            reaction_classification="acceptance_confirmed",
            zone_type="OB",
            near_lp=False,
            realized_r=1.0,
        ),
        _closed_plan(
            plan_id="duplicate_a",
            symbol="BTCBUSDC",
            valid_from=base + timedelta(minutes=10),
            closed_ts=base + timedelta(minutes=40),
            direction="long",
            regime="trend",
            family="trend_continuation",
            reaction_classification="acceptance_tentative",
            zone_type="OB",
            near_lp=False,
            realized_r=-1.2,
        ),
        _closed_plan(
            plan_id="primary_b",
            symbol="ETHAUSDC",
            valid_from=base + timedelta(minutes=15),
            closed_ts=base + timedelta(minutes=50),
            direction="short",
            regime="range",
            family="range_rotation",
            reaction_classification="rejection_confirmed",
            zone_type="LP",
            near_lp=True,
            realized_r=0.7,
        ),
        _closed_plan(
            plan_id="cluster_cap_block",
            symbol="SOLAUSDC",
            valid_from=base + timedelta(minutes=20),
            closed_ts=base + timedelta(minutes=55),
            direction="long",
            regime="trend",
            family="sweep_reversal",
            reaction_classification="rejection_confirmed",
            zone_type="LP",
            near_lp=True,
            realized_r=-0.9,
        ),
        _closed_plan(
            plan_id="later_a",
            symbol="BTCCUSDC",
            valid_from=base + timedelta(minutes=70),
            closed_ts=base + timedelta(minutes=110),
            direction="long",
            regime="trend",
            family="trend_continuation",
            reaction_classification="acceptance_confirmed",
            zone_type="OB",
            near_lp=False,
            realized_r=-0.2,
        ),
    ]

    payload = service.generate(symbol="BTCUSDC", version="v1", plans=plans, write_report=True)

    assert payload["available"] is True
    assert payload["evaluation_scope"] == "portfolio_global"
    assert sorted(payload["symbols_included"]) == ["BTCAUSDC", "BTCBUSDC", "BTCCUSDC", "ETHAUSDC", "SOLAUSDC"]
    assert payload["sample_counts"]["eligible_closed_trades"] == 5
    assert payload["sample_counts"]["after_dedupe_trades"] == 3
    assert payload["sample_counts"]["blocked_duplicate_trades"] == 1
    assert payload["sample_counts"]["blocked_active_cluster_cap_trades"] == 1
    assert payload["impact_counts"]["primary_trade_kept"] == 3
    assert payload["impact_counts"]["thesis_duplicate_blocked"] == 1
    assert payload["impact_counts"]["thesis_active_cluster_cap_reached"] == 1
    assert payload["comparison"]["max_drawdown"] < 0.0
    assert payload["deployment_recommendation"]["keep_dedupe_enabled"] is True
    assert payload["open_ts_sources"]["valid_from"] == 5
    path = Path(payload["report_path"])
    assert path.exists()
    assert "Comparison Table" in path.read_text(encoding="utf-8")


def test_strategy_v2_thesis_validation_handles_empty_input() -> None:
    service = StrategyV2ThesisValidationService()

    payload = service.generate(symbol="BTCUSDC", version="v1", plans=[], write_report=False)

    assert payload["available"] is False
    assert payload["reason"] == "no_closed_v2_trades"
    assert payload["thesis_metrics"]["before_dedupe"]["trades"] == 0
    assert payload["thesis_metrics"]["after_dedupe"]["trades"] == 0
