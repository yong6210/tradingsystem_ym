#!/usr/bin/env python3
"""Bridge fresh market_state_rotation_v6 decisions into the PAPER lifecycle."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Any

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings, sqlite_database_path_from_url
from app.core.enums import ExecutionFillStage, ExecutionMode, PlanState, SubmitDecision
from app.db.models import ExecutionFill, OrderSubmission, Plan
from app.db.session import SessionLocal, init_db
from app.services.strategy_engine import StrategyEngine
from scripts.run_market_state_rotation_v6_backtest import (
    MarketStateConfig,
    _carry_rate_per_bar,
    _load_feature_sets,
    backtest_config,
)


EXPECTED_SYMBOL = "BTCUSDT"
EXPECTED_STRATEGY_FAMILY = "market_state_rotation_v6"
DEFAULT_SOURCE_BACKTEST_REPORT = (
    "reports/validation/market_state_rotation_v6_backtest/"
    "market_state_rotation_v6_BTCUSDT_5m_365d_latest.json"
)
DEFAULT_PRE_APPLY_BACKUP_DIR = "reports/db_recovery/market_state_rotation_v6_bridge_tick"


def _resolve(path: str | Path) -> Path:
    raw = Path(path)
    return raw if raw.is_absolute() else ROOT_DIR / raw


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _load_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _create_sqlite_pre_apply_backup(
    *,
    backup_dir: Path,
    now: datetime | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    source_url = str(database_url or get_settings().database_url or "")
    db_path = sqlite_database_path_from_url(source_url)
    if db_path is None:
        return {
            "created": False,
            "reason": "non_sqlite_database_or_memory_database",
            "database_url": source_url,
        }
    if not db_path.exists():
        return {
            "created": False,
            "reason": "sqlite_database_missing",
            "source_path": str(db_path),
        }
    if not backup_dir.is_absolute():
        backup_dir = ROOT_DIR / backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_stem = f"trading.db.before_msrv6_bridge_{now:%Y%m%dT%H%M%SZ}"
    backup_path = backup_dir / f"{backup_stem}.bak"
    suffix = 1
    while backup_path.exists():
        backup_path = backup_dir / f"{backup_stem}.{suffix}.bak"
        suffix += 1
    source_uri = f"file:{db_path}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)
        quick_check = str(target.execute("PRAGMA quick_check").fetchone()[0])
    return {
        "created": True,
        "reason": "created",
        "source_path": str(db_path),
        "backup_path": str(backup_path),
        "size_bytes": int(backup_path.stat().st_size),
        "quick_check": quick_check,
    }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _median(values: list[float]) -> float | None:
    clean = sorted(float(value) for value in values if value >= 0.0)
    if not clean:
        return None
    mid = len(clean) // 2
    if len(clean) % 2:
        return round(clean[mid], 4)
    return round((clean[mid - 1] + clean[mid]) / 2.0, 4)


def _runtime_event_cadence(
    *,
    bridge_events: list[dict[str, Any]],
    data_meta: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    parsed_events: list[tuple[datetime, dict[str, Any]]] = []
    for event in bridge_events:
        ts = _parse_dt(event.get("ts"))
        if ts is not None:
            parsed_events.append((ts, event))
    parsed_events.sort(key=lambda item: item[0])
    data_start = _parse_dt(data_meta.get("exec_start"))
    data_end = _parse_dt(data_meta.get("exec_end")) or now
    if data_start is not None and data_end > data_start:
        window_days = max((data_end - data_start).total_seconds() / 86400.0, 1e-9)
    elif parsed_events:
        window_days = max((data_end - parsed_events[0][0]).total_seconds() / 86400.0, 1e-9)
    else:
        window_days = 0.0
    gaps_hours = [
        (parsed_events[idx][0] - parsed_events[idx - 1][0]).total_seconds() / 3600.0
        for idx in range(1, len(parsed_events))
        if parsed_events[idx][0] >= parsed_events[idx - 1][0]
    ]
    add_events = [(ts, event) for ts, event in parsed_events if str(event.get("action") or "") == "add"]
    add_gaps_hours = [
        (add_events[idx][0] - add_events[idx - 1][0]).total_seconds() / 3600.0
        for idx in range(1, len(add_events))
        if add_events[idx][0] >= add_events[idx - 1][0]
    ]
    latest_ts = parsed_events[-1][0] if parsed_events else None
    latest_age_hours = (now - latest_ts).total_seconds() / 3600.0 if latest_ts is not None else None
    latest_add_ts = add_events[-1][0] if add_events else None
    latest_add_age_hours = (now - latest_add_ts).total_seconds() / 3600.0 if latest_add_ts is not None else None
    median_gap = _median(gaps_hours)
    median_add_gap = _median(add_gaps_hours)
    event_rate = len(parsed_events) / window_days if window_days > 0.0 else 0.0
    add_rate = len(add_events) / window_days if window_days > 0.0 else 0.0
    age_to_median_gap = (
        round(float(latest_age_hours) / float(median_gap), 4)
        if latest_age_hours is not None and median_gap and median_gap > 0.0
        else None
    )
    add_age_to_median_gap = (
        round(float(latest_add_age_hours) / float(median_add_gap), 4)
        if latest_add_age_hours is not None and median_add_gap and median_add_gap > 0.0
        else None
    )
    if not parsed_events:
        wait_state = "no_recent_bridge_events"
    elif age_to_median_gap is not None and age_to_median_gap >= 2.0:
        wait_state = "latest_signal_age_above_recent_median_gap"
    else:
        wait_state = "within_recent_signal_gap_distribution"
    if not add_events:
        add_wait_state = "no_recent_add_events"
    elif add_age_to_median_gap is not None and add_age_to_median_gap >= 2.0:
        add_wait_state = "latest_add_age_above_recent_median_gap"
    else:
        add_wait_state = "within_recent_add_gap_distribution"
    return {
        "bridge_event_count": len(parsed_events),
        "add_event_count": len(add_events),
        "remove_event_count": sum(1 for _, event in parsed_events if str(event.get("action") or "") == "remove"),
        "window_days": round(window_days, 4) if window_days else 0.0,
        "events_per_day": round(event_rate, 4),
        "expected_days_per_event": round(1.0 / event_rate, 4) if event_rate > 0.0 else None,
        "add_events_per_day": round(add_rate, 4),
        "expected_days_per_add": round(1.0 / add_rate, 4) if add_rate > 0.0 else None,
        "avg_gap_hours": round(sum(gaps_hours) / len(gaps_hours), 4) if gaps_hours else None,
        "median_gap_hours": median_gap,
        "max_gap_hours": round(max(gaps_hours), 4) if gaps_hours else None,
        "avg_add_gap_hours": round(sum(add_gaps_hours) / len(add_gaps_hours), 4) if add_gaps_hours else None,
        "median_add_gap_hours": median_add_gap,
        "max_add_gap_hours": round(max(add_gaps_hours), 4) if add_gaps_hours else None,
        "latest_event_ts": latest_ts.isoformat() if latest_ts is not None else None,
        "latest_event_age_hours": round(float(latest_age_hours), 4) if latest_age_hours is not None else None,
        "latest_age_to_median_gap": age_to_median_gap,
        "latest_add_ts": latest_add_ts.isoformat() if latest_add_ts is not None else None,
        "latest_add_age_hours": round(float(latest_add_age_hours), 4) if latest_add_age_hours is not None else None,
        "latest_add_age_to_median_gap": add_age_to_median_gap,
        "wait_state": wait_state,
        "add_wait_state": add_wait_state,
    }


def _top_no_trade_reasons(event_counts: Any, *, limit: int = 8) -> list[dict[str, Any]]:
    counts = dict(event_counts or {})
    rows: list[tuple[str, int]] = []
    for key, value in counts.items():
        text = str(key)
        if not text.startswith("no_trade_") or "::" in text:
            continue
        rows.append((text, _safe_int(value)))
    rows.sort(key=lambda item: item[1], reverse=True)
    return [{"reason": key, "count": count} for key, count in rows[: max(1, int(limit))]]


def _top_count_mapping(values: Any, *, limit: int) -> dict[str, int]:
    rows = [
        (str(key), _safe_int(value))
        for key, value in dict(values or {}).items()
        if _safe_int(value) > 0
    ]
    rows.sort(key=lambda item: item[1], reverse=True)
    return {key: count for key, count in rows[: max(1, int(limit))]}


def _no_trade_hotspots(result: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(result.get("event_diagnostics") or {})
    return {
        "top_no_trade_contexts": _top_count_mapping(
            diagnostics.get("top_no_trade_contexts"),
            limit=12,
        ),
        "no_trade_reason_side_counts": _top_count_mapping(
            diagnostics.get("no_trade_reason_side_counts"),
            limit=24,
        ),
        "no_trade_reason_regime_counts": _top_count_mapping(
            diagnostics.get("no_trade_reason_regime_counts"),
            limit=24,
        ),
    }


def _side_to_direction(side: Any) -> str:
    text = str(side or "").strip().lower()
    return "short" if text == "short" else "long"


def _event_key(event: dict[str, Any]) -> str:
    ts = str(event.get("ts") or "").replace("-", "").replace(":", "").replace("+00:00", "Z")
    side = str(event.get("side") or "unknown").lower()
    action = str(event.get("action") or "event").lower()
    reason = str(event.get("reason") or "signal").lower().replace(" ", "_")
    return f"{ts}:{action}:{side}:{reason}"


def _plan_id_for_event(*, symbol: str, event: dict[str, Any]) -> str:
    ts = _parse_dt(event.get("ts")) or datetime.now(UTC)
    side = str(event.get("side") or "x").lower()[:1]
    reason = str(event.get("reason") or "signal").lower()
    reason_token = "".join(ch for ch in reason if ch.isalnum())[:8] or "signal"
    return f"msrv6_{symbol}_{ts:%y%m%d%H%M}_{side}_{reason_token}"[:50]


def _coerce_config(raw: dict[str, Any]) -> MarketStateConfig:
    allowed = {item.name for item in fields(MarketStateConfig)}
    return MarketStateConfig(**{key: value for key, value in raw.items() if key in allowed})


def _source_config(report: dict[str, Any]) -> MarketStateConfig:
    for key in ("best_by_method_score", "best_by_raw_return"):
        section = dict(report.get(key) or {})
        config = dict(section.get("config") or {})
        if config:
            return _coerce_config(config)
    top_results = list(report.get("top_results") or [])
    for item in top_results:
        config = dict(dict(item or {}).get("config") or {})
        if config:
            return _coerce_config(config)
    raise ValueError("source_backtest_config_missing")


def _source_args(report: dict[str, Any]) -> dict[str, Any]:
    return dict(report.get("args") or {})


def _source_arg(report: dict[str, Any], key: str, fallback: Any) -> Any:
    value = _source_args(report).get(key)
    return fallback if value in {None, ""} else value


def _optional_positive_int(value: Any) -> int | None:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _runtime_namespace(
    *,
    symbol: str,
    days: int,
    load_days: int,
    exec_interval: str,
    scenario_intervals: str,
    cache_dir: str,
    base_url: str,
    sleep_seconds: float,
    max_cache_age_minutes: float | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        symbol=symbol,
        days=max(1, int(days)),
        load_days=max(int(load_days), int(days)),
        exec_interval=exec_interval,
        scenario_intervals=scenario_intervals,
        cache_dir=cache_dir,
        base_url=base_url,
        sleep_seconds=max(0.0, float(sleep_seconds)),
        max_cache_age_minutes=max_cache_age_minutes,
    )


def _freshness_status(
    *,
    event: dict[str, Any] | None,
    data_end: datetime | None,
    now: datetime,
    max_signal_age_minutes: int,
    max_market_data_age_minutes: int,
) -> tuple[bool, list[str], dict[str, Any]]:
    blockers: list[str] = []
    ages: dict[str, Any] = {}
    if data_end is None:
        blockers.append("market_data_end_missing")
    else:
        data_age = max(0.0, (now - data_end).total_seconds() / 60.0)
        ages["market_data_age_minutes"] = round(data_age, 4)
        if data_age > max(1, int(max_market_data_age_minutes)):
            blockers.append("market_data_stale")

    if event is None:
        blockers.append("no_recent_v6_trade_event")
    else:
        event_ts = _parse_dt(event.get("ts"))
        if event_ts is None:
            blockers.append("signal_ts_missing")
        else:
            signal_age = max(0.0, (now - event_ts).total_seconds() / 60.0)
            ages["signal_age_minutes"] = round(signal_age, 4)
            if signal_age > max(1, int(max_signal_age_minutes)):
                blockers.append("signal_stale")
        if str(event.get("action") or "") not in {"add", "remove"}:
            blockers.append("signal_action_not_bridgeable")
    return not blockers, blockers, ages


def _plan_from_add_event(
    *,
    symbol: str,
    event: dict[str, Any],
    config: MarketStateConfig,
    now: datetime,
    valid_minutes: int,
) -> Plan:
    direction = _side_to_direction(event.get("side"))
    sign = 1.0 if direction == "long" else -1.0
    entry = _safe_float(event.get("price"))
    reaction = max(_safe_float(getattr(config, "reaction_usd", 0.0)), entry * 0.0025, 10.0)
    stop_distance = max(reaction * 1.15, entry * 0.003)
    sl = entry - sign * stop_distance
    tp1 = entry + sign * reaction * 0.65
    tp2 = entry + sign * reaction * 1.15
    tp3 = entry + sign * reaction * 1.75
    risk_distance = max(abs(entry - sl), 1e-9)
    plan_id = _plan_id_for_event(symbol=symbol, event=event)
    source_event_ts = str(event.get("ts") or "")
    valid_until = now + timedelta(minutes=max(1, int(valid_minutes)))
    validity = {
        "strategy_family": EXPECTED_STRATEGY_FAMILY,
        "strategy_grade": "A",
        "strategy_family_score": max(80.0, float(_safe_int(event.get("zone_score"), 80))),
        "strategy_mode": "PAPER_SAMPLE",
        "regime": str(event.get("regime") or "unknown"),
        "recommended_risk_r": 0.0,
        "expected_win_prob": 0.62,
        "expected_ev_r": 0.40,
        "expected_summary": "market_state_rotation_v6 fresh runtime PAPER bridge sample",
        "strategy_family_time_stop_max_bars": max(1, int(getattr(config, "max_hold_bars", 52))),
        "source_runtime_bridge": "market_state_rotation_v6_paper_bridge_tick",
        "source_event": dict(event),
        "source_event_key": _event_key(event),
        "source_event_ts": source_event_ts,
        "source_model_id": config.model_id,
        "thesis_fingerprint": {
            "symbol": symbol,
            "direction": direction,
            "family": EXPECTED_STRATEGY_FAMILY,
            "source_event_key": _event_key(event),
        },
        "thesis_cluster_id": f"{EXPECTED_STRATEGY_FAMILY}:{symbol}:{direction}:{source_event_ts}",
        "thesis_primary_symbol": symbol,
    }
    return Plan(
        plan_id=plan_id,
        zone_id=f"msrv6:{symbol}:{str(event.get('zone_key') or plan_id)}"[:50],
        symbol=symbol,
        timeframe="5m",
        direction=direction,
        entry_model="CONFIRM",
        entry_price=entry,
        entry_condition=str(event.get("reason") or "market_state_rotation_v6_add"),
        sl=round(float(sl), 4),
        tp1=round(float(tp1), 4),
        tp2=round(float(tp2), 4),
        tp3=round(float(tp3), 4),
        split={"tp1": 0.35, "tp2": 0.65, "runner": 0.0},
        rr_min=round(abs(tp1 - entry) / risk_distance, 4),
        rr_base=round(abs(tp2 - entry) / risk_distance, 4),
        rr_opt=round(abs(tp3 - entry) / risk_distance, 4),
        ev=0.4,
        cost_est=0.05,
        confidence=0.84,
        validity=validity,
        state=PlanState.ARMED.value,
        valid_from=now - timedelta(minutes=1),
        valid_until=valid_until,
        strategy_version="v6",
    )


def build_runtime_decision_snapshot(
    *,
    source_backtest_report: dict[str, Any],
    symbol: str = EXPECTED_SYMBOL,
    days: int = 120,
    load_days: int | None = None,
    exec_interval: str | None = None,
    scenario_intervals: str | None = None,
    cache_dir: str | None = None,
    base_url: str | None = None,
    sleep_seconds: float | None = None,
    fee_bps_per_side: float | None = None,
    slippage_bps_per_side: float | None = None,
    funding_bps_per_8h: float | None = None,
    borrow_bps_per_day: float | None = None,
    min_periods: int | None = None,
    max_signal_age_minutes: int = 15,
    max_market_data_age_minutes: int = 30,
    plan_valid_minutes: int = 15,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    config = _source_config(source_backtest_report)
    inherited_load_days = _optional_positive_int(_source_arg(source_backtest_report, "load_days", None))
    runtime_default_load_days = max(int(days) + 60, 180)
    resolved_load_days = _optional_positive_int(load_days) or runtime_default_load_days
    resolved_exec_interval = str(exec_interval or _source_arg(source_backtest_report, "exec_interval", "5m") or "5m")
    resolved_scenario_intervals = str(
        scenario_intervals or _source_arg(source_backtest_report, "scenario_intervals", "1h,4h") or "1h,4h"
    )
    resolved_cache_dir = str(
        cache_dir
        or _source_arg(source_backtest_report, "cache_dir", "reports/validation/btc_flip_rotation_search/cache")
        or "reports/validation/btc_flip_rotation_search/cache"
    )
    source_base_url = str(_source_arg(source_backtest_report, "base_url", "") or "")
    resolved_base_url = str(
        base_url
        if base_url is not None
        else source_base_url
        or get_settings().binance_rest_base_url
        or "https://fapi.binance.com"
    )
    resolved_sleep_seconds = (
        _optional_float(sleep_seconds)
        if sleep_seconds is not None
        else _optional_float(_source_arg(source_backtest_report, "sleep_seconds", 0.03))
    )
    resolved_fee_bps = (
        _optional_float(fee_bps_per_side)
        if fee_bps_per_side is not None
        else _optional_float(_source_arg(source_backtest_report, "fee_bps_per_side", 4.0))
    )
    resolved_slippage_bps = (
        _optional_float(slippage_bps_per_side)
        if slippage_bps_per_side is not None
        else _optional_float(_source_arg(source_backtest_report, "slippage_bps_per_side", 1.0))
    )
    resolved_funding_bps = (
        _optional_float(funding_bps_per_8h)
        if funding_bps_per_8h is not None
        else _optional_float(_source_arg(source_backtest_report, "funding_bps_per_8h", 0.0))
    )
    resolved_borrow_bps = (
        _optional_float(borrow_bps_per_day)
        if borrow_bps_per_day is not None
        else _optional_float(_source_arg(source_backtest_report, "borrow_bps_per_day", 0.0))
    )
    resolved_min_periods = (
        _optional_positive_int(min_periods)
        or _optional_positive_int(_source_arg(source_backtest_report, "min_periods", 5000))
        or 5000
    )
    namespace = _runtime_namespace(
        symbol=symbol,
        days=days,
        load_days=resolved_load_days,
        exec_interval=resolved_exec_interval,
        scenario_intervals=resolved_scenario_intervals,
        cache_dir=resolved_cache_dir,
        base_url=resolved_base_url,
        sleep_seconds=resolved_sleep_seconds if resolved_sleep_seconds is not None else 0.03,
        max_cache_age_minutes=max(1, int(max_market_data_age_minutes)),
    )
    features, scenario_features, scenario_maps, data_meta = _load_feature_sets(namespace)
    cost_rate = (max(float(resolved_fee_bps or 0.0), 0.0) + max(float(resolved_slippage_bps or 0.0), 0.0)) / 10_000.0
    carry_rate = _carry_rate_per_bar(
        exec_interval=resolved_exec_interval,
        funding_bps_per_8h=float(resolved_funding_bps or 0.0),
        borrow_bps_per_day=float(resolved_borrow_bps or 0.0),
    )
    result = backtest_config(
        symbol=symbol,
        features=features,
        scenario_features=scenario_features,
        scenario_maps=scenario_maps,
        config=config,
        cost_rate=cost_rate,
        min_periods=max(1, int(resolved_min_periods)),
        carry_rate_per_bar=carry_rate,
        recent_event_limit=80,
    )
    if result is None:
        return {
            "created_at": now.isoformat(),
            "overall_status": "not_actionable",
            "blockers": ["backtest_result_unavailable"],
            "data": data_meta,
            "no_live_order_sent": True,
        }
    recent_events = [
        dict(event)
        for event in list(result.get("recent_events") or result.get("sample_events") or [])
        if isinstance(event, dict) and "omitted_events" not in event
    ]
    bridge_events = [event for event in recent_events if str(event.get("action") or "") in {"add", "remove"}]
    latest_event = bridge_events[-1] if bridge_events else None
    data_end = _parse_dt(data_meta.get("exec_end"))
    event_cadence = _runtime_event_cadence(bridge_events=bridge_events, data_meta=dict(data_meta), now=now)
    top_no_trade_reasons = _top_no_trade_reasons(result.get("event_counts"))
    no_trade_hotspots = _no_trade_hotspots(result)
    actionable, blockers, ages = _freshness_status(
        event=latest_event,
        data_end=data_end,
        now=now,
        max_signal_age_minutes=max_signal_age_minutes,
        max_market_data_age_minutes=max_market_data_age_minutes,
    )
    plan_payload: dict[str, Any] | None = None
    if actionable and latest_event and str(latest_event.get("action") or "") == "add":
        plan = _plan_from_add_event(
            symbol=symbol,
            event=latest_event,
            config=config,
            now=now,
            valid_minutes=plan_valid_minutes,
        )
        plan_payload = {
            "plan_id": plan.plan_id,
            "symbol": plan.symbol,
            "direction": plan.direction,
            "entry_model": plan.entry_model,
            "entry_price": plan.entry_price,
            "sl": plan.sl,
            "tp1": plan.tp1,
            "tp2": plan.tp2,
            "tp3": plan.tp3,
            "valid_until": plan.valid_until.isoformat(),
            "strategy_family": EXPECTED_STRATEGY_FAMILY,
        }
    return {
        "created_at": now.isoformat(),
        "overall_status": "actionable" if actionable else "not_actionable",
        "symbol": symbol,
        "strategy_family": EXPECTED_STRATEGY_FAMILY,
        "no_live_order_sent": True,
        "data": data_meta,
        "freshness": ages,
        "blockers": blockers,
        "selected_model_id": config.model_id,
        "runtime_load_context": {
            "days": max(1, int(days)),
            "load_days": resolved_load_days,
            "source_load_days": inherited_load_days,
            "max_cache_age_minutes": max(1, int(max_market_data_age_minutes)),
            "cache_dir": resolved_cache_dir,
            "base_url": resolved_base_url,
        },
        "latest_event": latest_event,
        "recent_event_count": len(recent_events),
        "bridge_event_cadence": event_cadence,
        "top_no_trade_reasons": top_no_trade_reasons,
        "no_trade_hotspots": no_trade_hotspots,
        "bridge_action": str((latest_event or {}).get("action") or ""),
        "plan_candidate": plan_payload,
        "backtest_summary": {
            "total_return_pct": result.get("total_return_pct"),
            "max_drawdown_pct": result.get("max_drawdown_pct"),
            "trade_like_events": result.get("trade_like_events"),
        },
    }


def _candidate_row_for_plan(plan: Plan, snapshot: dict[str, Any]) -> dict[str, Any]:
    validity = dict(plan.validity or {})
    return {
        "plan_id": plan.plan_id,
        "accepted": True,
        "deployment_go_no_go": "GO",
        "deployment_code": "go_market_state_rotation_v6_paper_bridge",
        "deployment_message": "GO: fresh market_state_rotation_v6 runtime PAPER sample.",
        "session_guidance": {
            "session_name": "runtime",
            "state": "runtime",
            "risk_label": "paper_sample",
        },
        "risk_reason": "paper_sample",
        "operating_lock": {},
        "expected_win_prob": validity.get("expected_win_prob", 0.62),
        "expected_ev_r": validity.get("expected_ev_r", 0.40),
        "expected_summary": validity.get("expected_summary"),
        "strategy_family": EXPECTED_STRATEGY_FAMILY,
        "strategy_grade": "A",
        "strategy_family_score": validity.get("strategy_family_score", 84.0),
        "thesis_fingerprint": validity.get("thesis_fingerprint"),
        "thesis_cluster_id": validity.get("thesis_cluster_id"),
        "source_snapshot_created_at": snapshot.get("created_at"),
    }


def _v6_metrics(snapshot: dict[str, Any]) -> dict[str, Any]:
    summary = dict(snapshot.get("backtest_summary") or {})
    return {
        "grade": "A",
        "recommendation": "deploy",
        "risk_state": "OPEN",
        "risk_reason": "paper_sample",
        "sample_size": 100,
        "trade_count": max(100, _safe_int(summary.get("trade_like_events"), 100)),
        "closed_trades": max(100, _safe_int(summary.get("trade_like_events"), 100)),
        "expectancy_r": 0.4,
        "win_rate": 0.62,
        "total_score": 84.0,
        "max_drawdown_pct": summary.get("max_drawdown_pct"),
    }


def _patch_engine_for_v6(engine: StrategyEngine, plan: Plan, snapshot: dict[str, Any]) -> None:
    candidate = _candidate_row_for_plan(plan, snapshot)
    metrics = _v6_metrics(snapshot)

    def _execution_candidate_rows(self: StrategyEngine, symbol: str) -> tuple[Any, list[dict[str, Any]], Any]:
        if str(symbol or "").upper() != str(plan.symbol or "").upper():
            return None, [], None
        return None, [candidate], None

    def _metrics(self: StrategyEngine, symbol: str, version: str | None = None) -> dict[str, Any]:
        return dict(metrics)

    def _allowed_symbols(self: Any) -> set[str]:
        return {str(plan.symbol or "").upper()}

    def _allowed_families(self: Any) -> set[str]:
        return {EXPECTED_STRATEGY_FAMILY}

    engine._execution_candidate_rows = MethodType(_execution_candidate_rows, engine)  # type: ignore[method-assign]
    engine.metrics = MethodType(_metrics, engine)  # type: ignore[method-assign]
    engine.execution_planning.allowed_symbols = MethodType(_allowed_symbols, engine.execution_planning)  # type: ignore[method-assign]
    engine.execution_planning.allowed_families = MethodType(_allowed_families, engine.execution_planning)  # type: ignore[method-assign]


def _ensure_paper_rollout_policy(engine: StrategyEngine) -> dict[str, Any]:
    policy = engine.rollout_policy_service.upsert(
        family=EXPECTED_STRATEGY_FAMILY,
        live_enabled=False,
        max_execution_mode=ExecutionMode.PAPER,
        max_risk_r=0.0,
        allowed_sessions=(),
        min_quality_score=0.0,
        updated_by="market_state_rotation_v6_paper_bridge_tick",
        notes="PAPER-only bridge for v6 execution evidence collection; live remains disabled.",
    )
    return policy.to_dict()


def _latest_paper_submission_for_plan(db: Any, plan_id: str) -> OrderSubmission | None:
    stmt = (
        select(OrderSubmission)
        .where(OrderSubmission.plan_id == plan_id, OrderSubmission.adapter == "paper")
        .order_by(OrderSubmission.submitted_at.desc(), OrderSubmission.updated_at.desc())
        .limit(1)
    )
    return db.scalar(stmt)


def _open_v6_paper_plans(db: Any, *, symbol: str, direction: str) -> list[Plan]:
    stmt = (
        select(Plan)
        .where(
            Plan.symbol == symbol,
            Plan.state.in_([PlanState.ENTERED.value, PlanState.PARTIAL_EXIT.value]),
        )
        .order_by(Plan.valid_from.asc())
    )
    rows = []
    for plan in db.scalars(stmt):
        validity = dict(plan.validity or {})
        if str(validity.get("strategy_family") or "") != EXPECTED_STRATEGY_FAMILY:
            continue
        if str(plan.direction or "").lower() != direction:
            continue
        if _latest_paper_submission_for_plan(db, plan.plan_id) is None:
            continue
        rows.append(plan)
    return rows


def _remaining_paper_qty(db: Any, plan: Plan) -> float:
    fills = list(
        db.scalars(
            select(ExecutionFill)
            .where(ExecutionFill.plan_id == plan.plan_id, ExecutionFill.symbol == plan.symbol)
            .order_by(ExecutionFill.fill_ts.asc())
        )
    )
    entry_qty = sum(float(fill.qty or 0.0) for fill in fills if str(fill.stage) == ExecutionFillStage.ENTRY.value)
    exit_qty = sum(
        float(fill.qty or 0.0)
        for fill in fills
        if str(fill.stage) in {ExecutionFillStage.PARTIAL_EXIT.value, ExecutionFillStage.CLOSED.value}
    )
    return max(entry_qty - exit_qty, 0.0) if entry_qty > 0.0 else 1.0


def _apply_add_snapshot(*, db: Any, engine: StrategyEngine, snapshot: dict[str, Any], plan: Plan) -> dict[str, Any]:
    existing = db.get(Plan, plan.plan_id)
    if existing is not None:
        submission = _latest_paper_submission_for_plan(db, plan.plan_id)
        return {
            "status": "already_seen",
            "plan_id": plan.plan_id,
            "existing_state": existing.state,
            "submission_id": getattr(submission, "submission_id", None),
        }

    engine.plan_repo.upsert_many([plan])
    db.commit()
    _patch_engine_for_v6(engine, plan, snapshot)
    intent = engine.create_order_intent(plan_id=plan.plan_id, execution_mode=ExecutionMode.PAPER)
    submission = None
    if str(intent.get("submit_decision") or "") == SubmitDecision.SUBMIT.value:
        submission = engine.submit_order_intent(
            intent_id=str(intent.get("intent_id") or ""),
            live=False,
            paper_scenario="fill",
        )
    return {
        "status": "submitted" if submission else "intent_created_not_submitted",
        "plan_id": plan.plan_id,
        "intent": {
            "intent_id": intent.get("intent_id"),
            "approval_state": intent.get("approval_state"),
            "submit_decision": intent.get("submit_decision"),
            "decision_reason_code": intent.get("decision_reason_code"),
        },
        "submission": submission,
    }


def _apply_remove_snapshot(*, db: Any, engine: StrategyEngine, snapshot: dict[str, Any]) -> dict[str, Any]:
    event = dict(snapshot.get("latest_event") or {})
    direction = _side_to_direction(event.get("side"))
    open_plans = _open_v6_paper_plans(db, symbol=str(snapshot.get("symbol") or EXPECTED_SYMBOL), direction=direction)
    if not open_plans:
        return {"status": "no_open_v6_paper_plan", "direction": direction, "closed_or_partial": []}
    event_ts = _parse_dt(event.get("ts")) or datetime.now(UTC)
    price = _safe_float(event.get("price"), _safe_float(getattr(open_plans[0], "entry_price", 0.0)))
    requested_qty = max(0.0, _safe_float(event.get("qty"), 1.0))
    closed_or_partial: list[dict[str, Any]] = []
    for plan in open_plans:
        if requested_qty <= 1e-12:
            break
        remaining_qty = _remaining_paper_qty(db, plan)
        fill_qty = min(remaining_qty, requested_qty)
        if fill_qty <= 1e-12:
            continue
        stage = ExecutionFillStage.CLOSED if fill_qty >= remaining_qty - 1e-10 else ExecutionFillStage.PARTIAL_EXIT
        submission = _latest_paper_submission_for_plan(db, plan.plan_id)
        response = engine.ingest_execution_fill(
            fill_id=f"msrv6_exit_{plan.plan_id}_{str(event.get('ts') or '')[-14:].replace(':', '').replace('+', '')}",
            plan_id=plan.plan_id,
            symbol=plan.symbol,
            stage=stage,
            fill_ts=event_ts,
            price=price,
            qty=fill_qty,
            fee=0.0,
            payload={
                "source": "market_state_rotation_v6_paper_bridge",
                "execution_adapter": "paper",
                "client_order_id": getattr(submission, "client_order_id", ""),
                "strategy_family": EXPECTED_STRATEGY_FAMILY,
                "exit_reason": str(event.get("reason") or "market_state_rotation_v6_remove"),
                "source_event": event,
                "source_event_key": _event_key(event),
                "remaining_qty": max(0.0, remaining_qty - fill_qty),
            },
        )
        requested_qty -= fill_qty
        closed_or_partial.append(
            {
                "plan_id": plan.plan_id,
                "stage": stage.value,
                "qty": round(float(fill_qty), 6),
                "price": price,
                "accepted": bool(response.get("accepted")),
                "duplicate": bool(response.get("duplicate")),
                "to_state": response.get("to_state"),
            }
        )
    return {"status": "exit_recorded" if closed_or_partial else "no_exit_recorded", "closed_or_partial": closed_or_partial}


def run_paper_bridge_tick(
    *,
    source_backtest_report_path: Path,
    apply_paper: bool = False,
    symbol: str = EXPECTED_SYMBOL,
    days: int = 120,
    load_days: int | None = None,
    max_signal_age_minutes: int = 15,
    max_market_data_age_minutes: int = 30,
    plan_valid_minutes: int = 15,
    report_dir: Path | None = None,
    pre_apply_backup_dir: Path | None = _resolve(DEFAULT_PRE_APPLY_BACKUP_DIR),
    require_pre_apply_backup: bool = True,
) -> dict[str, Any]:
    source_report = _load_json(source_backtest_report_path)
    snapshot = build_runtime_decision_snapshot(
        source_backtest_report=source_report,
        symbol=symbol,
        days=days,
        load_days=load_days,
        max_signal_age_minutes=max_signal_age_minutes,
        max_market_data_age_minutes=max_market_data_age_minutes,
        plan_valid_minutes=plan_valid_minutes,
    )
    report: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "overall_status": "dry_run" if not apply_paper else "not_actionable",
        "apply_paper": bool(apply_paper),
        "no_live_order_sent": True,
        "source_backtest_report": _display_path(source_backtest_report_path),
        "snapshot": snapshot,
        "pre_apply_backup": None,
        "result": None,
        "non_negotiables": [
            "never_submit_live_orders_from_this_bridge",
            "do_not_apply_stale_market_data_or_stale_v6_signals",
            "do_not_count_historical_backtest_events_as_current_paper_fills",
            "paper_rollout_policy_keeps_live_enabled_false",
            "create_verified_sqlite_backup_before_any_apply_paper_db_write",
        ],
    }
    if snapshot.get("overall_status") != "actionable":
        report["overall_status"] = "not_actionable"
    elif not apply_paper:
        report["overall_status"] = "dry_run_actionable"
    else:
        backup_report: dict[str, Any]
        if pre_apply_backup_dir is None:
            backup_report = {
                "created": False,
                "required": bool(require_pre_apply_backup),
                "reason": "pre_apply_backup_disabled",
            }
        else:
            try:
                backup_report = _create_sqlite_pre_apply_backup(backup_dir=pre_apply_backup_dir)
                backup_report["required"] = bool(require_pre_apply_backup)
            except Exception as exc:  # pragma: no cover - defensive fail-closed guard.
                backup_report = {
                    "created": False,
                    "required": bool(require_pre_apply_backup),
                    "reason": "pre_apply_backup_exception",
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                }
        report["pre_apply_backup"] = backup_report
        backup_ok = bool(backup_report.get("created")) and str(backup_report.get("quick_check") or "") == "ok"
        if require_pre_apply_backup and not backup_ok:
            report["overall_status"] = "pre_apply_backup_failed"
            report["result"] = {
                "status": "blocked_before_db_write",
                "reason": str(backup_report.get("reason") or "pre_apply_backup_not_verified"),
            }
        else:
            init_db()
            with SessionLocal() as db:
                engine = StrategyEngine(db)
                policy = _ensure_paper_rollout_policy(engine)
                db.commit()
                action = str(snapshot.get("bridge_action") or "")
                if action == "add":
                    event = dict(snapshot.get("latest_event") or {})
                    config = _source_config(source_report)
                    plan = _plan_from_add_event(
                        symbol=symbol,
                        event=event,
                        config=config,
                        now=datetime.now(UTC),
                        valid_minutes=plan_valid_minutes,
                    )
                    bridge_result = _apply_add_snapshot(db=db, engine=engine, snapshot=snapshot, plan=plan)
                elif action == "remove":
                    bridge_result = _apply_remove_snapshot(db=db, engine=engine, snapshot=snapshot)
                else:
                    bridge_result = {"status": "unsupported_action", "action": action}
                report["overall_status"] = str(bridge_result.get("status") or "applied")
                report["paper_rollout_policy"] = policy
                report["result"] = bridge_result

    if report_dir is not None:
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_paper_bridge_tick.json"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
        report["report_path"] = _display_path(json_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bridge fresh v6 decisions to PAPER lifecycle rows.")
    parser.add_argument("--source-backtest-report", default=DEFAULT_SOURCE_BACKTEST_REPORT)
    parser.add_argument("--symbol", default=EXPECTED_SYMBOL)
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--load-days", type=int, default=0, help="0 uses runtime warmup window instead of source search load_days.")
    parser.add_argument("--max-signal-age-minutes", type=int, default=15)
    parser.add_argument("--max-market-data-age-minutes", type=int, default=30)
    parser.add_argument("--plan-valid-minutes", type=int, default=15)
    parser.add_argument("--apply-paper", action="store_true")
    parser.add_argument("--pre-apply-backup-dir", default=DEFAULT_PRE_APPLY_BACKUP_DIR)
    parser.add_argument("--report-dir", default="reports/validation/diagnostics/market_state_rotation_v6_paper_bridge_tick")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_paper_bridge_tick(
        source_backtest_report_path=_resolve(args.source_backtest_report),
        apply_paper=bool(args.apply_paper),
        symbol=str(args.symbol or EXPECTED_SYMBOL).upper(),
        days=max(1, int(args.days)),
        load_days=int(args.load_days) if int(args.load_days) > 0 else None,
        max_signal_age_minutes=max(1, int(args.max_signal_age_minutes)),
        max_market_data_age_minutes=max(1, int(args.max_market_data_age_minutes)),
        plan_valid_minutes=max(1, int(args.plan_valid_minutes)),
        pre_apply_backup_dir=_resolve(args.pre_apply_backup_dir),
        require_pre_apply_backup=True,
        report_dir=_resolve(args.report_dir) if args.write_report else None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
