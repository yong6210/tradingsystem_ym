from __future__ import annotations

import pytest
import httpx

from app.integrations.binance_futures import BinanceFuturesClient, BinanceFuturesHTTPError


def test_binance_client_tolerates_malformed_constructor_numeric_values() -> None:
    client = BinanceFuturesClient(timeout_seconds=float("inf"), recv_window=float("inf"))

    assert client.timeout_seconds == 10.0
    assert client.recv_window == 5000


def test_binance_client_parses_string_false_live_trade_flag() -> None:
    client = BinanceFuturesClient(live_trade_enabled="false")

    assert client.live_trade_enabled is False


def test_http_error_message_preserves_binance_reason_without_signed_query() -> None:
    response = httpx.Response(
        400,
        json={"code": -2021, "msg": "Order would immediately trigger."},
        request=httpx.Request(
            "POST",
            "https://fapi.binance.com/fapi/v1/order?timestamp=1779172989091&signature=secret",
        ),
    )

    with pytest.raises(BinanceFuturesHTTPError) as exc_info:
        BinanceFuturesClient._raise_for_status(response, path="/fapi/v1/order")

    exc = exc_info.value
    message = str(exc)
    assert exc.status_code == 400
    assert exc.code == -2021
    assert exc.path == "/fapi/v1/order"
    assert "Order would immediately trigger" in message
    assert "signature" not in message
    assert "timestamp" not in message


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


def test_try_parse_kline_row_skips_malformed_rows() -> None:
    malformed_row = [
        "bad-open-time",
        "100.0",
        "101.5",
        "99.3",
        "101.0",
        "1234.56",
        1700000299999,
    ]

    assert BinanceFuturesClient._try_parse_kline_row("BTCUSDC", "5m", malformed_row) is None
    assert BinanceFuturesClient._try_parse_kline_row("BTCUSDC", "5m", [float("inf"), "100", "101", "99", "100", "1", 1700000299999]) is None
    assert BinanceFuturesClient._try_parse_kline_row("BTCUSDC", "5m", [1700000000000, "0", "0", "0", "0", "1", 1700000299999]) is None
    assert BinanceFuturesClient._try_parse_kline_row("BTCUSDC", "5m", {"bad": "row"}) is None


def test_market_stat_parsers_tolerate_malformed_numeric_fields() -> None:
    funding = BinanceFuturesClient._parse_funding_rate_row(
        "btcusdc",
        {
            "fundingTime": "bad-ts",
            "fundingRate": "nan",
            "markPrice": "inf",
        },
    )
    open_interest = BinanceFuturesClient._parse_open_interest_hist_row(
        "btcusdc",
        "5m",
        {
            "timestamp": "inf",
            "sumOpenInterest": "bad-oi",
            "sumOpenInterestValue": "nan",
        },
    )
    basis = BinanceFuturesClient._parse_basis_kline_row("btcusdc", "5m", ["bad-ts", "bad-open"])
    position = BinanceFuturesClient.normalize_position_risk_row({"symbol": "BTCUSDC", "updateTime": "inf"})

    assert funding.symbol == "BTCUSDC"
    assert funding.funding_rate == 0.0
    assert funding.mark_price == 0.0
    assert open_interest.open_interest == 0.0
    assert open_interest.open_interest_value == 0.0
    assert basis.basis_open == 0.0
    assert basis.basis_close == 0.0
    assert position["update_ts"].timestamp() > 0


