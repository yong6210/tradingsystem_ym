#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.models import Plan
from app.db.session import SessionLocal, init_db
from app.services.live_route_contract import parse_direction_contract
from app.services.report_io import atomic_write_text
from app.services.strategy_engine import StrategyEngine


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replay recent session_impulse_retest opportunities and attribute whether "
            "runtime observed, blocked, or submitted them."
        )
    )
    parser.add_argument("--lookback-hours", type=int, default=72)
    parser.add_argument("--symbols", default="", help="Comma separated symbols. Empty -> current live universe.")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    return parser.parse_args()


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _session_bucket(ts: datetime, settings: Any) -> str:
    current = _to_utc(ts)
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    london_start = day_start.replace(hour=int(getattr(settings, "trading_session_london_start_hour_utc", 7)))
    london_end = day_start.replace(hour=int(getattr(settings, "trading_session_london_end_hour_utc", 12)))
    new_york_start = day_start.replace(hour=int(getattr(settings, "trading_session_new_york_start_hour_utc", 13)))
    new_york_end = day_start.replace(hour=int(getattr(settings, "trading_session_new_york_end_hour_utc", 18)))
    london_active = london_start <= current < london_end
    new_york_active = new_york_start <= current < new_york_end
    if london_active and new_york_active:
        return "london_new_york_overlap"
    if london_active:
        return "london"
    if new_york_active:
        return "new_york"
    return "dead_session"


def _matching_plan_ids(db: Any, plan_id: str) -> list[str]:
    stmt = (
        select(Plan.plan_id)
        .where(or_(Plan.plan_id == plan_id, Plan.plan_id.like(f"{plan_id}_r%")))
        .order_by(Plan.valid_from.asc(), Plan.plan_id.asc())
    )
    return [str(row) for row in db.scalars(stmt)]


