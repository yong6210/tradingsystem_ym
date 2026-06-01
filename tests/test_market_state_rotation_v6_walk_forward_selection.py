from dataclasses import dataclass
from types import SimpleNamespace
from datetime import UTC, datetime

from scripts.run_market_state_rotation_v6_walk_forward_validation import (
    _aggregate_folds,
    _aggregate_top_train_candidate_overlay_audit,
    _anchored_fold_start,
    _after_selection_confirmation_should_enforce,
    _after_selection_recent_oos_blocks,
    _after_selection_train_confirmation,
    _after_selection_confirmation_targets,
    _apply_battle_restore_overlay,
    _apply_distribution_balance_overlay,
    _apply_high_cost_balance_overlay,
    _apply_hold_compression_overlay,
    _apply_one_way_impulse_after_selection_overlay,
    _apply_repair_tune_overlay,
    _apply_reaction_tune_overlay,
    _apply_risk_off_micro_overlay,
    _apply_trim_cooldown_overlay,
    _equity_soft_sizer_after_selection_allowed,
    _exposure_rebalance_after_selection_allowed,
    _aggregate_top_train_candidate_audit,
    _fragile_regime_entry_after_selection_allowed,
    _fragile_regime_inventory_trim_after_selection_allowed,
    _near_miss_after_selection_allowed,
    _one_way_impulse_after_selection_allowed,
    _one_way_reversal_after_selection_weak_allowed,
    _report_provenance,
    _regime_dependency_stats,
    _risk_smoothing_after_selection_allowed,
    _selection_score,
    _train_state_after_selection_allowed,
    _write_markdown,
    _battle_restore_after_selection_allowed,
)


@dataclass(frozen=True)
class _HoldOnlyConfig:
    model_id: str
    max_hold_bars: int


@dataclass(frozen=True)
class _ReactionOnlyConfig:
    model_id: str
    reaction_trim_trigger: float
    repair_cut: float
    repair_stop: float


@dataclass(frozen=True)
class _TrimCooldownOnlyConfig:
    model_id: str
    one_way_trim_cooldown_bars: int
    base_entry_reduce_extension_atr: float
    base_entry_reduce_size_mult: float
    base_entry_reduce_promote_reaction: float


@dataclass(frozen=True)
class _HighCostBalanceOnlyConfig:
    model_id: str
    max_possible_units: float
    one_way_trim_cooldown_bars: int
    base_entry_reduce_extension_atr: float
    base_entry_reduce_size_mult: float
    base_entry_reduce_promote_reaction: float
    near_miss_probe_units: float
    near_miss_probe_min_score: int
    near_miss_probe_min_score_edge: int
    near_miss_probe_min_reason_stack: int
    near_miss_probe_cooldown_bars: int
    near_miss_probe_max_extension_atr: float
    near_miss_probe_failure_guard_count: int
    near_miss_probe_failure_guard_window_bars: int
    near_miss_probe_failure_cooldown_bars: int


@dataclass(frozen=True)
class _DistributionBalanceOnlyConfig:
    model_id: str
    max_possible_units: float
    near_miss_probe_units: float
    near_miss_probe_min_score: int
    near_miss_probe_min_score_edge: int
    near_miss_probe_min_reason_stack: int
    near_miss_probe_cooldown_bars: int
    near_miss_probe_max_extension_atr: float
    near_miss_probe_failure_guard_count: int
    near_miss_probe_failure_guard_window_bars: int
    near_miss_probe_failure_cooldown_bars: int


@dataclass(frozen=True)
class _RiskOffMicroOnlyConfig:
    model_id: str
    max_possible_units: float
    base_max_units: float
    battle_units: float
    trend_core_units: float
    reaction_trim_trigger: float


@dataclass(frozen=True)
class _BattleRestoreOnlyConfig:
    model_id: str
    max_possible_units: float
    battle_units: float
    battle_score: int
    battle_trigger_usd: float
    battle_trigger_atr: float
    max_repair_eff_for_add: float
    min_capacity_ratio: float


@dataclass(frozen=True)
class _ImpulseOnlyConfig:
    model_id: str
    max_possible_units: float
    one_way_impulse_probe_units: float
    one_way_impulse_min_one_way_score: float
    one_way_impulse_min_score_diff: int
    one_way_impulse_cooldown_bars: int
    one_way_impulse_max_extension_atr: float


def test_structural_flag_penalty_allows_zero_min_train_return() -> None:
    result = {
        "score": 1.0,
        "total_return_pct": 12.0,
        "max_drawdown_pct": 10.0,
        "estimated_cost_drag_pct": 0.0,
        "event_diagnostics": {
            "flags": ["one_way_forced_trim_overuse", "high_turnover_per_add"],
            "ratios": {},
        },
    }

    score = _selection_score(
        result,
        flag_penalty=0.0,
        structural_flag_min_train_return_pct=0.0,
        structural_flag_penalty=0.05,
    )

    assert score == 0.9


def test_anchored_fold_start_snaps_to_next_configured_utc_time() -> None:
    first_ts = datetime(2021, 6, 1, 19, 5, tzinfo=UTC)

    anchored = _anchored_fold_start(first_ts, 7, 0)
    unchanged = _anchored_fold_start(first_ts, None, 0)

    assert anchored == datetime(2021, 6, 2, 7, 0, tzinfo=UTC)
    assert unchanged == first_ts


def test_report_provenance_hashes_reproducibility_inputs(tmp_path) -> None:
    source_path = tmp_path / "source.json"
    source_report = {"created_at": "2026-05-31T00:00:00+00:00", "args": {"alpha": 1}}
    source_path.write_text('{"created_at":"2026-05-31T00:00:00+00:00","args":{"alpha":1}}')

    provenance = _report_provenance(
        source_path=source_path,
        source_report=source_report,
        configs=[],
        config_overrides={"beta": 2},
        folds=[
            {
                "fold": 1,
                "selected_model_id": "model-a",
                "test_result": {"total_return_pct": 3.5},
            }
        ],
    )

    assert provenance["source_report_exists"] is True
    assert provenance["source_report_created_at"] == "2026-05-31T00:00:00+00:00"
    assert len(provenance["source_report_sha256"]) == 64
    assert len(provenance["config_overrides_hash"]) == 64
    assert len(provenance["candidate_config_hash"]) == 64
    assert len(provenance["selected_result_hash"]) == 64


def test_high_train_flag_penalty_only_applies_above_return_threshold() -> None:
    result = {
        "score": 1.0,
        "total_return_pct": 125.0,
        "max_drawdown_pct": 10.0,
        "estimated_cost_drag_pct": 0.0,
        "event_diagnostics": {
            "flags": ["side_imbalance", "probe_overuse"],
            "ratios": {},
        },
    }

    penalized = _selection_score(
        result,
        flag_penalty=0.0,
        high_train_flag_min_return_pct=100.0,
        high_train_flag_penalty=0.15,
    )
    unpenalized = _selection_score(
        {**result, "total_return_pct": 95.0},
        flag_penalty=0.0,
        high_train_flag_min_return_pct=100.0,
        high_train_flag_penalty=0.15,
    )

    assert penalized == 0.7
    assert unpenalized == 1.0


def test_low_train_max_unit_penalty_only_applies_inside_return_band() -> None:
    result = {
        "score": 1.0,
        "total_return_pct": 8.0,
        "max_drawdown_pct": 10.0,
        "estimated_cost_drag_pct": 0.0,
        "config": {"max_possible_units": 1.5},
        "event_diagnostics": {"flags": [], "ratios": {}},
    }

    penalized = _selection_score(
        result,
        flag_penalty=0.0,
        low_train_max_unit_min_return_pct=0.0,
        low_train_max_unit_max_return_pct=15.0,
        low_train_max_unit_threshold=1.0,
        low_train_max_unit_penalty=0.2,
    )
    unpenalized = _selection_score(
        {**result, "total_return_pct": 20.0},
        flag_penalty=0.0,
        low_train_max_unit_min_return_pct=0.0,
        low_train_max_unit_max_return_pct=15.0,
        low_train_max_unit_threshold=1.0,
        low_train_max_unit_penalty=0.2,
    )

    assert penalized == 0.8
    assert unpenalized == 1.0


def test_selection_activity_penalty_uses_order_coverage_and_soft_blockers() -> None:
    result = {
        "score": 1.0,
        "total_return_pct": 18.0,
        "max_drawdown_pct": 10.0,
        "estimated_cost_drag_pct": 0.0,
        "event_counts": {
            "no_trade_MC12_low_confluence": 170,
            "no_trade_MC04_no_clear_first_touch": 90,
        },
        "event_diagnostics": {
            "flags": [],
            "add_events": 2,
            "diagnostic_thresholds": {"expected_add_events": 8},
            "ratios": {},
        },
        "regime_performance": {"uptrend": {"bars": 1000}},
    }

    penalized = _selection_score(
        result,
        flag_penalty=0.0,
        low_activity_coverage_threshold=0.5,
        low_activity_penalty=0.4,
        soft_no_trade_per_1k_threshold=200.0,
        soft_no_trade_per_1k_penalty=0.001,
    )
    unpenalized = _selection_score(
        {
            **result,
            "event_counts": {},
            "event_diagnostics": {
                "flags": [],
                "add_events": 5,
                "diagnostic_thresholds": {"expected_add_events": 8},
                "ratios": {},
            },
        },
        flag_penalty=0.0,
        low_activity_coverage_threshold=0.5,
        low_activity_penalty=0.4,
        soft_no_trade_per_1k_threshold=200.0,
        soft_no_trade_per_1k_penalty=0.001,
    )

    assert round(penalized, 6) == 0.84
    assert unpenalized == 1.0


def test_selection_role_concentration_penalty_is_opt_in() -> None:
    result = {
        "score": 1.0,
        "total_return_pct": 18.0,
        "max_drawdown_pct": 10.0,
        "estimated_cost_drag_pct": 0.0,
        "event_diagnostics": {
            "flags": [],
            "add_events": 13,
            "max_role_add_share": 0.9231,
            "ratios": {},
        },
    }

    penalized = _selection_score(
        result,
        flag_penalty=0.0,
        role_concentration_threshold=0.85,
        role_concentration_min_add_events=12,
        role_concentration_penalty=0.5,
    )
    unpenalized = _selection_score(
        result,
        flag_penalty=0.0,
        role_concentration_threshold=0.95,
        role_concentration_min_add_events=12,
        role_concentration_penalty=0.5,
    )

    assert round(penalized, 6) == 0.96345
    assert unpenalized == 1.0


def test_selection_base_dominance_penalty_targets_base_heavy_train_state() -> None:
    result = {
        "score": 1.0,
        "total_return_pct": 240.0,
        "max_drawdown_pct": 15.0,
        "estimated_cost_drag_pct": 75.0,
        "event_diagnostics": {
            "flags": [],
            "add_events": 48,
            "dominant_add_role": "base",
            "add_role_share": {"base": 0.8958, "probe": 0.1042},
            "ratios": {},
        },
    }

    penalized = _selection_score(
        result,
        flag_penalty=0.0,
        base_dominance_threshold=0.80,
        base_dominance_min_add_events=40,
        base_dominance_min_train_return_pct=200.0,
        base_dominance_max_train_cost_drag_pct=90.0,
        base_dominance_penalty=0.5,
    )
    non_base_dominant = _selection_score(
        {
            **result,
            "event_diagnostics": {
                **result["event_diagnostics"],
                "dominant_add_role": "probe",
            },
        },
        flag_penalty=0.0,
        base_dominance_threshold=0.80,
        base_dominance_min_add_events=40,
        base_dominance_min_train_return_pct=200.0,
        base_dominance_max_train_cost_drag_pct=90.0,
        base_dominance_penalty=0.5,
    )
    outside_train_band = _selection_score(
        {**result, "total_return_pct": 180.0},
        flag_penalty=0.0,
        base_dominance_threshold=0.80,
        base_dominance_min_add_events=40,
        base_dominance_min_train_return_pct=200.0,
        base_dominance_max_train_cost_drag_pct=90.0,
        base_dominance_penalty=0.5,
    )

    assert round(penalized, 6) == 0.9521
    assert non_base_dominant == 1.0
    assert outside_train_band == 1.0


def test_one_way_loss_fuse_bonus_only_applies_to_active_reducer() -> None:
    base_result = {
        "score": 1.0,
        "total_return_pct": 25.0,
        "max_drawdown_pct": 10.0,
        "estimated_cost_drag_pct": 0.0,
        "event_diagnostics": {"flags": [], "ratios": {}},
    }

    boosted = _selection_score(
        {
            **base_result,
            "config": {
                "one_way_loss_fuse_min_adverse_reaction": 0.03,
                "one_way_loss_fuse_cooldown_bars": 1440,
                "one_way_loss_fuse_size_mult": 0.0,
            },
        },
        one_way_loss_fuse_bonus=0.08,
    )
    inactive = _selection_score(
        {
            **base_result,
            "config": {
                "one_way_loss_fuse_min_adverse_reaction": 0.03,
                "one_way_loss_fuse_cooldown_bars": 1440,
                "one_way_loss_fuse_size_mult": 1.0,
            },
        },
        one_way_loss_fuse_bonus=0.08,
    )

    assert boosted == 1.08
    assert inactive == 1.0


def test_low_unit_reversal_bonus_requires_low_units_switch_and_train_band() -> None:
    result = {
        "score": 1.0,
        "total_return_pct": 42.0,
        "max_drawdown_pct": 31.0,
        "estimated_cost_drag_pct": 0.0,
        "config": {
            "max_possible_units": 1.0,
            "one_way_reversal_switch_units": 0.1,
        },
        "event_diagnostics": {
            "flags": [],
            "ratios": {"one_way_forced_trim_per_add": 0.39},
        },
    }

    boosted = _selection_score(
        result,
        low_unit_reversal_bonus=0.25,
        low_unit_reversal_max_units=1.0,
        low_unit_reversal_min_switch_units=0.1,
        low_unit_reversal_min_train_return_pct=35.0,
        low_unit_reversal_max_train_return_pct=50.0,
        low_unit_reversal_min_train_drawdown_pct=25.0,
        low_unit_reversal_max_train_drawdown_pct=35.0,
        low_unit_reversal_min_one_way_trim_per_add=0.35,
        low_unit_reversal_max_one_way_trim_per_add=0.45,
    )
    high_units = _selection_score(
        {**result, "config": {"max_possible_units": 1.5, "one_way_reversal_switch_units": 0.1}},
        low_unit_reversal_bonus=0.25,
        low_unit_reversal_max_units=1.0,
        low_unit_reversal_min_switch_units=0.1,
        low_unit_reversal_min_train_return_pct=35.0,
        low_unit_reversal_max_train_return_pct=50.0,
        low_unit_reversal_min_train_drawdown_pct=25.0,
        low_unit_reversal_max_train_drawdown_pct=35.0,
        low_unit_reversal_min_one_way_trim_per_add=0.35,
        low_unit_reversal_max_one_way_trim_per_add=0.45,
    )
    low_drawdown = _selection_score(
        {**result, "max_drawdown_pct": 20.0},
        low_unit_reversal_bonus=0.25,
        low_unit_reversal_max_units=1.0,
        low_unit_reversal_min_switch_units=0.1,
        low_unit_reversal_min_train_return_pct=35.0,
        low_unit_reversal_max_train_return_pct=50.0,
        low_unit_reversal_min_train_drawdown_pct=25.0,
        low_unit_reversal_max_train_drawdown_pct=35.0,
        low_unit_reversal_min_one_way_trim_per_add=0.35,
        low_unit_reversal_max_one_way_trim_per_add=0.45,
    )

    assert boosted == 1.25
    assert high_units == 1.0
    assert low_drawdown == 1.0


