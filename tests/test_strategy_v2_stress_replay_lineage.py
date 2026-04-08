from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.db.models import Candle, ExecutionFill, Plan
from app.db.repositories import CandleRepository, ExecutionFillRepository, PlanRepository
from app.db.session import SessionLocal, init_db
from app.services.strategy_v2_stress_replay_lineage import StrategyV2StressReplayLineageService


def test_stress_replay_lineage_reports_unavailable_without_closed_v2_trades() -> None:
    init_db()
    with SessionLocal() as db:
        db.execute(delete(ExecutionFill))
        db.execute(delete(Candle))
        db.execute(delete(Plan))
        db.commit()
        service = StrategyV2StressReplayLineageService(
            plan_repo=PlanRepository(db),
            fill_repo=ExecutionFillRepository(db),
            candle_repo=CandleRepository(db),
        )
        payload = service.generate(symbol="BTCUSDC", version="v2", write_report=False)

        assert payload["available"] is False
        assert payload["runtime_inputs_ready"] is False
        assert payload["reason"] == "no_closed_v2_trades"


def test_stress_replay_lineage_computes_fill_and_candle_coverage() -> None:
    init_db()
    now = datetime(2026, 3, 8, 10, 0, tzinfo=timezone.utc)
    base_kwargs = dict(
        timeframe="5m",
        direction="long",
        entry_model="CONFIRM",
        entry_price=100.0,
        entry_condition="touch_then_confirm",
        sl=98.0,
        tp1=101.0,
        tp2=102.0,
        tp3=103.0,
        split={"tp1": 0.5, "tp2": 0.3, "runner": 0.2},
        rr_min=1.2,
        rr_base=2.0,
        rr_opt=3.0,
        ev=0.3,
        cost_est=0.04,
        confidence=0.7,
        state="CLOSED",
        strategy_version="v2",
    )

    with SessionLocal() as db:
        db.execute(delete(ExecutionFill))
        db.execute(delete(Candle))
        db.execute(delete(Plan))
        db.commit()

        plan_a = Plan(
            plan_id="stress_lineage_plan_a",
            zone_id="stress_lineage_zone_a",
            symbol="BTCUSDC",
            valid_from=now - timedelta(minutes=20),
            valid_until=now + timedelta(hours=1),
            validity={
                "strategy_family": "sweep_reversal",
                "strategy_grade": "A",
                "final_exit_ts": now.isoformat(),
                "final_exit_realized_r": 1.5,
                "final_exit_reason": "target_tp1",
                "final_exit_held_bars": 4,
            },
            **base_kwargs,
        )
        plan_b = Plan(
            plan_id="stress_lineage_plan_b",
            zone_id="stress_lineage_zone_b",
            symbol="BTCUSDC",
            valid_from=now - timedelta(minutes=25),
            valid_until=now + timedelta(hours=1),
            validity={
                "strategy_family": "trend_continuation",
                "strategy_grade": "B",
                "final_exit_ts": now.isoformat(),
                "final_exit_realized_r": -0.7,
                "final_exit_reason": "time_failure",
                "final_exit_held_bars": 5,
            },
            **base_kwargs,
        )
        db.add_all([plan_a, plan_b])

        # Plan A has full fill path and contiguous candles.
        db.add_all(
            [
                ExecutionFill(
                    fill_id="stress_lineage_fill_a_entry",
                    plan_id=plan_a.plan_id,
                    symbol="BTCUSDC",
                    stage="ENTRY",
                    fill_ts=now - timedelta(minutes=20),
                    price=100.1,
                    qty=1.0,
                    fee=0.02,
                    from_state="TRIGGERED",
                    to_state="ENTERED",
                    state_changed=True,
                    payload={},
                    strategy_version="v2",
                ),
                ExecutionFill(
                    fill_id="stress_lineage_fill_a_close",
                    plan_id=plan_a.plan_id,
                    symbol="BTCUSDC",
                    stage="CLOSED",
                    fill_ts=now,
                    price=101.5,
                    qty=1.0,
                    fee=0.02,
                    from_state="PARTIAL_EXIT",
                    to_state="CLOSED",
                    state_changed=True,
                    payload={},
                    strategy_version="v2",
                ),
                ExecutionFill(
                    fill_id="stress_lineage_fill_b_entry",
                    plan_id=plan_b.plan_id,
                    symbol="BTCUSDC",
                    stage="ENTRY",
                    fill_ts=now - timedelta(minutes=25),
                    price=99.8,
                    qty=1.0,
                    fee=0.02,
                    from_state="TRIGGERED",
                    to_state="ENTERED",
                    state_changed=True,
                    payload={},
                    strategy_version="v2",
                ),
            ]
        )

        candle_ts = [now - timedelta(minutes=20), now - timedelta(minutes=15), now - timedelta(minutes=10), now - timedelta(minutes=5), now]
        for ts in candle_ts:
            db.add(
                Candle(
                    symbol="BTCUSDC",
                    timeframe="5m",
                    ts=ts,
                    o=100.0,
                    h=101.0,
                    l=99.0,
                    c=100.5,
                    v=1000.0,
                    source="test",
                    is_final=True,
                )
            )
        db.commit()

        service = StrategyV2StressReplayLineageService(
            plan_repo=PlanRepository(db),
            fill_repo=ExecutionFillRepository(db),
            candle_repo=CandleRepository(db),
        )
        payload = service.generate(symbol="BTCUSDC", version="v2", write_report=False)

        assert payload["available"] is True
        assert payload["sample_counts"]["eligible_closed_trades"] == 2
        assert payload["sample_counts"]["full_fill_path_trades"] == 1
        assert payload["sample_counts"]["latency_bar_trades"] == 2
        assert payload["coverage"]["execution_fill_coverage"] == 0.5
        assert payload["coverage"]["latency_candle_coverage"] == 1.0
        assert payload["coverage"]["estimate_only_share"] == 0.5
        assert payload["fill_path"]["entry_anchor_sources"]["execution_entry_fill"] == 2
        assert payload["fill_path"]["exit_anchor_sources"]["execution_closed_fill"] == 1
        assert payload["fill_path"]["exit_anchor_sources"]["plan_final_exit_ts"] == 1
        assert "execution_fill_coverage_below_threshold" in payload["blocked_by"]


