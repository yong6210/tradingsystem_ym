from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.enums import PlanState
from app.db.models import Plan
from app.services.strategy_family_edge_review import StrategyFamilyEdgeReviewService


def _closed_plan(
    *,
    plan_id: str,
    closed_ts: datetime,
    family: str,
    realized_r: float,
    regime: str,
    session_hour: int,
    symbol: str = "BTCUSDC",
    version: str = "v1",
) -> Plan:
    entry_ts = closed_ts.replace(hour=session_hour, minute=0, second=0, microsecond=0) - timedelta(hours=2)
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
            "strategy_grade": "A",
            "final_exit_ts": closed_ts.isoformat(),
            "final_exit_realized_r": realized_r,
            "final_exit_reason": "target_tp2" if realized_r > 0 else "stop_loss",
            "final_exit_held_bars": 6,
        },
        state=PlanState.CLOSED.value,
        valid_from=entry_ts,
        valid_until=entry_ts + timedelta(hours=6),
        strategy_version=version,
    )


def test_strategy_family_edge_review_validates_a_anchor_and_writes_report(tmp_path: Path) -> None:
    service = StrategyFamilyEdgeReviewService()
    service.settings.strategy_family_edge_review_report_dir = str(tmp_path)

    now = datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc)
    plans = [
        _closed_plan(
            plan_id=f"a_{idx}",
            closed_ts=(now - timedelta(days=8 - idx)).replace(hour=hour),
            family="sweep_reversal",
            realized_r=value,
            regime=regime,
            session_hour=hour,
        )
        for idx, (value, regime, hour) in enumerate(
            [
                (1.2, "range", 8),
                (0.9, "range", 9),
                (1.1, "trend", 10),
                (0.8, "range", 11),
                (-0.3, "range", 8),
                (1.0, "trend", 9),
                (0.7, "transition", 10),
                (1.1, "range", 11),
            ],
            start=1,
        )
    ]
    plans.extend(
        [
            _closed_plan(
                plan_id=f"b_peer_{idx}",
                closed_ts=(now - timedelta(days=8 - idx)).replace(hour=13),
                family="trend_continuation",
                realized_r=value,
                regime="trend",
                session_hour=13,
            )
            for idx, value in enumerate([0.4, -0.2, 0.3, -0.1, 0.5, -0.3, 0.2, -0.2], start=1)
        ]
    )

    payload = service.generate_from_plans(
        family="sweep_reversal",
        peer_family="trend_continuation",
        plans=plans,
        version="v1",
        write_report=True,
        days=180,
    )

    assert payload["available"] is True
    assert payload["family"] == "sweep_reversal"
    assert payload["role"] == "a_anchor"
    assert payload["edge_state"] == "validated_edge"
    assert payload["analysis_bias"] == "keep_anchor"
    assert payload["target_metrics"]["trades"] == 8
    assert payload["trade_frequency"]["active_weeks"] >= 1
    assert payload["regime_breakdown"]
    assert payload["session_breakdown"]
    report_path = Path(str(payload["report_path"]))
    assert report_path.exists()
    body = report_path.read_text(encoding="utf-8")
    assert "## Headline" in body
    assert "## Core Metrics" in body
    assert "## Peer Comparison" in body


def test_strategy_family_edge_review_validates_b_diversification_when_overlap_is_low(tmp_path: Path) -> None:
    service = StrategyFamilyEdgeReviewService()
    service.settings.strategy_family_edge_review_report_dir = str(tmp_path)

    now = datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc)
    target_values = [0.6, 0.5, 0.4, 0.6, 0.5, 0.4, 0.6, 0.5]
    peer_values = [-1.1, 0.9, -1.0, 0.8, -1.0, 0.9, -0.9, 0.8]
    plans: list[Plan] = []
    for idx, (target_value, peer_value) in enumerate(zip(target_values, peer_values, strict=True), start=1):
        closed_ts = (now - timedelta(days=8 - idx)).replace(hour=9)
        regime = "trend" if idx % 2 else "range"
        plans.append(
            _closed_plan(
                plan_id=f"b_{idx}",
                closed_ts=closed_ts,
                family="trend_continuation",
                realized_r=target_value,
                regime=regime,
                session_hour=9,
            )
        )
        plans.append(
            _closed_plan(
                plan_id=f"a_peer_{idx}",
                closed_ts=closed_ts,
                family="sweep_reversal",
                realized_r=peer_value,
                regime=regime,
                session_hour=9,
            )
        )

    payload = service.generate_from_plans(
        family="trend_continuation",
        peer_family="sweep_reversal",
        plans=plans,
        version="v1",
        write_report=False,
        days=180,
    )

    assert payload["available"] is True
    assert payload["family"] == "trend_continuation"
    assert payload["role"] == "b_diversification"
    assert payload["edge_state"] == "validated_edge"
    assert payload["analysis_bias"] == "support_guarded_activation"
    assert payload["target_metrics"]["trades"] == 8
    assert payload["positive_rate"] >= 0.5
    assert payload["diversification_proxy"]["correlation_state"] == "low_overlap_proxy"
    assert payload["diversification_proxy"]["drawdown_contribution_state"] == "drawdown_buffering"
    assert payload["ev_gap_vs_peer"] > 0.0