def test_fetch_position_risk_filters_malformed_rows(monkeypatch) -> None:
    def fake_signed_request(self, method: str, path: str, params: dict[str, object]) -> list[object]:
        return [
            ["bad-row"],
            {
                "symbol": "BTCUSDC",
                "positionSide": "LONG",
                "positionAmt": "0.01",
                "updateTime": 1700000000000,
            },
        ]

    monkeypatch.setattr(BinanceFuturesClient, "_signed_request", fake_signed_request)

    rows = BinanceFuturesClient(api_key="key", api_secret="secret", live_trade_enabled=True).fetch_position_risk("btcusdc")
    empty = BinanceFuturesClient.normalize_position_risk_row(["bad-row"])

    assert rows == [
        {
            "symbol": "BTCUSDC",
            "positionSide": "LONG",
            "positionAmt": "0.01",
            "updateTime": 1700000000000,
        }
    ]
    assert empty["symbol"] == ""
    assert empty["position_amt"] == 0.0


def test_fetch_futures_balances_filters_malformed_rows(monkeypatch) -> None:
    def fake_signed_request(self, method: str, path: str, params: dict[str, object]) -> list[object]:
        assert method == "GET"
        assert path == "/fapi/v2/balance"
        assert params == {}
        return [
            ["bad-row"],
            {
                "asset": "USDC",
                "balance": "170.0",
                "availableBalance": "169.5",
            },
        ]

    monkeypatch.setattr(BinanceFuturesClient, "_signed_request", fake_signed_request)

    rows = BinanceFuturesClient(api_key="key", api_secret="secret", live_trade_enabled=True).fetch_futures_balances()

    assert rows == [
        {
            "asset": "USDC",
            "balance": "170.0",
            "availableBalance": "169.5",
        }
    ]


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


def test_submit_order_includes_position_side_for_hedge_mode(monkeypatch) -> None:
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
        side="BUY",
        order_type="MARKET",
        quantity=0.01,
        reduce_only=False,
        position_side="LONG",
        client_order_id="test-order-2",
        live=False,
    )

    assert captured["method"] == "POST"
    assert captured["path"] == "/fapi/v1/order/test"
    params = captured["params"]
    assert isinstance(params, dict)
    assert params["positionSide"] == "LONG"
    assert "reduceOnly" not in params
    assert payload["positionSide"] == "LONG"


def test_submit_order_supports_stop_market_close_position(monkeypatch) -> None:
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
        order_type="STOP_MARKET",
        stop_price=98.5,
        close_position=True,
        position_side="LONG",
        working_type="MARK_PRICE",
        client_order_id="sl-test-order-1",
        live=False,
    )

    assert captured["method"] == "POST"
    assert captured["path"] == "/fapi/v1/order/test"
    params = captured["params"]
    assert isinstance(params, dict)
    assert params["type"] == "STOP_MARKET"
    assert params["stopPrice"] == 98.5
    assert params["closePosition"] is True
    assert params["positionSide"] == "LONG"
    assert params["workingType"] == "MARK_PRICE"
    assert "quantity" not in params
    assert "reduceOnly" not in params
    assert payload["closePosition"] is True
    assert payload["stopPrice"] == "98.5"


def test_submit_order_rejects_malformed_exchange_response(monkeypatch) -> None:
    def fake_signed_request(self, method: str, path: str, params: dict[str, object]) -> list[str]:
        return ["bad-response"]

    monkeypatch.setattr(BinanceFuturesClient, "_signed_request", fake_signed_request)
    client = BinanceFuturesClient(
        api_key="key",
        api_secret="secret",
        live_trade_enabled=True,
    )

    with pytest.raises(RuntimeError, match="binance_order_response_malformed:list"):
        client.submit_order(
            symbol="BTCUSDC",
            side="BUY",
            order_type="MARKET",
            quantity=0.01,
            live=True,
        )


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


def test_change_initial_leverage_uses_signed_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_signed_request(self, method: str, path: str, params: dict[str, object]) -> dict[str, object]:
        captured["method"] = method
        captured["path"] = path
        captured["params"] = params
        return {"symbol": "BTCUSDT", "leverage": 10, "maxNotionalValue": "50000000"}

    monkeypatch.setattr(BinanceFuturesClient, "_signed_request", fake_signed_request)
    client = BinanceFuturesClient(api_key="key", api_secret="secret", live_trade_enabled=True)

    payload = client.change_initial_leverage(symbol="btcusdt", leverage=10, live=True)

    assert payload["leverage"] == 10
    assert captured == {
        "method": "POST",
        "path": "/fapi/v1/leverage",
        "params": {"symbol": "BTCUSDT", "leverage": 10},
    }