def test_drawdown_reversal_bonus_requires_low_unit_high_drawdown_cost_band() -> None:
    result = {
        "score": 1.0,
        "total_return_pct": 14.0,
        "max_drawdown_pct": 31.0,
        "estimated_cost_drag_pct": 21.0,
        "config": {
            "max_possible_units": 1.0,
            "one_way_reversal_switch_units": 0.1,
        },
        "event_diagnostics": {
            "flags": [],
            "ratios": {
                "one_way_forced_trim_per_add": 0.54,
                "turnover_events_per_add": 2.02,
            },
        },
    }

    boosted = _selection_score(
        result,
        drawdown_reversal_bonus=0.12,
        drawdown_reversal_max_units=1.0,
        drawdown_reversal_min_switch_units=0.1,
        drawdown_reversal_min_train_return_pct=10.0,
        drawdown_reversal_max_train_return_pct=16.0,
        drawdown_reversal_min_train_drawdown_pct=28.0,
        drawdown_reversal_max_train_drawdown_pct=32.0,
        drawdown_reversal_min_train_cost_drag_pct=20.0,
        drawdown_reversal_max_train_cost_drag_pct=23.0,
        drawdown_reversal_min_one_way_trim_per_add=0.5,
        drawdown_reversal_max_one_way_trim_per_add=0.56,
        drawdown_reversal_min_turnover_per_add=2.0,
        drawdown_reversal_max_turnover_per_add=2.05,
    )
    high_units = _selection_score(
        {**result, "config": {"max_possible_units": 1.5, "one_way_reversal_switch_units": 0.1}},
        drawdown_reversal_bonus=0.12,
        drawdown_reversal_max_units=1.0,
        drawdown_reversal_min_switch_units=0.1,
        drawdown_reversal_min_train_return_pct=10.0,
        drawdown_reversal_max_train_return_pct=16.0,
        drawdown_reversal_min_train_drawdown_pct=28.0,
        drawdown_reversal_max_train_drawdown_pct=32.0,
        drawdown_reversal_min_train_cost_drag_pct=20.0,
        drawdown_reversal_max_train_cost_drag_pct=23.0,
        drawdown_reversal_min_one_way_trim_per_add=0.5,
        drawdown_reversal_max_one_way_trim_per_add=0.56,
        drawdown_reversal_min_turnover_per_add=2.0,
        drawdown_reversal_max_turnover_per_add=2.05,
    )
    low_cost = _selection_score(
        {**result, "estimated_cost_drag_pct": 19.0},
        drawdown_reversal_bonus=0.12,
        drawdown_reversal_max_units=1.0,
        drawdown_reversal_min_switch_units=0.1,
        drawdown_reversal_min_train_return_pct=10.0,
        drawdown_reversal_max_train_return_pct=16.0,
        drawdown_reversal_min_train_drawdown_pct=28.0,
        drawdown_reversal_max_train_drawdown_pct=32.0,
        drawdown_reversal_min_train_cost_drag_pct=20.0,
        drawdown_reversal_max_train_cost_drag_pct=23.0,
        drawdown_reversal_min_one_way_trim_per_add=0.5,
        drawdown_reversal_max_one_way_trim_per_add=0.56,
        drawdown_reversal_min_turnover_per_add=2.0,
        drawdown_reversal_max_turnover_per_add=2.05,
    )
    high_turnover = _selection_score(
        {
            **result,
            "event_diagnostics": {
                "flags": [],
                "ratios": {
                    "one_way_forced_trim_per_add": 0.54,
                    "turnover_events_per_add": 2.1,
                },
            },
        },
        drawdown_reversal_bonus=0.12,
        drawdown_reversal_max_units=1.0,
        drawdown_reversal_min_switch_units=0.1,
        drawdown_reversal_min_train_return_pct=10.0,
        drawdown_reversal_max_train_return_pct=16.0,
        drawdown_reversal_min_train_drawdown_pct=28.0,
        drawdown_reversal_max_train_drawdown_pct=32.0,
        drawdown_reversal_min_train_cost_drag_pct=20.0,
        drawdown_reversal_max_train_cost_drag_pct=23.0,
        drawdown_reversal_min_one_way_trim_per_add=0.5,
        drawdown_reversal_max_one_way_trim_per_add=0.56,
        drawdown_reversal_min_turnover_per_add=2.0,
        drawdown_reversal_max_turnover_per_add=2.05,
    )

    assert boosted == 1.12
    assert high_units == 1.0
    assert low_cost == 1.0
    assert high_turnover == 1.0


def test_short_hold_structural_bonus_requires_hold_and_structural_band() -> None:
    result = {
        "score": 1.0,
        "total_return_pct": 62.0,
        "max_drawdown_pct": 14.0,
        "estimated_cost_drag_pct": 27.0,
        "config": {"max_hold_bars": 52, "max_possible_units": 1.5},
        "event_diagnostics": {
            "flags": [],
            "ratios": {
                "one_way_forced_trim_per_add": 0.44,
                "turnover_events_per_add": 2.56,
            },
        },
    }

    boosted = _selection_score(
        result,
        short_hold_structural_bonus=0.03,
        short_hold_max_bars=52,
        short_hold_min_train_return_pct=55.0,
        short_hold_max_train_return_pct=70.0,
        short_hold_min_train_drawdown_pct=13.0,
        short_hold_max_train_drawdown_pct=16.0,
        short_hold_min_max_units=1.5,
        short_hold_max_max_units=1.5,
        short_hold_min_one_way_trim_per_add=0.42,
        short_hold_max_one_way_trim_per_add=0.46,
        short_hold_min_turnover_per_add=2.5,
        short_hold_max_turnover_per_add=2.65,
    )
    long_hold = _selection_score(
        {**result, "config": {"max_hold_bars": 53, "max_possible_units": 1.5}},
        short_hold_structural_bonus=0.03,
        short_hold_max_bars=52,
        short_hold_min_train_return_pct=55.0,
        short_hold_max_train_return_pct=70.0,
        short_hold_min_train_drawdown_pct=13.0,
        short_hold_max_train_drawdown_pct=16.0,
        short_hold_min_max_units=1.5,
        short_hold_max_max_units=1.5,
        short_hold_min_one_way_trim_per_add=0.42,
        short_hold_max_one_way_trim_per_add=0.46,
        short_hold_min_turnover_per_add=2.5,
        short_hold_max_turnover_per_add=2.65,
    )
    low_turnover = _selection_score(
        {
            **result,
            "event_diagnostics": {
                "flags": [],
                "ratios": {
                    "one_way_forced_trim_per_add": 0.44,
                    "turnover_events_per_add": 2.4,
                },
            },
        },
        short_hold_structural_bonus=0.03,
        short_hold_max_bars=52,
        short_hold_min_train_return_pct=55.0,
        short_hold_max_train_return_pct=70.0,
        short_hold_min_train_drawdown_pct=13.0,
        short_hold_max_train_drawdown_pct=16.0,
        short_hold_min_max_units=1.5,
        short_hold_max_max_units=1.5,
        short_hold_min_one_way_trim_per_add=0.42,
        short_hold_max_one_way_trim_per_add=0.46,
        short_hold_min_turnover_per_add=2.5,
        short_hold_max_turnover_per_add=2.65,
    )

    assert boosted == 1.03
    assert long_hold == 1.0
    assert low_turnover == 1.0


def test_fast_defense_structural_penalty_requires_fast_cooldown_and_fragile_ratios() -> None:
    result = {
        "score": 1.0,
        "total_return_pct": 70.0,
        "max_drawdown_pct": 10.0,
        "estimated_cost_drag_pct": 0.0,
        "config": {"defensive_trim_cooldown_bars": 12},
        "event_diagnostics": {
            "flags": [],
            "ratios": {
                "one_way_forced_trim_per_add": 0.41,
                "turnover_events_per_add": 2.8,
            },
        },
    }

    penalized = _selection_score(
        result,
        flag_penalty=0.0,
        fast_defense_structural_penalty=0.2,
        fast_defense_max_cooldown_bars=24,
        fast_defense_min_train_return_pct=60.0,
        fast_defense_min_one_way_trim_per_add=0.35,
        fast_defense_min_turnover_per_add=2.5,
    )
    source_defense = _selection_score(
        {**result, "config": {"defensive_trim_cooldown_bars": 12960}},
        flag_penalty=0.0,
        fast_defense_structural_penalty=0.2,
        fast_defense_max_cooldown_bars=24,
        fast_defense_min_train_return_pct=60.0,
        fast_defense_min_one_way_trim_per_add=0.35,
        fast_defense_min_turnover_per_add=2.5,
    )
    low_turnover = _selection_score(
        {
            **result,
            "event_diagnostics": {
                "flags": [],
                "ratios": {
                    "one_way_forced_trim_per_add": 0.41,
                    "turnover_events_per_add": 2.1,
                },
            },
        },
        flag_penalty=0.0,
        fast_defense_structural_penalty=0.2,
        fast_defense_max_cooldown_bars=24,
        fast_defense_min_train_return_pct=60.0,
        fast_defense_min_one_way_trim_per_add=0.35,
        fast_defense_min_turnover_per_add=2.5,
    )

    assert penalized == 0.8
    assert source_defense == 1.0
    assert low_turnover == 1.0


def test_regime_dependency_stats_reports_dominant_positive_regime() -> None:
    stats = _regime_dependency_stats(
        {
            "regime_performance": {
                "downtrend": {"return_pct": 90.0},
                "uptrend": {"return_pct": 10.0},
                "range_or_transition": {"return_pct": -2.0},
            }
        }
    )

    assert stats == {
        "dominant_regime": "downtrend",
        "dominant_regime_return_pct": 90.0,
        "dominant_regime_return_share": 0.9,
        "positive_regime_return_sum_pct": 100.0,
        "positive_regime_count": 2,
    }


def test_top_train_candidate_audit_reports_oracle_regret() -> None:
    audit = _aggregate_top_train_candidate_audit(
        [
            {
                "fold": 1,
                "test_start": "2026-01-01",
                "test_end": "2026-04-01",
                "train_top_test_results": [
                    {
                        "rank": 1,
                        "is_selected": True,
                        "model_id": "selected",
                        "train_selection_score": 1.0,
                        "train_return_pct": 40.0,
                        "test_return_pct": 5.0,
                        "test_max_drawdown_pct": 4.0,
                        "after_selection_overlays_applied": ["equity_circuit"],
                        "test_flags": ["too_few_orders"],
                        "test_result": {"estimated_cost_drag_pct": 2.0, "trade_like_events": 6},
                    },
                    {
                        "rank": 2,
                        "is_selected": False,
                        "model_id": "best",
                        "train_selection_score": 0.9,
                        "train_return_pct": 35.0,
                        "test_return_pct": 9.0,
                        "test_max_drawdown_pct": 3.0,
                        "after_selection_overlays_applied": ["equity_circuit", "near_miss"],
                        "test_flags": [],
                        "test_result": {"estimated_cost_drag_pct": 3.0, "trade_like_events": 12},
                    },
                ],
            },
            {
                "fold": 2,
                "test_start": "2026-04-01",
                "test_end": "2026-07-01",
                "train_top_test_results": [
                    {
                        "rank": 1,
                        "is_selected": True,
                        "model_id": "selected_2",
                        "train_selection_score": 1.1,
                        "train_return_pct": 20.0,
                        "test_return_pct": 4.0,
                        "test_max_drawdown_pct": 2.0,
                        "test_result": {"estimated_cost_drag_pct": 1.0},
                    },
                    {
                        "rank": 2,
                        "is_selected": False,
                        "model_id": "worse",
                        "train_selection_score": 1.0,
                        "train_return_pct": 19.0,
                        "test_return_pct": 1.0,
                        "test_max_drawdown_pct": 1.0,
                        "test_result": {"estimated_cost_drag_pct": 0.5},
                    },
                ],
            },
        ]
    )

    assert audit["audited_fold_count"] == 2
    assert audit["missed_best_count"] == 1
    assert audit["selected_best_count"] == 1
    assert audit["selected_best_with_test_flags_count"] == 0
    assert audit["missed_best_flag_improvement_count"] == 1
    assert audit["missed_best_higher_cost_count"] == 1
    assert audit["missed_best_higher_drawdown_count"] == 0
    assert audit["missed_best_higher_cost_or_drawdown_count"] == 1
    assert audit["missed_best_clean_improvement_count"] == 0
    assert audit["avg_return_regret_pct"] == 2.0
    assert audit["selected_compounded_return_pct"] == 9.2
    assert audit["oracle_best_compounded_return_pct"] == 13.36
    assert audit["best_rank_counts"] == {"1": 1, "2": 1}
    assert audit["highest_regret_folds"][0]["fold"] == 1
    assert audit["highest_regret_folds"][0]["best"]["rank"] == 2
    assert audit["highest_regret_folds"][0]["best"]["after_selection_overlays_applied"] == [
        "equity_circuit",
        "near_miss",
    ]
    assert audit["highest_regret_folds"][0]["selected"]["test_trade_like_events"] == 6
    assert audit["highest_regret_folds"][0]["best"]["test_trade_like_events"] == 12
    assert audit["highest_regret_folds"][0]["flag_delta_vs_best"] == {
        "selected_count": 1,
        "best_count": 0,
        "selected_only": ["too_few_orders"],
        "best_only": [],
    }


def test_top_train_candidate_overlay_audit_reports_candidate_family_edge() -> None:
    audit = _aggregate_top_train_candidate_overlay_audit(
        [
            {
                "fold": 1,
                "train_top_test_results": [
                    {
                        "rank": 1,
                        "is_selected": True,
                        "train_selection_score": 1.0,
                        "train_return_pct": 20.0,
                        "test_return_pct": 5.0,
                        "test_max_drawdown_pct": 4.0,
                        "test_result": {"estimated_cost_drag_pct": 1.0},
                        "after_selection_overlays_applied": ["equity_circuit"],
                        "test_flags": ["too_few_orders"],
                    },
                    {
                        "rank": 2,
                        "train_selection_score": 0.8,
                        "train_return_pct": 18.0,
                        "test_return_pct": 12.0,
                        "test_max_drawdown_pct": 3.0,
                        "test_result": {"estimated_cost_drag_pct": 2.0},
                        "after_selection_overlays_applied": [
                            "equity_circuit",
                            "one_way_loss_fuse",
                        ],
                        "test_flags": [],
                    },
                ],
            }
        ]
    )

    assert audit["equity_circuit"]["candidate_count"] == 2
    assert audit["equity_circuit"]["selected_count"] == 1
    assert audit["equity_circuit"]["best_count"] == 1
    assert audit["one_way_loss_fuse"]["candidate_count"] == 1
    assert audit["one_way_loss_fuse"]["best_count"] == 1
    assert audit["one_way_loss_fuse"]["avg_test_return_pct"] == 12.0
    assert audit["equity_circuit"]["test_flag_counts"] == {"too_few_orders": 1}


def test_after_selection_confirmation_rejects_weak_cost_efficiency() -> None:
    args = SimpleNamespace(
        after_selection_confirm_min_score_delta=None,
        after_selection_confirm_min_return_delta_pct=None,
        after_selection_confirm_max_drawdown_delta_pct=None,
        after_selection_confirm_max_cost_delta_pct=None,
        after_selection_confirm_min_return_per_cost_delta=1.0,
    )
    before = {
        "total_return_pct": 10.0,
        "max_drawdown_pct": 8.0,
        "estimated_cost_drag_pct": 5.0,
        "walk_forward_selection_score": 0.4,
    }
    after = {
        "total_return_pct": 10.2,
        "max_drawdown_pct": 8.0,
        "estimated_cost_drag_pct": 5.5,
        "walk_forward_selection_score": 0.4,
    }

    passed, details = _after_selection_train_confirmation(before, after, args)

    assert not passed
    assert details["failed_checks"] == ["return_per_cost_delta"]
    assert details["return_per_cost_delta"] == 0.4


def test_after_selection_confirmation_accepts_cost_efficient_overlay() -> None:
    args = SimpleNamespace(
        after_selection_confirm_min_score_delta=-0.1,
        after_selection_confirm_min_return_delta_pct=0.0,
        after_selection_confirm_max_drawdown_delta_pct=0.2,
        after_selection_confirm_max_cost_delta_pct=0.6,
        after_selection_confirm_min_return_per_cost_delta=1.0,
    )
    before = {
        "total_return_pct": 10.0,
        "max_drawdown_pct": 8.0,
        "estimated_cost_drag_pct": 5.0,
        "walk_forward_selection_score": 0.4,
    }
    after = {
        "total_return_pct": 10.8,
        "max_drawdown_pct": 8.1,
        "estimated_cost_drag_pct": 5.5,
        "walk_forward_selection_score": 0.35,
    }

    passed, details = _after_selection_train_confirmation(before, after, args)

    assert passed
    assert details["failed_checks"] == []
    assert details["return_per_cost_delta"] == 1.6


