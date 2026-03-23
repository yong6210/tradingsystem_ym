from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_submit_binance_order_route(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.submit_binance_order",
        lambda self, **kwargs: {
            "action": "submit",
            "mode": "test",
            "requested_live": False,
            "live_enabled": False,
            "test_order": True,
            "symbol": kwargs["symbol"],
            "plan_id": kwargs["plan_id"],
            "order_id": None,
            "client_order_id": kwargs["client_order_id"] or "auto-order-1",
            "status": "TEST_ACCEPTED",
            "side": kwargs["side"],
            "order_type": kwargs["order_type"],
            "price": kwargs["price"],
            "orig_qty": kwargs["quantity"],
            "executed_qty": 0.0,
            "reduce_only": kwargs["reduce_only"],
            "time_in_force": kwargs["time_in_force"],
            "raw": {"status": "TEST_ACCEPTED"},
        },
    )

    response = client.post(
        "/internal/binance/order",
        json={
            "symbol": "BTCUSDC",
            "side": "SELL",
            "order_type": "LIMIT",
            "quantity": 0.01,
            "price": 50000.0,
            "time_in_force": "GTC",
            "reduce_only": True,
            "plan_id": "plan_zone_demo_limit",
            "live": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "submit"
    assert payload["mode"] == "test"
    assert payload["test_order"] is True
    assert payload["status"] == "TEST_ACCEPTED"
    assert payload["plan_id"] == "plan_zone_demo_limit"


def test_query_and_cancel_binance_order_routes(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.query_binance_order",
        lambda self, **kwargs: {
            "action": "query",
            "mode": "live",
            "requested_live": True,
            "live_enabled": True,
            "test_order": False,
            "symbol": kwargs["symbol"],
            "plan_id": None,
            "order_id": kwargs["order_id"],
            "client_order_id": kwargs["client_order_id"] or "",
            "status": "NEW",
            "side": "BUY",
            "order_type": "LIMIT",
            "price": 50000.0,
            "orig_qty": 0.01,
            "executed_qty": 0.0,
            "reduce_only": False,
            "time_in_force": "GTC",
            "raw": {"status": "NEW"},
        },
    )
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.cancel_binance_order",
        lambda self, **kwargs: {
            "action": "cancel",
            "mode": "live",
            "requested_live": True,
            "live_enabled": True,
            "test_order": False,
            "symbol": kwargs["symbol"],
            "plan_id": None,
            "order_id": kwargs["order_id"],
            "client_order_id": kwargs["client_order_id"] or "",
            "status": "CANCELED",
            "side": "BUY",
            "order_type": "LIMIT",
            "price": 50000.0,
            "orig_qty": 0.01,
            "executed_qty": 0.0,
            "reduce_only": False,
            "time_in_force": "GTC",
            "raw": {"status": "CANCELED"},
        },
    )

    query_response = client.get("/internal/binance/order?symbol=BTCUSDC&order_id=12345")
    assert query_response.status_code == 200
    assert query_response.json()["action"] == "query"
    assert query_response.json()["status"] == "NEW"

    cancel_response = client.delete("/internal/binance/order?symbol=BTCUSDC&order_id=12345")
    assert cancel_response.status_code == 200
    assert cancel_response.json()["action"] == "cancel"
    assert cancel_response.json()["status"] == "CANCELED"


def test_submit_binance_order_route_maps_runtime_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.submit_binance_order",
        lambda self, **kwargs: (_ for _ in ()).throw(RuntimeError("binance_live_orders_disabled")),
    )

    response = client.post(
        "/internal/binance/order",
        json={
            "symbol": "BTCUSDC",
            "side": "BUY",
            "order_type": "MARKET",
            "quantity": 0.01,
            "live": True,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "binance_live_orders_disabled"
