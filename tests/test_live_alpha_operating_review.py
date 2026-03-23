from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.enums import PlanState
from app.db.models import Plan
from app.services.live_alpha_operating_review import LiveAlphaOperatingReviewService


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


def test_live_alpha_operating_review_combines_a_b_and_writes_report(tmp_path: Path) -> None:
    service = LiveAlphaOperatingReviewService()
    service.settings.strategy_family_edge_review_report_dir = str(tmp_path / "family")
    service.settings.live_alpha_operating_review_report_dir = str(tmp_path / "alpha")

    now = datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc)
    plans: list[Plan] = []
    a_values = [1.2, 0.9, 1.1, 0.8, -0.3, 1.0, 0.7, 1.1]
    b_values = [0.6, 0.5, 0.4, 0.6, 0.5, 0.4, 0.6, 0.5]
    peer_values = [-1.1, 0.9, -1.0, 0.8, -1.0, 0.9, -0.9, 0.8]
    for idx, (a_value, b_value, peer_value) in enumerate(zip(a_values, b_values, peer_values), start=1):
        closed_ts = (now - timedelta(days=8 - idx)).replace(hour=9)
        regime = "trend" if idx % 2 else "range"
        plans.append(
            _closed_plan(
                plan_id=f"a_{idx}",
                closed_ts=closed_ts,
                family="sweep_reversal",
                realized_r=a_value,
                regime=regime,
                session_hour=9,
            )
        )
        plans.append(
            _closed_plan(
                plan_id=f"b_{idx}",
                closed_ts=closed_ts,
                family="trend_continuation",
                realized_r=b_value,
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
                session_hour=11,
            )
        )

    payload = service.generate_from_plans(
        plans=plans,
        version="v1",
        days=180,
        write_report=True,
    )

    assert payload["portfolio_state"] in {
        "a_anchor_with_b_optional",
        "a_anchor_b_guarded",
        "a_anchor_collecting_b_evidence",
    }
    assert payload["a_review"]["family"] == "sweep_reversal"
    assert payload["b_review"]["family"] == "trend_continuation"
    assert payload["a_projection"]["projected_30d_post_cost_r"] > 0.0
    assert payload["b_projection"]["projected_30d_post_cost_r"] >= 0.0
    assert payload["portfolio_projection"]["combined_projected_30d_post_cost_r"] > 0.0
    report_path = Path(str(payload["report_path"]))
    assert report_path.exists()
    body = report_path.read_text(encoding="utf-8")
    assert "## A Anchor Review" in body
    assert "## B Diversification Review" in body
    assert "## Monthly Projection Proxy" in body
