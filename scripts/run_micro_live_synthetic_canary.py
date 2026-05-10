#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.integrations.binance_futures import BinanceFuturesClient
from app.services.execution_coordinator import ExecutionCoordinator
from scripts.operation_report_io import atomic_write_text, display_path, parse_report_generated_at, write_latest_aliases
from scripts.run_micro_live_preflight import _csv_set, _micro_live_config_drift_checks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dry-run MICRO_LIVE submit path through sizing and liquidity checks.")
    parser.add_argument("--symbol", default="")
    parser.add_argument("--direction", choices=["long", "short"], default="long")
    parser.add_argument("--entry-model", choices=["LIMIT", "CONFIRM"], default="LIMIT")
    parser.add_argument("--entry-price", type=float, default=0.0)
    parser.add_argument("--stop-bps", type=float, default=50.0)
    parser.add_argument("--report-dir", default="reports/operations/micro_live_synthetic_canary")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--no-network", action="store_true", help="Use settings/default rule and synthetic liquidity loaders only.")
    parser.add_argument("--no-fail-exit", action="store_true")
    return parser.parse_args()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _display_path(path: Path) -> str:
    return display_path(path, ROOT_DIR)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _blocking_config_checks(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in checks
        if str(item.get("severity") or "").lower() == "blocking" and str(item.get("status") or "").upper() != "PASS"
    ]


def _first_live_symbol(settings: Any, explicit_symbol: str = "") -> str:
    explicit = str(explicit_symbol or "").strip().upper()
    if explicit:
        return explicit
    symbols = sorted(_csv_set(getattr(settings, "auto_trading_micro_live_allowed_symbols", "")))
    return symbols[0] if symbols else "BTCUSDC"


def _public_mid_price(client: BinanceFuturesClient, symbol: str) -> float:
    book = client.fetch_order_book(symbol=symbol, limit=5)
    bids = list(book.get("bids") or [])
    asks = list(book.get("asks") or [])
    best_bid = _safe_float(bids[0][0]) if bids and isinstance(bids[0], (list, tuple)) and bids[0] else 0.0
    best_ask = _safe_float(asks[0][0]) if asks and isinstance(asks[0], (list, tuple)) and asks[0] else 0.0
    if best_bid > 0.0 and best_ask > 0.0:
        return (best_bid + best_ask) / 2.0
    return 0.0


def _settings_symbol_rules_loader(settings: Any):
    def _loader(symbol: str) -> dict[str, Any]:
        return {
            "symbol": symbol.upper(),
            "quantity_step": _safe_float(getattr(settings, "binance_live_quantity_step", 0.001), 0.001),
            "min_quantity": _safe_float(getattr(settings, "binance_live_min_quantity", 0.001), 0.001),
            "tick_size": None,
            "source": "settings_default",
        }

    return _loader


def _public_symbol_rules_loader(client: BinanceFuturesClient):
    def _loader(symbol: str) -> dict[str, Any]:
        rules = client.fetch_symbol_trading_rules(symbol)
        return {
            "symbol": rules.symbol,
            "quantity_step": float(rules.quantity_step),
            "min_quantity": float(rules.min_quantity),
            "tick_size": float(rules.tick_size) if rules.tick_size is not None else None,
            "price_precision": rules.price_precision,
            "quantity_precision": rules.quantity_precision,
            "source": "binance_exchange_info",
        }

    return _loader


def _synthetic_liquidity_loader(settings: Any):
    def _loader(**kwargs: Any) -> dict[str, Any]:
        reference_price = _safe_float(kwargs.get("reference_price") or kwargs.get("price"), 1.0)
        quantity = _safe_float(kwargs.get("quantity"))
        order_notional = quantity * max(reference_price, 0.0)
        depth = max(order_notional * 100.0, _safe_float(getattr(settings, "auto_trading_live_liquidity_gate_min_depth_usdt", 50_000.0), 50_000.0) * 2.0)
        return {
            "source": "synthetic_canary_liquidity",
            "order_notional": round(order_notional, 4),
            "opposite_depth_notional": round(depth, 4),
            "spread_bps": 1.0,
            "market_slippage_bps": 1.0,
            "recent_1m_quote_volume": round(max(order_notional * 250.0, 100_000.0), 4),
            "recent_5m_quote_volume": round(max(order_notional * 1000.0, 500_000.0), 4),
        }

    return _loader