def test_change_initial_leverage_dry_run_does_not_call_exchange(monkeypatch) -> None:
    def fake_signed_request(self, method: str, path: str, params: dict[str, object]) -> dict[str, object]:
        raise AssertionError("dry run should not call signed endpoint")

    monkeypatch.setattr(BinanceFuturesClient, "_signed_request", fake_signed_request)
    client = BinanceFuturesClient(api_key="key", api_secret="secret", live_trade_enabled=False)

    payload = client.change_initial_leverage(symbol="ethusdt", leverage=10, live=False)

    assert payload == {"symbol": "ETHUSDT", "leverage": 10, "dryRun": True}


def test_change_initial_leverage_live_disabled_raises() -> None:
    client = BinanceFuturesClient(api_key="key", api_secret="secret", live_trade_enabled=False)

    with pytest.raises(RuntimeError, match="binance_live_account_config_disabled"):
        client.change_initial_leverage(symbol="BTCUSDT", leverage=10, live=True)


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


def test_fetch_open_orders_uses_signed_request(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_signed_request(self, method: str, path: str, params: dict[str, object]) -> list[object]:
        captured["method"] = method
        captured["path"] = path
        captured["params"] = params
        return [
            ["bad-row"],
            {
                "symbol": "BTCUSDT",
                "side": "SELL",
                "type": "STOP_MARKET",
                "status": "NEW",
            },
        ]

    monkeypatch.setattr(BinanceFuturesClient, "_signed_request", fake_signed_request)
    client = BinanceFuturesClient(api_key="key", api_secret="secret", live_trade_enabled=True)

    payload = client.fetch_open_orders(symbol="btcusdt")

    assert payload == [
        {
            "symbol": "BTCUSDT",
            "side": "SELL",
            "type": "STOP_MARKET",
            "status": "NEW",
        }
    ]
    assert captured == {
        "method": "GET",
        "path": "/fapi/v1/openOrders",
        "params": {"symbol": "BTCUSDT"},
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


def test_parse_symbol_trading_rules_tolerates_malformed_filter_numbers() -> None:
    rules = BinanceFuturesClient._parse_symbol_trading_rules_row(
        {
            "symbol": "BADUSDC",
            "pricePrecision": "bad-price-precision",
            "quantityPrecision": "bad-quantity-precision",
            "filters": [
                {"filterType": "LOT_SIZE", "stepSize": "bad-step", "minQty": "bad-min"},
                {"filterType": "PRICE_FILTER", "tickSize": "bad-tick"},
            ],
        }
    )

    assert rules.symbol == "BADUSDC"
    assert rules.quantity_step == 0.0
    assert rules.min_quantity == 0.0
    assert rules.tick_size == 0.0
    assert rules.price_precision == 0
    assert rules.quantity_precision == 0


def test_fetch_symbol_trading_rules_skips_malformed_exchange_info_rows(monkeypatch) -> None:
    def fake_public_request(self, path: str, params: dict[str, object] | None = None) -> dict[str, object]:
        return {
            "symbols": [
                ["bad-row"],
                "bad-row",
                {
                    "symbol": "XRPUSDC",
                    "filters": [
                        {"filterType": "LOT_SIZE", "minQty": "0.1", "stepSize": "0.1"},
                    ],
                },
            ]
        }

    monkeypatch.setattr(BinanceFuturesClient, "_public_request", fake_public_request)

    rules = BinanceFuturesClient().fetch_symbol_trading_rules("xrpusdc")

    assert rules.symbol == "XRPUSDC"
    assert rules.quantity_step == 0.1


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


def test_normalize_user_stream_parses_string_false_reduce_only() -> None:
    trade_update = BinanceFuturesClient.normalize_user_stream_message(
        {
            "e": "ORDER_TRADE_UPDATE",
            "E": 1700000000000,
            "o": {
                "s": "BTCUSDC",
                "i": 12345,
                "c": "entry-order-1",
                "S": "BUY",
                "o": "LIMIT",
                "X": "NEW",
                "x": "NEW",
                "R": "false",
            },
        }
    )

    assert trade_update["reduce_only"] is False


def test_normalize_user_stream_tolerates_malformed_numeric_fields() -> None:
    trade_update = BinanceFuturesClient.normalize_user_stream_message(
        {
            "e": "ORDER_TRADE_UPDATE",
            "E": "bad-event-ts",
            "o": {
                "s": "BTCUSDC",
                "i": "bad-order-id",
                "c": "test-order-bad",
                "S": "BUY",
                "o": "LIMIT",
                "X": "FILLED",
                "x": "TRADE",
                "l": "bad-qty",
                "L": "bad-price",
                "z": "nan",
                "q": "bad-original",
                "ap": "bad-average",
                "rp": "bad-pnl",
                "t": "inf",
            },
        }
    )

    assert trade_update["kind"] == "order_trade_update"
    assert trade_update["order_id"] is None
    assert trade_update["last_fill_qty"] == 0.0
    assert trade_update["last_fill_price"] == 0.0
    assert trade_update["cumulative_fill_qty"] == 0.0
    assert trade_update["trade_id"] is None

    account_update = BinanceFuturesClient.normalize_user_stream_message(
        {
            "e": "ACCOUNT_UPDATE",
            "E": "bad-event-ts",
            "a": {
                "m": "ORDER",
                "P": [
                    {
                        "s": "BTCUSDC",
                        "ps": "LONG",
                        "pa": "bad-position",
                        "ep": "bad-entry",
                        "leverage": "bad-leverage",
                        "iw": "bad-wallet",
                    }
                ],
            },
        }
    )

    assert account_update["positions"][0]["position_amt"] == 0.0
    assert account_update["positions"][0]["entry_price"] == 0.0
    assert account_update["positions"][0]["leverage"] == 0


def test_normalize_user_stream_tolerates_malformed_payload_shapes() -> None:
    assert BinanceFuturesClient.normalize_user_stream_message(["bad-row"])["kind"] == "unknown"
    assert BinanceFuturesClient.normalize_user_stream_message({"data": ["bad-row"]})["kind"] == "unknown"

    trade_update = BinanceFuturesClient.normalize_user_stream_message(
        {
            "e": "ORDER_TRADE_UPDATE",
            "E": 1700000000000,
            "o": ["bad-order"],
        }
    )
    assert trade_update["kind"] == "order_trade_update"
    assert trade_update["symbol"] == ""
    assert trade_update["order_id"] is None

    account_update = BinanceFuturesClient.normalize_user_stream_message(
        {
            "e": "ACCOUNT_UPDATE",
            "E": 1700000000000,
            "a": {
                "m": "ORDER",
                "P": [
                    ["bad-position"],
                    {"s": "BTCUSDC", "ps": "LONG", "pa": "0.01"},
                ],
            },
        }
    )
    assert account_update["kind"] == "account_update"
    assert len(account_update["positions"]) == 1
    assert account_update["positions"][0]["position_key"] == "BTCUSDC:LONG"


def test_parse_force_order_event_tolerates_malformed_payload_shapes() -> None:
    assert BinanceFuturesClient._parse_force_order_event(["bad-row"]) is None
    assert BinanceFuturesClient._parse_force_order_event({"data": ["bad-row"]}) is None
    assert BinanceFuturesClient._parse_force_order_event({"data": {"e": "forceOrder", "o": ["bad-order"]}}) is None