def test_after_selection_confirmation_rejects_cost_delta_cap() -> None:
    args = SimpleNamespace(
        after_selection_confirm_min_score_delta=None,
        after_selection_confirm_min_return_delta_pct=None,
        after_selection_confirm_max_drawdown_delta_pct=None,
        after_selection_confirm_max_cost_delta_pct=0.25,
        after_selection_confirm_min_return_per_cost_delta=None,
    )
    before = {
        "total_return_pct": 10.0,
        "max_drawdown_pct": 8.0,
        "estimated_cost_drag_pct": 5.0,
        "walk_forward_selection_score": 0.4,
    }
    after = {
        "total_return_pct": 11.0,
        "max_drawdown_pct": 8.0,
        "estimated_cost_drag_pct": 5.5,
        "walk_forward_selection_score": 0.5,
    }

    passed, details = _after_selection_train_confirmation(before, after, args)

    assert not passed
    assert details["failed_checks"] == ["cost_delta"]


def test_after_selection_confirmation_targets_only_configured_overlays() -> None:
    args = SimpleNamespace(after_selection_confirm_overlays="one_way_impulse_tail, one_way_impulse_late")

    targets = _after_selection_confirmation_targets(
        ["equity_circuit", "one_way_impulse_tail", "risk_smoothing"],
        args,
    )

    assert targets == ["one_way_impulse_tail"]


def test_after_selection_confirmation_targets_all_when_unconfigured() -> None:
    args = SimpleNamespace(after_selection_confirm_overlays="")

    targets = _after_selection_confirmation_targets(
        ["equity_circuit", "one_way_impulse_tail"],
        args,
    )

    assert targets == ["equity_circuit", "one_way_impulse_tail"]


def test_after_selection_confirmation_mode_defaults_to_enforce() -> None:
    assert _after_selection_confirmation_should_enforce(SimpleNamespace())


def test_after_selection_confirmation_shadow_mode_does_not_enforce() -> None:
    args = SimpleNamespace(after_selection_confirmation_mode="shadow")

    assert not _after_selection_confirmation_should_enforce(args)


def test_after_selection_recent_oos_blocks_only_eligible_weak_overlays() -> None:
    args = SimpleNamespace(
        after_selection_recent_oos_block=True,
        after_selection_recent_oos_block_lookback=3,
        after_selection_recent_oos_block_min_samples=1,
        after_selection_recent_oos_block_min_avg_return_pct=5.0,
        after_selection_recent_oos_block_min_compounded_return_pct=None,
        after_selection_recent_oos_block_max_drawdown_pct=None,
        after_selection_recent_oos_block_max_avg_cost_drag_pct=None,
        after_selection_recent_oos_block_max_cost_to_return_ratio=1.0,
        after_selection_recent_oos_block_confirmation_warnings=True,
        after_selection_recent_oos_block_overlays="one_way_impulse_tail,near_miss",
    )
    completed_folds = [
        {
            "fold": 1,
            "after_selection_overlays_applied": ["equity_circuit", "one_way_impulse_tail"],
            "after_selection_train_confirmation": {
                "would_reject": True,
                "target_overlays": ["one_way_impulse_tail"],
            },
            "test_result": {
                "final_equity": 1.02,
                "total_return_pct": 2.0,
                "estimated_cost_drag_pct": 3.0,
                "max_drawdown_pct": 4.0,
            },
        },
        {
            "fold": 2,
            "after_selection_overlays_applied": ["equity_circuit", "near_miss"],
            "test_result": {
                "final_equity": 1.12,
                "total_return_pct": 12.0,
                "estimated_cost_drag_pct": 2.0,
                "max_drawdown_pct": 4.0,
            },
        },
    ]

    blocked = _after_selection_recent_oos_blocks(completed_folds, args)

    assert sorted(blocked) == ["one_way_impulse_tail"]
    assert blocked["one_way_impulse_tail"]["failed_checks"] == [
        "avg_return",
        "cost_to_return",
        "confirmation_warning",
    ]
    assert blocked["one_way_impulse_tail"]["confirmation_warning_count"] == 1


def test_near_miss_after_selection_only_applies_inside_train_return_band() -> None:
    args = SimpleNamespace(
        near_miss_after_selection_min_train_return_pct=0.0,
        near_miss_after_selection_max_train_return_pct=15.0,
        near_miss_after_selection_min_train_drawdown_pct=None,
        near_miss_after_selection_max_train_drawdown_pct=None,
    )

    assert _near_miss_after_selection_allowed({"total_return_pct": 8.0, "max_drawdown_pct": 10.0}, args)
    assert not _near_miss_after_selection_allowed({"total_return_pct": 25.0, "max_drawdown_pct": 10.0}, args)


def test_fragile_inventory_trim_after_selection_requires_targeted_train_band() -> None:
    args = SimpleNamespace(
        fragile_regime_inventory_trim_after_selection_min_train_return_pct=-10.0,
        fragile_regime_inventory_trim_after_selection_max_train_return_pct=15.0,
        fragile_regime_inventory_trim_after_selection_min_train_drawdown_pct=20.0,
        fragile_regime_inventory_trim_after_selection_max_train_drawdown_pct=35.0,
    )
    target_train = {"total_return_pct": 2.5, "max_drawdown_pct": 24.0}

    assert _fragile_regime_inventory_trim_after_selection_allowed(target_train, args)
    assert not _fragile_regime_inventory_trim_after_selection_allowed(
        {**target_train, "total_return_pct": 25.0},
        args,
    )
    assert not _fragile_regime_inventory_trim_after_selection_allowed(
        {**target_train, "max_drawdown_pct": 12.0},
        args,
    )


def test_fragile_regime_entry_after_selection_requires_targeted_train_band() -> None:
    args = SimpleNamespace(
        fragile_regime_entry_after_selection_min_train_return_pct=170.0,
        fragile_regime_entry_after_selection_max_train_return_pct=185.0,
        fragile_regime_entry_after_selection_min_train_drawdown_pct=15.0,
        fragile_regime_entry_after_selection_max_train_drawdown_pct=16.0,
    )
    target_train = {"total_return_pct": 178.9, "max_drawdown_pct": 15.5}

    assert _fragile_regime_entry_after_selection_allowed(target_train, args)
    assert not _fragile_regime_entry_after_selection_allowed(
        {**target_train, "total_return_pct": 190.0},
        args,
    )
    assert not _fragile_regime_entry_after_selection_allowed(
        {**target_train, "max_drawdown_pct": 18.0},
        args,
    )


def test_one_way_reversal_weak_overlay_requires_low_return_high_trim_band() -> None:
    args = SimpleNamespace(
        one_way_reversal_after_selection_weak_switch_units=0.2,
        one_way_reversal_after_selection_weak_min_train_return_pct=10.0,
        one_way_reversal_after_selection_weak_max_train_return_pct=15.0,
        one_way_reversal_after_selection_weak_min_train_drawdown_pct=20.0,
        one_way_reversal_after_selection_weak_max_train_drawdown_pct=None,
        one_way_reversal_after_selection_weak_min_one_way_trim_per_add=0.5,
        one_way_reversal_after_selection_weak_max_one_way_trim_per_add=0.0,
    )
    weak_train = {
        "total_return_pct": 12.0,
        "max_drawdown_pct": 23.0,
        "event_diagnostics": {"ratios": {"one_way_forced_trim_per_add": 0.55}},
    }

    assert _one_way_reversal_after_selection_weak_allowed(weak_train, args)
    assert not _one_way_reversal_after_selection_weak_allowed(
        {**weak_train, "total_return_pct": 18.0},
        args,
    )
    assert not _one_way_reversal_after_selection_weak_allowed(
        {**weak_train, "event_diagnostics": {"ratios": {"one_way_forced_trim_per_add": 0.3}}},
        args,
    )


def test_risk_smoothing_overlay_requires_targeted_profitable_drawdown_state() -> None:
    args = SimpleNamespace(
        risk_smoothing_after_selection_min_train_return_pct=75.0,
        risk_smoothing_after_selection_max_train_return_pct=90.0,
        risk_smoothing_after_selection_min_train_drawdown_pct=14.0,
        risk_smoothing_after_selection_max_train_drawdown_pct=15.0,
        risk_smoothing_after_selection_min_train_cost_drag_pct=75.0,
        risk_smoothing_after_selection_max_train_cost_drag_pct=90.0,
        risk_smoothing_after_selection_min_one_way_trim_per_add=0.4,
        risk_smoothing_after_selection_max_one_way_trim_per_add=0.45,
        risk_smoothing_after_selection_min_turnover_per_add=2.7,
        risk_smoothing_after_selection_max_turnover_per_add=2.9,
    )
    target_train = {
        "total_return_pct": 81.9,
        "max_drawdown_pct": 14.35,
        "estimated_cost_drag_pct": 82.75,
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.41,
                "turnover_events_per_add": 2.82,
            }
        },
    }

    assert _risk_smoothing_after_selection_allowed(target_train, args)
    assert not _risk_smoothing_after_selection_allowed({**target_train, "total_return_pct": 120.0}, args)
    assert not _risk_smoothing_after_selection_allowed(
        {
            **target_train,
            "event_diagnostics": {
                "ratios": {
                    "one_way_forced_trim_per_add": 0.41,
                    "turnover_events_per_add": 2.4,
                }
            },
        },
        args,
    )


def test_hold_compression_targets_medium_return_tail_risk_state() -> None:
    args = SimpleNamespace(
        hold_compression_after_selection_min_source_max_units=1.5,
        hold_compression_after_selection_max_source_max_units=1.5,
        hold_compression_after_selection_min_train_return_pct=18.0,
        hold_compression_after_selection_max_train_return_pct=22.0,
        hold_compression_after_selection_min_train_drawdown_pct=13.0,
        hold_compression_after_selection_max_train_drawdown_pct=15.0,
        hold_compression_after_selection_min_train_cost_drag_pct=18.0,
        hold_compression_after_selection_max_train_cost_drag_pct=21.0,
        hold_compression_after_selection_min_one_way_trim_per_add=0.42,
        hold_compression_after_selection_max_one_way_trim_per_add=0.45,
        hold_compression_after_selection_min_turnover_per_add=2.50,
        hold_compression_after_selection_max_turnover_per_add=2.60,
        hold_compression_after_selection_max_hold_bars=24,
    )
    target_train = {
        "total_return_pct": 19.2,
        "max_drawdown_pct": 14.1,
        "estimated_cost_drag_pct": 19.61,
        "config": {"max_possible_units": 1.5},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.4386,
                "turnover_events_per_add": 2.5614,
            }
        },
    }

    assert _train_state_after_selection_allowed(
        target_train,
        args,
        prefix="hold_compression_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {**target_train, "total_return_pct": 28.9},
        args,
        prefix="hold_compression_after_selection",
    )

    compressed = _apply_hold_compression_overlay(
        _HoldOnlyConfig(model_id="model", max_hold_bars=52),
        args,
    )
    unchanged = _apply_hold_compression_overlay(
        _HoldOnlyConfig(model_id="model", max_hold_bars=18),
        args,
    )

    assert compressed.max_hold_bars == 24
    assert compressed.model_id == "model:wfHoldCompress24"
    assert unchanged.max_hold_bars == 18
    assert unchanged.model_id == "model"


def test_reaction_tune_targets_exit_too_early_train_state() -> None:
    args = SimpleNamespace(
        reaction_tune_after_selection_min_source_max_units=1.0,
        reaction_tune_after_selection_max_source_max_units=1.0,
        reaction_tune_after_selection_min_train_return_pct=14.0,
        reaction_tune_after_selection_max_train_return_pct=75.0,
        reaction_tune_after_selection_min_train_drawdown_pct=12.0,
        reaction_tune_after_selection_max_train_drawdown_pct=31.0,
        reaction_tune_after_selection_min_train_cost_drag_pct=20.0,
        reaction_tune_after_selection_max_train_cost_drag_pct=35.0,
        reaction_tune_after_selection_min_one_way_trim_per_add=0.35,
        reaction_tune_after_selection_max_one_way_trim_per_add=0.55,
        reaction_tune_after_selection_min_turnover_per_add=2.0,
        reaction_tune_after_selection_max_turnover_per_add=2.2,
        reaction_tune_after_selection_reaction_trim_trigger=0.75,
        reaction_tune_after_selection_repair_cut=None,
        reaction_tune_after_selection_repair_stop=None,
    )
    target_train = {
        "total_return_pct": 71.95,
        "max_drawdown_pct": 12.15,
        "estimated_cost_drag_pct": 34.55,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.3696,
                "turnover_events_per_add": 2.1522,
            }
        },
    }

    assert _train_state_after_selection_allowed(
        target_train,
        args,
        prefix="reaction_tune_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {**target_train, "estimated_cost_drag_pct": 43.88},
        args,
        prefix="reaction_tune_after_selection",
    )

    tuned = _apply_reaction_tune_overlay(
        _ReactionOnlyConfig(
            model_id="model",
            reaction_trim_trigger=0.55,
            repair_cut=0.9,
            repair_stop=1.2,
        ),
        args,
    )

    assert tuned.reaction_trim_trigger == 0.75
    assert tuned.repair_cut == 0.9
    assert tuned.repair_stop == 1.2
    assert tuned.model_id == "model:wfReactTrim0.75"

    strong_args = SimpleNamespace(
        reaction_tune_strong_after_selection_reaction_trim_trigger=1.5,
        reaction_tune_strong_after_selection_repair_cut=None,
        reaction_tune_strong_after_selection_repair_stop=None,
    )
    strong = _apply_reaction_tune_overlay(
        tuned,
        strong_args,
        prefix="reaction_tune_strong_after_selection",
        reaction_suffix_label="wfReactStrong",
    )

    assert strong.reaction_trim_trigger == 1.5
    assert strong.repair_cut == 0.9
    assert strong.repair_stop == 1.2
    assert strong.model_id == "model:wfReactTrim0.75:wfReactStrong1.5"


def test_repair_tune_targets_high_cost_repair_state() -> None:
    args = SimpleNamespace(
        repair_tune_after_selection_min_source_max_units=1.0,
        repair_tune_after_selection_max_source_max_units=1.0,
        repair_tune_after_selection_min_train_return_pct=45.0,
        repair_tune_after_selection_max_train_return_pct=225.0,
        repair_tune_after_selection_min_train_drawdown_pct=14.0,
        repair_tune_after_selection_max_train_drawdown_pct=22.0,
        repair_tune_after_selection_min_train_cost_drag_pct=40.0,
        repair_tune_after_selection_max_train_cost_drag_pct=90.0,
        repair_tune_after_selection_min_one_way_trim_per_add=0.30,
        repair_tune_after_selection_max_one_way_trim_per_add=0.39,
        repair_tune_after_selection_min_turnover_per_add=2.40,
        repair_tune_after_selection_max_turnover_per_add=2.47,
        repair_tune_after_selection_repair_cut=0.7,
        repair_tune_after_selection_repair_stop=None,
    )
    target_train = {
        "total_return_pct": 221.4787,
        "max_drawdown_pct": 14.6319,
        "estimated_cost_drag_pct": 81.897,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.3091,
                "turnover_events_per_add": 2.4182,
            }
        },
    }

    assert _train_state_after_selection_allowed(
        target_train,
        args,
        prefix="repair_tune_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {**target_train, "estimated_cost_drag_pct": 35.0},
        args,
        prefix="repair_tune_after_selection",
    )

    tuned = _apply_repair_tune_overlay(
        _ReactionOnlyConfig(
            model_id="model",
            reaction_trim_trigger=0.55,
            repair_cut=0.9,
            repair_stop=1.2,
        ),
        args,
    )

    assert tuned.reaction_trim_trigger == 0.55
    assert tuned.repair_cut == 0.7
    assert tuned.repair_stop == 1.2
    assert tuned.model_id == "model:wfRepairTuneCut0.7"


