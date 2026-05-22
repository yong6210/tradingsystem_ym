#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.integrations.binance_futures import BinanceFuturesClient
from scripts.operation_report_io import atomic_write_text, display_path, write_latest_aliases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit live futures account positions for exchange-side protection orders.")
    parser.add_argument("--symbols", default="", help="Optional comma-separated symbol scope. Empty uses current MICRO_LIVE universe.")
    parser.add_argument("--report-dir", default="reports/operations/live_account_protection_audit")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--no-fail-exit", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--flatten-missing-stop",
        action="store_true",
        help="Submit live reduce/close market orders for positions missing stop protection.",
    )
    parser.add_argument(
        "--no-flatten-missing-stop",
        action="store_true",
        help="Disable missing-stop flatten even when enabled by settings.",
    )
    parser.add_argument(
        "--no-cancel-open-orders-after-flatten",
        action="store_true",
        help="Do not cancel same-symbol open orders after a missing-stop flatten submission.",
    )
    parser.add_argument(
        "--cancel-unexpected-open-orders",
        action="store_true",
        help="Cancel open orders that can create positions without a matching exchange position.",
    )
    parser.add_argument(
        "--no-cancel-unexpected-open-orders",
        action="store_true",
        help="Disable unexpected-open-order cancellation even when enabled by settings.",
    )
    return parser.parse_args()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _csv_set(raw: Any) -> set[str]:
    return {item.strip().upper() for item in str(raw or "").split(",") if item.strip()}


def _resolve_report_dir(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT_DIR / path


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, "", "None"):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if isfinite(parsed) else default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value) if isfinite(float(value)) else bool(default)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
        return False
    return bool(default)


def _position_side(row: dict[str, Any]) -> str:
    side = str(row.get("positionSide") or row.get("position_side") or "").upper()
    if side in {"LONG", "SHORT"}:
        return side
    amount = _safe_float(row.get("positionAmt", row.get("position_amt")))
    return "LONG" if amount > 0.0 else "SHORT"


def _position_amount(row: dict[str, Any]) -> float:
    return _safe_float(row.get("positionAmt", row.get("position_amt")))


def _position_leverage(row: dict[str, Any]) -> float:
    return _safe_float(row.get("leverage"))


def _order_position_side(row: dict[str, Any]) -> str:
    side = str(row.get("positionSide") or row.get("position_side") or "BOTH").upper()
    return side if side in {"LONG", "SHORT", "BOTH"} else "BOTH"


def _order_side(row: dict[str, Any]) -> str:
    return str(row.get("side") or "").upper()


def _order_status(row: dict[str, Any]) -> str:
    return str(row.get("status") or "").upper()


def _is_open_order(row: dict[str, Any]) -> bool:
    terminal = {"FILLED", "CANCELED", "CANCELLED", "REJECTED", "EXPIRED"}
    status = _order_status(row)
    return not status or status not in terminal


def _close_side(position_side: str) -> str:
    return "SELL" if position_side == "LONG" else "BUY"


def _round_down_to_step(value: float, *, step: float) -> float:
    if step <= 0.0:
        return float(value)
    return int(float(value) / step) * step


def _matches_position_close(order: dict[str, Any], *, symbol: str, position_side: str) -> bool:
    if str(order.get("symbol") or "").upper() != symbol:
        return False
    if _order_side(order) != _close_side(position_side):
        return False
    order_side = _order_position_side(order)
    if order_side not in {"BOTH", position_side}:
        return False
    exchange_close_flag = _order_reduce_or_close(order)
    hedge_side_match = order_side == position_side
    return exchange_close_flag or hedge_side_match


def _order_reduce_or_close(order: dict[str, Any]) -> bool:
    return (
        _safe_bool(order.get("reduceOnly"))
        or _safe_bool(order.get("reduce_only"))
        or _safe_bool(order.get("closePosition"))
        or _safe_bool(order.get("close_position"))
    )


