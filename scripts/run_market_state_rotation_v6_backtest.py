#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text
from scripts.run_btc_flip_rotation_search import (
    _INTERVAL_MS,
    _csv,
    _load_bars,
    _year_fraction,
    Bar,
    FeatureSet,
)
from scripts.run_scenario_repair_rotation_backtest import (
    PositionBook,
    RemovedLot,
    _cloud_bands,
    _map_closed_indices,
    _round_levels,
    _slice_last_days,
)


@dataclass(frozen=True, slots=True)
class MarketStateConfig:
    model_id: str
    exec_interval: str
    htf_fast: int
    htf_slow: int
    htf_band_atr: float
    exec_fast: int
    exec_slow: int
    zone_lookback: int
    entry_score: int
    battle_score: int
    opposite_score: int
    max_possible_units: float
    base_max_units: float
    probe_units: float
    base_add_units: float
    battle_units: float
    chase_units: float
    max_account_exposure: float
    exchange_leverage: float
    maintenance_margin_pct: float
    reaction_usd: float
    reaction_atr: float
    base_spacing_atr: float
    battle_trigger_usd: float
    battle_trigger_atr: float
    repair_cut: float
    repair_stop: float
    max_repair_eff_for_add: float
    min_capacity_ratio: float
    bad_rr_atr: float
    one_way_threshold: float
    one_way_window: int
    min_reason_stack: int
    flat_score_edge: int
    battle_primary_score: int
    battle_primary_dist_atr: float
    zone_retire_bars: int
    reaction_trim_trigger: float
    reaction_avg_band: float
    skip_weak_long_round_reclaim: bool
    blocked_kst_entry_hours: tuple[int, ...]
    against_trend_size_mult: float
    one_way_against_size_mult: float
    switch_repair_eff: float
    switch_score_edge: int
    base_primary_score: int
    base_add_score: int
    base_requires_major_confluence: bool
    chase_min_score: int
    chase_min_reason_stack: int
    chase_min_breakout_atr: float
    chase_max_breakout_atr: float
    chase_max_extension_atr: float
    chase_min_one_way_score: float
    chase_take_profit_reaction: float
    chase_stop_reaction: float
    chase_max_bars: int
    volume_layer_enabled: bool
    volume_lookback: int
    volume_confirm_mult: float
    volume_absorption_mult: float
    quiet_volume_mult: float
    probe_take_profit_reaction: float
    probe_stop_reaction: float
    probe_max_bars: int
    probe_reentry_cooldown_bars: int
    one_way_trim_min_adverse_reaction: float
    one_way_trim_cooldown_bars: int
    defensive_trim_cooldown_bars: int
    cooldown_after_loss_bars: int
    max_failed_rescues_before_reduce_only: int
    max_battle_bars: int
    max_stuck_bars: int
    max_hold_bars: int
    min_liquidation_buffer_pct: float
    trend_core_units: float
    strict_scenario_entry: bool
    switch_enabled: bool
    reaction_trim_size_mult: float = 1.0
    one_way_trim_size_mult: float = 1.0
    hard_time_exit_fraction: float = 1.0
    hard_time_exit_cooldown_bars: int = 0
    reaction_trim_trend_hold_trigger_mult: float = 1.0
    hard_time_exit_trend_defer_bars: int = 0
    hard_time_exit_trend_defer_min_favorable_reaction: float = 0.0
    hard_time_loss_defer_bars: int = 0
    hard_time_loss_defer_min_loss_usd: float = 0.0
    hard_time_loss_defer_context_fragments: tuple[str, ...] = ()
    trend_hold_min_trend_strength: float = 0.35
    trend_hold_min_one_way_score: float = 0.0
    one_way_trim_retire_same_zone: bool = False
    one_way_trim_same_side_cooldown_bars: int = 0
    one_way_trim_cluster_guard_count: int = 0
    one_way_trim_cluster_window_bars: int = 288
    one_way_trim_cluster_cooldown_bars: int = 288
    one_way_trim_context_guard_count: int = 0
    one_way_trim_context_window_bars: int = 288
    one_way_trim_context_cooldown_bars: int = 288
    one_way_trim_context_full_exit: bool = False
    one_way_loss_fuse_min_adverse_reaction: float = 0.0
    one_way_loss_fuse_cooldown_bars: int = 0
    one_way_loss_fuse_size_mult: float = 1.0
    one_way_trim_full_exit_min_one_way_score: float = 0.0
    one_way_trim_full_exit_min_score_diff: int = 0
    trend_idle_probe_units: float = 0.0
    trend_idle_min_score: int = 4
    trend_idle_min_reason_stack: int = 2
    trend_idle_cooldown_bars: int = 96
    trend_idle_max_extension_atr: float = 2.0
    near_miss_probe_units: float = 0.0
    near_miss_probe_min_score: int = 5
    near_miss_probe_min_score_edge: int = 1
    near_miss_probe_min_reason_stack: int = 1
    near_miss_probe_cooldown_bars: int = 72
    near_miss_probe_max_extension_atr: float = 1.75
    near_miss_probe_failure_guard_count: int = 0
    near_miss_probe_failure_guard_window_bars: int = 1440
    near_miss_probe_failure_cooldown_bars: int = 0
    near_miss_probe_allowed_soft_reasons: tuple[str, ...] = ()
    near_miss_probe_allowed_alignments: tuple[str, ...] = ()
    near_miss_probe_allowed_execution_contexts: tuple[str, ...] = ()
    near_miss_probe_allowed_regimes: tuple[str, ...] = ()
    equity_circuit_breaker_drawdown_pct: float = 0.0
    equity_circuit_breaker_pause_bars: int = 0
    equity_circuit_rearm_drawdown_pct: float = 0.0
    equity_soft_circuit_drawdown_pct: float = 0.0
    equity_soft_circuit_cooldown_bars: int = 0
    equity_soft_circuit_size_mult: float = 1.0
    equity_soft_circuit_force_flat: bool = False
    equity_soft_circuit_inventory_trim_fraction: float = 0.0
    equity_soft_circuit_prearm_bars: int = 0
    equity_soft_circuit_min_bars_after_add: int = 0
    equity_soft_circuit_recovery_probe_units: float = 0.0
    equity_soft_circuit_recovery_min_one_way_score: float = 3.5
    equity_soft_circuit_recovery_min_score_diff: int = 5
    equity_soft_circuit_recovery_max_extension_atr: float = 2.0
    equity_soft_circuit_recovery_failure_guard_count: int = 0
    equity_soft_circuit_recovery_failure_guard_window_bars: int = 1440
    equity_soft_circuit_recovery_failure_cooldown_bars: int = 0
    one_way_reversal_switch_units: float = 0.0
    one_way_reversal_min_score_edge: int = 2
    one_way_reversal_cooldown_bars: int = 24
    one_way_reversal_allow_scenario_override: bool = False
    one_way_reversal_allow_score_override: bool = False
    one_way_impulse_probe_units: float = 0.0
    one_way_impulse_min_one_way_score: float = 2.35
    one_way_impulse_min_score_diff: int = 3
    one_way_impulse_cooldown_bars: int = 48
    one_way_impulse_max_extension_atr: float = 2.75
    scenario_flip_units: float = 0.0
    scenario_flip_min_score_edge: int = 1
    scenario_flip_min_adverse_reaction: float = 0.45
    scenario_flip_min_one_way_score: float = 1.85
    scenario_flip_cooldown_bars: int = 24
    scenario_flip_max_extension_atr: float = 2.75
    winner_pyramid_units: float = 0.0
    winner_pyramid_min_profit_reaction: float = 0.55
    winner_pyramid_min_score: int = 6
    winner_pyramid_min_reason_stack: int = 2
    winner_pyramid_cooldown_bars: int = 24
    winner_pyramid_max_units: float = 0.0
    winner_pyramid_min_extension_atr: float = 0.0
    winner_pyramid_max_extension_atr: float = 2.75
    winner_pyramid_block_risk_off: bool = False
    winner_pyramid_block_one_way_chase: bool = False
    base_entry_max_extension_atr: float = 0.0
    base_entry_max_extension_side: str = "both"
    base_entry_reduce_extension_atr: float = 0.0
    base_entry_reduce_size_mult: float = 1.0
    base_entry_reduce_promote_reaction: float = 0.0
    base_entry_reduce_max_trend_strength: float = 0.0
    base_entry_reduce_min_trend_strength: float = 0.0
    base_entry_reduce_side: str = "both"
    base_context_reduce_size_mult: float = 1.0
    base_context_reduce_patterns: tuple[str, ...] = ()
    fragile_regime_entry_size_mult: float = 1.0
    fragile_regime_entry_regimes: tuple[str, ...] = ()
    fragile_regime_inventory_trim_fraction: float = 0.0
    fragile_regime_inventory_trim_regimes: tuple[str, ...] = ()
    event_risk_base_reduce_size_mult: float = 1.0
    event_risk_base_reduce_min_extension_atr: float = 0.0
    event_risk_base_reduce_max_extension_atr: float = 0.0
    event_risk_base_reduce_side: str = "both"
    event_risk_base_reduce_contexts: tuple[str, ...] = ()
    regime_router_enabled: bool = False
    router_trend_reaction_size_mult: float = 1.0
    router_one_way_chase_size_mult: float = 0.75
    router_one_way_counter_size_mult: float = 0.0
    router_range_probe_size_mult: float = 0.25
    router_range_base_size_mult: float = 0.0
    router_exhaustion_reversal_size_mult: float = 0.35
    router_exhaustion_min_score_edge: int = 2
    router_exhaustion_min_extension_atr: float = 1.5
    router_risk_off_size_mult: float = 0.0
    router_transition_trim_fraction: float = 0.0
    router_transition_trim_modes: tuple[str, ...] = ()
    router_transition_trim_against_only: bool = True
    router_transition_trim_cooldown_bars: int = 0


@dataclass(frozen=True, slots=True)
class MarketState:
    bias: int
    long_score: int
    short_score: int
    trend_strength: float
    one_way_side: int
    one_way_score: float
    bad_rr: bool
    long_dist_atr: float
    short_dist_atr: float
    regime: str
    score_diff: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ZonePlan:
    side: int
    mode: str
    stage: str
    score: int
    long_score: int
    short_score: int
    long_reason_stack: int
    short_reason_stack: int
    long_reasons: tuple[str, ...]
    short_reasons: tuple[str, ...]
    long_zone_key: str
    short_zone_key: str
    active_zone_key: str
    no_trade_reasons: tuple[str, ...]
    expected_reaction_usd: float
    nearest_long_dist: float
    nearest_short_dist: float
    chase_breakout_atr: float
    chase_extension_atr: float
    execution_context: str


@dataclass(slots=True)
class ZoneMemory:
    state: str
    touched_idx: int
    reacted_idx: int | None = None
    invalidated_idx: int | None = None
    touch_count: int = 0


class RotationMemory:
    def __init__(self) -> None:
        self.zones: dict[str, ZoneMemory] = {}
        self.failed_rescue_count = 0
        self.cooldown_until_idx = -1
        self.cooldown_side = 0
        self.last_one_way_trim_idx = -10**9
        self.one_way_trim_indices: list[int] = []
        self.one_way_trim_cluster_cooldown_until_idx = -1
        self.one_way_trim_context_indices: dict[str, list[int]] = {}
        self.one_way_trim_context_cooldown_until_idx: dict[str, int] = {}
        self.one_way_loss_fuse_until_idx = -1
        self.last_one_way_reversal_switch_idx = -10**9
        self.last_one_way_impulse_probe_idx = -10**9
        self.last_trend_idle_probe_idx = -10**9
        self.last_near_miss_probe_idx = -10**9
        self.near_miss_probe_failure_indices: list[int] = []
        self.near_miss_probe_failure_cooldown_until_idx = -1
        self.equity_soft_circuit_recovery_failure_indices: list[int] = []
        self.equity_soft_circuit_recovery_failure_cooldown_until_idx = -1
        self.last_scenario_flip_idx = -10**9
        self.last_winner_pyramid_idx = -10**9
        self.last_defensive_trim_idx = -10**9
        self.last_hard_time_exit_idx = -10**9
        self.last_router_transition_trim_idx = -10**9

    def state(self, key: str, idx: int, retire_bars: int) -> str:
        if not key:
            return "none"
        item = self.zones.get(key)
        if item is None:
            return "pending"
        if item.state in {"reacted", "invalidated", "retired"} and idx - item.touched_idx <= retire_bars:
            return "retired"
        if idx - item.touched_idx > retire_bars:
            return "pending"
        return item.state

    def touch(self, key: str, idx: int) -> None:
        if not key:
            return
        item = self.zones.get(key)
        if item is None:
            self.zones[key] = ZoneMemory(state="touched", touched_idx=idx, touch_count=1)
            return
        item.state = "touched"
        item.touched_idx = idx
        item.touch_count += 1

    def react(self, key: str, idx: int) -> None:
        if not key:
            return
        item = self.zones.get(key)
        if item is None:
            self.zones[key] = ZoneMemory(state="reacted", touched_idx=idx, reacted_idx=idx, touch_count=1)
            return
        item.state = "reacted"
        item.reacted_idx = idx

    def invalidate(self, key: str, idx: int) -> None:
        if not key:
            return
        item = self.zones.get(key)
        if item is None:
            self.zones[key] = ZoneMemory(state="invalidated", touched_idx=idx, invalidated_idx=idx, touch_count=1)
            return
        item.state = "invalidated"
        item.invalidated_idx = idx

    def cooldown(self, side: int, idx: int, bars: int) -> None:
        if side == 0 or bars <= 0:
            return
        self.cooldown_side = side
        self.cooldown_until_idx = max(self.cooldown_until_idx, idx + bars)

    def in_cooldown(self, side: int, idx: int) -> bool:
        return side != 0 and self.cooldown_side == side and idx <= self.cooldown_until_idx

    def record_one_way_trim(self, idx: int, *, window_bars: int, guard_count: int, cooldown_bars: int) -> None:
        if guard_count <= 0 or cooldown_bars <= 0:
            return
        window = max(int(window_bars), 1)
        self.one_way_trim_indices = [
            trim_idx for trim_idx in self.one_way_trim_indices if idx - trim_idx <= window
        ]
        self.one_way_trim_indices.append(idx)
        if len(self.one_way_trim_indices) >= int(guard_count):
            self.one_way_trim_cluster_cooldown_until_idx = max(
                self.one_way_trim_cluster_cooldown_until_idx,
                idx + int(cooldown_bars),
            )

    def in_one_way_trim_cluster_cooldown(self, idx: int) -> bool:
        return idx <= self.one_way_trim_cluster_cooldown_until_idx

    def record_one_way_trim_context(
        self,
        context: str,
        idx: int,
        *,
        window_bars: int,
        guard_count: int,
        cooldown_bars: int,
    ) -> None:
        key = _context_quarantine_key(context)
        if not key or guard_count <= 0 or cooldown_bars <= 0:
            return
        window = max(int(window_bars), 1)
        indices = [
            trim_idx
            for trim_idx in self.one_way_trim_context_indices.get(key, [])
            if idx - trim_idx <= window
        ]
        indices.append(idx)
        self.one_way_trim_context_indices[key] = indices
        if len(indices) >= int(guard_count):
            self.one_way_trim_context_cooldown_until_idx[key] = max(
                self.one_way_trim_context_cooldown_until_idx.get(key, -1),
                idx + int(cooldown_bars),
            )

    def in_one_way_trim_context_cooldown(self, context: str, idx: int) -> bool:
        key = _context_quarantine_key(context)
        return bool(key) and idx <= self.one_way_trim_context_cooldown_until_idx.get(key, -1)

    def trigger_one_way_loss_fuse(self, idx: int, *, cooldown_bars: int) -> None:
        if cooldown_bars <= 0:
            return
        self.one_way_loss_fuse_until_idx = max(
            self.one_way_loss_fuse_until_idx,
            idx + int(cooldown_bars),
        )

    def in_one_way_loss_fuse(self, idx: int) -> bool:
        return idx <= self.one_way_loss_fuse_until_idx

    def record_near_miss_probe_failure(
        self,
        idx: int,
        *,
        guard_count: int,
        window_bars: int,
        cooldown_bars: int,
    ) -> bool:
        if guard_count <= 0 or cooldown_bars <= 0:
            return False
        cutoff = idx - max(1, int(window_bars))
        self.near_miss_probe_failure_indices = [
            item for item in self.near_miss_probe_failure_indices if item >= cutoff
        ]
        self.near_miss_probe_failure_indices.append(idx)
        if len(self.near_miss_probe_failure_indices) < int(guard_count):
            return False
        self.near_miss_probe_failure_cooldown_until_idx = max(
            self.near_miss_probe_failure_cooldown_until_idx,
            idx + int(cooldown_bars),
        )
        self.near_miss_probe_failure_indices = []
        return True

    def in_near_miss_probe_failure_cooldown(self, idx: int) -> bool:
        return idx <= self.near_miss_probe_failure_cooldown_until_idx

    def record_equity_soft_circuit_recovery_failure(
        self,
        idx: int,
        *,
        guard_count: int,
        window_bars: int,
        cooldown_bars: int,
    ) -> bool:
        if guard_count <= 0 or cooldown_bars <= 0:
            return False
        cutoff = idx - max(1, int(window_bars))
        self.equity_soft_circuit_recovery_failure_indices = [
            item for item in self.equity_soft_circuit_recovery_failure_indices if item >= cutoff
        ]
        self.equity_soft_circuit_recovery_failure_indices.append(idx)
        if len(self.equity_soft_circuit_recovery_failure_indices) < int(guard_count):
            return False
        self.equity_soft_circuit_recovery_failure_cooldown_until_idx = max(
            self.equity_soft_circuit_recovery_failure_cooldown_until_idx,
            idx + int(cooldown_bars),
        )
        self.equity_soft_circuit_recovery_failure_indices = []
        return True

    def in_equity_soft_circuit_recovery_failure_cooldown(self, idx: int) -> bool:
        return idx <= self.equity_soft_circuit_recovery_failure_cooldown_until_idx


CONTEXT_REACTION_TARGET_USD = 370.0
CONTEXTUAL_SHORT_BASE_BLOCK_KST_HOURS = (5, 19, 23)
ONE_WAY_LONG_TRIM_FRACTION = 0.50
ONE_WAY_REPAIR_TRIM_FRACTION = 0.65


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Market-data-only Nanyotti/Wonyotti-style v6 detailed rotation proxy. Telegram material is "
            "used only as design guidance, never as a trading signal."
        )
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--load-days", type=int, default=1825)
    parser.add_argument("--exec-interval", default="5m")
    parser.add_argument("--scenario-intervals", default="1h,4h")
    parser.add_argument("--exchange-leverage", type=float, default=10.0)
    parser.add_argument("--max-account-exposures", default="1,2,3,5,10,20,30,50")
    parser.add_argument("--max-possible-units", default="10")
    parser.add_argument("--battle-units", default="3,5")
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument(
        "--funding-bps-per-8h",
        type=float,
        default=0.0,
        help="Conservative absolute funding drag per 8 hours, charged on notional exposure.",
    )
    parser.add_argument(
        "--borrow-bps-per-day",
        type=float,
        default=0.0,
        help="Additional conservative daily carry drag charged on notional exposure.",
    )
    parser.add_argument("--maintenance-margin-pct", type=float, default=0.5)
    parser.add_argument("--min-periods", type=int, default=5000)
    parser.add_argument("--model-offset", type=int, default=0)
    parser.add_argument("--max-models", type=int, default=160)
    parser.add_argument("--probe-units", default="0,0.1,0.25")
    parser.add_argument("--volume-layer", action="store_true")
    parser.add_argument("--one-way-trim-min-adverse-reaction", type=float, default=0.0)
    parser.add_argument("--one-way-trim-cooldown-bars", type=int, default=6)
    parser.add_argument(
        "--one-way-trim-size-mult",
        type=float,
        default=1.0,
        help="Throttle one-way forced-trim cut size without disabling the forced-trim rule.",
    )
    parser.add_argument(
        "--hard-time-exit-fraction",
        type=float,
        default=1.0,
        help="Fraction of remaining inventory to cut on max-hold time exit; 1.0 keeps legacy full exit.",
    )
    parser.add_argument(
        "--hard-time-exit-cooldown-bars",
        type=int,
        default=0,
        help="Cooldown between partial hard time exits when --hard-time-exit-fraction is below 1.0.",
    )
    parser.add_argument(
        "--hard-time-exit-trend-defer-bars",
        type=int,
        default=0,
        help="Allow hard time exits to defer for this many bars while trend context and profit buffer hold.",
    )
    parser.add_argument(
        "--hard-time-exit-trend-defer-min-favorable-reaction",
        type=float,
        default=0.0,
        help="Minimum favorable reaction buffer required before a hard time exit can be trend-deferred.",
    )
    parser.add_argument(
        "--trend-hold-min-trend-strength",
        type=float,
        default=0.35,
        help="Minimum aligned trend_strength used by trend-hold exit deferral and reaction trim delay.",
    )
    parser.add_argument(
        "--trend-hold-min-one-way-score",
        type=float,
        default=0.0,
        help="Minimum aligned one_way_score used by trend-hold exit deferral and reaction trim delay.",
    )
    parser.add_argument("--one-way-trim-retire-same-zone", action="store_true")
    parser.add_argument("--one-way-trim-same-side-cooldown-bars", type=int, default=0)
    parser.add_argument("--one-way-trim-cluster-guard-count", type=int, default=0)
    parser.add_argument("--one-way-trim-cluster-window-bars", type=int, default=288)
    parser.add_argument("--one-way-trim-cluster-cooldown-bars", type=int, default=288)
    parser.add_argument("--one-way-trim-context-guard-count", type=int, default=0)
    parser.add_argument("--one-way-trim-context-window-bars", type=int, default=288)
    parser.add_argument("--one-way-trim-context-cooldown-bars", type=int, default=288)
    parser.add_argument("--one-way-trim-context-full-exit", action="store_true")
    parser.add_argument(
        "--one-way-loss-fuse-min-adverse-reaction",
        type=float,
        default=0.0,
        help=(
            "Trigger a temporary base-entry size reduction after a one-way forced trim loses at least "
            "this reaction multiple."
        ),
    )
    parser.add_argument("--one-way-loss-fuse-cooldown-bars", type=int, default=0)
    parser.add_argument("--one-way-loss-fuse-size-mult", type=float, default=1.0)
    parser.add_argument("--one-way-trim-full-exit-min-one-way-score", type=float, default=0.0)
    parser.add_argument("--one-way-trim-full-exit-min-score-diff", type=int, default=0)
    parser.add_argument("--trend-idle-probe-units", type=float, default=0.0)
    parser.add_argument("--trend-idle-min-score", type=int, default=4)
    parser.add_argument("--trend-idle-min-reason-stack", type=int, default=2)
    parser.add_argument("--trend-idle-cooldown-bars", type=int, default=96)
    parser.add_argument("--trend-idle-max-extension-atr", type=float, default=2.0)
    parser.add_argument("--near-miss-probe-units", type=float, default=0.0)
    parser.add_argument("--near-miss-probe-min-score", type=int, default=5)
    parser.add_argument("--near-miss-probe-min-score-edge", type=int, default=1)
    parser.add_argument("--near-miss-probe-min-reason-stack", type=int, default=1)
    parser.add_argument("--near-miss-probe-cooldown-bars", type=int, default=72)
    parser.add_argument("--near-miss-probe-max-extension-atr", type=float, default=1.75)
    parser.add_argument("--near-miss-probe-failure-guard-count", type=int, default=0)
    parser.add_argument("--near-miss-probe-failure-guard-window-bars", type=int, default=1440)
    parser.add_argument("--near-miss-probe-failure-cooldown-bars", type=int, default=0)
    parser.add_argument("--equity-circuit-breaker-drawdown-pct", type=float, default=0.0)
    parser.add_argument("--equity-circuit-breaker-pause-bars", type=int, default=0)
    parser.add_argument(
        "--equity-circuit-rearm-drawdown-pct",
        type=float,
        default=0.0,
        help=(
            "Optional drawdown threshold that re-arms a hard equity circuit after it has fired. "
            "When set, repeated flat-period re-triggers are blocked until drawdown recovers to this level."
        ),
    )
    parser.add_argument("--equity-soft-circuit-drawdown-pct", type=float, default=0.0)
    parser.add_argument("--equity-soft-circuit-cooldown-bars", type=int, default=0)
    parser.add_argument("--equity-soft-circuit-size-mult", type=float, default=1.0)
    parser.add_argument("--equity-soft-circuit-force-flat", action="store_true")
    parser.add_argument(
        "--equity-soft-circuit-inventory-trim-fraction",
        type=float,
        default=0.0,
        help=(
            "When a soft equity circuit triggers without force-flat, trim this fraction of the "
            "current inventory at the next bar open while the entry sizer is cooled down."
        ),
    )
    parser.add_argument(
        "--equity-soft-circuit-prearm-bars",
        type=int,
        default=0,
        help=(
            "Start the backtest with the soft-circuit size multiplier already active for this many "
            "bars. This is useful when a walk-forward fold qualifies for soft-circuit protection "
            "before the OOS window starts."
        ),
    )
    parser.add_argument(
        "--equity-soft-circuit-min-bars-after-add",
        type=int,
        default=0,
        help="Minimum bars after a fresh add before the soft equity circuit can trigger.",
    )
    parser.add_argument("--equity-soft-circuit-recovery-probe-units", type=float, default=0.0)
    parser.add_argument("--equity-soft-circuit-recovery-min-one-way-score", type=float, default=3.5)
    parser.add_argument("--equity-soft-circuit-recovery-min-score-diff", type=int, default=5)
    parser.add_argument("--equity-soft-circuit-recovery-max-extension-atr", type=float, default=2.0)
    parser.add_argument(
        "--equity-soft-circuit-recovery-failure-guard-count",
        type=int,
        default=0,
        help="Trigger a soft-circuit recovery probe cooldown after this many failed recovery probes.",
    )
    parser.add_argument(
        "--equity-soft-circuit-recovery-failure-guard-window-bars",
        type=int,
        default=1440,
        help="Lookback window for counting failed soft-circuit recovery probes.",
    )
    parser.add_argument(
        "--equity-soft-circuit-recovery-failure-cooldown-bars",
        type=int,
        default=0,
        help="Cooldown bars applied after the soft-circuit recovery failure guard triggers.",
    )
    parser.add_argument("--one-way-reversal-switch-units", type=float, default=0.0)
    parser.add_argument("--one-way-reversal-min-score-edge", type=int, default=2)
    parser.add_argument("--one-way-reversal-cooldown-bars", type=int, default=24)
    parser.add_argument("--one-way-reversal-allow-scenario-override", action="store_true")
    parser.add_argument("--one-way-reversal-allow-score-override", action="store_true")
    parser.add_argument("--one-way-impulse-probe-units", type=float, default=0.0)
    parser.add_argument("--one-way-impulse-min-one-way-score", type=float, default=2.35)
    parser.add_argument("--one-way-impulse-min-score-diff", type=int, default=3)
    parser.add_argument("--one-way-impulse-cooldown-bars", type=int, default=48)
    parser.add_argument("--one-way-impulse-max-extension-atr", type=float, default=2.75)
    parser.add_argument("--scenario-flip-units", type=float, default=0.0)
    parser.add_argument("--scenario-flip-min-score-edge", type=int, default=1)
    parser.add_argument("--scenario-flip-min-adverse-reaction", type=float, default=0.45)
    parser.add_argument("--scenario-flip-min-one-way-score", type=float, default=1.85)
    parser.add_argument("--scenario-flip-cooldown-bars", type=int, default=24)
    parser.add_argument("--scenario-flip-max-extension-atr", type=float, default=2.75)
    parser.add_argument("--winner-pyramid-units", type=float, default=0.0)
    parser.add_argument("--winner-pyramid-min-profit-reaction", type=float, default=0.55)
    parser.add_argument("--winner-pyramid-min-score", type=int, default=6)
    parser.add_argument("--winner-pyramid-min-reason-stack", type=int, default=2)
    parser.add_argument("--winner-pyramid-cooldown-bars", type=int, default=24)
    parser.add_argument("--winner-pyramid-max-units", type=float, default=0.0)
    parser.add_argument("--winner-pyramid-min-extension-atr", type=float, default=0.0)
    parser.add_argument("--winner-pyramid-max-extension-atr", type=float, default=2.75)
    parser.add_argument(
        "--winner-pyramid-block-risk-off",
        action="store_true",
        help="Block winner-refill scale-ins when the regime router is in risk-off mode.",
    )
    parser.add_argument(
        "--winner-pyramid-block-one-way-chase",
        action="store_true",
        help="Block winner-refill scale-ins when the regime router is in one-way chase mode.",
    )
    parser.add_argument(
        "--base-entry-max-extension-atr",
        type=float,
        default=0.0,
        help="Optional cap for with-trend base entries that are already extended from the execution EMA.",
    )
    parser.add_argument(
        "--base-entry-max-extension-side",
        choices=("both", "long", "short"),
        default="both",
        help="Side filter for --base-entry-max-extension-atr.",
    )
    parser.add_argument(
        "--base-entry-reduce-extension-atr",
        type=float,
        default=0.0,
        help="Optional extension threshold for shrinking, rather than blocking, with-trend base entries.",
    )
    parser.add_argument(
        "--base-entry-reduce-size-mult",
        type=float,
        default=1.0,
        help="Size multiplier for with-trend base entries beyond --base-entry-reduce-extension-atr.",
    )
    parser.add_argument(
        "--base-entry-reduce-promote-reaction",
        type=float,
        default=0.0,
        help="If late base entries are reduced, add the withheld size only after this favorable reaction multiple.",
    )
    parser.add_argument(
        "--base-entry-reduce-max-trend-strength",
        type=float,
        default=0.0,
        help="Only shrink late with-trend base entries when HTF trend strength is at or below this value.",
    )
    parser.add_argument(
        "--base-entry-reduce-min-trend-strength",
        type=float,
        default=0.0,
        help="Only shrink late with-trend base entries when HTF trend strength is at or above this value.",
    )
    parser.add_argument(
        "--base-entry-reduce-side",
        choices=("both", "long", "short"),
        default="both",
        help="Side filter for late with-trend base-entry size reduction.",
    )
    parser.add_argument(
        "--base-context-reduce-size-mult",
        type=float,
        default=1.0,
        help="Size multiplier for exact base-context pattern matches.",
    )
    parser.add_argument(
        "--base-context-reduce-patterns",
        default="",
        help=(
            "Comma-separated base context patterns to shrink. Use seven pipe-separated tokens "
            "role|side|alignment|regime|execution_context|ext_bucket|break_bucket; '*' is a wildcard."
        ),
    )
    parser.add_argument(
        "--fragile-regime-entry-size-mult",
        type=float,
        default=1.0,
        help="Optional entry size multiplier in selected fragile regimes.",
    )
    parser.add_argument(
        "--fragile-regime-entry-regimes",
        default="",
        help=(
            "Comma-separated regimes where --fragile-regime-entry-size-mult applies, for example "
            "one_way_long,one_way_short,range_or_transition."
        ),
    )
    parser.add_argument(
        "--fragile-regime-inventory-trim-fraction",
        type=float,
        default=0.0,
        help="Optional fraction of open inventory to cut when the market first enters selected fragile regimes.",
    )
    parser.add_argument(
        "--fragile-regime-inventory-trim-regimes",
        default="",
        help="Comma-separated regimes where transition inventory trims apply.",
    )
    parser.add_argument(
        "--event-risk-base-reduce-size-mult",
        type=float,
        default=1.0,
        help="Size multiplier for base entries in selected execution-risk contexts.",
    )
    parser.add_argument(
        "--event-risk-base-reduce-min-extension-atr",
        type=float,
        default=0.0,
        help="Only shrink event-risk base entries when EMA extension is at least this ATR multiple.",
    )
    parser.add_argument(
        "--event-risk-base-reduce-max-extension-atr",
        type=float,
        default=0.0,
        help="Only shrink event-risk base entries when EMA extension is at most this ATR multiple; 0 disables the cap.",
    )
    parser.add_argument(
        "--event-risk-base-reduce-side",
        choices=("both", "long", "short"),
        default="both",
        help="Side filter for event-risk base-entry reduction.",
    )
    parser.add_argument(
        "--event-risk-base-reduce-contexts",
        default="",
        help='Comma-separated execution contexts to shrink, for example "hour_open".',
    )
    parser.add_argument(
        "--regime-router-enabled",
        action="store_true",
        help="Enable the explicit market-mode router that changes sizing by trend, one-way, range, and risk-off modes.",
    )
    parser.add_argument("--router-trend-reaction-size-mult", type=float, default=1.0)
    parser.add_argument("--router-one-way-chase-size-mult", type=float, default=0.75)
    parser.add_argument("--router-one-way-counter-size-mult", type=float, default=0.0)
    parser.add_argument("--router-range-probe-size-mult", type=float, default=0.25)
    parser.add_argument("--router-range-base-size-mult", type=float, default=0.0)
    parser.add_argument("--router-exhaustion-reversal-size-mult", type=float, default=0.35)
    parser.add_argument("--router-exhaustion-min-score-edge", type=int, default=2)
    parser.add_argument("--router-exhaustion-min-extension-atr", type=float, default=1.5)
    parser.add_argument("--router-risk-off-size-mult", type=float, default=0.0)
    parser.add_argument("--router-transition-trim-fraction", type=float, default=0.0)
    parser.add_argument(
        "--router-transition-trim-modes",
        default="",
        help="Comma-separated router modes where existing inventory is trimmed on mode transition.",
    )
    parser.add_argument(
        "--router-transition-trim-cooldown-bars",
        type=int,
        default=0,
        help="Minimum bars between router mode transition inventory trims. Default 0 keeps legacy behavior.",
    )
    parser.add_argument(
        "--router-transition-trim-all",
        dest="router_transition_trim_against_only",
        action="store_false",
        help="Trim inventory on selected router-mode transitions even when it is not opposite the new mode.",
    )
    parser.set_defaults(router_transition_trim_against_only=True)
    parser.add_argument("--defensive-trim-cooldown-bars", type=int, default=12960)
    parser.add_argument("--reaction-trim-trigger", type=float, default=0.55)
    parser.add_argument(
        "--reaction-trim-size-mult",
        type=float,
        default=1.0,
        help="Throttle v6 reaction inventory trim size while preserving the reaction trigger level.",
    )
    parser.add_argument(
        "--reaction-trim-trend-hold-trigger-mult",
        type=float,
        default=1.0,
        help="Raise the reaction trim trigger while the current side's trend/one-way context is still alive.",
    )
    parser.add_argument("--reaction-avg-band", type=float, default=0.95)
    parser.add_argument("--skip-weak-long-round-reclaim", dest="skip_weak_long_round_reclaim", action="store_true", default=True)
    parser.add_argument("--include-weak-long-round-reclaim", dest="skip_weak_long_round_reclaim", action="store_false")
    parser.add_argument(
        "--blocked-kst-entry-hours",
        default="4,9,13,16",
        help='Comma-separated KST hours to block new entries, or "none".',
    )
    parser.add_argument("--cache-dir", default="reports/validation/btc_flip_rotation_search/cache")
    parser.add_argument("--report-dir", default="reports/validation/market_state_rotation_v6_backtest")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _parse_float_csv(raw: str, fallback: list[float]) -> list[float]:
    values: list[float] = []
    for item in _csv(raw):
        try:
            value = float(item)
        except ValueError:
            continue
        if value > 0.0:
            values.append(value)
    return values or fallback


def _parse_nonnegative_float_csv(raw: str, fallback: list[float]) -> list[float]:
    values: list[float] = []
    for item in _csv(raw):
        try:
            value = float(item)
        except ValueError:
            continue
        if value >= 0.0:
            values.append(value)
    return values or fallback


def _parse_kst_hours(raw: str, fallback: tuple[int, ...]) -> tuple[int, ...]:
    text = str(raw or "").strip().lower()
    if text in {"none", "off", "false"}:
        return ()
    values: list[int] = []
    for item in _csv(raw):
        try:
            hour = int(item)
        except ValueError:
            continue
        if 0 <= hour <= 23 and hour not in values:
            values.append(hour)
    return tuple(values) if values else fallback


def _parse_regimes(raw: str) -> tuple[str, ...]:
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


def _parse_router_modes(raw: str) -> tuple[str, ...]:
    allowed = {
        "trend_reaction",
        "one_way_chase",
        "exhaustion_reversal",
        "range_transition",
        "risk_off",
    }
    modes = [item for item in _csv(raw) if item in allowed]
    return tuple(dict.fromkeys(modes))


def _parse_event_risk_contexts(raw: str) -> tuple[str, ...]:
    allowed = {"normal", "hour_open"}
    contexts = [item for item in _csv(raw) if item in allowed]
    return tuple(dict.fromkeys(contexts))


def _parse_base_context_reduce_patterns(raw: str) -> tuple[str, ...]:
    patterns: list[str] = []
    for item in _csv(raw):
        pattern = "|".join(part.strip() for part in item.split("|"))
        tokens = pattern.split("|")
        if len(tokens) != 7:
            continue
        if any(not token for token in tokens):
            continue
        if tokens[0] not in {"base", "*"}:
            continue
        if pattern not in patterns:
            patterns.append(pattern)
    return tuple(patterns)


def _format_kst_hours(hours: tuple[int, ...]) -> str:
    return "-".join(str(hour) for hour in hours) if hours else "none"


def _format_event_risk_contexts(contexts: tuple[str, ...]) -> str:
    return "-".join(contexts) if contexts else "none"


def _format_base_context_patterns(patterns: tuple[str, ...]) -> str:
    return "-".join(str(pattern).replace("|", "_").replace("*", "x") for pattern in patterns) or "none"


def _kst_hour(ts: datetime) -> int:
    return (ts.hour + 9) % 24


def _side_label(side: int) -> str:
    if side > 0:
        return "long"
    if side < 0:
        return "short"
    return "flat"


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(float(value), float(low)), float(high))


def _fragile_regime_entry_multiplier(config: MarketStateConfig, market: MarketState) -> float:
    if not config.fragile_regime_entry_regimes:
        return 1.0
    if market.regime not in set(config.fragile_regime_entry_regimes):
        return 1.0
    return _clamp(config.fragile_regime_entry_size_mult, 0.0, 1.0)


