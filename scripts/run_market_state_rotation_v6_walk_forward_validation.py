#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
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
    }


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
        "--warm-fold-offset-selection-state",
        action="store_true",
        help=(
            "When --fold-offset is used, still run skipped earlier folds internally so history-based "
            "selection penalties match a full walk-forward run. Skipped warmup folds are not written "
            "to the report."
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
    parser.add_argument(
        "--near-miss-after-selection",
        action="store_true",
        help=(
            "Select candidates without near-miss probes, then conditionally add the probe overlay "
            "to the selected OOS config."
        ),
    )
    parser.add_argument("--near-miss-after-selection-min-train-return-pct", type=float, default=None)
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
    if not updates:
        return config
    updates["model_id"] = config.model_id + ":" + ":".join(suffix_parts)
    return replace(config, **updates)


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
        updates["one_way_reversal_switch_units"] = min(value, config.max_possible_units)
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
            config = _apply_one_way_reversal_after_selection_overlay(config, args)
            overlays_applied.append("one_way_reversal")
        else:
            overlays_skipped.append("one_way_reversal")
        if args.one_way_reversal_after_selection_weak_switch_units is not None:
            if is_blocked("one_way_reversal_weak"):
                pass
            elif _one_way_reversal_after_selection_weak_allowed(train_result, args):
                config = _apply_one_way_reversal_after_selection_overlay(
                    config,
                    args,
                    switch_units=args.one_way_reversal_after_selection_weak_switch_units,
                    suffix_label="wfOwRevWeak",
                )
                overlays_applied.append("one_way_reversal_weak")
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
                config = _apply_one_way_reversal_after_selection_overlay(
                    config,
                    args,
                    switch_units=getattr(args, f"{arg_prefix}_switch_units"),
                    suffix_label=suffix_label,
                )
                overlays_applied.append(overlay_name)
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
            config = _apply_one_way_reversal_after_selection_overlay(
                config,
                args,
                switch_units=0.0,
                suffix_label="wfOwRevSuppress",
            )
            overlays_applied.append("one_way_reversal_suppress")
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
    if not configured:
        return list(overlays_applied)
    return [name for name in overlays_applied if name in configured]


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
        if str(key).startswith("no_trade_") and int(value or 0) > 0
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
    top_candidate_audit = dict(aggregate.get("top_train_candidate_audit") or {})
    top_candidate_overlay_audit = dict(
        aggregate.get("top_train_candidate_overlay_audit") or {}
    )
    regime_drift_diagnostics = dict(aggregate.get("regime_drift_diagnostics") or {})

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
            "- Regime drift diagnostics: "
            f"`avg_drift={regime_drift_diagnostics.get('avg_regime_share_drift', 0)}, "
            f"max_drift={regime_drift_diagnostics.get('max_regime_share_drift', 0)}, "
            f"high_drift={regime_drift_diagnostics.get('high_drift_count', 0)}, "
            f"high_dependency={regime_drift_diagnostics.get('high_dependency_count', 0)}`"
        ),
        "",
        "## After-Selection Confirmation",
        "",
    ]
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
    include_trend_idle_in_selection = not bool(args.trend_idle_after_selection)
    include_near_miss_in_selection = not bool(args.near_miss_after_selection)
    include_base_reduce_in_selection = not bool(args.base_entry_reduce_after_selection)
    include_context_quarantine_in_selection = not bool(args.one_way_trim_context_after_selection)
    include_loss_fuse_in_selection = not bool(args.one_way_loss_fuse_after_selection)
    include_fragile_regime_entry_in_selection = not bool(args.fragile_regime_entry_after_selection)
    include_fragile_regime_inventory_trim_in_selection = not bool(
        args.fragile_regime_inventory_trim_after_selection
    )

    def add_candidate_family(*, include_defensive_trim_cooldown: bool) -> None:
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
        )
        if bool(args.include_no_near_miss_probe_candidates) and include_near_miss_in_selection and near_miss_requested:
            near_miss_choices.insert(0, False)
        for include_equity_circuit in equity_choices:
            for include_btc_rotation in btc_rotation_choices:
                for include_impulse in impulse_choices:
                    for include_base_reduce in base_reduce_choices:
                        for include_loss_fuse in loss_fuse_choices:
                            for include_near_miss in near_miss_choices:
                                configs.extend(
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
                                    for config in source_configs
                                )

    if bool(args.include_no_defensive_trim_cooldown_candidates) and args.defensive_trim_cooldown_bars is not None:
        add_candidate_family(include_defensive_trim_cooldown=False)
    add_candidate_family(include_defensive_trim_cooldown=True)
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

    try:
        fold_start = _anchored_fold_start(
            exec_bars_all[0].ts,
            args.fold_anchor_hour_utc,
            args.fold_anchor_minute_utc,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    last_ts = exec_bars_all[-1].ts.astimezone(UTC)
    train_delta = timedelta(days=max(int(args.train_days), 1))
    test_delta = timedelta(days=max(int(args.test_days), 1))
    step_delta = timedelta(days=max(int(args.step_days), 1))
    folds: list[dict[str, Any]] = []
    selection_history_folds: list[dict[str, Any]] = []
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
        is_reported_fold = valid_fold_idx > fold_offset
        if not is_reported_fold and not bool(args.warm_fold_offset_selection_state):
            fold_start += step_delta
            continue

        train_results: list[dict[str, Any]] = []
        warm_note = " warming" if not is_reported_fold else ""
        print(f"walk-forward fold {valid_fold_idx}{warm_note} training {len(configs)} candidates", flush=True)
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
        "fold_anchor_hour_utc": args.fold_anchor_hour_utc,
        "fold_anchor_minute_utc": (
            int(args.fold_anchor_minute_utc) if args.fold_anchor_hour_utc is not None else None
        ),
        "candidate_count": len(configs),
        "cost_model": {
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": float(args.slippage_bps_per_side),
            "funding_bps_per_8h": float(args.funding_bps_per_8h),
            "borrow_bps_per_day": float(args.borrow_bps_per_day),
            "carry_rate_per_bar": carry_rate_per_bar,
        },
        "config_overrides": {
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
            "fold_anchor_hour_utc": args.fold_anchor_hour_utc,
            "fold_anchor_minute_utc": (
                int(args.fold_anchor_minute_utc) if args.fold_anchor_hour_utc is not None else None
            ),
            "warm_fold_offset_selection_state": bool(args.warm_fold_offset_selection_state),
        },
        "aggregate": _aggregate_folds(folds),
        "folds": folds,
    }
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
