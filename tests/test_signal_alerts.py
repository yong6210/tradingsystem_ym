from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.enums import ExecutionFillStage
from app.db.models import AlertSubscription, Plan
from app.db.session import SessionLocal, init_db
from app.services.strategy_engine import StrategyEngine


def _seed_plan(db, *, symbol: str, plan_id: str, direction: str = "long") -> Plan:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    plan = Plan(
        plan_id=plan_id,
        zone_id=f"{plan_id}_zone",
        symbol=symbol,
        timeframe="5m",
        direction=direction,
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
            "strategy_family": "sweep_reversal",
            "strategy_grade": "A",
            "expected_summary": "win≈52.0%, EV≈+0.18R, TP1≈61.0%, TP2≈44.0%, TP3≈29.0%",
            "strategy_family_time_stop_min_bars": 3,
            "strategy_family_time_stop_max_bars": 5,
            "reaction_classification": "rejection_confirmed",
        },
        state="ARMED",
        valid_from=now - timedelta(minutes=15),
        valid_until=now + timedelta(hours=6),
        strategy_version="v1",
    )
    db.add(plan)
    db.commit()
    return plan


def test_pre_entry_touch_and_confirm_alerts_emit_from_subscriptions(monkeypatch) -> None:
    init_db()
    symbol = f"SIGTOUCH{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    plan_id = f"{symbol}_p1"

    with SessionLocal() as db:
        plan = _seed_plan(db, symbol=symbol, plan_id=plan_id)
        engine = StrategyEngine(db)
        engine.subscribe_alert(symbol=symbol, channel="discord", alert_type="touch", plan_id=plan_id, payload={})
        engine.subscribe_alert(symbol=symbol, channel="discord", alert_type="confirm", plan_id=plan_id, payload={})

        calls: list[dict] = []

        def _fake_dispatch(*, channel: str, alert_type: str, symbol: str, payload: dict) -> dict:
            calls.append({"channel": channel, "alert_type": alert_type, "symbol": symbol, "payload": dict(payload)})
            return {
                "channel": channel,
                "delivered": True,
                "skipped": False,
                "reason": "delivered",
                "status_code": 204,
                "target": f"{channel}:unit-test",
                "latency_ms": 1.2,
                "ts": datetime.now(timezone.utc).isoformat(),
            }

        monkeypatch.setattr(engine.notification_dispatcher, "dispatch", _fake_dispatch)

        summary = engine._emit_pre_entry_plan_alerts(
            symbol=symbol,
            plans=[plan],
            current_price=100.0,
            candle_low=99.8,
            candle_high=100.2,
            atr_reference=1.0,
            event_ts=datetime.now(timezone.utc),
        )
        db.commit()

        assert summary["touch"] == 1
        assert summary["confirm"] == 1
        assert summary["emitted_total"] == 2
        assert [row["alert_type"] for row in calls] == ["touch", "confirm"]
        assert "signal-only no-order touch:" in calls[0]["payload"]["message"]
        assert "signal-only no-order confirm:" in calls[1]["payload"]["message"]
        assert calls[0]["payload"]["order_submission_expected"] is False
        assert calls[0]["payload"]["order_truth"] == "pre_entry_signal_only"
        assert calls[1]["payload"]["order_submission_expected"] is False
        assert calls[1]["payload"]["order_truth"] == "pre_entry_signal_only"

        emitted = list(
            db.scalars(
                select(AlertSubscription).where(
                    AlertSubscription.symbol == symbol,
                    AlertSubscription.plan_id == plan_id,
                    AlertSubscription.type.in_(["touch", "confirm"]),
                )
            )
        )
        assert sum(1 for row in emitted if (row.payload or {}).get("subscription_active")) == 2
        assert sum(1 for row in emitted if (row.payload or {}).get("subscription_alert")) == 2
        assert sum(1 for row in emitted if (row.payload or {}).get("order_submission_expected") is False) == 2