def test_stress_replay_lineage_includes_latency_bar_when_exit_shares_entry_bar() -> None:
    init_db()
    now = datetime(2026, 4, 7, 10, 58, tzinfo=timezone.utc)
    with SessionLocal() as db:
        db.execute(delete(ExecutionFill))
        db.execute(delete(Candle))
        db.execute(delete(Plan))
        db.commit()

        plan = Plan(
            plan_id="same_bar_exit_plan",
            zone_id="same_bar_exit_zone",
            symbol="BTCUSDC",
            timeframe="5m",
            direction="long",
            entry_model="CONFIRM",
            entry_price=100.0,
            entry_condition="touch_then_confirm",
            sl=98.0,
            tp1=101.0,
            tp2=102.0,
            tp3=103.0,
            split={"tp1": 0.5, "tp2": 0.3, "runner": 0.2},
            rr_min=1.2,
            rr_base=2.0,
            rr_opt=3.0,
            ev=0.3,
            cost_est=0.04,
            confidence=0.7,
            validity={
                "strategy_family": "sweep_reversal",
                "strategy_grade": "A",
                "final_exit_ts": "2026-04-07T10:59:00+00:00",
                "final_exit_realized_r": 1.0,
                "final_exit_reason": "target_tp1",
                "final_exit_held_bars": 1,
            },
            state="CLOSED",
            valid_from=datetime(2026, 4, 7, 10, 56, tzinfo=timezone.utc),
            valid_until=datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc),
            strategy_version="v2",
        )
        db.add(plan)
        db.add_all(
            [
                ExecutionFill(
                    fill_id="same_bar_entry_fill",
                    plan_id=plan.plan_id,
                    symbol="BTCUSDC",
                    stage="ENTRY",
                    fill_ts=datetime(2026, 4, 7, 10, 56, tzinfo=timezone.utc),
                    price=100.1,
                    qty=1.0,
                    fee=0.02,
                    from_state="TRIGGERED",
                    to_state="ENTERED",
                    state_changed=True,
                    payload={},
                    strategy_version="v2",
                ),
                ExecutionFill(
                    fill_id="same_bar_close_fill",
                    plan_id=plan.plan_id,
                    symbol="BTCUSDC",
                    stage="CLOSED",
                    fill_ts=datetime(2026, 4, 7, 10, 59, tzinfo=timezone.utc),
                    price=101.0,
                    qty=1.0,
                    fee=0.02,
                    from_state="ENTERED",
                    to_state="CLOSED",
                    state_changed=True,
                    payload={},
                    strategy_version="v2",
                ),
            ]
        )
        for ts in (
            datetime(2026, 4, 7, 10, 55, tzinfo=timezone.utc),
            datetime(2026, 4, 7, 11, 0, tzinfo=timezone.utc),
        ):
            db.add(
                Candle(
                    symbol="BTCUSDC",
                    timeframe="5m",
                    ts=ts,
                    o=100.0,
                    h=101.0,
                    l=99.0,
                    c=100.5,
                    v=1000.0,
                    source="test",
                    is_final=True,
                )
            )
        db.commit()

        service = StrategyV2StressReplayLineageService(
            plan_repo=PlanRepository(db),
            fill_repo=ExecutionFillRepository(db),
            candle_repo=CandleRepository(db),
        )
        rows = service.trade_rows(symbol="BTCUSDC", version="v2")

        assert len(rows) == 1
        assert rows[0]["entry_bar_exists"] is True
        assert rows[0]["latency_bar_exists"] is True
        assert rows[0]["exit_bar_exists"] is True
        assert rows[0]["complete_candle_path"] is True


