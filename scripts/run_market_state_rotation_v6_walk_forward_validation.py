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


def _apply_near_miss_overlay(config: MarketStateConfig, args: argparse.Namespace) -> MarketStateConfig:
    updates: dict[str, Any] = {}
    suffix_parts: list[str] = []
    if args.near_miss_probe_units is not None:
        value = max(0.0, float(args.near_miss_probe_units))
        updates["near_miss_probe_units"] = min(value, config.max_possible_units)
        suffix_parts.append(f"wfNearMiss{value:g}")
    if args.near_miss_probe_min_score is not None:
        value = int(args.near_miss_probe_min_score)
        updates["near_miss_probe_min_score"] = value
        suffix_parts.append(f"wfNearMissScore{value}")
    if args.near_miss_probe_min_score_edge is not None:
        value = max(0, int(args.near_miss_probe_min_score_edge))
        updates["near_miss_probe_min_score_edge"] = value
        suffix_parts.append(f"wfNearMissEdge{value}")
    if args.near_miss_probe_min_reason_stack is not None:
        value = max(0, int(args.near_miss_probe_min_reason_stack))
        updates["near_miss_probe_min_reason_stack"] = value
        suffix_parts.append(f"wfNearMissStack{value}")
    if args.near_miss_probe_cooldown_bars is not None:
        value = max(0, int(args.near_miss_probe_cooldown_bars))
        updates["near_miss_probe_cooldown_bars"] = value
        suffix_parts.append(f"wfNearMissCool{value}")
    if args.near_miss_probe_max_extension_atr is not None:
        value = max(0.1, float(args.near_miss_probe_max_extension_atr))
        updates["near_miss_probe_max_extension_atr"] = value
        suffix_parts.append(f"wfNearMissExt{value:g}")
    if args.near_miss_probe_failure_guard_count is not None:
        value = max(0, int(args.near_miss_probe_failure_guard_count))
        updates["near_miss_probe_failure_guard_count"] = value
        suffix_parts.append(f"wfNearMissFail{value}")
    if args.near_miss_probe_failure_guard_window_bars is not None:
        value = max(1, int(args.near_miss_probe_failure_guard_window_bars))
        updates["near_miss_probe_failure_guard_window_bars"] = value
        suffix_parts.append(f"wfNearMissFailWin{value}")
    if args.near_miss_probe_failure_cooldown_bars is not None:
        value = max(0, int(args.near_miss_probe_failure_cooldown_bars))
        updates["near_miss_probe_failure_cooldown_bars"] = value
        suffix_parts.append(f"wfNearMissFailCool{value}")
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
) -> tuple[MarketStateConfig, list[str], list[str]]:
    overlays_applied: list[str] = []
    overlays_skipped: list[str] = []
    if bool(args.equity_circuit_breaker_after_selection):
        config = _apply_equity_circuit_overlay(config, args)
        overlays_applied.append("equity_circuit")
    if bool(args.equity_soft_circuit_after_selection):
        if _equity_soft_circuit_after_selection_allowed(train_result, args):
            config = _apply_equity_soft_circuit_overlay(config, args)
            overlays_applied.append("equity_soft_circuit")
        else:
            overlays_skipped.append("equity_soft_circuit")
    if bool(args.equity_soft_sizer_after_selection):
        if _equity_soft_sizer_after_selection_allowed(train_result, args):
            config = _apply_equity_soft_sizer_overlay(config, args)
            overlays_applied.append("equity_soft_sizer")
        else:
            overlays_skipped.append("equity_soft_sizer")
    if bool(args.equity_soft_sizer_alt_after_selection):
        if _equity_soft_sizer_after_selection_allowed(
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
    if bool(args.one_way_trim_full_exit_after_selection):
        config = _apply_full_exit_overlay(config, args)
        overlays_applied.append("one_way_trim_full_exit")
    if bool(args.one_way_reversal_after_selection):
        if _one_way_reversal_after_selection_allowed(train_result, args):
            config = _apply_one_way_reversal_after_selection_overlay(config, args)
            overlays_applied.append("one_way_reversal")
        else:
            overlays_skipped.append("one_way_reversal")
        if args.one_way_reversal_after_selection_weak_switch_units is not None:
            if _one_way_reversal_after_selection_weak_allowed(train_result, args):
                config = _apply_one_way_reversal_after_selection_overlay(
                    config,
                    args,
                    switch_units=args.one_way_reversal_after_selection_weak_switch_units,
                    suffix_label="wfOwRevWeak",
                )
                overlays_applied.append("one_way_reversal_weak")
            else:
                overlays_skipped.append("one_way_reversal_weak")
    if bool(args.one_way_impulse_after_selection):
        if _one_way_impulse_after_selection_allowed(train_result, args):
            config = _apply_one_way_impulse_after_selection_overlay(config, args)
            overlays_applied.append("one_way_impulse")
        else:
            overlays_skipped.append("one_way_impulse")
    if bool(args.one_way_impulse_alt_after_selection):
        if _one_way_impulse_after_selection_allowed(
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
        if _one_way_impulse_after_selection_allowed(
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
        if _one_way_impulse_after_selection_allowed(
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
    if bool(args.trend_idle_after_selection):
        if _trend_idle_after_selection_allowed(train_result, args):
            config = _apply_trend_idle_overlay(config, args)
            overlays_applied.append("trend_idle")
        else:
            overlays_skipped.append("trend_idle")
    if bool(args.near_miss_after_selection):
        if _near_miss_after_selection_allowed(train_result, args):
            config = _apply_near_miss_overlay(config, args)
            overlays_applied.append("near_miss")
        else:
            overlays_skipped.append("near_miss")
    if bool(args.near_miss_late_after_selection):
        if "near_miss" in overlays_applied:
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
    if bool(args.near_miss_high_after_selection):
        if "near_miss" in overlays_applied or "near_miss_late" in overlays_applied:
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
        if _base_reduce_after_selection_allowed(train_result, args):
            config = _apply_base_reduce_overlay(config, args)
            overlays_applied.append("base_reduce")
        else:
            overlays_skipped.append("base_reduce")
    if bool(args.fragile_regime_entry_after_selection):
        if _fragile_regime_entry_after_selection_allowed(train_result, args):
            config = _apply_fragile_regime_entry_overlay(config, args)
            overlays_applied.append("fragile_regime_entry")
        else:
            overlays_skipped.append("fragile_regime_entry")
    if bool(args.fragile_regime_entry_high_after_selection):
        if _train_state_after_selection_allowed(
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
        if _train_state_after_selection_allowed(
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
        if _fragile_regime_inventory_trim_after_selection_allowed(train_result, args):
            config = _apply_fragile_regime_inventory_trim_overlay(config, args)
            overlays_applied.append("fragile_regime_inventory_trim")
        else:
            overlays_skipped.append("fragile_regime_inventory_trim")
    if bool(args.risk_smoothing_after_selection):
        if _risk_smoothing_after_selection_allowed(train_result, args):
            config = _apply_risk_smoothing_overlay(config, args)
            overlays_applied.append("risk_smoothing")
        else:
            overlays_skipped.append("risk_smoothing")
    if bool(args.exposure_rebalance_after_selection):
        if _exposure_rebalance_after_selection_allowed(train_result, args):
            config = _apply_exposure_rebalance_overlay(config, args)
            overlays_applied.append("exposure_rebalance")
        else:
            overlays_skipped.append("exposure_rebalance")
    if bool(args.one_way_trim_context_late_after_selection):
        if _train_state_after_selection_allowed(
            train_result,
            args,
            prefix="one_way_trim_context_late_after_selection",
        ):
            config = _apply_context_quarantine_overlay(config, args)
            overlays_applied.append("one_way_trim_context_late")
        else:
            overlays_skipped.append("one_way_trim_context_late")
    if bool(args.one_way_trim_context_after_selection):
        if "one_way_trim_context_late" in overlays_applied:
            overlays_skipped.append("one_way_trim_context")
        elif bool(args.one_way_trim_context_after_selection_require_base_reduce) and (
            "base_reduce" not in overlays_applied
        ):
            overlays_skipped.append("one_way_trim_context")
        else:
            config = _apply_context_quarantine_overlay(config, args)
            overlays_applied.append("one_way_trim_context")
    if bool(args.one_way_loss_fuse_after_selection):
        if _one_way_loss_fuse_after_selection_allowed(train_result, args):
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
    structural_flag_min_train_return_pct: float = 0.0,
    structural_flag_penalty: float = 0.0,
    high_train_flag_min_return_pct: float = 0.0,
    high_train_flag_penalty: float = 0.0,
    low_train_max_unit_min_return_pct: float | None = None,
    low_train_max_unit_max_return_pct: float | None = None,
    low_train_max_unit_threshold: float = 0.0,
    low_train_max_unit_penalty: float = 0.0,
) -> float:
    diagnostics = dict(result.get("event_diagnostics") or {})
    flags = diagnostics.get("flags") or []
    ratios = dict(diagnostics.get("ratios") or {})
    mdd = float(result.get("max_drawdown_pct") or 100.0)
    cost_drag = float(result.get("estimated_cost_drag_pct") or 0.0)
    one_way_trim_ratio = float(ratios.get("one_way_forced_trim_per_add") or 0.0)
    turnover_per_add = float(ratios.get("turnover_events_per_add") or 0.0)
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
    return (
        base_score
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
        - structural_penalty
        - high_train_flag_penalty_total
        - low_train_max_unit_penalty_total
        - impulse_penalty
        - btc_rotation_penalty
    )


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
    event_counter: Counter[str] = Counter()
    flag_totals: dict[str, dict[str, Any]] = {}
    regime_totals: dict[str, dict[str, Any]] = {}
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
        train_selected_config = dict(dict(fold.get("selected_train_result") or {}).get("config") or {})
        selected_config = dict(result.get("config") or {}) or train_selected_config
        model_id = str(selected_config.get("model_id") or fold.get("selected_model_id") or "unknown")
        parts = model_id.split(":")
        selected_profile_counter[parts[2] if len(parts) > 2 else "unknown"] += 1
        selected_hold_counter[str(selected_config.get("max_hold_bars", "unknown"))] += 1
        selected_max_units_counter[str(selected_config.get("max_possible_units", "unknown"))] += 1
        diagnostics = dict(result.get("event_diagnostics") or {})
        event_counter.update({str(k): int(v) for k, v in dict(result.get("event_counts") or {}).items()})
        test_health_counter[str(diagnostics.get("health") or "unknown")] += 1
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
        "test_flag_performance": flag_performance,
        "test_event_counts": _counter_payload(event_counter),
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
        f"- Test flag performance: `{json.dumps(aggregate.get('test_flag_performance', {}), ensure_ascii=False)}`",
        f"- Test event counts: `{json.dumps(aggregate.get('test_event_counts', {}), ensure_ascii=False)}`",
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
        train_start = fold.get("train_start_at") or fold.get("train_start")
        train_end = fold.get("train_end_at") or fold.get("train_end")
        test_start = fold.get("test_start_at") or fold.get("test_start")
        test_end = fold.get("test_end_at") or fold.get("test_end")
        lines.append(
            f"| {fold.get('fold')} | {train_start} to {train_end} | "
            f"{test_start} to {test_end} | "
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

    fold_start = exec_bars_all[0].ts.astimezone(UTC)
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
                result["walk_forward_selection_score"] = round(
                    _selection_score(
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
                        structural_flag_min_train_return_pct=float(
                            args.selection_structural_flag_min_train_return_pct
                        ),
                        structural_flag_penalty=float(args.selection_structural_flag_penalty),
                        high_train_flag_min_return_pct=float(
                            args.selection_high_train_flag_min_return_pct
                        ),
                        high_train_flag_penalty=float(args.selection_high_train_flag_penalty),
                        low_train_max_unit_min_return_pct=(
                            args.selection_low_train_max_unit_min_return_pct
                        ),
                        low_train_max_unit_max_return_pct=(
                            args.selection_low_train_max_unit_max_return_pct
                        ),
                        low_train_max_unit_threshold=float(args.selection_low_train_max_unit_threshold),
                        low_train_max_unit_penalty=float(args.selection_low_train_max_unit_penalty),
                    ),
                    6,
                )
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
        selected_config, overlays_applied, overlays_skipped = _apply_after_selection_overlays(
            selected_config,
            selected_train,
            args,
        )
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
            candidate_config = MarketStateConfig(**train_candidate["config"])
            candidate_config, candidate_applied, candidate_skipped = _apply_after_selection_overlays(
                candidate_config,
                train_candidate,
                args,
            )
            candidate_test = test_result if rank == 1 else _run_config(
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
            "one_way_impulse_probe_units": args.one_way_impulse_probe_units,
            "one_way_impulse_min_one_way_score": args.one_way_impulse_min_one_way_score,
            "one_way_impulse_min_score_diff": args.one_way_impulse_min_score_diff,
            "one_way_impulse_cooldown_bars": args.one_way_impulse_cooldown_bars,
            "one_way_impulse_max_extension_atr": args.one_way_impulse_max_extension_atr,
            **_one_way_impulse_after_selection_override_payload(args, "one_way_impulse_after_selection"),
            **_one_way_impulse_after_selection_override_payload(args, "one_way_impulse_alt_after_selection"),
            **_one_way_impulse_after_selection_override_payload(args, "one_way_impulse_tail_after_selection"),
            **_one_way_impulse_after_selection_override_payload(args, "one_way_impulse_late_after_selection"),
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
            "selection_recent_efficiency_lookback": int(args.selection_recent_efficiency_lookback),
            "selection_recent_efficiency_min_samples": int(args.selection_recent_efficiency_min_samples),
            "selection_recent_efficiency_min_train_return_pct": float(
                args.selection_recent_efficiency_min_train_return_pct
            ),
            "selection_recent_efficiency_threshold": float(args.selection_recent_efficiency_threshold),
            "selection_recent_efficiency_penalty": float(args.selection_recent_efficiency_penalty),
            "test_top_train_candidates": int(args.test_top_train_candidates),
            "warm_fold_offset_selection_state": bool(args.warm_fold_offset_selection_state),
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
