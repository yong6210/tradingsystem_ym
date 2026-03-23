from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.db.models import Plan
from app.db.session import SessionLocal, init_db

client = TestClient(app)


def _seed_plan(symbol: str, plan_id: str) -> None:
    with SessionLocal() as db:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        db.add(
            Plan(
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
                state="ARMED",
                valid_from=now - timedelta(minutes=15),
                valid_until=now + timedelta(hours=6),
                strategy_version="v1",
            )
        )
        db.commit()


def test_execution_fill_api_updates_state_and_is_idempotent() -> None:
    init_db()
    symbol = f"APIFILL{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    plan_id = f"{symbol}_p1"
    _seed_plan(symbol, plan_id)

    payload = {
        "fill_id": f"{plan_id}_f1",
        "plan_id": plan_id,
        "symbol": symbol,
        "stage": "ENTRY",
        "fill_ts": datetime.now(timezone.utc).isoformat(),
        "price": 100.1,
        "qty": 1.0,
        "fee": 0.01,
        "payload": {"source": "api_test"},
    }

    first = client.post("/internal/execution/fills", json=payload)
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["accepted"] is True
    assert first_payload["duplicate"] is False
    assert first_payload["to_state"] == "ENTERED"

    second = client.post("/internal/execution/fills", json=payload)
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["accepted"] is True
    assert second_payload["duplicate"] is True
    assert second_payload["reason"] == "duplicate_fill_id"


def test_execution_fill_api_accepts_explicit_exit_reason_fields() -> None:
    init_db()
    symbol = f"APIFILL{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 1}USDC"
    plan_id = f"{symbol}_p2"
    _seed_plan(symbol, plan_id)

    client.post(
        "/internal/execution/fills",
        json={
            "fill_id": f"{plan_id}_entry",
            "plan_id": plan_id,
            "symbol": symbol,
            "stage": "ENTRY",
            "fill_ts": datetime.now(timezone.utc).isoformat(),
            "price": 100.1,
            "qty": 1.0,
            "fee": 0.01,
            "payload": {"source": "api_test"},
        },
    )

    close = client.post(
        "/internal/execution/fills",
        json={
            "fill_id": f"{plan_id}_close",
            "plan_id": plan_id,
            "symbol": symbol,
            "stage": "CLOSED",
            "fill_ts": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
            "price": 100.3,
            "qty": 1.0,
            "fee": 0.01,
            "exit_reason": "information_failure",
            "classification_after_exit": "acceptance_confirmed",
            "trigger_detail": {"mixed_score": 0.42},
        },
    )
    assert close.status_code == 200
    close_payload = close.json()
    assert close_payload["accepted"] is True
    assert close_payload["exit_reason"] == "information_failure"


def test_execution_fill_api_returns_404_for_unknown_plan() -> None:
    init_db()
    unknown = client.post(
        "/internal/execution/fills",
        json={
            "fill_id": f"missing_{int(datetime.now(timezone.utc).timestamp())}",
            "plan_id": "missing_plan",
            "symbol": "BTCUSDC",
            "stage": "ENTRY",
            "fill_ts": datetime.now(timezone.utc).isoformat(),
            "price": 100.0,
            "qty": 1.0,
            "fee": 0.0,
            "payload": {},
        },
    )
    assert unknown.status_code == 404