def test_repair_tune_high_cost_targets_narrow_runner_state() -> None:
    args = SimpleNamespace(
        repair_tune_high_cost_after_selection_min_source_max_units=1.0,
        repair_tune_high_cost_after_selection_max_source_max_units=1.0,
        repair_tune_high_cost_after_selection_min_train_return_pct=45.0,
        repair_tune_high_cost_after_selection_max_train_return_pct=60.0,
        repair_tune_high_cost_after_selection_min_train_drawdown_pct=19.0,
        repair_tune_high_cost_after_selection_max_train_drawdown_pct=22.0,
        repair_tune_high_cost_after_selection_min_train_cost_drag_pct=40.0,
        repair_tune_high_cost_after_selection_max_train_cost_drag_pct=48.0,
        repair_tune_high_cost_after_selection_min_one_way_trim_per_add=0.35,
        repair_tune_high_cost_after_selection_max_one_way_trim_per_add=0.40,
        repair_tune_high_cost_after_selection_min_turnover_per_add=2.40,
        repair_tune_high_cost_after_selection_max_turnover_per_add=2.50,
        repair_tune_high_cost_after_selection_repair_cut=0.5,
        repair_tune_high_cost_after_selection_repair_stop=None,
    )
    target_train = {
        "total_return_pct": 51.606,
        "max_drawdown_pct": 20.5069,
        "estimated_cost_drag_pct": 43.885,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.375,
                "turnover_events_per_add": 2.4531,
            }
        },
    }

    assert _train_state_after_selection_allowed(
        target_train,
        args,
        prefix="repair_tune_high_cost_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {**target_train, "total_return_pct": 221.4787},
        args,
        prefix="repair_tune_high_cost_after_selection",
    )

    tuned = _apply_repair_tune_overlay(
        _ReactionOnlyConfig(
            model_id="model",
            reaction_trim_trigger=0.55,
            repair_cut=0.7,
            repair_stop=1.2,
        ),
        args,
        prefix="repair_tune_high_cost_after_selection",
        repair_cut_suffix_label="wfRepairHighCostCut",
        repair_stop_suffix_label="wfRepairHighCostStop",
    )

    assert tuned.reaction_trim_trigger == 0.55
    assert tuned.repair_cut == 0.5
    assert tuned.repair_stop == 1.2
    assert tuned.model_id == "model:wfRepairHighCostCut0.5"


def test_distribution_balance_targets_high_turnover_calendar_bucket_state() -> None:
    args = SimpleNamespace(
        distribution_balance_after_selection_min_source_max_units=1.0,
        distribution_balance_after_selection_max_source_max_units=1.0,
        distribution_balance_after_selection_min_train_return_pct=160.0,
        distribution_balance_after_selection_max_train_return_pct=175.0,
        distribution_balance_after_selection_min_train_drawdown_pct=19.0,
        distribution_balance_after_selection_max_train_drawdown_pct=22.0,
        distribution_balance_after_selection_min_train_cost_drag_pct=60.0,
        distribution_balance_after_selection_max_train_cost_drag_pct=70.0,
        distribution_balance_after_selection_min_one_way_trim_per_add=0.37,
        distribution_balance_after_selection_max_one_way_trim_per_add=0.39,
        distribution_balance_after_selection_min_turnover_per_add=2.45,
        distribution_balance_after_selection_max_turnover_per_add=2.49,
        distribution_balance_probe_units=0.00025,
        distribution_balance_probe_min_score=4,
        distribution_balance_probe_min_score_edge=0,
        distribution_balance_probe_min_reason_stack=1,
        distribution_balance_probe_cooldown_bars=36,
        distribution_balance_probe_max_extension_atr=2.0,
        distribution_balance_probe_failure_guard_count=2,
        distribution_balance_probe_failure_guard_window_bars=1440,
        distribution_balance_probe_failure_cooldown_bars=4320,
    )
    target_train = {
        "total_return_pct": 167.6266,
        "max_drawdown_pct": 20.5069,
        "estimated_cost_drag_pct": 66.9586,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.3818,
                "turnover_events_per_add": 2.4727,
            }
        },
    }

    assert _train_state_after_selection_allowed(
        target_train,
        args,
        prefix="distribution_balance_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {**target_train, "total_return_pct": 130.0},
        args,
        prefix="distribution_balance_after_selection",
    )

    tuned = _apply_distribution_balance_overlay(
        _DistributionBalanceOnlyConfig(
            model_id="model",
            max_possible_units=1.0,
            near_miss_probe_units=0.0,
            near_miss_probe_min_score=5,
            near_miss_probe_min_score_edge=1,
            near_miss_probe_min_reason_stack=1,
            near_miss_probe_cooldown_bars=72,
            near_miss_probe_max_extension_atr=1.75,
            near_miss_probe_failure_guard_count=0,
            near_miss_probe_failure_guard_window_bars=1440,
            near_miss_probe_failure_cooldown_bars=0,
        ),
        args,
    )

    assert tuned.near_miss_probe_units == 0.00025
    assert tuned.near_miss_probe_min_score == 4
    assert tuned.near_miss_probe_min_score_edge == 0
    assert tuned.near_miss_probe_cooldown_bars == 36
    assert tuned.near_miss_probe_failure_guard_count == 2
    assert tuned.near_miss_probe_failure_cooldown_bars == 4320
    assert tuned.model_id == (
        "model:wfDistributionBalance0.00025:wfDistributionBalanceScore4:"
        "wfDistributionBalanceEdge0:wfDistributionBalanceStack1:"
        "wfDistributionBalanceCool36:wfDistributionBalanceExt2:"
        "wfDistributionBalanceFail2:wfDistributionBalanceFailWin1440:"
        "wfDistributionBalanceFailCool4320"
    )


def test_high_cost_balance_targets_runner_state_with_tiny_probe() -> None:
    args = SimpleNamespace(
        high_cost_balance_after_selection_min_source_max_units=1.0,
        high_cost_balance_after_selection_max_source_max_units=1.0,
        high_cost_balance_after_selection_min_train_return_pct=45.0,
        high_cost_balance_after_selection_max_train_return_pct=60.0,
        high_cost_balance_after_selection_min_train_drawdown_pct=19.0,
        high_cost_balance_after_selection_max_train_drawdown_pct=22.0,
        high_cost_balance_after_selection_min_train_cost_drag_pct=40.0,
        high_cost_balance_after_selection_max_train_cost_drag_pct=48.0,
        high_cost_balance_after_selection_min_one_way_trim_per_add=0.35,
        high_cost_balance_after_selection_max_one_way_trim_per_add=0.40,
        high_cost_balance_after_selection_min_turnover_per_add=2.40,
        high_cost_balance_after_selection_max_turnover_per_add=2.50,
        high_cost_balance_after_selection_one_way_trim_cooldown_bars=2880,
        high_cost_balance_after_selection_base_entry_reduce_extension_atr=1.5,
        high_cost_balance_after_selection_base_entry_reduce_size_mult=0.25,
        high_cost_balance_after_selection_base_entry_reduce_promote_reaction=1.0,
        high_cost_balance_probe_units=0.0005,
        high_cost_balance_probe_min_score=4,
        high_cost_balance_probe_min_score_edge=0,
        high_cost_balance_probe_min_reason_stack=1,
        high_cost_balance_probe_cooldown_bars=36,
        high_cost_balance_probe_max_extension_atr=2.0,
        high_cost_balance_probe_failure_guard_count=2,
        high_cost_balance_probe_failure_guard_window_bars=1440,
        high_cost_balance_probe_failure_cooldown_bars=4320,
    )
    target_train = {
        "total_return_pct": 51.606,
        "max_drawdown_pct": 20.5069,
        "estimated_cost_drag_pct": 43.885,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.375,
                "turnover_events_per_add": 2.4531,
            }
        },
    }

    assert _train_state_after_selection_allowed(
        target_train,
        args,
        prefix="high_cost_balance_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {**target_train, "estimated_cost_drag_pct": 35.0},
        args,
        prefix="high_cost_balance_after_selection",
    )

    tuned = _apply_high_cost_balance_overlay(
        _HighCostBalanceOnlyConfig(
            model_id="model",
            max_possible_units=1.0,
            one_way_trim_cooldown_bars=1440,
            base_entry_reduce_extension_atr=0.0,
            base_entry_reduce_size_mult=1.0,
            base_entry_reduce_promote_reaction=0.0,
            near_miss_probe_units=0.0,
            near_miss_probe_min_score=5,
            near_miss_probe_min_score_edge=1,
            near_miss_probe_min_reason_stack=1,
            near_miss_probe_cooldown_bars=72,
            near_miss_probe_max_extension_atr=1.75,
            near_miss_probe_failure_guard_count=0,
            near_miss_probe_failure_guard_window_bars=1440,
            near_miss_probe_failure_cooldown_bars=0,
        ),
        args,
    )

    assert tuned.one_way_trim_cooldown_bars == 2880
    assert tuned.base_entry_reduce_extension_atr == 1.5
    assert tuned.base_entry_reduce_size_mult == 0.25
    assert tuned.base_entry_reduce_promote_reaction == 1.0
    assert tuned.near_miss_probe_units == 0.0005
    assert tuned.near_miss_probe_min_score == 4
    assert tuned.near_miss_probe_min_score_edge == 0
    assert tuned.near_miss_probe_cooldown_bars == 36
    assert tuned.near_miss_probe_failure_guard_count == 2
    assert tuned.near_miss_probe_failure_cooldown_bars == 4320
    assert tuned.model_id == (
        "model:wfHighCostBalanceTrim2880:wfHighCostBalanceBaseExt1.5:"
        "wfHighCostBalanceBaseMult0.25:wfHighCostBalanceBaseProm1:"
        "wfHighCostBalanceNear0.0005:"
        "wfHighCostBalanceNearScore4:wfHighCostBalanceNearEdge0:"
        "wfHighCostBalanceNearStack1:wfHighCostBalanceNearCool36:"
        "wfHighCostBalanceNearExt2:wfHighCostBalanceNearFail2:"
        "wfHighCostBalanceNearFailWin1440:wfHighCostBalanceNearFailCool4320"
    )


def test_trim_cooldown_targets_forced_trim_trend_cut_state() -> None:
    args = SimpleNamespace(
        trim_cooldown_after_selection_min_source_max_units=1.0,
        trim_cooldown_after_selection_max_source_max_units=1.0,
        trim_cooldown_after_selection_min_train_return_pct=42.0,
        trim_cooldown_after_selection_max_train_return_pct=45.0,
        trim_cooldown_after_selection_min_train_drawdown_pct=31.0,
        trim_cooldown_after_selection_max_train_drawdown_pct=33.0,
        trim_cooldown_after_selection_min_train_cost_drag_pct=37.0,
        trim_cooldown_after_selection_max_train_cost_drag_pct=40.0,
        trim_cooldown_after_selection_min_one_way_trim_per_add=0.39,
        trim_cooldown_after_selection_max_one_way_trim_per_add=0.41,
        trim_cooldown_after_selection_min_turnover_per_add=2.13,
        trim_cooldown_after_selection_max_turnover_per_add=2.16,
        trim_cooldown_after_selection_one_way_trim_cooldown_bars=12960,
        trim_cooldown_after_selection_base_entry_reduce_extension_atr=1.5,
        trim_cooldown_after_selection_base_entry_reduce_size_mult=0.25,
        trim_cooldown_after_selection_base_entry_reduce_promote_reaction=1.0,
    )
    target_train = {
        "total_return_pct": 43.7566,
        "max_drawdown_pct": 32.3797,
        "estimated_cost_drag_pct": 38.4444,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.4,
                "turnover_events_per_add": 2.1455,
            }
        },
    }

    assert _train_state_after_selection_allowed(
        target_train,
        args,
        prefix="trim_cooldown_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {**target_train, "config": {"max_possible_units": 1.5}},
        args,
        prefix="trim_cooldown_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {**target_train, "estimated_cost_drag_pct": 34.0},
        args,
        prefix="trim_cooldown_after_selection",
    )

    tuned = _apply_trim_cooldown_overlay(
        _TrimCooldownOnlyConfig(
            model_id="model",
            one_way_trim_cooldown_bars=6,
            base_entry_reduce_extension_atr=0.0,
            base_entry_reduce_size_mult=1.0,
            base_entry_reduce_promote_reaction=0.0,
        ),
        args,
    )

    assert tuned.one_way_trim_cooldown_bars == 12960
    assert tuned.base_entry_reduce_extension_atr == 1.5
    assert tuned.base_entry_reduce_size_mult == 0.25
    assert tuned.base_entry_reduce_promote_reaction == 1.0
    assert (
        tuned.model_id
        == "model:wfTrimCool12960:wfTrimBaseExt1.5:wfTrimBaseMult0.25:wfTrimBaseProm1"
    )

    deep_args = SimpleNamespace(
        trim_cooldown_deep_after_selection_one_way_trim_cooldown_bars=1440,
        trim_cooldown_deep_after_selection_base_entry_reduce_extension_atr=None,
        trim_cooldown_deep_after_selection_base_entry_reduce_size_mult=None,
        trim_cooldown_deep_after_selection_base_entry_reduce_promote_reaction=None,
    )
    deep_tuned = _apply_trim_cooldown_overlay(
        tuned,
        deep_args,
        prefix="trim_cooldown_deep_after_selection",
        cooldown_suffix_label="wfTrimDeepCool",
        base_extension_suffix_label="wfTrimDeepBaseExt",
        base_size_suffix_label="wfTrimDeepBaseMult",
        base_promote_suffix_label="wfTrimDeepBaseProm",
    )

    assert deep_tuned.one_way_trim_cooldown_bars == 1440
    assert deep_tuned.base_entry_reduce_extension_atr == 1.5
    assert deep_tuned.model_id.endswith(":wfTrimDeepCool1440")


def test_risk_off_micro_targets_sparse_defensive_train_state() -> None:
    args = SimpleNamespace(
        risk_off_micro_after_selection_min_source_max_units=1.5,
        risk_off_micro_after_selection_max_source_max_units=1.5,
        risk_off_micro_after_selection_min_train_return_pct=36.0,
        risk_off_micro_after_selection_max_train_return_pct=40.0,
        risk_off_micro_after_selection_min_train_drawdown_pct=19.0,
        risk_off_micro_after_selection_max_train_drawdown_pct=21.0,
        risk_off_micro_after_selection_min_train_cost_drag_pct=22.0,
        risk_off_micro_after_selection_max_train_cost_drag_pct=24.0,
        risk_off_micro_after_selection_min_one_way_trim_per_add=0.49,
        risk_off_micro_after_selection_max_one_way_trim_per_add=0.51,
        risk_off_micro_after_selection_min_turnover_per_add=2.36,
        risk_off_micro_after_selection_max_turnover_per_add=2.40,
        risk_off_micro_after_selection_max_possible_units=0.5,
        risk_off_micro_after_selection_base_max_units=0.5,
        risk_off_micro_after_selection_battle_units=0.5,
        risk_off_micro_after_selection_trend_core_units=0.5,
        risk_off_micro_after_selection_reaction_trim_trigger=0.45,
    )
    target_train = {
        "total_return_pct": 38.6814,
        "max_drawdown_pct": 19.9899,
        "estimated_cost_drag_pct": 23.362,
        "config": {"max_possible_units": 1.5},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.5,
                "turnover_events_per_add": 2.3846,
            }
        },
    }

    assert _train_state_after_selection_allowed(
        target_train,
        args,
        prefix="risk_off_micro_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {**target_train, "config": {"max_possible_units": 1.0}},
        args,
        prefix="risk_off_micro_after_selection",
    )

    tuned = _apply_risk_off_micro_overlay(
        _RiskOffMicroOnlyConfig(
            model_id="model",
            max_possible_units=1.5,
            base_max_units=1.5,
            battle_units=1.5,
            trend_core_units=1.0,
            reaction_trim_trigger=0.55,
        ),
        args,
    )

    assert tuned.max_possible_units == 0.5
    assert tuned.base_max_units == 0.5
    assert tuned.battle_units == 0.5
    assert tuned.trend_core_units == 0.5
    assert tuned.reaction_trim_trigger == 0.45
    assert tuned.model_id == (
        "model:wfRiskOffMaxU0.5:wfRiskOffBaseMax0.5:wfRiskOffBattle0.5:"
        "wfRiskOffTrend0.5:wfRiskOffReact0.45"
    )