def _row_payload(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    payload = {
        "id": str(getattr(row, "intent_id", getattr(row, "submission_id", "")) or ""),
        "approval_state": str(getattr(row, "approval_state", "") or ""),
        "submit_decision": str(getattr(row, "submit_decision", "") or ""),
        "decision_reason_code": str(getattr(row, "decision_reason_code", "") or ""),
        "decision_reason_message": str(getattr(row, "decision_reason_message", "") or ""),
        "submit_status": str(getattr(row, "submit_status", "") or ""),
        "state": str(getattr(row, "state", "") or ""),
        "message": str(getattr(row, "message", "") or ""),
        "created_at": str(getattr(row, "created_at", "") or ""),
        "submitted_at": str(getattr(row, "submitted_at", "") or ""),
    }
    compact_details = _row_compact_details(row)
    if compact_details:
        payload["details"] = compact_details
    return payload


def _safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _compact_live_order_sizing(value: Any) -> dict[str, Any]:
    sizing = _safe_dict(value)
    keys = (
        "sizing_mode",
        "account_equity_usdt",
        "account_equity_source",
        "balance_asset",
        "risk_per_trade_pct",
        "applied_risk_multiplier",
        "target_risk_usdt",
        "actual_risk_usdt",
        "target_notional",
        "normalized_notional",
        "stop_pct",
        "leverage_cap",
        "sizing_status",
        "liquidity_gate_decision",
    )
    compact = {key: sizing.get(key) for key in keys if sizing.get(key) not in (None, "", [])}
    for nested_key in ("live_tranche", "liquidity_tranche_continuation"):
        nested = _safe_dict(sizing.get(nested_key))
        if nested:
            compact[nested_key] = {
                key: nested.get(key)
                for key in (
                    "enabled",
                    "reason",
                    "tranche_index",
                    "next_tranche_index",
                    "max_tranches",
                    "target_notional",
                    "remaining_notional_before",
                    "submitted_notional",
                    "submitted_target_fraction",
                    "remaining_notional",
                    "capped_max_position_notional",
                    "reason_codes",
                )
                if nested.get(key) not in (None, "", [])
            }
    return compact


def _compact_liquidity_gate(value: Any) -> dict[str, Any]:
    gate = _safe_dict(value)
    if not gate:
        return {}
    snapshot = _safe_dict(gate.get("snapshot"))
    derived = _safe_dict(gate.get("derived"))
    thresholds = _safe_dict(gate.get("thresholds"))
    compact: dict[str, Any] = {
        key: gate.get(key)
        for key in ("enabled", "decision", "reason_codes", "message", "allowed_notional")
        if gate.get(key) not in (None, "", [])
    }
    if thresholds:
        compact["thresholds"] = {
            key: thresholds.get(key)
            for key in (
                "max_spread_bps",
                "max_market_slippage_bps",
                "max_1m_volume_participation",
                "max_5m_volume_participation",
                "max_depth_participation",
                "min_depth_usdt",
            )
            if thresholds.get(key) not in (None, "", [])
        }
    if derived:
        compact["derived"] = {
            key: derived.get(key)
            for key in (
                "order_notional",
                "allowed_notional",
                "depth_participation",
                "one_minute_volume_participation",
                "five_minute_volume_participation",
            )
            if derived.get(key) not in (None, "", [])
        }
    if snapshot:
        compact["snapshot"] = {
            key: snapshot.get(key)
            for key in (
                "best_bid",
                "best_ask",
                "mid_price",
                "reference_price",
                "spread_bps",
                "market_slippage_bps",
                "recent_1m_quote_volume",
                "recent_5m_quote_volume",
                "market_fill_avg_price",
            )
            if snapshot.get(key) not in (None, "", [])
        }
    return compact


def _compact_stop_precheck(value: Any) -> dict[str, Any]:
    precheck = _safe_dict(value)
    if not precheck:
        return {}
    compact = {
        key: precheck.get(key)
        for key in (
            "enabled",
            "decision",
            "reason",
            "reason_codes",
            "message",
            "close_side",
            "entry_side",
            "entry_order_type",
            "stop_price",
            "reference_price",
            "reference_price_source",
            "stop_cushion_bps",
            "min_cushion_bps",
        )
        if precheck.get(key) not in (None, "", [])
    }
    mark_guard = _safe_dict(precheck.get("mark_price_stop_guard"))
    if mark_guard:
        compact["mark_price_stop_guard"] = {
            key: mark_guard.get(key)
            for key in (
                "enabled",
                "decision",
                "reason",
                "reason_codes",
                "message",
                "reference_price_source",
                "reference_price",
                "stop_cushion_bps",
                "min_cushion_bps",
            )
            if mark_guard.get(key) not in (None, "", [])
        }
    return compact


def _compact_protection_orders(value: Any) -> dict[str, Any]:
    protection = _safe_dict(value)
    if not protection:
        return {}
    compact = {
        key: protection.get(key)
        for key in ("status", "reason", "parent_client_order_id", "requires_reconciliation")
        if protection.get(key) not in (None, "", [])
    }
    errors = list(protection.get("errors") or [])
    if errors:
        first_error = _safe_dict(errors[0])
        compact["first_error"] = {
            key: first_error.get(key)
            for key in ("role", "type", "message")
            if first_error.get(key) not in (None, "", [])
        }
        compact["error_count"] = len(errors)
    emergency = _safe_dict(protection.get("emergency_flatten"))
    if emergency:
        result = _safe_dict(emergency.get("result"))
        compact["emergency_flatten"] = {
            key: emergency.get(key)
            for key in ("status", "reason", "client_order_id", "quantity", "requires_reconciliation")
            if emergency.get(key) not in (None, "", [])
        }
        if result:
            compact["emergency_flatten"]["result"] = {
                key: result.get(key)
                for key in ("status", "order_id", "side", "order_type", "executed_qty", "reduce_only", "position_side")
                if result.get(key) not in (None, "", [])
            }
    return compact


def _row_compact_details(row: Any) -> dict[str, Any]:
    attachments = _safe_dict(getattr(row, "attachments", None))
    raw = _safe_dict(getattr(row, "raw", None))
    details: dict[str, Any] = {}
    sizing = _compact_live_order_sizing(attachments.get("live_order_sizing") or raw.get("live_order_sizing"))
    if sizing:
        details["live_order_sizing"] = sizing
    liquidity = _compact_liquidity_gate(attachments.get("live_liquidity_gate") or raw.get("live_liquidity_gate"))
    if liquidity:
        details["live_liquidity_gate"] = liquidity
    stop_precheck = _compact_stop_precheck(attachments.get("live_stop_precheck") or raw.get("live_stop_precheck"))
    if stop_precheck:
        details["live_stop_precheck"] = stop_precheck
    protection = _compact_protection_orders(attachments.get("live_protection_orders") or raw.get("live_protection_orders"))
    if protection:
        details["live_protection_orders"] = protection
    return details


def _submission_acceptance_rank(row: Any) -> int:
    state = str(getattr(row, "state", "") or "").upper()
    submit_status = str(getattr(row, "submit_status", "") or "").upper()
    protection = _safe_dict(_safe_dict(getattr(row, "raw", None)).get("live_protection_orders")) or _safe_dict(
        _safe_dict(getattr(row, "attachments", None)).get("live_protection_orders")
    )
    if str(protection.get("status") or "").upper() == "EMERGENCY_FLATTENED":
        return 5
    if state == "FILLED" or submit_status == "FILLED":
        return 4
    if state == "PARTIALLY_FILLED" or submit_status == "PARTIALLY_FILLED":
        return 3
    if state in {"ACKNOWLEDGED", "SUBMITTED"} or submit_status in {"ACKNOWLEDGED", "SUBMITTED", "LIVE_SUBMITTING"}:
        return 2
    if state == "REJECTED" or submit_status.startswith("LIVE_"):
        return 1
    return 0


def _primary_submission(submissions: list[Any]) -> Any | None:
    if not submissions:
        return None
    return max(
        submissions,
        key=lambda row: (
            _submission_acceptance_rank(row),
            _sort_ts(row, "submitted_at", "created_at"),
        ),
    )


def _sort_ts(row: Any, *attrs: str) -> datetime:
    for attr in attrs:
        value = getattr(row, attr, None)
        if isinstance(value, datetime):
            return _to_utc(value)
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _status_for(
    *,
    observed: bool,
    intents: list[Any],
    submissions: list[Any],
    before_runtime_start: bool = False,
    observation_reason: str = "",
) -> tuple[str, str]:
    if submissions:
        primary = _primary_submission(submissions) or submissions[0]
        return "submitted", str(getattr(primary, "submit_status", "") or getattr(primary, "state", "") or "")
    if intents:
        latest = intents[0]
        decision = str(getattr(latest, "submit_decision", "") or "")
        reason = str(getattr(latest, "decision_reason_code", "") or "")
        if decision == "SUBMIT":
            return "submit_ready_without_submission", reason
        return "blocked_or_skipped", reason
    normalized_observation_reason = str(observation_reason or "").strip() or "runtime_plan_not_seen"
    if before_runtime_start:
        if observed:
            return "pre_runtime_backfill_without_intent", "before_runtime_start"
        return "pre_runtime_unobservable", f"before_runtime_start_{normalized_observation_reason}"
    if observed:
        return "observed_without_intent", "missing_intent"
    return "not_observed", normalized_observation_reason


def _performance(rows: list[dict[str, Any]], *, risk_pct: float, account_equity: float) -> dict[str, Any]:
    total_r = sum(float(row["r_value"]) for row in rows)
    wins = sum(1 for row in rows if float(row["r_value"]) > 0.0)
    losses = len(rows) - wins
    compounded_equity = 1.0
    for row in rows:
        compounded_equity *= 1.0 + (float(row["r_value"]) * risk_pct)
    simple_return_pct = total_r * risk_pct * 100.0
    compounded_return_pct = (compounded_equity - 1.0) * 100.0
    return {
        "trade_count": len(rows),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(rows), 6) if rows else 0.0,
        "total_r": round(total_r, 6),
        "avg_r": round(total_r / len(rows), 6) if rows else 0.0,
        "risk_per_trade_pct": round(risk_pct * 100.0, 6),
        "simple_return_pct": round(simple_return_pct, 6),
        "compounded_return_pct": round(compounded_return_pct, 6),
        "account_equity_usdt": round(account_equity, 6),
        "simple_pnl_usdt": round(account_equity * simple_return_pct / 100.0, 6) if account_equity > 0 else None,
        "compounded_pnl_usdt": round(account_equity * compounded_return_pct / 100.0, 6) if account_equity > 0 else None,
    }


