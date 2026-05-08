from __future__ import annotations

import pytest

from app.integrations.binance_futures import BinanceFuturesClient


def test_parse_kline_row() -> None:
    row = [
        1700000000000,
        "100.0",
        "101.5",
        "99.3",
        "101.0",
        "1234.56",
        1700000299999,
        "0",
        "0",
        "0",
        "0",
        "0",
    ]
    k = BinanceFuturesClient._parse_kline_row("BTCUSDC", "5m", row)

    assert k.symbol == "BTCUSDC"
    assert k.interval == "5m"
    assert k.o == 100.0
    assert k.h == 101.5
    assert k.l == 99.3
    assert k.c == 101.0
    assert k.v == 1234.56
    assert k.open_time < k.close_time


def test_submit_order_uses_test_endpoint_and_echoes_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_signed_request(self, method: str, path: str, params: dict[str, object]) -> dict[str, object]:
        captured["method"] = method
        captured["path"] = path
        captured["params"] = params
        return {}

    monkeypatch.setattr(BinanceFuturesClient, "_signed_request", fake_signed_request)
    client = BinanceFuturesClient(
        api_key="key",
        api_secret="secret",
        live_trade_enabled=False,
    )

    payload = client.submit_order(
        symbol="BTCUSDC",
        side="SELL",
        order_type="LIMIT",
        quantity=0.01,
        price=50000.0,
        time_in_force="GTC",
        reduce_only=True,
        client_order_id="test-order-1",
        live=False,
    )

    assert captured["method"] == "POST"
    assert captured["path"] == "/fapi/v1/order/test"
    assert captured["params"] == {
        "symbol": "BTCUSDC",
        "side": "SELL",
        "type": "LIMIT",
        "quantity": 0.01,
        "timeInForce": "GTC",
        "price": 50000.0,
        "reduceOnly": True,
        "newClientOrderId": "test-order-1",
        "newOrderRespType": "RESULT",
    }
    assert payload["status"] == "TEST_ACCEPTED"
    assert payload["clientOrderId"] == "test-order-1"


def test_submit_order_live_disabled_raises() -> None:
    client = BinanceFuturesClient(
        api_key="key",
        api_secret="secret",
        live_trade_enabled=False,
    )

    with pytest.raises(RuntimeError, match="binance_live_orders_disabled"):
        client.submit_order(
            symbol="BTCUSDC",
            side="BUY",
            order_type="MARKET",
            quantity=0.01,
            live=True,
        )


def test_query_and_cancel_require_identifier() -> None:
    client = BinanceFuturesClient(
        api_key="key",
        api_secret="secret",
        live_trade_enabled=True,
    )

    with pytest.raises(ValueError, match="order_id_or_client_order_id_required"):
        client.query_order(symbol="BTCUSDC")
    with pytest.raises(ValueError, match="order_id_or_client_order_id_required"):
        client.cancel_order(symbol="BTCUSDC")


def test_user_stream_listen_key_routes_use_keyed_request(monkeypatch) -> None:
    captured: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_keyed_request(self, method: str, path: str, params: dict[str, object] | None = None) -> dict[str, object]:
        captured.append((method, path, params))
        if method == "POST":
            return {"listenKey": "lk-demo"}
        return {}

    monkeypatch.setattr(BinanceFuturesClient, "_keyed_request", fake_keyed_request)
    client = BinanceFuturesClient(api_key="key", api_secret="secret", live_trade_enabled=True)

    created = client.create_user_stream_listen_key()
    kept = client.keepalive_user_stream_listen_key("lk-demo")
    closed = client.close_user_stream_listen_key("lk-demo")

    assert created["listen_key"] == "lk-demo"
    assert kept["listen_key"] == "lk-demo"
    assert closed["closed"] is True
    assert captured == [
        ("POST", "/fapi/v1/listenKey", None),
        ("PUT", "/fapi/v1/listenKey", {"listenKey": "lk-demo"}),
        ("DELETE", "/fapi/v1/listenKey", {"listenKey": "lk-demo"}),
    ]