def test_battle_restore_targets_role_concentrated_train_state() -> None:
    args = SimpleNamespace(
        battle_restore_after_selection_min_source_max_units=1.5,
        battle_restore_after_selection_max_source_max_units=1.5,
        battle_restore_after_selection_min_train_return_pct=18.0,
        battle_restore_after_selection_max_train_return_pct=35.0,
        battle_restore_after_selection_min_train_drawdown_pct=6.0,
        battle_restore_after_selection_max_train_drawdown_pct=12.0,
        battle_restore_after_selection_min_train_cost_drag_pct=4.0,
        battle_restore_after_selection_max_train_cost_drag_pct=9.0,
        battle_restore_after_selection_min_one_way_trim_per_add=0.0,
        battle_restore_after_selection_max_one_way_trim_per_add=0.35,
        battle_restore_after_selection_min_turnover_per_add=1.0,
        battle_restore_after_selection_max_turnover_per_add=2.4,
        battle_restore_after_selection_min_battle_add_per_add=0.0,
        battle_restore_after_selection_max_battle_add_per_add=0.02,
        battle_restore_after_selection_min_max_role_add_share=0.75,
        battle_restore_after_selection_max_max_role_add_share=0.95,
        battle_restore_after_selection_min_add_events=12,
        battle_restore_after_selection_max_add_events=40,
        battle_restore_after_selection_battle_units=0.75,
        battle_restore_after_selection_battle_score=5,
        battle_restore_after_selection_battle_trigger_usd=80.0,
        battle_restore_after_selection_battle_trigger_atr=0.45,
        battle_restore_after_selection_max_repair_eff_for_add=1.45,
        battle_restore_after_selection_min_capacity_ratio=0.12,
    )
    target_train = {
        "total_return_pct": 24.5,
        "max_drawdown_pct": 8.4,
        "estimated_cost_drag_pct": 6.2,
        "config": {"max_possible_units": 1.5},
        "event_diagnostics": {
            "add_events": 18,
            "max_role_add_share": 0.8333,
            "ratios": {
                "battle_add_per_add": 0.0,
                "one_way_forced_trim_per_add": 0.22,
                "turnover_events_per_add": 2.0,
            },
        },
    }

    assert _battle_restore_after_selection_allowed(target_train, args)
    assert not _battle_restore_after_selection_allowed(
        {
            **target_train,
            "event_diagnostics": {
                "add_events": 18,
                "max_role_add_share": 0.8333,
                "ratios": {
                    "battle_add_per_add": 0.08,
                    "one_way_forced_trim_per_add": 0.22,
                    "turnover_events_per_add": 2.0,
                },
            },
        },
        args,
    )

    tuned = _apply_battle_restore_overlay(
        _BattleRestoreOnlyConfig(
            model_id="model",
            max_possible_units=1.5,
            battle_units=0.25,
            battle_score=7,
            battle_trigger_usd=150.0,
            battle_trigger_atr=0.8,
            max_repair_eff_for_add=1.1,
            min_capacity_ratio=0.25,
        ),
        args,
    )

    assert tuned.battle_units == 0.75
    assert tuned.battle_score == 5
    assert tuned.battle_trigger_usd == 80.0
    assert tuned.battle_trigger_atr == 0.45
    assert tuned.max_repair_eff_for_add == 1.45
    assert tuned.min_capacity_ratio == 0.12
    assert tuned.model_id == (
        "model:wfBattleUnits0.75:wfBattleScore5:wfBattleUsd80:"
        "wfBattleAtr0.45:wfBattleRepair1.45:wfBattleCap0.12"
    )


def test_exposure_rebalance_overlay_requires_targeted_unit_source_state() -> None:
    args = SimpleNamespace(
        exposure_rebalance_after_selection_min_source_max_units=1.0,
        exposure_rebalance_after_selection_max_source_max_units=1.0,
        exposure_rebalance_after_selection_min_train_return_pct=170.0,
        exposure_rebalance_after_selection_max_train_return_pct=185.0,
        exposure_rebalance_after_selection_min_train_drawdown_pct=15.0,
        exposure_rebalance_after_selection_max_train_drawdown_pct=16.0,
        exposure_rebalance_after_selection_min_train_cost_drag_pct=120.0,
        exposure_rebalance_after_selection_max_train_cost_drag_pct=130.0,
        exposure_rebalance_after_selection_min_one_way_trim_per_add=0.30,
        exposure_rebalance_after_selection_max_one_way_trim_per_add=0.32,
        exposure_rebalance_after_selection_min_turnover_per_add=2.40,
        exposure_rebalance_after_selection_max_turnover_per_add=2.43,
    )
    target_train = {
        "total_return_pct": 178.9,
        "max_drawdown_pct": 15.46,
        "estimated_cost_drag_pct": 124.5,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.309,
                "turnover_events_per_add": 2.418,
            }
        },
    }

    assert _exposure_rebalance_after_selection_allowed(target_train, args)
    assert not _exposure_rebalance_after_selection_allowed(
        {**target_train, "config": {"max_possible_units": 1.5}},
        args,
    )
    assert not _exposure_rebalance_after_selection_allowed(
        {
            **target_train,
            "event_diagnostics": {
                "ratios": {
                    "one_way_forced_trim_per_add": 0.309,
                    "turnover_events_per_add": 2.55,
                }
            },
        },
        args,
    )


def test_equity_soft_sizer_overlay_requires_targeted_train_state() -> None:
    args = SimpleNamespace(
        equity_soft_sizer_after_selection_min_source_max_units=1.0,
        equity_soft_sizer_after_selection_max_source_max_units=1.0,
        equity_soft_sizer_after_selection_min_train_return_pct=45.0,
        equity_soft_sizer_after_selection_max_train_return_pct=65.0,
        equity_soft_sizer_after_selection_min_train_drawdown_pct=10.0,
        equity_soft_sizer_after_selection_max_train_drawdown_pct=14.0,
        equity_soft_sizer_after_selection_min_train_cost_drag_pct=45.0,
        equity_soft_sizer_after_selection_max_train_cost_drag_pct=65.0,
        equity_soft_sizer_after_selection_min_one_way_trim_per_add=0.34,
        equity_soft_sizer_after_selection_max_one_way_trim_per_add=0.40,
        equity_soft_sizer_after_selection_min_turnover_per_add=2.05,
        equity_soft_sizer_after_selection_max_turnover_per_add=2.25,
    )
    target_train = {
        "total_return_pct": 52.98,
        "max_drawdown_pct": 12.83,
        "estimated_cost_drag_pct": 53.52,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.37,
                "turnover_events_per_add": 2.15,
            }
        },
    }

    assert _equity_soft_sizer_after_selection_allowed(target_train, args)
    assert not _equity_soft_sizer_after_selection_allowed(
        {**target_train, "config": {"max_possible_units": 1.5}},
        args,
    )
    assert not _equity_soft_sizer_after_selection_allowed(
        {
            **target_train,
            "event_diagnostics": {
                "ratios": {
                    "one_way_forced_trim_per_add": 0.37,
                    "turnover_events_per_add": 2.5,
                }
            },
        },
        args,
    )
    alt_args = SimpleNamespace(
        equity_soft_sizer_alt_after_selection_min_source_max_units=1.5,
        equity_soft_sizer_alt_after_selection_max_source_max_units=1.5,
        equity_soft_sizer_alt_after_selection_min_train_return_pct=15.0,
        equity_soft_sizer_alt_after_selection_max_train_return_pct=20.0,
        equity_soft_sizer_alt_after_selection_min_train_drawdown_pct=20.0,
        equity_soft_sizer_alt_after_selection_max_train_drawdown_pct=23.0,
        equity_soft_sizer_alt_after_selection_min_train_cost_drag_pct=25.0,
        equity_soft_sizer_alt_after_selection_max_train_cost_drag_pct=35.0,
        equity_soft_sizer_alt_after_selection_min_one_way_trim_per_add=0.30,
        equity_soft_sizer_alt_after_selection_max_one_way_trim_per_add=0.33,
        equity_soft_sizer_alt_after_selection_min_turnover_per_add=2.0,
        equity_soft_sizer_alt_after_selection_max_turnover_per_add=2.1,
    )
    alt_train = {
        "total_return_pct": 18.38,
        "max_drawdown_pct": 21.96,
        "estimated_cost_drag_pct": 28.58,
        "config": {"max_possible_units": 1.5},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.3125,
                "turnover_events_per_add": 2.04,
            }
        },
    }

    assert _equity_soft_sizer_after_selection_allowed(
        alt_train,
        alt_args,
        prefix="equity_soft_sizer_alt_after_selection",
    )
    deep_args = SimpleNamespace(
        equity_soft_sizer_deep_after_selection_min_source_max_units=1.0,
        equity_soft_sizer_deep_after_selection_max_source_max_units=1.0,
        equity_soft_sizer_deep_after_selection_min_train_return_pct=40.0,
        equity_soft_sizer_deep_after_selection_max_train_return_pct=45.0,
        equity_soft_sizer_deep_after_selection_min_train_drawdown_pct=30.0,
        equity_soft_sizer_deep_after_selection_max_train_drawdown_pct=33.0,
        equity_soft_sizer_deep_after_selection_min_train_cost_drag_pct=35.0,
        equity_soft_sizer_deep_after_selection_max_train_cost_drag_pct=40.0,
        equity_soft_sizer_deep_after_selection_min_one_way_trim_per_add=0.38,
        equity_soft_sizer_deep_after_selection_max_one_way_trim_per_add=0.42,
        equity_soft_sizer_deep_after_selection_min_turnover_per_add=2.10,
        equity_soft_sizer_deep_after_selection_max_turnover_per_add=2.17,
    )
    deep_train = {
        "total_return_pct": 43.7566,
        "max_drawdown_pct": 32.3797,
        "estimated_cost_drag_pct": 38.4444,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.4,
                "turnover_events_per_add": 2.1455,
            }
        },
    }

    assert _equity_soft_sizer_after_selection_allowed(
        deep_train,
        deep_args,
        prefix="equity_soft_sizer_deep_after_selection",
    )


def test_one_way_impulse_overlay_requires_targeted_low_order_train_state() -> None:
    args = SimpleNamespace(
        one_way_impulse_after_selection_min_source_max_units=1.5,
        one_way_impulse_after_selection_max_source_max_units=1.5,
        one_way_impulse_after_selection_min_train_return_pct=45.0,
        one_way_impulse_after_selection_max_train_return_pct=60.0,
        one_way_impulse_after_selection_min_train_drawdown_pct=22.0,
        one_way_impulse_after_selection_max_train_drawdown_pct=24.0,
        one_way_impulse_after_selection_min_train_cost_drag_pct=45.0,
        one_way_impulse_after_selection_max_train_cost_drag_pct=55.0,
        one_way_impulse_after_selection_min_one_way_trim_per_add=0.34,
        one_way_impulse_after_selection_max_one_way_trim_per_add=0.37,
        one_way_impulse_after_selection_min_turnover_per_add=2.15,
        one_way_impulse_after_selection_max_turnover_per_add=2.25,
    )
    target_train = {
        "total_return_pct": 51.79,
        "max_drawdown_pct": 22.84,
        "estimated_cost_drag_pct": 48.95,
        "config": {"max_possible_units": 1.5},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.356,
                "turnover_events_per_add": 2.203,
            }
        },
    }

    assert _one_way_impulse_after_selection_allowed(target_train, args)
    assert not _one_way_impulse_after_selection_allowed(
        {**target_train, "config": {"max_possible_units": 1.0}},
        args,
    )
    assert not _one_way_impulse_after_selection_allowed(
        {
            **target_train,
            "event_diagnostics": {
                "ratios": {
                    "one_way_forced_trim_per_add": 0.50,
                    "turnover_events_per_add": 2.203,
                }
            },
        },
        args,
    )


def test_one_way_impulse_micro_gate_targets_sparse_profitable_train_state() -> None:
    args = SimpleNamespace(
        one_way_impulse_micro_after_selection_min_source_max_units=1.0,
        one_way_impulse_micro_after_selection_max_source_max_units=1.0,
        one_way_impulse_micro_after_selection_min_train_return_pct=215.0,
        one_way_impulse_micro_after_selection_max_train_return_pct=222.0,
        one_way_impulse_micro_after_selection_min_train_drawdown_pct=15.0,
        one_way_impulse_micro_after_selection_max_train_drawdown_pct=15.2,
        one_way_impulse_micro_after_selection_min_train_cost_drag_pct=70.0,
        one_way_impulse_micro_after_selection_max_train_cost_drag_pct=75.0,
        one_way_impulse_micro_after_selection_min_one_way_trim_per_add=0.33,
        one_way_impulse_micro_after_selection_max_one_way_trim_per_add=0.35,
        one_way_impulse_micro_after_selection_min_turnover_per_add=2.22,
        one_way_impulse_micro_after_selection_max_turnover_per_add=2.25,
    )
    target_train = {
        "total_return_pct": 218.9651,
        "max_drawdown_pct": 15.0895,
        "estimated_cost_drag_pct": 72.5961,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.34,
                "turnover_events_per_add": 2.24,
            }
        },
    }

    assert _one_way_impulse_after_selection_allowed(
        target_train,
        args,
        prefix="one_way_impulse_micro_after_selection",
    )
    assert not _one_way_impulse_after_selection_allowed(
        {**target_train, "estimated_cost_drag_pct": 81.897},
        args,
        prefix="one_way_impulse_micro_after_selection",
    )
    assert not _one_way_impulse_after_selection_allowed(
        {
            **target_train,
            "event_diagnostics": {
                "ratios": {
                    "one_way_forced_trim_per_add": 0.3091,
                    "turnover_events_per_add": 2.4182,
                }
            },
        },
        args,
        prefix="one_way_impulse_micro_after_selection",
    )


def test_role_balance_impulse_targets_base_concentration_train_bands() -> None:
    args = SimpleNamespace(
        role_balance_impulse_after_selection_min_source_max_units=1.0,
        role_balance_impulse_after_selection_max_source_max_units=1.0,
        role_balance_impulse_after_selection_min_train_return_pct=70.0,
        role_balance_impulse_after_selection_max_train_return_pct=225.0,
        role_balance_impulse_after_selection_min_train_drawdown_pct=12.0,
        role_balance_impulse_after_selection_max_train_drawdown_pct=15.0,
        role_balance_impulse_after_selection_min_train_cost_drag_pct=30.0,
        role_balance_impulse_after_selection_max_train_cost_drag_pct=85.0,
        role_balance_impulse_after_selection_min_one_way_trim_per_add=0.30,
        role_balance_impulse_after_selection_max_one_way_trim_per_add=0.38,
        role_balance_impulse_after_selection_min_turnover_per_add=2.15,
        role_balance_impulse_after_selection_max_turnover_per_add=2.43,
        role_balance_impulse_after_selection_probe_units=0.0001,
        role_balance_impulse_after_selection_min_one_way_score=3.5,
        role_balance_impulse_after_selection_min_score_diff=5,
        role_balance_impulse_after_selection_cooldown_bars=48,
        role_balance_impulse_after_selection_max_extension_atr=2.75,
    )
    fold12_like_train = {
        "total_return_pct": 221.4787,
        "max_drawdown_pct": 14.6319,
        "estimated_cost_drag_pct": 81.897,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.3091,
                "turnover_events_per_add": 2.4182,
            }
        },
    }
    fold9_like_train = {
        "total_return_pct": 71.951,
        "max_drawdown_pct": 12.1462,
        "estimated_cost_drag_pct": 34.5525,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.3696,
                "turnover_events_per_add": 2.1522,
            }
        },
    }

    assert _one_way_impulse_after_selection_allowed(
        fold12_like_train,
        args,
        prefix="role_balance_impulse_after_selection",
    )
    assert _one_way_impulse_after_selection_allowed(
        fold9_like_train,
        args,
        prefix="role_balance_impulse_after_selection",
    )
    assert not _one_way_impulse_after_selection_allowed(
        {**fold9_like_train, "total_return_pct": 50.0},
        args,
        prefix="role_balance_impulse_after_selection",
    )

    tuned = _apply_one_way_impulse_after_selection_overlay(
        _ImpulseOnlyConfig(
            model_id="model",
            max_possible_units=1.0,
            one_way_impulse_probe_units=0.02,
            one_way_impulse_min_one_way_score=2.35,
            one_way_impulse_min_score_diff=3,
            one_way_impulse_cooldown_bars=48,
            one_way_impulse_max_extension_atr=2.75,
        ),
        args,
        prefix="role_balance_impulse_after_selection",
        suffix_label="wfRoleBalanceImpulse",
    )

    assert tuned.one_way_impulse_probe_units == 0.0001
    assert tuned.one_way_impulse_min_one_way_score == 3.5
    assert tuned.one_way_impulse_min_score_diff == 5
    assert tuned.model_id == (
        "model:wfRoleBalanceImpulse0.0001:"
        "wfRoleBalanceImpulseScore3.5:"
        "wfRoleBalanceImpulseDiff5:"
        "wfRoleBalanceImpulseCool48:"
        "wfRoleBalanceImpulseExt2.75"
    )


