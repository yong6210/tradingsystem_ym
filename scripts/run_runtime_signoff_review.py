#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import socket
import sys
import time
from typing import Any
from urllib import error, parse, request

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.core import operator_surface_contracts as osc


DEFAULT_STAGE_FILE = ROOT_DIR / "reports/operations/stage_monitor/current_stage.json"
_POST_PATCH_BASELINE_TEXT = os.environ.get("RUNTIME_MITIGATION_BASELINE_TS", "2026-04-10T00:00:00+09:00")
_POST_PATCH_SAMPLE_GOAL = max(int(os.environ.get("RUNTIME_MITIGATION_BASELINE_GOAL", "20")), 1)
_LIVE_ELIGIBLE_CONTRACT_SCOPE = str(
    os.environ.get("RUNTIME_LIVE_ELIGIBLE_CONTRACT_SCOPE", "limit_only")
).strip() or "limit_only"
_TREND_PROOF_CONTRACT_SCOPE = str(
    os.environ.get("RUNTIME_TREND_PROOF_CONTRACT_SCOPE", "trend_limit_only")
).strip() or "trend_limit_only"
_TREND_PROOF_FAMILIES = tuple(
    item.strip().lower()
    for item in str(os.environ.get("RUNTIME_TREND_PROOF_FAMILIES", "trend_continuation")).split(",")
    if item.strip()
)
_TREND_PROOF_MIN_CLOSED_TRADES = max(
    int(os.environ.get("RUNTIME_TREND_PROOF_MIN_CLOSED_TRADES", "5")),
    1,
)


def _resolve_root_path(raw_path: str | Path) -> Path:
    path = Path(raw_path).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


def _live_execution_allowed_entry_models() -> tuple[str, ...]:
    env_override = tuple(
        item.strip().upper()
        for item in str(os.environ.get("RUNTIME_LIVE_ELIGIBLE_ENTRY_MODELS", "")).split(",")
        if item.strip()
    )
    if env_override:
        return env_override
    settings = get_settings()
    configured = tuple(
        item.strip().upper()
        for item in str(getattr(settings, "auto_trading_micro_live_allowed_entry_models", "") or "").split(",")
        if item.strip()
    )
    return configured or ("LIMIT",)
_HISTORICAL_CONTRACT_PROOF_LOOKBACK_DAYS = max(
    int(os.environ.get("RUNTIME_HISTORICAL_CONTRACT_PROOF_LOOKBACK_DAYS", "180")),
    1,
)
_HISTORICAL_CONTRACT_PROOF_MIN_CLOSED_TRADES = max(
    int(os.environ.get("RUNTIME_HISTORICAL_CONTRACT_PROOF_MIN_CLOSED_TRADES", "20")),
    1,
)
_HISTORICAL_CONTRACT_PROOF_CONTRACT_SCOPE = str(
    os.environ.get("RUNTIME_HISTORICAL_CONTRACT_PROOF_CONTRACT_SCOPE", "historical_limit_only")
).strip() or "historical_limit_only"
_HISTORICAL_WALK_FORWARD_EXECUTION_PROOF_MIN_CLOSED_TRADES = max(
    int(os.environ.get("RUNTIME_HISTORICAL_WALK_FORWARD_EXECUTION_PROOF_MIN_CLOSED_TRADES", "20")),
    1,
)
_HISTORICAL_WALK_FORWARD_EXECUTION_PROOF_CONTRACT_SCOPE = str(
    os.environ.get("RUNTIME_HISTORICAL_WALK_FORWARD_EXECUTION_PROOF_CONTRACT_SCOPE", "historical_walk_forward_limit_only")
).strip() or "historical_walk_forward_limit_only"
_HISTORICAL_WALK_FORWARD_TREND_PROOF_MIN_CLOSED_TRADES = max(
    int(os.environ.get("RUNTIME_HISTORICAL_WALK_FORWARD_TREND_PROOF_MIN_CLOSED_TRADES", "5")),
    1,
)
_HISTORICAL_WALK_FORWARD_TREND_PROOF_CONTRACT_SCOPE = str(
    os.environ.get("RUNTIME_HISTORICAL_WALK_FORWARD_TREND_PROOF_CONTRACT_SCOPE", "historical_walk_forward_trend_limit_only")
).strip() or "historical_walk_forward_trend_limit_only"
_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_MIN_CLOSED_TRADES = max(
    int(os.environ.get("RUNTIME_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_MIN_CLOSED_TRADES", "100")),
    1,
)
_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_CONTRACT_SCOPE = str(
    os.environ.get("RUNTIME_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_CONTRACT_SCOPE", "historical_walk_forward_strategy_level")
).strip() or "historical_walk_forward_strategy_level"
_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_ENTRY_MODELS = tuple(
    item.strip().upper()
    for item in str(
        os.environ.get("RUNTIME_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_ENTRY_MODELS", "LIMIT")
    ).split(",")
    if item.strip()
)
_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_FAMILIES = tuple(
    item.strip().lower()
    for item in str(
        os.environ.get("RUNTIME_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_FAMILIES", "sweep_reversal")
    ).split(",")
    if item.strip()
)
_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_SOURCE_MODE = str(
    os.environ.get("RUNTIME_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_SOURCE_MODE", "raw_candle_heuristic")
).strip() or "raw_candle_heuristic"
_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_CACHE_KEY = str(
    os.environ.get("RUNTIME_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_CACHE_KEY", "strategy_proof_contract_live_subset")
).strip() or "strategy_proof_contract_live_subset"
_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_MAX_CANDIDATES_PER_BAR = max(
    int(os.environ.get("RUNTIME_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_MAX_CANDIDATES_PER_BAR", "1")),
    1,
)
_LIVE_EXECUTION_BOOTSTRAP_MIN_CLOSED_TRADES = max(
    int(os.environ.get("RUNTIME_LIVE_EXECUTION_BOOTSTRAP_MIN_CLOSED_TRADES", "5")),
    1,
)
_POST_PATCH_MICRO_LIVE_MIN_CLOSED_TRADES = max(
    int(os.environ.get("RUNTIME_MICRO_LIVE_POST_PATCH_MIN_CLOSED_TRADES", "50")),
    1,
)
_POST_PATCH_MICRO_LIVE_MAX_DRAWDOWN_R = float(
    os.environ.get("RUNTIME_MICRO_LIVE_POST_PATCH_MAX_DRAWDOWN_R", "5.0")
)
_POST_PATCH_MICRO_LIVE_MIN_P5_R = float(
    os.environ.get("RUNTIME_MICRO_LIVE_POST_PATCH_MIN_P5_R", "-1.05")
)
_POST_PATCH_MICRO_LIVE_MAX_STOP_LOSS_SHARE = float(
    os.environ.get("RUNTIME_MICRO_LIVE_POST_PATCH_MAX_STOP_LOSS_SHARE", "0.35")
)
_POST_PATCH_MICRO_LIVE_MAX_LOSS_STREAK = int(
    os.environ.get("RUNTIME_MICRO_LIVE_POST_PATCH_MAX_LOSS_STREAK", "5")
)
_POST_PATCH_FULL_LIVE_MIN_CLOSED_TRADES = max(
    int(os.environ.get("RUNTIME_FULL_LIVE_POST_PATCH_MIN_CLOSED_TRADES", "80")),
    1,
)
_POST_PATCH_FULL_LIVE_MAX_DRAWDOWN_R = float(
    os.environ.get("RUNTIME_FULL_LIVE_POST_PATCH_MAX_DRAWDOWN_R", "5.0")
)
_POST_PATCH_FULL_LIVE_MIN_P5_R = float(
    os.environ.get("RUNTIME_FULL_LIVE_POST_PATCH_MIN_P5_R", "-1.05")
)
_POST_PATCH_FULL_LIVE_MAX_STOP_LOSS_SHARE = float(
    os.environ.get("RUNTIME_FULL_LIVE_POST_PATCH_MAX_STOP_LOSS_SHARE", "0.30")
)
_POST_PATCH_FULL_LIVE_MAX_LOSS_STREAK = int(
    os.environ.get("RUNTIME_FULL_LIVE_POST_PATCH_MAX_LOSS_STREAK", "5")
)
_LIVE_ELIGIBLE_MICRO_LIVE_MIN_CLOSED_TRADES = max(
    int(os.environ.get("RUNTIME_MICRO_LIVE_LIMIT_ONLY_MIN_CLOSED_TRADES", "15")),
    1,
)
_LIVE_ELIGIBLE_MICRO_LIVE_MAX_DRAWDOWN_R = float(
    os.environ.get("RUNTIME_MICRO_LIVE_LIMIT_ONLY_MAX_DRAWDOWN_R", "4.5")
)
_LIVE_ELIGIBLE_MICRO_LIVE_MIN_P5_R = float(
    os.environ.get("RUNTIME_MICRO_LIVE_LIMIT_ONLY_MIN_P5_R", "-1.05")
)
_LIVE_ELIGIBLE_MICRO_LIVE_MAX_STOP_LOSS_SHARE = float(
    os.environ.get("RUNTIME_MICRO_LIVE_LIMIT_ONLY_MAX_STOP_LOSS_SHARE", "0.45")
)
_LIVE_ELIGIBLE_MICRO_LIVE_MAX_LOSS_STREAK = int(
    os.environ.get("RUNTIME_MICRO_LIVE_LIMIT_ONLY_MAX_LOSS_STREAK", "5")
)
_LIVE_ELIGIBLE_FULL_LIVE_MIN_CLOSED_TRADES = max(
    int(os.environ.get("RUNTIME_FULL_LIVE_LIMIT_ONLY_MIN_CLOSED_TRADES", "30")),
    1,
)
_LIVE_ELIGIBLE_FULL_LIVE_MAX_DRAWDOWN_R = float(
    os.environ.get("RUNTIME_FULL_LIVE_LIMIT_ONLY_MAX_DRAWDOWN_R", "4.5")
)
_LIVE_ELIGIBLE_FULL_LIVE_MIN_P5_R = float(
    os.environ.get("RUNTIME_FULL_LIVE_LIMIT_ONLY_MIN_P5_R", "-1.05")
)
_LIVE_ELIGIBLE_FULL_LIVE_MAX_STOP_LOSS_SHARE = float(
    os.environ.get("RUNTIME_FULL_LIVE_LIMIT_ONLY_MAX_STOP_LOSS_SHARE", "0.40")
)
_LIVE_ELIGIBLE_FULL_LIVE_MAX_LOSS_STREAK = int(
    os.environ.get("RUNTIME_FULL_LIVE_LIMIT_ONLY_MAX_LOSS_STREAK", "5")
)
_GLOBAL_LINEAGE_VALIDATION_SYMBOL = "LINEAGE_GLOBAL"
_GLOBAL_LINEAGE_VALIDATION_FAMILIES = ("sweep_reversal", "trend_continuation")


def _live_execution_allowed_symbols() -> tuple[str, ...]:
    override = str(os.environ.get("RUNTIME_LIVE_EXECUTION_ALLOWED_SYMBOLS", "") or "").strip()
    if override:
        return tuple(item.strip().upper() for item in override.split(",") if item.strip())
    settings = get_settings()
    return tuple(
        item.strip().upper()
        for item in str(getattr(settings, "auto_trading_micro_live_allowed_symbols", "") or "").split(",")
        if item.strip()
    )


def _live_execution_allowed_families() -> tuple[str, ...]:
    override = str(os.environ.get("RUNTIME_LIVE_EXECUTION_ALLOWED_FAMILIES", "") or "").strip()
    if override:
        return tuple(item.strip().lower() for item in override.split(",") if item.strip())
    settings = get_settings()
    return tuple(
        item.strip().lower()
        for item in str(getattr(settings, "auto_trading_micro_live_allowed_families", "") or "").split(",")
        if item.strip()
    )


def _parse_symbol_direction_contract(value: Any) -> dict[str, tuple[str, ...]]:
    mapping: dict[str, tuple[str, ...]] = {}
    for item in str(value or "").split(","):
        token = item.strip()
        if not token or ":" not in token:
            continue
        symbol, raw_directions = token.split(":", 1)
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            continue
        directions = tuple(
            dict.fromkeys(
                direction.strip().upper()
                for direction in str(raw_directions or "").replace("/", "|").split("|")
                if direction.strip()
            )
        )
        if directions:
            mapping[normalized_symbol] = directions
    return mapping


def _live_execution_direction_contract() -> dict[str, tuple[str, ...]]:
    override = str(os.environ.get("RUNTIME_LIVE_EXECUTION_DIRECTION_CONTRACT", "") or "").strip()
    if override:
        return _parse_symbol_direction_contract(override)
    settings = get_settings()
    return _parse_symbol_direction_contract(getattr(settings, "auto_trading_micro_live_direction_contract", ""))


def _direction_contract_summary_items(contract: dict[str, tuple[str, ...]] | None) -> list[str]:
    items: list[str] = []
    for symbol in sorted(dict(contract or {})):
        directions = [str(item or "").strip().upper() for item in list(dict(contract or {}).get(symbol) or []) if str(item or "").strip()]
        if directions:
            items.append(f"{symbol}:{'|'.join(directions)}")
    return items


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize the remaining runtime operator sign-off decision."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--stage-file", default=str(DEFAULT_STAGE_FILE))
    parser.add_argument("--report-dir", default="reports/operations/runtime_signoff_reviews")
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(item) for item in values)
    if len(ordered) == 1:
        return float(ordered[0])
    clamped = min(max(float(q), 0.0), 1.0)
    index = int(round(clamped * (len(ordered) - 1)))
    return float(ordered[index])


def _max_drawdown(values: list[float]) -> float:
    peak = 0.0
    equity = 0.0
    worst_drawdown = 0.0
    for item in values:
        equity += float(item)
        peak = max(peak, equity)
        worst_drawdown = max(worst_drawdown, peak - equity)
    return float(worst_drawdown)


def _build_post_patch_threshold_breaches(
    post_patch: dict[str, Any] | None,
    *,
    min_closed_trades: int,
    max_drawdown_r: float,
    min_p5_r: float,
    max_stop_loss_share: float,
    max_loss_streak: int,
    code_prefix: str = "post_patch",
) -> list[dict[str, Any]]:
    summary = dict(post_patch or {})
    breached_thresholds: list[dict[str, Any]] = []
    closed_trade_count = int(summary.get("closed_trade_count", 0) or 0)
    replay_max_drawdown_r = float(summary.get("replay_max_drawdown_r", 0.0) or 0.0)
    replay_p5_r = float(summary.get("replay_p5_r", 0.0) or 0.0)
    stop_loss_share = float(summary.get("stop_loss_share", 0.0) or 0.0)
    worst_loss_streak = int(summary.get("worst_loss_streak", 0) or 0)
    if closed_trade_count < min_closed_trades:
        breached_thresholds.append(
            {
                "code": f"{code_prefix}_sample_count_min",
                "value": closed_trade_count,
                "threshold": min_closed_trades,
            }
        )
    if replay_max_drawdown_r >= max_drawdown_r:
        breached_thresholds.append(
            {
                "code": f"{code_prefix}_max_drawdown_red",
                "value": round(replay_max_drawdown_r, 4),
                "threshold": max_drawdown_r,
            }
        )
    if replay_p5_r < min_p5_r:
        breached_thresholds.append(
            {
                "code": f"{code_prefix}_p5_red",
                "value": round(replay_p5_r, 4),
                "threshold": min_p5_r,
            }
        )
    if stop_loss_share >= max_stop_loss_share:
        breached_thresholds.append(
            {
                "code": f"{code_prefix}_stop_loss_share_red",
                "value": round(stop_loss_share, 4),
                "threshold": max_stop_loss_share,
            }
        )
    if worst_loss_streak >= max_loss_streak:
        breached_thresholds.append(
            {
                "code": f"{code_prefix}_loss_streak_red",
                "value": worst_loss_streak,
                "threshold": max_loss_streak,
            }
        )
    return breached_thresholds


def _build_runtime_reopen_gate_summary(
    approval_template_focus: dict[str, Any] | None,
    runtime_decision: dict[str, Any] | None,
) -> dict[str, Any]:
    focus = dict(approval_template_focus or {})
    decision = dict(runtime_decision or {})
    post_patch, post_patch_source = _runtime_gate_post_patch_summary(focus)

    def _build_gate(
        *,
        label: str,
        min_closed_trades: int,
        max_drawdown_r: float,
        min_p5_r: float,
        max_stop_loss_share: float,
        max_loss_streak: int,
        code_prefix: str,
    ) -> dict[str, Any]:
        breaches = _build_post_patch_threshold_breaches(
            post_patch,
            min_closed_trades=min_closed_trades,
            max_drawdown_r=max_drawdown_r,
            min_p5_r=min_p5_r,
            max_stop_loss_share=max_stop_loss_share,
            max_loss_streak=max_loss_streak,
            code_prefix=code_prefix,
        )
        closed_trade_count = int(post_patch.get("closed_trade_count", 0) or 0)
        ready = bool(post_patch.get("ready_for_replay_refresh", False)) and not breaches
        remaining_to_min = max(int(min_closed_trades) - closed_trade_count, 0)
        summary = (
            f"{label} ready"
            if ready
            else f"{label} waiting on {', '.join(str(item.get('code') or 'unknown') for item in breaches) or 'post_patch_refresh'}"
        )
        return {
            "label": label,
            "status": osc.RUNTIME_REOPEN_GATE_STATUS_READY if ready else osc.RUNTIME_REOPEN_GATE_STATUS_NOT_READY,
            "source_summary_key": post_patch_source,
            "contract_scope": str(post_patch.get("contract_scope") or ""),
            "eligible_entry_models": list(post_patch.get("eligible_entry_models") or []),
            "closed_trade_count": closed_trade_count,
            "min_closed_trades": int(min_closed_trades),
            "remaining_to_min": remaining_to_min,
            "replay_max_drawdown_r": float(post_patch.get("replay_max_drawdown_r", 0.0) or 0.0),
            "replay_p5_r": float(post_patch.get("replay_p5_r", 0.0) or 0.0),
            "stop_loss_share": float(post_patch.get("stop_loss_share", 0.0) or 0.0),
            "worst_loss_streak": int(post_patch.get("worst_loss_streak", 0) or 0),
            "breached_thresholds": breaches,
            "summary": summary,
        }

    return {
        "active_scope": str(decision.get("allowed_reopen_scope") or ""),
        "effective_action": str(decision.get("effective_action") or ""),
        "micro_live": _build_gate(
            label="MICRO_LIVE",
            min_closed_trades=_LIVE_ELIGIBLE_MICRO_LIVE_MIN_CLOSED_TRADES,
            max_drawdown_r=_LIVE_ELIGIBLE_MICRO_LIVE_MAX_DRAWDOWN_R,
            min_p5_r=_LIVE_ELIGIBLE_MICRO_LIVE_MIN_P5_R,
            max_stop_loss_share=_LIVE_ELIGIBLE_MICRO_LIVE_MAX_STOP_LOSS_SHARE,
            max_loss_streak=_LIVE_ELIGIBLE_MICRO_LIVE_MAX_LOSS_STREAK,
            code_prefix="live_eligible_post_patch",
        ),
        "full_live": _build_gate(
            label="FULL_LIVE",
            min_closed_trades=_LIVE_ELIGIBLE_FULL_LIVE_MIN_CLOSED_TRADES,
            max_drawdown_r=_LIVE_ELIGIBLE_FULL_LIVE_MAX_DRAWDOWN_R,
            min_p5_r=_LIVE_ELIGIBLE_FULL_LIVE_MIN_P5_R,
            max_stop_loss_share=_LIVE_ELIGIBLE_FULL_LIVE_MAX_STOP_LOSS_SHARE,
            max_loss_streak=_LIVE_ELIGIBLE_FULL_LIVE_MAX_LOSS_STREAK,
            code_prefix="live_eligible_full_live",
        ),
    }


