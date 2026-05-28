#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text
from scripts.run_btc_flip_rotation_search import _INTERVAL_MS, _csv, _load_bars, Bar, FeatureSet
from scripts.run_scenario_repair_rotation_backtest import _map_closed_indices
from scripts.run_market_state_rotation_v6_backtest import (
    MarketStateConfig,
    _carry_rate_per_bar,
    _counter_payload,
    _stdout_result_summary,
    backtest_config,
)


DEFAULT_SOURCE_REPORT = (
    "reports/validation/market_state_rotation_v6_backtest/"
    "market_state_rotation_v6_BTCUSDT_5m_365d_latest.json"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Walk-forward validation for market-state rotation v6. "
            "Each fold selects a candidate on the train window and evaluates it on the next unseen window."
        )
    )
    parser.add_argument("--source-report", default=DEFAULT_SOURCE_REPORT)
    parser.add_argument("--report-dir", default="reports/validation/market_state_rotation_v6_backtest")
    parser.add_argument("--symbol", default="")
    parser.add_argument("--exec-interval", default="")
    parser.add_argument("--scenario-intervals", default="")
    parser.add_argument("--load-days", type=int, default=1825)
    parser.add_argument("--train-days", type=int, default=365)
    parser.add_argument("--test-days", type=int, default=90)
    parser.add_argument("--step-days", type=int, default=90)
    parser.add_argument("--top-n", type=int, default=8)
    parser.add_argument("--fold-offset", type=int, default=0)
    parser.add_argument("--fold-limit", type=int, default=0)
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument("--funding-bps-per-8h", type=float, default=0.0)
    parser.add_argument("--borrow-bps-per-day", type=float, default=0.0)
    parser.add_argument("--one-way-trim-min-adverse-reaction", type=float, default=None)
    parser.add_argument("--one-way-trim-cooldown-bars", type=int, default=None)
    parser.add_argument("--one-way-trim-retire-same-zone", action="store_true")
    parser.add_argument("--one-way-trim-same-side-cooldown-bars", type=int, default=None)
    parser.add_argument("--one-way-trim-cluster-guard-count", type=int, default=None)
    parser.add_argument("--one-way-trim-cluster-window-bars", type=int, default=None)
    parser.add_argument("--one-way-trim-cluster-cooldown-bars", type=int, default=None)
    parser.add_argument("--one-way-trim-context-guard-count", type=int, default=None)
    parser.add_argument("--one-way-trim-context-window-bars", type=int, default=None)
    parser.add_argument("--one-way-trim-context-cooldown-bars", type=int, default=None)
    parser.add_argument("--one-way-trim-context-full-exit", action="store_true")
    parser.add_argument(
        "--one-way-trim-context-after-selection",
        action="store_true",
        help="Select alpha candidates without context quarantine, then apply it only as a test-time risk overlay.",
    )
    parser.add_argument("--one-way-trim-full-exit-min-one-way-score", type=float, default=None)
    parser.add_argument("--one-way-trim-full-exit-min-score-diff", type=int, default=None)
    parser.add_argument(
        "--one-way-trim-full-exit-after-selection",
        action="store_true",
        help="Select alpha candidates without full-exit trim, then apply it only as a test-time risk overlay.",
    )
    parser.add_argument("--trend-idle-probe-units", type=float, default=None)
    parser.add_argument("--trend-idle-min-score", type=int, default=None)
    parser.add_argument("--trend-idle-min-reason-stack", type=int, default=None)
    parser.add_argument("--trend-idle-cooldown-bars", type=int, default=None)
    parser.add_argument("--trend-idle-max-extension-atr", type=float, default=None)
    parser.add_argument("--equity-circuit-breaker-drawdown-pct", type=float, default=None)
    parser.add_argument("--equity-circuit-breaker-pause-bars", type=int, default=None)
    parser.add_argument(
        "--equity-circuit-breaker-after-selection",
        action="store_true",
        help="Select alpha candidates without the circuit breaker, then apply it only as a test-time risk overlay.",
    )
    parser.add_argument("--equity-soft-circuit-drawdown-pct", type=float, default=None)
    parser.add_argument("--equity-soft-circuit-cooldown-bars", type=int, default=None)
    parser.add_argument("--equity-soft-circuit-size-mult", type=float, default=None)
    parser.add_argument("--equity-soft-circuit-force-flat", action="store_true")
    parser.add_argument(
        "--equity-soft-circuit-after-selection",
        action="store_true",
        help="Select alpha candidates without the soft circuit, then apply it only as a test-time risk overlay.",
    )
    parser.add_argument("--one-way-reversal-switch-units", type=float, default=None)
    parser.add_argument("--one-way-reversal-min-score-edge", type=int, default=None)
    parser.add_argument("--one-way-reversal-cooldown-bars", type=int, default=None)
    parser.add_argument("--one-way-reversal-allow-scenario-override", action="store_true")
    parser.add_argument("--one-way-reversal-allow-score-override", action="store_true")
    parser.add_argument("--one-way-impulse-probe-units", type=float, default=None)
    parser.add_argument("--one-way-impulse-min-one-way-score", type=float, default=None)
    parser.add_argument("--one-way-impulse-min-score-diff", type=int, default=None)
    parser.add_argument("--one-way-impulse-cooldown-bars", type=int, default=None)
    parser.add_argument("--one-way-impulse-max-extension-atr", type=float, default=None)
    parser.add_argument("--base-entry-max-extension-atr", type=float, default=None)
    parser.add_argument("--base-entry-reduce-extension-atr", type=float, default=None)
    parser.add_argument("--base-entry-reduce-size-mult", type=float, default=None)
    parser.add_argument("--base-entry-reduce-promote-reaction", type=float, default=None)
    parser.add_argument("--base-entry-reduce-max-trend-strength", type=float, default=None)
    parser.add_argument(
        "--base-entry-reduce-after-selection",
        action="store_true",
        help="Select alpha candidates without late-base reduction, then apply it only as a test-time risk overlay.",
    )
    parser.add_argument(
        "--include-no-impulse-candidates",
        action="store_true",
        help="When impulse overrides are enabled, also keep otherwise identical candidates without impulse probes.",
    )
    parser.add_argument(
        "--impulse-selection-score-penalty",
        type=float,
        default=0.0,
        help="Optional train-selection penalty for impulse-probe candidates; use only as a promotion gate.",
    )
    parser.add_argument(
        "--selection-flag-penalty",
        type=float,
        default=0.10,
        help="Penalty per train-window distribution flag when ranking walk-forward candidates.",
    )
    parser.add_argument(
        "--selection-score-cap",
        type=float,
        default=0.0,
        help=(
            "Optional cap applied only to the train-window score before candidate ranking. "
            "Use this to reduce over-trust in unusually high in-sample scores."
        ),
    )
    parser.add_argument("--min-periods", type=int, default=5000)
    parser.add_argument("--cache-dir", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _material_config_key(config: MarketStateConfig) -> str:
    payload = {
        key: value
        for key, value in asdict(config).items()
        if key not in {"model_id", "max_battle_bars"}
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _configs_from_source(report: dict[str, Any], *, top_n: int) -> list[MarketStateConfig]:
    candidates: list[dict[str, Any]] = []
    for key in ("best_by_method_score", "best_by_raw_return"):
        result = report.get(key)
        if isinstance(result, dict) and isinstance(result.get("config"), dict):
            candidates.append(result)
    for section in ("top_results", "top_results_by_return", "all_results"):
        for result in report.get(section) or []:
            if isinstance(result, dict) and isinstance(result.get("config"), dict):
                candidates.append(result)

    configs: list[MarketStateConfig] = []
    seen: set[str] = set()
    for result in candidates:
        try:
            config = MarketStateConfig(**result["config"])
        except TypeError:
            continue
        key = _material_config_key(config)
        if key in seen:
            continue
        seen.add(key)
        configs.append(config)
        if len(configs) >= max(1, int(top_n)):
            break
    return configs


def _apply_config_overrides(
    config: MarketStateConfig,
    args: argparse.Namespace,
    *,
    include_impulse: bool = True,
    include_equity_circuit: bool = True,
    include_equity_soft_circuit: bool = True,
    include_full_exit: bool = True,
    include_base_reduce: bool = True,
    include_context_quarantine: bool = True,
) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    if args.one_way_trim_min_adverse_reaction is not None:
        value = max(0.0, float(args.one_way_trim_min_adverse_reaction))
        updates["one_way_trim_min_adverse_reaction"] = value
        suffix_parts.append(f"wfOwTrimMin{value:g}")
    if args.one_way_trim_cooldown_bars is not None:
        value = max(0, int(args.one_way_trim_cooldown_bars))
        updates["one_way_trim_cooldown_bars"] = value
        suffix_parts.append(f"wfOwTrimCool{value}")
    if bool(args.one_way_trim_retire_same_zone):
        updates["one_way_trim_retire_same_zone"] = True
        suffix_parts.append("wfOwTrimRetire1")
    if args.one_way_trim_same_side_cooldown_bars is not None:
        value = max(0, int(args.one_way_trim_same_side_cooldown_bars))
        updates["one_way_trim_same_side_cooldown_bars"] = value
        suffix_parts.append(f"wfOwTrimSideCool{value}")
    if args.one_way_trim_cluster_guard_count is not None:
        value = max(0, int(args.one_way_trim_cluster_guard_count))
        updates["one_way_trim_cluster_guard_count"] = value
        suffix_parts.append(f"wfOwTrimCluster{value}")
    if args.one_way_trim_cluster_window_bars is not None:
        value = max(1, int(args.one_way_trim_cluster_window_bars))
        updates["one_way_trim_cluster_window_bars"] = value
        suffix_parts.append(f"wfOwTrimClusterWin{value}")
    if args.one_way_trim_cluster_cooldown_bars is not None:
        value = max(0, int(args.one_way_trim_cluster_cooldown_bars))
        updates["one_way_trim_cluster_cooldown_bars"] = value
        suffix_parts.append(f"wfOwTrimClusterCool{value}")
    if include_context_quarantine and args.one_way_trim_context_guard_count is not None:
        value = max(0, int(args.one_way_trim_context_guard_count))
        updates["one_way_trim_context_guard_count"] = value
        suffix_parts.append(f"wfOwTrimCtxQ{value}")
    if include_context_quarantine and args.one_way_trim_context_window_bars is not None:
        value = max(1, int(args.one_way_trim_context_window_bars))
        updates["one_way_trim_context_window_bars"] = value
        suffix_parts.append(f"wfOwTrimCtxQWin{value}")
    if include_context_quarantine and args.one_way_trim_context_cooldown_bars is not None:
        value = max(0, int(args.one_way_trim_context_cooldown_bars))
        updates["one_way_trim_context_cooldown_bars"] = value
        suffix_parts.append(f"wfOwTrimCtxQCool{value}")
    if include_context_quarantine and bool(args.one_way_trim_context_full_exit):
        updates["one_way_trim_context_full_exit"] = True
        suffix_parts.append("wfOwTrimCtxQExit1")
    if include_full_exit and args.one_way_trim_full_exit_min_one_way_score is not None:
        value = max(0.0, float(args.one_way_trim_full_exit_min_one_way_score))
        updates["one_way_trim_full_exit_min_one_way_score"] = value
        suffix_parts.append(f"wfOwTrimFullExit{value:g}")
    if include_full_exit and args.one_way_trim_full_exit_min_score_diff is not None:
        value = max(0, int(args.one_way_trim_full_exit_min_score_diff))
        updates["one_way_trim_full_exit_min_score_diff"] = value
        suffix_parts.append(f"wfOwTrimFullExitDiff{value}")
    if args.trend_idle_probe_units is not None:
        value = max(0.0, float(args.trend_idle_probe_units))
        updates["trend_idle_probe_units"] = min(value, config.max_possible_units)
        suffix_parts.append(f"wfIdleProbe{value:g}")
    if args.trend_idle_min_score is not None:
        value = int(args.trend_idle_min_score)
        updates["trend_idle_min_score"] = value
        suffix_parts.append(f"wfIdleScore{value}")
    if args.trend_idle_min_reason_stack is not None:
        value = max(0, int(args.trend_idle_min_reason_stack))
        updates["trend_idle_min_reason_stack"] = value
        suffix_parts.append(f"wfIdleStack{value}")
    if args.trend_idle_cooldown_bars is not None:
        value = max(0, int(args.trend_idle_cooldown_bars))
        updates["trend_idle_cooldown_bars"] = value
        suffix_parts.append(f"wfIdleCool{value}")
    if args.trend_idle_max_extension_atr is not None:
        value = max(0.1, float(args.trend_idle_max_extension_atr))
        updates["trend_idle_max_extension_atr"] = value
        suffix_parts.append(f"wfIdleExt{value:g}")
    if include_equity_circuit and args.equity_circuit_breaker_drawdown_pct is not None:
        value = max(0.0, float(args.equity_circuit_breaker_drawdown_pct))
        updates["equity_circuit_breaker_drawdown_pct"] = value
        suffix_parts.append(f"wfEqCb{value:g}")
    if include_equity_circuit and args.equity_circuit_breaker_pause_bars is not None:
        value = max(0, int(args.equity_circuit_breaker_pause_bars))
        updates["equity_circuit_breaker_pause_bars"] = value
        suffix_parts.append(f"wfEqCbPause{value}")
    if include_equity_soft_circuit and args.equity_soft_circuit_drawdown_pct is not None:
        value = max(0.0, float(args.equity_soft_circuit_drawdown_pct))
        updates["equity_soft_circuit_drawdown_pct"] = value
        suffix_parts.append(f"wfEqSoft{value:g}")
    if include_equity_soft_circuit and args.equity_soft_circuit_cooldown_bars is not None:
        value = max(0, int(args.equity_soft_circuit_cooldown_bars))
        updates["equity_soft_circuit_cooldown_bars"] = value
        suffix_parts.append(f"wfEqSoftCool{value}")
    if include_equity_soft_circuit and args.equity_soft_circuit_size_mult is not None:
        value = min(max(float(args.equity_soft_circuit_size_mult), 0.0), 1.0)
        updates["equity_soft_circuit_size_mult"] = value
        suffix_parts.append(f"wfEqSoftMult{value:g}")
    if include_equity_soft_circuit and bool(args.equity_soft_circuit_force_flat):
        updates["equity_soft_circuit_force_flat"] = True
        suffix_parts.append("wfEqSoftFlat1")
    if args.one_way_reversal_switch_units is not None:
        value = max(0.0, float(args.one_way_reversal_switch_units))
        updates["one_way_reversal_switch_units"] = min(value, config.max_possible_units)
        suffix_parts.append(f"wfOwRev{value:g}")
    if args.one_way_reversal_min_score_edge is not None:
        value = int(args.one_way_reversal_min_score_edge)
        updates["one_way_reversal_min_score_edge"] = value
        suffix_parts.append(f"wfOwRevEdge{value}")
    if args.one_way_reversal_cooldown_bars is not None:
        value = max(0, int(args.one_way_reversal_cooldown_bars))
        updates["one_way_reversal_cooldown_bars"] = value
        suffix_parts.append(f"wfOwRevCool{value}")
    if bool(args.one_way_reversal_allow_scenario_override):
        updates["one_way_reversal_allow_scenario_override"] = True
        suffix_parts.append("wfOwRevScn1")
    if bool(args.one_way_reversal_allow_score_override):
        updates["one_way_reversal_allow_score_override"] = True
        suffix_parts.append("wfOwRevScore1")
    if include_impulse:
        if args.one_way_impulse_probe_units is not None:
            value = max(0.0, float(args.one_way_impulse_probe_units))
            updates["one_way_impulse_probe_units"] = min(value, config.max_possible_units)
            suffix_parts.append(f"wfOwImp{value:g}")
        if args.one_way_impulse_min_one_way_score is not None:
            value = max(0.0, float(args.one_way_impulse_min_one_way_score))
            updates["one_way_impulse_min_one_way_score"] = value
            suffix_parts.append(f"wfOwImpScore{value:g}")
        if args.one_way_impulse_min_score_diff is not None:
            value = max(0, int(args.one_way_impulse_min_score_diff))
            updates["one_way_impulse_min_score_diff"] = value
            suffix_parts.append(f"wfOwImpDiff{value}")
        if args.one_way_impulse_cooldown_bars is not None:
            value = max(0, int(args.one_way_impulse_cooldown_bars))
            updates["one_way_impulse_cooldown_bars"] = value
            suffix_parts.append(f"wfOwImpCool{value}")
        if args.one_way_impulse_max_extension_atr is not None:
            value = max(0.1, float(args.one_way_impulse_max_extension_atr))
            updates["one_way_impulse_max_extension_atr"] = value
            suffix_parts.append(f"wfOwImpExt{value:g}")
    if include_base_reduce:
        if args.base_entry_max_extension_atr is not None:
            value = max(0.0, float(args.base_entry_max_extension_atr))
            updates["base_entry_max_extension_atr"] = value
            suffix_parts.append(f"wfBaseExt{value:g}")
        if args.base_entry_reduce_extension_atr is not None:
            value = max(0.0, float(args.base_entry_reduce_extension_atr))
            updates["base_entry_reduce_extension_atr"] = value
            suffix_parts.append(f"wfBaseReduce{value:g}")
        if args.base_entry_reduce_size_mult is not None:
            value = min(max(float(args.base_entry_reduce_size_mult), 0.0), 1.0)
            updates["base_entry_reduce_size_mult"] = value
            suffix_parts.append(f"wfBaseReduceMult{value:g}")
        if args.base_entry_reduce_promote_reaction is not None:
            value = max(0.0, float(args.base_entry_reduce_promote_reaction))
            updates["base_entry_reduce_promote_reaction"] = value
            suffix_parts.append(f"wfBasePromote{value:g}")
        if args.base_entry_reduce_max_trend_strength is not None:
            value = max(0.0, float(args.base_entry_reduce_max_trend_strength))
            updates["base_entry_reduce_max_trend_strength"] = value
            suffix_parts.append(f"wfBaseReduceMaxTrend{value:g}")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _apply_equity_circuit_overlay(config: MarketStateConfig, args: argparse.Namespace) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    if args.equity_circuit_breaker_drawdown_pct is not None:
        value = max(0.0, float(args.equity_circuit_breaker_drawdown_pct))
        updates["equity_circuit_breaker_drawdown_pct"] = value
        suffix_parts.append(f"wfEqCb{value:g}")
    if args.equity_circuit_breaker_pause_bars is not None:
        value = max(0, int(args.equity_circuit_breaker_pause_bars))
        updates["equity_circuit_breaker_pause_bars"] = value
        suffix_parts.append(f"wfEqCbPause{value}")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _apply_equity_soft_circuit_overlay(config: MarketStateConfig, args: argparse.Namespace) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    if args.equity_soft_circuit_drawdown_pct is not None:
        value = max(0.0, float(args.equity_soft_circuit_drawdown_pct))
        updates["equity_soft_circuit_drawdown_pct"] = value
        suffix_parts.append(f"wfEqSoft{value:g}")
    if args.equity_soft_circuit_cooldown_bars is not None:
        value = max(0, int(args.equity_soft_circuit_cooldown_bars))
        updates["equity_soft_circuit_cooldown_bars"] = value
        suffix_parts.append(f"wfEqSoftCool{value}")
    if args.equity_soft_circuit_size_mult is not None:
        value = min(max(float(args.equity_soft_circuit_size_mult), 0.0), 1.0)
        updates["equity_soft_circuit_size_mult"] = value
        suffix_parts.append(f"wfEqSoftMult{value:g}")
    if bool(args.equity_soft_circuit_force_flat):
        updates["equity_soft_circuit_force_flat"] = True
        suffix_parts.append("wfEqSoftFlat1")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _apply_full_exit_overlay(config: MarketStateConfig, args: argparse.Namespace) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    if args.one_way_trim_full_exit_min_one_way_score is not None:
        value = max(0.0, float(args.one_way_trim_full_exit_min_one_way_score))
        updates["one_way_trim_full_exit_min_one_way_score"] = value
        suffix_parts.append(f"wfOwTrimFullExit{value:g}")
    if args.one_way_trim_full_exit_min_score_diff is not None:
        value = max(0, int(args.one_way_trim_full_exit_min_score_diff))
        updates["one_way_trim_full_exit_min_score_diff"] = value
        suffix_parts.append(f"wfOwTrimFullExitDiff{value}")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _apply_base_reduce_overlay(config: MarketStateConfig, args: argparse.Namespace) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    if args.base_entry_max_extension_atr is not None:
        value = max(0.0, float(args.base_entry_max_extension_atr))
        updates["base_entry_max_extension_atr"] = value
        suffix_parts.append(f"wfBaseExt{value:g}")
    if args.base_entry_reduce_extension_atr is not None:
        value = max(0.0, float(args.base_entry_reduce_extension_atr))
        updates["base_entry_reduce_extension_atr"] = value
        suffix_parts.append(f"wfBaseReduce{value:g}")
    if args.base_entry_reduce_size_mult is not None:
        value = min(max(float(args.base_entry_reduce_size_mult), 0.0), 1.0)
        updates["base_entry_reduce_size_mult"] = value
        suffix_parts.append(f"wfBaseReduceMult{value:g}")
    if args.base_entry_reduce_promote_reaction is not None:
        value = max(0.0, float(args.base_entry_reduce_promote_reaction))
        updates["base_entry_reduce_promote_reaction"] = value
        suffix_parts.append(f"wfBasePromote{value:g}")
    if args.base_entry_reduce_max_trend_strength is not None:
        value = max(0.0, float(args.base_entry_reduce_max_trend_strength))
        updates["base_entry_reduce_max_trend_strength"] = value
        suffix_parts.append(f"wfBaseReduceMaxTrend{value:g}")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _apply_context_quarantine_overlay(config: MarketStateConfig, args: argparse.Namespace) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    if args.one_way_trim_context_guard_count is not None:
        value = max(0, int(args.one_way_trim_context_guard_count))
        updates["one_way_trim_context_guard_count"] = value
        suffix_parts.append(f"wfOwTrimCtxQ{value}")
    if args.one_way_trim_context_window_bars is not None:
        value = max(1, int(args.one_way_trim_context_window_bars))
        updates["one_way_trim_context_window_bars"] = value
        suffix_parts.append(f"wfOwTrimCtxQWin{value}")
    if args.one_way_trim_context_cooldown_bars is not None:
        value = max(0, int(args.one_way_trim_context_cooldown_bars))
        updates["one_way_trim_context_cooldown_bars"] = value
        suffix_parts.append(f"wfOwTrimCtxQCool{value}")
    if bool(args.one_way_trim_context_full_exit):
        updates["one_way_trim_context_full_exit"] = True
        suffix_parts.append("wfOwTrimCtxQExit1")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _slice_between(bars: list[Bar], start: datetime, end: datetime) -> list[Bar]:
    return [bar for bar in bars if start <= bar.ts < end]


def _window_feature_sets(
    *,
    exec_bars_all: list[Bar],
    scenario_bars_all: dict[str, list[Bar]],
    start: datetime,
    end: datetime,
    scenario_intervals: list[str],
) -> tuple[FeatureSet, dict[str, FeatureSet], dict[str, list[int]], dict[str, Any]]:
    exec_bars = _slice_between(exec_bars_all, start, end)
    features = FeatureSet(exec_bars)
    scenario_features: dict[str, FeatureSet] = {}
    scenario_maps: dict[str, list[int]] = {}
    for interval in scenario_intervals:
        scenario_start = start - timedelta(milliseconds=_INTERVAL_MS[interval] * 300)
        scenario_bars = _slice_between(scenario_bars_all[interval], scenario_start, end)
        scenario_features[interval] = FeatureSet(scenario_bars)
        scenario_maps[interval] = _map_closed_indices(exec_bars, scenario_bars, interval)
    meta = {
        "exec_rows": len(exec_bars),
        "exec_start": exec_bars[0].ts.isoformat() if exec_bars else None,
        "exec_end": exec_bars[-1].ts.isoformat() if exec_bars else None,
        "scenario_rows": {interval: len(fs.bars) for interval, fs in scenario_features.items()},
    }
    return features, scenario_features, scenario_maps, meta


def _selection_score(
    result: dict[str, Any],
    *,
    impulse_score_penalty: float = 0.0,
    flag_penalty: float = 0.10,
    score_cap: float = 0.0,
) -> float:
    diagnostics = dict(result.get("event_diagnostics") or {})
    flags = diagnostics.get("flags") or []
    mdd = float(result.get("max_drawdown_pct") or 100.0)
    cost_drag = float(result.get("estimated_cost_drag_pct") or 0.0)
    config = dict(result.get("config") or {})
    impulse_penalty = (
        max(float(impulse_score_penalty), 0.0)
        if float(config.get("one_way_impulse_probe_units") or 0.0) > 0.0
        else 0.0
    )
    base_score = float(result.get("score") or -1e9)
    if float(score_cap) > 0.0:
        base_score = min(base_score, float(score_cap))
    return (
        base_score
        - max(float(flag_penalty), 0.0) * len(flags)
        - 0.005 * max(mdd - 35.0, 0.0)
        - 0.0005 * max(cost_drag - 250.0, 0.0)
        - impulse_penalty
    )


def _run_config(
    *,
    symbol: str,
    features: FeatureSet,
    scenario_features: dict[str, FeatureSet],
    scenario_maps: dict[str, list[int]],
    config: MarketStateConfig,
    cost_rate: float,
    carry_rate_per_bar: float,
    min_periods: int,
) -> dict[str, Any] | None:
    return backtest_config(
        symbol=symbol,
        features=features,
        scenario_features=scenario_features,
        scenario_maps=scenario_maps,
        config=config,
        cost_rate=cost_rate,
        min_periods=min_periods,
        carry_rate_per_bar=carry_rate_per_bar,
    )


def _aggregate_folds(folds: list[dict[str, Any]]) -> dict[str, Any]:
    tests = [fold["test_result"] for fold in folds if fold.get("test_result")]
    if not tests:
        return {}
    equity = 1.0
    returns: list[float] = []
    cost_drags: list[float] = []
    carry_costs: list[float] = []
    max_mdd = 0.0
    selected_counter: Counter[str] = Counter()
    selected_profile_counter: Counter[str] = Counter()
    selected_hold_counter: Counter[str] = Counter()
    selected_max_units_counter: Counter[str] = Counter()
    test_health_counter: Counter[str] = Counter()
    flag_counter: Counter[str] = Counter()
    regime_totals: dict[str, dict[str, Any]] = {}
    for fold in folds:
        result = fold.get("test_result")
        if not result:
            continue
        equity *= float(result.get("final_equity") or 1.0)
        returns.append(float(result.get("total_return_pct") or 0.0))
        cost_drags.append(float(result.get("estimated_cost_drag_pct") or 0.0))
        carry_costs.append(float(result.get("modeled_carry_cost_fraction_sum") or 0.0))
        max_mdd = max(max_mdd, float(result.get("max_drawdown_pct") or 0.0))
        selected_counter[str(fold.get("selected_model_id") or "unknown")] += 1
        selected_config = dict(dict(fold.get("selected_train_result") or {}).get("config") or {})
        model_id = str(selected_config.get("model_id") or fold.get("selected_model_id") or "unknown")
        parts = model_id.split(":")
        selected_profile_counter[parts[2] if len(parts) > 2 else "unknown"] += 1
        selected_hold_counter[str(selected_config.get("max_hold_bars", "unknown"))] += 1
        selected_max_units_counter[str(selected_config.get("max_possible_units", "unknown"))] += 1
        diagnostics = dict(result.get("event_diagnostics") or {})
        test_health_counter[str(diagnostics.get("health") or "unknown")] += 1
        for flag in diagnostics.get("flags") or []:
            flag_counter[str(flag)] += 1
        for regime, stats in dict(result.get("regime_performance") or {}).items():
            regime_stats = dict(stats or {})
            total = regime_totals.setdefault(
                str(regime),
                {
                    "fold_count": 0,
                    "equity": 1.0,
                    "bars": 0,
                    "exposed_bars": 0,
                    "max_drawdown_pct": 0.0,
                    "abs_exposure_weighted_sum": 0.0,
                    "add_events": 0,
                    "remove_events": 0,
                },
            )
            regime_return = float(regime_stats.get("return_pct") or 0.0) / 100.0
            total["fold_count"] += 1
            total["equity"] *= max(1.0 + regime_return, 1e-12)
            bars = int(regime_stats.get("bars") or 0)
            total["bars"] += bars
            total["exposed_bars"] += int(regime_stats.get("exposed_bars") or 0)
            total["max_drawdown_pct"] = max(
                float(total["max_drawdown_pct"]),
                float(regime_stats.get("max_drawdown_pct") or 0.0),
            )
            total["abs_exposure_weighted_sum"] += float(regime_stats.get("avg_abs_account_exposure") or 0.0) * bars
            total["add_events"] += int(regime_stats.get("add_events") or 0)
            total["remove_events"] += int(regime_stats.get("remove_events") or 0)
    regime_performance = {
        regime: {
            "fold_count": int(stats["fold_count"]),
            "compounded_return_pct": round((float(stats["equity"]) - 1.0) * 100.0, 4),
            "bars": int(stats["bars"]),
            "exposed_bars": int(stats["exposed_bars"]),
            "max_drawdown_pct": round(float(stats["max_drawdown_pct"]), 4),
            "avg_abs_account_exposure": round(
                float(stats["abs_exposure_weighted_sum"]) / max(int(stats["bars"]), 1),
                4,
            ),
            "add_events": int(stats["add_events"]),
            "remove_events": int(stats["remove_events"]),
        }
        for regime, stats in sorted(regime_totals.items())
    }
    return {
        "fold_count": len(tests),
        "compounded_oos_return_pct": round((equity - 1.0) * 100.0, 4),
        "avg_oos_return_pct": round(mean(returns), 4),
        "min_oos_return_pct": round(min(returns), 4),
        "max_oos_return_pct": round(max(returns), 4),
        "positive_fold_count": sum(1 for value in returns if value > 0.0),
        "max_fold_drawdown_pct": round(max_mdd, 4),
        "avg_oos_cost_drag_pct": round(mean(cost_drags), 4) if cost_drags else 0.0,
        "max_oos_cost_drag_pct": round(max(cost_drags), 4) if cost_drags else 0.0,
        "avg_modeled_carry_cost_fraction_sum": round(mean(carry_costs), 8) if carry_costs else 0.0,
        "selected_model_counts": _counter_payload(selected_counter),
        "selected_profile_counts": _counter_payload(selected_profile_counter),
        "selected_hold_counts": _counter_payload(selected_hold_counter),
        "selected_max_units_counts": _counter_payload(selected_max_units_counter),
        "test_health_counts": _counter_payload(test_health_counter),
        "test_flag_counts": _counter_payload(flag_counter),
        "test_regime_performance": regime_performance,
    }


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    aggregate = dict(report.get("aggregate") or {})
    lines = [
        "# Market-State Rotation V6 Walk-Forward Validation",
        "",
        f"- Created at: `{report.get('created_at')}`",
        f"- Source report: `{report.get('source_report')}`",
        f"- Symbol: `{report.get('symbol')}`",
        f"- Execution interval: `{report.get('exec_interval')}`",
        f"- Train/test/step days: `{report.get('train_days')}/{report.get('test_days')}/{report.get('step_days')}`",
        f"- Source top-n: `{report.get('source_top_n')}`",
        f"- Candidate count: `{report.get('candidate_count')}`",
        f"- Fold offset/limit: `{report.get('fold_offset')}/{report.get('fold_limit')}`",
        f"- Config overrides: `{json.dumps(report.get('config_overrides', {}), ensure_ascii=False)}`",
        f"- Fold count: `{aggregate.get('fold_count')}`",
        f"- OOS compounded return: `{aggregate.get('compounded_oos_return_pct')}%`",
        f"- OOS average fold return: `{aggregate.get('avg_oos_return_pct')}%`",
        f"- OOS min/max fold return: `{aggregate.get('min_oos_return_pct')}% / {aggregate.get('max_oos_return_pct')}%`",
        f"- OOS max fold drawdown: `{aggregate.get('max_fold_drawdown_pct')}%`",
        f"- Positive folds: `{aggregate.get('positive_fold_count')}/{aggregate.get('fold_count')}`",
        f"- OOS avg/max cost drag: `{aggregate.get('avg_oos_cost_drag_pct')}% / {aggregate.get('max_oos_cost_drag_pct')}%`",
        f"- OOS avg carry cost fraction sum: `{aggregate.get('avg_modeled_carry_cost_fraction_sum')}`",
        f"- Selected model counts: `{json.dumps(aggregate.get('selected_model_counts', {}), ensure_ascii=False)}`",
        f"- Selected profile counts: `{json.dumps(aggregate.get('selected_profile_counts', {}), ensure_ascii=False)}`",
        f"- Selected hold counts: `{json.dumps(aggregate.get('selected_hold_counts', {}), ensure_ascii=False)}`",
        f"- Selected max-unit counts: `{json.dumps(aggregate.get('selected_max_units_counts', {}), ensure_ascii=False)}`",
        f"- Test health counts: `{json.dumps(aggregate.get('test_health_counts', {}), ensure_ascii=False)}`",
        f"- Test flag counts: `{json.dumps(aggregate.get('test_flag_counts', {}), ensure_ascii=False)}`",
        "",
        "## OOS Regime Performance",
        "",
        f"`{json.dumps(aggregate.get('test_regime_performance', {}), ensure_ascii=False)}`",
        "",
        "## Selection Policy",
        "",
        "The adaptive profile selects from the current top candidates using the previous 365 days, then trades the next 90 days unseen. This is the preferred deployment validation view because it avoids choosing one static model from the same period being evaluated.",
        "",
        "## Folds",
        "",
        "| fold | train | test | selected train return % | selected test return % | test MDD % | flags | selected model |",
        "|---:|---|---|---:|---:|---:|---|---|",
    ]
    for fold in report.get("folds") or []:
        train = dict(fold.get("selected_train_result") or {})
        test = dict(fold.get("test_result") or {})
        diag = dict(test.get("event_diagnostics") or {})
        lines.append(
            f"| {fold.get('fold')} | {fold.get('train_start')} to {fold.get('train_end')} | "
            f"{fold.get('test_start')} to {fold.get('test_end')} | "
            f"{train.get('total_return_pct')} | {test.get('total_return_pct')} | "
            f"{test.get('max_drawdown_pct')} | {', '.join(diag.get('flags') or []) or 'none'} | "
            f"`{fold.get('selected_model_id')}` |"
        )
    lines.append("")
    atomic_write_text(path, "\n".join(lines))


def main() -> None:
    args = _parse_args()
    source_path = Path(args.source_report)
    source_report = json.loads(source_path.read_text())
    source_args = dict(source_report.get("args") or {})
    symbol = args.symbol or str(source_args.get("symbol") or "BTCUSDT")
    exec_interval = args.exec_interval or str(source_args.get("exec_interval") or "5m")
    scenario_intervals = _csv(args.scenario_intervals or str(source_args.get("scenario_intervals") or "1h,4h"))
    if exec_interval not in _INTERVAL_MS:
        raise SystemExit(f"unsupported exec interval: {exec_interval}")
    for interval in scenario_intervals:
        if interval not in _INTERVAL_MS:
            raise SystemExit(f"unsupported scenario interval: {interval}")

    source_configs = _configs_from_source(source_report, top_n=max(1, int(args.top_n)))
    configs: list[MarketStateConfig] = []
    include_equity_circuit_in_selection = not bool(args.equity_circuit_breaker_after_selection)
    include_equity_soft_circuit_in_selection = not bool(args.equity_soft_circuit_after_selection)
    include_full_exit_in_selection = not bool(args.one_way_trim_full_exit_after_selection)
    include_base_reduce_in_selection = not bool(args.base_entry_reduce_after_selection)
    include_context_quarantine_in_selection = not bool(args.one_way_trim_context_after_selection)
    if bool(args.include_no_impulse_candidates):
        configs.extend(
            _apply_config_overrides(
                config,
                args,
                include_impulse=False,
                include_equity_circuit=include_equity_circuit_in_selection,
                include_equity_soft_circuit=include_equity_soft_circuit_in_selection,
                include_full_exit=include_full_exit_in_selection,
                include_base_reduce=include_base_reduce_in_selection,
                include_context_quarantine=include_context_quarantine_in_selection,
            )
            for config in source_configs
        )
    configs.extend(
        _apply_config_overrides(
            config,
            args,
            include_impulse=True,
            include_equity_circuit=include_equity_circuit_in_selection,
            include_equity_soft_circuit=include_equity_soft_circuit_in_selection,
            include_full_exit=include_full_exit_in_selection,
            include_base_reduce=include_base_reduce_in_selection,
            include_context_quarantine=include_context_quarantine_in_selection,
        )
        for config in source_configs
    )
    deduped_configs: list[MarketStateConfig] = []
    seen_config_keys: set[str] = set()
    for config in configs:
        key = _material_config_key(config)
        if key in seen_config_keys:
            continue
        seen_config_keys.add(key)
        deduped_configs.append(config)
    configs = deduped_configs
    if not configs:
        raise SystemExit(f"no candidate configs found in {source_path}")

    settings = get_settings()
    base_url = str(args.base_url or source_args.get("base_url") or settings.binance_rest_base_url or "https://fapi.binance.com").rstrip("/")
    cache_dir = Path(args.cache_dir or source_args.get("cache_dir") or "reports/validation/btc_flip_rotation_search/cache")
    exec_bars_all = _load_bars(
        symbol=symbol,
        interval=exec_interval,
        days=max(int(args.load_days), int(args.train_days) + int(args.test_days) + 5),
        cache_dir=cache_dir,
        base_url=base_url,
        sleep_seconds=float(args.sleep_seconds),
    )
    scenario_bars_all = {
        interval: _load_bars(
            symbol=symbol,
            interval=interval,
            days=max(int(args.load_days), int(args.train_days) + int(args.test_days) + 5),
            cache_dir=cache_dir,
            base_url=base_url,
            sleep_seconds=float(args.sleep_seconds),
        )
        for interval in scenario_intervals
    }

    if not exec_bars_all:
        raise SystemExit("no execution bars loaded")
    cost_rate = (max(float(args.fee_bps_per_side), 0.0) + max(float(args.slippage_bps_per_side), 0.0)) / 10_000.0
    carry_rate_per_bar = _carry_rate_per_bar(
        exec_interval=exec_interval,
        funding_bps_per_8h=float(args.funding_bps_per_8h),
        borrow_bps_per_day=float(args.borrow_bps_per_day),
    )

    fold_start = exec_bars_all[0].ts.astimezone(UTC)
    last_ts = exec_bars_all[-1].ts.astimezone(UTC)
    train_delta = timedelta(days=max(int(args.train_days), 1))
    test_delta = timedelta(days=max(int(args.test_days), 1))
    step_delta = timedelta(days=max(int(args.step_days), 1))
    folds: list[dict[str, Any]] = []
    fold_idx = 0
    valid_fold_idx = 0
    fold_offset = max(0, int(args.fold_offset))
    while fold_start + train_delta + test_delta <= last_ts:
        fold_idx += 1
        train_start = fold_start
        train_end = train_start + train_delta
        test_start = train_end
        test_end = test_start + test_delta
        train_features, train_scenario_features, train_maps, train_meta = _window_feature_sets(
            exec_bars_all=exec_bars_all,
            scenario_bars_all=scenario_bars_all,
            start=train_start,
            end=train_end,
            scenario_intervals=scenario_intervals,
        )
        test_features, test_scenario_features, test_maps, test_meta = _window_feature_sets(
            exec_bars_all=exec_bars_all,
            scenario_bars_all=scenario_bars_all,
            start=test_start,
            end=test_end,
            scenario_intervals=scenario_intervals,
        )
        if len(train_features.bars) < int(args.min_periods) or len(test_features.bars) < int(args.min_periods):
            fold_start += step_delta
            continue
        valid_fold_idx += 1
        if valid_fold_idx <= fold_offset:
            fold_start += step_delta
            continue

        train_results: list[dict[str, Any]] = []
        print(f"walk-forward fold {valid_fold_idx} training {len(configs)} candidates", flush=True)
        for config_idx, config in enumerate(configs, start=1):
            result = _run_config(
                symbol=symbol,
                features=train_features,
                scenario_features=train_scenario_features,
                scenario_maps=train_maps,
                config=config,
                cost_rate=cost_rate,
                carry_rate_per_bar=carry_rate_per_bar,
                min_periods=int(args.min_periods),
            )
            if result:
                result["walk_forward_selection_score"] = round(
                    _selection_score(
                        result,
                        impulse_score_penalty=float(args.impulse_selection_score_penalty),
                        flag_penalty=float(args.selection_flag_penalty),
                        score_cap=float(args.selection_score_cap),
                    ),
                    6,
                )
                train_results.append(result)
            print(f"walk-forward fold {valid_fold_idx} trained {config_idx}/{len(configs)}", flush=True)
        if not train_results:
            fold_start += step_delta
            continue
        train_results.sort(
            key=lambda item: (
                float(item.get("walk_forward_selection_score") or -1e9),
                float(item.get("cagr_pct") or -1e9),
                -float(item.get("max_drawdown_pct") or math.inf),
            ),
            reverse=True,
        )
        selected_train = train_results[0]
        selected_config = MarketStateConfig(**selected_train["config"])
        if bool(args.equity_circuit_breaker_after_selection):
            selected_config = _apply_equity_circuit_overlay(selected_config, args)
        if bool(args.equity_soft_circuit_after_selection):
            selected_config = _apply_equity_soft_circuit_overlay(selected_config, args)
        if bool(args.one_way_trim_full_exit_after_selection):
            selected_config = _apply_full_exit_overlay(selected_config, args)
        if bool(args.base_entry_reduce_after_selection):
            selected_config = _apply_base_reduce_overlay(selected_config, args)
        if bool(args.one_way_trim_context_after_selection):
            selected_config = _apply_context_quarantine_overlay(selected_config, args)
        print(f"walk-forward fold {valid_fold_idx} testing selected candidate", flush=True)
        test_result = _run_config(
            symbol=symbol,
            features=test_features,
            scenario_features=test_scenario_features,
            scenario_maps=test_maps,
            config=selected_config,
            cost_rate=cost_rate,
            carry_rate_per_bar=carry_rate_per_bar,
            min_periods=int(args.min_periods),
        )
        folds.append(
            {
                "fold": valid_fold_idx,
                "chunk_fold": len(folds) + 1,
                "train_start": train_start.date().isoformat(),
                "train_end": train_end.date().isoformat(),
                "test_start": test_start.date().isoformat(),
                "test_end": test_end.date().isoformat(),
                "train_meta": train_meta,
                "test_meta": test_meta,
                "selected_model_id": selected_config.model_id,
                "selected_train_result": selected_train,
                "test_result": test_result,
                "train_top_results": train_results[:5],
            }
        )
        print(f"walk-forward fold {valid_fold_idx} selected {selected_config.model_id}", flush=True)
        if int(args.fold_limit) > 0 and len(folds) >= int(args.fold_limit):
            break
        fold_start += step_delta

    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "source_report": str(source_path),
        "symbol": symbol,
        "exec_interval": exec_interval,
        "scenario_intervals": scenario_intervals,
        "train_days": int(args.train_days),
        "test_days": int(args.test_days),
        "step_days": int(args.step_days),
        "load_days": int(args.load_days),
        "source_top_n": int(args.top_n),
        "fold_offset": fold_offset,
        "fold_limit": int(args.fold_limit),
        "candidate_count": len(configs),
        "cost_model": {
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": float(args.slippage_bps_per_side),
            "funding_bps_per_8h": float(args.funding_bps_per_8h),
            "borrow_bps_per_day": float(args.borrow_bps_per_day),
            "carry_rate_per_bar": carry_rate_per_bar,
        },
        "config_overrides": {
            "one_way_trim_min_adverse_reaction": args.one_way_trim_min_adverse_reaction,
            "one_way_trim_cooldown_bars": args.one_way_trim_cooldown_bars,
            "one_way_trim_retire_same_zone": bool(args.one_way_trim_retire_same_zone),
            "one_way_trim_same_side_cooldown_bars": args.one_way_trim_same_side_cooldown_bars,
            "one_way_trim_cluster_guard_count": args.one_way_trim_cluster_guard_count,
            "one_way_trim_cluster_window_bars": args.one_way_trim_cluster_window_bars,
            "one_way_trim_cluster_cooldown_bars": args.one_way_trim_cluster_cooldown_bars,
            "one_way_trim_context_guard_count": args.one_way_trim_context_guard_count,
            "one_way_trim_context_window_bars": args.one_way_trim_context_window_bars,
            "one_way_trim_context_cooldown_bars": args.one_way_trim_context_cooldown_bars,
            "one_way_trim_context_full_exit": bool(args.one_way_trim_context_full_exit),
            "one_way_trim_context_after_selection": bool(args.one_way_trim_context_after_selection),
            "one_way_trim_full_exit_min_one_way_score": args.one_way_trim_full_exit_min_one_way_score,
            "one_way_trim_full_exit_min_score_diff": args.one_way_trim_full_exit_min_score_diff,
            "one_way_trim_full_exit_after_selection": bool(args.one_way_trim_full_exit_after_selection),
            "trend_idle_probe_units": args.trend_idle_probe_units,
            "trend_idle_min_score": args.trend_idle_min_score,
            "trend_idle_min_reason_stack": args.trend_idle_min_reason_stack,
            "trend_idle_cooldown_bars": args.trend_idle_cooldown_bars,
            "trend_idle_max_extension_atr": args.trend_idle_max_extension_atr,
            "equity_circuit_breaker_drawdown_pct": args.equity_circuit_breaker_drawdown_pct,
            "equity_circuit_breaker_pause_bars": args.equity_circuit_breaker_pause_bars,
            "equity_circuit_breaker_after_selection": bool(args.equity_circuit_breaker_after_selection),
            "equity_soft_circuit_drawdown_pct": args.equity_soft_circuit_drawdown_pct,
            "equity_soft_circuit_cooldown_bars": args.equity_soft_circuit_cooldown_bars,
            "equity_soft_circuit_size_mult": args.equity_soft_circuit_size_mult,
            "equity_soft_circuit_force_flat": bool(args.equity_soft_circuit_force_flat),
            "equity_soft_circuit_after_selection": bool(args.equity_soft_circuit_after_selection),
            "one_way_reversal_switch_units": args.one_way_reversal_switch_units,
            "one_way_reversal_min_score_edge": args.one_way_reversal_min_score_edge,
            "one_way_reversal_cooldown_bars": args.one_way_reversal_cooldown_bars,
            "one_way_reversal_allow_scenario_override": bool(args.one_way_reversal_allow_scenario_override),
            "one_way_reversal_allow_score_override": bool(args.one_way_reversal_allow_score_override),
            "one_way_impulse_probe_units": args.one_way_impulse_probe_units,
            "one_way_impulse_min_one_way_score": args.one_way_impulse_min_one_way_score,
            "one_way_impulse_min_score_diff": args.one_way_impulse_min_score_diff,
            "one_way_impulse_cooldown_bars": args.one_way_impulse_cooldown_bars,
            "one_way_impulse_max_extension_atr": args.one_way_impulse_max_extension_atr,
            "base_entry_max_extension_atr": args.base_entry_max_extension_atr,
            "base_entry_reduce_extension_atr": args.base_entry_reduce_extension_atr,
            "base_entry_reduce_size_mult": args.base_entry_reduce_size_mult,
            "base_entry_reduce_promote_reaction": args.base_entry_reduce_promote_reaction,
            "base_entry_reduce_max_trend_strength": args.base_entry_reduce_max_trend_strength,
            "base_entry_reduce_after_selection": bool(args.base_entry_reduce_after_selection),
            "include_no_impulse_candidates": bool(args.include_no_impulse_candidates),
            "impulse_selection_score_penalty": float(args.impulse_selection_score_penalty),
            "selection_flag_penalty": float(args.selection_flag_penalty),
            "selection_score_cap": float(args.selection_score_cap),
        },
        "aggregate": _aggregate_folds(folds),
        "folds": folds,
    }

    if args.write_report:
        report_dir = Path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        json_path = report_dir / f"market_state_rotation_v6_walk_forward_{symbol}_{exec_interval}_{stamp}.json"
        latest_json = report_dir / f"market_state_rotation_v6_walk_forward_{symbol}_{exec_interval}_latest.json"
        summary_md = report_dir / "walk_forward_v6.md"
        text = json.dumps(report, ensure_ascii=False, indent=2)
        atomic_write_text(json_path, text)
        atomic_write_text(latest_json, text)
        _write_markdown(report, summary_md)
        print(f"wrote {json_path}")
        print(f"wrote {latest_json}")
        print(f"wrote {summary_md}")

    print(
        json.dumps(
            {
                "symbol": symbol,
                "exec_interval": exec_interval,
                "candidate_count": len(configs),
                "aggregate": report["aggregate"],
                "folds": [
                    {
                        "fold": fold.get("fold"),
                        "selected_model_id": fold.get("selected_model_id"),
                        "selected_train_result": _stdout_result_summary(fold["selected_train_result"]),
                        "test_result": _stdout_result_summary(fold["test_result"]) if fold.get("test_result") else None,
                    }
                    for fold in folds
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