def _order_can_increase_position(order: dict[str, Any]) -> bool:
    if _order_reduce_or_close(order):
        return False
    side = _order_side(order)
    if side not in {"BUY", "SELL"}:
        return False
    position_side = _order_position_side(order)
    if position_side == "LONG":
        return side == "BUY"
    if position_side == "SHORT":
        return side == "SELL"
    return True


def _order_id(order: dict[str, Any]) -> str:
    return str(order.get("orderId") or order.get("order_id") or "")


def _order_client_id(order: dict[str, Any]) -> str:
    return str(order.get("clientOrderId") or order.get("client_order_id") or "")


def _has_stop_order(position: dict[str, Any], open_orders: list[dict[str, Any]]) -> bool:
    symbol = str(position.get("symbol") or "").upper()
    side = _position_side(position)
    for order in open_orders:
        order_type = str(order.get("type") or order.get("order_type") or "").upper()
        if "STOP" in order_type and _matches_position_close(order, symbol=symbol, position_side=side):
            return True
    return False


def _order_target_price(order: dict[str, Any]) -> float:
    for key in ("price", "stopPrice", "stop_price"):
        value = _safe_float(order.get(key))
        if value > 0.0:
            return value
    return 0.0


def _is_favorable_take_profit(*, position: dict[str, Any], position_side: str, order: dict[str, Any]) -> bool:
    entry_price = _safe_float(position.get("entryPrice", position.get("entry_price")))
    target_price = _order_target_price(order)
    if entry_price <= 0.0 or target_price <= 0.0:
        return False
    if position_side == "LONG":
        return target_price > entry_price
    return target_price < entry_price


def _has_take_profit_order(position: dict[str, Any], open_orders: list[dict[str, Any]]) -> bool:
    symbol = str(position.get("symbol") or "").upper()
    side = _position_side(position)
    for order in open_orders:
        order_type = str(order.get("type") or order.get("order_type") or "").upper()
        if "STOP" in order_type:
            continue
        if (order_type == "LIMIT" or "TAKE_PROFIT" in order_type) and _matches_position_close(
            order,
            symbol=symbol,
            position_side=side,
        ) and _is_favorable_take_profit(position=position, position_side=side, order=order):
            return True
    return False