def test_signal_alert_channel_dedupe_and_cooldown(monkeypatch) -> None:
    init_db()
    symbol = f"SIGNEAR{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    plan_id = f"{symbol}_p1"

    with SessionLocal() as db:
        _seed_plan(db, symbol=symbol, plan_id=plan_id)
        engine = StrategyEngine(db)
        engine.subscribe_alert(symbol=symbol, channel="discord", alert_type="near", plan_id=None, payload={})
        engine.subscribe_alert(symbol=symbol, channel="discord", alert_type="near", plan_id=plan_id, payload={})

        calls: list[dict] = []

        def _fake_dispatch(*, channel: str, alert_type: str, symbol: str, payload: dict) -> dict:
            calls.append({"channel": channel, "alert_type": alert_type, "symbol": symbol, "payload": dict(payload)})
            return {
                "channel": channel,
                "delivered": True,
                "skipped": False,
                "reason": "delivered",
                "status_code": 204,
                "target": f"{channel}:unit-test",
                "latency_ms": 1.2,
                "ts": datetime.now(timezone.utc).isoformat(),
            }

        monkeypatch.setattr(engine.notification_dispatcher, "dispatch", _fake_dispatch)

        first = engine._emit_subscription_alerts(
            symbol=symbol,
            plan_id=plan_id,
            alert_type="near",
            event_ts=datetime.now(timezone.utc),
            payload={
                "symbol": symbol,
                "plan_id": plan_id,
                "direction": "long",
                "entry_model": "CONFIRM",
                "event_price": 99.95,
                "entry_price": 100.0,
                "distance_bps": 5.0,
                "distance_atr": 0.05,
                "expected_summary": "win≈52.0%, EV≈+0.18R",
            },
        )
        second = engine._emit_subscription_alerts(
            symbol=symbol,
            plan_id=plan_id,
            alert_type="near",
            event_ts=datetime.now(timezone.utc),
            payload={
                "symbol": symbol,
                "plan_id": plan_id,
                "direction": "long",
                "entry_model": "CONFIRM",
                "event_price": 99.94,
                "entry_price": 100.0,
                "distance_bps": 6.0,
                "distance_atr": 0.06,
                "expected_summary": "win≈52.0%, EV≈+0.18R",
            },
        )
        db.commit()

        assert first["matched"] == 1
        assert first["emitted"] == 1
        assert second["matched"] == 1
        assert second["emitted"] == 0
        assert second["cooldown"] == 1
        assert len(calls) == 1


def test_session_impulse_retest_confirm_message_uses_prop_manual_format(monkeypatch) -> None:
    init_db()
    symbol = f"SIGPROP{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    plan_id = f"{symbol}_p1"

    with SessionLocal() as db:
        plan = _seed_plan(db, symbol=symbol, plan_id=plan_id)
        plan.validity = {
            **dict(plan.validity or {}),
            "strategy_family": "session_impulse_retest",
            "strategy_grade": "A",
            "expected_summary": "session_impulse_retest benchmark | win≈67.0% EV≈+0.65R | tier=core",
            "strategy_family_time_stop_max_bars": 8,
        }
        db.add(plan)
        db.commit()

        engine = StrategyEngine(db)
        engine.subscribe_alert(symbol=symbol, channel="discord", alert_type="confirm", plan_id=plan_id, payload={})

        calls: list[dict] = []

        def _fake_dispatch(*, channel: str, alert_type: str, symbol: str, payload: dict) -> dict:
            calls.append({"channel": channel, "alert_type": alert_type, "symbol": symbol, "payload": dict(payload)})
            return {
                "channel": channel,
                "delivered": True,
                "skipped": False,
                "reason": "delivered",
                "status_code": 204,
                "target": f"{channel}:unit-test",
                "latency_ms": 1.2,
                "ts": datetime.now(timezone.utc).isoformat(),
            }

        monkeypatch.setattr(engine.notification_dispatcher, "dispatch", _fake_dispatch)

        summary = engine._emit_pre_entry_plan_alerts(
            symbol=symbol,
            plans=[plan],
            current_price=100.0,
            candle_low=99.8,
            candle_high=100.2,
            atr_reference=1.0,
            event_ts=datetime.now(timezone.utc),
        )

        assert summary["confirm"] == 1
        assert len(calls) == 1
        message = str(calls[0]["payload"]["message"])
        assert message.startswith("signal-only no-order confirm:")
        assert "LONG e=100.0000 sl=98.8000 tp1=101.0000 tp2=102.0000" in message
        assert "exp=" in message