def test_fetch_position_risk_uses_signed_request(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_signed_request(self, method: str, path: str, params: dict[str, object]) -> list[dict[str, object]]:
        captured["method"] = method
        captured["path"] = path
        captured["params"] = params
        return [{"symbol": "BTCUSDC", "positionAmt": "0.01"}]

    monkeypatch.setattr(BinanceFuturesClient, "_signed_request", fake_signed_request)
    client = BinanceFuturesClient(api_key="key", api_secret="secret", live_trade_enabled=True)

    payload = client.fetch_position_risk(symbol="BTCUSDC")

    assert payload == [{"symbol": "BTCUSDC", "positionAmt": "0.01"}]
    assert captured == {
        "method": "GET",
        "path": "/fapi/v2/positionRisk",
        "params": {"symbol": "BTCUSDC"},
    }


def test_fetch_symbol_trading_rules_uses_exchange_info(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_public_request(self, path: str, params: dict[str, object] | None = None) -> dict[str, object]:
        captured["path"] = path
        captured["params"] = params
        return {
            "symbols": [
                {
                    "symbol": "XRPUSDC",
                    "pricePrecision": 5,
                    "quantityPrecision": 1,
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": "0.00010"},
                        {"filterType": "LOT_SIZE", "minQty": "0.1", "stepSize": "0.1"},
                    ],
                }
            ]
        }

    monkeypatch.setattr(BinanceFuturesClient, "_public_request", fake_public_request)
    client = BinanceFuturesClient()

    rules = client.fetch_symbol_trading_rules("xrpusdc")

    assert captured == {
        "path": "/fapi/v1/exchangeInfo",
        "params": {"symbol": "XRPUSDC"},
    }
    assert rules.symbol == "XRPUSDC"
    assert rules.quantity_step == 0.1
    assert rules.min_quantity == 0.1
    assert rules.tick_size == 0.0001
    assert rules.price_precision == 5
    assert rules.quantity_precision == 1


def test_normalize_user_stream_order_trade_update_and_account_update() -> None:
    trade_update = BinanceFuturesClient.normalize_user_stream_message(
        {
            "e": "ORDER_TRADE_UPDATE",
            "E": 1700000000000,
            "o": {
                "s": "BTCUSDC",
                "i": 12345,
                "c": "test-order-1",
                "S": "BUY",
                "o": "LIMIT",
                "f": "GTC",
                "X": "FILLED",
                "x": "TRADE",
                "R": False,
                "ps": "LONG",
                "l": "0.01",
                "L": "50000.5",
                "z": "0.01",
                "q": "0.01",
                "ap": "50000.5",
                "rp": "0",
                "t": 998877,
            },
        }
    )
    assert trade_update["kind"] == "order_trade_update"
    assert trade_update["symbol"] == "BTCUSDC"
    assert trade_update["client_order_id"] == "test-order-1"
    assert trade_update["last_fill_qty"] == 0.01
    assert trade_update["trade_id"] == 998877

    account_update = BinanceFuturesClient.normalize_user_stream_message(
        {
            "e": "ACCOUNT_UPDATE",
            "E": 1700000000000,
            "a": {
                "m": "ORDER",
                "P": [
                    {
                        "s": "BTCUSDC",
                        "ps": "LONG",
                        "pa": "0.01",
                        "ep": "50000",
                        "bep": "50001",
                        "up": "12.5",
                        "mt": "isolated",
                        "iw": "100.0",
                    }
                ],
            },
        }
    )
    assert account_update["kind"] == "account_update"
    assert account_update["event_reason"] == "ORDER"
    assert account_update["positions"][0]["position_key"] == "BTCUSDC:LONG"
    assert account_update["positions"][0]["position_amt"] == 0.01
