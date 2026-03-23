from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.enums import ExecutionFillStage, PlanState
from app.db.models import EventOutbox, ExecutionFill, Plan
from app.db.session import SessionLocal, init_db
from app.services.strategy_engine import StrategyEngine


def _seed_plan(db, *, symbol: str, plan_id: str, state: str = "ARMED") -> Plan:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    plan = Plan(
        plan_id=plan_id,
        zone_id=f"{symbol}_z1",
        symbol=symbol,
        timeframe="5m",
        direction="long",
        entry_model="CONFIRM",
        entry_price=100.0,
        entry_condition="touch_then_confirm",
        sl=98.8,
        tp1=101.0,
        tp2=102.0,
        tp3=103.0,
        split={"tp1": 0.6, "tp2": 0.25, "runner": 0.15},
        rr_min=1.2,
        rr_base=1.8,
        rr_opt=2.4,
        ev=0.21,
        cost_est=0.08,
        confidence=0.71,
        validity={
            "meta_reason": "meta_pass",
            "strategy_family": "sweep_reversal",
            "strategy_family_time_stop_min_bars": 3,
            "strategy_family_time_stop_max_bars": 5,
            "reaction_classification": "rejection_confirmed",
        },
        state=state,
        valid_from=now - timedelta(minutes=15),
        valid_until=now + timedelta(hours=6),
        strategy_version="v1",
    )
    db.add(plan)
    db.commit()
    return plan


def test_position_state_machine_forward_transition_and_close_event() -> None:
    init_db()
    symbol = f"PSM{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"

    with SessionLocal() as db:
        plan = _seed_plan(db, symbol=symbol, plan_id=f"{symbol}_p1")
        engine = StrategyEngine(db)
        base_ts = datetime.now(timezone.utc)

        entry = engine.ingest_execution_fill(
            fill_id=f"{plan.plan_id}_f_entry",
            plan_id=plan.plan_id,
            symbol=symbol,
            stage=ExecutionFillStage.ENTRY,
            fill_ts=base_ts,
            price=100.1,
            qty=1.0,
            fee=0.01,
            payload={"source": "test"},
        )
        assert entry["accepted"] is True
        assert entry["duplicate"] is False
        assert entry["state_changed"] is True
        assert entry["to_state"] == PlanState.ENTERED.value

        partial = engine.ingest_execution_fill(
            fill_id=f"{plan.plan_id}_f_tp1",
            plan_id=plan.plan_id,
            symbol=symbol,
            stage=ExecutionFillStage.PARTIAL_EXIT,
            fill_ts=base_ts + timedelta(minutes=5),
            price=101.0,
            qty=0.6,
            fee=0.01,
            payload={"source": "test", "leg": "tp1"},
        )
        assert partial["accepted"] is True
        assert partial["state_changed"] is True
        assert partial["to_state"] == PlanState.PARTIAL_EXIT.value

        closed = engine.ingest_execution_fill(
            fill_id=f"{plan.plan_id}_f_close",
            plan_id=plan.plan_id,
            symbol=symbol,
            stage=ExecutionFillStage.CLOSED,
            fill_ts=base_ts + timedelta(minutes=10),
            price=102.2,
            qty=0.4,
            fee=0.01,
            payload={"source": "test", "leg": "runner"},
        )
        assert closed["accepted"] is True
        assert closed["state_changed"] is True
        assert closed["to_state"] == PlanState.CLOSED.value

        refreshed = db.get(Plan, plan.plan_id)
        assert refreshed is not None
        assert refreshed.state == PlanState.CLOSED.value

        closed_events = list(db.scalars(select(EventOutbox).where(EventOutbox.event_type == "trade.closed")))
        assert len(closed_events) >= 1