def _public_liquidity_loader(client: BinanceFuturesClient, settings: Any):
    def _levels(raw_rows: Any) -> list[tuple[float, float]]:
        levels: list[tuple[float, float]] = []
        for row in list(raw_rows or []):
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            price = _safe_float(row[0])
            qty = _safe_float(row[1])
            if price > 0.0 and qty > 0.0:
                levels.append((price, qty))
        return levels

    def _loader(**kwargs: Any) -> dict[str, Any]:
        symbol = str(kwargs.get("symbol") or "").upper()
        side = str(kwargs.get("side") or "").upper()
        quantity = _safe_float(kwargs.get("quantity"))
        price = kwargs.get("price")
        reference_price = _safe_float(kwargs.get("reference_price") or price)
        limit = max(5, int(getattr(settings, "auto_trading_live_liquidity_gate_orderbook_limit", 100) or 100))
        book = client.fetch_order_book(symbol=symbol, limit=limit)
        bids = _levels(book.get("bids"))
        asks = _levels(book.get("asks"))
        best_bid = bids[0][0] if bids else 0.0
        best_ask = asks[0][0] if asks else 0.0
        mid = (best_bid + best_ask) / 2.0 if best_bid > 0.0 and best_ask > 0.0 else reference_price
        effective_reference = reference_price or mid
        opposite = asks if side == "BUY" else bids
        opposite_depth = sum(level_price * level_qty for level_price, level_qty in opposite)
        spread_bps = ((best_ask - best_bid) / mid * 10_000.0) if mid > 0.0 else None
        quote_volumes: list[float] = []
        for row in client.fetch_klines(symbol=symbol, interval="1m", limit=5):
            quote_volumes.append(float(row.c) * float(row.v))
        order_notional = quantity * max(effective_reference, 0.0)
        return {
            "source": "binance_public_depth_klines",
            "symbol": symbol,
            "side": side,
            "order_notional": round(order_notional, 4),
            "opposite_depth_notional": round(opposite_depth, 4),
            "spread_bps": round(float(spread_bps), 4) if spread_bps is not None else None,
            "market_slippage_bps": 0.0,
            "recent_1m_quote_volume": round(quote_volumes[-1], 4) if quote_volumes else None,
            "recent_5m_quote_volume": round(sum(quote_volumes), 4) if quote_volumes else None,
        }

    return _loader


def _coordinator(*, settings: Any, rules_loader: Any, liquidity_loader: Any) -> ExecutionCoordinator:
    return ExecutionCoordinator(
        plan_repo=SimpleNamespace(),
        intent_repo=SimpleNamespace(),
        submission_repo=SimpleNamespace(add=lambda _row: None),
        approval_loader=lambda *_args, **_kwargs: {},
        fill_ingest=lambda **_kwargs: {},
        live_submitter=lambda **_kwargs: {"status": "DRY_RUN_NOT_SENT"},
        live_symbol_rules_loader=rules_loader,
        live_liquidity_loader=liquidity_loader,
        settings=settings,
    )


