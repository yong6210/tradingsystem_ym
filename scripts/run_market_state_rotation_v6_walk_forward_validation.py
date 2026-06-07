#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
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
    _parse_base_context_reduce_patterns,
    _parse_event_risk_contexts,
    _parse_router_modes,
    _stdout_result_summary,
    backtest_config,
)


DEFAULT_SOURCE_REPORT = (
    "reports/validation/market_state_rotation_v6_backtest/"
    "market_state_rotation_v6_BTCUSDT_5m_365d_latest.json"
)


def _add_one_way_impulse_after_selection_args(
    parser: argparse.ArgumentParser,
    *,
    option_prefix: str,
    description: str,
) -> None:
    parser.add_argument(
        f"--{option_prefix}-after-selection",
        action="store_true",
        help=description,
    )
    parser.add_argument(f"--{option_prefix}-after-selection-probe-units", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-min-one-way-score", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-min-score-diff", type=int, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-cooldown-bars", type=int, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-max-extension-atr", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-min-source-max-units", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-max-source-max-units", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-min-train-return-pct", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-max-train-return-pct", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-min-train-drawdown-pct", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-max-train-drawdown-pct", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-min-train-cost-drag-pct", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-max-train-cost-drag-pct", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-min-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument(f"--{option_prefix}-after-selection-max-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument(f"--{option_prefix}-after-selection-min-turnover-per-add", type=float, default=0.0)
    parser.add_argument(f"--{option_prefix}-after-selection-max-turnover-per-add", type=float, default=0.0)


def _one_way_impulse_after_selection_override_payload(
    args: argparse.Namespace,
    prefix: str,
) -> dict[str, Any]:
    return {
        prefix: bool(getattr(args, prefix)),
        f"{prefix}_probe_units": getattr(args, f"{prefix}_probe_units"),
        f"{prefix}_min_one_way_score": getattr(args, f"{prefix}_min_one_way_score"),
        f"{prefix}_min_score_diff": getattr(args, f"{prefix}_min_score_diff"),
        f"{prefix}_cooldown_bars": getattr(args, f"{prefix}_cooldown_bars"),
        f"{prefix}_max_extension_atr": getattr(args, f"{prefix}_max_extension_atr"),
        f"{prefix}_min_source_max_units": getattr(args, f"{prefix}_min_source_max_units"),
        f"{prefix}_max_source_max_units": getattr(args, f"{prefix}_max_source_max_units"),
        f"{prefix}_min_train_return_pct": getattr(args, f"{prefix}_min_train_return_pct"),
        f"{prefix}_max_train_return_pct": getattr(args, f"{prefix}_max_train_return_pct"),
        f"{prefix}_min_train_drawdown_pct": getattr(args, f"{prefix}_min_train_drawdown_pct"),
        f"{prefix}_max_train_drawdown_pct": getattr(args, f"{prefix}_max_train_drawdown_pct"),
        f"{prefix}_min_train_cost_drag_pct": getattr(args, f"{prefix}_min_train_cost_drag_pct"),
        f"{prefix}_max_train_cost_drag_pct": getattr(args, f"{prefix}_max_train_cost_drag_pct"),
        f"{prefix}_min_one_way_trim_per_add": float(getattr(args, f"{prefix}_min_one_way_trim_per_add")),
        f"{prefix}_max_one_way_trim_per_add": float(getattr(args, f"{prefix}_max_one_way_trim_per_add")),
        f"{prefix}_min_turnover_per_add": float(getattr(args, f"{prefix}_min_turnover_per_add")),
        f"{prefix}_max_turnover_per_add": float(getattr(args, f"{prefix}_max_turnover_per_add")),
    }


def _add_train_state_after_selection_args(
    parser: argparse.ArgumentParser,
    *,
    option_prefix: str,
    description: str,
) -> None:
    parser.add_argument(
        f"--{option_prefix}-after-selection",
        action="store_true",
        help=description,
    )
    parser.add_argument(f"--{option_prefix}-after-selection-min-source-max-units", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-max-source-max-units", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-min-train-return-pct", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-max-train-return-pct", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-min-train-drawdown-pct", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-max-train-drawdown-pct", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-min-train-cost-drag-pct", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-max-train-cost-drag-pct", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-min-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument(f"--{option_prefix}-after-selection-max-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument(f"--{option_prefix}-after-selection-min-turnover-per-add", type=float, default=0.0)
    parser.add_argument(f"--{option_prefix}-after-selection-max-turnover-per-add", type=float, default=0.0)


def _add_trim_cooldown_after_selection_args(
    parser: argparse.ArgumentParser,
    *,
    option_prefix: str,
    description: str,
) -> None:
    _add_train_state_after_selection_args(
        parser,
        option_prefix=option_prefix,
        description=description,
    )
    parser.add_argument(f"--{option_prefix}-after-selection-one-way-trim-cooldown-bars", type=int, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-base-entry-reduce-extension-atr", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-base-entry-reduce-size-mult", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-after-selection-base-entry-reduce-promote-reaction", type=float, default=None)


def _trim_cooldown_after_selection_override_payload(
    args: argparse.Namespace,
    prefix: str,
) -> dict[str, Any]:
    return {
        **_train_state_after_selection_override_payload(args, prefix),
        f"{prefix}_one_way_trim_cooldown_bars": getattr(args, f"{prefix}_one_way_trim_cooldown_bars"),
        f"{prefix}_base_entry_reduce_extension_atr": getattr(
            args,
            f"{prefix}_base_entry_reduce_extension_atr",
        ),
        f"{prefix}_base_entry_reduce_size_mult": getattr(args, f"{prefix}_base_entry_reduce_size_mult"),
        f"{prefix}_base_entry_reduce_promote_reaction": getattr(
            args,
            f"{prefix}_base_entry_reduce_promote_reaction",
        ),
    }


def _add_one_way_reversal_tune_after_selection_args(
    parser: argparse.ArgumentParser,
    *,
    option_prefix: str,
    description: str,
) -> None:
    _add_train_state_after_selection_args(
        parser,
        option_prefix=option_prefix,
        description=description,
    )
    parser.add_argument(f"--{option_prefix}-after-selection-switch-units", type=float, default=None)


def _one_way_reversal_tune_after_selection_override_payload(
    args: argparse.Namespace,
    prefix: str,
) -> dict[str, Any]:
    return {
        **_train_state_after_selection_override_payload(args, prefix),
        f"{prefix}_switch_units": getattr(args, f"{prefix}_switch_units"),
    }


def _train_state_after_selection_override_payload(
    args: argparse.Namespace,
    prefix: str,
) -> dict[str, Any]:
    return {
        prefix: bool(getattr(args, prefix)),
        f"{prefix}_min_source_max_units": getattr(args, f"{prefix}_min_source_max_units"),
        f"{prefix}_max_source_max_units": getattr(args, f"{prefix}_max_source_max_units"),
        f"{prefix}_min_train_return_pct": getattr(args, f"{prefix}_min_train_return_pct"),
        f"{prefix}_max_train_return_pct": getattr(args, f"{prefix}_max_train_return_pct"),
        f"{prefix}_min_train_drawdown_pct": getattr(args, f"{prefix}_min_train_drawdown_pct"),
        f"{prefix}_max_train_drawdown_pct": getattr(args, f"{prefix}_max_train_drawdown_pct"),
        f"{prefix}_min_train_cost_drag_pct": getattr(args, f"{prefix}_min_train_cost_drag_pct"),
        f"{prefix}_max_train_cost_drag_pct": getattr(args, f"{prefix}_max_train_cost_drag_pct"),
        f"{prefix}_min_one_way_trim_per_add": float(getattr(args, f"{prefix}_min_one_way_trim_per_add")),
        f"{prefix}_max_one_way_trim_per_add": float(getattr(args, f"{prefix}_max_one_way_trim_per_add")),
        f"{prefix}_min_turnover_per_add": float(getattr(args, f"{prefix}_min_turnover_per_add")),
        f"{prefix}_max_turnover_per_add": float(getattr(args, f"{prefix}_max_turnover_per_add")),
    }


def _add_near_miss_probe_override_args(parser: argparse.ArgumentParser, *, option_prefix: str) -> None:
    parser.add_argument(f"--{option_prefix}-probe-units", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-probe-min-score", type=int, default=None)
    parser.add_argument(f"--{option_prefix}-probe-min-score-edge", type=int, default=None)
    parser.add_argument(f"--{option_prefix}-probe-min-reason-stack", type=int, default=None)
    parser.add_argument(f"--{option_prefix}-probe-cooldown-bars", type=int, default=None)
    parser.add_argument(f"--{option_prefix}-probe-max-extension-atr", type=float, default=None)
    parser.add_argument(f"--{option_prefix}-probe-failure-guard-count", type=int, default=None)
    parser.add_argument(f"--{option_prefix}-probe-failure-guard-window-bars", type=int, default=None)
    parser.add_argument(f"--{option_prefix}-probe-failure-cooldown-bars", type=int, default=None)
    parser.add_argument(f"--{option_prefix}-probe-allowed-soft-reasons", default=None)
    parser.add_argument(f"--{option_prefix}-probe-allowed-alignments", default=None)
    parser.add_argument(f"--{option_prefix}-probe-allowed-execution-contexts", default=None)
    parser.add_argument(f"--{option_prefix}-probe-allowed-regimes", default=None)


def _near_miss_probe_override_payload(args: argparse.Namespace, prefix: str) -> dict[str, Any]:
    return {
        f"{prefix}_probe_units": getattr(args, f"{prefix}_probe_units"),
        f"{prefix}_probe_min_score": getattr(args, f"{prefix}_probe_min_score"),
        f"{prefix}_probe_min_score_edge": getattr(args, f"{prefix}_probe_min_score_edge"),
        f"{prefix}_probe_min_reason_stack": getattr(args, f"{prefix}_probe_min_reason_stack"),
        f"{prefix}_probe_cooldown_bars": getattr(args, f"{prefix}_probe_cooldown_bars"),
        f"{prefix}_probe_max_extension_atr": getattr(args, f"{prefix}_probe_max_extension_atr"),
        f"{prefix}_probe_failure_guard_count": getattr(args, f"{prefix}_probe_failure_guard_count"),
        f"{prefix}_probe_failure_guard_window_bars": getattr(
            args,
            f"{prefix}_probe_failure_guard_window_bars",
        ),
        f"{prefix}_probe_failure_cooldown_bars": getattr(
            args,
            f"{prefix}_probe_failure_cooldown_bars",
        ),
        f"{prefix}_probe_allowed_soft_reasons": getattr(args, f"{prefix}_probe_allowed_soft_reasons"),
        f"{prefix}_probe_allowed_alignments": getattr(args, f"{prefix}_probe_allowed_alignments"),
        f"{prefix}_probe_allowed_execution_contexts": getattr(args, f"{prefix}_probe_allowed_execution_contexts"),
        f"{prefix}_probe_allowed_regimes": getattr(args, f"{prefix}_probe_allowed_regimes"),
    }


def _provided_near_miss_recipe_change(args: argparse.Namespace, prefix: str) -> dict[str, Any]:
    field_specs = (
        ("probe_units", "near_miss_probe_units"),
        ("probe_min_score", "near_miss_probe_min_score"),
        ("probe_min_score_edge", "near_miss_probe_min_score_edge"),
        ("probe_min_reason_stack", "near_miss_probe_min_reason_stack"),
        ("probe_cooldown_bars", "near_miss_probe_cooldown_bars"),
        ("probe_max_extension_atr", "near_miss_probe_max_extension_atr"),
        ("probe_failure_guard_count", "near_miss_probe_failure_guard_count"),
        ("probe_failure_guard_window_bars", "near_miss_probe_failure_guard_window_bars"),
        ("probe_failure_cooldown_bars", "near_miss_probe_failure_cooldown_bars"),
        ("probe_allowed_soft_reasons", "near_miss_probe_allowed_soft_reasons"),
        ("probe_allowed_alignments", "near_miss_probe_allowed_alignments"),
        ("probe_allowed_execution_contexts", "near_miss_probe_allowed_execution_contexts"),
        ("probe_allowed_regimes", "near_miss_probe_allowed_regimes"),
    )
    change: dict[str, Any] = {}
    for attr_suffix, config_field in field_specs:
        value = getattr(args, f"{prefix}_{attr_suffix}", None)
        if value is None:
            continue
        change[config_field] = value
    return change


def _csv_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(dict.fromkeys(str(item) for item in value if str(item)))
    return tuple(dict.fromkeys(str(item) for item in _csv(str(value)) if str(item)))


def _tuple_suffix(value: tuple[str, ...]) -> str:
    return "-".join(str(item).replace("_", "").replace("|", "-") for item in value) or "none"


def _near_miss_recipe_override_suffix(label: str, change: dict[str, Any]) -> str:
    if "near_miss_probe_units" in change:
        return f"{label}Probe{max(0.0, float(change['near_miss_probe_units'])):g}"
    return f"{label}Cfg"


def _cli_provided_dests(
    parser: argparse.ArgumentParser,
    argv: list[str],
) -> set[str]:
    option_dests: dict[str, str] = {}
    for action in parser._actions:
        for option in action.option_strings:
            option_dests[option] = action.dest
    provided: set[str] = set()
    for token in argv:
        if not token.startswith("-"):
            continue
        option = token.split("=", 1)[0]
        dest = option_dests.get(option)
        if dest:
            provided.add(dest)
    return provided


def _source_replay_inheritable_field(name: str) -> bool:
    return bool(name)


def _source_replay_should_skip_inherited_confirmation_mode(
    name: str,
    provided_dests: set[str],
) -> bool:
    if name != "after_selection_confirmation_mode":
        return False
    if name in provided_dests:
        return False
    confirmation_dests = {
        "after_selection_train_confirmation",
        "after_selection_confirmation_ablation_mode",
        "after_selection_confirm_min_score_delta",
        "after_selection_confirm_min_return_delta_pct",
        "after_selection_confirm_max_drawdown_delta_pct",
        "after_selection_confirm_max_cost_delta_pct",
        "after_selection_confirm_min_return_per_cost_delta",
        "after_selection_confirm_overlays",
    }
    return bool(confirmation_dests & provided_dests)


def _inherit_source_replay_selection_policy(
    args: argparse.Namespace,
    config_overrides: dict[str, Any],
) -> list[str]:
    parser_defaults = dict(getattr(args, "_parser_defaults", {}) or {})
    provided_dests = set(getattr(args, "_provided_cli_dests", set()) or set())
    inherited: list[str] = []
    clamped: set[str] = set(getattr(args, "_source_replay_clamped_selection_policy_fields", set()) or set())
    for name, value in sorted(config_overrides.items()):
        if not _source_replay_inheritable_field(str(name)):
            continue
        if _source_replay_should_skip_inherited_confirmation_mode(str(name), provided_dests):
            continue
        if value is None or name in provided_dests or not hasattr(args, str(name)):
            continue
        if str(name) in parser_defaults and getattr(args, str(name)) != parser_defaults[str(name)]:
            continue
        inherited_value = value
        if str(name) == "near_miss_after_selection_min_train_return_pct":
            default_value = parser_defaults.get(str(name))
            try:
                if (
                    default_value is not None
                    and float(default_value) >= 0.0
                    and float(value) < float(default_value)
                ):
                    inherited_value = float(default_value)
                    clamped.add(str(name))
            except (TypeError, ValueError):
                pass
        setattr(args, str(name), inherited_value)
        inherited.append(str(name))
    args._source_replay_clamped_selection_policy_fields = sorted(clamped)
    return inherited


def _apply_force_in_selection_flags(args: argparse.Namespace) -> list[str]:
    forced: list[str] = []
    if bool(getattr(args, "force_near_miss_in_selection", False)) and bool(args.near_miss_after_selection):
        args.near_miss_after_selection = False
        forced.append("near_miss_after_selection")
    return forced


def _stabilize_source_replay_ratio_gates(
    args: argparse.Namespace,
    inherited_fields: list[str],
    *,
    source_report: dict[str, Any] | None = None,
    tolerance: float = 0.01,
) -> list[str]:
    """Loosen only inherited ratio gates enough to absorb deterministic replay drift."""
    if source_report and "source_replay_stabilized_ratio_gate_fields" in source_report:
        return []
    if tolerance <= 0.0:
        return []
    adjusted: list[str] = []
    provided_dests = set(getattr(args, "_provided_cli_dests", set()) or set())
    for name in sorted(set(inherited_fields)):
        if name in provided_dests or not hasattr(args, name):
            continue
        if name.endswith("_min_one_way_trim_per_add") or name.endswith("_min_turnover_per_add"):
            current = getattr(args, name)
            if current is None:
                continue
            value = max(0.0, float(current) - tolerance)
        else:
            continue
        if abs(float(current) - value) <= 1e-12:
            continue
        setattr(args, name, value)
        adjusted.append(name)
    return adjusted


def _inherit_source_replay_window_policy(
    args: argparse.Namespace,
    source_report: dict[str, Any],
) -> list[str]:
    parser_defaults = dict(getattr(args, "_parser_defaults", {}) or {})
    provided_dests = set(getattr(args, "_provided_cli_dests", set()) or set())
    inherited: list[str] = []
    for name in (
        "load_days",
        "train_days",
        "test_days",
        "step_days",
        "fold_anchor_hour_utc",
        "fold_anchor_minute_utc",
        "fold_start_at",
    ):
        value = source_report.get(name)
        if value is None and name == "fold_start_at":
            source_folds = source_report.get("folds") or []
            if source_folds and isinstance(source_folds[0], dict):
                value = source_folds[0].get("train_start_at") or source_folds[0].get("train_start")
        if value is None or name in provided_dests or not hasattr(args, name):
            continue
        if name in parser_defaults and getattr(args, name) != parser_defaults[name]:
            continue
        setattr(args, name, value)
        inherited.append(name)
    return inherited


def _source_replay_should_auto_warm_selection_state(
    args: argparse.Namespace,
    *,
    inherited_fields: list[str],
    fold_offset: int,
) -> bool:
    if fold_offset <= 0:
        return False
    if bool(getattr(args, "warm_fold_offset_selection_state", False)):
        return False
    if bool(getattr(args, "disable_source_replay_auto_warm_selection_state", False)):
        return False
    if not any(field.startswith("selection_recent_efficiency_") for field in inherited_fields):
        return False
    return (
        int(getattr(args, "selection_recent_efficiency_lookback", 0) or 0) > 0
        and float(getattr(args, "selection_recent_efficiency_penalty", 0.0) or 0.0) > 0.0
    )


_HIGH_RETURN_SOFT_SIZER_RELAX_PATTERN = re.compile(r":wfEqSoftRelax(?P<drawdown>[0-9]+(?:\.[0-9]+)?)M")


def _source_replay_high_return_soft_sizer_relax_drawdown_pct(
    report: dict[str, Any],
) -> float | None:
    values: Counter[str] = Counter()
    for fold in report.get("folds") or []:
        if not isinstance(fold, dict):
            continue
        overlays = {str(item) for item in fold.get("after_selection_overlays_applied") or []}
        if "high_return_soft_sizer_relax" not in overlays:
            continue
        model_id = str(fold.get("selected_model_id") or "")
        match = _HIGH_RETURN_SOFT_SIZER_RELAX_PATTERN.search(model_id)
        if match:
            values[match.group("drawdown")] += 1
    if not values:
        return None
    drawdown, _ = max(values.items(), key=lambda item: (int(item[1]), item[0]))
    try:
        return float(drawdown)
    except ValueError:
        return None


def _inherit_source_replay_model_encoded_policy(
    args: argparse.Namespace,
    source_report: dict[str, Any],
) -> list[str]:
    parser_defaults = dict(getattr(args, "_parser_defaults", {}) or {})
    provided_dests = set(getattr(args, "_provided_cli_dests", set()) or set())
    inherited: list[str] = []
    field = "high_return_soft_sizer_relax_drawdown_pct"
    value = _source_replay_high_return_soft_sizer_relax_drawdown_pct(source_report)
    if value is None or field in provided_dests or not hasattr(args, field):
        return inherited
    if field in parser_defaults and getattr(args, field) != parser_defaults[field]:
        return inherited
    setattr(args, field, value)
    inherited.append(field)
    return inherited


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
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
    parser.add_argument(
        "--fold-anchor-hour-utc",
        type=int,
        default=None,
        help=(
            "Optional UTC hour used to anchor the first walk-forward fold. When omitted, the first "
            "loaded execution bar remains the fold start for backwards compatibility."
        ),
    )
    parser.add_argument(
        "--fold-anchor-minute-utc",
        type=int,
        default=0,
        help="UTC minute used with --fold-anchor-hour-utc. Ignored when no anchor hour is provided.",
    )
    parser.add_argument(
        "--fold-start-at",
        default="",
        help=(
            "Optional exact UTC timestamp for the first fold train start. Source replay inherits "
            "the first source fold start by default to keep rolling load windows reproducible."
        ),
    )
    parser.add_argument(
        "--warm-fold-offset-selection-state",
        action="store_true",
        help=(
            "When --fold-offset is used, still run skipped earlier folds internally so history-based "
            "selection penalties match a full walk-forward run. Skipped warmup folds are not written "
            "to the report."
        ),
    )
    parser.add_argument(
        "--disable-source-replay-auto-warm-selection-state",
        action="store_true",
        help=(
            "Disable automatic warm-up of skipped folds when a source report's recent-efficiency "
            "selection policy is inherited. This is faster but can intentionally diverge from the "
            "source report's full walk-forward selection state."
        ),
    )
    parser.add_argument(
        "--disable-source-replay-selected-train-anchor",
        action="store_true",
        help=(
            "Do not prefer the source fold's selected train config during source replay. "
            "Leaving the anchor enabled keeps iterative reports focused on changes introduced "
            "after the source report instead of reselecting a different base candidate."
        ),
    )
    parser.add_argument(
        "--source-replay-fail-on-unresolved-material-drift",
        action="store_true",
        help=(
            "Exit non-zero after writing reports when source replay diagnostics show unresolved "
            "material return, drawdown, cost, or lineage drift. Use this for promotion candidates."
        ),
    )
    parser.add_argument(
        "--source-replay-watch-unresolved-material-drift",
        dest="source_replay_fail_on_unresolved_material_drift",
        action="store_false",
        default=False,
        help=(
            "Keep source replay drift in watch mode. Use this for shadow experiments that are "
            "expected to change lineage and should still write a research report."
        ),
    )
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument("--funding-bps-per-8h", type=float, default=0.0)
    parser.add_argument("--borrow-bps-per-day", type=float, default=0.0)
    parser.add_argument(
        "--after-selection-train-confirmation",
        action="store_true",
        help=(
            "Re-test the selected after-selection overlay on the train window and revert it "
            "when the overlay fails the configured cost/score confirmation gates."
        ),
    )
    parser.add_argument(
        "--after-selection-confirmation-mode",
        choices=("enforce", "shadow"),
        default="enforce",
        help=(
            "Use enforce to revert failed confirmed overlays, or shadow to record the same "
            "confirmation diagnostics without changing the selected model."
        ),
    )
    parser.add_argument(
        "--after-selection-confirmation-ablation-mode",
        choices=("stack", "per_overlay"),
        default="stack",
        help=(
            "Use stack to confirm the full overlay stack against the source model, or per_overlay "
            "to rerun train with each target overlay removed and reject only overlays that fail "
            "their leave-one-out check."
        ),
    )
    parser.add_argument("--after-selection-confirm-min-score-delta", type=float, default=None)
    parser.add_argument("--after-selection-confirm-min-return-delta-pct", type=float, default=None)
    parser.add_argument("--after-selection-confirm-max-drawdown-delta-pct", type=float, default=None)
    parser.add_argument("--after-selection-confirm-max-cost-delta-pct", type=float, default=None)
    parser.add_argument("--after-selection-confirm-min-return-per-cost-delta", type=float, default=None)
    parser.add_argument(
        "--after-selection-confirm-overlays",
        default="",
        help=(
            "Comma-separated overlay names to validate with train confirmation. Empty means every "
            "after-selection overlay is subject to confirmation."
        ),
    )
    parser.add_argument(
        "--after-selection-recent-oos-block",
        action="store_true",
        help=(
            "Block after-selection overlays whose recent walk-forward OOS record fails the configured "
            "return, drawdown, cost, or confirmation-warning gates."
        ),
    )
    parser.add_argument(
        "--after-selection-recent-oos-block-mode",
        choices=("enforce", "shadow"),
        default="enforce",
        help=(
            "Use enforce to block weak recent-OOS overlays, or shadow to record the same block list "
            "without changing the selected model."
        ),
    )
    parser.add_argument("--after-selection-recent-oos-block-lookback", type=int, default=4)
    parser.add_argument("--after-selection-recent-oos-block-min-samples", type=int, default=2)
    parser.add_argument("--after-selection-recent-oos-block-min-avg-return-pct", type=float, default=5.0)
    parser.add_argument(
        "--after-selection-recent-oos-block-min-compounded-return-pct",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--after-selection-recent-oos-block-max-drawdown-pct",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--after-selection-recent-oos-block-max-avg-cost-drag-pct",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--after-selection-recent-oos-block-max-cost-to-return-ratio",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--after-selection-recent-oos-block-confirmation-warnings",
        action="store_true",
        help="Block overlays that appeared in a recent OOS fold with a train-confirmation warning.",
    )
    parser.add_argument(
        "--after-selection-recent-oos-block-overlays",
        default="",
        help="Comma-separated overlay names eligible for recent-OOS blocking. Empty means every overlay.",
    )
    parser.add_argument("--one-way-trim-min-adverse-reaction", type=float, default=None)
    parser.add_argument("--one-way-trim-cooldown-bars", type=int, default=None)
    parser.add_argument("--one-way-trim-size-mult", type=float, default=None)
    parser.add_argument("--hard-time-exit-fraction", type=float, default=None)
    parser.add_argument("--hard-time-exit-cooldown-bars", type=int, default=None)
    parser.add_argument("--reaction-trim-trend-hold-trigger-mult", type=float, default=None)
    parser.add_argument("--hard-time-exit-trend-defer-bars", type=int, default=None)
    parser.add_argument("--hard-time-exit-trend-defer-min-favorable-reaction", type=float, default=None)
    parser.add_argument("--trend-hold-min-trend-strength", type=float, default=None)
    parser.add_argument("--trend-hold-min-one-way-score", type=float, default=None)
    parser.add_argument("--one-way-trim-retire-same-zone", action="store_true")
    parser.add_argument("--one-way-trim-same-side-cooldown-bars", type=int, default=None)
    parser.add_argument("--one-way-trim-cluster-guard-count", type=int, default=None)
    parser.add_argument("--one-way-trim-cluster-window-bars", type=int, default=None)
    parser.add_argument("--one-way-trim-cluster-cooldown-bars", type=int, default=None)
    parser.add_argument("--one-way-trim-context-guard-count", type=int, default=None)
    parser.add_argument("--one-way-trim-context-window-bars", type=int, default=None)
    parser.add_argument("--one-way-trim-context-cooldown-bars", type=int, default=None)
    parser.add_argument("--one-way-trim-context-full-exit", action="store_true")
    parser.add_argument("--one-way-loss-fuse-min-adverse-reaction", type=float, default=None)
    parser.add_argument("--one-way-loss-fuse-cooldown-bars", type=int, default=None)
    parser.add_argument("--one-way-loss-fuse-size-mult", type=float, default=None)
    parser.add_argument(
        "--one-way-trim-context-after-selection",
        action="store_true",
        help="Select alpha candidates without context quarantine, then apply it only as a test-time risk overlay.",
    )
    parser.add_argument(
        "--one-way-trim-context-after-selection-require-base-reduce",
        action="store_true",
        help=(
            "When context quarantine is applied after selection, only enable it on folds where the "
            "after-selection base-entry reduction overlay was also applied."
        ),
    )
    _add_train_state_after_selection_args(
        parser,
        option_prefix="one-way-trim-context-late",
        description=(
            "Apply context quarantine only when the selected train state matches a late high-turnover "
            "concentration band."
        ),
    )
    parser.add_argument(
        "--one-way-loss-fuse-after-selection",
        action="store_true",
        help="Select alpha candidates without one-way loss fuse, then apply it only as a test-time risk overlay.",
    )
    parser.add_argument("--one-way-loss-fuse-after-selection-min-train-return-pct", type=float, default=None)
    parser.add_argument("--one-way-loss-fuse-after-selection-max-train-return-pct", type=float, default=None)
    parser.add_argument("--one-way-loss-fuse-after-selection-min-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--one-way-loss-fuse-after-selection-max-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--one-way-loss-fuse-after-selection-min-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--one-way-loss-fuse-after-selection-max-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--one-way-trim-full-exit-min-one-way-score", type=float, default=None)
    parser.add_argument("--one-way-trim-full-exit-min-score-diff", type=int, default=None)
    parser.add_argument("--defensive-trim-cooldown-bars", type=int, default=None)
    parser.add_argument("--reaction-trim-size-mult", type=float, default=None)
    parser.add_argument("--regime-router-enabled", action="store_true")
    parser.add_argument("--router-trend-reaction-size-mult", type=float, default=None)
    parser.add_argument("--router-one-way-chase-size-mult", type=float, default=None)
    parser.add_argument("--router-one-way-counter-size-mult", type=float, default=None)
    parser.add_argument("--router-range-probe-size-mult", type=float, default=None)
    parser.add_argument("--router-range-base-size-mult", type=float, default=None)
    parser.add_argument("--router-exhaustion-reversal-size-mult", type=float, default=None)
    parser.add_argument("--router-exhaustion-min-score-edge", type=int, default=None)
    parser.add_argument("--router-exhaustion-min-extension-atr", type=float, default=None)
    parser.add_argument("--router-risk-off-size-mult", type=float, default=None)
    parser.add_argument("--router-transition-trim-fraction", type=float, default=None)
    parser.add_argument("--router-transition-trim-modes", default="")
    parser.add_argument("--router-transition-trim-cooldown-bars", type=int, default=None)
    parser.add_argument(
        "--router-transition-trim-all",
        dest="router_transition_trim_against_only",
        action="store_false",
    )
    parser.set_defaults(router_transition_trim_against_only=True)
    parser.add_argument(
        "--include-no-defensive-trim-cooldown-candidates",
        action="store_true",
        help="When defensive trim cooldown is overridden, also keep otherwise identical source-cooldown candidates.",
    )
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
    parser.add_argument("--near-miss-probe-units", type=float, default=None)
    parser.add_argument("--near-miss-probe-min-score", type=int, default=None)
    parser.add_argument("--near-miss-probe-min-score-edge", type=int, default=None)
    parser.add_argument("--near-miss-probe-min-reason-stack", type=int, default=None)
    parser.add_argument("--near-miss-probe-cooldown-bars", type=int, default=None)
    parser.add_argument("--near-miss-probe-max-extension-atr", type=float, default=None)
    parser.add_argument("--near-miss-probe-failure-guard-count", type=int, default=None)
    parser.add_argument("--near-miss-probe-failure-guard-window-bars", type=int, default=None)
    parser.add_argument("--near-miss-probe-failure-cooldown-bars", type=int, default=None)
    parser.add_argument("--near-miss-probe-allowed-soft-reasons", default=None)
    parser.add_argument("--near-miss-probe-allowed-alignments", default=None)
    parser.add_argument("--near-miss-probe-allowed-execution-contexts", default=None)
    parser.add_argument("--near-miss-probe-allowed-regimes", default=None)
    parser.add_argument(
        "--force-near-miss-in-selection",
        action="store_true",
        help=(
            "When source replay inherits near_miss_after_selection, force the provided near-miss "
            "probe override back into candidate selection."
        ),
    )
    parser.add_argument(
        "--near-miss-context-guard-after-selection",
        action="store_true",
        help=(
            "After all selection overlays and legacy recipes, restrict any active near-miss probe "
            "with the provided near-miss allowed reason/alignment/context/regime filters."
        ),
    )
    parser.add_argument(
        "--near-miss-context-guard-blocked-overlays",
        default="",
        help=(
            "Comma-separated after-selection overlays that prevent the near-miss context guard "
            "from applying when they have already changed the selected config."
        ),
    )
    parser.add_argument(
        "--near-miss-after-selection",
        action="store_true",
        help=(
            "Select candidates without near-miss probes, then conditionally add the probe overlay "
            "to the selected OOS config."
        ),
    )
    parser.add_argument(
        "--near-miss-after-selection-min-train-return-pct",
        type=float,
        default=0.0,
        help=(
            "Minimum selected-train return required before near-miss probes can be added after selection. "
            "Source replay clamps older looser values up to this default unless the CLI overrides it."
        ),
    )
    parser.add_argument("--near-miss-after-selection-max-train-return-pct", type=float, default=None)
    parser.add_argument("--near-miss-after-selection-min-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--near-miss-after-selection-max-train-drawdown-pct", type=float, default=None)
    _add_train_state_after_selection_args(
        parser,
        option_prefix="near-miss-late",
        description=(
            "Apply near-miss probes only when the selected train state matches a late high-turnover "
            "concentration band."
        ),
    )
    _add_train_state_after_selection_args(
        parser,
        option_prefix="near-miss-mid",
        description=(
            "Apply near-miss probes only when the selected train state matches a mid-return "
            "one-way rotation band."
        ),
    )
    _add_near_miss_probe_override_args(parser, option_prefix="near-miss-mid")
    _add_train_state_after_selection_args(
        parser,
        option_prefix="near-miss-activity",
        description=(
            "Apply a small near-miss probe only when the selected train state matches a "
            "low-activity high-drawdown rotation band."
        ),
    )
    _add_near_miss_probe_override_args(parser, option_prefix="near-miss-activity")
    _add_train_state_after_selection_args(
        parser,
        option_prefix="near-miss-high",
        description=(
            "Apply near-miss probes only when the selected train state matches a high-return "
            "low-drawdown concentration band."
        ),
    )
    parser.add_argument(
        "--trend-idle-after-selection",
        action="store_true",
        help="Select alpha candidates without trend-idle probes, then apply them only as a test-time overlay.",
    )
    parser.add_argument("--trend-idle-after-selection-min-train-return-pct", type=float, default=None)
    parser.add_argument("--trend-idle-after-selection-max-train-return-pct", type=float, default=None)
    parser.add_argument("--trend-idle-after-selection-min-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--trend-idle-after-selection-max-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--equity-circuit-breaker-drawdown-pct", type=float, default=None)
    parser.add_argument("--equity-circuit-breaker-pause-bars", type=int, default=None)
    parser.add_argument("--equity-circuit-rearm-drawdown-pct", type=float, default=None)
    parser.add_argument(
        "--equity-circuit-breaker-after-selection",
        action="store_true",
        help="Select alpha candidates without the circuit breaker, then apply it only as a test-time risk overlay.",
    )
    parser.add_argument(
        "--include-no-equity-circuit-candidates",
        action="store_true",
        help="When hard circuit overrides are enabled in selection, also keep otherwise identical candidates without them.",
    )
    parser.add_argument("--equity-soft-circuit-drawdown-pct", type=float, default=None)
    parser.add_argument("--equity-soft-circuit-cooldown-bars", type=int, default=None)
    parser.add_argument("--equity-soft-circuit-size-mult", type=float, default=None)
    parser.add_argument("--equity-soft-circuit-force-flat", action="store_true")
    parser.add_argument("--equity-soft-circuit-prearm-bars", type=int, default=None)
    parser.add_argument("--equity-soft-circuit-min-bars-after-add", type=int, default=None)
    parser.add_argument(
        "--equity-soft-circuit-after-selection",
        action="store_true",
        help="Select alpha candidates without the soft circuit, then apply it only as a test-time risk overlay.",
    )
    parser.add_argument("--equity-soft-circuit-after-selection-min-train-return-pct", type=float, default=None)
    parser.add_argument("--equity-soft-circuit-after-selection-max-train-return-pct", type=float, default=None)
    parser.add_argument("--equity-soft-circuit-after-selection-min-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--equity-soft-circuit-after-selection-max-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--equity-soft-circuit-after-selection-min-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--equity-soft-circuit-after-selection-max-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--equity-soft-circuit-after-selection-require-base-reduce", action="store_true")
    parser.add_argument(
        "--equity-soft-sizer-after-selection",
        action="store_true",
        help=(
            "Select candidates normally, then conditionally apply a second soft equity circuit that "
            "keeps trading but shrinks new adds in profitable, drawdown-sensitive train states."
        ),
    )
    parser.add_argument("--equity-soft-sizer-after-selection-drawdown-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-after-selection-cooldown-bars", type=int, default=None)
    parser.add_argument("--equity-soft-sizer-after-selection-size-mult", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-after-selection-force-flat", action="store_true")
    parser.add_argument("--equity-soft-sizer-after-selection-prearm-bars", type=int, default=None)
    parser.add_argument("--equity-soft-sizer-after-selection-min-source-max-units", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-after-selection-max-source-max-units", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-after-selection-min-train-return-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-after-selection-max-train-return-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-after-selection-min-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-after-selection-max-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-after-selection-min-train-cost-drag-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-after-selection-max-train-cost-drag-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-after-selection-min-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--equity-soft-sizer-after-selection-max-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--equity-soft-sizer-after-selection-min-turnover-per-add", type=float, default=0.0)
    parser.add_argument("--equity-soft-sizer-after-selection-max-turnover-per-add", type=float, default=0.0)
    parser.add_argument(
        "--equity-soft-sizer-alt-after-selection",
        action="store_true",
        help=(
            "Second conditional soft equity sizer for a different train-state band. This lets a "
            "low-return recovery state and a mid-return momentum state use different risk pacing."
        ),
    )
    parser.add_argument("--equity-soft-sizer-alt-after-selection-drawdown-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-alt-after-selection-cooldown-bars", type=int, default=None)
    parser.add_argument("--equity-soft-sizer-alt-after-selection-size-mult", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-alt-after-selection-force-flat", action="store_true")
    parser.add_argument("--equity-soft-sizer-alt-after-selection-prearm-bars", type=int, default=None)
    parser.add_argument("--equity-soft-sizer-alt-after-selection-min-source-max-units", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-alt-after-selection-max-source-max-units", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-alt-after-selection-min-train-return-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-alt-after-selection-max-train-return-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-alt-after-selection-min-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-alt-after-selection-max-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-alt-after-selection-min-train-cost-drag-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-alt-after-selection-max-train-cost-drag-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-alt-after-selection-min-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--equity-soft-sizer-alt-after-selection-max-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--equity-soft-sizer-alt-after-selection-min-turnover-per-add", type=float, default=0.0)
    parser.add_argument("--equity-soft-sizer-alt-after-selection-max-turnover-per-add", type=float, default=0.0)
    parser.add_argument(
        "--equity-soft-sizer-deep-after-selection",
        action="store_true",
        help=(
            "Third conditional soft equity sizer for high-drawdown/high-cost train states where "
            "a deeper temporary size cut improves OOS recovery."
        ),
    )
    parser.add_argument("--equity-soft-sizer-deep-after-selection-drawdown-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-deep-after-selection-cooldown-bars", type=int, default=None)
    parser.add_argument("--equity-soft-sizer-deep-after-selection-size-mult", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-deep-after-selection-force-flat", action="store_true")
    parser.add_argument("--equity-soft-sizer-deep-after-selection-prearm-bars", type=int, default=None)
    parser.add_argument("--equity-soft-sizer-deep-after-selection-min-source-max-units", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-deep-after-selection-max-source-max-units", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-deep-after-selection-min-train-return-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-deep-after-selection-max-train-return-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-deep-after-selection-min-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-deep-after-selection-max-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-deep-after-selection-min-train-cost-drag-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-deep-after-selection-max-train-cost-drag-pct", type=float, default=None)
    parser.add_argument("--equity-soft-sizer-deep-after-selection-min-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--equity-soft-sizer-deep-after-selection-max-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--equity-soft-sizer-deep-after-selection-min-turnover-per-add", type=float, default=0.0)
    parser.add_argument("--equity-soft-sizer-deep-after-selection-max-turnover-per-add", type=float, default=0.0)
    parser.add_argument("--one-way-reversal-switch-units", type=float, default=None)
    parser.add_argument("--one-way-reversal-min-score-edge", type=int, default=None)
    parser.add_argument("--one-way-reversal-cooldown-bars", type=int, default=None)
    parser.add_argument("--one-way-reversal-allow-scenario-override", action="store_true")
    parser.add_argument("--one-way-reversal-allow-score-override", action="store_true")
    parser.add_argument(
        "--one-way-reversal-after-selection",
        action="store_true",
        help=(
            "Select candidates with the normal one-way reversal settings, then conditionally override "
            "the reversal switch size on the OOS window."
        ),
    )
    parser.add_argument("--one-way-reversal-after-selection-switch-units", type=float, default=None)
    parser.add_argument("--one-way-reversal-after-selection-min-train-return-pct", type=float, default=None)
    parser.add_argument("--one-way-reversal-after-selection-max-train-return-pct", type=float, default=None)
    parser.add_argument("--one-way-reversal-after-selection-min-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--one-way-reversal-after-selection-max-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--one-way-reversal-after-selection-min-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--one-way-reversal-after-selection-max-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--one-way-reversal-after-selection-weak-switch-units", type=float, default=None)
    parser.add_argument("--one-way-reversal-after-selection-weak-min-train-return-pct", type=float, default=None)
    parser.add_argument("--one-way-reversal-after-selection-weak-max-train-return-pct", type=float, default=None)
    parser.add_argument("--one-way-reversal-after-selection-weak-min-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--one-way-reversal-after-selection-weak-max-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--one-way-reversal-after-selection-weak-min-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--one-way-reversal-after-selection-weak-max-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--one-way-reversal-after-selection-alt-min-train-return-pct", type=float, default=None)
    parser.add_argument("--one-way-reversal-after-selection-alt-max-train-return-pct", type=float, default=None)
    parser.add_argument("--one-way-reversal-after-selection-alt-min-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--one-way-reversal-after-selection-alt-max-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--one-way-reversal-after-selection-alt-min-train-cost-drag-pct", type=float, default=None)
    parser.add_argument("--one-way-reversal-after-selection-alt-max-train-cost-drag-pct", type=float, default=None)
    parser.add_argument("--one-way-reversal-after-selection-alt-min-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--one-way-reversal-after-selection-alt-max-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--one-way-reversal-after-selection-alt-min-turnover-per-add", type=float, default=0.0)
    parser.add_argument("--one-way-reversal-after-selection-alt-max-turnover-per-add", type=float, default=0.0)
    parser.add_argument("--one-way-reversal-after-selection-alt-min-reaction-trim-per-remove", type=float, default=0.0)
    parser.add_argument("--one-way-reversal-after-selection-alt-max-reaction-trim-per-remove", type=float, default=0.0)
    _add_train_state_after_selection_args(
        parser,
        option_prefix="one-way-reversal-suppress",
        description=(
            "After selection, suppress one-way reversal switches for train states where small "
            "immediate flips historically added drawdown without enough rotation edge."
        ),
    )
    _add_one_way_reversal_tune_after_selection_args(
        parser,
        option_prefix="one-way-reversal-boost",
        description=(
            "After selection, increase the immediate reversal switch size for high-return train "
            "states where stronger flip participation improved OOS rotation capture."
        ),
    )
    _add_one_way_reversal_tune_after_selection_args(
        parser,
        option_prefix="one-way-reversal-fine",
        description=(
            "After selection, use a smaller immediate reversal switch size for concentrated "
            "high-momentum train states where lighter flips reduce churn without muting the trend."
        ),
    )
    parser.add_argument("--one-way-impulse-probe-units", type=float, default=None)
    parser.add_argument("--one-way-impulse-min-one-way-score", type=float, default=None)
    parser.add_argument("--one-way-impulse-min-score-diff", type=int, default=None)
    parser.add_argument("--one-way-impulse-cooldown-bars", type=int, default=None)
    parser.add_argument("--one-way-impulse-max-extension-atr", type=float, default=None)
    _add_one_way_impulse_after_selection_args(
        parser,
        option_prefix="one-way-impulse",
        description=(
            "Select candidates normally, then conditionally add an impulse probe to the OOS config "
            "when the selected train state suggests too few executable rotations."
        ),
    )
    _add_one_way_impulse_after_selection_args(
        parser,
        option_prefix="one-way-impulse-alt",
        description="Alternate after-selection impulse-probe gate for a second train-state band.",
    )
    _add_one_way_impulse_after_selection_args(
        parser,
        option_prefix="one-way-impulse-tail",
        description="Third after-selection impulse-probe gate for a tail train-state band.",
    )
    _add_one_way_impulse_after_selection_args(
        parser,
        option_prefix="one-way-impulse-late",
        description="Fourth after-selection impulse-probe gate for late high-return concentration bands.",
    )
    _add_one_way_impulse_after_selection_args(
        parser,
        option_prefix="one-way-impulse-micro",
        description=(
            "Fifth after-selection impulse-probe gate for sparse but profitable train states where "
            "a tiny probe improves OOS order coverage without materially changing exposure."
        ),
    )
    _add_one_way_impulse_after_selection_args(
        parser,
        option_prefix="role-balance-impulse",
        description=(
            "After selection, apply a strict micro one-way impulse probe for profitable train "
            "states that tend to produce base-role concentration OOS."
        ),
    )
    _add_train_state_after_selection_args(
        parser,
        option_prefix="low-confidence-abstain",
        description=(
            "After selection, skip the next OOS window and record a flat result when the selected "
            "train state matches a low-confidence structure."
        ),
    )
    parser.add_argument("--low-confidence-abstain-after-selection-min-train-score", type=float, default=None)
    parser.add_argument("--low-confidence-abstain-after-selection-max-train-score", type=float, default=None)
    parser.add_argument("--low-confidence-abstain-after-selection-max-chase-add-per-add", type=float, default=0.0)
    parser.add_argument("--low-confidence-abstain-after-selection-min-chase-add-per-add", type=float, default=0.0)
    parser.add_argument("--low-confidence-abstain-after-selection-max-battle-add-per-add", type=float, default=0.0)
    parser.add_argument("--low-confidence-abstain-after-selection-min-battle-add-per-add", type=float, default=0.0)
    parser.add_argument("--scenario-flip-units", type=float, default=None)
    parser.add_argument("--scenario-flip-min-score-edge", type=int, default=None)
    parser.add_argument("--scenario-flip-min-adverse-reaction", type=float, default=None)
    parser.add_argument("--scenario-flip-min-one-way-score", type=float, default=None)
    parser.add_argument("--scenario-flip-cooldown-bars", type=int, default=None)
    parser.add_argument("--scenario-flip-max-extension-atr", type=float, default=None)
    parser.add_argument("--winner-pyramid-units", type=float, default=None)
    parser.add_argument("--winner-pyramid-min-profit-reaction", type=float, default=None)
    parser.add_argument("--winner-pyramid-min-score", type=int, default=None)
    parser.add_argument("--winner-pyramid-min-reason-stack", type=int, default=None)
    parser.add_argument("--winner-pyramid-cooldown-bars", type=int, default=None)
    parser.add_argument("--winner-pyramid-max-units", type=float, default=None)
    parser.add_argument("--winner-pyramid-max-extension-atr", type=float, default=None)
    parser.add_argument("--base-entry-max-extension-atr", type=float, default=None)
    parser.add_argument("--base-entry-max-extension-side", choices=("both", "long", "short"), default="")
    parser.add_argument("--base-entry-reduce-extension-atr", type=float, default=None)
    parser.add_argument("--base-entry-reduce-size-mult", type=float, default=None)
    parser.add_argument("--base-entry-reduce-promote-reaction", type=float, default=None)
    parser.add_argument("--base-entry-reduce-max-trend-strength", type=float, default=None)
    parser.add_argument("--base-entry-reduce-min-trend-strength", type=float, default=None)
    parser.add_argument("--base-entry-reduce-side", choices=("both", "long", "short"), default="")
    parser.add_argument("--base-context-reduce-size-mult", type=float, default=None)
    parser.add_argument("--base-context-reduce-patterns", default="")
    _add_train_state_after_selection_args(
        parser,
        option_prefix="negative-base-context-reduce",
        description=(
            "Apply train-diagnostic negative base-context reduction only inside a targeted selected "
            "train state band."
        ),
    )
    parser.add_argument("--negative-base-context-reduce-size-mult", type=float, default=0.0)
    parser.add_argument("--negative-base-context-reduce-min-loss-usd-units", type=float, default=50.0)
    parser.add_argument("--negative-base-context-reduce-max-per-add-usd-units", type=float, default=0.0)
    parser.add_argument("--negative-base-context-reduce-min-add-count", type=int, default=1)
    parser.add_argument("--negative-base-context-reduce-max-contexts", type=int, default=3)
    parser.add_argument("--event-risk-base-reduce-size-mult", type=float, default=None)
    parser.add_argument("--event-risk-base-reduce-min-extension-atr", type=float, default=None)
    parser.add_argument("--event-risk-base-reduce-max-extension-atr", type=float, default=None)
    parser.add_argument("--event-risk-base-reduce-side", choices=("both", "long", "short"), default="")
    parser.add_argument("--event-risk-base-reduce-contexts", default="")
    parser.add_argument(
        "--base-entry-reduce-after-selection",
        action="store_true",
        help="Select alpha candidates without late-base reduction, then apply it only as a test-time risk overlay.",
    )
    parser.add_argument(
        "--base-entry-reduce-after-selection-max-train-return-pct",
        type=float,
        default=None,
        help=(
            "When set with --base-entry-reduce-after-selection, apply the overlay only if the selected "
            "train return is at or below this value."
        ),
    )
    parser.add_argument(
        "--base-entry-reduce-after-selection-min-train-return-pct",
        type=float,
        default=None,
        help=(
            "When set with --base-entry-reduce-after-selection, apply the overlay only if the selected "
            "train return is at or above this value."
        ),
    )
    parser.add_argument(
        "--base-entry-reduce-after-selection-max-train-drawdown-pct",
        type=float,
        default=None,
        help=(
            "When set with --base-entry-reduce-after-selection, apply the overlay only if the selected "
            "train max drawdown is at or below this value."
        ),
    )
    parser.add_argument(
        "--base-entry-reduce-after-selection-min-one-way-trim-per-add",
        type=float,
        default=0.0,
        help=(
            "When set with --base-entry-reduce-after-selection, apply the overlay only if the selected "
            "train one-way forced trim/add ratio is at or above this value."
        ),
    )
    _add_train_state_after_selection_args(
        parser,
        option_prefix="base-reduce-suppress",
        description=(
            "After selection, neutralize late-base reduction for train states where it over-defended "
            "and removed otherwise valid rotation entries."
        ),
    )
    parser.add_argument("--fragile-regime-entry-size-mult", type=float, default=None)
    parser.add_argument("--fragile-regime-entry-regimes", default="")
    parser.add_argument("--fragile-regime-inventory-trim-fraction", type=float, default=None)
    parser.add_argument("--fragile-regime-inventory-trim-regimes", default="")
    parser.add_argument(
        "--fragile-regime-entry-after-selection",
        action="store_true",
        help=(
            "Select candidates normally, then conditionally shrink or block new entries in fragile "
            "regimes on the OOS window."
        ),
    )
    parser.add_argument("--fragile-regime-entry-after-selection-min-train-return-pct", type=float, default=None)
    parser.add_argument("--fragile-regime-entry-after-selection-max-train-return-pct", type=float, default=None)
    parser.add_argument("--fragile-regime-entry-after-selection-min-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--fragile-regime-entry-after-selection-max-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--fragile-regime-entry-high-size-mult", type=float, default=None)
    parser.add_argument("--fragile-regime-entry-high-regimes", default="")
    _add_train_state_after_selection_args(
        parser,
        option_prefix="fragile-regime-entry-high",
        description=(
            "Apply a second fragile-regime entry shrink only when the selected train state matches "
            "a high-return low-drawdown band."
        ),
    )
    parser.add_argument("--fragile-regime-entry-low-size-mult", type=float, default=None)
    parser.add_argument("--fragile-regime-entry-low-regimes", default="")
    _add_train_state_after_selection_args(
        parser,
        option_prefix="fragile-regime-entry-low",
        description=(
            "Apply a third fragile-regime entry shrink only when the selected train state matches "
            "a low-return high-forced-trim recovery band."
        ),
    )
    parser.add_argument(
        "--fragile-regime-inventory-trim-after-selection",
        action="store_true",
        help=(
            "Select candidates normally, then conditionally trim existing inventory when the OOS "
            "market first transitions into configured fragile regimes."
        ),
    )
    parser.add_argument(
        "--fragile-regime-inventory-trim-after-selection-min-train-return-pct",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--fragile-regime-inventory-trim-after-selection-max-train-return-pct",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--fragile-regime-inventory-trim-after-selection-min-train-drawdown-pct",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--fragile-regime-inventory-trim-after-selection-max-train-drawdown-pct",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--risk-smoothing-after-selection",
        action="store_true",
        help=(
            "Select candidates normally, then conditionally smooth OOS exposure sizing for train "
            "states that look profitable but drawdown-concentrated."
        ),
    )
    parser.add_argument("--risk-smoothing-after-selection-max-possible-units", type=float, default=None)
    parser.add_argument("--risk-smoothing-after-selection-base-max-units", type=float, default=None)
    parser.add_argument("--risk-smoothing-after-selection-battle-units", type=float, default=None)
    parser.add_argument("--risk-smoothing-after-selection-defensive-trim-cooldown-bars", type=int, default=None)
    parser.add_argument("--risk-smoothing-after-selection-max-hold-bars", type=int, default=None)
    parser.add_argument("--risk-smoothing-after-selection-min-train-return-pct", type=float, default=None)
    parser.add_argument("--risk-smoothing-after-selection-max-train-return-pct", type=float, default=None)
    parser.add_argument("--risk-smoothing-after-selection-min-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--risk-smoothing-after-selection-max-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--risk-smoothing-after-selection-min-train-cost-drag-pct", type=float, default=None)
    parser.add_argument("--risk-smoothing-after-selection-max-train-cost-drag-pct", type=float, default=None)
    parser.add_argument("--risk-smoothing-after-selection-min-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--risk-smoothing-after-selection-max-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--risk-smoothing-after-selection-min-turnover-per-add", type=float, default=0.0)
    parser.add_argument("--risk-smoothing-after-selection-max-turnover-per-add", type=float, default=0.0)
    _add_train_state_after_selection_args(
        parser,
        option_prefix="hold-compression",
        description=(
            "After selection, shorten max hold bars for medium-return train states where long "
            "inventory tails caused OOS drawdown without adding enough trend capture."
        ),
    )
    parser.add_argument("--hold-compression-after-selection-max-hold-bars", type=int, default=None)
    _add_train_state_after_selection_args(
        parser,
        option_prefix="hold-extension",
        description=(
            "After selection, lengthen max hold bars for low-return train states where a slightly "
            "longer continuation hold improved OOS cost-adjusted capture."
        ),
    )
    parser.add_argument("--hold-extension-after-selection-max-hold-bars", type=int, default=None)
    _add_train_state_after_selection_args(
        parser,
        option_prefix="reaction-tune",
        description=(
            "After selection, tune reaction trim and repair thresholds for train states where "
            "exits were too quick for OOS trend continuation."
        ),
    )
    parser.add_argument("--reaction-tune-after-selection-reaction-trim-trigger", type=float, default=None)
    parser.add_argument("--reaction-tune-after-selection-repair-cut", type=float, default=None)
    parser.add_argument("--reaction-tune-after-selection-repair-stop", type=float, default=None)
    _add_train_state_after_selection_args(
        parser,
        option_prefix="reaction-tune-strong",
        description=(
            "After selection, apply a stronger reaction trim delay for weak high-drawdown train "
            "states where the base tune still exits trends too early."
        ),
    )
    parser.add_argument("--reaction-tune-strong-after-selection-reaction-trim-trigger", type=float, default=None)
    parser.add_argument("--reaction-tune-strong-after-selection-repair-cut", type=float, default=None)
    parser.add_argument("--reaction-tune-strong-after-selection-repair-stop", type=float, default=None)
    _add_train_state_after_selection_args(
        parser,
        option_prefix="exit-trend-hold",
        description=(
            "After selection, delay reaction/time exits only for train states where trend-continuation "
            "holds can reduce cost without changing candidate selection."
        ),
    )
    parser.add_argument("--exit-trend-hold-after-selection-reaction-trim-trigger-mult", type=float, default=None)
    parser.add_argument("--exit-trend-hold-after-selection-hard-time-defer-bars", type=int, default=None)
    parser.add_argument(
        "--exit-trend-hold-after-selection-hard-time-min-favorable-reaction",
        type=float,
        default=None,
    )
    parser.add_argument("--exit-trend-hold-after-selection-min-trend-strength", type=float, default=None)
    parser.add_argument("--exit-trend-hold-after-selection-min-one-way-score", type=float, default=None)
    _add_train_state_after_selection_args(
        parser,
        option_prefix="repair-tune",
        description=(
            "After selection, tune repair thresholds for high-cost train states where slightly "
            "earlier repair improved OOS recovery without adding churn."
        ),
    )
    parser.add_argument("--repair-tune-after-selection-repair-cut", type=float, default=None)
    parser.add_argument("--repair-tune-after-selection-repair-stop", type=float, default=None)
    _add_train_state_after_selection_args(
        parser,
        option_prefix="repair-tune-high-cost",
        description=(
            "After selection, apply a narrower repair threshold tune for high-cost runner states "
            "where the broad repair tune is too loose."
        ),
    )
    parser.add_argument("--repair-tune-high-cost-after-selection-repair-cut", type=float, default=None)
    parser.add_argument("--repair-tune-high-cost-after-selection-repair-stop", type=float, default=None)
    _add_train_state_after_selection_args(
        parser,
        option_prefix="distribution-balance",
        description=(
            "After selection, add tiny near-miss probes for high-turnover train states whose OOS "
            "adds can otherwise concentrate in one calendar bucket."
        ),
    )
    _add_near_miss_probe_override_args(parser, option_prefix="distribution-balance")
    _add_trim_cooldown_after_selection_args(
        parser,
        option_prefix="high-cost-balance",
        description=(
            "After selection, add a risk-quality balance profile for high-cost runner states by "
            "combining a longer forced-trim cooldown with tiny near-miss probes."
        ),
    )
    _add_near_miss_probe_override_args(parser, option_prefix="high-cost-balance")
    _add_trim_cooldown_after_selection_args(
        parser,
        option_prefix="trim-cooldown",
        description=(
            "After selection, lengthen one-way forced-trim cooldown, optionally with late-base "
            "size reduction, for train states where repeated forced trims cut trend legs too early."
        ),
    )
    _add_trim_cooldown_after_selection_args(
        parser,
        option_prefix="trim-cooldown-deep",
        description=(
            "After selection, apply a second trim-cooldown profile for deep forced-trim states "
            "that also need late-base size reduction."
        ),
    )
    _add_trim_cooldown_after_selection_args(
        parser,
        option_prefix="trim-cooldown-strong",
        description=(
            "After selection, apply a second trim-cooldown delay for weak high-drawdown reaction "
            "states where trend legs were still cut too early."
        ),
    )
    _add_trim_cooldown_after_selection_args(
        parser,
        option_prefix="trim-cooldown-high-cost",
        description=(
            "After selection, apply trim-cooldown delay for high-cost runner states where fewer "
            "forced trims improved both return and cost."
        ),
    )
    _add_train_state_after_selection_args(
        parser,
        option_prefix="risk-off-micro",
        description=(
            "After selection, shrink unit caps and optionally speed reaction trim for risk-off train "
            "states where only a small probe should remain active."
        ),
    )
    parser.add_argument("--risk-off-micro-after-selection-max-possible-units", type=float, default=None)
    parser.add_argument("--risk-off-micro-after-selection-base-max-units", type=float, default=None)
    parser.add_argument("--risk-off-micro-after-selection-battle-units", type=float, default=None)
    parser.add_argument("--risk-off-micro-after-selection-trend-core-units", type=float, default=None)
    parser.add_argument("--risk-off-micro-after-selection-reaction-trim-trigger", type=float, default=None)
    _add_train_state_after_selection_args(
        parser,
        option_prefix="battle-restore",
        description=(
            "After selection, selectively reopen battle participation for train states where "
            "base/probe roles dominated but return, cost, and drawdown stayed acceptable."
        ),
    )
    parser.add_argument("--battle-restore-after-selection-min-battle-add-per-add", type=float, default=0.0)
    parser.add_argument("--battle-restore-after-selection-max-battle-add-per-add", type=float, default=0.0)
    parser.add_argument("--battle-restore-after-selection-min-max-role-add-share", type=float, default=0.0)
    parser.add_argument("--battle-restore-after-selection-max-max-role-add-share", type=float, default=0.0)
    parser.add_argument("--battle-restore-after-selection-min-add-events", type=int, default=0)
    parser.add_argument("--battle-restore-after-selection-max-add-events", type=int, default=0)
    parser.add_argument("--battle-restore-after-selection-battle-units", type=float, default=None)
    parser.add_argument("--battle-restore-after-selection-battle-score", type=int, default=None)
    parser.add_argument("--battle-restore-after-selection-battle-trigger-usd", type=float, default=None)
    parser.add_argument("--battle-restore-after-selection-battle-trigger-atr", type=float, default=None)
    parser.add_argument("--battle-restore-after-selection-max-repair-eff-for-add", type=float, default=None)
    parser.add_argument("--battle-restore-after-selection-min-capacity-ratio", type=float, default=None)
    parser.add_argument(
        "--exposure-rebalance-after-selection",
        action="store_true",
        help=(
            "Select candidates normally, then conditionally rebalance unit granularity on the OOS "
            "config when train state suggests concentrated exposure risk."
        ),
    )
    parser.add_argument("--exposure-rebalance-after-selection-max-possible-units", type=float, default=None)
    parser.add_argument("--exposure-rebalance-after-selection-base-max-units", type=float, default=None)
    parser.add_argument("--exposure-rebalance-after-selection-base-add-units", type=float, default=None)
    parser.add_argument("--exposure-rebalance-after-selection-battle-units", type=float, default=None)
    parser.add_argument("--exposure-rebalance-after-selection-min-source-max-units", type=float, default=None)
    parser.add_argument("--exposure-rebalance-after-selection-max-source-max-units", type=float, default=None)
    parser.add_argument("--exposure-rebalance-after-selection-min-train-return-pct", type=float, default=None)
    parser.add_argument("--exposure-rebalance-after-selection-max-train-return-pct", type=float, default=None)
    parser.add_argument("--exposure-rebalance-after-selection-min-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--exposure-rebalance-after-selection-max-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--exposure-rebalance-after-selection-min-train-cost-drag-pct", type=float, default=None)
    parser.add_argument("--exposure-rebalance-after-selection-max-train-cost-drag-pct", type=float, default=None)
    parser.add_argument("--exposure-rebalance-after-selection-min-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--exposure-rebalance-after-selection-max-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--exposure-rebalance-after-selection-min-turnover-per-add", type=float, default=0.0)
    parser.add_argument("--exposure-rebalance-after-selection-max-turnover-per-add", type=float, default=0.0)
    parser.add_argument(
        "--include-no-impulse-candidates",
        action="store_true",
        help="When impulse overrides are enabled, also keep otherwise identical candidates without impulse probes.",
    )
    parser.add_argument(
        "--include-no-btc-rotation-candidates",
        action="store_true",
        help="When BTC-only flip/pyramid overrides are enabled, also keep otherwise identical candidates without them.",
    )
    parser.add_argument(
        "--include-no-base-reduce-candidates",
        action="store_true",
        help="When late-base reduction overrides are enabled, also keep otherwise identical candidates without them.",
    )
    parser.add_argument(
        "--include-no-one-way-loss-fuse-candidates",
        action="store_true",
        help="When one-way loss fuse overrides are enabled, also keep otherwise identical candidates without them.",
    )
    parser.add_argument(
        "--include-no-near-miss-probe-candidates",
        action="store_true",
        help="When near-miss probe overrides are enabled, also keep otherwise identical candidates without them.",
    )
    parser.add_argument(
        "--impulse-selection-score-penalty",
        type=float,
        default=0.0,
        help="Optional train-selection penalty for impulse-probe candidates; use only as a promotion gate.",
    )
    parser.add_argument(
        "--btc-rotation-selection-score-penalty",
        type=float,
        default=0.0,
        help="Optional train-selection penalty for BTC-only scenario-flip or winner-pyramid candidates.",
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
    parser.add_argument(
        "--selection-mdd-soft-threshold-pct",
        type=float,
        default=0.0,
        help="Optional train-window MDD threshold for extra candidate-selection penalty.",
    )
    parser.add_argument(
        "--selection-mdd-soft-penalty",
        type=float,
        default=0.0,
        help="Penalty per one percentage point of train-window MDD above the soft threshold.",
    )
    parser.add_argument(
        "--selection-cost-soft-threshold-pct",
        type=float,
        default=0.0,
        help="Optional train-window estimated cost-drag threshold for extra candidate-selection penalty.",
    )
    parser.add_argument(
        "--selection-cost-soft-penalty",
        type=float,
        default=0.0,
        help="Penalty per one percentage point of train-window cost drag above the soft threshold.",
    )
    parser.add_argument(
        "--selection-stress-cost-multiplier",
        type=float,
        default=0.0,
        help=(
            "Optional train-window stress cost multiplier used for candidate ranking. "
            "When enabled, gross_return - multiplier*cost_drag - funding_proxy is compared to a floor."
        ),
    )
    parser.add_argument(
        "--selection-stress-funding-proxy-pct",
        type=float,
        default=0.0,
        help="Conservative extra train-window funding/carry proxy subtracted from the stress return estimate.",
    )
    parser.add_argument(
        "--selection-stress-min-return-floor-pct",
        type=float,
        default=0.0,
        help="Minimum train-window stressed return estimate before stress-floor penalty applies.",
    )
    parser.add_argument(
        "--selection-stress-floor-gap-penalty",
        type=float,
        default=0.0,
        help="Penalty per one percentage point that the train-window stressed return estimate falls below floor.",
    )
    parser.add_argument(
        "--selection-cost-to-gross-threshold",
        type=float,
        default=0.0,
        help="Optional train-window modeled cost/gross-return ratio threshold for candidate-selection penalty.",
    )
    parser.add_argument(
        "--selection-cost-to-gross-penalty",
        type=float,
        default=0.0,
        help="Penalty per 1.00 ratio point above the cost/gross-return threshold.",
    )
    parser.add_argument(
        "--selection-reaction-usd-risk-threshold",
        type=float,
        default=0.0,
        help="Apply the reaction-USD risk penalty to candidates at or above this reaction_usd value.",
    )
    parser.add_argument(
        "--selection-reaction-usd-risk-penalty",
        type=float,
        default=0.0,
        help="Fixed candidate-selection penalty for high reaction_usd candidates in risky train states.",
    )
    parser.add_argument("--selection-reaction-usd-risk-min-train-drawdown-pct", type=float, default=0.0)
    parser.add_argument("--selection-reaction-usd-risk-min-turnover-per-add", type=float, default=0.0)
    parser.add_argument("--selection-reaction-usd-risk-min-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--selection-reaction-usd-risk-min-cost-drag-pct", type=float, default=0.0)
    parser.add_argument(
        "--selection-max-reaction-usd",
        type=float,
        default=0.0,
        help="Hard cap for train candidate reaction_usd; candidates above the cap are not selectable.",
    )
    parser.add_argument(
        "--selection-stress-unresolved-keep-raw-leader",
        action="store_true",
        help=(
            "When no train candidate clears the stressed-return floor, keep the raw train-score "
            "leader if the penalized selection gives up too much train return without resolving stress."
        ),
    )
    parser.add_argument(
        "--selection-stress-unresolved-return-giveback-pct",
        type=float,
        default=0.0,
        help=(
            "Minimum train-return percentage-point giveback versus the raw train-score leader "
            "before unresolved-stress selection is reverted."
        ),
    )
    parser.add_argument(
        "--selection-stress-unresolved-leader-metric",
        choices=("raw_score", "train_return"),
        default="raw_score",
        help=(
            "Leader to preserve when stress remains unresolved: the raw score leader, or the "
            "highest train-return candidate."
        ),
    )
    parser.add_argument(
        "--selection-stress-unresolved-low-return-max-selected-pct",
        type=float,
        default=None,
        help=(
            "Optional lower train-return band where unresolved-stress guard can use a smaller "
            "return-giveback threshold."
        ),
    )
    parser.add_argument(
        "--selection-stress-unresolved-low-return-giveback-pct",
        type=float,
        default=None,
        help="Return giveback threshold used inside the low selected-train-return band.",
    )
    parser.add_argument(
        "--selection-stress-unresolved-drawdown-rescue-min-selected-pct",
        type=float,
        default=None,
        help="Optional selected train-return lower bound for unresolved-stress high-drawdown leader rescue.",
    )
    parser.add_argument(
        "--selection-stress-unresolved-drawdown-rescue-max-selected-pct",
        type=float,
        default=None,
        help="Optional selected train-return upper bound for unresolved-stress high-drawdown leader rescue.",
    )
    parser.add_argument(
        "--selection-stress-unresolved-drawdown-rescue-min-leader-dd-pct",
        type=float,
        default=None,
        help="Minimum leader train drawdown for unresolved-stress high-drawdown leader rescue.",
    )
    parser.add_argument(
        "--selection-stress-unresolved-drawdown-rescue-giveback-pct",
        type=float,
        default=None,
        help="Return giveback threshold for unresolved-stress high-drawdown leader rescue.",
    )
    parser.add_argument(
        "--selection-negative-train-distribution-rescue",
        action="store_true",
        help=(
            "Prefer a candidate that matches the negative-train-distribution replay gate when "
            "the selected train winner is only marginally positive/negative and the return "
            "giveback stays within the configured budget."
        ),
    )
    parser.add_argument(
        "--selection-negative-train-distribution-min-selected-return-pct",
        type=float,
        default=None,
        help="Optional selected train-return lower bound for negative-train-distribution rescue.",
    )
    parser.add_argument(
        "--selection-negative-train-distribution-max-selected-return-pct",
        type=float,
        default=None,
        help="Optional selected train-return upper bound for negative-train-distribution rescue.",
    )
    parser.add_argument(
        "--selection-negative-train-distribution-max-return-giveback-pct",
        type=float,
        default=0.0,
        help=(
            "Maximum train-return percentage-point giveback allowed when selecting a "
            "negative-train-distribution repair candidate."
        ),
    )
    parser.add_argument(
        "--selection-high-cost-runner-rescue",
        action="store_true",
        help=(
            "Prefer a candidate that matches the high-cost runner tight-repair replay gate when "
            "stress remains unresolved and the train-return leader only has a small return edge."
        ),
    )
    parser.add_argument(
        "--selection-high-cost-runner-min-selected-return-pct",
        type=float,
        default=None,
        help="Optional selected train-return lower bound for high-cost runner rescue.",
    )
    parser.add_argument(
        "--selection-high-cost-runner-max-selected-return-pct",
        type=float,
        default=None,
        help="Optional selected train-return upper bound for high-cost runner rescue.",
    )
    parser.add_argument(
        "--selection-high-cost-runner-max-return-giveback-pct",
        type=float,
        default=0.0,
        help="Maximum train-return percentage-point giveback allowed for high-cost runner rescue.",
    )
    parser.add_argument(
        "--selection-deep-soft-overlay-rescue",
        action="store_true",
        help=(
            "Prefer a candidate that satisfies the deep soft-sizer and near-miss activity gates "
            "when the train-return leader has only a small edge."
        ),
    )
    parser.add_argument(
        "--selection-deep-soft-overlay-min-selected-return-pct",
        type=float,
        default=None,
        help="Optional selected train-return lower bound for deep soft overlay rescue.",
    )
    parser.add_argument(
        "--selection-deep-soft-overlay-max-selected-return-pct",
        type=float,
        default=None,
        help="Optional selected train-return upper bound for deep soft overlay rescue.",
    )
    parser.add_argument(
        "--selection-deep-soft-overlay-max-return-giveback-pct",
        type=float,
        default=0.0,
        help="Maximum train-return percentage-point giveback allowed for deep soft overlay rescue.",
    )
    parser.add_argument(
        "--selection-deep-drawdown-reversal-rescue",
        action="store_true",
        help=(
            "Prefer a candidate that matches the deep-drawdown reversal replay gate when the "
            "train-return leader has only a small edge."
        ),
    )
    parser.add_argument(
        "--selection-deep-drawdown-reversal-min-selected-return-pct",
        type=float,
        default=None,
        help="Optional selected train-return lower bound for deep-drawdown reversal rescue.",
    )
    parser.add_argument(
        "--selection-deep-drawdown-reversal-max-selected-return-pct",
        type=float,
        default=None,
        help="Optional selected train-return upper bound for deep-drawdown reversal rescue.",
    )
    parser.add_argument(
        "--selection-deep-drawdown-reversal-max-return-giveback-pct",
        type=float,
        default=0.0,
        help="Maximum train-return percentage-point giveback allowed for deep-drawdown reversal rescue.",
    )
    parser.add_argument(
        "--selection-deep-drawdown-reversal-max-candidate-one-way-trim-per-add",
        type=float,
        default=None,
        help=(
            "Optional absolute one-way forced-trim/add cap for deep-drawdown reversal rescue "
            "candidates. This prevents selecting reversal-scale repairs that add too much "
            "forced exit churn."
        ),
    )
    parser.add_argument(
        "--selection-deep-drawdown-reversal-max-one-way-trim-increase-per-add",
        type=float,
        default=None,
        help=(
            "Optional maximum one-way forced-trim/add increase versus the currently selected "
            "train candidate for deep-drawdown reversal rescue."
        ),
    )
    parser.add_argument(
        "--selection-one-way-trim-ratio-threshold",
        type=float,
        default=0.0,
        help="Optional one-way forced-trim/add ratio threshold for extra candidate-selection penalty.",
    )
    parser.add_argument(
        "--selection-one-way-trim-ratio-penalty",
        type=float,
        default=0.0,
        help="Penalty per 1.00 ratio point above the one-way forced-trim/add threshold.",
    )
    parser.add_argument(
        "--selection-turnover-per-add-threshold",
        type=float,
        default=0.0,
        help="Optional turnover-events/add threshold for extra candidate-selection penalty.",
    )
    parser.add_argument(
        "--selection-turnover-per-add-penalty",
        type=float,
        default=0.0,
        help="Penalty per 1.00 ratio point above the turnover-events/add threshold.",
    )
    parser.add_argument(
        "--selection-low-activity-coverage-threshold",
        type=float,
        default=0.0,
        help=(
            "Optional train-window add-event coverage threshold. Candidates below this "
            "add_events/expected_add_events coverage receive an activity penalty."
        ),
    )
    parser.add_argument(
        "--selection-low-activity-penalty",
        type=float,
        default=0.0,
        help="Penalty per 1.00 add-event coverage gap below the low-activity threshold.",
    )
    parser.add_argument(
        "--selection-soft-no-trade-per-1k-threshold",
        type=float,
        default=0.0,
        help=(
            "Optional threshold for MC12/MC04 soft no-trade blockers per 1,000 train bars. "
            "Candidates above the threshold receive a selection penalty."
        ),
    )
    parser.add_argument(
        "--selection-soft-no-trade-per-1k-penalty",
        type=float,
        default=0.0,
        help="Penalty per 1.0 soft no-trade blocker per 1,000 train bars above the threshold.",
    )
    parser.add_argument(
        "--selection-role-concentration-threshold",
        type=float,
        default=0.0,
        help=(
            "Optional max single-role add share threshold for candidate-selection penalty. "
            "This dampens train winners that rely too heavily on one entry role."
        ),
    )
    parser.add_argument(
        "--selection-role-concentration-min-add-events",
        type=int,
        default=0,
        help="Minimum train add-event count before the role-concentration selection penalty can apply.",
    )
    parser.add_argument(
        "--selection-role-concentration-penalty",
        type=float,
        default=0.0,
        help="Penalty per 1.00 role-share point above the role-concentration threshold.",
    )
    parser.add_argument(
        "--selection-base-dominance-threshold",
        type=float,
        default=0.0,
        help=(
            "Optional base-entry add share threshold for candidate-selection penalty. "
            "This specifically dampens candidates whose train edge came mostly from base entries."
        ),
    )
    parser.add_argument("--selection-base-dominance-min-add-events", type=int, default=0)
    parser.add_argument("--selection-base-dominance-min-train-return-pct", type=float, default=None)
    parser.add_argument("--selection-base-dominance-max-train-return-pct", type=float, default=None)
    parser.add_argument("--selection-base-dominance-min-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--selection-base-dominance-max-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--selection-base-dominance-min-train-cost-drag-pct", type=float, default=None)
    parser.add_argument("--selection-base-dominance-max-train-cost-drag-pct", type=float, default=None)
    parser.add_argument(
        "--selection-base-dominance-penalty",
        type=float,
        default=0.0,
        help="Penalty per 1.00 base-entry share point above the base-dominance threshold.",
    )
    parser.add_argument(
        "--selection-structural-flag-min-train-return-pct",
        type=float,
        default=0.0,
        help=(
            "Apply an extra selection penalty only to train candidates at or above this return "
            "threshold when they have structural fragility flags."
        ),
    )
    parser.add_argument(
        "--selection-structural-flag-penalty",
        type=float,
        default=0.0,
        help="Extra selection penalty per structural fragility flag on qualifying high-return train candidates.",
    )
    parser.add_argument(
        "--selection-high-train-flag-min-return-pct",
        type=float,
        default=0.0,
        help=(
            "Apply an extra per-flag selection penalty only when the train return is at or above "
            "this threshold. This dampens fragile high in-sample winners without penalizing "
            "moderate-return setups."
        ),
    )
    parser.add_argument(
        "--selection-high-train-flag-penalty",
        type=float,
        default=0.0,
        help="Extra selection penalty per distribution flag on qualifying high-return train candidates.",
    )
    parser.add_argument("--selection-low-train-max-unit-min-return-pct", type=float, default=None)
    parser.add_argument("--selection-low-train-max-unit-max-return-pct", type=float, default=None)
    parser.add_argument(
        "--selection-low-train-max-unit-threshold",
        type=float,
        default=0.0,
        help="Optional max_possible_units threshold for low-train-return candidate penalty.",
    )
    parser.add_argument(
        "--selection-low-train-max-unit-penalty",
        type=float,
        default=0.0,
        help=(
            "Fixed candidate-selection penalty when train return is in the configured low-return "
            "band and max_possible_units is above the threshold."
        ),
    )
    parser.add_argument(
        "--selection-one-way-loss-fuse-bonus",
        type=float,
        default=0.0,
        help=(
            "Optional selection-score bonus for candidates that actively reduce base entries after "
            "a one-way adverse loss fuse. Default 0 keeps the live policy unchanged."
        ),
    )
    parser.add_argument(
        "--selection-low-unit-reversal-bonus",
        type=float,
        default=0.0,
        help=(
            "Optional selection-score bonus for low-unit candidates that keep reversal switching "
            "active in a configured train return/drawdown band. Default 0 keeps ranking unchanged."
        ),
    )
    parser.add_argument("--selection-low-unit-reversal-max-units", type=float, default=0.0)
    parser.add_argument("--selection-low-unit-reversal-min-switch-units", type=float, default=0.0)
    parser.add_argument("--selection-low-unit-reversal-min-train-return-pct", type=float, default=None)
    parser.add_argument("--selection-low-unit-reversal-max-train-return-pct", type=float, default=None)
    parser.add_argument("--selection-low-unit-reversal-min-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--selection-low-unit-reversal-max-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--selection-low-unit-reversal-min-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--selection-low-unit-reversal-max-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument(
        "--selection-drawdown-reversal-bonus",
        type=float,
        default=0.0,
        help=(
            "Optional selection-score bonus for low-unit reversal candidates that survived a "
            "configured high-drawdown/high-cost train band. Default 0 keeps ranking unchanged."
        ),
    )
    parser.add_argument("--selection-drawdown-reversal-max-units", type=float, default=0.0)
    parser.add_argument("--selection-drawdown-reversal-min-switch-units", type=float, default=0.0)
    parser.add_argument("--selection-drawdown-reversal-min-train-return-pct", type=float, default=None)
    parser.add_argument("--selection-drawdown-reversal-max-train-return-pct", type=float, default=None)
    parser.add_argument("--selection-drawdown-reversal-min-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--selection-drawdown-reversal-max-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--selection-drawdown-reversal-min-train-cost-drag-pct", type=float, default=None)
    parser.add_argument("--selection-drawdown-reversal-max-train-cost-drag-pct", type=float, default=None)
    parser.add_argument("--selection-drawdown-reversal-min-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--selection-drawdown-reversal-max-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--selection-drawdown-reversal-min-turnover-per-add", type=float, default=0.0)
    parser.add_argument("--selection-drawdown-reversal-max-turnover-per-add", type=float, default=0.0)
    parser.add_argument(
        "--selection-short-hold-structural-bonus",
        type=float,
        default=0.0,
        help=(
            "Optional selection-score bonus for shorter max-hold candidates in a configured "
            "structural train band. Default 0 keeps ranking unchanged."
        ),
    )
    parser.add_argument("--selection-short-hold-max-bars", type=int, default=0)
    parser.add_argument("--selection-short-hold-min-train-return-pct", type=float, default=None)
    parser.add_argument("--selection-short-hold-max-train-return-pct", type=float, default=None)
    parser.add_argument("--selection-short-hold-min-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--selection-short-hold-max-train-drawdown-pct", type=float, default=None)
    parser.add_argument("--selection-short-hold-min-max-units", type=float, default=0.0)
    parser.add_argument("--selection-short-hold-max-max-units", type=float, default=0.0)
    parser.add_argument("--selection-short-hold-min-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--selection-short-hold-max-one-way-trim-per-add", type=float, default=0.0)
    parser.add_argument("--selection-short-hold-min-turnover-per-add", type=float, default=0.0)
    parser.add_argument("--selection-short-hold-max-turnover-per-add", type=float, default=0.0)
    parser.add_argument(
        "--selection-fast-defense-structural-penalty",
        type=float,
        default=0.0,
        help=(
            "Fixed candidate-selection penalty for fast defensive-cooldown candidates whose train "
            "window also shows high one-way forced trims and turnover. Default 0 keeps ranking unchanged."
        ),
    )
    parser.add_argument(
        "--selection-fast-defense-max-cooldown-bars",
        type=int,
        default=0,
        help="Maximum defensive_trim_cooldown_bars treated as fast-defense for the structural penalty.",
    )
    parser.add_argument(
        "--selection-fast-defense-min-train-return-pct",
        type=float,
        default=0.0,
        help="Minimum train return required before applying the fast-defense structural penalty.",
    )
    parser.add_argument(
        "--selection-fast-defense-min-one-way-trim-per-add",
        type=float,
        default=0.0,
        help="Minimum one-way forced-trim/add ratio for the fast-defense structural penalty.",
    )
    parser.add_argument(
        "--selection-fast-defense-min-turnover-per-add",
        type=float,
        default=0.0,
        help="Minimum turnover-events/add ratio for the fast-defense structural penalty.",
    )
    parser.add_argument(
        "--selection-regime-dependency-threshold",
        type=float,
        default=0.0,
        help=(
            "Optional threshold for the share of positive train regime return coming from one "
            "regime. Above this, the regime-dependency penalty can be applied."
        ),
    )
    parser.add_argument(
        "--selection-regime-dependency-min-train-return-pct",
        type=float,
        default=0.0,
        help="Minimum train return required before applying the regime-dependency penalty.",
    )
    parser.add_argument(
        "--selection-regime-dependency-penalty",
        type=float,
        default=0.0,
        help="Fixed candidate-selection penalty for train candidates dominated by one return regime.",
    )
    parser.add_argument(
        "--selection-recent-efficiency-lookback",
        type=int,
        default=0,
        help=(
            "Optional number of previous completed folds used to penalize the same candidate family "
            "when high train returns have not translated into OOS returns."
        ),
    )
    parser.add_argument(
        "--selection-recent-efficiency-min-samples",
        type=int,
        default=2,
        help="Minimum matched completed folds required before applying the recent-efficiency penalty.",
    )
    parser.add_argument(
        "--selection-recent-efficiency-min-train-return-pct",
        type=float,
        default=100.0,
        help="Minimum train return for a completed fold or candidate to participate in the efficiency guard.",
    )
    parser.add_argument(
        "--selection-recent-efficiency-threshold",
        type=float,
        default=0.0,
        help="Minimum recent OOS/train return ratio expected from a candidate family before penalty.",
    )
    parser.add_argument(
        "--selection-recent-efficiency-penalty",
        type=float,
        default=0.0,
        help="Fixed candidate-selection penalty when the recent-efficiency guard is triggered.",
    )
    parser.add_argument("--min-periods", type=int, default=5000)
    parser.add_argument("--cache-dir", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    parser.add_argument(
        "--test-top-train-candidates",
        type=int,
        default=0,
        help=(
            "Diagnostic only. Also evaluate the top N train-ranked candidates on the OOS window "
            "with the same after-selection overlays, so selection misses can be separated from bad regimes."
        ),
    )
    parser.add_argument(
        "--high-return-soft-sizer-relax-drawdown-pct",
        type=float,
        default=11.0,
        help=(
            "Drawdown trigger used by the model-encoded high_return_soft_sizer_relax replay recipe. "
            "Source replay auto-inherits a value encoded in source fold model IDs unless this is set explicitly."
        ),
    )
    parser.add_argument(
        "--high-return-soft-sizer-relax-size-mult",
        type=float,
        default=0.25,
        help="Size multiplier used by the model-encoded high_return_soft_sizer_relax replay recipe.",
    )
    parser.add_argument(
        "--high-return-soft-sizer-relax-cooldown-bars",
        type=int,
        default=2880,
        help="Cooldown bars used by the model-encoded high_return_soft_sizer_relax replay recipe.",
    )
    parser.add_argument(
        "--high-return-soft-sizer-tight-replay-note",
        default=None,
        help=(
            "Enable an optional tighter high-return soft-sizer replay recipe. This is intended "
            "for risk-tight profiles and remains disabled by default."
        ),
    )
    parser.add_argument(
        "--high-return-soft-sizer-tight-drawdown-pct",
        type=float,
        default=9.0,
        help="Drawdown trigger used by the optional tight high-return soft-sizer replay recipe.",
    )
    parser.add_argument(
        "--high-return-soft-sizer-tight-size-mult",
        type=float,
        default=0.10,
        help="Size multiplier used by the optional tight high-return soft-sizer replay recipe.",
    )
    parser.add_argument(
        "--high-return-soft-sizer-tight-cooldown-bars",
        type=int,
        default=2880,
        help="Cooldown bars used by the optional tight high-return soft-sizer replay recipe.",
    )
    parser.add_argument(
        "--low-activity-reengage-probe-replay-note",
        default=None,
        help="Enable the low-activity reengage probe replay recipe with this note.",
    )
    parser.add_argument(
        "--role-balance-impulse-micro-replay-note",
        default=None,
        help="Enable the role-balance micro impulse replay recipe with this note.",
    )
    parser.add_argument(
        "--role-border-impulse-micro-replay-note",
        default=None,
        help="Enable the role-border micro impulse replay recipe with this note.",
    )
    parser.add_argument(
        "--base-heavy-probe-rebalance-replay-note",
        default=None,
        help="Enable the base-heavy probe rebalance replay recipe with this note.",
    )
    parser.add_argument(
        "--event-risk-base-throttle-replay-note",
        default=None,
        help="Enable the experimental event-risk base-entry throttle replay recipe with this note.",
    )
    parser.add_argument(
        "--event-risk-base-tight-repair-replay-note",
        default=None,
        help=(
            "Enable a narrow repair-tight event-risk base throttle replay recipe with this note. "
            "This stacks only after the event-risk throttle and tight repair recipes have applied."
        ),
    )
    parser.add_argument(
        "--low-return-stress-base-throttle-replay-note",
        default=None,
        help=(
            "Enable the broad low-return stress-floor base throttle recipe with this note. "
            "This widens short event-risk base reduction only for the validated low-return, "
            "high-cost single-unit state."
        ),
    )
    parser.add_argument(
        "--event-risk-distribution-base-off-replay-note",
        default=None,
        help=(
            "Enable the distribution-balanced event-risk base-off replay recipe with this note. "
            "This stacks only after event-risk throttle and distribution balance have applied."
        ),
    )
    parser.add_argument(
        "--event-risk-soft-hold-inventory-release-replay-note",
        default=None,
        help=(
            "Enable a narrow event-risk soft-hold replay recipe that releases soft-circuit "
            "inventory trimming after the near-miss reengagement state."
        ),
    )
    parser.add_argument(
        "--event-risk-soft-hold-inventory-release-fraction",
        type=float,
        default=0.0,
        help="equity_soft_circuit_inventory_trim_fraction used by the event-risk release recipe.",
    )
    parser.add_argument(
        "--fold13-stress-exit-sizer-replay-note",
        default=None,
        help=(
            "Enable an experimental fold13 stress repair that reduces reaction and hard-time "
            "partial exit size only after the distribution-balanced event-risk base-off state."
        ),
    )
    parser.add_argument(
        "--fold13-stress-exit-sizer-reaction-trim-size-mult",
        type=float,
        default=0.50,
        help="reaction_trim_size_mult used by the experimental fold13 stress exit-sizer recipe.",
    )
    parser.add_argument(
        "--fold13-stress-exit-sizer-hard-time-fraction",
        type=float,
        default=0.25,
        help="hard_time_exit_fraction used by the experimental fold13 stress exit-sizer recipe.",
    )
    parser.add_argument(
        "--fold13-selective-impulse-replay-note",
        default=None,
        help=(
            "Enable a narrow fold13 stress repair that adds one large one-way impulse probe only "
            "after the distribution-balanced event-risk base-off state."
        ),
    )
    parser.add_argument(
        "--fold13-selective-impulse-probe-units",
        type=float,
        default=1.0,
        help="one_way_impulse_probe_units used by the fold13 selective impulse recipe.",
    )
    parser.add_argument(
        "--fold13-selective-impulse-min-one-way-score",
        type=float,
        default=3.5,
        help="one_way_impulse_min_one_way_score used by the fold13 selective impulse recipe.",
    )
    parser.add_argument(
        "--fold13-selective-impulse-min-score-diff",
        type=int,
        default=5,
        help="one_way_impulse_min_score_diff used by the fold13 selective impulse recipe.",
    )
    parser.add_argument(
        "--fold13-selective-impulse-reaction-trim-trigger",
        type=float,
        default=0.60,
        help=(
            "reaction_trim_trigger used by the fold13 selective impulse recipe to preserve "
            "a small cost-x3 plus funding stress buffer."
        ),
    )
    parser.add_argument(
        "--fold13-near-miss-noise-filter-replay-note",
        default=None,
        help=(
            "Enable a narrow fold13 replay recipe that reduces near-miss probes to dust size only "
            "after the full-size selective impulse state has been applied."
        ),
    )
    parser.add_argument(
        "--fold13-hard-loss-defer-replay-note",
        default=None,
        help=(
            "Enable a narrow fold13 replay recipe that defers only losing low-extension "
            "hard-time exits after the selective impulse and dust near-miss state."
        ),
    )
    parser.add_argument(
        "--fold13-hold-extension-replay-note",
        default=None,
        help=(
            "Enable a narrow fold13 replay recipe that extends the post-repair max hold "
            "when direct replay shows it improves gross buffer and cost stress without "
            "raising drawdown."
        ),
    )
    parser.add_argument(
        "--fold13-hold-extension-bars",
        type=int,
        default=144,
        help="max_hold_bars used by the fold13 hold-extension recipe.",
    )
    parser.add_argument(
        "--fold13-one-way-delay-replay-note",
        default=None,
        help=(
            "Enable a narrow fold13 replay recipe that delays one-way forced trims only "
            "after the hold-extension state when direct replay shows lower cost without "
            "raising drawdown."
        ),
    )
    parser.add_argument(
        "--fold13-one-way-delay-min-adverse-reaction",
        type=float,
        default=0.30,
        help="one_way_trim_min_adverse_reaction used by the fold13 one-way delay recipe.",
    )
    parser.add_argument(
        "--fold13-reaction-band-widen-replay-note",
        default=None,
        help=(
            "Enable a narrow fold13 replay recipe that widens the reaction average band only "
            "after the one-way delay state when direct replay shows more winner room clears "
            "cost-x3 plus funding without adding orders."
        ),
    )
    parser.add_argument(
        "--fold13-reaction-band-widen-avg-band",
        type=float,
        default=2.0,
        help="reaction_avg_band used by the fold13 reaction-band widen recipe.",
    )
    parser.add_argument(
        "--fold11-reaction-delay-replay-note",
        default=None,
        help=(
            "Enable a narrow fold11 replay recipe that delays reaction trimming only after "
            "the event-risk soft-hold release state when direct replay shows a higher "
            "cost-x3 buffer without increasing drawdown or order count."
        ),
    )
    parser.add_argument(
        "--fold11-reaction-delay-trigger",
        type=float,
        default=1.25,
        help="reaction_trim_trigger used by the fold11 reaction-delay recipe.",
    )
    parser.add_argument(
        "--fold8-chase-suppress-replay-note",
        default=None,
        help=(
            "Enable a narrow fold8 replay recipe that suppresses chase entries only after "
            "the negative-train distribution probe state when the chase leg is the isolated "
            "OOS cost and loss leak."
        ),
    )
    parser.add_argument(
        "--fold8-chase-suppress-units",
        type=float,
        default=0.0,
        help="chase_units used by the fold8 chase-suppression recipe.",
    )
    parser.add_argument(
        "--deep-drawdown-reversal-scale-replay-note",
        default=None,
        help=(
            "Enable the deep-drawdown reversal scale replay recipe with this note. "
            "This raises reversal switch size only for the validated high-drawdown fold state."
        ),
    )
    parser.add_argument(
        "--high-cost-runner-reversal-scale-replay-note",
        default=None,
        help=(
            "Enable the high-cost runner reversal scale replay recipe with this note. "
            "This raises reversal switch size only after the validated high-cost runner repair."
        ),
    )
    parser.add_argument(
        "--high-cost-runner-tight-repair-replay-note",
        default=None,
        help=(
            "Enable the high-cost runner tight-repair replay recipe with this note. "
            "This tightens repair cut only after the validated high-cost runner reversal scale."
        ),
    )
    parser.add_argument(
        "--high-cost-near-zero-react-replay-note",
        default=None,
        help=(
            "Enable the high-cost runner recipe that disables the tiny near-miss probe and "
            "uses a slightly faster reaction trim. This is intended for return-seeking profiles."
        ),
    )
    parser.add_argument(
        "--soft-circuit-recovery-mid-probe-units",
        type=float,
        default=0.60,
        help="Probe units used by the model-encoded soft_circuit_recovery_mid replay recipe.",
    )
    parser.add_argument(
        "--soft-circuit-recovery-mid-min-one-way-score",
        type=float,
        default=3.5,
        help="Minimum one-way score used by the model-encoded soft_circuit_recovery_mid replay recipe.",
    )
    parser.add_argument(
        "--soft-circuit-recovery-mid-min-score-diff",
        type=int,
        default=5,
        help="Minimum score difference used by the model-encoded soft_circuit_recovery_mid replay recipe.",
    )
    parser.add_argument(
        "--soft-circuit-recovery-mid-max-extension-atr",
        type=float,
        default=3.5,
        help="Maximum extension ATR used by the model-encoded soft_circuit_recovery_mid replay recipe.",
    )
    parser.add_argument(
        "--soft-circuit-recovery-mid-failure-guard-count",
        type=int,
        default=0,
        help="Failure count that triggers the soft_circuit_recovery_mid probe cooldown.",
    )
    parser.add_argument(
        "--soft-circuit-recovery-mid-failure-guard-window-bars",
        type=int,
        default=1440,
        help="Lookback bars for the soft_circuit_recovery_mid failed-probe guard.",
    )
    parser.add_argument(
        "--soft-circuit-recovery-mid-failure-cooldown-bars",
        type=int,
        default=0,
        help="Cooldown bars applied after the soft_circuit_recovery_mid failed-probe guard triggers.",
    )
    parser.add_argument(
        "--soft-circuit-recovery-low-activity-probe-units",
        type=float,
        default=0.25,
        help="Probe units used by the low-activity soft-circuit recovery replay recipe.",
    )
    parser.add_argument(
        "--soft-circuit-recovery-low-activity-min-one-way-score",
        type=float,
        default=3.0,
        help="Minimum one-way score for the low-activity soft-circuit recovery replay recipe.",
    )
    parser.add_argument(
        "--soft-circuit-recovery-low-activity-min-score-diff",
        type=int,
        default=4,
        help="Minimum score difference for the low-activity soft-circuit recovery replay recipe.",
    )
    parser.add_argument(
        "--soft-circuit-recovery-low-activity-max-extension-atr",
        type=float,
        default=3.5,
        help="Maximum extension ATR for the low-activity soft-circuit recovery replay recipe.",
    )
    parser.add_argument(
        "--soft-circuit-recovery-low-activity-failure-guard-count",
        type=int,
        default=1,
        help="Failure count that triggers the low-activity soft-circuit recovery cooldown.",
    )
    parser.add_argument(
        "--soft-circuit-recovery-low-activity-failure-guard-window-bars",
        type=int,
        default=1440,
        help="Lookback bars for low-activity soft-circuit recovery failures.",
    )
    parser.add_argument(
        "--soft-circuit-recovery-low-activity-failure-cooldown-bars",
        type=int,
        default=4320,
        help="Cooldown bars applied after the low-activity soft-circuit recovery failure guard triggers.",
    )
    parser.add_argument(
        "--soft-circuit-low-activity-cooldown-replay-note",
        default=None,
        help=(
            "Enable the low-activity soft-circuit cooldown compression replay recipe with this note. "
            "This stacks only after the low-activity soft-circuit recovery recipe has applied."
        ),
    )
    parser.add_argument(
        "--soft-circuit-low-activity-entry-grace-replay-note",
        default=None,
        help=(
            "Enable the low-activity soft-circuit post-add grace replay recipe with this note. "
            "This stacks only after the low-activity soft-circuit recovery/cooldown repair."
        ),
    )
    parser.add_argument(
        "--soft-circuit-low-activity-near-miss-replay-note",
        default=None,
        help=(
            "Enable the low-activity soft-circuit near-miss reengagement replay recipe with this note. "
            "This stacks only after the low-activity soft-circuit recovery/cooldown repair."
        ),
    )
    parser.add_argument(
        "--soft-circuit-low-activity-cooldown-bars",
        type=int,
        default=4320,
        help="Soft-circuit cooldown bars used by the low-activity cooldown compression replay recipe.",
    )
    parser.add_argument(
        "--soft-circuit-low-activity-entry-grace-bars",
        type=int,
        default=6,
        help="Post-add soft-circuit trigger grace bars for the low-activity replay recipe.",
    )
    parser.add_argument(
        "--low-return-soft-inventory-trim-fraction",
        type=float,
        default=0.20,
        help="Inventory trim fraction used by the low-return soft-circuit replay recipe.",
    )
    parser.add_argument(
        "--low-return-soft-inventory-trim-replay-note",
        default=None,
        help="Enable the low-return soft-circuit inventory trim replay recipe with this note.",
    )
    parser.add_argument(
        "--low-return-current-chain-replay-note",
        default=None,
        help=(
            "Enable the experimental current-state low-return replay chain with this note. "
            "This stays off by default because direct OOS replay must validate each chain revision."
        ),
    )
    parser.add_argument(
        "--low-return-selective-impulse-replay-note",
        default=None,
        help=(
            "Enable a targeted low-return impulse-probe recipe that upgrades the dust-sized "
            "role-balance probe only when the one-way score is stricter."
        ),
    )
    parser.add_argument(
        "--low-return-selective-impulse-probe-units",
        type=float,
        default=0.20,
        help="Probe units used by the targeted low-return selective impulse recipe.",
    )
    parser.add_argument(
        "--low-return-selective-impulse-min-one-way-score",
        type=float,
        default=4.0,
        help="Minimum one-way score used by the targeted low-return selective impulse recipe.",
    )
    parser.add_argument(
        "--low-return-selective-impulse-min-score-diff",
        type=int,
        default=5,
        help="Minimum score difference used by the targeted low-return selective impulse recipe.",
    )
    parser.add_argument(
        "--low-return-impulse-noise-filter-replay-note",
        default=None,
        help=(
            "Enable a targeted low-return noise filter that disables small-but-executable "
            "one-way impulse probes only in the high-drawdown forced-trim state."
        ),
    )
    parser.add_argument(
        "--low-return-normal-short-base-throttle-replay-note",
        default=None,
        help=(
            "Enable a targeted low-return base throttle that reduces normal short base entries "
            "only in the executable impulse-noise state after the impulse filter has applied."
        ),
    )
    parser.add_argument(
        "--low-return-short-base-refine-replay-note",
        default=None,
        help=(
            "Enable a targeted low-return short-base refinement after the normal-short throttle "
            "when direct replay shows a narrower early-extension pocket plus longer hold improves "
            "stress return without increasing drawdown."
        ),
    )
    parser.add_argument(
        "--low-return-short-base-refine-max-extension-atr",
        type=float,
        default=1.0,
        help="event_risk_base_reduce_max_extension_atr used by the short-base refinement recipe.",
    )
    parser.add_argument(
        "--low-return-short-base-refine-hold-bars",
        type=int,
        default=96,
        help="max_hold_bars used by the short-base refinement recipe.",
    )
    parser.add_argument(
        "--low-return-one-way-delay-replay-note",
        default=None,
        help=(
            "Enable a targeted low-return one-way trim delay only after the normal short base "
            "throttle has already reduced noisy extension-pocket entries."
        ),
    )
    parser.add_argument(
        "--low-return-one-way-delay-min-adverse-reaction",
        type=float,
        default=0.10,
        help="one_way_trim_min_adverse_reaction used by the low-return one-way delay recipe.",
    )
    parser.add_argument(
        "--mid-impulse-reaction-band-replay-note",
        default=None,
        help=(
            "Enable a targeted mid-impulse reaction-band recipe that gives profitable "
            "reaction trims more average-price room in the single-unit mid-return state."
        ),
    )
    parser.add_argument(
        "--mid-impulse-reaction-avg-band",
        type=float,
        default=1.15,
        help="reaction_avg_band used by the targeted mid-impulse reaction-band recipe.",
    )
    parser.add_argument(
        "--mid-impulse-noise-filter-replay-note",
        default=None,
        help=(
            "Enable a targeted mid-impulse noise filter that disables the micro one-way "
            "impulse probe after the reaction-band repair when direct replay shows the probe "
            "adds order count without improving gross buffer."
        ),
    )
    parser.add_argument(
        "--mid-impulse-noise-filter-probe-units",
        type=float,
        default=0.0,
        help="one_way_impulse_probe_units used by the targeted mid-impulse noise filter.",
    )
    parser.add_argument(
        "--mid-impulse-long-base-throttle-replay-note",
        default=None,
        help=(
            "Enable a targeted mid-impulse long-base throttle after the noise filter when "
            "direct replay shows early-extension long base entries add cost and drawdown "
            "without improving gross buffer."
        ),
    )
    parser.add_argument(
        "--mid-impulse-long-base-throttle-max-extension-atr",
        type=float,
        default=0.75,
        help="event_risk_base_reduce_max_extension_atr used by the mid-impulse long-base throttle.",
    )
    parser.add_argument(
        "--low-return-reaction-band-replay-note",
        default=None,
        help=(
            "Enable a targeted low-return reaction-band recipe that gives profitable "
            "reaction trims a wider average-price band after the selective impulse repair."
        ),
    )
    parser.add_argument(
        "--low-return-reaction-avg-band",
        type=float,
        default=1.15,
        help="reaction_avg_band used by the targeted low-return reaction-band recipe.",
    )
    parser.add_argument(
        "--fast-defense-one-way-delay-replay-note",
        default=None,
        help=(
            "Enable a replay recipe that delays one-way forced trims only after a fast defensive "
            "state already shortened defensive trim cooldowns."
        ),
    )
    parser.add_argument(
        "--fast-defense-one-way-delay-min-adverse-reaction",
        type=float,
        default=0.50,
        help="one_way_trim_min_adverse_reaction used by the fast-defense one-way delay recipe.",
    )
    parser.add_argument(
        "--fast-defense-one-way-delay-max-defensive-cooldown-bars",
        type=int,
        default=100,
        help="Maximum source defensive trim cooldown for the fast-defense one-way delay recipe.",
    )
    parser.add_argument(
        "--low-return-single-unit-compression-replay-note",
        default=None,
        help=(
            "Enable a narrow low-return compression recipe that lowers inventory unit capacity "
            "after the stress base throttle only when the selected fold is already single-unit "
            "and OOS stress replay shows the 10x exposure cap remains intact."
        ),
    )
    parser.add_argument(
        "--low-return-single-unit-compression-units",
        type=float,
        default=0.50,
        help="max/base/battle units used by the low-return single-unit compression recipe.",
    )
    parser.add_argument(
        "--low-return-stress-reaction-band-restore-replay-note",
        default=None,
        help=(
            "Enable a targeted low-return stress recipe that restores a wider reaction average "
            "band only after the stress base throttle and single-unit compression have applied."
        ),
    )
    parser.add_argument(
        "--low-return-stress-reaction-band-restore-avg-band",
        type=float,
        default=1.15,
        help="reaction_avg_band used by the low-return stress reaction-band restore recipe.",
    )
    parser.add_argument(
        "--low-return-repair-stop-replay-note",
        default=None,
        help=(
            "Enable a targeted low-return repair-stop recipe after the stress reaction-band "
            "restore when direct replay shows a tighter repair stop improves both stress "
            "return and drawdown."
        ),
    )
    parser.add_argument(
        "--low-return-repair-stop-value",
        type=float,
        default=0.90,
        help="repair_stop used by the low-return repair-stop recipe.",
    )
    parser.add_argument(
        "--low-return-repair-stop-reaction-trim-trigger",
        type=float,
        default=0.60,
        help="reaction_trim_trigger used by the low-return repair-stop recipe.",
    )
    parser.add_argument(
        "--low-return-repair-stop-tighten-replay-note",
        default=None,
        help=(
            "Enable a final low-return repair-stop tighten recipe after the initial repair stop "
            "when direct replay shows a tighter stop improves stress return and drawdown."
        ),
    )
    parser.add_argument(
        "--low-return-repair-stop-tighten-value",
        type=float,
        default=0.70,
        help="repair_stop used by the final low-return repair-stop tighten recipe.",
    )
    parser.add_argument(
        "--low-return-strong-impulse-replay-note",
        default=None,
        help=(
            "Enable a targeted low-return strong impulse recipe after the repair-stop tighten "
            "when direct replay shows the fold needs one strict one-way probe with a slower "
            "probe take-profit reaction."
        ),
    )
    parser.add_argument(
        "--low-return-strong-impulse-probe-units",
        type=float,
        default=0.50,
        help="one_way_impulse_probe_units used by the low-return strong impulse recipe.",
    )
    parser.add_argument(
        "--low-return-strong-impulse-min-one-way-score",
        type=float,
        default=4.0,
        help="one_way_impulse_min_one_way_score used by the low-return strong impulse recipe.",
    )
    parser.add_argument(
        "--low-return-strong-impulse-min-score-diff",
        type=int,
        default=3,
        help="one_way_impulse_min_score_diff used by the low-return strong impulse recipe.",
    )
    parser.add_argument(
        "--low-return-strong-impulse-cooldown-bars",
        type=int,
        default=48,
        help="one_way_impulse_cooldown_bars used by the low-return strong impulse recipe.",
    )
    parser.add_argument(
        "--low-return-strong-impulse-max-extension-atr",
        type=float,
        default=2.75,
        help="one_way_impulse_max_extension_atr used by the low-return strong impulse recipe.",
    )
    parser.add_argument(
        "--low-return-strong-impulse-probe-take-profit-reaction",
        type=float,
        default=0.75,
        help="probe_take_profit_reaction used by the low-return strong impulse recipe.",
    )
    parser.add_argument("--write-report", action="store_true")
    parser.set_defaults(
        midfold_reaction_hold_recipes=None,
        selective_reaction_repair_clean_recipes=None,
        trim_cooldown_recipes=None,
        risk_off_micro_sizer_recipe=None,
        balanced_structure_replay_note=None,
        high_cost_repair_cut_05_replay_note=None,
        high_cost_near_zero_react_replay_note=None,
        role_balance_impulse_micro_replay_note=None,
        role_border_impulse_micro_replay_note=None,
        low_activity_reengage_probe_replay_note=None,
        base_heavy_probe_rebalance_replay_note=None,
        event_risk_base_throttle_replay_note=None,
        event_risk_base_tight_repair_replay_note=(
            "Tighten only the repair-tuned event-risk base throttle state whose OOS hour-open "
            "short reduction improved return and cost without raising drawdown."
        ),
        low_return_stress_base_throttle_replay_note=(
            "Broaden short event-risk base reduction only for the low-return stress-floor state "
            "where the raw return stayed positive but modeled costs made the fold fragile."
        ),
        low_return_single_unit_compression_replay_note=(
            "Compress the low-return single-unit state only after the stress base throttle, where "
            "fold replay showed the 10x exposure cap stayed intact while the smaller capacity "
            "increased gross buffer enough to improve cost-x3 plus funding survival."
        ),
        low_return_stress_reaction_band_restore_replay_note=(
            "Restore the wider reaction average band only after low-return stress base throttle "
            "and single-unit compression, where OOS replay showed extra winner room improved "
            "gross buffer without raising drawdown or order-count risk."
        ),
        low_return_repair_stop_replay_note=(
            "Tighten the repair stop only after the low-return stress reaction-band restore, "
            "where direct OOS replay improved stress return and reduced drawdown without "
            "adding orders or exposure."
        ),
        event_risk_reaction_soft_hold_replay_note=(
            "Delay reaction trimming only after the tight event-risk repair state, while using "
            "a soft-circuit inventory trim to keep the extra hold risk below the current OOS max drawdown."
        ),
        event_risk_soft_hold_near_miss_replay_note=(
            "Re-enable a small near-miss probe only after the event-risk soft-hold state whose "
            "OOS probe reengagement improved return and cost without raising drawdown."
        ),
        negative_train_distribution_probe_replay_note=(
            "Use a dust-sized near-miss probe only for the negative-train, high-drawdown state "
            "where it repaired OOS side/role concentration without changing drawdown."
        ),
        compressed_trend_distribution_probe_replay_note=(
            "Use a dust-sized near-miss probe only after compressed-trend reaction tuning where "
            "the larger role-balance probe is blocked but OOS role concentration can be repaired."
        ),
        event_risk_distribution_base_off_replay_note=(
            "Turn off event-risk base entries only after the distribution-balanced event-risk state "
            "where a partial short throttle still leaked cost without reducing OOS drawdown."
        ),
        event_risk_soft_hold_inventory_release_replay_note=(
            "Release the soft-circuit inventory trim only after the event-risk soft-hold near-miss "
            "state where stress-cost replay showed the circuit was cutting trend inventory too early."
        ),
        fold13_selective_impulse_replay_note=(
            "Add a single full-size one-way impulse probe only for the distribution-balanced "
            "fold13 stress-floor state, then hold reaction trims slightly longer where that "
            "preserved enough gross buffer to clear cost-x3 plus funding without increasing "
            "drawdown."
        ),
        fold13_near_miss_noise_filter_replay_note=(
            "Reduce near-miss probes to dust size after the fold13 full-size impulse state, where "
            "direct OOS replay showed the role distribution was useful but the executable size "
            "added cost without improving gross buffer, drawdown, or stress survival."
        ),
        fold13_hard_loss_defer_replay_note=(
            "Defer only losing low-extension hard-time exits after the fold13 full-size impulse "
            "and dust near-miss state, where direct OOS replay showed the delay improved gross "
            "buffer without changing order distribution or drawdown."
        ),
        fold13_hold_extension_replay_note=(
            "Extend max hold only after the fold13 hard-loss defer state, where direct OOS replay "
            "improved both base return and cost-x3 stress return while leaving drawdown unchanged."
        ),
        fold13_one_way_delay_replay_note=(
            "Delay one-way forced trims only after the fold13 hold-extension state, where direct "
            "OOS replay reduced forced-trim cost and improved both base and stressed return "
            "without changing drawdown or order count."
        ),
        fold13_reaction_band_widen_replay_note=(
            "Widen the reaction average band only after the fold13 one-way delay state, where "
            "direct OOS replay let winners breathe enough to clear cost-x3 plus funding while "
            "leaving order count unchanged and reducing drawdown."
        ),
        fold11_reaction_delay_replay_note=(
            "Delay reaction trimming only after the fold11 event-risk soft-hold release state, "
            "where direct OOS replay raised both base and cost-x3 return while leaving drawdown "
            "and order count unchanged."
        ),
        fold8_chase_suppress_replay_note=(
            "Suppress the chase leg only after the fold8 negative-train distribution probe state, "
            "where direct OOS replay showed the lone chase entry was a cost and loss leak while "
            "base and probe structure stayed profitable."
        ),
        low_return_impulse_noise_filter_replay_note=(
            "Disable only the 0.02-unit one-way impulse probe in the high-drawdown, high "
            "forced-trim state where OOS replay showed it was executable noise; micro probes "
            "and full-size impulse probes remain untouched."
        ),
        low_return_normal_short_base_throttle_replay_note=(
            "Reduce only normal short base entries in the 0.75-1.5 ATR extension pocket after "
            "the low-return impulse-noise filter, where OOS replay showed forced-trim cost "
            "leakage without reducing the winning hour-open and deeper-extension base trades."
        ),
        low_return_short_base_refine_replay_note=(
            "Retune the low-return normal-short base throttle to the 0-1 ATR pocket and allow "
            "a longer hold only after the first throttle state, where direct OOS replay lifted "
            "stress return above the deployment floor while lowering drawdown."
        ),
        low_return_one_way_delay_replay_note=None,
        low_return_repair_stop_tighten_replay_note=(
            "Tighten the low-return repair stop only after the first repair-stop state, where "
            "direct OOS replay gave a small but clean improvement to base return, stress return, "
            "and drawdown without changing order count."
        ),
        low_return_strong_impulse_replay_note=(
            "Add one strict full-capacity low-return impulse probe only after the repair-stop "
            "tighten state, and delay its probe take-profit reaction where direct OOS replay "
            "raised the fold12 stress floor without changing drawdown or broadening entries."
        ),
        mid_impulse_reaction_band_replay_note=(
            "Widen the reaction average band only for the mid-impulse, single-unit state where "
            "direct OOS replay showed more winner room improved stress return while preserving "
            "the same event count and drawdown."
        ),
        mid_impulse_noise_filter_replay_note=(
            "Disable the micro one-way impulse probe only after the mid-impulse reaction-band "
            "repair, where direct OOS replay showed the probe contributed order noise while "
            "adding no meaningful gross return or drawdown protection."
        ),
        mid_impulse_long_base_throttle_replay_note=(
            "Reduce only early-extension long base entries after the mid-impulse noise filter, "
            "where direct OOS replay showed the entries increased cost and drawdown without "
            "adding gross buffer under stressed fees."
        ),
        low_return_current_chain_replay_note=None,
        deep_drawdown_reversal_scale_replay_note=(
            "Scale one-way reversal only for the deep-drawdown train state whose OOS reversal "
            "follow-through improved return before forced-trim overuse appeared."
        ),
        high_cost_runner_reversal_scale_replay_note=(
            "Scale one-way reversal only after the high-cost runner repair whose OOS reversal "
            "follow-through improved return without raising the fold drawdown."
        ),
        high_cost_runner_tight_repair_replay_note=(
            "Tighten repair cut only after the high-cost runner reversal-scale state where the "
            "extra repair discipline improved OOS return without raising drawdown."
        ),
        low_return_soft_inventory_trim_replay_note=(
            "Use a partial soft-circuit inventory trim only for the high-return train state whose "
            "OOS base inventory kept return positive but leaked cost and late drawdown."
        ),
        deep_soft_reaction_delay_replay_note=(
            "Delay reaction trimming only for the deep-drawdown, high forced-trim train state "
            "where early reaction exits worsened the OOS equity trough."
        ),
        forced_trim_near_miss_tiny_replay_note=(
            "Use a smaller near-miss probe only for the high forced-trim, low-return train state "
            "where the default probe size did not improve OOS drawdown."
        ),
        high_return_soft_sizer_relax_replay_note=(
            "Relax the soft equity sizer only slightly for a high-return, downtrend-dependent train state "
            "where too much relaxation raised OOS drawdown more than the extra trend profit justified."
        ),
        soft_circuit_recovery_mid_replay_note=(
            "Enable a narrow soft-circuit recovery probe only for the mid-return, "
            "risk-off train state where force-flat protection was too inactive."
        ),
        soft_circuit_recovery_low_activity_replay_note=(
            "Re-engage a tiny soft-circuit recovery probe only for the low-activity, "
            "force-flat train state where OOS protection became almost fully inactive."
        ),
        soft_circuit_low_activity_cooldown_replay_note=None,
        soft_circuit_low_activity_entry_grace_replay_note=(
            "Give the low-activity soft-circuit state a short post-add grace so stressed entry "
            "costs cannot immediately force-flat a fresh base position before the planned "
            "reaction window can resolve."
        ),
        soft_circuit_low_activity_near_miss_replay_note=(
            "Use a larger near-miss reengagement probe only for the low-activity soft-circuit state "
            "where OOS drawdown stayed flat and two extra entries improved return."
        ),
    )
    default_args = parser.parse_args([])
    parsed = parser.parse_args(argv)
    parsed._parser_defaults = vars(default_args)
    parsed._provided_cli_dests = _cli_provided_dests(parser, list(sys.argv[1:] if argv is None else argv))
    return parsed


def _is_observe_only_router_config(config: MarketStateConfig) -> bool:
    if not bool(getattr(config, "regime_router_enabled", False)):
        return False
    size_fields = (
        "router_trend_reaction_size_mult",
        "router_one_way_chase_size_mult",
        "router_one_way_counter_size_mult",
        "router_range_probe_size_mult",
        "router_range_base_size_mult",
        "router_exhaustion_reversal_size_mult",
        "router_risk_off_size_mult",
    )
    if any(abs(float(getattr(config, field, 1.0) or 0.0) - 1.0) > 1e-12 for field in size_fields):
        return False
    return (
        float(getattr(config, "router_transition_trim_fraction", 0.0) or 0.0) <= 1e-12
        or not tuple(getattr(config, "router_transition_trim_modes", ()) or ())
    )


def _router_fields_are_source_replay_ignorable(config: MarketStateConfig) -> bool:
    return (not bool(getattr(config, "regime_router_enabled", False))) or _is_observe_only_router_config(config)


def _material_config_key(
    config: MarketStateConfig,
    *,
    ignore_observe_only_router: bool = False,
) -> str:
    ignored = {"model_id", "max_battle_bars"}
    if ignore_observe_only_router and _router_fields_are_source_replay_ignorable(config):
        ignored |= {
            "regime_router_enabled",
            "router_trend_reaction_size_mult",
            "router_one_way_chase_size_mult",
            "router_one_way_counter_size_mult",
            "router_range_probe_size_mult",
            "router_range_base_size_mult",
            "router_exhaustion_reversal_size_mult",
            "router_exhaustion_min_score_edge",
            "router_exhaustion_min_extension_atr",
            "router_risk_off_size_mult",
            "router_transition_trim_fraction",
            "router_transition_trim_modes",
            "router_transition_trim_against_only",
            "router_transition_trim_cooldown_bars",
        }
    payload = {
        key: value
        for key, value in asdict(config).items()
        if key not in ignored
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _configs_from_source(
    report: dict[str, Any],
    *,
    top_n: int,
    include_walk_forward_test_results: bool = False,
) -> list[MarketStateConfig]:
    candidates: list[dict[str, Any]] = []

    def append_result(result: Any) -> None:
        if isinstance(result, dict) and isinstance(result.get("config"), dict):
            candidates.append(result)

    for key in ("best_by_method_score", "best_by_raw_return"):
        append_result(report.get(key))
    for section in ("top_results", "top_results_by_return", "all_results"):
        for result in report.get(section) or []:
            append_result(result)

    # Walk-forward reports are often used as iterative replay sources. Their
    # candidate lineage lives inside fold records rather than top-level scan
    # result sections. Harvest every fold's selected train config before lower
    # ranked train fallbacks, so source-top N represents the chronological
    # selected lineage instead of one fold's local candidate neighborhood.
    # Test-side fold results are excluded by default because they may already
    # include after-selection overlays or OOS evaluation-only variants; feeding
    # them back as base candidates can stack those overlays during the next run.
    walk_forward_folds = [fold for fold in report.get("folds") or [] if isinstance(fold, dict)]
    for fold in walk_forward_folds:
        append_result(fold.get("selected_train_result"))
    for fold in walk_forward_folds:
        for result in fold.get("train_top_results") or []:
            append_result(result)
    if include_walk_forward_test_results:
        for fold in walk_forward_folds:
            append_result(fold.get("test_result"))
            for result in fold.get("train_top_test_results") or []:
                append_result(result)
                append_result(dict(result).get("test_result") if isinstance(result, dict) else None)

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


def _configs_from_source_fold(
    report: dict[str, Any],
    *,
    fold: int,
    top_n: int,
    include_walk_forward_test_results: bool = False,
) -> list[MarketStateConfig]:
    for fold_record in report.get("folds") or []:
        if not isinstance(fold_record, dict):
            continue
        if int(fold_record.get("fold") or 0) != int(fold):
            continue
        test_result = fold_record.get("test_result") if include_walk_forward_test_results else None
        train_top_test_results = (
            fold_record.get("train_top_test_results") or []
            if include_walk_forward_test_results
            else []
        )
        fold_report = {
            "folds": [
                {
                    "selected_train_result": fold_record.get("selected_train_result"),
                    "train_top_results": fold_record.get("train_top_results") or [],
                    "test_result": test_result,
                    "train_top_test_results": train_top_test_results,
                }
            ]
        }
        return _configs_from_source(
            fold_report,
            top_n=top_n,
            include_walk_forward_test_results=include_walk_forward_test_results,
        )
    return []


def _source_replay_selected_train_anchor(
    source_report: dict[str, Any],
    *,
    fold: int,
    train_results: list[dict[str, Any]],
    selected_train: dict[str, Any],
    enabled: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not enabled:
        return selected_train, {"enabled": False, "applied": False, "reason": "disabled"}
    source_selected_train: dict[str, Any] | None = None
    for fold_record in source_report.get("folds") or []:
        if not isinstance(fold_record, dict):
            continue
        if int(fold_record.get("fold") or 0) != int(fold):
            continue
        value = fold_record.get("selected_train_result")
        if isinstance(value, dict):
            source_selected_train = value
        break
    if not source_selected_train or not isinstance(source_selected_train.get("config"), dict):
        return selected_train, {"enabled": True, "applied": False, "reason": "source_selected_train_missing"}
    try:
        source_key = _material_config_key(
            MarketStateConfig(**source_selected_train["config"]),
            ignore_observe_only_router=True,
        )
    except TypeError:
        return selected_train, {"enabled": True, "applied": False, "reason": "source_selected_train_invalid"}
    selected_key = ""
    try:
        selected_key = _material_config_key(
            MarketStateConfig(**selected_train["config"]),
            ignore_observe_only_router=True,
        )
    except TypeError:
        selected_key = ""
    if selected_key == source_key:
        return selected_train, {
            "enabled": True,
            "applied": False,
            "reason": "already_selected",
            "source_model_id": source_selected_train.get("model_id"),
            "selected_model_id_before_anchor": selected_train.get("model_id"),
        }
    for candidate in train_results:
        if not isinstance(candidate.get("config"), dict):
            continue
        try:
            candidate_key = _material_config_key(
                MarketStateConfig(**candidate["config"]),
                ignore_observe_only_router=True,
            )
        except TypeError:
            continue
        if candidate_key != source_key:
            continue
        return candidate, {
            "enabled": True,
            "applied": True,
            "reason": "source_selected_train_matched",
            "source_model_id": source_selected_train.get("model_id"),
            "selected_model_id_before_anchor": selected_train.get("model_id"),
            "selected_model_id_after_anchor": candidate.get("model_id"),
            "selected_score_before_anchor": selected_train.get("walk_forward_selection_score"),
            "selected_score_after_anchor": candidate.get("walk_forward_selection_score"),
        }
    return selected_train, {
        "enabled": True,
        "applied": False,
        "reason": "source_selected_train_not_in_candidates",
        "source_model_id": source_selected_train.get("model_id"),
        "selected_model_id_before_anchor": selected_train.get("model_id"),
    }


def _apply_config_overrides(
    config: MarketStateConfig,
    args: argparse.Namespace,
    *,
    include_impulse: bool = True,
    include_trend_idle: bool = True,
    include_equity_circuit: bool = True,
    include_equity_soft_circuit: bool = True,
    include_full_exit: bool = True,
    include_defensive_trim_cooldown: bool = True,
    include_near_miss: bool = True,
    include_base_reduce: bool = True,
    include_context_quarantine: bool = True,
    include_loss_fuse: bool = True,
    include_btc_rotation: bool = True,
    include_fragile_regime_entry: bool = True,
    include_fragile_regime_inventory_trim: bool = True,
) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []

    def set_if_changed(field_name: str, value: Any, suffix: str) -> None:
        current = getattr(config, field_name)
        if isinstance(current, float) or isinstance(value, float):
            if math.isclose(float(current), float(value), rel_tol=0.0, abs_tol=1e-12):
                return
        elif current == value:
            return
        updates[field_name] = value
        suffix_parts.append(suffix)

    if args.one_way_trim_min_adverse_reaction is not None:
        value = max(0.0, float(args.one_way_trim_min_adverse_reaction))
        updates["one_way_trim_min_adverse_reaction"] = value
        suffix_parts.append(f"wfOwTrimMin{value:g}")
    if args.one_way_trim_cooldown_bars is not None:
        value = max(0, int(args.one_way_trim_cooldown_bars))
        updates["one_way_trim_cooldown_bars"] = value
        suffix_parts.append(f"wfOwTrimCool{value}")
    if args.one_way_trim_size_mult is not None:
        value = min(max(float(args.one_way_trim_size_mult), 0.05), 1.0)
        set_if_changed("one_way_trim_size_mult", value, f"wfOwTrimMult{value:g}")
    if args.hard_time_exit_fraction is not None:
        value = min(max(float(args.hard_time_exit_fraction), 0.05), 1.0)
        set_if_changed("hard_time_exit_fraction", value, f"wfHardTimeFrac{value:g}")
    if args.hard_time_exit_cooldown_bars is not None:
        value = max(0, int(args.hard_time_exit_cooldown_bars))
        set_if_changed("hard_time_exit_cooldown_bars", value, f"wfHardTimeCool{value}")
    if args.reaction_trim_trend_hold_trigger_mult is not None:
        value = min(max(float(args.reaction_trim_trend_hold_trigger_mult), 1.0), 5.0)
        set_if_changed("reaction_trim_trend_hold_trigger_mult", value, f"wfReactTrendHold{value:g}")
    if args.hard_time_exit_trend_defer_bars is not None:
        value = max(0, int(args.hard_time_exit_trend_defer_bars))
        set_if_changed("hard_time_exit_trend_defer_bars", value, f"wfHardTrendDef{value}")
    if args.hard_time_exit_trend_defer_min_favorable_reaction is not None:
        value = max(0.0, float(args.hard_time_exit_trend_defer_min_favorable_reaction))
        set_if_changed(
            "hard_time_exit_trend_defer_min_favorable_reaction",
            value,
            f"wfHardTrendFav{value:g}",
        )
    if args.trend_hold_min_trend_strength is not None:
        value = max(0.0, float(args.trend_hold_min_trend_strength))
        set_if_changed("trend_hold_min_trend_strength", value, f"wfTrendHoldT{value:g}")
    if args.trend_hold_min_one_way_score is not None:
        value = max(0.0, float(args.trend_hold_min_one_way_score))
        set_if_changed("trend_hold_min_one_way_score", value, f"wfTrendHoldO{value:g}")
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
    if include_loss_fuse and args.one_way_loss_fuse_min_adverse_reaction is not None:
        value = max(0.0, float(args.one_way_loss_fuse_min_adverse_reaction))
        updates["one_way_loss_fuse_min_adverse_reaction"] = value
        suffix_parts.append(f"wfOwLossFuse{value:g}")
    if include_loss_fuse and args.one_way_loss_fuse_cooldown_bars is not None:
        value = max(0, int(args.one_way_loss_fuse_cooldown_bars))
        updates["one_way_loss_fuse_cooldown_bars"] = value
        suffix_parts.append(f"wfOwLossFuseCool{value}")
    if include_loss_fuse and args.one_way_loss_fuse_size_mult is not None:
        value = min(max(float(args.one_way_loss_fuse_size_mult), 0.0), 1.0)
        updates["one_way_loss_fuse_size_mult"] = value
        suffix_parts.append(f"wfOwLossFuseMult{value:g}")
    if include_full_exit and args.one_way_trim_full_exit_min_one_way_score is not None:
        value = max(0.0, float(args.one_way_trim_full_exit_min_one_way_score))
        updates["one_way_trim_full_exit_min_one_way_score"] = value
        suffix_parts.append(f"wfOwTrimFullExit{value:g}")
    if include_full_exit and args.one_way_trim_full_exit_min_score_diff is not None:
        value = max(0, int(args.one_way_trim_full_exit_min_score_diff))
        updates["one_way_trim_full_exit_min_score_diff"] = value
        suffix_parts.append(f"wfOwTrimFullExitDiff{value}")
    if include_defensive_trim_cooldown and args.defensive_trim_cooldown_bars is not None:
        value = max(0, int(args.defensive_trim_cooldown_bars))
        updates["defensive_trim_cooldown_bars"] = value
        suffix_parts.append(f"wfDefCool{value}")
    if args.reaction_trim_size_mult is not None:
        value = min(max(float(args.reaction_trim_size_mult), 0.05), 1.0)
        set_if_changed("reaction_trim_size_mult", value, f"wfReactTrimMult{value:g}")
    if include_trend_idle and args.trend_idle_probe_units is not None:
        value = max(0.0, float(args.trend_idle_probe_units))
        updates["trend_idle_probe_units"] = min(value, config.max_possible_units)
        suffix_parts.append(f"wfIdleProbe{value:g}")
    if include_trend_idle and args.trend_idle_min_score is not None:
        value = int(args.trend_idle_min_score)
        updates["trend_idle_min_score"] = value
        suffix_parts.append(f"wfIdleScore{value}")
    if include_trend_idle and args.trend_idle_min_reason_stack is not None:
        value = max(0, int(args.trend_idle_min_reason_stack))
        updates["trend_idle_min_reason_stack"] = value
        suffix_parts.append(f"wfIdleStack{value}")
    if include_trend_idle and args.trend_idle_cooldown_bars is not None:
        value = max(0, int(args.trend_idle_cooldown_bars))
        updates["trend_idle_cooldown_bars"] = value
        suffix_parts.append(f"wfIdleCool{value}")
    if include_trend_idle and args.trend_idle_max_extension_atr is not None:
        value = max(0.1, float(args.trend_idle_max_extension_atr))
        updates["trend_idle_max_extension_atr"] = value
        suffix_parts.append(f"wfIdleExt{value:g}")
    if include_near_miss and args.near_miss_probe_units is not None:
        value = max(0.0, float(args.near_miss_probe_units))
        updates["near_miss_probe_units"] = min(value, config.max_possible_units)
        suffix_parts.append(f"wfNearMiss{value:g}")
    if include_near_miss and args.near_miss_probe_min_score is not None:
        value = int(args.near_miss_probe_min_score)
        updates["near_miss_probe_min_score"] = value
        suffix_parts.append(f"wfNearMissScore{value}")
    if include_near_miss and args.near_miss_probe_min_score_edge is not None:
        value = max(0, int(args.near_miss_probe_min_score_edge))
        updates["near_miss_probe_min_score_edge"] = value
        suffix_parts.append(f"wfNearMissEdge{value}")
    if include_near_miss and args.near_miss_probe_min_reason_stack is not None:
        value = max(0, int(args.near_miss_probe_min_reason_stack))
        updates["near_miss_probe_min_reason_stack"] = value
        suffix_parts.append(f"wfNearMissStack{value}")
    if include_near_miss and args.near_miss_probe_cooldown_bars is not None:
        value = max(0, int(args.near_miss_probe_cooldown_bars))
        updates["near_miss_probe_cooldown_bars"] = value
        suffix_parts.append(f"wfNearMissCool{value}")
    if include_near_miss and args.near_miss_probe_max_extension_atr is not None:
        value = max(0.1, float(args.near_miss_probe_max_extension_atr))
        updates["near_miss_probe_max_extension_atr"] = value
        suffix_parts.append(f"wfNearMissExt{value:g}")
    if include_near_miss and args.near_miss_probe_failure_guard_count is not None:
        value = max(0, int(args.near_miss_probe_failure_guard_count))
        updates["near_miss_probe_failure_guard_count"] = value
        suffix_parts.append(f"wfNearMissFail{value}")
    if include_near_miss and args.near_miss_probe_failure_guard_window_bars is not None:
        value = max(1, int(args.near_miss_probe_failure_guard_window_bars))
        updates["near_miss_probe_failure_guard_window_bars"] = value
        suffix_parts.append(f"wfNearMissFailWin{value}")
    if include_near_miss and args.near_miss_probe_failure_cooldown_bars is not None:
        value = max(0, int(args.near_miss_probe_failure_cooldown_bars))
        updates["near_miss_probe_failure_cooldown_bars"] = value
        suffix_parts.append(f"wfNearMissFailCool{value}")
    if include_near_miss and args.near_miss_probe_allowed_soft_reasons is not None:
        value = _csv_tuple(args.near_miss_probe_allowed_soft_reasons)
        updates["near_miss_probe_allowed_soft_reasons"] = value
        suffix_parts.append(f"wfNearMissReasons{_tuple_suffix(value)}")
    if include_near_miss and args.near_miss_probe_allowed_alignments is not None:
        value = _csv_tuple(args.near_miss_probe_allowed_alignments)
        updates["near_miss_probe_allowed_alignments"] = value
        suffix_parts.append(f"wfNearMissAlign{_tuple_suffix(value)}")
    if include_near_miss and args.near_miss_probe_allowed_execution_contexts is not None:
        value = _csv_tuple(args.near_miss_probe_allowed_execution_contexts)
        updates["near_miss_probe_allowed_execution_contexts"] = value
        suffix_parts.append(f"wfNearMissExec{_tuple_suffix(value)}")
    if include_near_miss and args.near_miss_probe_allowed_regimes is not None:
        value = _csv_tuple(args.near_miss_probe_allowed_regimes)
        updates["near_miss_probe_allowed_regimes"] = value
        suffix_parts.append(f"wfNearMissReg{_tuple_suffix(value)}")
    if include_equity_circuit and args.equity_circuit_breaker_drawdown_pct is not None:
        value = max(0.0, float(args.equity_circuit_breaker_drawdown_pct))
        updates["equity_circuit_breaker_drawdown_pct"] = value
        suffix_parts.append(f"wfEqCb{value:g}")
    if include_equity_circuit and args.equity_circuit_breaker_pause_bars is not None:
        value = max(0, int(args.equity_circuit_breaker_pause_bars))
        updates["equity_circuit_breaker_pause_bars"] = value
        suffix_parts.append(f"wfEqCbPause{value}")
    if include_equity_circuit and args.equity_circuit_rearm_drawdown_pct is not None:
        value = max(0.0, float(args.equity_circuit_rearm_drawdown_pct))
        updates["equity_circuit_rearm_drawdown_pct"] = value
        suffix_parts.append(f"wfEqCbRearm{value:g}")
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
    if include_equity_soft_circuit and args.equity_soft_circuit_prearm_bars is not None:
        value = max(0, int(args.equity_soft_circuit_prearm_bars))
        updates["equity_soft_circuit_prearm_bars"] = value
        suffix_parts.append(f"wfEqSoftPre{value}")
    if include_equity_soft_circuit and args.equity_soft_circuit_min_bars_after_add is not None:
        value = max(0, int(args.equity_soft_circuit_min_bars_after_add))
        updates["equity_soft_circuit_min_bars_after_add"] = value
        suffix_parts.append(f"wfEqSoftGrace{value}")
    if args.one_way_reversal_switch_units is not None:
        value = max(0.0, float(args.one_way_reversal_switch_units))
        effective_value = min(value, config.max_possible_units)
        if abs(float(config.one_way_reversal_switch_units) - effective_value) > 1e-12:
            updates["one_way_reversal_switch_units"] = effective_value
            suffix_parts.append(f"wfOwRev{value:g}")
    if args.one_way_reversal_min_score_edge is not None:
        value = int(args.one_way_reversal_min_score_edge)
        if int(config.one_way_reversal_min_score_edge) != value:
            updates["one_way_reversal_min_score_edge"] = value
            suffix_parts.append(f"wfOwRevEdge{value}")
    if args.one_way_reversal_cooldown_bars is not None:
        value = max(0, int(args.one_way_reversal_cooldown_bars))
        if int(config.one_way_reversal_cooldown_bars) != value:
            updates["one_way_reversal_cooldown_bars"] = value
            suffix_parts.append(f"wfOwRevCool{value}")
    if bool(args.one_way_reversal_allow_scenario_override) and not bool(
        config.one_way_reversal_allow_scenario_override
    ):
        updates["one_way_reversal_allow_scenario_override"] = True
        suffix_parts.append("wfOwRevScn1")
    if bool(args.one_way_reversal_allow_score_override) and not bool(
        config.one_way_reversal_allow_score_override
    ):
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
    if include_btc_rotation and args.scenario_flip_units is not None:
        value = max(0.0, float(args.scenario_flip_units))
        updates["scenario_flip_units"] = min(value, config.max_possible_units)
        suffix_parts.append(f"wfScnFlip{value:g}")
    if include_btc_rotation and args.scenario_flip_min_score_edge is not None:
        value = int(args.scenario_flip_min_score_edge)
        updates["scenario_flip_min_score_edge"] = value
        suffix_parts.append(f"wfScnFlipEdge{value}")
    if include_btc_rotation and args.scenario_flip_min_adverse_reaction is not None:
        value = max(0.0, float(args.scenario_flip_min_adverse_reaction))
        updates["scenario_flip_min_adverse_reaction"] = value
        suffix_parts.append(f"wfScnFlipAdv{value:g}")
    if include_btc_rotation and args.scenario_flip_min_one_way_score is not None:
        value = max(0.0, float(args.scenario_flip_min_one_way_score))
        updates["scenario_flip_min_one_way_score"] = value
        suffix_parts.append(f"wfScnFlipOw{value:g}")
    if include_btc_rotation and args.scenario_flip_cooldown_bars is not None:
        value = max(0, int(args.scenario_flip_cooldown_bars))
        updates["scenario_flip_cooldown_bars"] = value
        suffix_parts.append(f"wfScnFlipCool{value}")
    if include_btc_rotation and args.scenario_flip_max_extension_atr is not None:
        value = max(0.1, float(args.scenario_flip_max_extension_atr))
        updates["scenario_flip_max_extension_atr"] = value
        suffix_parts.append(f"wfScnFlipExt{value:g}")
    if include_btc_rotation and args.winner_pyramid_units is not None:
        value = max(0.0, float(args.winner_pyramid_units))
        updates["winner_pyramid_units"] = min(value, config.max_possible_units)
        suffix_parts.append(f"wfWinPyr{value:g}")
    if include_btc_rotation and args.winner_pyramid_min_profit_reaction is not None:
        value = max(0.0, float(args.winner_pyramid_min_profit_reaction))
        updates["winner_pyramid_min_profit_reaction"] = value
        suffix_parts.append(f"wfWinPyrReact{value:g}")
    if include_btc_rotation and args.winner_pyramid_min_score is not None:
        value = int(args.winner_pyramid_min_score)
        updates["winner_pyramid_min_score"] = value
        suffix_parts.append(f"wfWinPyrScore{value}")
    if include_btc_rotation and args.winner_pyramid_min_reason_stack is not None:
        value = max(0, int(args.winner_pyramid_min_reason_stack))
        updates["winner_pyramid_min_reason_stack"] = value
        suffix_parts.append(f"wfWinPyrStack{value}")
    if include_btc_rotation and args.winner_pyramid_cooldown_bars is not None:
        value = max(0, int(args.winner_pyramid_cooldown_bars))
        updates["winner_pyramid_cooldown_bars"] = value
        suffix_parts.append(f"wfWinPyrCool{value}")
    if include_btc_rotation and args.winner_pyramid_max_units is not None:
        value = max(0.0, float(args.winner_pyramid_max_units))
        updates["winner_pyramid_max_units"] = value
        suffix_parts.append(f"wfWinPyrMax{value:g}")
    if include_btc_rotation and args.winner_pyramid_max_extension_atr is not None:
        value = max(0.1, float(args.winner_pyramid_max_extension_atr))
        updates["winner_pyramid_max_extension_atr"] = value
        suffix_parts.append(f"wfWinPyrExt{value:g}")
    if include_base_reduce:
        if args.base_entry_max_extension_atr is not None:
            value = max(0.0, float(args.base_entry_max_extension_atr))
            updates["base_entry_max_extension_atr"] = value
            suffix_parts.append(f"wfBaseExt{value:g}")
        if args.base_entry_max_extension_side:
            updates["base_entry_max_extension_side"] = str(args.base_entry_max_extension_side)
            suffix_parts.append(f"wfBaseExtSide{args.base_entry_max_extension_side}")
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
        if args.base_entry_reduce_min_trend_strength is not None:
            value = max(0.0, float(args.base_entry_reduce_min_trend_strength))
            updates["base_entry_reduce_min_trend_strength"] = value
            suffix_parts.append(f"wfBaseReduceMinTrend{value:g}")
        if args.base_entry_reduce_side:
            updates["base_entry_reduce_side"] = str(args.base_entry_reduce_side)
            suffix_parts.append(f"wfBaseReduceSide{args.base_entry_reduce_side}")
    if args.base_context_reduce_size_mult is not None:
        value = min(max(float(args.base_context_reduce_size_mult), 0.0), 1.0)
        updates["base_context_reduce_size_mult"] = value
        suffix_parts.append(f"wfBaseCtxReduce{value:g}")
    base_context_patterns = _parse_base_context_reduce_patterns(str(args.base_context_reduce_patterns))
    if base_context_patterns:
        updates["base_context_reduce_patterns"] = base_context_patterns
        suffix_parts.append(f"wfBaseCtxSet{len(base_context_patterns)}")
    if args.event_risk_base_reduce_size_mult is not None:
        value = min(max(float(args.event_risk_base_reduce_size_mult), 0.0), 1.0)
        updates["event_risk_base_reduce_size_mult"] = value
        suffix_parts.append(f"wfEventBaseMult{value:g}")
    if args.event_risk_base_reduce_min_extension_atr is not None:
        value = max(0.0, float(args.event_risk_base_reduce_min_extension_atr))
        updates["event_risk_base_reduce_min_extension_atr"] = value
        suffix_parts.append(f"wfEventBaseMinExt{value:g}")
    if args.event_risk_base_reduce_max_extension_atr is not None:
        value = max(0.0, float(args.event_risk_base_reduce_max_extension_atr))
        updates["event_risk_base_reduce_max_extension_atr"] = value
        suffix_parts.append(f"wfEventBaseMaxExt{value:g}")
    if args.event_risk_base_reduce_side:
        updates["event_risk_base_reduce_side"] = str(args.event_risk_base_reduce_side)
        suffix_parts.append(f"wfEventBaseSide{args.event_risk_base_reduce_side}")
    event_contexts = _parse_event_risk_contexts(str(args.event_risk_base_reduce_contexts))
    if event_contexts:
        updates["event_risk_base_reduce_contexts"] = event_contexts
        suffix_parts.append(f"wfEventBaseCtx{'-'.join(event_contexts)}")
    if bool(args.regime_router_enabled):
        updates["regime_router_enabled"] = True
        suffix_parts.append("wfRouter1")
    if args.router_trend_reaction_size_mult is not None:
        value = min(max(float(args.router_trend_reaction_size_mult), 0.0), 1.5)
        updates["router_trend_reaction_size_mult"] = value
        suffix_parts.append(f"wfRtTrend{value:g}")
    if args.router_one_way_chase_size_mult is not None:
        value = min(max(float(args.router_one_way_chase_size_mult), 0.0), 1.5)
        updates["router_one_way_chase_size_mult"] = value
        suffix_parts.append(f"wfRtOw{value:g}")
    if args.router_one_way_counter_size_mult is not None:
        value = min(max(float(args.router_one_way_counter_size_mult), 0.0), 1.0)
        updates["router_one_way_counter_size_mult"] = value
        suffix_parts.append(f"wfRtOwCtr{value:g}")
    if args.router_range_probe_size_mult is not None:
        value = min(max(float(args.router_range_probe_size_mult), 0.0), 1.0)
        updates["router_range_probe_size_mult"] = value
        suffix_parts.append(f"wfRtRangeP{value:g}")
    if args.router_range_base_size_mult is not None:
        value = min(max(float(args.router_range_base_size_mult), 0.0), 1.0)
        updates["router_range_base_size_mult"] = value
        suffix_parts.append(f"wfRtRangeB{value:g}")
    if args.router_exhaustion_reversal_size_mult is not None:
        value = min(max(float(args.router_exhaustion_reversal_size_mult), 0.0), 1.0)
        updates["router_exhaustion_reversal_size_mult"] = value
        suffix_parts.append(f"wfRtExh{value:g}")
    if args.router_exhaustion_min_score_edge is not None:
        value = max(0, int(args.router_exhaustion_min_score_edge))
        updates["router_exhaustion_min_score_edge"] = value
        suffix_parts.append(f"wfRtExhEdge{value}")
    if args.router_exhaustion_min_extension_atr is not None:
        value = max(0.0, float(args.router_exhaustion_min_extension_atr))
        updates["router_exhaustion_min_extension_atr"] = value
        suffix_parts.append(f"wfRtExhExt{value:g}")
    if args.router_risk_off_size_mult is not None:
        value = min(max(float(args.router_risk_off_size_mult), 0.0), 1.0)
        updates["router_risk_off_size_mult"] = value
        suffix_parts.append(f"wfRtRisk{value:g}")
    if args.router_transition_trim_fraction is not None:
        value = min(max(float(args.router_transition_trim_fraction), 0.0), 1.0)
        updates["router_transition_trim_fraction"] = value
        suffix_parts.append(f"wfRtTransTrim{value:g}")
    router_transition_modes = _parse_router_modes(str(args.router_transition_trim_modes))
    if router_transition_modes:
        updates["router_transition_trim_modes"] = router_transition_modes
        suffix_parts.append(f"wfRtTransModes{'-'.join(router_transition_modes)}")
    if args.router_transition_trim_cooldown_bars is not None:
        value = max(0, int(args.router_transition_trim_cooldown_bars))
        updates["router_transition_trim_cooldown_bars"] = value
        suffix_parts.append(f"wfRtTransCool{value:g}")
    if not bool(args.router_transition_trim_against_only):
        updates["router_transition_trim_against_only"] = False
        suffix_parts.append("wfRtTransAll")
    if include_fragile_regime_entry:
        regimes = _parse_fragile_regimes(args.fragile_regime_entry_regimes)
        if regimes and args.fragile_regime_entry_size_mult is not None:
            value = min(max(float(args.fragile_regime_entry_size_mult), 0.0), 1.0)
            regime_code = "-".join(
                regime.replace("range_or_transition", "range").replace("one_way_", "ow")
                for regime in regimes
            )
            updates["fragile_regime_entry_size_mult"] = value
            updates["fragile_regime_entry_regimes"] = regimes
            suffix_parts.append(f"wfFragReg{value:g}")
            suffix_parts.append(f"wfFragSet{regime_code}")
    if include_fragile_regime_inventory_trim:
        regimes = _parse_fragile_regimes(args.fragile_regime_inventory_trim_regimes)
        if regimes and args.fragile_regime_inventory_trim_fraction is not None:
            value = min(max(float(args.fragile_regime_inventory_trim_fraction), 0.0), 1.0)
            if value > 1e-12:
                regime_code = "-".join(
                    regime.replace("range_or_transition", "range").replace("one_way_", "ow")
                    for regime in regimes
                )
                updates["fragile_regime_inventory_trim_fraction"] = value
                updates["fragile_regime_inventory_trim_regimes"] = regimes
                suffix_parts.append(f"wfFragInvTrim{value:g}")
                suffix_parts.append(f"wfFragInvSet{regime_code}")
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
    if args.equity_circuit_rearm_drawdown_pct is not None:
        value = max(0.0, float(args.equity_circuit_rearm_drawdown_pct))
        updates["equity_circuit_rearm_drawdown_pct"] = value
        suffix_parts.append(f"wfEqCbRearm{value:g}")
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
    if args.equity_soft_circuit_prearm_bars is not None:
        value = max(0, int(args.equity_soft_circuit_prearm_bars))
        updates["equity_soft_circuit_prearm_bars"] = value
        suffix_parts.append(f"wfEqSoftPre{value}")
    if args.equity_soft_circuit_min_bars_after_add is not None:
        value = max(0, int(args.equity_soft_circuit_min_bars_after_add))
        updates["equity_soft_circuit_min_bars_after_add"] = value
        suffix_parts.append(f"wfEqSoftGrace{value}")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _apply_equity_soft_sizer_overlay(
    config: MarketStateConfig,
    args: argparse.Namespace,
    *,
    prefix: str = "equity_soft_sizer_after_selection",
    suffix_label: str = "wfEqSize",
) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    drawdown_pct = getattr(args, f"{prefix}_drawdown_pct")
    cooldown_bars = getattr(args, f"{prefix}_cooldown_bars")
    size_mult = getattr(args, f"{prefix}_size_mult")
    force_flat = bool(getattr(args, f"{prefix}_force_flat"))
    prearm_bars = getattr(args, f"{prefix}_prearm_bars")
    if drawdown_pct is not None:
        value = max(0.0, float(drawdown_pct))
        updates["equity_soft_circuit_drawdown_pct"] = value
        suffix_parts.append(f"{suffix_label}{value:g}")
    if cooldown_bars is not None:
        value = max(0, int(cooldown_bars))
        updates["equity_soft_circuit_cooldown_bars"] = value
        suffix_parts.append(f"{suffix_label}Cool{value}")
    if size_mult is not None:
        value = min(max(float(size_mult), 0.0), 1.0)
        updates["equity_soft_circuit_size_mult"] = value
        suffix_parts.append(f"{suffix_label}Mult{value:g}")
    if force_flat:
        updates["equity_soft_circuit_force_flat"] = True
        suffix_parts.append(f"{suffix_label}Flat1")
    else:
        updates["equity_soft_circuit_force_flat"] = False
    if prearm_bars is not None:
        value = max(0, int(prearm_bars))
        updates["equity_soft_circuit_prearm_bars"] = value
        suffix_parts.append(f"{suffix_label}Pre{value}")
    if not suffix_parts:
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


def _apply_trend_idle_overlay(config: MarketStateConfig, args: argparse.Namespace) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
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
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _apply_near_miss_overlay(
    config: MarketStateConfig,
    args: argparse.Namespace,
    *,
    attr_prefix: str = "near_miss_probe",
    suffix_label: str = "wfNearMiss",
) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    units = getattr(args, f"{attr_prefix}_units")
    if units is not None:
        value = max(0.0, float(units))
        updates["near_miss_probe_units"] = min(value, config.max_possible_units)
        suffix_parts.append(f"{suffix_label}{value:g}")
    min_score = getattr(args, f"{attr_prefix}_min_score")
    if min_score is not None:
        value = int(min_score)
        updates["near_miss_probe_min_score"] = value
        suffix_parts.append(f"{suffix_label}Score{value}")
    min_score_edge = getattr(args, f"{attr_prefix}_min_score_edge")
    if min_score_edge is not None:
        value = max(0, int(min_score_edge))
        updates["near_miss_probe_min_score_edge"] = value
        suffix_parts.append(f"{suffix_label}Edge{value}")
    min_reason_stack = getattr(args, f"{attr_prefix}_min_reason_stack")
    if min_reason_stack is not None:
        value = max(0, int(min_reason_stack))
        updates["near_miss_probe_min_reason_stack"] = value
        suffix_parts.append(f"{suffix_label}Stack{value}")
    cooldown_bars = getattr(args, f"{attr_prefix}_cooldown_bars")
    if cooldown_bars is not None:
        value = max(0, int(cooldown_bars))
        updates["near_miss_probe_cooldown_bars"] = value
        suffix_parts.append(f"{suffix_label}Cool{value}")
    max_extension_atr = getattr(args, f"{attr_prefix}_max_extension_atr")
    if max_extension_atr is not None:
        value = max(0.1, float(max_extension_atr))
        updates["near_miss_probe_max_extension_atr"] = value
        suffix_parts.append(f"{suffix_label}Ext{value:g}")
    failure_guard_count = getattr(args, f"{attr_prefix}_failure_guard_count")
    if failure_guard_count is not None:
        value = max(0, int(failure_guard_count))
        updates["near_miss_probe_failure_guard_count"] = value
        suffix_parts.append(f"{suffix_label}Fail{value}")
    failure_guard_window_bars = getattr(args, f"{attr_prefix}_failure_guard_window_bars")
    if failure_guard_window_bars is not None:
        value = max(1, int(failure_guard_window_bars))
        updates["near_miss_probe_failure_guard_window_bars"] = value
        suffix_parts.append(f"{suffix_label}FailWin{value}")
    failure_cooldown_bars = getattr(args, f"{attr_prefix}_failure_cooldown_bars")
    if failure_cooldown_bars is not None:
        value = max(0, int(failure_cooldown_bars))
        updates["near_miss_probe_failure_cooldown_bars"] = value
        suffix_parts.append(f"{suffix_label}FailCool{value}")
    allowed_soft_reasons = getattr(args, f"{attr_prefix}_allowed_soft_reasons", None)
    if allowed_soft_reasons is not None:
        value = _csv_tuple(allowed_soft_reasons)
        updates["near_miss_probe_allowed_soft_reasons"] = value
        suffix_parts.append(f"{suffix_label}Reasons{_tuple_suffix(value)}")
    allowed_alignments = getattr(args, f"{attr_prefix}_allowed_alignments", None)
    if allowed_alignments is not None:
        value = _csv_tuple(allowed_alignments)
        updates["near_miss_probe_allowed_alignments"] = value
        suffix_parts.append(f"{suffix_label}Align{_tuple_suffix(value)}")
    allowed_execution_contexts = getattr(args, f"{attr_prefix}_allowed_execution_contexts", None)
    if allowed_execution_contexts is not None:
        value = _csv_tuple(allowed_execution_contexts)
        updates["near_miss_probe_allowed_execution_contexts"] = value
        suffix_parts.append(f"{suffix_label}Exec{_tuple_suffix(value)}")
    allowed_regimes = getattr(args, f"{attr_prefix}_allowed_regimes", None)
    if allowed_regimes is not None:
        value = _csv_tuple(allowed_regimes)
        updates["near_miss_probe_allowed_regimes"] = value
        suffix_parts.append(f"{suffix_label}Reg{_tuple_suffix(value)}")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _apply_near_miss_context_guard_overlay(
    config: MarketStateConfig,
    args: argparse.Namespace,
    *,
    suffix_label: str = "wfNearMissCtxGuard",
) -> MarketStateConfig:
    if float(getattr(config, "near_miss_probe_units", 0.0) or 0.0) <= 1e-12:
        return config
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    field_specs = (
        ("near_miss_probe_allowed_soft_reasons", "Reasons"),
        ("near_miss_probe_allowed_alignments", "Align"),
        ("near_miss_probe_allowed_execution_contexts", "Exec"),
        ("near_miss_probe_allowed_regimes", "Reg"),
    )
    for field_name, suffix in field_specs:
        raw_value = getattr(args, field_name, None)
        if raw_value is None:
            continue
        value = _csv_tuple(raw_value)
        if getattr(config, field_name) == value:
            continue
        updates[field_name] = value
        suffix_parts.append(f"{suffix_label}{suffix}{_tuple_suffix(value)}")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _near_miss_context_guard_blockers(
    overlays_applied: list[str],
    args: argparse.Namespace,
) -> tuple[str, ...]:
    blocked_overlays = _csv_tuple(getattr(args, "near_miss_context_guard_blocked_overlays", ""))
    if not blocked_overlays:
        return ()
    applied = set(overlays_applied)
    return tuple(name for name in blocked_overlays if name in applied)


def _trend_idle_after_selection_allowed(train_result: dict[str, Any], args: argparse.Namespace) -> bool:
    train_return = float(train_result.get("total_return_pct") or 0.0)
    min_train_return = args.trend_idle_after_selection_min_train_return_pct
    if min_train_return is not None and train_return < float(min_train_return):
        return False
    max_train_return = args.trend_idle_after_selection_max_train_return_pct
    if max_train_return is not None and train_return > float(max_train_return):
        return False
    train_drawdown = float(train_result.get("max_drawdown_pct") or 0.0)
    min_train_drawdown = args.trend_idle_after_selection_min_train_drawdown_pct
    if min_train_drawdown is not None and train_drawdown < float(min_train_drawdown):
        return False
    max_train_drawdown = args.trend_idle_after_selection_max_train_drawdown_pct
    if max_train_drawdown is not None and train_drawdown > float(max_train_drawdown):
        return False
    return True


def _near_miss_after_selection_allowed(train_result: dict[str, Any], args: argparse.Namespace) -> bool:
    train_return = float(train_result.get("total_return_pct") or 0.0)
    min_train_return = args.near_miss_after_selection_min_train_return_pct
    if min_train_return is not None and train_return < float(min_train_return):
        return False
    max_train_return = args.near_miss_after_selection_max_train_return_pct
    if max_train_return is not None and train_return > float(max_train_return):
        return False
    train_drawdown = float(train_result.get("max_drawdown_pct") or 0.0)
    min_train_drawdown = args.near_miss_after_selection_min_train_drawdown_pct
    if min_train_drawdown is not None and train_drawdown < float(min_train_drawdown):
        return False
    max_train_drawdown = args.near_miss_after_selection_max_train_drawdown_pct
    if max_train_drawdown is not None and train_drawdown > float(max_train_drawdown):
        return False
    return True


def _apply_one_way_reversal_after_selection_overlay(
    config: MarketStateConfig,
    args: argparse.Namespace,
    *,
    switch_units: float | None = None,
    suffix_label: str = "wfOwRevAS",
) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    configured_units = args.one_way_reversal_after_selection_switch_units if switch_units is None else switch_units
    if configured_units is not None:
        value = max(0.0, float(configured_units))
        effective_value = min(value, config.max_possible_units)
        if abs(float(config.one_way_reversal_switch_units) - effective_value) > 1e-12:
            updates["one_way_reversal_switch_units"] = effective_value
            suffix_parts.append(f"{suffix_label}{value:g}")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _one_way_impulse_after_selection_allowed(
    train_result: dict[str, Any],
    args: argparse.Namespace,
    *,
    prefix: str = "one_way_impulse_after_selection",
) -> bool:
    source_config = dict(train_result.get("config") or {})
    source_max_units = float(source_config.get("max_possible_units") or 0.0)
    if not _range_allowed(
        source_max_units,
        getattr(args, f"{prefix}_min_source_max_units"),
        getattr(args, f"{prefix}_max_source_max_units"),
    ):
        return False
    train_return = float(train_result.get("total_return_pct") or 0.0)
    if not _range_allowed(
        train_return,
        getattr(args, f"{prefix}_min_train_return_pct"),
        getattr(args, f"{prefix}_max_train_return_pct"),
    ):
        return False
    train_drawdown = float(train_result.get("max_drawdown_pct") or 0.0)
    if not _range_allowed(
        train_drawdown,
        getattr(args, f"{prefix}_min_train_drawdown_pct"),
        getattr(args, f"{prefix}_max_train_drawdown_pct"),
    ):
        return False
    train_cost_drag = float(train_result.get("estimated_cost_drag_pct") or 0.0)
    if not _range_allowed(
        train_cost_drag,
        getattr(args, f"{prefix}_min_train_cost_drag_pct"),
        getattr(args, f"{prefix}_max_train_cost_drag_pct"),
    ):
        return False
    trim_ratio = _train_ratio(train_result, "one_way_forced_trim_per_add")
    if not _positive_range_allowed(
        trim_ratio,
        max(0.0, float(getattr(args, f"{prefix}_min_one_way_trim_per_add"))),
        max(0.0, float(getattr(args, f"{prefix}_max_one_way_trim_per_add"))),
    ):
        return False
    turnover_ratio = _train_ratio(train_result, "turnover_events_per_add")
    if not _positive_range_allowed(
        turnover_ratio,
        max(0.0, float(getattr(args, f"{prefix}_min_turnover_per_add"))),
        max(0.0, float(getattr(args, f"{prefix}_max_turnover_per_add"))),
    ):
        return False
    return True


def _apply_one_way_impulse_after_selection_overlay(
    config: MarketStateConfig,
    args: argparse.Namespace,
    *,
    prefix: str = "one_way_impulse_after_selection",
    suffix_label: str = "wfOwImpAS",
) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    probe_units = getattr(args, f"{prefix}_probe_units")
    min_score = getattr(args, f"{prefix}_min_one_way_score")
    min_score_diff = getattr(args, f"{prefix}_min_score_diff")
    cooldown_bars = getattr(args, f"{prefix}_cooldown_bars")
    max_extension_atr = getattr(args, f"{prefix}_max_extension_atr")
    if probe_units is not None:
        value = min(max(0.0, float(probe_units)), config.max_possible_units)
        updates["one_way_impulse_probe_units"] = value
        suffix_parts.append(f"{suffix_label}{value:g}")
    if min_score is not None:
        value = max(0.0, float(min_score))
        updates["one_way_impulse_min_one_way_score"] = value
        suffix_parts.append(f"{suffix_label}Score{value:g}")
    if min_score_diff is not None:
        value = int(min_score_diff)
        updates["one_way_impulse_min_score_diff"] = value
        suffix_parts.append(f"{suffix_label}Diff{value}")
    if cooldown_bars is not None:
        value = max(0, int(cooldown_bars))
        updates["one_way_impulse_cooldown_bars"] = value
        suffix_parts.append(f"{suffix_label}Cool{value}")
    if max_extension_atr is not None:
        value = max(0.1, float(max_extension_atr))
        updates["one_way_impulse_max_extension_atr"] = value
        suffix_parts.append(f"{suffix_label}Ext{value:g}")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _range_allowed(value: float, min_value: float | None, max_value: float | None) -> bool:
    if min_value is not None and value < float(min_value):
        return False
    if max_value is not None and value > float(max_value):
        return False
    return True


def _positive_range_allowed(value: float, min_value: float, max_value: float) -> bool:
    if min_value > 0.0 and value < min_value:
        return False
    if max_value > 0.0 and value > max_value:
        return False
    return True


def _train_ratio(train_result: dict[str, Any], key: str) -> float:
    diagnostics = dict(train_result.get("event_diagnostics") or {})
    ratios = dict(diagnostics.get("ratios") or {})
    return float(ratios.get(key) or 0.0)


def _legacy_source_config_ranges_allowed(source_config: dict[str, Any], gate: dict[str, Any]) -> bool:
    for field_name, raw_bounds in dict(gate.get("source_config_ranges") or {}).items():
        if not isinstance(raw_bounds, dict):
            return False
        if field_name not in source_config:
            return False
        try:
            value = float(source_config.get(field_name))
        except (TypeError, ValueError):
            return False
        if not _range_allowed(value, raw_bounds.get("min"), raw_bounds.get("max")):
            return False
    return True


def _legacy_recipe_allowed(train_result: dict[str, Any], recipe: dict[str, Any]) -> bool:
    gate = dict(recipe.get("gate") or {})
    source_config = dict(train_result.get("config") or {})
    source_max_units = float(source_config.get("max_possible_units") or 0.0)
    if not _range_allowed(
        source_max_units,
        gate.get("min_source_max_units"),
        gate.get("max_source_max_units"),
    ):
        return False
    if not _legacy_source_config_ranges_allowed(source_config, gate):
        return False
    train_return = float(train_result.get("total_return_pct") or 0.0)
    if not _range_allowed(
        train_return,
        gate.get("min_train_return_pct"),
        gate.get("max_train_return_pct"),
    ):
        return False
    train_drawdown = float(train_result.get("max_drawdown_pct") or 0.0)
    if not _range_allowed(
        train_drawdown,
        gate.get("min_train_drawdown_pct"),
        gate.get("max_train_drawdown_pct"),
    ):
        return False
    train_cost_drag = float(train_result.get("estimated_cost_drag_pct") or 0.0)
    if not _range_allowed(
        train_cost_drag,
        gate.get("min_train_cost_drag_pct"),
        gate.get("max_train_cost_drag_pct"),
    ):
        return False
    trim_ratio = _train_ratio(train_result, "one_way_forced_trim_per_add")
    if not _positive_range_allowed(
        trim_ratio,
        max(0.0, float(gate.get("min_one_way_trim_per_add") or 0.0)),
        max(0.0, float(gate.get("max_one_way_trim_per_add") or 0.0)),
    ):
        return False
    turnover_ratio = _train_ratio(train_result, "turnover_events_per_add")
    if not _positive_range_allowed(
        turnover_ratio,
        max(0.0, float(gate.get("min_turnover_per_add") or 0.0)),
        max(0.0, float(gate.get("max_turnover_per_add") or 0.0)),
    ):
        return False
    return True


def _legacy_recipe_value(field_name: str, value: Any, config: MarketStateConfig) -> Any:
    if field_name in {
        "max_hold_bars",
        "one_way_trim_cooldown_bars",
        "one_way_impulse_min_score_diff",
        "one_way_impulse_cooldown_bars",
        "equity_soft_circuit_recovery_min_score_diff",
        "equity_soft_circuit_cooldown_bars",
        "near_miss_probe_min_score",
        "near_miss_probe_min_score_edge",
        "near_miss_probe_min_reason_stack",
        "near_miss_probe_cooldown_bars",
        "near_miss_probe_failure_guard_count",
        "near_miss_probe_failure_guard_window_bars",
        "near_miss_probe_failure_cooldown_bars",
        "hard_time_exit_cooldown_bars",
        "hard_time_exit_trend_defer_bars",
        "hard_time_loss_defer_bars",
    }:
        return max(0, int(value))
    if field_name in {
        "max_possible_units",
        "base_max_units",
        "base_add_units",
        "battle_units",
        "trend_core_units",
        "one_way_reversal_switch_units",
        "one_way_impulse_probe_units",
        "equity_soft_circuit_recovery_probe_units",
        "near_miss_probe_units",
    }:
        upper_bound = float(value) if field_name == "max_possible_units" else float(config.max_possible_units)
        return min(max(float(value), 0.0), upper_bound)
    if field_name in {
        "base_entry_reduce_size_mult",
        "equity_soft_circuit_size_mult",
        "equity_soft_circuit_inventory_trim_fraction",
        "event_risk_base_reduce_size_mult",
    }:
        return min(max(float(value), 0.0), 1.0)
    if field_name in {
        "reaction_trim_size_mult",
        "one_way_trim_size_mult",
        "hard_time_exit_fraction",
    }:
        return min(max(float(value), 0.05), 1.0)
    if field_name == "reaction_trim_trend_hold_trigger_mult":
        return min(max(float(value), 1.0), 5.0)
    if field_name in {
        "reaction_trim_trigger",
        "repair_cut",
        "repair_stop",
        "base_entry_reduce_extension_atr",
        "base_entry_reduce_promote_reaction",
        "event_risk_base_reduce_min_extension_atr",
        "event_risk_base_reduce_max_extension_atr",
        "equity_soft_circuit_drawdown_pct",
        "one_way_impulse_min_one_way_score",
        "one_way_impulse_max_extension_atr",
        "probe_take_profit_reaction",
        "probe_stop_reaction",
        "equity_soft_circuit_recovery_min_one_way_score",
        "equity_soft_circuit_recovery_max_extension_atr",
        "near_miss_probe_max_extension_atr",
        "one_way_trim_min_adverse_reaction",
        "hard_time_exit_trend_defer_min_favorable_reaction",
        "hard_time_loss_defer_min_loss_usd",
        "trend_hold_min_trend_strength",
        "trend_hold_min_one_way_score",
    }:
        return max(0.0, float(value))
    if field_name in {
        "hard_time_loss_defer_context_fragments",
        "near_miss_probe_allowed_soft_reasons",
        "near_miss_probe_allowed_alignments",
        "near_miss_probe_allowed_execution_contexts",
        "near_miss_probe_allowed_regimes",
    }:
        return _csv_tuple(value)
    if field_name == "event_risk_base_reduce_contexts":
        if isinstance(value, (list, tuple)):
            return tuple(dict.fromkeys(str(item) for item in value if str(item) in {"normal", "hour_open"}))
        return _parse_event_risk_contexts(str(value))
    if field_name == "event_risk_base_reduce_side":
        return str(value) if str(value) in {"both", "long", "short"} else "both"
    return value


def _apply_legacy_recipe_overlay(config: MarketStateConfig, recipe: dict[str, Any]) -> MarketStateConfig:
    change = dict(recipe.get("change") or {})
    if not change:
        return config
    config_fields = set(getattr(config, "__dataclass_fields__", {}))
    updates: dict[str, Any] = {}
    for field_name, raw_value in change.items():
        if field_name not in config_fields:
            continue
        value = _legacy_recipe_value(field_name, raw_value, config)
        current_value = getattr(config, field_name)
        if isinstance(current_value, float) or isinstance(value, float):
            if abs(float(current_value) - float(value)) <= 1e-12:
                continue
        elif current_value == value:
            continue
        updates[field_name] = value
    if not updates:
        return config
    suffix = str(recipe.get("suffix") or recipe.get("name") or "wfLegacyRecipe")
    updates["model_id"] = config.model_id if suffix in config.model_id.split(":") else f"{config.model_id}:{suffix}"
    return replace(config, **updates)


def _legacy_recipe_blockers(recipe: dict[str, Any], overlays_applied: list[str]) -> list[str]:
    applied = {str(name) for name in overlays_applied}
    return [
        str(name)
        for name in recipe.get("blocked_by_applied") or []
        if str(name) in applied
    ]


def _legacy_recipe_missing_required(recipe: dict[str, Any], overlays_applied: list[str]) -> list[str]:
    applied = {str(name) for name in overlays_applied}
    return [
        str(name)
        for name in recipe.get("required_applied") or []
        if str(name) not in applied
    ]


def _legacy_after_selection_recipes(args: argparse.Namespace) -> list[dict[str, Any]]:
    recipes: list[dict[str, Any]] = []
    for attr_name in (
        "selective_reaction_repair_clean_recipes",
        "midfold_reaction_hold_recipes",
        "trim_cooldown_recipes",
    ):
        for recipe in getattr(args, attr_name, None) or []:
            if isinstance(recipe, dict):
                recipes.append(recipe)
    risk_off_recipe = getattr(args, "risk_off_micro_sizer_recipe", None)
    if isinstance(risk_off_recipe, dict):
        recipes.append(risk_off_recipe)
    low_return_current_gate = {
        "min_source_max_units": 1.0,
        "max_source_max_units": 1.0,
        "min_train_return_pct": 215.0,
        "max_train_return_pct": 225.0,
        "min_train_drawdown_pct": 14.0,
        "max_train_drawdown_pct": 15.5,
        "min_train_cost_drag_pct": 65.0,
        "max_train_cost_drag_pct": 75.0,
        "min_one_way_trim_per_add": 0.30,
        "max_one_way_trim_per_add": 0.38,
        "min_turnover_per_add": 3.0,
        "max_turnover_per_add": 3.2,
    }
    low_return_current_chain_enabled = bool(
        getattr(args, "low_return_current_chain_replay_note", None)
    )
    if getattr(args, "soft_circuit_recovery_mid_replay_note", None):
        probe_units = max(
            0.0,
            float(getattr(args, "soft_circuit_recovery_mid_probe_units", 0.60)),
        )
        min_one_way_score = max(
            0.0,
            float(getattr(args, "soft_circuit_recovery_mid_min_one_way_score", 3.5)),
        )
        min_score_diff = max(
            0,
            int(getattr(args, "soft_circuit_recovery_mid_min_score_diff", 5)),
        )
        max_extension_atr = max(
            0.0,
            float(getattr(args, "soft_circuit_recovery_mid_max_extension_atr", 3.5)),
        )
        failure_guard_count = max(
            0,
            int(getattr(args, "soft_circuit_recovery_mid_failure_guard_count", 0)),
        )
        failure_guard_window = max(
            1,
            int(getattr(args, "soft_circuit_recovery_mid_failure_guard_window_bars", 1440)),
        )
        failure_cooldown = max(
            0,
            int(getattr(args, "soft_circuit_recovery_mid_failure_cooldown_bars", 0)),
        )
        change = {
            "equity_soft_circuit_recovery_probe_units": probe_units,
            "equity_soft_circuit_recovery_min_one_way_score": min_one_way_score,
            "equity_soft_circuit_recovery_min_score_diff": min_score_diff,
            "equity_soft_circuit_recovery_max_extension_atr": max_extension_atr,
        }
        if failure_guard_count > 0 and failure_cooldown > 0:
            change.update(
                {
                    "equity_soft_circuit_recovery_failure_guard_count": failure_guard_count,
                    "equity_soft_circuit_recovery_failure_guard_window_bars": failure_guard_window,
                    "equity_soft_circuit_recovery_failure_cooldown_bars": failure_cooldown,
                }
            )
        failure_suffix = (
            f"Fail{failure_guard_count}x{failure_guard_window}c{failure_cooldown}"
            if failure_guard_count > 0 and failure_cooldown > 0
            else ""
        )
        recipes.append(
            {
                "name": "soft_circuit_recovery_mid",
                "suffix": (
                    f"wfSoftRec{probe_units:g}Ow{min_one_way_score:g}"
                    f"D{min_score_diff:g}Ext{max_extension_atr:g}{failure_suffix}"
                ),
                "change": change,
                "gate": {
                    "min_source_max_units": 1.5,
                    "max_source_max_units": 1.5,
                    "min_train_return_pct": 36.0,
                    "max_train_return_pct": 40.0,
                    "min_train_drawdown_pct": 19.0,
                    "max_train_drawdown_pct": 21.0,
                    "min_train_cost_drag_pct": 22.0,
                    "max_train_cost_drag_pct": 25.0,
                    "min_one_way_trim_per_add": 0.49,
                    "max_one_way_trim_per_add": 0.51,
                    "min_turnover_per_add": 2.35,
                    "max_turnover_per_add": 2.40,
                },
            }
        )
    if getattr(args, "soft_circuit_recovery_low_activity_replay_note", None):
        probe_units = max(
            0.0,
            float(getattr(args, "soft_circuit_recovery_low_activity_probe_units", 0.25)),
        )
        min_one_way_score = max(
            0.0,
            float(getattr(args, "soft_circuit_recovery_low_activity_min_one_way_score", 3.0)),
        )
        min_score_diff = max(
            0,
            int(getattr(args, "soft_circuit_recovery_low_activity_min_score_diff", 4)),
        )
        max_extension_atr = max(
            0.0,
            float(getattr(args, "soft_circuit_recovery_low_activity_max_extension_atr", 3.5)),
        )
        failure_guard_count = max(
            0,
            int(getattr(args, "soft_circuit_recovery_low_activity_failure_guard_count", 1)),
        )
        failure_guard_window = max(
            1,
            int(getattr(args, "soft_circuit_recovery_low_activity_failure_guard_window_bars", 1440)),
        )
        failure_cooldown = max(
            0,
            int(getattr(args, "soft_circuit_recovery_low_activity_failure_cooldown_bars", 4320)),
        )
        change = {
            "equity_soft_circuit_recovery_probe_units": probe_units,
            "equity_soft_circuit_recovery_min_one_way_score": min_one_way_score,
            "equity_soft_circuit_recovery_min_score_diff": min_score_diff,
            "equity_soft_circuit_recovery_max_extension_atr": max_extension_atr,
        }
        if failure_guard_count > 0 and failure_cooldown > 0:
            change.update(
                {
                    "equity_soft_circuit_recovery_failure_guard_count": failure_guard_count,
                    "equity_soft_circuit_recovery_failure_guard_window_bars": failure_guard_window,
                    "equity_soft_circuit_recovery_failure_cooldown_bars": failure_cooldown,
                }
            )
        failure_suffix = (
            f"Fail{failure_guard_count}x{failure_guard_window}c{failure_cooldown}"
            if failure_guard_count > 0 and failure_cooldown > 0
            else ""
        )
        recipes.append(
            {
                "name": "soft_circuit_recovery_low_activity",
                "suffix": (
                    f"wfSoftRecLow{probe_units:g}Ow{min_one_way_score:g}"
                    f"D{min_score_diff:g}Ext{max_extension_atr:g}{failure_suffix}"
                ),
                "change": change,
                "required_applied": ["equity_soft_circuit"],
                "gate": {
                    "min_source_max_units": 1.5,
                    "max_source_max_units": 1.5,
                    "min_train_return_pct": 18.0,
                    "max_train_return_pct": 24.0,
                    "min_train_drawdown_pct": 21.0,
                    "max_train_drawdown_pct": 23.0,
                    "min_train_cost_drag_pct": 13.0,
                    "max_train_cost_drag_pct": 16.0,
                    "min_one_way_trim_per_add": 0.53,
                    "max_one_way_trim_per_add": 0.56,
                    "min_turnover_per_add": 2.0,
                    "max_turnover_per_add": 2.1,
                },
            }
        )
    if getattr(args, "soft_circuit_low_activity_cooldown_replay_note", None):
        cooldown_bars = max(
            0,
            int(getattr(args, "soft_circuit_low_activity_cooldown_bars", 4320)),
        )
        recipes.append(
            {
                "name": "soft_circuit_low_activity_cooldown",
                "suffix": f"wfEqSoftCool{cooldown_bars}",
                "change": {"equity_soft_circuit_cooldown_bars": cooldown_bars},
                "required_applied": ["soft_circuit_recovery_low_activity"],
                "gate": {
                    "min_source_max_units": 1.5,
                    "max_source_max_units": 1.5,
                    "min_train_return_pct": 18.0,
                    "max_train_return_pct": 24.0,
                    "min_train_drawdown_pct": 21.0,
                    "max_train_drawdown_pct": 23.0,
                    "min_train_cost_drag_pct": 13.0,
                    "max_train_cost_drag_pct": 16.0,
                    "min_one_way_trim_per_add": 0.53,
                    "max_one_way_trim_per_add": 0.56,
                    "min_turnover_per_add": 2.0,
                    "max_turnover_per_add": 2.1,
                },
            }
        )
    if getattr(args, "soft_circuit_low_activity_entry_grace_replay_note", None):
        grace_bars = max(
            0,
            int(getattr(args, "soft_circuit_low_activity_entry_grace_bars", 6)),
        )
        recipes.append(
            {
                "name": "soft_circuit_low_activity_entry_grace",
                "suffix": f"wfEqSoftGrace{grace_bars}",
                "change": {"equity_soft_circuit_min_bars_after_add": grace_bars},
                "required_applied": [
                    "soft_circuit_recovery_low_activity",
                    "soft_circuit_low_activity_cooldown",
                ],
                "gate": {
                    "min_source_max_units": 1.5,
                    "max_source_max_units": 1.5,
                    "min_train_return_pct": 18.0,
                    "max_train_return_pct": 24.0,
                    "min_train_drawdown_pct": 21.0,
                    "max_train_drawdown_pct": 23.0,
                    "min_train_cost_drag_pct": 13.0,
                    "max_train_cost_drag_pct": 16.0,
                    "min_one_way_trim_per_add": 0.53,
                    "max_one_way_trim_per_add": 0.56,
                    "min_turnover_per_add": 2.03,
                    "max_turnover_per_add": 2.06,
                },
            }
        )
    if getattr(args, "soft_circuit_low_activity_near_miss_replay_note", None):
        recipes.append(
            {
                "name": "soft_circuit_low_activity_near_miss",
                "suffix": "wfSoftLowNear0.2",
                "change": {"near_miss_probe_units": 0.20},
                "required_applied": [
                    "soft_circuit_recovery_low_activity",
                    "soft_circuit_low_activity_cooldown",
                ],
                "gate": {
                    "min_source_max_units": 1.5,
                    "max_source_max_units": 1.5,
                    "min_train_return_pct": 18.0,
                    "max_train_return_pct": 22.0,
                    "min_train_drawdown_pct": 21.0,
                    "max_train_drawdown_pct": 23.0,
                    "min_train_cost_drag_pct": 13.0,
                    "max_train_cost_drag_pct": 15.0,
                    "min_one_way_trim_per_add": 0.53,
                    "max_one_way_trim_per_add": 0.56,
                    "min_turnover_per_add": 2.03,
                    "max_turnover_per_add": 2.06,
                },
            }
        )
    if getattr(args, "high_return_soft_sizer_relax_replay_note", None):
        relax_drawdown = max(
            0.0,
            float(getattr(args, "high_return_soft_sizer_relax_drawdown_pct", 11.0)),
        )
        relax_size_mult = max(
            0.0,
            float(getattr(args, "high_return_soft_sizer_relax_size_mult", 0.25)),
        )
        relax_cooldown = max(
            0,
            int(getattr(args, "high_return_soft_sizer_relax_cooldown_bars", 2880)),
        )
        size_suffix = f"{int(round(relax_size_mult * 100)):03d}"
        recipes.append(
            {
                "name": "high_return_soft_sizer_relax",
                "suffix": f"wfEqSoftRelax{relax_drawdown:g}M{size_suffix}",
                "change": {
                    "equity_soft_circuit_drawdown_pct": relax_drawdown,
                    "equity_soft_circuit_size_mult": relax_size_mult,
                    "equity_soft_circuit_cooldown_bars": relax_cooldown,
                    "equity_soft_circuit_force_flat": False,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 68.0,
                    "max_train_return_pct": 75.0,
                    "min_train_drawdown_pct": 11.0,
                    "max_train_drawdown_pct": 13.0,
                    "min_train_cost_drag_pct": 32.0,
                    "max_train_cost_drag_pct": 36.0,
                    "min_one_way_trim_per_add": 0.35,
                    "max_one_way_trim_per_add": 0.39,
                    "min_turnover_per_add": 2.10,
                    "max_turnover_per_add": 2.20,
                },
            }
        )
    if getattr(args, "high_return_soft_sizer_tight_replay_note", None):
        tight_drawdown = max(
            0.0,
            float(getattr(args, "high_return_soft_sizer_tight_drawdown_pct", 9.0)),
        )
        tight_size_mult = max(
            0.0,
            float(getattr(args, "high_return_soft_sizer_tight_size_mult", 0.10)),
        )
        tight_cooldown = max(
            0,
            int(getattr(args, "high_return_soft_sizer_tight_cooldown_bars", 2880)),
        )
        tight_size_suffix = f"{int(round(tight_size_mult * 100)):03d}"
        recipes.append(
            {
                "name": "high_return_soft_sizer_relax",
                "suffix": f"wfEqSoftRelaxTight{tight_drawdown:g}M{tight_size_suffix}",
                "change": {
                    "equity_soft_circuit_drawdown_pct": tight_drawdown,
                    "equity_soft_circuit_size_mult": tight_size_mult,
                    "equity_soft_circuit_cooldown_bars": tight_cooldown,
                    "equity_soft_circuit_force_flat": False,
                },
                "required_applied": ["high_return_soft_sizer_relax"],
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 68.0,
                    "max_train_return_pct": 75.0,
                    "min_train_drawdown_pct": 11.0,
                    "max_train_drawdown_pct": 13.0,
                    "min_train_cost_drag_pct": 32.0,
                    "max_train_cost_drag_pct": 36.0,
                    "min_one_way_trim_per_add": 0.35,
                    "max_one_way_trim_per_add": 0.39,
                    "min_turnover_per_add": 2.10,
                    "max_turnover_per_add": 2.20,
                },
            }
        )
    if getattr(args, "deep_soft_reaction_delay_replay_note", None):
        recipes.append(
            {
                "name": "deep_soft_reaction_delay",
                "suffix": "wfDeepSoftReact1",
                "change": {"reaction_trim_trigger": 1.0},
                "blocked_by_applied": ["trim_cooldown_deep_soft"],
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 42.0,
                    "max_train_return_pct": 45.0,
                    "min_train_drawdown_pct": 31.0,
                    "max_train_drawdown_pct": 33.0,
                    "min_train_cost_drag_pct": 37.0,
                    "max_train_cost_drag_pct": 40.0,
                    "min_one_way_trim_per_add": 0.39,
                    "max_one_way_trim_per_add": 0.41,
                    "min_turnover_per_add": 2.13,
                    "max_turnover_per_add": 2.16,
                },
            }
        )
    if getattr(args, "forced_trim_near_miss_tiny_replay_note", None):
        recipes.append(
            {
                "name": "forced_trim_near_miss_tiny",
                "suffix": "wfNearMissTiny0.001",
                "change": {"near_miss_probe_units": 0.001},
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 13.0,
                    "max_train_return_pct": 16.0,
                    "min_train_drawdown_pct": 30.0,
                    "max_train_drawdown_pct": 32.0,
                    "min_train_cost_drag_pct": 20.0,
                    "max_train_cost_drag_pct": 23.0,
                    "min_one_way_trim_per_add": 0.53,
                    "max_one_way_trim_per_add": 0.56,
                    "min_turnover_per_add": 2.00,
                    "max_turnover_per_add": 2.04,
                },
            }
        )
    if getattr(args, "deep_drawdown_reversal_scale_replay_note", None):
        recipes.append(
            {
                "name": "deep_drawdown_reversal_scale",
                "suffix": "wfDeepOwRev0.7",
                "change": {"one_way_reversal_switch_units": 0.70},
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 60.0,
                    "max_train_return_pct": 63.0,
                    "min_train_drawdown_pct": 30.0,
                    "max_train_drawdown_pct": 32.0,
                    "min_train_cost_drag_pct": 35.0,
                    "max_train_cost_drag_pct": 38.0,
                    "min_one_way_trim_per_add": 0.54,
                    "max_one_way_trim_per_add": 0.56,
                    "min_turnover_per_add": 2.17,
                    "max_turnover_per_add": 2.20,
                },
            }
        )
    if getattr(args, "low_activity_reengage_probe_replay_note", None):
        recipes.append(
            {
                "name": "low_activity_reengage_probe",
                "suffix": "wfLowActNear0.0025",
                "change": {
                    "near_miss_probe_units": 0.0025,
                    "near_miss_probe_min_score": 4,
                    "near_miss_probe_min_score_edge": 0,
                    "near_miss_probe_min_reason_stack": 1,
                    "near_miss_probe_cooldown_bars": 36,
                    "near_miss_probe_max_extension_atr": 2.25,
                    "near_miss_probe_failure_guard_count": 2,
                    "near_miss_probe_failure_guard_window_bars": 1440,
                    "near_miss_probe_failure_cooldown_bars": 2880,
                },
                "gate": {
                    "min_source_max_units": 1.5,
                    "max_source_max_units": 1.5,
                    "min_train_return_pct": 18.0,
                    "max_train_return_pct": 40.0,
                    "min_train_drawdown_pct": 19.0,
                    "max_train_drawdown_pct": 23.0,
                    "min_train_cost_drag_pct": 13.0,
                    "max_train_cost_drag_pct": 25.0,
                    "min_one_way_trim_per_add": 0.49,
                    "max_one_way_trim_per_add": 0.56,
                    "min_turnover_per_add": 2.0,
                    "max_turnover_per_add": 2.4,
                },
            }
        )
    if getattr(args, "base_heavy_probe_rebalance_replay_note", None):
        recipes.append(
            {
                "name": "base_heavy_probe_rebalance",
                "suffix": "wfBaseHeavyNear0.0015Imp0.0001",
                "change": {
                    "near_miss_probe_units": 0.0015,
                    "near_miss_probe_min_score": 4,
                    "near_miss_probe_min_score_edge": 0,
                    "near_miss_probe_min_reason_stack": 1,
                    "near_miss_probe_cooldown_bars": 48,
                    "near_miss_probe_max_extension_atr": 2.0,
                    "near_miss_probe_failure_guard_count": 2,
                    "near_miss_probe_failure_guard_window_bars": 1440,
                    "near_miss_probe_failure_cooldown_bars": 4320,
                    "one_way_impulse_probe_units": 0.0001,
                    "one_way_impulse_min_one_way_score": 3.5,
                    "one_way_impulse_min_score_diff": 5,
                    "one_way_impulse_cooldown_bars": 48,
                    "one_way_impulse_max_extension_atr": 2.5,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 160.0,
                    "max_train_return_pct": 245.0,
                    "min_train_drawdown_pct": 14.0,
                    "max_train_drawdown_pct": 21.0,
                    "min_train_cost_drag_pct": 65.0,
                    "max_train_cost_drag_pct": 85.0,
                    "min_one_way_trim_per_add": 0.30,
                    "max_one_way_trim_per_add": 0.39,
                    "min_turnover_per_add": 2.40,
                    "max_turnover_per_add": 2.48,
                },
            }
        )
    if getattr(args, "event_risk_base_throttle_replay_note", None):
        recipes.append(
            {
                "name": "event_risk_base_throttle",
                "suffix": "wfEventBaseHourShortExt2.5M025",
                "change": {
                    "event_risk_base_reduce_size_mult": 0.25,
                    "event_risk_base_reduce_min_extension_atr": 2.5,
                    "event_risk_base_reduce_side": "short",
                    "event_risk_base_reduce_contexts": ("hour_open",),
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 160.0,
                    "max_train_return_pct": 245.0,
                    "min_train_drawdown_pct": 14.0,
                    "max_train_drawdown_pct": 21.0,
                    "min_train_cost_drag_pct": 65.0,
                    "max_train_cost_drag_pct": 85.0,
                    "min_one_way_trim_per_add": 0.30,
                    "max_one_way_trim_per_add": 0.39,
                    "min_turnover_per_add": 2.40,
                    "max_turnover_per_add": 2.49,
                },
            }
        )
    if getattr(args, "event_risk_base_tight_repair_replay_note", None):
        recipes.append(
            {
                "name": "event_risk_base_tight_repair",
                "suffix": "wfEventBaseTightM010",
                "change": {
                    "event_risk_base_reduce_size_mult": 0.10,
                },
                "required_applied": [
                    "event_risk_base_throttle",
                    "repair_tune_tight",
                ],
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 235.0,
                    "max_train_return_pct": 245.0,
                    "min_train_drawdown_pct": 14.0,
                    "max_train_drawdown_pct": 16.0,
                    "min_train_cost_drag_pct": 73.0,
                    "max_train_cost_drag_pct": 77.0,
                    "min_one_way_trim_per_add": 0.32,
                    "max_one_way_trim_per_add": 0.34,
                    "min_turnover_per_add": 2.44,
                    "max_turnover_per_add": 2.47,
                },
            }
        )
    if getattr(args, "event_risk_reaction_soft_hold_replay_note", None):
        recipes.append(
            {
                "name": "event_risk_reaction_soft_hold",
                "suffix": "wfEventReactSoft8Inv050M005",
                "change": {
                    "reaction_trim_trigger": 1.0,
                    "event_risk_base_reduce_size_mult": 0.05,
                    "equity_soft_circuit_drawdown_pct": 8.0,
                    "equity_soft_circuit_cooldown_bars": 2880,
                    "equity_soft_circuit_size_mult": 0.25,
                    "equity_soft_circuit_force_flat": False,
                    "equity_soft_circuit_inventory_trim_fraction": 0.50,
                },
                "required_applied": ["event_risk_base_tight_repair"],
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 235.0,
                    "max_train_return_pct": 245.0,
                    "min_train_drawdown_pct": 14.0,
                    "max_train_drawdown_pct": 16.0,
                    "min_train_cost_drag_pct": 73.0,
                    "max_train_cost_drag_pct": 77.0,
                    "min_one_way_trim_per_add": 0.32,
                    "max_one_way_trim_per_add": 0.34,
                    "min_turnover_per_add": 2.44,
                    "max_turnover_per_add": 2.47,
                },
            }
        )
    if getattr(args, "event_risk_soft_hold_near_miss_replay_note", None):
        recipes.append(
            {
                "name": "event_risk_soft_hold_near_miss",
                "suffix": "wfEventSoftNear0.0025",
                "change": {
                    "near_miss_probe_units": 0.0025,
                    "near_miss_probe_min_score": 4,
                    "near_miss_probe_min_score_edge": 0,
                },
                "required_applied": ["event_risk_reaction_soft_hold"],
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 235.0,
                    "max_train_return_pct": 245.0,
                    "min_train_drawdown_pct": 14.0,
                    "max_train_drawdown_pct": 16.0,
                    "min_train_cost_drag_pct": 73.0,
                    "max_train_cost_drag_pct": 77.0,
                    "min_one_way_trim_per_add": 0.32,
                    "max_one_way_trim_per_add": 0.34,
                    "min_turnover_per_add": 2.44,
                    "max_turnover_per_add": 2.47,
                },
            }
        )
    if getattr(args, "negative_train_distribution_probe_replay_note", None):
        recipes.append(
            {
                "name": "negative_train_distribution_probe",
                "suffix": "wfNegTrainDistNear1e-05",
                "change": {
                    "near_miss_probe_units": 0.00001,
                    "near_miss_probe_min_score": 4,
                    "near_miss_probe_min_score_edge": 0,
                    "near_miss_probe_min_reason_stack": 1,
                    "near_miss_probe_cooldown_bars": 36,
                    "near_miss_probe_max_extension_atr": 2.0,
                    "near_miss_probe_failure_guard_count": 2,
                    "near_miss_probe_failure_guard_window_bars": 1440,
                    "near_miss_probe_failure_cooldown_bars": 4320,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": -2.0,
                    "max_train_return_pct": 0.0,
                    "min_train_drawdown_pct": 29.0,
                    "max_train_drawdown_pct": 31.0,
                    "min_train_cost_drag_pct": 18.0,
                    "max_train_cost_drag_pct": 21.0,
                    "min_one_way_trim_per_add": 0.50,
                    "max_one_way_trim_per_add": 0.54,
                    "min_turnover_per_add": 2.03,
                    "max_turnover_per_add": 2.06,
                },
            }
        )
    if getattr(args, "compressed_trend_distribution_probe_replay_note", None):
        recipes.append(
            {
                "name": "compressed_trend_distribution_probe",
                "suffix": "wfCompressedDistNear1e-05",
                "change": {
                    "near_miss_probe_units": 0.00001,
                    "near_miss_probe_min_score": 4,
                    "near_miss_probe_min_score_edge": 0,
                    "near_miss_probe_min_reason_stack": 1,
                    "near_miss_probe_cooldown_bars": 36,
                    "near_miss_probe_max_extension_atr": 2.0,
                    "near_miss_probe_failure_guard_count": 2,
                    "near_miss_probe_failure_guard_window_bars": 1440,
                    "near_miss_probe_failure_cooldown_bars": 4320,
                },
                "required_applied": ["reaction_tune_compressed_trend"],
                "gate": {
                    "min_source_max_units": 1.5,
                    "max_source_max_units": 1.5,
                    "min_train_return_pct": 18.0,
                    "max_train_return_pct": 22.0,
                    "min_train_drawdown_pct": 13.0,
                    "max_train_drawdown_pct": 15.0,
                    "min_train_cost_drag_pct": 18.0,
                    "max_train_cost_drag_pct": 21.0,
                    "min_one_way_trim_per_add": 0.42,
                    "max_one_way_trim_per_add": 0.45,
                    "min_turnover_per_add": 2.50,
                    "max_turnover_per_add": 2.60,
                },
            }
        )
    if getattr(args, "balanced_structure_replay_note", None):
        recipes.extend(
            [
                {
                    "name": "distribution_balance",
                    "suffix": "wfDistributionBalance0.00025",
                    "change": {
                        "near_miss_probe_units": 0.00025,
                        "near_miss_probe_min_score": 4,
                        "near_miss_probe_min_score_edge": 0,
                        "near_miss_probe_cooldown_bars": 36,
                        "near_miss_probe_max_extension_atr": 2.0,
                        "near_miss_probe_failure_guard_count": 2,
                        "near_miss_probe_failure_guard_window_bars": 1440,
                        "near_miss_probe_failure_cooldown_bars": 4320,
                    },
                    "gate": {
                        "min_source_max_units": 1.0,
                        "max_source_max_units": 1.0,
                        "min_train_return_pct": 165.0,
                        "max_train_return_pct": 170.0,
                        "min_train_drawdown_pct": 20.0,
                        "max_train_drawdown_pct": 21.0,
                        "min_train_cost_drag_pct": 65.0,
                        "max_train_cost_drag_pct": 68.0,
                        "min_one_way_trim_per_add": 0.37,
                        "max_one_way_trim_per_add": 0.39,
                        "min_turnover_per_add": 2.46,
                        "max_turnover_per_add": 2.49,
                    },
                },
                {
                    "name": "role_balance_near_miss",
                    "suffix": "wfRoleBalanceNear0.0025",
                    "change": {
                        "near_miss_probe_units": 0.0025,
                        "near_miss_probe_min_score": 4,
                        "near_miss_probe_min_score_edge": 0,
                        "near_miss_probe_cooldown_bars": 36,
                        "near_miss_probe_max_extension_atr": 2.0,
                        "near_miss_probe_failure_guard_count": 2,
                        "near_miss_probe_failure_guard_window_bars": 1440,
                        "near_miss_probe_failure_cooldown_bars": 4320,
                    },
                    "blocked_by_applied": ["reaction_tune_compressed_trend"],
                    "gate": {
                        "min_source_max_units": 1.5,
                        "max_source_max_units": 1.5,
                        "min_train_return_pct": 18.0,
                        "max_train_return_pct": 22.0,
                        "min_train_drawdown_pct": 13.0,
                        "max_train_drawdown_pct": 15.0,
                        "min_train_cost_drag_pct": 18.0,
                        "max_train_cost_drag_pct": 21.0,
                        "min_one_way_trim_per_add": 0.42,
                        "max_one_way_trim_per_add": 0.45,
                        "min_turnover_per_add": 2.50,
                        "max_turnover_per_add": 2.60,
                    },
                },
                {
                    "name": "high_cost_trim_2880",
                    "suffix": "wfHighCostBalanceTrim2880",
                    "change": {"one_way_trim_cooldown_bars": 2880},
                    "gate": {
                        "min_source_max_units": 1.0,
                        "max_source_max_units": 1.0,
                        "min_train_return_pct": 45.0,
                        "max_train_return_pct": 60.0,
                        "min_train_drawdown_pct": 19.0,
                        "max_train_drawdown_pct": 22.0,
                        "min_train_cost_drag_pct": 40.0,
                        "max_train_cost_drag_pct": 48.0,
                        "min_one_way_trim_per_add": 0.35,
                        "max_one_way_trim_per_add": 0.40,
                        "min_turnover_per_add": 2.40,
                        "max_turnover_per_add": 2.50,
                    },
                },
                {
                    "name": "high_cost_balance_near_miss",
                    "suffix": "wfHighCostBalanceNear0.00025",
                    "change": {
                        "near_miss_probe_units": 0.00025,
                        "near_miss_probe_min_score": 4,
                        "near_miss_probe_min_score_edge": 0,
                        "near_miss_probe_cooldown_bars": 36,
                        "near_miss_probe_max_extension_atr": 2.0,
                        "near_miss_probe_failure_guard_count": 2,
                        "near_miss_probe_failure_guard_window_bars": 1440,
                        "near_miss_probe_failure_cooldown_bars": 4320,
                    },
                    "gate": {
                        "min_source_max_units": 1.0,
                        "max_source_max_units": 1.0,
                        "min_train_return_pct": 45.0,
                        "max_train_return_pct": 60.0,
                        "min_train_drawdown_pct": 19.0,
                        "max_train_drawdown_pct": 22.0,
                        "min_train_cost_drag_pct": 40.0,
                        "max_train_cost_drag_pct": 48.0,
                        "min_one_way_trim_per_add": 0.35,
                        "max_one_way_trim_per_add": 0.40,
                        "min_turnover_per_add": 2.40,
                        "max_turnover_per_add": 2.50,
                    },
                },
            ]
        )
        distribution_override_change = _provided_near_miss_recipe_change(
            args,
            "distribution_balance",
        )
        if distribution_override_change:
            recipes.append(
                {
                    "name": "distribution_balance_probe_override",
                    "suffix": _near_miss_recipe_override_suffix(
                        "wfDistributionBalance",
                        distribution_override_change,
                    ),
                    "change": distribution_override_change,
                    "required_applied": ["distribution_balance"],
                }
            )
    if getattr(args, "event_risk_distribution_base_off_replay_note", None):
        recipes.append(
            {
                "name": "event_risk_distribution_base_off",
                "suffix": "wfEventDistBaseM000",
                "change": {"event_risk_base_reduce_size_mult": 0.0},
                "required_applied": [
                    "event_risk_base_throttle",
                    "distribution_balance",
                ],
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 165.0,
                    "max_train_return_pct": 170.0,
                    "min_train_drawdown_pct": 20.0,
                    "max_train_drawdown_pct": 21.0,
                    "min_train_cost_drag_pct": 65.0,
                    "max_train_cost_drag_pct": 68.0,
                    "min_one_way_trim_per_add": 0.37,
                    "max_one_way_trim_per_add": 0.39,
                    "min_turnover_per_add": 2.46,
                    "max_turnover_per_add": 2.49,
                },
            }
        )
    if getattr(args, "event_risk_soft_hold_inventory_release_replay_note", None):
        release_fraction = min(
            max(
                float(getattr(args, "event_risk_soft_hold_inventory_release_fraction", 0.0)),
                0.0,
            ),
            1.0,
        )
        release_suffix = f"{int(round(release_fraction * 100)):03d}"
        recipes.append(
            {
                "name": "event_risk_soft_hold_inventory_release",
                "suffix": f"wfEventSoftInvReleaseF{release_suffix}",
                "change": {
                    "equity_soft_circuit_inventory_trim_fraction": release_fraction,
                },
                "required_applied": ["event_risk_soft_hold_near_miss"],
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 235.0,
                    "max_train_return_pct": 245.0,
                    "min_train_drawdown_pct": 14.0,
                    "max_train_drawdown_pct": 16.0,
                    "min_train_cost_drag_pct": 73.0,
                    "max_train_cost_drag_pct": 77.0,
                    "min_one_way_trim_per_add": 0.32,
                    "max_one_way_trim_per_add": 0.34,
                    "min_turnover_per_add": 2.44,
                    "max_turnover_per_add": 2.47,
                },
            }
        )
    if getattr(args, "fold13_stress_exit_sizer_replay_note", None):
        reaction_trim_size_mult = min(
            max(float(getattr(args, "fold13_stress_exit_sizer_reaction_trim_size_mult", 0.50)), 0.05),
            1.0,
        )
        hard_time_fraction = min(
            max(float(getattr(args, "fold13_stress_exit_sizer_hard_time_fraction", 0.25)), 0.05),
            1.0,
        )
        reaction_suffix = f"{int(round(reaction_trim_size_mult * 100)):03d}"
        hard_suffix = f"{int(round(hard_time_fraction * 100)):03d}"
        recipes.append(
            {
                "name": "fold13_stress_exit_sizer",
                "suffix": f"wfF13ExitSizerR{reaction_suffix}H{hard_suffix}",
                "required_applied": [
                    "one_way_reversal_boost",
                    "trim_cooldown",
                    "hold_compression_mid_reversal",
                    "event_risk_base_throttle",
                    "distribution_balance",
                    "event_risk_distribution_base_off",
                ],
                "change": {
                    "reaction_trim_size_mult": reaction_trim_size_mult,
                    "hard_time_exit_fraction": hard_time_fraction,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 160.0,
                    "max_train_return_pct": 175.0,
                    "min_train_drawdown_pct": 19.5,
                    "max_train_drawdown_pct": 21.0,
                    "min_train_cost_drag_pct": 64.0,
                    "max_train_cost_drag_pct": 69.0,
                    "min_one_way_trim_per_add": 0.36,
                    "max_one_way_trim_per_add": 0.40,
                    "min_turnover_per_add": 2.44,
                    "max_turnover_per_add": 2.50,
                },
            }
        )
    if getattr(args, "fold13_selective_impulse_replay_note", None):
        impulse_units = max(0.0, float(getattr(args, "fold13_selective_impulse_probe_units", 1.0)))
        impulse_score = max(0.0, float(getattr(args, "fold13_selective_impulse_min_one_way_score", 3.5)))
        impulse_diff = max(0, int(getattr(args, "fold13_selective_impulse_min_score_diff", 5)))
        reaction_trigger = max(
            0.05,
            float(getattr(args, "fold13_selective_impulse_reaction_trim_trigger", 0.60)),
        )
        recipes.append(
            {
                "name": "fold13_selective_impulse_probe",
                "suffix": (
                    f"wfF13OwImp{impulse_units:g}"
                    f"Score{impulse_score:g}D{impulse_diff}Ext2.75"
                    f"RTrim{reaction_trigger:g}"
                ),
                "required_applied": [
                    "one_way_reversal_boost",
                    "trim_cooldown",
                    "hold_compression_mid_reversal",
                    "event_risk_base_throttle",
                    "distribution_balance",
                    "event_risk_distribution_base_off",
                ],
                "change": {
                    "one_way_impulse_probe_units": impulse_units,
                    "one_way_impulse_min_one_way_score": impulse_score,
                    "one_way_impulse_min_score_diff": impulse_diff,
                    "one_way_impulse_cooldown_bars": 48,
                    "one_way_impulse_max_extension_atr": 2.75,
                    "reaction_trim_trigger": reaction_trigger,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 160.0,
                    "max_train_return_pct": 175.0,
                    "min_train_drawdown_pct": 19.5,
                    "max_train_drawdown_pct": 21.0,
                    "min_train_cost_drag_pct": 64.0,
                    "max_train_cost_drag_pct": 69.0,
                    "min_one_way_trim_per_add": 0.36,
                    "max_one_way_trim_per_add": 0.40,
                    "min_turnover_per_add": 2.44,
                    "max_turnover_per_add": 2.50,
                },
            }
        )
    if getattr(args, "fold13_near_miss_noise_filter_replay_note", None):
        recipes.append(
            {
                "name": "fold13_near_miss_noise_filter",
                "suffix": "wfF13NearMissDust1e-5",
                "required_applied": ["fold13_selective_impulse_probe"],
                "change": {"near_miss_probe_units": 0.00001},
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 160.0,
                    "max_train_return_pct": 175.0,
                    "min_train_drawdown_pct": 19.5,
                    "max_train_drawdown_pct": 21.0,
                    "min_train_cost_drag_pct": 64.0,
                    "max_train_cost_drag_pct": 69.0,
                    "min_one_way_trim_per_add": 0.36,
                    "max_one_way_trim_per_add": 0.40,
                    "min_turnover_per_add": 2.44,
                    "max_turnover_per_add": 2.50,
                },
            }
        )
    if getattr(args, "fold13_hard_loss_defer_replay_note", None):
        recipes.append(
            {
                "name": "fold13_hard_loss_defer",
                "suffix": "wfF13HardLossDef12",
                "required_applied": [
                    "fold13_selective_impulse_probe",
                    "fold13_near_miss_noise_filter",
                ],
                "change": {
                    "hard_time_loss_defer_bars": 12,
                    "hard_time_loss_defer_min_loss_usd": 10.0,
                    "hard_time_loss_defer_context_fragments": ("|normal|ext_0-0.75|",),
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 160.0,
                    "max_train_return_pct": 175.0,
                    "min_train_drawdown_pct": 19.5,
                    "max_train_drawdown_pct": 21.0,
                    "min_train_cost_drag_pct": 64.0,
                    "max_train_cost_drag_pct": 69.0,
                    "min_one_way_trim_per_add": 0.36,
                    "max_one_way_trim_per_add": 0.40,
                    "min_turnover_per_add": 2.44,
                    "max_turnover_per_add": 2.50,
                },
            }
        )
    if getattr(args, "fold13_hold_extension_replay_note", None):
        hold_bars = max(1, int(getattr(args, "fold13_hold_extension_bars", 144)))
        recipes.append(
            {
                "name": "fold13_hold_extension",
                "suffix": f"wfF13Hold{hold_bars}",
                "required_applied": [
                    "fold13_selective_impulse_probe",
                    "fold13_near_miss_noise_filter",
                    "fold13_hard_loss_defer",
                ],
                "change": {"max_hold_bars": hold_bars},
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "source_config_ranges": {
                        "max_hold_bars": {"min": 52.0, "max": 54.0},
                    },
                    "min_train_return_pct": 160.0,
                    "max_train_return_pct": 175.0,
                    "min_train_drawdown_pct": 19.5,
                    "max_train_drawdown_pct": 21.0,
                    "min_train_cost_drag_pct": 64.0,
                    "max_train_cost_drag_pct": 69.0,
                    "min_one_way_trim_per_add": 0.36,
                    "max_one_way_trim_per_add": 0.40,
                    "min_turnover_per_add": 2.44,
                    "max_turnover_per_add": 2.50,
                },
            }
        )
    if getattr(args, "fold13_one_way_delay_replay_note", None):
        min_adverse_reaction = max(
            0.0,
            float(getattr(args, "fold13_one_way_delay_min_adverse_reaction", 0.30)),
        )
        recipes.append(
            {
                "name": "fold13_one_way_delay",
                "suffix": f"wfF13OwMin{min_adverse_reaction:g}",
                "required_applied": ["fold13_hold_extension"],
                "change": {
                    "one_way_trim_min_adverse_reaction": min_adverse_reaction,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "source_config_ranges": {
                        "one_way_trim_min_adverse_reaction": {"min": 0.0, "max": 0.0},
                        "max_hold_bars": {"min": 52.0, "max": 54.0},
                    },
                    "min_train_return_pct": 160.0,
                    "max_train_return_pct": 175.0,
                    "min_train_drawdown_pct": 19.5,
                    "max_train_drawdown_pct": 21.0,
                    "min_train_cost_drag_pct": 64.0,
                    "max_train_cost_drag_pct": 69.0,
                    "min_one_way_trim_per_add": 0.36,
                    "max_one_way_trim_per_add": 0.40,
                    "min_turnover_per_add": 2.44,
                    "max_turnover_per_add": 2.50,
                },
            }
        )
    if getattr(args, "fold13_reaction_band_widen_replay_note", None):
        reaction_avg_band = max(
            0.05,
            float(getattr(args, "fold13_reaction_band_widen_avg_band", 2.0)),
        )
        recipes.append(
            {
                "name": "fold13_reaction_band_widen",
                "suffix": f"wfF13ReactBand{reaction_avg_band:g}",
                "required_applied": ["fold13_one_way_delay"],
                "change": {"reaction_avg_band": reaction_avg_band},
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "source_config_ranges": {
                        "reaction_avg_band": {"min": 0.94, "max": 0.96},
                        "one_way_trim_min_adverse_reaction": {"min": 0.0, "max": 0.0},
                        "max_hold_bars": {"min": 52.0, "max": 54.0},
                    },
                    "min_train_return_pct": 160.0,
                    "max_train_return_pct": 175.0,
                    "min_train_drawdown_pct": 19.5,
                    "max_train_drawdown_pct": 21.0,
                    "min_train_cost_drag_pct": 64.0,
                    "max_train_cost_drag_pct": 69.0,
                    "min_one_way_trim_per_add": 0.36,
                    "max_one_way_trim_per_add": 0.40,
                    "min_turnover_per_add": 2.44,
                    "max_turnover_per_add": 2.50,
                },
            }
        )
    if getattr(args, "fold11_reaction_delay_replay_note", None):
        reaction_trim_trigger = max(
            0.05,
            float(getattr(args, "fold11_reaction_delay_trigger", 1.25)),
        )
        recipes.append(
            {
                "name": "fold11_reaction_delay",
                "suffix": f"wfF11React{reaction_trim_trigger:g}",
                "required_applied": ["event_risk_soft_hold_inventory_release"],
                "change": {"reaction_trim_trigger": reaction_trim_trigger},
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "source_config_ranges": {
                        "reaction_trim_trigger": {"min": 0.54, "max": 0.56},
                        "repair_cut": {"min": 0.89, "max": 0.91},
                        "event_risk_base_reduce_size_mult": {"min": 0.99, "max": 1.01},
                        "near_miss_probe_units": {"min": 0.0, "max": 0.0},
                    },
                    "min_train_return_pct": 235.0,
                    "max_train_return_pct": 245.0,
                    "min_train_drawdown_pct": 14.5,
                    "max_train_drawdown_pct": 15.5,
                    "min_train_cost_drag_pct": 72.0,
                    "max_train_cost_drag_pct": 78.0,
                },
            }
        )
    if getattr(args, "fold8_chase_suppress_replay_note", None):
        chase_units = max(
            0.0,
            float(getattr(args, "fold8_chase_suppress_units", 0.0)),
        )
        recipes.append(
            {
                "name": "fold8_chase_suppress",
                "suffix": f"wfF8Chase{chase_units:g}",
                "required_applied": ["negative_train_distribution_probe"],
                "change": {"chase_units": chase_units},
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "source_config_ranges": {
                        "chase_units": {"min": 0.99, "max": 1.01},
                        "near_miss_probe_units": {"min": 0.0, "max": 0.00002},
                        "reaction_trim_trigger": {"min": 0.54, "max": 0.56},
                        "repair_cut": {"min": 0.89, "max": 0.91},
                    },
                    "min_train_return_pct": -2.0,
                    "max_train_return_pct": 0.0,
                    "min_train_drawdown_pct": 29.0,
                    "max_train_drawdown_pct": 31.0,
                    "min_train_cost_drag_pct": 18.0,
                    "max_train_cost_drag_pct": 21.0,
                },
            }
        )
    if getattr(args, "high_cost_repair_cut_05_replay_note", None):
        recipes.append(
            {
                "name": "high_cost_repair_cut_05",
                "suffix": "wfHighCostRepairCut0.5",
                "change": {"repair_cut": 0.5},
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 45.0,
                    "max_train_return_pct": 60.0,
                    "min_train_drawdown_pct": 19.0,
                    "max_train_drawdown_pct": 22.0,
                    "min_train_cost_drag_pct": 40.0,
                    "max_train_cost_drag_pct": 48.0,
                    "min_one_way_trim_per_add": 0.35,
                    "max_one_way_trim_per_add": 0.40,
                    "min_turnover_per_add": 2.40,
                    "max_turnover_per_add": 2.50,
                },
            }
        )
    if getattr(args, "high_cost_near_zero_react_replay_note", None):
        recipes.append(
            {
                "name": "high_cost_near_zero_react",
                "suffix": "wfHighCostNear0React0.56",
                "change": {
                    "near_miss_probe_units": 0.0,
                    "reaction_trim_trigger": 0.56,
                },
                "required_applied": ["high_cost_balance_near_miss"],
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 45.0,
                    "max_train_return_pct": 60.0,
                    "min_train_drawdown_pct": 19.0,
                    "max_train_drawdown_pct": 22.0,
                    "min_train_cost_drag_pct": 40.0,
                    "max_train_cost_drag_pct": 48.0,
                    "min_one_way_trim_per_add": 0.35,
                    "max_one_way_trim_per_add": 0.40,
                    "min_turnover_per_add": 2.40,
                    "max_turnover_per_add": 2.50,
                },
            }
        )
    if getattr(args, "high_cost_runner_reversal_scale_replay_note", None):
        recipes.append(
            {
                "name": "high_cost_runner_reversal_scale",
                "suffix": "wfHighCostOwRev1",
                "change": {"one_way_reversal_switch_units": 1.0},
                "required_applied": ["high_cost_near_zero_react"],
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 45.0,
                    "max_train_return_pct": 60.0,
                    "min_train_drawdown_pct": 19.0,
                    "max_train_drawdown_pct": 22.0,
                    "min_train_cost_drag_pct": 40.0,
                    "max_train_cost_drag_pct": 48.0,
                    "min_one_way_trim_per_add": 0.35,
                    "max_one_way_trim_per_add": 0.40,
                    "min_turnover_per_add": 2.40,
                    "max_turnover_per_add": 2.50,
                },
            }
        )
    if getattr(args, "high_cost_runner_tight_repair_replay_note", None):
        recipes.append(
            {
                "name": "high_cost_runner_tight_repair",
                "suffix": "wfHighCostRepairCut0.4",
                "change": {"repair_cut": 0.4},
                "required_applied": ["high_cost_runner_reversal_scale"],
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 45.0,
                    "max_train_return_pct": 60.0,
                    "min_train_drawdown_pct": 19.0,
                    "max_train_drawdown_pct": 22.0,
                    "min_train_cost_drag_pct": 40.0,
                    "max_train_cost_drag_pct": 48.0,
                    "min_one_way_trim_per_add": 0.35,
                    "max_one_way_trim_per_add": 0.40,
                    "min_turnover_per_add": 2.40,
                    "max_turnover_per_add": 2.50,
                },
            }
        )
    if getattr(args, "role_border_impulse_micro_replay_note", None):
        recipes.append(
            {
                "name": "role_border_impulse_micro",
                "suffix": "wfRoleBorderImpulse0.00005",
                "change": {
                    "one_way_impulse_probe_units": 0.00005,
                    "one_way_impulse_min_one_way_score": 3.5,
                    "one_way_impulse_min_score_diff": 5,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 65.0,
                    "max_train_return_pct": 80.0,
                    "min_train_drawdown_pct": 11.0,
                    "max_train_drawdown_pct": 13.0,
                    "min_train_cost_drag_pct": 30.0,
                    "max_train_cost_drag_pct": 40.0,
                    "min_one_way_trim_per_add": 0.34,
                    "max_one_way_trim_per_add": 0.39,
                    "min_turnover_per_add": 2.10,
                    "max_turnover_per_add": 2.20,
                },
            }
        )
    if getattr(args, "role_balance_impulse_micro_replay_note", None):
        recipes.append(
            {
                "name": "role_balance_impulse_micro",
                "suffix": "wfRoleBalanceImpulse0.0001",
                "change": {
                    "one_way_impulse_probe_units": 0.0001,
                    "one_way_impulse_min_one_way_score": 3.5,
                    "one_way_impulse_min_score_diff": 5,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 215.0,
                    "max_train_return_pct": 225.0,
                    "min_train_drawdown_pct": 14.0,
                    "max_train_drawdown_pct": 16.0,
                    "min_train_cost_drag_pct": 75.0,
                    "max_train_cost_drag_pct": 85.0,
                    "min_one_way_trim_per_add": 0.30,
                    "max_one_way_trim_per_add": 0.32,
                    "min_turnover_per_add": 2.39,
                    "max_turnover_per_add": 2.45,
                },
            }
        )
    if getattr(args, "low_return_soft_inventory_trim_replay_note", None):
        inventory_trim_fraction = min(
            max(float(getattr(args, "low_return_soft_inventory_trim_fraction", 0.20)), 0.0),
            1.0,
        )
        trim_suffix = f"{int(round(inventory_trim_fraction * 100)):03d}"
        recipes.append(
            {
                "name": "low_return_soft_inventory_trim",
                "suffix": f"wfEqSoftInvTrim8F{trim_suffix}",
                "change": {
                    "equity_soft_circuit_drawdown_pct": 8.0,
                    "equity_soft_circuit_cooldown_bars": 2880,
                    "equity_soft_circuit_size_mult": 0.25,
                    "equity_soft_circuit_force_flat": False,
                    "equity_soft_circuit_inventory_trim_fraction": inventory_trim_fraction,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 215.0,
                    "max_train_return_pct": 225.0,
                    "min_train_drawdown_pct": 14.0,
                    "max_train_drawdown_pct": 16.0,
                    "min_train_cost_drag_pct": 75.0,
                    "max_train_cost_drag_pct": 85.0,
                    "min_one_way_trim_per_add": 0.30,
                    "max_one_way_trim_per_add": 0.32,
                    "min_turnover_per_add": 2.39,
                    "max_turnover_per_add": 2.45,
                },
            }
        )
    if getattr(args, "low_return_impulse_noise_filter_replay_note", None):
        recipes.append(
            {
                "name": "low_return_impulse_noise_filter",
                "suffix": "wfLowRetOwImpNoiseOff",
                "change": {"one_way_impulse_probe_units": 0.0},
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "source_config_ranges": {
                        "one_way_impulse_probe_units": {"min": 0.015, "max": 0.025},
                    },
                    "min_train_return_pct": 60.0,
                    "max_train_return_pct": 64.0,
                    "min_train_drawdown_pct": 30.0,
                    "max_train_drawdown_pct": 32.0,
                    "min_train_cost_drag_pct": 36.0,
                    "max_train_cost_drag_pct": 38.0,
                    "min_one_way_trim_per_add": 0.39,
                    "max_one_way_trim_per_add": 0.41,
                    "min_turnover_per_add": 2.12,
                    "max_turnover_per_add": 2.14,
                },
            }
        )
    if getattr(args, "low_return_normal_short_base_throttle_replay_note", None):
        recipes.append(
            {
                "name": "low_return_normal_short_base_throttle",
                "suffix": "wfLowRetNormShortBaseM025Ext075-1.5",
                "required_applied": ["low_return_impulse_noise_filter"],
                "change": {
                    "event_risk_base_reduce_size_mult": 0.25,
                    "event_risk_base_reduce_min_extension_atr": 0.75,
                    "event_risk_base_reduce_max_extension_atr": 1.5,
                    "event_risk_base_reduce_side": "short",
                    "event_risk_base_reduce_contexts": ("normal",),
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "source_config_ranges": {
                        "one_way_impulse_probe_units": {"min": 0.015, "max": 0.025},
                    },
                    "min_train_return_pct": 60.0,
                    "max_train_return_pct": 64.0,
                    "min_train_drawdown_pct": 30.0,
                    "max_train_drawdown_pct": 32.0,
                    "min_train_cost_drag_pct": 36.0,
                    "max_train_cost_drag_pct": 38.0,
                    "min_one_way_trim_per_add": 0.39,
                    "max_one_way_trim_per_add": 0.41,
                    "min_turnover_per_add": 2.12,
                    "max_turnover_per_add": 2.14,
                },
            }
        )
    if getattr(args, "low_return_short_base_refine_replay_note", None):
        refine_max_extension = max(
            0.0,
            float(getattr(args, "low_return_short_base_refine_max_extension_atr", 1.0)),
        )
        refine_hold_bars = max(
            1,
            int(getattr(args, "low_return_short_base_refine_hold_bars", 96)),
        )
        recipes.append(
            {
                "name": "low_return_short_base_refine",
                "suffix": f"wfLowRetShortBaseExt0-{refine_max_extension:g}Hold{refine_hold_bars}",
                "required_applied": ["low_return_normal_short_base_throttle"],
                "change": {
                    "event_risk_base_reduce_size_mult": 0.25,
                    "event_risk_base_reduce_min_extension_atr": 0.0,
                    "event_risk_base_reduce_max_extension_atr": refine_max_extension,
                    "event_risk_base_reduce_side": "short",
                    "event_risk_base_reduce_contexts": ("normal", "hour_open"),
                    "max_hold_bars": refine_hold_bars,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "source_config_ranges": {
                        "one_way_impulse_probe_units": {"min": 0.015, "max": 0.025},
                    },
                    "min_train_return_pct": 60.0,
                    "max_train_return_pct": 64.0,
                    "min_train_drawdown_pct": 30.0,
                    "max_train_drawdown_pct": 32.0,
                    "min_train_cost_drag_pct": 36.0,
                    "max_train_cost_drag_pct": 38.0,
                    "min_one_way_trim_per_add": 0.39,
                    "max_one_way_trim_per_add": 0.41,
                    "min_turnover_per_add": 2.12,
                    "max_turnover_per_add": 2.14,
                },
            }
        )
    if getattr(args, "low_return_one_way_delay_replay_note", None):
        min_adverse_reaction = max(
            0.0,
            float(getattr(args, "low_return_one_way_delay_min_adverse_reaction", 0.10)),
        )
        recipes.append(
            {
                "name": "low_return_one_way_delay",
                "suffix": f"wfLowRetOwMin{min_adverse_reaction:g}",
                "required_applied": ["low_return_normal_short_base_throttle"],
                "change": {
                    "one_way_trim_min_adverse_reaction": min_adverse_reaction,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "source_config_ranges": {
                        "one_way_trim_min_adverse_reaction": {"min": 0.0, "max": 0.0},
                    },
                    "min_train_return_pct": 60.0,
                    "max_train_return_pct": 64.0,
                    "min_train_drawdown_pct": 30.0,
                    "max_train_drawdown_pct": 32.0,
                    "min_train_cost_drag_pct": 36.0,
                    "max_train_cost_drag_pct": 38.0,
                    "min_one_way_trim_per_add": 0.39,
                    "max_one_way_trim_per_add": 0.41,
                    "min_turnover_per_add": 2.12,
                    "max_turnover_per_add": 2.14,
                },
            }
        )
    if getattr(args, "mid_impulse_reaction_band_replay_note", None):
        mid_impulse_reaction_avg_band = max(
            0.05,
            float(getattr(args, "mid_impulse_reaction_avg_band", 1.15)),
        )
        recipes.append(
            {
                "name": "mid_impulse_reaction_band",
                "suffix": f"wfMidImpReactBand{mid_impulse_reaction_avg_band:g}",
                "required_applied": ["reaction_tune_mid_impulse"],
                "change": {
                    "reaction_avg_band": mid_impulse_reaction_avg_band,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "source_config_ranges": {
                        "reaction_avg_band": {"min": 0.94, "max": 0.96},
                    },
                    "min_train_return_pct": 215.0,
                    "max_train_return_pct": 222.0,
                    "min_train_drawdown_pct": 14.5,
                    "max_train_drawdown_pct": 15.5,
                    "min_train_cost_drag_pct": 70.0,
                    "max_train_cost_drag_pct": 74.0,
                    "min_one_way_trim_per_add": 0.33,
                    "max_one_way_trim_per_add": 0.35,
                    "min_turnover_per_add": 2.20,
                    "max_turnover_per_add": 2.26,
                },
            }
        )
    if getattr(args, "mid_impulse_noise_filter_replay_note", None):
        probe_units = max(
            0.0,
            float(getattr(args, "mid_impulse_noise_filter_probe_units", 0.0)),
        )
        recipes.append(
            {
                "name": "mid_impulse_noise_filter",
                "suffix": f"wfMidImpOwImp{probe_units:g}",
                "required_applied": ["mid_impulse_reaction_band"],
                "change": {
                    "one_way_impulse_probe_units": probe_units,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "source_config_ranges": {
                        "one_way_impulse_probe_units": {"min": 0.0, "max": 0.0},
                    },
                    "min_train_return_pct": 215.0,
                    "max_train_return_pct": 222.0,
                    "min_train_drawdown_pct": 14.5,
                    "max_train_drawdown_pct": 15.5,
                    "min_train_cost_drag_pct": 70.0,
                    "max_train_cost_drag_pct": 74.0,
                    "min_one_way_trim_per_add": 0.33,
                    "max_one_way_trim_per_add": 0.35,
                    "min_turnover_per_add": 2.20,
                    "max_turnover_per_add": 2.26,
                },
            }
        )
    if getattr(args, "mid_impulse_long_base_throttle_replay_note", None):
        max_extension = max(
            0.0,
            float(getattr(args, "mid_impulse_long_base_throttle_max_extension_atr", 0.75)),
        )
        recipes.append(
            {
                "name": "mid_impulse_long_base_throttle",
                "suffix": f"wfMidImpLongBaseM025Ext0-{max_extension:g}",
                "required_applied": ["mid_impulse_noise_filter"],
                "change": {
                    "event_risk_base_reduce_size_mult": 0.25,
                    "event_risk_base_reduce_min_extension_atr": 0.0,
                    "event_risk_base_reduce_max_extension_atr": max_extension,
                    "event_risk_base_reduce_side": "long",
                    "event_risk_base_reduce_contexts": ("normal", "hour_open"),
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "source_config_ranges": {
                        "event_risk_base_reduce_size_mult": {"min": 0.99, "max": 1.01},
                        "event_risk_base_reduce_max_extension_atr": {"min": 0.0, "max": 0.0},
                    },
                    "min_train_return_pct": 215.0,
                    "max_train_return_pct": 222.0,
                    "min_train_drawdown_pct": 14.5,
                    "max_train_drawdown_pct": 15.5,
                    "min_train_cost_drag_pct": 70.0,
                    "max_train_cost_drag_pct": 74.0,
                    "min_one_way_trim_per_add": 0.33,
                    "max_one_way_trim_per_add": 0.35,
                    "min_turnover_per_add": 2.20,
                    "max_turnover_per_add": 2.26,
                },
            }
        )
    if getattr(args, "low_return_selective_impulse_replay_note", None):
        selective_probe_units = max(
            0.0,
            float(getattr(args, "low_return_selective_impulse_probe_units", 0.20)),
        )
        selective_min_one_way_score = max(
            0.0,
            float(getattr(args, "low_return_selective_impulse_min_one_way_score", 4.0)),
        )
        selective_min_score_diff = max(
            0,
            int(getattr(args, "low_return_selective_impulse_min_score_diff", 5)),
        )
        recipes.append(
            {
                "name": "low_return_selective_impulse_probe",
                "suffix": (
                    f"wfLowRetOwImp{selective_probe_units:g}"
                    f"Score{selective_min_one_way_score:g}D{selective_min_score_diff}"
                ),
                "required_applied": [
                    "role_balance_impulse_micro",
                    "low_return_soft_inventory_trim",
                ],
                "change": {
                    "one_way_impulse_probe_units": selective_probe_units,
                    "one_way_impulse_min_one_way_score": selective_min_one_way_score,
                    "one_way_impulse_min_score_diff": selective_min_score_diff,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 215.0,
                    "max_train_return_pct": 225.0,
                    "min_train_drawdown_pct": 14.0,
                    "max_train_drawdown_pct": 16.0,
                    "min_train_cost_drag_pct": 75.0,
                    "max_train_cost_drag_pct": 85.0,
                    "min_one_way_trim_per_add": 0.30,
                    "max_one_way_trim_per_add": 0.32,
                    "min_turnover_per_add": 2.39,
                    "max_turnover_per_add": 2.45,
                },
            }
        )
    if getattr(args, "low_return_reaction_band_replay_note", None):
        low_return_reaction_avg_band = max(
            0.05,
            float(getattr(args, "low_return_reaction_avg_band", 1.15)),
        )
        recipes.append(
            {
                "name": "low_return_reaction_band",
                "suffix": f"wfLowRetReactBand{low_return_reaction_avg_band:g}",
                "required_applied": [
                    "role_balance_impulse_micro",
                    "low_return_soft_inventory_trim",
                    "low_return_selective_impulse_probe",
                ],
                "change": {
                    "reaction_avg_band": low_return_reaction_avg_band,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 215.0,
                    "max_train_return_pct": 225.0,
                    "min_train_drawdown_pct": 14.0,
                    "max_train_drawdown_pct": 16.0,
                    "min_train_cost_drag_pct": 75.0,
                    "max_train_cost_drag_pct": 85.0,
                    "min_one_way_trim_per_add": 0.30,
                    "max_one_way_trim_per_add": 0.32,
                    "min_turnover_per_add": 2.39,
                    "max_turnover_per_add": 2.45,
                },
            }
        )
    if getattr(args, "fast_defense_one_way_delay_replay_note", None):
        min_adverse_reaction = max(
            0.0,
            float(getattr(args, "fast_defense_one_way_delay_min_adverse_reaction", 0.50)),
        )
        max_defensive_cooldown = max(
            0,
            int(getattr(args, "fast_defense_one_way_delay_max_defensive_cooldown_bars", 100)),
        )
        recipes.append(
            {
                "name": "fast_defense_one_way_delay",
                "suffix": f"wfFastDefOwMin{min_adverse_reaction:g}",
                "required_applied": ["low_return_soft_inventory_trim"],
                "change": {
                    "one_way_trim_min_adverse_reaction": min_adverse_reaction,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "source_config_ranges": {
                        "defensive_trim_cooldown_bars": {
                            "min": 0.0,
                            "max": float(max_defensive_cooldown),
                        },
                    },
                    "min_train_return_pct": 215.0,
                    "max_train_return_pct": 225.0,
                    "min_train_drawdown_pct": 14.0,
                    "max_train_drawdown_pct": 16.0,
                    "min_train_cost_drag_pct": 75.0,
                    "max_train_cost_drag_pct": 85.0,
                    "min_one_way_trim_per_add": 0.30,
                    "max_one_way_trim_per_add": 0.32,
                    "min_turnover_per_add": 2.39,
                    "max_turnover_per_add": 2.45,
                },
            }
        )
    if getattr(args, "low_return_stress_base_throttle_replay_note", None):
        recipes.append(
            {
                "name": "low_return_stress_base_throttle",
                "suffix": "wfLowRetStressBaseResetM025Ext0",
                "required_applied": [
                    "event_risk_base_throttle",
                    "role_balance_impulse_micro",
                    "low_return_soft_inventory_trim",
                    "low_return_selective_impulse_probe",
                    "low_return_reaction_band",
                    "fast_defense_one_way_delay",
                ],
                "change": {
                    "defensive_trim_cooldown_bars": 12960,
                    "repair_cut": 0.9,
                    "reaction_avg_band": 0.95,
                    "one_way_trim_min_adverse_reaction": 0.0,
                    "equity_soft_circuit_drawdown_pct": 0.0,
                    "equity_soft_circuit_cooldown_bars": 0,
                    "equity_soft_circuit_size_mult": 1.0,
                    "equity_soft_circuit_force_flat": False,
                    "equity_soft_circuit_inventory_trim_fraction": 0.0,
                    "one_way_reversal_switch_units": 0.05,
                    "one_way_impulse_probe_units": 0.0,
                    "one_way_impulse_min_one_way_score": 2.35,
                    "one_way_impulse_min_score_diff": 3,
                    "event_risk_base_reduce_size_mult": 0.25,
                    "event_risk_base_reduce_min_extension_atr": 0.0,
                    "event_risk_base_reduce_side": "short",
                    "event_risk_base_reduce_contexts": ("normal", "hour_open"),
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 215.0,
                    "max_train_return_pct": 225.0,
                    "min_train_drawdown_pct": 14.0,
                    "max_train_drawdown_pct": 15.2,
                    "min_train_cost_drag_pct": 78.0,
                    "max_train_cost_drag_pct": 84.0,
                    "min_one_way_trim_per_add": 0.29,
                    "max_one_way_trim_per_add": 0.33,
                    "min_turnover_per_add": 2.38,
                    "max_turnover_per_add": 2.45,
                },
            }
        )
    if getattr(args, "low_return_single_unit_compression_replay_note", None):
        compression_units = min(
            max(float(getattr(args, "low_return_single_unit_compression_units", 0.50)), 0.05),
            1.0,
        )
        compression_suffix = f"{int(round(compression_units * 100)):03d}"
        recipes.append(
            {
                "name": "low_return_single_unit_compression",
                "suffix": f"wfLowRetSingleU{compression_suffix}",
                "required_applied": ["low_return_stress_base_throttle"],
                "change": {
                    "max_possible_units": compression_units,
                    "base_max_units": compression_units,
                    "battle_units": compression_units,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 215.0,
                    "max_train_return_pct": 225.0,
                    "min_train_drawdown_pct": 14.0,
                    "max_train_drawdown_pct": 15.2,
                    "min_train_cost_drag_pct": 78.0,
                    "max_train_cost_drag_pct": 84.0,
                    "min_one_way_trim_per_add": 0.29,
                    "max_one_way_trim_per_add": 0.33,
                    "min_turnover_per_add": 2.38,
                    "max_turnover_per_add": 2.45,
                },
            }
        )
    if getattr(args, "low_return_stress_reaction_band_restore_replay_note", None):
        restore_avg_band = max(
            0.05,
            float(getattr(args, "low_return_stress_reaction_band_restore_avg_band", 1.15)),
        )
        recipes.append(
            {
                "name": "low_return_stress_reaction_band_restore",
                "suffix": f"wfLowRetStressReactBand{restore_avg_band:g}",
                "required_applied": [
                    "low_return_stress_base_throttle",
                    "low_return_single_unit_compression",
                ],
                "change": {
                    "reaction_avg_band": restore_avg_band,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 215.0,
                    "max_train_return_pct": 225.0,
                    "min_train_drawdown_pct": 14.0,
                    "max_train_drawdown_pct": 15.2,
                    "min_train_cost_drag_pct": 78.0,
                    "max_train_cost_drag_pct": 84.0,
                    "min_one_way_trim_per_add": 0.29,
                    "max_one_way_trim_per_add": 0.33,
                    "min_turnover_per_add": 2.38,
                    "max_turnover_per_add": 2.45,
                },
            }
        )
    if getattr(args, "low_return_repair_stop_replay_note", None):
        repair_stop_value = max(
            0.0,
            float(getattr(args, "low_return_repair_stop_value", 0.90)),
        )
        reaction_trim_trigger = max(
            0.05,
            float(getattr(args, "low_return_repair_stop_reaction_trim_trigger", 0.60)),
        )
        recipes.append(
            {
                "name": "low_return_repair_stop",
                "suffix": (
                    f"wfLowRetRepairStop{repair_stop_value:g}"
                    f"RTrim{reaction_trim_trigger:g}"
                ),
                "required_applied": ["low_return_stress_reaction_band_restore"],
                "change": {
                    "repair_stop": repair_stop_value,
                    "reaction_trim_trigger": reaction_trim_trigger,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "min_train_return_pct": 215.0,
                    "max_train_return_pct": 225.0,
                    "min_train_drawdown_pct": 14.0,
                    "max_train_drawdown_pct": 15.2,
                    "min_train_cost_drag_pct": 78.0,
                    "max_train_cost_drag_pct": 84.0,
                    "min_one_way_trim_per_add": 0.29,
                    "max_one_way_trim_per_add": 0.33,
                    "min_turnover_per_add": 2.38,
                    "max_turnover_per_add": 2.45,
                },
            }
        )
    if getattr(args, "low_return_repair_stop_tighten_replay_note", None):
        tight_repair_stop = max(
            0.0,
            float(getattr(args, "low_return_repair_stop_tighten_value", 0.70)),
        )
        recipes.append(
            {
                "name": "low_return_repair_stop_tighten",
                "suffix": f"wfLowRetRepairStopTight{tight_repair_stop:g}",
                "required_applied": ["low_return_repair_stop"],
                "change": {"repair_stop": tight_repair_stop},
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "source_config_ranges": {
                        "repair_stop": {"min": 1.19, "max": 1.21},
                    },
                    "min_train_return_pct": 215.0,
                    "max_train_return_pct": 225.0,
                    "min_train_drawdown_pct": 14.0,
                    "max_train_drawdown_pct": 15.2,
                    "min_train_cost_drag_pct": 78.0,
                    "max_train_cost_drag_pct": 84.0,
                    "min_one_way_trim_per_add": 0.29,
                    "max_one_way_trim_per_add": 0.33,
                    "min_turnover_per_add": 2.38,
                    "max_turnover_per_add": 2.45,
                },
            }
        )
    if getattr(args, "low_return_strong_impulse_replay_note", None):
        strong_probe_units = max(
            0.0,
            float(getattr(args, "low_return_strong_impulse_probe_units", 0.50)),
        )
        strong_min_one_way_score = max(
            0.0,
            float(getattr(args, "low_return_strong_impulse_min_one_way_score", 4.0)),
        )
        strong_min_score_diff = max(
            0,
            int(getattr(args, "low_return_strong_impulse_min_score_diff", 3)),
        )
        strong_cooldown_bars = max(
            0,
            int(getattr(args, "low_return_strong_impulse_cooldown_bars", 48)),
        )
        strong_max_extension_atr = max(
            0.0,
            float(getattr(args, "low_return_strong_impulse_max_extension_atr", 2.75)),
        )
        strong_probe_take_profit = max(
            0.05,
            float(getattr(args, "low_return_strong_impulse_probe_take_profit_reaction", 0.75)),
        )
        recipes.append(
            {
                "name": "low_return_strong_impulse_probe",
                "suffix": (
                    f"wfLowRetStrongOwImp{strong_probe_units:g}"
                    f"Score{strong_min_one_way_score:g}D{strong_min_score_diff}"
                    f"Ext{strong_max_extension_atr:g}Tp{strong_probe_take_profit:g}"
                ),
                "required_applied": ["low_return_repair_stop_tighten"],
                "change": {
                    "one_way_impulse_probe_units": strong_probe_units,
                    "one_way_impulse_min_one_way_score": strong_min_one_way_score,
                    "one_way_impulse_min_score_diff": strong_min_score_diff,
                    "one_way_impulse_cooldown_bars": strong_cooldown_bars,
                    "one_way_impulse_max_extension_atr": strong_max_extension_atr,
                    "probe_take_profit_reaction": strong_probe_take_profit,
                },
                "gate": {
                    "min_source_max_units": 1.0,
                    "max_source_max_units": 1.0,
                    "source_config_ranges": {
                        "repair_stop": {"min": 1.19, "max": 1.21},
                        "one_way_impulse_probe_units": {"min": 0.0, "max": 0.0},
                        "one_way_impulse_max_extension_atr": {"min": 2.74, "max": 2.76},
                        "probe_take_profit_reaction": {"min": 0.64, "max": 0.66},
                    },
                    "min_train_return_pct": 215.0,
                    "max_train_return_pct": 225.0,
                    "min_train_drawdown_pct": 14.0,
                    "max_train_drawdown_pct": 15.2,
                    "min_train_cost_drag_pct": 78.0,
                    "max_train_cost_drag_pct": 84.0,
                    "min_one_way_trim_per_add": 0.29,
                    "max_one_way_trim_per_add": 0.33,
                    "min_turnover_per_add": 2.38,
                    "max_turnover_per_add": 2.45,
                },
            }
        )
    if getattr(args, "role_balance_impulse_micro_replay_note", None):
        recipes.append(
            {
                "name": "role_balance_impulse_micro_current",
                "suffix": "wfRoleBalanceCurImpulse0.0001",
                "change": {
                    "one_way_impulse_probe_units": 0.0001,
                    "one_way_impulse_min_one_way_score": 3.5,
                    "one_way_impulse_min_score_diff": 5,
                },
                "gate": low_return_current_gate,
            }
        )
    if (
        low_return_current_chain_enabled
        and getattr(args, "event_risk_base_throttle_replay_note", None)
    ):
        recipes.append(
            {
                "name": "event_risk_base_throttle_current",
                "suffix": "wfCurEventBaseShortM025Ext0",
                "change": {
                    "event_risk_base_reduce_size_mult": 0.25,
                    "event_risk_base_reduce_min_extension_atr": 0.0,
                    "event_risk_base_reduce_side": "short",
                    "event_risk_base_reduce_contexts": ("normal", "hour_open"),
                },
                "gate": low_return_current_gate,
            }
        )
    if (
        low_return_current_chain_enabled
        and getattr(args, "low_return_soft_inventory_trim_replay_note", None)
    ):
        inventory_trim_fraction = min(
            max(float(getattr(args, "low_return_soft_inventory_trim_fraction", 0.20)), 0.0),
            1.0,
        )
        trim_suffix = f"{int(round(inventory_trim_fraction * 100)):03d}"
        recipes.append(
            {
                "name": "low_return_soft_inventory_trim_current",
                "suffix": f"wfCurEqSoftInvTrim8F{trim_suffix}",
                "change": {
                    "equity_soft_circuit_drawdown_pct": 8.0,
                    "equity_soft_circuit_cooldown_bars": 2880,
                    "equity_soft_circuit_size_mult": 0.25,
                    "equity_soft_circuit_force_flat": False,
                    "equity_soft_circuit_inventory_trim_fraction": inventory_trim_fraction,
                },
                "gate": low_return_current_gate,
            }
        )
    if (
        low_return_current_chain_enabled
        and getattr(args, "low_return_selective_impulse_replay_note", None)
    ):
        selective_probe_units = max(
            0.0,
            float(getattr(args, "low_return_selective_impulse_probe_units", 0.20)),
        )
        selective_min_one_way_score = max(
            0.0,
            float(getattr(args, "low_return_selective_impulse_min_one_way_score", 4.0)),
        )
        selective_min_score_diff = max(
            0,
            int(getattr(args, "low_return_selective_impulse_min_score_diff", 5)),
        )
        recipes.append(
            {
                "name": "low_return_selective_impulse_probe_current",
                "suffix": (
                    f"wfCurLowRetOwImp{selective_probe_units:g}"
                    f"Score{selective_min_one_way_score:g}D{selective_min_score_diff}"
                ),
                "required_applied": [
                    "role_balance_impulse_micro_current",
                    "low_return_soft_inventory_trim_current",
                ],
                "change": {
                    "one_way_impulse_probe_units": selective_probe_units,
                    "one_way_impulse_min_one_way_score": selective_min_one_way_score,
                    "one_way_impulse_min_score_diff": selective_min_score_diff,
                },
                "gate": low_return_current_gate,
            }
        )
    if (
        low_return_current_chain_enabled
        and getattr(args, "low_return_reaction_band_replay_note", None)
    ):
        low_return_reaction_avg_band = max(
            0.05,
            float(getattr(args, "low_return_reaction_avg_band", 1.15)),
        )
        recipes.append(
            {
                "name": "low_return_reaction_band_current",
                "suffix": f"wfCurLowRetReactBand{low_return_reaction_avg_band:g}",
                "required_applied": [
                    "role_balance_impulse_micro_current",
                    "low_return_soft_inventory_trim_current",
                    "low_return_selective_impulse_probe_current",
                ],
                "change": {
                    "reaction_avg_band": low_return_reaction_avg_band,
                },
                "gate": low_return_current_gate,
            }
        )
    if (
        low_return_current_chain_enabled
        and getattr(args, "fast_defense_one_way_delay_replay_note", None)
    ):
        min_adverse_reaction = max(
            0.0,
            float(getattr(args, "fast_defense_one_way_delay_min_adverse_reaction", 0.50)),
        )
        recipes.append(
            {
                "name": "fast_defense_one_way_delay_current",
                "suffix": f"wfCurFastDefOwMin{min_adverse_reaction:g}",
                "required_applied": ["low_return_soft_inventory_trim_current"],
                "change": {
                    "one_way_trim_min_adverse_reaction": min_adverse_reaction,
                },
                "gate": low_return_current_gate,
            }
        )
    if (
        low_return_current_chain_enabled
        and getattr(args, "low_return_stress_base_throttle_replay_note", None)
    ):
        recipes.append(
            {
                "name": "low_return_stress_base_throttle_current",
                "suffix": "wfCurLowRetStressBaseM025Ext0",
                "required_applied": [
                    "event_risk_base_throttle_current",
                    "role_balance_impulse_micro_current",
                    "low_return_soft_inventory_trim_current",
                    "low_return_selective_impulse_probe_current",
                    "low_return_reaction_band_current",
                    "fast_defense_one_way_delay_current",
                ],
                "change": {
                    "defensive_trim_cooldown_bars": 12960,
                    "repair_cut": 0.9,
                    "reaction_avg_band": 0.95,
                    "one_way_trim_min_adverse_reaction": 0.0,
                    "equity_soft_circuit_drawdown_pct": 0.0,
                    "equity_soft_circuit_cooldown_bars": 0,
                    "equity_soft_circuit_size_mult": 1.0,
                    "equity_soft_circuit_force_flat": False,
                    "equity_soft_circuit_inventory_trim_fraction": 0.0,
                    "one_way_reversal_switch_units": 0.05,
                    "one_way_impulse_probe_units": 0.0,
                    "one_way_impulse_min_one_way_score": 2.35,
                    "one_way_impulse_min_score_diff": 3,
                    "event_risk_base_reduce_size_mult": 0.25,
                    "event_risk_base_reduce_min_extension_atr": 0.0,
                    "event_risk_base_reduce_side": "short",
                    "event_risk_base_reduce_contexts": ("normal", "hour_open"),
                },
                "gate": low_return_current_gate,
            }
        )
    if (
        low_return_current_chain_enabled
        and getattr(args, "low_return_single_unit_compression_replay_note", None)
    ):
        compression_units = min(
            max(float(getattr(args, "low_return_single_unit_compression_units", 0.50)), 0.05),
            1.0,
        )
        compression_suffix = f"{int(round(compression_units * 100)):03d}"
        recipes.append(
            {
                "name": "low_return_single_unit_compression_current",
                "suffix": f"wfCurLowRetSingleU{compression_suffix}",
                "required_applied": ["low_return_stress_base_throttle_current"],
                "change": {
                    "max_possible_units": compression_units,
                    "base_max_units": compression_units,
                    "battle_units": compression_units,
                },
                "gate": low_return_current_gate,
            }
        )
    if (
        low_return_current_chain_enabled
        and getattr(args, "low_return_stress_reaction_band_restore_replay_note", None)
    ):
        restore_avg_band = max(
            0.05,
            float(getattr(args, "low_return_stress_reaction_band_restore_avg_band", 1.15)),
        )
        recipes.append(
            {
                "name": "low_return_stress_reaction_band_restore_current",
                "suffix": f"wfCurLowRetStressReactBand{restore_avg_band:g}",
                "required_applied": [
                    "low_return_stress_base_throttle_current",
                    "low_return_single_unit_compression_current",
                ],
                "change": {
                    "reaction_avg_band": restore_avg_band,
                },
                "gate": low_return_current_gate,
            }
        )
    return recipes


def _train_max_role_add_share(train_result: dict[str, Any]) -> float:
    diagnostics = dict(train_result.get("event_diagnostics") or {})
    max_role_add_share = diagnostics.get("max_role_add_share")
    if max_role_add_share is not None:
        return float(max_role_add_share or 0.0)
    add_by_role = {
        str(role): int(count)
        for role, count in dict(diagnostics.get("add_by_role") or {}).items()
        if str(role) not in {"", "unknown"}
    }
    total = sum(add_by_role.values())
    if total <= 0:
        return 0.0
    return max(add_by_role.values()) / max(total, 1)


def _train_role_share(train_result: dict[str, Any], role: str) -> float:
    diagnostics = dict(train_result.get("event_diagnostics") or {})
    add_role_share = dict(diagnostics.get("add_role_share") or {})
    if role in add_role_share:
        return float(add_role_share.get(role) or 0.0)
    add_by_role = {
        str(item_role): int(count)
        for item_role, count in dict(diagnostics.get("add_by_role") or {}).items()
        if str(item_role) not in {"", "unknown"}
    }
    total = sum(add_by_role.values())
    if total <= 0:
        return 0.0
    return float(add_by_role.get(role, 0)) / max(total, 1)


def _train_dominant_add_role(train_result: dict[str, Any]) -> str:
    diagnostics = dict(train_result.get("event_diagnostics") or {})
    dominant = str(diagnostics.get("dominant_add_role") or "")
    if dominant and dominant != "none":
        return dominant
    add_by_role = {
        str(role): int(count)
        for role, count in dict(diagnostics.get("add_by_role") or {}).items()
        if str(role) not in {"", "unknown"}
    }
    if not add_by_role:
        return "none"
    return max(add_by_role.items(), key=lambda item: (int(item[1]), str(item[0])))[0]


def _train_state_after_selection_allowed(
    train_result: dict[str, Any],
    args: argparse.Namespace,
    *,
    prefix: str,
) -> bool:
    source_config = dict(train_result.get("config") or {})
    source_max_units = float(source_config.get("max_possible_units") or 0.0)
    if not _range_allowed(
        source_max_units,
        getattr(args, f"{prefix}_min_source_max_units"),
        getattr(args, f"{prefix}_max_source_max_units"),
    ):
        return False
    train_return = float(train_result.get("total_return_pct") or 0.0)
    if not _range_allowed(
        train_return,
        getattr(args, f"{prefix}_min_train_return_pct"),
        getattr(args, f"{prefix}_max_train_return_pct"),
    ):
        return False
    train_drawdown = float(train_result.get("max_drawdown_pct") or 0.0)
    if not _range_allowed(
        train_drawdown,
        getattr(args, f"{prefix}_min_train_drawdown_pct"),
        getattr(args, f"{prefix}_max_train_drawdown_pct"),
    ):
        return False
    train_cost_drag = float(train_result.get("estimated_cost_drag_pct") or 0.0)
    if not _range_allowed(
        train_cost_drag,
        getattr(args, f"{prefix}_min_train_cost_drag_pct"),
        getattr(args, f"{prefix}_max_train_cost_drag_pct"),
    ):
        return False
    trim_ratio = _train_ratio(train_result, "one_way_forced_trim_per_add")
    if not _positive_range_allowed(
        trim_ratio,
        max(0.0, float(getattr(args, f"{prefix}_min_one_way_trim_per_add"))),
        max(0.0, float(getattr(args, f"{prefix}_max_one_way_trim_per_add"))),
    ):
        return False
    turnover_ratio = _train_ratio(train_result, "turnover_events_per_add")
    if not _positive_range_allowed(
        turnover_ratio,
        max(0.0, float(getattr(args, f"{prefix}_min_turnover_per_add"))),
        max(0.0, float(getattr(args, f"{prefix}_max_turnover_per_add"))),
    ):
        return False
    return True


def _battle_restore_after_selection_allowed(
    train_result: dict[str, Any],
    args: argparse.Namespace,
) -> bool:
    if not _train_state_after_selection_allowed(
        train_result,
        args,
        prefix="battle_restore_after_selection",
    ):
        return False
    battle_ratio = _train_ratio(train_result, "battle_add_per_add")
    if not _positive_range_allowed(
        battle_ratio,
        max(0.0, float(args.battle_restore_after_selection_min_battle_add_per_add)),
        max(0.0, float(args.battle_restore_after_selection_max_battle_add_per_add)),
    ):
        return False
    max_role_share = _train_max_role_add_share(train_result)
    if not _positive_range_allowed(
        max_role_share,
        max(0.0, float(args.battle_restore_after_selection_min_max_role_add_share)),
        max(0.0, float(args.battle_restore_after_selection_max_max_role_add_share)),
    ):
        return False
    diagnostics = dict(train_result.get("event_diagnostics") or {})
    add_events = int(diagnostics.get("add_events") or train_result.get("trade_like_events") or 0)
    min_add_events = max(0, int(args.battle_restore_after_selection_min_add_events))
    max_add_events = max(0, int(args.battle_restore_after_selection_max_add_events))
    if min_add_events > 0 and add_events < min_add_events:
        return False
    if max_add_events > 0 and add_events > max_add_events:
        return False
    return True


def _equity_soft_circuit_after_selection_allowed(
    train_result: dict[str, Any],
    args: argparse.Namespace,
) -> bool:
    if bool(args.equity_soft_circuit_after_selection_require_base_reduce) and not _base_reduce_after_selection_allowed(
        train_result,
        args,
    ):
        return False
    train_return = float(train_result.get("total_return_pct") or 0.0)
    if not _range_allowed(
        train_return,
        args.equity_soft_circuit_after_selection_min_train_return_pct,
        args.equity_soft_circuit_after_selection_max_train_return_pct,
    ):
        return False
    train_drawdown = float(train_result.get("max_drawdown_pct") or 0.0)
    if not _range_allowed(
        train_drawdown,
        args.equity_soft_circuit_after_selection_min_train_drawdown_pct,
        args.equity_soft_circuit_after_selection_max_train_drawdown_pct,
    ):
        return False
    trim_ratio = _train_ratio(train_result, "one_way_forced_trim_per_add")
    if not _positive_range_allowed(
        trim_ratio,
        max(0.0, float(args.equity_soft_circuit_after_selection_min_one_way_trim_per_add)),
        max(0.0, float(args.equity_soft_circuit_after_selection_max_one_way_trim_per_add)),
    ):
        return False
    return True


def _equity_soft_sizer_after_selection_allowed(
    train_result: dict[str, Any],
    args: argparse.Namespace,
    *,
    prefix: str = "equity_soft_sizer_after_selection",
) -> bool:
    source_config = dict(train_result.get("config") or {})
    source_max_units = float(source_config.get("max_possible_units") or 0.0)
    if not _range_allowed(
        source_max_units,
        getattr(args, f"{prefix}_min_source_max_units"),
        getattr(args, f"{prefix}_max_source_max_units"),
    ):
        return False
    train_return = float(train_result.get("total_return_pct") or 0.0)
    if not _range_allowed(
        train_return,
        getattr(args, f"{prefix}_min_train_return_pct"),
        getattr(args, f"{prefix}_max_train_return_pct"),
    ):
        return False
    train_drawdown = float(train_result.get("max_drawdown_pct") or 0.0)
    if not _range_allowed(
        train_drawdown,
        getattr(args, f"{prefix}_min_train_drawdown_pct"),
        getattr(args, f"{prefix}_max_train_drawdown_pct"),
    ):
        return False
    train_cost_drag = float(train_result.get("estimated_cost_drag_pct") or 0.0)
    if not _range_allowed(
        train_cost_drag,
        getattr(args, f"{prefix}_min_train_cost_drag_pct"),
        getattr(args, f"{prefix}_max_train_cost_drag_pct"),
    ):
        return False
    trim_ratio = _train_ratio(train_result, "one_way_forced_trim_per_add")
    if not _positive_range_allowed(
        trim_ratio,
        max(0.0, float(getattr(args, f"{prefix}_min_one_way_trim_per_add"))),
        max(0.0, float(getattr(args, f"{prefix}_max_one_way_trim_per_add"))),
    ):
        return False
    turnover_ratio = _train_ratio(train_result, "turnover_events_per_add")
    if not _positive_range_allowed(
        turnover_ratio,
        max(0.0, float(getattr(args, f"{prefix}_min_turnover_per_add"))),
        max(0.0, float(getattr(args, f"{prefix}_max_turnover_per_add"))),
    ):
        return False
    return True


def _one_way_reversal_after_selection_alt_allowed(
    train_result: dict[str, Any],
    args: argparse.Namespace,
) -> bool:
    alt_gate_enabled = any(
        value is not None
        for value in (
            args.one_way_reversal_after_selection_alt_min_train_return_pct,
            args.one_way_reversal_after_selection_alt_max_train_return_pct,
            args.one_way_reversal_after_selection_alt_min_train_drawdown_pct,
            args.one_way_reversal_after_selection_alt_max_train_drawdown_pct,
            args.one_way_reversal_after_selection_alt_min_train_cost_drag_pct,
            args.one_way_reversal_after_selection_alt_max_train_cost_drag_pct,
        )
    ) or any(
        max(0.0, float(value)) > 0.0
        for value in (
            args.one_way_reversal_after_selection_alt_min_one_way_trim_per_add,
            args.one_way_reversal_after_selection_alt_max_one_way_trim_per_add,
            args.one_way_reversal_after_selection_alt_min_turnover_per_add,
            args.one_way_reversal_after_selection_alt_max_turnover_per_add,
            args.one_way_reversal_after_selection_alt_min_reaction_trim_per_remove,
            args.one_way_reversal_after_selection_alt_max_reaction_trim_per_remove,
        )
    )
    if not alt_gate_enabled:
        return False
    train_return = float(train_result.get("total_return_pct") or 0.0)
    if not _range_allowed(
        train_return,
        args.one_way_reversal_after_selection_alt_min_train_return_pct,
        args.one_way_reversal_after_selection_alt_max_train_return_pct,
    ):
        return False
    train_drawdown = float(train_result.get("max_drawdown_pct") or 0.0)
    if not _range_allowed(
        train_drawdown,
        args.one_way_reversal_after_selection_alt_min_train_drawdown_pct,
        args.one_way_reversal_after_selection_alt_max_train_drawdown_pct,
    ):
        return False
    train_cost_drag = float(train_result.get("estimated_cost_drag_pct") or 0.0)
    if not _range_allowed(
        train_cost_drag,
        args.one_way_reversal_after_selection_alt_min_train_cost_drag_pct,
        args.one_way_reversal_after_selection_alt_max_train_cost_drag_pct,
    ):
        return False
    trim_ratio = _train_ratio(train_result, "one_way_forced_trim_per_add")
    if not _positive_range_allowed(
        trim_ratio,
        max(0.0, float(args.one_way_reversal_after_selection_alt_min_one_way_trim_per_add)),
        max(0.0, float(args.one_way_reversal_after_selection_alt_max_one_way_trim_per_add)),
    ):
        return False
    turnover_ratio = _train_ratio(train_result, "turnover_events_per_add")
    if not _positive_range_allowed(
        turnover_ratio,
        max(0.0, float(args.one_way_reversal_after_selection_alt_min_turnover_per_add)),
        max(0.0, float(args.one_way_reversal_after_selection_alt_max_turnover_per_add)),
    ):
        return False
    reaction_trim_ratio = _train_ratio(train_result, "reaction_trim_per_remove")
    if not _positive_range_allowed(
        reaction_trim_ratio,
        max(0.0, float(args.one_way_reversal_after_selection_alt_min_reaction_trim_per_remove)),
        max(0.0, float(args.one_way_reversal_after_selection_alt_max_reaction_trim_per_remove)),
    ):
        return False
    return True


def _one_way_reversal_after_selection_allowed(
    train_result: dict[str, Any],
    args: argparse.Namespace,
) -> bool:
    primary_allowed = True
    train_return = float(train_result.get("total_return_pct") or 0.0)
    min_train_return = args.one_way_reversal_after_selection_min_train_return_pct
    if min_train_return is not None and train_return < float(min_train_return):
        primary_allowed = False
    max_train_return = args.one_way_reversal_after_selection_max_train_return_pct
    if max_train_return is not None and train_return > float(max_train_return):
        primary_allowed = False
    train_drawdown = float(train_result.get("max_drawdown_pct") or 0.0)
    min_train_drawdown = args.one_way_reversal_after_selection_min_train_drawdown_pct
    if min_train_drawdown is not None and train_drawdown < float(min_train_drawdown):
        primary_allowed = False
    max_train_drawdown = args.one_way_reversal_after_selection_max_train_drawdown_pct
    if max_train_drawdown is not None and train_drawdown > float(max_train_drawdown):
        primary_allowed = False
    diagnostics = dict(train_result.get("event_diagnostics") or {})
    ratios = dict(diagnostics.get("ratios") or {})
    trim_ratio = float(ratios.get("one_way_forced_trim_per_add") or 0.0)
    min_trim_ratio = max(0.0, float(args.one_way_reversal_after_selection_min_one_way_trim_per_add))
    if min_trim_ratio > 0.0 and trim_ratio < min_trim_ratio:
        primary_allowed = False
    max_trim_ratio = max(0.0, float(args.one_way_reversal_after_selection_max_one_way_trim_per_add))
    if max_trim_ratio > 0.0 and trim_ratio > max_trim_ratio:
        primary_allowed = False
    if primary_allowed:
        return True
    return _one_way_reversal_after_selection_alt_allowed(train_result, args)


def _one_way_reversal_after_selection_weak_allowed(
    train_result: dict[str, Any],
    args: argparse.Namespace,
) -> bool:
    if args.one_way_reversal_after_selection_weak_switch_units is None:
        return False
    train_return = float(train_result.get("total_return_pct") or 0.0)
    if not _range_allowed(
        train_return,
        args.one_way_reversal_after_selection_weak_min_train_return_pct,
        args.one_way_reversal_after_selection_weak_max_train_return_pct,
    ):
        return False
    train_drawdown = float(train_result.get("max_drawdown_pct") or 0.0)
    if not _range_allowed(
        train_drawdown,
        args.one_way_reversal_after_selection_weak_min_train_drawdown_pct,
        args.one_way_reversal_after_selection_weak_max_train_drawdown_pct,
    ):
        return False
    trim_ratio = _train_ratio(train_result, "one_way_forced_trim_per_add")
    if not _positive_range_allowed(
        trim_ratio,
        max(0.0, float(args.one_way_reversal_after_selection_weak_min_one_way_trim_per_add)),
        max(0.0, float(args.one_way_reversal_after_selection_weak_max_one_way_trim_per_add)),
    ):
        return False
    return True


def _apply_base_reduce_overlay(config: MarketStateConfig, args: argparse.Namespace) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    if args.base_entry_max_extension_atr is not None:
        value = max(0.0, float(args.base_entry_max_extension_atr))
        updates["base_entry_max_extension_atr"] = value
        suffix_parts.append(f"wfBaseExt{value:g}")
    if args.base_entry_max_extension_side:
        updates["base_entry_max_extension_side"] = str(args.base_entry_max_extension_side)
        suffix_parts.append(f"wfBaseExtSide{args.base_entry_max_extension_side}")
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
    if args.base_entry_reduce_min_trend_strength is not None:
        value = max(0.0, float(args.base_entry_reduce_min_trend_strength))
        updates["base_entry_reduce_min_trend_strength"] = value
        suffix_parts.append(f"wfBaseReduceMinTrend{value:g}")
    if args.base_entry_reduce_side:
        updates["base_entry_reduce_side"] = str(args.base_entry_reduce_side)
        suffix_parts.append(f"wfBaseReduceSide{args.base_entry_reduce_side}")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _apply_base_reduce_suppress_overlay(config: MarketStateConfig) -> MarketStateConfig:
    if (
        config.base_entry_max_extension_atr <= 0.0
        and config.base_entry_max_extension_side == "both"
        and config.base_entry_reduce_extension_atr <= 0.0
        and config.base_entry_reduce_size_mult >= 1.0
        and config.base_entry_reduce_promote_reaction <= 0.0
        and config.base_entry_reduce_max_trend_strength <= 0.0
        and config.base_entry_reduce_min_trend_strength <= 0.0
        and config.base_entry_reduce_side == "both"
    ):
        return config
    return replace(
        config,
        base_entry_max_extension_atr=0.0,
        base_entry_max_extension_side="both",
        base_entry_reduce_extension_atr=0.0,
        base_entry_reduce_size_mult=1.0,
        base_entry_reduce_promote_reaction=0.0,
        base_entry_reduce_max_trend_strength=0.0,
        base_entry_reduce_min_trend_strength=0.0,
        base_entry_reduce_side="both",
        model_id=config.model_id + ":wfBaseReduceSuppress",
    )


def _base_reduce_after_selection_allowed(train_result: dict[str, Any], args: argparse.Namespace) -> bool:
    min_train_return = args.base_entry_reduce_after_selection_min_train_return_pct
    if min_train_return is not None and float(train_result.get("total_return_pct") or 0.0) < float(min_train_return):
        return False
    max_train_return = args.base_entry_reduce_after_selection_max_train_return_pct
    if max_train_return is not None and float(train_result.get("total_return_pct") or 0.0) > float(max_train_return):
        return False
    max_train_drawdown = args.base_entry_reduce_after_selection_max_train_drawdown_pct
    if max_train_drawdown is not None and float(train_result.get("max_drawdown_pct") or 100.0) > float(
        max_train_drawdown
    ):
        return False
    min_trim_ratio = max(0.0, float(args.base_entry_reduce_after_selection_min_one_way_trim_per_add))
    if min_trim_ratio > 0.0:
        diagnostics = dict(train_result.get("event_diagnostics") or {})
        ratios = dict(diagnostics.get("ratios") or {})
        trim_ratio = float(ratios.get("one_way_forced_trim_per_add") or 0.0)
        if trim_ratio < min_trim_ratio:
            return False
    return True


_BASE_CONTEXT_MODIFIER_TOKENS = {
    "base_context_reduce",
    "event_risk_base_reduce",
    "late_base_reduce",
    "loss_fuse_reduce",
    "near_miss",
    "soft_recovery",
}


def _base_context_reduce_pattern_from_entry_context(context: str) -> str | None:
    tokens = [part.strip() for part in str(context or "").split("|") if part.strip()]
    if not tokens or tokens[0] != "base":
        return None
    clean_tokens: list[str] = []
    for token in tokens:
        if token in _BASE_CONTEXT_MODIFIER_TOKENS:
            continue
        clean_tokens.append(token)
        if len(clean_tokens) == 7:
            break
    if len(clean_tokens) != 7:
        return None
    return "|".join(clean_tokens)


def _negative_base_context_reduce_patterns(
    train_result: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[str, ...]:
    diagnostics = dict(train_result.get("event_diagnostics") or {})
    pnl_by_context = {
        str(key): float(value)
        for key, value in dict(diagnostics.get("worst_realized_pnl_usd_units_by_entry_context") or {}).items()
    }
    per_add_by_context = {
        str(key): float(value)
        for key, value in dict(diagnostics.get("realized_pnl_usd_units_per_add_by_entry_context") or {}).items()
    }
    add_by_context = {
        str(key): int(value)
        for key, value in dict(diagnostics.get("add_by_entry_context") or {}).items()
    }
    min_loss = max(0.0, float(args.negative_base_context_reduce_min_loss_usd_units))
    max_per_add = float(args.negative_base_context_reduce_max_per_add_usd_units)
    min_add_count = max(1, int(args.negative_base_context_reduce_min_add_count))
    max_contexts = max(1, int(args.negative_base_context_reduce_max_contexts))
    candidates: list[tuple[float, str]] = []
    for raw_context, total_pnl in pnl_by_context.items():
        if total_pnl > -min_loss:
            continue
        if int(add_by_context.get(raw_context) or 0) < min_add_count:
            continue
        if float(per_add_by_context.get(raw_context, total_pnl)) > max_per_add:
            continue
        pattern = _base_context_reduce_pattern_from_entry_context(raw_context)
        if not pattern:
            continue
        candidates.append((total_pnl, pattern))
    patterns: list[str] = []
    for _, pattern in sorted(candidates, key=lambda item: (item[0], item[1])):
        if pattern not in patterns:
            patterns.append(pattern)
        if len(patterns) >= max_contexts:
            break
    return tuple(patterns)


def _negative_base_context_reduce_after_selection_allowed(
    train_result: dict[str, Any],
    args: argparse.Namespace,
) -> bool:
    if not _train_state_after_selection_allowed(
        train_result,
        args,
        prefix="negative_base_context_reduce_after_selection",
    ):
        return False
    return bool(_negative_base_context_reduce_patterns(train_result, args))


def _apply_negative_base_context_reduce_overlay(
    config: MarketStateConfig,
    train_result: dict[str, Any],
    args: argparse.Namespace,
) -> MarketStateConfig:
    patterns = _negative_base_context_reduce_patterns(train_result, args)
    if not patterns:
        return config
    merged_patterns = tuple(dict.fromkeys([*(config.base_context_reduce_patterns or ()), *patterns]))
    size_mult = min(max(float(args.negative_base_context_reduce_size_mult), 0.0), 1.0)
    return replace(
        config,
        base_context_reduce_size_mult=size_mult,
        base_context_reduce_patterns=merged_patterns,
        model_id=f"{config.model_id}:wfNegBaseCtxReduce{size_mult:g}:wfNegBaseCtxSet{len(patterns)}",
    )


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


def _apply_one_way_loss_fuse_overlay(config: MarketStateConfig, args: argparse.Namespace) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    if args.one_way_loss_fuse_min_adverse_reaction is not None:
        value = max(0.0, float(args.one_way_loss_fuse_min_adverse_reaction))
        updates["one_way_loss_fuse_min_adverse_reaction"] = value
        suffix_parts.append(f"wfOwLossFuse{value:g}")
    if args.one_way_loss_fuse_cooldown_bars is not None:
        value = max(0, int(args.one_way_loss_fuse_cooldown_bars))
        updates["one_way_loss_fuse_cooldown_bars"] = value
        suffix_parts.append(f"wfOwLossFuseCool{value}")
    if args.one_way_loss_fuse_size_mult is not None:
        value = min(max(float(args.one_way_loss_fuse_size_mult), 0.0), 1.0)
        updates["one_way_loss_fuse_size_mult"] = value
        suffix_parts.append(f"wfOwLossFuseMult{value:g}")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _parse_fragile_regimes(raw: str) -> tuple[str, ...]:
    allowed = {
        "bad_rr_center",
        "downtrend",
        "mixed",
        "one_way_long",
        "one_way_short",
        "range_or_transition",
        "uptrend",
    }
    regimes = [item for item in _csv(raw) if item in allowed]
    return tuple(dict.fromkeys(regimes))


def _apply_fragile_regime_entry_overlay(
    config: MarketStateConfig,
    args: argparse.Namespace,
    *,
    size_attr: str = "fragile_regime_entry_size_mult",
    regimes_attr: str = "fragile_regime_entry_regimes",
    suffix_label: str = "wfFragReg",
    suffix_set_label: str = "wfFragSet",
) -> MarketStateConfig:
    regimes = _parse_fragile_regimes(str(getattr(args, regimes_attr)))
    configured_size = getattr(args, size_attr)
    if not regimes or configured_size is None:
        return config
    value = min(max(float(configured_size), 0.0), 1.0)
    suffix = (
        f"{suffix_label}{value:g}:"
        f"{suffix_set_label}{'-'.join(regime.replace('range_or_transition', 'range').replace('one_way_', 'ow') for regime in regimes)}"
    )
    return replace(
        config,
        fragile_regime_entry_size_mult=value,
        fragile_regime_entry_regimes=regimes,
        model_id=f"{config.model_id}:{suffix}",
    )


def _apply_fragile_regime_inventory_trim_overlay(
    config: MarketStateConfig,
    args: argparse.Namespace,
) -> MarketStateConfig:
    regimes = _parse_fragile_regimes(args.fragile_regime_inventory_trim_regimes)
    if not regimes or args.fragile_regime_inventory_trim_fraction is None:
        return config
    value = min(max(float(args.fragile_regime_inventory_trim_fraction), 0.0), 1.0)
    if value <= 1e-12:
        return config
    suffix = (
        f"wfFragInvTrim{value:g}:"
        f"wfFragInvSet{'-'.join(regime.replace('range_or_transition', 'range').replace('one_way_', 'ow') for regime in regimes)}"
    )
    return replace(
        config,
        fragile_regime_inventory_trim_fraction=value,
        fragile_regime_inventory_trim_regimes=regimes,
        model_id=f"{config.model_id}:{suffix}",
    )


def _fragile_regime_entry_after_selection_allowed(
    train_result: dict[str, Any],
    args: argparse.Namespace,
) -> bool:
    train_return = float(train_result.get("total_return_pct") or 0.0)
    min_train_return = args.fragile_regime_entry_after_selection_min_train_return_pct
    if min_train_return is not None and train_return < float(min_train_return):
        return False
    max_train_return = args.fragile_regime_entry_after_selection_max_train_return_pct
    if max_train_return is not None and train_return > float(max_train_return):
        return False
    train_drawdown = float(train_result.get("max_drawdown_pct") or 0.0)
    min_train_drawdown = args.fragile_regime_entry_after_selection_min_train_drawdown_pct
    if min_train_drawdown is not None and train_drawdown < float(min_train_drawdown):
        return False
    max_train_drawdown = args.fragile_regime_entry_after_selection_max_train_drawdown_pct
    if max_train_drawdown is not None and train_drawdown > float(max_train_drawdown):
        return False
    return True


def _fragile_regime_inventory_trim_after_selection_allowed(
    train_result: dict[str, Any],
    args: argparse.Namespace,
) -> bool:
    train_return = float(train_result.get("total_return_pct") or 0.0)
    min_train_return = args.fragile_regime_inventory_trim_after_selection_min_train_return_pct
    if min_train_return is not None and train_return < float(min_train_return):
        return False
    max_train_return = args.fragile_regime_inventory_trim_after_selection_max_train_return_pct
    if max_train_return is not None and train_return > float(max_train_return):
        return False
    train_drawdown = float(train_result.get("max_drawdown_pct") or 0.0)
    min_train_drawdown = args.fragile_regime_inventory_trim_after_selection_min_train_drawdown_pct
    if min_train_drawdown is not None and train_drawdown < float(min_train_drawdown):
        return False
    max_train_drawdown = args.fragile_regime_inventory_trim_after_selection_max_train_drawdown_pct
    if max_train_drawdown is not None and train_drawdown > float(max_train_drawdown):
        return False
    return True


def _risk_smoothing_after_selection_allowed(
    train_result: dict[str, Any],
    args: argparse.Namespace,
) -> bool:
    train_return = float(train_result.get("total_return_pct") or 0.0)
    if not _range_allowed(
        train_return,
        args.risk_smoothing_after_selection_min_train_return_pct,
        args.risk_smoothing_after_selection_max_train_return_pct,
    ):
        return False
    train_drawdown = float(train_result.get("max_drawdown_pct") or 0.0)
    if not _range_allowed(
        train_drawdown,
        args.risk_smoothing_after_selection_min_train_drawdown_pct,
        args.risk_smoothing_after_selection_max_train_drawdown_pct,
    ):
        return False
    train_cost_drag = float(train_result.get("estimated_cost_drag_pct") or 0.0)
    if not _range_allowed(
        train_cost_drag,
        args.risk_smoothing_after_selection_min_train_cost_drag_pct,
        args.risk_smoothing_after_selection_max_train_cost_drag_pct,
    ):
        return False
    trim_ratio = _train_ratio(train_result, "one_way_forced_trim_per_add")
    if not _positive_range_allowed(
        trim_ratio,
        max(0.0, float(args.risk_smoothing_after_selection_min_one_way_trim_per_add)),
        max(0.0, float(args.risk_smoothing_after_selection_max_one_way_trim_per_add)),
    ):
        return False
    turnover_ratio = _train_ratio(train_result, "turnover_events_per_add")
    if not _positive_range_allowed(
        turnover_ratio,
        max(0.0, float(args.risk_smoothing_after_selection_min_turnover_per_add)),
        max(0.0, float(args.risk_smoothing_after_selection_max_turnover_per_add)),
    ):
        return False
    return True


def _apply_risk_smoothing_overlay(config: MarketStateConfig, args: argparse.Namespace) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    if args.risk_smoothing_after_selection_max_possible_units is not None:
        value = max(0.01, float(args.risk_smoothing_after_selection_max_possible_units))
        updates["max_possible_units"] = value
        suffix_parts.append(f"wfRiskMaxU{value:g}")
    effective_max_units = float(updates.get("max_possible_units", config.max_possible_units))
    if args.risk_smoothing_after_selection_base_max_units is not None:
        value = min(max(0.01, float(args.risk_smoothing_after_selection_base_max_units)), effective_max_units)
        updates["base_max_units"] = value
        suffix_parts.append(f"wfRiskBaseMax{value:g}")
    if args.risk_smoothing_after_selection_battle_units is not None:
        value = min(max(0.0, float(args.risk_smoothing_after_selection_battle_units)), effective_max_units)
        updates["battle_units"] = value
        suffix_parts.append(f"wfRiskBattle{value:g}")
    if args.risk_smoothing_after_selection_defensive_trim_cooldown_bars is not None:
        value = max(0, int(args.risk_smoothing_after_selection_defensive_trim_cooldown_bars))
        updates["defensive_trim_cooldown_bars"] = value
        suffix_parts.append(f"wfRiskDefCool{value}")
    if args.risk_smoothing_after_selection_max_hold_bars is not None:
        value = max(1, int(args.risk_smoothing_after_selection_max_hold_bars))
        updates["max_hold_bars"] = value
        suffix_parts.append(f"wfRiskHold{value}")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _apply_hold_compression_overlay(config: MarketStateConfig, args: argparse.Namespace) -> MarketStateConfig:
    if args.hold_compression_after_selection_max_hold_bars is None:
        return config
    value = max(1, int(args.hold_compression_after_selection_max_hold_bars))
    if value >= int(config.max_hold_bars):
        return config
    return replace(
        config,
        max_hold_bars=value,
        model_id=f"{config.model_id}:wfHoldCompress{value}",
    )


def _apply_hold_extension_overlay(config: MarketStateConfig, args: argparse.Namespace) -> MarketStateConfig:
    if args.hold_extension_after_selection_max_hold_bars is None:
        return config
    value = max(1, int(args.hold_extension_after_selection_max_hold_bars))
    if value <= int(config.max_hold_bars):
        return config
    return replace(
        config,
        max_hold_bars=value,
        model_id=f"{config.model_id}:wfHoldExtend{value}",
    )


def _apply_reaction_tune_overlay(
    config: MarketStateConfig,
    args: argparse.Namespace,
    *,
    prefix: str = "reaction_tune_after_selection",
    reaction_suffix_label: str = "wfReactTrim",
    repair_cut_suffix_label: str = "wfRepairCut",
    repair_stop_suffix_label: str = "wfRepairStop",
) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    reaction_trim_trigger = getattr(args, f"{prefix}_reaction_trim_trigger")
    if reaction_trim_trigger is not None:
        value = max(0.0, float(reaction_trim_trigger))
        updates["reaction_trim_trigger"] = value
        suffix_parts.append(f"{reaction_suffix_label}{value:g}")
    repair_cut = getattr(args, f"{prefix}_repair_cut")
    if repair_cut is not None:
        value = max(0.0, float(repair_cut))
        updates["repair_cut"] = value
        suffix_parts.append(f"{repair_cut_suffix_label}{value:g}")
    repair_stop = getattr(args, f"{prefix}_repair_stop")
    if repair_stop is not None:
        value = max(0.0, float(repair_stop))
        updates["repair_stop"] = value
        suffix_parts.append(f"{repair_stop_suffix_label}{value:g}")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _apply_exit_trend_hold_overlay(config: MarketStateConfig, args: argparse.Namespace) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    reaction_mult = args.exit_trend_hold_after_selection_reaction_trim_trigger_mult
    if reaction_mult is not None:
        value = min(max(float(reaction_mult), 1.0), 5.0)
        updates["reaction_trim_trend_hold_trigger_mult"] = value
        suffix_parts.append(f"wfExitTrendReact{value:g}")
    hard_defer_bars = args.exit_trend_hold_after_selection_hard_time_defer_bars
    if hard_defer_bars is not None:
        value = max(0, int(hard_defer_bars))
        updates["hard_time_exit_trend_defer_bars"] = value
        suffix_parts.append(f"wfExitTrendHard{value}")
    min_favorable = args.exit_trend_hold_after_selection_hard_time_min_favorable_reaction
    if min_favorable is not None:
        value = max(0.0, float(min_favorable))
        updates["hard_time_exit_trend_defer_min_favorable_reaction"] = value
        suffix_parts.append(f"wfExitTrendFav{value:g}")
    min_trend = args.exit_trend_hold_after_selection_min_trend_strength
    if min_trend is not None:
        value = max(0.0, float(min_trend))
        updates["trend_hold_min_trend_strength"] = value
        suffix_parts.append(f"wfExitTrendT{value:g}")
    min_one_way = args.exit_trend_hold_after_selection_min_one_way_score
    if min_one_way is not None:
        value = max(0.0, float(min_one_way))
        updates["trend_hold_min_one_way_score"] = value
        suffix_parts.append(f"wfExitTrendO{value:g}")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _apply_repair_tune_overlay(
    config: MarketStateConfig,
    args: argparse.Namespace,
    *,
    prefix: str = "repair_tune_after_selection",
    repair_cut_suffix_label: str = "wfRepairTuneCut",
    repair_stop_suffix_label: str = "wfRepairTuneStop",
) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    repair_cut = getattr(args, f"{prefix}_repair_cut")
    if repair_cut is not None:
        value = max(0.0, float(repair_cut))
        updates["repair_cut"] = value
        suffix_parts.append(f"{repair_cut_suffix_label}{value:g}")
    repair_stop = getattr(args, f"{prefix}_repair_stop")
    if repair_stop is not None:
        value = max(0.0, float(repair_stop))
        updates["repair_stop"] = value
        suffix_parts.append(f"{repair_stop_suffix_label}{value:g}")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _apply_trim_cooldown_overlay(
    config: MarketStateConfig,
    args: argparse.Namespace,
    *,
    prefix: str = "trim_cooldown_after_selection",
    cooldown_suffix_label: str = "wfTrimCool",
    base_extension_suffix_label: str = "wfTrimBaseExt",
    base_size_suffix_label: str = "wfTrimBaseMult",
    base_promote_suffix_label: str = "wfTrimBaseProm",
) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    one_way_trim_cooldown_bars = getattr(args, f"{prefix}_one_way_trim_cooldown_bars")
    if one_way_trim_cooldown_bars is not None:
        value = max(0, int(one_way_trim_cooldown_bars))
        updates["one_way_trim_cooldown_bars"] = value
        suffix_parts.append(f"{cooldown_suffix_label}{value}")
    base_entry_reduce_extension_atr = getattr(args, f"{prefix}_base_entry_reduce_extension_atr")
    if base_entry_reduce_extension_atr is not None:
        value = max(0.0, float(base_entry_reduce_extension_atr))
        updates["base_entry_reduce_extension_atr"] = value
        suffix_parts.append(f"{base_extension_suffix_label}{value:g}")
    base_entry_reduce_size_mult = getattr(args, f"{prefix}_base_entry_reduce_size_mult")
    if base_entry_reduce_size_mult is not None:
        value = min(max(float(base_entry_reduce_size_mult), 0.0), 1.0)
        updates["base_entry_reduce_size_mult"] = value
        suffix_parts.append(f"{base_size_suffix_label}{value:g}")
    base_entry_reduce_promote_reaction = getattr(args, f"{prefix}_base_entry_reduce_promote_reaction")
    if base_entry_reduce_promote_reaction is not None:
        value = max(0.0, float(base_entry_reduce_promote_reaction))
        updates["base_entry_reduce_promote_reaction"] = value
        suffix_parts.append(f"{base_promote_suffix_label}{value:g}")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _apply_high_cost_balance_overlay(config: MarketStateConfig, args: argparse.Namespace) -> MarketStateConfig:
    updated = _apply_trim_cooldown_overlay(
        config,
        args,
        prefix="high_cost_balance_after_selection",
        cooldown_suffix_label="wfHighCostBalanceTrim",
        base_extension_suffix_label="wfHighCostBalanceBaseExt",
        base_size_suffix_label="wfHighCostBalanceBaseMult",
        base_promote_suffix_label="wfHighCostBalanceBaseProm",
    )
    return _apply_near_miss_overlay(
        updated,
        args,
        attr_prefix="high_cost_balance_probe",
        suffix_label="wfHighCostBalanceNear",
    )


def _apply_distribution_balance_overlay(config: MarketStateConfig, args: argparse.Namespace) -> MarketStateConfig:
    return _apply_near_miss_overlay(
        config,
        args,
        attr_prefix="distribution_balance_probe",
        suffix_label="wfDistributionBalance",
    )


def _apply_risk_off_micro_overlay(config: MarketStateConfig, args: argparse.Namespace) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    if args.risk_off_micro_after_selection_max_possible_units is not None:
        value = max(0.01, float(args.risk_off_micro_after_selection_max_possible_units))
        updates["max_possible_units"] = value
        suffix_parts.append(f"wfRiskOffMaxU{value:g}")
    effective_max_units = float(updates.get("max_possible_units", config.max_possible_units))
    if args.risk_off_micro_after_selection_base_max_units is not None:
        value = min(max(0.01, float(args.risk_off_micro_after_selection_base_max_units)), effective_max_units)
        updates["base_max_units"] = value
        suffix_parts.append(f"wfRiskOffBaseMax{value:g}")
    if args.risk_off_micro_after_selection_battle_units is not None:
        value = min(max(0.0, float(args.risk_off_micro_after_selection_battle_units)), effective_max_units)
        updates["battle_units"] = value
        suffix_parts.append(f"wfRiskOffBattle{value:g}")
    if args.risk_off_micro_after_selection_trend_core_units is not None:
        value = min(max(0.0, float(args.risk_off_micro_after_selection_trend_core_units)), effective_max_units)
        updates["trend_core_units"] = value
        suffix_parts.append(f"wfRiskOffTrend{value:g}")
    if args.risk_off_micro_after_selection_reaction_trim_trigger is not None:
        value = max(0.0, float(args.risk_off_micro_after_selection_reaction_trim_trigger))
        updates["reaction_trim_trigger"] = value
        suffix_parts.append(f"wfRiskOffReact{value:g}")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _apply_battle_restore_overlay(config: MarketStateConfig, args: argparse.Namespace) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    if args.battle_restore_after_selection_battle_units is not None:
        value = min(
            max(0.0, float(args.battle_restore_after_selection_battle_units)),
            config.max_possible_units,
        )
        updates["battle_units"] = value
        suffix_parts.append(f"wfBattleUnits{value:g}")
    if args.battle_restore_after_selection_battle_score is not None:
        value = max(0, int(args.battle_restore_after_selection_battle_score))
        updates["battle_score"] = value
        suffix_parts.append(f"wfBattleScore{value}")
    if args.battle_restore_after_selection_battle_trigger_usd is not None:
        value = max(0.0, float(args.battle_restore_after_selection_battle_trigger_usd))
        updates["battle_trigger_usd"] = value
        suffix_parts.append(f"wfBattleUsd{value:g}")
    if args.battle_restore_after_selection_battle_trigger_atr is not None:
        value = max(0.0, float(args.battle_restore_after_selection_battle_trigger_atr))
        updates["battle_trigger_atr"] = value
        suffix_parts.append(f"wfBattleAtr{value:g}")
    if args.battle_restore_after_selection_max_repair_eff_for_add is not None:
        value = max(0.0, float(args.battle_restore_after_selection_max_repair_eff_for_add))
        updates["max_repair_eff_for_add"] = value
        suffix_parts.append(f"wfBattleRepair{value:g}")
    if args.battle_restore_after_selection_min_capacity_ratio is not None:
        value = min(max(float(args.battle_restore_after_selection_min_capacity_ratio), 0.0), 1.0)
        updates["min_capacity_ratio"] = value
        suffix_parts.append(f"wfBattleCap{value:g}")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _exposure_rebalance_after_selection_allowed(
    train_result: dict[str, Any],
    args: argparse.Namespace,
) -> bool:
    source_config = dict(train_result.get("config") or {})
    source_max_units = float(source_config.get("max_possible_units") or 0.0)
    if not _range_allowed(
        source_max_units,
        args.exposure_rebalance_after_selection_min_source_max_units,
        args.exposure_rebalance_after_selection_max_source_max_units,
    ):
        return False
    train_return = float(train_result.get("total_return_pct") or 0.0)
    if not _range_allowed(
        train_return,
        args.exposure_rebalance_after_selection_min_train_return_pct,
        args.exposure_rebalance_after_selection_max_train_return_pct,
    ):
        return False
    train_drawdown = float(train_result.get("max_drawdown_pct") or 0.0)
    if not _range_allowed(
        train_drawdown,
        args.exposure_rebalance_after_selection_min_train_drawdown_pct,
        args.exposure_rebalance_after_selection_max_train_drawdown_pct,
    ):
        return False
    train_cost_drag = float(train_result.get("estimated_cost_drag_pct") or 0.0)
    if not _range_allowed(
        train_cost_drag,
        args.exposure_rebalance_after_selection_min_train_cost_drag_pct,
        args.exposure_rebalance_after_selection_max_train_cost_drag_pct,
    ):
        return False
    trim_ratio = _train_ratio(train_result, "one_way_forced_trim_per_add")
    if not _positive_range_allowed(
        trim_ratio,
        max(0.0, float(args.exposure_rebalance_after_selection_min_one_way_trim_per_add)),
        max(0.0, float(args.exposure_rebalance_after_selection_max_one_way_trim_per_add)),
    ):
        return False
    turnover_ratio = _train_ratio(train_result, "turnover_events_per_add")
    if not _positive_range_allowed(
        turnover_ratio,
        max(0.0, float(args.exposure_rebalance_after_selection_min_turnover_per_add)),
        max(0.0, float(args.exposure_rebalance_after_selection_max_turnover_per_add)),
    ):
        return False
    return True


def _apply_exposure_rebalance_overlay(config: MarketStateConfig, args: argparse.Namespace) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    if args.exposure_rebalance_after_selection_max_possible_units is not None:
        value = max(0.01, float(args.exposure_rebalance_after_selection_max_possible_units))
        updates["max_possible_units"] = value
        suffix_parts.append(f"wfExpMaxU{value:g}")
    effective_max_units = float(updates.get("max_possible_units", config.max_possible_units))
    if args.exposure_rebalance_after_selection_base_max_units is not None:
        value = min(max(0.01, float(args.exposure_rebalance_after_selection_base_max_units)), effective_max_units)
        updates["base_max_units"] = value
        suffix_parts.append(f"wfExpBaseMax{value:g}")
    if args.exposure_rebalance_after_selection_base_add_units is not None:
        value = min(max(0.01, float(args.exposure_rebalance_after_selection_base_add_units)), effective_max_units)
        updates["base_add_units"] = value
        suffix_parts.append(f"wfExpBaseAdd{value:g}")
    if args.exposure_rebalance_after_selection_battle_units is not None:
        value = min(max(0.0, float(args.exposure_rebalance_after_selection_battle_units)), effective_max_units)
        updates["battle_units"] = value
        suffix_parts.append(f"wfExpBattle{value:g}")
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


def _one_way_loss_fuse_after_selection_allowed(train_result: dict[str, Any], args: argparse.Namespace) -> bool:
    train_return = float(train_result.get("total_return_pct") or 0.0)
    min_train_return = args.one_way_loss_fuse_after_selection_min_train_return_pct
    if min_train_return is not None and train_return < float(min_train_return):
        return False
    max_train_return = args.one_way_loss_fuse_after_selection_max_train_return_pct
    if max_train_return is not None and train_return > float(max_train_return):
        return False
    train_drawdown = float(train_result.get("max_drawdown_pct") or 0.0)
    min_train_drawdown = args.one_way_loss_fuse_after_selection_min_train_drawdown_pct
    if min_train_drawdown is not None and train_drawdown < float(min_train_drawdown):
        return False
    max_train_drawdown = args.one_way_loss_fuse_after_selection_max_train_drawdown_pct
    if max_train_drawdown is not None and train_drawdown > float(max_train_drawdown):
        return False
    diagnostics = dict(train_result.get("event_diagnostics") or {})
    ratios = dict(diagnostics.get("ratios") or {})
    trim_ratio = float(ratios.get("one_way_forced_trim_per_add") or 0.0)
    min_trim_ratio = max(0.0, float(args.one_way_loss_fuse_after_selection_min_one_way_trim_per_add))
    if min_trim_ratio > 0.0 and trim_ratio < min_trim_ratio:
        return False
    max_trim_ratio = max(0.0, float(args.one_way_loss_fuse_after_selection_max_one_way_trim_per_add))
    if max_trim_ratio > 0.0 and trim_ratio > max_trim_ratio:
        return False
    return True


def _apply_after_selection_overlays(
    config: MarketStateConfig,
    train_result: dict[str, Any],
    args: argparse.Namespace,
    *,
    blocked_overlays: set[str] | dict[str, str] | None = None,
    blocked_reason: str = "train_confirm_rejected",
) -> tuple[MarketStateConfig, list[str], list[str]]:
    overlays_applied: list[str] = []
    overlays_skipped: list[str] = []
    blocked = blocked_overlays or {}
    blocked_reasons = (
        {str(name): str(reason) for name, reason in blocked.items()}
        if isinstance(blocked, dict)
        else {str(name): blocked_reason for name in blocked}
    )

    def is_blocked(name: str) -> bool:
        reason = blocked_reasons.get(name)
        if not reason:
            return False
        overlays_skipped.append(f"{name}:{reason}")
        return True

    def apply_changed_overlay(name: str, updated_config: MarketStateConfig) -> None:
        nonlocal config
        if _material_config_key(updated_config) == _material_config_key(config):
            overlays_skipped.append(f"{name}:no_material_change")
            return
        config = updated_config
        overlays_applied.append(name)

    if bool(args.equity_circuit_breaker_after_selection):
        if is_blocked("equity_circuit"):
            pass
        else:
            config = _apply_equity_circuit_overlay(config, args)
            overlays_applied.append("equity_circuit")
    if bool(args.equity_soft_circuit_after_selection):
        if is_blocked("equity_soft_circuit"):
            pass
        elif _equity_soft_circuit_after_selection_allowed(train_result, args):
            config = _apply_equity_soft_circuit_overlay(config, args)
            overlays_applied.append("equity_soft_circuit")
        else:
            overlays_skipped.append("equity_soft_circuit")
    if bool(args.equity_soft_sizer_after_selection):
        if is_blocked("equity_soft_sizer"):
            pass
        elif _equity_soft_sizer_after_selection_allowed(train_result, args):
            config = _apply_equity_soft_sizer_overlay(config, args)
            overlays_applied.append("equity_soft_sizer")
        else:
            overlays_skipped.append("equity_soft_sizer")
    if bool(args.equity_soft_sizer_alt_after_selection):
        if is_blocked("equity_soft_sizer_alt"):
            pass
        elif _equity_soft_sizer_after_selection_allowed(
            train_result,
            args,
            prefix="equity_soft_sizer_alt_after_selection",
        ):
            config = _apply_equity_soft_sizer_overlay(
                config,
                args,
                prefix="equity_soft_sizer_alt_after_selection",
                suffix_label="wfEqSizeAlt",
            )
            overlays_applied.append("equity_soft_sizer_alt")
        else:
            overlays_skipped.append("equity_soft_sizer_alt")
    if bool(args.equity_soft_sizer_deep_after_selection):
        if is_blocked("equity_soft_sizer_deep"):
            pass
        elif _equity_soft_sizer_after_selection_allowed(
            train_result,
            args,
            prefix="equity_soft_sizer_deep_after_selection",
        ):
            config = _apply_equity_soft_sizer_overlay(
                config,
                args,
                prefix="equity_soft_sizer_deep_after_selection",
                suffix_label="wfEqSizeDeep",
            )
            overlays_applied.append("equity_soft_sizer_deep")
        else:
            overlays_skipped.append("equity_soft_sizer_deep")
    if bool(args.one_way_trim_full_exit_after_selection):
        if is_blocked("one_way_trim_full_exit"):
            pass
        else:
            config = _apply_full_exit_overlay(config, args)
            overlays_applied.append("one_way_trim_full_exit")
    if bool(args.one_way_reversal_after_selection):
        if is_blocked("one_way_reversal"):
            pass
        elif _one_way_reversal_after_selection_allowed(train_result, args):
            apply_changed_overlay(
                "one_way_reversal",
                _apply_one_way_reversal_after_selection_overlay(config, args),
            )
        else:
            overlays_skipped.append("one_way_reversal")
        if args.one_way_reversal_after_selection_weak_switch_units is not None:
            if is_blocked("one_way_reversal_weak"):
                pass
            elif _one_way_reversal_after_selection_weak_allowed(train_result, args):
                apply_changed_overlay(
                    "one_way_reversal_weak",
                    _apply_one_way_reversal_after_selection_overlay(
                        config,
                        args,
                        switch_units=args.one_way_reversal_after_selection_weak_switch_units,
                        suffix_label="wfOwRevWeak",
                    ),
                )
            else:
                overlays_skipped.append("one_way_reversal_weak")
    for overlay_name, arg_prefix, suffix_label in (
        ("one_way_reversal_boost", "one_way_reversal_boost_after_selection", "wfOwRevBoost"),
        ("one_way_reversal_fine", "one_way_reversal_fine_after_selection", "wfOwRevFine"),
    ):
        if bool(getattr(args, arg_prefix)):
            if is_blocked(overlay_name):
                pass
            elif getattr(args, f"{arg_prefix}_switch_units") is None:
                overlays_skipped.append(overlay_name)
            elif _train_state_after_selection_allowed(train_result, args, prefix=arg_prefix):
                apply_changed_overlay(
                    overlay_name,
                    _apply_one_way_reversal_after_selection_overlay(
                        config,
                        args,
                        switch_units=getattr(args, f"{arg_prefix}_switch_units"),
                        suffix_label=suffix_label,
                    ),
                )
            else:
                overlays_skipped.append(overlay_name)
    if bool(args.one_way_reversal_suppress_after_selection):
        if is_blocked("one_way_reversal_suppress"):
            pass
        elif _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="one_way_reversal_suppress_after_selection",
        ):
            apply_changed_overlay(
                "one_way_reversal_suppress",
                _apply_one_way_reversal_after_selection_overlay(
                    config,
                    args,
                    switch_units=0.0,
                    suffix_label="wfOwRevSuppress",
                ),
            )
        else:
            overlays_skipped.append("one_way_reversal_suppress")
    if bool(args.one_way_impulse_after_selection):
        if is_blocked("one_way_impulse"):
            pass
        elif _one_way_impulse_after_selection_allowed(train_result, args):
            config = _apply_one_way_impulse_after_selection_overlay(config, args)
            overlays_applied.append("one_way_impulse")
        else:
            overlays_skipped.append("one_way_impulse")
    if bool(args.one_way_impulse_alt_after_selection):
        if is_blocked("one_way_impulse_alt"):
            pass
        elif _one_way_impulse_after_selection_allowed(
            train_result,
            args,
            prefix="one_way_impulse_alt_after_selection",
        ):
            config = _apply_one_way_impulse_after_selection_overlay(
                config,
                args,
                prefix="one_way_impulse_alt_after_selection",
                suffix_label="wfOwImpAlt",
            )
            overlays_applied.append("one_way_impulse_alt")
        else:
            overlays_skipped.append("one_way_impulse_alt")
    if bool(args.one_way_impulse_tail_after_selection):
        if is_blocked("one_way_impulse_tail"):
            pass
        elif _one_way_impulse_after_selection_allowed(
            train_result,
            args,
            prefix="one_way_impulse_tail_after_selection",
        ):
            config = _apply_one_way_impulse_after_selection_overlay(
                config,
                args,
                prefix="one_way_impulse_tail_after_selection",
                suffix_label="wfOwImpTail",
            )
            overlays_applied.append("one_way_impulse_tail")
        else:
            overlays_skipped.append("one_way_impulse_tail")
    if bool(args.one_way_impulse_late_after_selection):
        if is_blocked("one_way_impulse_late"):
            pass
        elif _one_way_impulse_after_selection_allowed(
            train_result,
            args,
            prefix="one_way_impulse_late_after_selection",
        ):
            config = _apply_one_way_impulse_after_selection_overlay(
                config,
                args,
                prefix="one_way_impulse_late_after_selection",
                suffix_label="wfOwImpLate",
            )
            overlays_applied.append("one_way_impulse_late")
        else:
            overlays_skipped.append("one_way_impulse_late")
    if bool(args.one_way_impulse_micro_after_selection):
        if is_blocked("one_way_impulse_micro"):
            pass
        elif _one_way_impulse_after_selection_allowed(
            train_result,
            args,
            prefix="one_way_impulse_micro_after_selection",
        ):
            config = _apply_one_way_impulse_after_selection_overlay(
                config,
                args,
                prefix="one_way_impulse_micro_after_selection",
                suffix_label="wfOwImpMicro",
            )
            overlays_applied.append("one_way_impulse_micro")
        else:
            overlays_skipped.append("one_way_impulse_micro")
    if bool(args.role_balance_impulse_after_selection):
        if is_blocked("role_balance_impulse"):
            pass
        elif (
            "one_way_impulse" in overlays_applied
            or "one_way_impulse_alt" in overlays_applied
            or "one_way_impulse_tail" in overlays_applied
            or "one_way_impulse_late" in overlays_applied
            or "one_way_impulse_micro" in overlays_applied
        ):
            overlays_skipped.append("role_balance_impulse")
        elif _one_way_impulse_after_selection_allowed(
            train_result,
            args,
            prefix="role_balance_impulse_after_selection",
        ):
            config = _apply_one_way_impulse_after_selection_overlay(
                config,
                args,
                prefix="role_balance_impulse_after_selection",
                suffix_label="wfRoleBalanceImpulse",
            )
            overlays_applied.append("role_balance_impulse")
        else:
            overlays_skipped.append("role_balance_impulse")
    if bool(args.trend_idle_after_selection):
        if is_blocked("trend_idle"):
            pass
        elif _trend_idle_after_selection_allowed(train_result, args):
            config = _apply_trend_idle_overlay(config, args)
            overlays_applied.append("trend_idle")
        else:
            overlays_skipped.append("trend_idle")
    if bool(args.near_miss_after_selection):
        if is_blocked("near_miss"):
            pass
        elif _near_miss_after_selection_allowed(train_result, args):
            config = _apply_near_miss_overlay(config, args)
            overlays_applied.append("near_miss")
        else:
            overlays_skipped.append("near_miss")
    if bool(args.near_miss_late_after_selection):
        if is_blocked("near_miss_late"):
            pass
        elif "near_miss" in overlays_applied:
            overlays_skipped.append("near_miss_late")
        elif _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="near_miss_late_after_selection",
        ):
            config = _apply_near_miss_overlay(config, args)
            overlays_applied.append("near_miss_late")
        else:
            overlays_skipped.append("near_miss_late")
    if bool(args.near_miss_mid_after_selection):
        if is_blocked("near_miss_mid"):
            pass
        elif "near_miss" in overlays_applied or "near_miss_late" in overlays_applied:
            overlays_skipped.append("near_miss_mid")
        elif _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="near_miss_mid_after_selection",
        ):
            config = _apply_near_miss_overlay(
                config,
                args,
                attr_prefix="near_miss_mid_probe",
                suffix_label="wfNearMissMid",
            )
            overlays_applied.append("near_miss_mid")
        else:
            overlays_skipped.append("near_miss_mid")
    if bool(args.near_miss_activity_after_selection):
        if is_blocked("near_miss_activity"):
            pass
        elif (
            "near_miss" in overlays_applied
            or "near_miss_late" in overlays_applied
            or "near_miss_mid" in overlays_applied
        ):
            overlays_skipped.append("near_miss_activity")
        elif _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="near_miss_activity_after_selection",
        ):
            config = _apply_near_miss_overlay(
                config,
                args,
                attr_prefix="near_miss_activity_probe",
                suffix_label="wfNearMissActivity",
            )
            overlays_applied.append("near_miss_activity")
        else:
            overlays_skipped.append("near_miss_activity")
    if bool(args.near_miss_high_after_selection):
        if is_blocked("near_miss_high"):
            pass
        elif (
            "near_miss" in overlays_applied
            or "near_miss_late" in overlays_applied
            or "near_miss_mid" in overlays_applied
            or "near_miss_activity" in overlays_applied
        ):
            overlays_skipped.append("near_miss_high")
        elif _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="near_miss_high_after_selection",
        ):
            config = _apply_near_miss_overlay(config, args)
            overlays_applied.append("near_miss_high")
        else:
            overlays_skipped.append("near_miss_high")
    if bool(args.base_entry_reduce_after_selection):
        if is_blocked("base_reduce"):
            pass
        elif _base_reduce_after_selection_allowed(train_result, args):
            config = _apply_base_reduce_overlay(config, args)
            overlays_applied.append("base_reduce")
        else:
            overlays_skipped.append("base_reduce")
    if bool(args.base_reduce_suppress_after_selection):
        if is_blocked("base_reduce_suppress"):
            pass
        elif _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="base_reduce_suppress_after_selection",
        ):
            config = _apply_base_reduce_suppress_overlay(config)
            overlays_applied.append("base_reduce_suppress")
        else:
            overlays_skipped.append("base_reduce_suppress")
    if bool(args.negative_base_context_reduce_after_selection):
        if is_blocked("negative_base_context_reduce"):
            pass
        elif _negative_base_context_reduce_after_selection_allowed(train_result, args):
            apply_changed_overlay(
                "negative_base_context_reduce",
                _apply_negative_base_context_reduce_overlay(config, train_result, args),
            )
        else:
            overlays_skipped.append("negative_base_context_reduce")
    if bool(args.fragile_regime_entry_after_selection):
        if is_blocked("fragile_regime_entry"):
            pass
        elif _fragile_regime_entry_after_selection_allowed(train_result, args):
            config = _apply_fragile_regime_entry_overlay(config, args)
            overlays_applied.append("fragile_regime_entry")
        else:
            overlays_skipped.append("fragile_regime_entry")
    if bool(args.fragile_regime_entry_high_after_selection):
        if is_blocked("fragile_regime_entry_high"):
            pass
        elif _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="fragile_regime_entry_high_after_selection",
        ):
            config = _apply_fragile_regime_entry_overlay(
                config,
                args,
                size_attr="fragile_regime_entry_high_size_mult",
                regimes_attr="fragile_regime_entry_high_regimes",
                suffix_label="wfFragHigh",
                suffix_set_label="wfFragHighSet",
            )
            overlays_applied.append("fragile_regime_entry_high")
        else:
            overlays_skipped.append("fragile_regime_entry_high")
    if bool(args.fragile_regime_entry_low_after_selection):
        if is_blocked("fragile_regime_entry_low"):
            pass
        elif _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="fragile_regime_entry_low_after_selection",
        ):
            config = _apply_fragile_regime_entry_overlay(
                config,
                args,
                size_attr="fragile_regime_entry_low_size_mult",
                regimes_attr="fragile_regime_entry_low_regimes",
                suffix_label="wfFragLow",
                suffix_set_label="wfFragLowSet",
            )
            overlays_applied.append("fragile_regime_entry_low")
        else:
            overlays_skipped.append("fragile_regime_entry_low")
    if bool(args.fragile_regime_inventory_trim_after_selection):
        if is_blocked("fragile_regime_inventory_trim"):
            pass
        elif _fragile_regime_inventory_trim_after_selection_allowed(train_result, args):
            config = _apply_fragile_regime_inventory_trim_overlay(config, args)
            overlays_applied.append("fragile_regime_inventory_trim")
        else:
            overlays_skipped.append("fragile_regime_inventory_trim")
    if bool(args.risk_smoothing_after_selection):
        if is_blocked("risk_smoothing"):
            pass
        elif _risk_smoothing_after_selection_allowed(train_result, args):
            config = _apply_risk_smoothing_overlay(config, args)
            overlays_applied.append("risk_smoothing")
        else:
            overlays_skipped.append("risk_smoothing")
    if bool(args.hold_compression_after_selection):
        if is_blocked("hold_compression"):
            pass
        elif _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="hold_compression_after_selection",
        ):
            updated_config = _apply_hold_compression_overlay(config, args)
            if updated_config is config:
                overlays_skipped.append("hold_compression")
            else:
                config = updated_config
                overlays_applied.append("hold_compression")
        else:
            overlays_skipped.append("hold_compression")
    if bool(args.hold_extension_after_selection):
        if is_blocked("hold_extension"):
            pass
        elif _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="hold_extension_after_selection",
        ):
            updated_config = _apply_hold_extension_overlay(config, args)
            if updated_config is config:
                overlays_skipped.append("hold_extension")
            else:
                config = updated_config
                overlays_applied.append("hold_extension")
        else:
            overlays_skipped.append("hold_extension")
    if bool(args.reaction_tune_after_selection):
        if is_blocked("reaction_tune"):
            pass
        elif _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="reaction_tune_after_selection",
        ):
            updated_config = _apply_reaction_tune_overlay(config, args)
            if updated_config is config:
                overlays_skipped.append("reaction_tune")
            else:
                config = updated_config
                overlays_applied.append("reaction_tune")
        else:
            overlays_skipped.append("reaction_tune")
    if bool(args.reaction_tune_strong_after_selection):
        if is_blocked("reaction_tune_strong"):
            pass
        elif _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="reaction_tune_strong_after_selection",
        ):
            updated_config = _apply_reaction_tune_overlay(
                config,
                args,
                prefix="reaction_tune_strong_after_selection",
                reaction_suffix_label="wfReactStrong",
                repair_cut_suffix_label="wfReactStrongCut",
                repair_stop_suffix_label="wfReactStrongStop",
            )
            if updated_config is config:
                overlays_skipped.append("reaction_tune_strong")
            else:
                config = updated_config
                overlays_applied.append("reaction_tune_strong")
        else:
            overlays_skipped.append("reaction_tune_strong")
    if bool(args.exit_trend_hold_after_selection):
        if is_blocked("exit_trend_hold"):
            pass
        elif _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="exit_trend_hold_after_selection",
        ):
            updated_config = _apply_exit_trend_hold_overlay(config, args)
            if updated_config is config:
                overlays_skipped.append("exit_trend_hold")
            else:
                config = updated_config
                overlays_applied.append("exit_trend_hold")
        else:
            overlays_skipped.append("exit_trend_hold")
    if bool(args.repair_tune_after_selection):
        if is_blocked("repair_tune"):
            pass
        elif _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="repair_tune_after_selection",
        ):
            updated_config = _apply_repair_tune_overlay(config, args)
            if updated_config is config:
                overlays_skipped.append("repair_tune")
            else:
                config = updated_config
                overlays_applied.append("repair_tune")
        else:
            overlays_skipped.append("repair_tune")
    if bool(args.repair_tune_high_cost_after_selection):
        if is_blocked("repair_tune_high_cost"):
            pass
        elif _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="repair_tune_high_cost_after_selection",
        ):
            updated_config = _apply_repair_tune_overlay(
                config,
                args,
                prefix="repair_tune_high_cost_after_selection",
                repair_cut_suffix_label="wfRepairHighCostCut",
                repair_stop_suffix_label="wfRepairHighCostStop",
            )
            if updated_config is config:
                overlays_skipped.append("repair_tune_high_cost")
            else:
                config = updated_config
                overlays_applied.append("repair_tune_high_cost")
        else:
            overlays_skipped.append("repair_tune_high_cost")
    for trim_prefix, trim_overlay_name, trim_suffix_label in (
        ("trim_cooldown_after_selection", "trim_cooldown", "wfTrimCool"),
        ("trim_cooldown_deep_after_selection", "trim_cooldown_deep", "wfTrimDeepCool"),
        ("trim_cooldown_strong_after_selection", "trim_cooldown_strong", "wfTrimStrongCool"),
        (
            "trim_cooldown_high_cost_after_selection",
            "trim_cooldown_high_cost",
            "wfTrimHighCostCool",
        ),
    ):
        if bool(getattr(args, trim_prefix)):
            if is_blocked(trim_overlay_name):
                pass
            elif _train_state_after_selection_allowed(
                train_result,
                args,
                prefix=trim_prefix,
            ):
                updated_config = _apply_trim_cooldown_overlay(
                    config,
                    args,
                    prefix=trim_prefix,
                    cooldown_suffix_label=trim_suffix_label,
                    base_extension_suffix_label=f"{trim_suffix_label}BaseExt",
                    base_size_suffix_label=f"{trim_suffix_label}BaseMult",
                    base_promote_suffix_label=f"{trim_suffix_label}BaseProm",
                )
                if updated_config is config:
                    overlays_skipped.append(trim_overlay_name)
                else:
                    config = updated_config
                    overlays_applied.append(trim_overlay_name)
            else:
                overlays_skipped.append(trim_overlay_name)
    if bool(args.high_cost_balance_after_selection):
        if is_blocked("high_cost_balance"):
            pass
        elif _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="high_cost_balance_after_selection",
        ):
            updated_config = _apply_high_cost_balance_overlay(config, args)
            if updated_config is config:
                overlays_skipped.append("high_cost_balance")
            else:
                config = updated_config
                overlays_applied.append("high_cost_balance")
        else:
            overlays_skipped.append("high_cost_balance")
    if bool(args.distribution_balance_after_selection):
        if is_blocked("distribution_balance"):
            pass
        elif (
            "near_miss" in overlays_applied
            or "near_miss_late" in overlays_applied
            or "near_miss_mid" in overlays_applied
            or "near_miss_activity" in overlays_applied
            or "near_miss_high" in overlays_applied
            or "high_cost_balance" in overlays_applied
        ):
            overlays_skipped.append("distribution_balance")
        elif _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="distribution_balance_after_selection",
        ):
            updated_config = _apply_distribution_balance_overlay(config, args)
            if updated_config is config:
                overlays_skipped.append("distribution_balance")
            else:
                config = updated_config
                overlays_applied.append("distribution_balance")
        else:
            overlays_skipped.append("distribution_balance")
    if bool(args.battle_restore_after_selection):
        if is_blocked("battle_restore"):
            pass
        elif _battle_restore_after_selection_allowed(train_result, args):
            updated_config = _apply_battle_restore_overlay(config, args)
            if updated_config is config:
                overlays_skipped.append("battle_restore")
            else:
                config = updated_config
                overlays_applied.append("battle_restore")
        else:
            overlays_skipped.append("battle_restore")
    if bool(args.risk_off_micro_after_selection):
        if is_blocked("risk_off_micro"):
            pass
        elif _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="risk_off_micro_after_selection",
        ):
            updated_config = _apply_risk_off_micro_overlay(config, args)
            if updated_config is config:
                overlays_skipped.append("risk_off_micro")
            else:
                config = updated_config
                overlays_applied.append("risk_off_micro")
        else:
            overlays_skipped.append("risk_off_micro")
    if bool(args.exposure_rebalance_after_selection):
        if is_blocked("exposure_rebalance"):
            pass
        elif _exposure_rebalance_after_selection_allowed(train_result, args):
            config = _apply_exposure_rebalance_overlay(config, args)
            overlays_applied.append("exposure_rebalance")
        else:
            overlays_skipped.append("exposure_rebalance")
    if bool(args.one_way_trim_context_late_after_selection):
        if is_blocked("one_way_trim_context_late"):
            pass
        elif _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="one_way_trim_context_late_after_selection",
        ):
            config = _apply_context_quarantine_overlay(config, args)
            overlays_applied.append("one_way_trim_context_late")
        else:
            overlays_skipped.append("one_way_trim_context_late")
    if bool(args.one_way_trim_context_after_selection):
        if is_blocked("one_way_trim_context"):
            pass
        elif "one_way_trim_context_late" in overlays_applied:
            overlays_skipped.append("one_way_trim_context")
        elif bool(args.one_way_trim_context_after_selection_require_base_reduce) and (
            "base_reduce" not in overlays_applied
        ):
            overlays_skipped.append("one_way_trim_context")
        else:
            config = _apply_context_quarantine_overlay(config, args)
            overlays_applied.append("one_way_trim_context")
    if bool(args.one_way_loss_fuse_after_selection):
        if is_blocked("one_way_loss_fuse"):
            pass
        elif _one_way_loss_fuse_after_selection_allowed(train_result, args):
            config = _apply_one_way_loss_fuse_overlay(config, args)
            overlays_applied.append("one_way_loss_fuse")
        else:
            overlays_skipped.append("one_way_loss_fuse")
    for recipe in _legacy_after_selection_recipes(args):
        overlay_name = str(recipe.get("name") or "legacy_recipe")
        if is_blocked(overlay_name):
            continue
        blockers = _legacy_recipe_blockers(recipe, overlays_applied)
        if blockers:
            overlays_skipped.append(f"{overlay_name}:blocked_by_applied={','.join(blockers)}")
            continue
        missing_required = _legacy_recipe_missing_required(recipe, overlays_applied)
        if missing_required:
            overlays_skipped.append(f"{overlay_name}:missing_required={','.join(missing_required)}")
            continue
        if not _legacy_recipe_allowed(train_result, recipe):
            overlays_skipped.append(overlay_name)
            continue
        apply_changed_overlay(
            overlay_name,
            _apply_legacy_recipe_overlay(config, recipe),
        )
    if bool(args.near_miss_context_guard_after_selection):
        context_guard_blockers = _near_miss_context_guard_blockers(overlays_applied, args)
        if context_guard_blockers:
            overlays_skipped.append(
                f"near_miss_context_guard:blocked_by_applied={','.join(context_guard_blockers)}"
            )
        else:
            apply_changed_overlay(
                "near_miss_context_guard",
                _apply_near_miss_context_guard_overlay(config, args),
            )
    return config, overlays_applied, overlays_skipped


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


def _soft_excess_penalty(value: float, threshold: float, penalty: float) -> float:
    if threshold <= 0.0 or penalty <= 0.0:
        return 0.0
    return max(value - threshold, 0.0) * penalty


def _anchored_fold_start(first_ts: datetime, anchor_hour_utc: int | None, anchor_minute_utc: int) -> datetime:
    first_ts = first_ts.astimezone(UTC)
    if anchor_hour_utc is None:
        return first_ts
    hour = int(anchor_hour_utc)
    minute = int(anchor_minute_utc)
    if not 0 <= hour <= 23:
        raise ValueError("fold anchor hour must be in 0..23")
    if not 0 <= minute <= 59:
        raise ValueError("fold anchor minute must be in 0..59")
    anchored = first_ts.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if anchored < first_ts:
        anchored += timedelta(days=1)
    return anchored


def _parse_fold_start_at(raw: str | None) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid fold start timestamp: {text}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _load_days_covering_fold_start(fold_start_at: datetime | None) -> int:
    if fold_start_at is None:
        return 0
    age_days = (datetime.now(UTC) - fold_start_at).total_seconds() / 86_400.0
    return max(0, int(math.ceil(age_days)) + 2)


def _selection_score(
    result: dict[str, Any],
    *,
    impulse_score_penalty: float = 0.0,
    btc_rotation_score_penalty: float = 0.0,
    flag_penalty: float = 0.10,
    score_cap: float = 0.0,
    mdd_soft_threshold_pct: float = 0.0,
    mdd_soft_penalty: float = 0.0,
    cost_soft_threshold_pct: float = 0.0,
    cost_soft_penalty: float = 0.0,
    stress_cost_multiplier: float = 0.0,
    stress_funding_proxy_pct: float = 0.0,
    stress_min_return_floor_pct: float = 0.0,
    stress_floor_gap_penalty: float = 0.0,
    cost_to_gross_threshold: float = 0.0,
    cost_to_gross_penalty: float = 0.0,
    reaction_usd_risk_threshold: float = 0.0,
    reaction_usd_risk_penalty: float = 0.0,
    reaction_usd_risk_min_train_drawdown_pct: float = 0.0,
    reaction_usd_risk_min_turnover_per_add: float = 0.0,
    reaction_usd_risk_min_one_way_trim_per_add: float = 0.0,
    reaction_usd_risk_min_cost_drag_pct: float = 0.0,
    max_reaction_usd: float = 0.0,
    one_way_trim_ratio_threshold: float = 0.0,
    one_way_trim_ratio_penalty: float = 0.0,
    turnover_per_add_threshold: float = 0.0,
    turnover_per_add_penalty: float = 0.0,
    low_activity_coverage_threshold: float = 0.0,
    low_activity_penalty: float = 0.0,
    soft_no_trade_per_1k_threshold: float = 0.0,
    soft_no_trade_per_1k_penalty: float = 0.0,
    role_concentration_threshold: float = 0.0,
    role_concentration_min_add_events: int = 0,
    role_concentration_penalty: float = 0.0,
    base_dominance_threshold: float = 0.0,
    base_dominance_min_add_events: int = 0,
    base_dominance_min_train_return_pct: float | None = None,
    base_dominance_max_train_return_pct: float | None = None,
    base_dominance_min_train_drawdown_pct: float | None = None,
    base_dominance_max_train_drawdown_pct: float | None = None,
    base_dominance_min_train_cost_drag_pct: float | None = None,
    base_dominance_max_train_cost_drag_pct: float | None = None,
    base_dominance_penalty: float = 0.0,
    structural_flag_min_train_return_pct: float = 0.0,
    structural_flag_penalty: float = 0.0,
    high_train_flag_min_return_pct: float = 0.0,
    high_train_flag_penalty: float = 0.0,
    low_train_max_unit_min_return_pct: float | None = None,
    low_train_max_unit_max_return_pct: float | None = None,
    low_train_max_unit_threshold: float = 0.0,
    low_train_max_unit_penalty: float = 0.0,
    one_way_loss_fuse_bonus: float = 0.0,
    low_unit_reversal_bonus: float = 0.0,
    low_unit_reversal_max_units: float = 0.0,
    low_unit_reversal_min_switch_units: float = 0.0,
    low_unit_reversal_min_train_return_pct: float | None = None,
    low_unit_reversal_max_train_return_pct: float | None = None,
    low_unit_reversal_min_train_drawdown_pct: float | None = None,
    low_unit_reversal_max_train_drawdown_pct: float | None = None,
    low_unit_reversal_min_one_way_trim_per_add: float = 0.0,
    low_unit_reversal_max_one_way_trim_per_add: float = 0.0,
    drawdown_reversal_bonus: float = 0.0,
    drawdown_reversal_max_units: float = 0.0,
    drawdown_reversal_min_switch_units: float = 0.0,
    drawdown_reversal_min_train_return_pct: float | None = None,
    drawdown_reversal_max_train_return_pct: float | None = None,
    drawdown_reversal_min_train_drawdown_pct: float | None = None,
    drawdown_reversal_max_train_drawdown_pct: float | None = None,
    drawdown_reversal_min_train_cost_drag_pct: float | None = None,
    drawdown_reversal_max_train_cost_drag_pct: float | None = None,
    drawdown_reversal_min_one_way_trim_per_add: float = 0.0,
    drawdown_reversal_max_one_way_trim_per_add: float = 0.0,
    drawdown_reversal_min_turnover_per_add: float = 0.0,
    drawdown_reversal_max_turnover_per_add: float = 0.0,
    short_hold_structural_bonus: float = 0.0,
    short_hold_max_bars: int = 0,
    short_hold_min_train_return_pct: float | None = None,
    short_hold_max_train_return_pct: float | None = None,
    short_hold_min_train_drawdown_pct: float | None = None,
    short_hold_max_train_drawdown_pct: float | None = None,
    short_hold_min_max_units: float = 0.0,
    short_hold_max_max_units: float = 0.0,
    short_hold_min_one_way_trim_per_add: float = 0.0,
    short_hold_max_one_way_trim_per_add: float = 0.0,
    short_hold_min_turnover_per_add: float = 0.0,
    short_hold_max_turnover_per_add: float = 0.0,
    fast_defense_structural_penalty: float = 0.0,
    fast_defense_max_cooldown_bars: int = 0,
    fast_defense_min_train_return_pct: float = 0.0,
    fast_defense_min_one_way_trim_per_add: float = 0.0,
    fast_defense_min_turnover_per_add: float = 0.0,
) -> float:
    diagnostics = dict(result.get("event_diagnostics") or {})
    flags = diagnostics.get("flags") or []
    ratios = dict(diagnostics.get("ratios") or {})
    mdd = float(result.get("max_drawdown_pct") or 100.0)
    cost_drag = float(result.get("estimated_cost_drag_pct") or 0.0)
    one_way_trim_ratio = float(ratios.get("one_way_forced_trim_per_add") or 0.0)
    turnover_per_add = float(ratios.get("turnover_events_per_add") or 0.0)
    add_events = int(diagnostics.get("add_events") or result.get("trade_like_events") or 0)
    add_by_role = {
        str(role): int(count)
        for role, count in dict(diagnostics.get("add_by_role") or {}).items()
        if str(role) not in {"", "unknown"}
    }
    known_role_adds = sum(add_by_role.values())
    dominant_add_role, dominant_add_role_count = (
        max(add_by_role.items(), key=lambda item: (int(item[1]), str(item[0])))
        if add_by_role
        else ("none", 0)
    )
    diagnostic_dominant_add_role = str(diagnostics.get("dominant_add_role") or "")
    if diagnostic_dominant_add_role and diagnostic_dominant_add_role != "none":
        dominant_add_role = diagnostic_dominant_add_role
    max_role_add_share = diagnostics.get("max_role_add_share")
    if max_role_add_share is None:
        max_role_add_share = (
            dominant_add_role_count / max(known_role_adds, 1)
            if known_role_adds > 0
            else 0.0
        )
    max_role_add_share = float(max_role_add_share or 0.0)
    add_role_share = dict(diagnostics.get("add_role_share") or {})
    base_add_share = (
        float(add_role_share.get("base") or 0.0)
        if "base" in add_role_share
        else float(add_by_role.get("base", 0)) / max(known_role_adds, 1)
        if known_role_adds > 0
        else 0.0
    )
    diagnostic_thresholds = dict(diagnostics.get("diagnostic_thresholds") or {})
    expected_add_events = int(diagnostic_thresholds.get("expected_add_events") or 0)
    add_event_coverage = (
        add_events / max(expected_add_events, 1)
        if expected_add_events > 0
        else 1.0
    )
    event_counts = dict(result.get("event_counts") or {})
    soft_no_trade_blockers = int(event_counts.get("no_trade_MC12_low_confluence") or 0) + int(
        event_counts.get("no_trade_MC04_no_clear_first_touch") or 0
    )
    train_bar_count = _result_regime_bar_count(result)
    soft_no_trade_per_1k = (
        soft_no_trade_blockers / max(train_bar_count, 1) * 1000.0
        if train_bar_count > 0
        else 0.0
    )
    config = dict(result.get("config") or {})
    impulse_penalty = (
        max(float(impulse_score_penalty), 0.0)
        if float(config.get("one_way_impulse_probe_units") or 0.0) > 0.0
        else 0.0
    )
    btc_rotation_penalty = (
        max(float(btc_rotation_score_penalty), 0.0)
        if (
            float(config.get("scenario_flip_units") or 0.0) > 0.0
            or float(config.get("winner_pyramid_units") or 0.0) > 0.0
        )
        else 0.0
    )
    base_score = float(result.get("score") or -1e9)
    if float(score_cap) > 0.0:
        base_score = min(base_score, float(score_cap))
    structural_flags = {
        "side_imbalance",
        "role_concentration",
        "one_way_forced_trim_overuse",
        "high_turnover_per_add",
    }
    train_return = float(result.get("total_return_pct") or 0.0)
    structural_penalty = 0.0
    if (
        float(structural_flag_penalty) > 0.0
        and train_return >= float(structural_flag_min_train_return_pct)
    ):
        structural_penalty = max(float(structural_flag_penalty), 0.0) * sum(
            1 for flag in flags if str(flag) in structural_flags
        )
    high_train_flag_penalty_total = 0.0
    if (
        float(high_train_flag_penalty) > 0.0
        and train_return >= float(high_train_flag_min_return_pct)
    ):
        high_train_flag_penalty_total = max(float(high_train_flag_penalty), 0.0) * len(flags)
    role_concentration_penalty_total = 0.0
    if (
        max(float(role_concentration_threshold), 0.0) > 0.0
        and max(float(role_concentration_penalty), 0.0) > 0.0
        and add_events >= max(int(role_concentration_min_add_events), 0)
        and max_role_add_share > float(role_concentration_threshold)
    ):
        role_concentration_penalty_total = (
            max_role_add_share - float(role_concentration_threshold)
        ) * max(float(role_concentration_penalty), 0.0)
    base_dominance_penalty_total = 0.0
    if (
        max(float(base_dominance_threshold), 0.0) > 0.0
        and max(float(base_dominance_penalty), 0.0) > 0.0
        and add_events >= max(int(base_dominance_min_add_events), 0)
        and dominant_add_role == "base"
        and base_add_share > float(base_dominance_threshold)
        and _range_allowed(
            train_return,
            base_dominance_min_train_return_pct,
            base_dominance_max_train_return_pct,
        )
        and _range_allowed(
            mdd,
            base_dominance_min_train_drawdown_pct,
            base_dominance_max_train_drawdown_pct,
        )
        and _range_allowed(
            cost_drag,
            base_dominance_min_train_cost_drag_pct,
            base_dominance_max_train_cost_drag_pct,
        )
    ):
        base_dominance_penalty_total = (
            base_add_share - float(base_dominance_threshold)
        ) * max(float(base_dominance_penalty), 0.0)
    low_train_max_unit_penalty_total = 0.0
    max_possible_units = float(config.get("max_possible_units") or 0.0)
    low_train_min_ok = (
        low_train_max_unit_min_return_pct is None
        or train_return >= float(low_train_max_unit_min_return_pct)
    )
    low_train_max_ok = (
        low_train_max_unit_max_return_pct is None
        or train_return <= float(low_train_max_unit_max_return_pct)
    )
    if (
        max(float(low_train_max_unit_penalty), 0.0) > 0.0
        and low_train_min_ok
        and low_train_max_ok
        and max_possible_units > max(float(low_train_max_unit_threshold), 0.0)
    ):
        low_train_max_unit_penalty_total = max(float(low_train_max_unit_penalty), 0.0)
    loss_fuse_bonus = 0.0
    loss_fuse_size_mult = config.get("one_way_loss_fuse_size_mult")
    loss_fuse_size_mult = 1.0 if loss_fuse_size_mult is None else float(loss_fuse_size_mult)
    if (
        max(float(one_way_loss_fuse_bonus), 0.0) > 0.0
        and float(config.get("one_way_loss_fuse_min_adverse_reaction") or 0.0) > 0.0
        and int(config.get("one_way_loss_fuse_cooldown_bars") or 0) > 0
        and loss_fuse_size_mult < 1.0 - 1e-12
    ):
        loss_fuse_bonus = max(float(one_way_loss_fuse_bonus), 0.0)
    low_unit_reversal_bonus_total = 0.0
    reversal_switch_units = float(config.get("one_way_reversal_switch_units") or 0.0)
    low_unit_reversal_min_return_ok = (
        low_unit_reversal_min_train_return_pct is None
        or train_return >= float(low_unit_reversal_min_train_return_pct)
    )
    low_unit_reversal_max_return_ok = (
        low_unit_reversal_max_train_return_pct is None
        or train_return <= float(low_unit_reversal_max_train_return_pct)
    )
    low_unit_reversal_min_drawdown_ok = (
        low_unit_reversal_min_train_drawdown_pct is None
        or mdd >= float(low_unit_reversal_min_train_drawdown_pct)
    )
    low_unit_reversal_max_drawdown_ok = (
        low_unit_reversal_max_train_drawdown_pct is None
        or mdd <= float(low_unit_reversal_max_train_drawdown_pct)
    )
    low_unit_reversal_max_trim = float(low_unit_reversal_max_one_way_trim_per_add)
    low_unit_reversal_trim_ok = (
        one_way_trim_ratio >= float(low_unit_reversal_min_one_way_trim_per_add)
        and (low_unit_reversal_max_trim <= 0.0 or one_way_trim_ratio <= low_unit_reversal_max_trim)
    )
    if (
        max(float(low_unit_reversal_bonus), 0.0) > 0.0
        and float(low_unit_reversal_max_units) > 0.0
        and max_possible_units <= float(low_unit_reversal_max_units) + 1e-12
        and reversal_switch_units >= float(low_unit_reversal_min_switch_units)
        and low_unit_reversal_min_return_ok
        and low_unit_reversal_max_return_ok
        and low_unit_reversal_min_drawdown_ok
        and low_unit_reversal_max_drawdown_ok
        and low_unit_reversal_trim_ok
    ):
        low_unit_reversal_bonus_total = max(float(low_unit_reversal_bonus), 0.0)
    drawdown_reversal_bonus_total = 0.0
    drawdown_reversal_min_return_ok = (
        drawdown_reversal_min_train_return_pct is None
        or train_return >= float(drawdown_reversal_min_train_return_pct)
    )
    drawdown_reversal_max_return_ok = (
        drawdown_reversal_max_train_return_pct is None
        or train_return <= float(drawdown_reversal_max_train_return_pct)
    )
    drawdown_reversal_min_drawdown_ok = (
        drawdown_reversal_min_train_drawdown_pct is None
        or mdd >= float(drawdown_reversal_min_train_drawdown_pct)
    )
    drawdown_reversal_max_drawdown_ok = (
        drawdown_reversal_max_train_drawdown_pct is None
        or mdd <= float(drawdown_reversal_max_train_drawdown_pct)
    )
    drawdown_reversal_min_cost_ok = (
        drawdown_reversal_min_train_cost_drag_pct is None
        or cost_drag >= float(drawdown_reversal_min_train_cost_drag_pct)
    )
    drawdown_reversal_max_cost_ok = (
        drawdown_reversal_max_train_cost_drag_pct is None
        or cost_drag <= float(drawdown_reversal_max_train_cost_drag_pct)
    )
    drawdown_reversal_max_trim = float(drawdown_reversal_max_one_way_trim_per_add)
    drawdown_reversal_trim_ok = (
        one_way_trim_ratio >= float(drawdown_reversal_min_one_way_trim_per_add)
        and (drawdown_reversal_max_trim <= 0.0 or one_way_trim_ratio <= drawdown_reversal_max_trim)
    )
    drawdown_reversal_max_turnover = float(drawdown_reversal_max_turnover_per_add)
    drawdown_reversal_turnover_ok = turnover_per_add >= float(
        drawdown_reversal_min_turnover_per_add
    ) and (
        drawdown_reversal_max_turnover <= 0.0
        or turnover_per_add <= drawdown_reversal_max_turnover
    )
    if (
        max(float(drawdown_reversal_bonus), 0.0) > 0.0
        and float(drawdown_reversal_max_units) > 0.0
        and max_possible_units <= float(drawdown_reversal_max_units) + 1e-12
        and reversal_switch_units >= float(drawdown_reversal_min_switch_units)
        and drawdown_reversal_min_return_ok
        and drawdown_reversal_max_return_ok
        and drawdown_reversal_min_drawdown_ok
        and drawdown_reversal_max_drawdown_ok
        and drawdown_reversal_min_cost_ok
        and drawdown_reversal_max_cost_ok
        and drawdown_reversal_trim_ok
        and drawdown_reversal_turnover_ok
    ):
        drawdown_reversal_bonus_total = max(float(drawdown_reversal_bonus), 0.0)
    short_hold_bonus_total = 0.0
    max_hold_bars = int(config.get("max_hold_bars") or 0)
    short_hold_min_return_ok = (
        short_hold_min_train_return_pct is None
        or train_return >= float(short_hold_min_train_return_pct)
    )
    short_hold_max_return_ok = (
        short_hold_max_train_return_pct is None
        or train_return <= float(short_hold_max_train_return_pct)
    )
    short_hold_min_drawdown_ok = (
        short_hold_min_train_drawdown_pct is None
        or mdd >= float(short_hold_min_train_drawdown_pct)
    )
    short_hold_max_drawdown_ok = (
        short_hold_max_train_drawdown_pct is None
        or mdd <= float(short_hold_max_train_drawdown_pct)
    )
    short_hold_max_units = float(short_hold_max_max_units)
    short_hold_units_ok = max_possible_units >= float(short_hold_min_max_units) and (
        short_hold_max_units <= 0.0 or max_possible_units <= short_hold_max_units
    )
    short_hold_max_trim = float(short_hold_max_one_way_trim_per_add)
    short_hold_trim_ok = one_way_trim_ratio >= float(short_hold_min_one_way_trim_per_add) and (
        short_hold_max_trim <= 0.0 or one_way_trim_ratio <= short_hold_max_trim
    )
    short_hold_max_turnover = float(short_hold_max_turnover_per_add)
    short_hold_turnover_ok = turnover_per_add >= float(short_hold_min_turnover_per_add) and (
        short_hold_max_turnover <= 0.0 or turnover_per_add <= short_hold_max_turnover
    )
    if (
        max(float(short_hold_structural_bonus), 0.0) > 0.0
        and int(short_hold_max_bars) > 0
        and 0 < max_hold_bars <= int(short_hold_max_bars)
        and short_hold_min_return_ok
        and short_hold_max_return_ok
        and short_hold_min_drawdown_ok
        and short_hold_max_drawdown_ok
        and short_hold_units_ok
        and short_hold_trim_ok
        and short_hold_turnover_ok
    ):
        short_hold_bonus_total = max(float(short_hold_structural_bonus), 0.0)
    fast_defense_penalty_total = 0.0
    defensive_cooldown = int(config.get("defensive_trim_cooldown_bars") or 0)
    if (
        max(float(fast_defense_structural_penalty), 0.0) > 0.0
        and int(fast_defense_max_cooldown_bars) > 0
        and 0 < defensive_cooldown <= int(fast_defense_max_cooldown_bars)
        and train_return >= float(fast_defense_min_train_return_pct)
        and one_way_trim_ratio >= float(fast_defense_min_one_way_trim_per_add)
        and turnover_per_add >= float(fast_defense_min_turnover_per_add)
    ):
        fast_defense_penalty_total = max(float(fast_defense_structural_penalty), 0.0)
    stress_floor_penalty_total = 0.0
    if (
        float(stress_cost_multiplier) > 0.0
        and float(stress_floor_gap_penalty) > 0.0
    ):
        gross_return = float(result.get("gross_return_pct_before_costs") or train_return + cost_drag)
        stressed_return = (
            gross_return
            - max(float(stress_cost_multiplier), 0.0) * cost_drag
            - max(float(stress_funding_proxy_pct), 0.0)
        )
        stress_gap = max(float(stress_min_return_floor_pct) - stressed_return, 0.0)
        stress_floor_penalty_total = stress_gap * max(float(stress_floor_gap_penalty), 0.0)
    cost_to_gross_penalty_total = 0.0
    if max(float(cost_to_gross_threshold), 0.0) > 0.0 and max(float(cost_to_gross_penalty), 0.0) > 0.0:
        gross_return = float(result.get("gross_return_pct_before_costs") or train_return + cost_drag)
        if gross_return > 1e-12:
            cost_to_gross = cost_drag / gross_return
            cost_to_gross_penalty_total = _soft_excess_penalty(
                cost_to_gross,
                float(cost_to_gross_threshold),
                float(cost_to_gross_penalty),
            )
    reaction_usd_risk_penalty_total = 0.0
    reaction_usd = float(config.get("reaction_usd") or 0.0)
    reaction_usd_cap = max(float(max_reaction_usd), 0.0)
    if reaction_usd_cap > 0.0 and reaction_usd > reaction_usd_cap:
        return -1e9
    reaction_usd_threshold = max(float(reaction_usd_risk_threshold), 0.0)
    reaction_usd_penalty = max(float(reaction_usd_risk_penalty), 0.0)
    if reaction_usd_threshold > 0.0 and reaction_usd_penalty > 0.0 and reaction_usd >= reaction_usd_threshold:
        risk_triggers: list[bool] = []
        if float(reaction_usd_risk_min_train_drawdown_pct) > 0.0:
            risk_triggers.append(mdd >= float(reaction_usd_risk_min_train_drawdown_pct))
        if float(reaction_usd_risk_min_turnover_per_add) > 0.0:
            risk_triggers.append(turnover_per_add >= float(reaction_usd_risk_min_turnover_per_add))
        if float(reaction_usd_risk_min_one_way_trim_per_add) > 0.0:
            risk_triggers.append(one_way_trim_ratio >= float(reaction_usd_risk_min_one_way_trim_per_add))
        if float(reaction_usd_risk_min_cost_drag_pct) > 0.0:
            risk_triggers.append(cost_drag >= float(reaction_usd_risk_min_cost_drag_pct))
        if not risk_triggers or any(risk_triggers):
            reaction_usd_risk_penalty_total = reaction_usd_penalty
    return (
        base_score
        + loss_fuse_bonus
        + low_unit_reversal_bonus_total
        + drawdown_reversal_bonus_total
        + short_hold_bonus_total
        - max(float(flag_penalty), 0.0) * len(flags)
        - 0.005 * max(mdd - 35.0, 0.0)
        - 0.0005 * max(cost_drag - 250.0, 0.0)
        - _soft_excess_penalty(mdd, float(mdd_soft_threshold_pct), float(mdd_soft_penalty))
        - _soft_excess_penalty(cost_drag, float(cost_soft_threshold_pct), float(cost_soft_penalty))
        - _soft_excess_penalty(
            one_way_trim_ratio,
            float(one_way_trim_ratio_threshold),
            float(one_way_trim_ratio_penalty),
        )
        - _soft_excess_penalty(
            turnover_per_add,
            float(turnover_per_add_threshold),
            float(turnover_per_add_penalty),
        )
        - max(float(low_activity_coverage_threshold) - add_event_coverage, 0.0)
        * max(float(low_activity_penalty), 0.0)
        - _soft_excess_penalty(
            soft_no_trade_per_1k,
            float(soft_no_trade_per_1k_threshold),
            float(soft_no_trade_per_1k_penalty),
        )
        - structural_penalty
        - high_train_flag_penalty_total
        - role_concentration_penalty_total
        - base_dominance_penalty_total
        - low_train_max_unit_penalty_total
        - fast_defense_penalty_total
        - stress_floor_penalty_total
        - cost_to_gross_penalty_total
        - reaction_usd_risk_penalty_total
        - impulse_penalty
        - btc_rotation_penalty
    )


def _selection_score_from_args(result: dict[str, Any], args: argparse.Namespace) -> float:
    return _selection_score(
        result,
        impulse_score_penalty=float(args.impulse_selection_score_penalty),
        btc_rotation_score_penalty=float(args.btc_rotation_selection_score_penalty),
        flag_penalty=float(args.selection_flag_penalty),
        score_cap=float(args.selection_score_cap),
        mdd_soft_threshold_pct=float(args.selection_mdd_soft_threshold_pct),
        mdd_soft_penalty=float(args.selection_mdd_soft_penalty),
        cost_soft_threshold_pct=float(args.selection_cost_soft_threshold_pct),
        cost_soft_penalty=float(args.selection_cost_soft_penalty),
        stress_cost_multiplier=float(args.selection_stress_cost_multiplier),
        stress_funding_proxy_pct=float(args.selection_stress_funding_proxy_pct),
        stress_min_return_floor_pct=float(args.selection_stress_min_return_floor_pct),
        stress_floor_gap_penalty=float(args.selection_stress_floor_gap_penalty),
        cost_to_gross_threshold=float(args.selection_cost_to_gross_threshold),
        cost_to_gross_penalty=float(args.selection_cost_to_gross_penalty),
        reaction_usd_risk_threshold=float(args.selection_reaction_usd_risk_threshold),
        reaction_usd_risk_penalty=float(args.selection_reaction_usd_risk_penalty),
        reaction_usd_risk_min_train_drawdown_pct=float(
            args.selection_reaction_usd_risk_min_train_drawdown_pct
        ),
        reaction_usd_risk_min_turnover_per_add=float(
            args.selection_reaction_usd_risk_min_turnover_per_add
        ),
        reaction_usd_risk_min_one_way_trim_per_add=float(
            args.selection_reaction_usd_risk_min_one_way_trim_per_add
        ),
        reaction_usd_risk_min_cost_drag_pct=float(args.selection_reaction_usd_risk_min_cost_drag_pct),
        max_reaction_usd=float(args.selection_max_reaction_usd),
        one_way_trim_ratio_threshold=float(args.selection_one_way_trim_ratio_threshold),
        one_way_trim_ratio_penalty=float(args.selection_one_way_trim_ratio_penalty),
        turnover_per_add_threshold=float(args.selection_turnover_per_add_threshold),
        turnover_per_add_penalty=float(args.selection_turnover_per_add_penalty),
        low_activity_coverage_threshold=float(args.selection_low_activity_coverage_threshold),
        low_activity_penalty=float(args.selection_low_activity_penalty),
        soft_no_trade_per_1k_threshold=float(args.selection_soft_no_trade_per_1k_threshold),
        soft_no_trade_per_1k_penalty=float(args.selection_soft_no_trade_per_1k_penalty),
        role_concentration_threshold=float(args.selection_role_concentration_threshold),
        role_concentration_min_add_events=int(args.selection_role_concentration_min_add_events),
        role_concentration_penalty=float(args.selection_role_concentration_penalty),
        base_dominance_threshold=float(args.selection_base_dominance_threshold),
        base_dominance_min_add_events=int(args.selection_base_dominance_min_add_events),
        base_dominance_min_train_return_pct=args.selection_base_dominance_min_train_return_pct,
        base_dominance_max_train_return_pct=args.selection_base_dominance_max_train_return_pct,
        base_dominance_min_train_drawdown_pct=args.selection_base_dominance_min_train_drawdown_pct,
        base_dominance_max_train_drawdown_pct=args.selection_base_dominance_max_train_drawdown_pct,
        base_dominance_min_train_cost_drag_pct=args.selection_base_dominance_min_train_cost_drag_pct,
        base_dominance_max_train_cost_drag_pct=args.selection_base_dominance_max_train_cost_drag_pct,
        base_dominance_penalty=float(args.selection_base_dominance_penalty),
        structural_flag_min_train_return_pct=float(args.selection_structural_flag_min_train_return_pct),
        structural_flag_penalty=float(args.selection_structural_flag_penalty),
        high_train_flag_min_return_pct=float(args.selection_high_train_flag_min_return_pct),
        high_train_flag_penalty=float(args.selection_high_train_flag_penalty),
        low_train_max_unit_min_return_pct=args.selection_low_train_max_unit_min_return_pct,
        low_train_max_unit_max_return_pct=args.selection_low_train_max_unit_max_return_pct,
        low_train_max_unit_threshold=float(args.selection_low_train_max_unit_threshold),
        low_train_max_unit_penalty=float(args.selection_low_train_max_unit_penalty),
        one_way_loss_fuse_bonus=float(args.selection_one_way_loss_fuse_bonus),
        low_unit_reversal_bonus=float(args.selection_low_unit_reversal_bonus),
        low_unit_reversal_max_units=float(args.selection_low_unit_reversal_max_units),
        low_unit_reversal_min_switch_units=float(args.selection_low_unit_reversal_min_switch_units),
        low_unit_reversal_min_train_return_pct=args.selection_low_unit_reversal_min_train_return_pct,
        low_unit_reversal_max_train_return_pct=args.selection_low_unit_reversal_max_train_return_pct,
        low_unit_reversal_min_train_drawdown_pct=args.selection_low_unit_reversal_min_train_drawdown_pct,
        low_unit_reversal_max_train_drawdown_pct=args.selection_low_unit_reversal_max_train_drawdown_pct,
        low_unit_reversal_min_one_way_trim_per_add=float(
            args.selection_low_unit_reversal_min_one_way_trim_per_add
        ),
        low_unit_reversal_max_one_way_trim_per_add=float(
            args.selection_low_unit_reversal_max_one_way_trim_per_add
        ),
        drawdown_reversal_bonus=float(args.selection_drawdown_reversal_bonus),
        drawdown_reversal_max_units=float(args.selection_drawdown_reversal_max_units),
        drawdown_reversal_min_switch_units=float(args.selection_drawdown_reversal_min_switch_units),
        drawdown_reversal_min_train_return_pct=args.selection_drawdown_reversal_min_train_return_pct,
        drawdown_reversal_max_train_return_pct=args.selection_drawdown_reversal_max_train_return_pct,
        drawdown_reversal_min_train_drawdown_pct=(
            args.selection_drawdown_reversal_min_train_drawdown_pct
        ),
        drawdown_reversal_max_train_drawdown_pct=(
            args.selection_drawdown_reversal_max_train_drawdown_pct
        ),
        drawdown_reversal_min_train_cost_drag_pct=(
            args.selection_drawdown_reversal_min_train_cost_drag_pct
        ),
        drawdown_reversal_max_train_cost_drag_pct=(
            args.selection_drawdown_reversal_max_train_cost_drag_pct
        ),
        drawdown_reversal_min_one_way_trim_per_add=float(
            args.selection_drawdown_reversal_min_one_way_trim_per_add
        ),
        drawdown_reversal_max_one_way_trim_per_add=float(
            args.selection_drawdown_reversal_max_one_way_trim_per_add
        ),
        drawdown_reversal_min_turnover_per_add=float(
            args.selection_drawdown_reversal_min_turnover_per_add
        ),
        drawdown_reversal_max_turnover_per_add=float(
            args.selection_drawdown_reversal_max_turnover_per_add
        ),
        short_hold_structural_bonus=float(args.selection_short_hold_structural_bonus),
        short_hold_max_bars=int(args.selection_short_hold_max_bars),
        short_hold_min_train_return_pct=args.selection_short_hold_min_train_return_pct,
        short_hold_max_train_return_pct=args.selection_short_hold_max_train_return_pct,
        short_hold_min_train_drawdown_pct=args.selection_short_hold_min_train_drawdown_pct,
        short_hold_max_train_drawdown_pct=args.selection_short_hold_max_train_drawdown_pct,
        short_hold_min_max_units=float(args.selection_short_hold_min_max_units),
        short_hold_max_max_units=float(args.selection_short_hold_max_max_units),
        short_hold_min_one_way_trim_per_add=float(
            args.selection_short_hold_min_one_way_trim_per_add
        ),
        short_hold_max_one_way_trim_per_add=float(
            args.selection_short_hold_max_one_way_trim_per_add
        ),
        short_hold_min_turnover_per_add=float(args.selection_short_hold_min_turnover_per_add),
        short_hold_max_turnover_per_add=float(args.selection_short_hold_max_turnover_per_add),
        fast_defense_structural_penalty=float(args.selection_fast_defense_structural_penalty),
        fast_defense_max_cooldown_bars=int(args.selection_fast_defense_max_cooldown_bars),
        fast_defense_min_train_return_pct=float(args.selection_fast_defense_min_train_return_pct),
        fast_defense_min_one_way_trim_per_add=float(
            args.selection_fast_defense_min_one_way_trim_per_add
        ),
        fast_defense_min_turnover_per_add=float(args.selection_fast_defense_min_turnover_per_add),
    )


def _selection_train_stressed_return_pct(
    result: dict[str, Any],
    args: argparse.Namespace,
) -> float | None:
    multiplier = max(float(args.selection_stress_cost_multiplier), 0.0)
    if multiplier <= 0.0:
        return None
    train_return = float(result.get("total_return_pct") or 0.0)
    cost_drag = float(result.get("estimated_cost_drag_pct") or 0.0)
    gross_return = float(result.get("gross_return_pct_before_costs") or train_return + cost_drag)
    return gross_return - multiplier * cost_drag - max(float(args.selection_stress_funding_proxy_pct), 0.0)


def _raw_train_selection_key(result: dict[str, Any]) -> tuple[float, float, float]:
    return (
        float(result.get("score") or -1e9),
        float(result.get("cagr_pct") or -1e9),
        -float(result.get("max_drawdown_pct") or math.inf),
    )


def _train_return_selection_key(result: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        float(result.get("total_return_pct") or -1e9),
        float(result.get("score") or -1e9),
        float(result.get("cagr_pct") or -1e9),
        -float(result.get("max_drawdown_pct") or math.inf),
    )


def _apply_unresolved_stress_raw_leader_guard(
    train_results: list[dict[str, Any]],
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not train_results or not bool(args.selection_stress_unresolved_keep_raw_leader):
        return train_results, None
    if float(args.selection_stress_min_return_floor_pct) <= 0.0:
        return train_results, None
    stressed_returns = [
        _selection_train_stressed_return_pct(result, args)
        for result in train_results
    ]
    known_stressed_returns = [value for value in stressed_returns if value is not None]
    if not known_stressed_returns:
        return train_results, None
    stress_floor = float(args.selection_stress_min_return_floor_pct)
    if any(value >= stress_floor for value in known_stressed_returns):
        return train_results, {
            "applied": False,
            "reason": "stress_floor_candidate_available",
            "stress_floor_pct": round(stress_floor, 6),
            "max_stressed_return_pct": round(max(known_stressed_returns), 6),
        }

    selected = train_results[0]
    leader_metric = str(getattr(args, "selection_stress_unresolved_leader_metric", "raw_score"))
    leader_key = _train_return_selection_key if leader_metric == "train_return" else _raw_train_selection_key
    leader = max(train_results, key=leader_key)
    if leader is selected:
        return train_results, {
            "applied": False,
            "reason": "selected_is_raw_leader",
            "leader_metric": leader_metric,
            "stress_floor_pct": round(stress_floor, 6),
            "selected_stressed_return_pct": round(known_stressed_returns[0], 6),
        }

    selected_return = float(selected.get("total_return_pct") or 0.0)
    leader_return = float(leader.get("total_return_pct") or 0.0)
    return_giveback = leader_return - selected_return
    giveback_threshold = max(float(args.selection_stress_unresolved_return_giveback_pct), 0.0)
    threshold_reasons = ["default"]
    low_return_max = getattr(args, "selection_stress_unresolved_low_return_max_selected_pct", None)
    low_return_giveback = getattr(args, "selection_stress_unresolved_low_return_giveback_pct", None)
    low_return_band_active = (
        low_return_max is not None
        and low_return_giveback is not None
        and selected_return <= float(low_return_max)
    )
    effective_giveback_threshold = giveback_threshold
    if low_return_band_active:
        effective_giveback_threshold = min(
            effective_giveback_threshold,
            max(float(low_return_giveback), 0.0),
        )
        threshold_reasons.append("low_return_band")
    dd_min_selected = getattr(
        args,
        "selection_stress_unresolved_drawdown_rescue_min_selected_pct",
        None,
    )
    dd_max_selected = getattr(
        args,
        "selection_stress_unresolved_drawdown_rescue_max_selected_pct",
        None,
    )
    dd_min_leader = getattr(
        args,
        "selection_stress_unresolved_drawdown_rescue_min_leader_dd_pct",
        None,
    )
    dd_giveback = getattr(
        args,
        "selection_stress_unresolved_drawdown_rescue_giveback_pct",
        None,
    )
    leader_drawdown = float(leader.get("max_drawdown_pct") or 0.0)
    drawdown_rescue_active = (
        dd_min_selected is not None
        and dd_max_selected is not None
        and dd_min_leader is not None
        and dd_giveback is not None
        and selected_return >= float(dd_min_selected)
        and selected_return <= float(dd_max_selected)
        and leader_drawdown >= float(dd_min_leader)
    )
    if drawdown_rescue_active:
        effective_giveback_threshold = min(
            effective_giveback_threshold,
            max(float(dd_giveback), 0.0),
        )
        threshold_reasons.append("drawdown_rescue")
    if return_giveback < effective_giveback_threshold:
        return train_results, {
            "applied": False,
            "reason": "return_giveback_below_threshold",
            "leader_metric": leader_metric,
            "stress_floor_pct": round(stress_floor, 6),
            "return_giveback_pct": round(return_giveback, 6),
            "return_giveback_threshold_pct": round(effective_giveback_threshold, 6),
            "low_return_band_active": low_return_band_active,
            "drawdown_rescue_active": drawdown_rescue_active,
            "threshold_reasons": threshold_reasons,
        }

    leader_stressed_return = _selection_train_stressed_return_pct(leader, args)
    selected_stressed_return = _selection_train_stressed_return_pct(selected, args)
    reordered = [leader] + [result for result in train_results if result is not leader]
    return reordered, {
        "applied": True,
        "reason": "unresolved_stress_preserve_raw_leader",
        "leader_metric": leader_metric,
        "stress_floor_pct": round(stress_floor, 6),
        "return_giveback_pct": round(return_giveback, 6),
        "return_giveback_threshold_pct": round(effective_giveback_threshold, 6),
        "low_return_band_active": low_return_band_active,
        "drawdown_rescue_active": drawdown_rescue_active,
        "threshold_reasons": threshold_reasons,
        "selected_model_id_before_guard": selected.get("model_id"),
        "raw_leader_model_id": leader.get("model_id"),
        "selected_train_return_pct_before_guard": round(selected_return, 6),
        "raw_leader_train_return_pct": round(leader_return, 6),
        "raw_leader_drawdown_pct": round(leader_drawdown, 6),
        "selected_stressed_return_pct_before_guard": (
            None if selected_stressed_return is None else round(selected_stressed_return, 6)
        ),
        "raw_leader_stressed_return_pct": (
            None if leader_stressed_return is None else round(leader_stressed_return, 6)
        ),
        "max_stressed_return_pct": round(max(known_stressed_returns), 6),
    }


def _apply_negative_train_distribution_rescue_guard(
    train_results: list[dict[str, Any]],
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not train_results or not bool(
        getattr(args, "selection_negative_train_distribution_rescue", False)
    ):
        return train_results, None
    selected = train_results[0]
    selected_return = float(selected.get("total_return_pct") or 0.0)
    if not _range_allowed(
        selected_return,
        getattr(args, "selection_negative_train_distribution_min_selected_return_pct", None),
        getattr(args, "selection_negative_train_distribution_max_selected_return_pct", None),
    ):
        return train_results, {
            "applied": False,
            "reason": "negative_train_distribution_selected_return_out_of_band",
            "selected_train_return_pct": round(selected_return, 6),
        }
    recipes = [
        recipe
        for recipe in _legacy_after_selection_recipes(args)
        if str(recipe.get("name") or "") == "negative_train_distribution_probe"
    ]
    if not recipes:
        return train_results, {
            "applied": False,
            "reason": "negative_train_distribution_recipe_disabled",
        }
    if any(_legacy_recipe_allowed(selected, recipe) for recipe in recipes):
        return train_results, {
            "applied": False,
            "reason": "selected_already_matches_negative_train_distribution",
            "selected_model_id": selected.get("model_id"),
            "selected_train_return_pct": round(selected_return, 6),
        }
    candidate_matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for candidate in train_results[1:]:
        for recipe in recipes:
            if _legacy_recipe_allowed(candidate, recipe):
                candidate_matches.append((candidate, recipe))
                break
    if not candidate_matches:
        return train_results, {
            "applied": False,
            "reason": "negative_train_distribution_candidate_not_found",
            "selected_model_id": selected.get("model_id"),
            "selected_train_return_pct": round(selected_return, 6),
        }
    candidate, recipe = max(
        candidate_matches,
        key=lambda item: (
            float(item[0].get("walk_forward_selection_score") or -1e9),
            float(item[0].get("score") or -1e9),
            float(item[0].get("total_return_pct") or -1e9),
            -float(item[0].get("max_drawdown_pct") or math.inf),
        ),
    )
    candidate_return = float(candidate.get("total_return_pct") or 0.0)
    return_giveback = selected_return - candidate_return
    max_giveback = max(
        0.0,
        float(getattr(args, "selection_negative_train_distribution_max_return_giveback_pct", 0.0)),
    )
    if return_giveback > max_giveback:
        return train_results, {
            "applied": False,
            "reason": "negative_train_distribution_return_giveback_above_threshold",
            "selected_model_id": selected.get("model_id"),
            "candidate_model_id": candidate.get("model_id"),
            "selected_train_return_pct": round(selected_return, 6),
            "candidate_train_return_pct": round(candidate_return, 6),
            "return_giveback_pct": round(return_giveback, 6),
            "return_giveback_threshold_pct": round(max_giveback, 6),
        }
    reordered = [candidate] + [result for result in train_results if result is not candidate]
    return reordered, {
        "applied": True,
        "reason": "negative_train_distribution_repair",
        "recipe": str(recipe.get("name") or ""),
        "selected_model_id_before_guard": selected.get("model_id"),
        "repair_candidate_model_id": candidate.get("model_id"),
        "selected_train_return_pct_before_guard": round(selected_return, 6),
        "repair_candidate_train_return_pct": round(candidate_return, 6),
        "return_giveback_pct": round(return_giveback, 6),
        "return_giveback_threshold_pct": round(max_giveback, 6),
        "repair_candidate_drawdown_pct": round(float(candidate.get("max_drawdown_pct") or 0.0), 6),
        "repair_candidate_cost_drag_pct": round(
            float(candidate.get("estimated_cost_drag_pct") or 0.0),
            6,
        ),
        "repair_candidate_one_way_trim_per_add": round(
            _train_ratio(candidate, "one_way_forced_trim_per_add"),
            6,
        ),
        "repair_candidate_turnover_per_add": round(
            _train_ratio(candidate, "turnover_events_per_add"),
            6,
        ),
    }


def _apply_high_cost_runner_rescue_guard(
    train_results: list[dict[str, Any]],
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not train_results or not bool(getattr(args, "selection_high_cost_runner_rescue", False)):
        return train_results, None
    selected = train_results[0]
    selected_return = float(selected.get("total_return_pct") or 0.0)
    if not _range_allowed(
        selected_return,
        getattr(args, "selection_high_cost_runner_min_selected_return_pct", None),
        getattr(args, "selection_high_cost_runner_max_selected_return_pct", None),
    ):
        return train_results, {
            "applied": False,
            "reason": "high_cost_runner_selected_return_out_of_band",
            "selected_train_return_pct": round(selected_return, 6),
        }
    recipes = [
        recipe
        for recipe in _legacy_after_selection_recipes(args)
        if str(recipe.get("name") or "") == "high_cost_runner_tight_repair"
    ]
    if not recipes:
        return train_results, {
            "applied": False,
            "reason": "high_cost_runner_recipe_disabled",
        }
    if any(_legacy_recipe_allowed(selected, recipe) for recipe in recipes):
        return train_results, {
            "applied": False,
            "reason": "selected_already_matches_high_cost_runner",
            "selected_model_id": selected.get("model_id"),
            "selected_train_return_pct": round(selected_return, 6),
        }
    candidate_matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for candidate in train_results[1:]:
        for recipe in recipes:
            if _legacy_recipe_allowed(candidate, recipe):
                candidate_matches.append((candidate, recipe))
                break
    if not candidate_matches:
        return train_results, {
            "applied": False,
            "reason": "high_cost_runner_candidate_not_found",
            "selected_model_id": selected.get("model_id"),
            "selected_train_return_pct": round(selected_return, 6),
        }
    candidate, recipe = max(
        candidate_matches,
        key=lambda item: (
            float(item[0].get("total_return_pct") or -1e9),
            float(item[0].get("walk_forward_selection_score") or -1e9),
            float(item[0].get("score") or -1e9),
            -float(item[0].get("max_drawdown_pct") or math.inf),
        ),
    )
    candidate_return = float(candidate.get("total_return_pct") or 0.0)
    return_giveback = selected_return - candidate_return
    max_giveback = max(
        0.0,
        float(getattr(args, "selection_high_cost_runner_max_return_giveback_pct", 0.0)),
    )
    if return_giveback > max_giveback:
        return train_results, {
            "applied": False,
            "reason": "high_cost_runner_return_giveback_above_threshold",
            "selected_model_id": selected.get("model_id"),
            "candidate_model_id": candidate.get("model_id"),
            "selected_train_return_pct": round(selected_return, 6),
            "candidate_train_return_pct": round(candidate_return, 6),
            "return_giveback_pct": round(return_giveback, 6),
            "return_giveback_threshold_pct": round(max_giveback, 6),
        }
    reordered = [candidate] + [result for result in train_results if result is not candidate]
    return reordered, {
        "applied": True,
        "reason": "high_cost_runner_repair",
        "recipe": str(recipe.get("name") or ""),
        "selected_model_id_before_guard": selected.get("model_id"),
        "repair_candidate_model_id": candidate.get("model_id"),
        "selected_train_return_pct_before_guard": round(selected_return, 6),
        "repair_candidate_train_return_pct": round(candidate_return, 6),
        "return_giveback_pct": round(return_giveback, 6),
        "return_giveback_threshold_pct": round(max_giveback, 6),
        "repair_candidate_drawdown_pct": round(float(candidate.get("max_drawdown_pct") or 0.0), 6),
        "repair_candidate_cost_drag_pct": round(
            float(candidate.get("estimated_cost_drag_pct") or 0.0),
            6,
        ),
        "repair_candidate_one_way_trim_per_add": round(
            _train_ratio(candidate, "one_way_forced_trim_per_add"),
            6,
        ),
        "repair_candidate_turnover_per_add": round(
            _train_ratio(candidate, "turnover_events_per_add"),
            6,
        ),
    }


def _deep_soft_overlay_rescue_candidate_allowed(
    train_result: dict[str, Any],
    args: argparse.Namespace,
) -> bool:
    if not bool(getattr(args, "equity_soft_sizer_deep_after_selection", False)):
        return False
    if not bool(getattr(args, "near_miss_activity_after_selection", False)):
        return False
    return bool(
        _equity_soft_sizer_after_selection_allowed(
            train_result,
            args,
            prefix="equity_soft_sizer_deep_after_selection",
        )
        and _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="near_miss_activity_after_selection",
        )
    )


def _apply_deep_soft_overlay_rescue_guard(
    train_results: list[dict[str, Any]],
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not train_results or not bool(getattr(args, "selection_deep_soft_overlay_rescue", False)):
        return train_results, None
    selected = train_results[0]
    selected_return = float(selected.get("total_return_pct") or 0.0)
    if not _range_allowed(
        selected_return,
        getattr(args, "selection_deep_soft_overlay_min_selected_return_pct", None),
        getattr(args, "selection_deep_soft_overlay_max_selected_return_pct", None),
    ):
        return train_results, {
            "applied": False,
            "reason": "deep_soft_overlay_selected_return_out_of_band",
            "selected_train_return_pct": round(selected_return, 6),
        }
    if _deep_soft_overlay_rescue_candidate_allowed(selected, args):
        return train_results, {
            "applied": False,
            "reason": "selected_already_matches_deep_soft_overlay",
            "selected_model_id": selected.get("model_id"),
            "selected_train_return_pct": round(selected_return, 6),
        }
    candidate_matches = [
        candidate
        for candidate in train_results[1:]
        if _deep_soft_overlay_rescue_candidate_allowed(candidate, args)
    ]
    if not candidate_matches:
        return train_results, {
            "applied": False,
            "reason": "deep_soft_overlay_candidate_not_found",
            "selected_model_id": selected.get("model_id"),
            "selected_train_return_pct": round(selected_return, 6),
        }
    candidate = max(
        candidate_matches,
        key=lambda item: (
            float(item.get("total_return_pct") or -1e9),
            float(item.get("walk_forward_selection_score") or -1e9),
            float(item.get("score") or -1e9),
            -float(item.get("max_drawdown_pct") or math.inf),
        ),
    )
    candidate_return = float(candidate.get("total_return_pct") or 0.0)
    return_giveback = selected_return - candidate_return
    max_giveback = max(
        0.0,
        float(getattr(args, "selection_deep_soft_overlay_max_return_giveback_pct", 0.0)),
    )
    if return_giveback > max_giveback:
        return train_results, {
            "applied": False,
            "reason": "deep_soft_overlay_return_giveback_above_threshold",
            "selected_model_id": selected.get("model_id"),
            "candidate_model_id": candidate.get("model_id"),
            "selected_train_return_pct": round(selected_return, 6),
            "candidate_train_return_pct": round(candidate_return, 6),
            "return_giveback_pct": round(return_giveback, 6),
            "return_giveback_threshold_pct": round(max_giveback, 6),
        }
    reordered = [candidate] + [result for result in train_results if result is not candidate]
    return reordered, {
        "applied": True,
        "reason": "deep_soft_overlay_repair",
        "selected_model_id_before_guard": selected.get("model_id"),
        "repair_candidate_model_id": candidate.get("model_id"),
        "selected_train_return_pct_before_guard": round(selected_return, 6),
        "repair_candidate_train_return_pct": round(candidate_return, 6),
        "return_giveback_pct": round(return_giveback, 6),
        "return_giveback_threshold_pct": round(max_giveback, 6),
        "repair_candidate_drawdown_pct": round(float(candidate.get("max_drawdown_pct") or 0.0), 6),
        "repair_candidate_cost_drag_pct": round(
            float(candidate.get("estimated_cost_drag_pct") or 0.0),
            6,
        ),
        "repair_candidate_one_way_trim_per_add": round(
            _train_ratio(candidate, "one_way_forced_trim_per_add"),
            6,
        ),
        "repair_candidate_turnover_per_add": round(
            _train_ratio(candidate, "turnover_events_per_add"),
            6,
        ),
    }


def _apply_deep_drawdown_reversal_rescue_guard(
    train_results: list[dict[str, Any]],
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not train_results or not bool(
        getattr(args, "selection_deep_drawdown_reversal_rescue", False)
    ):
        return train_results, None
    selected = train_results[0]
    selected_return = float(selected.get("total_return_pct") or 0.0)
    if not _range_allowed(
        selected_return,
        getattr(args, "selection_deep_drawdown_reversal_min_selected_return_pct", None),
        getattr(args, "selection_deep_drawdown_reversal_max_selected_return_pct", None),
    ):
        return train_results, {
            "applied": False,
            "reason": "deep_drawdown_reversal_selected_return_out_of_band",
            "selected_train_return_pct": round(selected_return, 6),
        }
    recipes = [
        recipe
        for recipe in _legacy_after_selection_recipes(args)
        if str(recipe.get("name") or "") == "deep_drawdown_reversal_scale"
    ]
    if not recipes:
        return train_results, {
            "applied": False,
            "reason": "deep_drawdown_reversal_recipe_disabled",
        }
    if any(_legacy_recipe_allowed(selected, recipe) for recipe in recipes):
        return train_results, {
            "applied": False,
            "reason": "selected_already_matches_deep_drawdown_reversal",
            "selected_model_id": selected.get("model_id"),
            "selected_train_return_pct": round(selected_return, 6),
        }
    max_candidate_one_way = getattr(
        args,
        "selection_deep_drawdown_reversal_max_candidate_one_way_trim_per_add",
        None,
    )
    max_one_way_increase = getattr(
        args,
        "selection_deep_drawdown_reversal_max_one_way_trim_increase_per_add",
        None,
    )
    selected_one_way_trim = _train_ratio(selected, "one_way_forced_trim_per_add")
    candidate_matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    forced_trim_blocked: list[dict[str, Any]] = []
    for candidate in train_results[1:]:
        for recipe in recipes:
            if _legacy_recipe_allowed(candidate, recipe):
                candidate_one_way_trim = _train_ratio(candidate, "one_way_forced_trim_per_add")
                one_way_increase = candidate_one_way_trim - selected_one_way_trim
                blocked_reasons: list[str] = []
                if (
                    max_candidate_one_way is not None
                    and candidate_one_way_trim > float(max_candidate_one_way)
                ):
                    blocked_reasons.append("candidate_one_way_trim_above_cap")
                if (
                    max_one_way_increase is not None
                    and one_way_increase > float(max_one_way_increase)
                ):
                    blocked_reasons.append("one_way_trim_increase_above_cap")
                if blocked_reasons:
                    forced_trim_blocked.append(
                        {
                            "candidate_model_id": candidate.get("model_id"),
                            "recipe": str(recipe.get("name") or ""),
                            "candidate_one_way_trim_per_add": round(candidate_one_way_trim, 6),
                            "selected_one_way_trim_per_add": round(selected_one_way_trim, 6),
                            "one_way_trim_increase_per_add": round(one_way_increase, 6),
                            "blocked_reasons": blocked_reasons,
                        }
                    )
                    break
                candidate_matches.append((candidate, recipe))
                break
    if not candidate_matches:
        if forced_trim_blocked:
            return train_results, {
                "applied": False,
                "reason": "deep_drawdown_reversal_forced_trim_cap_blocked",
                "selected_model_id": selected.get("model_id"),
                "selected_train_return_pct": round(selected_return, 6),
                "selected_one_way_trim_per_add": round(selected_one_way_trim, 6),
                "max_candidate_one_way_trim_per_add": (
                    None if max_candidate_one_way is None else round(float(max_candidate_one_way), 6)
                ),
                "max_one_way_trim_increase_per_add": (
                    None if max_one_way_increase is None else round(float(max_one_way_increase), 6)
                ),
                "blocked_candidate_count": len(forced_trim_blocked),
                "blocked_candidates": forced_trim_blocked[:5],
            }
        return train_results, {
            "applied": False,
            "reason": "deep_drawdown_reversal_candidate_not_found",
            "selected_model_id": selected.get("model_id"),
            "selected_train_return_pct": round(selected_return, 6),
        }
    candidate, recipe = max(
        candidate_matches,
        key=lambda item: (
            float(item[0].get("total_return_pct") or -1e9),
            float(item[0].get("walk_forward_selection_score") or -1e9),
            float(item[0].get("score") or -1e9),
            -float(item[0].get("max_drawdown_pct") or math.inf),
        ),
    )
    candidate_return = float(candidate.get("total_return_pct") or 0.0)
    return_giveback = selected_return - candidate_return
    max_giveback = max(
        0.0,
        float(getattr(args, "selection_deep_drawdown_reversal_max_return_giveback_pct", 0.0)),
    )
    if return_giveback > max_giveback:
        return train_results, {
            "applied": False,
            "reason": "deep_drawdown_reversal_return_giveback_above_threshold",
            "selected_model_id": selected.get("model_id"),
            "candidate_model_id": candidate.get("model_id"),
            "selected_train_return_pct": round(selected_return, 6),
            "candidate_train_return_pct": round(candidate_return, 6),
            "return_giveback_pct": round(return_giveback, 6),
            "return_giveback_threshold_pct": round(max_giveback, 6),
        }
    reordered = [candidate] + [result for result in train_results if result is not candidate]
    return reordered, {
        "applied": True,
        "reason": "deep_drawdown_reversal_repair",
        "recipe": str(recipe.get("name") or ""),
        "selected_model_id_before_guard": selected.get("model_id"),
        "repair_candidate_model_id": candidate.get("model_id"),
        "selected_train_return_pct_before_guard": round(selected_return, 6),
        "repair_candidate_train_return_pct": round(candidate_return, 6),
        "return_giveback_pct": round(return_giveback, 6),
        "return_giveback_threshold_pct": round(max_giveback, 6),
        "repair_candidate_drawdown_pct": round(float(candidate.get("max_drawdown_pct") or 0.0), 6),
        "repair_candidate_cost_drag_pct": round(
            float(candidate.get("estimated_cost_drag_pct") or 0.0),
            6,
        ),
        "repair_candidate_one_way_trim_per_add": round(
            _train_ratio(candidate, "one_way_forced_trim_per_add"),
            6,
        ),
        "selected_one_way_trim_per_add_before_guard": round(selected_one_way_trim, 6),
        "repair_candidate_one_way_trim_increase_per_add": round(
            _train_ratio(candidate, "one_way_forced_trim_per_add") - selected_one_way_trim,
            6,
        ),
        "repair_candidate_turnover_per_add": round(
            _train_ratio(candidate, "turnover_events_per_add"),
            6,
        ),
    }


def _regime_dependency_stats(result: dict[str, Any]) -> dict[str, Any]:
    regime_performance = dict(result.get("regime_performance") or {})
    positive_returns: list[tuple[str, float]] = []
    for regime, payload in regime_performance.items():
        regime_stats = dict(payload or {})
        regime_return = float(regime_stats.get("return_pct") or 0.0)
        if regime_return > 0.0:
            positive_returns.append((str(regime), regime_return))
    positive_sum = sum(value for _, value in positive_returns)
    if positive_sum <= 0.0 or not positive_returns:
        return {
            "dominant_regime": "none",
            "dominant_regime_return_pct": 0.0,
            "dominant_regime_return_share": 0.0,
            "positive_regime_return_sum_pct": 0.0,
            "positive_regime_count": 0,
        }
    dominant_regime, dominant_return = max(
        positive_returns,
        key=lambda item: (item[1], item[0]),
    )
    return {
        "dominant_regime": dominant_regime,
        "dominant_regime_return_pct": round(dominant_return, 4),
        "dominant_regime_return_share": round(dominant_return / positive_sum, 6),
        "positive_regime_return_sum_pct": round(positive_sum, 4),
        "positive_regime_count": len(positive_returns),
    }


def _apply_regime_dependency_penalty(result: dict[str, Any], args: argparse.Namespace) -> None:
    threshold = float(getattr(args, "selection_regime_dependency_threshold", 0.0) or 0.0)
    penalty = float(getattr(args, "selection_regime_dependency_penalty", 0.0) or 0.0)
    if threshold <= 0.0 or penalty <= 0.0:
        return
    train_return = float(result.get("total_return_pct") or 0.0)
    min_train_return = float(
        getattr(args, "selection_regime_dependency_min_train_return_pct", 0.0) or 0.0
    )
    if train_return < min_train_return:
        return
    stats = _regime_dependency_stats(result)
    dependency = float(stats.get("dominant_regime_return_share") or 0.0)
    if dependency <= threshold:
        return
    raw_score = float(result.get("walk_forward_selection_score") or -1e9)
    applied_penalty = max(penalty, 0.0)
    result["walk_forward_selection_score_before_regime_dependency"] = round(raw_score, 6)
    result["walk_forward_selection_regime_dependency"] = stats
    result["walk_forward_selection_regime_dependency_threshold"] = round(threshold, 6)
    result["walk_forward_selection_regime_dependency_penalty"] = round(applied_penalty, 6)
    result["walk_forward_selection_score"] = round(raw_score - applied_penalty, 6)


def _after_selection_train_confirmation(
    before_result: dict[str, Any],
    after_result: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[bool, dict[str, Any]]:
    before_return = float(before_result.get("total_return_pct") or 0.0)
    after_return = float(after_result.get("total_return_pct") or 0.0)
    before_drawdown = float(before_result.get("max_drawdown_pct") or 0.0)
    after_drawdown = float(after_result.get("max_drawdown_pct") or 0.0)
    before_cost = float(before_result.get("estimated_cost_drag_pct") or 0.0)
    after_cost = float(after_result.get("estimated_cost_drag_pct") or 0.0)
    before_score = float(
        before_result.get("walk_forward_selection_score", before_result.get("score") or -1e9)
    )
    after_score = float(
        after_result.get("walk_forward_selection_score", after_result.get("score") or -1e9)
    )
    return_delta = after_return - before_return
    drawdown_delta = after_drawdown - before_drawdown
    cost_delta = after_cost - before_cost
    score_delta = after_score - before_score
    return_per_cost_delta = math.inf if cost_delta <= 0.0 else return_delta / cost_delta
    failed: list[str] = []
    min_score_delta = args.after_selection_confirm_min_score_delta
    if min_score_delta is not None and score_delta < float(min_score_delta):
        failed.append("score_delta")
    min_return_delta = args.after_selection_confirm_min_return_delta_pct
    if min_return_delta is not None and return_delta < float(min_return_delta):
        failed.append("return_delta")
    max_drawdown_delta = args.after_selection_confirm_max_drawdown_delta_pct
    if max_drawdown_delta is not None and drawdown_delta > float(max_drawdown_delta):
        failed.append("drawdown_delta")
    max_cost_delta = args.after_selection_confirm_max_cost_delta_pct
    if max_cost_delta is not None and cost_delta > float(max_cost_delta):
        failed.append("cost_delta")
    min_return_per_cost_delta = args.after_selection_confirm_min_return_per_cost_delta
    if (
        min_return_per_cost_delta is not None
        and cost_delta > 0.0
        and return_per_cost_delta < float(min_return_per_cost_delta)
    ):
        failed.append("return_per_cost_delta")
    details = {
        "passed": not failed,
        "failed_checks": failed,
        "before_return_pct": round(before_return, 6),
        "after_return_pct": round(after_return, 6),
        "return_delta_pct": round(return_delta, 6),
        "before_drawdown_pct": round(before_drawdown, 6),
        "after_drawdown_pct": round(after_drawdown, 6),
        "drawdown_delta_pct": round(drawdown_delta, 6),
        "before_cost_drag_pct": round(before_cost, 6),
        "after_cost_drag_pct": round(after_cost, 6),
        "cost_delta_pct": round(cost_delta, 6),
        "before_selection_score": round(before_score, 6),
        "after_selection_score": round(after_score, 6),
        "selection_score_delta": round(score_delta, 6),
        "return_per_cost_delta": (
            "inf" if math.isinf(return_per_cost_delta) else round(return_per_cost_delta, 6)
        ),
    }
    return not failed, details


def _after_selection_confirmation_targets(
    overlays_applied: list[str],
    args: argparse.Namespace,
) -> list[str]:
    configured = {
        item.strip()
        for item in str(args.after_selection_confirm_overlays or "").split(",")
        if item.strip()
    }
    targets: list[str] = []
    seen: set[str] = set()
    for name in overlays_applied:
        if configured and name not in configured:
            continue
        if name in seen:
            continue
        seen.add(name)
        targets.append(name)
    return targets


def _after_selection_confirmation_should_enforce(args: argparse.Namespace) -> bool:
    return str(getattr(args, "after_selection_confirmation_mode", "enforce")) == "enforce"


def _confirmation_float(value: Any, default: float = 0.0) -> float:
    if value == "inf":
        return math.inf
    if value == "-inf":
        return -math.inf
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _status_performance_payload(stats: dict[str, Any]) -> dict[str, Any]:
    returns = list(stats.get("returns") or [])
    cost_drags = list(stats.get("cost_drags") or [])
    if not returns:
        return {
            "fold_count": 0,
            "positive_fold_count": 0,
            "compounded_return_pct": 0.0,
            "avg_return_pct": 0.0,
            "min_return_pct": 0.0,
            "max_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "avg_cost_drag_pct": 0.0,
        }
    return {
        "fold_count": len(returns),
        "positive_fold_count": sum(1 for value in returns if value > 0.0),
        "compounded_return_pct": round((float(stats.get("equity") or 1.0) - 1.0) * 100.0, 4),
        "avg_return_pct": round(mean(returns), 4),
        "min_return_pct": round(min(returns), 4),
        "max_return_pct": round(max(returns), 4),
        "max_drawdown_pct": round(float(stats.get("max_drawdown_pct") or 0.0), 4),
        "avg_cost_drag_pct": round(mean(cost_drags), 4) if cost_drags else 0.0,
    }


def _aggregate_after_selection_confirmations(folds: list[dict[str, Any]]) -> dict[str, Any]:
    mode_counter: Counter[str] = Counter()
    target_counter: Counter[str] = Counter()
    failed_check_counter: Counter[str] = Counter()
    target_totals: dict[str, dict[str, Any]] = {}
    status_totals: dict[str, dict[str, Any]] = {}
    record_count = 0
    passed_count = 0
    would_reject_count = 0
    enforced_count = 0

    def add_status(status: str, result: dict[str, Any]) -> None:
        fold_return = float(result.get("total_return_pct") or 0.0)
        fold_cost_drag = float(result.get("estimated_cost_drag_pct") or 0.0)
        fold_drawdown = float(result.get("max_drawdown_pct") or 0.0)
        total = status_totals.setdefault(
            status,
            {"equity": 1.0, "returns": [], "cost_drags": [], "max_drawdown_pct": 0.0},
        )
        total["equity"] *= float(result.get("final_equity") or max(1.0 + fold_return / 100.0, 1e-12))
        total["returns"].append(fold_return)
        total["cost_drags"].append(fold_cost_drag)
        total["max_drawdown_pct"] = max(float(total["max_drawdown_pct"]), fold_drawdown)

    for fold in folds:
        confirmation = fold.get("after_selection_train_confirmation")
        if not confirmation:
            continue
        details = dict(confirmation)
        record_count += 1
        passed = bool(details.get("passed"))
        would_reject = bool(details.get("would_reject", not passed))
        enforced = bool(details.get("enforced"))
        passed_count += int(passed)
        would_reject_count += int(would_reject)
        enforced_count += int(enforced)
        mode_counter[str(details.get("mode") or "unknown")] += 1
        failed_checks = [str(item) for item in details.get("failed_checks") or []]
        failed_check_counter.update(failed_checks)
        targets = [str(item) for item in details.get("target_overlays") or []]
        target_counter.update(targets)
        rejected_overlays = {str(item) for item in details.get("rejected_overlays") or []}
        target_details = {
            str(target): dict(payload or {})
            for target, payload in dict(details.get("target_details") or {}).items()
        }
        for target in targets:
            target_detail = dict(target_details.get(target) or details)
            target_passed = bool(target_detail.get("passed", passed))
            target_would_reject = (
                target in rejected_overlays if rejected_overlays else bool(would_reject)
            )
            target_enforced = bool(enforced and target_would_reject)
            target_failed_checks = [
                str(item) for item in target_detail.get("failed_checks") or []
            ]
            return_delta = _confirmation_float(target_detail.get("return_delta_pct"))
            cost_delta = _confirmation_float(target_detail.get("cost_delta_pct"))
            drawdown_delta = _confirmation_float(target_detail.get("drawdown_delta_pct"))
            total = target_totals.setdefault(
                target,
                {
                    "fold_count": 0,
                    "passed_count": 0,
                    "would_reject_count": 0,
                    "enforced_count": 0,
                    "cost_reducing_count": 0,
                    "return_deltas": [],
                    "cost_deltas": [],
                    "drawdown_deltas": [],
                    "failed_checks": Counter(),
                },
            )
            total["fold_count"] += 1
            total["passed_count"] += int(target_passed)
            total["would_reject_count"] += int(target_would_reject)
            total["enforced_count"] += int(target_enforced)
            total["cost_reducing_count"] += int(cost_delta <= 0.0)
            total["return_deltas"].append(return_delta)
            total["cost_deltas"].append(cost_delta)
            total["drawdown_deltas"].append(drawdown_delta)
            total["failed_checks"].update(target_failed_checks)
        test_result = dict(fold.get("test_result") or {})
        if test_result:
            add_status("passed" if passed else "would_reject", test_result)
            if enforced:
                add_status("enforced", test_result)

    if record_count == 0:
        return {}

    target_diagnostics = {}
    for target, stats in sorted(target_totals.items()):
        target_diagnostics[target] = {
            "fold_count": int(stats["fold_count"]),
            "passed_count": int(stats["passed_count"]),
            "would_reject_count": int(stats["would_reject_count"]),
            "enforced_count": int(stats["enforced_count"]),
            "cost_reducing_count": int(stats["cost_reducing_count"]),
            "avg_return_delta_pct": round(mean(stats["return_deltas"]), 4),
            "avg_cost_delta_pct": round(mean(stats["cost_deltas"]), 4),
            "avg_drawdown_delta_pct": round(mean(stats["drawdown_deltas"]), 4),
            "failed_check_counts": _counter_payload(stats["failed_checks"]),
        }

    return {
        "record_count": record_count,
        "passed_count": passed_count,
        "failed_count": record_count - passed_count,
        "would_reject_count": would_reject_count,
        "enforced_count": enforced_count,
        "mode_counts": _counter_payload(mode_counter),
        "target_counts": _counter_payload(target_counter),
        "failed_check_counts": _counter_payload(failed_check_counter),
        "target_diagnostics": target_diagnostics,
        "oos_by_status": {
            status: _status_performance_payload(stats)
            for status, stats in sorted(status_totals.items())
        },
    }


def _fold_confirmation_status(fold: dict[str, Any]) -> str:
    confirmation = fold.get("after_selection_train_confirmation")
    if not confirmation:
        return "none"
    details = dict(confirmation)
    rejected = [str(item) for item in details.get("rejected_overlays") or []]
    targets = ",".join(rejected or [str(item) for item in details.get("target_overlays") or []]) or "none"
    if bool(details.get("enforced")):
        status = "enforced"
    elif bool(details.get("would_reject")):
        status = "would_reject"
    elif bool(details.get("passed")):
        status = "passed"
    else:
        status = "failed"
    return f"{status}:{targets}"


def _top_no_trade_reasons(result: dict[str, Any], *, limit: int = 3) -> list[dict[str, Any]]:
    event_counts = dict(result.get("event_counts") or {})
    no_trade_items = [
        (str(key).removeprefix("no_trade_"), int(value))
        for key, value in event_counts.items()
        if str(key).startswith("no_trade_") and "::" not in str(key) and int(value or 0) > 0
    ]
    return [
        {"reason": reason, "count": count}
        for reason, count in sorted(no_trade_items, key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _result_regime_bar_count(result: dict[str, Any]) -> int:
    return sum(
        int(dict(stats or {}).get("bars") or 0)
        for stats in dict(result.get("regime_performance") or {}).values()
    )


def _fold_risk_brief(fold: dict[str, Any]) -> dict[str, Any]:
    result = dict(fold.get("test_result") or {})
    diagnostics = dict(result.get("event_diagnostics") or {})
    overlays = [str(item) for item in fold.get("after_selection_overlays_applied") or []]
    fold_return = float(result.get("total_return_pct") or 0.0)
    fold_cost_drag = float(result.get("estimated_cost_drag_pct") or 0.0)
    event_counts = dict(result.get("event_counts") or {})
    trade_like_events = int(result.get("trade_like_events") or diagnostics.get("add_events") or 0)
    diagnostic_thresholds = dict(diagnostics.get("diagnostic_thresholds") or {})
    expected_add_events = int(diagnostic_thresholds.get("expected_add_events") or 0)
    risk_adjusted_expected_add_events = int(
        diagnostic_thresholds.get("risk_adjusted_expected_add_events") or expected_add_events
    )
    capacity_context = dict(diagnostics.get("capacity_structure_context") or {})
    sample_mode = str(diagnostics.get("sample_mode") or "active")
    effective_expected_add_events = (
        risk_adjusted_expected_add_events
        if sample_mode in {"risk_off_idle", "risk_off_partial"}
        else expected_add_events
    )
    total_bars = _result_regime_bar_count(result)
    soft_circuit_cooldown_bars = int(event_counts.get("equity_soft_circuit_cooldown_bars") or 0)
    return {
        "fold": int(fold.get("fold") or 0),
        "test_start": fold.get("test_start_at") or fold.get("test_start"),
        "test_end": fold.get("test_end_at") or fold.get("test_end"),
        "return_pct": round(fold_return, 4),
        "max_drawdown_pct": round(float(result.get("max_drawdown_pct") or 0.0), 4),
        "cost_drag_pct": round(fold_cost_drag, 4),
        "cost_to_return_ratio": (
            "inf" if fold_return <= 0.0 else round(fold_cost_drag / max(fold_return, 1e-12), 6)
        ),
        "overlay_count": len(overlays),
        "overlays": overlays,
        "confirmation": _fold_confirmation_status(fold),
        "flags": [str(item) for item in diagnostics.get("flags") or []],
        "borderline_flags": [str(item) for item in diagnostics.get("borderline_flags") or []],
        "trade_like_events": trade_like_events,
        "sample_mode": sample_mode,
        "expected_add_events": expected_add_events,
        "risk_adjusted_expected_add_events": risk_adjusted_expected_add_events,
        "effective_expected_add_events": effective_expected_add_events,
        "add_event_coverage": (
            None
            if expected_add_events <= 0
            else round(trade_like_events / max(expected_add_events, 1), 6)
        ),
        "effective_add_event_coverage": (
            None
            if effective_expected_add_events <= 0
            else round(trade_like_events / max(effective_expected_add_events, 1), 6)
        ),
        "add_by_side": {
            str(key): int(value)
            for key, value in sorted(dict(diagnostics.get("add_by_side") or {}).items())
        },
        "add_by_role": {
            str(key): int(value)
            for key, value in sorted(dict(diagnostics.get("add_by_role") or {}).items())
        },
        "add_role_share": {
            str(key): float(value)
            for key, value in sorted(dict(diagnostics.get("add_role_share") or {}).items())
        },
        "dominant_add_role": str(diagnostics.get("dominant_add_role") or "none"),
        "max_role_add_share": round(float(diagnostics.get("max_role_add_share") or 0.0), 4),
        "base_add_share": round(_train_role_share({"event_diagnostics": diagnostics}, "base"), 4),
        "capacity_status": str(capacity_context.get("status") or "unknown"),
        "scale_in_capacity_available": (
            bool(capacity_context.get("scale_in_capacity_available"))
            if capacity_context
            else None
        ),
        "capacity_after_first_base_units": capacity_context.get("capacity_after_first_base_units"),
        "unit_account_exposure": capacity_context.get("unit_account_exposure"),
        "base_add_account_exposure": capacity_context.get("base_add_account_exposure"),
        "top_no_trade_reasons": _top_no_trade_reasons(result),
        "equity_soft_circuit_cooldown_bars": soft_circuit_cooldown_bars,
        "equity_soft_circuit_cooldown_share": (
            round(soft_circuit_cooldown_bars / max(total_bars, 1), 6) if total_bars else 0.0
        ),
    }


def _fold_risk_tags(
    brief: dict[str, Any],
    *,
    low_return_threshold_pct: float,
    high_drawdown_threshold_pct: float,
    high_cost_threshold_pct: float,
    high_overlay_count_threshold: int,
) -> list[str]:
    tags: list[str] = []
    fold_return = float(brief["return_pct"])
    fold_drawdown = float(brief["max_drawdown_pct"])
    fold_cost = float(brief["cost_drag_pct"])
    cost_to_return_ratio = brief.get("cost_to_return_ratio")
    if fold_return <= 0.0:
        tags.append("non_positive_return")
    if fold_return < low_return_threshold_pct:
        tags.append("low_return")
    if fold_drawdown >= high_drawdown_threshold_pct:
        tags.append("high_drawdown")
    if fold_cost >= high_cost_threshold_pct:
        tags.append("high_cost")
    if cost_to_return_ratio == "inf" or float(cost_to_return_ratio or 0.0) > 1.0:
        tags.append("cost_exceeds_return")
    if int(brief["overlay_count"]) >= high_overlay_count_threshold:
        tags.append("high_overlay_count")
    fold_flags = {str(flag) for flag in brief.get("flags") or []}
    fold_borderline_flags = {str(flag) for flag in brief.get("borderline_flags") or []}
    if "role_concentration" in fold_flags or "role_concentration" in fold_borderline_flags:
        tags.append("role_concentration")
    if (
        str(brief.get("dominant_add_role") or "") == "base"
        and float(brief.get("base_add_share") or 0.0) >= 0.80
    ):
        tags.append("base_dominance")
    capacity_status = str(brief.get("capacity_status") or "")
    if capacity_status == "battle_capacity_saturated":
        tags.append("battle_capacity_saturated")
    elif brief.get("scale_in_capacity_available") is False:
        tags.append("single_unit_full_entry")
    if str(brief.get("confirmation") or "").startswith("would_reject:"):
        tags.append("confirmation_warning")
    if brief.get("flags"):
        tags.append("test_flags")
    return tags


def _aggregate_weak_fold_diagnostics(folds: list[dict[str, Any]], *, limit: int = 5) -> dict[str, Any]:
    briefs = [_fold_risk_brief(fold) for fold in folds if fold.get("test_result")]
    if not briefs:
        return {}
    low_return_threshold_pct = 5.0
    high_drawdown_threshold_pct = 10.0
    high_cost_threshold_pct = 20.0
    high_overlay_count_threshold = 5
    risk_tag_counter: Counter[str] = Counter()
    no_trade_reason_counter: Counter[str] = Counter()
    for brief in briefs:
        tags = _fold_risk_tags(
            brief,
            low_return_threshold_pct=low_return_threshold_pct,
            high_drawdown_threshold_pct=high_drawdown_threshold_pct,
            high_cost_threshold_pct=high_cost_threshold_pct,
            high_overlay_count_threshold=high_overlay_count_threshold,
        )
        brief["risk_tags"] = tags
        risk_tag_counter.update(tags)
        no_trade_reason_counter.update(
            {
                str(item.get("reason")): int(item.get("count") or 0)
                for item in list(brief.get("top_no_trade_reasons") or [])
            }
        )
    confirmation_warning_folds = [
        brief for brief in briefs if str(brief.get("confirmation") or "").startswith("would_reject:")
    ]
    low_activity_folds = [
        brief
        for brief in briefs
        if int(brief.get("effective_expected_add_events") or brief.get("expected_add_events") or 0) > 0
        and int(brief.get("trade_like_events") or 0)
        < int(brief.get("effective_expected_add_events") or brief.get("expected_add_events") or 0)
    ]
    soft_circuit_dominated_folds = [
        brief
        for brief in briefs
        if float(brief.get("equity_soft_circuit_cooldown_share") or 0.0) >= 0.50
    ]
    capacity_status_counter: Counter[str] = Counter(
        str(brief.get("capacity_status") or "unknown") for brief in briefs
    )
    role_concentration_folds = [
        brief
        for brief in briefs
        if "role_concentration" in set(brief.get("flags") or [])
        or "role_concentration" in set(brief.get("borderline_flags") or [])
    ]
    base_dominance_folds = [
        brief
        for brief in briefs
        if str(brief.get("dominant_add_role") or "") == "base"
        and float(brief.get("base_add_share") or 0.0) >= 0.80
    ]
    return {
        "low_return_threshold_pct": low_return_threshold_pct,
        "high_drawdown_threshold_pct": high_drawdown_threshold_pct,
        "high_cost_threshold_pct": high_cost_threshold_pct,
        "high_overlay_count_threshold": high_overlay_count_threshold,
        "non_positive_return_count": sum(1 for brief in briefs if float(brief["return_pct"]) <= 0.0),
        "low_return_count": sum(
            1 for brief in briefs if float(brief["return_pct"]) < low_return_threshold_pct
        ),
        "high_drawdown_count": sum(
            1 for brief in briefs if float(brief["max_drawdown_pct"]) >= high_drawdown_threshold_pct
        ),
        "high_cost_count": sum(
            1 for brief in briefs if float(brief["cost_drag_pct"]) >= high_cost_threshold_pct
        ),
        "high_overlay_count": sum(
            1 for brief in briefs if int(brief["overlay_count"]) >= high_overlay_count_threshold
        ),
        "confirmation_warning_count": len(confirmation_warning_folds),
        "role_concentration_count": len(role_concentration_folds),
        "base_dominance_count": len(base_dominance_folds),
        "no_scale_in_capacity_count": sum(
            1 for brief in briefs if brief.get("scale_in_capacity_available") is False
        ),
        "single_unit_full_entry_count": sum(
            1 for brief in briefs if str(brief.get("capacity_status") or "") == "single_unit_full_entry"
        ),
        "battle_capacity_saturated_count": sum(
            1 for brief in briefs if str(brief.get("capacity_status") or "") == "battle_capacity_saturated"
        ),
        "capacity_status_counts": _counter_payload(capacity_status_counter),
        "low_activity_count": len(low_activity_folds),
        "soft_circuit_dominated_count": len(soft_circuit_dominated_folds),
        "top_no_trade_reason_counts": _counter_payload(no_trade_reason_counter),
        "risk_tag_counts": _counter_payload(risk_tag_counter),
        "lowest_return_folds": sorted(briefs, key=lambda item: (float(item["return_pct"]), item["fold"]))[
            :limit
        ],
        "highest_drawdown_folds": sorted(
            briefs,
            key=lambda item: (-float(item["max_drawdown_pct"]), item["fold"]),
        )[:limit],
        "highest_cost_folds": sorted(
            briefs,
            key=lambda item: (-float(item["cost_drag_pct"]), item["fold"]),
        )[:limit],
        "highest_overlay_count_folds": sorted(
            briefs,
            key=lambda item: (-int(item["overlay_count"]), item["fold"]),
        )[:limit],
        "lowest_activity_folds": sorted(
            low_activity_folds,
            key=lambda item: (
                float(item.get("effective_add_event_coverage") or item.get("add_event_coverage") or 0.0),
                float(item["return_pct"]),
                item["fold"],
            ),
        )[:limit],
        "soft_circuit_dominated_folds": sorted(
            soft_circuit_dominated_folds,
            key=lambda item: (
                -float(item.get("equity_soft_circuit_cooldown_share") or 0.0),
                float(item["return_pct"]),
                item["fold"],
            ),
        )[:limit],
        "role_concentration_folds": sorted(
            role_concentration_folds,
            key=lambda item: (
                -float(item.get("max_role_add_share") or 0.0),
                float(item["return_pct"]),
                item["fold"],
            ),
        )[:limit],
        "base_dominance_folds": sorted(
            base_dominance_folds,
            key=lambda item: (
                -float(item.get("base_add_share") or 0.0),
                float(item["return_pct"]),
                item["fold"],
            ),
        )[:limit],
        "confirmation_warning_folds": confirmation_warning_folds[:limit],
    }


def _aggregate_after_selection_overlay_oos_performance(
    folds: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    low_return_threshold_pct = 5.0
    high_drawdown_threshold_pct = 10.0
    high_cost_threshold_pct = 20.0
    high_overlay_count_threshold = 5
    overlay_totals: dict[str, dict[str, Any]] = {}
    for fold in folds:
        result = dict(fold.get("test_result") or {})
        if not result:
            continue
        overlays = [str(item) for item in fold.get("after_selection_overlays_applied") or []]
        if not overlays:
            continue
        brief = _fold_risk_brief(fold)
        risk_tags = _fold_risk_tags(
            brief,
            low_return_threshold_pct=low_return_threshold_pct,
            high_drawdown_threshold_pct=high_drawdown_threshold_pct,
            high_cost_threshold_pct=high_cost_threshold_pct,
            high_overlay_count_threshold=high_overlay_count_threshold,
        )
        fold_return = float(result.get("total_return_pct") or 0.0)
        fold_cost_drag = float(result.get("estimated_cost_drag_pct") or 0.0)
        fold_drawdown = float(result.get("max_drawdown_pct") or 0.0)
        fold_equity = float(result.get("final_equity") or max(1.0 + fold_return / 100.0, 1e-12))
        for overlay in overlays:
            total = overlay_totals.setdefault(
                overlay,
                {
                    "equity": 1.0,
                    "returns": [],
                    "cost_drags": [],
                    "max_drawdown_pct": 0.0,
                    "risk_tags": Counter(),
                    "folds": [],
                },
            )
            total["equity"] *= max(fold_equity, 1e-12)
            total["returns"].append(fold_return)
            total["cost_drags"].append(fold_cost_drag)
            total["max_drawdown_pct"] = max(float(total["max_drawdown_pct"]), fold_drawdown)
            total["risk_tags"].update(risk_tags)
            total["folds"].append(int(brief.get("fold") or 0))

    performance: dict[str, dict[str, Any]] = {}
    for overlay, stats in sorted(overlay_totals.items()):
        payload = _status_performance_payload(stats)
        risk_tag_counts = _counter_payload(stats["risk_tags"])
        payload.update(
            {
                "risk_tag_counts": risk_tag_counts,
                "folds": list(stats.get("folds") or []),
                "low_return_count": int(risk_tag_counts.get("low_return", 0)),
                "high_drawdown_count": int(risk_tag_counts.get("high_drawdown", 0)),
                "high_cost_count": int(risk_tag_counts.get("high_cost", 0)),
                "cost_exceeds_return_count": int(risk_tag_counts.get("cost_exceeds_return", 0)),
                "confirmation_warning_count": int(risk_tag_counts.get("confirmation_warning", 0)),
            }
        )
        performance[overlay] = payload
    return performance


def _regime_bar_shares(regime_performance: dict[str, Any]) -> dict[str, float]:
    payload = {str(regime): dict(stats or {}) for regime, stats in dict(regime_performance or {}).items()}
    total_bars = sum(int(stats.get("bars") or 0) for stats in payload.values())
    if total_bars <= 0:
        return {}
    return {
        regime: round(int(stats.get("bars") or 0) / total_bars, 6)
        for regime, stats in sorted(payload.items())
    }


def _dominant_regime_share(shares: dict[str, float]) -> tuple[str, float]:
    if not shares:
        return "none", 0.0
    return max(shares.items(), key=lambda item: (float(item[1]), item[0]))


def _fold_regime_drift_brief(fold: dict[str, Any]) -> dict[str, Any]:
    train_result = dict(fold.get("selected_train_result") or {})
    test_result = dict(fold.get("test_result") or {})
    train_shares = _regime_bar_shares(dict(train_result.get("regime_performance") or {}))
    test_shares = _regime_bar_shares(dict(test_result.get("regime_performance") or {}))
    regimes = sorted(set(train_shares) | set(test_shares))
    regime_deltas = {
        regime: round(float(test_shares.get(regime, 0.0)) - float(train_shares.get(regime, 0.0)), 6)
        for regime in regimes
    }
    drift = round(sum(abs(value) for value in regime_deltas.values()) / 2.0, 6)
    largest_shift_regime = "none"
    largest_shift = 0.0
    if regime_deltas:
        largest_shift_regime, largest_shift = max(
            regime_deltas.items(),
            key=lambda item: (abs(float(item[1])), item[0]),
        )
    train_dominant_regime, train_dominant_share = _dominant_regime_share(train_shares)
    test_dominant_regime, test_dominant_share = _dominant_regime_share(test_shares)
    return {
        "fold": int(fold.get("fold") or 0),
        "test_start": fold.get("test_start_at") or fold.get("test_start"),
        "test_end": fold.get("test_end_at") or fold.get("test_end"),
        "return_pct": round(float(test_result.get("total_return_pct") or 0.0), 4),
        "max_drawdown_pct": round(float(test_result.get("max_drawdown_pct") or 0.0), 4),
        "cost_drag_pct": round(float(test_result.get("estimated_cost_drag_pct") or 0.0), 4),
        "regime_share_drift": drift,
        "train_dominant_regime": train_dominant_regime,
        "train_dominant_share": round(float(train_dominant_share), 6),
        "test_dominant_regime": test_dominant_regime,
        "test_dominant_share": round(float(test_dominant_share), 6),
        "largest_shift_regime": largest_shift_regime,
        "largest_shift": round(float(largest_shift), 6),
        "train_regime_dependency": _regime_dependency_stats(train_result),
    }


def _aggregate_regime_drift_diagnostics(
    folds: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> dict[str, Any]:
    briefs = [
        _fold_regime_drift_brief(fold)
        for fold in folds
        if fold.get("selected_train_result") and fold.get("test_result")
    ]
    if not briefs:
        return {}
    high_drift_threshold = 0.15
    high_dependency_threshold = 0.65
    high_drift_folds = [
        brief for brief in briefs if float(brief.get("regime_share_drift") or 0.0) >= high_drift_threshold
    ]
    high_dependency_folds = [
        brief
        for brief in briefs
        if float(
            dict(brief.get("train_regime_dependency") or {}).get(
                "dominant_regime_return_share",
                0.0,
            )
        )
        >= high_dependency_threshold
    ]
    return {
        "high_drift_threshold": high_drift_threshold,
        "high_dependency_threshold": high_dependency_threshold,
        "avg_regime_share_drift": round(
            mean(float(brief.get("regime_share_drift") or 0.0) for brief in briefs),
            6,
        ),
        "max_regime_share_drift": round(
            max(float(brief.get("regime_share_drift") or 0.0) for brief in briefs),
            6,
        ),
        "high_drift_count": len(high_drift_folds),
        "high_dependency_count": len(high_dependency_folds),
        "highest_drift_folds": sorted(
            briefs,
            key=lambda item: (-float(item.get("regime_share_drift") or 0.0), int(item["fold"])),
        )[:limit],
        "highest_dependency_folds": sorted(
            briefs,
            key=lambda item: (
                -float(
                    dict(item.get("train_regime_dependency") or {}).get(
                        "dominant_regime_return_share",
                        0.0,
                    )
                ),
                int(item["fold"]),
            ),
        )[:limit],
        "lowest_return_folds": sorted(
            briefs,
            key=lambda item: (float(item.get("return_pct") or 0.0), int(item["fold"])),
        )[:limit],
    }


def _after_selection_recent_oos_block_should_enforce(args: argparse.Namespace) -> bool:
    return str(getattr(args, "after_selection_recent_oos_block_mode", "enforce")) == "enforce"


def _after_selection_recent_oos_block_targets(args: argparse.Namespace) -> set[str]:
    return {
        item.strip()
        for item in str(getattr(args, "after_selection_recent_oos_block_overlays", "") or "").split(",")
        if item.strip()
    }


def _after_selection_recent_oos_blocks(
    completed_folds: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, dict[str, Any]]:
    if not bool(getattr(args, "after_selection_recent_oos_block", False)):
        return {}
    lookback = max(1, int(getattr(args, "after_selection_recent_oos_block_lookback", 4) or 4))
    min_samples = max(1, int(getattr(args, "after_selection_recent_oos_block_min_samples", 2) or 2))
    eligible_overlays = _after_selection_recent_oos_block_targets(args)
    overlay_totals: dict[str, dict[str, Any]] = {}
    for fold in completed_folds[-lookback:]:
        result = dict(fold.get("test_result") or {})
        if not result:
            continue
        overlays = [str(item) for item in fold.get("after_selection_overlays_applied") or []]
        if eligible_overlays:
            overlays = [name for name in overlays if name in eligible_overlays]
        if not overlays:
            continue
        confirmation = dict(fold.get("after_selection_train_confirmation") or {})
        confirmation_warning_overlays = (
            {
                str(item)
                for item in (
                    confirmation.get("rejected_overlays")
                    or confirmation.get("target_overlays")
                    or []
                )
            }
            if bool(confirmation.get("would_reject"))
            else set()
        )
        fold_return = float(result.get("total_return_pct") or 0.0)
        fold_cost_drag = float(result.get("estimated_cost_drag_pct") or 0.0)
        fold_drawdown = float(result.get("max_drawdown_pct") or 0.0)
        fold_equity = float(result.get("final_equity") or max(1.0 + fold_return / 100.0, 1e-12))
        for overlay in overlays:
            total = overlay_totals.setdefault(
                overlay,
                {
                    "equity": 1.0,
                    "returns": [],
                    "cost_drags": [],
                    "max_drawdown_pct": 0.0,
                    "folds": [],
                    "confirmation_warning_count": 0,
                },
            )
            total["equity"] *= max(fold_equity, 1e-12)
            total["returns"].append(fold_return)
            total["cost_drags"].append(fold_cost_drag)
            total["max_drawdown_pct"] = max(float(total["max_drawdown_pct"]), fold_drawdown)
            total["folds"].append(int(fold.get("fold") or 0))
            total["confirmation_warning_count"] += int(overlay in confirmation_warning_overlays)

    blocked: dict[str, dict[str, Any]] = {}
    min_avg_return = getattr(args, "after_selection_recent_oos_block_min_avg_return_pct", None)
    min_compounded_return = getattr(
        args,
        "after_selection_recent_oos_block_min_compounded_return_pct",
        None,
    )
    max_drawdown = getattr(args, "after_selection_recent_oos_block_max_drawdown_pct", None)
    max_avg_cost = getattr(args, "after_selection_recent_oos_block_max_avg_cost_drag_pct", None)
    max_cost_to_return = getattr(
        args,
        "after_selection_recent_oos_block_max_cost_to_return_ratio",
        None,
    )
    block_confirmation_warnings = bool(
        getattr(args, "after_selection_recent_oos_block_confirmation_warnings", False)
    )
    for overlay, stats in sorted(overlay_totals.items()):
        returns = list(stats.get("returns") or [])
        if len(returns) < min_samples:
            continue
        payload = _status_performance_payload(stats)
        failed: list[str] = []
        avg_return = float(payload.get("avg_return_pct") or 0.0)
        compounded_return = float(payload.get("compounded_return_pct") or 0.0)
        avg_cost = float(payload.get("avg_cost_drag_pct") or 0.0)
        cost_to_return_ratio = math.inf if avg_return <= 0.0 else avg_cost / max(avg_return, 1e-12)
        if min_avg_return is not None and avg_return < float(min_avg_return):
            failed.append("avg_return")
        if min_compounded_return is not None and compounded_return < float(min_compounded_return):
            failed.append("compounded_return")
        if max_drawdown is not None and float(payload.get("max_drawdown_pct") or 0.0) > float(max_drawdown):
            failed.append("drawdown")
        if max_avg_cost is not None and avg_cost > float(max_avg_cost):
            failed.append("avg_cost")
        if max_cost_to_return is not None and cost_to_return_ratio > float(max_cost_to_return):
            failed.append("cost_to_return")
        if block_confirmation_warnings and int(stats.get("confirmation_warning_count") or 0) > 0:
            failed.append("confirmation_warning")
        if not failed:
            continue
        blocked[overlay] = {
            **payload,
            "failed_checks": failed,
            "folds": list(stats.get("folds") or []),
            "confirmation_warning_count": int(stats.get("confirmation_warning_count") or 0),
            "cost_to_return_ratio": (
                "inf" if math.isinf(cost_to_return_ratio) else round(cost_to_return_ratio, 6)
            ),
        }
    return blocked


def _aggregate_after_selection_recent_oos_blocks(folds: list[dict[str, Any]]) -> dict[str, Any]:
    mode_counter: Counter[str] = Counter()
    overlay_counter: Counter[str] = Counter()
    failed_check_counter: Counter[str] = Counter()
    record_count = 0
    enforced_count = 0
    for fold in folds:
        record = dict(fold.get("after_selection_recent_oos_block") or {})
        if not record:
            continue
        record_count += 1
        mode_counter[str(record.get("mode") or "unknown")] += 1
        enforced_count += int(bool(record.get("enforced")))
        blocked_overlays = [str(item) for item in record.get("blocked_overlays") or []]
        overlay_counter.update(blocked_overlays)
        details = dict(record.get("details") or {})
        for overlay in blocked_overlays:
            failed_check_counter.update(
                str(item) for item in dict(details.get(overlay) or {}).get("failed_checks") or []
            )
    if record_count == 0:
        return {}
    return {
        "record_count": record_count,
        "enforced_count": enforced_count,
        "mode_counts": _counter_payload(mode_counter),
        "blocked_overlay_counts": _counter_payload(overlay_counter),
        "failed_check_counts": _counter_payload(failed_check_counter),
    }


def _selection_recent_efficiency_key(config_payload: dict[str, Any]) -> tuple[str, float, str]:
    defensive_cooldown = int(config_payload.get("defensive_trim_cooldown_bars") or 0)
    cooldown_bucket = "fast_defense" if 0 < defensive_cooldown <= 24 else "source_defense"
    return (
        str(config_payload.get("profile_name") or ""),
        round(float(config_payload.get("max_possible_units") or 0.0), 4),
        cooldown_bucket,
    )


def _apply_recent_efficiency_penalty(
    result: dict[str, Any],
    completed_folds: list[dict[str, Any]],
    *,
    lookback: int,
    min_samples: int,
    min_train_return_pct: float,
    efficiency_threshold: float,
    penalty: float,
) -> None:
    if int(lookback) <= 0 or float(penalty) <= 0.0 or float(efficiency_threshold) <= 0.0:
        return
    candidate_train_return = float(result.get("total_return_pct") or 0.0)
    if candidate_train_return < float(min_train_return_pct):
        return
    config_payload = dict(result.get("config") or {})
    key = _selection_recent_efficiency_key(config_payload)
    recent = completed_folds[-max(1, int(lookback)) :]
    matched: list[tuple[float, float]] = []
    for fold in recent:
        train_result = dict(fold.get("selected_train_result") or {})
        test_result = dict(fold.get("test_result") or {})
        train_config = dict(train_result.get("config") or {})
        if _selection_recent_efficiency_key(train_config) != key:
            continue
        train_return = float(train_result.get("total_return_pct") or 0.0)
        if train_return < float(min_train_return_pct):
            continue
        matched.append((train_return, float(test_result.get("total_return_pct") or 0.0)))
    if len(matched) < max(1, int(min_samples)):
        return
    train_sum = sum(train for train, _ in matched)
    if train_sum <= 0.0:
        return
    efficiency = sum(test for _, test in matched) / train_sum
    if efficiency >= float(efficiency_threshold):
        return
    raw_score = float(result.get("walk_forward_selection_score") or -1e9)
    applied_penalty = max(float(penalty), 0.0)
    result["walk_forward_selection_score_before_recent_efficiency"] = round(raw_score, 6)
    result["walk_forward_selection_recent_efficiency_ratio"] = round(efficiency, 6)
    result["walk_forward_selection_recent_efficiency_samples"] = len(matched)
    result["walk_forward_selection_recent_efficiency_penalty"] = round(applied_penalty, 6)
    result["walk_forward_selection_score"] = round(raw_score - applied_penalty, 6)


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


def _low_confidence_abstain_decision(
    train_result: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any] | None:
    if not bool(getattr(args, "low_confidence_abstain_after_selection", False)):
        return None
    prefix = "low_confidence_abstain_after_selection"
    if not _train_state_after_selection_allowed(train_result, args, prefix=prefix):
        return None
    train_score = float(train_result.get("walk_forward_selection_score") or 0.0)
    if not _range_allowed(
        train_score,
        getattr(args, f"{prefix}_min_train_score"),
        getattr(args, f"{prefix}_max_train_score"),
    ):
        return None
    chase_ratio = _train_ratio(train_result, "chase_add_per_add")
    if not _positive_range_allowed(
        chase_ratio,
        max(0.0, float(getattr(args, f"{prefix}_min_chase_add_per_add"))),
        max(0.0, float(getattr(args, f"{prefix}_max_chase_add_per_add"))),
    ):
        return None
    battle_ratio = _train_ratio(train_result, "battle_add_per_add")
    if not _positive_range_allowed(
        battle_ratio,
        max(0.0, float(getattr(args, f"{prefix}_min_battle_add_per_add"))),
        max(0.0, float(getattr(args, f"{prefix}_max_battle_add_per_add"))),
    ):
        return None
    return {
        "applied": True,
        "name": "low_confidence_abstain",
        "reason": "train_state_low_confidence",
        "train_selection_score": round(train_score, 6),
        "train_return_pct": round(float(train_result.get("total_return_pct") or 0.0), 6),
        "train_drawdown_pct": round(float(train_result.get("max_drawdown_pct") or 0.0), 6),
        "train_cost_drag_pct": round(float(train_result.get("estimated_cost_drag_pct") or 0.0), 6),
        "one_way_trim_per_add": round(_train_ratio(train_result, "one_way_forced_trim_per_add"), 6),
        "turnover_per_add": round(_train_ratio(train_result, "turnover_events_per_add"), 6),
        "chase_add_per_add": round(chase_ratio, 6),
        "battle_add_per_add": round(battle_ratio, 6),
    }


def _flat_walk_forward_result(
    *,
    symbol: str,
    exec_interval: str,
    config: MarketStateConfig,
    features: FeatureSet,
    reason: str,
) -> dict[str, Any]:
    bars = list(features.bars)
    start_ts = bars[0].ts if bars else None
    end_ts = bars[-1].ts if bars else None
    years = 0.0
    if start_ts is not None and end_ts is not None and end_ts > start_ts:
        years = (end_ts - start_ts).total_seconds() / (365.25 * 24 * 60 * 60)
    drawdown_detail = {
        "peak_ts": start_ts.isoformat() if start_ts is not None else None,
        "trough_ts": start_ts.isoformat() if start_ts is not None else None,
        "trough_side": "flat",
        "trough_regime": "abstain",
        "recovered_peak": True,
        "trough_to_recovery_hours": 0.0,
    }
    event_diagnostics = {
        "health": "abstain",
        "flags": ["walk_forward_abstain"],
        "borderline_flags": [],
        "add_events": 0,
        "remove_events": 0,
        "add_by_side": {},
        "add_by_role": {},
        "ratios": {},
        "exposure_side_bars": {"flat": len(bars)},
        "exposure_side_share": {"flat": 1.0},
    }
    empty_cost = {
        "total_modeled_trade_cost_pct": 0.0,
        "by_action_pct": {},
        "by_side_pct": {},
        "by_role_pct": {},
        "by_reason_pct": {},
        "by_action_reason_pct": {},
    }
    return {
        "symbol": symbol,
        "exec_interval": exec_interval,
        "model_id": f"{config.model_id}:wfAbstain",
        "config": asdict(config),
        "years": round(years, 8),
        "total_return_pct": 0.0,
        "gross_return_pct_before_costs": 0.0,
        "estimated_cost_drag_pct": 0.0,
        "modeled_trade_cost_fraction_sum": 0.0,
        "modeled_carry_cost_fraction_sum": 0.0,
        "final_equity": 1.0,
        "gross_final_equity_before_costs": 1.0,
        "min_equity": 1.0,
        "gross_min_equity_before_costs": 1.0,
        "max_drawdown_pct": 0.0,
        "gross_max_drawdown_pct_before_costs": 0.0,
        "max_drawdown_detail": drawdown_detail,
        "max_abs_account_exposure": 0.0,
        "avg_abs_account_exposure": 0.0,
        "trade_like_events": 0,
        "battle_adds": 0,
        "battle_success_rate": 0.0,
        "cagr_pct": 0.0,
        "gross_cagr_pct_before_costs": 0.0,
        "sharpe_proxy": 0.0,
        "score": 0.0,
        "event_counts": {
            "walk_forward_abstain_folds": 1,
            f"walk_forward_abstain_{reason}": 1,
        },
        "event_diagnostics": event_diagnostics,
        "cost_diagnostics": empty_cost,
        "monthly": {"months": 0, "monthly_returns": {}, "months_doubled": 0, "monthly_double_rate": 0.0, "losing_months": 0},
        "calendar_rolling": {"daily_count": 0, "windows": {}},
        "regime_performance": {},
        "router_mode_performance": {},
        "sample_events": [],
        "scenario_intervals": [],
        "walk_forward_abstain": True,
        "walk_forward_abstain_reason": reason,
    }


def _candidate_test_return(candidate: dict[str, Any]) -> float:
    value = candidate.get("test_return_pct")
    if value is None:
        value = dict(candidate.get("test_result") or {}).get("total_return_pct")
    return float(value or 0.0)


def _candidate_test_cost(candidate: dict[str, Any]) -> float:
    value = dict(candidate.get("test_result") or {}).get("estimated_cost_drag_pct")
    return float(value or 0.0)


def _candidate_test_drawdown(candidate: dict[str, Any]) -> float:
    value = candidate.get("test_max_drawdown_pct")
    if value is None:
        value = dict(candidate.get("test_result") or {}).get("max_drawdown_pct")
    return float(value or 0.0)


def _candidate_test_flags(candidate: dict[str, Any]) -> list[str]:
    flags = candidate.get("test_flags")
    if flags is None:
        flags = dict(dict(candidate.get("test_result") or {}).get("event_diagnostics") or {}).get(
            "flags"
        )
    return [str(item) for item in flags or []]


def _candidate_test_trade_like_events(candidate: dict[str, Any]) -> int:
    value = candidate.get("test_trade_like_events")
    if value is None:
        value = dict(candidate.get("test_result") or {}).get("trade_like_events")
    return int(value or 0)


def _candidate_flag_delta(selected: dict[str, Any], best: dict[str, Any]) -> dict[str, Any]:
    selected_flags = set(_candidate_test_flags(selected))
    best_flags = set(_candidate_test_flags(best))
    return {
        "selected_count": len(selected_flags),
        "best_count": len(best_flags),
        "selected_only": sorted(selected_flags - best_flags),
        "best_only": sorted(best_flags - selected_flags),
    }


def _candidate_brief(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": int(candidate.get("rank") or 0),
        "model_id": str(candidate.get("model_id") or ""),
        "train_selection_score": (
            None
            if candidate.get("train_selection_score") is None
            else round(float(candidate.get("train_selection_score") or 0.0), 6)
        ),
        "train_return_pct": round(float(candidate.get("train_return_pct") or 0.0), 4),
        "test_return_pct": round(_candidate_test_return(candidate), 4),
        "test_cost_drag_pct": round(_candidate_test_cost(candidate), 4),
        "test_max_drawdown_pct": round(_candidate_test_drawdown(candidate), 4),
        "test_trade_like_events": _candidate_test_trade_like_events(candidate),
        "after_selection_overlays_applied": [
            str(item) for item in candidate.get("after_selection_overlays_applied") or []
        ],
        "test_flags": _candidate_test_flags(candidate),
    }


def _aggregate_top_train_candidate_audit(
    folds: list[dict[str, Any]],
    *,
    limit: int = 8,
) -> dict[str, Any]:
    audited: list[dict[str, Any]] = []
    selected_equity = 1.0
    best_equity = 1.0
    regret_values: list[float] = []
    best_rank_counter: Counter[str] = Counter()
    candidate_counts: list[int] = []
    for fold in folds:
        candidates = [dict(item or {}) for item in fold.get("train_top_test_results") or []]
        candidates = [item for item in candidates if item.get("test_return_pct") is not None or item.get("test_result")]
        if len(candidates) <= 1:
            continue
        selected = next((item for item in candidates if bool(item.get("is_selected"))), candidates[0])
        best = max(
            candidates,
            key=lambda item: (
                _candidate_test_return(item),
                -_candidate_test_drawdown(item),
                -_candidate_test_cost(item),
            ),
        )
        selected_return = _candidate_test_return(selected)
        best_return = _candidate_test_return(best)
        regret = max(best_return - selected_return, 0.0)
        selected_equity *= max(1.0 + selected_return / 100.0, 1e-12)
        best_equity *= max(1.0 + best_return / 100.0, 1e-12)
        regret_values.append(regret)
        best_rank_counter[str(int(best.get("rank") or 0))] += 1
        candidate_counts.append(len(candidates))
        flag_delta = _candidate_flag_delta(selected, best)
        audited.append(
            {
                "fold": int(fold.get("fold") or 0),
                "test_start": fold.get("test_start"),
                "test_end": fold.get("test_end"),
                "candidate_count": len(candidates),
                "selected": _candidate_brief(selected),
                "best": _candidate_brief(best),
                "return_regret_pct": round(regret, 4),
                "cost_delta_vs_best_pct": round(
                    _candidate_test_cost(selected) - _candidate_test_cost(best),
                    4,
                ),
                "drawdown_delta_vs_best_pct": round(
                    _candidate_test_drawdown(selected) - _candidate_test_drawdown(best),
                    4,
                ),
                "flag_delta_vs_best": flag_delta,
            }
        )
    if not audited:
        return {}
    missed = [item for item in audited if float(item.get("return_regret_pct") or 0.0) > 0.0]
    selected_best_flagged = [
        item
        for item in audited
        if float(item.get("return_regret_pct") or 0.0) <= 0.0
        and dict(item.get("selected") or {}).get("test_flags")
    ]
    missed_best_flag_improvements = [
        item
        for item in missed
        if int(dict(item.get("flag_delta_vs_best") or {}).get("best_count") or 0)
        < int(dict(item.get("flag_delta_vs_best") or {}).get("selected_count") or 0)
    ]
    missed_best_higher_cost = [
        item
        for item in missed
        if float(item.get("cost_delta_vs_best_pct") or 0.0) < 0.0
    ]
    missed_best_higher_drawdown = [
        item
        for item in missed
        if float(item.get("drawdown_delta_vs_best_pct") or 0.0) < 0.0
    ]
    missed_best_higher_cost_or_drawdown = [
        item
        for item in missed
        if (
            float(item.get("cost_delta_vs_best_pct") or 0.0) < 0.0
            or float(item.get("drawdown_delta_vs_best_pct") or 0.0) < 0.0
        )
    ]
    missed_best_clean_improvements = [
        item
        for item in missed
        if (
            float(item.get("cost_delta_vs_best_pct") or 0.0) >= 0.0
            and float(item.get("drawdown_delta_vs_best_pct") or 0.0) >= 0.0
            and int(dict(item.get("flag_delta_vs_best") or {}).get("best_count") or 0)
            <= int(dict(item.get("flag_delta_vs_best") or {}).get("selected_count") or 0)
        )
    ]
    highest_regret = sorted(
        audited,
        key=lambda item: (
            float(item.get("return_regret_pct") or 0.0),
            int(dict(item.get("best") or {}).get("rank") or 0),
        ),
        reverse=True,
    )[:limit]
    return {
        "audited_fold_count": len(audited),
        "avg_candidate_count": round(mean(candidate_counts), 4) if candidate_counts else 0.0,
        "selected_best_count": len(audited) - len(missed),
        "missed_best_count": len(missed),
        "missed_best_rate": round(len(missed) / max(len(audited), 1), 6),
        "selected_best_with_test_flags_count": len(selected_best_flagged),
        "missed_best_flag_improvement_count": len(missed_best_flag_improvements),
        "missed_best_higher_cost_count": len(missed_best_higher_cost),
        "missed_best_higher_drawdown_count": len(missed_best_higher_drawdown),
        "missed_best_higher_cost_or_drawdown_count": len(missed_best_higher_cost_or_drawdown),
        "missed_best_clean_improvement_count": len(missed_best_clean_improvements),
        "avg_return_regret_pct": round(mean(regret_values), 4),
        "max_return_regret_pct": round(max(regret_values), 4),
        "selected_compounded_return_pct": round((selected_equity - 1.0) * 100.0, 4),
        "oracle_best_compounded_return_pct": round((best_equity - 1.0) * 100.0, 4),
        "oracle_compounded_improvement_pct": round((best_equity - selected_equity) * 100.0, 4),
        "best_rank_counts": _counter_payload(best_rank_counter),
        "highest_regret_folds": highest_regret,
    }


def _candidate_overlay_names(candidate: dict[str, Any]) -> list[str]:
    overlays = [str(item) for item in candidate.get("after_selection_overlays_applied") or []]
    return overlays or ["none"]


def _aggregate_top_train_candidate_overlay_audit(
    folds: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    overlay_totals: dict[str, dict[str, Any]] = {}
    for fold in folds:
        candidates = [dict(item or {}) for item in fold.get("train_top_test_results") or []]
        candidates = [
            item for item in candidates if item.get("test_return_pct") is not None or item.get("test_result")
        ]
        if not candidates:
            continue
        best = max(
            candidates,
            key=lambda item: (
                _candidate_test_return(item),
                -_candidate_test_drawdown(item),
                -_candidate_test_cost(item),
            ),
        )
        for candidate in candidates:
            fold_return = _candidate_test_return(candidate)
            fold_cost = _candidate_test_cost(candidate)
            fold_drawdown = _candidate_test_drawdown(candidate)
            for overlay in _candidate_overlay_names(candidate):
                total = overlay_totals.setdefault(
                    overlay,
                    {
                        "candidate_count": 0,
                        "folds": set(),
                        "selected_count": 0,
                        "best_count": 0,
                        "returns": [],
                        "cost_drags": [],
                        "drawdowns": [],
                        "train_scores": [],
                        "train_returns": [],
                        "test_flags": Counter(),
                    },
                )
                total["candidate_count"] += 1
                total["folds"].add(int(fold.get("fold") or 0))
                total["selected_count"] += int(bool(candidate.get("is_selected")))
                total["best_count"] += int(candidate == best)
                total["returns"].append(fold_return)
                total["cost_drags"].append(fold_cost)
                total["drawdowns"].append(fold_drawdown)
                if candidate.get("train_selection_score") is not None:
                    total["train_scores"].append(float(candidate.get("train_selection_score") or 0.0))
                total["train_returns"].append(float(candidate.get("train_return_pct") or 0.0))
                total["test_flags"].update(str(item) for item in candidate.get("test_flags") or [])
    audit: dict[str, dict[str, Any]] = {}
    for overlay, stats in sorted(overlay_totals.items()):
        returns = list(stats.get("returns") or [])
        cost_drags = list(stats.get("cost_drags") or [])
        drawdowns = list(stats.get("drawdowns") or [])
        train_scores = list(stats.get("train_scores") or [])
        train_returns = list(stats.get("train_returns") or [])
        if not returns:
            continue
        audit[overlay] = {
            "candidate_count": int(stats["candidate_count"]),
            "fold_count": len(set(stats.get("folds") or set())),
            "selected_count": int(stats["selected_count"]),
            "best_count": int(stats["best_count"]),
            "positive_candidate_count": sum(1 for value in returns if value > 0.0),
            "avg_train_score": round(mean(train_scores), 6) if train_scores else 0.0,
            "avg_train_return_pct": round(mean(train_returns), 4) if train_returns else 0.0,
            "avg_test_return_pct": round(mean(returns), 4),
            "min_test_return_pct": round(min(returns), 4),
            "max_test_return_pct": round(max(returns), 4),
            "avg_test_cost_drag_pct": round(mean(cost_drags), 4) if cost_drags else 0.0,
            "max_test_drawdown_pct": round(max(drawdowns), 4) if drawdowns else 0.0,
            "test_flag_counts": _counter_payload(stats["test_flags"]),
            "folds": sorted(int(item) for item in set(stats.get("folds") or set())),
        }
    return audit


def _aggregate_improvement_backlog_diagnostics(
    folds: list[dict[str, Any]],
    *,
    low_return_threshold_pct: float = 15.0,
    material_upside_pct: float = 1.0,
    selection_regret_threshold_pct: float = 1.0,
    high_drawdown_threshold_pct: float = 10.0,
    high_cost_threshold_pct: float = 20.0,
    risk_reduction_threshold_pct: float = 0.5,
    cost_reduction_threshold_pct: float = 1.0,
    max_return_giveback_pct: float = 5.0,
    limit: int = 8,
) -> dict[str, Any]:
    audited_count = 0
    low_return_candidate_ceiling: list[dict[str, Any]] = []
    clean_selection_misses: list[dict[str, Any]] = []
    risky_or_marginal_oracle_misses: list[dict[str, Any]] = []
    risk_compression_tradeoffs: list[dict[str, Any]] = []
    cost_compression_tradeoffs: list[dict[str, Any]] = []

    for fold in folds:
        candidates = [dict(item or {}) for item in fold.get("train_top_test_results") or []]
        candidates = [
            item
            for item in candidates
            if item.get("test_return_pct") is not None or item.get("test_result")
        ]
        if len(candidates) <= 1:
            continue
        audited_count += 1
        selected = next((item for item in candidates if bool(item.get("is_selected"))), candidates[0])
        selected_return = _candidate_test_return(selected)
        selected_drawdown = _candidate_test_drawdown(selected)
        selected_cost = _candidate_test_cost(selected)
        selected_flag_count = len(_candidate_test_flags(selected))
        best = max(
            candidates,
            key=lambda item: (
                _candidate_test_return(item),
                -_candidate_test_drawdown(item),
                -_candidate_test_cost(item),
            ),
        )
        best_return = _candidate_test_return(best)
        best_drawdown = _candidate_test_drawdown(best)
        best_cost = _candidate_test_cost(best)
        best_flag_count = len(_candidate_test_flags(best))
        return_upside = round(best_return - selected_return, 4)
        base_row = {
            "fold": int(fold.get("fold") or 0),
            "test_start": fold.get("test_start"),
            "test_end": fold.get("test_end"),
            "candidate_count": len(candidates),
            "selected_return_pct": round(selected_return, 4),
            "selected_max_drawdown_pct": round(selected_drawdown, 4),
            "selected_cost_drag_pct": round(selected_cost, 4),
            "best_candidate": _candidate_brief(best),
            "best_return_upside_pct": return_upside,
        }
        if selected_return < float(low_return_threshold_pct) and return_upside <= float(
            material_upside_pct
        ):
            low_return_candidate_ceiling.append(
                {
                    **base_row,
                    "diagnosis": "candidate_generation_ceiling",
                }
            )
        if return_upside >= float(selection_regret_threshold_pct):
            best_is_cleaner_or_equal = (
                best_cost <= selected_cost + 0.0001
                and best_drawdown <= selected_drawdown + 0.0001
                and best_flag_count <= selected_flag_count
            )
            if best_is_cleaner_or_equal:
                clean_selection_misses.append(
                    {
                        **base_row,
                        "diagnosis": "clean_selection_miss",
                    }
                )
            else:
                risky_or_marginal_oracle_misses.append(
                    {
                        **base_row,
                        "diagnosis": "risky_or_marginal_oracle",
                        "best_cost_delta_pct": round(best_cost - selected_cost, 4),
                        "best_drawdown_delta_pct": round(best_drawdown - selected_drawdown, 4),
                        "best_flag_delta": best_flag_count - selected_flag_count,
                    }
                )

        if selected_drawdown >= float(high_drawdown_threshold_pct):
            risk_candidates = [
                item
                for item in candidates
                if (
                    selected_drawdown - _candidate_test_drawdown(item)
                    >= float(risk_reduction_threshold_pct)
                    and selected_return - _candidate_test_return(item)
                    <= float(max_return_giveback_pct)
                )
            ]
            if risk_candidates:
                risk_choice = max(
                    risk_candidates,
                    key=lambda item: (
                        selected_drawdown - _candidate_test_drawdown(item),
                        _candidate_test_return(item),
                        -_candidate_test_cost(item),
                    ),
                )
                risk_compression_tradeoffs.append(
                    {
                        **base_row,
                        "diagnosis": "risk_compression_tradeoff",
                        "tradeoff_candidate": _candidate_brief(risk_choice),
                        "drawdown_reduction_pct": round(
                            selected_drawdown - _candidate_test_drawdown(risk_choice),
                            4,
                        ),
                        "return_giveback_pct": round(
                            selected_return - _candidate_test_return(risk_choice),
                            4,
                        ),
                        "cost_reduction_pct": round(
                            selected_cost - _candidate_test_cost(risk_choice),
                            4,
                        ),
                    }
                )

        if selected_cost >= float(high_cost_threshold_pct):
            cost_candidates = [
                item
                for item in candidates
                if (
                    selected_cost - _candidate_test_cost(item)
                    >= float(cost_reduction_threshold_pct)
                    and selected_return - _candidate_test_return(item)
                    <= float(max_return_giveback_pct)
                )
            ]
            if cost_candidates:
                cost_choice = max(
                    cost_candidates,
                    key=lambda item: (
                        selected_cost - _candidate_test_cost(item),
                        _candidate_test_return(item),
                        -_candidate_test_drawdown(item),
                    ),
                )
                cost_compression_tradeoffs.append(
                    {
                        **base_row,
                        "diagnosis": "cost_compression_tradeoff",
                        "tradeoff_candidate": _candidate_brief(cost_choice),
                        "cost_reduction_pct": round(
                            selected_cost - _candidate_test_cost(cost_choice),
                            4,
                        ),
                        "return_giveback_pct": round(
                            selected_return - _candidate_test_return(cost_choice),
                            4,
                        ),
                        "drawdown_reduction_pct": round(
                            selected_drawdown - _candidate_test_drawdown(cost_choice),
                            4,
                        ),
                    }
                )

    next_step = "collect_top_candidate_audit"
    if audited_count:
        if clean_selection_misses:
            next_step = "tune_selection_policy"
        elif low_return_candidate_ceiling:
            next_step = "expand_candidate_family"
        elif risk_compression_tradeoffs or cost_compression_tradeoffs:
            next_step = "tune_risk_cost_compression"
        else:
            next_step = "stress_test_current_system"

    def limited_rows(
        rows: list[dict[str, Any]],
        *,
        key: str,
        descending: bool = True,
    ) -> list[dict[str, Any]]:
        sign = -1.0 if descending else 1.0
        return sorted(
            rows,
            key=lambda item: (sign * float(item.get(key) or 0.0), int(item.get("fold") or 0)),
        )[:limit]

    return {
        "audited_fold_count": audited_count,
        "thresholds": {
            "low_return_threshold_pct": float(low_return_threshold_pct),
            "material_upside_pct": float(material_upside_pct),
            "selection_regret_threshold_pct": float(selection_regret_threshold_pct),
            "high_drawdown_threshold_pct": float(high_drawdown_threshold_pct),
            "high_cost_threshold_pct": float(high_cost_threshold_pct),
            "risk_reduction_threshold_pct": float(risk_reduction_threshold_pct),
            "cost_reduction_threshold_pct": float(cost_reduction_threshold_pct),
            "max_return_giveback_pct": float(max_return_giveback_pct),
        },
        "next_step": next_step,
        "clean_selection_miss_count": len(clean_selection_misses),
        "risky_or_marginal_oracle_miss_count": len(risky_or_marginal_oracle_misses),
        "low_return_candidate_ceiling_count": len(low_return_candidate_ceiling),
        "risk_compression_tradeoff_count": len(risk_compression_tradeoffs),
        "cost_compression_tradeoff_count": len(cost_compression_tradeoffs),
        "low_return_candidate_ceiling_folds": limited_rows(
            low_return_candidate_ceiling,
            key="selected_return_pct",
            descending=False,
        ),
        "clean_selection_miss_folds": limited_rows(
            clean_selection_misses,
            key="best_return_upside_pct",
        ),
        "risky_or_marginal_oracle_miss_folds": limited_rows(
            risky_or_marginal_oracle_misses,
            key="best_return_upside_pct",
        ),
        "risk_compression_tradeoff_folds": limited_rows(
            risk_compression_tradeoffs,
            key="drawdown_reduction_pct",
        ),
        "cost_compression_tradeoff_folds": limited_rows(
            cost_compression_tradeoffs,
            key="cost_reduction_pct",
        ),
    }


def _selected_config_for_fold(fold: dict[str, Any]) -> dict[str, Any]:
    result = dict(fold.get("test_result") or {})
    train_selected = dict(fold.get("selected_train_result") or {})
    return dict(result.get("config") or {}) or dict(train_selected.get("config") or {})


def _selected_profile_name(config: dict[str, Any], fallback_model_id: str = "") -> str:
    profile = config.get("profile_name")
    if profile:
        return str(profile)
    model_id = str(config.get("model_id") or fallback_model_id or "unknown")
    parts = model_id.split(":")
    return parts[2] if len(parts) > 2 else "unknown"


def _selected_risk_shape_key(config: dict[str, Any], fallback_model_id: str = "") -> str:
    profile = _selected_profile_name(config, fallback_model_id=fallback_model_id)
    return (
        f"profile={profile}|"
        f"maxU={config.get('max_possible_units', 'unknown')}|"
        f"react={config.get('reaction_usd', 'unknown')}|"
        f"hold={config.get('max_hold_bars', 'unknown')}|"
        f"dCool={config.get('defensive_trim_cooldown_bars', 'unknown')}"
    )


def _new_selected_shape_total() -> dict[str, Any]:
    return {
        "equity": 1.0,
        "returns": [],
        "cost_drags": [],
        "max_drawdown_pct": 0.0,
        "risk_tags": Counter(),
        "folds": [],
    }


def _add_selected_shape_total(
    total: dict[str, Any],
    *,
    fold: dict[str, Any],
    result: dict[str, Any],
    fold_return: float,
    fold_cost_drag: float,
    fold_drawdown: float,
    risk_tags: list[str],
) -> None:
    fold_equity = float(result.get("final_equity") or max(1.0 + fold_return / 100.0, 1e-12))
    total["equity"] *= max(fold_equity, 1e-12)
    total["returns"].append(fold_return)
    total["cost_drags"].append(fold_cost_drag)
    total["max_drawdown_pct"] = max(float(total["max_drawdown_pct"]), fold_drawdown)
    total["risk_tags"].update(risk_tags)
    total["folds"].append(int(fold.get("fold") or 0))


def _selected_shape_performance_payload(
    totals: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    performance: dict[str, dict[str, Any]] = {}
    for key, stats in sorted(totals.items()):
        payload = _status_performance_payload(stats)
        payload.update(
            {
                "risk_tag_counts": _counter_payload(stats["risk_tags"]),
                "folds": list(stats.get("folds") or []),
            }
        )
        performance[key] = payload
    return performance


def _stable_json_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _top_float_payload(counter: Counter[str], *, limit: int = 12) -> dict[str, float]:
    items = sorted(counter.items(), key=lambda item: (float(item[1]), str(item[0])), reverse=True)
    return {str(key): round(float(value), 4) for key, value in items[:limit]}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _report_provenance(
    *,
    source_path: Path,
    source_report: dict[str, Any],
    configs: list[MarketStateConfig],
    config_overrides: dict[str, Any],
    folds: list[dict[str, Any]],
) -> dict[str, Any]:
    source_stat = source_path.stat() if source_path.exists() else None
    candidate_payload = [asdict(config) for config in configs]
    selected_payload = [
        {
            "fold": int(fold.get("fold") or 0),
            "selected_model_id": str(fold.get("selected_model_id") or ""),
            "test_return_pct": dict(fold.get("test_result") or {}).get("total_return_pct"),
        }
        for fold in folds
    ]
    return {
        "script_path": str(Path(__file__).resolve()),
        "source_report_path": str(source_path),
        "source_report_exists": bool(source_path.exists()),
        "source_report_sha256": _file_sha256(source_path) if source_path.exists() else "",
        "source_report_mtime": (
            datetime.fromtimestamp(float(source_stat.st_mtime), UTC).isoformat()
            if source_stat is not None
            else ""
        ),
        "source_report_created_at": source_report.get("created_at"),
        "source_report_config_hash": _stable_json_sha256(source_report.get("args") or {}),
        "config_overrides_hash": _stable_json_sha256(config_overrides),
        "candidate_config_hash": _stable_json_sha256(candidate_payload),
        "selected_result_hash": _stable_json_sha256(selected_payload),
    }


def _source_replay_result_metric(result: dict[str, Any], name: str) -> float | None:
    value = result.get(name)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _source_replay_metric_delta(
    replay_result: dict[str, Any],
    source_result: dict[str, Any],
    name: str,
) -> float | None:
    replay_value = _source_replay_result_metric(replay_result, name)
    source_value = _source_replay_result_metric(source_result, name)
    if replay_value is None or source_value is None:
        return None
    return round(replay_value - source_value, 4)


def _source_replay_accepted_risk_tradeoff(
    *,
    return_delta: float | None,
    drawdown_delta: float | None,
    cost_delta: float | None,
) -> bool:
    if drawdown_delta is None or float(drawdown_delta) > -1.0:
        return False
    if return_delta is not None and float(return_delta) < -0.25:
        return False
    if cost_delta is not None and float(cost_delta) > 1.0:
        return False
    return True


def _source_replay_accepted_stress_floor_repair(
    *,
    replay_return: float | None,
    source_return: float | None,
    return_delta: float | None,
    drawdown_delta: float | None,
    cost_delta: float | None,
    replay_overlays: list[str],
) -> bool:
    if "low_return_stress_base_throttle" not in {str(item) for item in replay_overlays}:
        return False
    if replay_return is None or source_return is None or return_delta is None:
        return False
    if drawdown_delta is None or cost_delta is None:
        return False
    if float(replay_return) < 5.0 or float(source_return) < 8.0:
        return False
    if float(return_delta) < -8.0:
        return False
    if float(drawdown_delta) > -5.0:
        return False
    if float(cost_delta) > -2.5:
        return False
    return True


def _source_replay_drift_quality(
    *,
    return_delta: float | None,
    drawdown_delta: float | None,
    cost_delta: float | None,
    material_reasons: list[str],
    accepted_stress_floor_repair: bool = False,
) -> str:
    if not material_reasons:
        return "matched_or_immaterial"
    if _source_replay_accepted_risk_tradeoff(
        return_delta=return_delta,
        drawdown_delta=drawdown_delta,
        cost_delta=cost_delta,
    ):
        return "accepted_risk_reduction"
    if accepted_stress_floor_repair:
        return "stress_floor_repair"
    if return_delta is not None and float(return_delta) > 0.25:
        return "return_improving"
    if drawdown_delta is not None and float(drawdown_delta) > 0.25:
        return "risk_worsening"
    if cost_delta is not None and float(cost_delta) > 0.25:
        return "cost_worsening"
    if return_delta is not None and float(return_delta) < -0.25:
        return "return_worsening"
    return "material_drift"


def _source_replay_lineage_status(
    *,
    selected_model_match: bool,
    overlay_match: bool,
    material_reasons: list[str],
    drift_quality: str,
) -> str:
    if drift_quality == "accepted_risk_reduction":
        return "accepted_risk_reduction"
    if drift_quality == "stress_floor_repair":
        return "stress_floor_repair"
    if drift_quality == "return_improving":
        return "return_improving"
    if material_reasons:
        if not selected_model_match or not overlay_match:
            return "unresolved_material_drift"
        return "unresolved_metric_drift"
    if not selected_model_match:
        if not overlay_match:
            return "immaterial_overlay_variant"
        return "immaterial_model_id_variant"
    if not overlay_match:
        return "immaterial_overlay_variant"
    return "matched_or_immaterial"


_SOURCE_REPLAY_NOOP_OVERLAY_MODEL_PREFIXES = {
    "event_risk_base_throttle": ("wfEventBase",),
    "high_cost_balance_near_miss": ("wfHighCostBalanceNear",),
    "near_miss_context_guard": ("wfNearMissCtxGuard",),
}


def _source_replay_result_event_count(
    result: dict[str, Any],
    name: str,
) -> int:
    counts = dict(result.get("event_counts") or {})
    value = counts.get(name)
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _source_replay_noop_overlays(fold: dict[str, Any]) -> set[str]:
    overlays = {str(item) for item in fold.get("after_selection_overlays_applied") or []}
    test_result = dict(fold.get("test_result") or {})
    config = dict(test_result.get("config") or {})
    noops: set[str] = set()
    if (
        "event_risk_base_throttle" in overlays
        and _source_replay_result_event_count(test_result, "event_risk_base_reduced_adds") <= 0
    ):
        noops.add("event_risk_base_throttle")
    near_miss_units = _source_replay_result_metric({"near_miss_probe_units": config.get("near_miss_probe_units")}, "near_miss_probe_units")
    if near_miss_units is not None and near_miss_units <= 1e-12:
        for overlay in ("high_cost_balance_near_miss", "near_miss_context_guard"):
            if overlay in overlays:
                noops.add(overlay)
    return noops


def _source_replay_effective_overlays(
    overlays: list[str],
    ignored_overlays: set[str],
) -> list[str]:
    return [overlay for overlay in overlays if overlay not in ignored_overlays]


def _source_replay_effective_model_id(
    model_id: str,
    ignored_overlays: set[str],
) -> str:
    if not model_id or not ignored_overlays:
        return model_id
    ignored_prefixes: tuple[str, ...] = tuple(
        prefix
        for overlay in ignored_overlays
        for prefix in _SOURCE_REPLAY_NOOP_OVERLAY_MODEL_PREFIXES.get(overlay, ())
    )
    if not ignored_prefixes:
        return model_id
    return ":".join(
        part for part in model_id.split(":") if not part.startswith(ignored_prefixes)
    )


def _source_replay_fold_drift(
    replay_fold: dict[str, Any],
    source_fold: dict[str, Any],
    *,
    metric_tolerance_pct: float = 0.0001,
    material_metric_tolerance_pct: float = 0.25,
) -> dict[str, Any]:
    replay_test = dict(replay_fold.get("test_result") or {})
    source_test = dict(source_fold.get("test_result") or {})
    replay_overlays = [str(item) for item in replay_fold.get("after_selection_overlays_applied") or []]
    source_overlays = [str(item) for item in source_fold.get("after_selection_overlays_applied") or []]
    replay_model_id = str(replay_fold.get("selected_model_id") or "")
    source_model_id = str(source_fold.get("selected_model_id") or "")
    ignored_noop_overlays = _source_replay_noop_overlays(replay_fold) | _source_replay_noop_overlays(
        source_fold
    )
    effective_replay_overlays = _source_replay_effective_overlays(
        replay_overlays,
        ignored_noop_overlays,
    )
    effective_source_overlays = _source_replay_effective_overlays(
        source_overlays,
        ignored_noop_overlays,
    )
    effective_replay_model_id = _source_replay_effective_model_id(
        replay_model_id,
        ignored_noop_overlays,
    )
    effective_source_model_id = _source_replay_effective_model_id(
        source_model_id,
        ignored_noop_overlays,
    )
    return_delta = _source_replay_metric_delta(replay_test, source_test, "total_return_pct")
    drawdown_delta = _source_replay_metric_delta(replay_test, source_test, "max_drawdown_pct")
    cost_delta = _source_replay_metric_delta(replay_test, source_test, "estimated_cost_drag_pct")
    replay_return = _source_replay_result_metric(replay_test, "total_return_pct")
    source_return = _source_replay_result_metric(source_test, "total_return_pct")
    replay_events = replay_test.get("trade_like_events")
    source_events = source_test.get("trade_like_events")
    event_delta = None
    if replay_events is not None and source_events is not None:
        event_delta = int(replay_events) - int(source_events)
    reasons: list[str] = []
    if effective_replay_model_id != effective_source_model_id:
        reasons.append("model_id")
    if effective_replay_overlays != effective_source_overlays:
        reasons.append("overlays")
    for reason, delta in (
        ("return", return_delta),
        ("drawdown", drawdown_delta),
        ("cost", cost_delta),
    ):
        if delta is not None and abs(float(delta)) > metric_tolerance_pct:
            reasons.append(reason)
    if event_delta not in (None, 0):
        reasons.append("trade_like_events")
    material_reasons = [
        reason
        for reason, delta in (
            ("return", return_delta),
            ("drawdown", drawdown_delta),
            ("cost", cost_delta),
        )
        if delta is not None and abs(float(delta)) >= material_metric_tolerance_pct
    ]
    accepted_risk_tradeoff = _source_replay_accepted_risk_tradeoff(
        return_delta=return_delta,
        drawdown_delta=drawdown_delta,
        cost_delta=cost_delta,
    )
    accepted_stress_floor_repair = _source_replay_accepted_stress_floor_repair(
        replay_return=replay_return,
        source_return=source_return,
        return_delta=return_delta,
        drawdown_delta=drawdown_delta,
        cost_delta=cost_delta,
        replay_overlays=replay_overlays,
    )
    drift_quality = _source_replay_drift_quality(
        return_delta=return_delta,
        drawdown_delta=drawdown_delta,
        cost_delta=cost_delta,
        material_reasons=material_reasons,
        accepted_stress_floor_repair=accepted_stress_floor_repair,
    )
    selected_model_match = effective_replay_model_id == effective_source_model_id
    overlay_match = effective_replay_overlays == effective_source_overlays
    lineage_status = _source_replay_lineage_status(
        selected_model_match=selected_model_match,
        overlay_match=overlay_match,
        material_reasons=material_reasons,
        drift_quality=drift_quality,
    )
    return {
        "fold": int(replay_fold.get("fold") or 0),
        "test_start": replay_fold.get("test_start_at") or replay_fold.get("test_start"),
        "test_end": replay_fold.get("test_end_at") or replay_fold.get("test_end"),
        "selected_model_id": replay_model_id,
        "source_selected_model_id": source_model_id,
        "effective_selected_model_id": effective_replay_model_id,
        "effective_source_selected_model_id": effective_source_model_id,
        "selected_model_match": selected_model_match,
        "after_selection_overlays_applied": replay_overlays,
        "source_after_selection_overlays_applied": source_overlays,
        "effective_after_selection_overlays_applied": effective_replay_overlays,
        "effective_source_after_selection_overlays_applied": effective_source_overlays,
        "overlay_match": overlay_match,
        "ignored_noop_overlays": sorted(ignored_noop_overlays),
        "return_pct": replay_return,
        "source_return_pct": source_return,
        "return_delta_pct": return_delta,
        "max_drawdown_pct": _source_replay_result_metric(replay_test, "max_drawdown_pct"),
        "source_max_drawdown_pct": _source_replay_result_metric(source_test, "max_drawdown_pct"),
        "drawdown_delta_pct": drawdown_delta,
        "cost_drag_pct": _source_replay_result_metric(replay_test, "estimated_cost_drag_pct"),
        "source_cost_drag_pct": _source_replay_result_metric(source_test, "estimated_cost_drag_pct"),
        "cost_delta_pct": cost_delta,
        "trade_like_events": int(replay_events) if replay_events is not None else None,
        "source_trade_like_events": int(source_events) if source_events is not None else None,
        "trade_like_events_delta": event_delta,
        "mismatch_reasons": reasons,
        "material_mismatch_reasons": material_reasons,
        "accepted_risk_tradeoff": accepted_risk_tradeoff,
        "accepted_stress_floor_repair": accepted_stress_floor_repair,
        "drift_quality": drift_quality,
        "lineage_status": lineage_status,
    }


def _source_replay_diagnostics(
    source_report: dict[str, Any],
    folds: list[dict[str, Any]],
    *,
    limit: int = 8,
) -> dict[str, Any]:
    source_folds = {
        int(fold.get("fold") or 0): fold
        for fold in source_report.get("folds") or []
        if isinstance(fold, dict) and int(fold.get("fold") or 0) > 0
    }
    if not source_folds or not folds:
        return {}
    drifts: list[dict[str, Any]] = []
    missing_source_folds: list[int] = []
    for fold in folds:
        fold_number = int(fold.get("fold") or 0)
        source_fold = source_folds.get(fold_number)
        if not source_fold:
            missing_source_folds.append(fold_number)
            continue
        drifts.append(_source_replay_fold_drift(fold, source_fold))
    if not drifts:
        return {
            "compared_fold_count": 0,
            "missing_source_fold_count": len(missing_source_folds),
            "missing_source_folds": missing_source_folds,
            "folds": [],
        }

    def non_null_values(name: str) -> list[float]:
        return [float(item[name]) for item in drifts if item.get(name) is not None]

    return_deltas = non_null_values("return_delta_pct")
    drawdown_deltas = non_null_values("drawdown_delta_pct")
    cost_deltas = non_null_values("cost_delta_pct")
    event_deltas = [
        int(item["trade_like_events_delta"])
        for item in drifts
        if item.get("trade_like_events_delta") is not None
    ]
    model_mismatches = [item for item in drifts if not bool(item.get("selected_model_match"))]
    overlay_mismatches = [item for item in drifts if not bool(item.get("overlay_match"))]
    metric_mismatches = [item for item in drifts if item.get("mismatch_reasons")]
    material_mismatches = [item for item in drifts if item.get("material_mismatch_reasons")]
    accepted_risk_tradeoffs = [
        item for item in material_mismatches if bool(item.get("accepted_risk_tradeoff"))
    ]
    stress_floor_repairs = [
        item for item in material_mismatches if bool(item.get("accepted_stress_floor_repair"))
    ]
    beneficial_return_improvements = [
        item
        for item in material_mismatches
        if str(item.get("lineage_status") or "") == "return_improving"
    ]
    resolved_material_statuses = {
        "accepted_risk_reduction",
        "stress_floor_repair",
        "return_improving",
    }
    unresolved_material_mismatches = [
        item
        for item in material_mismatches
        if str(item.get("lineage_status") or "") not in resolved_material_statuses
    ]
    immaterial_model_mismatches = [
        item
        for item in model_mismatches
        if str(item.get("lineage_status") or "")
        in {"immaterial_model_id_variant", "immaterial_overlay_variant"}
    ]
    accepted_model_mismatches = [
        item
        for item in model_mismatches
        if str(item.get("lineage_status") or "") == "accepted_risk_reduction"
    ]
    stress_floor_model_mismatches = [
        item
        for item in model_mismatches
        if str(item.get("lineage_status") or "") == "stress_floor_repair"
    ]
    beneficial_model_mismatches = [
        item for item in model_mismatches if str(item.get("lineage_status") or "") == "return_improving"
    ]
    unresolved_model_mismatches = [
        item
        for item in model_mismatches
        if str(item.get("lineage_status") or "").startswith("unresolved_")
    ]

    def largest_by_abs(name: str) -> list[dict[str, Any]]:
        return sorted(
            drifts,
            key=lambda item: (-abs(float(item.get(name) or 0.0)), int(item.get("fold") or 0)),
        )[:limit]

    return {
        "compared_fold_count": len(drifts),
        "missing_source_fold_count": len(missing_source_folds),
        "missing_source_folds": missing_source_folds,
        "selected_model_match_count": len(drifts) - len(model_mismatches),
        "selected_model_mismatch_count": len(model_mismatches),
        "selected_model_immaterial_mismatch_count": len(immaterial_model_mismatches),
        "selected_model_accepted_risk_tradeoff_count": len(accepted_model_mismatches),
        "selected_model_stress_floor_repair_count": len(stress_floor_model_mismatches),
        "selected_model_beneficial_mismatch_count": len(beneficial_model_mismatches),
        "selected_model_unresolved_mismatch_count": len(unresolved_model_mismatches),
        "overlay_match_count": len(drifts) - len(overlay_mismatches),
        "overlay_mismatch_count": len(overlay_mismatches),
        "metric_mismatch_count": len(metric_mismatches),
        "material_metric_mismatch_count": len(material_mismatches),
        "accepted_risk_tradeoff_count": len(accepted_risk_tradeoffs),
        "stress_floor_repair_count": len(stress_floor_repairs),
        "beneficial_return_improvement_count": len(beneficial_return_improvements),
        "unresolved_material_metric_mismatch_count": len(unresolved_material_mismatches),
        "avg_return_delta_pct": round(mean(return_deltas), 4) if return_deltas else 0.0,
        "max_abs_return_delta_pct": (
            round(max(abs(value) for value in return_deltas), 4) if return_deltas else 0.0
        ),
        "avg_drawdown_delta_pct": round(mean(drawdown_deltas), 4) if drawdown_deltas else 0.0,
        "max_abs_drawdown_delta_pct": (
            round(max(abs(value) for value in drawdown_deltas), 4) if drawdown_deltas else 0.0
        ),
        "avg_cost_delta_pct": round(mean(cost_deltas), 4) if cost_deltas else 0.0,
        "max_abs_cost_delta_pct": (
            round(max(abs(value) for value in cost_deltas), 4) if cost_deltas else 0.0
        ),
        "total_cost_delta_pct": round(sum(cost_deltas), 4) if cost_deltas else 0.0,
        "total_trade_like_events_delta": sum(event_deltas) if event_deltas else 0,
        "mismatch_reason_counts": _counter_payload(
            Counter(reason for item in drifts for reason in item.get("mismatch_reasons") or [])
        ),
        "material_mismatch_reason_counts": _counter_payload(
            Counter(reason for item in drifts for reason in item.get("material_mismatch_reasons") or [])
        ),
        "drift_quality_counts": _counter_payload(
            Counter(str(item.get("drift_quality") or "unknown") for item in drifts)
        ),
        "lineage_status_counts": _counter_payload(
            Counter(str(item.get("lineage_status") or "unknown") for item in drifts)
        ),
        "model_mismatch_status_counts": _counter_payload(
            Counter(str(item.get("lineage_status") or "unknown") for item in model_mismatches)
        ),
        "largest_return_drift_folds": largest_by_abs("return_delta_pct"),
        "largest_drawdown_drift_folds": largest_by_abs("drawdown_delta_pct"),
        "largest_cost_drift_folds": largest_by_abs("cost_delta_pct"),
        "accepted_risk_tradeoff_folds": accepted_risk_tradeoffs[:limit],
        "stress_floor_repair_folds": stress_floor_repairs[:limit],
        "beneficial_return_improvement_folds": beneficial_return_improvements[:limit],
        "unresolved_material_mismatch_folds": unresolved_material_mismatches[:limit],
        "immaterial_model_mismatch_folds": immaterial_model_mismatches[:limit],
        "accepted_model_mismatch_folds": accepted_model_mismatches[:limit],
        "stress_floor_model_mismatch_folds": stress_floor_model_mismatches[:limit],
        "beneficial_model_mismatch_folds": beneficial_model_mismatches[:limit],
        "unresolved_model_mismatch_folds": unresolved_model_mismatches[:limit],
        "model_mismatch_folds": model_mismatches[:limit],
        "overlay_mismatch_folds": overlay_mismatches[:limit],
        "folds": drifts,
    }


def _source_replay_lineage_guard(
    diagnostics: dict[str, Any],
    *,
    fail_on_unresolved_material: bool,
) -> dict[str, Any]:
    if not diagnostics:
        return {
            "status": "not_applicable",
            "failed": False,
            "fail_on_unresolved_material": bool(fail_on_unresolved_material),
            "message": "No source replay diagnostics were available.",
        }
    unresolved_material = int(diagnostics.get("unresolved_material_metric_mismatch_count") or 0)
    unresolved_model = int(diagnostics.get("selected_model_unresolved_mismatch_count") or 0)
    compared = int(diagnostics.get("compared_fold_count") or 0)
    unresolved_material_folds = [
        int(item.get("fold") or 0)
        for item in list(diagnostics.get("unresolved_material_mismatch_folds") or [])
        if isinstance(item, dict) and int(item.get("fold") or 0) > 0
    ]
    failed = bool(fail_on_unresolved_material and unresolved_material > 0)
    status = "fail" if failed else ("watch" if unresolved_material > 0 else "pass")
    if failed:
        message = (
            "Source replay lineage guard failed: unresolved material drift exists "
            f"({unresolved_material}/{compared} compared folds; "
            f"model_unresolved={unresolved_model}; folds={unresolved_material_folds})."
        )
    elif unresolved_material > 0:
        message = (
            "Source replay lineage guard is in watch mode: unresolved material drift exists "
            f"({unresolved_material}/{compared} compared folds; "
            f"model_unresolved={unresolved_model}; folds={unresolved_material_folds})."
        )
    else:
        message = (
            "Source replay lineage guard passed: no unresolved material drift was detected "
            f"across {compared} compared folds."
        )
    return {
        "status": status,
        "failed": failed,
        "fail_on_unresolved_material": bool(fail_on_unresolved_material),
        "compared_fold_count": compared,
        "unresolved_material_metric_mismatch_count": unresolved_material,
        "selected_model_unresolved_mismatch_count": unresolved_model,
        "unresolved_material_folds": unresolved_material_folds,
        "message": message,
    }


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
    selected_reaction_usd_counter: Counter[str] = Counter()
    selected_defensive_cooldown_counter: Counter[str] = Counter()
    selected_risk_shape_counter: Counter[str] = Counter()
    after_selection_overlay_counter: Counter[str] = Counter()
    after_selection_overlay_skipped_counter: Counter[str] = Counter()
    after_selection_overlay_skip_reason_counter: Counter[str] = Counter()
    after_selection_overlay_count_counter: Counter[str] = Counter()
    test_health_counter: Counter[str] = Counter()
    flag_counter: Counter[str] = Counter()
    borderline_flag_counter: Counter[str] = Counter()
    event_counter: Counter[str] = Counter()
    trade_like_event_counts: list[int] = []
    battle_add_counts: list[int] = []
    add_side_counter: Counter[str] = Counter()
    add_role_counter: Counter[str] = Counter()
    cost_by_action_counter: Counter[str] = Counter()
    cost_by_side_counter: Counter[str] = Counter()
    cost_by_role_counter: Counter[str] = Counter()
    cost_by_reason_counter: Counter[str] = Counter()
    cost_by_action_reason_counter: Counter[str] = Counter()
    high_drawdown_recovery_hours: list[float] = []
    all_drawdown_recovery_hours: list[float] = []
    recovered_drawdown_count = 0
    high_drawdown_recovered_count = 0
    high_drawdown_slow_recovery_count = 0
    high_drawdown_unrecovered_count = 0
    drawdown_recovery_rows: list[dict[str, Any]] = []
    flag_totals: dict[str, dict[str, Any]] = {}
    regime_totals: dict[str, dict[str, Any]] = {}
    selected_reaction_usd_totals: dict[str, dict[str, Any]] = {}
    selected_risk_shape_totals: dict[str, dict[str, Any]] = {}
    for fold in folds:
        result = fold.get("test_result")
        if not result:
            continue
        fold_return = float(result.get("total_return_pct") or 0.0)
        fold_cost_drag = float(result.get("estimated_cost_drag_pct") or 0.0)
        fold_drawdown = float(result.get("max_drawdown_pct") or 0.0)
        equity *= float(result.get("final_equity") or 1.0)
        returns.append(fold_return)
        cost_drags.append(fold_cost_drag)
        carry_costs.append(float(result.get("modeled_carry_cost_fraction_sum") or 0.0))
        max_mdd = max(max_mdd, fold_drawdown)
        selected_counter[str(fold.get("selected_model_id") or "unknown")] += 1
        overlays_applied = [str(item) for item in fold.get("after_selection_overlays_applied") or []]
        overlays_skipped = [str(item) for item in fold.get("after_selection_overlays_skipped") or []]
        after_selection_overlay_counter.update(overlays_applied)
        after_selection_overlay_count_counter[str(len(overlays_applied))] += 1
        for skipped in overlays_skipped:
            overlay_name, _, reason = skipped.partition(":")
            after_selection_overlay_skipped_counter[overlay_name or skipped] += 1
            if reason:
                after_selection_overlay_skip_reason_counter[reason] += 1
        selected_config = _selected_config_for_fold(fold)
        model_id = str(selected_config.get("model_id") or fold.get("selected_model_id") or "unknown")
        selected_profile_counter[_selected_profile_name(selected_config, fallback_model_id=model_id)] += 1
        selected_hold_counter[str(selected_config.get("max_hold_bars", "unknown"))] += 1
        selected_max_units_counter[str(selected_config.get("max_possible_units", "unknown"))] += 1
        reaction_usd_key = str(selected_config.get("reaction_usd", "unknown"))
        defensive_cooldown_key = str(
            selected_config.get("defensive_trim_cooldown_bars", "unknown")
        )
        risk_shape_key = _selected_risk_shape_key(selected_config, fallback_model_id=model_id)
        selected_reaction_usd_counter[reaction_usd_key] += 1
        selected_defensive_cooldown_counter[defensive_cooldown_key] += 1
        selected_risk_shape_counter[risk_shape_key] += 1
        diagnostics = dict(result.get("event_diagnostics") or {})
        event_counter.update({str(k): int(v) for k, v in dict(result.get("event_counts") or {}).items()})
        trade_like_events = int(result.get("trade_like_events") or diagnostics.get("add_events") or 0)
        trade_like_event_counts.append(trade_like_events)
        battle_add_counts.append(int(result.get("battle_adds") or 0))
        add_side_counter.update(
            {str(key): int(value) for key, value in dict(diagnostics.get("add_by_side") or {}).items()}
        )
        add_role_counter.update(
            {str(key): int(value) for key, value in dict(diagnostics.get("add_by_role") or {}).items()}
        )
        cost_diagnostics = dict(result.get("cost_diagnostics") or {})
        for key, value in dict(cost_diagnostics.get("by_action_pct") or {}).items():
            cost_by_action_counter[str(key)] += float(value or 0.0)
        for key, value in dict(cost_diagnostics.get("by_side_pct") or {}).items():
            cost_by_side_counter[str(key)] += float(value or 0.0)
        for key, value in dict(cost_diagnostics.get("by_role_pct") or {}).items():
            cost_by_role_counter[str(key)] += float(value or 0.0)
        for key, value in dict(cost_diagnostics.get("by_reason_pct") or {}).items():
            cost_by_reason_counter[str(key)] += float(value or 0.0)
        for key, value in dict(cost_diagnostics.get("by_action_reason_pct") or {}).items():
            cost_by_action_reason_counter[str(key)] += float(value or 0.0)
        drawdown_detail = dict(result.get("max_drawdown_detail") or {})
        recovered_peak = bool(drawdown_detail.get("recovered_peak"))
        if recovered_peak:
            recovered_drawdown_count += 1
        recovery_hours_raw = drawdown_detail.get("trough_to_recovery_hours")
        recovery_hours = float(recovery_hours_raw) if recovery_hours_raw is not None else None
        if recovery_hours is not None:
            all_drawdown_recovery_hours.append(recovery_hours)
        if fold_drawdown >= 10.0:
            if recovered_peak:
                high_drawdown_recovered_count += 1
            else:
                high_drawdown_unrecovered_count += 1
            if recovery_hours is not None:
                high_drawdown_recovery_hours.append(recovery_hours)
                if recovery_hours >= 168.0:
                    high_drawdown_slow_recovery_count += 1
            drawdown_recovery_rows.append(
                {
                    "fold": int(fold.get("fold") or 0),
                    "return_pct": round(fold_return, 4),
                    "drawdown_pct": round(fold_drawdown, 4),
                    "peak_ts": drawdown_detail.get("peak_ts"),
                    "trough_ts": drawdown_detail.get("trough_ts"),
                    "trough_side": drawdown_detail.get("trough_side"),
                    "trough_regime": drawdown_detail.get("trough_regime"),
                    "recovered_peak": recovered_peak,
                    "recovery_hours": round(recovery_hours, 4) if recovery_hours is not None else None,
                }
            )
        test_health_counter[str(diagnostics.get("health") or "unknown")] += 1
        risk_brief = _fold_risk_brief(fold)
        risk_tags = _fold_risk_tags(
            risk_brief,
            low_return_threshold_pct=5.0,
            high_drawdown_threshold_pct=10.0,
            high_cost_threshold_pct=20.0,
            high_overlay_count_threshold=5,
        )
        _add_selected_shape_total(
            selected_reaction_usd_totals.setdefault(
                reaction_usd_key,
                _new_selected_shape_total(),
            ),
            fold=fold,
            result=dict(result),
            fold_return=fold_return,
            fold_cost_drag=fold_cost_drag,
            fold_drawdown=fold_drawdown,
            risk_tags=risk_tags,
        )
        _add_selected_shape_total(
            selected_risk_shape_totals.setdefault(
                risk_shape_key,
                _new_selected_shape_total(),
            ),
            fold=fold,
            result=dict(result),
            fold_return=fold_return,
            fold_cost_drag=fold_cost_drag,
            fold_drawdown=fold_drawdown,
            risk_tags=risk_tags,
        )
        for flag in diagnostics.get("flags") or []:
            flag_name = str(flag)
            flag_counter[flag_name] += 1
            total = flag_totals.setdefault(
                flag_name,
                {
                    "fold_count": 0,
                    "positive_fold_count": 0,
                    "equity": 1.0,
                    "returns": [],
                    "cost_drags": [],
                    "max_drawdown_pct": 0.0,
                },
            )
            total["fold_count"] += 1
            total["positive_fold_count"] += int(fold_return > 0.0)
            total["equity"] *= max(1.0 + fold_return / 100.0, 1e-12)
            total["returns"].append(fold_return)
            total["cost_drags"].append(fold_cost_drag)
            total["max_drawdown_pct"] = max(float(total["max_drawdown_pct"]), fold_drawdown)
        borderline_flag_counter.update(str(flag) for flag in diagnostics.get("borderline_flags") or [])
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
    flag_performance = {
        flag: {
            "fold_count": int(stats["fold_count"]),
            "positive_fold_count": int(stats["positive_fold_count"]),
            "compounded_return_pct": round((float(stats["equity"]) - 1.0) * 100.0, 4),
            "avg_return_pct": round(mean(stats["returns"]), 4),
            "min_return_pct": round(min(stats["returns"]), 4),
            "max_return_pct": round(max(stats["returns"]), 4),
            "max_drawdown_pct": round(float(stats["max_drawdown_pct"]), 4),
            "avg_cost_drag_pct": round(mean(stats["cost_drags"]), 4),
        }
        for flag, stats in sorted(flag_totals.items())
    }
    total_add_side_count = sum(add_side_counter.values())
    total_add_role_count = sum(add_role_counter.values())
    total_trade_like_event_count = sum(trade_like_event_counts)
    total_battle_add_count = sum(battle_add_counts)
    directional_add_count = add_side_counter.get("long", 0) + add_side_counter.get("short", 0)
    dominant_add_side, dominant_add_side_count = (
        max(
            ((side, add_side_counter.get(side, 0)) for side in ("long", "short")),
            key=lambda item: (int(item[1]), str(item[0])),
        )
        if directional_add_count > 0
        else ("none", 0)
    )
    known_add_role_counter = Counter(
        {
            role: count
            for role, count in add_role_counter.items()
            if role not in {"", "unknown"}
        }
    )
    known_add_role_count = sum(known_add_role_counter.values())
    dominant_add_role, dominant_add_role_count = (
        max(known_add_role_counter.items(), key=lambda item: (int(item[1]), str(item[0])))
        if known_add_role_counter
        else ("none", 0)
    )
    dominant_add_side_share = (
        dominant_add_side_count / max(directional_add_count, 1)
        if directional_add_count > 0
        else 0.0
    )
    dominant_add_role_share = (
        dominant_add_role_count / max(known_add_role_count, 1)
        if known_add_role_count > 0
        else 0.0
    )
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
        "total_trade_like_events": sum(trade_like_event_counts),
        "avg_trade_like_events": (
            round(mean(trade_like_event_counts), 4) if trade_like_event_counts else 0.0
        ),
        "min_trade_like_events": min(trade_like_event_counts) if trade_like_event_counts else 0,
        "max_trade_like_events": max(trade_like_event_counts) if trade_like_event_counts else 0,
        "total_battle_adds": total_battle_add_count,
        "battle_add_share": round(total_battle_add_count / max(total_trade_like_event_count, 1), 4),
        "battle_participation_fold_count": sum(1 for value in battle_add_counts if value > 0),
        "test_add_by_side_counts": _counter_payload(add_side_counter),
        "test_add_by_side_share": {
            side: round(count / max(total_add_side_count, 1), 4)
            for side, count in sorted(add_side_counter.items())
        },
        "test_add_by_role_counts": _counter_payload(add_role_counter),
        "test_add_by_role_share": {
            role: round(count / max(total_add_role_count, 1), 4)
            for role, count in sorted(add_role_counter.items())
        },
        "test_add_distribution_diagnostics": {
            "directional_add_count": int(directional_add_count),
            "dominant_add_side": str(dominant_add_side),
            "dominant_add_side_share": round(dominant_add_side_share, 4),
            "side_skew": (
                round(
                    abs(add_side_counter.get("long", 0) - add_side_counter.get("short", 0))
                    / max(directional_add_count, 1),
                    4,
                )
                if directional_add_count > 0
                else 0.0
            ),
            "known_add_role_count": int(known_add_role_count),
            "dominant_add_role": str(dominant_add_role),
            "dominant_add_role_share": round(dominant_add_role_share, 4),
        },
        "test_cost_attribution": {
            "total_modeled_trade_cost_pct": round(
                sum(float(value) for value in cost_by_action_counter.values()),
                4,
            ),
            "by_action_pct": _top_float_payload(cost_by_action_counter),
            "by_side_pct": _top_float_payload(cost_by_side_counter),
            "by_role_pct": _top_float_payload(cost_by_role_counter),
            "by_reason_pct": _top_float_payload(cost_by_reason_counter),
            "by_action_reason_pct": _top_float_payload(cost_by_action_reason_counter),
        },
        "drawdown_recovery_diagnostics": {
            "recovered_drawdown_count": int(recovered_drawdown_count),
            "high_drawdown_count": int(len(drawdown_recovery_rows)),
            "high_drawdown_recovered_count": int(high_drawdown_recovered_count),
            "high_drawdown_unrecovered_count": int(high_drawdown_unrecovered_count),
            "high_drawdown_slow_recovery_count": int(high_drawdown_slow_recovery_count),
            "avg_drawdown_recovery_hours": (
                round(mean(all_drawdown_recovery_hours), 4) if all_drawdown_recovery_hours else None
            ),
            "avg_high_drawdown_recovery_hours": (
                round(mean(high_drawdown_recovery_hours), 4) if high_drawdown_recovery_hours else None
            ),
            "max_high_drawdown_recovery_hours": (
                round(max(high_drawdown_recovery_hours), 4) if high_drawdown_recovery_hours else None
            ),
            "high_drawdown_folds": sorted(
                drawdown_recovery_rows,
                key=lambda item: (-float(item.get("drawdown_pct") or 0.0), int(item.get("fold") or 0)),
            ),
        },
        "unique_selected_model_count": len(selected_counter),
        "selected_model_counts": _counter_payload(selected_counter),
        "selected_profile_counts": _counter_payload(selected_profile_counter),
        "selected_hold_counts": _counter_payload(selected_hold_counter),
        "selected_max_units_counts": _counter_payload(selected_max_units_counter),
        "selected_reaction_usd_counts": _counter_payload(selected_reaction_usd_counter),
        "selected_defensive_cooldown_counts": _counter_payload(
            selected_defensive_cooldown_counter
        ),
        "selected_risk_shape_counts": _counter_payload(selected_risk_shape_counter),
        "selected_reaction_usd_performance": _selected_shape_performance_payload(
            selected_reaction_usd_totals
        ),
        "selected_risk_shape_performance": _selected_shape_performance_payload(
            selected_risk_shape_totals
        ),
        "after_selection_overlay_counts": _counter_payload(after_selection_overlay_counter),
        "after_selection_overlay_skipped_counts": _counter_payload(after_selection_overlay_skipped_counter),
        "after_selection_overlay_skip_reason_counts": _counter_payload(
            after_selection_overlay_skip_reason_counter
        ),
        "after_selection_overlay_count_distribution": _counter_payload(
            after_selection_overlay_count_counter
        ),
        "test_health_counts": _counter_payload(test_health_counter),
        "test_flag_counts": _counter_payload(flag_counter),
        "test_borderline_flag_counts": _counter_payload(borderline_flag_counter),
        "test_flag_performance": flag_performance,
        "test_event_counts": _counter_payload(event_counter),
        "test_regime_performance": regime_performance,
        "after_selection_confirmation": _aggregate_after_selection_confirmations(folds),
        "after_selection_recent_oos_blocks": _aggregate_after_selection_recent_oos_blocks(folds),
        "after_selection_overlay_oos_performance": (
            _aggregate_after_selection_overlay_oos_performance(folds)
        ),
        "top_train_candidate_audit": _aggregate_top_train_candidate_audit(folds),
        "top_train_candidate_overlay_audit": _aggregate_top_train_candidate_overlay_audit(folds),
        "improvement_backlog_diagnostics": _aggregate_improvement_backlog_diagnostics(folds),
        "regime_drift_diagnostics": _aggregate_regime_drift_diagnostics(folds),
        "weak_fold_diagnostics": _aggregate_weak_fold_diagnostics(folds),
    }


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    aggregate = dict(report.get("aggregate") or {})
    config_overrides = dict(report.get("config_overrides") or {})
    provenance = dict(report.get("provenance") or {})
    after_selection_confirmation = dict(aggregate.get("after_selection_confirmation") or {})
    recent_oos_blocks = dict(aggregate.get("after_selection_recent_oos_blocks") or {})
    overlay_oos_performance = dict(
        aggregate.get("after_selection_overlay_oos_performance") or {}
    )
    selected_reaction_usd_performance = dict(
        aggregate.get("selected_reaction_usd_performance") or {}
    )
    selected_risk_shape_performance = dict(
        aggregate.get("selected_risk_shape_performance") or {}
    )
    test_cost_attribution = dict(aggregate.get("test_cost_attribution") or {})
    drawdown_recovery_diagnostics = dict(
        aggregate.get("drawdown_recovery_diagnostics") or {}
    )
    top_candidate_audit = dict(aggregate.get("top_train_candidate_audit") or {})
    top_candidate_overlay_audit = dict(
        aggregate.get("top_train_candidate_overlay_audit") or {}
    )
    improvement_backlog = dict(aggregate.get("improvement_backlog_diagnostics") or {})
    regime_drift_diagnostics = dict(aggregate.get("regime_drift_diagnostics") or {})
    source_replay_diagnostics = dict(report.get("source_replay_diagnostics") or {})
    source_replay_lineage_guard = dict(report.get("source_replay_lineage_guard") or {})

    def top_counter_items(payload: dict[str, Any], limit: int = 20) -> dict[str, int]:
        items = sorted(
            ((str(key), int(value)) for key, value in dict(payload or {}).items()),
            key=lambda item: (-item[1], item[0]),
        )
        return dict(items[:limit])

    def fold_model_summary(fold: dict[str, Any]) -> str:
        config = _selected_config_for_fold(fold)
        model_id = str(config.get("model_id") or fold.get("selected_model_id") or "unknown")
        profile = _selected_profile_name(config, fallback_model_id=model_id)
        max_units = config.get("max_possible_units", "unknown")
        reaction_usd = config.get("reaction_usd", "unknown")
        hold = config.get("max_hold_bars", "unknown")
        defensive_cooldown = config.get("defensive_trim_cooldown_bars", "unknown")
        return f"{profile}; maxU={max_units}; react={reaction_usd}; hold={hold}; dCool={defensive_cooldown}"

    def confirmation_summary(fold: dict[str, Any]) -> str:
        return _fold_confirmation_status(fold)

    def risk_table_rows(items: list[dict[str, Any]]) -> list[str]:
        rows = [
            "| fold | test | return % | max DD % | cost % | cost/return | tags | overlays | confirmation | flags |",
            "|---:|---|---:|---:|---:|---:|---|---|---|---|",
        ]
        for item in items:
            rows.append(
                f"| {item.get('fold')} | {item.get('test_start')} to {item.get('test_end')} | "
                f"{item.get('return_pct')} | {item.get('max_drawdown_pct')} | "
                f"{item.get('cost_drag_pct')} | {item.get('cost_to_return_ratio')} | "
                f"`{','.join(item.get('risk_tags') or []) or 'none'}` | "
                f"`{','.join(item.get('overlays') or []) or 'none'}` | "
                f"`{item.get('confirmation')}` | {', '.join(item.get('flags') or []) or 'none'} |"
            )
        return rows

    def root_cause_rows(items: list[dict[str, Any]]) -> list[str]:
        rows = [
            "| fold | test | return % | events/expected | sample | soft circuit share | top no-trade blockers | add side | add role | flags |",
            "|---:|---|---:|---:|---|---:|---|---|---|---|",
        ]
        for item in items:
            blockers = ", ".join(
                f"{entry.get('reason')}:{entry.get('count')}"
                for entry in list(item.get("top_no_trade_reasons") or [])
            ) or "none"
            hard_flags = [str(flag) for flag in item.get("flags") or []]
            borderline_flags = [str(flag) for flag in item.get("borderline_flags") or []]
            flag_text = ", ".join(hard_flags) if hard_flags else "none"
            if borderline_flags:
                flag_text = f"{flag_text}; borderline={','.join(borderline_flags)}"
            rows.append(
                f"| {item.get('fold')} | {item.get('test_start')} to {item.get('test_end')} | "
                f"{item.get('return_pct')} | "
                f"{item.get('trade_like_events')}/{item.get('effective_expected_add_events', item.get('expected_add_events'))} "
                f"(raw {item.get('expected_add_events')}) | "
                f"`{item.get('sample_mode')}` | "
                f"{item.get('equity_soft_circuit_cooldown_share')} | "
                f"`{blockers}` | "
                f"`{json.dumps(item.get('add_by_side', {}), ensure_ascii=False)}` | "
                f"`{json.dumps(item.get('add_by_role', {}), ensure_ascii=False)}` | "
                f"{flag_text} |"
            )
        return rows

    def regime_drift_rows(items: list[dict[str, Any]]) -> list[str]:
        rows = [
            "| fold | test | return % | drift | train dominant | test dominant | largest shift | train return dependency |",
            "|---:|---|---:|---:|---|---|---|---|",
        ]
        for item in items:
            dependency = dict(item.get("train_regime_dependency") or {})
            rows.append(
                f"| {item.get('fold')} | {item.get('test_start')} to {item.get('test_end')} | "
                f"{item.get('return_pct')} | {item.get('regime_share_drift')} | "
                f"`{item.get('train_dominant_regime')}:{item.get('train_dominant_share')}` | "
                f"`{item.get('test_dominant_regime')}:{item.get('test_dominant_share')}` | "
                f"`{item.get('largest_shift_regime')}:{item.get('largest_shift')}` | "
                f"`{dependency.get('dominant_regime')}:{dependency.get('dominant_regime_return_share')}` |"
            )
        return rows

    def cost_attribution_rows(section: str, payload: dict[str, Any]) -> list[str]:
        rows = [
            f"| {section} | modeled cost % |",
            "|---|---:|",
        ]
        for key, value in dict(payload or {}).items():
            rows.append(f"| `{key}` | {value} |")
        return rows

    def drawdown_recovery_rows(items: list[dict[str, Any]]) -> list[str]:
        rows = [
            "| fold | return % | max DD % | peak | trough | recovered | recovery hours | trough regime | trough side |",
            "|---:|---:|---:|---|---|---:|---:|---|---|",
        ]
        for item in items:
            rows.append(
                f"| {item.get('fold')} | {item.get('return_pct')} | {item.get('drawdown_pct')} | "
                f"{item.get('peak_ts') or ''} | {item.get('trough_ts') or ''} | "
                f"{item.get('recovered_peak')} | {item.get('recovery_hours')} | "
                f"`{item.get('trough_regime') or ''}` | `{item.get('trough_side') or ''}` |"
            )
        return rows

    def source_replay_drift_rows(items: list[dict[str, Any]]) -> list[str]:
        rows = [
            "| fold | return delta % | DD delta % | cost delta % | event delta | model match | overlay match | accepted | quality | lineage status | reasons |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|",
        ]
        for item in items:
            reasons = ",".join(str(reason) for reason in item.get("mismatch_reasons") or []) or "none"
            rows.append(
                f"| {item.get('fold')} | {item.get('return_delta_pct')} | "
                f"{item.get('drawdown_delta_pct')} | {item.get('cost_delta_pct')} | "
                f"{item.get('trade_like_events_delta')} | {item.get('selected_model_match')} | "
                f"{item.get('overlay_match')} | {item.get('accepted_risk_tradeoff')} | "
                f"`{item.get('drift_quality')}` | `{item.get('lineage_status')}` | `{reasons}` |"
            )
        return rows

    def selected_shape_rows(items: dict[str, Any], *, key_label: str, limit: int = 20) -> list[str]:
        rows = [
            f"| {key_label} | folds | positive | compounded return % | avg return % | min/max return % | max DD % | avg cost % | risk tags | fold ids |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
        ]
        sorted_items = sorted(
            ((str(key), dict(stats or {})) for key, stats in dict(items or {}).items()),
            key=lambda item: (-int(item[1].get("fold_count") or 0), item[0]),
        )
        for key, stats in sorted_items[:limit]:
            risk_tag_counts = json.dumps(stats.get("risk_tag_counts", {}), ensure_ascii=False)
            fold_ids = ",".join(str(item) for item in stats.get("folds") or []) or "none"
            rows.append(
                f"| `{key}` | {stats.get('fold_count')} | {stats.get('positive_fold_count')} | "
                f"{stats.get('compounded_return_pct')} | {stats.get('avg_return_pct')} | "
                f"{stats.get('min_return_pct')}/{stats.get('max_return_pct')} | "
                f"{stats.get('max_drawdown_pct')} | {stats.get('avg_cost_drag_pct')} | "
                f"`{risk_tag_counts}` | `{fold_ids}` |"
            )
        return rows

    lines = [
        "# Market-State Rotation V6 Walk-Forward Validation",
        "",
        f"- Created at: `{report.get('created_at')}`",
        f"- Source report: `{report.get('source_report')}`",
        f"- Source report sha256: `{provenance.get('source_report_sha256', '')}`",
        f"- Candidate config hash: `{provenance.get('candidate_config_hash', '')}`",
        f"- Config override hash: `{provenance.get('config_overrides_hash', '')}`",
        f"- Selected result hash: `{provenance.get('selected_result_hash', '')}`",
        f"- Symbol: `{report.get('symbol')}`",
        f"- Execution interval: `{report.get('exec_interval')}`",
        f"- Train/test/step days: `{report.get('train_days')}/{report.get('test_days')}/{report.get('step_days')}`",
        f"- Source top-n: `{report.get('source_top_n')}`",
        f"- Candidate count: `{report.get('candidate_count')}`",
        f"- Fold offset/limit: `{report.get('fold_offset')}/{report.get('fold_limit')}`",
        f"- Config override count: `{len(config_overrides)}`",
        (
            "- Confirmation config: "
            f"`mode={config_overrides.get('after_selection_confirmation_mode')}, "
            f"ablation={config_overrides.get('after_selection_confirmation_ablation_mode')}, "
            f"targets={config_overrides.get('after_selection_confirm_overlays')}, "
            f"max_dd_delta={config_overrides.get('after_selection_confirm_max_drawdown_delta_pct')}, "
            f"max_cost_delta={config_overrides.get('after_selection_confirm_max_cost_delta_pct')}, "
            f"min_return_per_cost_delta={config_overrides.get('after_selection_confirm_min_return_per_cost_delta')}`"
        ),
        f"- Fold count: `{aggregate.get('fold_count')}`",
        f"- OOS compounded return: `{aggregate.get('compounded_oos_return_pct')}%`",
        f"- OOS average fold return: `{aggregate.get('avg_oos_return_pct')}%`",
        f"- OOS min/max fold return: `{aggregate.get('min_oos_return_pct')}% / {aggregate.get('max_oos_return_pct')}%`",
        f"- OOS max fold drawdown: `{aggregate.get('max_fold_drawdown_pct')}%`",
        f"- Positive folds: `{aggregate.get('positive_fold_count')}/{aggregate.get('fold_count')}`",
        f"- OOS avg/max cost drag: `{aggregate.get('avg_oos_cost_drag_pct')}% / {aggregate.get('max_oos_cost_drag_pct')}%`",
        f"- OOS avg carry cost fraction sum: `{aggregate.get('avg_modeled_carry_cost_fraction_sum')}`",
        (
            "- OOS trade-like events total/avg/min/max: "
            f"`{aggregate.get('total_trade_like_events')}/"
            f"{aggregate.get('avg_trade_like_events')}/"
            f"{aggregate.get('min_trade_like_events')}/"
            f"{aggregate.get('max_trade_like_events')}`"
        ),
        (
            "- OOS battle adds/share/folds: "
            f"`{aggregate.get('total_battle_adds')}/"
            f"{aggregate.get('battle_add_share')}/"
            f"{aggregate.get('battle_participation_fold_count')}`"
        ),
        (
            "- OOS add side counts/share: "
            f"`{json.dumps(aggregate.get('test_add_by_side_counts', {}), ensure_ascii=False)} / "
            f"{json.dumps(aggregate.get('test_add_by_side_share', {}), ensure_ascii=False)}`"
        ),
        (
            "- OOS add role counts: "
            f"`{json.dumps(aggregate.get('test_add_by_role_counts', {}), ensure_ascii=False)}`"
        ),
        (
            "- OOS add role share: "
            f"`{json.dumps(aggregate.get('test_add_by_role_share', {}), ensure_ascii=False)}`"
        ),
        (
            "- OOS add distribution diagnostics: "
            f"`{json.dumps(aggregate.get('test_add_distribution_diagnostics', {}), ensure_ascii=False)}`"
        ),
        (
            "- OOS modeled cost attribution: "
            f"`total={test_cost_attribution.get('total_modeled_trade_cost_pct', 0)}%, "
            f"by_role={json.dumps(test_cost_attribution.get('by_role_pct', {}), ensure_ascii=False)}, "
            f"by_reason={json.dumps(test_cost_attribution.get('by_reason_pct', {}), ensure_ascii=False)}`"
        ),
        (
            "- OOS drawdown recovery: "
            f"`recovered={drawdown_recovery_diagnostics.get('recovered_drawdown_count', 0)}, "
            f"high_dd={drawdown_recovery_diagnostics.get('high_drawdown_count', 0)}, "
            f"high_dd_recovered={drawdown_recovery_diagnostics.get('high_drawdown_recovered_count', 0)}, "
            f"high_dd_unrecovered={drawdown_recovery_diagnostics.get('high_drawdown_unrecovered_count', 0)}, "
            f"high_dd_slow={drawdown_recovery_diagnostics.get('high_drawdown_slow_recovery_count', 0)}, "
            f"avg_high_recovery_h={drawdown_recovery_diagnostics.get('avg_high_drawdown_recovery_hours')}, "
            f"max_high_recovery_h={drawdown_recovery_diagnostics.get('max_high_drawdown_recovery_hours')}`"
        ),
        f"- Unique selected models: `{aggregate.get('unique_selected_model_count')}`",
        f"- Selected profile counts: `{json.dumps(aggregate.get('selected_profile_counts', {}), ensure_ascii=False)}`",
        f"- Selected hold counts: `{json.dumps(aggregate.get('selected_hold_counts', {}), ensure_ascii=False)}`",
        f"- Selected max-unit counts: `{json.dumps(aggregate.get('selected_max_units_counts', {}), ensure_ascii=False)}`",
        (
            "- Selected reaction USD counts: "
            f"`{json.dumps(aggregate.get('selected_reaction_usd_counts', {}), ensure_ascii=False)}`"
        ),
        (
            "- Selected defensive cooldown counts: "
            f"`{json.dumps(aggregate.get('selected_defensive_cooldown_counts', {}), ensure_ascii=False)}`"
        ),
        (
            "- After-selection overlay counts: "
            f"`{json.dumps(aggregate.get('after_selection_overlay_counts', {}), ensure_ascii=False)}`"
        ),
        (
            "- After-selection overlay skipped counts: "
            f"`{json.dumps(aggregate.get('after_selection_overlay_skipped_counts', {}), ensure_ascii=False)}`"
        ),
        (
            "- After-selection overlay skip reasons: "
            f"`{json.dumps(aggregate.get('after_selection_overlay_skip_reason_counts', {}), ensure_ascii=False)}`"
        ),
        (
            "- After-selection overlay count distribution: "
            f"`{json.dumps(aggregate.get('after_selection_overlay_count_distribution', {}), ensure_ascii=False)}`"
        ),
        f"- Test health counts: `{json.dumps(aggregate.get('test_health_counts', {}), ensure_ascii=False)}`",
        f"- Test flag counts: `{json.dumps(aggregate.get('test_flag_counts', {}), ensure_ascii=False)}`",
        (
            "- Test borderline flag counts: "
            f"`{json.dumps(aggregate.get('test_borderline_flag_counts', {}), ensure_ascii=False)}`"
        ),
        f"- Test flag performance: `{json.dumps(aggregate.get('test_flag_performance', {}), ensure_ascii=False)}`",
        (
            "- After-selection confirmation: "
            f"`records={after_selection_confirmation.get('record_count', 0)}, "
            f"passed={after_selection_confirmation.get('passed_count', 0)}, "
            f"would_reject={after_selection_confirmation.get('would_reject_count', 0)}, "
            f"enforced={after_selection_confirmation.get('enforced_count', 0)}`"
        ),
        (
            "- Recent OOS overlay blocks: "
            f"`records={recent_oos_blocks.get('record_count', 0)}, "
            f"enforced={recent_oos_blocks.get('enforced_count', 0)}, "
            f"overlays={json.dumps(recent_oos_blocks.get('blocked_overlay_counts', {}), ensure_ascii=False)}`"
        ),
        (
            "- Top test event counts: "
            f"`{json.dumps(top_counter_items(aggregate.get('test_event_counts', {})), ensure_ascii=False)}`"
        ),
        (
            "- Weak fold diagnostics: "
            f"`low_return={dict(aggregate.get('weak_fold_diagnostics') or {}).get('low_return_count', 0)}, "
            f"high_dd={dict(aggregate.get('weak_fold_diagnostics') or {}).get('high_drawdown_count', 0)}, "
            f"high_cost={dict(aggregate.get('weak_fold_diagnostics') or {}).get('high_cost_count', 0)}, "
            f"role_concentration={dict(aggregate.get('weak_fold_diagnostics') or {}).get('role_concentration_count', 0)}, "
            f"base_dominance={dict(aggregate.get('weak_fold_diagnostics') or {}).get('base_dominance_count', 0)}, "
            f"no_scale={dict(aggregate.get('weak_fold_diagnostics') or {}).get('no_scale_in_capacity_count', 0)}, "
            f"single_unit={dict(aggregate.get('weak_fold_diagnostics') or {}).get('single_unit_full_entry_count', 0)}, "
            f"battle_capacity={dict(aggregate.get('weak_fold_diagnostics') or {}).get('battle_capacity_saturated_count', 0)}, "
            f"confirmation_warnings={dict(aggregate.get('weak_fold_diagnostics') or {}).get('confirmation_warning_count', 0)}`"
        ),
        (
            "- Top-train candidate audit: "
            f"`audited={top_candidate_audit.get('audited_fold_count', 0)}, "
            f"missed_best={top_candidate_audit.get('missed_best_count', 0)}, "
            f"avg_regret={top_candidate_audit.get('avg_return_regret_pct', 0)}%, "
            f"oracle={top_candidate_audit.get('oracle_best_compounded_return_pct', 0)}%`"
        ),
        (
            "- Top-train candidate overlay audit: "
            f"`overlays={len(top_candidate_overlay_audit)}, "
            f"records={sum(int(dict(stats or {}).get('candidate_count') or 0) for stats in top_candidate_overlay_audit.values())}`"
        ),
        (
            "- Improvement backlog: "
            f"`next={improvement_backlog.get('next_step', 'none')}, "
            f"selection_miss={improvement_backlog.get('clean_selection_miss_count', 0)}, "
            f"candidate_ceiling={improvement_backlog.get('low_return_candidate_ceiling_count', 0)}, "
            f"risk_compression={improvement_backlog.get('risk_compression_tradeoff_count', 0)}, "
            f"cost_compression={improvement_backlog.get('cost_compression_tradeoff_count', 0)}`"
        ),
        (
            "- Regime drift diagnostics: "
            f"`avg_drift={regime_drift_diagnostics.get('avg_regime_share_drift', 0)}, "
            f"max_drift={regime_drift_diagnostics.get('max_regime_share_drift', 0)}, "
            f"high_drift={regime_drift_diagnostics.get('high_drift_count', 0)}, "
            f"high_dependency={regime_drift_diagnostics.get('high_dependency_count', 0)}`"
        ),
        (
            "- Source replay drift: "
            f"`compared={source_replay_diagnostics.get('compared_fold_count', 0)}, "
            f"model_mismatch={source_replay_diagnostics.get('selected_model_mismatch_count', 0)}, "
            f"model_unresolved={source_replay_diagnostics.get('selected_model_unresolved_mismatch_count', 0)}, "
            f"model_immaterial={source_replay_diagnostics.get('selected_model_immaterial_mismatch_count', 0)}, "
            f"model_accepted={source_replay_diagnostics.get('selected_model_accepted_risk_tradeoff_count', 0)}, "
            f"overlay_mismatch={source_replay_diagnostics.get('overlay_mismatch_count', 0)}, "
            f"material_metric_mismatch={source_replay_diagnostics.get('material_metric_mismatch_count', 0)}, "
            f"accepted_risk_tradeoff={source_replay_diagnostics.get('accepted_risk_tradeoff_count', 0)}, "
            f"unresolved_material={source_replay_diagnostics.get('unresolved_material_metric_mismatch_count', 0)}, "
            f"max_abs_return_delta={source_replay_diagnostics.get('max_abs_return_delta_pct', 0)}%, "
            f"max_abs_dd_delta={source_replay_diagnostics.get('max_abs_drawdown_delta_pct', 0)}%`"
        ),
        (
            "- Source replay guard: "
            f"`status={source_replay_lineage_guard.get('status', 'not_applicable')}, "
            f"strict={source_replay_lineage_guard.get('fail_on_unresolved_material', False)}, "
            f"unresolved_material="
            f"{source_replay_lineage_guard.get('unresolved_material_metric_mismatch_count', 0)}, "
            f"model_unresolved="
            f"{source_replay_lineage_guard.get('selected_model_unresolved_mismatch_count', 0)}, "
            f"folds={source_replay_lineage_guard.get('unresolved_material_folds', [])}`"
        ),
        "",
        "## Source Replay Drift",
        "",
    ]
    if source_replay_diagnostics:
        lines.extend(
            [
                (
                    "- Guard: "
                    f"`status={source_replay_lineage_guard.get('status', 'not_applicable')}, "
                    f"strict={source_replay_lineage_guard.get('fail_on_unresolved_material', False)}, "
                    f"message={source_replay_lineage_guard.get('message', '')}`"
                ),
                (
                    "- Summary: "
                    f"`avg_return_delta={source_replay_diagnostics.get('avg_return_delta_pct')}%, "
                    f"avg_dd_delta={source_replay_diagnostics.get('avg_drawdown_delta_pct')}%, "
                    f"avg_cost_delta={source_replay_diagnostics.get('avg_cost_delta_pct')}%, "
                    f"total_cost_delta={source_replay_diagnostics.get('total_cost_delta_pct')}%, "
                    f"event_delta={source_replay_diagnostics.get('total_trade_like_events_delta')}`"
                ),
                (
                    "- Mismatch reasons: "
                    f"`{json.dumps(source_replay_diagnostics.get('mismatch_reason_counts', {}), ensure_ascii=False)}`"
                ),
                (
                    "- Drift quality: "
                    f"`{json.dumps(source_replay_diagnostics.get('drift_quality_counts', {}), ensure_ascii=False)}`"
                ),
                (
                    "- Lineage status: "
                    f"`{json.dumps(source_replay_diagnostics.get('lineage_status_counts', {}), ensure_ascii=False)}`"
                ),
                (
                    "- Model mismatch status: "
                    f"`{json.dumps(source_replay_diagnostics.get('model_mismatch_status_counts', {}), ensure_ascii=False)}`"
                ),
                "",
                "### Largest Return Drift Folds",
                "",
            ]
        )
        lines.extend(
            source_replay_drift_rows(
                list(source_replay_diagnostics.get("largest_return_drift_folds") or [])
            )
        )
        lines.extend(["", "### Largest Drawdown Drift Folds", ""])
        lines.extend(
            source_replay_drift_rows(
                list(source_replay_diagnostics.get("largest_drawdown_drift_folds") or [])
            )
        )
        if source_replay_diagnostics.get("accepted_risk_tradeoff_folds"):
            lines.extend(["", "### Accepted Risk Tradeoff Folds", ""])
            lines.extend(
                source_replay_drift_rows(
                    list(source_replay_diagnostics.get("accepted_risk_tradeoff_folds") or [])
                )
            )
        if source_replay_diagnostics.get("unresolved_model_mismatch_folds"):
            lines.extend(["", "### Unresolved Model Drift Folds", ""])
            lines.extend(
                source_replay_drift_rows(
                    list(source_replay_diagnostics.get("unresolved_model_mismatch_folds") or [])
                )
            )
        if source_replay_diagnostics.get("immaterial_model_mismatch_folds"):
            lines.extend(["", "### Immaterial Model Mismatch Folds", ""])
            lines.extend(
                source_replay_drift_rows(
                    list(source_replay_diagnostics.get("immaterial_model_mismatch_folds") or [])
                )
            )
        if source_replay_diagnostics.get("unresolved_material_mismatch_folds"):
            lines.extend(["", "### Unresolved Material Drift Folds", ""])
            lines.extend(
                source_replay_drift_rows(
                    list(source_replay_diagnostics.get("unresolved_material_mismatch_folds") or [])
                )
            )
        lines.append("")
    else:
        lines.extend(["No source replay drift diagnostics.", ""])
    lines.extend(
        [
            "## After-Selection Confirmation",
            "",
        ]
    )
    if after_selection_confirmation:
        lines.extend(
            [
                f"- Modes: `{json.dumps(after_selection_confirmation.get('mode_counts', {}), ensure_ascii=False)}`",
                (
                    "- Failed checks: "
                    f"`{json.dumps(after_selection_confirmation.get('failed_check_counts', {}), ensure_ascii=False)}`"
                ),
                "",
                "| target | folds | passed | would reject | enforced | cost reducing | avg return delta % | avg cost delta % | avg drawdown delta % | failed checks |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for target, stats in dict(
            after_selection_confirmation.get("target_diagnostics") or {}
        ).items():
            stats = dict(stats or {})
            lines.append(
                f"| `{target}` | {stats.get('fold_count')} | {stats.get('passed_count')} | "
                f"{stats.get('would_reject_count')} | {stats.get('enforced_count')} | "
                f"{stats.get('cost_reducing_count')} | {stats.get('avg_return_delta_pct')} | "
                f"{stats.get('avg_cost_delta_pct')} | {stats.get('avg_drawdown_delta_pct')} | "
                f"`{json.dumps(stats.get('failed_check_counts', {}), ensure_ascii=False)}` |"
            )
        lines.extend(
            [
                "",
                "| status | folds | positive | compounded return % | avg return % | max DD % | avg cost drag % |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for status, stats in dict(after_selection_confirmation.get("oos_by_status") or {}).items():
            stats = dict(stats or {})
            lines.append(
                f"| `{status}` | {stats.get('fold_count')} | {stats.get('positive_fold_count')} | "
                f"{stats.get('compounded_return_pct')} | {stats.get('avg_return_pct')} | "
                f"{stats.get('max_drawdown_pct')} | {stats.get('avg_cost_drag_pct')} |"
            )
        lines.append("")
    else:
        lines.extend(["No after-selection confirmation records.", ""])
    lines.extend(["## Recent OOS Overlay Blocks", ""])
    if recent_oos_blocks:
        lines.extend(
            [
                f"- Modes: `{json.dumps(recent_oos_blocks.get('mode_counts', {}), ensure_ascii=False)}`",
                (
                    "- Blocked overlays: "
                    f"`{json.dumps(recent_oos_blocks.get('blocked_overlay_counts', {}), ensure_ascii=False)}`"
                ),
                (
                    "- Failed checks: "
                    f"`{json.dumps(recent_oos_blocks.get('failed_check_counts', {}), ensure_ascii=False)}`"
                ),
                "",
            ]
        )
    else:
        lines.extend(["No recent OOS overlay block records.", ""])
    lines.extend(["## After-Selection Overlay OOS Performance", ""])
    if overlay_oos_performance:
        lines.extend(
            [
                "Co-occurrence diagnostics: each row reports folds where the overlay was present, not isolated causal attribution.",
                "",
                "| overlay | folds | positive | compounded return % | avg return % | min/max return % | max DD % | avg cost % | risk tags | fold ids |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
            ]
        )
        overlay_rows = sorted(
            ((str(overlay), dict(stats or {})) for overlay, stats in overlay_oos_performance.items()),
            key=lambda item: (-int(item[1].get("fold_count") or 0), item[0]),
        )
        for overlay, stats in overlay_rows:
            risk_tag_counts = json.dumps(stats.get("risk_tag_counts", {}), ensure_ascii=False)
            fold_ids = ",".join(str(item) for item in stats.get("folds") or []) or "none"
            lines.append(
                f"| `{overlay}` | {stats.get('fold_count')} | {stats.get('positive_fold_count')} | "
                f"{stats.get('compounded_return_pct')} | {stats.get('avg_return_pct')} | "
                f"{stats.get('min_return_pct')}/{stats.get('max_return_pct')} | "
                f"{stats.get('max_drawdown_pct')} | {stats.get('avg_cost_drag_pct')} | "
                f"`{risk_tag_counts}` | `{fold_ids}` |"
            )
        lines.append("")
    else:
        lines.extend(["No after-selection overlay OOS records.", ""])
    lines.extend(["## Selected Shape Performance", ""])
    if selected_reaction_usd_performance or selected_risk_shape_performance:
        lines.extend(
            [
                "These are selected-model co-occurrence diagnostics. They show which selected parameter families produced the OOS return, cost, drawdown, and weak-fold tags.",
                "",
                "### Reaction USD",
                "",
            ]
        )
        if selected_reaction_usd_performance:
            lines.extend(
                selected_shape_rows(
                    selected_reaction_usd_performance,
                    key_label="reaction_usd",
                )
            )
        else:
            lines.append("No selected reaction USD records.")
        lines.extend(["", "### Risk Shape", ""])
        if selected_risk_shape_performance:
            lines.extend(
                selected_shape_rows(
                    selected_risk_shape_performance,
                    key_label="shape",
                )
            )
        else:
            lines.append("No selected risk-shape records.")
        lines.append("")
    else:
        lines.extend(["No selected shape performance records.", ""])
    lines.extend(["## Top-Train Candidate Audit", ""])
    if top_candidate_audit:
        lines.extend(
            [
                (
                    "- Summary: "
                    f"`audited={top_candidate_audit.get('audited_fold_count')}, "
                    f"avg_candidates={top_candidate_audit.get('avg_candidate_count')}, "
                    f"selected_best={top_candidate_audit.get('selected_best_count')}, "
                    f"missed_best={top_candidate_audit.get('missed_best_count')}, "
                    f"missed_rate={top_candidate_audit.get('missed_best_rate')}, "
                    f"selected_best_with_flags={top_candidate_audit.get('selected_best_with_test_flags_count')}, "
                    f"missed_best_flag_improvements={top_candidate_audit.get('missed_best_flag_improvement_count')}, "
                    f"missed_best_higher_cost={top_candidate_audit.get('missed_best_higher_cost_count')}, "
                    f"missed_best_higher_dd={top_candidate_audit.get('missed_best_higher_drawdown_count')}, "
                    f"clean_missed_improvements={top_candidate_audit.get('missed_best_clean_improvement_count')}, "
                    f"avg_regret={top_candidate_audit.get('avg_return_regret_pct')}%, "
                    f"max_regret={top_candidate_audit.get('max_return_regret_pct')}%`"
                ),
                (
                    "- Compounded selected vs oracle-best: "
                    f"`{top_candidate_audit.get('selected_compounded_return_pct')}% / "
                    f"{top_candidate_audit.get('oracle_best_compounded_return_pct')}% "
                    f"(diff={top_candidate_audit.get('oracle_compounded_improvement_pct')}%)`"
                ),
                (
                    "- Best-rank counts: "
                    f"`{json.dumps(top_candidate_audit.get('best_rank_counts', {}), ensure_ascii=False)}`"
                ),
                "",
                "| fold | test | selected return % | best return % | regret % | best rank | selected/best cost % | selected/best DD % | selected/best events | best overlays | flag delta |",
                "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
            ]
        )
        for item in list(top_candidate_audit.get("highest_regret_folds") or []):
            selected = dict(item.get("selected") or {})
            best = dict(item.get("best") or {})
            flag_delta = dict(item.get("flag_delta_vs_best") or {})
            flag_delta_label = (
                f"selected_only={','.join(flag_delta.get('selected_only') or []) or 'none'}; "
                f"best_only={','.join(flag_delta.get('best_only') or []) or 'none'}"
            )
            lines.append(
                f"| {item.get('fold')} | {item.get('test_start')} to {item.get('test_end')} | "
                f"{selected.get('test_return_pct')} | {best.get('test_return_pct')} | "
                f"{item.get('return_regret_pct')} | {best.get('rank')} | "
                f"{selected.get('test_cost_drag_pct')}/{best.get('test_cost_drag_pct')} | "
                f"{selected.get('test_max_drawdown_pct')}/{best.get('test_max_drawdown_pct')} | "
                f"{selected.get('test_trade_like_events')}/{best.get('test_trade_like_events')} | "
                f"`{','.join(best.get('after_selection_overlays_applied') or []) or 'none'}` | "
                f"`{flag_delta_label}` |"
            )
        lines.append("")
    else:
        lines.extend(["No top-train candidate audit records.", ""])
    lines.extend(["## Improvement Backlog Diagnostics", ""])
    if improvement_backlog:
        lines.extend(
            [
                (
                    "- Summary: "
                    f"`audited={improvement_backlog.get('audited_fold_count')}, "
                    f"next={improvement_backlog.get('next_step')}, "
                    f"clean_selection_miss={improvement_backlog.get('clean_selection_miss_count')}, "
                    f"risky_or_marginal_oracle={improvement_backlog.get('risky_or_marginal_oracle_miss_count')}, "
                    f"candidate_ceiling={improvement_backlog.get('low_return_candidate_ceiling_count')}, "
                    f"risk_compression={improvement_backlog.get('risk_compression_tradeoff_count')}, "
                    f"cost_compression={improvement_backlog.get('cost_compression_tradeoff_count')}`"
                ),
                (
                    "- Thresholds: "
                    f"`{json.dumps(improvement_backlog.get('thresholds', {}), ensure_ascii=False)}`"
                ),
                "",
            ]
        )

        def backlog_rows(items: list[dict[str, Any]], *, include_tradeoff: bool = False) -> list[str]:
            rows = [
                "| fold | test | selected return % | selected DD % | selected cost % | best/upside % | best rank | diagnosis | tradeoff |",
                "|---:|---|---:|---:|---:|---:|---:|---|---|",
            ]
            for item in items:
                best = dict(item.get("best_candidate") or {})
                tradeoff = ""
                if include_tradeoff:
                    candidate = dict(item.get("tradeoff_candidate") or {})
                    tradeoff = (
                        f"rank={candidate.get('rank')}, "
                        f"giveback={item.get('return_giveback_pct')}%, "
                        f"dd_reduction={item.get('drawdown_reduction_pct')}%, "
                        f"cost_reduction={item.get('cost_reduction_pct')}%"
                    )
                rows.append(
                    f"| {item.get('fold')} | {item.get('test_start')} to {item.get('test_end')} | "
                    f"{item.get('selected_return_pct')} | {item.get('selected_max_drawdown_pct')} | "
                    f"{item.get('selected_cost_drag_pct')} | "
                    f"{best.get('test_return_pct')}/{item.get('best_return_upside_pct')} | "
                    f"{best.get('rank')} | `{item.get('diagnosis')}` | `{tradeoff or 'none'}` |"
                )
            return rows

        ceiling_folds = list(improvement_backlog.get("low_return_candidate_ceiling_folds") or [])
        if ceiling_folds:
            lines.extend(["### Low-Return Candidate Ceiling Folds", ""])
            lines.extend(backlog_rows(ceiling_folds))
            lines.append("")
        selection_folds = list(improvement_backlog.get("clean_selection_miss_folds") or [])
        if selection_folds:
            lines.extend(["### Clean Selection Miss Folds", ""])
            lines.extend(backlog_rows(selection_folds))
            lines.append("")
        marginal_folds = list(improvement_backlog.get("risky_or_marginal_oracle_miss_folds") or [])
        if marginal_folds:
            lines.extend(["### Risky Or Marginal Oracle Folds", ""])
            lines.extend(backlog_rows(marginal_folds))
            lines.append("")
        risk_folds = list(improvement_backlog.get("risk_compression_tradeoff_folds") or [])
        if risk_folds:
            lines.extend(["### Risk Compression Tradeoff Folds", ""])
            lines.extend(backlog_rows(risk_folds, include_tradeoff=True))
            lines.append("")
        cost_folds = list(improvement_backlog.get("cost_compression_tradeoff_folds") or [])
        if cost_folds:
            lines.extend(["### Cost Compression Tradeoff Folds", ""])
            lines.extend(backlog_rows(cost_folds, include_tradeoff=True))
            lines.append("")
    else:
        lines.extend(["No improvement backlog diagnostics.", ""])
    lines.extend(["## Top-Train Candidate Overlay Audit", ""])
    if top_candidate_overlay_audit:
        lines.extend(
            [
                "Candidate co-occurrence diagnostics across the audited top-train set. These rows are not live-selectable oracle results, but they show which overlay families deserve promotion or stronger gates.",
                "",
                "| overlay | candidates | folds | selected | oos best | positive | avg train score | avg train return % | avg test return % | min/max test return % | max DD % | avg cost % | flags | fold ids |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
            ]
        )
        overlay_rows = sorted(
            ((str(overlay), dict(stats or {})) for overlay, stats in top_candidate_overlay_audit.items()),
            key=lambda item: (-float(item[1].get("avg_test_return_pct") or 0.0), item[0]),
        )
        for overlay, stats in overlay_rows:
            flags = json.dumps(stats.get("test_flag_counts", {}), ensure_ascii=False)
            fold_ids = ",".join(str(item) for item in stats.get("folds") or []) or "none"
            lines.append(
                f"| `{overlay}` | {stats.get('candidate_count')} | {stats.get('fold_count')} | "
                f"{stats.get('selected_count')} | {stats.get('best_count')} | "
                f"{stats.get('positive_candidate_count')} | {stats.get('avg_train_score')} | "
                f"{stats.get('avg_train_return_pct')} | {stats.get('avg_test_return_pct')} | "
                f"{stats.get('min_test_return_pct')}/{stats.get('max_test_return_pct')} | "
                f"{stats.get('max_test_drawdown_pct')} | {stats.get('avg_test_cost_drag_pct')} | "
                f"`{flags}` | `{fold_ids}` |"
            )
        lines.append("")
    else:
        lines.extend(["No top-train candidate overlay audit records.", ""])
    lines.extend(["## Regime Drift Diagnostics", ""])
    if regime_drift_diagnostics:
        lines.extend(
            [
                (
                    "- Thresholds: "
                    f"`high_drift>={regime_drift_diagnostics.get('high_drift_threshold')}, "
                    f"high_dependency>={regime_drift_diagnostics.get('high_dependency_threshold')}`"
                ),
                (
                    "- Counts: "
                    f"`high_drift={regime_drift_diagnostics.get('high_drift_count')}, "
                    f"high_dependency={regime_drift_diagnostics.get('high_dependency_count')}, "
                    f"avg_drift={regime_drift_diagnostics.get('avg_regime_share_drift')}, "
                    f"max_drift={regime_drift_diagnostics.get('max_regime_share_drift')}`"
                ),
                "",
                "### Highest Drift Folds",
                "",
            ]
        )
        lines.extend(regime_drift_rows(list(regime_drift_diagnostics.get("highest_drift_folds") or [])))
        lines.extend(["", "### Highest Train Regime Dependency Folds", ""])
        lines.extend(
            regime_drift_rows(list(regime_drift_diagnostics.get("highest_dependency_folds") or []))
        )
        lines.extend(["", "### Lowest Return Regime Drift Folds", ""])
        lines.extend(regime_drift_rows(list(regime_drift_diagnostics.get("lowest_return_folds") or [])))
        lines.append("")
    else:
        lines.extend(["No regime drift diagnostics.", ""])
    lines.extend(["## OOS Cost Attribution", ""])
    if test_cost_attribution and test_cost_attribution.get("total_modeled_trade_cost_pct"):
        lines.extend(
            [
                (
                    "- Total modeled trade cost: "
                    f"`{test_cost_attribution.get('total_modeled_trade_cost_pct')}%`"
                ),
                "",
                "### By Action",
                "",
            ]
        )
        lines.extend(cost_attribution_rows("action", dict(test_cost_attribution.get("by_action_pct") or {})))
        lines.extend(["", "### By Side", ""])
        lines.extend(cost_attribution_rows("side", dict(test_cost_attribution.get("by_side_pct") or {})))
        lines.extend(["", "### By Role", ""])
        lines.extend(cost_attribution_rows("role", dict(test_cost_attribution.get("by_role_pct") or {})))
        lines.extend(["", "### By Reason", ""])
        lines.extend(cost_attribution_rows("reason", dict(test_cost_attribution.get("by_reason_pct") or {})))
        lines.extend(["", "### By Action/Reason", ""])
        lines.extend(
            cost_attribution_rows(
                "action/reason",
                dict(test_cost_attribution.get("by_action_reason_pct") or {}),
            )
        )
        lines.append("")
    else:
        lines.extend(["No modeled cost attribution records.", ""])
    lines.extend(["## Drawdown Recovery Diagnostics", ""])
    if drawdown_recovery_diagnostics:
        lines.extend(
            [
                (
                    "- Summary: "
                    f"`recovered={drawdown_recovery_diagnostics.get('recovered_drawdown_count')}, "
                    f"high_dd={drawdown_recovery_diagnostics.get('high_drawdown_count')}, "
                    f"high_dd_recovered={drawdown_recovery_diagnostics.get('high_drawdown_recovered_count')}, "
                    f"high_dd_unrecovered={drawdown_recovery_diagnostics.get('high_drawdown_unrecovered_count')}, "
                    f"high_dd_slow={drawdown_recovery_diagnostics.get('high_drawdown_slow_recovery_count')}, "
                    f"avg_recovery_h={drawdown_recovery_diagnostics.get('avg_drawdown_recovery_hours')}, "
                    f"avg_high_recovery_h={drawdown_recovery_diagnostics.get('avg_high_drawdown_recovery_hours')}, "
                    f"max_high_recovery_h={drawdown_recovery_diagnostics.get('max_high_drawdown_recovery_hours')}`"
                ),
                "",
            ]
        )
        high_drawdown_folds = list(drawdown_recovery_diagnostics.get("high_drawdown_folds") or [])
        if high_drawdown_folds:
            lines.extend(drawdown_recovery_rows(high_drawdown_folds))
            lines.append("")
        else:
            lines.extend(["No high-drawdown fold records.", ""])
    else:
        lines.extend(["No drawdown recovery records.", ""])
    weak_fold_diagnostics = dict(aggregate.get("weak_fold_diagnostics") or {})
    lines.extend(["## Weak Fold Diagnostics", ""])
    if weak_fold_diagnostics:
        lines.extend(
            [
                (
                    "- Thresholds: "
                    f"`low_return<{weak_fold_diagnostics.get('low_return_threshold_pct')}%, "
                    f"high_dd>={weak_fold_diagnostics.get('high_drawdown_threshold_pct')}%, "
                    f"high_cost>={weak_fold_diagnostics.get('high_cost_threshold_pct')}%, "
                    f"high_overlay_count>={weak_fold_diagnostics.get('high_overlay_count_threshold')}`"
                ),
                (
                    "- Counts: "
                    f"`non_positive={weak_fold_diagnostics.get('non_positive_return_count')}, "
                    f"low_return={weak_fold_diagnostics.get('low_return_count')}, "
                    f"high_dd={weak_fold_diagnostics.get('high_drawdown_count')}, "
                    f"high_cost={weak_fold_diagnostics.get('high_cost_count')}, "
                    f"high_overlay={weak_fold_diagnostics.get('high_overlay_count')}, "
                    f"role_concentration={weak_fold_diagnostics.get('role_concentration_count')}, "
                    f"base_dominance={weak_fold_diagnostics.get('base_dominance_count')}, "
                    f"no_scale={weak_fold_diagnostics.get('no_scale_in_capacity_count')}, "
                    f"single_unit={weak_fold_diagnostics.get('single_unit_full_entry_count')}, "
                    f"battle_capacity={weak_fold_diagnostics.get('battle_capacity_saturated_count')}, "
                    f"low_activity={weak_fold_diagnostics.get('low_activity_count')}, "
                    f"soft_circuit_dominated={weak_fold_diagnostics.get('soft_circuit_dominated_count')}, "
                    f"confirmation_warnings={weak_fold_diagnostics.get('confirmation_warning_count')}`"
                ),
                (
                    "- Top no-trade blockers: "
                    f"`{json.dumps(weak_fold_diagnostics.get('top_no_trade_reason_counts', {}), ensure_ascii=False)}`"
                ),
                (
                    "- Risk tags: "
                    f"`{json.dumps(weak_fold_diagnostics.get('risk_tag_counts', {}), ensure_ascii=False)}`"
                ),
                (
                    "- Capacity statuses: "
                    f"`{json.dumps(weak_fold_diagnostics.get('capacity_status_counts', {}), ensure_ascii=False)}`"
                ),
                "",
                "### Lowest Return Folds",
                "",
            ]
        )
        lines.extend(risk_table_rows(list(weak_fold_diagnostics.get("lowest_return_folds") or [])))
        lines.extend(["", "### Highest Drawdown Folds", ""])
        lines.extend(risk_table_rows(list(weak_fold_diagnostics.get("highest_drawdown_folds") or [])))
        lines.extend(["", "### Highest Cost Folds", ""])
        lines.extend(risk_table_rows(list(weak_fold_diagnostics.get("highest_cost_folds") or [])))
        if weak_fold_diagnostics.get("lowest_activity_folds"):
            lines.extend(["", "### Lowest Activity Folds", ""])
            lines.extend(root_cause_rows(list(weak_fold_diagnostics.get("lowest_activity_folds") or [])))
        if weak_fold_diagnostics.get("soft_circuit_dominated_folds"):
            lines.extend(["", "### Soft Circuit Dominated Folds", ""])
            lines.extend(
                root_cause_rows(list(weak_fold_diagnostics.get("soft_circuit_dominated_folds") or []))
            )
        if weak_fold_diagnostics.get("role_concentration_folds"):
            lines.extend(["", "### Role Concentration Folds", ""])
            lines.extend(root_cause_rows(list(weak_fold_diagnostics.get("role_concentration_folds") or [])))
        if weak_fold_diagnostics.get("base_dominance_folds"):
            lines.extend(["", "### Base Dominance Folds", ""])
            lines.extend(root_cause_rows(list(weak_fold_diagnostics.get("base_dominance_folds") or [])))
        if weak_fold_diagnostics.get("confirmation_warning_folds"):
            lines.extend(["", "### Confirmation Warning Folds", ""])
            lines.extend(
                risk_table_rows(list(weak_fold_diagnostics.get("confirmation_warning_folds") or []))
            )
        lines.append("")
    else:
        lines.extend(["No weak fold diagnostics.", ""])
    lines.extend(
        [
        "## OOS Regime Performance",
        "",
        "| regime | folds | compounded return % | bars | exposed bars | max DD % | avg abs exposure | adds | removes |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for regime, stats in dict(aggregate.get("test_regime_performance") or {}).items():
        stats = dict(stats or {})
        lines.append(
            f"| `{regime}` | {stats.get('fold_count')} | {stats.get('compounded_return_pct')} | "
            f"{stats.get('bars')} | {stats.get('exposed_bars')} | {stats.get('max_drawdown_pct')} | "
            f"{stats.get('avg_abs_account_exposure')} | {stats.get('add_events')} | {stats.get('remove_events')} |"
        )
    lines.extend(
        [
        "",
        "## Selection Policy",
        "",
        "The adaptive profile selects from the current top candidates using the previous 365 days, then trades the next 90 days unseen. This is the preferred deployment validation view because it avoids choosing one static model from the same period being evaluated.",
        "",
        "## Folds",
        "",
        "| fold | train | test | selected train return % | selected test return % | test MDD % | overlays | confirmation | flags | model summary |",
        "|---:|---|---|---:|---:|---:|---|---|---|---|",
        ]
    )
    for fold in report.get("folds") or []:
        train = dict(fold.get("selected_train_result") or {})
        test = dict(fold.get("test_result") or {})
        diag = dict(test.get("event_diagnostics") or {})
        train_start = fold.get("train_start_at") or fold.get("train_start")
        train_end = fold.get("train_end_at") or fold.get("train_end")
        test_start = fold.get("test_start_at") or fold.get("test_start")
        test_end = fold.get("test_end_at") or fold.get("test_end")
        overlays = ",".join(str(item) for item in fold.get("after_selection_overlays_applied") or []) or "none"
        lines.append(
            f"| {fold.get('fold')} | {train_start} to {train_end} | "
            f"{test_start} to {test_end} | "
            f"{train.get('total_return_pct')} | {test.get('total_return_pct')} | "
            f"{test.get('max_drawdown_pct')} | `{overlays}` | "
            f"`{confirmation_summary(dict(fold))}` | "
            f"{', '.join(diag.get('flags') or []) or 'none'} | "
            f"`{fold_model_summary(dict(fold))}` |"
        )
    lines.append("")
    atomic_write_text(path, "\n".join(lines))


def main() -> None:
    args = _parse_args()
    source_path = Path(args.source_report)
    source_report = json.loads(source_path.read_text())
    source_args = dict(source_report.get("args") or {})
    source_config_overrides = dict(source_report.get("config_overrides") or {})
    inherited_source_replay_fields = _inherit_source_replay_selection_policy(
        args,
        source_config_overrides,
    )
    forced_source_replay_selection_fields = _apply_force_in_selection_flags(args)
    inherited_source_replay_window_fields = _inherit_source_replay_window_policy(
        args,
        source_report,
    )
    stabilized_source_replay_ratio_gate_fields = _stabilize_source_replay_ratio_gates(
        args,
        inherited_source_replay_fields,
        source_report=source_report,
    )
    inherited_source_replay_model_encoded_fields = _inherit_source_replay_model_encoded_policy(
        args,
        source_report,
    )
    symbol = args.symbol or str(source_args.get("symbol") or "BTCUSDT")
    exec_interval = args.exec_interval or str(source_args.get("exec_interval") or "5m")
    scenario_intervals = _csv(args.scenario_intervals or str(source_args.get("scenario_intervals") or "1h,4h"))
    if exec_interval not in _INTERVAL_MS:
        raise SystemExit(f"unsupported exec interval: {exec_interval}")
    for interval in scenario_intervals:
        if interval not in _INTERVAL_MS:
            raise SystemExit(f"unsupported scenario interval: {interval}")

    source_configs = _configs_from_source(source_report, top_n=max(1, int(args.top_n)))
    include_equity_circuit_in_selection = not bool(args.equity_circuit_breaker_after_selection)
    include_equity_soft_circuit_in_selection = not bool(args.equity_soft_circuit_after_selection)
    include_full_exit_in_selection = not bool(args.one_way_trim_full_exit_after_selection)
    include_trend_idle_in_selection = not bool(args.trend_idle_after_selection)
    include_near_miss_in_selection = not bool(args.near_miss_after_selection)
    include_base_reduce_in_selection = not bool(args.base_entry_reduce_after_selection)
    include_context_quarantine_in_selection = not bool(args.one_way_trim_context_after_selection)
    include_loss_fuse_in_selection = not bool(args.one_way_loss_fuse_after_selection)
    include_fragile_regime_entry_in_selection = not bool(args.fragile_regime_entry_after_selection)
    include_fragile_regime_inventory_trim_in_selection = not bool(
        args.fragile_regime_inventory_trim_after_selection
    )

    def add_candidate_family(
        *,
        include_defensive_trim_cooldown: bool,
        base_source_configs: list[MarketStateConfig],
        target_configs: list[MarketStateConfig],
    ) -> None:
        equity_choices = [include_equity_circuit_in_selection]
        if bool(args.include_no_equity_circuit_candidates) and include_equity_circuit_in_selection:
            equity_choices.insert(0, False)
        impulse_choices = [True]
        if bool(args.include_no_impulse_candidates):
            impulse_choices.insert(0, False)
        btc_rotation_choices = [True]
        if bool(args.include_no_btc_rotation_candidates):
            btc_rotation_choices.insert(0, False)
        base_reduce_choices = [include_base_reduce_in_selection]
        base_reduce_requested = (
            args.base_entry_max_extension_atr is not None
            or bool(args.base_entry_max_extension_side)
            or args.base_entry_reduce_extension_atr is not None
            or args.base_entry_reduce_size_mult is not None
            or args.base_entry_reduce_promote_reaction is not None
            or args.base_entry_reduce_max_trend_strength is not None
            or args.base_entry_reduce_min_trend_strength is not None
            or bool(args.base_entry_reduce_side)
        )
        if (
            bool(args.include_no_base_reduce_candidates)
            and include_base_reduce_in_selection
            and base_reduce_requested
        ):
            base_reduce_choices.insert(0, False)
        loss_fuse_choices = [include_loss_fuse_in_selection]
        loss_fuse_requested = (
            args.one_way_loss_fuse_min_adverse_reaction is not None
            or args.one_way_loss_fuse_cooldown_bars is not None
            or args.one_way_loss_fuse_size_mult is not None
        )
        if (
            bool(args.include_no_one_way_loss_fuse_candidates)
            and include_loss_fuse_in_selection
            and loss_fuse_requested
        ):
            loss_fuse_choices.insert(0, False)
        near_miss_choices = [include_near_miss_in_selection]
        near_miss_requested = (
            args.near_miss_probe_units is not None
            or args.near_miss_probe_min_score is not None
            or args.near_miss_probe_min_score_edge is not None
            or args.near_miss_probe_min_reason_stack is not None
            or args.near_miss_probe_cooldown_bars is not None
            or args.near_miss_probe_max_extension_atr is not None
            or args.near_miss_probe_failure_guard_count is not None
            or args.near_miss_probe_failure_guard_window_bars is not None
            or args.near_miss_probe_failure_cooldown_bars is not None
            or args.near_miss_probe_allowed_soft_reasons is not None
            or args.near_miss_probe_allowed_alignments is not None
            or args.near_miss_probe_allowed_execution_contexts is not None
            or args.near_miss_probe_allowed_regimes is not None
        )
        if bool(args.include_no_near_miss_probe_candidates) and include_near_miss_in_selection and near_miss_requested:
            near_miss_choices.insert(0, False)
        for include_equity_circuit in equity_choices:
            for include_btc_rotation in btc_rotation_choices:
                for include_impulse in impulse_choices:
                    for include_base_reduce in base_reduce_choices:
                        for include_loss_fuse in loss_fuse_choices:
                            for include_near_miss in near_miss_choices:
                                target_configs.extend(
                                    _apply_config_overrides(
                                        config,
                                        args,
                                        include_impulse=include_impulse,
                                        include_trend_idle=include_trend_idle_in_selection,
                                        include_equity_circuit=include_equity_circuit,
                                        include_equity_soft_circuit=include_equity_soft_circuit_in_selection,
                                        include_full_exit=include_full_exit_in_selection,
                                        include_defensive_trim_cooldown=include_defensive_trim_cooldown,
                                        include_near_miss=include_near_miss,
                                        include_base_reduce=include_base_reduce,
                                        include_context_quarantine=include_context_quarantine_in_selection,
                                        include_loss_fuse=include_loss_fuse,
                                        include_btc_rotation=include_btc_rotation,
                                        include_fragile_regime_entry=include_fragile_regime_entry_in_selection,
                                        include_fragile_regime_inventory_trim=(
                                            include_fragile_regime_inventory_trim_in_selection
                                        ),
                                    )
                                    for config in base_source_configs
                                )

    def build_candidate_configs(base_source_configs: list[MarketStateConfig]) -> list[MarketStateConfig]:
        built_configs: list[MarketStateConfig] = []
        if (
            bool(args.include_no_defensive_trim_cooldown_candidates)
            and args.defensive_trim_cooldown_bars is not None
        ):
            add_candidate_family(
                include_defensive_trim_cooldown=False,
                base_source_configs=base_source_configs,
                target_configs=built_configs,
            )
        add_candidate_family(
            include_defensive_trim_cooldown=True,
            base_source_configs=base_source_configs,
            target_configs=built_configs,
        )
        deduped_configs: list[MarketStateConfig] = []
        seen_config_keys: set[str] = set()
        for config in built_configs:
            key = _material_config_key(config)
            if key in seen_config_keys:
                continue
            seen_config_keys.add(key)
            deduped_configs.append(config)
        return deduped_configs

    configs = build_candidate_configs(source_configs)
    if not configs:
        raise SystemExit(f"no candidate configs found in {source_path}")

    settings = get_settings()
    base_url = str(args.base_url or source_args.get("base_url") or settings.binance_rest_base_url or "https://fapi.binance.com").rstrip("/")
    cache_dir = Path(args.cache_dir or source_args.get("cache_dir") or "reports/validation/btc_flip_rotation_search/cache")
    try:
        fold_start_override = _parse_fold_start_at(getattr(args, "fold_start_at", ""))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    effective_load_days = max(
        int(args.load_days),
        _load_days_covering_fold_start(fold_start_override),
    )
    args.load_days = effective_load_days
    exec_bars_all = _load_bars(
        symbol=symbol,
        interval=exec_interval,
        days=max(effective_load_days, int(args.train_days) + int(args.test_days) + 5),
        cache_dir=cache_dir,
        base_url=base_url,
        sleep_seconds=float(args.sleep_seconds),
    )
    scenario_bars_all = {
        interval: _load_bars(
            symbol=symbol,
            interval=interval,
            days=max(effective_load_days, int(args.train_days) + int(args.test_days) + 5),
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

    try:
        fold_start = (
            fold_start_override
            if fold_start_override is not None
            else _anchored_fold_start(
                exec_bars_all[0].ts,
                args.fold_anchor_hour_utc,
                args.fold_anchor_minute_utc,
            )
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    last_ts = exec_bars_all[-1].ts.astimezone(UTC)
    first_loaded_ts = exec_bars_all[0].ts.astimezone(UTC)
    if fold_start < first_loaded_ts:
        raise SystemExit(
            "fold start is before the loaded execution bars; increase --load-days "
            f"(fold_start_at={fold_start.isoformat()}, first_loaded={first_loaded_ts.isoformat()})"
        )
    if fold_start >= last_ts:
        raise SystemExit(
            "fold start is after the loaded execution bars "
            f"(fold_start_at={fold_start.isoformat()}, last_loaded={last_ts.isoformat()})"
        )
    initial_fold_start = fold_start
    train_delta = timedelta(days=max(int(args.train_days), 1))
    test_delta = timedelta(days=max(int(args.test_days), 1))
    step_delta = timedelta(days=max(int(args.step_days), 1))
    folds: list[dict[str, Any]] = []
    selection_history_folds: list[dict[str, Any]] = []
    fold_idx = 0
    valid_fold_idx = 0
    fold_offset = max(0, int(args.fold_offset))
    source_replay_auto_warm_selection_state = _source_replay_should_auto_warm_selection_state(
        args,
        inherited_fields=inherited_source_replay_fields,
        fold_offset=fold_offset,
    )
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
        is_reported_fold = valid_fold_idx > fold_offset
        if not is_reported_fold and not (
            bool(args.warm_fold_offset_selection_state) or source_replay_auto_warm_selection_state
        ):
            fold_start += step_delta
            continue

        fold_source_configs = _configs_from_source_fold(
            source_report,
            fold=valid_fold_idx,
            top_n=max(1, int(args.top_n)),
        )
        fold_configs = build_candidate_configs(fold_source_configs) if fold_source_configs else configs
        if not fold_configs:
            fold_start += step_delta
            continue
        train_results: list[dict[str, Any]] = []
        warm_note = " warming" if not is_reported_fold else ""
        print(
            f"walk-forward fold {valid_fold_idx}{warm_note} training {len(fold_configs)} candidates",
            flush=True,
        )
        for config_idx, config in enumerate(fold_configs, start=1):
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
                result["walk_forward_selection_score"] = round(_selection_score_from_args(result, args), 6)
                _apply_regime_dependency_penalty(result, args)
                _apply_recent_efficiency_penalty(
                    result,
                    selection_history_folds,
                    lookback=int(args.selection_recent_efficiency_lookback),
                    min_samples=int(args.selection_recent_efficiency_min_samples),
                    min_train_return_pct=float(args.selection_recent_efficiency_min_train_return_pct),
                    efficiency_threshold=float(args.selection_recent_efficiency_threshold),
                    penalty=float(args.selection_recent_efficiency_penalty),
                )
                train_results.append(result)
            print(f"walk-forward fold {valid_fold_idx} trained {config_idx}/{len(fold_configs)}", flush=True)
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
        train_results, selection_guard = _apply_unresolved_stress_raw_leader_guard(
            train_results,
            args,
        )
        train_results, negative_train_distribution_guard = (
            _apply_negative_train_distribution_rescue_guard(
                train_results,
                args,
            )
        )
        if negative_train_distribution_guard:
            if (
                selection_guard is not None
                and bool(negative_train_distribution_guard.get("applied"))
            ):
                negative_train_distribution_guard["previous_selection_guard"] = selection_guard
            if bool(negative_train_distribution_guard.get("applied")) or selection_guard is None:
                selection_guard = negative_train_distribution_guard
        train_results, high_cost_runner_guard = _apply_high_cost_runner_rescue_guard(
            train_results,
            args,
        )
        if high_cost_runner_guard:
            if selection_guard is not None and bool(high_cost_runner_guard.get("applied")):
                high_cost_runner_guard["previous_selection_guard"] = selection_guard
            if bool(high_cost_runner_guard.get("applied")) or selection_guard is None:
                selection_guard = high_cost_runner_guard
        train_results, deep_soft_overlay_guard = _apply_deep_soft_overlay_rescue_guard(
            train_results,
            args,
        )
        if deep_soft_overlay_guard:
            if selection_guard is not None and bool(deep_soft_overlay_guard.get("applied")):
                deep_soft_overlay_guard["previous_selection_guard"] = selection_guard
            if bool(deep_soft_overlay_guard.get("applied")) or selection_guard is None:
                selection_guard = deep_soft_overlay_guard
        train_results, deep_drawdown_reversal_guard = (
            _apply_deep_drawdown_reversal_rescue_guard(
                train_results,
                args,
            )
        )
        if deep_drawdown_reversal_guard:
            if selection_guard is not None and bool(deep_drawdown_reversal_guard.get("applied")):
                deep_drawdown_reversal_guard["previous_selection_guard"] = selection_guard
            if bool(deep_drawdown_reversal_guard.get("applied")) or selection_guard is None:
                selection_guard = deep_drawdown_reversal_guard
        selected_train = train_results[0]
        selected_train, source_replay_selected_train_anchor = _source_replay_selected_train_anchor(
            source_report,
            fold=valid_fold_idx,
            train_results=train_results,
            selected_train=selected_train,
            enabled=not bool(args.disable_source_replay_selected_train_anchor),
        )
        selected_config = MarketStateConfig(**selected_train["config"])
        source_selected_config = selected_config
        recent_oos_block_details = _after_selection_recent_oos_blocks(selection_history_folds, args)
        recent_oos_block_enforced = bool(recent_oos_block_details) and (
            _after_selection_recent_oos_block_should_enforce(args)
        )
        recent_oos_block_reasons = (
            {overlay: "recent_oos_block" for overlay in recent_oos_block_details}
            if recent_oos_block_enforced
            else {}
        )
        selected_config, overlays_applied, overlays_skipped = _apply_after_selection_overlays(
            selected_config,
            selected_train,
            args,
            blocked_overlays=recent_oos_block_reasons,
        )
        after_selection_recent_oos_block = (
            {
                "mode": args.after_selection_recent_oos_block_mode,
                "enforced": recent_oos_block_enforced,
                "would_block": bool(recent_oos_block_details),
                "blocked_overlays": sorted(recent_oos_block_details),
                "details": recent_oos_block_details,
            }
            if bool(args.after_selection_recent_oos_block)
            else None
        )
        after_selection_train_confirmation: dict[str, Any] | None = None
        confirmation_targets = (
            _after_selection_confirmation_targets(overlays_applied, args)
            if bool(args.after_selection_train_confirmation)
            else []
        )
        if confirmation_targets:
            confirmation_ablation_mode = str(args.after_selection_confirmation_ablation_mode)
            confirmed_train = _run_config(
                symbol=symbol,
                features=train_features,
                scenario_features=train_scenario_features,
                scenario_maps=train_maps,
                config=selected_config,
                cost_rate=cost_rate,
                carry_rate_per_bar=carry_rate_per_bar,
                min_periods=int(args.min_periods),
            )
            if confirmed_train:
                confirmed_train["walk_forward_selection_score"] = round(
                    _selection_score_from_args(confirmed_train, args),
                    6,
                )
                if confirmation_ablation_mode == "per_overlay":
                    target_details: dict[str, dict[str, Any]] = {}
                    rejected_targets: list[str] = []
                    failed_checks: set[str] = set()
                    for target in confirmation_targets:
                        target_block_reasons = dict(recent_oos_block_reasons)
                        target_block_reasons[target] = "train_confirm_rejected"
                        ablated_config, _, _ = _apply_after_selection_overlays(
                            source_selected_config,
                            selected_train,
                            args,
                            blocked_overlays=target_block_reasons,
                        )
                        ablated_train = _run_config(
                            symbol=symbol,
                            features=train_features,
                            scenario_features=train_scenario_features,
                            scenario_maps=train_maps,
                            config=ablated_config,
                            cost_rate=cost_rate,
                            carry_rate_per_bar=carry_rate_per_bar,
                            min_periods=int(args.min_periods),
                        )
                        if ablated_train:
                            ablated_train["walk_forward_selection_score"] = round(
                                _selection_score_from_args(ablated_train, args),
                                6,
                            )
                            target_passed, target_detail = _after_selection_train_confirmation(
                                ablated_train,
                                confirmed_train,
                                args,
                            )
                        else:
                            target_passed = False
                            target_detail = {
                                "passed": False,
                                "failed_checks": ["train_ablation_rerun_failed"],
                            }
                        target_detail = {
                            **target_detail,
                            "passed": target_passed,
                            "baseline_model_id": ablated_config.model_id,
                            "evaluated_model_id": selected_config.model_id,
                        }
                        target_details[target] = target_detail
                        failed_checks.update(str(item) for item in target_detail.get("failed_checks") or [])
                        if not target_passed:
                            rejected_targets.append(target)
                    confirmation_passed = not rejected_targets
                    confirmation_details = {
                        "passed": confirmation_passed,
                        "failed_checks": sorted(failed_checks),
                        "target_details": target_details,
                        "rejected_overlays": rejected_targets,
                    }
                else:
                    confirmation_passed, confirmation_details = _after_selection_train_confirmation(
                        selected_train,
                        confirmed_train,
                        args,
                    )
                    rejected_targets = list(confirmation_targets) if not confirmation_passed else []
            else:
                confirmation_passed = False
                rejected_targets = list(confirmation_targets)
                confirmation_details = {"passed": False, "failed_checks": ["train_rerun_failed"]}
            after_selection_train_confirmation = {
                **confirmation_details,
                "mode": args.after_selection_confirmation_mode,
                "ablation_mode": confirmation_ablation_mode,
                "enforced": False,
                "would_reject": not confirmation_passed,
                "target_overlays": confirmation_targets,
                "rejected_overlays": list(confirmation_details.get("rejected_overlays") or rejected_targets),
                "evaluated_model_id": selected_config.model_id,
                "source_model_id": source_selected_config.model_id,
            }
            if not confirmation_passed and _after_selection_confirmation_should_enforce(args):
                confirmation_block_reasons = dict(recent_oos_block_reasons)
                confirmation_block_reasons.update(
                    {
                        overlay: "train_confirm_rejected"
                        for overlay in after_selection_train_confirmation["rejected_overlays"]
                    }
                )
                selected_config, overlays_applied, overlays_skipped = _apply_after_selection_overlays(
                    source_selected_config,
                    selected_train,
                    args,
                    blocked_overlays=confirmation_block_reasons,
                )
                after_selection_train_confirmation["enforced"] = True
                after_selection_train_confirmation["post_rejection_model_id"] = selected_config.model_id
        low_confidence_abstain = _low_confidence_abstain_decision(selected_train, args)
        if low_confidence_abstain:
            overlays_applied = [*overlays_applied, "low_confidence_abstain"]
            print(f"walk-forward fold {valid_fold_idx} abstaining selected candidate", flush=True)
            test_result = _flat_walk_forward_result(
                symbol=symbol,
                exec_interval=exec_interval,
                config=selected_config,
                features=test_features,
                reason=str(low_confidence_abstain.get("reason") or "low_confidence"),
            )
        else:
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
        train_top_test_results: list[dict[str, Any]] = []
        top_test_count = (
            min(max(0, int(args.test_top_train_candidates)), len(train_results))
            if is_reported_fold
            else 0
        )
        for rank, train_candidate in enumerate(train_results[:top_test_count], start=1):
            if rank == 1:
                candidate_config = selected_config
                candidate_applied = overlays_applied
                candidate_skipped = overlays_skipped
                candidate_test = test_result
            else:
                candidate_config = MarketStateConfig(**train_candidate["config"])
                candidate_config, candidate_applied, candidate_skipped = _apply_after_selection_overlays(
                    candidate_config,
                    train_candidate,
                    args,
                    blocked_overlays=recent_oos_block_reasons,
                )
                candidate_test = _run_config(
                    symbol=symbol,
                    features=test_features,
                    scenario_features=test_scenario_features,
                    scenario_maps=test_maps,
                    config=candidate_config,
                    cost_rate=cost_rate,
                    carry_rate_per_bar=carry_rate_per_bar,
                    min_periods=int(args.min_periods),
                )
            train_diagnostics = dict(train_candidate.get("event_diagnostics") or {})
            test_diagnostics = dict((candidate_test or {}).get("event_diagnostics") or {})
            train_top_test_results.append(
                {
                    "rank": rank,
                    "is_selected": rank == 1,
                    "model_id": candidate_config.model_id,
                    "after_selection_overlays_applied": candidate_applied,
                    "after_selection_overlays_skipped": candidate_skipped,
                    "train_selection_score": train_candidate.get("walk_forward_selection_score"),
                    "train_return_pct": train_candidate.get("total_return_pct"),
                    "train_max_drawdown_pct": train_candidate.get("max_drawdown_pct"),
                    "train_flags": train_diagnostics.get("flags") or [],
                    "test_return_pct": (candidate_test or {}).get("total_return_pct"),
                    "test_max_drawdown_pct": (candidate_test or {}).get("max_drawdown_pct"),
                    "test_trade_like_events": (candidate_test or {}).get("trade_like_events"),
                    "test_flags": test_diagnostics.get("flags") or [],
                    "test_result": candidate_test,
                }
            )
        fold_record = {
            "fold": valid_fold_idx,
            "chunk_fold": len(folds) + 1 if is_reported_fold else 0,
            "train_start": train_start.date().isoformat(),
            "train_end": train_end.date().isoformat(),
            "test_start": test_start.date().isoformat(),
            "test_end": test_end.date().isoformat(),
            "train_start_at": train_start.isoformat(),
            "train_end_at": train_end.isoformat(),
            "test_start_at": test_start.isoformat(),
            "test_end_at": test_end.isoformat(),
            "train_meta": train_meta,
            "test_meta": test_meta,
            "selected_model_id": selected_config.model_id,
            "after_selection_overlays_applied": overlays_applied,
            "after_selection_overlays_skipped": overlays_skipped,
            "after_selection_recent_oos_block": after_selection_recent_oos_block,
            "after_selection_train_confirmation": after_selection_train_confirmation,
            "selection_guard": selection_guard,
            "source_replay_selected_train_anchor": source_replay_selected_train_anchor,
            "low_confidence_abstain": low_confidence_abstain,
            "selected_train_result": selected_train,
            "test_result": test_result,
            "train_top_results": train_results[:5],
            "train_top_test_results": train_top_test_results,
        }
        selection_history_folds.append(fold_record)
        if is_reported_fold:
            folds.append(fold_record)
            print(f"walk-forward fold {valid_fold_idx} selected {selected_config.model_id}", flush=True)
            if int(args.fold_limit) > 0 and len(folds) >= int(args.fold_limit):
                break
        else:
            print(f"walk-forward fold {valid_fold_idx} warmed {selected_config.model_id}", flush=True)
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
        "fold_start_at": initial_fold_start.isoformat(),
        "fold_anchor_hour_utc": args.fold_anchor_hour_utc,
        "fold_anchor_minute_utc": (
            int(args.fold_anchor_minute_utc) if args.fold_anchor_hour_utc is not None else None
        ),
        "candidate_count": len(configs),
        "source_replay_inherited_selection_policy_fields": inherited_source_replay_fields,
        "source_replay_inherited_config_override_fields": inherited_source_replay_fields,
        "source_replay_forced_selection_fields": forced_source_replay_selection_fields,
        "source_replay_inherited_window_policy_fields": inherited_source_replay_window_fields,
        "source_replay_stabilized_ratio_gate_fields": stabilized_source_replay_ratio_gate_fields,
        "source_replay_clamped_selection_policy_fields": (
            getattr(args, "_source_replay_clamped_selection_policy_fields", [])
        ),
        "source_replay_inherited_model_encoded_fields": inherited_source_replay_model_encoded_fields,
        "source_replay_auto_warm_selection_state": source_replay_auto_warm_selection_state,
        "source_replay_selected_train_anchor_enabled": not bool(
            args.disable_source_replay_selected_train_anchor
        ),
        "cost_model": {
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": float(args.slippage_bps_per_side),
            "funding_bps_per_8h": float(args.funding_bps_per_8h),
            "borrow_bps_per_day": float(args.borrow_bps_per_day),
            "carry_rate_per_bar": carry_rate_per_bar,
        },
        "config_overrides": {
            "midfold_reaction_hold_recipes": getattr(args, "midfold_reaction_hold_recipes", None),
            "selective_reaction_repair_clean_recipes": getattr(
                args,
                "selective_reaction_repair_clean_recipes",
                None,
            ),
            "trim_cooldown_recipes": getattr(args, "trim_cooldown_recipes", None),
            "risk_off_micro_sizer_recipe": getattr(args, "risk_off_micro_sizer_recipe", None),
            "disable_source_replay_selected_train_anchor": bool(
                args.disable_source_replay_selected_train_anchor
            ),
            "force_near_miss_in_selection": bool(args.force_near_miss_in_selection),
            "balanced_structure_replay_note": getattr(args, "balanced_structure_replay_note", None),
            "high_cost_repair_cut_05_replay_note": getattr(
                args,
                "high_cost_repair_cut_05_replay_note",
                None,
            ),
            "high_cost_near_zero_react_replay_note": getattr(
                args,
                "high_cost_near_zero_react_replay_note",
                None,
            ),
            "role_balance_impulse_micro_replay_note": getattr(
                args,
                "role_balance_impulse_micro_replay_note",
                None,
            ),
            "role_border_impulse_micro_replay_note": getattr(
                args,
                "role_border_impulse_micro_replay_note",
                None,
            ),
            "low_activity_reengage_probe_replay_note": getattr(
                args,
                "low_activity_reengage_probe_replay_note",
                None,
            ),
            "base_heavy_probe_rebalance_replay_note": getattr(
                args,
                "base_heavy_probe_rebalance_replay_note",
                None,
            ),
            "event_risk_base_throttle_replay_note": getattr(
                args,
                "event_risk_base_throttle_replay_note",
                None,
            ),
            "event_risk_base_tight_repair_replay_note": getattr(
                args,
                "event_risk_base_tight_repair_replay_note",
                None,
            ),
            "low_return_stress_base_throttle_replay_note": getattr(
                args,
                "low_return_stress_base_throttle_replay_note",
                None,
            ),
            "event_risk_reaction_soft_hold_replay_note": getattr(
                args,
                "event_risk_reaction_soft_hold_replay_note",
                None,
            ),
            "event_risk_soft_hold_near_miss_replay_note": getattr(
                args,
                "event_risk_soft_hold_near_miss_replay_note",
                None,
            ),
            "negative_train_distribution_probe_replay_note": getattr(
                args,
                "negative_train_distribution_probe_replay_note",
                None,
            ),
            "compressed_trend_distribution_probe_replay_note": getattr(
                args,
                "compressed_trend_distribution_probe_replay_note",
                None,
            ),
            "event_risk_distribution_base_off_replay_note": getattr(
                args,
                "event_risk_distribution_base_off_replay_note",
                None,
            ),
            "event_risk_soft_hold_inventory_release_replay_note": getattr(
                args,
                "event_risk_soft_hold_inventory_release_replay_note",
                None,
            ),
            "event_risk_soft_hold_inventory_release_fraction": float(
                args.event_risk_soft_hold_inventory_release_fraction
            ),
            "fold13_stress_exit_sizer_replay_note": getattr(
                args,
                "fold13_stress_exit_sizer_replay_note",
                None,
            ),
            "fold13_stress_exit_sizer_reaction_trim_size_mult": float(
                args.fold13_stress_exit_sizer_reaction_trim_size_mult
            ),
            "fold13_stress_exit_sizer_hard_time_fraction": float(
                args.fold13_stress_exit_sizer_hard_time_fraction
            ),
            "fold13_selective_impulse_replay_note": getattr(
                args,
                "fold13_selective_impulse_replay_note",
                None,
            ),
            "fold13_selective_impulse_probe_units": float(
                args.fold13_selective_impulse_probe_units
            ),
            "fold13_selective_impulse_min_one_way_score": float(
                args.fold13_selective_impulse_min_one_way_score
            ),
            "fold13_selective_impulse_min_score_diff": int(
                args.fold13_selective_impulse_min_score_diff
            ),
            "fold13_selective_impulse_reaction_trim_trigger": float(
                args.fold13_selective_impulse_reaction_trim_trigger
            ),
            "fold13_near_miss_noise_filter_replay_note": getattr(
                args,
                "fold13_near_miss_noise_filter_replay_note",
                None,
            ),
            "fold13_hard_loss_defer_replay_note": getattr(
                args,
                "fold13_hard_loss_defer_replay_note",
                None,
            ),
            "fold13_hold_extension_replay_note": getattr(
                args,
                "fold13_hold_extension_replay_note",
                None,
            ),
            "fold13_hold_extension_bars": int(args.fold13_hold_extension_bars),
            "fold13_one_way_delay_replay_note": getattr(
                args,
                "fold13_one_way_delay_replay_note",
                None,
            ),
            "fold13_one_way_delay_min_adverse_reaction": float(
                args.fold13_one_way_delay_min_adverse_reaction
            ),
            "fold13_reaction_band_widen_replay_note": getattr(
                args,
                "fold13_reaction_band_widen_replay_note",
                None,
            ),
            "fold13_reaction_band_widen_avg_band": float(
                args.fold13_reaction_band_widen_avg_band
            ),
            "fold11_reaction_delay_replay_note": getattr(
                args,
                "fold11_reaction_delay_replay_note",
                None,
            ),
            "fold11_reaction_delay_trigger": float(
                args.fold11_reaction_delay_trigger
            ),
            "fold8_chase_suppress_replay_note": getattr(
                args,
                "fold8_chase_suppress_replay_note",
                None,
            ),
            "fold8_chase_suppress_units": float(
                args.fold8_chase_suppress_units
            ),
            "deep_drawdown_reversal_scale_replay_note": getattr(
                args,
                "deep_drawdown_reversal_scale_replay_note",
                None,
            ),
            "high_cost_runner_reversal_scale_replay_note": getattr(
                args,
                "high_cost_runner_reversal_scale_replay_note",
                None,
            ),
            "high_cost_runner_tight_repair_replay_note": getattr(
                args,
                "high_cost_runner_tight_repair_replay_note",
                None,
            ),
            "low_return_soft_inventory_trim_replay_note": getattr(
                args,
                "low_return_soft_inventory_trim_replay_note",
                None,
            ),
            "low_return_soft_inventory_trim_fraction": float(
                args.low_return_soft_inventory_trim_fraction
            ),
            "low_return_selective_impulse_replay_note": getattr(
                args,
                "low_return_selective_impulse_replay_note",
                None,
            ),
            "low_return_selective_impulse_probe_units": float(
                args.low_return_selective_impulse_probe_units
            ),
            "low_return_selective_impulse_min_one_way_score": float(
                args.low_return_selective_impulse_min_one_way_score
            ),
            "low_return_selective_impulse_min_score_diff": int(
                args.low_return_selective_impulse_min_score_diff
            ),
            "low_return_impulse_noise_filter_replay_note": getattr(
                args,
                "low_return_impulse_noise_filter_replay_note",
                None,
            ),
            "low_return_normal_short_base_throttle_replay_note": getattr(
                args,
                "low_return_normal_short_base_throttle_replay_note",
                None,
            ),
            "low_return_current_chain_replay_note": getattr(
                args,
                "low_return_current_chain_replay_note",
                None,
            ),
            "low_return_reaction_band_replay_note": getattr(
                args,
                "low_return_reaction_band_replay_note",
                None,
            ),
            "low_return_reaction_avg_band": float(
                args.low_return_reaction_avg_band
            ),
            "low_return_stress_reaction_band_restore_replay_note": getattr(
                args,
                "low_return_stress_reaction_band_restore_replay_note",
                None,
            ),
            "low_return_stress_reaction_band_restore_avg_band": float(
                args.low_return_stress_reaction_band_restore_avg_band
            ),
            "low_return_repair_stop_replay_note": getattr(
                args,
                "low_return_repair_stop_replay_note",
                None,
            ),
            "low_return_repair_stop_value": float(args.low_return_repair_stop_value),
            "low_return_repair_stop_reaction_trim_trigger": float(
                args.low_return_repair_stop_reaction_trim_trigger
            ),
            "low_return_repair_stop_tighten_replay_note": getattr(
                args,
                "low_return_repair_stop_tighten_replay_note",
                None,
            ),
            "low_return_repair_stop_tighten_value": float(
                args.low_return_repair_stop_tighten_value
            ),
            "low_return_strong_impulse_replay_note": getattr(
                args,
                "low_return_strong_impulse_replay_note",
                None,
            ),
            "low_return_strong_impulse_probe_units": float(
                args.low_return_strong_impulse_probe_units
            ),
            "low_return_strong_impulse_min_one_way_score": float(
                args.low_return_strong_impulse_min_one_way_score
            ),
            "low_return_strong_impulse_min_score_diff": int(
                args.low_return_strong_impulse_min_score_diff
            ),
            "low_return_strong_impulse_cooldown_bars": int(
                args.low_return_strong_impulse_cooldown_bars
            ),
            "low_return_strong_impulse_max_extension_atr": float(
                args.low_return_strong_impulse_max_extension_atr
            ),
            "low_return_strong_impulse_probe_take_profit_reaction": float(
                args.low_return_strong_impulse_probe_take_profit_reaction
            ),
            "fast_defense_one_way_delay_replay_note": getattr(
                args,
                "fast_defense_one_way_delay_replay_note",
                None,
            ),
            "fast_defense_one_way_delay_min_adverse_reaction": float(
                args.fast_defense_one_way_delay_min_adverse_reaction
            ),
            "fast_defense_one_way_delay_max_defensive_cooldown_bars": int(
                args.fast_defense_one_way_delay_max_defensive_cooldown_bars
            ),
            "deep_soft_reaction_delay_replay_note": getattr(
                args,
                "deep_soft_reaction_delay_replay_note",
                None,
            ),
            "forced_trim_near_miss_tiny_replay_note": getattr(
                args,
                "forced_trim_near_miss_tiny_replay_note",
                None,
            ),
            "soft_circuit_recovery_mid_replay_note": getattr(
                args,
                "soft_circuit_recovery_mid_replay_note",
                None,
            ),
            "soft_circuit_recovery_mid_probe_units": float(
                args.soft_circuit_recovery_mid_probe_units
            ),
            "soft_circuit_recovery_mid_min_one_way_score": float(
                args.soft_circuit_recovery_mid_min_one_way_score
            ),
            "soft_circuit_recovery_mid_min_score_diff": int(
                args.soft_circuit_recovery_mid_min_score_diff
            ),
            "soft_circuit_recovery_mid_max_extension_atr": float(
                args.soft_circuit_recovery_mid_max_extension_atr
            ),
            "soft_circuit_recovery_mid_failure_guard_count": int(
                args.soft_circuit_recovery_mid_failure_guard_count
            ),
            "soft_circuit_recovery_mid_failure_guard_window_bars": int(
                args.soft_circuit_recovery_mid_failure_guard_window_bars
            ),
            "soft_circuit_recovery_mid_failure_cooldown_bars": int(
                args.soft_circuit_recovery_mid_failure_cooldown_bars
            ),
            "soft_circuit_recovery_low_activity_replay_note": getattr(
                args,
                "soft_circuit_recovery_low_activity_replay_note",
                None,
            ),
            "soft_circuit_recovery_low_activity_probe_units": float(
                args.soft_circuit_recovery_low_activity_probe_units
            ),
            "soft_circuit_recovery_low_activity_min_one_way_score": float(
                args.soft_circuit_recovery_low_activity_min_one_way_score
            ),
            "soft_circuit_recovery_low_activity_min_score_diff": int(
                args.soft_circuit_recovery_low_activity_min_score_diff
            ),
            "soft_circuit_recovery_low_activity_max_extension_atr": float(
                args.soft_circuit_recovery_low_activity_max_extension_atr
            ),
            "soft_circuit_recovery_low_activity_failure_guard_count": int(
                args.soft_circuit_recovery_low_activity_failure_guard_count
            ),
            "soft_circuit_recovery_low_activity_failure_guard_window_bars": int(
                args.soft_circuit_recovery_low_activity_failure_guard_window_bars
            ),
            "soft_circuit_recovery_low_activity_failure_cooldown_bars": int(
                args.soft_circuit_recovery_low_activity_failure_cooldown_bars
            ),
            "soft_circuit_low_activity_cooldown_replay_note": getattr(
                args,
                "soft_circuit_low_activity_cooldown_replay_note",
                None,
            ),
            "soft_circuit_low_activity_entry_grace_replay_note": getattr(
                args,
                "soft_circuit_low_activity_entry_grace_replay_note",
                None,
            ),
            "soft_circuit_low_activity_near_miss_replay_note": getattr(
                args,
                "soft_circuit_low_activity_near_miss_replay_note",
                None,
            ),
            "soft_circuit_low_activity_cooldown_bars": int(
                args.soft_circuit_low_activity_cooldown_bars
            ),
            "soft_circuit_low_activity_entry_grace_bars": int(
                args.soft_circuit_low_activity_entry_grace_bars
            ),
            "high_return_soft_sizer_relax_replay_note": getattr(
                args,
                "high_return_soft_sizer_relax_replay_note",
                None,
            ),
            "high_return_soft_sizer_relax_drawdown_pct": float(
                args.high_return_soft_sizer_relax_drawdown_pct
            ),
            "high_return_soft_sizer_relax_size_mult": float(
                args.high_return_soft_sizer_relax_size_mult
            ),
            "high_return_soft_sizer_relax_cooldown_bars": int(
                args.high_return_soft_sizer_relax_cooldown_bars
            ),
            "high_return_soft_sizer_tight_replay_note": getattr(
                args,
                "high_return_soft_sizer_tight_replay_note",
                None,
            ),
            "high_return_soft_sizer_tight_drawdown_pct": float(
                args.high_return_soft_sizer_tight_drawdown_pct
            ),
            "high_return_soft_sizer_tight_size_mult": float(
                args.high_return_soft_sizer_tight_size_mult
            ),
            "high_return_soft_sizer_tight_cooldown_bars": int(
                args.high_return_soft_sizer_tight_cooldown_bars
            ),
            "after_selection_train_confirmation": bool(args.after_selection_train_confirmation),
            "after_selection_confirmation_mode": args.after_selection_confirmation_mode,
            "after_selection_confirmation_ablation_mode": (
                args.after_selection_confirmation_ablation_mode
            ),
            "after_selection_confirm_min_score_delta": args.after_selection_confirm_min_score_delta,
            "after_selection_confirm_min_return_delta_pct": (
                args.after_selection_confirm_min_return_delta_pct
            ),
            "after_selection_confirm_max_drawdown_delta_pct": (
                args.after_selection_confirm_max_drawdown_delta_pct
            ),
            "after_selection_confirm_max_cost_delta_pct": args.after_selection_confirm_max_cost_delta_pct,
            "after_selection_confirm_min_return_per_cost_delta": (
                args.after_selection_confirm_min_return_per_cost_delta
            ),
            "after_selection_confirm_overlays": args.after_selection_confirm_overlays,
            "after_selection_recent_oos_block": bool(args.after_selection_recent_oos_block),
            "after_selection_recent_oos_block_mode": args.after_selection_recent_oos_block_mode,
            "after_selection_recent_oos_block_lookback": int(
                args.after_selection_recent_oos_block_lookback
            ),
            "after_selection_recent_oos_block_min_samples": int(
                args.after_selection_recent_oos_block_min_samples
            ),
            "after_selection_recent_oos_block_min_avg_return_pct": (
                args.after_selection_recent_oos_block_min_avg_return_pct
            ),
            "after_selection_recent_oos_block_min_compounded_return_pct": (
                args.after_selection_recent_oos_block_min_compounded_return_pct
            ),
            "after_selection_recent_oos_block_max_drawdown_pct": (
                args.after_selection_recent_oos_block_max_drawdown_pct
            ),
            "after_selection_recent_oos_block_max_avg_cost_drag_pct": (
                args.after_selection_recent_oos_block_max_avg_cost_drag_pct
            ),
            "after_selection_recent_oos_block_max_cost_to_return_ratio": (
                args.after_selection_recent_oos_block_max_cost_to_return_ratio
            ),
            "after_selection_recent_oos_block_confirmation_warnings": bool(
                args.after_selection_recent_oos_block_confirmation_warnings
            ),
            "after_selection_recent_oos_block_overlays": args.after_selection_recent_oos_block_overlays,
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
            "one_way_trim_context_after_selection_require_base_reduce": bool(
                args.one_way_trim_context_after_selection_require_base_reduce
            ),
            **_train_state_after_selection_override_payload(args, "one_way_trim_context_late_after_selection"),
            "one_way_loss_fuse_min_adverse_reaction": args.one_way_loss_fuse_min_adverse_reaction,
            "one_way_loss_fuse_cooldown_bars": args.one_way_loss_fuse_cooldown_bars,
            "one_way_loss_fuse_size_mult": args.one_way_loss_fuse_size_mult,
            "one_way_loss_fuse_after_selection": bool(args.one_way_loss_fuse_after_selection),
            "one_way_loss_fuse_after_selection_min_train_return_pct": (
                args.one_way_loss_fuse_after_selection_min_train_return_pct
            ),
            "one_way_loss_fuse_after_selection_max_train_return_pct": (
                args.one_way_loss_fuse_after_selection_max_train_return_pct
            ),
            "one_way_loss_fuse_after_selection_min_train_drawdown_pct": (
                args.one_way_loss_fuse_after_selection_min_train_drawdown_pct
            ),
            "one_way_loss_fuse_after_selection_max_train_drawdown_pct": (
                args.one_way_loss_fuse_after_selection_max_train_drawdown_pct
            ),
            "one_way_loss_fuse_after_selection_min_one_way_trim_per_add": float(
                args.one_way_loss_fuse_after_selection_min_one_way_trim_per_add
            ),
            "one_way_loss_fuse_after_selection_max_one_way_trim_per_add": float(
                args.one_way_loss_fuse_after_selection_max_one_way_trim_per_add
            ),
            "one_way_trim_full_exit_min_one_way_score": args.one_way_trim_full_exit_min_one_way_score,
            "one_way_trim_full_exit_min_score_diff": args.one_way_trim_full_exit_min_score_diff,
            "defensive_trim_cooldown_bars": args.defensive_trim_cooldown_bars,
            "include_no_defensive_trim_cooldown_candidates": bool(
                args.include_no_defensive_trim_cooldown_candidates
            ),
            "one_way_trim_full_exit_after_selection": bool(args.one_way_trim_full_exit_after_selection),
            "trend_idle_probe_units": args.trend_idle_probe_units,
            "trend_idle_min_score": args.trend_idle_min_score,
            "trend_idle_min_reason_stack": args.trend_idle_min_reason_stack,
            "trend_idle_cooldown_bars": args.trend_idle_cooldown_bars,
            "trend_idle_max_extension_atr": args.trend_idle_max_extension_atr,
            "near_miss_probe_units": args.near_miss_probe_units,
            "near_miss_probe_min_score": args.near_miss_probe_min_score,
            "near_miss_probe_min_score_edge": args.near_miss_probe_min_score_edge,
            "near_miss_probe_min_reason_stack": args.near_miss_probe_min_reason_stack,
            "near_miss_probe_cooldown_bars": args.near_miss_probe_cooldown_bars,
            "near_miss_probe_max_extension_atr": args.near_miss_probe_max_extension_atr,
            "near_miss_probe_failure_guard_count": args.near_miss_probe_failure_guard_count,
            "near_miss_probe_failure_guard_window_bars": args.near_miss_probe_failure_guard_window_bars,
            "near_miss_probe_failure_cooldown_bars": args.near_miss_probe_failure_cooldown_bars,
            "near_miss_probe_allowed_soft_reasons": args.near_miss_probe_allowed_soft_reasons,
            "near_miss_probe_allowed_alignments": args.near_miss_probe_allowed_alignments,
            "near_miss_probe_allowed_execution_contexts": args.near_miss_probe_allowed_execution_contexts,
            "near_miss_probe_allowed_regimes": args.near_miss_probe_allowed_regimes,
            "near_miss_context_guard_after_selection": bool(args.near_miss_context_guard_after_selection),
            "near_miss_context_guard_blocked_overlays": (
                args.near_miss_context_guard_blocked_overlays
            ),
            "include_no_near_miss_probe_candidates": bool(args.include_no_near_miss_probe_candidates),
            "near_miss_after_selection": bool(args.near_miss_after_selection),
            "near_miss_after_selection_min_train_return_pct": (
                args.near_miss_after_selection_min_train_return_pct
            ),
            "near_miss_after_selection_max_train_return_pct": (
                args.near_miss_after_selection_max_train_return_pct
            ),
            "near_miss_after_selection_min_train_drawdown_pct": (
                args.near_miss_after_selection_min_train_drawdown_pct
            ),
            "near_miss_after_selection_max_train_drawdown_pct": (
                args.near_miss_after_selection_max_train_drawdown_pct
            ),
            **_train_state_after_selection_override_payload(args, "near_miss_late_after_selection"),
            **_train_state_after_selection_override_payload(args, "near_miss_mid_after_selection"),
            **_near_miss_probe_override_payload(args, "near_miss_mid"),
            **_train_state_after_selection_override_payload(args, "near_miss_activity_after_selection"),
            **_near_miss_probe_override_payload(args, "near_miss_activity"),
            **_train_state_after_selection_override_payload(args, "near_miss_high_after_selection"),
            "trend_idle_after_selection": bool(args.trend_idle_after_selection),
            "trend_idle_after_selection_min_train_return_pct": (
                args.trend_idle_after_selection_min_train_return_pct
            ),
            "trend_idle_after_selection_max_train_return_pct": (
                args.trend_idle_after_selection_max_train_return_pct
            ),
            "trend_idle_after_selection_min_train_drawdown_pct": (
                args.trend_idle_after_selection_min_train_drawdown_pct
            ),
            "trend_idle_after_selection_max_train_drawdown_pct": (
                args.trend_idle_after_selection_max_train_drawdown_pct
            ),
            "equity_circuit_breaker_drawdown_pct": args.equity_circuit_breaker_drawdown_pct,
            "equity_circuit_breaker_pause_bars": args.equity_circuit_breaker_pause_bars,
            "equity_circuit_rearm_drawdown_pct": args.equity_circuit_rearm_drawdown_pct,
            "equity_circuit_breaker_after_selection": bool(args.equity_circuit_breaker_after_selection),
            "include_no_equity_circuit_candidates": bool(args.include_no_equity_circuit_candidates),
            "equity_soft_circuit_drawdown_pct": args.equity_soft_circuit_drawdown_pct,
            "equity_soft_circuit_cooldown_bars": args.equity_soft_circuit_cooldown_bars,
            "equity_soft_circuit_size_mult": args.equity_soft_circuit_size_mult,
            "equity_soft_circuit_force_flat": bool(args.equity_soft_circuit_force_flat),
            "equity_soft_circuit_prearm_bars": args.equity_soft_circuit_prearm_bars,
            "equity_soft_circuit_min_bars_after_add": args.equity_soft_circuit_min_bars_after_add,
            "equity_soft_circuit_after_selection": bool(args.equity_soft_circuit_after_selection),
            "equity_soft_circuit_after_selection_min_train_return_pct": (
                args.equity_soft_circuit_after_selection_min_train_return_pct
            ),
            "equity_soft_circuit_after_selection_max_train_return_pct": (
                args.equity_soft_circuit_after_selection_max_train_return_pct
            ),
            "equity_soft_circuit_after_selection_min_train_drawdown_pct": (
                args.equity_soft_circuit_after_selection_min_train_drawdown_pct
            ),
            "equity_soft_circuit_after_selection_max_train_drawdown_pct": (
                args.equity_soft_circuit_after_selection_max_train_drawdown_pct
            ),
            "equity_soft_circuit_after_selection_min_one_way_trim_per_add": float(
                args.equity_soft_circuit_after_selection_min_one_way_trim_per_add
            ),
            "equity_soft_circuit_after_selection_max_one_way_trim_per_add": float(
                args.equity_soft_circuit_after_selection_max_one_way_trim_per_add
            ),
            "equity_soft_circuit_after_selection_require_base_reduce": bool(
                args.equity_soft_circuit_after_selection_require_base_reduce
            ),
            "equity_soft_sizer_after_selection": bool(args.equity_soft_sizer_after_selection),
            "equity_soft_sizer_after_selection_drawdown_pct": (
                args.equity_soft_sizer_after_selection_drawdown_pct
            ),
            "equity_soft_sizer_after_selection_cooldown_bars": (
                args.equity_soft_sizer_after_selection_cooldown_bars
            ),
            "equity_soft_sizer_after_selection_size_mult": (
                args.equity_soft_sizer_after_selection_size_mult
            ),
            "equity_soft_sizer_after_selection_force_flat": bool(
                args.equity_soft_sizer_after_selection_force_flat
            ),
            "equity_soft_sizer_after_selection_prearm_bars": (
                args.equity_soft_sizer_after_selection_prearm_bars
            ),
            "equity_soft_sizer_after_selection_min_source_max_units": (
                args.equity_soft_sizer_after_selection_min_source_max_units
            ),
            "equity_soft_sizer_after_selection_max_source_max_units": (
                args.equity_soft_sizer_after_selection_max_source_max_units
            ),
            "equity_soft_sizer_after_selection_min_train_return_pct": (
                args.equity_soft_sizer_after_selection_min_train_return_pct
            ),
            "equity_soft_sizer_after_selection_max_train_return_pct": (
                args.equity_soft_sizer_after_selection_max_train_return_pct
            ),
            "equity_soft_sizer_after_selection_min_train_drawdown_pct": (
                args.equity_soft_sizer_after_selection_min_train_drawdown_pct
            ),
            "equity_soft_sizer_after_selection_max_train_drawdown_pct": (
                args.equity_soft_sizer_after_selection_max_train_drawdown_pct
            ),
            "equity_soft_sizer_after_selection_min_train_cost_drag_pct": (
                args.equity_soft_sizer_after_selection_min_train_cost_drag_pct
            ),
            "equity_soft_sizer_after_selection_max_train_cost_drag_pct": (
                args.equity_soft_sizer_after_selection_max_train_cost_drag_pct
            ),
            "equity_soft_sizer_after_selection_min_one_way_trim_per_add": float(
                args.equity_soft_sizer_after_selection_min_one_way_trim_per_add
            ),
            "equity_soft_sizer_after_selection_max_one_way_trim_per_add": float(
                args.equity_soft_sizer_after_selection_max_one_way_trim_per_add
            ),
            "equity_soft_sizer_after_selection_min_turnover_per_add": float(
                args.equity_soft_sizer_after_selection_min_turnover_per_add
            ),
            "equity_soft_sizer_after_selection_max_turnover_per_add": float(
                args.equity_soft_sizer_after_selection_max_turnover_per_add
            ),
            "equity_soft_sizer_alt_after_selection": bool(args.equity_soft_sizer_alt_after_selection),
            "equity_soft_sizer_alt_after_selection_drawdown_pct": (
                args.equity_soft_sizer_alt_after_selection_drawdown_pct
            ),
            "equity_soft_sizer_alt_after_selection_cooldown_bars": (
                args.equity_soft_sizer_alt_after_selection_cooldown_bars
            ),
            "equity_soft_sizer_alt_after_selection_size_mult": (
                args.equity_soft_sizer_alt_after_selection_size_mult
            ),
            "equity_soft_sizer_alt_after_selection_force_flat": bool(
                args.equity_soft_sizer_alt_after_selection_force_flat
            ),
            "equity_soft_sizer_alt_after_selection_prearm_bars": (
                args.equity_soft_sizer_alt_after_selection_prearm_bars
            ),
            "equity_soft_sizer_alt_after_selection_min_source_max_units": (
                args.equity_soft_sizer_alt_after_selection_min_source_max_units
            ),
            "equity_soft_sizer_alt_after_selection_max_source_max_units": (
                args.equity_soft_sizer_alt_after_selection_max_source_max_units
            ),
            "equity_soft_sizer_alt_after_selection_min_train_return_pct": (
                args.equity_soft_sizer_alt_after_selection_min_train_return_pct
            ),
            "equity_soft_sizer_alt_after_selection_max_train_return_pct": (
                args.equity_soft_sizer_alt_after_selection_max_train_return_pct
            ),
            "equity_soft_sizer_alt_after_selection_min_train_drawdown_pct": (
                args.equity_soft_sizer_alt_after_selection_min_train_drawdown_pct
            ),
            "equity_soft_sizer_alt_after_selection_max_train_drawdown_pct": (
                args.equity_soft_sizer_alt_after_selection_max_train_drawdown_pct
            ),
            "equity_soft_sizer_alt_after_selection_min_train_cost_drag_pct": (
                args.equity_soft_sizer_alt_after_selection_min_train_cost_drag_pct
            ),
            "equity_soft_sizer_alt_after_selection_max_train_cost_drag_pct": (
                args.equity_soft_sizer_alt_after_selection_max_train_cost_drag_pct
            ),
            "equity_soft_sizer_alt_after_selection_min_one_way_trim_per_add": float(
                args.equity_soft_sizer_alt_after_selection_min_one_way_trim_per_add
            ),
            "equity_soft_sizer_alt_after_selection_max_one_way_trim_per_add": float(
                args.equity_soft_sizer_alt_after_selection_max_one_way_trim_per_add
            ),
            "equity_soft_sizer_alt_after_selection_min_turnover_per_add": float(
                args.equity_soft_sizer_alt_after_selection_min_turnover_per_add
            ),
            "equity_soft_sizer_alt_after_selection_max_turnover_per_add": float(
                args.equity_soft_sizer_alt_after_selection_max_turnover_per_add
            ),
            "equity_soft_sizer_deep_after_selection": bool(args.equity_soft_sizer_deep_after_selection),
            "equity_soft_sizer_deep_after_selection_drawdown_pct": (
                args.equity_soft_sizer_deep_after_selection_drawdown_pct
            ),
            "equity_soft_sizer_deep_after_selection_cooldown_bars": (
                args.equity_soft_sizer_deep_after_selection_cooldown_bars
            ),
            "equity_soft_sizer_deep_after_selection_size_mult": (
                args.equity_soft_sizer_deep_after_selection_size_mult
            ),
            "equity_soft_sizer_deep_after_selection_force_flat": bool(
                args.equity_soft_sizer_deep_after_selection_force_flat
            ),
            "equity_soft_sizer_deep_after_selection_prearm_bars": (
                args.equity_soft_sizer_deep_after_selection_prearm_bars
            ),
            "equity_soft_sizer_deep_after_selection_min_source_max_units": (
                args.equity_soft_sizer_deep_after_selection_min_source_max_units
            ),
            "equity_soft_sizer_deep_after_selection_max_source_max_units": (
                args.equity_soft_sizer_deep_after_selection_max_source_max_units
            ),
            "equity_soft_sizer_deep_after_selection_min_train_return_pct": (
                args.equity_soft_sizer_deep_after_selection_min_train_return_pct
            ),
            "equity_soft_sizer_deep_after_selection_max_train_return_pct": (
                args.equity_soft_sizer_deep_after_selection_max_train_return_pct
            ),
            "equity_soft_sizer_deep_after_selection_min_train_drawdown_pct": (
                args.equity_soft_sizer_deep_after_selection_min_train_drawdown_pct
            ),
            "equity_soft_sizer_deep_after_selection_max_train_drawdown_pct": (
                args.equity_soft_sizer_deep_after_selection_max_train_drawdown_pct
            ),
            "equity_soft_sizer_deep_after_selection_min_train_cost_drag_pct": (
                args.equity_soft_sizer_deep_after_selection_min_train_cost_drag_pct
            ),
            "equity_soft_sizer_deep_after_selection_max_train_cost_drag_pct": (
                args.equity_soft_sizer_deep_after_selection_max_train_cost_drag_pct
            ),
            "equity_soft_sizer_deep_after_selection_min_one_way_trim_per_add": float(
                args.equity_soft_sizer_deep_after_selection_min_one_way_trim_per_add
            ),
            "equity_soft_sizer_deep_after_selection_max_one_way_trim_per_add": float(
                args.equity_soft_sizer_deep_after_selection_max_one_way_trim_per_add
            ),
            "equity_soft_sizer_deep_after_selection_min_turnover_per_add": float(
                args.equity_soft_sizer_deep_after_selection_min_turnover_per_add
            ),
            "equity_soft_sizer_deep_after_selection_max_turnover_per_add": float(
                args.equity_soft_sizer_deep_after_selection_max_turnover_per_add
            ),
            "one_way_reversal_switch_units": args.one_way_reversal_switch_units,
            "one_way_reversal_min_score_edge": args.one_way_reversal_min_score_edge,
            "one_way_reversal_cooldown_bars": args.one_way_reversal_cooldown_bars,
            "one_way_reversal_allow_scenario_override": bool(args.one_way_reversal_allow_scenario_override),
            "one_way_reversal_allow_score_override": bool(args.one_way_reversal_allow_score_override),
            "one_way_trim_size_mult": args.one_way_trim_size_mult,
            "hard_time_exit_fraction": args.hard_time_exit_fraction,
            "hard_time_exit_cooldown_bars": args.hard_time_exit_cooldown_bars,
            "reaction_trim_size_mult": args.reaction_trim_size_mult,
            "reaction_trim_trend_hold_trigger_mult": args.reaction_trim_trend_hold_trigger_mult,
            "hard_time_exit_trend_defer_bars": args.hard_time_exit_trend_defer_bars,
            "hard_time_exit_trend_defer_min_favorable_reaction": (
                args.hard_time_exit_trend_defer_min_favorable_reaction
            ),
            "trend_hold_min_trend_strength": args.trend_hold_min_trend_strength,
            "trend_hold_min_one_way_score": args.trend_hold_min_one_way_score,
            "one_way_reversal_after_selection": bool(args.one_way_reversal_after_selection),
            "one_way_reversal_after_selection_switch_units": (
                args.one_way_reversal_after_selection_switch_units
            ),
            "one_way_reversal_after_selection_min_train_return_pct": (
                args.one_way_reversal_after_selection_min_train_return_pct
            ),
            "one_way_reversal_after_selection_max_train_return_pct": (
                args.one_way_reversal_after_selection_max_train_return_pct
            ),
            "one_way_reversal_after_selection_min_train_drawdown_pct": (
                args.one_way_reversal_after_selection_min_train_drawdown_pct
            ),
            "one_way_reversal_after_selection_max_train_drawdown_pct": (
                args.one_way_reversal_after_selection_max_train_drawdown_pct
            ),
            "one_way_reversal_after_selection_min_one_way_trim_per_add": float(
                args.one_way_reversal_after_selection_min_one_way_trim_per_add
            ),
            "one_way_reversal_after_selection_max_one_way_trim_per_add": float(
                args.one_way_reversal_after_selection_max_one_way_trim_per_add
            ),
            "one_way_reversal_after_selection_weak_switch_units": (
                args.one_way_reversal_after_selection_weak_switch_units
            ),
            "one_way_reversal_after_selection_weak_min_train_return_pct": (
                args.one_way_reversal_after_selection_weak_min_train_return_pct
            ),
            "one_way_reversal_after_selection_weak_max_train_return_pct": (
                args.one_way_reversal_after_selection_weak_max_train_return_pct
            ),
            "one_way_reversal_after_selection_weak_min_train_drawdown_pct": (
                args.one_way_reversal_after_selection_weak_min_train_drawdown_pct
            ),
            "one_way_reversal_after_selection_weak_max_train_drawdown_pct": (
                args.one_way_reversal_after_selection_weak_max_train_drawdown_pct
            ),
            "one_way_reversal_after_selection_weak_min_one_way_trim_per_add": float(
                args.one_way_reversal_after_selection_weak_min_one_way_trim_per_add
            ),
            "one_way_reversal_after_selection_weak_max_one_way_trim_per_add": float(
                args.one_way_reversal_after_selection_weak_max_one_way_trim_per_add
            ),
            "one_way_reversal_after_selection_alt_min_train_return_pct": (
                args.one_way_reversal_after_selection_alt_min_train_return_pct
            ),
            "one_way_reversal_after_selection_alt_max_train_return_pct": (
                args.one_way_reversal_after_selection_alt_max_train_return_pct
            ),
            "one_way_reversal_after_selection_alt_min_train_drawdown_pct": (
                args.one_way_reversal_after_selection_alt_min_train_drawdown_pct
            ),
            "one_way_reversal_after_selection_alt_max_train_drawdown_pct": (
                args.one_way_reversal_after_selection_alt_max_train_drawdown_pct
            ),
            "one_way_reversal_after_selection_alt_min_train_cost_drag_pct": (
                args.one_way_reversal_after_selection_alt_min_train_cost_drag_pct
            ),
            "one_way_reversal_after_selection_alt_max_train_cost_drag_pct": (
                args.one_way_reversal_after_selection_alt_max_train_cost_drag_pct
            ),
            "one_way_reversal_after_selection_alt_min_one_way_trim_per_add": float(
                args.one_way_reversal_after_selection_alt_min_one_way_trim_per_add
            ),
            "one_way_reversal_after_selection_alt_max_one_way_trim_per_add": float(
                args.one_way_reversal_after_selection_alt_max_one_way_trim_per_add
            ),
            "one_way_reversal_after_selection_alt_min_turnover_per_add": float(
                args.one_way_reversal_after_selection_alt_min_turnover_per_add
            ),
            "one_way_reversal_after_selection_alt_max_turnover_per_add": float(
                args.one_way_reversal_after_selection_alt_max_turnover_per_add
            ),
            "one_way_reversal_after_selection_alt_min_reaction_trim_per_remove": float(
                args.one_way_reversal_after_selection_alt_min_reaction_trim_per_remove
            ),
            "one_way_reversal_after_selection_alt_max_reaction_trim_per_remove": float(
                args.one_way_reversal_after_selection_alt_max_reaction_trim_per_remove
            ),
            **_train_state_after_selection_override_payload(
                args,
                "one_way_reversal_suppress_after_selection",
            ),
            **_one_way_reversal_tune_after_selection_override_payload(
                args,
                "one_way_reversal_boost_after_selection",
            ),
            **_one_way_reversal_tune_after_selection_override_payload(
                args,
                "one_way_reversal_fine_after_selection",
            ),
            "one_way_impulse_probe_units": args.one_way_impulse_probe_units,
            "one_way_impulse_min_one_way_score": args.one_way_impulse_min_one_way_score,
            "one_way_impulse_min_score_diff": args.one_way_impulse_min_score_diff,
            "one_way_impulse_cooldown_bars": args.one_way_impulse_cooldown_bars,
            "one_way_impulse_max_extension_atr": args.one_way_impulse_max_extension_atr,
            **_one_way_impulse_after_selection_override_payload(args, "one_way_impulse_after_selection"),
            **_one_way_impulse_after_selection_override_payload(args, "one_way_impulse_alt_after_selection"),
            **_one_way_impulse_after_selection_override_payload(args, "one_way_impulse_tail_after_selection"),
            **_one_way_impulse_after_selection_override_payload(args, "one_way_impulse_late_after_selection"),
            **_one_way_impulse_after_selection_override_payload(args, "one_way_impulse_micro_after_selection"),
            **_one_way_impulse_after_selection_override_payload(args, "role_balance_impulse_after_selection"),
            **_train_state_after_selection_override_payload(args, "low_confidence_abstain_after_selection"),
            "low_confidence_abstain_after_selection_min_train_score": (
                args.low_confidence_abstain_after_selection_min_train_score
            ),
            "low_confidence_abstain_after_selection_max_train_score": (
                args.low_confidence_abstain_after_selection_max_train_score
            ),
            "low_confidence_abstain_after_selection_min_chase_add_per_add": float(
                args.low_confidence_abstain_after_selection_min_chase_add_per_add
            ),
            "low_confidence_abstain_after_selection_max_chase_add_per_add": float(
                args.low_confidence_abstain_after_selection_max_chase_add_per_add
            ),
            "low_confidence_abstain_after_selection_min_battle_add_per_add": float(
                args.low_confidence_abstain_after_selection_min_battle_add_per_add
            ),
            "low_confidence_abstain_after_selection_max_battle_add_per_add": float(
                args.low_confidence_abstain_after_selection_max_battle_add_per_add
            ),
            "scenario_flip_units": args.scenario_flip_units,
            "scenario_flip_min_score_edge": args.scenario_flip_min_score_edge,
            "scenario_flip_min_adverse_reaction": args.scenario_flip_min_adverse_reaction,
            "scenario_flip_min_one_way_score": args.scenario_flip_min_one_way_score,
            "scenario_flip_cooldown_bars": args.scenario_flip_cooldown_bars,
            "scenario_flip_max_extension_atr": args.scenario_flip_max_extension_atr,
            "winner_pyramid_units": args.winner_pyramid_units,
            "winner_pyramid_min_profit_reaction": args.winner_pyramid_min_profit_reaction,
            "winner_pyramid_min_score": args.winner_pyramid_min_score,
            "winner_pyramid_min_reason_stack": args.winner_pyramid_min_reason_stack,
            "winner_pyramid_cooldown_bars": args.winner_pyramid_cooldown_bars,
            "winner_pyramid_max_units": args.winner_pyramid_max_units,
            "winner_pyramid_max_extension_atr": args.winner_pyramid_max_extension_atr,
            "base_entry_max_extension_atr": args.base_entry_max_extension_atr,
            "base_entry_max_extension_side": args.base_entry_max_extension_side or None,
            "base_entry_reduce_extension_atr": args.base_entry_reduce_extension_atr,
            "base_entry_reduce_size_mult": args.base_entry_reduce_size_mult,
            "base_entry_reduce_promote_reaction": args.base_entry_reduce_promote_reaction,
            "base_entry_reduce_max_trend_strength": args.base_entry_reduce_max_trend_strength,
            "base_entry_reduce_min_trend_strength": args.base_entry_reduce_min_trend_strength,
            "base_entry_reduce_side": args.base_entry_reduce_side or None,
            "base_context_reduce_size_mult": args.base_context_reduce_size_mult,
            "base_context_reduce_patterns": args.base_context_reduce_patterns or None,
            "negative_base_context_reduce_after_selection": bool(
                args.negative_base_context_reduce_after_selection
            ),
            **_train_state_after_selection_override_payload(
                args,
                "negative_base_context_reduce_after_selection",
            ),
            "negative_base_context_reduce_size_mult": float(args.negative_base_context_reduce_size_mult),
            "negative_base_context_reduce_min_loss_usd_units": float(
                args.negative_base_context_reduce_min_loss_usd_units
            ),
            "negative_base_context_reduce_max_per_add_usd_units": float(
                args.negative_base_context_reduce_max_per_add_usd_units
            ),
            "negative_base_context_reduce_min_add_count": int(args.negative_base_context_reduce_min_add_count),
            "negative_base_context_reduce_max_contexts": int(args.negative_base_context_reduce_max_contexts),
            "event_risk_base_reduce_size_mult": args.event_risk_base_reduce_size_mult,
            "event_risk_base_reduce_min_extension_atr": args.event_risk_base_reduce_min_extension_atr,
            "event_risk_base_reduce_max_extension_atr": args.event_risk_base_reduce_max_extension_atr,
            "event_risk_base_reduce_side": args.event_risk_base_reduce_side or None,
            "event_risk_base_reduce_contexts": args.event_risk_base_reduce_contexts or None,
            "regime_router_enabled": bool(args.regime_router_enabled),
            "router_trend_reaction_size_mult": args.router_trend_reaction_size_mult,
            "router_one_way_chase_size_mult": args.router_one_way_chase_size_mult,
            "router_one_way_counter_size_mult": args.router_one_way_counter_size_mult,
            "router_range_probe_size_mult": args.router_range_probe_size_mult,
            "router_range_base_size_mult": args.router_range_base_size_mult,
            "router_exhaustion_reversal_size_mult": args.router_exhaustion_reversal_size_mult,
            "router_exhaustion_min_score_edge": args.router_exhaustion_min_score_edge,
            "router_exhaustion_min_extension_atr": args.router_exhaustion_min_extension_atr,
            "router_risk_off_size_mult": args.router_risk_off_size_mult,
            "router_transition_trim_fraction": args.router_transition_trim_fraction,
            "router_transition_trim_modes": args.router_transition_trim_modes or None,
            "router_transition_trim_cooldown_bars": args.router_transition_trim_cooldown_bars,
            "router_transition_trim_against_only": bool(args.router_transition_trim_against_only),
            "base_entry_reduce_after_selection": bool(args.base_entry_reduce_after_selection),
            "base_entry_reduce_after_selection_max_train_return_pct": (
                args.base_entry_reduce_after_selection_max_train_return_pct
            ),
            "base_entry_reduce_after_selection_min_train_return_pct": (
                args.base_entry_reduce_after_selection_min_train_return_pct
            ),
            "base_entry_reduce_after_selection_max_train_drawdown_pct": (
                args.base_entry_reduce_after_selection_max_train_drawdown_pct
            ),
            "base_entry_reduce_after_selection_min_one_way_trim_per_add": float(
                args.base_entry_reduce_after_selection_min_one_way_trim_per_add
            ),
            **_train_state_after_selection_override_payload(args, "base_reduce_suppress_after_selection"),
            "fragile_regime_entry_size_mult": args.fragile_regime_entry_size_mult,
            "fragile_regime_entry_regimes": args.fragile_regime_entry_regimes,
            "fragile_regime_inventory_trim_fraction": args.fragile_regime_inventory_trim_fraction,
            "fragile_regime_inventory_trim_regimes": args.fragile_regime_inventory_trim_regimes,
            "fragile_regime_entry_after_selection": bool(args.fragile_regime_entry_after_selection),
            "fragile_regime_entry_after_selection_min_train_return_pct": (
                args.fragile_regime_entry_after_selection_min_train_return_pct
            ),
            "fragile_regime_entry_after_selection_max_train_return_pct": (
                args.fragile_regime_entry_after_selection_max_train_return_pct
            ),
            "fragile_regime_entry_after_selection_min_train_drawdown_pct": (
                args.fragile_regime_entry_after_selection_min_train_drawdown_pct
            ),
            "fragile_regime_entry_after_selection_max_train_drawdown_pct": (
                args.fragile_regime_entry_after_selection_max_train_drawdown_pct
            ),
            "fragile_regime_entry_high_size_mult": args.fragile_regime_entry_high_size_mult,
            "fragile_regime_entry_high_regimes": args.fragile_regime_entry_high_regimes,
            **_train_state_after_selection_override_payload(args, "fragile_regime_entry_high_after_selection"),
            "fragile_regime_entry_low_size_mult": args.fragile_regime_entry_low_size_mult,
            "fragile_regime_entry_low_regimes": args.fragile_regime_entry_low_regimes,
            **_train_state_after_selection_override_payload(args, "fragile_regime_entry_low_after_selection"),
            "fragile_regime_inventory_trim_after_selection": bool(
                args.fragile_regime_inventory_trim_after_selection
            ),
            "fragile_regime_inventory_trim_after_selection_min_train_return_pct": (
                args.fragile_regime_inventory_trim_after_selection_min_train_return_pct
            ),
            "fragile_regime_inventory_trim_after_selection_max_train_return_pct": (
                args.fragile_regime_inventory_trim_after_selection_max_train_return_pct
            ),
            "fragile_regime_inventory_trim_after_selection_min_train_drawdown_pct": (
                args.fragile_regime_inventory_trim_after_selection_min_train_drawdown_pct
            ),
            "fragile_regime_inventory_trim_after_selection_max_train_drawdown_pct": (
                args.fragile_regime_inventory_trim_after_selection_max_train_drawdown_pct
            ),
            "risk_smoothing_after_selection": bool(args.risk_smoothing_after_selection),
            "risk_smoothing_after_selection_max_possible_units": (
                args.risk_smoothing_after_selection_max_possible_units
            ),
            "risk_smoothing_after_selection_base_max_units": args.risk_smoothing_after_selection_base_max_units,
            "risk_smoothing_after_selection_battle_units": args.risk_smoothing_after_selection_battle_units,
            "risk_smoothing_after_selection_defensive_trim_cooldown_bars": (
                args.risk_smoothing_after_selection_defensive_trim_cooldown_bars
            ),
            "risk_smoothing_after_selection_max_hold_bars": args.risk_smoothing_after_selection_max_hold_bars,
            "risk_smoothing_after_selection_min_train_return_pct": (
                args.risk_smoothing_after_selection_min_train_return_pct
            ),
            "risk_smoothing_after_selection_max_train_return_pct": (
                args.risk_smoothing_after_selection_max_train_return_pct
            ),
            "risk_smoothing_after_selection_min_train_drawdown_pct": (
                args.risk_smoothing_after_selection_min_train_drawdown_pct
            ),
            "risk_smoothing_after_selection_max_train_drawdown_pct": (
                args.risk_smoothing_after_selection_max_train_drawdown_pct
            ),
            "risk_smoothing_after_selection_min_train_cost_drag_pct": (
                args.risk_smoothing_after_selection_min_train_cost_drag_pct
            ),
            "risk_smoothing_after_selection_max_train_cost_drag_pct": (
                args.risk_smoothing_after_selection_max_train_cost_drag_pct
            ),
            "risk_smoothing_after_selection_min_one_way_trim_per_add": float(
                args.risk_smoothing_after_selection_min_one_way_trim_per_add
            ),
            "risk_smoothing_after_selection_max_one_way_trim_per_add": float(
                args.risk_smoothing_after_selection_max_one_way_trim_per_add
            ),
            "risk_smoothing_after_selection_min_turnover_per_add": float(
                args.risk_smoothing_after_selection_min_turnover_per_add
            ),
            "risk_smoothing_after_selection_max_turnover_per_add": float(
                args.risk_smoothing_after_selection_max_turnover_per_add
            ),
            **_train_state_after_selection_override_payload(
                args,
                "hold_compression_after_selection",
            ),
            "hold_compression_after_selection_max_hold_bars": (
                args.hold_compression_after_selection_max_hold_bars
            ),
            **_train_state_after_selection_override_payload(
                args,
                "hold_extension_after_selection",
            ),
            "hold_extension_after_selection_max_hold_bars": args.hold_extension_after_selection_max_hold_bars,
            **_train_state_after_selection_override_payload(
                args,
                "reaction_tune_after_selection",
            ),
            "reaction_tune_after_selection_reaction_trim_trigger": (
                args.reaction_tune_after_selection_reaction_trim_trigger
            ),
            "reaction_tune_after_selection_repair_cut": (
                args.reaction_tune_after_selection_repair_cut
            ),
            "reaction_tune_after_selection_repair_stop": (
                args.reaction_tune_after_selection_repair_stop
            ),
            **_train_state_after_selection_override_payload(
                args,
                "reaction_tune_strong_after_selection",
            ),
            "reaction_tune_strong_after_selection_reaction_trim_trigger": (
                args.reaction_tune_strong_after_selection_reaction_trim_trigger
            ),
            "reaction_tune_strong_after_selection_repair_cut": (
                args.reaction_tune_strong_after_selection_repair_cut
            ),
            "reaction_tune_strong_after_selection_repair_stop": (
                args.reaction_tune_strong_after_selection_repair_stop
            ),
            **_train_state_after_selection_override_payload(
                args,
                "exit_trend_hold_after_selection",
            ),
            "exit_trend_hold_after_selection_reaction_trim_trigger_mult": (
                args.exit_trend_hold_after_selection_reaction_trim_trigger_mult
            ),
            "exit_trend_hold_after_selection_hard_time_defer_bars": (
                args.exit_trend_hold_after_selection_hard_time_defer_bars
            ),
            "exit_trend_hold_after_selection_hard_time_min_favorable_reaction": (
                args.exit_trend_hold_after_selection_hard_time_min_favorable_reaction
            ),
            "exit_trend_hold_after_selection_min_trend_strength": (
                args.exit_trend_hold_after_selection_min_trend_strength
            ),
            "exit_trend_hold_after_selection_min_one_way_score": (
                args.exit_trend_hold_after_selection_min_one_way_score
            ),
            **_train_state_after_selection_override_payload(
                args,
                "repair_tune_after_selection",
            ),
            "repair_tune_after_selection_repair_cut": (
                args.repair_tune_after_selection_repair_cut
            ),
            "repair_tune_after_selection_repair_stop": (
                args.repair_tune_after_selection_repair_stop
            ),
            **_train_state_after_selection_override_payload(
                args,
                "repair_tune_high_cost_after_selection",
            ),
            "repair_tune_high_cost_after_selection_repair_cut": (
                args.repair_tune_high_cost_after_selection_repair_cut
            ),
            "repair_tune_high_cost_after_selection_repair_stop": (
                args.repair_tune_high_cost_after_selection_repair_stop
            ),
            **_train_state_after_selection_override_payload(
                args,
                "distribution_balance_after_selection",
            ),
            **_near_miss_probe_override_payload(args, "distribution_balance"),
            **_trim_cooldown_after_selection_override_payload(
                args,
                "high_cost_balance_after_selection",
            ),
            **_near_miss_probe_override_payload(args, "high_cost_balance"),
            **_train_state_after_selection_override_payload(
                args,
                "trim_cooldown_after_selection",
            ),
            "trim_cooldown_after_selection_one_way_trim_cooldown_bars": (
                args.trim_cooldown_after_selection_one_way_trim_cooldown_bars
            ),
            "trim_cooldown_after_selection_base_entry_reduce_extension_atr": (
                args.trim_cooldown_after_selection_base_entry_reduce_extension_atr
            ),
            "trim_cooldown_after_selection_base_entry_reduce_size_mult": (
                args.trim_cooldown_after_selection_base_entry_reduce_size_mult
            ),
            "trim_cooldown_after_selection_base_entry_reduce_promote_reaction": (
                args.trim_cooldown_after_selection_base_entry_reduce_promote_reaction
            ),
            **_trim_cooldown_after_selection_override_payload(
                args,
                "trim_cooldown_deep_after_selection",
            ),
            **_trim_cooldown_after_selection_override_payload(
                args,
                "trim_cooldown_strong_after_selection",
            ),
            **_trim_cooldown_after_selection_override_payload(
                args,
                "trim_cooldown_high_cost_after_selection",
            ),
            **_train_state_after_selection_override_payload(
                args,
                "risk_off_micro_after_selection",
            ),
            "risk_off_micro_after_selection_max_possible_units": (
                args.risk_off_micro_after_selection_max_possible_units
            ),
            "risk_off_micro_after_selection_base_max_units": (
                args.risk_off_micro_after_selection_base_max_units
            ),
            "risk_off_micro_after_selection_battle_units": (
                args.risk_off_micro_after_selection_battle_units
            ),
            "risk_off_micro_after_selection_trend_core_units": (
                args.risk_off_micro_after_selection_trend_core_units
            ),
            "risk_off_micro_after_selection_reaction_trim_trigger": (
                args.risk_off_micro_after_selection_reaction_trim_trigger
            ),
            **_train_state_after_selection_override_payload(
                args,
                "battle_restore_after_selection",
            ),
            "battle_restore_after_selection_min_battle_add_per_add": float(
                args.battle_restore_after_selection_min_battle_add_per_add
            ),
            "battle_restore_after_selection_max_battle_add_per_add": float(
                args.battle_restore_after_selection_max_battle_add_per_add
            ),
            "battle_restore_after_selection_min_max_role_add_share": float(
                args.battle_restore_after_selection_min_max_role_add_share
            ),
            "battle_restore_after_selection_max_max_role_add_share": float(
                args.battle_restore_after_selection_max_max_role_add_share
            ),
            "battle_restore_after_selection_min_add_events": int(
                args.battle_restore_after_selection_min_add_events
            ),
            "battle_restore_after_selection_max_add_events": int(
                args.battle_restore_after_selection_max_add_events
            ),
            "battle_restore_after_selection_battle_units": (
                args.battle_restore_after_selection_battle_units
            ),
            "battle_restore_after_selection_battle_score": (
                args.battle_restore_after_selection_battle_score
            ),
            "battle_restore_after_selection_battle_trigger_usd": (
                args.battle_restore_after_selection_battle_trigger_usd
            ),
            "battle_restore_after_selection_battle_trigger_atr": (
                args.battle_restore_after_selection_battle_trigger_atr
            ),
            "battle_restore_after_selection_max_repair_eff_for_add": (
                args.battle_restore_after_selection_max_repair_eff_for_add
            ),
            "battle_restore_after_selection_min_capacity_ratio": (
                args.battle_restore_after_selection_min_capacity_ratio
            ),
            "exposure_rebalance_after_selection": bool(args.exposure_rebalance_after_selection),
            "exposure_rebalance_after_selection_max_possible_units": (
                args.exposure_rebalance_after_selection_max_possible_units
            ),
            "exposure_rebalance_after_selection_base_max_units": (
                args.exposure_rebalance_after_selection_base_max_units
            ),
            "exposure_rebalance_after_selection_base_add_units": (
                args.exposure_rebalance_after_selection_base_add_units
            ),
            "exposure_rebalance_after_selection_battle_units": (
                args.exposure_rebalance_after_selection_battle_units
            ),
            "exposure_rebalance_after_selection_min_source_max_units": (
                args.exposure_rebalance_after_selection_min_source_max_units
            ),
            "exposure_rebalance_after_selection_max_source_max_units": (
                args.exposure_rebalance_after_selection_max_source_max_units
            ),
            "exposure_rebalance_after_selection_min_train_return_pct": (
                args.exposure_rebalance_after_selection_min_train_return_pct
            ),
            "exposure_rebalance_after_selection_max_train_return_pct": (
                args.exposure_rebalance_after_selection_max_train_return_pct
            ),
            "exposure_rebalance_after_selection_min_train_drawdown_pct": (
                args.exposure_rebalance_after_selection_min_train_drawdown_pct
            ),
            "exposure_rebalance_after_selection_max_train_drawdown_pct": (
                args.exposure_rebalance_after_selection_max_train_drawdown_pct
            ),
            "exposure_rebalance_after_selection_min_train_cost_drag_pct": (
                args.exposure_rebalance_after_selection_min_train_cost_drag_pct
            ),
            "exposure_rebalance_after_selection_max_train_cost_drag_pct": (
                args.exposure_rebalance_after_selection_max_train_cost_drag_pct
            ),
            "exposure_rebalance_after_selection_min_one_way_trim_per_add": float(
                args.exposure_rebalance_after_selection_min_one_way_trim_per_add
            ),
            "exposure_rebalance_after_selection_max_one_way_trim_per_add": float(
                args.exposure_rebalance_after_selection_max_one_way_trim_per_add
            ),
            "exposure_rebalance_after_selection_min_turnover_per_add": float(
                args.exposure_rebalance_after_selection_min_turnover_per_add
            ),
            "exposure_rebalance_after_selection_max_turnover_per_add": float(
                args.exposure_rebalance_after_selection_max_turnover_per_add
            ),
            "include_no_impulse_candidates": bool(args.include_no_impulse_candidates),
            "include_no_btc_rotation_candidates": bool(args.include_no_btc_rotation_candidates),
            "include_no_base_reduce_candidates": bool(args.include_no_base_reduce_candidates),
            "include_no_one_way_loss_fuse_candidates": bool(args.include_no_one_way_loss_fuse_candidates),
            "impulse_selection_score_penalty": float(args.impulse_selection_score_penalty),
            "btc_rotation_selection_score_penalty": float(args.btc_rotation_selection_score_penalty),
            "selection_flag_penalty": float(args.selection_flag_penalty),
            "selection_score_cap": float(args.selection_score_cap),
            "selection_mdd_soft_threshold_pct": float(args.selection_mdd_soft_threshold_pct),
            "selection_mdd_soft_penalty": float(args.selection_mdd_soft_penalty),
            "selection_cost_soft_threshold_pct": float(args.selection_cost_soft_threshold_pct),
            "selection_cost_soft_penalty": float(args.selection_cost_soft_penalty),
            "selection_stress_cost_multiplier": float(args.selection_stress_cost_multiplier),
            "selection_stress_funding_proxy_pct": float(args.selection_stress_funding_proxy_pct),
            "selection_stress_min_return_floor_pct": float(args.selection_stress_min_return_floor_pct),
            "selection_stress_floor_gap_penalty": float(args.selection_stress_floor_gap_penalty),
            "selection_cost_to_gross_threshold": float(args.selection_cost_to_gross_threshold),
            "selection_cost_to_gross_penalty": float(args.selection_cost_to_gross_penalty),
            "selection_reaction_usd_risk_threshold": float(args.selection_reaction_usd_risk_threshold),
            "selection_reaction_usd_risk_penalty": float(args.selection_reaction_usd_risk_penalty),
            "selection_reaction_usd_risk_min_train_drawdown_pct": float(
                args.selection_reaction_usd_risk_min_train_drawdown_pct
            ),
            "selection_reaction_usd_risk_min_turnover_per_add": float(
                args.selection_reaction_usd_risk_min_turnover_per_add
            ),
            "selection_reaction_usd_risk_min_one_way_trim_per_add": float(
                args.selection_reaction_usd_risk_min_one_way_trim_per_add
            ),
            "selection_reaction_usd_risk_min_cost_drag_pct": float(
                args.selection_reaction_usd_risk_min_cost_drag_pct
            ),
            "selection_max_reaction_usd": float(args.selection_max_reaction_usd),
            "selection_stress_unresolved_keep_raw_leader": bool(
                args.selection_stress_unresolved_keep_raw_leader
            ),
            "selection_stress_unresolved_return_giveback_pct": float(
                args.selection_stress_unresolved_return_giveback_pct
            ),
            "selection_stress_unresolved_leader_metric": str(
                args.selection_stress_unresolved_leader_metric
            ),
            "selection_stress_unresolved_low_return_max_selected_pct": (
                args.selection_stress_unresolved_low_return_max_selected_pct
            ),
            "selection_stress_unresolved_low_return_giveback_pct": (
                args.selection_stress_unresolved_low_return_giveback_pct
            ),
            "selection_stress_unresolved_drawdown_rescue_min_selected_pct": (
                args.selection_stress_unresolved_drawdown_rescue_min_selected_pct
            ),
            "selection_stress_unresolved_drawdown_rescue_max_selected_pct": (
                args.selection_stress_unresolved_drawdown_rescue_max_selected_pct
            ),
            "selection_stress_unresolved_drawdown_rescue_min_leader_dd_pct": (
                args.selection_stress_unresolved_drawdown_rescue_min_leader_dd_pct
            ),
            "selection_stress_unresolved_drawdown_rescue_giveback_pct": (
                args.selection_stress_unresolved_drawdown_rescue_giveback_pct
            ),
            "selection_negative_train_distribution_rescue": bool(
                args.selection_negative_train_distribution_rescue
            ),
            "selection_negative_train_distribution_min_selected_return_pct": (
                args.selection_negative_train_distribution_min_selected_return_pct
            ),
            "selection_negative_train_distribution_max_selected_return_pct": (
                args.selection_negative_train_distribution_max_selected_return_pct
            ),
            "selection_negative_train_distribution_max_return_giveback_pct": float(
                args.selection_negative_train_distribution_max_return_giveback_pct
            ),
            "selection_high_cost_runner_rescue": bool(args.selection_high_cost_runner_rescue),
            "selection_high_cost_runner_min_selected_return_pct": (
                args.selection_high_cost_runner_min_selected_return_pct
            ),
            "selection_high_cost_runner_max_selected_return_pct": (
                args.selection_high_cost_runner_max_selected_return_pct
            ),
            "selection_high_cost_runner_max_return_giveback_pct": float(
                args.selection_high_cost_runner_max_return_giveback_pct
            ),
            "selection_deep_soft_overlay_rescue": bool(args.selection_deep_soft_overlay_rescue),
            "selection_deep_soft_overlay_min_selected_return_pct": (
                args.selection_deep_soft_overlay_min_selected_return_pct
            ),
            "selection_deep_soft_overlay_max_selected_return_pct": (
                args.selection_deep_soft_overlay_max_selected_return_pct
            ),
            "selection_deep_soft_overlay_max_return_giveback_pct": float(
                args.selection_deep_soft_overlay_max_return_giveback_pct
            ),
            "selection_deep_drawdown_reversal_rescue": bool(
                args.selection_deep_drawdown_reversal_rescue
            ),
            "selection_deep_drawdown_reversal_min_selected_return_pct": (
                args.selection_deep_drawdown_reversal_min_selected_return_pct
            ),
            "selection_deep_drawdown_reversal_max_selected_return_pct": (
                args.selection_deep_drawdown_reversal_max_selected_return_pct
            ),
            "selection_deep_drawdown_reversal_max_return_giveback_pct": float(
                args.selection_deep_drawdown_reversal_max_return_giveback_pct
            ),
            "selection_deep_drawdown_reversal_max_candidate_one_way_trim_per_add": (
                args.selection_deep_drawdown_reversal_max_candidate_one_way_trim_per_add
            ),
            "selection_deep_drawdown_reversal_max_one_way_trim_increase_per_add": (
                args.selection_deep_drawdown_reversal_max_one_way_trim_increase_per_add
            ),
            "selection_one_way_trim_ratio_threshold": float(args.selection_one_way_trim_ratio_threshold),
            "selection_one_way_trim_ratio_penalty": float(args.selection_one_way_trim_ratio_penalty),
            "selection_turnover_per_add_threshold": float(args.selection_turnover_per_add_threshold),
            "selection_turnover_per_add_penalty": float(args.selection_turnover_per_add_penalty),
            "selection_low_activity_coverage_threshold": float(
                args.selection_low_activity_coverage_threshold
            ),
            "selection_low_activity_penalty": float(args.selection_low_activity_penalty),
            "selection_soft_no_trade_per_1k_threshold": float(
                args.selection_soft_no_trade_per_1k_threshold
            ),
            "selection_soft_no_trade_per_1k_penalty": float(
                args.selection_soft_no_trade_per_1k_penalty
            ),
            "selection_role_concentration_threshold": float(
                args.selection_role_concentration_threshold
            ),
            "selection_role_concentration_min_add_events": int(
                args.selection_role_concentration_min_add_events
            ),
            "selection_role_concentration_penalty": float(
                args.selection_role_concentration_penalty
            ),
            "selection_base_dominance_threshold": float(args.selection_base_dominance_threshold),
            "selection_base_dominance_min_add_events": int(
                args.selection_base_dominance_min_add_events
            ),
            "selection_base_dominance_min_train_return_pct": (
                args.selection_base_dominance_min_train_return_pct
            ),
            "selection_base_dominance_max_train_return_pct": (
                args.selection_base_dominance_max_train_return_pct
            ),
            "selection_base_dominance_min_train_drawdown_pct": (
                args.selection_base_dominance_min_train_drawdown_pct
            ),
            "selection_base_dominance_max_train_drawdown_pct": (
                args.selection_base_dominance_max_train_drawdown_pct
            ),
            "selection_base_dominance_min_train_cost_drag_pct": (
                args.selection_base_dominance_min_train_cost_drag_pct
            ),
            "selection_base_dominance_max_train_cost_drag_pct": (
                args.selection_base_dominance_max_train_cost_drag_pct
            ),
            "selection_base_dominance_penalty": float(
                args.selection_base_dominance_penalty
            ),
            "selection_structural_flag_min_train_return_pct": float(
                args.selection_structural_flag_min_train_return_pct
            ),
            "selection_structural_flag_penalty": float(args.selection_structural_flag_penalty),
            "selection_high_train_flag_min_return_pct": float(
                args.selection_high_train_flag_min_return_pct
            ),
            "selection_high_train_flag_penalty": float(args.selection_high_train_flag_penalty),
            "selection_low_train_max_unit_min_return_pct": (
                args.selection_low_train_max_unit_min_return_pct
            ),
            "selection_low_train_max_unit_max_return_pct": (
                args.selection_low_train_max_unit_max_return_pct
            ),
            "selection_low_train_max_unit_threshold": float(args.selection_low_train_max_unit_threshold),
            "selection_low_train_max_unit_penalty": float(args.selection_low_train_max_unit_penalty),
            "selection_one_way_loss_fuse_bonus": float(args.selection_one_way_loss_fuse_bonus),
            "selection_low_unit_reversal_bonus": float(args.selection_low_unit_reversal_bonus),
            "selection_low_unit_reversal_max_units": float(
                args.selection_low_unit_reversal_max_units
            ),
            "selection_low_unit_reversal_min_switch_units": float(
                args.selection_low_unit_reversal_min_switch_units
            ),
            "selection_low_unit_reversal_min_train_return_pct": (
                args.selection_low_unit_reversal_min_train_return_pct
            ),
            "selection_low_unit_reversal_max_train_return_pct": (
                args.selection_low_unit_reversal_max_train_return_pct
            ),
            "selection_low_unit_reversal_min_train_drawdown_pct": (
                args.selection_low_unit_reversal_min_train_drawdown_pct
            ),
            "selection_low_unit_reversal_max_train_drawdown_pct": (
                args.selection_low_unit_reversal_max_train_drawdown_pct
            ),
            "selection_low_unit_reversal_min_one_way_trim_per_add": float(
                args.selection_low_unit_reversal_min_one_way_trim_per_add
            ),
            "selection_low_unit_reversal_max_one_way_trim_per_add": float(
                args.selection_low_unit_reversal_max_one_way_trim_per_add
            ),
            "selection_drawdown_reversal_bonus": float(args.selection_drawdown_reversal_bonus),
            "selection_drawdown_reversal_max_units": float(
                args.selection_drawdown_reversal_max_units
            ),
            "selection_drawdown_reversal_min_switch_units": float(
                args.selection_drawdown_reversal_min_switch_units
            ),
            "selection_drawdown_reversal_min_train_return_pct": (
                args.selection_drawdown_reversal_min_train_return_pct
            ),
            "selection_drawdown_reversal_max_train_return_pct": (
                args.selection_drawdown_reversal_max_train_return_pct
            ),
            "selection_drawdown_reversal_min_train_drawdown_pct": (
                args.selection_drawdown_reversal_min_train_drawdown_pct
            ),
            "selection_drawdown_reversal_max_train_drawdown_pct": (
                args.selection_drawdown_reversal_max_train_drawdown_pct
            ),
            "selection_drawdown_reversal_min_train_cost_drag_pct": (
                args.selection_drawdown_reversal_min_train_cost_drag_pct
            ),
            "selection_drawdown_reversal_max_train_cost_drag_pct": (
                args.selection_drawdown_reversal_max_train_cost_drag_pct
            ),
            "selection_drawdown_reversal_min_one_way_trim_per_add": float(
                args.selection_drawdown_reversal_min_one_way_trim_per_add
            ),
            "selection_drawdown_reversal_max_one_way_trim_per_add": float(
                args.selection_drawdown_reversal_max_one_way_trim_per_add
            ),
            "selection_drawdown_reversal_min_turnover_per_add": float(
                args.selection_drawdown_reversal_min_turnover_per_add
            ),
            "selection_drawdown_reversal_max_turnover_per_add": float(
                args.selection_drawdown_reversal_max_turnover_per_add
            ),
            "selection_short_hold_structural_bonus": float(
                args.selection_short_hold_structural_bonus
            ),
            "selection_short_hold_max_bars": int(args.selection_short_hold_max_bars),
            "selection_short_hold_min_train_return_pct": (
                args.selection_short_hold_min_train_return_pct
            ),
            "selection_short_hold_max_train_return_pct": (
                args.selection_short_hold_max_train_return_pct
            ),
            "selection_short_hold_min_train_drawdown_pct": (
                args.selection_short_hold_min_train_drawdown_pct
            ),
            "selection_short_hold_max_train_drawdown_pct": (
                args.selection_short_hold_max_train_drawdown_pct
            ),
            "selection_short_hold_min_max_units": float(args.selection_short_hold_min_max_units),
            "selection_short_hold_max_max_units": float(args.selection_short_hold_max_max_units),
            "selection_short_hold_min_one_way_trim_per_add": float(
                args.selection_short_hold_min_one_way_trim_per_add
            ),
            "selection_short_hold_max_one_way_trim_per_add": float(
                args.selection_short_hold_max_one_way_trim_per_add
            ),
            "selection_short_hold_min_turnover_per_add": float(
                args.selection_short_hold_min_turnover_per_add
            ),
            "selection_short_hold_max_turnover_per_add": float(
                args.selection_short_hold_max_turnover_per_add
            ),
            "selection_fast_defense_structural_penalty": float(
                args.selection_fast_defense_structural_penalty
            ),
            "selection_fast_defense_max_cooldown_bars": int(
                args.selection_fast_defense_max_cooldown_bars
            ),
            "selection_fast_defense_min_train_return_pct": float(
                args.selection_fast_defense_min_train_return_pct
            ),
            "selection_fast_defense_min_one_way_trim_per_add": float(
                args.selection_fast_defense_min_one_way_trim_per_add
            ),
            "selection_fast_defense_min_turnover_per_add": float(
                args.selection_fast_defense_min_turnover_per_add
            ),
            "selection_regime_dependency_threshold": float(
                args.selection_regime_dependency_threshold
            ),
            "selection_regime_dependency_min_train_return_pct": float(
                args.selection_regime_dependency_min_train_return_pct
            ),
            "selection_regime_dependency_penalty": float(
                args.selection_regime_dependency_penalty
            ),
            "selection_recent_efficiency_lookback": int(args.selection_recent_efficiency_lookback),
            "selection_recent_efficiency_min_samples": int(args.selection_recent_efficiency_min_samples),
            "selection_recent_efficiency_min_train_return_pct": float(
                args.selection_recent_efficiency_min_train_return_pct
            ),
            "selection_recent_efficiency_threshold": float(args.selection_recent_efficiency_threshold),
            "selection_recent_efficiency_penalty": float(args.selection_recent_efficiency_penalty),
            "test_top_train_candidates": int(args.test_top_train_candidates),
            "load_days": int(args.load_days),
            "fold_start_at": initial_fold_start.isoformat(),
            "fold_anchor_hour_utc": args.fold_anchor_hour_utc,
            "fold_anchor_minute_utc": (
                int(args.fold_anchor_minute_utc) if args.fold_anchor_hour_utc is not None else None
            ),
            "warm_fold_offset_selection_state": bool(args.warm_fold_offset_selection_state),
            "source_replay_fail_on_unresolved_material_drift": bool(
                args.source_replay_fail_on_unresolved_material_drift
            ),
        },
        "aggregate": _aggregate_folds(folds),
        "folds": folds,
    }
    source_replay_diagnostics = _source_replay_diagnostics(source_report, folds)
    source_replay_lineage_guard = _source_replay_lineage_guard(
        source_replay_diagnostics,
        fail_on_unresolved_material=bool(args.source_replay_fail_on_unresolved_material_drift),
    )
    report["source_replay_diagnostics"] = source_replay_diagnostics
    report["source_replay_lineage_guard"] = source_replay_lineage_guard
    report["provenance"] = _report_provenance(
        source_path=source_path,
        source_report=source_report,
        configs=configs,
        config_overrides=dict(report.get("config_overrides") or {}),
        folds=folds,
    )

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

    if source_replay_lineage_guard.get("failed"):
        raise SystemExit(str(source_replay_lineage_guard.get("message") or "Source replay guard failed."))

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
