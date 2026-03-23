from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_binance_user_stream_and_positions_routes(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.create_binance_user_stream_listen_key",
        lambda self: {"action": "create", "listen_key": "lk-demo-1", "raw": {"listenKey": "lk-demo-1"}},
    )
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.keepalive_binance_user_stream_listen_key",
        lambda self, **kwargs: {"action": "keepalive", "listen_key": kwargs["listen_key"], "raw": {}},
    )
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.close_binance_user_stream_listen_key",
        lambda self, **kwargs: {"action": "close", "listen_key": kwargs["listen_key"], "closed": True, "raw": {}},
    )
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.process_binance_user_stream",
        lambda self, **kwargs: {
            "listen_key": kwargs["listen_key"],
            "processed": 2,
            "order_updates": 1,
            "account_updates": 1,
            "fills_ingested": 1,
            "positions_synced": 1,
            "last_event_ts": "2026-03-09T00:00:00+00:00",
            "events": [{"kind": "order_trade_update"}, {"kind": "account_update"}],
        },
    )
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.ingest_binance_user_stream_event",
        lambda self, **kwargs: {
            "accepted": True,
            "kind": "order_trade_update",
            "event_type": "ORDER_TRADE_UPDATE",
            "symbol": "BTCUSDC",
            "plan_id": "plan_zone_demo",
            "client_order_id": "demo-order-1",
            "order_id": 12345,
            "order_snapshot": {"status": "FILLED"},
            "position_sync": {"synced": 1},
            "fill_ingest": {"accepted": True, "stage": "ENTRY"},
        },
    )
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.sync_binance_positions",
        lambda self, **kwargs: {
            "symbol": kwargs.get("symbol"),
            "synced": 1,
            "open_positions": 1,
            "positions": [
                {
                    "position_key": "BTCUSDC:LONG",
                    "symbol": "BTCUSDC",
                    "position_side": "LONG",
                    "position_amt": 0.01,
                    "entry_price": 50000.0,
                    "break_even_price": 50001.0,
                    "mark_price": 50010.0,
                    "liquidation_price": 0.0,
                    "unrealized_pnl": 1.0,
                    "notional": 500.1,
                    "leverage": 5,
                    "margin_type": "isolated",
                    "isolated_wallet": 100.0,
                    "update_ts": "2026-03-09T00:00:00+00:00",
                    "raw": {},
                }
            ],
        },
    )
    monkeypatch.setattr(
        "app.services.strategy_engine.StrategyEngine.list_binance_positions",
        lambda self, **kwargs: {
            "symbol": kwargs.get("symbol"),
            "open_only": kwargs.get("open_only", False),
            "count": 1,
            "positions": [
                {
                    "position_key": "BTCUSDC:LONG",
                    "symbol": "BTCUSDC",
                    "position_side": "LONG",
                    "position_amt": 0.01,
                    "entry_price": 50000.0,
                    "break_even_price": 50001.0,
                    "mark_price": 50010.0,
                    "liquidation_price": 0.0,
                    "unrealized_pnl": 1.0,
                    "notional": 500.1,
                    "leverage": 5,
                    "margin_type": "isolated",
                    "isolated_wallet": 100.0,
                    "update_ts": "2026-03-09T00:00:00+00:00",
                    "raw": {},
                }
            ],
        },
    )

    create_resp = client.post("/internal/binance/user-stream/listen-key")
    assert create_resp.status_code == 200
    assert create_resp.json()["listen_key"] == "lk-demo-1"

    keepalive_resp = client.put("/internal/binance/user-stream/listen-key?listen_key=lk-demo-1")
    assert keepalive_resp.status_code == 200
    assert keepalive_resp.json()["action"] == "keepalive"

    close_resp = client.delete("/internal/binance/user-stream/listen-key?listen_key=lk-demo-1")
    assert close_resp.status_code == 200
    assert close_resp.json()["closed"] is True

    process_resp = client.post(
        "/internal/binance/user-stream/process",
        json={"listen_key": "lk-demo-1", "max_events": 5, "timeout_seconds": 10.0},
    )
    assert process_resp.status_code == 200
    assert process_resp.json()["processed"] == 2

    event_resp = client.post(
        "/internal/binance/user-stream/event",
        json={"payload": {"e": "ORDER_TRADE_UPDATE"}},
    )
    assert event_resp.status_code == 200
    assert event_resp.json()["accepted"] is True
    assert event_resp.json()["fill_ingest"]["stage"] == "ENTRY"

    sync_resp = client.post("/internal/binance/positions/sync?symbol=BTCUSDC")
    assert sync_resp.status_code == 200
    assert sync_resp.json()["synced"] == 1

    list_resp = client.get("/internal/binance/positions?symbol=BTCUSDC&open_only=true")
    assert list_resp.status_code == 200
    assert list_resp.json()["count"] == 1