def run_canary(
    *,
    symbol: str,
    direction: str,
    entry_model: str,
    entry_price: float,
    stop_bps: float,
    use_network: bool,
) -> dict[str, Any]:
    settings = get_settings()
    normalized_symbol = _first_live_symbol(settings, symbol)
    client = BinanceFuturesClient() if use_network else None
    reference_price = float(entry_price or 0.0)
    if reference_price <= 0.0 and client is not None:
        reference_price = _public_mid_price(client, normalized_symbol)
    if reference_price <= 0.0:
        reference_price = 100.0

    normalized_direction = str(direction or "long").lower()
    stop_distance = reference_price * max(float(stop_bps or 0.0), 1.0) / 10_000.0
    stop_price = reference_price - stop_distance if normalized_direction == "long" else reference_price + stop_distance
    plan = SimpleNamespace(
        plan_id="synthetic_micro_live_canary_plan",
        symbol=normalized_symbol,
        direction=normalized_direction,
        entry_model=str(entry_model or "LIMIT").upper(),
        entry_price=reference_price,
        sl=stop_price,
    )
    intent = SimpleNamespace(
        intent_id="intent_synthetic_micro_live_canary",
        payload={
            "executable_plan": {
                "entry_limit_price": reference_price,
                "entry_trigger_price": reference_price,
                "stop_price": stop_price,
            }
        },
        quality_snapshot={"recommended_risk_r": 1.0},
        dedupe_result={},
    )
    rules_loader = _public_symbol_rules_loader(client) if client is not None else _settings_symbol_rules_loader(settings)
    liquidity_loader = _public_liquidity_loader(client, settings) if client is not None else _synthetic_liquidity_loader(settings)
    coordinator = _coordinator(settings=settings, rules_loader=rules_loader, liquidity_loader=liquidity_loader)

    checks = _micro_live_config_drift_checks(check_binance_rules=False)
    blocking_config = _blocking_config_checks(checks)
    live_quantity, live_sizing, sizing_error = coordinator._live_order_sizing(intent=intent, plan=plan)
    side = "BUY" if normalized_direction == "long" else "SELL"
    normalized_price, price_details = coordinator._normalize_live_limit_price(
        symbol=normalized_symbol,
        side=side,
        requested_price=reference_price if str(entry_model).upper() == "LIMIT" else None,
    )
    liquidity_gate: dict[str, Any] = {}
    liquidity_error = ""
    if live_quantity is not None and live_quantity > 0.0:
        try:
            liquidity_gate = coordinator._live_liquidity_gate(
                symbol=normalized_symbol,
                side=side,
                order_type="LIMIT" if str(entry_model).upper() == "LIMIT" else "MARKET",
                quantity=live_quantity,
                price=normalized_price,
                reference_price=normalized_price or reference_price,
            )
        except Exception as exc:
            liquidity_error = f"{exc.__class__.__name__}:{exc}"

    path_checks = [
        {
            "name": "approval_config_precheck",
            "status": "FAIL" if blocking_config else "PASS",
            "message": ",".join(str(item.get("name")) for item in blocking_config) if blocking_config else "config drift checks pass",
        },
        {
            "name": "live_sizing",
            "status": "FAIL" if sizing_error else "PASS",
            "message": sizing_error or f"quantity={live_quantity}",
        },
        {
            "name": "limit_price_normalization",
            "status": "PASS" if str(entry_model).upper() != "LIMIT" or (normalized_price is not None and normalized_price > 0.0) else "FAIL",
            "message": json.dumps(price_details, sort_keys=True),
        },
        {
            "name": "liquidity_gate",
            "status": "FAIL"
            if liquidity_error or str(liquidity_gate.get("decision") or "PASS").upper() not in {"PASS", "SPLIT_PARTIAL_SUBMIT"}
            else "PASS",
            "message": liquidity_error or str(liquidity_gate.get("message") or "not evaluated"),
        },
        {
            "name": "submission_boundary",
            "status": "PASS",
            "message": "dry-run stopped before live_submitter; no order was sent",
        },
    ]
    overall = "PASS" if all(str(item["status"]) == "PASS" for item in path_checks) else "FAIL"
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "overall_status": overall,
        "no_live_order_sent": True,
        "symbol": normalized_symbol,
        "direction": normalized_direction,
        "entry_model": str(entry_model).upper(),
        "reference_price": round(reference_price, 8),
        "stop_price": round(stop_price, 8),
        "use_network": bool(use_network),
        "checks": path_checks,
        "live_sizing": live_sizing,
        "normalized_price": normalized_price,
        "price_details": price_details,
        "liquidity_gate": liquidity_gate,
    }


def _write_report(path: Path, payload: dict[str, Any], *, atomic: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# MICRO_LIVE Synthetic Submit Canary",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- overall_status: {payload.get('overall_status')}",
        f"- symbol: {payload.get('symbol')}",
        f"- no_live_order_sent: {payload.get('no_live_order_sent')}",
        "",
    ]
    for check in payload.get("checks") or []:
        lines.append(f"- {check.get('name')}: {check.get('status')} | {check.get('message')}")
    lines.extend(["", "```json", json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), "```"])
    content = "\n".join(lines)
    if atomic:
        atomic_write_text(path, content)
    else:
        atomic_write_text(path, content)


def main() -> int:
    args = parse_args()
    payload = run_canary(
        symbol=str(args.symbol or ""),
        direction=str(args.direction),
        entry_model=str(args.entry_model),
        entry_price=float(args.entry_price or 0.0),
        stop_bps=float(args.stop_bps or 50.0),
        use_network=not bool(args.no_network),
    )
    if not args.no_write_report:
        generated = parse_report_generated_at(payload.get("generated_at"))
        report_dir = ROOT_DIR / args.report_dir
        report_path = report_dir / f"micro_live_synthetic_canary_{payload['symbol']}_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
        payload["report_path"] = _display_path(report_path)
        payload["latest_report_path"] = _display_path(report_dir / "latest.md")
        payload["latest_json_path"] = _display_path(report_dir / "latest.json")
        _write_report(report_path, payload, atomic=True)
        payload.update(
            write_latest_aliases(
                report_dir=report_dir,
                payload=payload,
                write_markdown_report=_write_report,
                root_dir=ROOT_DIR,
                json_default=_json_default,
            )
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 1 if payload["overall_status"] != "PASS" and not bool(args.no_fail_exit) else 0


if __name__ == "__main__":
    raise SystemExit(main())