def _event_risk_base_size_multiplier(config: MarketStateConfig, zone: ZonePlan, side: int, role: str) -> float:
    if role != "base":
        return 1.0
    contexts = tuple(str(item) for item in getattr(config, "event_risk_base_reduce_contexts", ()) or ())
    if not contexts:
        return 1.0
    if str(zone.execution_context or "") not in set(contexts):
        return 1.0
    if getattr(config, "event_risk_base_reduce_side", "both") not in {"both", _side_label(side)}:
        return 1.0
    min_extension = max(0.0, float(getattr(config, "event_risk_base_reduce_min_extension_atr", 0.0) or 0.0))
    if min_extension > 0.0 and float(zone.chase_extension_atr) < min_extension:
        return 1.0
    max_extension = max(0.0, float(getattr(config, "event_risk_base_reduce_max_extension_atr", 0.0) or 0.0))
    if max_extension > 0.0 and float(zone.chase_extension_atr) > max_extension:
        return 1.0
    raw_mult = getattr(config, "event_risk_base_reduce_size_mult", 1.0)
    if raw_mult is None:
        raw_mult = 1.0
    return _clamp(float(raw_mult), 0.0, 1.0)


def _base_context_pattern_matches(context_key: str, pattern: str) -> bool:
    context_tokens = str(context_key or "").split("|")
    pattern_tokens = str(pattern or "").split("|")
    if len(context_tokens) != 7 or len(pattern_tokens) != 7:
        return False
    return all(pattern_token == "*" or pattern_token == context_token for pattern_token, context_token in zip(pattern_tokens, context_tokens))


def _base_context_size_multiplier(config: MarketStateConfig, context_key: str, role: str) -> float:
    if role != "base":
        return 1.0
    patterns = tuple(str(item) for item in getattr(config, "base_context_reduce_patterns", ()) or ())
    if not patterns:
        return 1.0
    if not any(_base_context_pattern_matches(context_key, pattern) for pattern in patterns):
        return 1.0
    raw_mult = getattr(config, "base_context_reduce_size_mult", 1.0)
    if raw_mult is None:
        raw_mult = 1.0
    return _clamp(float(raw_mult), 0.0, 1.0)


def _unit_cut_qty(qty: float, fraction: float, *, minimum: float = 1.0) -> float:
    if qty <= minimum + 1e-12:
        return qty
    rounded = round(qty * fraction)
    return min(qty, max(minimum, float(rounded)))


def _scaled_unit_cut_qty(
    qty: float,
    fraction: float,
    size_mult: float,
    *,
    minimum: float = 1.0,
) -> float:
    effective_fraction = max(float(fraction), 0.0) * _clamp(size_mult, 0.05, 1.0)
    if effective_fraction <= 1e-12:
        return 0.0
    return _unit_cut_qty(qty, effective_fraction, minimum=minimum)


def _min_cut_units(config: MarketStateConfig) -> float:
    return max(config.probe_units, min(config.base_add_units, 0.25))


def _trend_hold_context(config: MarketStateConfig, market: MarketState, side: int) -> bool:
    if side == 0:
        return False
    min_trend_strength = max(0.0, float(config.trend_hold_min_trend_strength))
    min_one_way_score = max(0.0, float(config.trend_hold_min_one_way_score))
    if market.one_way_side == side and market.one_way_score >= min_one_way_score:
        return True
    return market.bias == side and market.trend_strength >= min_trend_strength


def _reaction_trim_trigger(config: MarketStateConfig, market: MarketState, side: int) -> float:
    trigger = max(0.05, float(config.reaction_trim_trigger))
    trend_mult = max(1.0, float(config.reaction_trim_trend_hold_trigger_mult))
    if trend_mult <= 1.0 + 1e-12:
        return trigger
    if not _trend_hold_context(config, market, side):
        return trigger
    return trigger * _clamp(trend_mult, 1.0, 5.0)


def _hard_time_exit_trend_defer_ready(
    config: MarketStateConfig,
    market: MarketState,
    side: int,
    *,
    age_bars: int,
    favorable_reaction: float,
) -> bool:
    grace_bars = max(0, int(config.hard_time_exit_trend_defer_bars))
    if grace_bars <= 0:
        return False
    if age_bars >= int(config.max_hold_bars) + grace_bars:
        return False
    min_favorable = max(0.0, float(config.hard_time_exit_trend_defer_min_favorable_reaction))
    if favorable_reaction < min_favorable:
        return False
    return _trend_hold_context(config, market, side)


def _hard_time_loss_defer_ready(
    config: MarketStateConfig,
    book: PositionBook,
    price: float,
    *,
    age_bars: int,
) -> bool:
    defer_bars = max(0, int(config.hard_time_loss_defer_bars))
    if defer_bars <= 0 or book.side == 0:
        return False
    if age_bars >= int(config.max_hold_bars) + defer_bars:
        return False
    fragments = tuple(str(item) for item in config.hard_time_loss_defer_context_fragments if str(item))
    if fragments and not any(
        any(fragment in str(lot.zone_context or "") for fragment in fragments)
        for lot in book.tranches
        if lot.qty > 1e-12
    ):
        return False
    unrealized_pnl = sum(
        lot.side * lot.qty * (float(price) - lot.entry)
        for lot in book.tranches
        if lot.qty > 1e-12
    )
    min_loss = max(0.0, float(config.hard_time_loss_defer_min_loss_usd))
    return unrealized_pnl <= -min_loss


def _inventory_throttle_multiplier(config: MarketStateConfig, qty: float, size_mult: float) -> float:
    if config.max_possible_units <= config.base_add_units + 1e-12:
        return 1.0
    min_scalable_qty = max(config.base_add_units, _min_cut_units(config)) + 1e-12
    if qty <= min_scalable_qty:
        return 1.0
    return _clamp(size_mult, 0.05, 1.0)


def _hard_time_exit_fraction(config: MarketStateConfig, qty: float) -> float:
    if config.max_possible_units <= config.base_add_units + 1e-12:
        return 1.0
    min_scalable_qty = max(config.base_add_units, _min_cut_units(config)) + 1e-12
    if qty <= min_scalable_qty:
        return 1.0
    return _clamp(config.hard_time_exit_fraction, 0.05, 1.0)


def _one_way_full_exit_ready(config: MarketStateConfig, market: MarketState) -> bool:
    return (
        config.one_way_trim_full_exit_min_one_way_score > 0.0
        and market.one_way_score >= config.one_way_trim_full_exit_min_one_way_score
        and abs(market.score_diff) >= config.one_way_trim_full_exit_min_score_diff
    )


def _role_qty(book: PositionBook, role: str) -> float:
    return sum(lot.qty for lot in book.tranches if lot.role == role)


def _role_avg(book: PositionBook, role: str) -> float:
    lots = [lot for lot in book.tranches if lot.role == role and lot.qty > 1e-12]
    qty = sum(lot.qty for lot in lots)
    if qty <= 1e-12:
        return 0.0
    return sum(lot.qty * lot.entry for lot in lots) / qty


def _role_age_bars(book: PositionBook, role: str, exec_idx: int) -> int:
    ages = [exec_idx - lot.entry_idx for lot in book.tranches if lot.role == role and lot.qty > 1e-12]
    return max(ages) if ages else 0


def _late_base_lots(book: PositionBook) -> list[Any]:
    return [
        lot
        for lot in book.tranches
        if lot.role == "base" and lot.qty > 1e-12 and "|late_base_reduce|" in f"|{lot.zone_context}|"
    ]


def _late_base_qty(book: PositionBook) -> float:
    return sum(lot.qty for lot in _late_base_lots(book))


def _late_base_avg(book: PositionBook) -> float:
    lots = _late_base_lots(book)
    qty = sum(lot.qty for lot in lots)
    if qty <= 1e-12:
        return 0.0
    return sum(lot.qty * lot.entry for lot in lots) / qty


def _context_quarantine_key(context: str) -> str:
    parts = [part for part in str(context or "").split("|") if part]
    if not parts:
        return ""
    while parts and parts[-1] in {"late_base_reduce", "loss_fuse_reduce", "soft_recovery"}:
        parts = parts[:-1]
    return "|".join(parts)


def _remove_context_lots(book: PositionBook, context_key: str, price: float) -> list[RemovedLot]:
    key = str(context_key or "")
    if not key:
        return []
    removed: list[RemovedLot] = []
    for lot in book.tranches:
        if lot.qty <= 1e-12 or _context_quarantine_key(lot.zone_context) != key:
            continue
        take = lot.qty
        pnl = lot.side * take * (float(price) - lot.entry)
        book.cycle_realized_pnl_usd_units += pnl
        removed.append(
            RemovedLot(
                side=lot.side,
                qty=take,
                entry=lot.entry,
                exit_price=float(price),
                role=lot.role,
                pnl_usd_units=pnl,
                zone_score=lot.zone_score,
                zone_id=lot.zone_id,
                zone_context=lot.zone_context,
            )
        )
        lot.qty = 0.0
    if removed:
        book.tranches = [lot for lot in book.tranches if lot.qty > 1e-12]
        if not book.tranches:
            book.cycle_realized_pnl_usd_units = 0.0
    return removed


def _book_weight(config: MarketStateConfig, book: PositionBook) -> float:
    if book.side == 0:
        return 0.0
    unit_weight = config.max_account_exposure / max(config.max_possible_units, 1e-12)
    return book.side * book.qty * unit_weight


def _book_open_role_payloads(book: PositionBook) -> tuple[dict[str, int], dict[str, float]]:
    lot_count_by_role: Counter[str] = Counter()
    qty_by_role: Counter[str] = Counter()
    for lot in book.tranches:
        if lot.qty <= 1e-12:
            continue
        role = str(lot.role or "unknown")
        lot_count_by_role[role] += 1
        qty_by_role[role] += float(lot.qty)
    return (
        _counter_payload(lot_count_by_role),
        {key: round(float(value), 6) for key, value in sorted(qty_by_role.items())},
    )


def _liquidation_price(config: MarketStateConfig, side: int, avg_entry: float) -> float:
    distance = max(1.0 / max(config.exchange_leverage, 1e-12) - config.maintenance_margin_pct / 100.0, 0.005)
    if side > 0:
        return avg_entry * (1.0 - distance)
    if side < 0:
        return avg_entry * (1.0 + distance)
    return 0.0


def _liquidation_buffer_pct(config: MarketStateConfig, book: PositionBook, price: float) -> float:
    if book.side == 0 or price <= 0.0:
        return math.inf
    liq = _liquidation_price(config, book.side, book.avg_entry)
    if book.side > 0:
        return (price - liq) / price
    return (liq - price) / price


def _nearest_round_dist(price: float, side: int) -> float:
    levels = _round_levels(price)
    if side > 0:
        candidates = [abs(price - level) for level in levels if level <= price]
    else:
        candidates = [abs(price - level) for level in levels if level >= price]
    return min(candidates) if candidates else math.inf


def _side_distance_to_major_zone(features: FeatureSet, idx: int, config: MarketStateConfig, side: int) -> float:
    close = features.c[idx]
    atr = max(features.atr[idx], 1e-12)
    prev_high = features.rolling_high_prev(config.zone_lookback)[idx]
    prev_low = features.rolling_low_prev(config.zone_lookback)[idx]
    cloud_low, cloud_high, _cloud_mid = _cloud_bands(features, idx)
    round_dist = _nearest_round_dist(close, side)
    if side > 0:
        raw = min(abs(close - prev_low), abs(close - cloud_high), abs(close - cloud_low), round_dist)
    else:
        raw = min(abs(close - prev_high), abs(close - cloud_high), abs(close - cloud_low), round_dist)
    return raw / atr


def _market_state(
    *,
    exec_features: FeatureSet,
    scenario_features: dict[str, FeatureSet],
    scenario_maps: dict[str, list[int]],
    exec_idx: int,
    sig_idx: int,
    config: MarketStateConfig,
) -> MarketState:
    long_score = 0
    short_score = 0
    strength_parts: list[float] = []
    reasons: list[str] = []

    for interval, features in scenario_features.items():
        idx = scenario_maps[interval][exec_idx]
        if idx <= max(config.htf_slow, 60):
            continue
        close = features.c[idx]
        atr = max(features.atr[idx], 1e-12)
        fast = features.ema(config.htf_fast)[idx]
        slow = features.ema(config.htf_slow)[idx]
        cloud_low, cloud_high, cloud_mid = _cloud_bands(features, idx)
        spread_atr = (fast - slow) / atr
        strength_parts.append(abs(spread_atr))
        weight = 3 if interval == "4h" else 2

        if fast > slow and close > cloud_mid:
            long_score += weight
            reasons.append(f"{interval}_trend_long")
        elif fast < slow and close < cloud_mid:
            short_score += weight
            reasons.append(f"{interval}_trend_short")

        if close > cloud_high:
            long_score += 1
        elif close < cloud_low:
            short_score += 1

        if spread_atr > config.htf_band_atr:
            long_score += 1
        elif spread_atr < -config.htf_band_atr:
            short_score += 1

    diff = long_score - short_score
    bias = 1 if diff >= 2 else -1 if diff <= -2 else 0
    trend_strength = mean(strength_parts) if strength_parts else 0.0

    atr = max(exec_features.atr[sig_idx], 1e-12)
    close = exec_features.c[sig_idx]
    start = max(0, sig_idx - max(config.one_way_window, 3))
    net_move = close - exec_features.c[start]
    move_atr = abs(net_move) / atr
    recent_high = max(exec_features.h[start : sig_idx + 1])
    recent_low = min(exec_features.l[start : sig_idx + 1])
    recent_range = max(recent_high - recent_low, atr)
    pullback_ratio = max((recent_range - abs(net_move)) / recent_range, 0.0)
    exec_slow = exec_features.ema(config.exec_slow)[sig_idx]
    extension_atr = abs(close - exec_slow) / atr
    directional_bars = 0
    direction = 1 if net_move > 0.0 else -1 if net_move < 0.0 else 0
    if direction:
        for pos in range(max(1, start + 1), sig_idx + 1):
            step = exec_features.c[pos] - exec_features.c[pos - 1]
            if step * direction > 0.0:
                directional_bars += 1

    one_way_score = (
        max(move_atr - 1.6, 0.0)
        + max(0.35 - pullback_ratio, 0.0) * 3.0
        + max(extension_atr - 2.0, 0.0) * 0.65
        + max(directional_bars - config.one_way_window * 0.55, 0.0) * 0.08
    )
    one_way_side = direction if direction and one_way_score >= config.one_way_threshold else 0

    long_dist_atr = _side_distance_to_major_zone(exec_features, sig_idx, config, 1)
    short_dist_atr = _side_distance_to_major_zone(exec_features, sig_idx, config, -1)
    bad_rr = min(long_dist_atr, short_dist_atr) > config.bad_rr_atr and abs(diff) <= 3
    if bad_rr:
        reasons.append("bad_rr_center")
    if one_way_side:
        reasons.append(f"one_way_{_side_label(one_way_side)}")
    if one_way_side:
        regime = f"one_way_{_side_label(one_way_side)}"
    elif bad_rr:
        regime = "bad_rr_center"
    elif bias > 0 and trend_strength >= 0.35:
        regime = "uptrend"
    elif bias < 0 and trend_strength >= 0.35:
        regime = "downtrend"
    elif abs(diff) <= 1:
        regime = "range_or_transition"
    else:
        regime = "mixed"

    return MarketState(
        bias=bias,
        long_score=long_score,
        short_score=short_score,
        trend_strength=trend_strength,
        one_way_side=one_way_side,
        one_way_score=one_way_score,
        bad_rr=bad_rr,
        long_dist_atr=long_dist_atr,
        short_dist_atr=short_dist_atr,
        regime=regime,
        score_diff=diff,
        reasons=tuple(reasons[:8]),
    )


def _near_2468_support(low: float, close: float, atr: float) -> bool:
    tolerance = max(0.28 * atr, 35.0)
    return any(low <= level + tolerance and close >= level for level in _round_levels(close))


def _near_2468_resistance(high: float, close: float, atr: float) -> bool:
    tolerance = max(0.28 * atr, 35.0)
    return any(high >= level - tolerance and close <= level for level in _round_levels(close))


def _nearest_round_level(price: float, side: int) -> float | None:
    levels = _round_levels(price)
    if side > 0:
        candidates = [level for level in levels if level <= price]
        return min(candidates, key=lambda level: abs(price - level)) if candidates else None
    candidates = [level for level in levels if level >= price]
    return min(candidates, key=lambda level: abs(price - level)) if candidates else None


def _reason_category(reason: str) -> str:
    if reason.startswith("htf_bias"):
        return "trend"
    if "sweep" in reason or "range_" in reason:
        return "wick_supply"
    if reason.startswith("cloud"):
        return "cloud"
    if reason.startswith("2468"):
        return "round"
    if "rsi" in reason:
        return "momentum"
    if reason.startswith("trend_chase"):
        return "chase"
    if reason.startswith("volume"):
        return "volume"
    return reason


def _reason_stack(reasons: list[str] | tuple[str, ...]) -> int:
    return len({_reason_category(reason) for reason in reasons})


def _zone_anchor(
    *,
    features: FeatureSet,
    idx: int,
    side: int,
    config: MarketStateConfig,
    close: float,
    atr: float,
) -> float:
    prev_high = features.rolling_high_prev(config.zone_lookback)[idx]
    prev_low = features.rolling_low_prev(config.zone_lookback)[idx]
    cloud_low, cloud_high, _cloud_mid = _cloud_bands(features, idx)
    round_level = _nearest_round_level(close, side)
    candidates: list[float] = []
    if side > 0:
        candidates.extend([prev_low, cloud_low, cloud_high])
    else:
        candidates.extend([prev_high, cloud_low, cloud_high])
    if round_level is not None:
        candidates.append(round_level)
    return min(candidates, key=lambda level: abs(close - level)) if candidates else close


def _zone_key(side: int, anchor: float, atr: float, reasons: list[str] | tuple[str, ...]) -> str:
    bucket = max(100.0, atr * 0.50)
    rounded_anchor = round(anchor / bucket) * bucket
    cats = "-".join(sorted({_reason_category(reason) for reason in reasons})[:4])
    return f"{_side_label(side)}:{rounded_anchor:.0f}:{cats}"


def _stage_for_side(
    *,
    mode: str,
    side: int,
    score: int,
    reason_stack: int,
    reasons: list[str],
    dist_atr: float,
    market: MarketState,
    breakout_atr: float,
    extension_atr: float,
    close_position: float,
    rsi: float,
    config: MarketStateConfig,
) -> str:
    reason_set = set(reasons)
    if mode == "chase" and any(reason.startswith("trend_chase") for reason in reason_set):
        volume_ok = (not config.volume_layer_enabled) or any(reason.startswith("volume_breakout") for reason in reason_set)
        rsi_ok = rsi <= 78.0 if side > 0 else rsi >= 22.0
        close_ok = close_position >= 0.56 if side > 0 else close_position <= 0.44
        trend_ok = (
            market.one_way_side == side
            or (
                market.bias == side
                and market.trend_strength >= 0.35
                and abs(market.score_diff) >= 3
                and market.one_way_score >= config.chase_min_one_way_score * 0.25
            )
        )
        breakout_ok = config.chase_min_breakout_atr <= breakout_atr <= config.chase_max_breakout_atr
        extension_ok = extension_atr <= config.chase_max_extension_atr
        if (
            score >= config.chase_min_score
            and reason_stack >= config.chase_min_reason_stack
            and trend_ok
            and volume_ok
            and breakout_ok
            and extension_ok
            and close_ok
            and rsi_ok
        ):
            return "chase"
        return "watch"
    has_reaction_zone = any(
        reason in reason_set
        for reason in {
            "low_sweep_reclaim",
            "high_sweep_reject",
            "range_low_reaction",
            "range_high_reaction",
        }
    )
    has_major_confluence = any(reason.startswith("cloud") for reason in reason_set) or any(
        reason.startswith("2468") for reason in reason_set
    )
    has_volume_confirmation = any(reason.startswith("volume") for reason in reason_set)
    if (
        score >= config.battle_primary_score
        and reason_stack >= max(config.min_reason_stack, 3)
        and has_reaction_zone
        and (has_major_confluence or has_volume_confirmation)
        and dist_atr <= config.battle_primary_dist_atr
    ):
        return "battle"
    with_trend = market.bias == 0 or market.bias == side
    if config.base_requires_major_confluence:
        base_quality_ok = has_reaction_zone and (has_major_confluence or has_volume_confirmation)
    else:
        base_quality_ok = (
            has_reaction_zone
            or (with_trend and has_major_confluence and score >= config.base_primary_score + 1)
            or (with_trend and has_volume_confirmation and score >= config.base_primary_score + 1)
        )
    if score >= config.base_primary_score and reason_stack >= config.min_reason_stack and base_quality_ok:
        return "base"
    if (
        score >= max(config.entry_score, config.base_primary_score - 1)
        and reason_stack >= config.min_reason_stack
        and has_reaction_zone
        and has_major_confluence
        and market.one_way_side != -side
    ):
        return "probe"
    return "watch"


def _zone_plan(
    *,
    features: FeatureSet,
    idx: int,
    market: MarketState,
    config: MarketStateConfig,
) -> ZonePlan:
    open_ = features.o[idx]
    high = features.h[idx]
    low = features.l[idx]
    close = features.c[idx]
    atr = max(features.atr[idx], 1e-12)
    span = max(high - low, 1e-12)
    close_position = (close - low) / span
    body_atr = (close - open_) / atr
    prev_high = features.rolling_high_prev(config.zone_lookback)[idx]
    prev_low = features.rolling_low_prev(config.zone_lookback)[idx]
    cloud_low, cloud_high, cloud_mid = _cloud_bands(features, idx)
    rsi = features.rsi(14)[idx]
    exec_fast = features.ema(config.exec_fast)[idx]
    exec_slow = features.ema(config.exec_slow)[idx]
    exec_spread = (exec_fast - exec_slow) / atr
    extension_atr = abs(close - exec_slow) / atr
    long_breakout_atr = max((close - prev_high) / atr, 0.0)
    short_breakout_atr = max((prev_low - close) / atr, 0.0)
    volume_mean = max(features.rolling_volume_mean_prev(config.volume_lookback)[idx], 1e-12)
    volume_rel = features.v[idx] / volume_mean
    event_risk = "hour_open" if features.ts[idx].minute in {0, 5} else "normal"

    long_score = 0
    short_score = 0
    long_reasons: list[str] = []
    short_reasons: list[str] = []

    if market.bias > 0:
        long_score += 2
        long_reasons.append("htf_bias_long")
    elif market.bias < 0:
        short_score += 2
        short_reasons.append("htf_bias_short")

    long_sweep_reclaim = low <= prev_low - 0.08 * atr and close > prev_low
    short_sweep_reject = high >= prev_high + 0.08 * atr and close < prev_high
    if long_sweep_reclaim:
        long_score += 3
        long_reasons.append("low_sweep_reclaim")
        if config.volume_layer_enabled and volume_rel >= config.volume_absorption_mult:
            long_score += 1
            long_reasons.append("volume_absorption_long")
    elif low <= prev_low + 0.35 * atr and close_position >= 0.58:
        long_score += 2
        long_reasons.append("range_low_reaction")
        if config.volume_layer_enabled and volume_rel >= config.volume_absorption_mult and close_position >= 0.68:
            long_score += 1
            long_reasons.append("volume_reaction_long")

    if short_sweep_reject:
        short_score += 3
        short_reasons.append("high_sweep_reject")
        if config.volume_layer_enabled and volume_rel >= config.volume_absorption_mult:
            short_score += 1
            short_reasons.append("volume_absorption_short")
    elif high >= prev_high - 0.35 * atr and close_position <= 0.42:
        short_score += 2
        short_reasons.append("range_high_reaction")
        if config.volume_layer_enabled and volume_rel >= config.volume_absorption_mult and close_position <= 0.32:
            short_score += 1
            short_reasons.append("volume_reaction_short")

    if low <= cloud_high + 0.20 * atr and close >= cloud_low and market.bias >= 0:
        long_score += 1
        long_reasons.append("cloud_support")
    if high >= cloud_low - 0.20 * atr and close <= cloud_high and market.bias <= 0:
        short_score += 1
        short_reasons.append("cloud_resistance")

    if _near_2468_support(low, close, atr) and close_position >= 0.50:
        long_score += 1
        long_reasons.append("2468_support")
    if _near_2468_resistance(high, close, atr) and close_position <= 0.50:
        short_score += 1
        short_reasons.append("2468_resistance")

    if rsi <= 36.0 and body_atr > -0.15:
        long_score += 1
        long_reasons.append("washed_rsi")
    elif rsi >= 64.0 and body_atr < 0.15:
        short_score += 1
        short_reasons.append("heated_rsi")

    mode = "zone"
    if close > prev_high and exec_spread > 0.25 and market.bias >= 0:
        long_score += 2
        long_reasons.append("trend_chase_breakout")
        if config.volume_layer_enabled and volume_rel >= config.volume_confirm_mult and body_atr > 0.10:
            long_score += 1
            long_reasons.append("volume_breakout_long")
        mode = "chase"
    if close < prev_low and exec_spread < -0.25 and market.bias <= 0:
        short_score += 2
        short_reasons.append("trend_chase_breakdown")
        if config.volume_layer_enabled and volume_rel >= config.volume_confirm_mult and body_atr < -0.10:
            short_score += 1
            short_reasons.append("volume_breakout_short")
        mode = "chase"

    long_reason_stack = _reason_stack(long_reasons)
    short_reason_stack = _reason_stack(short_reasons)
    long_anchor = _zone_anchor(features=features, idx=idx, side=1, config=config, close=close, atr=atr)
    short_anchor = _zone_anchor(features=features, idx=idx, side=-1, config=config, close=close, atr=atr)
    long_zone_key = _zone_key(1, long_anchor, atr, long_reasons)
    short_zone_key = _zone_key(-1, short_anchor, atr, short_reasons)
    long_stage = _stage_for_side(
        mode=mode,
        side=1,
        score=long_score,
        reason_stack=long_reason_stack,
        reasons=long_reasons,
        dist_atr=market.long_dist_atr,
        market=market,
        breakout_atr=long_breakout_atr,
        extension_atr=extension_atr,
        close_position=close_position,
        rsi=rsi,
        config=config,
    )
    short_stage = _stage_for_side(
        mode=mode,
        side=-1,
        score=short_score,
        reason_stack=short_reason_stack,
        reasons=short_reasons,
        dist_atr=market.short_dist_atr,
        market=market,
        breakout_atr=short_breakout_atr,
        extension_atr=extension_atr,
        close_position=close_position,
        rsi=rsi,
        config=config,
    )
    no_trade_reasons: list[str] = []
    if market.bad_rr:
        no_trade_reasons.append("MC04_bad_rr_center")
    if long_score and long_reason_stack < config.min_reason_stack and short_score and short_reason_stack < config.min_reason_stack:
        no_trade_reasons.append("MC12_low_confluence")
    if abs(long_score - short_score) <= 1 and max(long_score, short_score) < config.battle_primary_score:
        no_trade_reasons.append("MC04_no_clear_first_touch")
    if mode == "chase" and event_risk == "hour_open" and max(long_score, short_score) < config.chase_min_score + 2:
        no_trade_reasons.append("MC27_time_event_chase_risk")
    if config.volume_layer_enabled and mode == "chase":
        active_reasons = long_reasons if long_score >= short_score else short_reasons
        if any(reason.startswith("trend_chase") for reason in active_reasons) and not any(
            reason.startswith("volume_breakout") for reason in active_reasons
        ):
            no_trade_reasons.append("MC31_unconfirmed_breakout_volume")
    if (
        config.volume_layer_enabled
        and volume_rel < config.quiet_volume_mult
        and abs(body_atr) < 0.20
        and max(long_score, short_score) < config.battle_primary_score
    ):
        no_trade_reasons.append("MC32_quiet_tape")
    long_reason_set = set(long_reasons)
    short_reason_set = set(short_reasons)
    market_reason_set = set(market.reasons)
    short_entry_candidate = short_score >= long_score + config.flat_score_edge and short_stage != "watch"
    if config.skip_weak_long_round_reclaim:
        weak_round_reclaim = {
            "htf_bias_long",
            "low_sweep_reclaim",
            "2468_support",
            "washed_rsi",
        }.issubset(long_reason_set) and not any(reason.startswith("cloud") for reason in long_reason_set)
        if weak_round_reclaim and long_score >= short_score:
            no_trade_reasons.append("MC41_weak_long_round_rsi_reclaim")
    short_dominant_base = (
        short_stage == "base"
        and short_score >= long_score + config.flat_score_edge
        and "high_sweep_reject" in short_reason_set
    )
    if short_dominant_base and market.regime == "mixed" and event_risk == "hour_open":
        no_trade_reasons.append("MC42_mixed_hour_open_short_reject")
    if short_dominant_base and extension_atr > 4.0 and not any(reason.startswith("cloud") for reason in short_reasons):
        no_trade_reasons.append("MC43_late_extended_short_reject")
    if (
        short_dominant_base
        and market.regime == "downtrend"
        and "heated_rsi" in short_reason_set
        and 1.5 < extension_atr <= 2.5
    ):
        no_trade_reasons.append("MC44_mid_extension_heated_short_reject")
    long_chase_no_reaction = (
        long_stage == "chase"
        and "trend_chase_breakout" in long_reason_set
        and not {"low_sweep_reclaim", "range_low_reaction"}.intersection(long_reason_set)
    )
    if long_chase_no_reaction and extension_atr > 1.5:
        no_trade_reasons.append("MC45_late_long_chase_without_reaction")
    if long_stage == "battle" and market.regime == "uptrend" and 0.75 < extension_atr <= 1.5:
        no_trade_reasons.append("MC46_mid_extension_long_battle_reject")
    if long_stage == "base" and event_risk == "hour_open" and 0.75 < extension_atr <= 1.5:
        no_trade_reasons.append("MC47_mid_extension_hour_open_long_reject")
    if (
        long_stage == "base"
        and "range_low_reaction" in long_reason_set
        and "4h_trend_long" not in market_reason_set
    ):
        no_trade_reasons.append("MC49_unconfirmed_range_low_long")
    if (
        short_entry_candidate
        and short_stage == "base"
        and {"high_sweep_reject", "cloud_resistance", "2468_resistance"}.issubset(short_reason_set)
        and "1h_trend_short" not in market_reason_set
    ):
        no_trade_reasons.append("MC50_unconfirmed_cloud_short")
    if short_entry_candidate and short_stage == "chase" and short_breakout_atr <= 0.10:
        no_trade_reasons.append("MC51_weak_breakdown_chase_short")
    if (
        short_entry_candidate
        and short_stage == "base"
        and market.regime == "mixed"
        and 0.75 < extension_atr <= 2.5
    ):
        no_trade_reasons.append("MC52_mixed_mid_extension_short")
    if config.base_entry_max_extension_atr > 0.0:
        base_extension_cap = max(0.1, float(config.base_entry_max_extension_atr))
        if (
            long_stage == "base"
            and long_score >= short_score
            and market.bias == 1
            and config.base_entry_max_extension_side in {"both", "long"}
            and extension_atr > base_extension_cap
        ):
            no_trade_reasons.append("MC57_late_extended_long_base")
        if (
            short_stage == "base"
            and short_score >= long_score
            and market.bias == -1
            and config.base_entry_max_extension_side in {"both", "short"}
            and extension_atr > base_extension_cap
        ):
            no_trade_reasons.append("MC58_late_extended_short_base")

    side = 0
    stage = "watch"
    score = max(long_score, short_score)
    if not no_trade_reasons:
        if long_score >= short_score + config.flat_score_edge and long_stage != "watch":
            side = 1
            score = long_score
            stage = long_stage
        elif short_score >= long_score + config.flat_score_edge and short_stage != "watch":
            side = -1
            score = short_score
            stage = short_stage
    exec_ts = features.ts[min(idx + 1, len(features.ts) - 1)]
    entry_kst_hour = _kst_hour(exec_ts)
    if side != 0 and entry_kst_hour in config.blocked_kst_entry_hours:
        no_trade_reasons.append(f"MC48_kst_hour_{entry_kst_hour:02d}_entry_block")
        side = 0
        stage = "watch"
    if side < 0 and stage == "base" and entry_kst_hour in CONTEXTUAL_SHORT_BASE_BLOCK_KST_HOURS:
        no_trade_reasons.append(f"MC56_short_base_kst_hour_{entry_kst_hour:02d}_entry_block")
        side = 0
        stage = "watch"

    expected_reaction_usd = max(config.reaction_usd, config.reaction_atr * atr)
    if abs(close - cloud_mid) <= 0.35 * atr or min(market.long_dist_atr, market.short_dist_atr) <= 0.35:
        expected_reaction_usd *= 1.08
    active_zone_key = long_zone_key if side > 0 else short_zone_key if side < 0 else ""

    return ZonePlan(
        side=side,
        mode=mode,
        stage=stage,
        score=score,
        long_score=long_score,
        short_score=short_score,
        long_reason_stack=long_reason_stack,
        short_reason_stack=short_reason_stack,
        long_reasons=tuple(long_reasons[:8]),
        short_reasons=tuple(short_reasons[:8]),
        long_zone_key=long_zone_key,
        short_zone_key=short_zone_key,
        active_zone_key=active_zone_key,
        no_trade_reasons=tuple(no_trade_reasons[:6]),
        expected_reaction_usd=expected_reaction_usd,
        nearest_long_dist=market.long_dist_atr * atr,
        nearest_short_dist=market.short_dist_atr * atr,
        chase_breakout_atr=long_breakout_atr if side > 0 else short_breakout_atr if side < 0 else 0.0,
        chase_extension_atr=extension_atr,
        execution_context=event_risk,
    )


def _scenario_allows_side(config: MarketStateConfig, market: MarketState, side: int) -> bool:
    if side == 0:
        return False
    if not config.strict_scenario_entry:
        return True
    return market.bias == 0 or market.bias == side


def _side_alignment(market: MarketState, side: int) -> str:
    if market.bias == 0:
        return "neutral"
    return "with_trend" if market.bias == side else "against_trend"


def _entry_size_multiplier(config: MarketStateConfig, market: MarketState, side: int) -> float:
    multiplier = 1.0
    if _side_alignment(market, side) == "against_trend":
        multiplier *= config.against_trend_size_mult
    if market.one_way_side == -side:
        multiplier *= config.one_way_against_size_mult
    return _clamp(multiplier, 0.10, 1.0)


def _router_mode(
    config: MarketStateConfig,
    market: MarketState,
    zone: ZonePlan,
    *,
    soft_circuit_active: bool = False,
) -> str:
    if not bool(getattr(config, "regime_router_enabled", False)):
        return "legacy"
    if soft_circuit_active:
        return "risk_off"
    if market.bad_rr or market.regime in {"range_or_transition", "bad_rr_center"}:
        return "range_transition"
    if market.one_way_side:
        one_way_side = market.one_way_side
        aligned_score = zone.long_score if one_way_side > 0 else zone.short_score
        opposite_score = zone.short_score if one_way_side > 0 else zone.long_score
        opposite_side = -one_way_side
        candidate_side = zone.side or _no_trade_candidate_side(market=market, zone=zone)
        exhaustion_ready = (
            candidate_side == opposite_side
            and opposite_score >= aligned_score + max(0, int(config.router_exhaustion_min_score_edge))
            and zone.chase_extension_atr >= max(0.0, float(config.router_exhaustion_min_extension_atr))
        )
        return "exhaustion_reversal" if exhaustion_ready else "one_way_chase"
    if market.bias != 0 and market.trend_strength >= 0.35:
        return "trend_reaction"
    if abs(market.score_diff) <= 1 or market.regime == "mixed":
        return "range_transition"
    return "trend_reaction"


def _router_entry_size_multiplier(
    config: MarketStateConfig,
    *,
    route_mode: str,
    market: MarketState,
    side: int,
    role: str,
) -> float:
    if not bool(getattr(config, "regime_router_enabled", False)) or route_mode == "legacy":
        return 1.0
    role = str(role or "probe")
    if route_mode == "risk_off":
        return _clamp(float(config.router_risk_off_size_mult), 0.0, 1.0)
    if route_mode == "trend_reaction":
        return _clamp(float(config.router_trend_reaction_size_mult), 0.0, 1.5)
    if route_mode == "range_transition":
        if role in {"base", "battle", "chase"}:
            return _clamp(float(config.router_range_base_size_mult), 0.0, 1.0)
        return _clamp(float(config.router_range_probe_size_mult), 0.0, 1.0)
    if route_mode == "one_way_chase":
        if market.one_way_side == -side:
            return _clamp(float(config.router_one_way_counter_size_mult), 0.0, 1.0)
        return _clamp(float(config.router_one_way_chase_size_mult), 0.0, 1.5)
    if route_mode == "exhaustion_reversal":
        if market.one_way_side == -side:
            return _clamp(float(config.router_exhaustion_reversal_size_mult), 0.0, 1.0)
        return _clamp(float(config.router_one_way_chase_size_mult), 0.0, 1.5)
    return 1.0


def _has_hard_no_trade_reasons(no_trade_reasons: tuple[str, ...]) -> bool:
    return any(
        reason.startswith("MC48")
        or reason
        in {
            "MC04_bad_rr_center",
            "MC27_time_event_chase_risk",
            "MC31_unconfirmed_breakout_volume",
            "MC32_quiet_tape",
        }
        for reason in no_trade_reasons
    )


def _recovery_price(book: PositionBook) -> float:
    return book.effective_breakeven()


def _repair_efficiency(book: PositionBook, price: float, expected_reaction: float) -> float:
    if book.side == 0:
        return 0.0
    recovery = _recovery_price(book)
    distance = abs(recovery - price)
    return distance / max(expected_reaction, 1e-12)


def _one_way_forced_trim_fraction(side: int, repair_eff: float) -> float:
    if side > 0:
        return ONE_WAY_LONG_TRIM_FRACTION
    return ONE_WAY_REPAIR_TRIM_FRACTION if repair_eff > 1.0 else ONE_WAY_LONG_TRIM_FRACTION


