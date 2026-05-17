#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text


@dataclass(frozen=True, slots=True)
class TradeRow:
    symbol: str
    direction: str
    entry_ts: datetime
    exit_ts: datetime
    entry_price: float
    stop_price: float
    r_value: float
    stop_pct: float
    scores: dict[str, float]


@dataclass(frozen=True, slots=True)
class AllocationModel:
    name: str
    weights: dict[str, float]
    shape: str
    min_r: float
    mid_r: float
    max_r: float
    gamma: float = 1.0


@dataclass(frozen=True, slots=True)
class Case:
    account_equity: float
    risk_pct: float
    leverage_cap: float
    max_concurrent: int
    total_risk_cap_r: float
    daily_cap: int
    score_floor: float
    min_entry_r: float
    allocation_model: AllocationModel


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Optimize portfolio execution settings from a trade-including micro-main backtest report. "
            "This replays the already generated signal rows with live-like risk, margin, and position constraints."
        )
    )
    parser.add_argument("--backtest-path", required=True)
    parser.add_argument("--label", default="")
    parser.add_argument("--accounts", default="170,1000")
    parser.add_argument("--risk-pcts", default="0.003,0.004,0.005,0.006,0.0075,0.01,0.0125")
    parser.add_argument("--leverage-caps", default="7,10,15")
    parser.add_argument("--max-concurrent", default="2,3,4,5,6")
    parser.add_argument("--total-risk-caps", default="0.75,1.0,1.25,1.5,1.75,2.0,2.25,2.5,3.0,3.5")
    parser.add_argument("--daily-caps", default="0,4,6,8,10")
    parser.add_argument("--score-floors", default="0,0.15,0.30")
    parser.add_argument("--min-entry-rs", default="0.15,0.20,0.25")
    parser.add_argument(
        "--allocation-models",
        default="",
        help="Optional comma-separated allocation model names. Defaults to the full built-in model grid.",
    )
    parser.add_argument("--usable-margin-fraction", type=float, default=0.85)
    parser.add_argument("--cluster-window-minutes", type=int, default=30)
    parser.add_argument("--cluster-cap", type=int, default=3)
    parser.add_argument("--same-direction-cap", type=int, default=3)
    parser.add_argument("--capacity-mode", choices=("off", "current-liquidity"), default="off")
    parser.add_argument("--capacity-orderbook-limit", type=int, default=100)
    parser.add_argument("--capacity-min-depth-usdt", type=float, default=50_000.0)
    parser.add_argument("--capacity-max-depth-participation", type=float, default=0.10)
    parser.add_argument("--capacity-max-1m-volume-participation", type=float, default=0.02)
    parser.add_argument("--capacity-max-5m-volume-participation", type=float, default=0.01)
    parser.add_argument("--capacity-min-target-fraction", type=float, default=0.50)
    parser.add_argument("--capacity-min-tranche-notional-usdt", type=float, default=10.0)
    parser.add_argument("--top-n", type=int, default=40)
    parser.add_argument("--max-cases", type=int, default=0, help="Optional deterministic cap after case generation.")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if math.isfinite(parsed) else float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return int(default)
    return int(parsed) if math.isfinite(parsed) else int(default)


def _float_list(raw: Any) -> list[float]:
    out: list[float] = []
    for token in str(raw or "").split(","):
        text = token.strip()
        if text:
            out.append(float(text))
    if not out:
        raise ValueError("float list must not be empty")
    return out


def _int_list(raw: Any) -> list[int]:
    return [int(round(value)) for value in _float_list(raw)]


