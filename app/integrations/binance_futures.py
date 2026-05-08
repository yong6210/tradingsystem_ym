from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from decimal import Decimal
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings


@dataclass(slots=True)
class BinanceKline:
    symbol: str
    interval: str
    open_time: datetime
    close_time: datetime
    o: float
    h: float
    l: float
    c: float
    v: float
    is_final: bool


@dataclass(slots=True)
class BinanceFundingRate:
    symbol: str
    ts: datetime
    funding_rate: float
    mark_price: float | None
    raw: dict[str, Any]


@dataclass(slots=True)
class BinanceOpenInterestStat:
    symbol: str
    period: str
    ts: datetime
    open_interest: float
    open_interest_value: float | None
    raw: dict[str, Any]


@dataclass(slots=True)
class BinanceBasisKline:
    symbol: str
    interval: str
    open_time: datetime
    basis_open: float
    basis_high: float
    basis_low: float
    basis_close: float
    raw: list[Any]


@dataclass(slots=True)
class BinanceLiquidationOrder:
    symbol: str
    side: str
    ts: datetime
    price: float
    avg_price: float
    qty: float
    filled_qty: float
    status: str
    raw: dict[str, Any]


@dataclass(slots=True)
class BinanceSymbolTradingRules:
    symbol: str
    quantity_step: float
    min_quantity: float
    tick_size: float | None
    price_precision: int | None
    quantity_precision: int | None
    raw: dict[str, Any]