def evaluate_account_protection(
    *,
    positions: list[dict[str, Any]],
    open_orders: list[dict[str, Any]],
    allowed_symbols: set[str],
    leverage_cap: float = 0.0,
    now: datetime,
) -> dict[str, Any]:
    open_positions = [
        dict(row)
        for row in positions
        if str(row.get("symbol") or "").strip() and abs(_position_amount(row)) > 1e-12
    ]
    active_orders = [dict(row) for row in open_orders if _is_open_order(dict(row))]
    position_keys = {
        (str(position.get("symbol") or "").upper(), _position_side(position))
        for position in open_positions
    }
    position_symbols = {symbol for symbol, _side in position_keys}
    issues: list[dict[str, Any]] = []
    position_summaries: list[dict[str, Any]] = []
    order_summaries: list[dict[str, Any]] = []

    for order in active_orders:
        symbol = str(order.get("symbol") or "").upper()
        order_position_side = _order_position_side(order)
        matching_position = (
            (symbol, order_position_side) in position_keys
            if order_position_side in {"LONG", "SHORT"}
            else symbol in position_symbols
        )
        in_universe = not allowed_symbols or symbol in allowed_symbols
        can_increase_position = _order_can_increase_position(order)
        summary = {
            "symbol": symbol,
            "order_id": _order_id(order),
            "client_order_id": _order_client_id(order),
            "side": _order_side(order),
            "position_side": order_position_side,
            "order_type": str(order.get("type") or order.get("order_type") or "").upper(),
            "status": _order_status(order),
            "price": _safe_float(order.get("price")),
            "stop_price": _safe_float(order.get("stopPrice", order.get("stop_price"))),
            "quantity": _safe_float(order.get("origQty", order.get("orig_qty"))),
            "executed_quantity": _safe_float(order.get("executedQty", order.get("executed_qty"))),
            "reduce_only": _safe_bool(order.get("reduceOnly")) or _safe_bool(order.get("reduce_only")),
            "close_position": _safe_bool(order.get("closePosition")) or _safe_bool(order.get("close_position")),
            "can_increase_position": can_increase_position,
            "matching_position": matching_position,
            "in_live_universe": in_universe,
            "active": True,
        }
        order_summaries.append(summary)
        issue_base = {
            "symbol": symbol,
            "position_side": order_position_side,
            "order_id": summary["order_id"],
            "client_order_id": summary["client_order_id"],
            "side": summary["side"],
            "order_type": summary["order_type"],
        }
        if not in_universe:
            issues.append(
                {
                    **issue_base,
                    "type": "out_of_universe_open_order",
                    "severity": "FAIL",
                    "message": "Open order is outside the current live universe.",
                }
            )
        if can_increase_position and not matching_position:
            issues.append(
                {
                    **issue_base,
                    "type": "orphan_entry_order_without_position",
                    "severity": "FAIL",
                    "message": "Open order can create or increase a position, but no matching exchange position exists.",
                }
            )

    for position in open_positions:
        symbol = str(position.get("symbol") or "").upper()
        side = _position_side(position)
        has_stop = _has_stop_order(position, active_orders)
        has_tp = _has_take_profit_order(position, active_orders)
        in_universe = not allowed_symbols or symbol in allowed_symbols
        leverage = _position_leverage(position)
        leverage_cap_breached = leverage_cap > 0.0 and leverage > leverage_cap + 1e-12
        summary = {
            "symbol": symbol,
            "position_side": side,
            "position_amt": _position_amount(position),
            "entry_price": _safe_float(position.get("entryPrice", position.get("entry_price"))),
            "mark_price": _safe_float(position.get("markPrice", position.get("mark_price"))),
            "leverage": leverage,
            "leverage_cap": leverage_cap,
            "leverage_cap_breached": leverage_cap_breached,
            "has_stop": has_stop,
            "has_take_profit": has_tp,
            "in_live_universe": in_universe,
        }
        position_summaries.append(summary)
        if not has_stop:
            issues.append(
                {
                    "type": "missing_stop_protection",
                    "severity": "FAIL",
                    "symbol": symbol,
                    "position_side": side,
                    "message": "Open position has no matching exchange-side stop protection order.",
                }
            )
        if not has_tp:
            issues.append(
                {
                    "type": "missing_take_profit_protection",
                    "severity": "WARN",
                    "symbol": symbol,
                    "position_side": side,
                    "message": "Open position has no matching exchange-side take-profit order.",
                }
            )
        if not in_universe:
            issues.append(
                {
                    "type": "out_of_universe_open_position",
                    "severity": "FAIL",
                    "symbol": symbol,
                    "position_side": side,
                    "message": "Open position is outside the current live universe.",
                }
            )
        if leverage_cap_breached:
            issues.append(
                {
                    "type": "exchange_leverage_above_cap",
                    "severity": "FAIL",
                    "symbol": symbol,
                    "position_side": side,
                    "message": f"Exchange leverage {leverage:g}x is above configured cap {leverage_cap:g}x.",
                }
            )

    fail_count = sum(1 for item in issues if item["severity"] == "FAIL")
    warn_count = sum(1 for item in issues if item["severity"] == "WARN")
    return {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "overall_status": "ALERT" if issues else "OK",
        "severity": "FAIL" if fail_count else ("WARN" if warn_count else "INFO"),
        "issue_count": len(issues),
        "fail_count": fail_count,
        "warn_count": warn_count,
        "open_position_count": len(open_positions),
        "open_order_count": len(active_orders),
        "allowed_symbol_count": len(allowed_symbols),
        "issues": issues,
        "positions": position_summaries,
        "orders": order_summaries,
    }