def test_stress_replay_lineage_allows_boundary_entry_bar_fallback_when_fill_anchored() -> None:
    init_db()
    now = datetime(2026, 3, 8, 10, 0, tzinfo=timezone.utc)
    with SessionLocal() as db:
        db.execute(delete(ExecutionFill))
        db.execute(delete(Candle))
        db.execute(delete(Plan))
        db.commit()

        plan = Plan(
            plan_id="boundary_entry_plan",
            zone_id="boundary_entry_zone",
            symbol="BTCUSDC",
            timeframe="5m",
            direction="long",
            entry_model="CONFIRM",
            entry_price=100.0,
            entry_condition="touch_then_confirm",
            sl=98.0,
            tp1=101.0,
            tp2=102.0,
            tp3=103.0,
            split={"tp1": 0.5, "tp2": 0.3, "runner": 0.2},
            rr_min=1.2,
            rr_base=2.0,
            rr_opt=3.0,
            ev=0.3,
            cost_est=0.04,
            confidence=0.7,
            validity={
                "strategy_family": "trend_continuation",
                "strategy_grade": "B",
                "final_exit_ts": now.isoformat(),
                "final_exit_realized_r": -0.7,
                "final_exit_reason": "time_failure",
                "final_exit_held_bars": 5,
            },
            state="CLOSED",
            valid_from=now - timedelta(minutes=25),
            valid_until=now + timedelta(hours=1),
            strategy_version="v2",
        )
        db.add(plan)
        db.add(
            ExecutionFill(
                fill_id="boundary_entry_fill",
                plan_id=plan.plan_id,
                symbol="BTCUSDC",
                stage="ENTRY",
                fill_ts=now - timedelta(minutes=25),
                price=99.8,
                qty=1.0,
                fee=0.02,
                from_state="TRIGGERED",
                to_state="ENTERED",
                state_changed=True,
                payload={},
                strategy_version="v2",
            )
        )
        for ts in (
            now - timedelta(minutes=20),
            now - timedelta(minutes=15),
            now - timedelta(minutes=10),
            now - timedelta(minutes=5),
            now,
        ):
            db.add(
                Candle(
                    symbol="BTCUSDC",
                    timeframe="5m",
                    ts=ts,
                    o=100.0,
                    h=101.0,
                    l=99.0,
                    c=100.5,
                    v=1000.0,
                    source="test",
                    is_final=True,
                )
            )
        db.commit()

        service = StrategyV2StressReplayLineageService(
            plan_repo=PlanRepository(db),
            fill_repo=ExecutionFillRepository(db),
            candle_repo=CandleRepository(db),
        )
        rows = service.trade_rows(symbol="BTCUSDC", version="v2")

        assert len(rows) == 1
        assert rows[0]["entry_bar_exists"] is False
        assert rows[0]["latency_bar_exists"] is True
        assert rows[0]["exit_bar_exists"] is True
        assert rows[0]["entry_bar_boundary_fallback_used"] is True
        assert rows[0]["complete_candle_path"] is True