def _parse_dt(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _clip(value: float, low: float, high: float) -> float:
    return min(max(float(value), low), high)


def _scale_high(value: Any, low: float, high: float) -> float:
    return _clip((_safe_float(value) - low) / max(high - low, 1e-12), 0.0, 1.0)


def _scale_low(value: Any, low: float, high: float) -> float:
    return 1.0 - _scale_high(value, low, high)


def _feature_scores(row: dict[str, Any]) -> dict[str, float]:
    diagnostics = dict(row.get("diagnostics") or {})
    return {
        "body": _scale_high(diagnostics.get("reclaim_body_atr"), 0.20, 0.60),
        "volume": _scale_high(diagnostics.get("volume_factor"), 0.90, 2.20),
        "trend": _scale_high(diagnostics.get("trend_strength_atr"), 0.45, 1.25),
        "overshoot": _scale_low(diagnostics.get("reclaim_overshoot_atr"), 0.05, 0.35),
        "risk": _scale_low(diagnostics.get("risk_atr"), 0.30, 1.15),
        "speed": _scale_low(diagnostics.get("retest_wait_minutes"), 0.0, 10.0),
    }


def _allocation_models() -> list[AllocationModel]:
    weight_sets: list[tuple[str, dict[str, float]]] = [
        ("balanced", {"body": 1.0, "volume": 1.0, "trend": 1.0, "overshoot": 1.0, "risk": 1.0, "speed": 0.5}),
        ("quality", {"body": 1.4, "volume": 1.2, "trend": 1.2, "overshoot": 1.0, "risk": 0.8, "speed": 0.4}),
        ("safety", {"body": 1.0, "volume": 1.0, "trend": 1.0, "overshoot": 1.2, "risk": 1.5, "speed": 0.8}),
        ("volume_trend", {"body": 0.9, "volume": 1.6, "trend": 1.5, "overshoot": 0.7, "risk": 0.7, "speed": 0.3}),
        ("clean_retest", {"body": 1.1, "volume": 0.9, "trend": 0.9, "overshoot": 1.5, "risk": 1.1, "speed": 1.0}),
    ]
    shapes: list[tuple[str, float, float, float, float]] = [
        ("fixed_060", 0.60, 0.60, 0.60, 1.0),
        ("fixed_080", 0.80, 0.80, 0.80, 1.0),
        ("fixed_100", 1.00, 1.00, 1.00, 1.0),
        ("tier_025_050_100", 0.25, 0.50, 1.00, 1.0),
        ("tier_030_060_100", 0.30, 0.60, 1.00, 1.0),
        ("linear_020_100_g075", 0.20, 0.60, 1.00, 0.75),
        ("linear_020_100_g100", 0.20, 0.60, 1.00, 1.00),
        ("linear_020_100_g150", 0.20, 0.60, 1.00, 1.50),
        ("linear_030_080_g100", 0.30, 0.55, 0.80, 1.00),
        ("linear_035_100_g125", 0.35, 0.70, 1.00, 1.25),
    ]
    out: list[AllocationModel] = []
    for weight_name, weights in weight_sets:
        for shape, min_r, mid_r, max_r, gamma in shapes:
            if shape.startswith("fixed") and weight_name != "balanced":
                continue
            out.append(
                AllocationModel(
                    name=f"{weight_name}:{shape}",
                    weights=weights,
                    shape=shape,
                    min_r=min_r,
                    mid_r=mid_r,
                    max_r=max_r,
                    gamma=gamma,
                )
            )
    return out


def _weighted_score(scores: dict[str, float], weights: dict[str, float]) -> float:
    total_weight = sum(max(float(value), 0.0) for value in weights.values())
    if total_weight <= 0.0:
        return 0.0
    return _clip(
        sum(float(scores.get(key, 0.0)) * max(float(weight), 0.0) for key, weight in weights.items()) / total_weight,
        0.0,
        1.0,
    )


def _risk_multiplier(score: float, model: AllocationModel) -> float:
    if model.shape.startswith("fixed"):
        return model.max_r
    if model.shape.startswith("tier"):
        if score < 0.333333:
            return model.min_r
        if score < 0.666667:
            return model.mid_r
        return model.max_r
    shaped = math.pow(_clip(score, 0.0, 1.0), max(float(model.gamma), 0.01))
    return _clip(model.min_r + (model.max_r - model.min_r) * shaped, 0.0, model.max_r)


def _round_down_to_step(value: float, *, step: float) -> float:
    if step <= 0.0:
        return max(value, 0.0)
    return math.floor(max(value, 0.0) / step + 1e-12) * step


def _load_trade_rows(path: Path) -> tuple[dict[str, Any], list[TradeRow]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[TradeRow] = []
    for item in dict(payload.get("results") or {}).values():
        if not isinstance(item, dict):
            continue
        for raw in list(item.get("trades") or []):
            if not isinstance(raw, dict):
                continue
            entry_price = _safe_float(raw.get("entry_price"))
            stop_price = _safe_float(raw.get("stop_price"))
            stop_pct = _safe_float(raw.get("stop_distance_pct"))
            if stop_pct <= 0.0 and entry_price > 0.0:
                stop_pct = abs(entry_price - stop_price) / entry_price
            if entry_price <= 0.0 or stop_pct <= 0.0:
                continue
            rows.append(
                TradeRow(
                    symbol=str(raw.get("proxy_symbol") or raw.get("symbol") or "").strip().upper(),
                    direction=str(raw.get("direction") or "").strip().lower(),
                    entry_ts=_parse_dt(raw.get("entry_ts")),
                    exit_ts=_parse_dt(raw.get("exit_ts")),
                    entry_price=entry_price,
                    stop_price=stop_price,
                    r_value=_safe_float(raw.get("r_value")),
                    stop_pct=stop_pct,
                    scores=_feature_scores(raw),
                )
            )
    rows.sort(key=lambda row: (row.entry_ts, row.exit_ts, row.symbol))
    if not rows:
        raise ValueError(f"Backtest report has no usable trade rows: {path}")
    return payload, rows


def _fetch_symbol_rules(symbols: Iterable[str]) -> dict[str, dict[str, float]]:
    settings = get_settings()
    rules: dict[str, dict[str, float]] = {}
    url = f"{settings.binance_rest_base_url.rstrip('/')}/fapi/v1/exchangeInfo"
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        print(json.dumps({"warning": "exchange_info_fetch_failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        payload = {}
    for item in list(dict(payload).get("symbols") or []):
        symbol = str(item.get("symbol") or "").upper()
        if not symbol:
            continue
        lot = {}
        for filt in list(item.get("filters") or []):
            if str(filt.get("filterType") or "") == "LOT_SIZE":
                lot = dict(filt)
                break
        step = _safe_float(lot.get("stepSize"), 0.0)
        min_qty = _safe_float(lot.get("minQty"), 0.0)
        if step > 0.0 or min_qty > 0.0:
            rules[symbol] = {
                "quantity_step": step if step > 0.0 else 1e-9,
                "min_quantity": min_qty if min_qty > 0.0 else step,
            }
    for symbol in symbols:
        rules.setdefault(str(symbol).upper(), {"quantity_step": 1e-9, "min_quantity": 0.0})
    return rules


def _quote_volume_from_kline(row: Any) -> float:
    values = list(row or [])
    if len(values) >= 6:
        close_price = _safe_float(values[4])
        base_volume = _safe_float(values[5])
        return max(close_price * base_volume, 0.0)
    return 0.0


def _allowed_notional_from_liquidity(
    *,
    opposite_depth_notional: float,
    recent_1m_quote_volume: float,
    recent_5m_quote_volume: float,
    min_depth_usdt: float,
    max_depth_participation: float,
    max_1m_volume_participation: float,
    max_5m_volume_participation: float,
) -> float:
    if min_depth_usdt > 0.0 and opposite_depth_notional < min_depth_usdt:
        return 0.0
    caps: list[float] = []
    if max_depth_participation > 0.0 and opposite_depth_notional > 0.0:
        caps.append(opposite_depth_notional * max_depth_participation)
    if max_1m_volume_participation > 0.0 and recent_1m_quote_volume > 0.0:
        caps.append(recent_1m_quote_volume * max_1m_volume_participation)
    if max_5m_volume_participation > 0.0 and recent_5m_quote_volume > 0.0:
        caps.append(recent_5m_quote_volume * max_5m_volume_participation)
    return max(min(caps), 0.0) if caps else 0.0


def _fetch_current_capacity_caps(symbols: Iterable[str], args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    symbol_list = sorted({str(symbol or "").strip().upper() for symbol in symbols if str(symbol or "").strip()})
    if str(args.capacity_mode) != "current-liquidity":
        return {"enabled": False, "source": "disabled", "symbols": {}}

    base_url = settings.binance_rest_base_url.rstrip("/")
    details: dict[str, Any] = {}
    with httpx.Client(base_url=base_url, timeout=20.0) as client:
        for symbol in symbol_list:
            try:
                depth = client.get(
                    "/fapi/v1/depth",
                    params={"symbol": symbol, "limit": max(5, int(args.capacity_orderbook_limit))},
                )
                depth.raise_for_status()
                depth_payload = depth.json()
                klines = client.get("/fapi/v1/klines", params={"symbol": symbol, "interval": "1m", "limit": 5})
                klines.raise_for_status()
                kline_rows = list(klines.json() or [])
            except Exception as exc:
                details[symbol] = {"error": str(exc), "long_allowed_notional": 0.0, "short_allowed_notional": 0.0}
                continue

            bids = [
                (_safe_float(level[0]), _safe_float(level[1]))
                for level in list(dict(depth_payload).get("bids") or [])
                if isinstance(level, list) and len(level) >= 2
            ]
            asks = [
                (_safe_float(level[0]), _safe_float(level[1]))
                for level in list(dict(depth_payload).get("asks") or [])
                if isinstance(level, list) and len(level) >= 2
            ]
            bid_depth = sum(price * qty for price, qty in bids if price > 0.0 and qty > 0.0)
            ask_depth = sum(price * qty for price, qty in asks if price > 0.0 and qty > 0.0)
            now_ms = int(datetime.now(UTC).timestamp() * 1000)
            closed_kline_rows = [
                row
                for row in kline_rows
                if not isinstance(row, list)
                or len(row) < 7
                or int(_safe_float(row[6], default=0.0)) <= now_ms
            ]
            quote_volumes = [_quote_volume_from_kline(row) for row in closed_kline_rows]
            quote_volumes = [value for value in quote_volumes if value > 0.0]
            volume_1m = quote_volumes[-1] if quote_volumes else 0.0
            volume_5m = sum(quote_volumes[-5:])
            long_allowed = _allowed_notional_from_liquidity(
                opposite_depth_notional=ask_depth,
                recent_1m_quote_volume=volume_1m,
                recent_5m_quote_volume=volume_5m,
                min_depth_usdt=float(args.capacity_min_depth_usdt),
                max_depth_participation=float(args.capacity_max_depth_participation),
                max_1m_volume_participation=float(args.capacity_max_1m_volume_participation),
                max_5m_volume_participation=float(args.capacity_max_5m_volume_participation),
            )
            short_allowed = _allowed_notional_from_liquidity(
                opposite_depth_notional=bid_depth,
                recent_1m_quote_volume=volume_1m,
                recent_5m_quote_volume=volume_5m,
                min_depth_usdt=float(args.capacity_min_depth_usdt),
                max_depth_participation=float(args.capacity_max_depth_participation),
                max_1m_volume_participation=float(args.capacity_max_1m_volume_participation),
                max_5m_volume_participation=float(args.capacity_max_5m_volume_participation),
            )
            details[symbol] = {
                "bid_depth_notional": round(bid_depth, 4),
                "ask_depth_notional": round(ask_depth, 4),
                "recent_1m_quote_volume": round(volume_1m, 4),
                "recent_5m_quote_volume": round(volume_5m, 4),
                "long_allowed_notional": round(long_allowed, 4),
                "short_allowed_notional": round(short_allowed, 4),
            }
    return {
        "enabled": True,
        "source": "binance_current_depth_and_1m_klines",
        "thresholds": {
            "orderbook_limit": int(args.capacity_orderbook_limit),
            "min_depth_usdt": float(args.capacity_min_depth_usdt),
            "max_depth_participation": float(args.capacity_max_depth_participation),
            "max_1m_volume_participation": float(args.capacity_max_1m_volume_participation),
            "max_5m_volume_participation": float(args.capacity_max_5m_volume_participation),
            "min_target_fraction": float(args.capacity_min_target_fraction),
            "min_tranche_notional_usdt": float(args.capacity_min_tranche_notional_usdt),
        },
        "symbols": details,
    }


def _build_cases(args: argparse.Namespace) -> list[Case]:
    models = _allocation_models()
    requested_models = {item.strip() for item in str(args.allocation_models or "").split(",") if item.strip()}
    if requested_models:
        models = [model for model in models if model.name in requested_models]
        missing = sorted(requested_models - {model.name for model in models})
        if missing:
            raise ValueError(f"unknown allocation models: {', '.join(missing)}")
    cases: list[Case] = []
    for account in _float_list(args.accounts):
        for risk_pct in _float_list(args.risk_pcts):
            for leverage_cap in _float_list(args.leverage_caps):
                for max_concurrent in _int_list(args.max_concurrent):
                    for total_risk_cap in _float_list(args.total_risk_caps):
                        for daily_cap in _int_list(args.daily_caps):
                            for score_floor in _float_list(args.score_floors):
                                for min_entry_r in _float_list(args.min_entry_rs):
                                    for model in models:
                                        if total_risk_cap + 1e-12 < min_entry_r:
                                            continue
                                        if max_concurrent <= 0:
                                            continue
                                        cases.append(
                                            Case(
                                                account_equity=account,
                                                risk_pct=risk_pct,
                                                leverage_cap=leverage_cap,
                                                max_concurrent=max_concurrent,
                                                total_risk_cap_r=total_risk_cap,
                                                daily_cap=daily_cap,
                                                score_floor=score_floor,
                                                min_entry_r=min_entry_r,
                                                allocation_model=model,
                                            )
                                        )
    cases.sort(
        key=lambda case: (
            case.account_equity,
            case.risk_pct,
            case.max_concurrent,
            case.total_risk_cap_r,
            case.daily_cap,
            case.leverage_cap,
            case.score_floor,
            case.min_entry_r,
            case.allocation_model.name,
        )
    )
    if int(args.max_cases or 0) > 0:
        limit = int(args.max_cases)
        if len(cases) > limit:
            step = len(cases) / limit
            cases = [cases[min(int(idx * step), len(cases) - 1)] for idx in range(limit)]
    return cases


def _case_settings(case: Case) -> dict[str, Any]:
    return {
        "account_equity": case.account_equity,
        "risk_pct": case.risk_pct,
        "leverage_cap": case.leverage_cap,
        "max_concurrent": case.max_concurrent,
        "total_risk_cap_r": case.total_risk_cap_r,
        "daily_cap": case.daily_cap,
        "score_floor": case.score_floor,
        "min_entry_r": case.min_entry_r,
        "allocation_model": case.allocation_model.name,
    }


def _simulate_case(
    *,
    trades: list[TradeRow],
    symbol_rules: dict[str, dict[str, float]],
    capacity_caps: dict[str, Any],
    case: Case,
    usable_margin_fraction: float,
    cluster_window_minutes: int,
    cluster_cap: int,
    same_direction_cap: int,
) -> dict[str, Any]:
    active: list[tuple[TradeRow, float]] = []
    accepted: list[tuple[TradeRow, float, float, float]] = []
    day_counts: dict[str, int] = {}
    blocked = {
        "score_floor": 0,
        "daily_cap": 0,
        "max_concurrent": 0,
        "cluster_cap": 0,
        "same_direction_cap": 0,
        "risk_budget": 0,
        "min_quantity": 0,
        "leverage_cap": 0,
        "capacity_cap": 0,
        "capacity_min_fraction": 0,
        "capacity_min_tranche": 0,
    }
    total_signal_count = len(trades)
    target_risk_unit = case.account_equity * case.risk_pct
    leverage_cap_notional = case.account_equity * usable_margin_fraction * case.leverage_cap
    cluster_window_seconds = max(int(cluster_window_minutes), 0) * 60

    for trade in trades:
        active = [(item, risk_r) for item, risk_r in active if item.exit_ts > trade.entry_ts]
        score = _weighted_score(trade.scores, case.allocation_model.weights)
        if score + 1e-12 < case.score_floor:
            blocked["score_floor"] += 1
            continue

        day_key = trade.entry_ts.astimezone(timezone.utc).date().isoformat()
        if case.daily_cap > 0 and day_counts.get(day_key, 0) >= case.daily_cap:
            blocked["daily_cap"] += 1
            continue

        if len(active) >= case.max_concurrent:
            blocked["max_concurrent"] += 1
            continue

        if cluster_window_seconds > 0 and cluster_cap > 0:
            cutoff_ts = trade.entry_ts.timestamp() - cluster_window_seconds
            if sum(1 for item, _risk_r in active if item.entry_ts.timestamp() >= cutoff_ts) >= cluster_cap:
                blocked["cluster_cap"] += 1
                continue

        if same_direction_cap > 0:
            if sum(1 for item, _risk_r in active if item.direction == trade.direction) >= same_direction_cap:
                blocked["same_direction_cap"] += 1
                continue

        desired_r = _risk_multiplier(score, case.allocation_model)
        active_r = sum(risk_r for _item, risk_r in active)
        remaining_r = max(case.total_risk_cap_r - active_r, 0.0)
        allocated_r = min(desired_r, remaining_r, 1.0)
        if allocated_r + 1e-12 < case.min_entry_r:
            blocked["risk_budget"] += 1
            continue

        target_risk_usdt = target_risk_unit * allocated_r
        target_notional = target_risk_usdt / max(trade.stop_pct, 1e-12)
        capped_notional = min(target_notional, leverage_cap_notional)
        if capped_notional + 1e-12 < target_notional:
            blocked["leverage_cap"] += 1
        if dict(capacity_caps or {}).get("enabled"):
            symbol_capacity = dict(dict(capacity_caps.get("symbols") or {}).get(trade.symbol) or {})
            capacity_key = "short_allowed_notional" if trade.direction == "short" else "long_allowed_notional"
            allowed_notional = _safe_float(symbol_capacity.get(capacity_key))
            if allowed_notional <= 0.0:
                blocked["capacity_cap"] += 1
                continue
            if capped_notional > allowed_notional:
                reduced_notional = min(capped_notional, allowed_notional)
                capacity_thresholds = dict(capacity_caps.get("thresholds") or {})
                min_fraction = _clip(_safe_float(capacity_thresholds.get("min_target_fraction"), 0.0), 0.0, 1.0)
                if min_fraction > 0.0 and reduced_notional + 1e-12 < target_notional * min_fraction:
                    blocked["capacity_min_fraction"] += 1
                    continue
                min_tranche = max(_safe_float(capacity_thresholds.get("min_tranche_notional_usdt"), 0.0), 0.0)
                if min_tranche > 0.0 and reduced_notional + 1e-12 < min_tranche:
                    blocked["capacity_min_tranche"] += 1
                    continue
                capped_notional = reduced_notional
                blocked["capacity_cap"] += 1
        rules = symbol_rules.get(trade.symbol) or {"quantity_step": 1e-9, "min_quantity": 0.0}
        step = max(_safe_float(rules.get("quantity_step"), 1e-9), 1e-9)
        min_qty = max(_safe_float(rules.get("min_quantity"), 0.0), 0.0)
        raw_qty = capped_notional / max(trade.entry_price, 1e-12)
        qty = _round_down_to_step(raw_qty, step=step)
        if qty + 1e-12 < min_qty:
            blocked["min_quantity"] += 1
            continue

        actual_notional = qty * trade.entry_price
        actual_risk_usdt = actual_notional * trade.stop_pct
        actual_r = actual_risk_usdt / max(target_risk_unit, 1e-12)
        if actual_r + 1e-12 < case.min_entry_r:
            blocked["risk_budget"] += 1
            continue
        accepted.append((trade, actual_risk_usdt, actual_r, score))
        active.append((trade, actual_r))
        day_counts[day_key] = day_counts.get(day_key, 0) + 1

    equity = case.account_equity
    peak = equity
    max_drawdown_pct = 0.0
    max_drawdown_usdt = 0.0
    wins = 0
    gross_r = 0.0
    actual_r_sum = 0.0
    by_year: dict[int, float] = {}
    by_year_trades: dict[int, int] = {}
    for trade, actual_risk_usdt, actual_r, _score in sorted(accepted, key=lambda item: (item[0].exit_ts, item[0].entry_ts, item[0].symbol)):
        pnl = actual_risk_usdt * trade.r_value
        equity += pnl
        peak = max(peak, equity)
        if peak > 0:
            drawdown_usdt = max(0.0, peak - equity)
            max_drawdown_usdt = max(max_drawdown_usdt, drawdown_usdt)
            max_drawdown_pct = max(max_drawdown_pct, drawdown_usdt / peak * 100.0)
        wins += 1 if trade.r_value > 0.0 else 0
        weighted_r = trade.r_value * actual_r
        gross_r += weighted_r
        actual_r_sum += actual_r
        year = trade.entry_ts.year
        by_year[year] = by_year.get(year, 0.0) + weighted_r
        by_year_trades[year] = by_year_trades.get(year, 0) + 1

    accepted_count = len(accepted)
    return_pct = ((equity / case.account_equity) - 1.0) * 100.0 if case.account_equity > 0 else 0.0
    max_drawdown_initial_pct = max_drawdown_usdt / max(case.account_equity, 1e-12) * 100.0
    avg_actual_r = actual_r_sum / accepted_count if accepted_count else 0.0
    years_positive = sum(1 for value in by_year.values() if value > 0.0)
    year_count = len(by_year)
    practical_score = (
        return_pct
        - max_drawdown_initial_pct * 2.0
        - max_drawdown_pct * 1.0
        + years_positive * 25.0
        - (total_signal_count - accepted_count) / max(total_signal_count, 1) * 20.0
    )
    return {
        **_case_settings(case),
        "signals": total_signal_count,
        "accepted": accepted_count,
        "accepted_pct": round(accepted_count / max(total_signal_count, 1), 4),
        "blocked": {key: value for key, value in blocked.items() if value},
        "ending_equity": round(equity, 2),
        "return_pct": round(return_pct, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "max_drawdown_initial_pct": round(max_drawdown_initial_pct, 2),
        "max_drawdown_usdt": round(max_drawdown_usdt, 2),
        "return_to_dd": round(return_pct / max(max_drawdown_pct, 1.0), 4),
        "return_to_initial_dd": round(return_pct / max(max_drawdown_initial_pct, 1.0), 4),
        "weighted_total_r": round(gross_r, 4),
        "weighted_ev_r": round(gross_r / accepted_count, 4) if accepted_count else 0.0,
        "win_rate": round(wins / accepted_count, 4) if accepted_count else 0.0,
        "avg_actual_r": round(avg_actual_r, 4),
        "years_positive": years_positive,
        "year_count": year_count,
        "years": {
            str(year): {
                "weighted_total_r": round(value, 4),
                "trades": by_year_trades.get(year, 0),
            }
            for year, value in sorted(by_year.items())
        },
        "practical_score": round(practical_score, 4),
    }


def _baseline_stats(trades: list[TradeRow]) -> dict[str, Any]:
    total = sum(row.r_value for row in trades)
    wins = sum(1 for row in trades if row.r_value > 0.0)
    by_symbol: dict[str, list[TradeRow]] = {}
    for row in trades:
        by_symbol.setdefault(row.symbol, []).append(row)
    return {
        "signals": len(trades),
        "symbols": len(by_symbol),
        "total_r": round(total, 4),
        "ev_r": round(total / max(len(trades), 1), 4),
        "win_rate": round(wins / max(len(trades), 1), 4),
    }


def _select_top(rows: list[dict[str, Any]], *, top_n: int) -> dict[str, Any]:
    min_trades = max(1, int(max(row.get("signals", 0) for row in rows) * 0.20)) if rows else 1
    viable = [
        row
        for row in rows
        if _safe_int(row.get("accepted")) >= min_trades
        and _safe_int(row.get("years_positive")) >= max(1, _safe_int(row.get("year_count")) - 1)
    ]
    by_practical = sorted(
        viable,
        key=lambda row: (_safe_float(row.get("practical_score")), _safe_float(row.get("return_to_initial_dd"))),
        reverse=True,
    )
    by_return_to_dd = sorted(
        viable,
        key=lambda row: (_safe_float(row.get("return_to_initial_dd")), _safe_float(row.get("return_pct"))),
        reverse=True,
    )
    by_return = sorted(
        viable,
        key=lambda row: (_safe_float(row.get("return_pct")), -_safe_float(row.get("max_drawdown_initial_pct"))),
        reverse=True,
    )
    conservative = [
        row
        for row in viable
        if _safe_float(row.get("max_drawdown_initial_pct")) <= 25.0 and _safe_float(row.get("accepted_pct")) >= 0.35
    ]
    conservative.sort(
        key=lambda row: (_safe_float(row.get("return_to_initial_dd")), _safe_float(row.get("return_pct"))),
        reverse=True,
    )
    def _account_key(account: float) -> str:
        return str(int(account) if account.is_integer() else account)

    def _rank_account_rows(account_rows: list[dict[str, Any]]) -> dict[str, Any]:
        practical_rows = sorted(
            account_rows,
            key=lambda row: (_safe_float(row.get("practical_score")), _safe_float(row.get("return_to_initial_dd"))),
            reverse=True,
        )
        efficiency_rows = sorted(
            account_rows,
            key=lambda row: (_safe_float(row.get("return_to_initial_dd")), _safe_float(row.get("return_pct"))),
            reverse=True,
        )
        raw_rows = sorted(
            account_rows,
            key=lambda row: (_safe_float(row.get("return_pct")), -_safe_float(row.get("max_drawdown_initial_pct"))),
            reverse=True,
        )
        return {
            "top_practical": practical_rows[: min(top_n, 12)],
            "top_return_to_initial_dd": efficiency_rows[: min(top_n, 12)],
            "top_raw_return": raw_rows[: min(top_n, 12)],
        }

    by_account: dict[str, dict[str, Any]] = {}
    for account in sorted({_safe_float(row.get("account_equity")) for row in viable}):
        account_rows = [row for row in viable if _safe_float(row.get("account_equity")) == account]
        by_account[_account_key(account)] = _rank_account_rows(account_rows)

    by_account_all: dict[str, dict[str, Any]] = {}
    for account in sorted({_safe_float(row.get("account_equity")) for row in rows}):
        account_rows = [row for row in rows if _safe_float(row.get("account_equity")) == account]
        ranked = _rank_account_rows(account_rows)
        ranked["candidate_count"] = len(account_rows)
        ranked["viable_count"] = sum(
            1
            for row in account_rows
            if _safe_int(row.get("accepted")) >= min_trades
            and _safe_int(row.get("years_positive")) >= max(1, _safe_int(row.get("year_count")) - 1)
        )
        by_account_all[_account_key(account)] = ranked
    return {
        "top_practical": by_practical[:top_n],
        "top_return_to_drawdown": by_return_to_dd[:top_n],
        "top_raw_return": by_return[:top_n],
        "top_conservative_dd25": conservative[:top_n],
        "top_by_account": by_account,
        "top_by_account_all": by_account_all,
        "viable_cases": len(viable),
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    baseline = dict(payload.get("baseline") or {})
    lines = [
        "# Micro Main Portfolio Optimizer",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- label: {payload.get('label')}",
        f"- source_backtest: {payload.get('source_backtest')}",
        f"- evaluated_cases: {payload.get('evaluated_cases')}",
        f"- baseline: signals={baseline.get('signals')} symbols={baseline.get('symbols')} total_r={baseline.get('total_r')} ev={baseline.get('ev_r')} win={baseline.get('win_rate')}",
        "",
        "## Top Practical",
    ]
    for item in list(dict(payload.get("selection") or {}).get("top_practical") or [])[:12]:
        lines.append(
            "- "
            f"acct={item.get('account_equity')} risk={item.get('risk_pct')} lev={item.get('leverage_cap')} "
            f"max_pos={item.get('max_concurrent')} totalR={item.get('total_risk_cap_r')} daily={item.get('daily_cap')} "
            f"model={item.get('allocation_model')} floor={item.get('score_floor')} minEntryR={item.get('min_entry_r')} "
            f"accepted={item.get('accepted')} ret={item.get('return_pct')}% dd={item.get('max_drawdown_pct')}% "
            f"initDD={item.get('max_drawdown_initial_pct')}% ret/initDD={item.get('return_to_initial_dd')} "
            f"ev={item.get('weighted_ev_r')} avgR={item.get('avg_actual_r')}"
        )
    lines.append("")
    lines.append("## Top Conservative DD<=25")
    for item in list(dict(payload.get("selection") or {}).get("top_conservative_dd25") or [])[:12]:
        lines.append(
            "- "
            f"acct={item.get('account_equity')} risk={item.get('risk_pct')} lev={item.get('leverage_cap')} "
            f"max_pos={item.get('max_concurrent')} totalR={item.get('total_risk_cap_r')} daily={item.get('daily_cap')} "
            f"model={item.get('allocation_model')} accepted={item.get('accepted')} ret={item.get('return_pct')}% "
            f"dd={item.get('max_drawdown_pct')}% initDD={item.get('max_drawdown_initial_pct')}% "
            f"ret/initDD={item.get('return_to_initial_dd')}"
        )
    lines.append("")
    lines.append("This replay uses already generated signal rows. It optimizes portfolio execution settings, not the entry signal generator itself.")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    generated_at = datetime.now(UTC)
    source_path = Path(args.backtest_path).expanduser()
    if not source_path.is_absolute():
        source_path = ROOT_DIR / source_path
    source_payload, trades = _load_trade_rows(source_path)
    rules = _fetch_symbol_rules({row.symbol for row in trades})
    capacity_caps = _fetch_current_capacity_caps({row.symbol for row in trades}, args)
    cases = _build_cases(args)
    rows: list[dict[str, Any]] = []
    for idx, case in enumerate(cases, start=1):
        rows.append(
            _simulate_case(
                trades=trades,
                symbol_rules=rules,
                capacity_caps=capacity_caps,
                case=case,
                usable_margin_fraction=float(args.usable_margin_fraction),
                cluster_window_minutes=int(args.cluster_window_minutes),
                cluster_cap=int(args.cluster_cap),
                same_direction_cap=int(args.same_direction_cap),
            )
        )
        if idx % 1000 == 0:
            print(json.dumps({"progress": idx, "total_cases": len(cases)}, ensure_ascii=False), file=sys.stderr, flush=True)

    payload: dict[str, Any] = {
        "schema_version": "micro_main_portfolio_optimizer_v1",
        "generated_at": generated_at.isoformat(),
        "label": str(args.label or source_path.stem),
        "source_backtest": str(source_path),
        "source_backtest_generated_at": source_payload.get("generated_at"),
        "source_backtest_days": source_payload.get("days"),
        "baseline": _baseline_stats(trades),
        "capacity": {
            **{key: value for key, value in capacity_caps.items() if key != "symbols"},
            "symbol_count": len(dict(capacity_caps.get("symbols") or {})),
            "weakest_symbols": sorted(
                (
                    {
                        "symbol": symbol,
                        "long_allowed_notional": _safe_float(item.get("long_allowed_notional")),
                        "short_allowed_notional": _safe_float(item.get("short_allowed_notional")),
                    }
                    for symbol, item in dict(capacity_caps.get("symbols") or {}).items()
                ),
                key=lambda item: min(item["long_allowed_notional"], item["short_allowed_notional"]),
            )[:12],
        },
        "grid": {
            "accounts": _float_list(args.accounts),
            "risk_pcts": _float_list(args.risk_pcts),
            "leverage_caps": _float_list(args.leverage_caps),
            "max_concurrent": _int_list(args.max_concurrent),
            "total_risk_caps": _float_list(args.total_risk_caps),
            "daily_caps": _int_list(args.daily_caps),
            "score_floors": _float_list(args.score_floors),
            "min_entry_rs": _float_list(args.min_entry_rs),
            "allocation_models": sorted({case.allocation_model.name for case in cases}),
            "usable_margin_fraction": float(args.usable_margin_fraction),
            "cluster_window_minutes": int(args.cluster_window_minutes),
            "cluster_cap": int(args.cluster_cap),
            "same_direction_cap": int(args.same_direction_cap),
            "max_cases": int(args.max_cases or 0),
        },
        "evaluated_cases": len(rows),
        "selection": _select_top(rows, top_n=int(args.top_n)),
    }
    if args.write_report:
        out_dir = Path(settings.validation_report_dir) / "micro_main_portfolio_optimizers"
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"micro_main_portfolio_optimizer_{str(args.label or 'run')}_{generated_at.strftime('%Y%m%dT%H%M%SZ')}"
        json_path = out_dir / f"{stem}.json"
        md_path = out_dir / f"{stem}.md"
        payload["report_path"] = str(json_path)
        payload["markdown_report_path"] = str(md_path)
        atomic_write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2))
        atomic_write_text(md_path, _render_markdown(payload))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