def _build_runtime_operator_signoff_summary(
    *,
    runtime_decision: dict[str, Any] | None,
    runtime_preflight_summary: dict[str, Any] | None,
    runtime_signoff_summary: dict[str, Any] | None,
    runtime_reopen_gate_summary: dict[str, Any] | None = None,
    base_url: str = "http://127.0.0.1:8000",
    symbol: str = "BTCUSDC",
    universe: str = "usdc_perp_top30",
    days: int = 30,
) -> dict[str, Any]:
    decision = dict(runtime_decision or {})
    preflight = dict(runtime_preflight_summary or {})
    signoff = dict(runtime_signoff_summary or {})
    gate = dict(runtime_reopen_gate_summary or {})
    settings = get_settings()
    action = str(decision.get("effective_action") or signoff.get("operator_recommendation") or "")
    scope = str(decision.get("allowed_reopen_scope") or osc.RUNTIME_DECISION_SCOPE_NONE)
    preflight_status = str(preflight.get("status") or "not_available")
    required_reviews = [dict(item) for item in list(signoff.get("required_reviews") or [])]
    required_review_codes = [str(item.get("code") or "") for item in required_reviews if str(item.get("code") or "")]
    review_command = str(
        preflight.get("command")
        or f"./.venv/bin/python scripts/run_micro_live_preflight.py --base-url {base_url} "
        f"--symbol {symbol.upper()} --universe {universe} --days {max(int(days), 1)} --no-write-report"
    )
    signoff_review_command = _runtime_signoff_command(symbol=symbol, universe=universe, days=days)
    active_gate = dict(
        gate.get("micro_live" if scope == osc.RUNTIME_DECISION_SCOPE_MICRO_LIVE_ONLY else "full_live")
        or gate.get("micro_live")
        or {}
    )
    contract_scope = str(active_gate.get("contract_scope") or "")
    allowed_symbols = _csv_items(getattr(settings, "auto_trading_micro_live_allowed_symbols", ""))
    priority_symbols = _csv_items(getattr(settings, "auto_trading_micro_live_symbol_priority", ""))
    allowed_direction_contract = _live_execution_direction_contract()
    allowed_direction_items = _direction_contract_summary_items(allowed_direction_contract)
    if allowed_symbols and priority_symbols:
        allowed_set = set(allowed_symbols)
        priority_symbols = [item for item in priority_symbols if item in allowed_set]
    allowed_families = _csv_items(getattr(settings, "auto_trading_micro_live_allowed_families", ""))
    allowed_sessions = _csv_items(getattr(settings, "auto_trading_micro_live_allowed_sessions", ""))
    intent_execution_mode = "MICRO_LIVE" if scope == osc.RUNTIME_DECISION_SCOPE_MICRO_LIVE_ONLY else "LIVE"
    intent_command_template = (
        f"curl -s -X POST \"{base_url.rstrip('/')}/execution/order-intents\" "
        "-H \"Content-Type: application/json\" "
        f"-d '{{\"plan_id\":\"<PLAN_ID>\",\"execution_mode\":\"{intent_execution_mode}\"}}' | jq"
    )
    submit_command_template = (
        f"curl -s -X POST \"{base_url.rstrip('/')}/execution/submit\" "
        "-H \"Content-Type: application/json\" "
        "-d '{\"intent_id\":\"<INTENT_ID>\",\"live\":true}' | jq"
    )
    requirement_bits = ["APPROVED_*"]
    if contract_scope:
        requirement_bits.append(contract_scope)
    if allowed_symbols:
        requirement_bits.append(f"symbols={','.join(allowed_symbols)}")
    if priority_symbols:
        requirement_bits.append(f"priority={'>'.join(priority_symbols)}")
    if allowed_families:
        requirement_bits.append(f"families={','.join(allowed_families)}")
    if allowed_direction_items:
        requirement_bits.append(f"directions={';'.join(allowed_direction_items)}")
    if allowed_sessions:
        requirement_bits.append(f"sessions={','.join(allowed_sessions)}")
    candidate_requirements_summary = (
        f"use only {' '.join(requirement_bits)} intents within {scope or 'the active reopen scope'}"
    )
    submit_path_summary = (
        f"APPROVED_* -> order-intents({intent_execution_mode}) -> submit(live=true"
        + (f", {contract_scope}" if contract_scope else "")
        + ")"
    )

    applicable_actions = {
        osc.RUNTIME_REOPEN_ACTION_CONDITIONAL_MICRO_LIVE_SIGNOFF,
        osc.RUNTIME_REOPEN_ACTION_CONDITIONAL_FULL_LIVE_SIGNOFF,
        osc.RUNTIME_REOPEN_ACTION_PROCEED_TO_OPERATOR_SIGNOFF,
    }
    if action not in applicable_actions:
        return {
            "active": False,
            "status": "not_applicable",
            "effective_action": action,
            "allowed_scope": scope,
            "preflight_status": preflight_status,
            "required_review_codes": required_review_codes,
            "review_command": review_command,
            "signoff_review_command": signoff_review_command,
            "intent_execution_mode": intent_execution_mode,
            "intent_command_template": intent_command_template,
            "submit_command_template": submit_command_template,
            "contract_scope": contract_scope,
            "allowed_symbols": allowed_symbols,
            "allowed_families": allowed_families,
            "allowed_direction_contract": {symbol: list(directions) for symbol, directions in allowed_direction_contract.items()},
            "allowed_sessions": allowed_sessions,
            "candidate_requirements_summary": candidate_requirements_summary,
            "submit_path_summary": submit_path_summary,
            "summary": "operator sign-off summary is only applicable once runtime enters a sign-off path",
            "next_step": osc.RUNTIME_OPERATOR_SIGNOFF_NEXT_STEP_WAIT_FOR_SIGNOFF_PATH,
        }

    if preflight_status != osc.MICRO_LIVE_PREFLIGHT_STATUS_READY:
        return {
            "active": True,
            "status": osc.RUNTIME_OPERATOR_SIGNOFF_STATUS_WAITING_FOR_PREFLIGHT,
            "effective_action": action,
            "allowed_scope": scope,
            "preflight_status": preflight_status,
            "required_review_codes": required_review_codes,
            "review_command": review_command,
            "signoff_review_command": signoff_review_command,
            "intent_execution_mode": intent_execution_mode,
            "intent_command_template": intent_command_template,
            "submit_command_template": submit_command_template,
            "contract_scope": contract_scope,
            "allowed_symbols": allowed_symbols,
            "allowed_families": allowed_families,
            "allowed_direction_contract": {symbol: list(directions) for symbol, directions in allowed_direction_contract.items()},
            "allowed_sessions": allowed_sessions,
            "candidate_requirements_summary": candidate_requirements_summary,
            "submit_path_summary": submit_path_summary,
            "summary": "runtime sign-off is waiting for MICRO_LIVE preflight to clear",
            "next_step": osc.RUNTIME_OPERATOR_SIGNOFF_NEXT_STEP_CLEAR_PREFLIGHT_FAILURES,
        }

    if action == osc.RUNTIME_REOPEN_ACTION_CONDITIONAL_MICRO_LIVE_SIGNOFF:
        return {
            "active": True,
            "status": osc.RUNTIME_OPERATOR_SIGNOFF_STATUS_READY_FOR_MANUAL_MICRO_LIVE_SIGNOFF,
            "effective_action": action,
            "allowed_scope": scope,
            "preflight_status": preflight_status,
            "required_review_codes": required_review_codes,
            "first_required_review_code": str(required_reviews[0].get("code") or "") if required_reviews else "",
            "review_command": review_command,
            "signoff_review_command": signoff_review_command,
            "intent_execution_mode": intent_execution_mode,
            "intent_command_template": intent_command_template,
            "submit_command_template": submit_command_template,
            "contract_scope": contract_scope,
            "allowed_symbols": allowed_symbols,
            "allowed_families": allowed_families,
            "allowed_direction_contract": {symbol: list(directions) for symbol, directions in allowed_direction_contract.items()},
            "allowed_sessions": allowed_sessions,
            "candidate_requirements_summary": candidate_requirements_summary,
            "submit_path_summary": submit_path_summary,
            "summary": "MICRO_LIVE preflight is green; operator may sign off MICRO_LIVE only",
            "next_step": osc.RUNTIME_OPERATOR_SIGNOFF_NEXT_STEP_REVIEW_AND_RECORD_MICRO,
        }

    if action == osc.RUNTIME_REOPEN_ACTION_CONDITIONAL_FULL_LIVE_SIGNOFF:
        return {
            "active": True,
            "status": osc.RUNTIME_OPERATOR_SIGNOFF_STATUS_READY_FOR_MANUAL_FULL_LIVE_SIGNOFF,
            "effective_action": action,
            "allowed_scope": scope,
            "preflight_status": preflight_status,
            "required_review_codes": required_review_codes,
            "first_required_review_code": str(required_reviews[0].get("code") or "") if required_reviews else "",
            "review_command": review_command,
            "signoff_review_command": signoff_review_command,
            "intent_execution_mode": intent_execution_mode,
            "intent_command_template": intent_command_template,
            "submit_command_template": submit_command_template,
            "contract_scope": contract_scope,
            "allowed_symbols": allowed_symbols,
            "allowed_families": allowed_families,
            "allowed_direction_contract": {symbol: list(directions) for symbol, directions in allowed_direction_contract.items()},
            "allowed_sessions": allowed_sessions,
            "candidate_requirements_summary": candidate_requirements_summary,
            "submit_path_summary": submit_path_summary,
            "summary": "FULL_LIVE preflight is green; operator may sign off FULL_LIVE scope",
            "next_step": osc.RUNTIME_OPERATOR_SIGNOFF_NEXT_STEP_REVIEW_AND_RECORD_FULL,
        }

    return {
        "active": True,
        "status": osc.RUNTIME_OPERATOR_SIGNOFF_STATUS_READY_FOR_OPERATOR_SIGNOFF,
        "effective_action": action,
        "allowed_scope": scope,
        "preflight_status": preflight_status,
        "required_review_codes": required_review_codes,
        "first_required_review_code": str(required_reviews[0].get("code") or "") if required_reviews else "",
        "review_command": review_command,
        "signoff_review_command": signoff_review_command,
        "intent_execution_mode": intent_execution_mode,
        "intent_command_template": intent_command_template,
        "submit_command_template": submit_command_template,
        "contract_scope": contract_scope,
        "allowed_symbols": allowed_symbols,
        "allowed_families": allowed_families,
        "allowed_direction_contract": {symbol: list(directions) for symbol, directions in allowed_direction_contract.items()},
        "allowed_sessions": allowed_sessions,
        "candidate_requirements_summary": candidate_requirements_summary,
        "submit_path_summary": submit_path_summary,
        "summary": "preflight is green and runtime may proceed to final operator sign-off",
        "next_step": osc.RUNTIME_OPERATOR_SIGNOFF_NEXT_STEP_RECORD_OPERATOR_SIGNOFF,
    }


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _csv_items(value: Any) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _read_stage(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"stage file does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"stage file is invalid: {path}")
    return payload


def _runtime_signoff_command(*, symbol: str, universe: str, days: int) -> str:
    return (
        f"./.venv/bin/python scripts/run_runtime_signoff_review.py "
        f"--symbol {symbol.upper()} --universe {universe} --days {max(int(days), 1)}"
    )


def _ensure_http_url(url: str) -> None:
    scheme = parse.urlparse(url).scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError(f"unsupported request URL scheme: {scheme or 'missing'}")


def _request_json(base_url: str, path: str, *, query: dict[str, Any]) -> dict[str, Any]:
    params = parse.urlencode({key: value for key, value in query.items() if value is not None})
    url = f"{base_url.rstrip('/')}{path}"
    if params:
        url = f"{url}?{params}"
    _ensure_http_url(url)
    try:
        with request.urlopen(url, timeout=30) as response:  # noqa: S310
            payload = json.load(response)
    except (error.URLError, TimeoutError, socket.timeout) as exc:
        raise RuntimeError(f"request failed for {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"non-object payload returned for {url}")
    return payload


def _is_retryable_request_error(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(
        token in lowered
        for token in (
            "http error 500",
            "internal server error",
            "database is locked",
            "sqlite busy",
            "timed out",
            "timeout",
            "remote end closed connection without response",
            "remotedisconnected",
        )
    )


def _request_json_with_retry(
    base_url: str,
    path: str,
    *,
    query: dict[str, Any],
    request_json_fn=_request_json,
    attempts: int = 3,
    sleep_seconds: float = 0.25,
) -> dict[str, Any]:
    last_error: RuntimeError | None = None
    for attempt in range(max(int(attempts), 1)):
        try:
            return request_json_fn(base_url, path, query=query)
        except Exception as exc:
            runtime_exc = exc if isinstance(exc, RuntimeError) else RuntimeError(
                f"request failed for {path}: {exc}"
            )
            last_error = runtime_exc
            if not _is_retryable_request_error(str(exc)) or attempt + 1 >= max(int(attempts), 1):
                raise runtime_exc from exc
            time.sleep(sleep_seconds * float(attempt + 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"request failed for {path}: exhausted retries without a response")


def _fallback_operator_recommendation(
    *,
    runtime_ready: bool,
    required_reviews: list[dict[str, Any]],
) -> tuple[str, str]:
    if not runtime_ready:
        return osc.RUNTIME_REOPEN_ACTION_WAIT_UNTIL_RUNTIME_READY, "runtime reopen status is not ready yet"
    approval_review = next(
        (item for item in required_reviews if str(item.get("code") or "") == "approval_template_review"),
        None,
    )
    if approval_review is not None and str(approval_review.get("worst_scenario_status") or "").upper() == "FAIL":
        return (
            osc.RUNTIME_REOPEN_ACTION_HOLD_RUNTIME_REOPEN,
            "replay-derived worst scenario still fails; keep runtime closed unless the operator explicitly accepts the risk",
        )
    if required_reviews:
        return osc.RUNTIME_REOPEN_ACTION_MANUAL_SIGNOFF_REQUIRED, "runtime is reopen-ready but required operator review items remain"
    return osc.RUNTIME_REOPEN_ACTION_PROCEED_TO_OPERATOR_SIGNOFF, "runtime is reopen-ready and no required operator review items remain"


def _runtime_signoff_eligible_status(value: Any) -> bool:
    return str(value or "").strip().lower() in osc.RUNTIME_REOPEN_ELIGIBLE_STATUSES


def _build_runtime_decision(
    *,
    runtime_ready: bool,
    required_reviews: list[dict[str, Any]],
    approval_template_focus: dict[str, Any] | None,
) -> dict[str, Any]:
    if not runtime_ready:
        return {
            "band": osc.RUNTIME_DECISION_BAND_GREY_WAIT,
            "effective_action": osc.RUNTIME_REOPEN_ACTION_WAIT_UNTIL_RUNTIME_READY,
            "allowed_reopen_scope": osc.RUNTIME_DECISION_SCOPE_NONE,
            "summary": "runtime is not ready yet; do not reopen",
            "breached_thresholds": [],
        }

    approval_review = next(
        (item for item in required_reviews if str(item.get("code") or "") == "approval_template_review"),
        None,
    )
    focus = dict(approval_template_focus or {})
    post_patch, post_patch_source = _runtime_gate_post_patch_summary(focus)
    downside = dict(focus.get("downside_profile") or {})
    breached_thresholds: list[dict[str, Any]] = []

    if approval_review is not None and str(approval_review.get("worst_scenario_status") or "").upper() == "FAIL":
        replay_max_drawdown_r = float(focus.get("replay_max_drawdown_r", 0.0) or 0.0)
        replay_p5_r = float(focus.get("replay_p5_r", 0.0) or 0.0)
        stop_loss_share = float(downside.get("stop_loss_share", 0.0) or 0.0)
        worst_loss_streak = int(downside.get("worst_loss_streak", 0) or 0)
        if replay_max_drawdown_r >= 8.0:
            breached_thresholds.append(
                {"code": "max_drawdown_red", "value": round(replay_max_drawdown_r, 4), "threshold": 8.0}
            )
        if replay_p5_r <= -1.0:
            breached_thresholds.append(
                {"code": "p5_red", "value": round(replay_p5_r, 4), "threshold": -1.0}
            )
        if stop_loss_share >= 0.5:
            breached_thresholds.append(
                {"code": "stop_loss_share_red", "value": round(stop_loss_share, 4), "threshold": 0.5}
            )
        if worst_loss_streak >= 7:
            breached_thresholds.append(
                {"code": "loss_streak_red", "value": worst_loss_streak, "threshold": 7}
            )

        if breached_thresholds:
            micro_live_post_patch_breaches = _build_post_patch_threshold_breaches(
                post_patch,
                min_closed_trades=_LIVE_ELIGIBLE_MICRO_LIVE_MIN_CLOSED_TRADES,
                max_drawdown_r=_LIVE_ELIGIBLE_MICRO_LIVE_MAX_DRAWDOWN_R,
                min_p5_r=_LIVE_ELIGIBLE_MICRO_LIVE_MIN_P5_R,
                max_stop_loss_share=_LIVE_ELIGIBLE_MICRO_LIVE_MAX_STOP_LOSS_SHARE,
                max_loss_streak=_LIVE_ELIGIBLE_MICRO_LIVE_MAX_LOSS_STREAK,
                code_prefix="live_eligible_post_patch",
            )
            full_live_post_patch_breaches = _build_post_patch_threshold_breaches(
                post_patch,
                min_closed_trades=_LIVE_ELIGIBLE_FULL_LIVE_MIN_CLOSED_TRADES,
                max_drawdown_r=_LIVE_ELIGIBLE_FULL_LIVE_MAX_DRAWDOWN_R,
                min_p5_r=_LIVE_ELIGIBLE_FULL_LIVE_MIN_P5_R,
                max_stop_loss_share=_LIVE_ELIGIBLE_FULL_LIVE_MAX_STOP_LOSS_SHARE,
                max_loss_streak=_LIVE_ELIGIBLE_FULL_LIVE_MAX_LOSS_STREAK,
                code_prefix="live_eligible_full_live",
            )
            if bool(post_patch.get("ready_for_replay_refresh", False)) and not full_live_post_patch_breaches:
                return {
                    "band": osc.RUNTIME_DECISION_BAND_AMBER_CONDITIONAL,
                    "effective_action": osc.RUNTIME_REOPEN_ACTION_CONDITIONAL_FULL_LIVE_SIGNOFF,
                    "allowed_reopen_scope": osc.RUNTIME_DECISION_SCOPE_MICRO_LIVE_OR_LIVE,
                    "summary": (
                        "legacy replay downside remains red, but the live-eligible post-patch cohort met the "
                        "conditional FULL LIVE thresholds"
                    ),
                    "breached_thresholds": breached_thresholds,
                    "post_patch_breached_thresholds": [],
                    "post_patch_override_active": True,
                    "post_patch_summary_key": post_patch_source,
                }
            if bool(post_patch.get("ready_for_replay_refresh", False)) and not micro_live_post_patch_breaches:
                return {
                    "band": osc.RUNTIME_DECISION_BAND_AMBER_CONDITIONAL,
                    "effective_action": osc.RUNTIME_REOPEN_ACTION_CONDITIONAL_MICRO_LIVE_SIGNOFF,
                    "allowed_reopen_scope": osc.RUNTIME_DECISION_SCOPE_MICRO_LIVE_ONLY,
                    "summary": (
                        "legacy replay downside remains red, but the live-eligible post-patch cohort met the "
                        "conditional MICRO_LIVE thresholds"
                    ),
                    "breached_thresholds": breached_thresholds,
                    "post_patch_breached_thresholds": [],
                    "post_patch_override_active": True,
                    "post_patch_summary_key": post_patch_source,
                }
            return {
                "band": osc.RUNTIME_DECISION_BAND_RED_HOLD,
                "effective_action": osc.RUNTIME_REOPEN_ACTION_HOLD_RUNTIME_REOPEN,
                "allowed_reopen_scope": osc.RUNTIME_DECISION_SCOPE_NONE,
                "summary": "replay downside exceeds operating tolerance; keep runtime closed",
                "breached_thresholds": breached_thresholds,
                "post_patch_breached_thresholds": micro_live_post_patch_breaches if bool(post_patch) else [],
                "post_patch_override_active": False,
                "post_patch_summary_key": post_patch_source,
            }
        return {
            "band": osc.RUNTIME_DECISION_BAND_AMBER_CONDITIONAL,
            "effective_action": osc.RUNTIME_REOPEN_ACTION_CONDITIONAL_MICRO_LIVE_SIGNOFF,
            "allowed_reopen_scope": osc.RUNTIME_DECISION_SCOPE_MICRO_LIVE_ONLY,
            "summary": "approval-template warning remains, but replay downside is below the red operating thresholds",
            "breached_thresholds": [],
            "post_patch_breached_thresholds": [],
            "post_patch_override_active": False,
            "post_patch_summary_key": post_patch_source,
        }

    if required_reviews:
        return {
            "band": osc.RUNTIME_DECISION_BAND_AMBER_CONDITIONAL,
            "effective_action": osc.RUNTIME_REOPEN_ACTION_MANUAL_SIGNOFF_REQUIRED,
            "allowed_reopen_scope": osc.RUNTIME_DECISION_SCOPE_MICRO_LIVE_ONLY,
            "summary": "runtime is reopen-ready but required operator review items remain",
            "breached_thresholds": [],
            "post_patch_breached_thresholds": [],
            "post_patch_override_active": False,
        }

    return {
        "band": osc.RUNTIME_DECISION_BAND_GREEN_PROCEED,
        "effective_action": osc.RUNTIME_REOPEN_ACTION_PROCEED_TO_OPERATOR_SIGNOFF,
        "allowed_reopen_scope": osc.RUNTIME_DECISION_SCOPE_MICRO_LIVE_OR_LIVE,
        "summary": "runtime is reopen-ready and no required operator review items remain",
        "breached_thresholds": [],
        "post_patch_breached_thresholds": [],
        "post_patch_override_active": False,
    }


def _apply_runtime_decision(payload: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(payload or {})
    runtime_reopen = dict(enriched.get("runtime_reopen_status") or {})
    required_reviews = [dict(item) for item in list(enriched.get("required_reviews") or [])]
    approval_template_focus = dict(enriched.get("approval_template_focus") or {})
    decision = _build_runtime_decision(
        runtime_ready=_runtime_signoff_eligible_status(runtime_reopen.get("status"))
        or bool(runtime_reopen.get("ready", False)),
        required_reviews=required_reviews,
        approval_template_focus=approval_template_focus,
    )
    enriched["runtime_decision"] = decision
    action = str(decision.get("effective_action") or "")
    if action:
        enriched["operator_recommendation"] = action
        if action == osc.RUNTIME_REOPEN_ACTION_CONDITIONAL_MICRO_LIVE_SIGNOFF:
            enriched["operator_recommendation_reason"] = (
                "legacy replay remains red, but the post-patch mitigation cohort cleared the red thresholds; "
                "limit any reopen to MICRO_LIVE while operator sign-off remains manual"
            )
        elif action == osc.RUNTIME_REOPEN_ACTION_CONDITIONAL_FULL_LIVE_SIGNOFF:
            enriched["operator_recommendation_reason"] = (
                "legacy replay remains red, but the post-patch mitigation cohort cleared the conditional FULL LIVE "
                "thresholds; any reopen still requires explicit operator sign-off"
            )
        elif action == osc.RUNTIME_REOPEN_ACTION_HOLD_RUNTIME_REOPEN:
            enriched["operator_recommendation_reason"] = "replay downside exceeds operating tolerance; keep runtime closed"
        elif action == osc.RUNTIME_REOPEN_ACTION_MANUAL_SIGNOFF_REQUIRED:
            enriched["operator_recommendation_reason"] = "runtime is reopen-ready but required operator review items remain"
        elif action == osc.RUNTIME_REOPEN_ACTION_PROCEED_TO_OPERATOR_SIGNOFF:
            enriched["operator_recommendation_reason"] = "runtime is reopen-ready and no required operator review items remain"
    enriched["runtime_reopen_gate_summary"] = _build_runtime_reopen_gate_summary(
        enriched.get("approval_template_focus"),
        enriched.get("runtime_decision"),
    )
    return enriched


def _approval_template_focus_symbol(stage: dict[str, Any], *, symbol: str) -> str:
    selected_trial_run_id = str(stage.get("selected_trial_run_id") or "")
    lineage_sample = dict(stage.get("lineage_sample_summary") or {})
    scope = str(lineage_sample.get("scope") or "")
    if selected_trial_run_id.startswith("LINEAGE_GLOBAL") or scope == "family_global":
        return "LINEAGE_GLOBAL"
    return symbol.upper()


def _load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _build_approval_template_downside_profile(*, artifact_path: str) -> dict[str, Any] | None:
    artifact_rel = str(artifact_path or "").strip()
    if not artifact_rel:
        return None
    artifact = _load_json_file(ROOT_DIR / artifact_rel)
    if not artifact:
        return None

    trade_rows = list(artifact.get("trade_rows") or [])
    if not trade_rows:
        return None

    plan_to_meta: dict[str, dict[str, Any]] = {}
    for path_str in list(artifact.get("input_artifact_paths") or []):
        batch = _load_json_file(ROOT_DIR / str(path_str))
        if not batch:
            continue
        for row in list(batch.get("trade_rows") or []):
            plan_to_meta[str(row.get("plan_id") or "")] = dict(row)

    total_trades = len(trade_rows)
    stop_loss_count = 0
    regime_counts: Counter[str] = Counter()
    loss_timestamp_counts: Counter[str] = Counter()
    long_hold_trade_count = 0
    long_hold_loss_count = 0
    current_loss_streak = 0
    worst_loss_streak = 0
    current_loss_block_sum = 0.0
    worst_loss_block_sum = 0.0
    worst_loss_block_len = 0
    negative_r_by_symbol: dict[str, float] = defaultdict(float)
    negative_trade_count_by_symbol: Counter[str] = Counter()
    entry_anchor_source_counts: Counter[str] = Counter()
    confirm_named_loss_count = 0
    loss_held_bars: list[int] = []

    for row in trade_rows:
        replayed_r = float(row.get("replayed_realized_r", 0.0) or 0.0)
        exit_reason = str(row.get("final_exit_reason") or "unknown")
        meta = dict(plan_to_meta.get(str(row.get("plan_id") or ""), {}) or {})
        symbol = str(meta.get("symbol") or "UNKNOWN")
        regime = str(meta.get("regime") or "unknown")
        held_bars = int(meta.get("final_exit_held_bars", 0) or 0)
        regime_counts[regime] += 1
        if held_bars > 240:
            long_hold_trade_count += 1
        if exit_reason == "stop_loss":
            stop_loss_count += 1
        if replayed_r < 0:
            current_loss_streak += 1
            current_loss_block_sum += replayed_r
            worst_loss_streak = max(worst_loss_streak, current_loss_streak)
            if current_loss_block_sum < worst_loss_block_sum:
                worst_loss_block_sum = current_loss_block_sum
                worst_loss_block_len = current_loss_streak
            negative_r_by_symbol[symbol] += replayed_r
            negative_trade_count_by_symbol[symbol] += 1
            loss_timestamp_counts[str(row.get("closed_ts") or "")] += 1
            entry_anchor_source_counts[str(meta.get("entry_anchor_source") or "unknown")] += 1
            if "confirm" in str(row.get("plan_id") or ""):
                confirm_named_loss_count += 1
            loss_held_bars.append(held_bars)
            if held_bars > 240:
                long_hold_loss_count += 1
        else:
            current_loss_streak = 0
            current_loss_block_sum = 0.0

    top_loss_symbols = [
        {
            "symbol": symbol,
            "negative_r": round(total_negative_r, 4),
            "loss_trade_count": int(negative_trade_count_by_symbol.get(symbol, 0) or 0),
        }
        for symbol, total_negative_r in sorted(negative_r_by_symbol.items(), key=lambda item: item[1])[:3]
    ]

    top_loss_waves = [
        {
            "closed_ts": closed_ts,
            "loss_trade_count": int(count or 0),
        }
        for closed_ts, count in loss_timestamp_counts.most_common(3)
    ]
    dominant_regime = regime_counts.most_common(1)[0][0] if regime_counts else "unknown"
    loss_trade_count = int(sum(negative_trade_count_by_symbol.values()) or 0)
    confirm_named_loss_share = round(float(confirm_named_loss_count) / float(loss_trade_count), 4) if loss_trade_count else 0.0
    top_loss_wave = dict(top_loss_waves[0] or {}) if top_loss_waves else {}
    top_loss_wave_count = int(top_loss_wave.get("loss_trade_count", 0) or 0)
    top_loss_wave_share_of_losses = round(
        float(top_loss_wave_count) / float(loss_trade_count),
        4,
    ) if loss_trade_count else 0.0
    long_hold_loss_share = round(float(long_hold_loss_count) / float(loss_trade_count), 4) if loss_trade_count else 0.0
    dominant_entry_anchor_source = entry_anchor_source_counts.most_common(1)[0][0] if entry_anchor_source_counts else "unknown"
    median_loss_held_bars = 0.0
    p75_loss_held_bars = 0
    max_loss_held_bars = 0
    if loss_held_bars:
        ordered_loss_held_bars = sorted(loss_held_bars)
        median_loss_held_bars = round(float(ordered_loss_held_bars[len(ordered_loss_held_bars) // 2]), 4)
        p75_loss_held_bars = int(ordered_loss_held_bars[int(0.75 * (len(ordered_loss_held_bars) - 1))] or 0)
        max_loss_held_bars = int(max(ordered_loss_held_bars) or 0)

    mitigation_focus: list[dict[str, Any]] = []
    if dominant_regime == "range" and stop_loss_count >= max(3, int(total_trades * 0.4)):
        mitigation_focus.append(
            {
                "code": "range_entry_timing_review",
                "summary": "range regime dominates the replay losses; review sweep_reversal entry timing before reopening runtime",
            }
        )
    if long_hold_loss_share >= 0.75:
        mitigation_focus.append(
            {
                "code": "shadow_fail_fast_review",
                "summary": "most replay losses are long-held stop-outs; prioritize fail_fast_no_reaction_within_3_bars as a shadow review",
            }
        )
    if top_loss_wave_share_of_losses >= 0.5:
        mitigation_focus.append(
            {
                "code": "loss_wave_cluster_review",
                "summary": "losses cluster in the same close wave; review cluster throttling and same-window exposure before reopening runtime",
            }
        )

    primary_failure_mode = "general_replay_drawdown"
    primary_failure_summary = "replay losses remain elevated and should be reviewed before reopening runtime"
    if (
        dominant_regime == "range"
        and long_hold_loss_share >= 0.75
        and top_loss_wave_share_of_losses >= 0.5
        and confirm_named_loss_share >= 0.7
    ):
        primary_failure_mode = "range_confirm_entry_loss_wave"
        primary_failure_summary = (
            "range regime losses are dominated by confirm-entry stop-outs that stay open too long and cluster in the same close wave"
        )
    elif dominant_regime == "range" and long_hold_loss_share >= 0.75 and top_loss_wave_share_of_losses >= 0.5:
        primary_failure_mode = "range_late_entry_loss_wave"
        primary_failure_summary = (
            "range regime losses are dominated by long-held stop-outs that cluster in the same close wave"
        )
    elif dominant_regime == "range" and long_hold_loss_share >= 0.75:
        primary_failure_mode = "range_long_hold_stopouts"
        primary_failure_summary = "range regime losses are dominated by long-held stop-outs"
    elif top_loss_wave_share_of_losses >= 0.5 and stop_loss_count >= max(2, int(total_trades * 0.4)):
        primary_failure_mode = "clustered_stop_loss_wave"
        primary_failure_summary = "losses cluster in the same wave and produce a long stop-loss streak"
    elif stop_loss_count >= max(3, int(total_trades * 0.5)):
        primary_failure_mode = "stop_loss_heavy_distribution"
        primary_failure_summary = "too many replay trades finish at stop-loss under the worst-case replay scenario"

    return {
        "trade_count": total_trades,
        "dominant_regime": dominant_regime,
        "stop_loss_count": stop_loss_count,
        "stop_loss_share": round(float(stop_loss_count) / float(total_trades), 4) if total_trades else 0.0,
        "loss_trade_count": loss_trade_count,
        "confirm_named_loss_count": confirm_named_loss_count,
        "confirm_named_loss_share": confirm_named_loss_share,
        "long_hold_trade_count": long_hold_trade_count,
        "long_hold_loss_count": long_hold_loss_count,
        "long_hold_loss_share": long_hold_loss_share,
        "median_loss_held_bars": median_loss_held_bars,
        "p75_loss_held_bars": p75_loss_held_bars,
        "max_loss_held_bars": max_loss_held_bars,
        "dominant_entry_anchor_source": dominant_entry_anchor_source,
        "worst_loss_streak": worst_loss_streak,
        "worst_loss_block_sum_r": round(worst_loss_block_sum, 4),
        "worst_loss_block_len": worst_loss_block_len,
        "top_loss_symbols": top_loss_symbols,
        "top_loss_waves": top_loss_waves,
        "top_loss_wave_share_of_losses": top_loss_wave_share_of_losses,
        "primary_failure_mode": primary_failure_mode,
        "primary_failure_summary": primary_failure_summary,
        "mitigation_focus": mitigation_focus,
    }


def _split_review_command(*, symbol: str, universe: str, days: int, action: str) -> str:
    return (
        f"./.venv/bin/python scripts/run_split_review_followup.py "
        f"--symbol {symbol.upper()} --universe {universe} --days {max(int(days), 1)} --action {action}"
    )


def _build_mitigation_review_summary(
    *,
    downside_profile: dict[str, Any] | None,
    stage: dict[str, Any],
    symbol: str,
    universe: str,
    days: int,
) -> dict[str, Any] | None:
    downside = dict(downside_profile or {})
    focus_items = list(downside.get("mitigation_focus") or [])
    if not focus_items:
        return None

    entry_target = dict(stage.get("entry_timing_review_target") or {})
    items: list[dict[str, Any]] = []
    for focus in focus_items:
        code = str(focus.get("code") or "").strip()
        summary = str(focus.get("summary") or "").strip()
        item: dict[str, Any] = {
            "code": code,
            "summary": summary,
            "review_mode": osc.MITIGATION_ACTION_STATUS_RESEARCH_ONLY,
            "status": osc.MITIGATION_ACTION_STATUS_RESEARCH_ONLY,
            "current_constraint": "",
            "command": "",
        }
        if code == "range_entry_timing_review":
            command = str(entry_target.get("followup_command") or "").strip() or _split_review_command(
                symbol=symbol,
                universe=universe,
                days=days,
                action="run_entry_timing_split_review",
            )
            has_target = bool(entry_target.get("symbol"))
            item.update(
                {
                    "review_mode": "live_split_review",
                    "status": (
                        osc.MITIGATION_ACTION_STATUS_ACTIONABLE_NOW
                        if has_target
                        else osc.MITIGATION_ACTION_STATUS_CANDIDATE_REVIEW_PENDING
                    ),
                    "current_constraint": "" if has_target else osc.MITIGATION_WAIT_CONSTRAINT_ENTRY_TIMING_TARGET,
                    "command": command,
                }
            )
        elif code == "shadow_fail_fast_review":
            item.update(
                {
                    "review_mode": "shadow_only",
                    "status": osc.MITIGATION_ACTION_STATUS_DEFERRED,
                    "current_constraint": "exit_optimization_live_change_not_allowed",
                    "shadow_hypothesis": "fail_fast_no_reaction_within_3_bars",
                }
            )
        elif code == "loss_wave_cluster_review":
            item.update(
                {
                    "review_mode": osc.MITIGATION_ACTION_STATUS_RESEARCH_ONLY,
                    "status": osc.MITIGATION_ACTION_STATUS_MANUAL_REVIEW,
                    "current_constraint": "operator_review_before_cluster_policy_change",
                    "command": _runtime_signoff_command(symbol=symbol, universe=universe, days=days),
                }
            )
        items.append(item)

    primary = next(
        (
            item
            for item in items
            if str(item.get("status") or "") in {
                osc.MITIGATION_ACTION_STATUS_ACTIONABLE_NOW,
                osc.MITIGATION_ACTION_STATUS_CANDIDATE_REVIEW_PENDING,
            }
        ),
        items[0],
    )
    return {
        "primary_action_code": str(primary.get("code") or ""),
        "primary_action_status": str(primary.get("status") or ""),
        "primary_action_command": str(primary.get("command") or ""),
        "actionable_now_count": sum(
            1 for item in items if str(item.get("status") or "") == osc.MITIGATION_ACTION_STATUS_ACTIONABLE_NOW
        ),
        "candidate_pending_count": sum(
            1
            for item in items
            if str(item.get("status") or "") == osc.MITIGATION_ACTION_STATUS_CANDIDATE_REVIEW_PENDING
        ),
        "deferred_count": sum(
            1 for item in items if str(item.get("status") or "") == osc.MITIGATION_ACTION_STATUS_DEFERRED
        ),
        "research_only_count": sum(
            1
            for item in items
            if str(item.get("status") or "") in {
                osc.MITIGATION_ACTION_STATUS_RESEARCH_ONLY,
                osc.MITIGATION_ACTION_STATUS_MANUAL_REVIEW,
            }
        ),
        "items": items,
    }


def _build_mitigation_execution_plan(
    *,
    priority_summary: dict[str, Any] | None,
    mitigation_review_summary: dict[str, Any] | None,
) -> dict[str, Any] | None:
    priority = dict(priority_summary or {})
    review_summary = dict(mitigation_review_summary or {})
    items = list(review_summary.get("items") or [])
    if not priority or not items:
        return None

    item_by_code = {str(item.get("code") or ""): dict(item) for item in items}
    review_code_map = {
        "confirm_entry_tighten": "range_entry_timing_review",
        "non_confirm_fail_fast": "shadow_fail_fast_review",
        "confirm_fail_fast": "shadow_fail_fast_review",
        "loss_wave_cluster": "loss_wave_cluster_review",
    }
    label_map = {
        "confirm_entry_tighten": "confirm 진입 타이밍 축소",
        "non_confirm_fail_fast": "non-confirm fail-fast",
        "confirm_fail_fast": "confirm fail-fast",
        "loss_wave_cluster": "loss wave cluster 검토",
    }

    ordered_steps: list[dict[str, Any]] = []
    for step_code in list(priority.get("ordered_focus") or []):
        mapped_code = str(review_code_map.get(str(step_code), "") or "")
        item = dict(item_by_code.get(mapped_code) or {})
        if not item:
            continue
        ordered_steps.append(
            {
                "focus_code": str(step_code),
                "focus_label": str(label_map.get(str(step_code), step_code)),
                "review_code": mapped_code,
                "review_mode": str(item.get("review_mode") or ""),
                "status": str(item.get("status") or ""),
                "command": str(item.get("command") or ""),
                "constraint": str(item.get("current_constraint") or ""),
            }
        )

    if not ordered_steps:
        return None

    primary_step = dict(ordered_steps[0])
    secondary_step = dict(ordered_steps[1]) if len(ordered_steps) > 1 else {}
    return {
        "primary_focus_code": str(primary_step.get("focus_code") or ""),
        "primary_focus_label": str(primary_step.get("focus_label") or ""),
        "primary_status": str(primary_step.get("status") or ""),
        "primary_command": str(primary_step.get("command") or ""),
        "secondary_focus_code": str(secondary_step.get("focus_code") or ""),
        "secondary_focus_label": str(secondary_step.get("focus_label") or ""),
        "secondary_status": str(secondary_step.get("status") or ""),
        "secondary_command": str(secondary_step.get("command") or ""),
        "ordered_steps": ordered_steps,
    }


def _build_confirm_loss_cluster_summary(
    *,
    artifact_path: str,
) -> dict[str, Any] | None:
    artifact_rel = str(artifact_path or "").strip()
    if not artifact_rel:
        return None
    artifact = _load_json_file(ROOT_DIR / artifact_rel)
    if not artifact:
        return None

    plan_to_meta: dict[str, dict[str, Any]] = {}
    for path_str in list(artifact.get("input_artifact_paths") or []):
        batch = _load_json_file(ROOT_DIR / str(path_str))
        if not batch:
            continue
        for row in list(batch.get("trade_rows") or []):
            plan_to_meta[str(row.get("plan_id") or "")] = dict(row)

    confirm_losses: list[dict[str, Any]] = []
    for row in list(artifact.get("trade_rows") or []):
        replayed_r = float(row.get("replayed_realized_r", 0.0) or 0.0)
        plan_id = str(row.get("plan_id") or "")
        if replayed_r >= 0 or "confirm" not in plan_id:
            continue
        meta = dict(plan_to_meta.get(plan_id, {}) or {})
        confirm_losses.append({**meta, **dict(row)})

    if not confirm_losses:
        return None

    symbol_counts: Counter[str] = Counter()
    symbol_negative_r: defaultdict[str, float] = defaultdict(float)
    closed_ts_counts: Counter[str] = Counter()
    wave_negative_r: defaultdict[str, float] = defaultdict(float)
    held_bars_values: list[int] = []
    symbol_held_bars: defaultdict[str, list[int]] = defaultdict(list)
    wave_symbols: defaultdict[str, Counter[str]] = defaultdict(Counter)
    held_bar_bands = {
        "over_240": 0,
        "over_1000": 0,
        "over_2000": 0,
    }
    for row in confirm_losses:
        symbol = str(row.get("symbol") or "UNKNOWN")
        replayed_r = float(row.get("replayed_realized_r", 0.0) or 0.0)
        closed_ts = str(row.get("closed_ts") or "")
        held_bars = int(row.get("final_exit_held_bars", 0) or 0)
        symbol_counts[symbol] += 1
        symbol_negative_r[symbol] += replayed_r
        closed_ts_counts[closed_ts] += 1
        wave_negative_r[closed_ts] += replayed_r
        held_bars_values.append(held_bars)
        symbol_held_bars[symbol].append(held_bars)
        wave_symbols[closed_ts][symbol] += 1
        if held_bars > 240:
            held_bar_bands["over_240"] += 1
        if held_bars > 1000:
            held_bar_bands["over_1000"] += 1
        if held_bars > 2000:
            held_bar_bands["over_2000"] += 1

    def _median(values: list[int]) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        return round(float(ordered[len(ordered) // 2]), 4)

    def _p75(values: list[int]) -> int:
        if not values:
            return 0
        ordered = sorted(values)
        return int(ordered[int(0.75 * (len(ordered) - 1))] or 0)

    top_symbols = [
        {
            "symbol": symbol,
            "loss_trade_count": int(symbol_counts.get(symbol, 0) or 0),
            "negative_r": round(symbol_negative_r.get(symbol, 0.0), 4),
            "median_held_bars": _median(symbol_held_bars.get(symbol, [])),
            "p75_held_bars": _p75(symbol_held_bars.get(symbol, [])),
        }
        for symbol, _ in symbol_counts.most_common(5)
    ]
    top_waves = [
        {
            "closed_ts": closed_ts,
            "loss_trade_count": int(count or 0),
            "negative_r": round(wave_negative_r.get(closed_ts, 0.0), 4),
            "top_symbols": [
                {"symbol": symbol, "loss_trade_count": int(symbol_count or 0)}
                for symbol, symbol_count in wave_symbols.get(closed_ts, Counter()).most_common(3)
            ],
        }
        for closed_ts, count in closed_ts_counts.most_common(3)
    ]
    held_sorted = sorted(held_bars_values)
    median_held_bars = _median(held_sorted)
    p75_held_bars = _p75(held_sorted)
    review_priority = [
        {
            "symbol": item["symbol"],
            "negative_r": item["negative_r"],
            "loss_trade_count": item["loss_trade_count"],
            "median_held_bars": item["median_held_bars"],
        }
        for item in top_symbols[:3]
    ]

    return {
        "loss_trade_count": len(confirm_losses),
        "median_held_bars": median_held_bars,
        "p75_held_bars": p75_held_bars,
        "held_bar_bands": held_bar_bands,
        "top_symbols": top_symbols,
        "top_waves": top_waves,
        "review_priority": review_priority,
    }


def _build_entry_timing_loss_profile(
    *,
    artifact_path: str,
) -> dict[str, Any] | None:
    artifact_rel = str(artifact_path or "").strip()
    if not artifact_rel:
        return None
    artifact = _load_json_file(ROOT_DIR / artifact_rel)
    if not artifact:
        return None

    plan_to_meta: dict[str, dict[str, Any]] = {}
    for path_str in list(artifact.get("input_artifact_paths") or []):
        batch = _load_json_file(ROOT_DIR / str(path_str))
        if not batch:
            continue
        for row in list(batch.get("trade_rows") or []):
            plan_to_meta[str(row.get("plan_id") or "")] = dict(row)

    losses = [
        {**dict(plan_to_meta.get(str(row.get("plan_id") or ""), {}) or {}), **dict(row)}
        for row in list(artifact.get("trade_rows") or [])
        if float(row.get("replayed_realized_r", 0.0) or 0.0) < 0
    ]
    if not losses:
        return None

    def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        held = sorted(int(row.get("final_exit_held_bars", 0) or 0) for row in rows)
        loss_by_symbol: defaultdict[str, float] = defaultdict(float)
        count_by_symbol: Counter[str] = Counter()
        total_negative_r = 0.0
        for row in rows:
            symbol = str(row.get("symbol") or "UNKNOWN")
            replayed_r = float(row.get("replayed_realized_r", 0.0) or 0.0)
            total_negative_r += replayed_r
            loss_by_symbol[symbol] += replayed_r
            count_by_symbol[symbol] += 1
        return {
            "loss_trade_count": len(rows),
            "negative_r": round(total_negative_r, 4),
            "median_held_bars": round(float(held[len(held) // 2]), 4) if held else 0.0,
            "p75_held_bars": int(held[int(0.75 * (len(held) - 1))] or 0) if held else 0,
            "top_symbols": [
                {
                    "symbol": symbol,
                    "loss_trade_count": int(count_by_symbol.get(symbol, 0) or 0),
                    "negative_r": round(loss_by_symbol.get(symbol, 0.0), 4),
                }
                for symbol, _ in sorted(loss_by_symbol.items(), key=lambda item: item[1])[:3]
            ],
        }

    confirm_losses = [row for row in losses if "confirm" in str(row.get("plan_id") or "")]
    non_confirm_losses = [row for row in losses if "confirm" not in str(row.get("plan_id") or "")]
    confirm_summary = _summarize(confirm_losses) if confirm_losses else {}
    non_confirm_summary = _summarize(non_confirm_losses) if non_confirm_losses else {}
    total_negative_r = abs(sum(float(row.get("replayed_realized_r", 0.0) or 0.0) for row in losses))
    confirm_negative_r = abs(float(confirm_summary.get("negative_r", 0.0) or 0.0))
    confirm_share = round(float(len(confirm_losses)) / float(len(losses)), 4) if losses else 0.0
    confirm_negative_share = round(confirm_negative_r / total_negative_r, 4) if total_negative_r else 0.0
    confirm_median = float(confirm_summary.get("median_held_bars", 0.0) or 0.0)
    non_confirm_median = float(non_confirm_summary.get("median_held_bars", 0.0) or 0.0)
    held_bar_gap = round(confirm_median - non_confirm_median, 4)
    dominant_loss_cohort = "confirm" if confirm_share >= 0.5 else "non_confirm"

    if dominant_loss_cohort == "confirm" and held_bar_gap >= 0:
        summary = "confirm losses dominate and hold longer"
    elif dominant_loss_cohort == "confirm":
        summary = "confirm losses dominate, but non-confirm losses hold longer"
    elif held_bar_gap >= 0:
        summary = "non-confirm losses dominate, but confirm losses hold longer"
    else:
        summary = "non-confirm losses dominate and hold longer"

    return {
        "loss_trade_count": len(losses),
        "dominant_loss_cohort": dominant_loss_cohort,
        "confirm_loss_share": confirm_share,
        "confirm_negative_r_share": confirm_negative_share,
        "held_bar_gap_confirm_minus_non_confirm": held_bar_gap,
        "confirm": confirm_summary,
        "non_confirm": non_confirm_summary,
        "summary": summary,
    }


def _build_entry_timing_priority_summary(
    profile: dict[str, Any] | None,
) -> dict[str, Any] | None:
    source = dict(profile or {})
    if not source:
        return None

    confirm_share = float(source.get("confirm_loss_share", 0.0) or 0.0)
    confirm_negative_share = float(source.get("confirm_negative_r_share", 0.0) or 0.0)
    held_gap = float(source.get("held_bar_gap_confirm_minus_non_confirm", 0.0) or 0.0)
    confirm = dict(source.get("confirm") or {})
    non_confirm = dict(source.get("non_confirm") or {})

    if confirm_share >= 0.7 or confirm_negative_share >= 0.7:
        primary_focus_code = "confirm_entry_tighten"
        primary_summary = "confirm 손실 비중이 높아 range confirm-entry를 먼저 줄여야 함"
    else:
        primary_focus_code = "non_confirm_fail_fast"
        primary_summary = "non-confirm 손실 비중이 커서 fail-fast 쪽을 먼저 봐야 함"

    if held_gap <= -240 and int(non_confirm.get("loss_trade_count", 0) or 0) > 0:
        secondary_focus_code = "non_confirm_fail_fast"
        secondary_summary = "non-confirm 손실은 수는 적지만 더 오래 끌려서 fail-fast shadow 검토가 필요함"
    elif held_gap >= 240 and int(confirm.get("loss_trade_count", 0) or 0) > 0:
        secondary_focus_code = "confirm_fail_fast"
        secondary_summary = "confirm 손실도 오래 끌리는 편이라 confirm fail-fast shadow 검토가 필요함"
    else:
        secondary_focus_code = "loss_wave_cluster"
        secondary_summary = "보유시간 차이보다 손실 파동 동시성이 더 크므로 cluster 검토를 우선 유지"

    ordered_focus = [primary_focus_code]
    if secondary_focus_code != primary_focus_code:
        ordered_focus.append(secondary_focus_code)

    return {
        "primary_focus_code": primary_focus_code,
        "primary_summary": primary_summary,
        "secondary_focus_code": secondary_focus_code,
        "secondary_summary": secondary_summary,
        "ordered_focus": ordered_focus,
    }


def _build_post_patch_sample_summary(
    *,
    focus_symbol: str,
    artifact_path: str,
    baseline_ts: datetime | None = None,
    target_closed_trades: int = _POST_PATCH_SAMPLE_GOAL,
    previous_summary: dict[str, Any] | None = None,
    previous_artifact_path: str = "",
    eligible_entry_models: tuple[str, ...] | None = None,
    eligible_symbols: tuple[str, ...] | None = None,
    eligible_families: tuple[str, ...] | None = None,
    eligible_direction_contract: dict[str, tuple[str, ...]] | None = None,
    contract_scope: str = "",
    summary_label: str = "post-patch sample",
) -> dict[str, Any] | None:
    artifact_rel = str(artifact_path or "").strip()
    if not artifact_rel:
        return None

    cutoff = baseline_ts or _parse_ts(_POST_PATCH_BASELINE_TEXT)
    if cutoff is None:
        return None

    replay_rows = _load_post_patch_rows_from_artifact(artifact_rel, cutoff=cutoff)
    if replay_rows is None:
        return None
    replay_rows = _filter_post_patch_rows_by_family(replay_rows, eligible_families)
    replay_rows = _filter_post_patch_rows_by_entry_model(replay_rows, eligible_entry_models)
    replay_rows = _filter_post_patch_rows_by_symbol(replay_rows, eligible_symbols)
    replay_rows = _filter_post_patch_rows_by_direction_contract(replay_rows, eligible_direction_contract)
    lineage_rows = _load_post_patch_rows_from_lineage(focus_symbol=focus_symbol, cutoff=cutoff)
    lineage_rows = _filter_post_patch_rows_by_family(lineage_rows, eligible_families)
    lineage_rows = _filter_post_patch_rows_by_entry_model(lineage_rows, eligible_entry_models)
    lineage_rows = _filter_post_patch_rows_by_symbol(lineage_rows, eligible_symbols)
    lineage_rows = _filter_post_patch_rows_by_direction_contract(lineage_rows, eligible_direction_contract)
    lineage_by_plan_id = {
        str(row.get("plan_id") or ""): dict(row)
        for row in list(lineage_rows or [])
        if str(row.get("plan_id") or "").strip()
    }
    replay_by_plan_id = {
        str(row.get("plan_id") or ""): dict(row)
        for row in list(replay_rows or [])
        if str(row.get("plan_id") or "").strip()
    }
    merged_cohort_by_plan_id = dict(replay_by_plan_id)
    merged_cohort_by_plan_id.update(lineage_by_plan_id)
    cohort_rows = sorted(
        merged_cohort_by_plan_id.values(),
        key=lambda row: (_parse_ts(row.get("closed_ts")) or datetime.min.replace(tzinfo=UTC), str(row.get("plan_id") or "")),
    )

    replay_cohort_by_plan_id = {
        str(row.get("plan_id") or ""): dict(row)
        for row in replay_rows
        if str(row.get("plan_id") or "").strip()
    }
    sticky_reused_plan_ids: list[str] = []
    sticky_source_artifact_path = str(previous_artifact_path or "").strip()
    if sticky_source_artifact_path == artifact_rel:
        sticky_source_artifact_path = ""
    previous_summary_map = dict(previous_summary or {})
    previous_baseline = _parse_ts(previous_summary_map.get("baseline_ts"))
    previous_ids = [
        str(plan_id).strip()
        for plan_id in list(previous_summary_map.get("cohort_plan_ids") or [])
        if str(plan_id).strip()
    ]
    if str(previous_artifact_path or "").strip() == artifact_rel:
        previous_ids = []
    if previous_baseline is not None and previous_baseline != cutoff:
        previous_ids = []
        sticky_source_artifact_path = ""
    candidate_artifact_paths: list[str] = []
    if sticky_source_artifact_path:
        candidate_artifact_paths.append(sticky_source_artifact_path)
    if not previous_ids:
        candidate_artifact_paths.extend(_list_previous_replay_artifact_paths(artifact_rel, limit=96))
    seen_candidate_paths: set[str] = set()
    for candidate_artifact_path in candidate_artifact_paths:
        candidate_rel = str(candidate_artifact_path or "").strip()
        if not candidate_rel or candidate_rel == artifact_rel or candidate_rel in seen_candidate_paths:
            continue
        seen_candidate_paths.add(candidate_rel)
        previous_rows = _filter_post_patch_rows_by_entry_model(
            _filter_post_patch_rows_by_family(
                _load_post_patch_rows_from_artifact(candidate_rel, cutoff=cutoff) or [],
                eligible_families,
            ),
            eligible_entry_models,
        )
        previous_rows = _filter_post_patch_rows_by_symbol(previous_rows, eligible_symbols)
        previous_rows = _filter_post_patch_rows_by_direction_contract(previous_rows, eligible_direction_contract)
        previous_by_plan_id = {
            str(row.get("plan_id") or ""): dict(row)
            for row in previous_rows
            if str(row.get("plan_id") or "").strip()
        }
        plan_ids_to_check = previous_ids or list(previous_by_plan_id.keys())
        reused_before = len(sticky_reused_plan_ids)
        for plan_id in plan_ids_to_check:
            if not plan_id or plan_id in replay_cohort_by_plan_id:
                continue
            sticky_row = dict(previous_by_plan_id.get(plan_id) or {})
            if not sticky_row:
                continue
            replay_cohort_by_plan_id[plan_id] = sticky_row
            sticky_reused_plan_ids.append(plan_id)
        if len(sticky_reused_plan_ids) > reused_before:
            sticky_source_artifact_path = candidate_rel
            if not previous_ids:
                break
    replay_rows = sorted(
        replay_cohort_by_plan_id.values(),
        key=lambda row: (_parse_ts(row.get("closed_ts")) or datetime.min.replace(tzinfo=UTC), str(row.get("plan_id") or "")),
    )
    merged_cohort_with_sticky = dict(merged_cohort_by_plan_id)
    for plan_id, row in replay_cohort_by_plan_id.items():
        if plan_id not in merged_cohort_with_sticky:
            merged_cohort_with_sticky[plan_id] = dict(row)
    cohort_rows = sorted(
        merged_cohort_with_sticky.values(),
        key=lambda row: (_parse_ts(row.get("closed_ts")) or datetime.min.replace(tzinfo=UTC), str(row.get("plan_id") or "")),
    )

    return _summarize_contract_sample_rows(
        cohort_rows=cohort_rows,
        replay_rows=replay_rows,
        cutoff=cutoff,
        target_closed_trades=target_closed_trades,
        contract_scope=contract_scope,
        eligible_entry_models=eligible_entry_models,
        eligible_symbols=eligible_symbols,
        eligible_families=eligible_families,
        eligible_direction_contract=eligible_direction_contract,
        summary_label=summary_label,
        sticky_reused_plan_ids=sticky_reused_plan_ids,
        sticky_source_artifact_path=sticky_source_artifact_path,
    )


def _summarize_contract_sample_rows(
    *,
    cohort_rows: list[dict[str, Any]] | None,
    replay_rows: list[dict[str, Any]] | None,
    cutoff: datetime,
    target_closed_trades: int,
    contract_scope: str,
    eligible_entry_models: tuple[str, ...] | None,
    eligible_symbols: tuple[str, ...] | None,
    eligible_families: tuple[str, ...] | None,
    eligible_direction_contract: dict[str, tuple[str, ...]] | None,
    summary_label: str,
    sticky_reused_plan_ids: list[str] | None = None,
    sticky_source_artifact_path: str = "",
    advisory_only: bool = False,
    evidence_basis: str = "",
    lookback_days: int | None = None,
) -> dict[str, Any]:
    cohort_by_plan_id = {
        str(row.get("plan_id") or ""): dict(row)
        for row in list(cohort_rows or [])
        if str(row.get("plan_id") or "").strip()
    }
    replay_by_plan_id = {
        str(row.get("plan_id") or ""): dict(row)
        for row in list(replay_rows or [])
        if str(row.get("plan_id") or "").strip()
    }
    cohort_rows_sorted = sorted(
        cohort_by_plan_id.values(),
        key=lambda row: (_parse_ts(row.get("closed_ts")) or datetime.min.replace(tzinfo=UTC), str(row.get("plan_id") or "")),
    )
    replay_rows_sorted = sorted(
        replay_by_plan_id.values(),
        key=lambda row: (_parse_ts(row.get("closed_ts")) or datetime.min.replace(tzinfo=UTC), str(row.get("plan_id") or "")),
    )
    sticky_ids = [str(item).strip() for item in list(sticky_reused_plan_ids or []) if str(item).strip()]

    if not cohort_rows_sorted:
        summary = f"{summary_label} 0/{int(target_closed_trades)}; waiting for new closes"
        if advisory_only and lookback_days is not None:
            summary = (
                f"{summary_label} 0/{int(target_closed_trades)}; "
                f"waiting for historical closes over the last {int(lookback_days)}d"
            )
        return {
            "baseline_ts": cutoff.isoformat(),
            "target_closed_trades": int(target_closed_trades),
            "closed_trade_count": 0,
            "count_basis": "distinct_plan_ids",
            "remaining_to_target": int(target_closed_trades),
            "ready_for_replay_refresh": False,
            "confirm_named_loss_share": 0.0,
            "stop_loss_share": 0.0,
            "median_held_bars": 0.0,
            "top_symbols": [],
            "cohort_plan_ids": [],
            "sticky_reused_plan_ids": sticky_ids,
            "sticky_reused_plan_count": int(len(sticky_ids)),
            "sticky_source_artifact_path": sticky_source_artifact_path,
            "replay_trade_row_count": int(len(replay_rows_sorted)),
            "contract_scope": contract_scope,
            "eligible_entry_models": list(eligible_entry_models or []),
            "eligible_symbols": list(eligible_symbols or []),
            "eligible_families": list(eligible_families or []),
            "eligible_direction_contract": {
                symbol: list(directions)
                for symbol, directions in dict(eligible_direction_contract or {}).items()
            },
            "advisory_only": advisory_only,
            "evidence_basis": str(evidence_basis or ""),
            "lookback_days": int(lookback_days) if lookback_days is not None else None,
            "summary": summary,
        }

    total = len(cohort_rows_sorted)
    stop_loss_count = 0
    confirm_loss_count = 0
    loss_held_bars: list[int] = []
    symbol_counts: Counter[str] = Counter()
    replay_rs: list[float] = []
    cohort_rs: list[float] = []
    current_loss_streak = 0
    worst_loss_streak = 0
    for row in cohort_rows_sorted:
        plan_id = str(row.get("plan_id") or "")
        exit_reason = str(row.get("final_exit_reason") or "")
        replayed_r = float(row.get("replayed_realized_r", 0.0) or 0.0)
        held_bars = int(row.get("final_exit_held_bars", 0) or 0)
        cohort_rs.append(replayed_r)
        symbol_counts[str(row.get("symbol") or "UNKNOWN")] += 1
        if exit_reason == "stop_loss":
            stop_loss_count += 1
        if replayed_r < 0 and "confirm" in plan_id:
            confirm_loss_count += 1
        if replayed_r < 0:
            loss_held_bars.append(held_bars)
            current_loss_streak += 1
            worst_loss_streak = max(worst_loss_streak, current_loss_streak)
        else:
            current_loss_streak = 0

    for row in replay_rows_sorted:
        replay_rs.append(float(row.get("replayed_realized_r", row.get("final_exit_realized_r", 0.0)) or 0.0))

    remaining = max(int(target_closed_trades) - total, 0)
    median_held_bars = 0.0
    if loss_held_bars:
        ordered = sorted(loss_held_bars)
        median_held_bars = round(float(ordered[len(ordered) // 2]), 4)
    top_symbols = [
        {"symbol": symbol, "trade_count": int(count or 0)}
        for symbol, count in symbol_counts.most_common(3)
    ]
    confirm_share = round(float(confirm_loss_count) / float(max(len(loss_held_bars), 1)), 4) if loss_held_bars else 0.0
    stop_loss_share = round(float(stop_loss_count) / float(total), 4) if total else 0.0
    replay_max_drawdown_r = round(_max_drawdown(replay_rs), 4) if replay_rs else 0.0
    replay_p5_r = round(_percentile(replay_rs, 0.05), 4) if replay_rs else 0.0
    winning_trade_count = sum(1 for value in cohort_rs if value > 0)
    losing_trade_count = sum(1 for value in cohort_rs if value < 0)
    win_rate = round(float(winning_trade_count) / float(total), 4) if total else 0.0
    total_realized_r = round(sum(cohort_rs), 4) if cohort_rs else 0.0
    ev_r = round(float(total_realized_r) / float(total), 4) if total else 0.0
    gross_win_r = round(sum(value for value in cohort_rs if value > 0), 4) if cohort_rs else 0.0
    gross_loss_r = round(abs(sum(value for value in cohort_rs if value < 0)), 4) if cohort_rs else 0.0
    profit_factor = round(gross_win_r / gross_loss_r, 4) if gross_loss_r > 0 else None
    summary = (
        f"{summary_label} {total}/{int(target_closed_trades)}"
        f" distinct_plans"
        f" | win_rate={win_rate:.0%}"
        f" | ev={ev_r:+.2f}R"
        f" | stop_loss={stop_loss_share:.0%}"
        f" | confirm_loss={confirm_share:.0%}"
    )
    if advisory_only and lookback_days is not None:
        summary += f" | advisory_only | lookback={int(lookback_days)}d"
    return {
        "baseline_ts": cutoff.isoformat(),
        "target_closed_trades": int(target_closed_trades),
        "closed_trade_count": int(total),
        "count_basis": "distinct_plan_ids",
        "remaining_to_target": int(remaining),
        "ready_for_replay_refresh": remaining == 0,
        "confirm_named_loss_share": confirm_share,
        "stop_loss_share": stop_loss_share,
        "median_held_bars": median_held_bars,
        "replay_max_drawdown_r": replay_max_drawdown_r,
        "replay_p5_r": replay_p5_r,
        "worst_loss_streak": int(worst_loss_streak),
        "winning_trade_count": int(winning_trade_count),
        "losing_trade_count": int(losing_trade_count),
        "win_rate": win_rate,
        "total_realized_r": total_realized_r,
        "ev_r": ev_r,
        "profit_factor": profit_factor,
        "top_symbols": top_symbols,
        "cohort_plan_ids": [str(row.get("plan_id") or "") for row in cohort_rows_sorted if str(row.get("plan_id") or "").strip()],
        "sticky_reused_plan_ids": sticky_ids,
        "sticky_reused_plan_count": int(len(sticky_ids)),
        "sticky_source_artifact_path": sticky_source_artifact_path,
        "replay_trade_row_count": int(len(replay_rows_sorted)),
        "contract_scope": contract_scope,
        "eligible_entry_models": list(eligible_entry_models or []),
        "eligible_symbols": list(eligible_symbols or []),
        "eligible_families": list(eligible_families or []),
        "eligible_direction_contract": {
            symbol: list(directions)
            for symbol, directions in dict(eligible_direction_contract or {}).items()
        },
        "advisory_only": advisory_only,
        "evidence_basis": str(evidence_basis or ""),
        "lookback_days": int(lookback_days) if lookback_days is not None else None,
        "summary": summary,
    }


def _build_historical_contract_proof_summary(
    *,
    focus_symbol: str,
    as_of: datetime | None = None,
    lookback_days: int = _HISTORICAL_CONTRACT_PROOF_LOOKBACK_DAYS,
    target_closed_trades: int = _HISTORICAL_CONTRACT_PROOF_MIN_CLOSED_TRADES,
    eligible_entry_models: tuple[str, ...] | None = None,
    eligible_symbols: tuple[str, ...] | None = None,
    eligible_families: tuple[str, ...] | None = None,
    eligible_direction_contract: dict[str, tuple[str, ...]] | None = None,
    contract_scope: str = _HISTORICAL_CONTRACT_PROOF_CONTRACT_SCOPE,
    summary_label: str = "historical-contract proof",
) -> dict[str, Any] | None:
    lookback = max(int(lookback_days), 1)
    cutoff = (as_of or _now()) - timedelta(days=lookback)
    lineage_rows = _load_post_patch_rows_from_lineage(focus_symbol=focus_symbol, cutoff=cutoff)
    if lineage_rows is None:
        return None
    lineage_rows = _filter_post_patch_rows_by_family(lineage_rows, eligible_families)
    lineage_rows = _filter_post_patch_rows_by_entry_model(lineage_rows, eligible_entry_models)
    lineage_rows = _filter_post_patch_rows_by_symbol(lineage_rows, eligible_symbols)
    lineage_rows = _filter_post_patch_rows_by_direction_contract(lineage_rows, eligible_direction_contract)
    return _summarize_contract_sample_rows(
        cohort_rows=lineage_rows,
        replay_rows=lineage_rows,
        cutoff=cutoff,
        target_closed_trades=target_closed_trades,
        contract_scope=contract_scope,
        eligible_entry_models=eligible_entry_models,
        eligible_symbols=eligible_symbols,
        eligible_families=eligible_families,
        eligible_direction_contract=eligible_direction_contract,
        summary_label=summary_label,
        advisory_only=True,
        evidence_basis="historical_closed_lineage_only",
        lookback_days=lookback,
    )


def _build_historical_walk_forward_contract_proof_summary(
    *,
    eligible_symbols: tuple[str, ...],
    eligible_families: tuple[str, ...],
    eligible_entry_models: tuple[str, ...],
    eligible_direction_contract: dict[str, tuple[str, ...]] | None = None,
    target_closed_trades: int,
    contract_scope: str,
    cache_key: str,
    summary_label: str,
    generate_on_new_15m_only: bool = False,
    independent_signal_mode: bool = False,
    max_candidates_per_bar: int | None = None,
    source_mode: str = "engine_regenerated",
) -> dict[str, Any] | None:
    try:
        from app.db.repositories import CandleRepository
        from app.db.session import SessionLocal
        from app.services.historical_walk_forward_proof import HistoricalWalkForwardProofService
    except Exception:
        return None

    db = SessionLocal()
    try:
        service = HistoricalWalkForwardProofService(
            candle_repo=CandleRepository(db),
            settings=get_settings(),
        )
        payload = service.generate(
            eligible_symbols=eligible_symbols,
            eligible_families=eligible_families,
            eligible_entry_models=eligible_entry_models,
            contract_scope=contract_scope,
            cache_key=cache_key,
            generate_on_new_15m_only=generate_on_new_15m_only,
            independent_signal_mode=independent_signal_mode,
            max_candidates_per_bar=max_candidates_per_bar,
            source_mode=source_mode,
        )
    except Exception:
        return None
    finally:
        db.close()

    trade_rows = [dict(row) for row in list(payload.get("trade_rows") or [])]
    trade_rows = _filter_post_patch_rows_by_direction_contract(trade_rows, eligible_direction_contract)
    simulation_start_ts = str(payload.get("simulation_start_ts") or "")
    simulation_end_ts = str(payload.get("simulation_end_ts") or "")
    latest_source_ts = str(payload.get("latest_source_ts") or "")
    symbol_summaries = [dict(item) for item in list(payload.get("symbol_summaries") or [])]
    baseline_ts = _parse_ts(simulation_start_ts) or _parse_ts(latest_source_ts) or _now()
    summary = _summarize_contract_sample_rows(
        cohort_rows=trade_rows,
        replay_rows=trade_rows,
        cutoff=baseline_ts,
        target_closed_trades=target_closed_trades,
        contract_scope=contract_scope,
        eligible_entry_models=eligible_entry_models,
        eligible_symbols=eligible_symbols,
        eligible_families=eligible_families,
        eligible_direction_contract=eligible_direction_contract,
        summary_label=summary_label,
        advisory_only=True,
        evidence_basis="historical_walk_forward_candles",
    )
    if summary is None:
        return None
    summary["simulation_start_ts"] = simulation_start_ts
    summary["simulation_end_ts"] = simulation_end_ts or latest_source_ts
    summary["latest_source_ts"] = latest_source_ts
    summary["latest_source_ts_by_symbol"] = dict(payload.get("latest_source_ts_by_symbol") or {})
    summary["symbol_summaries"] = symbol_summaries
    summary["schema_version"] = str(payload.get("schema_version") or "")
    return summary


def _load_post_patch_rows_from_artifact(artifact_path: str, *, cutoff: datetime) -> list[dict[str, Any]] | None:
    artifact_rel = str(artifact_path or "").strip()
    if not artifact_rel:
        return []
    artifact = _load_json_file(ROOT_DIR / artifact_rel)
    if not artifact:
        return None

    plan_to_meta: dict[str, dict[str, Any]] = {}
    for path_str in list(artifact.get("input_artifact_paths") or []):
        batch = _load_json_file(ROOT_DIR / str(path_str))
        if not batch:
            continue
        for row in list(batch.get("trade_rows") or []):
            plan_to_meta[str(row.get("plan_id") or "")] = dict(row)

    merged_rows: list[dict[str, Any]] = []
    for row in list(artifact.get("trade_rows") or []):
        closed_ts = _parse_ts(row.get("closed_ts"))
        if closed_ts is None or closed_ts < cutoff:
            continue
        plan_id = str(row.get("plan_id") or "")
        meta = dict(plan_to_meta.get(plan_id, {}) or {})
        merged_rows.append({**meta, **dict(row)})
    return merged_rows


def _load_post_patch_rows_from_lineage(*, focus_symbol: str, cutoff: datetime, version: str = "v2") -> list[dict[str, Any]] | None:
    normalized_symbol = str(focus_symbol or "").strip() or _GLOBAL_LINEAGE_VALIDATION_SYMBOL
    try:
        from sqlalchemy import select
        from app.core.enums import ExecutionFillStage
        from app.db.models import ExecutionFill, Plan
        from app.db.session import SessionLocal
    except Exception:
        return None

    db = SessionLocal()
    try:
        family_set = set(_GLOBAL_LINEAGE_VALIDATION_FAMILIES)
        closed_fills = list(
            db.scalars(
                select(ExecutionFill)
                .where(
                    ExecutionFill.stage == ExecutionFillStage.CLOSED.value,
                    ExecutionFill.fill_ts >= cutoff,
                )
                .order_by(ExecutionFill.fill_ts.asc(), ExecutionFill.created_at.asc())
            )
        )
        close_fill_by_plan_id: dict[str, Any] = {}
        for fill in closed_fills:
            plan_id = str(getattr(fill, "plan_id", "") or "")
            if not plan_id:
                continue
            close_fill_by_plan_id[plan_id] = fill

        if not close_fill_by_plan_id:
            return []

        plans = list(
            db.scalars(
                select(Plan).where(Plan.plan_id.in_(list(close_fill_by_plan_id.keys())))
            )
        )

        rows: list[dict[str, Any]] = []
        for plan in plans:
            validity = dict(getattr(plan, "validity", {}) or {})
            family = str(validity.get("strategy_family") or "").strip()
            if family not in family_set or str(getattr(plan, "strategy_version", "")) != version:
                continue
            if normalized_symbol != _GLOBAL_LINEAGE_VALIDATION_SYMBOL and str(getattr(plan, "symbol", "") or "").upper() != normalized_symbol.upper():
                continue
            plan_id = str(getattr(plan, "plan_id", "") or "")
            close_fill = close_fill_by_plan_id.get(plan_id)
            if close_fill is None:
                continue
            payload = dict(getattr(close_fill, "payload", {}) or {})
            raw_closed_ts = validity.get("final_exit_ts") or payload.get("exit_ts") or getattr(close_fill, "fill_ts", None)
            closed_ts = _parse_ts(raw_closed_ts)
            if closed_ts is None or closed_ts < cutoff:
                continue
            realized_r = validity.get("final_exit_realized_r")
            if realized_r is None:
                realized_r = payload.get("realized_r")
            try:
                realized_r_value = float(realized_r)
            except (TypeError, ValueError):
                continue
            held_bars = validity.get("final_exit_held_bars")
            if held_bars is None:
                held_bars = payload.get("held_bars") or 0
            try:
                held_bars_value = int(held_bars or 0)
            except (TypeError, ValueError):
                held_bars_value = 0
            exit_reason = str(validity.get("final_exit_reason") or payload.get("exit_reason") or "unknown").strip() or "unknown"
            rows.append(
                {
                    "plan_id": plan_id,
                    "zone_id": str(getattr(plan, "zone_id", "") or ""),
                    "symbol": str(validity.get("lineage_source_symbol") or getattr(plan, "symbol", "") or ""),
                    "direction": str(getattr(plan, "direction", "") or ""),
                    "strategy_family": family,
                    "entry_model": str(getattr(plan, "entry_model", "") or "").upper(),
                    "strategy_grade": str(validity.get("strategy_grade") or "").strip().upper(),
                    "regime": str(validity.get("regime") or "unknown").strip().lower() or "unknown",
                    "closed_ts": closed_ts.isoformat(),
                    "final_exit_realized_r": realized_r_value,
                    "replayed_realized_r": realized_r_value,
                    "final_exit_reason": exit_reason,
                    "final_exit_held_bars": held_bars_value,
                    "strategy_version": str(getattr(plan, "strategy_version", "") or ""),
                }
            )
    except Exception:
        return None
    finally:
        db.close()

    rows.sort(key=lambda row: (_parse_ts(row.get("closed_ts")) or datetime.min.replace(tzinfo=UTC), str(row.get("plan_id") or "")))
    return rows


def _entry_variant_from_row(row: dict[str, Any] | None) -> str:
    payload = dict(row or {})
    entry_model = str(payload.get("entry_model") or payload.get("entry_model_used") or "").strip().upper()
    if entry_model == "LIMIT":
        return "limit"
    if entry_model == "SWEEP_CONFIRM":
        return "sweep_confirm"
    if entry_model == "CONFIRM":
        return "confirm"
    plan_id = str(payload.get("plan_id") or "").strip().lower()
    if "sweep_confirm" in plan_id:
        return "sweep_confirm"
    if "confirm" in plan_id:
        return "confirm"
    if "limit" in plan_id:
        return "limit"
    return "other"


def _filter_post_patch_rows_by_entry_model(
    rows: list[dict[str, Any]] | None,
    eligible_entry_models: tuple[str, ...] | None,
) -> list[dict[str, Any]]:
    items = [dict(row) for row in list(rows or [])]
    normalized = {str(item or "").strip().upper() for item in tuple(eligible_entry_models or ()) if str(item or "").strip()}
    if not normalized:
        return items

    filtered: list[dict[str, Any]] = []
    for row in items:
        entry_model = str(row.get("entry_model") or row.get("entry_model_used") or "").strip().upper()
        if not entry_model:
            variant = _entry_variant_from_row(row)
            entry_model = {
                "limit": "LIMIT",
                "sweep_confirm": "SWEEP_CONFIRM",
                "confirm": "CONFIRM",
            }.get(variant, "")
        if entry_model in normalized:
            filtered.append(row)
    return filtered


def _filter_post_patch_rows_by_family(
    rows: list[dict[str, Any]] | None,
    eligible_families: tuple[str, ...] | None,
) -> list[dict[str, Any]]:
    items = [dict(row) for row in list(rows or [])]
    normalized = {
        str(item or "").strip().lower()
        for item in tuple(eligible_families or ())
        if str(item or "").strip()
    }
    if not normalized:
        return items
    return [
        row
        for row in items
        if str(row.get("strategy_family") or row.get("family") or "").strip().lower() in normalized
    ]


def _filter_post_patch_rows_by_symbol(
    rows: list[dict[str, Any]] | None,
    eligible_symbols: tuple[str, ...] | None,
) -> list[dict[str, Any]]:
    items = [dict(row) for row in list(rows or [])]
    normalized = {
        str(item or "").strip().upper()
        for item in tuple(eligible_symbols or ())
        if str(item or "").strip()
    }
    if not normalized:
        return items
    return [row for row in items if str(row.get("symbol") or "").strip().upper() in normalized]


def _filter_post_patch_rows_by_direction_contract(
    rows: list[dict[str, Any]] | None,
    eligible_direction_contract: dict[str, tuple[str, ...]] | None,
) -> list[dict[str, Any]]:
    items = [dict(row) for row in list(rows or [])]
    normalized = {
        str(symbol or "").strip().upper(): {
            str(direction or "").strip().upper()
            for direction in list(directions or [])
            if str(direction or "").strip()
        }
        for symbol, directions in dict(eligible_direction_contract or {}).items()
        if str(symbol or "").strip()
    }
    normalized = {symbol: directions for symbol, directions in normalized.items() if directions}
    if not normalized:
        return items
    filtered: list[dict[str, Any]] = []
    for row in items:
        symbol = str(row.get("symbol") or "").strip().upper()
        allowed = normalized.get(symbol)
        if not allowed:
            filtered.append(row)
            continue
        direction = str(row.get("direction") or "").strip().upper()
        if not direction or direction in allowed:
            filtered.append(row)
    return filtered


def _runtime_gate_post_patch_summary(focus: dict[str, Any] | None) -> tuple[dict[str, Any], str]:
    payload = dict(focus or {})
    live_execution = dict(payload.get("live_execution_post_patch_sample_summary") or {})
    if int(live_execution.get("closed_trade_count", 0) or 0) >= _LIVE_EXECUTION_BOOTSTRAP_MIN_CLOSED_TRADES:
        return live_execution, "live_execution_post_patch_sample_summary"
    live_eligible = dict(payload.get("live_eligible_post_patch_sample_summary") or {})
    if live_eligible:
        return live_eligible, "live_eligible_post_patch_sample_summary"
    return dict(payload.get("post_patch_sample_summary") or {}), "post_patch_sample_summary"


def _find_previous_replay_artifact_path(current_artifact_path: str) -> str:
    previous_paths = _list_previous_replay_artifact_paths(current_artifact_path, limit=1)
    if not previous_paths:
        return ""
    return str(previous_paths[0])


def _find_latest_replay_artifact_path(current_artifact_path: str) -> str:
    artifact_rel = str(current_artifact_path or "").strip()
    artifact_file = ROOT_DIR / artifact_rel
    parent = artifact_file.parent
    stem = artifact_file.stem
    if not artifact_file.exists() or not parent.exists() or "_" not in stem:
        return artifact_rel
    prefix, _timestamp = stem.rsplit("_", 1)
    candidates = sorted(parent.glob(f"{prefix}_*.json"))
    if not candidates:
        return artifact_rel
    latest = candidates[-1]
    return _report_path_value(latest)


def _replay_artifact_trade_row_count(artifact_path: str) -> int:
    artifact_rel = str(artifact_path or "").strip()
    if not artifact_rel:
        return 0
    artifact = _load_json_file(ROOT_DIR / artifact_rel)
    if not artifact:
        return 0
    return len(list(artifact.get("trade_rows") or []))


def _select_refresh_artifact_path(current_artifact_path: str, latest_artifact_path: str) -> str:
    current_rel = str(current_artifact_path or "").strip()
    latest_rel = str(latest_artifact_path or "").strip()
    if not latest_rel:
        return current_rel
    if not current_rel or latest_rel == current_rel:
        return latest_rel

    current_count = _replay_artifact_trade_row_count(current_rel)
    latest_count = _replay_artifact_trade_row_count(latest_rel)
    if latest_count <= 0 and current_count > 0:
        return current_rel
    if current_count > 0 and latest_count < current_count:
        return current_rel
    return latest_rel


def _list_previous_replay_artifact_paths(current_artifact_path: str, *, limit: int = 96) -> list[str]:
    artifact_rel = str(current_artifact_path or "").strip()
    artifact_file = ROOT_DIR / artifact_rel
    parent = artifact_file.parent
    stem = artifact_file.stem
    if not parent.exists() or "_" not in stem:
        return []
    prefix, _timestamp = stem.rsplit("_", 1)
    candidates = sorted(parent.glob(f"{prefix}_*.json"))
    current_name = artifact_file.name
    previous = [path for path in candidates if path.name < current_name]
    if not previous:
        return []
    return [_report_path_value(path) for path in reversed(previous[-limit:])]


def _refresh_focus_from_local_artifact(
    focus: dict[str, Any] | None,
    *,
    stage: dict[str, Any] | None = None,
    symbol: str = "BTCUSDC",
    universe: str = "usdc_perp_top30",
    days: int = 30,
    artifact_path_override: str = "",
) -> dict[str, Any]:
    payload = dict(focus or {})
    current_artifact_path = str(artifact_path_override or payload.get("artifact_path") or "").strip()
    latest_artifact_path = _find_latest_replay_artifact_path(current_artifact_path)
    artifact_path = _select_refresh_artifact_path(current_artifact_path, latest_artifact_path)
    if not artifact_path:
        return payload

    payload["artifact_path"] = artifact_path

    downside_profile = _build_approval_template_downside_profile(artifact_path=artifact_path)
    if downside_profile:
        payload["downside_profile"] = downside_profile
    confirm_loss_cluster_summary = _build_confirm_loss_cluster_summary(artifact_path=artifact_path)
    if confirm_loss_cluster_summary:
        payload["confirm_loss_cluster_summary"] = confirm_loss_cluster_summary
    entry_timing_loss_profile = _build_entry_timing_loss_profile(artifact_path=artifact_path)
    if entry_timing_loss_profile:
        payload["entry_timing_loss_profile"] = entry_timing_loss_profile
        entry_timing_priority_summary = _build_entry_timing_priority_summary(entry_timing_loss_profile)
        if entry_timing_priority_summary:
            payload["entry_timing_priority_summary"] = entry_timing_priority_summary
    if downside_profile and stage is not None:
        mitigation_review_summary = _build_mitigation_review_summary(
            downside_profile=downside_profile,
            stage=stage,
            symbol=symbol,
            universe=universe,
            days=days,
        )
        if mitigation_review_summary:
            payload["mitigation_review_summary"] = mitigation_review_summary
            mitigation_execution_plan = _build_mitigation_execution_plan(
                priority_summary=dict(payload.get("entry_timing_priority_summary") or {}),
                mitigation_review_summary=mitigation_review_summary,
            )
            if mitigation_execution_plan:
                payload["mitigation_execution_plan"] = mitigation_execution_plan

    full_summary = _build_post_patch_sample_summary(
        focus_symbol=str(payload.get("focus_symbol") or _GLOBAL_LINEAGE_VALIDATION_SYMBOL),
        artifact_path=artifact_path,
        previous_summary=dict(payload.get("post_patch_sample_summary") or {}),
        previous_artifact_path=current_artifact_path,
    )
    if full_summary:
        payload["post_patch_sample_summary"] = full_summary
        payload["replay_max_drawdown_r"] = float(full_summary.get("replay_max_drawdown_r", 0.0) or 0.0)
        payload["replay_p5_r"] = float(full_summary.get("replay_p5_r", 0.0) or 0.0)
        payload["replay_trade_rows"] = int(full_summary.get("replay_trade_row_count", 0) or 0)

    live_eligible_summary = _build_post_patch_sample_summary(
        focus_symbol=str(payload.get("focus_symbol") or _GLOBAL_LINEAGE_VALIDATION_SYMBOL),
        artifact_path=artifact_path,
        target_closed_trades=_LIVE_ELIGIBLE_MICRO_LIVE_MIN_CLOSED_TRADES,
        previous_summary=dict(payload.get("live_eligible_post_patch_sample_summary") or {}),
        previous_artifact_path=current_artifact_path,
        eligible_entry_models=_live_execution_allowed_entry_models(),
        eligible_symbols=_live_execution_allowed_symbols(),
        eligible_families=_live_execution_allowed_families(),
        eligible_direction_contract=_live_execution_direction_contract(),
        contract_scope=_LIVE_ELIGIBLE_CONTRACT_SCOPE,
        summary_label="live-eligible post-patch sample",
    )
    if live_eligible_summary:
        payload["live_eligible_post_patch_sample_summary"] = live_eligible_summary
        payload["live_contract_scope"] = str(live_eligible_summary.get("contract_scope") or "")
    live_execution_summary = _build_post_patch_sample_summary(
        focus_symbol=str(payload.get("focus_symbol") or _GLOBAL_LINEAGE_VALIDATION_SYMBOL),
        artifact_path=artifact_path,
        target_closed_trades=_LIVE_EXECUTION_BOOTSTRAP_MIN_CLOSED_TRADES,
        previous_summary=dict(payload.get("live_execution_post_patch_sample_summary") or {}),
        previous_artifact_path=current_artifact_path,
        eligible_entry_models=_live_execution_allowed_entry_models(),
        eligible_symbols=_live_execution_allowed_symbols(),
        eligible_families=_live_execution_allowed_families(),
        eligible_direction_contract=_live_execution_direction_contract(),
        contract_scope=_LIVE_ELIGIBLE_CONTRACT_SCOPE,
        summary_label="live-execution post-patch sample",
    )
    if live_execution_summary:
        payload["live_execution_post_patch_sample_summary"] = live_execution_summary
    historical_contract_summary = _build_historical_contract_proof_summary(
        focus_symbol=str(payload.get("focus_symbol") or _GLOBAL_LINEAGE_VALIDATION_SYMBOL),
        eligible_entry_models=_live_execution_allowed_entry_models(),
        eligible_symbols=_live_execution_allowed_symbols(),
        eligible_families=_live_execution_allowed_families(),
        eligible_direction_contract=_live_execution_direction_contract(),
    )
    if historical_contract_summary:
        payload["historical_execution_contract_proof_summary"] = historical_contract_summary
    historical_walk_forward_execution_summary = _build_historical_walk_forward_contract_proof_summary(
        eligible_symbols=_live_execution_allowed_symbols(),
        eligible_families=_live_execution_allowed_families(),
        eligible_entry_models=_live_execution_allowed_entry_models(),
        eligible_direction_contract=_live_execution_direction_contract(),
        target_closed_trades=_HISTORICAL_WALK_FORWARD_EXECUTION_PROOF_MIN_CLOSED_TRADES,
        contract_scope=_HISTORICAL_WALK_FORWARD_EXECUTION_PROOF_CONTRACT_SCOPE,
        cache_key="execution_contract",
        summary_label="historical walk-forward execution proof",
    )
    if historical_walk_forward_execution_summary:
        payload["historical_walk_forward_execution_contract_proof_summary"] = historical_walk_forward_execution_summary
    historical_walk_forward_strategy_summary = _build_historical_walk_forward_contract_proof_summary(
        eligible_symbols=_live_execution_allowed_symbols(),
        eligible_families=_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_FAMILIES,
        eligible_entry_models=_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_ENTRY_MODELS,
        eligible_direction_contract=_live_execution_direction_contract(),
        target_closed_trades=_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_MIN_CLOSED_TRADES,
        contract_scope=_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_CONTRACT_SCOPE,
        cache_key=_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_CACHE_KEY,
        summary_label="historical walk-forward BTC/ETH strategy proof",
        generate_on_new_15m_only=True,
        independent_signal_mode=True,
        max_candidates_per_bar=_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_MAX_CANDIDATES_PER_BAR,
        source_mode=_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_SOURCE_MODE,
    )
    if historical_walk_forward_strategy_summary:
        payload["historical_walk_forward_strategy_proof_summary"] = historical_walk_forward_strategy_summary
    trend_proof_summary = _build_post_patch_sample_summary(
        focus_symbol=str(payload.get("focus_symbol") or _GLOBAL_LINEAGE_VALIDATION_SYMBOL),
        artifact_path=artifact_path,
        target_closed_trades=_TREND_PROOF_MIN_CLOSED_TRADES,
        previous_summary=dict(payload.get("trend_proof_post_patch_sample_summary") or {}),
        previous_artifact_path=current_artifact_path,
        eligible_entry_models=_live_execution_allowed_entry_models(),
        eligible_symbols=_live_execution_allowed_symbols(),
        eligible_families=_TREND_PROOF_FAMILIES,
        contract_scope=_TREND_PROOF_CONTRACT_SCOPE,
        summary_label="trend-proof post-patch sample",
    )
    if trend_proof_summary:
        payload["trend_proof_post_patch_sample_summary"] = trend_proof_summary
    historical_walk_forward_trend_summary = _build_historical_walk_forward_contract_proof_summary(
        eligible_symbols=_live_execution_allowed_symbols(),
        eligible_families=_TREND_PROOF_FAMILIES,
        eligible_entry_models=_live_execution_allowed_entry_models(),
        target_closed_trades=_HISTORICAL_WALK_FORWARD_TREND_PROOF_MIN_CLOSED_TRADES,
        contract_scope=_HISTORICAL_WALK_FORWARD_TREND_PROOF_CONTRACT_SCOPE,
        cache_key="trend_proof_contract",
        summary_label="historical walk-forward trend proof",
    )
    if historical_walk_forward_trend_summary:
        payload["historical_walk_forward_trend_proof_summary"] = historical_walk_forward_trend_summary
    return payload


def _build_approval_template_focus(
    *,
    focus_symbol: str,
    worst_scenario: str,
    assessment_payload: dict[str, Any] | None,
    output_artifacts_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    assessment = dict(assessment_payload or {})
    output_artifacts = dict(output_artifacts_payload or {})
    scenario_statuses = dict((assessment.get("scenario_evidence") or {}).get("scenario_statuses") or {})
    scenario_outputs = dict(output_artifacts.get("scenario_outputs") or {})
    scenario_status = dict(scenario_statuses.get(worst_scenario) or {})
    scenario_output = dict(scenario_outputs.get(worst_scenario) or {})
    replay_summary = dict(scenario_output.get("summary") or {})
    approximation_gap = dict(scenario_output.get("approximation_gap") or scenario_status.get("approximation_delta") or {})

    if not scenario_status and not scenario_output:
        return None

    focus = {
        "focus_symbol": focus_symbol,
        "worst_scenario": worst_scenario,
        "worst_scenario_status": str(scenario_status.get("status") or "NOT_AVAILABLE"),
        "worst_scenario_reason": str(scenario_status.get("reason") or "not_available"),
        "worst_scenario_source": str(scenario_status.get("source") or "not_available"),
        "divergence_status": str(scenario_status.get("divergence_status") or "NOT_AVAILABLE"),
        "divergence_reason": str(scenario_status.get("divergence_reason") or "not_available"),
        "replay_trade_rows": int((output_artifacts.get("summary_counts") or {}).get("replay_trade_rows", 0) or 0),
        "replay_scenarios_compared": int((output_artifacts.get("summary_counts") or {}).get("scenarios_compared", 0) or 0),
        "replay_ev_r": float(replay_summary.get("ev", 0.0) or 0.0),
        "replay_p5_r": float(replay_summary.get("p5_ev", 0.0) or 0.0),
        "replay_max_drawdown_r": float(replay_summary.get("max_drawdown", 0.0) or 0.0),
        "approximation_gap_ev_r": float(approximation_gap.get("ev", 0.0) or 0.0),
        "approximation_gap_max_drawdown_r": float(approximation_gap.get("max_drawdown", 0.0) or 0.0),
        "artifact_path": str(scenario_output.get("artifact_path") or ""),
    }
    downside_profile = _build_approval_template_downside_profile(artifact_path=str(focus.get("artifact_path") or ""))
    if downside_profile:
        focus["downside_profile"] = downside_profile
    return focus


def _attach_approval_template_focus(
    payload: dict[str, Any],
    *,
    stage: dict[str, Any],
    symbol: str,
    base_url: str,
    request_json_fn=_request_json,
) -> dict[str, Any]:
    enriched = dict(payload or {})
    primary_required = dict(enriched.get("primary_required_review") or {})
    if str(primary_required.get("code") or "") != "approval_template_review":
        return enriched

    worst_scenario = str(primary_required.get("worst_scenario") or "").strip()
    if not worst_scenario:
        return enriched

    focus_symbol = _approval_template_focus_symbol(stage, symbol=symbol)
    previous_focus = dict(enriched.get("approval_template_focus") or {})
    if not previous_focus:
        previous_focus = dict(dict(stage.get("runtime_signoff_summary") or {}).get("approval_template_focus") or {})
    if not previous_focus:
        previous_focus = dict(stage.get("approval_template_focus") or {})
    try:
        assessment_payload = _request_json_with_retry(
            base_url,
            "/validation/stress-replay-assessment",
            query={"symbol": focus_symbol, "write_report": False},
            request_json_fn=request_json_fn,
        )
        output_artifacts_payload = _request_json_with_retry(
            base_url,
            "/validation/stress-replay-output-artifacts",
            query={"symbol": focus_symbol, "write_report": False},
            request_json_fn=request_json_fn,
        )
    except RuntimeError as exc:
        enriched["approval_template_focus_error"] = str(exc)
        if previous_focus:
            enriched["approval_template_focus"] = previous_focus
        return enriched

    focus = _build_approval_template_focus(
        focus_symbol=focus_symbol,
        worst_scenario=worst_scenario,
        assessment_payload=assessment_payload,
        output_artifacts_payload=output_artifacts_payload,
    )
    if focus is not None:
        downside = dict(focus.get("downside_profile") or {})
        confirm_loss_cluster_summary = _build_confirm_loss_cluster_summary(
            artifact_path=str(focus.get("artifact_path") or "")
        )
        if confirm_loss_cluster_summary:
            focus["confirm_loss_cluster_summary"] = confirm_loss_cluster_summary
        entry_timing_loss_profile = _build_entry_timing_loss_profile(
            artifact_path=str(focus.get("artifact_path") or "")
        )
        entry_timing_priority_summary = None
        if entry_timing_loss_profile:
            focus["entry_timing_loss_profile"] = entry_timing_loss_profile
            entry_timing_priority_summary = _build_entry_timing_priority_summary(entry_timing_loss_profile)
            if entry_timing_priority_summary:
                focus["entry_timing_priority_summary"] = entry_timing_priority_summary
        mitigation_review_summary = _build_mitigation_review_summary(
            downside_profile=downside,
            stage=stage,
            symbol=symbol,
            universe=str(payload.get("universe") or stage.get("universe") or "usdc_perp_top30"),
            days=int(payload.get("days") or stage.get("days") or 30),
        )
        if mitigation_review_summary:
            focus["mitigation_review_summary"] = mitigation_review_summary
            mitigation_execution_plan = _build_mitigation_execution_plan(
                priority_summary=entry_timing_priority_summary,
                mitigation_review_summary=mitigation_review_summary,
            )
            if mitigation_execution_plan:
                focus["mitigation_execution_plan"] = mitigation_execution_plan
        post_patch_sample_summary = _build_post_patch_sample_summary(
            focus_symbol=str(focus.get("focus_symbol") or _GLOBAL_LINEAGE_VALIDATION_SYMBOL),
            artifact_path=str(focus.get("artifact_path") or ""),
            previous_summary=dict(previous_focus.get("post_patch_sample_summary") or {}),
            previous_artifact_path=str(previous_focus.get("artifact_path") or ""),
        )
        if post_patch_sample_summary:
            focus["post_patch_sample_summary"] = post_patch_sample_summary
        live_eligible_post_patch_sample_summary = _build_post_patch_sample_summary(
            focus_symbol=str(focus.get("focus_symbol") or _GLOBAL_LINEAGE_VALIDATION_SYMBOL),
            artifact_path=str(focus.get("artifact_path") or ""),
            target_closed_trades=_LIVE_ELIGIBLE_MICRO_LIVE_MIN_CLOSED_TRADES,
            previous_summary=dict(previous_focus.get("live_eligible_post_patch_sample_summary") or {}),
            previous_artifact_path=str(previous_focus.get("artifact_path") or ""),
            eligible_entry_models=_live_execution_allowed_entry_models(),
            eligible_symbols=_live_execution_allowed_symbols(),
            eligible_families=_live_execution_allowed_families(),
            eligible_direction_contract=_live_execution_direction_contract(),
            contract_scope=_LIVE_ELIGIBLE_CONTRACT_SCOPE,
            summary_label="live-eligible post-patch sample",
        )
        if live_eligible_post_patch_sample_summary:
            focus["live_eligible_post_patch_sample_summary"] = live_eligible_post_patch_sample_summary
            focus["live_contract_scope"] = str(live_eligible_post_patch_sample_summary.get("contract_scope") or "")
        live_execution_post_patch_sample_summary = _build_post_patch_sample_summary(
            focus_symbol=str(focus.get("focus_symbol") or _GLOBAL_LINEAGE_VALIDATION_SYMBOL),
            artifact_path=str(focus.get("artifact_path") or ""),
            target_closed_trades=_LIVE_EXECUTION_BOOTSTRAP_MIN_CLOSED_TRADES,
            previous_summary=dict(previous_focus.get("live_execution_post_patch_sample_summary") or {}),
            previous_artifact_path=str(previous_focus.get("artifact_path") or ""),
            eligible_entry_models=_live_execution_allowed_entry_models(),
            eligible_symbols=_live_execution_allowed_symbols(),
            eligible_families=_live_execution_allowed_families(),
            eligible_direction_contract=_live_execution_direction_contract(),
            contract_scope=_LIVE_ELIGIBLE_CONTRACT_SCOPE,
            summary_label="live-execution post-patch sample",
        )
        if live_execution_post_patch_sample_summary:
            focus["live_execution_post_patch_sample_summary"] = live_execution_post_patch_sample_summary
        historical_contract_proof_summary = _build_historical_contract_proof_summary(
            focus_symbol=str(focus.get("focus_symbol") or _GLOBAL_LINEAGE_VALIDATION_SYMBOL),
            eligible_entry_models=_live_execution_allowed_entry_models(),
            eligible_symbols=_live_execution_allowed_symbols(),
            eligible_families=_live_execution_allowed_families(),
            eligible_direction_contract=_live_execution_direction_contract(),
        )
        if historical_contract_proof_summary:
            focus["historical_execution_contract_proof_summary"] = historical_contract_proof_summary
        historical_walk_forward_execution_summary = _build_historical_walk_forward_contract_proof_summary(
            eligible_symbols=_live_execution_allowed_symbols(),
            eligible_families=_live_execution_allowed_families(),
            eligible_entry_models=_live_execution_allowed_entry_models(),
            eligible_direction_contract=_live_execution_direction_contract(),
            target_closed_trades=_HISTORICAL_WALK_FORWARD_EXECUTION_PROOF_MIN_CLOSED_TRADES,
            contract_scope=_HISTORICAL_WALK_FORWARD_EXECUTION_PROOF_CONTRACT_SCOPE,
            cache_key="execution_contract",
            summary_label="historical walk-forward execution proof",
        )
        if historical_walk_forward_execution_summary:
            focus["historical_walk_forward_execution_contract_proof_summary"] = historical_walk_forward_execution_summary
        historical_walk_forward_strategy_summary = _build_historical_walk_forward_contract_proof_summary(
            eligible_symbols=_live_execution_allowed_symbols(),
            eligible_families=_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_FAMILIES,
            eligible_entry_models=_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_ENTRY_MODELS,
            eligible_direction_contract=_live_execution_direction_contract(),
            target_closed_trades=_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_MIN_CLOSED_TRADES,
            contract_scope=_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_CONTRACT_SCOPE,
            cache_key=_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_CACHE_KEY,
            summary_label="historical walk-forward BTC/ETH strategy proof",
            generate_on_new_15m_only=True,
            independent_signal_mode=True,
            max_candidates_per_bar=_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_MAX_CANDIDATES_PER_BAR,
            source_mode=_HISTORICAL_WALK_FORWARD_STRATEGY_PROOF_SOURCE_MODE,
        )
        if historical_walk_forward_strategy_summary:
            focus["historical_walk_forward_strategy_proof_summary"] = historical_walk_forward_strategy_summary
        trend_proof_post_patch_sample_summary = _build_post_patch_sample_summary(
            focus_symbol=str(focus.get("focus_symbol") or _GLOBAL_LINEAGE_VALIDATION_SYMBOL),
            artifact_path=str(focus.get("artifact_path") or ""),
            target_closed_trades=_TREND_PROOF_MIN_CLOSED_TRADES,
            previous_summary=dict(previous_focus.get("trend_proof_post_patch_sample_summary") or {}),
            previous_artifact_path=str(previous_focus.get("artifact_path") or ""),
            eligible_entry_models=_live_execution_allowed_entry_models(),
            eligible_symbols=_live_execution_allowed_symbols(),
            eligible_families=_TREND_PROOF_FAMILIES,
            contract_scope=_TREND_PROOF_CONTRACT_SCOPE,
            summary_label="trend-proof post-patch sample",
        )
        if trend_proof_post_patch_sample_summary:
            focus["trend_proof_post_patch_sample_summary"] = trend_proof_post_patch_sample_summary
        historical_walk_forward_trend_summary = _build_historical_walk_forward_contract_proof_summary(
            eligible_symbols=_live_execution_allowed_symbols(),
            eligible_families=_TREND_PROOF_FAMILIES,
            eligible_entry_models=_live_execution_allowed_entry_models(),
            target_closed_trades=_HISTORICAL_WALK_FORWARD_TREND_PROOF_MIN_CLOSED_TRADES,
            contract_scope=_HISTORICAL_WALK_FORWARD_TREND_PROOF_CONTRACT_SCOPE,
            cache_key="trend_proof_contract",
            summary_label="historical walk-forward trend proof",
        )
        if historical_walk_forward_trend_summary:
            focus["historical_walk_forward_trend_proof_summary"] = historical_walk_forward_trend_summary
        focus = _refresh_focus_from_local_artifact(
            focus,
            stage=stage,
            symbol=symbol,
            universe=str(payload.get("universe") or stage.get("universe") or "usdc_perp_top30"),
            days=int(payload.get("days") or stage.get("days") or 30),
            artifact_path_override=str(focus.get("artifact_path") or ""),
        )
        enriched["approval_template_focus"] = focus
    return enriched


def _build_payload(stage: dict[str, Any], *, symbol: str, universe: str, days: int) -> dict[str, Any]:
    runtime_reopen = dict(stage.get("runtime_reopen_status") or {})
    signoff = dict(stage.get("runtime_signoff_summary") or {})
    lineage = dict(stage.get("lineage_sample_summary") or {})
    risk = dict(stage.get("risk_gate_summary") or {})
    validation = dict(stage.get("validation_approval_strip") or {})

    required_reviews = [dict(item) for item in list(signoff.get("required_reviews") or [])]
    advisory_reviews = [dict(item) for item in list(signoff.get("advisory_reviews") or [])]
    primary_required = dict(required_reviews[0] or {}) if required_reviews else {}

    runtime_ready = _runtime_signoff_eligible_status(runtime_reopen.get("status")) or bool(runtime_reopen.get("ready", False))
    if not runtime_ready:
        status = "NOT_READY_FOR_SIGNOFF"
        summary_line = "Runtime reopen is not ready yet; operator sign-off should not proceed."
    elif required_reviews:
        status = "MANUAL_SIGNOFF_REQUIRED"
        summary_line = "Runtime can reopen only after operator explicitly reviews the remaining required warning."
    else:
        status = "READY_FOR_OPERATOR_SIGNOFF"
        summary_line = "Runtime reopen is ready and no required sign-off warnings remain."

    operator_recommendation, operator_recommendation_reason = _fallback_operator_recommendation(
        runtime_ready=runtime_ready,
        required_reviews=required_reviews,
    )

    next_steps: list[str] = []
    if status == "NOT_READY_FOR_SIGNOFF":
        next_steps.append("Wait until runtime_reopen_status becomes ready_to_reopen_runtime.")
    elif required_reviews:
        if str(primary_required.get("code") or "") == "approval_template_review":
            next_steps.append(
                "Review whether the replay-derived worst scenario failure should still block runtime reopen."
            )
            next_steps.append(
                "If the warning is acceptable, record explicit operator sign-off before reopening runtime."
            )
            next_steps.append(
                "If the warning is not acceptable, keep runtime closed and continue candidate review only."
            )
        else:
            next_steps.append("Review the remaining required warning and decide whether runtime reopen is acceptable.")
    else:
        next_steps.append("Proceed to final operator sign-off and runtime reopen decision.")

    payload = {
        "generated_at": _now().isoformat(),
        "symbol": symbol.upper(),
        "universe": universe,
        "days": int(days),
        "status": status,
        "summary_line": summary_line,
        "runtime_signoff_review_command": _runtime_signoff_command(symbol=symbol, universe=universe, days=days),
        "runtime_reopen_status": {
            "status": str(runtime_reopen.get("status") or "not_available"),
            "ready": bool(runtime_reopen.get("ready", False)),
        },
        "risk_gate": {
            "status": str(risk.get("status") or "NOT_AVAILABLE"),
            "state": str(risk.get("risk_state") or "UNKNOWN"),
        },
        "validation": {
            "approve_value": str(validation.get("approve_value") or "n/a"),
            "align_value": str(validation.get("align_value") or "n/a"),
            "act_value": str(validation.get("act_value") or "n/a"),
        },
        "operator_recommendation": operator_recommendation,
        "operator_recommendation_reason": operator_recommendation_reason,
        "lineage_sample": {
            "closed_trade_count": int(lineage.get("closed_trade_count") or 0),
            "proof_goal_closed_trades": int(lineage.get("proof_goal_closed_trades") or 0),
        },
        "required_reviews": required_reviews,
        "advisory_reviews": advisory_reviews,
        "primary_required_review": primary_required or None,
        "next_steps": next_steps,
    }
    return payload


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    primary = dict(payload.get("primary_required_review") or {})
    focus = dict(payload.get("approval_template_focus") or {})
    decision = dict(payload.get("runtime_decision") or {})
    gate = dict(payload.get("runtime_reopen_gate_summary") or {})
    lines: list[str] = []
    lines.append("# Runtime Sign-off Review")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- symbol: {payload['symbol']}")
    lines.append(f"- status: {payload['status']}")
    lines.append(f"- summary: {payload['summary_line']}")
    lines.append("")
    lines.append("## Current State")
    lines.append("")
    lines.append(
        f"- runtime_reopen_status: {payload['runtime_reopen_status']['status']} / ready={payload['runtime_reopen_status']['ready']}"
    )
    lines.append(f"- operator_recommendation: {payload.get('operator_recommendation') or 'n/a'}")
    lines.append(f"- operator_recommendation_reason: {payload.get('operator_recommendation_reason') or 'n/a'}")
    if decision:
        lines.append(
            f"- runtime_decision: {decision.get('band') or 'n/a'} / "
            f"{decision.get('effective_action') or 'n/a'} / "
            f"scope={decision.get('allowed_reopen_scope') or 'n/a'}"
        )
        lines.append(f"- runtime_decision_summary: {decision.get('summary') or 'n/a'}")
    if gate:
        micro = dict(gate.get("micro_live") or {})
        full = dict(gate.get("full_live") or {})
        lines.append(
            "- runtime_reopen_gate: "
            f"MICRO={micro.get('status') or 'n/a'} "
            f"({int(micro.get('closed_trade_count') or 0)}/{int(micro.get('min_closed_trades') or 0)})"
            f" | FULL={full.get('status') or 'n/a'} "
            f"({int(full.get('closed_trade_count') or 0)}/{int(full.get('min_closed_trades') or 0)})"
        )
        if str(micro.get("source_summary_key") or ""):
            lines.append(
                f"- runtime_reopen_gate_source: {str(micro.get('source_summary_key') or 'n/a')} "
                f"/ contract={str(micro.get('contract_scope') or 'full_post_patch')}"
            )
    lines.append(f"- risk_gate: {payload['risk_gate']['status']} / {payload['risk_gate']['state']}")
    lines.append(
        f"- lineage_sample: {payload['lineage_sample']['closed_trade_count']}/{payload['lineage_sample']['proof_goal_closed_trades']}"
    )
    lines.append("")
    lines.append("## Required Review")
    lines.append("")
    if primary:
        lines.append(f"- code: {primary.get('code', 'n/a')}")
        lines.append(f"- summary: {primary.get('summary', 'n/a')}")
        lines.append(f"- current_value: {primary.get('current_value', 'n/a')}")
        if primary.get("worst_scenario"):
            lines.append(
                f"- worst_scenario: {primary.get('worst_scenario')}/{primary.get('worst_scenario_status', 'NOT_AVAILABLE')}"
            )
        if primary.get("worst_scenario_reason"):
            lines.append(f"- worst_scenario_reason: {primary.get('worst_scenario_reason')}")
        lines.append(f"- clear_when: {primary.get('clear_when', 'n/a')}")
    else:
        lines.append("- none")
    if focus:
        lines.append("")
        lines.append("## Approval Template Focus")
        lines.append("")
        lines.append(f"- focus_symbol: {focus.get('focus_symbol', 'n/a')}")
        lines.append(
            f"- worst_scenario: {focus.get('worst_scenario', 'n/a')}/{focus.get('worst_scenario_status', 'NOT_AVAILABLE')}"
        )
        lines.append(f"- worst_scenario_reason: {focus.get('worst_scenario_reason', 'n/a')}")
        lines.append(f"- source: {focus.get('worst_scenario_source', 'n/a')}")
        lines.append(
            f"- replay_ev_r: {float(focus.get('replay_ev_r', 0.0) or 0.0):.4f} | "
            f"replay_p5_r: {float(focus.get('replay_p5_r', 0.0) or 0.0):.4f} | "
            f"replay_max_drawdown_r: {float(focus.get('replay_max_drawdown_r', 0.0) or 0.0):.4f}"
        )
        lines.append(
            f"- approximation_gap_ev_r: {float(focus.get('approximation_gap_ev_r', 0.0) or 0.0):+.4f} | "
            f"approximation_gap_max_drawdown_r: {float(focus.get('approximation_gap_max_drawdown_r', 0.0) or 0.0):+.4f}"
        )
        lines.append(
            f"- divergence: {focus.get('divergence_status', 'NOT_AVAILABLE')} / "
            f"{focus.get('divergence_reason', 'n/a')}"
        )
        lines.append(
            f"- replay_trade_rows: {int(focus.get('replay_trade_rows', 0) or 0)} | "
            f"scenarios_compared: {int(focus.get('replay_scenarios_compared', 0) or 0)}"
        )
        downside = dict(focus.get("downside_profile") or {})
        if downside:
            lines.append(
                f"- downside_profile: regime={str(downside.get('dominant_regime') or 'unknown')}, "
                f"stop_loss={int(downside.get('stop_loss_count', 0) or 0)}/"
                f"{int(downside.get('trade_count', 0) or 0)} "
                f"({float(downside.get('stop_loss_share', 0.0) or 0.0):.2%}), "
                f"confirm_losses={int(downside.get('confirm_named_loss_count', 0) or 0)}/"
                f"{int(downside.get('loss_trade_count', 0) or 0)} "
                f"({float(downside.get('confirm_named_loss_share', 0.0) or 0.0):.2%}), "
                f"long_hold_losses={int(downside.get('long_hold_loss_count', 0) or 0)}/"
                f"{int(downside.get('loss_trade_count', 0) or 0)} "
                f"({float(downside.get('long_hold_loss_share', 0.0) or 0.0):.2%}), "
                f"held_bars_median={float(downside.get('median_loss_held_bars', 0.0) or 0.0):.0f}, "
                f"held_bars_p75={int(downside.get('p75_loss_held_bars', 0) or 0)}, "
                f"worst_loss_streak={int(downside.get('worst_loss_streak', 0) or 0)}, "
                f"worst_loss_block={float(downside.get('worst_loss_block_sum_r', 0.0) or 0.0):.4f}R/"
                f"{int(downside.get('worst_loss_block_len', 0) or 0)} trades"
            )
            lines.append(
                f"- primary_failure_mode: {str(downside.get('primary_failure_mode') or 'unknown')} / "
                f"{str(downside.get('primary_failure_summary') or 'n/a')}"
            )
            top_loss_symbols = list(downside.get("top_loss_symbols") or [])
            if top_loss_symbols:
                top_line = ", ".join(
                    f"{str(item.get('symbol') or 'UNKNOWN')} "
                    f"({float(item.get('negative_r', 0.0) or 0.0):.4f}R/"
                    f"{int(item.get('loss_trade_count', 0) or 0)})"
                    for item in top_loss_symbols[:3]
                )
                lines.append(f"- top_loss_symbols: {top_line}")
            top_loss_waves = list(downside.get("top_loss_waves") or [])
            if top_loss_waves:
                wave = dict(top_loss_waves[0] or {})
                lines.append(
                    f"- top_loss_wave: {str(wave.get('closed_ts') or 'n/a')} / "
                    f"{int(wave.get('loss_trade_count', 0) or 0)} losses / "
                    f"{float(downside.get('top_loss_wave_share_of_losses', 0.0) or 0.0):.2%} of replay losses"
                )
            mitigation_focus = list(downside.get("mitigation_focus") or [])
            if mitigation_focus:
                lines.append("- mitigation_focus:")
                for item in mitigation_focus[:3]:
                    lines.append(
                        f"  - {str(item.get('code') or 'unknown')}: {str(item.get('summary') or 'n/a')}"
                    )
        mitigation_review_summary = dict(focus.get("mitigation_review_summary") or {})
        if mitigation_review_summary:
            lines.append(
                "- mitigation_review_summary: "
                f"primary={str(mitigation_review_summary.get('primary_action_code') or 'unknown')}/"
                f"{str(mitigation_review_summary.get('primary_action_status') or 'unknown')}"
            )
            for item in list(mitigation_review_summary.get("items") or [])[:3]:
                lines.append(
                    "  - "
                    f"{str(item.get('code') or 'unknown')}: "
                    f"status={str(item.get('status') or 'unknown')} | "
                    f"mode={str(item.get('review_mode') or 'unknown')} | "
                    f"constraint={str(item.get('current_constraint') or 'none')} | "
                    f"command={str(item.get('command') or 'n/a')}"
                )
        confirm_cluster = dict(focus.get("confirm_loss_cluster_summary") or {})
        if confirm_cluster:
            top_symbols = ", ".join(
                f"{str(item.get('symbol') or 'UNKNOWN')} "
                f"({int(item.get('loss_trade_count', 0) or 0)} / {float(item.get('negative_r', 0.0) or 0.0):.4f}R)"
                for item in list(confirm_cluster.get("top_symbols") or [])[:3]
            )
            top_wave = dict((confirm_cluster.get("top_waves") or [None])[0] or {})
            lines.append(
                f"- confirm_loss_cluster: losses={int(confirm_cluster.get('loss_trade_count', 0) or 0)}, "
                f"median_held_bars={float(confirm_cluster.get('median_held_bars', 0.0) or 0.0):.0f}, "
                f"p75_held_bars={int(confirm_cluster.get('p75_held_bars', 0) or 0)}, "
                f"top_wave={str(top_wave.get('closed_ts') or 'n/a')}/{int(top_wave.get('loss_trade_count', 0) or 0)}, "
                f"top_symbols={top_symbols or 'n/a'}"
            )
        entry_timing_profile = dict(focus.get("entry_timing_loss_profile") or {})
        if entry_timing_profile:
            confirm_profile = dict(entry_timing_profile.get("confirm") or {})
            non_confirm_profile = dict(entry_timing_profile.get("non_confirm") or {})
            lines.append(
                f"- entry_timing_loss_profile: dominant={str(entry_timing_profile.get('dominant_loss_cohort') or 'unknown')}, "
                f"confirm_share={float(entry_timing_profile.get('confirm_loss_share', 0.0) or 0.0):.2%}, "
                f"confirm_negative_r_share={float(entry_timing_profile.get('confirm_negative_r_share', 0.0) or 0.0):.2%}, "
                f"held_gap={float(entry_timing_profile.get('held_bar_gap_confirm_minus_non_confirm', 0.0) or 0.0):+.0f} bars, "
                f"confirm={int(confirm_profile.get('loss_trade_count', 0) or 0)}/"
                f"{float(confirm_profile.get('negative_r', 0.0) or 0.0):.4f}R, "
                f"non_confirm={int(non_confirm_profile.get('loss_trade_count', 0) or 0)}/"
                f"{float(non_confirm_profile.get('negative_r', 0.0) or 0.0):.4f}R"
            )
        priority_summary = dict(focus.get("entry_timing_priority_summary") or {})
        if priority_summary:
            lines.append(
                f"- entry_timing_priority: primary={str(priority_summary.get('primary_focus_code') or 'unknown')} / "
                f"{str(priority_summary.get('primary_summary') or 'n/a')} | "
                f"secondary={str(priority_summary.get('secondary_focus_code') or 'unknown')} / "
                f"{str(priority_summary.get('secondary_summary') or 'n/a')}"
            )
        execution_plan = dict(focus.get("mitigation_execution_plan") or {})
        if execution_plan:
            lines.append(
                f"- mitigation_execution_plan: primary={str(execution_plan.get('primary_focus_label') or 'unknown')}/"
                f"{str(execution_plan.get('primary_status') or 'unknown')} | "
                f"secondary={str(execution_plan.get('secondary_focus_label') or 'none')}/"
                f"{str(execution_plan.get('secondary_status') or 'none')}"
            )
        post_patch = dict(focus.get("post_patch_sample_summary") or {})
        if post_patch:
            top_symbols = ", ".join(
                f"{str(item.get('symbol') or 'UNKNOWN')} ({int(item.get('trade_count', 0) or 0)})"
                for item in list(post_patch.get("top_symbols") or [])[:3]
            )
            lines.append(
                f"- post_patch_sample: {int(post_patch.get('closed_trade_count', 0) or 0)}/"
                f"{int(post_patch.get('target_closed_trades', 0) or 0)} | "
                f"ready={bool(post_patch.get('ready_for_replay_refresh', False))} | "
                f"stop_loss={float(post_patch.get('stop_loss_share', 0.0) or 0.0):.0%} | "
                f"confirm_loss={float(post_patch.get('confirm_named_loss_share', 0.0) or 0.0):.0%} | "
                f"median_held_bars={float(post_patch.get('median_held_bars', 0.0) or 0.0):.0f}"
                + (f" | top_symbols={top_symbols}" if top_symbols else "")
            )
        live_eligible_post_patch = dict(focus.get("live_eligible_post_patch_sample_summary") or {})
        if live_eligible_post_patch:
            eligible_top_symbols = ", ".join(
                f"{str(item.get('symbol') or 'UNKNOWN')} ({int(item.get('trade_count', 0) or 0)})"
                for item in list(live_eligible_post_patch.get("top_symbols") or [])[:3]
            )
            lines.append(
                f"- live_eligible_post_patch_sample: {int(live_eligible_post_patch.get('closed_trade_count', 0) or 0)}/"
                f"{int(live_eligible_post_patch.get('target_closed_trades', 0) or 0)} | "
                f"contract={str(live_eligible_post_patch.get('contract_scope') or 'none')} | "
                f"ready={bool(live_eligible_post_patch.get('ready_for_replay_refresh', False))} | "
                f"stop_loss={float(live_eligible_post_patch.get('stop_loss_share', 0.0) or 0.0):.0%} | "
                f"p5={float(live_eligible_post_patch.get('replay_p5_r', 0.0) or 0.0):+.2f}R | "
                f"maxDD={float(live_eligible_post_patch.get('replay_max_drawdown_r', 0.0) or 0.0):.2f}R"
                + (f" | top_symbols={eligible_top_symbols}" if eligible_top_symbols else "")
            )
        historical_contract = dict(focus.get("historical_execution_contract_proof_summary") or {})
        if historical_contract:
            historical_top_symbols = ", ".join(
                f"{str(item.get('symbol') or 'UNKNOWN')} ({int(item.get('trade_count', 0) or 0)})"
                for item in list(historical_contract.get("top_symbols") or [])[:3]
            )
            lines.append(
                f"- historical_execution_contract_proof: {int(historical_contract.get('closed_trade_count', 0) or 0)}/"
                f"{int(historical_contract.get('target_closed_trades', 0) or 0)} | "
                f"lookback={int(historical_contract.get('lookback_days', 0) or 0)}d | "
                f"advisory_only={bool(historical_contract.get('advisory_only', False))} | "
                f"stop_loss={float(historical_contract.get('stop_loss_share', 0.0) or 0.0):.0%} | "
                f"p5={float(historical_contract.get('replay_p5_r', 0.0) or 0.0):+.2f}R | "
                f"maxDD={float(historical_contract.get('replay_max_drawdown_r', 0.0) or 0.0):.2f}R"
                + (f" | top_symbols={historical_top_symbols}" if historical_top_symbols else "")
            )
        historical_walk_forward_execution = dict(focus.get("historical_walk_forward_execution_contract_proof_summary") or {})
        if historical_walk_forward_execution:
            walk_forward_execution_symbols = ", ".join(
                f"{str(item.get('symbol') or 'UNKNOWN')} ({int(item.get('closed_trade_count', 0) or 0)})"
                for item in list(historical_walk_forward_execution.get("symbol_summaries") or [])[:3]
            )
            lines.append(
                f"- historical_walk_forward_execution: {int(historical_walk_forward_execution.get('closed_trade_count', 0) or 0)}/"
                f"{int(historical_walk_forward_execution.get('target_closed_trades', 0) or 0)} | "
                f"advisory_only={bool(historical_walk_forward_execution.get('advisory_only', False))} | "
                f"stop_loss={float(historical_walk_forward_execution.get('stop_loss_share', 0.0) or 0.0):.0%} | "
                f"p5={float(historical_walk_forward_execution.get('replay_p5_r', 0.0) or 0.0):+.2f}R | "
                f"maxDD={float(historical_walk_forward_execution.get('replay_max_drawdown_r', 0.0) or 0.0):.2f}R"
                + (f" | symbol_closes={walk_forward_execution_symbols}" if walk_forward_execution_symbols else "")
            )
        historical_walk_forward_strategy = dict(focus.get("historical_walk_forward_strategy_proof_summary") or {})
        if historical_walk_forward_strategy:
            walk_forward_strategy_symbols = ", ".join(
                f"{str(item.get('symbol') or 'UNKNOWN')} ({int(item.get('closed_trade_count', 0) or 0)})"
                for item in list(historical_walk_forward_strategy.get("symbol_summaries") or [])[:3]
            )
            lines.append(
                f"- historical_walk_forward_strategy: {int(historical_walk_forward_strategy.get('closed_trade_count', 0) or 0)}/"
                f"{int(historical_walk_forward_strategy.get('target_closed_trades', 0) or 0)} | "
                f"advisory_only={bool(historical_walk_forward_strategy.get('advisory_only', False))} | "
                f"stop_loss={float(historical_walk_forward_strategy.get('stop_loss_share', 0.0) or 0.0):.0%} | "
                f"p5={float(historical_walk_forward_strategy.get('replay_p5_r', 0.0) or 0.0):+.2f}R | "
                f"maxDD={float(historical_walk_forward_strategy.get('replay_max_drawdown_r', 0.0) or 0.0):.2f}R"
                + (f" | symbol_closes={walk_forward_strategy_symbols}" if walk_forward_strategy_symbols else "")
            )
        historical_walk_forward_trend = dict(focus.get("historical_walk_forward_trend_proof_summary") or {})
        if historical_walk_forward_trend:
            walk_forward_trend_symbols = ", ".join(
                f"{str(item.get('symbol') or 'UNKNOWN')} ({int(item.get('closed_trade_count', 0) or 0)})"
                for item in list(historical_walk_forward_trend.get("symbol_summaries") or [])[:3]
            )
            lines.append(
                f"- historical_walk_forward_trend: {int(historical_walk_forward_trend.get('closed_trade_count', 0) or 0)}/"
                f"{int(historical_walk_forward_trend.get('target_closed_trades', 0) or 0)} | "
                f"advisory_only={bool(historical_walk_forward_trend.get('advisory_only', False))} | "
                f"stop_loss={float(historical_walk_forward_trend.get('stop_loss_share', 0.0) or 0.0):.0%} | "
                f"p5={float(historical_walk_forward_trend.get('replay_p5_r', 0.0) or 0.0):+.2f}R | "
                f"maxDD={float(historical_walk_forward_trend.get('replay_max_drawdown_r', 0.0) or 0.0):.2f}R"
                + (f" | symbol_closes={walk_forward_trend_symbols}" if walk_forward_trend_symbols else "")
            )
    if decision.get("breached_thresholds"):
        lines.append("")
        lines.append("## Runtime Decision Thresholds")
        lines.append("")
        for item in list(decision.get("breached_thresholds") or []):
            lines.append(
                f"- {str(item.get('code') or 'unknown')}: "
                f"value={item.get('value')} threshold={item.get('threshold')}"
            )
    lines.append("")
    lines.append("## Next Steps")
    lines.append("")
    for item in payload.get("next_steps") or []:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Raw Payload")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    lines.append("```")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_confirm_loss_cluster_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    focus = dict(payload.get("approval_template_focus") or {})
    downside = dict(focus.get("downside_profile") or {})
    cluster = dict(focus.get("confirm_loss_cluster_summary") or {})
    lines: list[str] = []
    lines.append("# Confirm Loss Cluster Review")
    lines.append("")
    lines.append(f"- generated_at: {payload.get('generated_at') or 'n/a'}")
    lines.append(f"- symbol: {payload.get('symbol') or 'n/a'}")
    lines.append(f"- focus_symbol: {focus.get('focus_symbol') or 'n/a'}")
    lines.append(f"- worst_scenario: {focus.get('worst_scenario') or 'n/a'}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(
        f"- primary_failure_mode: {downside.get('primary_failure_mode') or 'unknown'} / "
        f"{downside.get('primary_failure_summary') or 'n/a'}"
    )
    lines.append(
        f"- confirm_losses: {int(cluster.get('loss_trade_count', 0) or 0)} / "
        f"{int(downside.get('loss_trade_count', 0) or 0)} "
        f"({float(downside.get('confirm_named_loss_share', 0.0) or 0.0):.2%})"
    )
    lines.append(
        f"- held_bars: median={float(cluster.get('median_held_bars', 0.0) or 0.0):.0f} / "
        f"p75={int(cluster.get('p75_held_bars', 0) or 0)}"
    )
    lines.append(
        f"- worst_wave_share: {float(downside.get('top_loss_wave_share_of_losses', 0.0) or 0.0):.2%}"
    )
    held_bar_bands = dict(cluster.get("held_bar_bands") or {})
    if held_bar_bands:
        lines.append(
            f"- held_bar_bands: >240={int(held_bar_bands.get('over_240', 0) or 0)}, "
            f">1000={int(held_bar_bands.get('over_1000', 0) or 0)}, "
            f">2000={int(held_bar_bands.get('over_2000', 0) or 0)}"
        )
    lines.append("")
    lines.append("## Top Symbols")
    lines.append("")
    top_symbols = list(cluster.get("top_symbols") or [])
    if top_symbols:
        for item in top_symbols:
            lines.append(
                f"- {str(item.get('symbol') or 'UNKNOWN')}: "
                f"{int(item.get('loss_trade_count', 0) or 0)} losses / "
                f"{float(item.get('negative_r', 0.0) or 0.0):.4f}R / "
                f"median={float(item.get('median_held_bars', 0.0) or 0.0):.0f} bars / "
                f"p75={int(item.get('p75_held_bars', 0) or 0)} bars"
            )
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Loss Waves")
    lines.append("")
    top_waves = list(cluster.get("top_waves") or [])
    if top_waves:
        for item in top_waves:
            top_symbols_line = ", ".join(
                f"{str(symbol_item.get('symbol') or 'UNKNOWN')}({int(symbol_item.get('loss_trade_count', 0) or 0)})"
                for symbol_item in list(item.get("top_symbols") or [])[:3]
            )
            lines.append(
                f"- {str(item.get('closed_ts') or 'n/a')}: "
                f"{int(item.get('loss_trade_count', 0) or 0)} confirm losses / "
                f"{float(item.get('negative_r', 0.0) or 0.0):.4f}R / "
                f"top={top_symbols_line or 'n/a'}"
            )
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Review Priority")
    lines.append("")
    review_priority = list(cluster.get("review_priority") or [])
    if review_priority:
        for item in review_priority:
            lines.append(
                f"- {str(item.get('symbol') or 'UNKNOWN')}: "
                f"{float(item.get('negative_r', 0.0) or 0.0):.4f}R / "
                f"{int(item.get('loss_trade_count', 0) or 0)} losses / "
                f"median={float(item.get('median_held_bars', 0.0) or 0.0):.0f} bars"
            )
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Next Step")
    lines.append("")
    lines.append(
        "- Prioritize `range_entry_timing_review` before any reopen decision; "
        "treat `shadow_fail_fast_review` as the next shadow-only mitigation."
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_entry_timing_loss_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    focus = dict(payload.get("approval_template_focus") or {})
    profile = dict(focus.get("entry_timing_loss_profile") or {})
    priority = dict(focus.get("entry_timing_priority_summary") or {})
    confirm = dict(profile.get("confirm") or {})
    non_confirm = dict(profile.get("non_confirm") or {})
    lines: list[str] = []
    lines.append("# Entry Timing Loss Review")
    lines.append("")
    lines.append(f"- generated_at: {payload.get('generated_at') or 'n/a'}")
    lines.append(f"- symbol: {payload.get('symbol') or 'n/a'}")
    lines.append(f"- focus_symbol: {focus.get('focus_symbol') or 'n/a'}")
    lines.append(f"- worst_scenario: {focus.get('worst_scenario') or 'n/a'}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- dominant_loss_cohort: {profile.get('dominant_loss_cohort') or 'unknown'}")
    lines.append(f"- summary: {profile.get('summary') or 'n/a'}")
    lines.append(
        f"- confirm_loss_share: {float(profile.get('confirm_loss_share', 0.0) or 0.0):.2%} / "
        f"confirm_negative_r_share: {float(profile.get('confirm_negative_r_share', 0.0) or 0.0):.2%}"
    )
    lines.append(
        f"- held_bar_gap_confirm_minus_non_confirm: {float(profile.get('held_bar_gap_confirm_minus_non_confirm', 0.0) or 0.0):+.0f} bars"
    )
    if priority:
        lines.append(
            f"- priority: primary={str(priority.get('primary_focus_code') or 'unknown')} / "
            f"{str(priority.get('primary_summary') or 'n/a')}"
        )
        lines.append(
            f"- secondary: {str(priority.get('secondary_focus_code') or 'unknown')} / "
            f"{str(priority.get('secondary_summary') or 'n/a')}"
        )
    execution_plan = dict(focus.get("mitigation_execution_plan") or {})
    if execution_plan:
        lines.append(
            f"- execution_plan: primary={str(execution_plan.get('primary_focus_label') or 'unknown')} / "
            f"{str(execution_plan.get('primary_status') or 'unknown')} / "
            f"cmd={str(execution_plan.get('primary_command') or 'n/a')}"
        )
        if str(execution_plan.get("secondary_focus_label") or "").strip():
            lines.append(
                f"- execution_plan_secondary: {str(execution_plan.get('secondary_focus_label') or 'unknown')} / "
                f"{str(execution_plan.get('secondary_status') or 'unknown')} / "
                f"cmd={str(execution_plan.get('secondary_command') or 'n/a')}"
            )
    lines.append("")
    lines.append("## Confirm Cohort")
    lines.append("")
    lines.append(
        f"- losses: {int(confirm.get('loss_trade_count', 0) or 0)} / "
        f"{float(confirm.get('negative_r', 0.0) or 0.0):.4f}R / "
        f"median={float(confirm.get('median_held_bars', 0.0) or 0.0):.0f} bars / "
        f"p75={int(confirm.get('p75_held_bars', 0) or 0)} bars"
    )
    for item in list(confirm.get("top_symbols") or [])[:3]:
        lines.append(
            f"- {str(item.get('symbol') or 'UNKNOWN')}: "
            f"{int(item.get('loss_trade_count', 0) or 0)} losses / "
            f"{float(item.get('negative_r', 0.0) or 0.0):.4f}R"
        )
    lines.append("")
    lines.append("## Non-Confirm Cohort")
    lines.append("")
    lines.append(
        f"- losses: {int(non_confirm.get('loss_trade_count', 0) or 0)} / "
        f"{float(non_confirm.get('negative_r', 0.0) or 0.0):.4f}R / "
        f"median={float(non_confirm.get('median_held_bars', 0.0) or 0.0):.0f} bars / "
        f"p75={int(non_confirm.get('p75_held_bars', 0) or 0)} bars"
    )
    for item in list(non_confirm.get("top_symbols") or [])[:3]:
        lines.append(
            f"- {str(item.get('symbol') or 'UNKNOWN')}: "
            f"{int(item.get('loss_trade_count', 0) or 0)} losses / "
            f"{float(item.get('negative_r', 0.0) or 0.0):.4f}R"
        )
    lines.append("")
    lines.append("## Next Step")
    lines.append("")
    lines.append("- Prioritize `range_entry_timing_review`; confirm cohort dominates the replay downside.")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_runtime_mitigation_plan_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    focus = dict(payload.get("approval_template_focus") or {})
    execution_plan = dict(focus.get("mitigation_execution_plan") or {})
    review_summary = dict(focus.get("mitigation_review_summary") or {})
    lines: list[str] = []
    lines.append("# Runtime Mitigation Plan")
    lines.append("")
    lines.append(f"- generated_at: {payload.get('generated_at') or 'n/a'}")
    lines.append(f"- symbol: {payload.get('symbol') or 'n/a'}")
    lines.append(f"- runtime_status: {payload.get('status') or 'n/a'}")
    lines.append("")
    lines.append("## Plan")
    lines.append("")
    if execution_plan:
        lines.append(
            f"- 1st: {execution_plan.get('primary_focus_label') or 'n/a'} / "
            f"{execution_plan.get('primary_status') or 'n/a'}"
        )
        lines.append(f"  command: {execution_plan.get('primary_command') or 'n/a'}")
        if str(execution_plan.get("secondary_focus_label") or "").strip():
            lines.append(
                f"- 2nd: {execution_plan.get('secondary_focus_label') or 'n/a'} / "
                f"{execution_plan.get('secondary_status') or 'n/a'}"
            )
            lines.append(f"  command: {execution_plan.get('secondary_command') or 'n/a'}")
    else:
        lines.append("- no mitigation execution plan available")
    lines.append("")
    lines.append("## Review Items")
    lines.append("")
    for item in list(review_summary.get("items") or []):
        lines.append(
            f"- {str(item.get('code') or 'unknown')}: "
            f"status={str(item.get('status') or 'unknown')} / "
            f"mode={str(item.get('review_mode') or 'unknown')} / "
            f"constraint={str(item.get('current_constraint') or 'none')} / "
            f"command={str(item.get('command') or 'n/a')}"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _report_path_value(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def main() -> int:
    args = parse_args()
    stage = _read_stage(_resolve_root_path(args.stage_file))
    payload = _build_payload(
        stage,
        symbol=args.symbol,
        universe=args.universe,
        days=args.days,
    )
    payload = _attach_approval_template_focus(
        payload,
        stage=stage,
        symbol=args.symbol,
        base_url=args.base_url,
    )
    payload = _apply_runtime_decision(payload)
    if not args.no_write_report:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        report_path = ROOT_DIR / args.report_dir / f"runtime_signoff_review_{args.symbol.upper()}_{ts}.md"
        _write_report(report_path, payload)
        payload["report_path"] = _report_path_value(report_path)
        confirm_cluster = dict(dict(payload.get("approval_template_focus") or {}).get("confirm_loss_cluster_summary") or {})
        if confirm_cluster:
            confirm_report_path = (
                ROOT_DIR
                / args.report_dir
                / f"confirm_loss_cluster_review_{args.symbol.upper()}_{ts}.md"
            )
            _write_confirm_loss_cluster_report(confirm_report_path, payload)
            payload["confirm_loss_cluster_report_path"] = _report_path_value(confirm_report_path)
        entry_timing_profile = dict(dict(payload.get("approval_template_focus") or {}).get("entry_timing_loss_profile") or {})
        if entry_timing_profile:
            entry_timing_report_path = (
                ROOT_DIR
                / args.report_dir
                / f"entry_timing_loss_review_{args.symbol.upper()}_{ts}.md"
            )
            _write_entry_timing_loss_report(entry_timing_report_path, payload)
            payload["entry_timing_loss_report_path"] = _report_path_value(entry_timing_report_path)
        mitigation_execution_plan = dict(dict(payload.get("approval_template_focus") or {}).get("mitigation_execution_plan") or {})
        if mitigation_execution_plan:
            mitigation_plan_report_path = (
                ROOT_DIR
                / args.report_dir
                / f"runtime_mitigation_plan_{args.symbol.upper()}_{ts}.md"
            )
            _write_runtime_mitigation_plan_report(mitigation_plan_report_path, payload)
            payload["runtime_mitigation_plan_report_path"] = _report_path_value(mitigation_plan_report_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