def _book_reaction_context_target(config: MarketStateConfig, book: PositionBook) -> float:
    """Use the original entry context to avoid widening every generic trend hold."""
    if book.side == 0:
        return config.reaction_usd
    for lot in book.tranches:
        context = str(getattr(lot, "zone_context", ""))
        if lot.side < 0 and (
            "|hour_open|ext_0-0.75|" in context
            or "|normal|ext_0-0.75|" in context
            or "mixed|normal|ext_2.5-4|" in context
        ):
            return max(config.reaction_usd, CONTEXT_REACTION_TARGET_USD)
        if lot.side > 0 and (
            "|normal|ext_0.75-1.5|" in context
            or "|normal|ext_1.5-2.5|" in context
            or "|hour_open|ext_1.5-2.5|" in context
        ):
            return max(config.reaction_usd, CONTEXT_REACTION_TARGET_USD)
    return config.reaction_usd


def _record_event(
    events: list[dict[str, Any]],
    *,
    ts: datetime,
    action: str,
    side: int,
    qty: float,
    price: float,
    reason: str,
    equity: float,
    extra: dict[str, Any] | None = None,
) -> None:
    item: dict[str, Any] = {
        "ts": ts.isoformat(),
        "action": action,
        "side": _side_label(side),
        "qty": round(float(qty), 6),
        "price": round(float(price), 2),
        "reason": reason,
        "equity": round(float(equity), 6),
    }
    if extra:
        item.update(extra)
    events.append(item)