class BinanceFuturesClient:
    """Binance USD-M futures client for REST backfill and optional WS streaming."""

    def __init__(
        self,
        rest_base_url: str | None = None,
        ws_base_url: str | None = None,
        timeout_seconds: float | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        recv_window: int | None = None,
        live_trade_enabled: bool | None = None,
    ):
        settings = get_settings()
        self.rest_base_url = (rest_base_url or settings.binance_rest_base_url).rstrip("/")
        self.ws_base_url = (ws_base_url or settings.binance_ws_base_url).rstrip("/")
        self.timeout_seconds = timeout_seconds or settings.binance_timeout_seconds
        self.ws_receive_timeout_seconds = float(settings.binance_ws_receive_timeout_seconds)
        self.api_key = api_key if api_key is not None else settings.binance_api_key
        self.api_secret = api_secret if api_secret is not None else settings.binance_api_secret
        self.recv_window = int(recv_window if recv_window is not None else settings.binance_trade_recv_window)
        self.live_trade_enabled = (
            bool(live_trade_enabled) if live_trade_enabled is not None else bool(settings.binance_trade_live_enabled)
        )
        self._symbol_trading_rules_cache: dict[str, BinanceSymbolTradingRules] = {}

    @staticmethod
    def _to_dt(ms: int) -> datetime:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)

    @staticmethod
    def _parse_kline_row(symbol: str, interval: str, row: list[Any]) -> BinanceKline:
        return BinanceKline(
            symbol=symbol,
            interval=interval,
            open_time=BinanceFuturesClient._to_dt(int(row[0])),
            close_time=BinanceFuturesClient._to_dt(int(row[6])),
            o=float(row[1]),
            h=float(row[2]),
            l=float(row[3]),
            c=float(row[4]),
            v=float(row[5]),
            is_final=True,
        )

    @staticmethod
    def _parse_funding_rate_row(symbol: str, row: dict[str, Any]) -> BinanceFundingRate:
        ts_ms = int(row.get("fundingTime") or row.get("time") or 0)
        return BinanceFundingRate(
            symbol=symbol.upper(),
            ts=BinanceFuturesClient._to_dt(ts_ms),
            funding_rate=float(row.get("fundingRate") or 0.0),
            mark_price=float(row.get("markPrice")) if row.get("markPrice") not in {None, ""} else None,
            raw=dict(row),
        )

    @staticmethod
    def _parse_open_interest_hist_row(symbol: str, period: str, row: dict[str, Any]) -> BinanceOpenInterestStat:
        ts_ms = int(row.get("timestamp") or row.get("time") or 0)
        return BinanceOpenInterestStat(
            symbol=symbol.upper(),
            period=period,
            ts=BinanceFuturesClient._to_dt(ts_ms),
            open_interest=float(row.get("sumOpenInterest") or row.get("openInterest") or 0.0),
            open_interest_value=float(row.get("sumOpenInterestValue")) if row.get("sumOpenInterestValue") not in {None, ""} else None,
            raw=dict(row),
        )

    @staticmethod
    def _parse_basis_kline_row(symbol: str, interval: str, row: list[Any]) -> BinanceBasisKline:
        return BinanceBasisKline(
            symbol=symbol.upper(),
            interval=interval,
            open_time=BinanceFuturesClient._to_dt(int(row[0])),
            basis_open=float(row[1]),
            basis_high=float(row[2]),
            basis_low=float(row[3]),
            basis_close=float(row[4]),
            raw=list(row),
        )

    @staticmethod
    def _parse_force_order_event(payload: dict[str, Any]) -> BinanceLiquidationOrder | None:
        data = dict(payload.get("data") or payload)
        if str(data.get("e") or "").lower() != "forceorder":
            return None
        order = dict(data.get("o") or {})
        ts_ms = int(order.get("T") or data.get("E") or 0)
        if ts_ms <= 0:
            return None
        return BinanceLiquidationOrder(
            symbol=str(order.get("s") or "").upper(),
            side=str(order.get("S") or "").upper(),
            ts=BinanceFuturesClient._to_dt(ts_ms),
            price=float(order.get("p") or 0.0),
            avg_price=float(order.get("ap") or 0.0),
            qty=float(order.get("q") or 0.0),
            filled_qty=float(order.get("z") or order.get("l") or 0.0),
            status=str(order.get("X") or ""),
            raw=data,
        )

    @staticmethod
    def _timestamp_ms() -> int:
        return int(datetime.now(tz=timezone.utc).timestamp() * 1000)

    @staticmethod
    def _format_decimal(value: float | int | str | Decimal) -> str:
        normalized = Decimal(str(value))
        text = format(normalized, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text or "0"

    @staticmethod
    def _stringify_param(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (float, int, Decimal)):
            return BinanceFuturesClient._format_decimal(value)
        return str(value)

    def _require_trade_credentials(self) -> None:
        if not self.api_key or not self.api_secret:
            raise RuntimeError("binance_trade_credentials_not_configured")

    def _signed_request(self, method: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        self._require_trade_credentials()

        request_params: dict[str, str] = {
            key: self._stringify_param(value)
            for key, value in params.items()
            if value is not None
        }
        request_params["timestamp"] = str(self._timestamp_ms())
        request_params["recvWindow"] = str(self.recv_window)
        query_string = urlencode(request_params)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signed_params = {**request_params, "signature": signature}

        with httpx.Client(base_url=self.rest_base_url, timeout=self.timeout_seconds) as client:
            response = client.request(
                method=method.upper(),
                url=path,
                params=signed_params,
                headers={"X-MBX-APIKEY": self.api_key},
            )
            response.raise_for_status()
            if response.content:
                return response.json()
        return {}

    def _keyed_request(self, method: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require_trade_credentials()
        request_params = {
            key: self._stringify_param(value)
            for key, value in (params or {}).items()
            if value is not None
        }
        with httpx.Client(base_url=self.rest_base_url, timeout=self.timeout_seconds) as client:
            response = client.request(
                method=method.upper(),
                url=path,
                params=request_params or None,
                headers={"X-MBX-APIKEY": self.api_key},
            )
            response.raise_for_status()
            if response.content:
                return response.json()
        return {}

    def _public_request(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_params = {
            key: self._stringify_param(value)
            for key, value in (params or {}).items()
            if value is not None
        }
        with httpx.Client(base_url=self.rest_base_url, timeout=self.timeout_seconds) as client:
            response = client.get(path, params=request_params or None)
            response.raise_for_status()
            if response.content:
                return response.json()
        return {}

    @staticmethod
    def _ws_root(base_url: str) -> str:
        if base_url.endswith("/stream"):
            return base_url[: -len("/stream")]
        if "/stream" in base_url:
            return base_url.split("/stream", 1)[0]
        return base_url.rstrip("/")

    @staticmethod
    def _parse_symbol_trading_rules_row(row: dict[str, Any]) -> BinanceSymbolTradingRules:
        filters = {
            str(item.get("filterType") or "").upper(): item
            for item in list(row.get("filters") or [])
            if isinstance(item, dict)
        }
        lot_size = dict(filters.get("LOT_SIZE") or {})
        price_filter = dict(filters.get("PRICE_FILTER") or {})

        quantity_step = float(lot_size.get("stepSize") or 0.0)
        min_quantity = float(lot_size.get("minQty") or quantity_step or 0.0)
        tick_size_raw = price_filter.get("tickSize")
        tick_size = float(tick_size_raw) if tick_size_raw not in {None, ""} else None

        return BinanceSymbolTradingRules(
            symbol=str(row.get("symbol") or "").upper(),
            quantity_step=quantity_step,
            min_quantity=min_quantity,
            tick_size=tick_size,
            price_precision=int(row["pricePrecision"]) if row.get("pricePrecision") is not None else None,
            quantity_precision=int(row["quantityPrecision"]) if row.get("quantityPrecision") is not None else None,
            raw=dict(row),
        )

    def fetch_symbol_trading_rules(self, symbol: str) -> BinanceSymbolTradingRules:
        normalized_symbol = str(symbol or "").upper()
        if not normalized_symbol:
            raise ValueError("symbol_required")
        cached = self._symbol_trading_rules_cache.get(normalized_symbol)
        if cached is not None:
            return cached

        payload = self._public_request("/fapi/v1/exchangeInfo", {"symbol": normalized_symbol})
        symbol_rows = payload.get("symbols") if isinstance(payload, dict) else None
        if not isinstance(symbol_rows, list):
            raise RuntimeError("binance_symbol_exchange_info_missing")
        for row in symbol_rows:
            if str((row or {}).get("symbol") or "").upper() != normalized_symbol:
                continue
            rules = self._parse_symbol_trading_rules_row(dict(row))
            self._symbol_trading_rules_cache[normalized_symbol] = rules
            return rules
        raise RuntimeError(f"binance_symbol_exchange_info_not_found:{normalized_symbol}")

    def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
        client_order_id: str | None = None,
        live: bool = False,
        new_order_resp_type: str = "RESULT",
    ) -> dict[str, Any]:
        normalized_type = order_type.upper()
        if normalized_type == "LIMIT" and price is None:
            raise ValueError("limit_orders_require_price")
        if live and not self.live_trade_enabled:
            raise RuntimeError("binance_live_orders_disabled")

        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": normalized_type,
            "quantity": quantity,
            "timeInForce": time_in_force.upper() if normalized_type == "LIMIT" else None,
            "price": price if normalized_type == "LIMIT" else None,
            "reduceOnly": reduce_only,
            "newClientOrderId": client_order_id,
            "newOrderRespType": new_order_resp_type.upper(),
        }
        path = "/fapi/v1/order" if live else "/fapi/v1/order/test"
        payload = self._signed_request("POST", path, params)
        if not live and not payload:
            return {
                "symbol": symbol.upper(),
                "side": side.upper(),
                "type": normalized_type,
                "price": self._format_decimal(price) if price is not None else "0",
                "origQty": self._format_decimal(quantity),
                "executedQty": "0",
                "status": "TEST_ACCEPTED",
                "clientOrderId": client_order_id or "",
                "timeInForce": time_in_force.upper() if normalized_type == "LIMIT" else "",
                "reduceOnly": reduce_only,
                "testOrder": True,
            }
        return payload

    def query_order(
        self,
        *,
        symbol: str,
        order_id: int | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        if order_id is None and not client_order_id:
            raise ValueError("order_id_or_client_order_id_required")
        return self._signed_request(
            "GET",
            "/fapi/v1/order",
            {
                "symbol": symbol.upper(),
                "orderId": order_id,
                "origClientOrderId": client_order_id,
            },
        )

    def cancel_order(
        self,
        *,
        symbol: str,
        order_id: int | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        if not self.live_trade_enabled:
            raise RuntimeError("binance_live_orders_disabled")
        if order_id is None and not client_order_id:
            raise ValueError("order_id_or_client_order_id_required")
        return self._signed_request(
            "DELETE",
            "/fapi/v1/order",
            {
                "symbol": symbol.upper(),
                "orderId": order_id,
                "origClientOrderId": client_order_id,
            },
        )

    def create_user_stream_listen_key(self) -> dict[str, Any]:
        payload = self._keyed_request("POST", "/fapi/v1/listenKey")
        return {
            "listen_key": str(payload.get("listenKey") or ""),
            "raw": payload,
        }

    def keepalive_user_stream_listen_key(self, listen_key: str) -> dict[str, Any]:
        payload = self._keyed_request("PUT", "/fapi/v1/listenKey", {"listenKey": listen_key})
        returned = str(payload.get("listenKey") or listen_key)
        return {
            "listen_key": returned,
            "raw": payload,
        }

    def close_user_stream_listen_key(self, listen_key: str) -> dict[str, Any]:
        payload = self._keyed_request("DELETE", "/fapi/v1/listenKey", {"listenKey": listen_key})
        return {
            "listen_key": listen_key,
            "closed": True,
            "raw": payload,
        }

    def fetch_position_risk(self, symbol: str | None = None) -> list[dict[str, Any]]:
        payload = self._signed_request(
            "GET",
            "/fapi/v2/positionRisk",
            {"symbol": symbol.upper() if symbol else None},
        )
        if isinstance(payload, list):
            return payload
        return []

    @staticmethod
    def _normalize_position_side(value: Any) -> str:
        text = str(value or "BOTH").upper()
        return text if text in {"LONG", "SHORT", "BOTH"} else "BOTH"

    @staticmethod
    def normalize_position_risk_row(row: dict[str, Any]) -> dict[str, Any]:
        update_ms = int(row.get("updateTime") or BinanceFuturesClient._timestamp_ms())
        return {
            "position_key": f"{str(row.get('symbol') or '').upper()}:{BinanceFuturesClient._normalize_position_side(row.get('positionSide'))}",
            "symbol": str(row.get("symbol") or "").upper(),
            "position_side": BinanceFuturesClient._normalize_position_side(row.get("positionSide")),
            "position_amt": float(row.get("positionAmt") or 0.0),
            "entry_price": float(row.get("entryPrice") or 0.0),
            "break_even_price": float(row.get("breakEvenPrice") or 0.0),
            "mark_price": float(row.get("markPrice") or 0.0),
            "liquidation_price": float(row.get("liquidationPrice") or 0.0),
            "unrealized_pnl": float(row.get("unRealizedProfit") or 0.0),
            "notional": float(row.get("notional") or 0.0),
            "leverage": int(float(row.get("leverage") or 0.0)),
            "margin_type": str(row.get("marginType") or ""),
            "isolated_wallet": float(row.get("isolatedWallet") or 0.0),
            "update_ts": BinanceFuturesClient._to_dt(update_ms),
            "raw": row,
        }

    @staticmethod
    def normalize_account_update_position(row: dict[str, Any], *, event_ts_ms: int) -> dict[str, Any]:
        symbol = str(row.get("s") or row.get("symbol") or "").upper()
        position_side = BinanceFuturesClient._normalize_position_side(row.get("ps") or row.get("positionSide"))
        return {
            "position_key": f"{symbol}:{position_side}",
            "symbol": symbol,
            "position_side": position_side,
            "position_amt": float(row.get("pa") or row.get("positionAmt") or 0.0),
            "entry_price": float(row.get("ep") or row.get("entryPrice") or 0.0),
            "break_even_price": float(row.get("bep") or row.get("breakEvenPrice") or 0.0),
            "mark_price": float(row.get("mp") or row.get("markPrice") or 0.0),
            "liquidation_price": float(row.get("lp") or row.get("liquidationPrice") or 0.0),
            "unrealized_pnl": float(row.get("up") or row.get("unRealizedProfit") or 0.0),
            "notional": float(row.get("notional") or 0.0),
            "leverage": int(float(row.get("leverage") or 0.0)),
            "margin_type": str(row.get("mt") or row.get("marginType") or ""),
            "isolated_wallet": float(row.get("iw") or row.get("isolatedWallet") or 0.0),
            "update_ts": BinanceFuturesClient._to_dt(event_ts_ms),
            "raw": row,
        }

    @staticmethod
    def normalize_user_stream_message(payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload.get("data") or payload)
        event_type = str(data.get("e") or "")
        event_ts_ms = int(data.get("E") or data.get("T") or BinanceFuturesClient._timestamp_ms())
        event_ts = BinanceFuturesClient._to_dt(event_ts_ms).isoformat()

        if event_type == "ORDER_TRADE_UPDATE":
            order = dict(data.get("o") or {})
            return {
                "kind": "order_trade_update",
                "event_type": event_type,
                "event_ts": event_ts,
                "symbol": str(order.get("s") or "").upper(),
                "order_id": int(order.get("i") or 0) or None,
                "client_order_id": str(order.get("c") or ""),
                "status": str(order.get("X") or ""),
                "execution_type": str(order.get("x") or ""),
                "side": str(order.get("S") or ""),
                "order_type": str(order.get("o") or ""),
                "time_in_force": str(order.get("f") or ""),
                "reduce_only": bool(order.get("R")),
                "position_side": BinanceFuturesClient._normalize_position_side(order.get("ps")),
                "last_fill_qty": float(order.get("l") or 0.0),
                "last_fill_price": float(order.get("L") or 0.0),
                "cumulative_fill_qty": float(order.get("z") or 0.0),
                "original_qty": float(order.get("q") or 0.0),
                "avg_price": float(order.get("ap") or 0.0),
                "realized_pnl": float(order.get("rp") or 0.0),
                "trade_id": int(order.get("t") or 0) or None,
                "raw": data,
            }

        if event_type == "executionReport":
            return {
                "kind": "order_trade_update",
                "event_type": event_type,
                "event_ts": event_ts,
                "symbol": str(data.get("s") or "").upper(),
                "order_id": int(data.get("i") or 0) or None,
                "client_order_id": str(data.get("c") or ""),
                "status": str(data.get("X") or ""),
                "execution_type": str(data.get("x") or ""),
                "side": str(data.get("S") or ""),
                "order_type": str(data.get("o") or ""),
                "time_in_force": str(data.get("f") or ""),
                "reduce_only": bool(data.get("R")),
                "position_side": BinanceFuturesClient._normalize_position_side(data.get("ps")),
                "last_fill_qty": float(data.get("l") or 0.0),
                "last_fill_price": float(data.get("L") or 0.0),
                "cumulative_fill_qty": float(data.get("z") or 0.0),
                "original_qty": float(data.get("q") or 0.0),
                "avg_price": float(data.get("ap") or 0.0),
                "realized_pnl": float(data.get("rp") or 0.0),
                "trade_id": int(data.get("t") or 0) or None,
                "raw": data,
            }

        if event_type == "ACCOUNT_UPDATE":
            account = dict(data.get("a") or {})
            positions = [
                BinanceFuturesClient.normalize_account_update_position(row, event_ts_ms=event_ts_ms)
                for row in list(account.get("P") or [])
            ]
            return {
                "kind": "account_update",
                "event_type": event_type,
                "event_ts": event_ts,
                "event_reason": str(account.get("m") or ""),
                "balances": list(account.get("B") or []),
                "positions": positions,
                "raw": data,
            }

        return {
            "kind": "unknown",
            "event_type": event_type or "unknown",
            "event_ts": event_ts,
            "raw": data,
        }

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> list[BinanceKline]:
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": max(1, min(limit, 1500)),
        }
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms

        with httpx.Client(base_url=self.rest_base_url, timeout=self.timeout_seconds) as client:
            response = client.get("/fapi/v1/klines", params=params)
            response.raise_for_status()
            payload = response.json()

        return [self._parse_kline_row(symbol.upper(), interval, row) for row in payload]

    def fetch_order_book(self, symbol: str, limit: int = 100) -> dict[str, Any]:
        allowed_limits = [5, 10, 20, 50, 100, 500, 1000]
        requested_limit = max(1, int(limit or 100))
        normalized_limit = next((item for item in allowed_limits if item >= requested_limit), allowed_limits[-1])
        with httpx.Client(base_url=self.rest_base_url, timeout=self.timeout_seconds) as client:
            response = client.get(
                "/fapi/v1/depth",
                params={"symbol": symbol.upper(), "limit": normalized_limit},
            )
            response.raise_for_status()
            payload = response.json()
        return dict(payload)

    def fetch_funding_rates(
        self,
        *,
        symbol: str,
        limit: int = 100,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> list[BinanceFundingRate]:
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "limit": max(1, min(limit, 1000)),
        }
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        with httpx.Client(base_url=self.rest_base_url, timeout=self.timeout_seconds) as client:
            response = client.get("/fapi/v1/fundingRate", params=params)
            response.raise_for_status()
            payload = response.json()
        return [self._parse_funding_rate_row(symbol.upper(), row) for row in payload]

    def fetch_open_interest_hist(
        self,
        *,
        symbol: str,
        period: str = "15m",
        limit: int = 500,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> list[BinanceOpenInterestStat]:
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "period": period,
            "limit": max(1, min(limit, 500)),
        }
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        with httpx.Client(base_url=self.rest_base_url, timeout=self.timeout_seconds) as client:
            response = client.get("/futures/data/openInterestHist", params=params)
            response.raise_for_status()
            payload = response.json()
        return [self._parse_open_interest_hist_row(symbol.upper(), period, row) for row in payload]

    def fetch_premium_index_klines(
        self,
        *,
        symbol: str,
        interval: str = "15m",
        limit: int = 500,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> list[BinanceBasisKline]:
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": max(1, min(limit, 1500)),
        }
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        with httpx.Client(base_url=self.rest_base_url, timeout=self.timeout_seconds) as client:
            response = client.get("/fapi/v1/premiumIndexKlines", params=params)
            response.raise_for_status()
            payload = response.json()
        return [self._parse_basis_kline_row(symbol.upper(), interval, row) for row in payload]

    def ping(self) -> bool:
        with httpx.Client(base_url=self.rest_base_url, timeout=self.timeout_seconds) as client:
            response = client.get("/fapi/v1/ping")
            response.raise_for_status()
        return True

    def fetch_top_usdc_perp_symbols(self, limit: int = 30) -> list[str]:
        with httpx.Client(base_url=self.rest_base_url, timeout=self.timeout_seconds) as client:
            response = client.get("/fapi/v1/ticker/24hr")
            response.raise_for_status()
            rows = response.json()

        candidates: list[tuple[str, float]] = []
        for row in rows:
            symbol = str(row.get("symbol", ""))
            if not symbol.endswith("USDC"):
                continue
            quote_vol = float(row.get("quoteVolume", 0.0))
            candidates.append((symbol, quote_vol))

        candidates.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in candidates[:limit]]

    async def stream_klines(self, symbols: list[str], interval: str) -> AsyncIterator[BinanceKline]:
        """Combined stream async generator.

        Requires optional `websockets` package and network access.
        """
        try:
            import websockets
        except Exception as exc:  # pragma: no cover - optional runtime dependency
            raise RuntimeError("websocket streaming requires `websockets` package") from exc

        streams = "/".join(f"{s.lower()}@kline_{interval}" for s in symbols)
        url = f"{self.ws_base_url}?streams={streams}"

        async with websockets.connect(
            url,
            ping_interval=20,
            ping_timeout=20,
            open_timeout=self.timeout_seconds,
        ) as ws:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=self.ws_receive_timeout_seconds)
                data = json.loads(raw)
                k = data.get("data", {}).get("k", {})
                symbol = str(k.get("s", ""))
                if not symbol:
                    continue

                yield BinanceKline(
                    symbol=symbol,
                    interval=str(k.get("i", interval)),
                    open_time=self._to_dt(int(k.get("t"))),
                    close_time=self._to_dt(int(k.get("T"))),
                    o=float(k.get("o", 0.0)),
                    h=float(k.get("h", 0.0)),
                    l=float(k.get("l", 0.0)),
                    c=float(k.get("c", 0.0)),
                    v=float(k.get("v", 0.0)),
                    is_final=bool(k.get("x", False)),
                )

    async def stream_force_orders(
        self,
        symbols: list[str],
        *,
        max_events: int | None = None,
        timeout_seconds: float | None = None,
    ) -> AsyncIterator[BinanceLiquidationOrder]:
        try:
            import websockets
        except Exception as exc:  # pragma: no cover - optional runtime dependency
            raise RuntimeError("liquidation stream requires `websockets` package") from exc

        streams = "/".join(f"{s.lower()}@forceOrder" for s in symbols)
        url = f"{self.ws_base_url}?streams={streams}"
        processed = 0
        async with websockets.connect(url, ping_interval=20, ping_timeout=20, open_timeout=self.timeout_seconds) as ws:
            while max_events is None or processed < max_events:
                try:
                    if timeout_seconds is None:
                        raw = await ws.recv()
                    else:
                        raw = await asyncio.wait_for(ws.recv(), timeout=float(timeout_seconds))
                except TimeoutError:
                    break
                event = self._parse_force_order_event(json.loads(raw))
                if event is None or not event.symbol:
                    continue
                processed += 1
                yield event

    async def warmup_and_stream(
        self,
        symbols: list[str],
        interval: str,
        warmup_limit: int = 500,
    ) -> tuple[dict[str, list[BinanceKline]], AsyncIterator[BinanceKline]]:
        warmup: dict[str, list[BinanceKline]] = {}
        for symbol in symbols:
            warmup[symbol] = self.fetch_klines(symbol=symbol, interval=interval, limit=warmup_limit)
            await asyncio.sleep(0)
        return warmup, self.stream_klines(symbols=symbols, interval=interval)

    async def stream_user_events(
        self,
        listen_key: str,
        *,
        max_events: int | None = None,
        timeout_seconds: float | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        try:
            import websockets
        except Exception as exc:  # pragma: no cover - optional runtime dependency
            raise RuntimeError("user stream requires `websockets` package") from exc

        ws_root = self._ws_root(self.ws_base_url)
        url = f"{ws_root}/ws/{listen_key}"
        processed = 0
        async with websockets.connect(url, ping_interval=20, ping_timeout=20, open_timeout=self.timeout_seconds) as ws:
            while max_events is None or processed < max_events:
                try:
                    if timeout_seconds is None:
                        raw = await ws.recv()
                    else:
                        raw = await asyncio.wait_for(ws.recv(), timeout=float(timeout_seconds))
                except TimeoutError:
                    break
                normalized = self.normalize_user_stream_message(json.loads(raw))
                processed += 1
                yield normalized