def _summary_for_opportunities(
    rows: list[dict[str, Any]],
    *,
    risk_pct: float,
    account_equity: float,
) -> dict[str, Any]:
    status_counts = Counter(str(row["runtime_status"]) for row in rows)
    reason_counts = Counter(str(row["runtime_reason"]) for row in rows)
    symbol_counts = Counter(str(row["symbol"]) for row in rows)
    session_counts = Counter(str(row["session"]) for row in rows)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["runtime_reason"])].append(row)
    return {
        "expected_order_count": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "symbol_counts": dict(sorted(symbol_counts.items())),
        "session_counts": dict(sorted(session_counts.items())),
        "before_current_runtime_start_count": sum(
            1 for row in rows if bool(row.get("before_current_runtime_start"))
        ),
        "potential_performance": _performance(rows, risk_pct=risk_pct, account_equity=account_equity),
        "performance_by_runtime_reason": {
            reason: _performance(grouped_rows, risk_pct=risk_pct, account_equity=account_equity)
            for reason, grouped_rows in grouped.items()
        },
    }


def _candle_coverage_for_symbols(
    engine: StrategyEngine,
    *,
    symbols: list[str],
    cutoff: datetime,
    end_ts: datetime,
) -> dict[str, Any]:
    requested_hours = max(0.0, (_to_utc(end_ts) - _to_utc(cutoff)).total_seconds() / 3600.0)
    preload_cutoff = _to_utc(cutoff) - timedelta(hours=12)
    rows: list[dict[str, Any]] = []
    missing_1m: list[str] = []
    missing_5m: list[str] = []
    for symbol in symbols:
        first_1m = engine.candle_repo.get_first_candle(symbol, "1m")
        last_1m = engine.candle_repo.get_last_candle(symbol, "1m")
        first_5m = engine.candle_repo.get_first_candle(symbol, "5m")
        last_5m = engine.candle_repo.get_last_candle(symbol, "5m")
        if first_1m is None or last_1m is None:
            missing_1m.append(symbol)
            continue
        if first_5m is None or last_5m is None:
            missing_5m.append(symbol)
        first_1m_ts = _to_utc(first_1m.ts)
        last_1m_ts = min(_to_utc(last_1m.ts), _to_utc(end_ts))
        coverage_hours = max(0.0, (last_1m_ts - first_1m_ts).total_seconds() / 3600.0)
        rows.append(
            {
                "symbol": symbol,
                "first_1m_ts": first_1m_ts,
                "last_1m_ts": last_1m_ts,
                "coverage_hours": coverage_hours,
                "covers_requested_window": first_1m_ts <= _to_utc(cutoff),
                "covers_requested_window_with_preload": first_1m_ts <= preload_cutoff,
            }
        )

    if not rows:
        return {
            "requested_lookback_hours": round(requested_hours, 2),
            "symbol_count": len(symbols),
            "covered_symbol_count": 0,
            "coverage_limited": True,
            "missing_1m_symbols": missing_1m,
            "missing_5m_symbols": missing_5m,
            "note": "No local 1m candles were available for the requested symbols.",
        }

    first_values = [row["first_1m_ts"] for row in rows]
    last_values = [row["last_1m_ts"] for row in rows]
    coverage_values = [float(row["coverage_hours"]) for row in rows]
    limited_symbols = [
        str(row["symbol"])
        for row in rows
        if not bool(row.get("covers_requested_window_with_preload"))
    ]
    coverage_limited = bool(limited_symbols or missing_1m or missing_5m)
    min_coverage = min(coverage_values)
    return {
        "requested_lookback_hours": round(requested_hours, 2),
        "requested_start_ts": _to_utc(cutoff).isoformat(),
        "window_end_ts": _to_utc(end_ts).isoformat(),
        "symbol_count": len(symbols),
        "covered_symbol_count": len(rows),
        "min_first_1m_ts": min(first_values).isoformat(),
        "max_first_1m_ts": max(first_values).isoformat(),
        "min_last_1m_ts": min(last_values).isoformat(),
        "max_last_1m_ts": max(last_values).isoformat(),
        "min_local_1m_coverage_hours": round(min_coverage, 2),
        "max_local_1m_coverage_hours": round(max(coverage_values), 2),
        "full_requested_lookback_available": all(bool(row.get("covers_requested_window")) for row in rows)
        and not missing_1m,
        "full_requested_lookback_with_preload_available": not limited_symbols and not missing_1m,
        "coverage_limited": coverage_limited,
        "limited_symbol_count": len(limited_symbols),
        "limited_symbols_sample": limited_symbols[:10],
        "missing_1m_symbols": missing_1m,
        "missing_5m_symbols": missing_5m,
        "note": (
            f"Local candle replay covers at least {min_coverage:.1f}h of 1m data; "
            "use the external historical replay for older opportunities."
            if coverage_limited
            else "Local candles cover the requested lookback window plus replay preload."
        ),
    }