def test_train_state_overlay_requires_targeted_late_concentration_state() -> None:
    args = SimpleNamespace(
        near_miss_late_after_selection_min_source_max_units=1.0,
        near_miss_late_after_selection_max_source_max_units=1.0,
        near_miss_late_after_selection_min_train_return_pct=30.0,
        near_miss_late_after_selection_max_train_return_pct=35.0,
        near_miss_late_after_selection_min_train_drawdown_pct=16.0,
        near_miss_late_after_selection_max_train_drawdown_pct=18.0,
        near_miss_late_after_selection_min_train_cost_drag_pct=65.0,
        near_miss_late_after_selection_max_train_cost_drag_pct=70.0,
        near_miss_late_after_selection_min_one_way_trim_per_add=0.34,
        near_miss_late_after_selection_max_one_way_trim_per_add=0.36,
        near_miss_late_after_selection_min_turnover_per_add=2.65,
        near_miss_late_after_selection_max_turnover_per_add=2.70,
    )
    target_train = {
        "total_return_pct": 32.7867,
        "max_drawdown_pct": 17.0723,
        "estimated_cost_drag_pct": 68.0176,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.3492,
                "turnover_events_per_add": 2.6825,
            }
        },
    }

    assert _train_state_after_selection_allowed(
        target_train,
        args,
        prefix="near_miss_late_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {**target_train, "config": {"max_possible_units": 1.5}},
        args,
        prefix="near_miss_late_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {
            **target_train,
            "event_diagnostics": {
                "ratios": {
                    "one_way_forced_trim_per_add": 0.3492,
                    "turnover_events_per_add": 2.8,
                }
            },
        },
        args,
        prefix="near_miss_late_after_selection",
    )


def test_mid_near_miss_gate_targets_mid_return_one_way_rotation_state() -> None:
    args = SimpleNamespace(
        near_miss_mid_after_selection_min_source_max_units=1.5,
        near_miss_mid_after_selection_max_source_max_units=1.5,
        near_miss_mid_after_selection_min_train_return_pct=70.0,
        near_miss_mid_after_selection_max_train_return_pct=80.0,
        near_miss_mid_after_selection_min_train_drawdown_pct=19.0,
        near_miss_mid_after_selection_max_train_drawdown_pct=20.5,
        near_miss_mid_after_selection_min_train_cost_drag_pct=30.0,
        near_miss_mid_after_selection_max_train_cost_drag_pct=35.0,
        near_miss_mid_after_selection_min_one_way_trim_per_add=0.34,
        near_miss_mid_after_selection_max_one_way_trim_per_add=0.36,
        near_miss_mid_after_selection_min_turnover_per_add=2.15,
        near_miss_mid_after_selection_max_turnover_per_add=2.25,
    )
    target_train = {
        "total_return_pct": 75.4235,
        "max_drawdown_pct": 19.712,
        "estimated_cost_drag_pct": 33.1432,
        "config": {"max_possible_units": 1.5},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.35,
                "turnover_events_per_add": 2.2,
            }
        },
    }

    assert _train_state_after_selection_allowed(
        target_train,
        args,
        prefix="near_miss_mid_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {**target_train, "total_return_pct": 221.4787},
        args,
        prefix="near_miss_mid_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {
            **target_train,
            "event_diagnostics": {
                "ratios": {
                    "one_way_forced_trim_per_add": 0.31,
                    "turnover_events_per_add": 2.42,
                }
            },
        },
        args,
        prefix="near_miss_mid_after_selection",
    )


def test_near_miss_activity_gate_targets_low_activity_rotation_state() -> None:
    args = SimpleNamespace(
        near_miss_activity_after_selection_min_source_max_units=1.0,
        near_miss_activity_after_selection_max_source_max_units=1.0,
        near_miss_activity_after_selection_min_train_return_pct=40.0,
        near_miss_activity_after_selection_max_train_return_pct=45.0,
        near_miss_activity_after_selection_min_train_drawdown_pct=30.0,
        near_miss_activity_after_selection_max_train_drawdown_pct=33.0,
        near_miss_activity_after_selection_min_train_cost_drag_pct=35.0,
        near_miss_activity_after_selection_max_train_cost_drag_pct=40.0,
        near_miss_activity_after_selection_min_one_way_trim_per_add=0.38,
        near_miss_activity_after_selection_max_one_way_trim_per_add=0.42,
        near_miss_activity_after_selection_min_turnover_per_add=2.10,
        near_miss_activity_after_selection_max_turnover_per_add=2.17,
    )
    target_train = {
        "total_return_pct": 43.7566,
        "max_drawdown_pct": 32.3797,
        "estimated_cost_drag_pct": 38.4444,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.4,
                "turnover_events_per_add": 2.1455,
            }
        },
    }

    assert _train_state_after_selection_allowed(
        target_train,
        args,
        prefix="near_miss_activity_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {**target_train, "total_return_pct": 61.6222},
        args,
        prefix="near_miss_activity_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {
            **target_train,
            "event_diagnostics": {
                "ratios": {
                    "one_way_forced_trim_per_add": 0.551,
                    "turnover_events_per_add": 2.1837,
                }
            },
        },
        args,
        prefix="near_miss_activity_after_selection",
    )


def test_one_way_reversal_suppress_gate_targets_high_cost_flip_state() -> None:
    args = SimpleNamespace(
        one_way_reversal_suppress_after_selection_min_source_max_units=1.0,
        one_way_reversal_suppress_after_selection_max_source_max_units=1.5,
        one_way_reversal_suppress_after_selection_min_train_return_pct=18.0,
        one_way_reversal_suppress_after_selection_max_train_return_pct=225.0,
        one_way_reversal_suppress_after_selection_min_train_drawdown_pct=14.0,
        one_way_reversal_suppress_after_selection_max_train_drawdown_pct=15.5,
        one_way_reversal_suppress_after_selection_min_train_cost_drag_pct=19.0,
        one_way_reversal_suppress_after_selection_max_train_cost_drag_pct=85.0,
        one_way_reversal_suppress_after_selection_min_one_way_trim_per_add=0.30,
        one_way_reversal_suppress_after_selection_max_one_way_trim_per_add=0.45,
        one_way_reversal_suppress_after_selection_min_turnover_per_add=2.20,
        one_way_reversal_suppress_after_selection_max_turnover_per_add=2.57,
    )
    fold12_train = {
        "total_return_pct": 221.4787,
        "max_drawdown_pct": 14.6319,
        "estimated_cost_drag_pct": 81.897,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.3091,
                "turnover_events_per_add": 2.4182,
            }
        },
    }
    fold10_train = {
        "total_return_pct": 218.9651,
        "max_drawdown_pct": 15.0895,
        "estimated_cost_drag_pct": 72.5961,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.34,
                "turnover_events_per_add": 2.24,
            }
        },
    }
    fold14_train = {
        "total_return_pct": 19.2012,
        "max_drawdown_pct": 14.1031,
        "estimated_cost_drag_pct": 19.6133,
        "config": {"max_possible_units": 1.5},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.4386,
                "turnover_events_per_add": 2.5614,
            }
        },
    }

    assert _train_state_after_selection_allowed(
        fold12_train,
        args,
        prefix="one_way_reversal_suppress_after_selection",
    )
    assert _train_state_after_selection_allowed(
        fold10_train,
        args,
        prefix="one_way_reversal_suppress_after_selection",
    )
    assert _train_state_after_selection_allowed(
        fold14_train,
        args,
        prefix="one_way_reversal_suppress_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {**fold12_train, "total_return_pct": 240.3162},
        args,
        prefix="one_way_reversal_suppress_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {
            **fold12_train,
            "max_drawdown_pct": 20.5069,
            "event_diagnostics": {
                "ratios": {
                    "one_way_forced_trim_per_add": 0.375,
                    "turnover_events_per_add": 2.4531,
                }
            },
        },
        args,
        prefix="one_way_reversal_suppress_after_selection",
    )


def test_one_way_reversal_boost_gate_targets_high_return_rotation_state() -> None:
    args = SimpleNamespace(
        one_way_reversal_boost_after_selection_min_source_max_units=1.0,
        one_way_reversal_boost_after_selection_max_source_max_units=1.0,
        one_way_reversal_boost_after_selection_min_train_return_pct=160.0,
        one_way_reversal_boost_after_selection_max_train_return_pct=175.0,
        one_way_reversal_boost_after_selection_min_train_drawdown_pct=20.0,
        one_way_reversal_boost_after_selection_max_train_drawdown_pct=21.0,
        one_way_reversal_boost_after_selection_min_train_cost_drag_pct=60.0,
        one_way_reversal_boost_after_selection_max_train_cost_drag_pct=70.0,
        one_way_reversal_boost_after_selection_min_one_way_trim_per_add=0.37,
        one_way_reversal_boost_after_selection_max_one_way_trim_per_add=0.39,
        one_way_reversal_boost_after_selection_min_turnover_per_add=2.45,
        one_way_reversal_boost_after_selection_max_turnover_per_add=2.50,
    )
    target_train = {
        "total_return_pct": 167.6266,
        "max_drawdown_pct": 20.5069,
        "estimated_cost_drag_pct": 66.9586,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.3818,
                "turnover_events_per_add": 2.4727,
            }
        },
    }

    assert _train_state_after_selection_allowed(
        target_train,
        args,
        prefix="one_way_reversal_boost_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {**target_train, "estimated_cost_drag_pct": 81.897},
        args,
        prefix="one_way_reversal_boost_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {
            **target_train,
            "event_diagnostics": {
                "ratios": {
                    "one_way_forced_trim_per_add": 0.3091,
                    "turnover_events_per_add": 2.4182,
                }
            },
        },
        args,
        prefix="one_way_reversal_boost_after_selection",
    )


def test_one_way_reversal_fine_gate_targets_concentrated_momentum_state() -> None:
    args = SimpleNamespace(
        one_way_reversal_fine_after_selection_min_source_max_units=1.0,
        one_way_reversal_fine_after_selection_max_source_max_units=1.0,
        one_way_reversal_fine_after_selection_min_train_return_pct=45.0,
        one_way_reversal_fine_after_selection_max_train_return_pct=60.0,
        one_way_reversal_fine_after_selection_min_train_drawdown_pct=20.0,
        one_way_reversal_fine_after_selection_max_train_drawdown_pct=21.0,
        one_way_reversal_fine_after_selection_min_train_cost_drag_pct=40.0,
        one_way_reversal_fine_after_selection_max_train_cost_drag_pct=48.0,
        one_way_reversal_fine_after_selection_min_one_way_trim_per_add=0.36,
        one_way_reversal_fine_after_selection_max_one_way_trim_per_add=0.39,
        one_way_reversal_fine_after_selection_min_turnover_per_add=2.44,
        one_way_reversal_fine_after_selection_max_turnover_per_add=2.47,
    )
    target_train = {
        "total_return_pct": 51.606,
        "max_drawdown_pct": 20.5069,
        "estimated_cost_drag_pct": 43.885,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.375,
                "turnover_events_per_add": 2.4531,
            }
        },
    }

    assert _train_state_after_selection_allowed(
        target_train,
        args,
        prefix="one_way_reversal_fine_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {**target_train, "total_return_pct": 167.6266},
        args,
        prefix="one_way_reversal_fine_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {
            **target_train,
            "event_diagnostics": {
                "ratios": {
                    "one_way_forced_trim_per_add": 0.3818,
                    "turnover_events_per_add": 2.4727,
                }
            },
        },
        args,
        prefix="one_way_reversal_fine_after_selection",
    )


def test_base_reduce_suppress_gate_targets_over_defended_low_return_state() -> None:
    args = SimpleNamespace(
        base_reduce_suppress_after_selection_min_source_max_units=1.5,
        base_reduce_suppress_after_selection_max_source_max_units=1.5,
        base_reduce_suppress_after_selection_min_train_return_pct=20.0,
        base_reduce_suppress_after_selection_max_train_return_pct=21.0,
        base_reduce_suppress_after_selection_min_train_drawdown_pct=21.0,
        base_reduce_suppress_after_selection_max_train_drawdown_pct=22.0,
        base_reduce_suppress_after_selection_min_train_cost_drag_pct=13.0,
        base_reduce_suppress_after_selection_max_train_cost_drag_pct=15.0,
        base_reduce_suppress_after_selection_min_one_way_trim_per_add=0.54,
        base_reduce_suppress_after_selection_max_one_way_trim_per_add=0.55,
        base_reduce_suppress_after_selection_min_turnover_per_add=2.04,
        base_reduce_suppress_after_selection_max_turnover_per_add=2.05,
    )
    target_train = {
        "total_return_pct": 20.327,
        "max_drawdown_pct": 21.7254,
        "estimated_cost_drag_pct": 14.0317,
        "config": {"max_possible_units": 1.5},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.5455,
                "turnover_events_per_add": 2.0455,
            }
        },
    }

    assert _train_state_after_selection_allowed(
        target_train,
        args,
        prefix="base_reduce_suppress_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {**target_train, "total_return_pct": 38.6814},
        args,
        prefix="base_reduce_suppress_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {
            **target_train,
            "event_diagnostics": {
                "ratios": {
                    "one_way_forced_trim_per_add": 0.50,
                    "turnover_events_per_add": 2.3846,
                }
            },
        },
        args,
        prefix="base_reduce_suppress_after_selection",
    )


def test_high_state_overlays_share_precise_train_state_gate() -> None:
    args = SimpleNamespace(
        fragile_regime_entry_high_after_selection_min_source_max_units=1.0,
        fragile_regime_entry_high_after_selection_max_source_max_units=1.0,
        fragile_regime_entry_high_after_selection_min_train_return_pct=195.0,
        fragile_regime_entry_high_after_selection_max_train_return_pct=205.0,
        fragile_regime_entry_high_after_selection_min_train_drawdown_pct=15.0,
        fragile_regime_entry_high_after_selection_max_train_drawdown_pct=16.0,
        fragile_regime_entry_high_after_selection_min_train_cost_drag_pct=110.0,
        fragile_regime_entry_high_after_selection_max_train_cost_drag_pct=120.0,
        fragile_regime_entry_high_after_selection_min_one_way_trim_per_add=0.33,
        fragile_regime_entry_high_after_selection_max_one_way_trim_per_add=0.34,
        fragile_regime_entry_high_after_selection_min_turnover_per_add=2.45,
        fragile_regime_entry_high_after_selection_max_turnover_per_add=2.47,
    )
    target_train = {
        "total_return_pct": 199.7584,
        "max_drawdown_pct": 15.8478,
        "estimated_cost_drag_pct": 115.6986,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.3333,
                "turnover_events_per_add": 2.4583,
            }
        },
    }

    assert _train_state_after_selection_allowed(
        target_train,
        args,
        prefix="fragile_regime_entry_high_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {**target_train, "total_return_pct": 191.8095},
        args,
        prefix="fragile_regime_entry_high_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {**target_train, "estimated_cost_drag_pct": 124.5},
        args,
        prefix="fragile_regime_entry_high_after_selection",
    )


def test_fragile_low_overlay_requires_low_return_high_trim_state() -> None:
    args = SimpleNamespace(
        fragile_regime_entry_low_after_selection_min_source_max_units=1.5,
        fragile_regime_entry_low_after_selection_max_source_max_units=1.5,
        fragile_regime_entry_low_after_selection_min_train_return_pct=10.0,
        fragile_regime_entry_low_after_selection_max_train_return_pct=15.0,
        fragile_regime_entry_low_after_selection_min_train_drawdown_pct=23.0,
        fragile_regime_entry_low_after_selection_max_train_drawdown_pct=24.5,
        fragile_regime_entry_low_after_selection_min_train_cost_drag_pct=20.0,
        fragile_regime_entry_low_after_selection_max_train_cost_drag_pct=25.0,
        fragile_regime_entry_low_after_selection_min_one_way_trim_per_add=0.54,
        fragile_regime_entry_low_after_selection_max_one_way_trim_per_add=0.56,
        fragile_regime_entry_low_after_selection_min_turnover_per_add=2.03,
        fragile_regime_entry_low_after_selection_max_turnover_per_add=2.06,
    )
    target_train = {
        "total_return_pct": 12.091,
        "max_drawdown_pct": 23.6477,
        "estimated_cost_drag_pct": 22.2678,
        "config": {"max_possible_units": 1.5},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.5455,
                "turnover_events_per_add": 2.0455,
            }
        },
    }

    assert _train_state_after_selection_allowed(
        target_train,
        args,
        prefix="fragile_regime_entry_low_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {**target_train, "max_drawdown_pct": 21.0},
        args,
        prefix="fragile_regime_entry_low_after_selection",
    )
    assert not _train_state_after_selection_allowed(
        {
            **target_train,
            "event_diagnostics": {
                "ratios": {
                    "one_way_forced_trim_per_add": 0.45,
                    "turnover_events_per_add": 2.0455,
                }
            },
        },
        args,
        prefix="fragile_regime_entry_low_after_selection",
    )