def test_stress_replay_lineage_uses_lineage_source_symbol_for_global_synthetic_plans() -> None:
    init_db()
    now = datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc)
    with SessionLocal() as db:
        db.execute(delete(ExecutionFill))
        db.execute(delete(Candle))
        db.execute(delete(Plan))
        db.commit()

        plan = Plan(
            plan_id="global_lineage_plan",
            zone_id="global_lineage_zone",
            symbol="LINEAGE_GLOBAL",
            timeframe="5m",
            direction="long",
            entry_model="CONFIRM",
            entry_price=100.0,
            entry_condition="touch_then_confirm",
            sl=98.0,
            tp1=101.0,
            tp2=102.0,
            tp3=103.0,
            split={"tp1": 0.5, "tp2": 0.3, "runner": 0.2},
            rr_min=1.2,
            rr_base=2.0,
            rr_opt=3.0,
            ev=0.3,
            cost_est=0.04,
            confidence=0.7,
            validity={
                "strategy_family": "sweep_reversal",
                "strategy_grade": "A",
                "lineage_source_symbol": "BTCUSDC",
                "final_exit_ts": now.isoformat(),
                "final_exit_realized_r": 1.0,
                "final_exit_reason": "target_tp1",
                "final_exit_held_bars": 4,
            },
            state="CLOSED",
            valid_from=now - timedelta(minutes=20),
            valid_until=now + timedelta(hours=1),
            strategy_version="v2",
        )
        db.add(plan)
        db.add_all(
            [
                ExecutionFill(
                    fill_id="global_lineage_entry_fill",
                    plan_id=plan.plan_id,
                    symbol="BTCUSDC",
                    stage="ENTRY",
                    fill_ts=now - timedelta(minutes=20),
                    price=100.1,
                    qty=1.0,
                    fee=0.02,
                    from_state="TRIGGERED",
                    to_state="ENTERED",
                    state_changed=True,
                    payload={},
                    strategy_version="v2",
                ),
                ExecutionFill(
                    fill_id="global_lineage_close_fill",
                    plan_id=plan.plan_id,
                    symbol="BTCUSDC",
                    stage="CLOSED",
                    fill_ts=now,
                    price=101.0,
                    qty=1.0,
                    fee=0.02,
                    from_state="PARTIAL_EXIT",
                    to_state="CLOSED",
                    state_changed=True,
                    payload={},
                    strategy_version="v2",
                ),
            ]
        )
        for ts in (
            now - timedelta(minutes=20),
            now - timedelta(minutes=15),
            now - timedelta(minutes=10),
            now - timedelta(minutes=5),
            now,
        ):
            db.add(
                Candle(
                    symbol="BTCUSDC",
                    timeframe="5m",
                    ts=ts,
                    o=100.0,
                    h=101.0,
                    l=99.0,
                    c=100.5,
                    v=1000.0,
                    source="test",
                    is_final=True,
                )
            )
        db.commit()

        service = StrategyV2StressReplayLineageService(
            plan_repo=PlanRepository(db),
            fill_repo=ExecutionFillRepository(db),
            candle_repo=CandleRepository(db),
        )
        rows = service.trade_rows(symbol="LINEAGE_GLOBAL", version="v2")

        assert len(rows) == 1
        assert rows[0]["symbol"] == "BTCUSDC"
        assert rows[0]["entry_bar_exists"] is True
        assert rows[0]["latency_bar_exists"] is True
        assert rows[0]["exit_bar_exists"] is True
        assert rows[0]["complete_candle_path"] is True