def test_ingest_execution_fill_emits_entry_tp_and_closed_alerts(monkeypatch) -> None:
    init_db()
    symbol = f"SIGFILL{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    plan_id = f"{symbol}_p1"

    with SessionLocal() as db:
        _seed_plan(db, symbol=symbol, plan_id=plan_id)
        engine = StrategyEngine(db)
        engine.subscribe_alert(symbol=symbol, channel="discord", alert_type="entry", plan_id=plan_id, payload={})
        engine.subscribe_alert(symbol=symbol, channel="discord", alert_type="tp", plan_id=plan_id, payload={})
        engine.subscribe_alert(symbol=symbol, channel="discord", alert_type="closed", plan_id=plan_id, payload={})

        calls: list[dict] = []

        def _fake_dispatch(*, channel: str, alert_type: str, symbol: str, payload: dict) -> dict:
            calls.append({"channel": channel, "alert_type": alert_type, "symbol": symbol, "payload": dict(payload)})
            return {
                "channel": channel,
                "delivered": True,
                "skipped": False,
                "reason": "delivered",
                "status_code": 204,
                "target": f"{channel}:unit-test",
                "latency_ms": 1.2,
                "ts": datetime.now(timezone.utc).isoformat(),
            }

        monkeypatch.setattr(engine.notification_dispatcher, "dispatch", _fake_dispatch)

        entry = engine.ingest_execution_fill(
            fill_id=f"{plan_id}_entry",
            plan_id=plan_id,
            symbol=symbol,
            stage=ExecutionFillStage.ENTRY,
            fill_ts=datetime.now(timezone.utc),
            price=100.1,
            qty=1.0,
            fee=0.01,
            payload={"source": "unit_test"},
        )
        closed = engine.ingest_execution_fill(
            fill_id=f"{plan_id}_closed",
            plan_id=plan_id,
            symbol=symbol,
            stage=ExecutionFillStage.CLOSED,
            fill_ts=datetime.now(timezone.utc) + timedelta(minutes=15),
            price=101.0,
            qty=1.0,
            fee=0.01,
            payload={"exit_reason": "target_tp1", "realized_r": 0.83},
        )

        assert entry["accepted"] is True
        assert closed["accepted"] is True
        assert [row["alert_type"] for row in calls] == ["entry", "closed", "tp"]
        assert "fill=" in calls[0]["payload"]["message"]
        assert "position closed:" in calls[1]["payload"]["message"]
        assert "target exit:" in calls[2]["payload"]["message"]


def test_duplicate_fill_does_not_reemit_fill_stage_alerts(monkeypatch) -> None:
    init_db()
    symbol = f"SIGDUP{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    plan_id = f"{symbol}_p1"
    fill_ts = datetime.now(timezone.utc)

    with SessionLocal() as db:
        _seed_plan(db, symbol=symbol, plan_id=plan_id)
        engine = StrategyEngine(db)
        engine.subscribe_alert(symbol=symbol, channel="discord", alert_type="closed", plan_id=plan_id, payload={})
        engine.subscribe_alert(symbol=symbol, channel="discord", alert_type="tp", plan_id=plan_id, payload={})

        calls: list[dict] = []

        def _fake_dispatch(*, channel: str, alert_type: str, symbol: str, payload: dict) -> dict:
            calls.append({"channel": channel, "alert_type": alert_type, "symbol": symbol, "payload": dict(payload)})
            return {
                "channel": channel,
                "delivered": True,
                "skipped": False,
                "reason": "delivered",
                "status_code": 204,
                "target": f"{channel}:unit-test",
                "latency_ms": 1.2,
                "ts": datetime.now(timezone.utc).isoformat(),
            }

        monkeypatch.setattr(engine.notification_dispatcher, "dispatch", _fake_dispatch)

        first = engine.ingest_execution_fill(
            fill_id=f"{plan_id}_closed",
            plan_id=plan_id,
            symbol=symbol,
            stage=ExecutionFillStage.CLOSED,
            fill_ts=fill_ts,
            price=101.0,
            qty=1.0,
            fee=0.01,
            payload={"exit_reason": "target_tp1", "realized_r": 1.0},
        )
        second = engine.ingest_execution_fill(
            fill_id=f"{plan_id}_closed",
            plan_id=plan_id,
            symbol=symbol,
            stage=ExecutionFillStage.CLOSED,
            fill_ts=fill_ts,
            price=101.0,
            qty=1.0,
            fee=0.01,
            payload={"exit_reason": "target_tp1", "realized_r": 1.0},
        )

        assert first["accepted"] is True
        assert second["accepted"] is True
        assert second["duplicate"] is True
        assert [row["alert_type"] for row in calls] == ["closed", "tp"]