def test_aggregate_folds_reports_flag_performance() -> None:
    aggregate = _aggregate_folds(
        [
            {
                "selected_model_id": "5m:market_state_rotation_v6:profile",
                "after_selection_overlays_applied": ["equity_circuit", "one_way_impulse"],
                "after_selection_overlays_skipped": [
                    "one_way_impulse_tail:train_confirm_rejected",
                    "near_miss",
                ],
                "after_selection_recent_oos_block": {
                    "mode": "enforce",
                    "enforced": True,
                    "blocked_overlays": ["one_way_impulse_tail"],
                    "details": {
                        "one_way_impulse_tail": {
                            "failed_checks": ["avg_return", "cost_to_return"],
                        }
                    },
                },
                "selected_train_result": {
                    "config": {
                        "model_id": "5m:market_state_rotation_v6:profile",
                        "max_hold_bars": 10,
                        "max_possible_units": 1.0,
                        "reaction_usd": 200.0,
                        "defensive_trim_cooldown_bars": 12960,
                    }
                },
                "test_result": {
                    "final_equity": 1.10,
                    "total_return_pct": 10.0,
                    "estimated_cost_drag_pct": 1.0,
                    "modeled_carry_cost_fraction_sum": 0.0,
                    "max_drawdown_pct": 3.0,
                    "config": {
                        "model_id": "5m:market_state_rotation_v6:profile:wfOverlay",
                        "max_hold_bars": 20,
                        "max_possible_units": 1.5,
                        "reaction_usd": 200.0,
                        "defensive_trim_cooldown_bars": 12,
                    },
                    "event_counts": {},
                    "trade_like_events": 4,
                    "battle_adds": 1,
                    "event_diagnostics": {
                        "health": "watch",
                        "flags": ["month_concentration"],
                        "add_events": 4,
                        "add_by_side": {"long": 3, "short": 1},
                        "add_by_role": {"base": 2, "probe": 2},
                    },
                    "regime_performance": {},
                },
            },
            {
                "selected_model_id": "5m:market_state_rotation_v6:profile",
                "after_selection_overlays_applied": ["equity_circuit"],
                "after_selection_overlays_skipped": ["one_way_impulse_tail"],
                "selected_train_result": {
                    "config": {
                        "model_id": "5m:market_state_rotation_v6:profile",
                        "max_hold_bars": 11,
                        "max_possible_units": 1.0,
                        "reaction_usd": 350.0,
                        "defensive_trim_cooldown_bars": 12960,
                    }
                },
                "test_result": {
                    "final_equity": 0.95,
                    "total_return_pct": -5.0,
                    "estimated_cost_drag_pct": 2.0,
                    "modeled_carry_cost_fraction_sum": 0.0,
                    "max_drawdown_pct": 7.0,
                    "config": {
                        "model_id": "5m:market_state_rotation_v6:profile",
                        "max_hold_bars": 11,
                        "max_possible_units": 1.0,
                        "reaction_usd": 350.0,
                        "defensive_trim_cooldown_bars": 12960,
                    },
                    "event_counts": {},
                    "trade_like_events": 2,
                    "battle_adds": 0,
                    "event_diagnostics": {
                        "health": "watch",
                        "flags": ["month_concentration", "too_few_orders"],
                        "add_events": 2,
                        "add_by_side": {"long": 1, "short": 1},
                        "add_by_role": {"base": 1, "chase": 1},
                    },
                    "regime_performance": {},
                },
            },
        ]
    )

    assert aggregate["test_flag_performance"]["month_concentration"] == {
        "fold_count": 2,
        "positive_fold_count": 1,
        "compounded_return_pct": 4.5,
        "avg_return_pct": 2.5,
        "min_return_pct": -5.0,
        "max_return_pct": 10.0,
        "max_drawdown_pct": 7.0,
        "avg_cost_drag_pct": 1.5,
    }
    assert aggregate["test_flag_performance"]["too_few_orders"]["compounded_return_pct"] == -5.0
    assert aggregate["unique_selected_model_count"] == 1
    assert aggregate["selected_hold_counts"] == {"11": 1, "20": 1}
    assert aggregate["selected_max_units_counts"] == {"1.0": 1, "1.5": 1}
    assert aggregate["selected_reaction_usd_counts"] == {"200.0": 1, "350.0": 1}
    assert aggregate["selected_defensive_cooldown_counts"] == {"12": 1, "12960": 1}
    assert aggregate["total_trade_like_events"] == 6
    assert aggregate["avg_trade_like_events"] == 3.0
    assert aggregate["min_trade_like_events"] == 2
    assert aggregate["max_trade_like_events"] == 4
    assert aggregate["total_battle_adds"] == 1
    assert aggregate["battle_add_share"] == 0.1667
    assert aggregate["battle_participation_fold_count"] == 1
    assert aggregate["test_add_by_side_counts"] == {"long": 4, "short": 2}
    assert aggregate["test_add_by_side_share"] == {"long": 0.6667, "short": 0.3333}
    assert aggregate["test_add_by_role_counts"] == {"base": 3, "chase": 1, "probe": 2}
    assert aggregate["test_add_by_role_share"] == {"base": 0.5, "chase": 0.1667, "probe": 0.3333}
    assert aggregate["test_add_distribution_diagnostics"] == {
        "directional_add_count": 6,
        "dominant_add_side": "long",
        "dominant_add_side_share": 0.6667,
        "side_skew": 0.3333,
        "known_add_role_count": 6,
        "dominant_add_role": "base",
        "dominant_add_role_share": 0.5,
    }
    assert aggregate["selected_reaction_usd_performance"]["200.0"]["compounded_return_pct"] == 10.0
    assert aggregate["selected_reaction_usd_performance"]["350.0"]["compounded_return_pct"] == -5.0
    assert aggregate["selected_reaction_usd_performance"]["350.0"]["risk_tag_counts"] == {
        "non_positive_return": 1,
        "low_return": 1,
        "cost_exceeds_return": 1,
        "test_flags": 1,
    }
    selected_shape = "profile=profile|maxU=1.5|react=200.0|hold=20|dCool=12"
    assert aggregate["selected_risk_shape_counts"][selected_shape] == 1
    assert aggregate["selected_risk_shape_performance"][selected_shape]["folds"] == [0]
    assert aggregate["after_selection_overlay_counts"] == {
        "equity_circuit": 2,
        "one_way_impulse": 1,
    }
    assert aggregate["after_selection_overlay_skipped_counts"] == {
        "near_miss": 1,
        "one_way_impulse_tail": 2,
    }
    assert aggregate["after_selection_overlay_skip_reason_counts"] == {
        "train_confirm_rejected": 1
    }
    assert aggregate["after_selection_overlay_count_distribution"] == {"1": 1, "2": 1}
    overlay_performance = aggregate["after_selection_overlay_oos_performance"]
    assert overlay_performance["equity_circuit"]["fold_count"] == 2
    assert overlay_performance["equity_circuit"]["positive_fold_count"] == 1
    assert overlay_performance["equity_circuit"]["compounded_return_pct"] == 4.5
    assert overlay_performance["equity_circuit"]["avg_return_pct"] == 2.5
    assert overlay_performance["equity_circuit"]["max_drawdown_pct"] == 7.0
    assert overlay_performance["equity_circuit"]["avg_cost_drag_pct"] == 1.5
    assert overlay_performance["equity_circuit"]["risk_tag_counts"][
        "non_positive_return"
    ] == 1
    assert overlay_performance["equity_circuit"]["risk_tag_counts"]["low_return"] == 1
    assert overlay_performance["equity_circuit"]["risk_tag_counts"]["test_flags"] == 2
    assert overlay_performance["one_way_impulse"]["fold_count"] == 1
    assert overlay_performance["one_way_impulse"]["compounded_return_pct"] == 10.0
    assert aggregate["after_selection_recent_oos_blocks"] == {
        "record_count": 1,
        "enforced_count": 1,
        "mode_counts": {"enforce": 1},
        "blocked_overlay_counts": {"one_way_impulse_tail": 1},
        "failed_check_counts": {"avg_return": 1, "cost_to_return": 1},
    }


def test_aggregate_folds_reports_after_selection_confirmation_diagnostics() -> None:
    aggregate = _aggregate_folds(
        [
            {
                "fold": 1,
                "selected_model_id": "5m:market_state_rotation_v6:profile",
                "after_selection_train_confirmation": {
                    "passed": True,
                    "would_reject": False,
                    "enforced": False,
                    "mode": "shadow",
                    "target_overlays": ["one_way_impulse"],
                    "failed_checks": [],
                    "return_delta_pct": -10.0,
                    "cost_delta_pct": -3.0,
                    "drawdown_delta_pct": 0.1,
                },
                "selected_train_result": {
                    "config": {
                        "model_id": "5m:market_state_rotation_v6:profile",
                        "max_hold_bars": 10,
                        "max_possible_units": 1.0,
                    }
                },
                "test_result": {
                    "final_equity": 1.05,
                    "total_return_pct": 5.0,
                    "estimated_cost_drag_pct": 1.0,
                    "modeled_carry_cost_fraction_sum": 0.0,
                    "max_drawdown_pct": 2.0,
                    "config": {
                        "model_id": "5m:market_state_rotation_v6:profile",
                        "max_hold_bars": 10,
                        "max_possible_units": 1.0,
                    },
                    "event_counts": {},
                    "event_diagnostics": {"health": "ok", "flags": []},
                    "regime_performance": {},
                },
            },
            {
                "fold": 2,
                "selected_model_id": "5m:market_state_rotation_v6:profile",
                "after_selection_train_confirmation": {
                    "passed": False,
                    "would_reject": True,
                    "enforced": False,
                    "mode": "shadow",
                    "target_overlays": ["one_way_impulse_tail"],
                    "failed_checks": ["cost_delta", "return_per_cost_delta"],
                    "return_delta_pct": -20.0,
                    "cost_delta_pct": 5.0,
                    "drawdown_delta_pct": 0.2,
                },
                "selected_train_result": {
                    "config": {
                        "model_id": "5m:market_state_rotation_v6:profile",
                        "max_hold_bars": 10,
                        "max_possible_units": 1.0,
                    }
                },
                "test_result": {
                    "final_equity": 1.07,
                    "total_return_pct": 7.0,
                    "estimated_cost_drag_pct": 2.0,
                    "modeled_carry_cost_fraction_sum": 0.0,
                    "max_drawdown_pct": 4.0,
                    "config": {
                        "model_id": "5m:market_state_rotation_v6:profile",
                        "max_hold_bars": 10,
                        "max_possible_units": 1.0,
                    },
                    "event_counts": {},
                    "event_diagnostics": {"health": "ok", "flags": []},
                    "regime_performance": {},
                },
            },
        ]
    )

    confirmation = aggregate["after_selection_confirmation"]
    assert confirmation["record_count"] == 2
    assert confirmation["passed_count"] == 1
    assert confirmation["would_reject_count"] == 1
    assert confirmation["enforced_count"] == 0
    assert confirmation["mode_counts"] == {"shadow": 2}
    assert confirmation["failed_check_counts"] == {
        "cost_delta": 1,
        "return_per_cost_delta": 1,
    }
    assert confirmation["target_diagnostics"]["one_way_impulse_tail"] == {
        "fold_count": 1,
        "passed_count": 0,
        "would_reject_count": 1,
        "enforced_count": 0,
        "cost_reducing_count": 0,
        "avg_return_delta_pct": -20.0,
        "avg_cost_delta_pct": 5.0,
        "avg_drawdown_delta_pct": 0.2,
        "failed_check_counts": {
            "cost_delta": 1,
            "return_per_cost_delta": 1,
        },
    }
    assert confirmation["oos_by_status"]["would_reject"]["compounded_return_pct"] == 7.0
    weak_folds = aggregate["weak_fold_diagnostics"]
    assert weak_folds["low_return_count"] == 0
    assert weak_folds["confirmation_warning_count"] == 1
    assert weak_folds["risk_tag_counts"] == {"confirmation_warning": 1}
    assert weak_folds["confirmation_warning_folds"][0]["fold"] == 2
    assert weak_folds["confirmation_warning_folds"][0]["confirmation"] == (
        "would_reject:one_way_impulse_tail"
    )


def test_aggregate_folds_reports_low_activity_root_causes() -> None:
    aggregate = _aggregate_folds(
        [
            {
                "fold": 6,
                "selected_model_id": "5m:market_state_rotation_v6:profile",
                "after_selection_overlays_applied": ["equity_circuit", "equity_soft_circuit"],
                "selected_train_result": {
                    "config": {
                        "model_id": "5m:market_state_rotation_v6:profile",
                        "max_hold_bars": 52,
                        "max_possible_units": 1.5,
                        "reaction_usd": 200.0,
                        "defensive_trim_cooldown_bars": 12960,
                    }
                },
                "test_result": {
                    "final_equity": 1.02,
                    "total_return_pct": 2.0,
                    "estimated_cost_drag_pct": 0.5,
                    "modeled_carry_cost_fraction_sum": 0.0,
                    "max_drawdown_pct": 1.0,
                    "trade_like_events": 2,
                    "config": {
                        "model_id": "5m:market_state_rotation_v6:profile",
                        "max_hold_bars": 52,
                        "max_possible_units": 1.5,
                        "reaction_usd": 200.0,
                        "defensive_trim_cooldown_bars": 12960,
                    },
                    "event_counts": {
                        "equity_soft_circuit_cooldown_bars": 700,
                        "no_trade_MC12_low_confluence": 100,
                        "no_trade_MC04_no_clear_first_touch": 80,
                    },
                    "event_diagnostics": {
                        "health": "watch",
                        "flags": ["too_few_orders"],
                        "diagnostic_thresholds": {"expected_add_events": 8},
                        "add_events": 2,
                        "add_by_side": {"long": 2},
                        "add_by_role": {"base": 1, "probe": 1},
                    },
                    "regime_performance": {"uptrend": {"bars": 1000}},
                },
            }
        ]
    )

    weak = aggregate["weak_fold_diagnostics"]
    activity = weak["lowest_activity_folds"][0]

    assert weak["low_activity_count"] == 1
    assert weak["soft_circuit_dominated_count"] == 1
    assert weak["top_no_trade_reason_counts"] == {
        "MC04_no_clear_first_touch": 80,
        "MC12_low_confluence": 100,
    }
    assert activity["trade_like_events"] == 2
    assert activity["expected_add_events"] == 8
    assert activity["add_event_coverage"] == 0.25
    assert activity["equity_soft_circuit_cooldown_share"] == 0.7


def test_aggregate_folds_uses_risk_off_adjusted_activity_threshold() -> None:
    aggregate = _aggregate_folds(
        [
            {
                "fold": 6,
                "selected_model_id": "5m:market_state_rotation_v6:profile",
                "after_selection_overlays_applied": ["equity_circuit", "equity_soft_circuit"],
                "test_result": {
                    "final_equity": 1.05,
                    "total_return_pct": 5.0,
                    "estimated_cost_drag_pct": 0.5,
                    "modeled_carry_cost_fraction_sum": 0.0,
                    "max_drawdown_pct": 1.0,
                    "trade_like_events": 3,
                    "event_counts": {
                        "equity_soft_circuit_cooldown_bars": 630,
                    },
                    "event_diagnostics": {
                        "health": "ok",
                        "flags": [],
                        "sample_mode": "risk_off_partial",
                        "diagnostic_thresholds": {
                            "expected_add_events": 12,
                            "risk_adjusted_expected_add_events": 3,
                        },
                        "add_events": 3,
                        "add_by_side": {"long": 3},
                        "add_by_role": {"base": 3},
                    },
                    "regime_performance": {"uptrend": {"bars": 1000}},
                },
            }
        ]
    )

    weak = aggregate["weak_fold_diagnostics"]
    fold = weak["lowest_return_folds"][0]

    assert weak["low_activity_count"] == 0
    assert weak["risk_tag_counts"] == {}
    assert fold["expected_add_events"] == 12
    assert fold["risk_adjusted_expected_add_events"] == 3
    assert fold["effective_expected_add_events"] == 3
    assert fold["effective_add_event_coverage"] == 1.0