def test_position_state_machine_idempotent_fill_and_non_forward_transition() -> None:
    init_db()
    symbol = f"PSM{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 1}USDC"

    with SessionLocal() as db:
        plan = _seed_plan(db, symbol=symbol, plan_id=f"{symbol}_p2")
        engine = StrategyEngine(db)
        base_ts = datetime.now(timezone.utc)

        first = engine.ingest_execution_fill(
            fill_id=f"{plan.plan_id}_dup",
            plan_id=plan.plan_id,
            symbol=symbol,
            stage=ExecutionFillStage.ENTRY,
            fill_ts=base_ts,
            price=100.0,
            qty=1.0,
            payload={"source": "test"},
        )
        assert first["accepted"] is True
        assert first["state_changed"] is True
        assert first["to_state"] == PlanState.ENTERED.value

        second = engine.ingest_execution_fill(
            fill_id=f"{plan.plan_id}_dup",
            plan_id=plan.plan_id,
            symbol=symbol,
            stage=ExecutionFillStage.CLOSED,
            fill_ts=base_ts + timedelta(minutes=1),
            price=99.0,
            qty=1.0,
            payload={"source": "test"},
        )
        assert second["accepted"] is True
        assert second["duplicate"] is True
        assert second["reason"] == "duplicate_fill_id"
        assert second["to_state"] == PlanState.ENTERED.value

        close = engine.ingest_execution_fill(
            fill_id=f"{plan.plan_id}_close",
            plan_id=plan.plan_id,
            symbol=symbol,
            stage=ExecutionFillStage.CLOSED,
            fill_ts=base_ts + timedelta(minutes=2),
            price=99.0,
            qty=1.0,
            payload={"source": "test"},
        )
        assert close["accepted"] is True
        assert close["state_changed"] is True
        assert close["to_state"] == PlanState.CLOSED.value

        stale = engine.ingest_execution_fill(
            fill_id=f"{plan.plan_id}_late_entry",
            plan_id=plan.plan_id,
            symbol=symbol,
            stage=ExecutionFillStage.ENTRY,
            fill_ts=base_ts + timedelta(minutes=3),
            price=99.5,
            qty=0.2,
            payload={"source": "test", "late": True},
        )
        assert stale["accepted"] is True
        assert stale["state_changed"] is False
        assert stale["reason"] == "non_forward_transition"
        assert stale["from_state"] == PlanState.CLOSED.value
        assert stale["to_state"] == PlanState.CLOSED.value

        fills = list(db.scalars(select(ExecutionFill).where(ExecutionFill.plan_id == plan.plan_id)))
        assert len(fills) == 3

        refreshed = db.get(Plan, plan.plan_id)
        assert refreshed is not None
        assert refreshed.state == PlanState.CLOSED.value


def test_position_state_machine_infers_information_failure_on_classification_flip() -> None:
    init_db()
    symbol = f"PSM{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 2}USDC"

    with SessionLocal() as db:
        plan = _seed_plan(db, symbol=symbol, plan_id=f"{symbol}_p3")
        engine = StrategyEngine(db)
        base_ts = datetime.now(timezone.utc)

        engine.ingest_execution_fill(
            fill_id=f"{plan.plan_id}_entry",
            plan_id=plan.plan_id,
            symbol=symbol,
            stage=ExecutionFillStage.ENTRY,
            fill_ts=base_ts,
            price=100.1,
            qty=1.0,
            fee=0.01,
            payload={"source": "test"},
        )

        close = engine.ingest_execution_fill(
            fill_id=f"{plan.plan_id}_close",
            plan_id=plan.plan_id,
            symbol=symbol,
            stage=ExecutionFillStage.CLOSED,
            fill_ts=base_ts + timedelta(minutes=10),
            price=100.4,
            qty=1.0,
            fee=0.01,
            payload={
                "classification_after_exit": "acceptance_confirmed",
                "trigger_detail": {"mixed_score": 0.61},
            },
        )
        assert close["accepted"] is True
        assert close["exit_reason"] == "information_failure"

        refreshed = db.get(Plan, plan.plan_id)
        assert refreshed is not None
        assert refreshed.validity["final_exit_reason"] == "information_failure"
        assert refreshed.validity["final_exit_classification_after"] == "acceptance_confirmed"
        assert refreshed.validity["final_exit_trigger_detail"]["narrative_invalidated"] is True


def test_position_state_machine_infers_time_failure_from_family_time_stop() -> None:
    init_db()
    symbol = f"PSM{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 3}USDC"

    with SessionLocal() as db:
        plan = _seed_plan(db, symbol=symbol, plan_id=f"{symbol}_p4")
        engine = StrategyEngine(db)
        base_ts = datetime.now(timezone.utc)

        engine.ingest_execution_fill(
            fill_id=f"{plan.plan_id}_entry",
            plan_id=plan.plan_id,
            symbol=symbol,
            stage=ExecutionFillStage.ENTRY,
            fill_ts=base_ts,
            price=100.0,
            qty=1.0,
            fee=0.01,
            payload={"source": "test"},
        )

        close = engine.ingest_execution_fill(
            fill_id=f"{plan.plan_id}_close",
            plan_id=plan.plan_id,
            symbol=symbol,
            stage=ExecutionFillStage.CLOSED,
            fill_ts=base_ts + timedelta(minutes=31),
            price=100.3,
            qty=1.0,
            fee=0.01,
            payload={"notes": "no follow through"},
        )
        assert close["accepted"] is True
        assert close["exit_reason"] == "time_failure"

        refreshed = db.get(Plan, plan.plan_id)
        assert refreshed is not None
        assert refreshed.validity["final_exit_reason"] == "time_failure"
        assert refreshed.validity["final_exit_held_bars"] >= 6
        assert refreshed.validity["final_exit_trigger_detail"]["max_allowed_bars"] == 5