def test_ingest_execution_fill_emits_partial_exit_and_stop_loss_alerts(monkeypatch) -> None:
    init_db()
    symbol = f"SIGEXIT{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    plan_id = f"{symbol}_p1"

    with SessionLocal() as db:
        _seed_plan(db, symbol=symbol, plan_id=plan_id)
        engine = StrategyEngine(db)
        engine.subscribe_alert(symbol=symbol, channel="discord", alert_type="partial_exit", plan_id=plan_id, payload={})
        engine.subscribe_alert(symbol=symbol, channel="discord", alert_type="sl", plan_id=plan_id, payload={})

        calls: list[dict] = []

        def _fake_dispatch(*, channel: str, alert_type: str, symbol: str, payload: dict) -> dict:
            calls.append({"channel": channel, "alert_type": alert_type, "symbol": symbol, "payload": dict(payload)})
            return {
                "channel": channel,
                "delivered": True,
                "skipped": False,
                "reason": "delivered",
                "status_code": 204,
                "target": f"{channel}:unit-test",
                "latency_ms": 1.2,
                "ts": datetime.now(timezone.utc).isoformat(),
            }

        monkeypatch.setattr(engine.notification_dispatcher, "dispatch", _fake_dispatch)

        partial = engine.ingest_execution_fill(
            fill_id=f"{plan_id}_partial",
            plan_id=plan_id,
            symbol=symbol,
            stage=ExecutionFillStage.PARTIAL_EXIT,
            fill_ts=datetime.now(timezone.utc),
            price=101.0,
            qty=0.4,
            fee=0.01,
            payload={"exit_reason": "manual_partial", "realized_r": 0.35},
        )
        stopped = engine.ingest_execution_fill(
            fill_id=f"{plan_id}_stop",
            plan_id=plan_id,
            symbol=symbol,
            stage=ExecutionFillStage.CLOSED,
            fill_ts=datetime.now(timezone.utc) + timedelta(minutes=15),
            price=98.8,
            qty=0.6,
            fee=0.01,
            payload={"exit_reason": "stop_loss", "realized_r": -1.0},
        )

        assert partial["accepted"] is True
        assert stopped["accepted"] is True
        assert [row["alert_type"] for row in calls] == ["partial_exit", "sl"]
        assert all(row["payload"]["order_truth"] == "execution_fill_truth" for row in calls)
        assert "partial exit:" in calls[0]["payload"]["message"]
        assert "stop exit:" in calls[1]["payload"]["message"]


def test_tv_webhook_fanouts_confirm_subscription(monkeypatch) -> None:
    init_db()
    symbol = f"SIGTV{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    plan_id = f"{symbol}_p1"

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        engine.subscribe_alert(symbol=symbol, channel="discord", alert_type="confirm", plan_id=plan_id, payload={})

        calls: list[dict] = []

        def _fake_dispatch(*, channel: str, alert_type: str, symbol: str, payload: dict) -> dict:
            calls.append({"channel": channel, "alert_type": alert_type, "symbol": symbol, "payload": dict(payload)})
            return {
                "channel": channel,
                "delivered": True,
                "skipped": False,
                "reason": "delivered",
                "status_code": 204,
                "target": f"{channel}:unit-test",
                "latency_ms": 1.2,
                "ts": datetime.now(timezone.utc).isoformat(),
            }

        monkeypatch.setattr(engine.notification_dispatcher, "dispatch", _fake_dispatch)

        payload = engine.tv_webhook(
            event="confirm",
            symbol=symbol,
            price=100.25,
            ts=datetime.now(timezone.utc),
            payload={
                "plan_id": plan_id,
                "direction": "long",
                "entry_model": "CONFIRM",
                "entry_price": 100.0,
                "expected_summary": "win≈52.0%, EV≈+0.18R",
            },
        )
        assert payload["accepted"] is True
        assert payload["subscription_alerts"]["emitted"] == 1
        assert len(calls) == 1
        assert calls[0]["alert_type"] == "confirm"
        assert "tv webhook confirm:" in calls[0]["payload"]["message"]
        assert calls[0]["payload"]["order_submission_expected"] is False
        assert calls[0]["payload"]["order_truth"] == "pre_entry_signal_only"