def test_aggregate_folds_reports_base_dominance_root_cause() -> None:
    aggregate = _aggregate_folds(
        [
            {
                "fold": 7,
                "selected_model_id": "5m:market_state_rotation_v6:profile",
                "after_selection_overlays_applied": [],
                "selected_train_result": {
                    "config": {"model_id": "5m:market_state_rotation_v6:profile"}
                },
                "test_result": {
                    "final_equity": 1.06,
                    "total_return_pct": 6.0,
                    "estimated_cost_drag_pct": 1.0,
                    "modeled_carry_cost_fraction_sum": 0.0,
                    "max_drawdown_pct": 2.0,
                    "trade_like_events": 20,
                    "config": {"model_id": "5m:market_state_rotation_v6:profile"},
                    "event_counts": {},
                    "event_diagnostics": {
                        "health": "ok",
                        "flags": [],
                        "add_events": 20,
                        "add_by_side": {"long": 11, "short": 9},
                        "add_by_role": {"base": 18, "probe": 2},
                        "add_role_share": {"base": 0.9, "probe": 0.1},
                        "dominant_add_role": "base",
                        "max_role_add_share": 0.9,
                    },
                    "regime_performance": {},
                },
            }
        ]
    )

    weak = aggregate["weak_fold_diagnostics"]
    fold = weak["base_dominance_folds"][0]

    assert weak["base_dominance_count"] == 1
    assert weak["risk_tag_counts"] == {"base_dominance": 1}
    assert fold["fold"] == 7
    assert fold["base_add_share"] == 0.9
    assert fold["dominant_add_role"] == "base"


def test_aggregate_confirmation_uses_per_overlay_target_details() -> None:
    aggregate = _aggregate_folds(
        [
            {
                "fold": 1,
                "selected_model_id": "5m:market_state_rotation_v6:profile",
                "after_selection_train_confirmation": {
                    "passed": False,
                    "would_reject": True,
                    "enforced": False,
                    "mode": "enforce",
                    "ablation_mode": "per_overlay",
                    "target_overlays": ["base_reduce", "one_way_impulse_tail"],
                    "rejected_overlays": ["one_way_impulse_tail"],
                    "failed_checks": ["cost_to_return"],
                    "target_details": {
                        "base_reduce": {
                            "passed": True,
                            "failed_checks": [],
                            "return_delta_pct": 2.0,
                            "cost_delta_pct": 0.2,
                            "drawdown_delta_pct": -0.1,
                        },
                        "one_way_impulse_tail": {
                            "passed": False,
                            "failed_checks": ["cost_to_return"],
                            "return_delta_pct": 0.5,
                            "cost_delta_pct": 2.0,
                            "drawdown_delta_pct": 0.3,
                        },
                    },
                },
                "selected_train_result": {"config": {"model_id": "5m:market_state_rotation_v6:profile"}},
                "test_result": {
                    "final_equity": 1.04,
                    "total_return_pct": 4.0,
                    "estimated_cost_drag_pct": 1.0,
                    "modeled_carry_cost_fraction_sum": 0.0,
                    "max_drawdown_pct": 2.0,
                    "config": {"model_id": "5m:market_state_rotation_v6:profile"},
                    "event_counts": {},
                    "event_diagnostics": {"health": "ok", "flags": []},
                    "regime_performance": {},
                },
            }
        ]
    )

    targets = aggregate["after_selection_confirmation"]["target_diagnostics"]
    assert targets["base_reduce"]["passed_count"] == 1
    assert targets["base_reduce"]["would_reject_count"] == 0
    assert targets["one_way_impulse_tail"]["passed_count"] == 0
    assert targets["one_way_impulse_tail"]["would_reject_count"] == 1
    assert targets["one_way_impulse_tail"]["failed_check_counts"] == {"cost_to_return": 1}
    assert aggregate["weak_fold_diagnostics"]["confirmation_warning_folds"][0][
        "confirmation"
    ] == "would_reject:one_way_impulse_tail"


def test_write_markdown_renders_after_selection_confirmation_table(tmp_path) -> None:
    path = tmp_path / "walk_forward_v6.md"
    _write_markdown(
        {
            "created_at": "2026-05-31T00:00:00Z",
            "source_report": "source.json",
            "symbol": "BTCUSDT",
            "exec_interval": "5m",
            "train_days": 365,
            "test_days": 90,
            "step_days": 90,
            "source_top_n": 4,
            "candidate_count": 16,
            "fold_offset": 0,
            "fold_limit": 0,
            "config_overrides": {},
            "aggregate": {
                "fold_count": 1,
                "compounded_oos_return_pct": 7.0,
                "avg_oos_return_pct": 7.0,
                "min_oos_return_pct": 7.0,
                "max_oos_return_pct": 7.0,
                "max_fold_drawdown_pct": 4.0,
                "positive_fold_count": 1,
                "avg_oos_cost_drag_pct": 2.0,
                "max_oos_cost_drag_pct": 2.0,
                "avg_modeled_carry_cost_fraction_sum": 0.0,
                "selected_model_counts": {},
                "selected_profile_counts": {},
                "selected_hold_counts": {},
                "selected_max_units_counts": {},
                "selected_reaction_usd_counts": {"200.0": 1},
                "selected_defensive_cooldown_counts": {"12": 1},
                "selected_risk_shape_counts": {
                    "profile=profile|maxU=1.5|react=200.0|hold=20|dCool=12": 1
                },
                "selected_reaction_usd_performance": {
                    "200.0": {
                        "fold_count": 1,
                        "positive_fold_count": 1,
                        "compounded_return_pct": 7.0,
                        "avg_return_pct": 7.0,
                        "min_return_pct": 7.0,
                        "max_return_pct": 7.0,
                        "max_drawdown_pct": 4.0,
                        "avg_cost_drag_pct": 2.0,
                        "risk_tag_counts": {"confirmation_warning": 1},
                        "folds": [1],
                    }
                },
                "selected_risk_shape_performance": {
                    "profile=profile|maxU=1.5|react=200.0|hold=20|dCool=12": {
                        "fold_count": 1,
                        "positive_fold_count": 1,
                        "compounded_return_pct": 7.0,
                        "avg_return_pct": 7.0,
                        "min_return_pct": 7.0,
                        "max_return_pct": 7.0,
                        "max_drawdown_pct": 4.0,
                        "avg_cost_drag_pct": 2.0,
                        "risk_tag_counts": {"confirmation_warning": 1},
                        "folds": [1],
                    }
                },
                "test_health_counts": {},
                "test_flag_counts": {},
                "test_flag_performance": {},
                "test_event_counts": {},
                "test_regime_performance": {},
                "after_selection_confirmation": {
                    "record_count": 1,
                    "passed_count": 0,
                    "would_reject_count": 1,
                    "enforced_count": 0,
                    "mode_counts": {"shadow": 1},
                    "failed_check_counts": {"cost_delta": 1},
                    "target_diagnostics": {
                        "one_way_impulse_tail": {
                            "fold_count": 1,
                            "passed_count": 0,
                            "would_reject_count": 1,
                            "enforced_count": 0,
                            "cost_reducing_count": 0,
                            "avg_return_delta_pct": -20.0,
                            "avg_cost_delta_pct": 5.0,
                            "avg_drawdown_delta_pct": 0.2,
                            "failed_check_counts": {"cost_delta": 1},
                        }
                    },
                    "oos_by_status": {
                        "would_reject": {
                            "fold_count": 1,
                            "positive_fold_count": 1,
                            "compounded_return_pct": 7.0,
                            "avg_return_pct": 7.0,
                            "max_drawdown_pct": 4.0,
                            "avg_cost_drag_pct": 2.0,
                        }
                    },
                },
                "after_selection_recent_oos_blocks": {
                    "record_count": 1,
                    "enforced_count": 1,
                    "mode_counts": {"enforce": 1},
                    "blocked_overlay_counts": {"one_way_impulse_tail": 1},
                    "failed_check_counts": {"avg_return": 1},
                },
                "after_selection_overlay_oos_performance": {
                    "equity_circuit": {
                        "fold_count": 1,
                        "positive_fold_count": 1,
                        "compounded_return_pct": 7.0,
                        "avg_return_pct": 7.0,
                        "min_return_pct": 7.0,
                        "max_return_pct": 7.0,
                        "max_drawdown_pct": 4.0,
                        "avg_cost_drag_pct": 2.0,
                        "risk_tag_counts": {"confirmation_warning": 1},
                        "folds": [1],
                    },
                    "one_way_impulse_tail": {
                        "fold_count": 1,
                        "positive_fold_count": 1,
                        "compounded_return_pct": 7.0,
                        "avg_return_pct": 7.0,
                        "min_return_pct": 7.0,
                        "max_return_pct": 7.0,
                        "max_drawdown_pct": 4.0,
                        "avg_cost_drag_pct": 2.0,
                        "risk_tag_counts": {"confirmation_warning": 1},
                        "folds": [1],
                    },
                },
                "top_train_candidate_audit": {
                    "audited_fold_count": 1,
                    "avg_candidate_count": 2.0,
                    "selected_best_count": 0,
                    "missed_best_count": 1,
                    "missed_best_rate": 1.0,
                    "selected_best_with_test_flags_count": 0,
                    "missed_best_flag_improvement_count": 0,
                    "missed_best_higher_cost_count": 1,
                    "missed_best_higher_drawdown_count": 1,
                    "missed_best_higher_cost_or_drawdown_count": 1,
                    "missed_best_clean_improvement_count": 0,
                    "avg_return_regret_pct": 3.0,
                    "max_return_regret_pct": 3.0,
                    "selected_compounded_return_pct": 7.0,
                    "oracle_best_compounded_return_pct": 10.0,
                    "oracle_compounded_improvement_pct": 3.0,
                    "best_rank_counts": {"2": 1},
                    "highest_regret_folds": [
                        {
                            "fold": 1,
                            "test_start": "2026-01-01",
                            "test_end": "2026-04-01",
                            "return_regret_pct": 3.0,
                            "selected": {
                                "rank": 1,
                                "test_return_pct": 7.0,
                                "test_cost_drag_pct": 2.0,
                                "test_max_drawdown_pct": 4.0,
                                "test_trade_like_events": 6,
                                "after_selection_overlays_applied": ["equity_circuit"],
                                "test_flags": [],
                            },
                            "best": {
                                "rank": 2,
                                "test_return_pct": 10.0,
                                "test_cost_drag_pct": 3.0,
                                "test_max_drawdown_pct": 5.0,
                                "test_trade_like_events": 12,
                                "after_selection_overlays_applied": ["equity_circuit", "near_miss"],
                                "test_flags": ["too_few_orders"],
                            },
                            "flag_delta_vs_best": {
                                "selected_count": 0,
                                "best_count": 1,
                                "selected_only": [],
                                "best_only": ["too_few_orders"],
                            },
                        }
                    ],
                },
                "top_train_candidate_overlay_audit": {
                    "equity_circuit": {
                        "candidate_count": 2,
                        "fold_count": 1,
                        "selected_count": 1,
                        "best_count": 1,
                        "positive_candidate_count": 2,
                        "avg_train_score": 0.5,
                        "avg_train_return_pct": 9.0,
                        "avg_test_return_pct": 8.5,
                        "min_test_return_pct": 7.0,
                        "max_test_return_pct": 10.0,
                        "avg_test_cost_drag_pct": 2.5,
                        "max_test_drawdown_pct": 5.0,
                        "test_flag_counts": {"too_few_orders": 1},
                        "folds": [1],
                    },
                    "near_miss": {
                        "candidate_count": 1,
                        "fold_count": 1,
                        "selected_count": 0,
                        "best_count": 1,
                        "positive_candidate_count": 1,
                        "avg_train_score": 0.4,
                        "avg_train_return_pct": 8.0,
                        "avg_test_return_pct": 10.0,
                        "min_test_return_pct": 10.0,
                        "max_test_return_pct": 10.0,
                        "avg_test_cost_drag_pct": 3.0,
                        "max_test_drawdown_pct": 5.0,
                        "test_flag_counts": {"too_few_orders": 1},
                        "folds": [1],
                    },
                },
                "weak_fold_diagnostics": {
                    "low_return_threshold_pct": 5.0,
                    "high_drawdown_threshold_pct": 10.0,
                    "high_cost_threshold_pct": 20.0,
                    "high_overlay_count_threshold": 5,
                    "non_positive_return_count": 0,
                    "low_return_count": 0,
                    "high_drawdown_count": 0,
                    "high_cost_count": 0,
                    "high_overlay_count": 0,
                    "confirmation_warning_count": 1,
                    "lowest_return_folds": [
                        {
                            "fold": 1,
                            "test_start": "2026-01-01",
                            "test_end": "2026-04-01",
                            "return_pct": 7.0,
                            "max_drawdown_pct": 4.0,
                            "cost_drag_pct": 2.0,
                            "cost_to_return_ratio": 0.285714,
                            "overlay_count": 2,
                            "overlays": ["equity_circuit", "one_way_impulse_tail"],
                            "confirmation": "would_reject:one_way_impulse_tail",
                            "risk_tags": ["confirmation_warning"],
                            "flags": [],
                        }
                    ],
                    "highest_drawdown_folds": [],
                    "highest_cost_folds": [],
                    "highest_overlay_count_folds": [],
                    "confirmation_warning_folds": [
                        {
                            "fold": 1,
                            "test_start": "2026-01-01",
                            "test_end": "2026-04-01",
                            "return_pct": 7.0,
                            "max_drawdown_pct": 4.0,
                            "cost_drag_pct": 2.0,
                            "cost_to_return_ratio": 0.285714,
                            "overlay_count": 2,
                            "overlays": ["equity_circuit", "one_way_impulse_tail"],
                            "confirmation": "would_reject:one_way_impulse_tail",
                            "risk_tags": ["confirmation_warning"],
                            "flags": [],
                        }
                    ],
                },
            },
            "folds": [],
        },
        path,
    )

    text = path.read_text()
    assert "records=1, passed=0, would_reject=1, enforced=0" in text
    assert "- Unique selected models:" in text
    assert "- Selected model counts:" not in text
    assert "- Selected reaction USD counts: `{\"200.0\": 1}`" in text
    assert "| `one_way_impulse_tail` | 1 | 0 | 1 | 0 | 0 | -20.0 | 5.0 | 0.2 |" in text
    assert "| `would_reject` | 1 | 1 | 7.0 | 7.0 | 4.0 | 2.0 |" in text
    assert "## Recent OOS Overlay Blocks" in text
    assert "overlays={\"one_way_impulse_tail\": 1}" in text
    assert "## After-Selection Overlay OOS Performance" in text
    assert "| `equity_circuit` | 1 | 1 | 7.0 | 7.0 | 7.0/7.0 | 4.0 | 2.0 |" in text
    assert "## Selected Shape Performance" in text
    assert "| `200.0` | 1 | 1 | 7.0 | 7.0 | 7.0/7.0 | 4.0 | 2.0 |" in text
    assert (
        "| `profile=profile|maxU=1.5|react=200.0|hold=20|dCool=12` | 1 | 1 | 7.0 |"
        in text
    )
    assert "## Top-Train Candidate Audit" in text
    assert "audited=1, avg_candidates=2.0, selected_best=0, missed_best=1" in text
    assert "selected_best_with_flags=0, missed_best_flag_improvements=0" in text
    assert "missed_best_higher_cost=1, missed_best_higher_dd=1" in text
    assert "clean_missed_improvements=0" in text
    assert "| 1 | 2026-01-01 to 2026-04-01 | 7.0 | 10.0 | 3.0 | 2 | 2.0/3.0 | 4.0/5.0 | 6/12 | `equity_circuit,near_miss` | `selected_only=none; best_only=too_few_orders` |" in text
    assert "## Top-Train Candidate Overlay Audit" in text
    assert "| `near_miss` | 1 | 1 | 0 | 1 | 1 | 0.4 | 8.0 | 10.0 | 10.0/10.0 | 5.0 | 3.0 |" in text
    assert "## Weak Fold Diagnostics" in text
    assert "confirmation_warnings=1" in text
    assert "| 1 | 2026-01-01 to 2026-04-01 | 7.0 | 4.0 | 2.0 | 0.285714 | `confirmation_warning` |" in text