def apply_missing_stop_flatten(
    payload: dict[str, Any],
    *,
    client: BinanceFuturesClient,
    live: bool,
    cancel_open_orders: bool = True,
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    stop_issue_keys = {
        (str(issue.get("symbol") or "").upper(), str(issue.get("position_side") or "").upper())
        for issue in list(payload.get("issues") or [])
        if str(issue.get("type") or "") == "missing_stop_protection"
        and str(issue.get("severity") or "").upper() == "FAIL"
    }
    if not stop_issue_keys:
        payload["missing_stop_flatten"] = {
            "enabled": bool(live),
            "status": "NO_ACTION",
            "action_count": 0,
            "actions": [],
        }
        return payload

    for position in list(payload.get("positions") or []):
        symbol = str(position.get("symbol") or "").upper()
        position_side = str(position.get("position_side") or "").upper()
        if (symbol, position_side) not in stop_issue_keys:
            continue
        raw_qty = abs(_safe_float(position.get("position_amt")))
        side = _close_side(position_side)
        action: dict[str, Any] = {
            "symbol": symbol,
            "position_side": position_side,
            "side": side,
            "raw_quantity": raw_qty,
            "live": bool(live),
            "cancel_open_orders": bool(cancel_open_orders),
        }
        if raw_qty <= 0.0:
            action["status"] = "SKIPPED_ZERO_POSITION"
            actions.append(action)
            continue

        quantity = raw_qty
        min_quantity = 0.0
        step = 0.0
        try:
            rules = client.fetch_symbol_trading_rules(symbol)
            step = _safe_float(getattr(rules, "quantity_step", 0.0))
            min_quantity = _safe_float(getattr(rules, "min_quantity", 0.0))
            quantity = _round_down_to_step(raw_qty, step=step)
        except Exception as exc:
            action["symbol_rules_error"] = f"{exc.__class__.__name__}:{exc}"
        action["quantity_step"] = step
        action["min_quantity"] = min_quantity
        action["quantity"] = quantity
        if quantity <= 0.0 or (min_quantity > 0.0 and quantity + 1e-12 < min_quantity):
            action["status"] = "SKIPPED_QUANTITY_BELOW_MINIMUM"
            actions.append(action)
            continue
        if not live:
            action["status"] = "DRY_RUN"
            actions.append(action)
            continue

        client_order_id = f"msw-flat-{symbol[:10].lower()}-{uuid4().hex[:8]}"
        try:
            submit = client.submit_order(
                symbol=symbol,
                side=side,
                order_type="MARKET",
                quantity=quantity,
                reduce_only=False if position_side in {"LONG", "SHORT"} else True,
                position_side=position_side if position_side in {"LONG", "SHORT"} else None,
                client_order_id=client_order_id,
                live=True,
                new_order_resp_type="RESULT",
            )
            action["status"] = "FLATTEN_SUBMITTED"
            action["client_order_id"] = client_order_id
            action["submit_result"] = submit
        except Exception as exc:
            action["status"] = "FLATTEN_FAILED"
            action["error"] = f"{exc.__class__.__name__}:{exc}"
            actions.append(action)
            continue

        if cancel_open_orders:
            cancels: list[dict[str, Any]] = []
            try:
                open_orders = client.fetch_open_orders(symbol=symbol)
                for order in list(open_orders or []):
                    client_order_id_to_cancel = str(order.get("clientOrderId") or order.get("client_order_id") or "")
                    order_id = order.get("orderId") or order.get("order_id")
                    if client_order_id_to_cancel == client_order_id:
                        continue
                    try:
                        cancel = client.cancel_order(
                            symbol=symbol,
                            order_id=int(order_id) if order_id not in {None, ""} else None,
                            client_order_id=client_order_id_to_cancel or None,
                        )
                        cancels.append(
                            {
                                "status": "CANCEL_SUBMITTED",
                                "order_id": order_id,
                                "client_order_id": client_order_id_to_cancel,
                                "result": cancel,
                            }
                        )
                    except Exception as exc:
                        cancels.append(
                            {
                                "status": "CANCEL_FAILED",
                                "order_id": order_id,
                                "client_order_id": client_order_id_to_cancel,
                                "error": f"{exc.__class__.__name__}:{exc}",
                            }
                        )
            except Exception as exc:
                action["cancel_open_orders_error"] = f"{exc.__class__.__name__}:{exc}"
                cancels = []
            action["cancel_results"] = cancels
        actions.append(action)

    failed_count = sum(1 for item in actions if str(item.get("status") or "").endswith("FAILED"))
    submitted_count = sum(1 for item in actions if str(item.get("status") or "") == "FLATTEN_SUBMITTED")
    payload["missing_stop_flatten"] = {
        "enabled": bool(live),
        "status": "FAILED" if failed_count else ("SUBMITTED" if submitted_count else "NO_LIVE_SUBMIT"),
        "action_count": len(actions),
        "submitted_count": submitted_count,
        "failed_count": failed_count,
        "actions": actions,
    }
    return payload


def apply_unexpected_open_order_cancel(
    payload: dict[str, Any],
    *,
    client: BinanceFuturesClient,
    live: bool,
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    for order in list(payload.get("orders") or []):
        if not _safe_bool(order.get("active"), default=True):
            continue
        matching_position = _safe_bool(order.get("matching_position"))
        can_increase_position = _safe_bool(order.get("can_increase_position"))
        in_universe = _safe_bool(order.get("in_live_universe"), default=True)
        if matching_position:
            continue
        if can_increase_position:
            reason = "orphan_entry_order_without_position"
        elif not in_universe:
            reason = "out_of_universe_open_order_without_position"
        else:
            continue

        symbol = str(order.get("symbol") or "").upper()
        order_id_raw = order.get("order_id")
        client_order_id = str(order.get("client_order_id") or "")
        order_id = None
        try:
            order_id = int(order_id_raw) if order_id_raw not in {None, ""} else None
        except (TypeError, ValueError):
            order_id = None
        action: dict[str, Any] = {
            "symbol": symbol,
            "order_id": order_id_raw,
            "client_order_id": client_order_id,
            "side": order.get("side"),
            "position_side": order.get("position_side"),
            "order_type": order.get("order_type"),
            "reason": reason,
            "live": bool(live),
        }
        if not symbol or (order_id is None and not client_order_id):
            action["status"] = "SKIPPED_MISSING_ORDER_REFERENCE"
            actions.append(action)
            continue
        if not live:
            action["status"] = "DRY_RUN"
            actions.append(action)
            continue
        try:
            action["result"] = client.cancel_order(
                symbol=symbol,
                order_id=order_id,
                client_order_id=client_order_id or None,
            )
            action["status"] = "CANCEL_SUBMITTED"
        except Exception as exc:
            action["status"] = "CANCEL_FAILED"
            action["error"] = f"{exc.__class__.__name__}:{exc}"
        actions.append(action)

    failed_count = sum(1 for item in actions if str(item.get("status") or "") == "CANCEL_FAILED")
    submitted_count = sum(1 for item in actions if str(item.get("status") or "") == "CANCEL_SUBMITTED")
    payload["unexpected_open_order_cancel"] = {
        "enabled": bool(live),
        "status": "FAILED" if failed_count else ("SUBMITTED" if submitted_count else "NO_ACTION"),
        "action_count": len(actions),
        "submitted_count": submitted_count,
        "failed_count": failed_count,
        "actions": actions,
    }
    return payload


def build_payload(*, symbols: set[str] | None = None) -> dict[str, Any]:
    settings = get_settings()
    allowed_symbols = set(symbols or set())
    if not allowed_symbols:
        allowed_symbols = _csv_set(getattr(settings, "auto_trading_micro_live_allowed_symbols", ""))
    client = BinanceFuturesClient()
    raw_positions = client.fetch_position_risk()
    raw_open_orders = client.fetch_open_orders()
    positions = [client.normalize_position_risk_row(row) for row in raw_positions]
    return evaluate_account_protection(
        positions=positions,
        open_orders=raw_open_orders,
        allowed_symbols=allowed_symbols,
        leverage_cap=_safe_float(getattr(settings, "auto_trading_live_leverage_cap", 0.0)),
        now=datetime.now(UTC),
    )


def _write_report(path: Path, payload: dict[str, Any], *, atomic: bool = False) -> None:
    lines = [
        "# Live Account Protection Audit",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- status: {payload.get('overall_status')}",
        f"- severity: {payload.get('severity')}",
        f"- open_positions: {payload.get('open_position_count')}",
        f"- open_orders: {payload.get('open_order_count')}",
        f"- issues: {payload.get('issue_count')} fail={payload.get('fail_count')} warn={payload.get('warn_count')}",
        "",
        "## Issues",
        "",
    ]
    for issue in list(payload.get("issues") or [])[:30]:
        lines.append(
            f"- {issue.get('severity')} {issue.get('type')} {issue.get('symbol')} "
            f"{issue.get('position_side')}: {issue.get('message')}"
        )
    if not payload.get("issues"):
        lines.append("- none")
    lines.extend(["", "```json", json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), "```"])
    if atomic:
        atomic_write_text(path, "\n".join(lines))
    else:
        atomic_write_text(path, "\n".join(lines))


def main() -> int:
    args = parse_args()
    settings = get_settings()
    try:
        payload = build_payload(symbols=_csv_set(args.symbols))
    except Exception as exc:
        payload = {
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "overall_status": "ALERT",
            "severity": "FAIL",
            "issue_count": 1,
            "fail_count": 1,
            "warn_count": 0,
            "open_position_count": 0,
            "open_order_count": 0,
            "issues": [
                {
                    "type": "account_protection_audit_error",
                    "severity": "FAIL",
                    "message": f"{exc.__class__.__name__}:{exc}",
                }
            ],
        }
    flatten_enabled = _safe_bool(
        getattr(settings, "auto_trading_live_missing_stop_watchdog_flatten_enabled", False),
        default=False,
    )
    if args.flatten_missing_stop:
        flatten_enabled = True
    if args.no_flatten_missing_stop:
        flatten_enabled = False
    cancel_open_orders = _safe_bool(
        getattr(settings, "auto_trading_live_missing_stop_watchdog_cancel_open_orders", True),
        default=True,
    )
    if args.no_cancel_open_orders_after_flatten:
        cancel_open_orders = False
    if flatten_enabled:
        try:
            payload = apply_missing_stop_flatten(
                payload,
                client=BinanceFuturesClient(),
                live=True,
                cancel_open_orders=cancel_open_orders,
            )
        except Exception as exc:
            payload["missing_stop_flatten"] = {
                "enabled": True,
                "status": "WATCHDOG_ERROR",
                "error": f"{exc.__class__.__name__}:{exc}",
                "action_count": 0,
                "actions": [],
            }
    unexpected_cancel_enabled = _safe_bool(
        getattr(settings, "auto_trading_live_unexpected_open_order_watchdog_cancel_enabled", False),
        default=False,
    )
    if args.cancel_unexpected_open_orders:
        unexpected_cancel_enabled = True
    if args.no_cancel_unexpected_open_orders:
        unexpected_cancel_enabled = False
    if unexpected_cancel_enabled:
        try:
            payload = apply_unexpected_open_order_cancel(
                payload,
                client=BinanceFuturesClient(),
                live=True,
            )
        except Exception as exc:
            payload["unexpected_open_order_cancel"] = {
                "enabled": True,
                "status": "WATCHDOG_ERROR",
                "error": f"{exc.__class__.__name__}:{exc}",
                "action_count": 0,
                "actions": [],
            }
    else:
        payload["unexpected_open_order_cancel"] = {
            "enabled": False,
            "status": "DISABLED",
            "action_count": 0,
            "actions": [],
        }
    if not args.no_write_report:
        generated = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
        report_dir = _resolve_report_dir(args.report_dir)
        report_path = report_dir / f"live_account_protection_audit_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
        _write_report(report_path, payload, atomic=True)
        payload["report_path"] = display_path(report_path, ROOT_DIR)
        payload["latest_paths"] = write_latest_aliases(
            report_dir=report_dir,
            payload=payload,
            write_markdown_report=_write_report,
            root_dir=ROOT_DIR,
            json_default=_json_default,
        )
    if not args.quiet:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 1 if payload.get("overall_status") == "ALERT" and not args.no_fail_exit else 0


if __name__ == "__main__":
    raise SystemExit(main())
