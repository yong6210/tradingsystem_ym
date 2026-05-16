#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.active_contract_replay_baseline import active_micro_live_symbol_contract, usdt_proxy_contract_symbols
from app.services.execution_approval import ExecutionPlanningService
from app.services.report_io import atomic_write_text


BACKTEST_DIR = ROOT_DIR / "reports/validation/micro_main_usdt_proxy_backtests"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure replayable MICRO_LIVE safety-gate drag against a session_impulse_retest backtest report."
    )
    parser.add_argument("--backtest-report", default="", help="Backtest JSON with include-trades output.")
    parser.add_argument("--report-dir", default="reports/validation/micro_live_safety_drag_audits")
    parser.add_argument("--include-samples", action="store_true")
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


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


def _csv_set(raw: Any, *, case: str = "upper") -> set[str]:
    values: set[str] = set()
    for item in str(raw or "").split(","):
        text = str(item or "").strip()
        if not text:
            continue
        if case == "upper":
            text = text.upper()
        elif case == "lower":
            text = text.lower()
        values.add(text)
    return values


def _parse_ts(raw: Any) -> datetime:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("missing timestamp")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _latest_backtest_report(settings: Any | None = None) -> Path:
    candidates = sorted(
        path
        for path in BACKTEST_DIR.glob("micro_main_usdt_proxy_backtest_*.json")
        if "unseen" not in path.name and "top" not in path.name
    )
    if not candidates:
        raise FileNotFoundError(f"no micro_main_usdt_proxy_backtest report under {BACKTEST_DIR}")
    active_symbols = active_micro_live_symbol_contract(settings or get_settings())
    if active_symbols:
        for path in reversed(candidates):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if usdt_proxy_contract_symbols(payload) == active_symbols:
                return path
    return candidates[-1]


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _load_trades(report_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    trades: list[dict[str, Any]] = []
    for symbol_payload in dict(payload.get("results") or {}).values():
        for row in list(dict(symbol_payload or {}).get("trades") or []):
            trade = dict(row)
            trade["entry_ts_dt"] = _parse_ts(trade.get("entry_ts"))
            trade["exit_ts_dt"] = _parse_ts(trade.get("exit_ts"))
            trade["r_value_float"] = _safe_float(trade.get("r_value"))
            trades.append(trade)
    trades.sort(key=lambda row: (row["entry_ts_dt"], str(row.get("symbol") or "")))
    if not trades:
        raise ValueError(f"{report_path} does not include trades; rerun backtest with --include-trades")
    return payload, trades


def _stats(rows: list[dict[str, Any]], *, r_key: str = "r_value_float") -> dict[str, Any]:
    closed = len(rows)
    r_values = [_safe_float(row.get(r_key)) for row in rows]
    wins = [value for value in r_values if value > 0.0]
    losses = [value for value in r_values if value <= 0.0]
    return {
        "closed": closed,
        "total_r": round(sum(r_values), 4),
        "ev_r": round(sum(r_values) / closed, 4) if closed else 0.0,
        "win_rate": round(len(wins) / closed, 4) if closed else 0.0,
        "loss_count": len(losses),
        "loss_r": round(sum(losses), 4),
    }


def _session_name(settings: Any, entry_ts: datetime) -> str:
    hour = int(entry_ts.astimezone(UTC).hour)
    london_start = _safe_int(getattr(settings, "trading_session_london_start_hour_utc", 7), 7)
    london_end = _safe_int(getattr(settings, "trading_session_london_end_hour_utc", 12), 12)
    ny_start = _safe_int(getattr(settings, "trading_session_new_york_start_hour_utc", 13), 13)
    ny_end = _safe_int(getattr(settings, "trading_session_new_york_end_hour_utc", 18), 18)
    if london_start <= hour < london_end:
        return "london"
    if ny_start <= hour < ny_end:
        return "new_york"
    return "dead_session"


def _direction(row: dict[str, Any]) -> str:
    text = str(row.get("direction") or "").strip().lower()
    if text == "long":
        return "LONG"
    if text == "short":
        return "SHORT"
    return text.upper()


def _entry_model(row: dict[str, Any]) -> str:
    explicit = str(row.get("entry_model") or "").strip().upper()
    if explicit:
        return explicit
    if str(row.get("family") or "").strip().lower() == "session_impulse_retest":
        return "CONFIRM"
    return ""


def _plan_id(row: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or "").strip().upper()
    direction_code = "L" if _direction(row) == "LONG" else "S"
    entry_ts = row["entry_ts_dt"].astimezone(UTC).strftime("%Y%m%dT%H%M")
    return f"sir_{symbol}_{direction_code}_{entry_ts}"[:50]


def _parse_direction_contract(raw: Any) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for token in str(raw or "").split(","):
        item = token.strip()
        if not item or ":" not in item:
            continue
        symbol, directions_raw = item.split(":", 1)
        directions = {
            part.strip().upper()
            for part in directions_raw.replace("/", "|").split("|")
            if part.strip()
        }
        normalized_symbol = symbol.strip().upper()
        if normalized_symbol and directions:
            mapping[normalized_symbol] = directions
    return mapping


def _parse_blocked_hours(raw: Any) -> dict[tuple[str, str, str], set[int]]:
    mapping: dict[tuple[str, str, str], set[int]] = {}
    for token in str(raw or "").split(","):
        item = token.strip()
        if not item:
            continue
        parts = [part.strip() for part in item.split(":", 3)]
        if len(parts) != 4:
            continue
        symbol, session_name, direction, hours_raw = parts
        hours: set[int] = set()
        for raw_hour in hours_raw.replace("/", "|").split("|"):
            try:
                hour = int(raw_hour.strip())
            except ValueError:
                continue
            if 0 <= hour <= 23:
                hours.add(hour)
        if hours:
            mapping[(symbol.upper(), session_name.lower(), direction.upper())] = hours
    return mapping


def _load_event_blackouts(settings: Any) -> list[dict[str, Any]]:
    service = ExecutionPlanningService(settings=settings)
    return service.micro_live_event_blackouts()


def _matches_event_blackout(row: dict[str, Any], blackouts: list[dict[str, Any]]) -> str:
    entry_ts = row["entry_ts_dt"]
    symbol = str(row.get("symbol") or "").strip().upper()
    family = str(row.get("family") or "").strip().lower()
    entry_model = _entry_model(row)
    direction = _direction(row)
    session_name = str(row.get("audit_session_name") or "")
    for blackout in blackouts:
        if ExecutionPlanningService._matches_event_blackout(
            entry_ts,
            symbol=symbol,
            family=family,
            entry_model=entry_model,
            direction=direction,
            session_name=session_name,
            blackout_row=blackout,
        ):
            return str(blackout.get("label") or "micro_live_event_blackout_active")
    return ""


def _sizing_gate_reason(settings: Any, row: dict[str, Any]) -> str:
    if str(getattr(settings, "auto_trading_live_sizing_mode", "NOTIONAL_PER_R") or "").strip().upper() != "RISK_PCT":
        return ""
    entry_price = _safe_float(row.get("entry_price"))
    stop_distance_pct = abs(_safe_float(row.get("stop_distance_pct")))
    if entry_price <= 0.0 or stop_distance_pct <= 0.0:
        return "live_sizing_missing_reference"
    equity = _safe_float(getattr(settings, "auto_trading_live_account_equity_usdt", 0.0))
    risk_pct = _safe_float(getattr(settings, "auto_trading_live_risk_per_trade_pct", 0.0))
    margin_fraction = _safe_float(getattr(settings, "auto_trading_live_usable_margin_fraction", 0.0))
    leverage_cap = _safe_float(getattr(settings, "auto_trading_live_leverage_cap", 0.0))
    if equity <= 0.0 or risk_pct <= 0.0 or margin_fraction <= 0.0 or leverage_cap <= 0.0:
        return "live_sizing_config_invalid"
    target_notional = equity * risk_pct / stop_distance_pct
    leverage_cap_notional = equity * margin_fraction * leverage_cap
    max_position_notional = min(target_notional, leverage_cap_notional)
    quantity = max_position_notional / entry_price
    step = max(_safe_float(getattr(settings, "binance_live_quantity_step", 0.001), 0.001), 1e-12)
    min_qty = max(_safe_float(getattr(settings, "binance_live_min_quantity", step), step), step)
    normalized_quantity = int(quantity / step) * step
    row["audit_live_sizing"] = {
        "target_notional": round(target_notional, 4),
        "leverage_cap_notional": round(leverage_cap_notional, 4),
        "max_position_notional": round(max_position_notional, 4),
        "quantity": round(quantity, 8),
        "normalized_quantity": round(normalized_quantity, 8),
        "min_quantity": round(min_qty, 8),
    }
    if normalized_quantity + 1e-12 < min_qty:
        return "live_sizing_min_quantity_not_met"
    return ""


def _contract_block_reason(
    settings: Any,
    row: dict[str, Any],
    *,
    event_blackouts: list[dict[str, Any]],
    plan_blocklist: set[str],
) -> str:
    symbol = str(row.get("symbol") or "").strip().upper()
    family = str(row.get("family") or "").strip().lower()
    entry_model = _entry_model(row)
    direction = _direction(row)
    session_name = _session_name(settings, row["entry_ts_dt"])
    row["audit_session_name"] = session_name
    row["audit_entry_model"] = entry_model
    row["audit_plan_id"] = _plan_id(row)

    allowed_symbols = _csv_set(getattr(settings, "auto_trading_micro_live_allowed_symbols", ""), case="upper")
    allowed_families = _csv_set(getattr(settings, "auto_trading_micro_live_allowed_families", ""), case="lower")
    allowed_entry_models = _csv_set(getattr(settings, "auto_trading_micro_live_allowed_entry_models", ""), case="upper")
    allowed_sessions = _csv_set(getattr(settings, "auto_trading_micro_live_allowed_sessions", ""), case="lower")
    direction_contract = _parse_direction_contract(getattr(settings, "auto_trading_micro_live_direction_contract", ""))
    blocked_hours = _parse_blocked_hours(
        getattr(settings, "auto_trading_micro_live_session_direction_blocked_hours_utc", "")
    )

    if allowed_symbols and symbol not in allowed_symbols:
        return "micro_live_symbol_not_allowed"
    if allowed_families and family not in allowed_families:
        return "micro_live_family_not_allowed"
    if allowed_entry_models and entry_model not in allowed_entry_models:
        return "micro_live_entry_model_not_allowed"
    if allowed_sessions and session_name not in allowed_sessions:
        return "micro_live_session_not_allowed"
    allowed_directions = direction_contract.get(symbol) or set()
    if allowed_directions and direction not in allowed_directions:
        return "micro_live_direction_not_allowed"
    blocked = blocked_hours.get((symbol, session_name, direction)) or set()
    if blocked and int(row["entry_ts_dt"].hour) in blocked:
        return "micro_live_session_direction_hour_not_allowed"
    blackout_label = _matches_event_blackout(row, event_blackouts)
    if blackout_label:
        row["audit_event_blackout_label"] = blackout_label
        return "micro_live_event_blackout_active"
    if plan_blocklist and row["audit_plan_id"] in plan_blocklist:
        return "micro_live_plan_id_blocklisted"
    sizing_reason = _sizing_gate_reason(settings, row)
    if sizing_reason:
        return sizing_reason
    return ""


def _load_plan_blocklist(settings: Any) -> set[str]:
    raw = str(getattr(settings, "auto_trading_micro_live_plan_blocklist_path", "") or "").strip()
    if not raw:
        return set()
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT_DIR / path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    rows = payload.get("blocked_plan_ids")
    if not isinstance(rows, list):
        rows = payload.get("plan_ids")
    return {str(item or "").strip() for item in list(rows or []) if str(item or "").strip()}


def _simulate_pacing(
    settings: Any,
    rows: list[dict[str, Any]],
    *,
    enabled_gates: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    gates = set(enabled_gates or {"position_cap", "daily_cap", "family_cluster", "direction_exposure", "loss_cooldown"})
    max_concurrent = max(0, _safe_int(getattr(settings, "auto_trading_micro_live_max_concurrent_positions", 2), 2))
    daily_cap = max(0, _safe_int(getattr(settings, "auto_trading_micro_live_max_daily_new_entries", 0), 0))
    cluster_window_minutes = max(0, _safe_int(getattr(settings, "auto_trading_live_family_cluster_window_minutes", 60), 60))
    cluster_cap = max(0, _safe_int(getattr(settings, "auto_trading_live_max_same_family_entries_per_window", 0), 0))
    direction_cap = max(0, _safe_int(getattr(settings, "auto_trading_live_max_same_family_direction_exposures", 0), 0))
    loss_window_minutes = max(0, _safe_int(getattr(settings, "auto_trading_live_recent_loss_cooldown_minutes", 90), 90))
    loss_trigger = max(0, _safe_int(getattr(settings, "auto_trading_live_recent_loss_trigger_count", 0), 0))
    saturday_multiplier = max(
        0.0,
        _safe_float(getattr(settings, "session_impulse_retest_saturday_risk_multiplier", 1.0), 1.0),
    )

    accepted: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    open_positions: list[dict[str, Any]] = []
    recent_losses: list[dict[str, Any]] = []
    daily_counts: dict[str, int] = defaultdict(int)

    for row in rows:
        entry_ts = row["entry_ts_dt"]
        family = str(row.get("family") or "").strip().lower()
        direction = _direction(row)

        closed_now = [item for item in open_positions if item["exit_ts_dt"] <= entry_ts]
        open_positions = [item for item in open_positions if item["exit_ts_dt"] > entry_ts]
        for closed in closed_now:
            if _safe_float(closed.get("r_value_float")) <= 0.0:
                recent_losses.append(closed)

        cluster_cutoff = entry_ts - timedelta(minutes=cluster_window_minutes) if cluster_window_minutes > 0 else entry_ts

        if loss_window_minutes > 0:
            loss_cutoff = entry_ts - timedelta(minutes=loss_window_minutes)
            recent_losses = [item for item in recent_losses if item["exit_ts_dt"] > loss_cutoff]
        else:
            recent_losses = []

        reason = ""
        if "position_cap" in gates and max_concurrent > 0 and len(open_positions) >= max_concurrent:
            reason = "micro_live_position_cap_reached"
        elif "daily_cap" in gates and daily_cap > 0 and daily_counts[entry_ts.date().isoformat()] >= daily_cap:
            reason = "micro_live_daily_entry_cap_reached"
        elif "family_cluster" in gates and cluster_cap > 0 and sum(
            1
            for item in open_positions
            if str(item.get("family") or "").strip().lower() == family and item["entry_ts_dt"] >= cluster_cutoff
        ) >= cluster_cap:
            reason = "live_family_cluster_window_cap_reached"
        elif "direction_exposure" in gates and direction_cap > 0 and sum(
            1
            for item in open_positions
            if str(item.get("family") or "").strip().lower() == family and _direction(item) == direction
        ) >= direction_cap:
            reason = "live_family_direction_exposure_cap_reached"
        elif "loss_cooldown" in gates and loss_trigger > 0 and sum(1 for item in recent_losses if str(item.get("family") or "").strip().lower() == family) >= loss_trigger:
            reason = "live_family_loss_cooldown_active"

        if reason:
            blocked_row = dict(row)
            blocked_row["audit_block_reason"] = reason
            blocked.append(blocked_row)
            continue

        accepted_row = dict(row)
        risk_multiplier = saturday_multiplier if entry_ts.weekday() == 5 else 1.0
        accepted_row["audit_risk_multiplier"] = round(risk_multiplier, 4)
        accepted_row["risk_adjusted_r"] = round(_safe_float(row.get("r_value_float")) * risk_multiplier, 6)
        accepted.append(accepted_row)
        open_positions.append(accepted_row)
        daily_counts[entry_ts.date().isoformat()] += 1

    return accepted, blocked


def build_payload(*, backtest_report: Path, include_samples: bool = False) -> dict[str, Any]:
    settings = get_settings()
    report_payload, trades = _load_trades(backtest_report)
    event_blackouts = _load_event_blackouts(settings)
    plan_blocklist = _load_plan_blocklist(settings)

    contract_pass: list[dict[str, Any]] = []
    contract_blocked: list[dict[str, Any]] = []
    for row in trades:
        reason = _contract_block_reason(
            settings,
            row,
            event_blackouts=event_blackouts,
            plan_blocklist=plan_blocklist,
        )
        if reason:
            blocked_row = dict(row)
            blocked_row["audit_block_reason"] = reason
            contract_blocked.append(blocked_row)
        else:
            contract_pass.append(dict(row))

    accepted, pacing_blocked = _simulate_pacing(settings, contract_pass)
    all_blocked = contract_blocked + pacing_blocked
    baseline_stats = _stats(trades)
    contract_stats = _stats(contract_pass)
    accepted_stats = _stats(accepted)
    accepted_risk_stats = _stats(accepted, r_key="risk_adjusted_r")
    removed_stats = _stats(all_blocked)
    block_counts = Counter(str(row.get("audit_block_reason") or "unknown") for row in all_blocked)

    def drag(after: dict[str, Any]) -> dict[str, Any]:
        baseline_closed = max(_safe_int(baseline_stats.get("closed")), 1)
        baseline_total = _safe_float(baseline_stats.get("total_r"))
        after_total = _safe_float(after.get("total_r"))
        return {
            "closed_delta": _safe_int(after.get("closed")) - _safe_int(baseline_stats.get("closed")),
            "closed_delta_pct": round(
                (_safe_int(after.get("closed")) - _safe_int(baseline_stats.get("closed"))) / baseline_closed,
                6,
            ),
            "total_r_delta": round(after_total - baseline_total, 4),
            "total_r_delta_pct": round((after_total - baseline_total) / baseline_total, 6) if baseline_total else None,
            "ev_r_delta": round(_safe_float(after.get("ev_r")) - _safe_float(baseline_stats.get("ev_r")), 4),
        }

    waterfall_specs = [
        ("contract_filters_only", set()),
        ("position_cap", {"position_cap"}),
        ("position_plus_daily_cap", {"position_cap", "daily_cap"}),
        ("plus_family_cluster_window", {"position_cap", "daily_cap", "family_cluster"}),
        (
            "plus_same_direction_exposure",
            {"position_cap", "daily_cap", "family_cluster", "direction_exposure"},
        ),
        (
            "plus_loss_cooldown",
            {"position_cap", "daily_cap", "family_cluster", "direction_exposure", "loss_cooldown"},
        ),
    ]
    safety_waterfall: list[dict[str, Any]] = []
    previous_stats = contract_stats
    for name, gates in waterfall_specs:
        if name == "contract_filters_only":
            stage_rows = contract_pass
            stage_blocked: list[dict[str, Any]] = []
        else:
            stage_rows, stage_blocked = _simulate_pacing(settings, contract_pass, enabled_gates=gates)
        stage_stats = _stats(stage_rows)
        safety_waterfall.append(
            {
                "stage": name,
                **stage_stats,
                "incremental_closed_delta": _safe_int(stage_stats.get("closed")) - _safe_int(previous_stats.get("closed")),
                "incremental_total_r_delta": round(
                    _safe_float(stage_stats.get("total_r")) - _safe_float(previous_stats.get("total_r")),
                    4,
                ),
                "drag_vs_baseline": drag(stage_stats),
                "block_reason_counts": dict(
                    sorted(Counter(str(row.get("audit_block_reason") or "unknown") for row in stage_blocked).items())
                ),
            }
        )
        previous_stats = stage_stats

    samples: dict[str, Any] = {}
    if include_samples:
        samples = {
            "blocked": [
                {
                    "symbol": row.get("symbol"),
                    "entry_ts": row.get("entry_ts"),
                    "exit_ts": row.get("exit_ts"),
                    "direction": row.get("direction"),
                    "r_value": row.get("r_value"),
                    "reason": row.get("audit_block_reason"),
                    "session_name": row.get("audit_session_name"),
                }
                for row in all_blocked[:50]
            ],
            "accepted": [
                {
                    "symbol": row.get("symbol"),
                    "entry_ts": row.get("entry_ts"),
                    "direction": row.get("direction"),
                    "r_value": row.get("r_value"),
                    "risk_adjusted_r": row.get("risk_adjusted_r"),
                    "risk_multiplier": row.get("audit_risk_multiplier"),
                }
                for row in accepted[:50]
            ],
        }

    return {
        "schema_version": "micro_live_safety_drag_audit_v1",
        "generated_at": _now().isoformat().replace("+00:00", "Z"),
        "backtest_report": _display_path(backtest_report),
        "backtest_generated_at": report_payload.get("generated_at"),
        "config": {
            "allowed_symbols": sorted(_csv_set(getattr(settings, "auto_trading_micro_live_allowed_symbols", ""), case="upper")),
            "allowed_families": sorted(_csv_set(getattr(settings, "auto_trading_micro_live_allowed_families", ""), case="lower")),
            "allowed_entry_models": sorted(_csv_set(getattr(settings, "auto_trading_micro_live_allowed_entry_models", ""), case="upper")),
            "allowed_sessions": sorted(_csv_set(getattr(settings, "auto_trading_micro_live_allowed_sessions", ""), case="lower")),
            "max_concurrent_positions": _safe_int(getattr(settings, "auto_trading_micro_live_max_concurrent_positions", 2), 2),
            "max_daily_new_entries": _safe_int(getattr(settings, "auto_trading_micro_live_max_daily_new_entries", 0), 0),
            "family_cluster_window_minutes": _safe_int(getattr(settings, "auto_trading_live_family_cluster_window_minutes", 60), 60),
            "max_same_family_entries_per_window": _safe_int(getattr(settings, "auto_trading_live_max_same_family_entries_per_window", 0), 0),
            "max_same_family_direction_exposures": _safe_int(getattr(settings, "auto_trading_live_max_same_family_direction_exposures", 0), 0),
            "recent_loss_cooldown_minutes": _safe_int(getattr(settings, "auto_trading_live_recent_loss_cooldown_minutes", 90), 90),
            "recent_loss_trigger_count": _safe_int(getattr(settings, "auto_trading_live_recent_loss_trigger_count", 0), 0),
            "saturday_risk_multiplier": _safe_float(getattr(settings, "session_impulse_retest_saturday_risk_multiplier", 1.0), 1.0),
            "event_blackout_windows": len(event_blackouts),
            "plan_blocklist_count": len(plan_blocklist),
            "liquidity_gate_enabled": bool(getattr(settings, "auto_trading_live_liquidity_gate_enabled", False)),
            "liquidity_gate_historical_drag": "not_quantified_without_historical_orderbook_snapshots",
        },
        "baseline": baseline_stats,
        "after_contract_filters": {
            **contract_stats,
            "drag_vs_baseline": drag(contract_stats),
        },
        "after_replayable_safety_gates": {
            **accepted_stats,
            "drag_vs_baseline": drag(accepted_stats),
        },
        "after_replayable_safety_gates_and_risk_multipliers": {
            **accepted_risk_stats,
            "drag_vs_baseline": drag(accepted_risk_stats),
        },
        "safety_waterfall": safety_waterfall,
        "removed_by_safety": {
            **removed_stats,
            "reason_counts": dict(sorted(block_counts.items())),
            "removed_positive_r": round(sum(_safe_float(row.get("r_value_float")) for row in all_blocked if _safe_float(row.get("r_value_float")) > 0.0), 4),
            "removed_nonpositive_r": round(sum(_safe_float(row.get("r_value_float")) for row in all_blocked if _safe_float(row.get("r_value_float")) <= 0.0), 4),
        },
        "notes": [
            "Replayable gates use the current .env contract against historical backtest trades.",
            "Session names are reconstructed from configured UTC London/New York windows; all remaining hours are dead_session.",
            "Liquidity depth/spread/slippage drag is not exact from this report because historical orderbook snapshots are not in the backtest artifact.",
            "This audit measures strategy opportunity drag, not exchange fill slippage or live PnL guarantee.",
        ],
        **({"samples": samples} if samples else {}),
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# MICRO_LIVE Safety Drag Audit",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- backtest_report: {payload.get('backtest_report')}",
        "",
        "## Summary",
        "",
        f"- baseline: {payload['baseline']}",
        f"- after_contract_filters: {payload['after_contract_filters']}",
        f"- after_replayable_safety_gates: {payload['after_replayable_safety_gates']}",
        f"- after_replayable_safety_gates_and_risk_multipliers: {payload['after_replayable_safety_gates_and_risk_multipliers']}",
        f"- removed_by_safety: {payload['removed_by_safety']}",
        "",
        "## Config",
        "",
        "```json",
        json.dumps(payload.get("config") or {}, ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Notes",
        "",
    ]
    lines.extend(f"- {item}" for item in list(payload.get("notes") or []))
    lines.extend(["", "## Payload", "", "```json", json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), "```"])
    atomic_write_text(path, "\n".join(lines) + "\n")


def main() -> int:
    args = _parse_args()
    backtest_report = Path(args.backtest_report) if str(args.backtest_report or "").strip() else _latest_backtest_report(settings)
    if not backtest_report.is_absolute():
        backtest_report = ROOT_DIR / backtest_report
    payload = build_payload(backtest_report=backtest_report, include_samples=bool(args.include_samples))
    if not bool(args.no_write_report):
        generated = _parse_ts(payload["generated_at"])
        report_dir = Path(str(args.report_dir))
        if not report_dir.is_absolute():
            report_dir = ROOT_DIR / report_dir
        report_path = report_dir / f"micro_live_safety_drag_audit_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
        _write_report(report_path, payload)
        payload["report_path"] = _display_path(report_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