def _drawdown_bar_event_payload(events: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    if len(events) > limit:
        payload.append({"omitted_events": len(events) - limit})
    for event in events[-limit:]:
        item: dict[str, Any] = {
            "action": event.get("action"),
            "side": event.get("side"),
            "qty": event.get("qty"),
            "price": event.get("price"),
            "reason": event.get("reason"),
        }
        for key in (
            "role",
            "entry",
            "pnl_usd_units",
            "zone_score",
            "entry_zone_score",
            "soft_circuit_recovery",
            "drawdown_pct",
        ):
            if key in event:
                item[key] = event[key]
        payload.append(item)
    return payload


def _event_cost_multiplier(event: dict[str, Any]) -> float:
    action = str(event.get("action") or "")
    role = str(event.get("role") or "")
    reason = str(event.get("reason") or "")
    if action == "add":
        if role in {"battle", "base", "probe"} and reason.endswith("entry"):
            return 0.35
        if role == "chase":
            return 0.75
        if "switch" in reason:
            return 0.80
        return 0.50
    if action == "remove":
        if reason in {
            "battle_reaction_first",
            "chase_quick_reaction_exit",
            "chase_inventory_reaction_exit",
            "probe_reaction_exit",
            "reaction_profit_trim",
            "v6_reaction_inventory_trim",
        }:
            return 0.35
        if any(token in reason for token in ("stop", "forced", "failed", "timeout", "hard", "invalidated", "stuck")):
            return 1.0
        return 0.70
    return 1.0


def _event_trade_cost(
    *,
    config: MarketStateConfig,
    new_events: list[dict[str, Any]],
    cost_rate: float,
    counters: Counter[str],
    cost_breakdown: dict[str, Counter[str]] | None = None,
) -> float:
    unit_weight = config.max_account_exposure / max(config.max_possible_units, 1e-12)
    total = 0.0
    for event in new_events:
        action = str(event.get("action") or "")
        if action not in {"add", "remove"}:
            continue
        qty = abs(float(event.get("qty") or 0.0))
        if qty <= 1e-12:
            continue
        multiplier = _event_cost_multiplier(event)
        event_cost = qty * unit_weight * cost_rate * multiplier
        total += event_cost
        counters["costed_order_events"] += 1
        if multiplier <= 0.50:
            counters["passive_cost_events"] += 1
        else:
            counters["aggressive_cost_events"] += 1
        if cost_breakdown is not None and event_cost > 0.0:
            reason = str(event.get("reason") or "unknown")
            role = str(event.get("role") or "unknown")
            side = str(event.get("side") or "unknown")
            cost_breakdown["by_action"][action] += event_cost
            cost_breakdown["by_reason"][reason] += event_cost
            cost_breakdown["by_role"][role] += event_cost
            cost_breakdown["by_side"][side] += event_cost
            cost_breakdown["by_action_reason"][f"{action}:{reason}"] += event_cost
            cost_breakdown["by_action_role"][f"{action}:{role}"] += event_cost
    return total


def _exit_removed_lots(
    *,
    events: list[dict[str, Any]],
    removed: list[RemovedLot],
    ts: datetime,
    action: str,
    reason: str,
    equity: float,
) -> dict[str, float]:
    stats = {
        "battle_exits": 0.0,
        "battle_success": 0.0,
        "battle_failed": 0.0,
        "removed_qty": 0.0,
        "realized_pnl_usd_units": 0.0,
    }
    for lot in removed:
        if lot.role == "battle":
            stats["battle_exits"] += 1.0
            if lot.pnl_usd_units > 0.0:
                stats["battle_success"] += 1.0
            else:
                stats["battle_failed"] += 1.0
        stats["removed_qty"] += lot.qty
        stats["realized_pnl_usd_units"] += lot.pnl_usd_units
        _record_event(
            events,
            ts=ts,
            action=action,
            side=lot.side,
            qty=lot.qty,
            price=lot.exit_price,
            reason=reason,
            equity=equity,
            extra={
                "role": lot.role,
                "entry": round(lot.entry, 2),
                "pnl_usd_units": round(lot.pnl_usd_units, 4),
                "entry_zone_score": int(getattr(lot, "zone_score", 0)),
                "entry_zone_id": str(getattr(lot, "zone_id", "")),
                "entry_zone_context": str(getattr(lot, "zone_context", "")),
            },
        )
    return stats


def _parse_event_ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _counter_payload(counter: Counter[str]) -> dict[str, int]:
    return {key: int(value) for key, value in sorted(counter.items())}


def _pnl_payload(counter: Counter[str]) -> dict[str, float]:
    return {key: round(float(value), 4) for key, value in sorted(counter.items())}


def _top_numeric_payload(counter: Counter[str], *, limit: int = 12, reverse: bool = True) -> dict[str, float]:
    items = sorted(counter.items(), key=lambda item: (float(item[1]), item[0]), reverse=reverse)
    return {key: round(float(value), 4) for key, value in items[:limit]}


def _top_prefixed_counter_payload(counters: Counter[str], prefix: str, *, limit: int = 12) -> dict[str, int]:
    values = Counter(
        {
            key[len(prefix) :]: int(value)
            for key, value in counters.items()
            if key.startswith(prefix) and int(value) > 0
        }
    )
    items = sorted(values.items(), key=lambda item: (-int(item[1]), item[0]))
    return {key: int(value) for key, value in items[:limit]}


def _prefixed_counter_payload(counters: Counter[str], prefix: str) -> dict[str, int]:
    values = Counter(
        {
            key[len(prefix) :]: int(value)
            for key, value in counters.items()
            if key.startswith(prefix) and int(value) > 0
        }
    )
    items = sorted(values.items(), key=lambda item: (-int(item[1]), item[0]))
    return {key: int(value) for key, value in items}


def _top_cost_pct_payload(counter: Counter[str], *, limit: int = 12) -> dict[str, float]:
    items = sorted(counter.items(), key=lambda item: (float(item[1]), item[0]), reverse=True)
    return {key: round(float(value) * 100.0, 4) for key, value in items[:limit]}


def _avg_payload(total: Counter[str], count: Counter[str], *, limit: int = 12, reverse: bool = True) -> dict[str, float]:
    values = Counter(
        {
            key: float(value) / max(float(count.get(key, 0)), 1.0)
            for key, value in total.items()
        }
    )
    return _top_numeric_payload(values, limit=limit, reverse=reverse)


def _zone_category_from_event_value(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "unknown"
    if ":" in raw:
        raw = ":".join(raw.split(":")[2:]) or raw
    raw = raw.replace(",", "|")
    return raw or "unknown"


def _context_bucket(value: float, cuts: tuple[float, ...]) -> str:
    value = float(value)
    previous = 0.0
    for cut in cuts:
        if value <= cut:
            return f"{previous:g}-{cut:g}"
        previous = cut
    return f">{cuts[-1]:g}" if cuts else "unknown"


def _zone_context_key(*, side: int, role: str, market: MarketState, zone: ZonePlan) -> str:
    extension_bucket = _context_bucket(zone.chase_extension_atr, (0.75, 1.50, 2.50, 4.00))
    breakout_bucket = _context_bucket(zone.chase_breakout_atr, (0.10, 0.50, 1.00, 1.50))
    return "|".join(
        (
            str(role or "unknown"),
            _side_label(side),
            _side_alignment(market, side),
            market.regime,
            zone.execution_context,
            f"ext_{extension_bucket}",
            f"break_{breakout_bucket}",
        )
    )


def _near_miss_context_allowed(
    config: MarketStateConfig,
    *,
    blockers: set[str],
    market: MarketState,
    side: int,
    zone: ZonePlan,
) -> bool:
    allowed_reasons = {str(item) for item in getattr(config, "near_miss_probe_allowed_soft_reasons", ()) or ()}
    if allowed_reasons and (not blockers or not blockers.issubset(allowed_reasons)):
        return False
    allowed_alignments = {str(item) for item in getattr(config, "near_miss_probe_allowed_alignments", ()) or ()}
    if allowed_alignments and _side_alignment(market, side) not in allowed_alignments:
        return False
    allowed_contexts = {
        str(item) for item in getattr(config, "near_miss_probe_allowed_execution_contexts", ()) or ()
    }
    if allowed_contexts and str(zone.execution_context or "") not in allowed_contexts:
        return False
    allowed_regimes = {str(item) for item in getattr(config, "near_miss_probe_allowed_regimes", ()) or ()}
    if allowed_regimes and str(market.regime or "") not in allowed_regimes:
        return False
    return True


def _no_trade_candidate_side(*, market: MarketState, zone: ZonePlan) -> int:
    if zone.long_score > zone.short_score:
        return 1
    if zone.short_score > zone.long_score:
        return -1
    if zone.long_score == zone.short_score and zone.long_score > 0 and market.bias:
        return market.bias
    return 0


def _no_trade_candidate_score(zone: ZonePlan, side: int) -> int:
    if side > 0:
        return int(zone.long_score)
    if side < 0:
        return int(zone.short_score)
    return int(max(zone.long_score, zone.short_score))


def _no_trade_candidate_reason_stack(zone: ZonePlan, side: int) -> int:
    if side > 0:
        return int(zone.long_reason_stack)
    if side < 0:
        return int(zone.short_reason_stack)
    return int(max(zone.long_reason_stack, zone.short_reason_stack))


def _no_trade_context_key(*, reason: str, side: int, market: MarketState, zone: ZonePlan) -> str:
    score = _no_trade_candidate_score(zone, side)
    reason_stack = _no_trade_candidate_reason_stack(zone, side)
    score_edge = abs(int(zone.long_score) - int(zone.short_score))
    extension_bucket = _context_bucket(zone.chase_extension_atr, (0.75, 1.50, 2.50, 4.00))
    breakout_bucket = _context_bucket(zone.chase_breakout_atr, (0.10, 0.50, 1.00, 1.50))
    score_bucket = _context_bucket(score, (3.0, 5.0, 7.0, 9.0))
    edge_bucket = _context_bucket(score_edge, (1.0, 2.0, 4.0, 6.0))
    stack_bucket = _context_bucket(reason_stack, (1.0, 2.0, 3.0, 4.0))
    alignment = "neutral" if side == 0 else _side_alignment(market, side)
    return "|".join(
        (
            str(reason or "unknown"),
            _side_label(side),
            alignment,
            str(market.regime or "unknown"),
            str(zone.execution_context or "unknown"),
            f"score_{score_bucket}",
            f"edge_{edge_bucket}",
            f"stack_{stack_bucket}",
            f"ext_{extension_bucket}",
            f"break_{breakout_bucket}",
        )
    )


def _max_share(counter: Counter[str]) -> float:
    total = sum(counter.values())
    if total <= 0:
        return 0.0
    return max(counter.values()) / total


def _max_consecutive_add_side(add_events: list[dict[str, Any]]) -> int:
    max_run = 0
    current_side = ""
    current_run = 0
    for event in add_events:
        side = str(event.get("side") or "")
        if side == current_side:
            current_run += 1
        else:
            current_side = side
            current_run = 1
        max_run = max(max_run, current_run)
    return max_run


_TREND_ALIGNED_REGIMES_BY_SIDE = {
    "long": {"uptrend", "one_way_long"},
    "short": {"downtrend", "one_way_short"},
}
_KNOWN_MARKET_REGIMES = {
    "bad_rr_center",
    "downtrend",
    "mixed",
    "one_way_long",
    "one_way_short",
    "range_or_transition",
    "uptrend",
}


def _event_entry_regime(event: dict[str, Any]) -> str:
    raw_regime = str(event.get("regime") or "")
    if raw_regime in _KNOWN_MARKET_REGIMES:
        return raw_regime
    for key in ("zone_context", "entry_zone_context"):
        for part in str(event.get(key) or "").split("|"):
            if part in _KNOWN_MARKET_REGIMES:
                return part
    return raw_regime or "unknown"


def _side_imbalance_context(
    *,
    add_events: list[dict[str, Any]],
    add_by_side: Counter[str],
    pnl_by_side: Counter[str],
    directional_adds: int,
    side_imbalance_min_directional_adds: int,
    side_imbalance_share: float,
    trend_aligned_min_share: float,
) -> dict[str, Any]:
    long_adds = int(add_by_side.get("long", 0))
    short_adds = int(add_by_side.get("short", 0))
    if directional_adds <= 0:
        return {
            "status": "no_directional_adds",
            "flag_suppressed": False,
            "dominant_side": "none",
            "dominant_side_adds": 0,
            "directional_adds": 0,
            "dominant_side_share": 0.0,
            "dominant_side_trend_aligned_adds": 0,
            "dominant_side_trend_aligned_share": 0.0,
            "dominant_side_realized_pnl_usd_units": 0.0,
            "opposite_side_realized_pnl_usd_units": 0.0,
            "total_side_realized_pnl_usd_units": 0.0,
            "dominant_side_add_by_regime": {},
        }

    dominant_side = "long" if long_adds >= short_adds else "short"
    opposite_side = "short" if dominant_side == "long" else "long"
    dominant_side_adds = int(add_by_side.get(dominant_side, 0))
    dominant_side_share = dominant_side_adds / max(directional_adds, 1)
    dominant_add_by_regime: Counter[str] = Counter(
        _event_entry_regime(event)
        for event in add_events
        if str(event.get("side") or "unknown") == dominant_side
    )
    aligned_regimes = _TREND_ALIGNED_REGIMES_BY_SIDE.get(dominant_side, set())
    aligned_adds = sum(dominant_add_by_regime.get(regime, 0) for regime in aligned_regimes)
    aligned_share = aligned_adds / max(dominant_side_adds, 1)
    dominant_side_pnl = float(pnl_by_side.get(dominant_side, 0.0))
    opposite_side_pnl = float(pnl_by_side.get(opposite_side, 0.0))
    total_side_pnl = float(pnl_by_side.get("long", 0.0) + pnl_by_side.get("short", 0.0))
    imbalance_triggered = (
        directional_adds >= side_imbalance_min_directional_adds
        and dominant_side_share >= side_imbalance_share
    )
    trend_aligned = (
        imbalance_triggered
        and aligned_share >= trend_aligned_min_share
        and dominant_side_pnl > 0.0
        and total_side_pnl > 0.0
    )
    status = "trend_aligned" if trend_aligned else "imbalanced" if imbalance_triggered else "balanced"

    return {
        "status": status,
        "flag_suppressed": bool(trend_aligned),
        "dominant_side": dominant_side,
        "dominant_side_adds": dominant_side_adds,
        "directional_adds": int(directional_adds),
        "dominant_side_share": round(dominant_side_share, 4),
        "dominant_side_trend_aligned_adds": int(aligned_adds),
        "dominant_side_trend_aligned_share": round(aligned_share, 4),
        "dominant_side_realized_pnl_usd_units": round(dominant_side_pnl, 4),
        "opposite_side_realized_pnl_usd_units": round(opposite_side_pnl, 4),
        "total_side_realized_pnl_usd_units": round(total_side_pnl, 4),
        "dominant_side_add_by_regime": _counter_payload(dominant_add_by_regime),
    }


def _month_concentration_context(
    *,
    add_by_month: Counter[str],
    add_total: int,
    active_months: int,
    total_months: int,
    concentration_min_adds: int,
    month_concentration_share: float,
    month_concentration_borderline_share: float,
    full_coverage_relief_gap: float,
    sample_tier: str,
) -> dict[str, Any]:
    dominant_month, dominant_month_adds = (
        max(add_by_month.items(), key=lambda item: (int(item[1]), str(item[0])))
        if add_by_month
        else ("none", 0)
    )
    dominant_month_share = int(dominant_month_adds) / max(add_total, 1)
    hard = (
        total_months >= 4
        and add_total >= concentration_min_adds
        and dominant_month_share >= month_concentration_share
    )
    borderline = (
        not hard
        and total_months >= 4
        and add_total >= concentration_min_adds
        and dominant_month_share >= month_concentration_borderline_share
    )
    full_coverage = active_months >= min(max(int(total_months), 1), 4)
    broadly_active_relief = (
        borderline
        and sample_tier == "short"
        and full_coverage
        and dominant_month_share <= month_concentration_share - full_coverage_relief_gap
    )
    status = (
        "hard"
        if hard
        else "borderline_broadly_active"
        if broadly_active_relief
        else "borderline"
        if borderline
        else "balanced"
    )
    return {
        "status": status,
        "flag_suppressed": bool(broadly_active_relief),
        "dominant_month": str(dominant_month),
        "dominant_month_adds": int(dominant_month_adds),
        "dominant_month_share": round(dominant_month_share, 4),
        "active_months": int(active_months),
        "total_months": int(total_months),
        "full_coverage": bool(full_coverage),
        "monthly_adds": _counter_payload(add_by_month),
    }


def _role_concentration_context(
    *,
    known_add_by_role: Counter[str],
    pnl_by_role: Counter[str],
    role_adds: int,
    role_concentration_min_add_events: int,
    role_concentration_share: float,
    role_concentration_borderline_share: float,
    profitable_mix_relief_gap: float,
) -> dict[str, Any]:
    dominant_role, dominant_role_adds = (
        max(known_add_by_role.items(), key=lambda item: (int(item[1]), str(item[0])))
        if known_add_by_role
        else ("none", 0)
    )
    dominant_role_share = int(dominant_role_adds) / max(role_adds, 1)
    dominant_role_pnl = float(pnl_by_role.get(dominant_role, 0.0))
    total_role_pnl = float(sum(pnl_by_role.values()))
    hard = (
        role_adds >= role_concentration_min_add_events
        and dominant_role_share >= role_concentration_share
    )
    borderline = (
        not hard
        and role_adds >= role_concentration_min_add_events
        and dominant_role_share >= role_concentration_borderline_share
    )
    profitable_mix_relief = (
        borderline
        and len(known_add_by_role) >= 2
        and dominant_role_share <= role_concentration_share - profitable_mix_relief_gap
        and dominant_role_pnl > 0.0
        and total_role_pnl > 0.0
    )
    status = (
        "hard"
        if hard
        else "borderline_profitable_mix"
        if profitable_mix_relief
        else "borderline"
        if borderline
        else "balanced"
    )
    return {
        "status": status,
        "flag_suppressed": bool(profitable_mix_relief),
        "dominant_role": str(dominant_role),
        "dominant_role_adds": int(dominant_role_adds),
        "dominant_role_share": round(dominant_role_share, 4),
        "known_role_count": int(len(known_add_by_role)),
        "role_adds": int(role_adds),
        "dominant_role_realized_pnl_usd_units": round(dominant_role_pnl, 4),
        "total_role_realized_pnl_usd_units": round(total_role_pnl, 4),
        "add_by_role": _counter_payload(known_add_by_role),
    }


def _capacity_structure_context(
    *,
    config: MarketStateConfig,
    add_total: int,
    add_by_role: Counter[str],
    battle_add_ratio: float,
    winner_pyramid_add_count: int,
    battle_capacity_saturated: bool,
) -> dict[str, Any]:
    max_possible_units = max(0.0, float(getattr(config, "max_possible_units", 0.0) or 0.0))
    base_add_units = max(0.0, float(getattr(config, "base_add_units", 0.0) or 0.0))
    base_max_units = max(0.0, float(getattr(config, "base_max_units", 0.0) or 0.0))
    max_account_exposure = max(0.0, float(getattr(config, "max_account_exposure", 0.0) or 0.0))
    capacity_after_first_base = max(max_possible_units - base_add_units, 0.0)
    unit_exposure = max_account_exposure / max(max_possible_units, 1e-12)
    base_add_share = int(add_by_role.get("base", 0)) / max(int(add_total), 1)
    winner_pyramid_add_ratio = int(winner_pyramid_add_count) / max(int(add_total), 1)
    scale_in_capacity = max_possible_units > base_add_units + 1e-12
    if not scale_in_capacity and winner_pyramid_add_count > 0:
        status = "single_unit_winner_refill_active"
    elif battle_capacity_saturated and battle_add_ratio <= 0.015:
        status = "battle_capacity_saturated"
    elif not scale_in_capacity:
        status = "single_unit_full_entry"
    else:
        status = "scale_in_capacity_available"
    return {
        "status": status,
        "scale_in_capacity_available": bool(scale_in_capacity),
        "max_possible_units": round(max_possible_units, 6),
        "base_add_units": round(base_add_units, 6),
        "base_max_units": round(base_max_units, 6),
        "capacity_after_first_base_units": round(capacity_after_first_base, 6),
        "max_account_exposure": round(max_account_exposure, 6),
        "unit_account_exposure": round(unit_exposure, 6),
        "base_add_account_exposure": round(base_add_units * unit_exposure, 6),
        "base_add_share": round(base_add_share, 4),
        "battle_add_ratio": round(float(battle_add_ratio), 4),
        "winner_pyramid_add_count": int(winner_pyramid_add_count),
        "winner_pyramid_add_ratio": round(float(winner_pyramid_add_ratio), 4),
    }


def _diagnostic_thresholds(*, total_months: int, add_total: int) -> dict[str, Any]:
    months = max(int(total_months), 1)
    adds = max(int(add_total), 0)
    short_sample = months <= 4 or adds < 30
    expected_add_events = max(8, math.ceil(months * 3.0))
    concentration_min_add_events = max(18, math.ceil(months * 4.0))
    return {
        "sample_tier": "short" if short_sample else "normal",
        "expected_add_events": int(expected_add_events),
        "concentration_min_add_events": int(concentration_min_add_events),
        "overtrading_add_events": 1500,
        "side_imbalance_min_directional_adds": int(max(12, expected_add_events)),
        "side_imbalance_share": 0.85 if short_sample else 0.70,
        "side_imbalance_trend_aligned_min_share": 0.70,
        "role_concentration_min_add_events": int(max(12, expected_add_events)),
        "role_concentration_share": 0.90 if short_sample else 0.80,
        "role_concentration_borderline_share": 0.85 if short_sample else 0.75,
        "poor_month_coverage_min_months": 4,
        "poor_month_coverage_active_month_share": 0.65,
        "poor_month_coverage_min_active_months": int(max(3, math.ceil(months * 0.65))),
        "month_concentration_share": 0.50 if short_sample else 0.25,
        "month_concentration_borderline_share": 0.45 if short_sample else 0.25,
        "month_concentration_borderline_full_coverage_relief_gap": 0.01,
        "day_concentration_share": 0.14 if short_sample else 0.08,
        "kst_hour_concentration_share": 0.24 if short_sample else 0.18,
        "role_concentration_borderline_profitable_relief_gap": 0.02,
        "repair_stop_per_add": 0.30,
        "one_way_forced_trim_per_add": 0.50 if short_sample else 0.25,
        "turnover_events_per_add": 3.25 if short_sample else 2.50,
        "profit_or_reaction_trim_underuse": 0.08,
        "profit_trim_underuse_min_removes": 50,
        "battle_underuse_min_adds": 100,
        "battle_add_per_add": 0.015,
        "probe_overuse_min_adds": 100,
        "probe_add_per_add": 0.35,
        "chase_failed_fast_exit_min_adds": 20,
        "chase_failed_fast_exit_per_chase_add": 0.45,
        "probe_failed_fast_exit_min_adds": 20,
        "probe_failed_fast_exit_per_probe_add": 0.45,
    }


def _event_diagnostics(
    *,
    events: list[dict[str, Any]],
    counters: Counter[str],
    exposure_side_bars: Counter[str],
    exposure_bars: int,
    total_months: int,
    config: MarketStateConfig,
) -> dict[str, Any]:
    add_events = [event for event in events if event.get("action") == "add"]
    remove_events = [event for event in events if event.get("action") == "remove"]
    add_total = len(add_events)
    remove_total = len(remove_events)

    add_by_side: Counter[str] = Counter(str(event.get("side") or "unknown") for event in add_events)
    add_by_role: Counter[str] = Counter(str(event.get("role") or str(event.get("reason") or "").split("_", 1)[0] or "unknown") for event in add_events)
    add_by_reason: Counter[str] = Counter(str(event.get("reason") or "unknown") for event in add_events)
    add_by_zone_category: Counter[str] = Counter(
        _zone_category_from_event_value(event.get("zone") or event.get("zone_key") or "unknown")
        for event in add_events
    )
    add_by_entry_context: Counter[str] = Counter(str(event.get("zone_context") or "unknown") for event in add_events)
    add_by_router_mode: Counter[str] = Counter(str(event.get("router_mode") or "legacy") for event in add_events)
    remove_by_router_mode: Counter[str] = Counter(str(event.get("router_mode") or "legacy") for event in remove_events)
    remove_by_reason: Counter[str] = Counter(str(event.get("reason") or "unknown") for event in remove_events)
    remove_by_role: Counter[str] = Counter(str(event.get("role") or "unknown") for event in remove_events)
    add_by_month: Counter[str] = Counter()
    add_by_utc_hour: Counter[str] = Counter()
    add_by_kst_hour: Counter[str] = Counter()
    add_by_weekday: Counter[str] = Counter()
    add_by_day: Counter[str] = Counter()
    remove_by_utc_hour: Counter[str] = Counter()
    remove_by_kst_hour: Counter[str] = Counter()
    pnl_by_utc_hour: Counter[str] = Counter()
    pnl_by_kst_hour: Counter[str] = Counter()
    pnl_by_side: Counter[str] = Counter()
    pnl_by_role: Counter[str] = Counter()
    pnl_by_reason: Counter[str] = Counter()
    pnl_by_entry_zone_score: Counter[str] = Counter()
    pnl_by_entry_zone_category: Counter[str] = Counter()
    pnl_by_entry_context: Counter[str] = Counter()
    remove_qty_by_reason: Counter[str] = Counter()
    remove_by_reason_side: Counter[str] = Counter()
    pnl_by_reason_side: Counter[str] = Counter()
    remove_by_reason_context: Counter[str] = Counter()
    pnl_by_reason_context: Counter[str] = Counter()
    pnl_by_exit_reason_context_totals: dict[str, Counter[str]] = defaultdict(Counter)
    remove_by_exit_reason_context_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for event in add_events:
        ts = _parse_event_ts(event.get("ts"))
        if ts is None:
            continue
        add_by_month[ts.strftime("%Y-%m")] += 1
        add_by_day[ts.strftime("%Y-%m-%d")] += 1
        add_by_utc_hour[f"{ts.hour:02d}"] += 1
        add_by_kst_hour[f"{(ts.hour + 9) % 24:02d}"] += 1
        add_by_weekday[ts.strftime("%a")] += 1

    for event in remove_events:
        side = str(event.get("side") or "unknown")
        role = str(event.get("role") or "unknown")
        pnl = float(event.get("pnl_usd_units") or 0.0)
        qty = float(event.get("qty") or 0.0)
        reason = str(event.get("reason") or "unknown")
        reason_side = f"{reason}|{side}"
        ts = _parse_event_ts(event.get("ts"))
        if ts is not None:
            utc_hour = f"{ts.hour:02d}"
            kst_hour = f"{(ts.hour + 9) % 24:02d}"
            remove_by_utc_hour[utc_hour] += 1
            remove_by_kst_hour[kst_hour] += 1
            pnl_by_utc_hour[utc_hour] += pnl
            pnl_by_kst_hour[kst_hour] += pnl
        pnl_by_side[side] += pnl
        pnl_by_role[role] += pnl
        pnl_by_reason[reason] += pnl
        remove_by_reason_side[reason_side] += 1
        pnl_by_reason_side[reason_side] += pnl
        zone_score = str(event.get("entry_zone_score") or "unknown")
        zone_category = _zone_category_from_event_value(event.get("entry_zone_id") or "unknown")
        entry_context = str(event.get("entry_zone_context") or "unknown")
        pnl_by_entry_zone_score[zone_score] += pnl
        pnl_by_entry_zone_category[zone_category or "unknown"] += pnl
        pnl_by_entry_context[entry_context or "unknown"] += pnl
        reason_context = f"{reason}|{entry_context or 'unknown'}"
        remove_by_reason_context[reason_context] += 1
        pnl_by_reason_context[reason_context] += pnl
        pnl_by_exit_reason_context_totals[reason][entry_context or "unknown"] += pnl
        remove_by_exit_reason_context_counts[reason][entry_context or "unknown"] += 1
        remove_qty_by_reason[reason] += qty

    pnl_per_add_by_entry_zone_category = {
        key: round(float(value) / max(add_by_zone_category.get(key, 0), 1), 4)
        for key, value in sorted(pnl_by_entry_zone_category.items())
    }
    pnl_per_add_by_entry_context = {
        key: round(float(value) / max(add_by_entry_context.get(key, 0), 1), 4)
        for key, value in sorted(pnl_by_entry_context.items())
    }

    long_adds = add_by_side.get("long", 0)
    short_adds = add_by_side.get("short", 0)
    directional_adds = long_adds + short_adds
    long_add_share = long_adds / directional_adds if directional_adds else 0.0
    short_add_share = short_adds / directional_adds if directional_adds else 0.0
    total_role_adds = sum(add_by_role.values())
    known_add_by_role = Counter(
        {role: count for role, count in add_by_role.items() if role not in {"", "unknown"}}
    )
    role_adds = sum(known_add_by_role.values())
    dominant_add_role, dominant_add_role_count = (
        max(known_add_by_role.items(), key=lambda item: (int(item[1]), str(item[0])))
        if known_add_by_role
        else ("none", 0)
    )
    max_role_add_share = dominant_add_role_count / role_adds if role_adds else 0.0
    active_months = len(add_by_month)
    active_days = len(add_by_day)
    max_month_share = _max_share(add_by_month)
    max_day_share = _max_share(add_by_day)
    max_hour_share = _max_share(add_by_kst_hour)
    exposure_long_share = exposure_side_bars.get("long", 0) / max(exposure_bars, 1)
    exposure_short_share = exposure_side_bars.get("short", 0) / max(exposure_bars, 1)
    exposure_flat_share = exposure_side_bars.get("flat", 0) / max(exposure_bars, 1)
    repair_stop_ratio = counters.get("repair_stop_trims", 0) / max(add_total, 1)
    one_way_trim_ratio = counters.get("one_way_forced_trims", 0) / max(add_total, 1)
    profit_trim_ratio = counters.get("profit_trims", 0) / max(remove_total, 1)
    reaction_trim_ratio = counters.get("reaction_inventory_trims", 0) / max(remove_total, 1)
    battle_add_ratio = counters.get("battle_adds", 0) / max(add_total, 1)
    battle_capacity_saturated = config.max_possible_units <= config.base_add_units + 1e-12
    probe_add_ratio = counters.get("probe_adds", 0) / max(add_total, 1)
    chase_add_ratio = counters.get("chase_adds", 0) / max(add_total, 1)
    chase_failed_ratio = counters.get("chase_failed_fast_exits", 0) / max(counters.get("chase_adds", 0), 1)
    probe_failed_ratio = counters.get("probe_failed_fast_exits", 0) / max(counters.get("probe_adds", 0), 1)
    turnover_per_add = counters.get("turnover_events", 0) / max(add_total, 1)

    thresholds = _diagnostic_thresholds(total_months=total_months, add_total=add_total)
    concentration_min_adds = int(thresholds["concentration_min_add_events"])
    side_imbalance_min_directional_adds = int(thresholds["side_imbalance_min_directional_adds"])
    side_imbalance_share = float(thresholds["side_imbalance_share"])
    role_concentration_min_add_events = int(thresholds["role_concentration_min_add_events"])
    expected_add_events = int(thresholds["expected_add_events"])
    side_imbalance_context = _side_imbalance_context(
        add_events=add_events,
        add_by_side=add_by_side,
        pnl_by_side=pnl_by_side,
        directional_adds=directional_adds,
        side_imbalance_min_directional_adds=side_imbalance_min_directional_adds,
        side_imbalance_share=side_imbalance_share,
        trend_aligned_min_share=float(thresholds["side_imbalance_trend_aligned_min_share"]),
    )
    month_concentration_context = _month_concentration_context(
        add_by_month=add_by_month,
        add_total=add_total,
        active_months=active_months,
        total_months=total_months,
        concentration_min_adds=concentration_min_adds,
        month_concentration_share=float(thresholds["month_concentration_share"]),
        month_concentration_borderline_share=float(thresholds["month_concentration_borderline_share"]),
        full_coverage_relief_gap=float(thresholds["month_concentration_borderline_full_coverage_relief_gap"]),
        sample_tier=str(thresholds["sample_tier"]),
    )
    role_concentration_context = _role_concentration_context(
        known_add_by_role=known_add_by_role,
        pnl_by_role=pnl_by_role,
        role_adds=role_adds,
        role_concentration_min_add_events=role_concentration_min_add_events,
        role_concentration_share=float(thresholds["role_concentration_share"]),
        role_concentration_borderline_share=float(thresholds["role_concentration_borderline_share"]),
        profitable_mix_relief_gap=float(thresholds["role_concentration_borderline_profitable_relief_gap"]),
    )
    capacity_structure_context = _capacity_structure_context(
        config=config,
        add_total=add_total,
        add_by_role=add_by_role,
        battle_add_ratio=battle_add_ratio,
        winner_pyramid_add_count=int(counters.get("winner_pyramid_adds", 0)),
        battle_capacity_saturated=battle_capacity_saturated,
    )
    enough_orders_for_coverage = add_total >= expected_add_events
    soft_circuit_cooldown_share = counters.get("equity_soft_circuit_cooldown_bars", 0) / max(exposure_bars, 1)
    soft_circuit_force_flat = bool(getattr(config, "equity_soft_circuit_force_flat", False))
    soft_circuit_zero_size = float(getattr(config, "equity_soft_circuit_size_mult", 1.0) or 0.0) <= 1e-12
    soft_circuit_prearmed = int(getattr(config, "equity_soft_circuit_prearm_bars", 0) or 0) > 0
    soft_circuit_diagnostic = (
        exposure_bars > 0
        and soft_circuit_force_flat
        and soft_circuit_zero_size
        and soft_circuit_prearmed
    )
    risk_off_active_share = _clamp(1.0 - soft_circuit_cooldown_share, 0.0, 1.0)
    risk_adjusted_expected_add_events = expected_add_events
    if soft_circuit_diagnostic and soft_circuit_cooldown_share >= 0.50:
        risk_adjusted_expected_add_events = max(1, math.ceil(expected_add_events * risk_off_active_share * 0.60))
    thresholds["risk_adjusted_expected_add_events"] = int(risk_adjusted_expected_add_events)
    thresholds["risk_off_active_share"] = round(risk_off_active_share, 4)
    thresholds["risk_off_adjustment_min_cooldown_share"] = 0.50
    thresholds["risk_off_adjustment_active_expected_mult"] = 0.60
    risk_off_idle = (
        add_total < expected_add_events
        and soft_circuit_diagnostic
        and soft_circuit_cooldown_share >= 0.90
        and exposure_flat_share >= 0.95
    )
    risk_off_partial = (
        not risk_off_idle
        and add_total < expected_add_events
        and soft_circuit_diagnostic
        and soft_circuit_cooldown_share >= 0.50
        and add_total >= risk_adjusted_expected_add_events
    )
    low_activity_min_adds = max(1, math.ceil(expected_add_events * 0.75))
    profitable_side_pnl = {
        side: float(pnl_by_side.get(side, 0.0))
        for side in ("long", "short")
        if add_by_side.get(side, 0) > 0
    }
    profitable_low_activity_day_share_limit = max(
        float(thresholds["day_concentration_share"]),
        0.20,
    )
    thresholds["profitable_low_activity_max_day_share"] = round(
        float(profitable_low_activity_day_share_limit),
        4,
    )
    profitable_low_activity = (
        not (risk_off_idle or risk_off_partial)
        and add_total < expected_add_events
        and add_total >= low_activity_min_adds
        and active_months >= min(max(total_months, 1), 3)
        and long_adds > 0
        and short_adds > 0
        and sum(float(value) for value in pnl_by_side.values()) > 0.0
        and bool(profitable_side_pnl)
        and all(value > 0.0 for value in profitable_side_pnl.values())
        and max_day_share <= profitable_low_activity_day_share_limit
        and max_hour_share < float(thresholds["kst_hour_concentration_share"])
        and max_month_share <= 0.60
    )
    thresholds["profitable_low_activity_min_add_events"] = int(low_activity_min_adds)
    thresholds["profitable_low_activity_max_month_share"] = 0.60

    borderline_flags: list[str] = []
    flags: list[str] = []
    if add_total < expected_add_events and not (
        risk_off_idle or risk_off_partial or profitable_low_activity
    ):
        flags.append("too_few_orders")
    if add_total > int(thresholds["overtrading_add_events"]):
        flags.append("overtrading")
    if (
        directional_adds >= side_imbalance_min_directional_adds
        and max(long_add_share, short_add_share) >= side_imbalance_share
        and side_imbalance_context.get("status") != "trend_aligned"
    ):
        flags.append("side_imbalance")
    if role_concentration_context.get("status") == "hard":
        flags.append("role_concentration")
    elif role_concentration_context.get("status") == "borderline":
        borderline_flags.append("role_concentration")
    if (
        total_months >= int(thresholds["poor_month_coverage_min_months"])
        and enough_orders_for_coverage
        and active_months < int(thresholds["poor_month_coverage_min_active_months"])
    ):
        flags.append("poor_month_coverage")
    if month_concentration_context.get("status") == "hard":
        flags.append("month_concentration")
    elif month_concentration_context.get("status") == "borderline":
        borderline_flags.append("month_concentration")
    if add_total >= concentration_min_adds and max_day_share >= float(thresholds["day_concentration_share"]):
        flags.append("day_concentration")
    if add_total >= concentration_min_adds and max_hour_share >= float(thresholds["kst_hour_concentration_share"]):
        flags.append("kst_hour_concentration")
    if repair_stop_ratio >= float(thresholds["repair_stop_per_add"]):
        flags.append("repair_stop_overuse")
    if one_way_trim_ratio > float(thresholds["one_way_forced_trim_per_add"]) + 1e-12:
        flags.append("one_way_forced_trim_overuse")
    elif one_way_trim_ratio >= float(thresholds["one_way_forced_trim_per_add"]):
        borderline_flags.append("one_way_forced_trim_overuse")
    if (
        profit_trim_ratio + reaction_trim_ratio <= float(thresholds["profit_or_reaction_trim_underuse"])
        and remove_total >= int(thresholds["profit_trim_underuse_min_removes"])
    ):
        flags.append("profit_trim_underuse")
    if (
        battle_add_ratio <= float(thresholds["battle_add_per_add"])
        and add_total >= int(thresholds["battle_underuse_min_adds"])
        and battle_capacity_saturated
    ):
        flags.append("battle_capacity_saturated")
    elif battle_add_ratio <= float(thresholds["battle_add_per_add"]) and add_total >= int(
        thresholds["battle_underuse_min_adds"]
    ):
        flags.append("battle_underuse")
    if probe_add_ratio >= float(thresholds["probe_add_per_add"]) and add_total >= int(thresholds["probe_overuse_min_adds"]):
        flags.append("probe_overuse")
    if (
        chase_failed_ratio >= float(thresholds["chase_failed_fast_exit_per_chase_add"])
        and counters.get("chase_adds", 0) >= int(thresholds["chase_failed_fast_exit_min_adds"])
    ):
        flags.append("chase_failed_fast_exit_overuse")
    if (
        probe_failed_ratio >= float(thresholds["probe_failed_fast_exit_per_probe_add"])
        and counters.get("probe_adds", 0) >= int(thresholds["probe_failed_fast_exit_min_adds"])
    ):
        flags.append("probe_failed_fast_exit_overuse")
    if turnover_per_add >= float(thresholds["turnover_events_per_add"]):
        flags.append("high_turnover_per_add")
    if counters.get("liquidations", 0) > 0:
        flags.append("liquidation_occurred")
    if counters.get("account_ruin_events", 0) > 0:
        flags.append("account_ruin")

    if any(flag in flags for flag in {"liquidation_occurred", "account_ruin", "poor_month_coverage"}):
        health = "fail"
    elif flags:
        health = "watch"
    else:
        health = "ok"

    return {
        "health": health,
        "flags": flags,
        "borderline_flags": borderline_flags,
        "sample_mode": (
            "risk_off_idle"
            if risk_off_idle
            else "risk_off_partial"
            if risk_off_partial
            else "profitable_low_activity"
            if profitable_low_activity
            else "active"
        ),
        "profitable_low_activity_context": {
            "status": "suppressed" if profitable_low_activity else "inactive",
            "min_add_events": int(low_activity_min_adds),
            "active_months": int(active_months),
            "max_month_add_share": round(max_month_share, 4),
            "max_day_add_share": round(max_day_share, 4),
            "max_kst_hour_add_share": round(max_hour_share, 4),
            "realized_pnl_usd_units_by_active_side": {
                side: round(value, 4) for side, value in profitable_side_pnl.items()
            },
        },
        "risk_off_cooldown_share": round(soft_circuit_cooldown_share, 4),
        "diagnostic_thresholds": thresholds,
        "side_imbalance_context": side_imbalance_context,
        "month_concentration_context": month_concentration_context,
        "role_concentration_context": role_concentration_context,
        "capacity_structure_context": capacity_structure_context,
        "add_events": add_total,
        "remove_events": remove_total,
        "no_trade_contexts": _prefixed_counter_payload(counters, "no_trade_context::"),
        "top_no_trade_contexts": _top_prefixed_counter_payload(counters, "no_trade_context::", limit=12),
        "no_trade_reason_side_counts": _top_prefixed_counter_payload(
            counters,
            "no_trade_reason_side::",
            limit=24,
        ),
        "no_trade_reason_regime_counts": _top_prefixed_counter_payload(
            counters,
            "no_trade_reason_regime::",
            limit=24,
        ),
        "add_by_side": _counter_payload(add_by_side),
        "add_side_share": {"long": round(long_add_share, 4), "short": round(short_add_share, 4)},
        "add_by_role": _counter_payload(add_by_role),
        "add_role_share": {
            role: round(count / max(total_role_adds, 1), 4)
            for role, count in sorted(add_by_role.items())
        },
        "dominant_add_role": str(dominant_add_role),
        "max_role_add_share": round(max_role_add_share, 4),
        "add_by_reason": _counter_payload(add_by_reason),
        "add_by_zone_category": _counter_payload(add_by_zone_category),
        "add_by_entry_context": _counter_payload(add_by_entry_context),
        "add_by_router_mode": _counter_payload(add_by_router_mode),
        "remove_by_router_mode": _counter_payload(remove_by_router_mode),
        "remove_by_reason": _counter_payload(remove_by_reason),
        "remove_by_role": _counter_payload(remove_by_role),
        "remove_by_utc_hour": _counter_payload(remove_by_utc_hour),
        "remove_by_kst_hour": _counter_payload(remove_by_kst_hour),
        "realized_pnl_usd_units_by_utc_hour": _pnl_payload(pnl_by_utc_hour),
        "realized_pnl_usd_units_by_kst_hour": _pnl_payload(pnl_by_kst_hour),
        "realized_pnl_usd_units_per_remove_by_kst_hour": _avg_payload(
            pnl_by_kst_hour,
            remove_by_kst_hour,
            limit=24,
            reverse=False,
        ),
        "realized_pnl_usd_units_by_side": _pnl_payload(pnl_by_side),
        "realized_pnl_usd_units_by_role": _pnl_payload(pnl_by_role),
        "realized_pnl_usd_units_by_remove_reason": _pnl_payload(pnl_by_reason),
        "remove_by_reason_side": _counter_payload(remove_by_reason_side),
        "realized_pnl_usd_units_by_remove_reason_side": _pnl_payload(pnl_by_reason_side),
        "realized_pnl_usd_units_by_entry_zone_score": _pnl_payload(pnl_by_entry_zone_score),
        "realized_pnl_usd_units_by_entry_zone_category": _pnl_payload(pnl_by_entry_zone_category),
        "realized_pnl_usd_units_per_add_by_entry_zone_category": pnl_per_add_by_entry_zone_category,
        "realized_pnl_usd_units_by_entry_context": _pnl_payload(pnl_by_entry_context),
        "realized_pnl_usd_units_per_add_by_entry_context": pnl_per_add_by_entry_context,
        "remove_qty_by_reason": _pnl_payload(remove_qty_by_reason),
        "worst_realized_pnl_usd_units_by_entry_context": _top_numeric_payload(
            pnl_by_entry_context,
            limit=12,
            reverse=False,
        ),
        "best_realized_pnl_usd_units_by_entry_context": _top_numeric_payload(
            pnl_by_entry_context,
            limit=12,
            reverse=True,
        ),
        "worst_avg_pnl_usd_units_by_remove_reason_context": _avg_payload(
            pnl_by_reason_context,
            remove_by_reason_context,
            limit=12,
            reverse=False,
        ),
        "worst_total_pnl_usd_units_by_remove_reason_context": _top_numeric_payload(
            pnl_by_reason_context,
            limit=12,
            reverse=False,
        ),
        "one_way_forced_trim_hotspots": {
            "counts_by_entry_context": _top_numeric_payload(
                remove_by_exit_reason_context_counts.get("one_way_against_forced_trim", Counter()),
                limit=12,
                reverse=True,
            ),
            "pnl_by_entry_context": _top_numeric_payload(
                pnl_by_exit_reason_context_totals.get("one_way_against_forced_trim", Counter()),
                limit=12,
                reverse=False,
            ),
            "avg_pnl_by_entry_context": _avg_payload(
                pnl_by_exit_reason_context_totals.get("one_way_against_forced_trim", Counter()),
                remove_by_exit_reason_context_counts.get("one_way_against_forced_trim", Counter()),
                limit=12,
                reverse=False,
            ),
        },
        "hard_time_exit_hotspots": {
            "counts_by_entry_context": _top_numeric_payload(
                remove_by_exit_reason_context_counts.get("hard_intraday_time_exit", Counter()),
                limit=12,
                reverse=True,
            ),
            "pnl_by_entry_context": _top_numeric_payload(
                pnl_by_exit_reason_context_totals.get("hard_intraday_time_exit", Counter()),
                limit=12,
                reverse=False,
            ),
            "avg_pnl_by_entry_context": _avg_payload(
                pnl_by_exit_reason_context_totals.get("hard_intraday_time_exit", Counter()),
                remove_by_exit_reason_context_counts.get("hard_intraday_time_exit", Counter()),
                limit=12,
                reverse=False,
            ),
        },
        "reaction_trim_hotspots": {
            "counts_by_entry_context": _top_numeric_payload(
                remove_by_exit_reason_context_counts.get("v6_reaction_inventory_trim", Counter()),
                limit=12,
                reverse=True,
            ),
            "pnl_by_entry_context": _top_numeric_payload(
                pnl_by_exit_reason_context_totals.get("v6_reaction_inventory_trim", Counter()),
                limit=12,
                reverse=True,
            ),
            "avg_pnl_by_entry_context": _avg_payload(
                pnl_by_exit_reason_context_totals.get("v6_reaction_inventory_trim", Counter()),
                remove_by_exit_reason_context_counts.get("v6_reaction_inventory_trim", Counter()),
                limit=12,
                reverse=True,
            ),
        },
        "monthly_adds": _counter_payload(add_by_month),
        "active_order_months": int(active_months),
        "total_months": int(total_months),
        "active_order_days": int(active_days),
        "max_month_add_share": round(max_month_share, 4),
        "max_day_add_share": round(max_day_share, 4),
        "add_by_utc_hour": _counter_payload(add_by_utc_hour),
        "add_by_kst_hour": _counter_payload(add_by_kst_hour),
        "max_kst_hour_add_share": round(max_hour_share, 4),
        "add_by_weekday": _counter_payload(add_by_weekday),
        "max_consecutive_same_side_adds": _max_consecutive_add_side(add_events),
        "exposure_side_bars": _counter_payload(exposure_side_bars),
        "exposure_side_share": {
            "long": round(exposure_long_share, 4),
            "short": round(exposure_short_share, 4),
            "flat": round(exposure_flat_share, 4),
        },
        "ratios": {
            "repair_stop_per_add": round(repair_stop_ratio, 4),
            "one_way_forced_trim_per_add": round(one_way_trim_ratio, 4),
            "profit_trim_per_remove": round(profit_trim_ratio, 4),
            "reaction_trim_per_remove": round(reaction_trim_ratio, 4),
            "profit_or_reaction_trim_per_remove": round(profit_trim_ratio + reaction_trim_ratio, 4),
            "battle_add_per_add": round(battle_add_ratio, 4),
            "battle_capacity_saturated": battle_capacity_saturated,
            "probe_add_per_add": round(probe_add_ratio, 4),
            "chase_add_per_add": round(chase_add_ratio, 4),
            "chase_failed_fast_exit_per_chase_add": round(chase_failed_ratio, 4),
            "probe_failed_fast_exit_per_probe_add": round(probe_failed_ratio, 4),
            "turnover_events_per_add": round(turnover_per_add, 4),
        },
    }


def _add_lot(
    *,
    book: PositionBook,
    side: int,
    qty: float,
    price: float,
    exec_idx: int,
    role: str,
    zone_score: int,
    zone_reasons: tuple[str, ...],
    zone_context: str = "",
) -> None:
    book.add(
        side=side,
        qty=qty,
        price=price,
        entry_idx=exec_idx,
        role=role,
        zone_score=zone_score,
        zone_id="|".join(zone_reasons[:4]),
        zone_context=zone_context,
    )


def _apply_decision(
    *,
    book: PositionBook,
    features: FeatureSet,
    sig_idx: int,
    exec_idx: int,
    exec_price: float,
    config: MarketStateConfig,
    market: MarketState,
    zone: ZonePlan,
    route_mode: str,
    events: list[dict[str, Any]],
    equity: float,
    counters: Counter[str],
    memory: RotationMemory,
    risk_size_mult: float = 1.0,
    soft_circuit_active: bool = False,
) -> None:
    ts = features.ts[exec_idx]
    fragile_regime_entry_mult = _fragile_regime_entry_multiplier(config, market)
    entry_risk_mult = _clamp(risk_size_mult, 0.0, 1.0) * fragile_regime_entry_mult
    one_way_loss_fuse_size_mult = (
        _clamp(config.one_way_loss_fuse_size_mult, 0.0, 1.0)
        if memory.in_one_way_loss_fuse(exec_idx)
        else 1.0
    )

    def route_mult(side: int, role: str) -> float:
        value = _router_entry_size_multiplier(
            config,
            route_mode=route_mode,
            market=market,
            side=side,
            role=role,
        )
        if value <= 1e-12:
            counters[f"router_{route_mode}_{role}_entry_blocks"] += 1
        elif value < 1.0 - 1e-12:
            counters[f"router_{route_mode}_{role}_entry_reductions"] += 1
        return value

    atr = max(features.atr[sig_idx], 1e-12)
    close = features.c[sig_idx]
    expected_reaction = zone.expected_reaction_usd
    if book.side != 0:
        expected_reaction = max(expected_reaction, _book_reaction_context_target(config, book))

    if book.side != 0 and _role_qty(book, "battle") > 0.0:
        battle_avg = _role_avg(book, "battle")
        target = battle_avg + book.side * expected_reaction
        reaction_hit = features.h[sig_idx] >= target if book.side > 0 else features.l[sig_idx] <= target
        if reaction_hit:
            removed = book.remove(qty=_role_qty(book, "battle"), price=exec_price, role_priority=("battle",))
            stats = _exit_removed_lots(
                events=events,
                removed=removed,
                ts=ts,
                action="remove",
                reason="battle_reaction_first",
                equity=equity,
            )
            counters["battle_reaction_exits"] += int(stats["battle_exits"])
            counters["battle_success"] += int(stats["battle_success"])
            counters["battle_failed"] += int(stats["battle_failed"])

    if book.side != 0:
        buffer_pct = _liquidation_buffer_pct(config, book, close)
        if buffer_pct < config.min_liquidation_buffer_pct:
            cut_qty = book.qty if buffer_pct < config.min_liquidation_buffer_pct * 0.55 else book.qty * 0.50
            removed = book.remove(qty=cut_qty, price=exec_price, role_priority=("battle", "chase", "base", "probe"))
            _exit_removed_lots(
                events=events,
                removed=removed,
                ts=ts,
                action="remove",
                reason="liquidation_buffer_cut",
                equity=equity,
            )
            counters["buffer_cuts"] += 1

    if book.side == 0:
        if memory.cooldown_until_idx >= 0 and exec_idx > memory.cooldown_until_idx:
            memory.failed_rescue_count = 0
            memory.cooldown_side = 0
        if memory.in_one_way_trim_cluster_cooldown(exec_idx):
            counters["one_way_trim_cluster_entry_blocks"] += 1
            return
        zone_state = memory.state(zone.active_zone_key, exec_idx, config.zone_retire_bars)
        if zone.side != 0 and memory.in_cooldown(zone.side, exec_idx):
            counters[f"cooldown_block_{_side_label(zone.side)}"] += 1
            return
        if (
            zone.side != 0
            and zone.score >= config.entry_score
            and not zone.no_trade_reasons
            and zone_state != "retired"
            and _scenario_allows_side(config, market, zone.side)
            and market.one_way_side != -zone.side
        ):
            role = zone.stage
            if role == "watch":
                idle_reason_stack = zone.long_reason_stack if zone.side > 0 else zone.short_reason_stack
                idle_reasons = zone.long_reasons if zone.side > 0 else zone.short_reasons
                idle_ready = (
                    config.trend_idle_probe_units > 1e-12
                    and market.bias == zone.side
                    and zone.score >= config.trend_idle_min_score
                    and idle_reason_stack >= config.trend_idle_min_reason_stack
                    and not market.bad_rr
                    and zone.chase_extension_atr <= config.trend_idle_max_extension_atr
                    and exec_idx - memory.last_trend_idle_probe_idx > config.trend_idle_cooldown_bars
                    and _kst_hour(ts) not in config.blocked_kst_entry_hours
                )
                if idle_ready:
                    qty = min(
                        config.trend_idle_probe_units
                        * _entry_size_multiplier(config, market, zone.side)
                        * route_mult(zone.side, "probe")
                        * entry_risk_mult,
                        config.max_possible_units,
                    )
                    if qty > 1e-12:
                        zone_context = _zone_context_key(side=zone.side, role="probe", market=market, zone=zone)
                        if memory.in_one_way_trim_context_cooldown(zone_context, exec_idx):
                            counters["one_way_trim_context_entry_blocks"] += 1
                            return
                        _add_lot(
                            book=book,
                            side=zone.side,
                            qty=qty,
                            price=exec_price,
                            exec_idx=exec_idx,
                            role="probe",
                            zone_score=zone.score,
                            zone_reasons=idle_reasons,
                            zone_context=zone_context,
                        )
                        memory.touch(zone.active_zone_key, exec_idx)
                        memory.failed_rescue_count = 0
                        memory.last_trend_idle_probe_idx = exec_idx
                        counters["probe_adds"] += 1
                        counters["trend_idle_probe_adds"] += 1
                        _record_event(
                            events,
                            ts=ts,
                            action="add",
                            side=zone.side,
                            qty=qty,
                            price=exec_price,
                            reason="trend_idle_probe_entry",
                            equity=equity,
                            extra={
                                "role": "probe",
                                "zone_score": zone.score,
                                "reason_stack": idle_reason_stack,
                                "zone_key": zone.active_zone_key,
                                "zone_state": zone_state,
                                "side_alignment": _side_alignment(market, zone.side),
                                "regime": market.regime,
                                "market": ",".join(market.reasons[:4]),
                                "zone": ",".join(idle_reasons[:4]),
                                "zone_context": zone_context,
                                "chase_extension_atr": round(zone.chase_extension_atr, 4),
                                "execution_context": zone.execution_context,
                            },
                        )
                return
            base_qty = {
                "battle": config.battle_units,
                "base": config.base_add_units,
                "chase": config.chase_units,
                "probe": config.probe_units,
            }.get(role, config.probe_units)
            late_base_size_mult = 1.0
            if (
                role == "base"
                and config.base_entry_reduce_extension_atr > 0.0
                and config.base_entry_reduce_side in {"both", _side_label(zone.side)}
                and market.bias == zone.side
                and zone.chase_extension_atr > max(0.1, float(config.base_entry_reduce_extension_atr))
                and (
                    config.base_entry_reduce_max_trend_strength <= 0.0
                    or market.trend_strength <= config.base_entry_reduce_max_trend_strength
                )
                and (
                    config.base_entry_reduce_min_trend_strength <= 0.0
                    or market.trend_strength >= config.base_entry_reduce_min_trend_strength
                )
            ):
                late_base_size_mult = _clamp(config.base_entry_reduce_size_mult, 0.0, 1.0)
            late_base_reduced = late_base_size_mult < 1.0 - 1e-12
            event_base_size_mult = _event_risk_base_size_multiplier(config, zone, zone.side, role)
            event_base_reduced = event_base_size_mult < 1.0 - 1e-12
            zone_context = _zone_context_key(side=zone.side, role=role, market=market, zone=zone)
            base_context_size_mult = _base_context_size_multiplier(config, zone_context, role)
            base_context_reduced = base_context_size_mult < 1.0 - 1e-12
            loss_fuse_reduced = role == "base" and one_way_loss_fuse_size_mult < 1.0 - 1e-12
            qty = min(
                base_qty
                * _entry_size_multiplier(config, market, zone.side)
                * late_base_size_mult
                * event_base_size_mult
                * base_context_size_mult
                * (one_way_loss_fuse_size_mult if role == "base" else 1.0)
                * route_mult(zone.side, role)
                * entry_risk_mult,
                config.max_possible_units,
            )
            if qty <= 1e-12:
                if loss_fuse_reduced:
                    counters["one_way_loss_fuse_base_blocks"] += 1
                if event_base_reduced:
                    counters["event_risk_base_reduce_blocks"] += 1
                if base_context_reduced:
                    counters["base_context_reduce_blocks"] += 1
                return
            reasons = zone.long_reasons if zone.side > 0 else zone.short_reasons
            if late_base_reduced:
                zone_context += "|late_base_reduce"
            if event_base_reduced:
                zone_context += "|event_risk_base_reduce"
            if base_context_reduced:
                zone_context += "|base_context_reduce"
            if loss_fuse_reduced:
                zone_context += "|loss_fuse_reduce"
            if memory.in_one_way_trim_context_cooldown(zone_context, exec_idx):
                counters["one_way_trim_context_entry_blocks"] += 1
                return
            _add_lot(
                book=book,
                side=zone.side,
                qty=qty,
                price=exec_price,
                exec_idx=exec_idx,
                role=role,
                zone_score=zone.score,
                zone_reasons=reasons,
                zone_context=zone_context,
            )
            memory.touch(zone.active_zone_key, exec_idx)
            memory.failed_rescue_count = 0
            counters[f"{role}_adds"] += 1
            if loss_fuse_reduced:
                counters["one_way_loss_fuse_base_reduced_adds"] += 1
            if event_base_reduced:
                counters["event_risk_base_reduced_adds"] += 1
            if base_context_reduced:
                counters["base_context_reduced_adds"] += 1
            if role == "battle":
                counters["battle_primary_adds"] += 1
            _record_event(
                events,
                ts=ts,
                action="add",
                side=zone.side,
                qty=qty,
                price=exec_price,
                reason=f"{role}_primary_entry" if role == "battle" else f"{role}_entry",
                equity=equity,
                extra={
                    "role": role,
                    "zone_score": zone.score,
                    "reason_stack": zone.long_reason_stack if zone.side > 0 else zone.short_reason_stack,
                    "zone_key": zone.active_zone_key,
                    "zone_state": zone_state,
                    "side_alignment": _side_alignment(market, zone.side),
                    "regime": market.regime,
                    "market": ",".join(market.reasons[:4]),
                    "zone": ",".join(reasons[:4]),
                    "zone_context": zone_context,
                    "chase_breakout_atr": round(zone.chase_breakout_atr, 4),
                    "chase_extension_atr": round(zone.chase_extension_atr, 4),
                    "trend_strength": round(market.trend_strength, 4),
                    "execution_context": zone.execution_context,
                    "late_base_size_mult": round(late_base_size_mult, 4),
                    "event_risk_base_size_mult": round(event_base_size_mult, 4),
                    "base_context_size_mult": round(base_context_size_mult, 4),
                    "one_way_loss_fuse_size_mult": round(
                        one_way_loss_fuse_size_mult if role == "base" else 1.0,
                        4,
                    ),
                },
            )
        if book.side == 0 and config.near_miss_probe_units > 1e-12:
            soft_no_trade_reasons = {"MC12_low_confluence", "MC04_no_clear_first_touch"}
            blockers = set(zone.no_trade_reasons)
            near_miss_side = 0
            score_edge = 0
            if zone.long_score > zone.short_score:
                near_miss_side = 1
                score_edge = zone.long_score - zone.short_score
            elif zone.short_score > zone.long_score:
                near_miss_side = -1
                score_edge = zone.short_score - zone.long_score
            elif config.near_miss_probe_min_score_edge <= 0 and market.bias:
                near_miss_side = market.bias
                score_edge = 0
            near_miss_score = zone.long_score if near_miss_side > 0 else zone.short_score if near_miss_side < 0 else 0
            near_miss_reason_stack = (
                zone.long_reason_stack
                if near_miss_side > 0
                else zone.short_reason_stack
                if near_miss_side < 0
                else 0
            )
            near_miss_reasons = (
                zone.long_reasons if near_miss_side > 0 else zone.short_reasons if near_miss_side < 0 else tuple()
            )
            near_miss_zone_key = (
                zone.long_zone_key if near_miss_side > 0 else zone.short_zone_key if near_miss_side < 0 else ""
            )
            near_miss_zone_state = memory.state(near_miss_zone_key, exec_idx, config.zone_retire_bars)
            near_miss_ready = (
                bool(blockers)
                and blockers.issubset(soft_no_trade_reasons)
                and near_miss_side != 0
                and near_miss_score >= config.near_miss_probe_min_score
                and score_edge >= config.near_miss_probe_min_score_edge
                and near_miss_reason_stack >= config.near_miss_probe_min_reason_stack
                and _near_miss_context_allowed(
                    config,
                    blockers=blockers,
                    market=market,
                    side=near_miss_side,
                    zone=zone,
                )
                and near_miss_zone_state != "retired"
                and _scenario_allows_side(config, market, near_miss_side)
                and market.bias in {0, near_miss_side}
                and market.one_way_side != -near_miss_side
                and not market.bad_rr
                and not memory.in_cooldown(near_miss_side, exec_idx)
                and not memory.in_near_miss_probe_failure_cooldown(exec_idx)
                and zone.chase_extension_atr <= config.near_miss_probe_max_extension_atr
                and exec_idx - memory.last_near_miss_probe_idx > config.near_miss_probe_cooldown_bars
                and _kst_hour(ts) not in config.blocked_kst_entry_hours
            )
            if near_miss_ready:
                qty = min(
                    config.near_miss_probe_units
                    * _entry_size_multiplier(config, market, near_miss_side)
                    * route_mult(near_miss_side, "probe")
                    * entry_risk_mult,
                    config.max_possible_units,
                )
                if qty > 1e-12:
                    zone_context = _zone_context_key(side=near_miss_side, role="probe", market=market, zone=zone)
                    zone_context += "|near_miss"
                    if memory.in_one_way_trim_context_cooldown(zone_context, exec_idx):
                        counters["one_way_trim_context_entry_blocks"] += 1
                        return
                    _add_lot(
                        book=book,
                        side=near_miss_side,
                        qty=qty,
                        price=exec_price,
                        exec_idx=exec_idx,
                        role="probe",
                        zone_score=near_miss_score,
                        zone_reasons=near_miss_reasons,
                        zone_context=zone_context,
                    )
                    memory.touch(near_miss_zone_key, exec_idx)
                    memory.failed_rescue_count = 0
                    memory.last_near_miss_probe_idx = exec_idx
                    counters["probe_adds"] += 1
                    counters["near_miss_probe_adds"] += 1
                    _record_event(
                        events,
                        ts=ts,
                        action="add",
                        side=near_miss_side,
                        qty=qty,
                        price=exec_price,
                        reason="near_miss_probe_entry",
                        equity=equity,
                        extra={
                            "role": "probe",
                            "zone_score": near_miss_score,
                            "score_edge": score_edge,
                            "reason_stack": near_miss_reason_stack,
                            "zone_key": near_miss_zone_key,
                            "zone_state": near_miss_zone_state,
                            "side_alignment": _side_alignment(market, near_miss_side),
                            "regime": market.regime,
                            "market": ",".join(market.reasons[:4]),
                            "zone": ",".join(near_miss_reasons[:4]),
                            "soft_no_trade": ",".join(zone.no_trade_reasons),
                            "zone_context": zone_context,
                            "chase_extension_atr": round(zone.chase_extension_atr, 4),
                            "execution_context": zone.execution_context,
                        },
                    )
        if book.side == 0 and config.trend_idle_probe_units > 1e-12:
            idle_reason_stack = zone.long_reason_stack if zone.side > 0 else zone.short_reason_stack if zone.side < 0 else 0
            idle_reasons = zone.long_reasons if zone.side > 0 else zone.short_reasons if zone.side < 0 else tuple()
            idle_zone_state = memory.state(zone.active_zone_key, exec_idx, config.zone_retire_bars)
            idle_ready = (
                zone.side != 0
                and zone.score >= config.trend_idle_min_score
                and idle_reason_stack >= config.trend_idle_min_reason_stack
                and not zone.no_trade_reasons
                and idle_zone_state != "retired"
                and _scenario_allows_side(config, market, zone.side)
                and market.bias == zone.side
                and market.one_way_side != -zone.side
                and not market.bad_rr
                and not memory.in_cooldown(zone.side, exec_idx)
                and zone.chase_extension_atr <= config.trend_idle_max_extension_atr
                and exec_idx - memory.last_trend_idle_probe_idx > config.trend_idle_cooldown_bars
                and _kst_hour(ts) not in config.blocked_kst_entry_hours
            )
            if idle_ready:
                qty = min(
                    config.trend_idle_probe_units
                    * _entry_size_multiplier(config, market, zone.side)
                    * route_mult(zone.side, "probe")
                    * entry_risk_mult,
                    config.max_possible_units,
                )
                if qty > 1e-12:
                    zone_context = _zone_context_key(side=zone.side, role="probe", market=market, zone=zone)
                    if memory.in_one_way_trim_context_cooldown(zone_context, exec_idx):
                        counters["one_way_trim_context_entry_blocks"] += 1
                        return
                    _add_lot(
                        book=book,
                        side=zone.side,
                        qty=qty,
                        price=exec_price,
                        exec_idx=exec_idx,
                        role="probe",
                        zone_score=zone.score,
                        zone_reasons=idle_reasons,
                        zone_context=zone_context,
                    )
                    memory.touch(zone.active_zone_key, exec_idx)
                    memory.failed_rescue_count = 0
                    memory.last_trend_idle_probe_idx = exec_idx
                    counters["probe_adds"] += 1
                    counters["trend_idle_probe_adds"] += 1
                    _record_event(
                        events,
                        ts=ts,
                        action="add",
                        side=zone.side,
                        qty=qty,
                        price=exec_price,
                        reason="trend_idle_probe_entry",
                        equity=equity,
                        extra={
                            "role": "probe",
                            "zone_score": zone.score,
                            "reason_stack": idle_reason_stack,
                            "zone_key": zone.active_zone_key,
                            "zone_state": idle_zone_state,
                            "side_alignment": _side_alignment(market, zone.side),
                            "regime": market.regime,
                            "market": ",".join(market.reasons[:4]),
                            "zone": ",".join(idle_reasons[:4]),
                            "zone_context": zone_context,
                            "chase_extension_atr": round(zone.chase_extension_atr, 4),
                            "execution_context": zone.execution_context,
                        },
                    )
        recovery_probe_units = (
            max(0.0, float(config.equity_soft_circuit_recovery_probe_units))
            if soft_circuit_active and entry_risk_mult <= 1e-12
            else 0.0
        )
        if book.side == 0 and (
            config.one_way_impulse_probe_units > 1e-12 or recovery_probe_units > 1e-12
        ):
            impulse_side = market.one_way_side
            impulse_score = zone.long_score if impulse_side > 0 else zone.short_score if impulse_side < 0 else 0
            impulse_reason_stack = (
                zone.long_reason_stack if impulse_side > 0 else zone.short_reason_stack if impulse_side < 0 else 0
            )
            impulse_reasons = (
                zone.long_reasons if impulse_side > 0 else zone.short_reasons if impulse_side < 0 else tuple()
            )
            if not impulse_reasons:
                impulse_reasons = market.reasons
            impulse_has_chase_break = any(reason.startswith("trend_chase") for reason in impulse_reasons)
            impulse_zone_key = zone.long_zone_key if impulse_side > 0 else zone.short_zone_key if impulse_side < 0 else ""
            hard_no_trade = _has_hard_no_trade_reasons(zone.no_trade_reasons)
            impulse_units = max(0.0, float(config.one_way_impulse_probe_units))
            impulse_min_one_way_score = max(0.0, float(config.one_way_impulse_min_one_way_score))
            impulse_min_score_diff = max(0, int(config.one_way_impulse_min_score_diff))
            impulse_max_extension_atr = max(0.1, float(config.one_way_impulse_max_extension_atr))
            impulse_entry_risk_mult = entry_risk_mult
            impulse_reason = "one_way_impulse_probe_entry"
            recovery_ready_mode = recovery_probe_units > 1e-12
            if recovery_ready_mode:
                impulse_units = recovery_probe_units
                impulse_min_one_way_score = max(
                    impulse_min_one_way_score,
                    max(0.0, float(config.equity_soft_circuit_recovery_min_one_way_score)),
                )
                impulse_min_score_diff = max(
                    impulse_min_score_diff,
                    max(0, int(config.equity_soft_circuit_recovery_min_score_diff)),
                )
                impulse_max_extension_atr = max(
                    0.1,
                    float(config.equity_soft_circuit_recovery_max_extension_atr),
                )
                impulse_entry_risk_mult = fragile_regime_entry_mult
                impulse_reason = "equity_soft_circuit_recovery_probe_entry"
            impulse_ready = (
                impulse_side != 0
                and market.bias == impulse_side
                and market.one_way_score >= impulse_min_one_way_score
                and abs(market.score_diff) >= impulse_min_score_diff
                and impulse_has_chase_break
                and impulse_score >= config.entry_score
                and impulse_reason_stack >= max(2, config.min_reason_stack - 1)
                and zone.chase_extension_atr <= impulse_max_extension_atr
                and not market.bad_rr
                and not hard_no_trade
                and not memory.in_cooldown(impulse_side, exec_idx)
                and not (
                    recovery_ready_mode
                    and memory.in_equity_soft_circuit_recovery_failure_cooldown(exec_idx)
                )
                and exec_idx - memory.last_one_way_impulse_probe_idx > config.one_way_impulse_cooldown_bars
                and memory.state(impulse_zone_key, exec_idx, config.zone_retire_bars) != "retired"
                and _kst_hour(ts) not in config.blocked_kst_entry_hours
            )
            if impulse_ready:
                qty = min(
                    impulse_units
                    * _entry_size_multiplier(config, market, impulse_side)
                    * route_mult(impulse_side, "probe")
                    * impulse_entry_risk_mult,
                    config.max_possible_units,
                )
                if qty > 1e-12:
                    zone_context = _zone_context_key(side=impulse_side, role="probe", market=market, zone=zone)
                    if memory.in_one_way_trim_context_cooldown(zone_context, exec_idx):
                        counters["one_way_trim_context_entry_blocks"] += 1
                        return
                    lot_zone_context = zone_context
                    if recovery_ready_mode:
                        lot_zone_context += "|soft_recovery"
                    _add_lot(
                        book=book,
                        side=impulse_side,
                        qty=qty,
                        price=exec_price,
                        exec_idx=exec_idx,
                        role="probe",
                        zone_score=impulse_score,
                        zone_reasons=impulse_reasons,
                        zone_context=lot_zone_context,
                    )
                    memory.touch(impulse_zone_key, exec_idx)
                    memory.failed_rescue_count = 0
                    memory.last_one_way_impulse_probe_idx = exec_idx
                    counters["probe_adds"] += 1
                    if recovery_ready_mode:
                        counters["equity_soft_circuit_recovery_probe_adds"] += 1
                    else:
                        counters["one_way_impulse_probe_adds"] += 1
                    _record_event(
                        events,
                        ts=ts,
                        action="add",
                        side=impulse_side,
                        qty=qty,
                        price=exec_price,
                        reason=impulse_reason,
                        equity=equity,
                        extra={
                            "role": "probe",
                            "zone_score": impulse_score,
                            "reason_stack": impulse_reason_stack,
                            "one_way_score": round(market.one_way_score, 4),
                            "score_diff": market.score_diff,
                            "zone_key": impulse_zone_key,
                            "side_alignment": _side_alignment(market, impulse_side),
                            "regime": market.regime,
                            "market": ",".join(market.reasons[:4]),
                            "zone": ",".join(impulse_reasons[:4]),
                            "zone_context": lot_zone_context,
                            "chase_extension_atr": round(zone.chase_extension_atr, 4),
                            "execution_context": zone.execution_context,
                            "soft_circuit_recovery": recovery_ready_mode,
                        },
                    )
        return

    side = book.side
    avg = book.avg_entry
    recovery = _recovery_price(book)
    repair_eff = _repair_efficiency(book, close, expected_reaction)
    adverse_usd = max(-side * (close - avg), 0.0)
    favorable_from_recovery = side * (close - recovery)
    capacity = max(config.max_possible_units - book.qty, 0.0)
    remaining_capacity_ratio = capacity / max(book.qty, 1e-12)
    last_entry = book.last_entry or avg
    adverse_from_last = side * (last_entry - close)
    spacing_ok = adverse_from_last >= config.base_spacing_atr * atr
    same_score = zone.long_score if side > 0 else zone.short_score
    opposite_score = zone.short_score if side > 0 else zone.long_score
    same_reasons = zone.long_reasons if side > 0 else zone.short_reasons
    same_reason_stack = zone.long_reason_stack if side > 0 else zone.short_reason_stack
    same_zone_key = zone.long_zone_key if side > 0 else zone.short_zone_key
    opposite_zone_key = zone.short_zone_key if side > 0 else zone.long_zone_key
    opposite_side = -side
    opposite_zone_side = zone.side == opposite_side
    scenario_allows_current = _scenario_allows_side(config, market, side)
    one_way_against = market.one_way_side == opposite_side
    min_cut_units = _min_cut_units(config)
    defensive_trim_ready = exec_idx - memory.last_defensive_trim_idx > config.defensive_trim_cooldown_bars
    hard_no_trade = _has_hard_no_trade_reasons(zone.no_trade_reasons)

    opposite_one_way_flip = (
        market.one_way_side == opposite_side
        and market.one_way_score >= max(0.0, float(config.scenario_flip_min_one_way_score))
    )
    opposite_bias_flip = market.bias == opposite_side
    scenario_flip_ready = (
        config.scenario_flip_units > 1e-12
        and config.switch_enabled
        and (opposite_one_way_flip or opposite_bias_flip)
        and (_scenario_allows_side(config, market, opposite_side) or opposite_one_way_flip)
        and adverse_usd >= expected_reaction * max(0.0, float(config.scenario_flip_min_adverse_reaction))
        and opposite_score >= max(config.entry_score, same_score + config.scenario_flip_min_score_edge)
        and zone.chase_extension_atr <= max(0.1, float(config.scenario_flip_max_extension_atr))
        and not market.bad_rr
        and not hard_no_trade
        and not memory.in_cooldown(opposite_side, exec_idx)
        and exec_idx - memory.last_scenario_flip_idx > config.scenario_flip_cooldown_bars
        and memory.state(opposite_zone_key, exec_idx, config.zone_retire_bars) != "retired"
    )
    if scenario_flip_ready:
        reasons = zone.short_reasons if opposite_side < 0 else zone.long_reasons
        zone_context = _zone_context_key(side=opposite_side, role="probe", market=market, zone=zone)
        if memory.in_one_way_trim_context_cooldown(zone_context, exec_idx):
            counters["scenario_failure_flip_context_blocks"] += 1
        else:
            old_qty = book.qty
            removed = book.remove(qty=book.qty, price=exec_price, role_priority=("battle", "chase", "base", "probe"))
            _exit_removed_lots(
                events=events,
                removed=removed,
                ts=ts,
                action="remove",
                reason="scenario_failure_forced_flip_exit",
                equity=equity,
            )
            memory.invalidate(same_zone_key, exec_idx)
            memory.cooldown(side, exec_idx, max(1, config.cooldown_after_loss_bars // 2))
            memory.last_scenario_flip_idx = exec_idx
            counters["scenario_failure_flips"] += 1
            switch_qty = min(
                config.scenario_flip_units
                * _entry_size_multiplier(config, market, opposite_side)
                * route_mult(opposite_side, "probe")
                * entry_risk_mult,
                config.max_possible_units,
            )
            if switch_qty > 1e-12:
                _add_lot(
                    book=book,
                    side=opposite_side,
                    qty=switch_qty,
                    price=exec_price,
                    exec_idx=exec_idx,
                    role="probe",
                    zone_score=opposite_score,
                    zone_reasons=reasons,
                    zone_context=zone_context,
                )
                memory.touch(opposite_zone_key, exec_idx)
                memory.failed_rescue_count = 0
                counters["switches"] += 1
                counters["probe_adds"] += 1
                counters["scenario_failure_flip_entries"] += 1
                _record_event(
                    events,
                    ts=ts,
                    action="add",
                    side=opposite_side,
                    qty=switch_qty,
                    price=exec_price,
                    reason="scenario_failure_flip_switch_entry",
                    equity=equity,
                    extra={
                        "role": "probe",
                        "old_qty": round(old_qty, 4),
                        "zone_score": opposite_score,
                        "same_score": same_score,
                        "score_edge": opposite_score - same_score,
                        "one_way_score": round(market.one_way_score, 4),
                        "adverse_reaction": round(adverse_usd / max(expected_reaction, 1e-12), 4),
                        "repair_efficiency": round(repair_eff, 4),
                        "zone_context": zone_context,
                        "side_alignment": _side_alignment(market, opposite_side),
                        "regime": market.regime,
                    },
                )
            else:
                counters["switch_flat_only"] += 1
            return

    one_way_trim_ready = (
        one_way_against
        and adverse_usd >= expected_reaction * config.one_way_trim_min_adverse_reaction
    )
    full_exit_forced_trim = (
        one_way_trim_ready
        and _one_way_full_exit_ready(config, market)
    )
    trim_cooldown_ready = exec_idx - memory.last_one_way_trim_idx > config.one_way_trim_cooldown_bars
    if one_way_trim_ready and (trim_cooldown_ready or full_exit_forced_trim) and (
        book.qty > min_cut_units or full_exit_forced_trim
    ):
        fraction = 1.0 if full_exit_forced_trim else _one_way_forced_trim_fraction(side, repair_eff)
        reversal_blockers: list[str] = []
        if config.one_way_reversal_switch_units <= 1e-12:
            reversal_blockers.append("disabled")
        if not config.switch_enabled:
            reversal_blockers.append("switch_disabled")
        if not config.one_way_reversal_allow_score_override and opposite_score < config.opposite_score:
            reversal_blockers.append("opposite_score_low")
        if (
            not config.one_way_reversal_allow_score_override
            and opposite_score < same_score + config.one_way_reversal_min_score_edge
        ):
            reversal_blockers.append("score_edge_low")
        if (
            not config.one_way_reversal_allow_scenario_override
            and not _scenario_allows_side(config, market, opposite_side)
        ):
            reversal_blockers.append("scenario_blocks")
        if zone.no_trade_reasons:
            reversal_blockers.append("zone_no_trade")
        if memory.in_cooldown(opposite_side, exec_idx):
            reversal_blockers.append("cooldown")
        if exec_idx - memory.last_one_way_reversal_switch_idx <= config.one_way_reversal_cooldown_bars:
            reversal_blockers.append("reversal_cooldown")
        if memory.state(opposite_zone_key, exec_idx, config.zone_retire_bars) == "retired":
            reversal_blockers.append("opposite_zone_retired")
        reversal_candidate = (
            config.one_way_reversal_switch_units > 1e-12
            and not reversal_blockers
        )
        if config.one_way_reversal_switch_units > 1e-12 and not reversal_candidate:
            counters["one_way_reversal_blocks"] += 1
            for blocker in reversal_blockers:
                counters[f"one_way_reversal_block_{blocker}"] += 1
        if reversal_candidate or full_exit_forced_trim:
            cut_qty = book.qty
        else:
            one_way_trim_size_mult = _inventory_throttle_multiplier(
                config,
                book.qty,
                config.one_way_trim_size_mult,
            )
            cut_qty = _scaled_unit_cut_qty(
                book.qty,
                fraction,
                one_way_trim_size_mult,
                minimum=min_cut_units,
            )
            if one_way_trim_size_mult < 1.0:
                counters["one_way_forced_trim_size_throttles"] += 1
        removed = book.remove(qty=cut_qty, price=exec_price, role_priority=("battle", "chase", "base", "probe"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=ts,
            action="remove",
            reason="one_way_against_forced_trim",
            equity=equity,
        )
        counters["one_way_forced_trims"] += 1
        if full_exit_forced_trim:
            counters["one_way_forced_trim_full_exits"] += 1
        memory.last_one_way_trim_idx = exec_idx
        memory.record_one_way_trim(
            exec_idx,
            window_bars=config.one_way_trim_cluster_window_bars,
            guard_count=config.one_way_trim_cluster_guard_count,
            cooldown_bars=config.one_way_trim_cluster_cooldown_bars,
        )
        triggered_context_keys: set[str] = set()
        for lot in removed:
            context = str(getattr(lot, "zone_context", ""))
            if lot.pnl_usd_units >= 0.0 or not context:
                continue
            before = memory.in_one_way_trim_context_cooldown(context, exec_idx)
            memory.record_one_way_trim_context(
                context,
                exec_idx,
                window_bars=config.one_way_trim_context_window_bars,
                guard_count=config.one_way_trim_context_guard_count,
                cooldown_bars=config.one_way_trim_context_cooldown_bars,
            )
            if not before and memory.in_one_way_trim_context_cooldown(context, exec_idx):
                triggered_context_keys.add(_context_quarantine_key(context))
        if triggered_context_keys:
            counters["one_way_trim_context_quarantine_triggers"] += len(triggered_context_keys)
        if config.one_way_trim_context_full_exit and triggered_context_keys and book.side != 0:
            for context_key in sorted(triggered_context_keys):
                context_removed = _remove_context_lots(book, context_key, exec_price)
                if not context_removed:
                    continue
                _exit_removed_lots(
                    events=events,
                    removed=context_removed,
                    ts=ts,
                    action="remove",
                    reason="one_way_context_quarantine_exit",
                    equity=equity,
                )
                counters["one_way_trim_context_quarantine_exits"] += 1
        if (
            config.one_way_loss_fuse_min_adverse_reaction > 0.0
            and config.one_way_loss_fuse_cooldown_bars > 0
            and config.one_way_loss_fuse_size_mult < 1.0 - 1e-12
            and adverse_usd
            >= max(expected_reaction, 1e-12) * max(0.0, float(config.one_way_loss_fuse_min_adverse_reaction))
        ):
            fuse_was_active = memory.in_one_way_loss_fuse(exec_idx)
            memory.trigger_one_way_loss_fuse(
                exec_idx,
                cooldown_bars=config.one_way_loss_fuse_cooldown_bars,
            )
            counters["one_way_loss_fuse_triggers"] += 1
            if not fuse_was_active:
                counters["one_way_loss_fuse_activations"] += 1
            _record_event(
                events,
                ts=ts,
                action="risk",
                side=side,
                qty=0.0,
                price=exec_price,
                reason="one_way_loss_fuse_trigger",
                equity=equity,
                extra={
                    "adverse_usd": round(adverse_usd, 4),
                    "expected_reaction": round(expected_reaction, 4),
                    "min_adverse_reaction": round(config.one_way_loss_fuse_min_adverse_reaction, 4),
                    "cooldown_bars": int(config.one_way_loss_fuse_cooldown_bars),
                    "size_mult": round(_clamp(config.one_way_loss_fuse_size_mult, 0.0, 1.0), 4),
                    "was_active": bool(fuse_was_active),
                },
            )
        if config.one_way_trim_retire_same_zone:
            memory.invalidate(same_zone_key, exec_idx)
        if config.one_way_trim_same_side_cooldown_bars > 0:
            memory.cooldown(side, exec_idx, config.one_way_trim_same_side_cooldown_bars)
        switch_ready = (
            reversal_candidate
            and book.side == 0
            and not memory.in_one_way_trim_cluster_cooldown(exec_idx)
        )
        if reversal_candidate and book.side == 0 and not switch_ready:
            counters["one_way_trim_cluster_switch_blocks"] += 1
        if switch_ready:
            enhanced_scenario_flip_switch = (
                config.scenario_flip_units > config.one_way_reversal_switch_units + 1e-12
                and opposite_one_way_flip
                and adverse_usd >= expected_reaction * max(0.0, float(config.scenario_flip_min_adverse_reaction))
                and zone.chase_extension_atr <= max(0.1, float(config.scenario_flip_max_extension_atr))
                and exec_idx - memory.last_scenario_flip_idx > config.scenario_flip_cooldown_bars
            )
            switch_units = (
                config.scenario_flip_units
                if enhanced_scenario_flip_switch
                else config.one_way_reversal_switch_units
            )
            switch_qty = min(
                switch_units
                * _entry_size_multiplier(config, market, opposite_side)
                * route_mult(opposite_side, "probe")
                * entry_risk_mult,
                config.max_possible_units,
            )
            if switch_qty > 1e-12:
                reasons = zone.short_reasons if opposite_side < 0 else zone.long_reasons
                zone_context = _zone_context_key(side=opposite_side, role="probe", market=market, zone=zone)
                _add_lot(
                    book=book,
                    side=opposite_side,
                    qty=switch_qty,
                    price=exec_price,
                    exec_idx=exec_idx,
                    role="probe",
                    zone_score=opposite_score,
                    zone_reasons=reasons,
                    zone_context=zone_context,
                )
                memory.touch(opposite_zone_key, exec_idx)
                memory.failed_rescue_count = 0
                memory.last_one_way_reversal_switch_idx = exec_idx
                counters["switches"] += 1
                counters["one_way_reversal_switches"] += 1
                if enhanced_scenario_flip_switch:
                    memory.last_scenario_flip_idx = exec_idx
                    counters["scenario_failure_flips"] += 1
                    counters["scenario_failure_flip_entries"] += 1
                _record_event(
                    events,
                    ts=ts,
                    action="add",
                    side=opposite_side,
                    qty=switch_qty,
                    price=exec_price,
                    reason=(
                        "scenario_failure_flip_switch_entry"
                        if enhanced_scenario_flip_switch
                        else "one_way_forced_trim_reversal_switch"
                    ),
                    equity=equity,
                    extra={
                        "role": "probe",
                        "zone_score": opposite_score,
                        "same_score": same_score,
                        "score_edge": opposite_score - same_score,
                        "one_way_score": round(market.one_way_score, 4),
                        "repair_efficiency": round(repair_eff, 4),
                        "zone_context": zone_context,
                        "switch_units": round(switch_units, 4),
                    },
                )
        return

    chase_qty = _role_qty(book, "chase")
    if chase_qty > 1e-12:
        chase_avg = _role_avg(book, "chase")
        chase_favorable = side * (close - chase_avg)
        chase_adverse = max(-chase_favorable, 0.0)
        chase_age = _role_age_bars(book, "chase", exec_idx)
        if chase_favorable >= expected_reaction * config.chase_take_profit_reaction:
            removed = book.remove(qty=chase_qty, price=exec_price, role_priority=("chase",))
            _exit_removed_lots(
                events=events,
                removed=removed,
                ts=ts,
                action="remove",
                reason="chase_quick_reaction_exit",
                equity=equity,
            )
            memory.react(same_zone_key, exec_idx)
            memory.failed_rescue_count = 0
            counters["chase_reaction_exits"] += 1
            return
        if chase_favorable >= expected_reaction * min(config.reaction_trim_trigger, config.chase_take_profit_reaction):
            removed = book.remove(qty=chase_qty, price=exec_price, role_priority=("chase",))
            _exit_removed_lots(
                events=events,
                removed=removed,
                ts=ts,
                action="remove",
                reason="chase_inventory_reaction_exit",
                equity=equity,
            )
            memory.react(same_zone_key, exec_idx)
            memory.failed_rescue_count = 0
            counters["chase_reaction_exits"] += 1
            return
        if chase_adverse >= expected_reaction * config.chase_stop_reaction or (
            chase_age >= config.chase_max_bars and chase_favorable < expected_reaction * 0.15
        ):
            removed = book.remove(qty=chase_qty, price=exec_price, role_priority=("chase",))
            _exit_removed_lots(
                events=events,
                removed=removed,
                ts=ts,
                action="remove",
                reason="chase_failed_fast_exit",
                equity=equity,
            )
            memory.failed_rescue_count += 1
            memory.cooldown(side, exec_idx, max(1, config.cooldown_after_loss_bars // 2))
            counters["chase_failed_fast_exits"] += 1
            if book.side == 0:
                memory.invalidate(same_zone_key, exec_idx)
            return

    probe_qty = _role_qty(book, "probe")
    if probe_qty > 1e-12:
        probe_avg = _role_avg(book, "probe")
        probe_favorable = side * (close - probe_avg)
        probe_adverse = max(-probe_favorable, 0.0)
        probe_age = _role_age_bars(book, "probe", exec_idx)
        if probe_favorable >= expected_reaction * config.probe_take_profit_reaction:
            removed = book.remove(qty=probe_qty, price=exec_price, role_priority=("probe",))
            _exit_removed_lots(
                events=events,
                removed=removed,
                ts=ts,
                action="remove",
                reason="probe_reaction_exit",
                equity=equity,
            )
            memory.react(same_zone_key, exec_idx)
            memory.failed_rescue_count = 0
            counters["probe_reaction_exits"] += 1
            if any("near_miss" in str(lot.zone_context) for lot in removed):
                counters["near_miss_probe_reaction_exits"] += 1
            if any("soft_recovery" in str(lot.zone_context) for lot in removed):
                counters["equity_soft_circuit_recovery_probe_reaction_exits"] += 1
            return
        if probe_adverse >= expected_reaction * config.probe_stop_reaction or (
            probe_age >= config.probe_max_bars and probe_favorable < 0.0
        ):
            removed = book.remove(qty=probe_qty, price=exec_price, role_priority=("probe",))
            _exit_removed_lots(
                events=events,
                removed=removed,
                ts=ts,
                action="remove",
                reason="probe_failed_fast_exit",
                equity=equity,
            )
            memory.failed_rescue_count += 1
            memory.cooldown(side, exec_idx, config.cooldown_after_loss_bars)
            counters["probe_failed_fast_exits"] += 1
            if any("near_miss" in str(lot.zone_context) for lot in removed):
                counters["near_miss_probe_failed_fast_exits"] += 1
                if memory.record_near_miss_probe_failure(
                    exec_idx,
                    guard_count=config.near_miss_probe_failure_guard_count,
                    window_bars=config.near_miss_probe_failure_guard_window_bars,
                    cooldown_bars=config.near_miss_probe_failure_cooldown_bars,
                ):
                    counters["near_miss_probe_failure_cooldown_triggers"] += 1
            if any("soft_recovery" in str(lot.zone_context) for lot in removed):
                counters["equity_soft_circuit_recovery_probe_failed_fast_exits"] += 1
                if memory.record_equity_soft_circuit_recovery_failure(
                    exec_idx,
                    guard_count=config.equity_soft_circuit_recovery_failure_guard_count,
                    window_bars=config.equity_soft_circuit_recovery_failure_guard_window_bars,
                    cooldown_bars=config.equity_soft_circuit_recovery_failure_cooldown_bars,
                ):
                    counters["equity_soft_circuit_recovery_failure_cooldown_triggers"] += 1
            if book.side == 0:
                memory.invalidate(same_zone_key, exec_idx)
            return

    late_base_qty = _late_base_qty(book)
    if (
        config.base_entry_reduce_promote_reaction > 0.0
        and late_base_qty > 1e-12
        and config.base_entry_reduce_size_mult < 1.0 - 1e-12
    ):
        late_base_avg = _late_base_avg(book)
        late_reaction_price = features.h[sig_idx] if side > 0 else features.l[sig_idx]
        favorable_from_late_base = side * (late_reaction_price - late_base_avg)
        close_favorable_from_late_base = side * (close - late_base_avg)
        reduced_mult = _clamp(config.base_entry_reduce_size_mult, 0.05, 1.0)
        target_base_qty = late_base_qty / reduced_mult
        promotion_missing = max(target_base_qty - _role_qty(book, "base"), 0.0)
        promotion_ready = (
            promotion_missing > 1e-12
            and favorable_from_late_base >= expected_reaction * config.base_entry_reduce_promote_reaction
            and zone.side == side
            and market.bias == side
            and same_score >= config.base_add_score
            and same_reason_stack >= config.min_reason_stack
            and scenario_allows_current
            and not zone.no_trade_reasons
            and not one_way_against
            and capacity > 1e-12
            and memory.state(same_zone_key, exec_idx, config.zone_retire_bars) != "retired"
        )
        if promotion_ready:
            qty = min(
                promotion_missing,
                config.base_add_units
                * (1.0 - reduced_mult)
                * route_mult(side, "base")
                * entry_risk_mult
                * one_way_loss_fuse_size_mult,
                capacity,
            )
            if qty > 1e-12:
                zone_context = _zone_context_key(side=side, role="base", market=market, zone=zone)
                if one_way_loss_fuse_size_mult < 1.0 - 1e-12:
                    zone_context += "|loss_fuse_reduce"
                _add_lot(
                    book=book,
                    side=side,
                    qty=qty,
                    price=exec_price,
                    exec_idx=exec_idx,
                    role="base",
                    zone_score=same_score,
                    zone_reasons=same_reasons,
                    zone_context=zone_context,
                )
                memory.touch(same_zone_key, exec_idx)
                memory.failed_rescue_count = 0
                counters["base_adds"] += 1
                counters["late_base_promotion_adds"] += 1
                if one_way_loss_fuse_size_mult < 1.0 - 1e-12:
                    counters["one_way_loss_fuse_base_reduced_adds"] += 1
                _record_event(
                    events,
                    ts=ts,
                    action="add",
                    side=side,
                    qty=qty,
                    price=exec_price,
                    reason="late_base_continuation_promote",
                    equity=equity,
                    extra={
                        "role": "base",
                        "zone_score": same_score,
                        "reason_stack": same_reason_stack,
                        "zone_key": same_zone_key,
                        "side_alignment": _side_alignment(market, side),
                        "regime": market.regime,
                        "market": ",".join(market.reasons[:4]),
                        "zone": ",".join(same_reasons[:4]),
                        "zone_context": zone_context,
                        "late_base_qty": round(late_base_qty, 4),
                        "late_base_avg": round(late_base_avg, 4),
                        "promotion_missing": round(promotion_missing, 4),
                        "favorable_from_late_base": round(favorable_from_late_base, 4),
                        "close_favorable_from_late_base": round(close_favorable_from_late_base, 4),
                        "promote_reaction": round(config.base_entry_reduce_promote_reaction, 4),
                        "chase_extension_atr": round(zone.chase_extension_atr, 4),
                        "execution_context": zone.execution_context,
                        "one_way_loss_fuse_size_mult": round(one_way_loss_fuse_size_mult, 4),
                    },
                )
                return

    winner_target_units = (
        min(config.winner_pyramid_max_units, config.max_possible_units)
        if config.winner_pyramid_max_units > 1e-12
        else config.max_possible_units
    )
    winner_capacity = min(capacity, max(winner_target_units - book.qty, 0.0))
    favorable_from_avg = side * (close - avg)
    favorable_from_last_entry = side * (close - last_entry)
    winner_trend_alive = market.bias == side or (
        market.one_way_side == side and market.one_way_score >= max(0.0, float(config.chase_min_one_way_score))
    )
    winner_pyramid_blocker = ""
    if config.winner_pyramid_units <= 1e-12:
        winner_pyramid_blocker = "disabled"
    elif winner_capacity <= 1e-12:
        winner_pyramid_blocker = "no_capacity"
    elif not winner_trend_alive:
        winner_pyramid_blocker = "trend_not_alive"
    elif bool(config.winner_pyramid_block_risk_off) and route_mode == "risk_off":
        winner_pyramid_blocker = "risk_off"
    elif bool(config.winner_pyramid_block_one_way_chase) and route_mode == "one_way_chase":
        winner_pyramid_blocker = "one_way_chase"
    elif favorable_from_avg < expected_reaction * max(0.0, float(config.winner_pyramid_min_profit_reaction)):
        winner_pyramid_blocker = "avg_profit_reaction"
    elif favorable_from_last_entry < expected_reaction * 0.10:
        winner_pyramid_blocker = "last_entry_profit_reaction"
    elif same_score < config.winner_pyramid_min_score:
        winner_pyramid_blocker = "score"
    elif same_reason_stack < config.winner_pyramid_min_reason_stack:
        winner_pyramid_blocker = "reason_stack"
    elif not scenario_allows_current:
        winner_pyramid_blocker = "scenario"
    elif one_way_against:
        winner_pyramid_blocker = "one_way_against"
    elif market.bad_rr:
        winner_pyramid_blocker = "bad_rr"
    elif hard_no_trade:
        winner_pyramid_blocker = "hard_no_trade"
    elif zone.chase_extension_atr < max(0.0, float(config.winner_pyramid_min_extension_atr)):
        winner_pyramid_blocker = "early_extension"
    elif zone.chase_extension_atr > max(0.1, float(config.winner_pyramid_max_extension_atr)):
        winner_pyramid_blocker = "extension"
    elif memory.in_cooldown(side, exec_idx):
        winner_pyramid_blocker = "side_cooldown"
    elif exec_idx - memory.last_winner_pyramid_idx <= config.winner_pyramid_cooldown_bars:
        winner_pyramid_blocker = "pyramid_cooldown"
    elif memory.state(same_zone_key, exec_idx, config.zone_retire_bars) == "retired":
        winner_pyramid_blocker = "retired_zone"
    winner_pyramid_ready = not winner_pyramid_blocker
    if config.winner_pyramid_units > 1e-12:
        counters["winner_pyramid_evaluations"] += 1
        if winner_pyramid_blocker:
            counters[f"winner_pyramid_block_{winner_pyramid_blocker}"] += 1
    if winner_pyramid_ready:
        qty = min(
            config.winner_pyramid_units
            * _entry_size_multiplier(config, market, side)
            * route_mult(side, "chase")
            * entry_risk_mult,
            winner_capacity,
        )
        if qty > 1e-12:
            zone_context = _zone_context_key(side=side, role="chase", market=market, zone=zone)
            if memory.in_one_way_trim_context_cooldown(zone_context, exec_idx):
                counters["winner_pyramid_context_blocks"] += 1
            else:
                _add_lot(
                    book=book,
                    side=side,
                    qty=qty,
                    price=exec_price,
                    exec_idx=exec_idx,
                    role="chase",
                    zone_score=same_score,
                    zone_reasons=same_reasons,
                    zone_context=zone_context,
                )
                memory.touch(same_zone_key, exec_idx)
                memory.failed_rescue_count = 0
                memory.last_winner_pyramid_idx = exec_idx
                counters["chase_adds"] += 1
                counters["winner_pyramid_adds"] += 1
                _record_event(
                    events,
                    ts=ts,
                    action="add",
                    side=side,
                    qty=qty,
                    price=exec_price,
                    reason="winner_pyramid_add",
                    equity=equity,
                    extra={
                        "role": "chase",
                        "zone_score": same_score,
                        "reason_stack": same_reason_stack,
                        "zone_key": same_zone_key,
                        "side_alignment": _side_alignment(market, side),
                        "regime": market.regime,
                        "market": ",".join(market.reasons[:4]),
                        "zone": ",".join(same_reasons[:4]),
                        "zone_context": zone_context,
                        "favorable_reaction": round(favorable_from_avg / max(expected_reaction, 1e-12), 4),
                        "favorable_from_last_reaction": round(
                            favorable_from_last_entry / max(expected_reaction, 1e-12),
                            4,
                        ),
                        "chase_extension_atr": round(zone.chase_extension_atr, 4),
                        "target_units": round(winner_target_units, 4),
                    },
                )
                return
        else:
            counters["winner_pyramid_block_zero_qty"] += 1

    reaction_roles_qty = _role_qty(book, "battle") + _role_qty(book, "chase") + _role_qty(book, "base")
    near_recovery_band = abs(recovery - close) <= expected_reaction * config.reaction_avg_band
    reaction_trim_trigger = _reaction_trim_trigger(config, market, side)
    if (
        reaction_roles_qty > 1e-12
        and favorable_from_last_entry >= expected_reaction * reaction_trim_trigger
        and near_recovery_band
    ):
        reaction_trim_size_mult = _inventory_throttle_multiplier(
            config,
            reaction_roles_qty,
            config.reaction_trim_size_mult,
        )
        trim_qty = min(
            reaction_roles_qty,
            max(
                min_cut_units,
                _scaled_unit_cut_qty(
                    reaction_roles_qty,
                    reaction_trim_trigger,
                    reaction_trim_size_mult,
                    minimum=min_cut_units,
                ),
            ),
        )
        removed = book.remove(qty=trim_qty, price=exec_price, role_priority=("battle", "chase", "base"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=ts,
            action="remove",
            reason="v6_reaction_inventory_trim",
            equity=equity,
        )
        memory.react(same_zone_key, exec_idx)
        memory.failed_rescue_count = 0
        counters["reaction_inventory_trims"] += 1
        if reaction_trim_size_mult < 1.0:
            counters["reaction_inventory_trim_size_throttles"] += 1
        return

    invalidated = market.bias == opposite_side and adverse_usd >= max(config.reaction_usd, config.battle_trigger_atr * atr)
    if invalidated and repair_eff >= config.repair_cut:
        memory.invalidate(same_zone_key, exec_idx)
        memory.failed_rescue_count += 1
        memory.cooldown(side, exec_idx, config.cooldown_after_loss_bars)
        removed = book.remove(qty=book.qty, price=exec_price, role_priority=("battle", "chase", "base", "probe"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=ts,
            action="remove",
            reason="scenario_invalidated_by_repair_math",
            equity=equity,
        )
        counters["repair_invalidations"] += 1
        if (
            config.switch_enabled
            and opposite_zone_side
            and opposite_score >= config.opposite_score
            and opposite_score >= same_score + config.switch_score_edge
            and repair_eff >= config.switch_repair_eff
            and not zone.no_trade_reasons
            and market.one_way_side != side
            and memory.state(opposite_zone_key, exec_idx, config.zone_retire_bars) != "retired"
        ):
            reasons = zone.short_reasons if opposite_side < 0 else zone.long_reasons
            qty = min(
                config.probe_units
                * _entry_size_multiplier(config, market, opposite_side)
                * route_mult(opposite_side, "probe")
                * entry_risk_mult,
                config.max_possible_units,
            )
            if qty > 1e-12:
                zone_context = _zone_context_key(side=opposite_side, role="probe", market=market, zone=zone)
                _add_lot(
                    book=book,
                    side=opposite_side,
                    qty=qty,
                    price=exec_price,
                    exec_idx=exec_idx,
                    role="probe",
                    zone_score=opposite_score,
                    zone_reasons=reasons,
                    zone_context=zone_context,
                )
                memory.touch(opposite_zone_key, exec_idx)
                counters["switches"] += 1
                _record_event(
                    events,
                    ts=ts,
                    action="add",
                    side=opposite_side,
                    qty=qty,
                    price=exec_price,
                    reason="repair_invalidation_switch_probe",
                    equity=equity,
                    extra={
                        "role": "probe",
                        "repair_efficiency": round(repair_eff, 4),
                        "zone_score": opposite_score,
                        "zone_context": zone_context,
                    },
                )
            else:
                counters["switch_flat_only"] += 1
        return

    if repair_eff >= config.repair_stop and adverse_usd > 0.0:
        if not defensive_trim_ready:
            counters["defensive_trim_cooldown_blocks"] += 1
            return
        memory.failed_rescue_count += 1
        memory.cooldown(side, exec_idx, max(1, config.cooldown_after_loss_bars // 2))
        cut_qty = book.qty if book.qty <= min_cut_units + 1e-12 else _unit_cut_qty(
            book.qty,
            0.50,
            minimum=min_cut_units,
        )
        removed = book.remove(qty=cut_qty, price=exec_price, role_priority=("battle", "chase", "base", "probe"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=ts,
            action="remove",
            reason="repair_efficiency_stop_trim",
            equity=equity,
        )
        counters["repair_stop_trims"] += 1
        memory.last_defensive_trim_idx = exec_idx
        if book.side == 0:
            memory.invalidate(same_zone_key, exec_idx)
        return

    battle_ready = (
        capacity > 1e-12
        and _role_qty(book, "battle") <= 1e-12
        and zone.side == side
        and zone.stage == "battle"
        and same_score >= config.battle_score
        and same_reason_stack >= max(config.min_reason_stack, 3)
        and scenario_allows_current
        and not zone.no_trade_reasons
        and not one_way_against
        and memory.failed_rescue_count < config.max_failed_rescues_before_reduce_only
        and remaining_capacity_ratio >= config.min_capacity_ratio
        and repair_eff <= config.max_repair_eff_for_add
        and adverse_usd >= max(config.battle_trigger_usd, config.battle_trigger_atr * atr)
        and memory.state(same_zone_key, exec_idx, config.zone_retire_bars) != "retired"
    )
    if battle_ready:
        qty = min(config.battle_units * route_mult(side, "battle") * entry_risk_mult, capacity)
        zone_context = _zone_context_key(side=side, role="battle", market=market, zone=zone)
        _add_lot(
            book=book,
            side=side,
            qty=qty,
            price=exec_price,
            exec_idx=exec_idx,
            role="battle",
            zone_score=same_score,
            zone_reasons=same_reasons,
            zone_context=zone_context,
        )
        memory.touch(same_zone_key, exec_idx)
        counters["battle_adds"] += 1
        _record_event(
            events,
            ts=ts,
            action="add",
            side=side,
            qty=qty,
            price=exec_price,
            reason="battle_add_with_repair_capacity",
            equity=equity,
            extra={
                "avg_entry": round(avg, 2),
                "recovery_price": round(recovery, 2),
                "repair_efficiency": round(repair_eff, 4),
                "capacity_ratio": round(remaining_capacity_ratio, 4),
                "zone_score": same_score,
                "reason_stack": same_reason_stack,
                "zone_key": same_zone_key,
                "zone_context": zone_context,
            },
        )
        return

    if (
        same_score >= config.base_add_score
        and same_reason_stack >= config.min_reason_stack
        and zone.side == side
        and zone.stage in {"base", "battle"}
        and scenario_allows_current
        and not zone.no_trade_reasons
        and not one_way_against
        and memory.failed_rescue_count < config.max_failed_rescues_before_reduce_only
        and repair_eff <= config.max_repair_eff_for_add
        and book.qty < config.base_max_units - 1e-12
        and spacing_ok
        and capacity > 1e-12
        and memory.state(same_zone_key, exec_idx, config.zone_retire_bars) != "retired"
    ):
        event_base_size_mult = _event_risk_base_size_multiplier(config, zone, side, "base")
        event_base_reduced = event_base_size_mult < 1.0 - 1e-12
        zone_context = _zone_context_key(side=side, role="base", market=market, zone=zone)
        base_context_size_mult = _base_context_size_multiplier(config, zone_context, "base")
        base_context_reduced = base_context_size_mult < 1.0 - 1e-12
        qty = min(
            config.base_add_units
            * _entry_size_multiplier(config, market, side)
            * event_base_size_mult
            * base_context_size_mult
            * one_way_loss_fuse_size_mult
            * route_mult(side, "base")
            * entry_risk_mult,
            config.base_max_units - book.qty,
            capacity,
        )
        if qty > 1e-12:
            if event_base_reduced:
                zone_context += "|event_risk_base_reduce"
            if base_context_reduced:
                zone_context += "|base_context_reduce"
            if one_way_loss_fuse_size_mult < 1.0 - 1e-12:
                zone_context += "|loss_fuse_reduce"
            _add_lot(
                book=book,
                side=side,
                qty=qty,
                price=exec_price,
                exec_idx=exec_idx,
                role="base",
                zone_score=same_score,
                zone_reasons=same_reasons,
                zone_context=zone_context,
            )
            memory.touch(same_zone_key, exec_idx)
            counters["base_adds"] += 1
            if one_way_loss_fuse_size_mult < 1.0 - 1e-12:
                counters["one_way_loss_fuse_base_reduced_adds"] += 1
            if event_base_reduced:
                counters["event_risk_base_reduced_adds"] += 1
            if base_context_reduced:
                counters["base_context_reduced_adds"] += 1
            _record_event(
                events,
                ts=ts,
                action="add",
                side=side,
                qty=qty,
                price=exec_price,
                reason="base_add_on_better_zone",
                equity=equity,
                extra={
                    "zone_score": same_score,
                    "reason_stack": same_reason_stack,
                    "repair_efficiency": round(repair_eff, 4),
                    "zone_key": same_zone_key,
                    "side_alignment": _side_alignment(market, side),
                    "zone_context": zone_context,
                    "event_risk_base_size_mult": round(event_base_size_mult, 4),
                    "base_context_size_mult": round(base_context_size_mult, 4),
                    "one_way_loss_fuse_size_mult": round(one_way_loss_fuse_size_mult, 4),
                },
            )
            return
        if event_base_reduced:
            counters["event_risk_base_reduce_blocks"] += 1
        if base_context_reduced:
            counters["base_context_reduce_blocks"] += 1

    if _role_qty(book, "battle") > 0.0:
        battle_age = max(exec_idx - lot.entry_idx for lot in book.tranches if lot.role == "battle")
        if battle_age >= config.max_battle_bars and favorable_from_recovery < 0.0:
            memory.failed_rescue_count += 1
            memory.cooldown(side, exec_idx, max(1, config.cooldown_after_loss_bars // 2))
            memory.invalidate(same_zone_key, exec_idx)
            removed = book.remove(qty=_role_qty(book, "battle"), price=exec_price, role_priority=("battle",))
            stats = _exit_removed_lots(
                events=events,
                removed=removed,
                ts=ts,
                action="remove",
                reason="battle_timeout_no_reaction",
                equity=equity,
            )
            counters["battle_timeouts"] += 1
            counters["battle_failed"] += int(stats["battle_failed"])
            return

    if repair_eff >= config.repair_cut and adverse_usd > 0.0 and book.qty > min_cut_units:
        if not defensive_trim_ready:
            counters["defensive_trim_cooldown_blocks"] += 1
            return
        memory.failed_rescue_count += 1
        memory.cooldown(side, exec_idx, max(1, config.cooldown_after_loss_bars // 2))
        cut_qty = _unit_cut_qty(book.qty, 0.30, minimum=min_cut_units)
        removed = book.remove(qty=cut_qty, price=exec_price, role_priority=("battle", "chase", "base", "probe"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=ts,
            action="remove",
            reason="loss_rotation_repair_trim",
            equity=equity,
        )
        counters["loss_rotation_trims"] += 1
        memory.last_defensive_trim_idx = exec_idx
        return

    first_idx = book.first_entry_idx
    if first_idx is not None and exec_idx - first_idx >= config.max_hold_bars:
        age_bars = exec_idx - first_idx
        favorable_reaction = favorable_from_recovery / max(expected_reaction, 1e-12)
        if _hard_time_exit_trend_defer_ready(
            config,
            market,
            side,
            age_bars=age_bars,
            favorable_reaction=favorable_reaction,
        ):
            counters["hard_time_exit_trend_defer_blocks"] += 1
            return
        if _hard_time_loss_defer_ready(
            config,
            book,
            exec_price,
            age_bars=age_bars,
        ):
            counters["hard_time_exit_loss_defer_blocks"] += 1
            return
        hard_time_exit_fraction = _hard_time_exit_fraction(config, book.qty)
        if hard_time_exit_fraction < 1.0 - 1e-12 and (
            exec_idx - memory.last_hard_time_exit_idx <= config.hard_time_exit_cooldown_bars
        ):
            counters["hard_time_exit_cooldown_blocks"] += 1
            return
        cut_qty = (
            book.qty
            if hard_time_exit_fraction >= 1.0 - 1e-12
            else _scaled_unit_cut_qty(
                book.qty,
                hard_time_exit_fraction,
                1.0,
                minimum=min_cut_units,
            )
        )
        removed = book.remove(qty=cut_qty, price=exec_price, role_priority=("battle", "chase", "base", "probe"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=ts,
            action="remove",
            reason="hard_intraday_time_exit",
            equity=equity,
        )
        counters["hard_time_exits"] += 1
        if hard_time_exit_fraction < 1.0 - 1e-12:
            counters["hard_time_exit_partial_trims"] += 1
        memory.last_hard_time_exit_idx = exec_idx
        return

    if first_idx is not None and exec_idx - first_idx >= config.max_stuck_bars and favorable_from_recovery < 0.0:
        memory.failed_rescue_count += 1
        memory.cooldown(side, exec_idx, max(1, config.cooldown_after_loss_bars // 2))
        cut_qty = _unit_cut_qty(book.qty, 0.35, minimum=min_cut_units)
        removed = book.remove(qty=cut_qty, price=exec_price, role_priority=("battle", "chase", "base", "probe"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=ts,
            action="remove",
            reason="stuck_position_trim",
            equity=equity,
        )
        counters["stuck_trims"] += 1
        return

    if (
        config.switch_enabled
        and opposite_zone_side
        and opposite_score >= config.opposite_score
        and opposite_score >= same_score + config.switch_score_edge
        and market.bias == opposite_side
        and repair_eff >= config.switch_repair_eff
        and favorable_from_recovery < 0.0
        and not zone.no_trade_reasons
        and memory.failed_rescue_count >= 1
        and memory.state(opposite_zone_key, exec_idx, config.zone_retire_bars) != "retired"
    ):
        old_qty = book.qty
        removed = book.remove(qty=book.qty, price=exec_price, role_priority=("battle", "chase", "base", "probe"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=ts,
            action="remove",
            reason="opposite_switch_after_repair_failure",
            equity=equity,
        )
        reasons = zone.short_reasons if opposite_side < 0 else zone.long_reasons
        qty = min(
            config.probe_units
            * _entry_size_multiplier(config, market, opposite_side)
            * route_mult(opposite_side, "probe")
            * entry_risk_mult,
            config.max_possible_units,
        )
        if qty > 1e-12:
            zone_context = _zone_context_key(side=opposite_side, role="probe", market=market, zone=zone)
            _add_lot(
                book=book,
                side=opposite_side,
                qty=qty,
                price=exec_price,
                exec_idx=exec_idx,
                role="probe",
                zone_score=opposite_score,
                zone_reasons=reasons,
                zone_context=zone_context,
            )
            memory.touch(opposite_zone_key, exec_idx)
            memory.failed_rescue_count = 0
            counters["switches"] += 1
            _record_event(
                events,
                ts=ts,
                action="add",
                side=opposite_side,
                qty=qty,
                price=exec_price,
                reason="opposite_switch_probe",
                equity=equity,
                extra={
                    "role": "probe",
                    "old_qty": round(old_qty, 4),
                    "repair_efficiency": round(repair_eff, 4),
                    "zone_context": zone_context,
                },
            )
        else:
            counters["switch_flat_only"] += 1
        return

    trend_core = config.trend_core_units if market.bias == side else config.probe_units
    if favorable_from_recovery >= expected_reaction and book.qty > trend_core:
        trim_qty = min(book.qty - trend_core, _unit_cut_qty(book.qty, 0.35, minimum=min_cut_units))
        if book.qty - trim_qty < trend_core:
            trim_qty = book.qty
        removed = book.remove(qty=trim_qty, price=exec_price, role_priority=("chase", "battle", "base", "probe"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=ts,
            action="remove",
            reason="reaction_profit_trim",
            equity=equity,
        )
        memory.react(same_zone_key, exec_idx)
        memory.failed_rescue_count = 0
        counters["profit_trims"] += 1


def _monthly_stats(month_equity: dict[str, dict[str, float]]) -> dict[str, Any]:
    returns: dict[str, float] = {}
    doubled = 0
    losing = 0
    for month, values in sorted(month_equity.items()):
        start = values.get("start", 0.0)
        end = values.get("end", start)
        if start <= 0.0:
            continue
        ret = end / start - 1.0
        returns[month] = ret
        if ret >= 1.0:
            doubled += 1
        if ret < 0.0:
            losing += 1
    months = len(returns)
    return {
        "months": months,
        "monthly_returns": {key: round(value, 6) for key, value in returns.items()},
        "months_doubled": doubled,
        "monthly_double_rate": doubled / months if months else 0.0,
        "losing_months": losing,
    }


def _calendar_rolling_stats(day_equity: dict[str, dict[str, float]]) -> dict[str, Any]:
    parsed_days: list[tuple[datetime, str, dict[str, float]]] = []
    for day, values in sorted(day_equity.items()):
        try:
            parsed_days.append((datetime.fromisoformat(day), str(day), values))
        except ValueError:
            continue

    windows: dict[str, dict[str, Any]] = {}
    for window_days in (30, 60, 90):
        returns: list[dict[str, Any]] = []
        label = f"{window_days}d"
        for start_idx, (start_date, start_day, start_values) in enumerate(parsed_days):
            target_date = start_date + timedelta(days=window_days - 1)
            end_idx = start_idx
            while end_idx + 1 < len(parsed_days) and parsed_days[end_idx + 1][0] <= target_date:
                end_idx += 1
            end_date, end_day, end_values = parsed_days[end_idx]
            if end_date < target_date:
                continue
            start_equity = float(start_values.get("start") or 0.0)
            end_equity = float(end_values.get("end") or start_equity)
            if start_equity <= 0.0:
                continue
            returns.append(
                {
                    "start_day": start_day,
                    "end_day": end_day,
                    "return_pct": round((end_equity / start_equity - 1.0) * 100.0, 4),
                }
            )
        values = [float(row["return_pct"]) for row in returns]
        worst_window = min(returns, key=lambda row: float(row["return_pct"]), default=None)
        best_window = max(returns, key=lambda row: float(row["return_pct"]), default=None)
        windows[label] = {
            "count": len(returns),
            "min_return_pct": round(min(values), 4) if values else None,
            "avg_return_pct": round(mean(values), 4) if values else None,
            "max_return_pct": round(max(values), 4) if values else None,
            "positive_window_count": sum(1 for value in values if value > 0.0),
            "worst_window": worst_window or {},
            "best_window": best_window or {},
        }

    return {
        "daily_count": len(parsed_days),
        "first_day": parsed_days[0][1] if parsed_days else None,
        "last_day": parsed_days[-1][1] if parsed_days else None,
        "windows": windows,
    }


def _new_performance_bucket() -> dict[str, Any]:
    return {
        "bars": 0,
        "exposed_bars": 0,
        "equity": 1.0,
        "min_equity": 1.0,
        "max_drawdown": 0.0,
        "peak": 1.0,
        "abs_exposure_sum": 0.0,
        "max_abs_exposure": 0.0,
        "add_events": 0,
        "remove_events": 0,
        "side_bars": Counter(),
    }


def _update_performance_bucket(
    stats: dict[str, Any],
    *,
    bar_return: float,
    new_weight: float,
    new_trade_events: list[dict[str, Any]],
) -> None:
    stats["bars"] += 1
    stats["equity"] = max(float(stats["equity"]) * max(1.0 + bar_return, 1e-12), 1e-12)
    stats["peak"] = max(float(stats["peak"]), float(stats["equity"]))
    stats["min_equity"] = min(float(stats["min_equity"]), float(stats["equity"]))
    if float(stats["peak"]) > 0.0:
        stats["max_drawdown"] = max(
            float(stats["max_drawdown"]),
            1.0 - float(stats["equity"]) / float(stats["peak"]),
        )
    stats["abs_exposure_sum"] += abs(new_weight)
    stats["max_abs_exposure"] = max(float(stats["max_abs_exposure"]), abs(new_weight))
    if abs(new_weight) > 1e-12:
        stats["exposed_bars"] += 1
        if new_weight > 0.0:
            stats["side_bars"]["long"] += 1
        else:
            stats["side_bars"]["short"] += 1
    else:
        stats["side_bars"]["flat"] += 1
    for event in new_trade_events:
        action = str(event.get("action") or "")
        if action == "add":
            stats["add_events"] += 1
        elif action == "remove":
            stats["remove_events"] += 1


def _performance_payload(stats_by_key: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        key: {
            "bars": int(stats["bars"]),
            "exposed_bars": int(stats["exposed_bars"]),
            "return_pct": round((float(stats["equity"]) - 1.0) * 100.0, 4),
            "max_drawdown_pct": round(float(stats["max_drawdown"]) * 100.0, 4),
            "avg_abs_account_exposure": round(
                float(stats["abs_exposure_sum"]) / max(int(stats["bars"]), 1),
                4,
            ),
            "max_abs_account_exposure": round(float(stats["max_abs_exposure"]), 4),
            "add_events": int(stats["add_events"]),
            "remove_events": int(stats["remove_events"]),
            "side_bars": _counter_payload(stats["side_bars"]),
        }
        for key, stats in sorted(stats_by_key.items())
    }


def backtest_config(
    *,
    symbol: str,
    features: FeatureSet,
    scenario_features: dict[str, FeatureSet],
    scenario_maps: dict[str, list[int]],
    config: MarketStateConfig,
    cost_rate: float,
    min_periods: int,
    carry_rate_per_bar: float = 0.0,
    recent_event_limit: int = 24,
) -> dict[str, Any] | None:
    warmup = max(config.zone_lookback + 60, config.exec_slow + 30, 260)
    if len(features.bars) < max(min_periods, warmup + 10):
        return None

    equity = 1.0
    gross_equity = 1.0
    peak = 1.0
    gross_peak = 1.0
    peak_ts = features.ts[warmup] if warmup < len(features.ts) else features.ts[0]
    peak_idx = warmup
    max_drawdown = 0.0
    gross_max_drawdown = 0.0
    max_drawdown_detail: dict[str, Any] = {}
    max_drawdown_recovery_peak_equity = 0.0
    max_drawdown_trough_idx = -1
    min_equity = equity
    gross_min_equity = gross_equity
    book = PositionBook()
    memory = RotationMemory()
    counters: Counter[str] = Counter()
    events: list[dict[str, Any]] = []
    bar_returns: list[float] = []
    month_equity: dict[str, dict[str, float]] = {}
    day_equity: dict[str, dict[str, float]] = {}
    exposure_sum = 0.0
    exposure_bars = 0
    max_abs_weight = 0.0
    exposure_side_bars: Counter[str] = Counter()
    modeled_trade_cost_fraction_sum = 0.0
    modeled_carry_cost_fraction_sum = 0.0
    cost_breakdown: dict[str, Counter[str]] = defaultdict(Counter)
    regime_stats: dict[str, dict[str, Any]] = {}
    router_mode_stats: dict[str, dict[str, Any]] = {}
    equity_circuit_pause_until_idx = -1
    equity_circuit_armed = True
    equity_soft_circuit_cooldown_until_idx = (
        warmup + max(0, int(config.equity_soft_circuit_prearm_bars))
        if config.equity_soft_circuit_prearm_bars > 0
        else -1
    )
    equity_soft_circuit_force_exit_pending = False
    equity_soft_circuit_inventory_trim_pending_fraction = 0.0
    last_entry_add_idx = -10**9
    previous_regime = ""
    previous_router_mode = ""

    for exec_idx in range(warmup + 1, len(features.bars) - 1):
        sig_idx = exec_idx - 1
        exec_price = features.o[exec_idx]
        next_open = features.o[exec_idx + 1]
        if exec_price <= 0.0 or next_open <= 0.0:
            continue

        bar_start_equity = equity
        old_weight = _book_weight(config, book)
        market = _market_state(
            exec_features=features,
            scenario_features=scenario_features,
            scenario_maps=scenario_maps,
            exec_idx=exec_idx,
            sig_idx=sig_idx,
            config=config,
        )
        zone = _zone_plan(features=features, idx=sig_idx, market=market, config=config)
        if market.bad_rr:
            counters["bad_rr_bars"] += 1
        if zone.no_trade_reasons:
            no_trade_side = _no_trade_candidate_side(market=market, zone=zone)
            for reason in zone.no_trade_reasons:
                counters[f"no_trade_{reason}"] += 1
                counters[
                    "no_trade_context::"
                    + _no_trade_context_key(
                        reason=reason,
                        side=no_trade_side,
                        market=market,
                        zone=zone,
                    )
                ] += 1
                counters[f"no_trade_reason_side::{reason}|{_side_label(no_trade_side)}"] += 1
                counters[f"no_trade_reason_regime::{reason}|{market.regime}"] += 1
        if market.one_way_side:
            counters[f"one_way_{_side_label(market.one_way_side)}_bars"] += 1

        soft_circuit_active = exec_idx <= equity_soft_circuit_cooldown_until_idx
        route_mode = _router_mode(
            config,
            market,
            zone,
            soft_circuit_active=soft_circuit_active,
        )
        if bool(config.regime_router_enabled):
            counters[f"router_mode_{route_mode}_bars"] += 1
        event_start = len(events)
        soft_risk_size_mult = (
            _clamp(config.equity_soft_circuit_size_mult, 0.0, 1.0) if soft_circuit_active else 1.0
        )
        if soft_circuit_active:
            counters["equity_soft_circuit_cooldown_bars"] += 1
        if exec_idx <= equity_circuit_pause_until_idx:
            counters["equity_circuit_breaker_pause_bars"] += 1
            if book.side != 0:
                removed = book.remove(
                    qty=book.qty,
                    price=exec_price,
                    role_priority=("battle", "chase", "base", "probe"),
                )
                _exit_removed_lots(
                    events=events,
                    removed=removed,
                    ts=features.ts[exec_idx],
                    action="remove",
                    reason="equity_circuit_breaker_pause_exit",
                    equity=equity,
                )
                counters["equity_circuit_breaker_pause_exits"] += 1
        elif equity_soft_circuit_force_exit_pending:
            equity_soft_circuit_force_exit_pending = False
            counters["equity_soft_circuit_force_exit_bars"] += 1
            if book.side != 0:
                removed = book.remove(
                    qty=book.qty,
                    price=exec_price,
                    role_priority=("battle", "chase", "base", "probe"),
                )
                _exit_removed_lots(
                    events=events,
                    removed=removed,
                    ts=features.ts[exec_idx],
                    action="remove",
                    reason="equity_soft_circuit_force_exit",
                    equity=equity,
                )
                counters["equity_soft_circuit_force_exits"] += 1
        elif equity_soft_circuit_inventory_trim_pending_fraction > 1e-12:
            trim_fraction = _clamp(equity_soft_circuit_inventory_trim_pending_fraction, 0.0, 1.0)
            equity_soft_circuit_inventory_trim_pending_fraction = 0.0
            counters["equity_soft_circuit_inventory_trim_bars"] += 1
            if book.side != 0 and trim_fraction > 1e-12:
                trim_qty = min(book.qty, max(0.0, book.qty * trim_fraction))
                if trim_qty > 1e-12:
                    removed = book.remove(
                        qty=trim_qty,
                        price=exec_price,
                        role_priority=("battle", "chase", "base", "probe"),
                    )
                    _exit_removed_lots(
                        events=events,
                        removed=removed,
                        ts=features.ts[exec_idx],
                        action="remove",
                        reason="equity_soft_circuit_inventory_trim",
                        equity=equity,
                    )
                    counters["equity_soft_circuit_inventory_trims"] += 1
        else:
            router_inventory_trimmed = False
            router_trim_modes = set(config.router_transition_trim_modes)
            if (
                bool(config.regime_router_enabled)
                and book.side != 0
                and config.router_transition_trim_fraction > 0.0
                and route_mode in router_trim_modes
                and route_mode != previous_router_mode
                and exec_idx - memory.last_router_transition_trim_idx
                > max(0, int(config.router_transition_trim_cooldown_bars))
            ):
                if route_mode == "one_way_chase":
                    against_new_mode = market.one_way_side == -book.side
                elif route_mode == "exhaustion_reversal":
                    against_new_mode = zone.side == -book.side or market.one_way_side == book.side
                elif route_mode == "risk_off":
                    against_new_mode = True
                else:
                    against_new_mode = False
                if against_new_mode or not config.router_transition_trim_against_only:
                    trim_fraction = _clamp(config.router_transition_trim_fraction, 0.0, 1.0)
                    trim_qty = (
                        book.qty
                        if trim_fraction >= 1.0 - 1e-12
                        else _unit_cut_qty(book.qty, trim_fraction, minimum=_min_cut_units(config))
                    )
                    if trim_qty > 1e-12:
                        removed = book.remove(
                            qty=trim_qty,
                            price=exec_price,
                            role_priority=("chase", "battle", "base", "probe"),
                        )
                        _exit_removed_lots(
                            events=events,
                            removed=removed,
                            ts=features.ts[exec_idx],
                            action="remove",
                            reason="router_mode_transition_trim",
                            equity=equity,
                        )
                        counters["router_mode_transition_trims"] += 1
                        counters[f"router_mode_transition_trim_{route_mode}"] += 1
                        memory.last_router_transition_trim_idx = exec_idx
                        router_inventory_trimmed = True
            fragile_inventory_trimmed = False
            if (
                not router_inventory_trimmed
                and book.side != 0
                and config.fragile_regime_inventory_trim_regimes
                and market.regime in set(config.fragile_regime_inventory_trim_regimes)
                and market.regime != previous_regime
                and config.fragile_regime_inventory_trim_fraction > 0.0
            ):
                trim_fraction = _clamp(config.fragile_regime_inventory_trim_fraction, 0.0, 1.0)
                trim_qty = (
                    book.qty
                    if trim_fraction >= 1.0 - 1e-12
                    else _unit_cut_qty(book.qty, trim_fraction, minimum=1.0)
                )
                if trim_qty > 1e-12:
                    removed = book.remove(
                        qty=trim_qty,
                        price=exec_price,
                        role_priority=("chase", "battle", "base", "probe"),
                    )
                    _exit_removed_lots(
                        events=events,
                        removed=removed,
                        ts=features.ts[exec_idx],
                        action="remove",
                        reason="fragile_regime_transition_trim",
                        equity=equity,
                    )
                    counters["fragile_regime_transition_trims"] += 1
                    fragile_inventory_trimmed = True
            if not router_inventory_trimmed and not fragile_inventory_trimmed:
                _apply_decision(
                    book=book,
                    features=features,
                    sig_idx=sig_idx,
                    exec_idx=exec_idx,
                    exec_price=exec_price,
                    config=config,
                    market=market,
                    zone=zone,
                    route_mode=route_mode,
                    events=events,
                    equity=equity,
                    counters=counters,
                    memory=memory,
                    risk_size_mult=soft_risk_size_mult,
                    soft_circuit_active=soft_circuit_active,
                )

        new_weight = _book_weight(config, book)
        turnover = abs(new_weight - old_weight)
        new_trade_events = events[event_start:]
        if bool(config.regime_router_enabled):
            for event in new_trade_events:
                event.setdefault("router_mode", route_mode)
        if any(str(event.get("action") or "") == "add" for event in new_trade_events):
            last_entry_add_idx = exec_idx
        if soft_circuit_active and soft_risk_size_mult < 1.0 - 1e-12:
            reduced_add_events = sum(1 for event in new_trade_events if str(event.get("action") or "") == "add")
            counters["equity_soft_circuit_reduced_add_events"] += reduced_add_events
        trade_cost = _event_trade_cost(
            config=config,
            new_events=new_trade_events,
            cost_rate=cost_rate,
            counters=counters,
            cost_breakdown=cost_breakdown,
        )
        if trade_cost <= 1e-18 and turnover > 0.0:
            trade_cost = turnover * cost_rate
            counters["fallback_turnover_cost_events"] += 1
        if trade_cost > 0.0:
            equity *= max(1.0 - trade_cost, 0.0)
            modeled_trade_cost_fraction_sum += trade_cost
            counters["turnover_events"] += 1

        liquidated = False
        if book.side != 0:
            liq_price = _liquidation_price(config, book.side, book.avg_entry)
            if (book.side > 0 and features.l[exec_idx] <= liq_price) or (
                book.side < 0 and features.h[exec_idx] >= liq_price
            ):
                margin_fraction = min(abs(new_weight) / max(config.exchange_leverage, 1e-12), 1.0)
                liquidation_loss = min(equity * margin_fraction, equity * 0.995)
                counters["liquidations"] += 1
                _record_event(
                    events,
                    ts=features.ts[exec_idx],
                    action="liquidation",
                    side=book.side,
                    qty=book.qty,
                    price=liq_price,
                    reason="exchange_liquidation_proxy",
                    equity=equity,
                    extra={
                        "avg_entry": round(book.avg_entry, 2),
                        "weight": round(new_weight, 4),
                        "loss_fraction": round(margin_fraction, 6),
                    },
                )
                equity = max(equity - liquidation_loss, 1e-12)
                gross_liquidation_loss = min(gross_equity * margin_fraction, gross_equity * 0.995)
                gross_equity = max(gross_equity - gross_liquidation_loss, 1e-12)
                book.reset()
                new_weight = 0.0
                liquidated = True

        if not liquidated and new_weight != 0.0:
            carry_cost = abs(new_weight) * max(float(carry_rate_per_bar), 0.0)
            if carry_cost > 0.0:
                equity *= max(1.0 - carry_cost, 0.0)
                modeled_carry_cost_fraction_sum += carry_cost
                counters["carry_cost_events"] += 1
            raw_price_return = next_open / exec_price - 1.0
            equity *= max(1.0 + new_weight * raw_price_return, 1e-12)
            gross_equity *= max(1.0 + new_weight * raw_price_return, 1e-12)

        bar_return = equity / max(bar_start_equity, 1e-12) - 1.0
        if math.isfinite(bar_return):
            bar_returns.append(bar_return)
            regime = market.regime or "unknown"
            _update_performance_bucket(
                regime_stats.setdefault(regime, _new_performance_bucket()),
                bar_return=bar_return,
                new_weight=new_weight,
                new_trade_events=new_trade_events,
            )
            _update_performance_bucket(
                router_mode_stats.setdefault(route_mode, _new_performance_bucket()),
                bar_return=bar_return,
                new_weight=new_weight,
                new_trade_events=new_trade_events,
            )

        month = features.ts[exec_idx].strftime("%Y-%m")
        if month not in month_equity:
            month_equity[month] = {"start": equity, "end": equity}
        month_equity[month]["end"] = equity
        day = features.ts[exec_idx].strftime("%Y-%m-%d")
        if day not in day_equity:
            day_equity[day] = {"start": equity, "end": equity}
        day_equity[day]["end"] = equity

        if equity > peak:
            peak = equity
            peak_ts = features.ts[exec_idx]
            peak_idx = exec_idx
        gross_peak = max(gross_peak, gross_equity)
        min_equity = min(min_equity, equity)
        gross_min_equity = min(gross_min_equity, gross_equity)
        if peak > 0.0:
            drawdown = 1.0 - equity / peak
            if drawdown > max_drawdown + 1e-12:
                lot_count_by_role, qty_by_role = _book_open_role_payloads(book)
                max_drawdown = drawdown
                max_drawdown_detail = {
                    "drawdown_pct": round(drawdown * 100.0, 4),
                    "peak_ts": peak_ts.isoformat(),
                    "trough_ts": features.ts[exec_idx].isoformat(),
                    "peak_to_trough_bars": max(exec_idx - peak_idx, 0),
                    "peak_to_trough_hours": round(
                        max(exec_idx - peak_idx, 0) * _INTERVAL_MS[config.exec_interval] / 3_600_000.0,
                        4,
                    ),
                    "peak_equity": round(float(peak), 8),
                    "trough_equity": round(float(equity), 8),
                    "trough_price": round(float(exec_price), 2),
                    "trough_side": _side_label(book.side),
                    "trough_weight": round(float(new_weight), 4),
                    "trough_qty": round(float(book.qty), 6),
                    "trough_avg_entry": round(float(book.avg_entry), 2) if book.side != 0 else 0.0,
                    "trough_regime": market.regime,
                    "trough_router_mode": route_mode,
                    "trough_one_way_side": _side_label(market.one_way_side),
                    "trough_one_way_score": round(float(market.one_way_score), 4),
                    "trough_score_diff": int(market.score_diff),
                    "trough_zone_side": _side_label(zone.side),
                    "trough_zone_score": int(zone.score),
                    "trough_zone_mode": zone.mode,
                    "trough_zone_stage": zone.stage,
                    "trough_no_trade_reasons": list(zone.no_trade_reasons),
                    "trough_open_lot_count_by_role": lot_count_by_role,
                    "trough_open_qty_by_role": qty_by_role,
                    "trough_bar_event_count": len(new_trade_events),
                    "trough_bar_events": _drawdown_bar_event_payload(new_trade_events),
                    "recovered_peak": False,
                    "recovered_peak_ts": None,
                    "trough_to_recovery_bars": None,
                    "trough_to_recovery_hours": None,
                }
                max_drawdown_recovery_peak_equity = peak
            max_drawdown_trough_idx = exec_idx
            circuit_rearm_drawdown = max(float(config.equity_circuit_rearm_drawdown_pct), 0.0) / 100.0
            circuit_rearm_enabled = circuit_rearm_drawdown > 0.0
            if circuit_rearm_enabled and not equity_circuit_armed and drawdown <= circuit_rearm_drawdown:
                equity_circuit_armed = True
                counters["equity_circuit_breaker_rearmed"] += 1
                _record_event(
                    events,
                    ts=features.ts[exec_idx],
                    action="risk",
                    side=book.side,
                    qty=book.qty,
                    price=exec_price,
                    reason="equity_circuit_breaker_rearmed",
                    equity=equity,
                    extra={
                        "drawdown_pct": round(drawdown * 100.0, 4),
                        "rearm_drawdown_pct": round(circuit_rearm_drawdown * 100.0, 4),
                    },
                )
            if (
                config.equity_circuit_breaker_drawdown_pct > 0.0
                and config.equity_circuit_breaker_pause_bars > 0
                and drawdown >= config.equity_circuit_breaker_drawdown_pct / 100.0
                and exec_idx > equity_circuit_pause_until_idx
                and (not circuit_rearm_enabled or equity_circuit_armed)
            ):
                equity_circuit_pause_until_idx = exec_idx + config.equity_circuit_breaker_pause_bars
                if circuit_rearm_enabled:
                    equity_circuit_armed = False
                counters["equity_circuit_breaker_triggers"] += 1
                _record_event(
                    events,
                    ts=features.ts[exec_idx],
                    action="risk",
                    side=book.side,
                    qty=book.qty,
                    price=exec_price,
                    reason="equity_circuit_breaker_trigger",
                    equity=equity,
                    extra={
                        "drawdown_pct": round(drawdown * 100.0, 4),
                        "pause_bars": int(config.equity_circuit_breaker_pause_bars),
                        "rearm_drawdown_pct": round(circuit_rearm_drawdown * 100.0, 4),
                    },
                )
            if (
                config.equity_soft_circuit_drawdown_pct > 0.0
                and config.equity_soft_circuit_cooldown_bars > 0
                and (
                    config.equity_soft_circuit_force_flat
                    or config.equity_soft_circuit_size_mult < 1.0 - 1e-12
                )
                and drawdown >= config.equity_soft_circuit_drawdown_pct / 100.0
                and exec_idx > equity_soft_circuit_cooldown_until_idx
            ):
                grace_bars = max(0, int(config.equity_soft_circuit_min_bars_after_add))
                grace_active = grace_bars > 0 and exec_idx - last_entry_add_idx < grace_bars
                if grace_active:
                    counters["equity_soft_circuit_grace_blocks"] += 1
                else:
                    equity_soft_circuit_cooldown_until_idx = exec_idx + config.equity_soft_circuit_cooldown_bars
                    equity_soft_circuit_force_exit_pending = bool(config.equity_soft_circuit_force_flat)
                    if equity_soft_circuit_force_exit_pending:
                        equity_soft_circuit_inventory_trim_pending_fraction = 0.0
                    else:
                        equity_soft_circuit_inventory_trim_pending_fraction = _clamp(
                            config.equity_soft_circuit_inventory_trim_fraction,
                            0.0,
                            1.0,
                        )
                    counters["equity_soft_circuit_triggers"] += 1
                    _record_event(
                        events,
                        ts=features.ts[exec_idx],
                        action="risk",
                        side=book.side,
                        qty=book.qty,
                        price=exec_price,
                        reason="equity_soft_circuit_trigger",
                        equity=equity,
                        extra={
                            "drawdown_pct": round((1.0 - equity / peak) * 100.0, 4),
                            "cooldown_bars": int(config.equity_soft_circuit_cooldown_bars),
                            "size_mult": round(_clamp(config.equity_soft_circuit_size_mult, 0.0, 1.0), 4),
                            "force_flat": bool(config.equity_soft_circuit_force_flat),
                            "inventory_trim_fraction": round(
                                _clamp(config.equity_soft_circuit_inventory_trim_fraction, 0.0, 1.0),
                                4,
                            ),
                            "min_bars_after_add": grace_bars,
                        },
                    )
        if (
            max_drawdown_detail
            and not bool(max_drawdown_detail.get("recovered_peak"))
            and max_drawdown_trough_idx >= 0
            and exec_idx > max_drawdown_trough_idx
            and equity >= max_drawdown_recovery_peak_equity - 1e-12
        ):
            recovery_bars = max(exec_idx - max_drawdown_trough_idx, 0)
            max_drawdown_detail["recovered_peak"] = True
            max_drawdown_detail["recovered_peak_ts"] = features.ts[exec_idx].isoformat()
            max_drawdown_detail["trough_to_recovery_bars"] = recovery_bars
            max_drawdown_detail["trough_to_recovery_hours"] = round(
                recovery_bars * _INTERVAL_MS[config.exec_interval] / 3_600_000.0,
                4,
            )
        if gross_peak > 0.0:
            gross_max_drawdown = max(gross_max_drawdown, 1.0 - gross_equity / gross_peak)
        exposure_sum += abs(new_weight)
        max_abs_weight = max(max_abs_weight, abs(new_weight))
        exposure_bars += 1
        if new_weight > 1e-12:
            exposure_side_bars["long"] += 1
        elif new_weight < -1e-12:
            exposure_side_bars["short"] += 1
        else:
            exposure_side_bars["flat"] += 1

        if equity <= 0.02:
            counters["account_ruin_events"] += 1
            break
        previous_regime = market.regime
        previous_router_mode = route_mode

    if book.side != 0:
        removed = book.remove(qty=book.qty, price=features.c[-1], role_priority=("battle", "chase", "base", "probe"))
        _exit_removed_lots(
            events=events,
            removed=removed,
            ts=features.ts[-1],
            action="remove",
            reason="end_of_sample",
            equity=equity,
        )

    first_ts = features.ts[warmup + 1] if len(features.ts) > warmup + 1 else features.ts[0]
    last_ts = features.ts[min(len(features.ts) - 1, warmup + 1 + exposure_bars)] if exposure_bars else features.ts[-1]
    years = max(_year_fraction(first_ts, last_ts), 1e-12)
    final_return = equity - 1.0
    gross_return = gross_equity - 1.0
    cagr = equity ** (1.0 / years) - 1.0 if equity > 0.0 else -1.0
    gross_cagr = gross_equity ** (1.0 / years) - 1.0 if gross_equity > 0.0 else -1.0
    periods_per_year = 365.25 * 24.0 * 60.0 * 60.0 * 1000.0 / _INTERVAL_MS[config.exec_interval]
    if len(bar_returns) >= 5:
        avg_ret = mean(bar_returns)
        vol = pstdev(bar_returns)
        sharpe = avg_ret / vol * math.sqrt(periods_per_year) if vol > 1e-12 else 0.0
    else:
        sharpe = 0.0

    monthly = _monthly_stats(month_equity)
    calendar_rolling = _calendar_rolling_stats(day_equity)
    battle_success = counters.get("battle_success", 0)
    battle_failed = counters.get("battle_failed", 0)
    battle_resolved = battle_success + battle_failed
    battle_success_rate = battle_success / battle_resolved if battle_resolved else 0.0
    avg_abs_weight = exposure_sum / max(exposure_bars, 1)
    score = (
        cagr
        - 1.45 * max_drawdown
        + 0.25 * sharpe
        + 0.20 * monthly["monthly_double_rate"]
        + 0.18 * battle_success_rate
        - 1.75 * counters.get("liquidations", 0)
        - 2.50 * counters.get("account_ruin_events", 0)
    )

    trade_like_events = (
        counters.get("probe_adds", 0)
        + counters.get("base_adds", 0)
        + counters.get("battle_adds", 0)
        + counters.get("chase_adds", 0)
        + counters.get("switches", 0)
    )
    if len(events) <= 24:
        sample_events = events
    else:
        sample_events = events[:12] + [{"omitted_events": len(events) - 24}] + events[-12:]
    recent_events = events[-max(1, int(recent_event_limit)) :] if events else []
    event_diagnostics = _event_diagnostics(
        events=events,
        counters=counters,
        exposure_side_bars=exposure_side_bars,
        exposure_bars=exposure_bars,
        total_months=int(monthly["months"]),
        config=config,
    )
    cost_diagnostics = {
        "modeled_trade_cost_pct": round(modeled_trade_cost_fraction_sum * 100.0, 4),
        "modeled_carry_cost_pct": round(modeled_carry_cost_fraction_sum * 100.0, 4),
        "by_action_pct": _top_cost_pct_payload(cost_breakdown["by_action"]),
        "by_side_pct": _top_cost_pct_payload(cost_breakdown["by_side"]),
        "by_role_pct": _top_cost_pct_payload(cost_breakdown["by_role"]),
        "by_reason_pct": _top_cost_pct_payload(cost_breakdown["by_reason"]),
        "by_action_reason_pct": _top_cost_pct_payload(cost_breakdown["by_action_reason"]),
        "by_action_role_pct": _top_cost_pct_payload(cost_breakdown["by_action_role"]),
    }
    regime_performance = _performance_payload(regime_stats)
    router_mode_performance = _performance_payload(router_mode_stats)

    return {
        "model_id": config.model_id,
        "symbol": symbol,
        "exec_interval": config.exec_interval,
        "scenario_intervals": list(scenario_features),
        "final_equity": round(equity, 8),
        "gross_final_equity_before_costs": round(gross_equity, 8),
        "total_return_pct": round(final_return * 100.0, 4),
        "gross_return_pct_before_costs": round(gross_return * 100.0, 4),
        "estimated_cost_drag_pct": round((gross_return - final_return) * 100.0, 4),
        "cagr_pct": round(cagr * 100.0, 4),
        "gross_cagr_pct_before_costs": round(gross_cagr * 100.0, 4),
        "max_drawdown_pct": round(max_drawdown * 100.0, 4),
        "max_drawdown_detail": max_drawdown_detail,
        "gross_max_drawdown_pct_before_costs": round(gross_max_drawdown * 100.0, 4),
        "modeled_trade_cost_fraction_sum": round(modeled_trade_cost_fraction_sum, 8),
        "modeled_carry_cost_fraction_sum": round(modeled_carry_cost_fraction_sum, 8),
        "min_equity": round(min_equity, 8),
        "gross_min_equity_before_costs": round(gross_min_equity, 8),
        "sharpe_proxy": round(sharpe, 4),
        "years": round(years, 4),
        "score": round(score, 6),
        "avg_abs_account_exposure": round(avg_abs_weight, 4),
        "max_abs_account_exposure": round(max_abs_weight, 4),
        "trade_like_events": int(trade_like_events),
        "event_counts": dict(counters),
        "battle_adds": int(counters.get("battle_adds", 0)),
        "battle_success_rate": round(battle_success_rate, 6),
        "monthly": monthly,
        "calendar_rolling": calendar_rolling,
        "regime_performance": regime_performance,
        "router_mode_performance": router_mode_performance,
        "event_diagnostics": event_diagnostics,
        "cost_diagnostics": cost_diagnostics,
        "config": asdict(config),
        "sample_events": sample_events,
        "recent_events": recent_events,
    }


def build_configs(
    *,
    exec_interval: str,
    exchange_leverage: float,
    maintenance_margin_pct: float,
    max_account_exposures: list[float],
    max_possible_units_options: list[float],
    battle_units_options: list[float],
    probe_units_options: list[float],
    volume_layer_enabled: bool,
    one_way_trim_min_adverse_reaction: float,
    one_way_trim_cooldown_bars: int,
    one_way_trim_size_mult: float,
    hard_time_exit_fraction: float,
    hard_time_exit_cooldown_bars: int,
    reaction_trim_trend_hold_trigger_mult: float,
    hard_time_exit_trend_defer_bars: int,
    hard_time_exit_trend_defer_min_favorable_reaction: float,
    trend_hold_min_trend_strength: float,
    trend_hold_min_one_way_score: float,
    one_way_trim_retire_same_zone: bool,
    one_way_trim_same_side_cooldown_bars: int,
    one_way_trim_cluster_guard_count: int,
    one_way_trim_cluster_window_bars: int,
    one_way_trim_cluster_cooldown_bars: int,
    one_way_trim_context_guard_count: int,
    one_way_trim_context_window_bars: int,
    one_way_trim_context_cooldown_bars: int,
    one_way_trim_context_full_exit: bool,
    one_way_loss_fuse_min_adverse_reaction: float,
    one_way_loss_fuse_cooldown_bars: int,
    one_way_loss_fuse_size_mult: float,
    one_way_trim_full_exit_min_one_way_score: float,
    one_way_trim_full_exit_min_score_diff: int,
    trend_idle_probe_units: float,
    trend_idle_min_score: int,
    trend_idle_min_reason_stack: int,
    trend_idle_cooldown_bars: int,
    trend_idle_max_extension_atr: float,
    near_miss_probe_units: float,
    near_miss_probe_min_score: int,
    near_miss_probe_min_score_edge: int,
    near_miss_probe_min_reason_stack: int,
    near_miss_probe_cooldown_bars: int,
    near_miss_probe_max_extension_atr: float,
    near_miss_probe_failure_guard_count: int,
    near_miss_probe_failure_guard_window_bars: int,
    near_miss_probe_failure_cooldown_bars: int,
    equity_circuit_breaker_drawdown_pct: float,
    equity_circuit_breaker_pause_bars: int,
    equity_circuit_rearm_drawdown_pct: float,
    equity_soft_circuit_drawdown_pct: float,
    equity_soft_circuit_cooldown_bars: int,
    equity_soft_circuit_size_mult: float,
    equity_soft_circuit_force_flat: bool,
    equity_soft_circuit_inventory_trim_fraction: float,
    equity_soft_circuit_prearm_bars: int,
    equity_soft_circuit_min_bars_after_add: int,
    equity_soft_circuit_recovery_probe_units: float,
    equity_soft_circuit_recovery_min_one_way_score: float,
    equity_soft_circuit_recovery_min_score_diff: int,
    equity_soft_circuit_recovery_max_extension_atr: float,
    equity_soft_circuit_recovery_failure_guard_count: int,
    equity_soft_circuit_recovery_failure_guard_window_bars: int,
    equity_soft_circuit_recovery_failure_cooldown_bars: int,
    one_way_reversal_switch_units: float,
    one_way_reversal_min_score_edge: int,
    one_way_reversal_cooldown_bars: int,
    one_way_reversal_allow_scenario_override: bool,
    one_way_reversal_allow_score_override: bool,
    one_way_impulse_probe_units: float,
    one_way_impulse_min_one_way_score: float,
    one_way_impulse_min_score_diff: int,
    one_way_impulse_cooldown_bars: int,
    one_way_impulse_max_extension_atr: float,
    scenario_flip_units: float,
    scenario_flip_min_score_edge: int,
    scenario_flip_min_adverse_reaction: float,
    scenario_flip_min_one_way_score: float,
    scenario_flip_cooldown_bars: int,
    scenario_flip_max_extension_atr: float,
    winner_pyramid_units: float,
    winner_pyramid_min_profit_reaction: float,
    winner_pyramid_min_score: int,
    winner_pyramid_min_reason_stack: int,
    winner_pyramid_cooldown_bars: int,
    winner_pyramid_max_units: float,
    winner_pyramid_min_extension_atr: float,
    winner_pyramid_max_extension_atr: float,
    winner_pyramid_block_risk_off: bool,
    winner_pyramid_block_one_way_chase: bool,
    base_entry_max_extension_atr: float,
    base_entry_max_extension_side: str,
    base_entry_reduce_extension_atr: float,
    base_entry_reduce_size_mult: float,
    base_entry_reduce_promote_reaction: float,
    base_entry_reduce_max_trend_strength: float,
    base_entry_reduce_min_trend_strength: float,
    base_entry_reduce_side: str,
    base_context_reduce_size_mult: float,
    base_context_reduce_patterns: tuple[str, ...],
    fragile_regime_entry_size_mult: float,
    fragile_regime_entry_regimes: tuple[str, ...],
    fragile_regime_inventory_trim_fraction: float,
    fragile_regime_inventory_trim_regimes: tuple[str, ...],
    event_risk_base_reduce_size_mult: float,
    event_risk_base_reduce_min_extension_atr: float,
    event_risk_base_reduce_max_extension_atr: float,
    event_risk_base_reduce_side: str,
    event_risk_base_reduce_contexts: tuple[str, ...],
    regime_router_enabled: bool,
    router_trend_reaction_size_mult: float,
    router_one_way_chase_size_mult: float,
    router_one_way_counter_size_mult: float,
    router_range_probe_size_mult: float,
    router_range_base_size_mult: float,
    router_exhaustion_reversal_size_mult: float,
    router_exhaustion_min_score_edge: int,
    router_exhaustion_min_extension_atr: float,
    router_risk_off_size_mult: float,
    router_transition_trim_fraction: float,
    router_transition_trim_modes: tuple[str, ...],
    router_transition_trim_against_only: bool,
    router_transition_trim_cooldown_bars: int,
    defensive_trim_cooldown_bars: int,
    reaction_trim_trigger: float,
    reaction_trim_size_mult: float,
    reaction_avg_band: float,
    skip_weak_long_round_reclaim: bool,
    blocked_kst_entry_hours: tuple[int, ...],
) -> list[MarketStateConfig]:
    configs: list[MarketStateConfig] = []
    seen_model_ids: set[str] = set()
    profiles = (
        ("balanced", False, 1.10, 1.55, 1.25, 0.45, 2.8),
        ("strict_sample_generalized", True, 0.90, 1.20, 0.90, 0.55, 2.5),
    )
    impulse_suffix = ""
    if one_way_impulse_probe_units > 1e-12:
        impulse_suffix = (
            f":owImp{max(0.0, float(one_way_impulse_probe_units)):g}"
            f":owImpScore{max(0.0, float(one_way_impulse_min_one_way_score)):g}"
            f":owImpDiff{int(one_way_impulse_min_score_diff)}"
            f":owImpCool{max(0, int(one_way_impulse_cooldown_bars))}"
            f":owImpExt{max(0.1, float(one_way_impulse_max_extension_atr)):g}"
        )
    btc_rotation_suffix = ""
    if scenario_flip_units > 1e-12:
        btc_rotation_suffix += (
            f":scnFlip{max(0.0, float(scenario_flip_units)):g}"
            f":scnFlipEdge{int(scenario_flip_min_score_edge)}"
            f":scnFlipAdv{max(0.0, float(scenario_flip_min_adverse_reaction)):g}"
            f":scnFlipOw{max(0.0, float(scenario_flip_min_one_way_score)):g}"
            f":scnFlipCool{max(0, int(scenario_flip_cooldown_bars))}"
            f":scnFlipExt{max(0.1, float(scenario_flip_max_extension_atr)):g}"
        )
    if winner_pyramid_units > 1e-12:
        btc_rotation_suffix += (
            f":winPyr{max(0.0, float(winner_pyramid_units)):g}"
            f":winPyrReact{max(0.0, float(winner_pyramid_min_profit_reaction)):g}"
            f":winPyrScore{int(winner_pyramid_min_score)}"
            f":winPyrStack{max(0, int(winner_pyramid_min_reason_stack))}"
            f":winPyrCool{max(0, int(winner_pyramid_cooldown_bars))}"
            f":winPyrMax{max(0.0, float(winner_pyramid_max_units)):g}"
            f":winPyrMinExt{max(0.0, float(winner_pyramid_min_extension_atr)):g}"
            f":winPyrExt{max(0.1, float(winner_pyramid_max_extension_atr)):g}"
        )
        if bool(winner_pyramid_block_risk_off):
            btc_rotation_suffix += ":winPyrNoRiskOff"
        if bool(winner_pyramid_block_one_way_chase):
            btc_rotation_suffix += ":winPyrNoOwChase"
    trim_memory_suffix = ""
    if one_way_trim_retire_same_zone:
        trim_memory_suffix += ":owRetire1"
    if one_way_trim_same_side_cooldown_bars > 0:
        trim_memory_suffix += f":owSideCool{max(0, int(one_way_trim_same_side_cooldown_bars))}"
    if one_way_trim_cluster_guard_count > 0 and one_way_trim_cluster_cooldown_bars > 0:
        trim_memory_suffix += (
            f":owCluster{max(1, int(one_way_trim_cluster_guard_count))}"
            f"x{max(1, int(one_way_trim_cluster_window_bars))}"
            f"c{max(1, int(one_way_trim_cluster_cooldown_bars))}"
        )
    if one_way_trim_context_guard_count > 0 and one_way_trim_context_cooldown_bars > 0:
        trim_memory_suffix += (
            f":owCtxQ{max(1, int(one_way_trim_context_guard_count))}"
            f"x{max(1, int(one_way_trim_context_window_bars))}"
            f"c{max(1, int(one_way_trim_context_cooldown_bars))}"
        )
        if one_way_trim_context_full_exit:
            trim_memory_suffix += ":owCtxQExit1"
    if (
        one_way_loss_fuse_min_adverse_reaction > 0.0
        and one_way_loss_fuse_cooldown_bars > 0
        and one_way_loss_fuse_size_mult < 1.0
    ):
        trim_memory_suffix += (
            f":owLossFuse{max(0.0, float(one_way_loss_fuse_min_adverse_reaction)):g}"
            f"c{max(1, int(one_way_loss_fuse_cooldown_bars))}"
            f"m{_clamp(one_way_loss_fuse_size_mult, 0.0, 1.0):g}"
        )
    if one_way_trim_full_exit_min_one_way_score > 0.0:
        trim_memory_suffix += (
            f":owFullExit{max(0.0, float(one_way_trim_full_exit_min_one_way_score)):g}"
            f"d{max(0, int(one_way_trim_full_exit_min_score_diff))}"
        )
    cost_throttle_suffix = ""
    if one_way_trim_size_mult < 1.0:
        cost_throttle_suffix += f":owTrimMult{_clamp(one_way_trim_size_mult, 0.05, 1.0):g}"
    if hard_time_exit_fraction < 1.0:
        cost_throttle_suffix += (
            f":hardTimeFrac{_clamp(hard_time_exit_fraction, 0.05, 1.0):g}"
            f"x{max(0, int(hard_time_exit_cooldown_bars))}"
        )
    if reaction_trim_size_mult < 1.0:
        cost_throttle_suffix += f":rTrimMult{_clamp(reaction_trim_size_mult, 0.05, 1.0):g}"
    if reaction_trim_trend_hold_trigger_mult > 1.0:
        cost_throttle_suffix += (
            f":rTrendHold{_clamp(reaction_trim_trend_hold_trigger_mult, 1.0, 5.0):g}"
        )
    if hard_time_exit_trend_defer_bars > 0:
        cost_throttle_suffix += (
            f":hardTrendDef{max(0, int(hard_time_exit_trend_defer_bars))}"
            f"f{max(0.0, float(hard_time_exit_trend_defer_min_favorable_reaction)):g}"
        )
    if (
        reaction_trim_trend_hold_trigger_mult > 1.0
        or hard_time_exit_trend_defer_bars > 0
    ):
        cost_throttle_suffix += (
            f":trendHoldT{max(0.0, float(trend_hold_min_trend_strength)):g}"
            f"O{max(0.0, float(trend_hold_min_one_way_score)):g}"
        )
    trend_idle_suffix = ""
    if trend_idle_probe_units > 1e-12:
        trend_idle_suffix = (
            f":idleProbe{max(0.0, float(trend_idle_probe_units)):g}"
            f":idleScore{int(trend_idle_min_score)}"
            f":idleStack{max(0, int(trend_idle_min_reason_stack))}"
            f":idleCool{max(0, int(trend_idle_cooldown_bars))}"
            f":idleExt{max(0.1, float(trend_idle_max_extension_atr)):g}"
        )
    near_miss_suffix = ""
    if near_miss_probe_units > 1e-12:
        near_miss_suffix = (
            f":nearMiss{max(0.0, float(near_miss_probe_units)):g}"
            f":nearMissScore{int(near_miss_probe_min_score)}"
            f":nearMissEdge{int(near_miss_probe_min_score_edge)}"
            f":nearMissStack{max(0, int(near_miss_probe_min_reason_stack))}"
            f":nearMissCool{max(0, int(near_miss_probe_cooldown_bars))}"
            f":nearMissExt{max(0.1, float(near_miss_probe_max_extension_atr)):g}"
        )
        if near_miss_probe_failure_guard_count > 0 and near_miss_probe_failure_cooldown_bars > 0:
            near_miss_suffix += (
                f":nearMissFail{max(1, int(near_miss_probe_failure_guard_count))}"
                f"x{max(1, int(near_miss_probe_failure_guard_window_bars))}"
                f"c{max(1, int(near_miss_probe_failure_cooldown_bars))}"
            )
    circuit_suffix = ""
    if equity_circuit_breaker_drawdown_pct > 0.0 and equity_circuit_breaker_pause_bars > 0:
        circuit_suffix = (
            f":eqCb{max(0.0, float(equity_circuit_breaker_drawdown_pct)):g}"
            f"x{max(1, int(equity_circuit_breaker_pause_bars))}"
        )
        if equity_circuit_rearm_drawdown_pct > 0.0:
            circuit_suffix += f":eqCbRearm{max(0.0, float(equity_circuit_rearm_drawdown_pct)):g}"
    soft_circuit_suffix = ""
    if equity_soft_circuit_drawdown_pct > 0.0 and equity_soft_circuit_cooldown_bars > 0:
        soft_circuit_suffix = (
            f":eqSoft{max(0.0, float(equity_soft_circuit_drawdown_pct)):g}"
            f"x{max(1, int(equity_soft_circuit_cooldown_bars))}"
            f"m{_clamp(equity_soft_circuit_size_mult, 0.0, 1.0):g}"
        )
        if equity_soft_circuit_force_flat:
            soft_circuit_suffix += ":eqSoftFlat1"
        if equity_soft_circuit_inventory_trim_fraction > 0.0:
            soft_circuit_suffix += (
                f":eqSoftInvTrim{_clamp(equity_soft_circuit_inventory_trim_fraction, 0.0, 1.0):g}"
            )
        if equity_soft_circuit_prearm_bars > 0:
            soft_circuit_suffix += f":eqSoftPre{max(1, int(equity_soft_circuit_prearm_bars))}"
        if equity_soft_circuit_min_bars_after_add > 0:
            soft_circuit_suffix += (
                f":eqSoftGrace{max(1, int(equity_soft_circuit_min_bars_after_add))}"
            )
    if equity_soft_circuit_recovery_probe_units > 1e-12:
        soft_circuit_suffix += (
            f":eqSoftRec{max(0.0, float(equity_soft_circuit_recovery_probe_units)):g}"
            f"ow{max(0.0, float(equity_soft_circuit_recovery_min_one_way_score)):g}"
            f"d{max(0, int(equity_soft_circuit_recovery_min_score_diff))}"
            f"e{max(0.1, float(equity_soft_circuit_recovery_max_extension_atr)):g}"
        )
    if (
        equity_soft_circuit_recovery_failure_guard_count > 0
        and equity_soft_circuit_recovery_failure_cooldown_bars > 0
    ):
        soft_circuit_suffix += (
            f":eqSoftRecFail{max(1, int(equity_soft_circuit_recovery_failure_guard_count))}"
            f"x{max(1, int(equity_soft_circuit_recovery_failure_guard_window_bars))}"
            f"c{max(1, int(equity_soft_circuit_recovery_failure_cooldown_bars))}"
        )
    base_extension_suffix = ""
    if base_entry_max_extension_atr > 0.0:
        base_extension_suffix = f":baseExt{max(0.1, float(base_entry_max_extension_atr)):g}"
        if base_entry_max_extension_side != "both":
            base_extension_suffix += f":baseExtSide{base_entry_max_extension_side}"
    base_reduce_suffix = ""
    if base_entry_reduce_extension_atr > 0.0 and base_entry_reduce_size_mult < 1.0:
        base_reduce_suffix = (
            f":baseReduce{max(0.1, float(base_entry_reduce_extension_atr)):g}"
            f"x{_clamp(base_entry_reduce_size_mult, 0.0, 1.0):g}"
        )
        if base_entry_reduce_promote_reaction > 0.0:
            base_reduce_suffix += f":basePromote{max(0.0, float(base_entry_reduce_promote_reaction)):g}"
        if base_entry_reduce_max_trend_strength > 0.0:
            base_reduce_suffix += f":baseReduceMaxTrend{max(0.0, float(base_entry_reduce_max_trend_strength)):g}"
        if base_entry_reduce_min_trend_strength > 0.0:
            base_reduce_suffix += f":baseReduceMinTrend{max(0.0, float(base_entry_reduce_min_trend_strength)):g}"
        if base_entry_reduce_side != "both":
            base_reduce_suffix += f":baseReduceSide{base_entry_reduce_side}"
    base_context_reduce_suffix = ""
    if base_context_reduce_patterns and base_context_reduce_size_mult < 1.0:
        base_context_reduce_suffix = (
            f":baseCtxReduce{_clamp(base_context_reduce_size_mult, 0.0, 1.0):g}"
            f":baseCtxSet{_format_base_context_patterns(base_context_reduce_patterns)}"
        )
    fragile_regime_suffix = ""
    if fragile_regime_entry_regimes and fragile_regime_entry_size_mult < 1.0:
        regime_code = "-".join(
            regime.replace("range_or_transition", "range").replace("one_way_", "ow")
            for regime in fragile_regime_entry_regimes
        )
        fragile_regime_suffix = (
            f":fragReg{_clamp(fragile_regime_entry_size_mult, 0.0, 1.0):g}"
            f":fragRegSet{regime_code}"
        )
    fragile_inventory_suffix = ""
    if fragile_regime_inventory_trim_regimes and fragile_regime_inventory_trim_fraction > 0.0:
        regime_code = "-".join(
            regime.replace("range_or_transition", "range").replace("one_way_", "ow")
            for regime in fragile_regime_inventory_trim_regimes
        )
        fragile_inventory_suffix = (
            f":fragInvTrim{_clamp(fragile_regime_inventory_trim_fraction, 0.0, 1.0):g}"
            f":fragInvSet{regime_code}"
        )
    event_risk_base_suffix = ""
    if event_risk_base_reduce_contexts and event_risk_base_reduce_size_mult < 1.0:
        event_risk_base_suffix = (
            f":eventBaseRisk{_format_event_risk_contexts(event_risk_base_reduce_contexts)}"
            f":eventBaseMinExt{max(0.0, float(event_risk_base_reduce_min_extension_atr)):g}"
            f":eventBaseMult{_clamp(event_risk_base_reduce_size_mult, 0.0, 1.0):g}"
        )
        if event_risk_base_reduce_max_extension_atr > 0.0:
            event_risk_base_suffix += (
                f":eventBaseMaxExt{max(0.0, float(event_risk_base_reduce_max_extension_atr)):g}"
            )
        if event_risk_base_reduce_side != "both":
            event_risk_base_suffix += f":eventBaseSide{event_risk_base_reduce_side}"
    router_suffix = ""
    if regime_router_enabled:
        router_suffix = (
            f":router1"
            f":rtTrend{_clamp(router_trend_reaction_size_mult, 0.0, 1.5):g}"
            f":rtOw{_clamp(router_one_way_chase_size_mult, 0.0, 1.5):g}"
            f":rtOwCtr{_clamp(router_one_way_counter_size_mult, 0.0, 1.0):g}"
            f":rtRangeP{_clamp(router_range_probe_size_mult, 0.0, 1.0):g}"
            f":rtRangeB{_clamp(router_range_base_size_mult, 0.0, 1.0):g}"
            f":rtExh{_clamp(router_exhaustion_reversal_size_mult, 0.0, 1.0):g}"
            f":rtExhEdge{max(0, int(router_exhaustion_min_score_edge))}"
            f":rtExhExt{max(0.0, float(router_exhaustion_min_extension_atr)):g}"
            f":rtRisk{_clamp(router_risk_off_size_mult, 0.0, 1.0):g}"
        )
        if router_transition_trim_fraction > 0.0 and router_transition_trim_modes:
            router_suffix += (
                f":rtTransTrim{_clamp(router_transition_trim_fraction, 0.0, 1.0):g}"
                f":rtTransModes{'-'.join(router_transition_trim_modes)}"
                f":rtTransAgainst{int(bool(router_transition_trim_against_only))}"
            )
            if router_transition_trim_cooldown_bars > 0:
                router_suffix += f":rtTransCool{max(0, int(router_transition_trim_cooldown_bars))}"
    for zone_lookback in (48, 96):
        for entry_score in (5, 6):
            for battle_score in (7, 8):
                for base_max_units in (3.0, 5.0):
                    for battle_units in battle_units_options:
                        for max_possible_units in max_possible_units_options:
                            effective_base_max_units = min(base_max_units, max_possible_units)
                            effective_battle_units = min(battle_units, max_possible_units)
                            if max_possible_units <= 0.0 or effective_base_max_units <= 0.0:
                                continue
                            for max_exposure in max_account_exposures:
                                for probe_units in probe_units_options:
                                    effective_probe_units = min(probe_units, max_possible_units)
                                    for reaction_usd in (200.0, 350.0):
                                        for max_battle_bars in (3, 6):
                                            for max_hold_bars in (52, 53):
                                                for (
                                                    profile_name,
                                                    strict_scenario_entry,
                                                    repair_cut,
                                                    repair_stop,
                                                    max_repair_eff_for_add,
                                                    min_capacity_ratio,
                                                    bad_rr_atr,
                                                ) in profiles:
                                                    model_id = (
                                                    f"{exec_interval}:market_state_rotation_v6:{profile_name}:"
                                                    f"lb{zone_lookback}:entry{entry_score}:battle{battle_score}:"
                                                    f"maxU{max_possible_units:g}:"
                                                    f"baseMax{effective_base_max_units:g}:battleU{effective_battle_units:g}:"
                                                    f"probe{effective_probe_units:g}:"
                                                    f"gross{max_exposure:g}:react{reaction_usd:g}:"
                                                    f"bBars{max_battle_bars}:hold{max_hold_bars}:lev{exchange_leverage:g}:"
                                                    f"dCool{max(0, int(defensive_trim_cooldown_bars))}:"
                                                    f"owMin{max(0.0, float(one_way_trim_min_adverse_reaction)):g}:"
                                                    f"owCool{max(0, int(one_way_trim_cooldown_bars))}{trim_memory_suffix}:"
                                                    f"owRev{max(0.0, float(one_way_reversal_switch_units)):g}:"
                                                    f"owRevEdge{int(one_way_reversal_min_score_edge)}:"
                                                    f"owRevCool{max(0, int(one_way_reversal_cooldown_bars))}:"
                                                    f"owRevScn{int(bool(one_way_reversal_allow_scenario_override))}:"
                                                    f"owRevScore{int(bool(one_way_reversal_allow_score_override))}:"
                                                    f"rTrim{max(0.05, float(reaction_trim_trigger)):g}:"
                                                    f"rBand{max(0.05, float(reaction_avg_band)):g}:"
                                                    f"wlSkip{int(bool(skip_weak_long_round_reclaim))}:"
                                                    f"kstBlock{_format_kst_hours(blocked_kst_entry_hours)}:"
                                                    f"sbKst{_format_kst_hours(CONTEXTUAL_SHORT_BASE_BLOCK_KST_HOURS)}:"
                                                    f"owLongTrim{ONE_WAY_LONG_TRIM_FRACTION:g}:"
                                                    f"ctxReact{CONTEXT_REACTION_TARGET_USD:g}:ctxF18"
                                                    f"{trend_idle_suffix}"
                                                    f"{near_miss_suffix}"
                                                    f"{cost_throttle_suffix}"
                                                    f"{circuit_suffix}"
                                                    f"{soft_circuit_suffix}"
                                                    f"{impulse_suffix}"
                                                    f"{btc_rotation_suffix}"
                                                    f"{base_extension_suffix}"
                                                    f"{base_reduce_suffix}"
                                                    f"{base_context_reduce_suffix}"
                                                    f"{fragile_regime_suffix}"
                                                    f"{fragile_inventory_suffix}"
                                                    f"{event_risk_base_suffix}"
                                                    f"{router_suffix}"
                                                )
                                                    if model_id in seen_model_ids:
                                                        continue
                                                    seen_model_ids.add(model_id)
                                                    configs.append(
                                                    MarketStateConfig(
                                                    model_id=model_id,
                                                    exec_interval=exec_interval,
                                                    htf_fast=21,
                                                    htf_slow=89,
                                                    htf_band_atr=0.12,
                                                    exec_fast=13,
                                                    exec_slow=55,
                                                    zone_lookback=zone_lookback,
                                                    entry_score=entry_score,
                                                    battle_score=battle_score,
                                                    opposite_score=max(entry_score + 1, 7),
                                                    max_possible_units=max_possible_units,
                                                    base_max_units=effective_base_max_units,
                                                    probe_units=effective_probe_units,
                                                    base_add_units=1.0,
                                                    battle_units=effective_battle_units,
                                                    chase_units=1.5 if profile_name == "balanced" else 1.0,
                                                    max_account_exposure=max_exposure,
                                                    exchange_leverage=exchange_leverage,
                                                    maintenance_margin_pct=maintenance_margin_pct,
                                                    reaction_usd=reaction_usd,
                                                    reaction_atr=1.15,
                                                    base_spacing_atr=0.75,
                                                    battle_trigger_usd=max(180.0, reaction_usd),
                                                    battle_trigger_atr=1.30,
                                                    repair_cut=repair_cut,
                                                    repair_stop=repair_stop,
                                                    max_repair_eff_for_add=max_repair_eff_for_add,
                                                    min_capacity_ratio=min_capacity_ratio,
                                                    bad_rr_atr=bad_rr_atr,
                                                    one_way_threshold=1.85,
                                                    one_way_window=12,
                                                    min_reason_stack=2 if profile_name == "balanced" else 3,
                                                    flat_score_edge=2,
                                                    battle_primary_score=max(battle_score, 7),
                                                    battle_primary_dist_atr=1.05 if profile_name == "balanced" else 0.85,
                                                    zone_retire_bars=48 if zone_lookback == 48 else 72,
                                                    reaction_trim_trigger=max(0.05, float(reaction_trim_trigger)),
                                                    reaction_trim_size_mult=_clamp(
                                                        reaction_trim_size_mult,
                                                        0.05,
                                                        1.0,
                                                    ),
                                                    reaction_avg_band=max(0.05, float(reaction_avg_band)),
                                                    skip_weak_long_round_reclaim=bool(skip_weak_long_round_reclaim),
                                                    blocked_kst_entry_hours=blocked_kst_entry_hours,
                                                    against_trend_size_mult=0.50 if profile_name == "balanced" else 0.35,
                                                    one_way_against_size_mult=0.25,
                                                    switch_repair_eff=max(repair_cut, 1.15),
                                                    switch_score_edge=1 if profile_name == "balanced" else 2,
                                                    base_primary_score=entry_score + (1 if profile_name == "balanced" else 2),
                                                    base_add_score=entry_score + (1 if profile_name == "balanced" else 2),
                                                    base_requires_major_confluence=False,
                                                    chase_min_score=entry_score if profile_name == "balanced" else entry_score + 1,
                                                    chase_min_reason_stack=2 if profile_name == "balanced" else 3,
                                                    chase_min_breakout_atr=0.04,
                                                    chase_max_breakout_atr=1.25 if profile_name == "balanced" else 0.95,
                                                    chase_max_extension_atr=3.10 if profile_name == "balanced" else 2.55,
                                                    chase_min_one_way_score=1.15 if profile_name == "balanced" else 1.45,
                                                    chase_take_profit_reaction=0.60 if profile_name == "balanced" else 0.50,
                                                    chase_stop_reaction=0.70 if profile_name == "balanced" else 0.55,
                                                    chase_max_bars=18 if profile_name == "balanced" else 12,
                                                    volume_layer_enabled=volume_layer_enabled,
                                                    volume_lookback=48,
                                                    volume_confirm_mult=1.08 if profile_name == "balanced" else 1.15,
                                                    volume_absorption_mult=1.20 if profile_name == "balanced" else 1.30,
                                                    quiet_volume_mult=0.45 if profile_name == "balanced" else 0.50,
                                                    probe_take_profit_reaction=0.55 if profile_name == "balanced" else 0.65,
                                                    probe_stop_reaction=0.85 if profile_name == "balanced" else 0.75,
                                                    probe_max_bars=36 if profile_name == "balanced" else 24,
                                                    probe_reentry_cooldown_bars=3 if profile_name == "balanced" else 4,
                                                    one_way_trim_min_adverse_reaction=max(
                                                        0.0,
                                                        float(one_way_trim_min_adverse_reaction),
                                                    ),
                                                    one_way_trim_cooldown_bars=max(0, int(one_way_trim_cooldown_bars)),
                                                    one_way_trim_size_mult=_clamp(
                                                        one_way_trim_size_mult,
                                                        0.05,
                                                        1.0,
                                                    ),
                                                    hard_time_exit_fraction=_clamp(
                                                        hard_time_exit_fraction,
                                                        0.05,
                                                        1.0,
                                                    ),
                                                    hard_time_exit_cooldown_bars=max(
                                                        0,
                                                        int(hard_time_exit_cooldown_bars),
                                                    ),
                                                    reaction_trim_trend_hold_trigger_mult=_clamp(
                                                        reaction_trim_trend_hold_trigger_mult,
                                                        1.0,
                                                        5.0,
                                                    ),
                                                    hard_time_exit_trend_defer_bars=max(
                                                        0,
                                                        int(hard_time_exit_trend_defer_bars),
                                                    ),
                                                    hard_time_exit_trend_defer_min_favorable_reaction=max(
                                                        0.0,
                                                        float(hard_time_exit_trend_defer_min_favorable_reaction),
                                                    ),
                                                    trend_hold_min_trend_strength=max(
                                                        0.0,
                                                        float(trend_hold_min_trend_strength),
                                                    ),
                                                    trend_hold_min_one_way_score=max(
                                                        0.0,
                                                        float(trend_hold_min_one_way_score),
                                                    ),
                                                    one_way_trim_retire_same_zone=bool(one_way_trim_retire_same_zone),
                                                    one_way_trim_same_side_cooldown_bars=max(
                                                        0,
                                                        int(one_way_trim_same_side_cooldown_bars),
                                                    ),
                                                    one_way_trim_cluster_guard_count=max(
                                                        0,
                                                        int(one_way_trim_cluster_guard_count),
                                                    ),
                                                    one_way_trim_cluster_window_bars=max(
                                                        1,
                                                        int(one_way_trim_cluster_window_bars),
                                                    ),
                                                    one_way_trim_cluster_cooldown_bars=max(
                                                        0,
                                                        int(one_way_trim_cluster_cooldown_bars),
                                                    ),
                                                    one_way_trim_context_guard_count=max(
                                                        0,
                                                        int(one_way_trim_context_guard_count),
                                                    ),
                                                    one_way_trim_context_window_bars=max(
                                                        1,
                                                        int(one_way_trim_context_window_bars),
                                                    ),
                                                    one_way_trim_context_cooldown_bars=max(
                                                        0,
                                                        int(one_way_trim_context_cooldown_bars),
                                                    ),
                                                    one_way_trim_context_full_exit=bool(
                                                        one_way_trim_context_full_exit
                                                    ),
                                                    one_way_loss_fuse_min_adverse_reaction=max(
                                                        0.0,
                                                        float(one_way_loss_fuse_min_adverse_reaction),
                                                    ),
                                                    one_way_loss_fuse_cooldown_bars=max(
                                                        0,
                                                        int(one_way_loss_fuse_cooldown_bars),
                                                    ),
                                                    one_way_loss_fuse_size_mult=_clamp(
                                                        one_way_loss_fuse_size_mult,
                                                        0.0,
                                                        1.0,
                                                    ),
                                                    one_way_trim_full_exit_min_one_way_score=max(
                                                        0.0,
                                                        float(one_way_trim_full_exit_min_one_way_score),
                                                    ),
                                                    one_way_trim_full_exit_min_score_diff=max(
                                                        0,
                                                        int(one_way_trim_full_exit_min_score_diff),
                                                    ),
                                                    trend_idle_probe_units=min(
                                                        max(0.0, float(trend_idle_probe_units)),
                                                        max_possible_units,
                                                    ),
                                                    trend_idle_min_score=int(trend_idle_min_score),
                                                    trend_idle_min_reason_stack=max(
                                                        0,
                                                        int(trend_idle_min_reason_stack),
                                                    ),
                                                    trend_idle_cooldown_bars=max(0, int(trend_idle_cooldown_bars)),
                                                    trend_idle_max_extension_atr=max(
                                                        0.1,
                                                        float(trend_idle_max_extension_atr),
                                                    ),
                                                    near_miss_probe_units=min(
                                                        max(0.0, float(near_miss_probe_units)),
                                                        max_possible_units,
                                                    ),
                                                    near_miss_probe_min_score=int(near_miss_probe_min_score),
                                                    near_miss_probe_min_score_edge=max(
                                                        0,
                                                        int(near_miss_probe_min_score_edge),
                                                    ),
                                                    near_miss_probe_min_reason_stack=max(
                                                        0,
                                                        int(near_miss_probe_min_reason_stack),
                                                    ),
                                                    near_miss_probe_cooldown_bars=max(
                                                        0,
                                                        int(near_miss_probe_cooldown_bars),
                                                    ),
                                                    near_miss_probe_max_extension_atr=max(
                                                        0.1,
                                                        float(near_miss_probe_max_extension_atr),
                                                    ),
                                                    near_miss_probe_failure_guard_count=max(
                                                        0,
                                                        int(near_miss_probe_failure_guard_count),
                                                    ),
                                                    near_miss_probe_failure_guard_window_bars=max(
                                                        1,
                                                        int(near_miss_probe_failure_guard_window_bars),
                                                    ),
                                                    near_miss_probe_failure_cooldown_bars=max(
                                                        0,
                                                        int(near_miss_probe_failure_cooldown_bars),
                                                    ),
                                                    equity_circuit_breaker_drawdown_pct=max(
                                                        0.0,
                                                        float(equity_circuit_breaker_drawdown_pct),
                                                    ),
                                                    equity_circuit_breaker_pause_bars=max(
                                                        0,
                                                        int(equity_circuit_breaker_pause_bars),
                                                    ),
                                                    equity_circuit_rearm_drawdown_pct=max(
                                                        0.0,
                                                        float(equity_circuit_rearm_drawdown_pct),
                                                    ),
                                                    equity_soft_circuit_drawdown_pct=max(
                                                        0.0,
                                                        float(equity_soft_circuit_drawdown_pct),
                                                    ),
                                                    equity_soft_circuit_cooldown_bars=max(
                                                        0,
                                                        int(equity_soft_circuit_cooldown_bars),
                                                    ),
                                                    equity_soft_circuit_size_mult=_clamp(
                                                        equity_soft_circuit_size_mult,
                                                        0.0,
                                                        1.0,
                                                    ),
                                                    equity_soft_circuit_force_flat=bool(equity_soft_circuit_force_flat),
                                                    equity_soft_circuit_inventory_trim_fraction=_clamp(
                                                        equity_soft_circuit_inventory_trim_fraction,
                                                        0.0,
                                                        1.0,
                                                    ),
                                                    equity_soft_circuit_prearm_bars=max(
                                                        0,
                                                        int(equity_soft_circuit_prearm_bars),
                                                    ),
                                                    equity_soft_circuit_min_bars_after_add=max(
                                                        0,
                                                        int(equity_soft_circuit_min_bars_after_add),
                                                    ),
                                                    equity_soft_circuit_recovery_probe_units=min(
                                                        max(0.0, float(equity_soft_circuit_recovery_probe_units)),
                                                        max_possible_units,
                                                    ),
                                                    equity_soft_circuit_recovery_min_one_way_score=max(
                                                        0.0,
                                                        float(equity_soft_circuit_recovery_min_one_way_score),
                                                    ),
                                                    equity_soft_circuit_recovery_min_score_diff=max(
                                                        0,
                                                        int(equity_soft_circuit_recovery_min_score_diff),
                                                    ),
                                                    equity_soft_circuit_recovery_max_extension_atr=max(
                                                        0.1,
                                                        float(equity_soft_circuit_recovery_max_extension_atr),
                                                    ),
                                                    equity_soft_circuit_recovery_failure_guard_count=max(
                                                        0,
                                                        int(equity_soft_circuit_recovery_failure_guard_count),
                                                    ),
                                                    equity_soft_circuit_recovery_failure_guard_window_bars=max(
                                                        1,
                                                        int(equity_soft_circuit_recovery_failure_guard_window_bars),
                                                    ),
                                                    equity_soft_circuit_recovery_failure_cooldown_bars=max(
                                                        0,
                                                        int(equity_soft_circuit_recovery_failure_cooldown_bars),
                                                    ),
                                                    one_way_reversal_switch_units=min(
                                                        max(0.0, float(one_way_reversal_switch_units)),
                                                        max_possible_units,
                                                    ),
                                                    one_way_reversal_min_score_edge=int(one_way_reversal_min_score_edge),
                                                    one_way_reversal_cooldown_bars=max(
                                                        0,
                                                        int(one_way_reversal_cooldown_bars),
                                                    ),
                                                    one_way_reversal_allow_scenario_override=bool(
                                                        one_way_reversal_allow_scenario_override
                                                    ),
                                                    one_way_reversal_allow_score_override=bool(
                                                        one_way_reversal_allow_score_override
                                                    ),
                                                    one_way_impulse_probe_units=min(
                                                        max(0.0, float(one_way_impulse_probe_units)),
                                                        max_possible_units,
                                                    ),
                                                    one_way_impulse_min_one_way_score=max(
                                                        0.0,
                                                        float(one_way_impulse_min_one_way_score),
                                                    ),
                                                    one_way_impulse_min_score_diff=max(
                                                        0,
                                                        int(one_way_impulse_min_score_diff),
                                                    ),
                                                    one_way_impulse_cooldown_bars=max(
                                                        0,
                                                        int(one_way_impulse_cooldown_bars),
                                                    ),
                                                    one_way_impulse_max_extension_atr=max(
                                                        0.1,
                                                        float(one_way_impulse_max_extension_atr),
                                                    ),
                                                    scenario_flip_units=min(
                                                        max(0.0, float(scenario_flip_units)),
                                                        max_possible_units,
                                                    ),
                                                    scenario_flip_min_score_edge=int(scenario_flip_min_score_edge),
                                                    scenario_flip_min_adverse_reaction=max(
                                                        0.0,
                                                        float(scenario_flip_min_adverse_reaction),
                                                    ),
                                                    scenario_flip_min_one_way_score=max(
                                                        0.0,
                                                        float(scenario_flip_min_one_way_score),
                                                    ),
                                                    scenario_flip_cooldown_bars=max(
                                                        0,
                                                        int(scenario_flip_cooldown_bars),
                                                    ),
                                                    scenario_flip_max_extension_atr=max(
                                                        0.1,
                                                        float(scenario_flip_max_extension_atr),
                                                    ),
                                                    winner_pyramid_units=min(
                                                        max(0.0, float(winner_pyramid_units)),
                                                        max_possible_units,
                                                    ),
                                                    winner_pyramid_min_profit_reaction=max(
                                                        0.0,
                                                        float(winner_pyramid_min_profit_reaction),
                                                    ),
                                                    winner_pyramid_min_score=int(winner_pyramid_min_score),
                                                    winner_pyramid_min_reason_stack=max(
                                                        0,
                                                        int(winner_pyramid_min_reason_stack),
                                                    ),
                                                    winner_pyramid_cooldown_bars=max(
                                                        0,
                                                        int(winner_pyramid_cooldown_bars),
                                                    ),
                                                    winner_pyramid_max_units=max(
                                                        0.0,
                                                        float(winner_pyramid_max_units),
                                                    ),
                                                    winner_pyramid_min_extension_atr=max(
                                                        0.0,
                                                        float(winner_pyramid_min_extension_atr),
                                                    ),
                                                    winner_pyramid_max_extension_atr=max(
                                                        0.1,
                                                        float(winner_pyramid_max_extension_atr),
                                                    ),
                                                    winner_pyramid_block_risk_off=bool(winner_pyramid_block_risk_off),
                                                    winner_pyramid_block_one_way_chase=bool(
                                                        winner_pyramid_block_one_way_chase
                                                    ),
                                                    base_entry_max_extension_atr=max(
                                                        0.0,
                                                        float(base_entry_max_extension_atr),
                                                    ),
                                                    base_entry_max_extension_side=(
                                                        base_entry_max_extension_side
                                                        if base_entry_max_extension_side in {"both", "long", "short"}
                                                        else "both"
                                                    ),
                                                    base_entry_reduce_extension_atr=max(
                                                        0.0,
                                                        float(base_entry_reduce_extension_atr),
                                                    ),
                                                    base_entry_reduce_size_mult=_clamp(
                                                        base_entry_reduce_size_mult,
                                                        0.0,
                                                        1.0,
                                                    ),
                                                    base_entry_reduce_promote_reaction=max(
                                                        0.0,
                                                        float(base_entry_reduce_promote_reaction),
                                                    ),
                                                    base_entry_reduce_max_trend_strength=max(
                                                        0.0,
                                                        float(base_entry_reduce_max_trend_strength),
                                                    ),
                                                    base_entry_reduce_min_trend_strength=max(
                                                        0.0,
                                                        float(base_entry_reduce_min_trend_strength),
                                                    ),
                                                    base_entry_reduce_side=(
                                                        base_entry_reduce_side
                                                        if base_entry_reduce_side in {"both", "long", "short"}
                                                        else "both"
                                                    ),
                                                    base_context_reduce_size_mult=_clamp(
                                                        base_context_reduce_size_mult,
                                                        0.0,
                                                        1.0,
                                                    ),
                                                    base_context_reduce_patterns=(
                                                        base_context_reduce_patterns
                                                    ),
                                                    fragile_regime_entry_size_mult=_clamp(
                                                        fragile_regime_entry_size_mult,
                                                        0.0,
                                                        1.0,
                                                    ),
                                                    fragile_regime_entry_regimes=fragile_regime_entry_regimes,
                                                    fragile_regime_inventory_trim_fraction=_clamp(
                                                        fragile_regime_inventory_trim_fraction,
                                                        0.0,
                                                        1.0,
                                                    ),
                                                    fragile_regime_inventory_trim_regimes=(
                                                        fragile_regime_inventory_trim_regimes
                                                    ),
                                                    event_risk_base_reduce_size_mult=_clamp(
                                                        event_risk_base_reduce_size_mult,
                                                        0.0,
                                                        1.0,
                                                    ),
                                                    event_risk_base_reduce_min_extension_atr=max(
                                                        0.0,
                                                        float(event_risk_base_reduce_min_extension_atr),
                                                    ),
                                                    event_risk_base_reduce_max_extension_atr=max(
                                                        0.0,
                                                        float(event_risk_base_reduce_max_extension_atr),
                                                    ),
                                                    event_risk_base_reduce_side=(
                                                        event_risk_base_reduce_side
                                                        if event_risk_base_reduce_side in {"both", "long", "short"}
                                                        else "both"
                                                    ),
                                                    event_risk_base_reduce_contexts=(
                                                        event_risk_base_reduce_contexts
                                                    ),
                                                    regime_router_enabled=bool(regime_router_enabled),
                                                    router_trend_reaction_size_mult=_clamp(
                                                        router_trend_reaction_size_mult,
                                                        0.0,
                                                        1.5,
                                                    ),
                                                    router_one_way_chase_size_mult=_clamp(
                                                        router_one_way_chase_size_mult,
                                                        0.0,
                                                        1.5,
                                                    ),
                                                    router_one_way_counter_size_mult=_clamp(
                                                        router_one_way_counter_size_mult,
                                                        0.0,
                                                        1.0,
                                                    ),
                                                    router_range_probe_size_mult=_clamp(
                                                        router_range_probe_size_mult,
                                                        0.0,
                                                        1.0,
                                                    ),
                                                    router_range_base_size_mult=_clamp(
                                                        router_range_base_size_mult,
                                                        0.0,
                                                        1.0,
                                                    ),
                                                    router_exhaustion_reversal_size_mult=_clamp(
                                                        router_exhaustion_reversal_size_mult,
                                                        0.0,
                                                        1.0,
                                                    ),
                                                    router_exhaustion_min_score_edge=max(
                                                        0,
                                                        int(router_exhaustion_min_score_edge),
                                                    ),
                                                    router_exhaustion_min_extension_atr=max(
                                                        0.0,
                                                        float(router_exhaustion_min_extension_atr),
                                                    ),
                                                    router_risk_off_size_mult=_clamp(
                                                        router_risk_off_size_mult,
                                                        0.0,
                                                        1.0,
                                                    ),
                                                    router_transition_trim_fraction=_clamp(
                                                        router_transition_trim_fraction,
                                                        0.0,
                                                        1.0,
                                                    ),
                                                    router_transition_trim_modes=router_transition_trim_modes,
                                                    router_transition_trim_against_only=bool(
                                                        router_transition_trim_against_only
                                                    ),
                                                    router_transition_trim_cooldown_bars=max(
                                                        0,
                                                        int(router_transition_trim_cooldown_bars),
                                                    ),
                                                    defensive_trim_cooldown_bars=max(0, int(defensive_trim_cooldown_bars)),
                                                    cooldown_after_loss_bars=12 if profile_name == "balanced" else 48,
                                                    max_failed_rescues_before_reduce_only=2,
                                                    max_battle_bars=max_battle_bars,
                                                    max_stuck_bars=96,
                                                    max_hold_bars=max_hold_bars,
                                                    min_liquidation_buffer_pct=0.018,
                                                    trend_core_units=1.0 if strict_scenario_entry else 2.0,
                                                    strict_scenario_entry=strict_scenario_entry,
                                                    switch_enabled=True,
                                                    )
                                                    )
    return configs


def _load_feature_sets(args: argparse.Namespace) -> tuple[FeatureSet, dict[str, FeatureSet], dict[str, list[int]], dict[str, Any]]:
    settings = get_settings()
    base_url = str(args.base_url or settings.binance_rest_base_url or "https://fapi.binance.com").rstrip("/")
    cache_dir = Path(args.cache_dir)
    load_days = max(int(args.load_days), int(args.days))
    max_cache_age_minutes = getattr(args, "max_cache_age_minutes", None)

    exec_bars = _load_bars(
        symbol=args.symbol,
        interval=args.exec_interval,
        days=load_days,
        cache_dir=cache_dir,
        base_url=base_url,
        sleep_seconds=float(args.sleep_seconds),
        max_cache_age_minutes=max_cache_age_minutes,
    )
    exec_bars = _slice_last_days(exec_bars, int(args.days))
    features = FeatureSet(exec_bars)

    scenario_features: dict[str, FeatureSet] = {}
    scenario_maps: dict[str, list[int]] = {}
    for interval in _csv(args.scenario_intervals):
        bars = _load_bars(
            symbol=args.symbol,
            interval=interval,
            days=load_days,
            cache_dir=cache_dir,
            base_url=base_url,
            sleep_seconds=float(args.sleep_seconds),
            max_cache_age_minutes=max_cache_age_minutes,
        )
        if exec_bars:
            start_ms = exec_bars[0].open_ms - _INTERVAL_MS[interval] * 300
            end_ms = exec_bars[-1].open_ms
            bars = [bar for bar in bars if start_ms <= bar.open_ms <= end_ms]
        scenario_features[interval] = FeatureSet(bars)
        scenario_maps[interval] = _map_closed_indices(exec_bars, bars, interval)

    meta = {
        "base_url": base_url,
        "exec_rows": len(exec_bars),
        "exec_start": exec_bars[0].ts.isoformat() if exec_bars else None,
        "exec_end": exec_bars[-1].ts.isoformat() if exec_bars else None,
        "scenario_rows": {interval: len(fs.bars) for interval, fs in scenario_features.items()},
        "max_cache_age_minutes": max_cache_age_minutes,
    }
    return features, scenario_features, scenario_maps, meta


def _write_markdown_summary(report: dict[str, Any], path: Path) -> None:
    top = report.get("top_results", [])
    top_return = report.get("top_results_by_return", [])
    best = top[0] if top else {}
    best_return = top_return[0] if top_return else best
    best_diag = dict(best.get("event_diagnostics") or {}) if best else {}
    best_return_diag = dict(best_return.get("event_diagnostics") or {}) if best_return else {}
    lines = [
        "# Market-State Rotation V6 Backtest Summary",
        "",
        f"- Created at: `{report.get('created_at')}`",
        f"- Symbol: `{report.get('args', {}).get('symbol')}`",
        f"- Execution interval: `{report.get('args', {}).get('exec_interval')}`",
        f"- Days: `{report.get('args', {}).get('days')}`",
        f"- Tested configs: `{report.get('tested_configs')}`",
        f"- Data: `{report.get('data', {}).get('exec_start')}` to `{report.get('data', {}).get('exec_end')}`",
        "",
        "## Best By Method Score",
        "",
    ]
    if best:
        lines.extend(
            [
                f"- Model: `{best.get('model_id')}`",
                f"- Total return: `{best.get('total_return_pct')}%`",
                f"- Gross return before costs: `{best.get('gross_return_pct_before_costs')}%`",
                f"- Estimated cost drag: `{best.get('estimated_cost_drag_pct')}%`",
                f"- Modeled trade cost fraction sum: `{best.get('modeled_trade_cost_fraction_sum')}`",
                f"- Modeled carry cost fraction sum: `{best.get('modeled_carry_cost_fraction_sum')}`",
                f"- CAGR: `{best.get('cagr_pct')}%`",
                f"- Max drawdown: `{best.get('max_drawdown_pct')}%`",
                f"- Max account exposure: `{best.get('max_abs_account_exposure')}x`",
                f"- Trade-like events: `{best.get('trade_like_events')}`",
                f"- Battle adds: `{best.get('battle_adds')}`",
                f"- Battle success rate: `{best.get('battle_success_rate')}`",
                f"- Order distribution health: `{best_diag.get('health')}`",
                f"- Distribution flags: `{', '.join(best_diag.get('flags') or []) or 'none'}`",
                f"- Diagnostic thresholds: `{json.dumps(best_diag.get('diagnostic_thresholds', {}), ensure_ascii=False)}`",
                f"- Event counts: `{json.dumps(best.get('event_counts', {}), ensure_ascii=False)}`",
                "",
                "## Best Result Regime Performance",
                "",
                f"- Regime performance: `{json.dumps(best.get('regime_performance', {}), ensure_ascii=False)}`",
                f"- Router mode performance: `{json.dumps(best.get('router_mode_performance', {}), ensure_ascii=False)}`",
                "",
            ]
        )
        lines.extend(
            [
                "## Best Result Order Distribution",
                "",
                f"- Adds by side: `{json.dumps(best_diag.get('add_by_side', {}), ensure_ascii=False)}`",
                f"- Add side share: `{json.dumps(best_diag.get('add_side_share', {}), ensure_ascii=False)}`",
                f"- Adds by role: `{json.dumps(best_diag.get('add_by_role', {}), ensure_ascii=False)}`",
                f"- Adds by zone category: `{json.dumps(best_diag.get('add_by_zone_category', {}), ensure_ascii=False)}`",
                f"- Realized PnL by entry zone category: `{json.dumps(best_diag.get('realized_pnl_usd_units_by_entry_zone_category', {}), ensure_ascii=False)}`",
                f"- Realized PnL per add by entry zone category: `{json.dumps(best_diag.get('realized_pnl_usd_units_per_add_by_entry_zone_category', {}), ensure_ascii=False)}`",
                f"- Realized PnL per add by entry context: `{json.dumps(best_diag.get('realized_pnl_usd_units_per_add_by_entry_context', {}), ensure_ascii=False)}`",
                f"- Monthly adds: `{json.dumps(best_diag.get('monthly_adds', {}), ensure_ascii=False)}`",
                f"- Active order months: `{best_diag.get('active_order_months')}/{best_diag.get('total_months')}`",
                f"- Max month add share: `{best_diag.get('max_month_add_share')}`",
                f"- KST hour max share: `{best_diag.get('max_kst_hour_add_share')}`",
                f"- Exposure side share: `{json.dumps(best_diag.get('exposure_side_share', {}), ensure_ascii=False)}`",
                f"- Ratios: `{json.dumps(best_diag.get('ratios', {}), ensure_ascii=False)}`",
                "",
                "## Best Result Exit Hotspots",
                "",
                f"- PnL by exit reason/side: `{json.dumps(best_diag.get('realized_pnl_usd_units_by_remove_reason_side', {}), ensure_ascii=False)}`",
                f"- Worst entry contexts by total PnL: `{json.dumps(best_diag.get('worst_realized_pnl_usd_units_by_entry_context', {}), ensure_ascii=False)}`",
                f"- Best entry contexts by total PnL: `{json.dumps(best_diag.get('best_realized_pnl_usd_units_by_entry_context', {}), ensure_ascii=False)}`",
                f"- Worst exit reason/context averages: `{json.dumps(best_diag.get('worst_avg_pnl_usd_units_by_remove_reason_context', {}), ensure_ascii=False)}`",
                f"- One-way forced trim hotspots: `{json.dumps(best_diag.get('one_way_forced_trim_hotspots', {}), ensure_ascii=False)}`",
                f"- Hard time exit hotspots: `{json.dumps(best_diag.get('hard_time_exit_hotspots', {}), ensure_ascii=False)}`",
                f"- Reaction trim hotspots: `{json.dumps(best_diag.get('reaction_trim_hotspots', {}), ensure_ascii=False)}`",
                "",
            ]
        )
    if best_return:
        lines.extend(
            [
                "## Best By Raw Return",
                "",
                f"- Model: `{best_return.get('model_id')}`",
                f"- Total return: `{best_return.get('total_return_pct')}%`",
                f"- Gross return before costs: `{best_return.get('gross_return_pct_before_costs')}%`",
                f"- Estimated cost drag: `{best_return.get('estimated_cost_drag_pct')}%`",
                f"- Modeled trade cost fraction sum: `{best_return.get('modeled_trade_cost_fraction_sum')}`",
                f"- Modeled carry cost fraction sum: `{best_return.get('modeled_carry_cost_fraction_sum')}`",
                f"- CAGR: `{best_return.get('cagr_pct')}%`",
                f"- Max drawdown: `{best_return.get('max_drawdown_pct')}%`",
                f"- Max account exposure: `{best_return.get('max_abs_account_exposure')}x`",
                f"- Trade-like events: `{best_return.get('trade_like_events')}`",
                f"- Battle adds: `{best_return.get('battle_adds')}`",
                f"- Order distribution health: `{best_return_diag.get('health')}`",
                f"- Distribution flags: `{', '.join(best_return_diag.get('flags') or []) or 'none'}`",
                f"- Diagnostic thresholds: `{json.dumps(best_return_diag.get('diagnostic_thresholds', {}), ensure_ascii=False)}`",
                f"- Adds by role: `{json.dumps(best_return_diag.get('add_by_role', {}), ensure_ascii=False)}`",
                f"- Realized PnL by role: `{json.dumps(best_return_diag.get('realized_pnl_usd_units_by_role', {}), ensure_ascii=False)}`",
                f"- Realized PnL by exit reason: `{json.dumps(best_return_diag.get('realized_pnl_usd_units_by_remove_reason', {}), ensure_ascii=False)}`",
                f"- Realized PnL per add by entry zone category: `{json.dumps(best_return_diag.get('realized_pnl_usd_units_per_add_by_entry_zone_category', {}), ensure_ascii=False)}`",
                f"- Realized PnL per add by entry context: `{json.dumps(best_return_diag.get('realized_pnl_usd_units_per_add_by_entry_context', {}), ensure_ascii=False)}`",
                f"- Ratios: `{json.dumps(best_return_diag.get('ratios', {}), ensure_ascii=False)}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Interpretation",
            "",
            "This run treats the Telegram/PDF/video material as strategy samples only.",
            "No message price level is used as an entry signal. All entries, trims, battle adds, and switches are generated from market bars.",
            "The v6-specific mechanics add micro-choice gates: reason-stack confluence, zone lifecycle retirement, primary battle zones, reaction-first inventory trims, asymmetric countertrend sizing, and stricter switch permission.",
            "",
            "## Top 10 By Method Score",
            "",
            "| rank | return % | gross % | cost drag % | CAGR % | MDD % | exposure | events | battle adds | dist | model |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for idx, result in enumerate(top[:10], start=1):
        diagnostics = dict(result.get("event_diagnostics") or {})
        lines.append(
            f"| {idx} | {result.get('total_return_pct')} | {result.get('gross_return_pct_before_costs')} | "
            f"{result.get('estimated_cost_drag_pct')} | {result.get('cagr_pct')} | "
            f"{result.get('max_drawdown_pct')} | {result.get('max_abs_account_exposure')} | "
            f"{result.get('trade_like_events')} | {result.get('battle_adds')} | "
            f"{diagnostics.get('health', 'n/a')} | `{result.get('model_id')}` |"
        )
    lines.extend(
        [
            "",
            "## Top 10 By Raw Return",
            "",
            "| rank | return % | gross % | cost drag % | CAGR % | MDD % | exposure | events | battle adds | dist | model |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for idx, result in enumerate(top_return[:10], start=1):
        diagnostics = dict(result.get("event_diagnostics") or {})
        lines.append(
            f"| {idx} | {result.get('total_return_pct')} | {result.get('gross_return_pct_before_costs')} | "
            f"{result.get('estimated_cost_drag_pct')} | {result.get('cagr_pct')} | "
            f"{result.get('max_drawdown_pct')} | {result.get('max_abs_account_exposure')} | "
            f"{result.get('trade_like_events')} | {result.get('battle_adds')} | "
            f"{diagnostics.get('health', 'n/a')} | `{result.get('model_id')}` |"
        )
    lines.append("")
    atomic_write_text(path, "\n".join(lines))


def _stdout_result_summary(result: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(result.get("event_diagnostics") or {})
    ratios = dict(diagnostics.get("ratios") or {})
    return {
        "model_id": result.get("model_id"),
        "total_return_pct": result.get("total_return_pct"),
        "gross_return_pct_before_costs": result.get("gross_return_pct_before_costs"),
        "estimated_cost_drag_pct": result.get("estimated_cost_drag_pct"),
        "modeled_trade_cost_fraction_sum": result.get("modeled_trade_cost_fraction_sum"),
        "modeled_carry_cost_fraction_sum": result.get("modeled_carry_cost_fraction_sum"),
        "cagr_pct": result.get("cagr_pct"),
        "max_drawdown_pct": result.get("max_drawdown_pct"),
        "max_abs_account_exposure": result.get("max_abs_account_exposure"),
        "trade_like_events": result.get("trade_like_events"),
        "battle_adds": result.get("battle_adds"),
        "router_mode_performance": result.get("router_mode_performance") or {},
        "distribution_health": diagnostics.get("health"),
        "distribution_flags": diagnostics.get("flags") or [],
        "add_by_side": diagnostics.get("add_by_side") or {},
        "ratios": {
            "one_way_forced_trim_per_add": ratios.get("one_way_forced_trim_per_add"),
            "turnover_events_per_add": ratios.get("turnover_events_per_add"),
            "reaction_trim_per_remove": ratios.get("reaction_trim_per_remove"),
            "battle_add_per_add": ratios.get("battle_add_per_add"),
        },
    }


def _carry_rate_per_bar(*, exec_interval: str, funding_bps_per_8h: float, borrow_bps_per_day: float) -> float:
    interval_ms = _INTERVAL_MS[exec_interval]
    bars_per_8h = max(8.0 * 60.0 * 60.0 * 1000.0 / interval_ms, 1.0)
    bars_per_day = max(24.0 * 60.0 * 60.0 * 1000.0 / interval_ms, 1.0)
    funding = max(float(funding_bps_per_8h), 0.0) / 10_000.0 / bars_per_8h
    borrow = max(float(borrow_bps_per_day), 0.0) / 10_000.0 / bars_per_day
    return funding + borrow


def main() -> None:
    args = _parse_args()
    if args.exec_interval not in _INTERVAL_MS:
        raise SystemExit(f"unsupported exec interval: {args.exec_interval}")
    for interval in _csv(args.scenario_intervals):
        if interval not in _INTERVAL_MS:
            raise SystemExit(f"unsupported scenario interval: {interval}")

    features, scenario_features, scenario_maps, data_meta = _load_feature_sets(args)
    if len(features.bars) < int(args.min_periods):
        raise SystemExit(f"not enough execution bars: {len(features.bars)} < {args.min_periods}")

    max_account_exposures = _parse_float_csv(args.max_account_exposures, [1.0, 2.0, 3.0, 5.0])
    max_possible_units_options = [
        value for value in _parse_float_csv(args.max_possible_units, [10.0]) if value > 0.0
    ] or [10.0]
    battle_units_options = _parse_float_csv(args.battle_units, [3.0, 5.0])
    probe_units_options = _parse_nonnegative_float_csv(args.probe_units, [0.0, 0.1, 0.25])
    blocked_kst_entry_hours = _parse_kst_hours(args.blocked_kst_entry_hours, (4, 9, 13, 16))
    event_risk_base_reduce_contexts = _parse_event_risk_contexts(args.event_risk_base_reduce_contexts)
    base_context_reduce_patterns = _parse_base_context_reduce_patterns(args.base_context_reduce_patterns)
    configs = build_configs(
        exec_interval=args.exec_interval,
        exchange_leverage=float(args.exchange_leverage),
        maintenance_margin_pct=float(args.maintenance_margin_pct),
        max_account_exposures=max_account_exposures,
        max_possible_units_options=max_possible_units_options,
        battle_units_options=battle_units_options,
        probe_units_options=probe_units_options,
        volume_layer_enabled=bool(args.volume_layer),
        one_way_trim_min_adverse_reaction=max(0.0, float(args.one_way_trim_min_adverse_reaction)),
        one_way_trim_cooldown_bars=max(0, int(args.one_way_trim_cooldown_bars)),
        one_way_trim_size_mult=_clamp(args.one_way_trim_size_mult, 0.05, 1.0),
        hard_time_exit_fraction=_clamp(args.hard_time_exit_fraction, 0.05, 1.0),
        hard_time_exit_cooldown_bars=max(0, int(args.hard_time_exit_cooldown_bars)),
        reaction_trim_trend_hold_trigger_mult=_clamp(
            args.reaction_trim_trend_hold_trigger_mult,
            1.0,
            5.0,
        ),
        hard_time_exit_trend_defer_bars=max(0, int(args.hard_time_exit_trend_defer_bars)),
        hard_time_exit_trend_defer_min_favorable_reaction=max(
            0.0,
            float(args.hard_time_exit_trend_defer_min_favorable_reaction),
        ),
        trend_hold_min_trend_strength=max(0.0, float(args.trend_hold_min_trend_strength)),
        trend_hold_min_one_way_score=max(0.0, float(args.trend_hold_min_one_way_score)),
        one_way_trim_retire_same_zone=bool(args.one_way_trim_retire_same_zone),
        one_way_trim_same_side_cooldown_bars=max(0, int(args.one_way_trim_same_side_cooldown_bars)),
        one_way_trim_cluster_guard_count=max(0, int(args.one_way_trim_cluster_guard_count)),
        one_way_trim_cluster_window_bars=max(1, int(args.one_way_trim_cluster_window_bars)),
        one_way_trim_cluster_cooldown_bars=max(0, int(args.one_way_trim_cluster_cooldown_bars)),
        one_way_trim_context_guard_count=max(0, int(args.one_way_trim_context_guard_count)),
        one_way_trim_context_window_bars=max(1, int(args.one_way_trim_context_window_bars)),
        one_way_trim_context_cooldown_bars=max(0, int(args.one_way_trim_context_cooldown_bars)),
        one_way_trim_context_full_exit=bool(args.one_way_trim_context_full_exit),
        one_way_loss_fuse_min_adverse_reaction=max(
            0.0,
            float(args.one_way_loss_fuse_min_adverse_reaction),
        ),
        one_way_loss_fuse_cooldown_bars=max(0, int(args.one_way_loss_fuse_cooldown_bars)),
        one_way_loss_fuse_size_mult=_clamp(args.one_way_loss_fuse_size_mult, 0.0, 1.0),
        one_way_trim_full_exit_min_one_way_score=max(0.0, float(args.one_way_trim_full_exit_min_one_way_score)),
        one_way_trim_full_exit_min_score_diff=max(0, int(args.one_way_trim_full_exit_min_score_diff)),
        trend_idle_probe_units=max(0.0, float(args.trend_idle_probe_units)),
        trend_idle_min_score=int(args.trend_idle_min_score),
        trend_idle_min_reason_stack=max(0, int(args.trend_idle_min_reason_stack)),
        trend_idle_cooldown_bars=max(0, int(args.trend_idle_cooldown_bars)),
        trend_idle_max_extension_atr=max(0.1, float(args.trend_idle_max_extension_atr)),
        near_miss_probe_units=max(0.0, float(args.near_miss_probe_units)),
        near_miss_probe_min_score=int(args.near_miss_probe_min_score),
        near_miss_probe_min_score_edge=max(0, int(args.near_miss_probe_min_score_edge)),
        near_miss_probe_min_reason_stack=max(0, int(args.near_miss_probe_min_reason_stack)),
        near_miss_probe_cooldown_bars=max(0, int(args.near_miss_probe_cooldown_bars)),
        near_miss_probe_max_extension_atr=max(0.1, float(args.near_miss_probe_max_extension_atr)),
        near_miss_probe_failure_guard_count=max(0, int(args.near_miss_probe_failure_guard_count)),
        near_miss_probe_failure_guard_window_bars=max(
            1,
            int(args.near_miss_probe_failure_guard_window_bars),
        ),
        near_miss_probe_failure_cooldown_bars=max(0, int(args.near_miss_probe_failure_cooldown_bars)),
        equity_circuit_breaker_drawdown_pct=max(0.0, float(args.equity_circuit_breaker_drawdown_pct)),
        equity_circuit_breaker_pause_bars=max(0, int(args.equity_circuit_breaker_pause_bars)),
        equity_circuit_rearm_drawdown_pct=max(0.0, float(args.equity_circuit_rearm_drawdown_pct)),
        equity_soft_circuit_drawdown_pct=max(0.0, float(args.equity_soft_circuit_drawdown_pct)),
        equity_soft_circuit_cooldown_bars=max(0, int(args.equity_soft_circuit_cooldown_bars)),
        equity_soft_circuit_size_mult=_clamp(args.equity_soft_circuit_size_mult, 0.0, 1.0),
        equity_soft_circuit_force_flat=bool(args.equity_soft_circuit_force_flat),
        equity_soft_circuit_inventory_trim_fraction=_clamp(
            args.equity_soft_circuit_inventory_trim_fraction,
            0.0,
            1.0,
        ),
        equity_soft_circuit_prearm_bars=max(0, int(args.equity_soft_circuit_prearm_bars)),
        equity_soft_circuit_min_bars_after_add=max(
            0,
            int(args.equity_soft_circuit_min_bars_after_add),
        ),
        equity_soft_circuit_recovery_probe_units=max(
            0.0,
            float(args.equity_soft_circuit_recovery_probe_units),
        ),
        equity_soft_circuit_recovery_min_one_way_score=max(
            0.0,
            float(args.equity_soft_circuit_recovery_min_one_way_score),
        ),
        equity_soft_circuit_recovery_min_score_diff=max(
            0,
            int(args.equity_soft_circuit_recovery_min_score_diff),
        ),
        equity_soft_circuit_recovery_max_extension_atr=max(
            0.1,
            float(args.equity_soft_circuit_recovery_max_extension_atr),
        ),
        equity_soft_circuit_recovery_failure_guard_count=max(
            0,
            int(args.equity_soft_circuit_recovery_failure_guard_count),
        ),
        equity_soft_circuit_recovery_failure_guard_window_bars=max(
            1,
            int(args.equity_soft_circuit_recovery_failure_guard_window_bars),
        ),
        equity_soft_circuit_recovery_failure_cooldown_bars=max(
            0,
            int(args.equity_soft_circuit_recovery_failure_cooldown_bars),
        ),
        one_way_reversal_switch_units=max(0.0, float(args.one_way_reversal_switch_units)),
        one_way_reversal_min_score_edge=int(args.one_way_reversal_min_score_edge),
        one_way_reversal_cooldown_bars=max(0, int(args.one_way_reversal_cooldown_bars)),
        one_way_reversal_allow_scenario_override=bool(args.one_way_reversal_allow_scenario_override),
        one_way_reversal_allow_score_override=bool(args.one_way_reversal_allow_score_override),
        one_way_impulse_probe_units=max(0.0, float(args.one_way_impulse_probe_units)),
        one_way_impulse_min_one_way_score=max(0.0, float(args.one_way_impulse_min_one_way_score)),
        one_way_impulse_min_score_diff=max(0, int(args.one_way_impulse_min_score_diff)),
        one_way_impulse_cooldown_bars=max(0, int(args.one_way_impulse_cooldown_bars)),
        one_way_impulse_max_extension_atr=max(0.1, float(args.one_way_impulse_max_extension_atr)),
        scenario_flip_units=max(0.0, float(args.scenario_flip_units)),
        scenario_flip_min_score_edge=int(args.scenario_flip_min_score_edge),
        scenario_flip_min_adverse_reaction=max(0.0, float(args.scenario_flip_min_adverse_reaction)),
        scenario_flip_min_one_way_score=max(0.0, float(args.scenario_flip_min_one_way_score)),
        scenario_flip_cooldown_bars=max(0, int(args.scenario_flip_cooldown_bars)),
        scenario_flip_max_extension_atr=max(0.1, float(args.scenario_flip_max_extension_atr)),
        winner_pyramid_units=max(0.0, float(args.winner_pyramid_units)),
        winner_pyramid_min_profit_reaction=max(0.0, float(args.winner_pyramid_min_profit_reaction)),
        winner_pyramid_min_score=int(args.winner_pyramid_min_score),
        winner_pyramid_min_reason_stack=max(0, int(args.winner_pyramid_min_reason_stack)),
        winner_pyramid_cooldown_bars=max(0, int(args.winner_pyramid_cooldown_bars)),
        winner_pyramid_max_units=max(0.0, float(args.winner_pyramid_max_units)),
        winner_pyramid_min_extension_atr=max(0.0, float(args.winner_pyramid_min_extension_atr)),
        winner_pyramid_max_extension_atr=max(0.1, float(args.winner_pyramid_max_extension_atr)),
        winner_pyramid_block_risk_off=bool(args.winner_pyramid_block_risk_off),
        winner_pyramid_block_one_way_chase=bool(args.winner_pyramid_block_one_way_chase),
        base_entry_max_extension_atr=max(0.0, float(args.base_entry_max_extension_atr)),
        base_entry_max_extension_side=(
            args.base_entry_max_extension_side
            if args.base_entry_max_extension_side in {"both", "long", "short"}
            else "both"
        ),
        base_entry_reduce_extension_atr=max(0.0, float(args.base_entry_reduce_extension_atr)),
        base_entry_reduce_size_mult=_clamp(args.base_entry_reduce_size_mult, 0.0, 1.0),
        base_entry_reduce_promote_reaction=max(0.0, float(args.base_entry_reduce_promote_reaction)),
        base_entry_reduce_max_trend_strength=max(0.0, float(args.base_entry_reduce_max_trend_strength)),
        base_entry_reduce_min_trend_strength=max(0.0, float(args.base_entry_reduce_min_trend_strength)),
        base_entry_reduce_side=(
            args.base_entry_reduce_side if args.base_entry_reduce_side in {"both", "long", "short"} else "both"
        ),
        base_context_reduce_size_mult=_clamp(args.base_context_reduce_size_mult, 0.0, 1.0),
        base_context_reduce_patterns=base_context_reduce_patterns,
        fragile_regime_entry_size_mult=_clamp(args.fragile_regime_entry_size_mult, 0.0, 1.0),
        fragile_regime_entry_regimes=_parse_regimes(args.fragile_regime_entry_regimes),
        fragile_regime_inventory_trim_fraction=_clamp(
            args.fragile_regime_inventory_trim_fraction,
            0.0,
            1.0,
        ),
        fragile_regime_inventory_trim_regimes=_parse_regimes(args.fragile_regime_inventory_trim_regimes),
        event_risk_base_reduce_size_mult=_clamp(args.event_risk_base_reduce_size_mult, 0.0, 1.0),
        event_risk_base_reduce_min_extension_atr=max(0.0, float(args.event_risk_base_reduce_min_extension_atr)),
        event_risk_base_reduce_max_extension_atr=max(0.0, float(args.event_risk_base_reduce_max_extension_atr)),
        event_risk_base_reduce_side=(
            args.event_risk_base_reduce_side
            if args.event_risk_base_reduce_side in {"both", "long", "short"}
            else "both"
        ),
        event_risk_base_reduce_contexts=event_risk_base_reduce_contexts,
        regime_router_enabled=bool(args.regime_router_enabled),
        router_trend_reaction_size_mult=_clamp(args.router_trend_reaction_size_mult, 0.0, 1.5),
        router_one_way_chase_size_mult=_clamp(args.router_one_way_chase_size_mult, 0.0, 1.5),
        router_one_way_counter_size_mult=_clamp(args.router_one_way_counter_size_mult, 0.0, 1.0),
        router_range_probe_size_mult=_clamp(args.router_range_probe_size_mult, 0.0, 1.0),
        router_range_base_size_mult=_clamp(args.router_range_base_size_mult, 0.0, 1.0),
        router_exhaustion_reversal_size_mult=_clamp(args.router_exhaustion_reversal_size_mult, 0.0, 1.0),
        router_exhaustion_min_score_edge=max(0, int(args.router_exhaustion_min_score_edge)),
        router_exhaustion_min_extension_atr=max(0.0, float(args.router_exhaustion_min_extension_atr)),
        router_risk_off_size_mult=_clamp(args.router_risk_off_size_mult, 0.0, 1.0),
        router_transition_trim_fraction=_clamp(args.router_transition_trim_fraction, 0.0, 1.0),
        router_transition_trim_modes=_parse_router_modes(args.router_transition_trim_modes),
        router_transition_trim_against_only=bool(args.router_transition_trim_against_only),
        router_transition_trim_cooldown_bars=max(0, int(args.router_transition_trim_cooldown_bars)),
        defensive_trim_cooldown_bars=max(0, int(args.defensive_trim_cooldown_bars)),
        reaction_trim_trigger=max(0.05, float(args.reaction_trim_trigger)),
        reaction_trim_size_mult=_clamp(args.reaction_trim_size_mult, 0.05, 1.0),
        reaction_avg_band=max(0.05, float(args.reaction_avg_band)),
        skip_weak_long_round_reclaim=bool(args.skip_weak_long_round_reclaim),
        blocked_kst_entry_hours=blocked_kst_entry_hours,
    )
    if int(args.model_offset) > 0:
        configs = configs[int(args.model_offset) :]
    if int(args.max_models) > 0:
        configs = configs[: int(args.max_models)]

    cost_rate = (max(float(args.fee_bps_per_side), 0.0) + max(float(args.slippage_bps_per_side), 0.0)) / 10_000.0
    carry_rate_per_bar = _carry_rate_per_bar(
        exec_interval=args.exec_interval,
        funding_bps_per_8h=float(args.funding_bps_per_8h),
        borrow_bps_per_day=float(args.borrow_bps_per_day),
    )
    results: list[dict[str, Any]] = []
    for idx, config in enumerate(configs, start=1):
        result = backtest_config(
            symbol=args.symbol,
            features=features,
            scenario_features=scenario_features,
            scenario_maps=scenario_maps,
            config=config,
            cost_rate=cost_rate,
            min_periods=int(args.min_periods),
            carry_rate_per_bar=carry_rate_per_bar,
        )
        if result is not None:
            results.append(result)
        if idx % 25 == 0:
            print(f"tested {idx}/{len(configs)} configs", flush=True)

    results.sort(
        key=lambda item: (
            item["score"],
            item["cagr_pct"],
            -item["max_drawdown_pct"],
            item["battle_success_rate"],
        ),
        reverse=True,
    )
    results_by_return = sorted(
        results,
        key=lambda item: (
            item["total_return_pct"],
            item["cagr_pct"],
            -item["max_drawdown_pct"],
            item["score"],
        ),
        reverse=True,
    )

    positive = sum(1 for item in results if item["total_return_pct"] > 0.0)
    monthly_double = sum(1 for item in results if item["monthly"]["months_doubled"] > 0)
    distribution_health_counts = Counter(
        str(dict(item.get("event_diagnostics") or {}).get("health") or "unknown")
        for item in results
    )
    distribution_flag_counts: Counter[str] = Counter()
    for item in results:
        for flag in dict(item.get("event_diagnostics") or {}).get("flags") or []:
            distribution_flag_counts[str(flag)] += 1
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "strategy_note": (
            "Market-state rotation v6 detailed proxy. Telegram/PDF/video material is used only to design "
            "the state machine. Trading decisions use market bars only."
        ),
        "risk_note": (
            "This is a research proxy with simplified liquidation, fee, slippage, optional carry/funding drag, and open-to-open execution. "
            "It is not an execution-ready live strategy."
        ),
        "args": vars(args),
        "data": data_meta,
        "tested_configs": len(configs),
        "result_count": len(results),
        "positive_result_count": positive,
        "monthly_double_candidate_count": monthly_double,
        "distribution_health_counts": _counter_payload(distribution_health_counts),
        "distribution_flag_counts": _counter_payload(distribution_flag_counts),
        "best_by_method_score": results[0] if results else None,
        "best_by_raw_return": results_by_return[0] if results_by_return else None,
        "top_results": results[:30],
        "top_results_by_return": results_by_return[:30],
        "all_results": results,
    }

    if args.write_report:
        report_dir = Path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        json_path = report_dir / f"market_state_rotation_v6_{args.symbol}_{args.exec_interval}_{args.days}d_{stamp}.json"
        latest_json = report_dir / f"market_state_rotation_v6_{args.symbol}_{args.exec_interval}_{args.days}d_latest.json"
        summary_md = report_dir / "summary_v6.md"
        text = json.dumps(report, ensure_ascii=False, indent=2)
        atomic_write_text(json_path, text)
        atomic_write_text(latest_json, text)
        _write_markdown_summary(report, summary_md)
        print(f"wrote {json_path}")
        print(f"wrote {latest_json}")
        print(f"wrote {summary_md}")

    print(
        json.dumps(
            {
                "data": data_meta,
                "tested": len(configs),
                "positive": positive,
                "monthly_double_candidates": monthly_double,
                "top_results": [_stdout_result_summary(result) for result in results[:5]],
                "top_results_by_return": [
                    _stdout_result_summary(result) for result in results_by_return[:5]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