def _report_path(settings: Any, generated_at: datetime) -> Path:
    out_dir = Path(str(getattr(settings, "validation_report_dir", "reports/validation"))) / "micro_main_opportunity_reports"
    if not out_dir.is_absolute():
        out_dir = ROOT_DIR / out_dir
    return out_dir / f"session_impulse_retest_opportunity_report_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"


def _direction_contract_allows(direction_contract: dict[str, list[str]], symbol: str, direction: str) -> bool:
    normalized_symbol = str(symbol or "").strip().upper()
    normalized_direction = str(direction or "").strip().upper()
    allowed = {
        str(item or "").strip().upper()
        for item in list(direction_contract.get(normalized_symbol) or [])
        if str(item or "").strip()
    }
    if not allowed:
        return True
    return bool(normalized_direction and normalized_direction in allowed)


def _direction_contract_payload(direction_contract: dict[str, list[str]]) -> dict[str, list[str]]:
    return {
        str(symbol or "").strip().upper(): sorted(
            {
                str(direction or "").strip().upper()
                for direction in list(directions or [])
                if str(direction or "").strip()
            }
        )
        for symbol, directions in sorted(dict(direction_contract or {}).items())
        if str(symbol or "").strip()
    }


def build_report(*, lookback_hours: int, symbols: list[str] | None = None) -> dict[str, Any]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    risk_pct = float(getattr(settings, "auto_trading_live_risk_per_trade_pct", 0.0) or 0.0)
    account_equity = float(getattr(settings, "auto_trading_live_account_equity_usdt", 0.0) or 0.0)
    direction_contract = parse_direction_contract(
        getattr(settings, "auto_trading_micro_live_direction_contract", "")
    )

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        target_symbols = engine._session_impulse_retest_miss_detector_symbols(symbols=symbols)
        cutoff = now - timedelta(hours=max(1, int(lookback_hours)))
        runtime_started_at = engine._session_impulse_retest_runtime_started_at()
        coverage = _candle_coverage_for_symbols(
            engine,
            symbols=target_symbols,
            cutoff=cutoff,
            end_ts=now,
        )
        opportunities: list[dict[str, Any]] = []
        direction_filtered_count = 0
        direction_filtered_samples: list[dict[str, Any]] = []

        for symbol in target_symbols:
            trades = engine._session_impulse_retest_recent_replay_trades(
                symbol=symbol,
                cutoff=cutoff,
                end_ts=now,
            )
            for trade in trades:
                entry_ts = engine._to_utc(getattr(trade, "entry_ts"))
                direction = str(getattr(trade, "direction", "") or "").lower()
                if not _direction_contract_allows(direction_contract, symbol, direction):
                    direction_filtered_count += 1
                    if len(direction_filtered_samples) < 10:
                        direction_filtered_samples.append(
                            {
                                "symbol": symbol,
                                "direction": direction,
                                "entry_ts": entry_ts.isoformat(),
                                "allowed_directions": list(
                                    _direction_contract_payload(direction_contract).get(symbol.upper(), [])
                                ),
                                "r_value": round(float(getattr(trade, "r_value", 0.0) or 0.0), 6),
                            }
                        )
                    continue
                plan_id = engine._session_impulse_retest_plan_id_for_entry(
                    symbol=symbol,
                    direction=direction,
                    entry_ts=entry_ts,
                )
                persisted_plan_ids = _matching_plan_ids(db, plan_id)
                observation = engine._session_impulse_retest_runtime_plan_observation(
                    symbol=symbol,
                    entry_ts=entry_ts,
                    direction=direction,
                )
                observed = bool(observation.get("seen")) or bool(persisted_plan_ids)
                lookup_plan_ids = persisted_plan_ids or [plan_id]
                intents = []
                submissions = []
                for lookup_plan_id in lookup_plan_ids:
                    intents.extend(engine.intent_repo.list_for_plan(lookup_plan_id, limit=20))
                    submissions.extend(engine.submission_repo.list_for_plan(lookup_plan_id, limit=20))
                intents.sort(key=lambda row: _sort_ts(row, "created_at"), reverse=True)
                submissions.sort(key=lambda row: _sort_ts(row, "submitted_at", "created_at"), reverse=True)
                primary_submission = _primary_submission(submissions)
                before_current_runtime_start = bool(
                    runtime_started_at is not None and entry_ts < runtime_started_at
                )
                status, reason = _status_for(
                    observed=observed,
                    intents=intents,
                    submissions=submissions,
                    before_runtime_start=before_current_runtime_start,
                    observation_reason=str(observation.get("reason") or ""),
                )
                opportunities.append(
                    {
                        "symbol": symbol,
                        "direction": direction,
                        "session": _session_bucket(entry_ts, settings),
                        "entry_ts": entry_ts.isoformat(),
                        "signal_ts": str(getattr(trade, "signal_ts", "") or ""),
                        "exit_ts": str(getattr(trade, "exit_ts", "") or ""),
                        "exit_reason": str(getattr(trade, "exit_reason", "") or ""),
                        "hold_minutes": int(getattr(trade, "hold_minutes", 0) or 0),
                        "r_value": round(float(getattr(trade, "r_value", 0.0) or 0.0), 6),
                        "return_pct_at_configured_risk": round(
                            float(getattr(trade, "r_value", 0.0) or 0.0) * risk_pct * 100.0,
                            6,
                        ),
                        "expected_plan_id": plan_id,
                        "persisted_plan_ids": persisted_plan_ids,
                        "runtime_observed": observed,
                        "runtime_observation": observation,
                        "intent_count": len(intents),
                        "submission_count": len(submissions),
                        "latest_intent": _row_payload(intents[0] if intents else None),
                        "primary_submission": _row_payload(primary_submission),
                        "latest_submission": _row_payload(submissions[0] if submissions else None),
                        "runtime_status": status,
                        "runtime_reason": reason,
                        "before_current_runtime_start": before_current_runtime_start,
                    }
                )

    opportunities.sort(key=lambda row: str(row.get("entry_ts") or ""))
    runtime_scope = runtime_started_at is not None
    active_opportunities = [
        row for row in opportunities if not bool(row.get("before_current_runtime_start"))
    ] if runtime_scope else list(opportunities)

    payload = {
        "schema_version": "session_impulse_retest_opportunity_report_v2",
        "generated_at": now.isoformat(),
        "lookback_hours": max(1, int(lookback_hours)),
        "opportunity_scope": "runtime_since_ws_start" if runtime_scope else "lookback_window",
        "window_start": cutoff.isoformat(),
        "window_end": now.isoformat(),
        "runtime_started_at": runtime_started_at.isoformat() if runtime_started_at else None,
        "coverage": coverage,
        "contract": {
            "family": "session_impulse_retest",
            "entry_model": "CONFIRM",
            "symbols": target_symbols,
            "direction_contract": _direction_contract_payload(direction_contract),
            "sessions": str(getattr(settings, "auto_trading_micro_live_allowed_sessions", "")),
            "execution_mode": str(getattr(settings, "auto_trading_execution_mode", "")),
            "risk_per_trade_pct": round(risk_pct * 100.0, 6),
            "account_equity_usdt": round(account_equity, 6),
        },
        "direction_filtered_count": direction_filtered_count,
        "direction_filtered_samples": direction_filtered_samples,
        "summary": _summary_for_opportunities(
            active_opportunities,
            risk_pct=risk_pct,
            account_equity=account_equity,
        ),
        "lookback_summary": _summary_for_opportunities(
            opportunities,
            risk_pct=risk_pct,
            account_equity=account_equity,
        ) if runtime_scope else {},
        "opportunities": active_opportunities,
        "lookback_opportunities": opportunities if runtime_scope else [],
        "report_path": None,
    }
    return payload


def main() -> int:
    args = _parse_args()
    init_db()
    symbols = [item.strip().upper() for item in str(args.symbols or "").split(",") if item.strip()]
    payload = build_report(lookback_hours=args.lookback_hours, symbols=symbols or None)
    if args.write_report:
        path = _report_path(get_settings(), datetime.now(timezone.utc))
        payload["report_path"] = str(path)
        atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    if args.summary_only:
        print(
            json.dumps(
                {
                    key: payload[key]
                    for key in (
                        "schema_version",
                        "generated_at",
                        "lookback_hours",
                        "opportunity_scope",
                        "runtime_started_at",
                        "coverage",
                        "contract",
                        "direction_filtered_count",
                        "direction_filtered_samples",
                        "summary",
                        "lookback_summary",
                        "report_path",
                    )
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
