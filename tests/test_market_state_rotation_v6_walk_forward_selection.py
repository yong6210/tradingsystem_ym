from dataclasses import dataclass
from types import SimpleNamespace
from datetime import UTC, datetime

import scripts.run_market_state_rotation_v6_walk_forward_validation as walk_forward_module
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
    _apply_exit_trend_hold_overlay,
    _apply_exposure_rebalance_overlay,
    _apply_high_cost_balance_overlay,
    _apply_hold_compression_overlay,
    _apply_one_way_impulse_after_selection_overlay,
    _apply_one_way_reversal_after_selection_overlay,
    _apply_repair_tune_overlay,
    _apply_reaction_tune_overlay,
    _apply_risk_off_micro_overlay,
    _apply_trim_cooldown_overlay,
    _apply_legacy_recipe_overlay,
    _aggregate_improvement_backlog_diagnostics,
    _equity_soft_sizer_after_selection_allowed,
    _exposure_rebalance_after_selection_allowed,
    _aggregate_top_train_candidate_audit,
    _fragile_regime_entry_after_selection_allowed,
    _fragile_regime_inventory_trim_after_selection_allowed,
    _legacy_after_selection_recipes,
    _legacy_recipe_blockers,
    _legacy_recipe_missing_required,
    _legacy_recipe_allowed,
    _inherit_source_replay_selection_policy,
    _inherit_source_replay_window_policy,
    _near_miss_after_selection_allowed,
    _one_way_impulse_after_selection_allowed,
    _one_way_reversal_after_selection_weak_allowed,
    _report_provenance,
    _regime_dependency_stats,
    _apply_deep_drawdown_reversal_rescue_guard,
    _apply_deep_soft_overlay_rescue_guard,
    _apply_high_cost_runner_rescue_guard,
    _apply_negative_train_distribution_rescue_guard,
    _risk_smoothing_after_selection_allowed,
    _apply_unresolved_stress_raw_leader_guard,
    _selection_score,
    _source_replay_diagnostics,
    _source_replay_lineage_guard,
    _source_replay_high_return_soft_sizer_relax_drawdown_pct,
    _inherit_source_replay_model_encoded_policy,
    _stabilize_source_replay_ratio_gates,
    _source_replay_selected_train_anchor,
    _source_replay_should_auto_warm_selection_state,
    _top_no_trade_reasons,
    _train_state_after_selection_allowed,
    _write_markdown,
    _battle_restore_after_selection_allowed,
    _configs_from_source,
    _configs_from_source_fold,
)


@dataclass(frozen=True)
class _HoldOnlyConfig:
    model_id: str
    max_hold_bars: int


@dataclass(frozen=True)
class _TinySourceConfig:
    model_id: str
    max_hold_bars: int


@dataclass(frozen=True)
class _ReactionOnlyConfig:
    model_id: str
    reaction_trim_trigger: float
    repair_cut: float
    repair_stop: float
    reaction_avg_band: float = 0.95


@dataclass(frozen=True)
class _SoftRecoveryOnlyConfig:
    model_id: str
    max_possible_units: float
    equity_soft_circuit_recovery_probe_units: float
    equity_soft_circuit_recovery_min_one_way_score: float
    equity_soft_circuit_recovery_min_score_diff: int
    equity_soft_circuit_recovery_max_extension_atr: float
    equity_soft_circuit_recovery_failure_guard_count: int = 0
    equity_soft_circuit_recovery_failure_guard_window_bars: int = 1440
    equity_soft_circuit_recovery_failure_cooldown_bars: int = 0


@dataclass(frozen=True)
class _ExposureRebalanceOnlyConfig:
    model_id: str
    max_possible_units: float
    base_max_units: float
    base_add_units: float
    battle_units: float


@dataclass(frozen=True)
class _SoftSizerOnlyConfig:
    model_id: str
    equity_soft_circuit_drawdown_pct: float
    equity_soft_circuit_size_mult: float
    equity_soft_circuit_cooldown_bars: int
    equity_soft_circuit_force_flat: bool
    equity_soft_circuit_inventory_trim_fraction: float = 0.0


@dataclass(frozen=True)
class _TrimCooldownOnlyConfig:
    model_id: str
    one_way_trim_cooldown_bars: int
    base_entry_reduce_extension_atr: float
    base_entry_reduce_size_mult: float
    base_entry_reduce_promote_reaction: float


@dataclass(frozen=True)
class _CostThrottleOnlyConfig:
    model_id: str
    one_way_trim_size_mult: float
    hard_time_exit_fraction: float
    hard_time_exit_cooldown_bars: int
    reaction_trim_size_mult: float
    reaction_trim_trend_hold_trigger_mult: float
    hard_time_exit_trend_defer_bars: int
    hard_time_exit_trend_defer_min_favorable_reaction: float
    trend_hold_min_trend_strength: float
    trend_hold_min_one_way_score: float


@dataclass(frozen=True)
class _ExitTrendHoldOnlyConfig:
    model_id: str
    reaction_trim_trend_hold_trigger_mult: float
    hard_time_exit_trend_defer_bars: int
    hard_time_exit_trend_defer_min_favorable_reaction: float
    trend_hold_min_trend_strength: float
    trend_hold_min_one_way_score: float


@dataclass(frozen=True)
class _HardTimeLossDeferOnlyConfig:
    model_id: str
    hard_time_loss_defer_bars: int
    hard_time_loss_defer_min_loss_usd: float
    hard_time_loss_defer_context_fragments: tuple[str, ...]


@dataclass(frozen=True)
class _EventRiskBaseOnlyConfig:
    model_id: str
    event_risk_base_reduce_size_mult: float
    event_risk_base_reduce_min_extension_atr: float
    event_risk_base_reduce_max_extension_atr: float
    event_risk_base_reduce_side: str
    event_risk_base_reduce_contexts: tuple[str, ...]


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


def test_configs_from_source_reads_walk_forward_fold_lineage(monkeypatch) -> None:
    monkeypatch.setattr(walk_forward_module, "MarketStateConfig", _TinySourceConfig)
    report = {
        "folds": [
            {
                "selected_train_result": {
                    "config": {"model_id": "selected-a", "max_hold_bars": 52}
                },
                "train_top_results": [
                    {"config": {"model_id": "top-duplicate-material", "max_hold_bars": 52}},
                    {"config": {"model_id": "top-b", "max_hold_bars": 53}},
                ],
                "test_result": {"config": {"model_id": "test-c", "max_hold_bars": 54}},
            },
            {
                "selected_train_result": {
                    "config": {"model_id": "selected-b", "max_hold_bars": 55}
                },
                "train_top_results": [
                    {"config": {"model_id": "top-d", "max_hold_bars": 56}},
                ],
            }
        ]
    }

    configs = _configs_from_source(report, top_n=3)

    assert [config.model_id for config in configs] == ["selected-a", "selected-b", "top-b"]

    configs_with_test_results = _configs_from_source(
        report,
        top_n=5,
        include_walk_forward_test_results=True,
    )

    assert [config.model_id for config in configs_with_test_results] == [
        "selected-a",
        "selected-b",
        "top-b",
        "top-d",
        "test-c",
    ]


def test_configs_from_source_fold_reads_matching_fold_lineage(monkeypatch) -> None:
    monkeypatch.setattr(walk_forward_module, "MarketStateConfig", _TinySourceConfig)
    report = {
        "folds": [
            {
                "fold": 1,
                "selected_train_result": {
                    "config": {"model_id": "selected-a", "max_hold_bars": 52}
                },
                "train_top_results": [
                    {"config": {"model_id": "top-a", "max_hold_bars": 53}},
                ],
            },
            {
                "fold": 12,
                "selected_train_result": {
                    "config": {"model_id": "selected-fold-12", "max_hold_bars": 54}
                },
                "train_top_results": [
                    {"config": {"model_id": "top-duplicate-material", "max_hold_bars": 54}},
                    {"config": {"model_id": "top-fold-12", "max_hold_bars": 55}},
                ],
                "test_result": {"config": {"model_id": "test-fold-12", "max_hold_bars": 56}},
            },
        ]
    }

    configs = _configs_from_source_fold(report, fold=12, top_n=3)

    assert [config.model_id for config in configs] == [
        "selected-fold-12",
        "top-fold-12",
    ]

    configs_with_test_results = _configs_from_source_fold(
        report,
        fold=12,
        top_n=3,
        include_walk_forward_test_results=True,
    )

    assert [config.model_id for config in configs_with_test_results] == [
        "selected-fold-12",
        "top-fold-12",
        "test-fold-12",
    ]


def test_source_replay_selected_train_anchor_prefers_source_fold_candidate(monkeypatch) -> None:
    monkeypatch.setattr(walk_forward_module, "MarketStateConfig", _TinySourceConfig)
    source_report = {
        "folds": [
            {
                "fold": 12,
                "selected_train_result": {
                    "model_id": "source-selected",
                    "config": {"model_id": "source-selected", "max_hold_bars": 54},
                },
            }
        ]
    }
    selected_train = {
        "model_id": "score-leader",
        "walk_forward_selection_score": 3.0,
        "config": {"model_id": "score-leader", "max_hold_bars": 55},
    }
    source_candidate = {
        "model_id": "source-selected-replayed",
        "walk_forward_selection_score": 2.8,
        "config": {"model_id": "source-selected-replayed", "max_hold_bars": 54},
    }

    anchored, detail = _source_replay_selected_train_anchor(
        source_report,
        fold=12,
        train_results=[selected_train, source_candidate],
        selected_train=selected_train,
        enabled=True,
    )

    assert anchored is source_candidate
    assert detail["applied"] is True
    assert detail["reason"] == "source_selected_train_matched"
    assert detail["selected_model_id_before_anchor"] == "score-leader"
    assert detail["selected_model_id_after_anchor"] == "source-selected-replayed"


def test_source_replay_selected_train_anchor_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setattr(walk_forward_module, "MarketStateConfig", _TinySourceConfig)
    selected_train = {
        "model_id": "score-leader",
        "config": {"model_id": "score-leader", "max_hold_bars": 55},
    }

    anchored, detail = _source_replay_selected_train_anchor(
        {
            "folds": [
                {
                    "fold": 12,
                    "selected_train_result": {
                        "config": {"model_id": "source-selected", "max_hold_bars": 54},
                    },
                }
            ]
        },
        fold=12,
        train_results=[],
        selected_train=selected_train,
        enabled=False,
    )

    assert anchored is selected_train
    assert detail == {"enabled": False, "applied": False, "reason": "disabled"}


def test_source_replay_inherits_selection_policy_when_cli_is_default() -> None:
    args = SimpleNamespace(
        selection_low_unit_reversal_bonus=0.0,
        include_no_impulse_candidates=False,
        one_way_impulse_probe_units=None,
        _parser_defaults={
            "selection_low_unit_reversal_bonus": 0.0,
            "include_no_impulse_candidates": False,
            "one_way_impulse_probe_units": None,
        },
        _provided_cli_dests=set(),
    )

    inherited = _inherit_source_replay_selection_policy(
        args,
        {
            "selection_low_unit_reversal_bonus": 0.34,
            "include_no_impulse_candidates": True,
            "one_way_impulse_probe_units": 0.02,
        },
    )

    assert inherited == [
        "include_no_impulse_candidates",
        "one_way_impulse_probe_units",
        "selection_low_unit_reversal_bonus",
    ]
    assert args.selection_low_unit_reversal_bonus == 0.34
    assert args.include_no_impulse_candidates is True
    assert args.one_way_impulse_probe_units == 0.02


def test_source_replay_clamps_old_near_miss_min_train_return_when_cli_is_default() -> None:
    args = SimpleNamespace(
        near_miss_after_selection_min_train_return_pct=0.0,
        _parser_defaults={"near_miss_after_selection_min_train_return_pct": 0.0},
        _provided_cli_dests=set(),
    )

    inherited = _inherit_source_replay_selection_policy(
        args,
        {"near_miss_after_selection_min_train_return_pct": -10.0},
    )

    assert inherited == ["near_miss_after_selection_min_train_return_pct"]
    assert args.near_miss_after_selection_min_train_return_pct == 0.0
    assert args._source_replay_clamped_selection_policy_fields == [
        "near_miss_after_selection_min_train_return_pct"
    ]


def test_source_replay_does_not_override_explicit_cli_selection_policy() -> None:
    args = SimpleNamespace(
        selection_low_unit_reversal_bonus=0.0,
        _parser_defaults={"selection_low_unit_reversal_bonus": 0.0},
        _provided_cli_dests={"selection_low_unit_reversal_bonus"},
    )

    inherited = _inherit_source_replay_selection_policy(
        args,
        {"selection_low_unit_reversal_bonus": 0.34},
    )

    assert inherited == []
    assert args.selection_low_unit_reversal_bonus == 0.0


def test_source_replay_keeps_enforce_confirmation_mode_when_cli_sets_confirmation_gate() -> None:
    args = SimpleNamespace(
        after_selection_train_confirmation=True,
        after_selection_confirmation_mode="enforce",
        after_selection_confirm_max_cost_delta_pct=3.0,
        after_selection_confirm_overlays="high_return_soft_sizer_relax",
        _parser_defaults={
            "after_selection_train_confirmation": False,
            "after_selection_confirmation_mode": "enforce",
            "after_selection_confirm_max_cost_delta_pct": None,
            "after_selection_confirm_overlays": "",
        },
        _provided_cli_dests={
            "after_selection_train_confirmation",
            "after_selection_confirm_max_cost_delta_pct",
            "after_selection_confirm_overlays",
        },
    )

    inherited = _inherit_source_replay_selection_policy(
        args,
        {
            "after_selection_confirmation_mode": "shadow",
            "selection_low_unit_reversal_bonus": 0.34,
        },
    )

    assert inherited == []
    assert args.after_selection_confirmation_mode == "enforce"


def test_source_replay_inherits_legacy_recipe_notes_when_default_missing() -> None:
    args = SimpleNamespace(
        role_balance_impulse_micro_replay_note=None,
        _parser_defaults={"role_balance_impulse_micro_replay_note": None},
        _provided_cli_dests=set(),
    )

    inherited = _inherit_source_replay_selection_policy(
        args,
        {"role_balance_impulse_micro_replay_note": "enabled by source replay"},
    )

    assert inherited == ["role_balance_impulse_micro_replay_note"]
    assert args.role_balance_impulse_micro_replay_note == "enabled by source replay"


def test_source_replay_inherits_window_policy_when_cli_is_default() -> None:
    args = SimpleNamespace(
        load_days=1825,
        train_days=365,
        test_days=90,
        step_days=90,
        fold_anchor_hour_utc=None,
        fold_anchor_minute_utc=0,
        _parser_defaults={
            "load_days": 1825,
            "train_days": 365,
            "test_days": 90,
            "step_days": 90,
            "fold_anchor_hour_utc": None,
            "fold_anchor_minute_utc": 0,
        },
        _provided_cli_dests=set(),
    )

    inherited = _inherit_source_replay_window_policy(
        args,
        {
            "load_days": 1826,
            "train_days": 364,
            "test_days": 91,
            "step_days": 89,
            "fold_anchor_hour_utc": 7,
            "fold_anchor_minute_utc": 5,
        },
    )

    assert inherited == [
        "load_days",
        "train_days",
        "test_days",
        "step_days",
        "fold_anchor_hour_utc",
        "fold_anchor_minute_utc",
    ]
    assert args.load_days == 1826
    assert args.train_days == 364
    assert args.test_days == 91
    assert args.step_days == 89
    assert args.fold_anchor_hour_utc == 7
    assert args.fold_anchor_minute_utc == 5


def test_source_replay_inherits_first_fold_start_when_top_level_missing() -> None:
    args = SimpleNamespace(
        fold_start_at="",
        _parser_defaults={"fold_start_at": ""},
        _provided_cli_dests=set(),
    )

    inherited = _inherit_source_replay_window_policy(
        args,
        {"folds": [{"train_start_at": "2021-06-02T07:00:00+00:00"}]},
    )

    assert inherited == ["fold_start_at"]
    assert args.fold_start_at == "2021-06-02T07:00:00+00:00"


def test_source_replay_window_policy_preserves_explicit_or_non_default_values() -> None:
    args = SimpleNamespace(
        load_days=1825,
        train_days=400,
        test_days=90,
        _parser_defaults={
            "load_days": 1825,
            "train_days": 365,
            "test_days": 90,
        },
        _provided_cli_dests={"test_days"},
    )

    inherited = _inherit_source_replay_window_policy(
        args,
        {
            "load_days": 1826,
            "train_days": 364,
            "test_days": 91,
        },
    )

    assert inherited == ["load_days"]
    assert args.load_days == 1826
    assert args.train_days == 400
    assert args.test_days == 90


def test_source_replay_inherits_after_selection_overlay_policy() -> None:
    args = SimpleNamespace(
        repair_tune_after_selection=False,
        repair_tune_after_selection_repair_cut=None,
        _parser_defaults={
            "repair_tune_after_selection": False,
            "repair_tune_after_selection_repair_cut": None,
        },
        _provided_cli_dests=set(),
    )

    inherited = _inherit_source_replay_selection_policy(
        args,
        {
            "repair_tune_after_selection": True,
            "repair_tune_after_selection_repair_cut": 0.7,
        },
    )

    assert inherited == [
        "repair_tune_after_selection",
        "repair_tune_after_selection_repair_cut",
    ]
    assert args.repair_tune_after_selection is True
    assert args.repair_tune_after_selection_repair_cut == 0.7


def test_source_replay_stabilizes_only_inherited_ratio_gates() -> None:
    args = SimpleNamespace(
        repair_tune_after_selection_min_turnover_per_add=2.40,
        repair_tune_after_selection_max_turnover_per_add=2.47,
        repair_tune_after_selection_min_one_way_trim_per_add=0.30,
        repair_tune_after_selection_max_one_way_trim_per_add=0.39,
        repair_tune_after_selection_min_train_return_pct=45.0,
        role_balance_impulse_micro_replay_note="enabled",
        _provided_cli_dests={"repair_tune_after_selection_max_turnover_per_add"},
    )

    adjusted = _stabilize_source_replay_ratio_gates(
        args,
        [
            "repair_tune_after_selection_min_turnover_per_add",
            "repair_tune_after_selection_max_turnover_per_add",
            "repair_tune_after_selection_min_one_way_trim_per_add",
            "repair_tune_after_selection_max_one_way_trim_per_add",
            "repair_tune_after_selection_min_train_return_pct",
            "role_balance_impulse_micro_replay_note",
        ],
    )

    assert adjusted == [
        "repair_tune_after_selection_min_one_way_trim_per_add",
        "repair_tune_after_selection_min_turnover_per_add",
    ]
    assert args.repair_tune_after_selection_min_turnover_per_add == 2.39
    assert args.repair_tune_after_selection_max_turnover_per_add == 2.47
    assert args.repair_tune_after_selection_min_one_way_trim_per_add == 0.29
    assert args.repair_tune_after_selection_max_one_way_trim_per_add == 0.39
    assert args.repair_tune_after_selection_min_train_return_pct == 45.0


def test_source_replay_does_not_restabilize_already_stabilized_report() -> None:
    args = SimpleNamespace(
        repair_tune_after_selection_min_turnover_per_add=2.40,
        repair_tune_after_selection_min_one_way_trim_per_add=0.30,
        _provided_cli_dests=set(),
    )

    adjusted = _stabilize_source_replay_ratio_gates(
        args,
        [
            "repair_tune_after_selection_min_turnover_per_add",
            "repair_tune_after_selection_min_one_way_trim_per_add",
        ],
        source_report={
            "source_replay_stabilized_ratio_gate_fields": [
                "repair_tune_after_selection_min_turnover_per_add"
            ]
        },
    )

    assert adjusted == []
    assert args.repair_tune_after_selection_min_turnover_per_add == 2.40
    assert args.repair_tune_after_selection_min_one_way_trim_per_add == 0.30

    args_empty = SimpleNamespace(
        repair_tune_after_selection_min_turnover_per_add=2.40,
        repair_tune_after_selection_min_one_way_trim_per_add=0.30,
        _provided_cli_dests=set(),
    )

    adjusted_empty = _stabilize_source_replay_ratio_gates(
        args_empty,
        [
            "repair_tune_after_selection_min_turnover_per_add",
            "repair_tune_after_selection_min_one_way_trim_per_add",
        ],
        source_report={"source_replay_stabilized_ratio_gate_fields": []},
    )

    assert adjusted_empty == []
    assert args_empty.repair_tune_after_selection_min_turnover_per_add == 2.40
    assert args_empty.repair_tune_after_selection_min_one_way_trim_per_add == 0.30


def test_source_replay_auto_warms_when_recent_efficiency_policy_is_inherited() -> None:
    args = SimpleNamespace(
        warm_fold_offset_selection_state=False,
        disable_source_replay_auto_warm_selection_state=False,
        selection_recent_efficiency_lookback=2,
        selection_recent_efficiency_penalty=0.45,
    )

    should_warm = _source_replay_should_auto_warm_selection_state(
        args,
        inherited_fields=["selection_recent_efficiency_penalty"],
        fold_offset=11,
    )

    assert should_warm is True


def test_source_replay_auto_warm_respects_explicit_disable() -> None:
    args = SimpleNamespace(
        warm_fold_offset_selection_state=False,
        disable_source_replay_auto_warm_selection_state=True,
        selection_recent_efficiency_lookback=2,
        selection_recent_efficiency_penalty=0.45,
    )

    should_warm = _source_replay_should_auto_warm_selection_state(
        args,
        inherited_fields=["selection_recent_efficiency_penalty"],
        fold_offset=11,
    )

    assert should_warm is False


def test_source_replay_reads_model_encoded_high_return_relax_drawdown() -> None:
    report = {
        "folds": [
            {
                "fold": 9,
                "selected_model_id": "base:wfEqSoftRelax12M025:wfRoleBorderImpulse0.00005",
                "after_selection_overlays_applied": [
                    "equity_soft_sizer",
                    "high_return_soft_sizer_relax",
                ],
            },
            {
                "fold": 10,
                "selected_model_id": "base:wfEqSoftRelax11M025",
                "after_selection_overlays_applied": ["equity_soft_sizer"],
            },
        ]
    }

    assert _source_replay_high_return_soft_sizer_relax_drawdown_pct(report) == 12.0


def test_source_replay_inherits_model_encoded_policy_when_cli_is_default() -> None:
    args = SimpleNamespace(
        high_return_soft_sizer_relax_drawdown_pct=11.0,
        _parser_defaults={"high_return_soft_sizer_relax_drawdown_pct": 11.0},
        _provided_cli_dests=set(),
    )
    report = {
        "folds": [
            {
                "fold": 9,
                "selected_model_id": "base:wfEqSoftRelax12M025",
                "after_selection_overlays_applied": ["high_return_soft_sizer_relax"],
            }
        ]
    }

    inherited = _inherit_source_replay_model_encoded_policy(args, report)

    assert inherited == ["high_return_soft_sizer_relax_drawdown_pct"]
    assert args.high_return_soft_sizer_relax_drawdown_pct == 12.0


def test_source_replay_model_encoded_policy_respects_explicit_cli() -> None:
    args = SimpleNamespace(
        high_return_soft_sizer_relax_drawdown_pct=11.0,
        _parser_defaults={"high_return_soft_sizer_relax_drawdown_pct": 11.0},
        _provided_cli_dests={"high_return_soft_sizer_relax_drawdown_pct"},
    )
    report = {
        "folds": [
            {
                "fold": 9,
                "selected_model_id": "base:wfEqSoftRelax12M025",
                "after_selection_overlays_applied": ["high_return_soft_sizer_relax"],
            }
        ]
    }

    inherited = _inherit_source_replay_model_encoded_policy(args, report)

    assert inherited == []
    assert args.high_return_soft_sizer_relax_drawdown_pct == 11.0


def test_source_replay_diagnostics_reports_metric_model_and_overlay_drift() -> None:
    source_report = {
        "folds": [
            {
                "fold": 1,
                "selected_model_id": "source-a",
                "after_selection_overlays_applied": ["equity_circuit"],
                "test_result": {
                    "total_return_pct": 12.0,
                    "max_drawdown_pct": 4.0,
                    "estimated_cost_drag_pct": 1.0,
                    "trade_like_events": 5,
                },
            },
            {
                "fold": 2,
                "selected_model_id": "same-b",
                "after_selection_overlays_applied": ["repair_tune"],
                "test_result": {
                    "total_return_pct": 8.0,
                    "max_drawdown_pct": 3.0,
                    "estimated_cost_drag_pct": 0.5,
                    "trade_like_events": 3,
                },
            },
        ]
    }
    folds = [
        {
            "fold": 1,
            "selected_model_id": "replay-a",
            "after_selection_overlays_applied": ["equity_circuit", "repair_tune"],
            "test_result": {
                "total_return_pct": 10.0,
                "max_drawdown_pct": 3.5,
                "estimated_cost_drag_pct": 0.6,
                "trade_like_events": 4,
            },
        },
        {
            "fold": 2,
            "selected_model_id": "same-b",
            "after_selection_overlays_applied": ["repair_tune"],
            "test_result": {
                "total_return_pct": 8.0,
                "max_drawdown_pct": 3.0,
                "estimated_cost_drag_pct": 0.5,
                "trade_like_events": 3,
            },
        },
        {
            "fold": 3,
            "selected_model_id": "missing-source",
            "after_selection_overlays_applied": [],
            "test_result": {"total_return_pct": 1.0},
        },
    ]

    diagnostics = _source_replay_diagnostics(source_report, folds)

    assert diagnostics["compared_fold_count"] == 2
    assert diagnostics["missing_source_fold_count"] == 1
    assert diagnostics["missing_source_folds"] == [3]
    assert diagnostics["selected_model_mismatch_count"] == 1
    assert diagnostics["selected_model_immaterial_mismatch_count"] == 0
    assert diagnostics["selected_model_accepted_risk_tradeoff_count"] == 0
    assert diagnostics["selected_model_beneficial_mismatch_count"] == 0
    assert diagnostics["selected_model_unresolved_mismatch_count"] == 1
    assert diagnostics["overlay_mismatch_count"] == 1
    assert diagnostics["metric_mismatch_count"] == 1
    assert diagnostics["material_metric_mismatch_count"] == 1
    assert diagnostics["accepted_risk_tradeoff_count"] == 0
    assert diagnostics["unresolved_material_metric_mismatch_count"] == 1
    assert diagnostics["avg_return_delta_pct"] == -1.0
    assert diagnostics["avg_drawdown_delta_pct"] == -0.25
    assert diagnostics["avg_cost_delta_pct"] == -0.2
    assert diagnostics["total_trade_like_events_delta"] == -1
    assert diagnostics["mismatch_reason_counts"] == {
        "cost": 1,
        "drawdown": 1,
        "model_id": 1,
        "overlays": 1,
        "return": 1,
        "trade_like_events": 1,
    }
    assert diagnostics["lineage_status_counts"] == {
        "matched_or_immaterial": 1,
        "unresolved_material_drift": 1,
    }
    assert diagnostics["model_mismatch_status_counts"] == {"unresolved_material_drift": 1}
    assert diagnostics["largest_return_drift_folds"][0]["fold"] == 1
    assert diagnostics["folds"][0]["material_mismatch_reasons"] == [
        "return",
        "drawdown",
        "cost",
    ]
    assert diagnostics["folds"][0]["accepted_risk_tradeoff"] is False
    assert diagnostics["folds"][0]["drift_quality"] == "return_worsening"
    assert diagnostics["folds"][0]["lineage_status"] == "unresolved_material_drift"
    assert diagnostics["unresolved_model_mismatch_folds"][0]["fold"] == 1
    guard = _source_replay_lineage_guard(
        diagnostics,
        fail_on_unresolved_material=True,
    )
    assert guard["status"] == "fail"
    assert guard["failed"] is True
    assert guard["unresolved_material_folds"] == [1]


def test_source_replay_lineage_guard_tracks_watch_strict_and_clean_states() -> None:
    diagnostics = {
        "compared_fold_count": 3,
        "unresolved_material_metric_mismatch_count": 1,
        "selected_model_unresolved_mismatch_count": 1,
        "unresolved_material_mismatch_folds": [{"fold": 5}],
    }

    watch = _source_replay_lineage_guard(
        diagnostics,
        fail_on_unresolved_material=False,
    )
    strict = _source_replay_lineage_guard(
        diagnostics,
        fail_on_unresolved_material=True,
    )
    clean = _source_replay_lineage_guard(
        {
            "compared_fold_count": 3,
            "unresolved_material_metric_mismatch_count": 0,
            "selected_model_unresolved_mismatch_count": 0,
            "unresolved_material_mismatch_folds": [],
        },
        fail_on_unresolved_material=True,
    )

    assert watch["status"] == "watch"
    assert watch["failed"] is False
    assert strict["status"] == "fail"
    assert strict["failed"] is True
    assert strict["unresolved_material_folds"] == [5]
    assert clean["status"] == "pass"
    assert clean["failed"] is False


def test_source_replay_diagnostics_accepts_small_return_loss_for_large_drawdown_improvement() -> None:
    source_report = {
        "folds": [
            {
                "fold": 3,
                "selected_model_id": "source",
                "after_selection_overlays_applied": ["trim_cooldown_deep_soft"],
                "test_result": {
                    "total_return_pct": 26.156,
                    "max_drawdown_pct": 10.0209,
                    "estimated_cost_drag_pct": 2.6887,
                    "trade_like_events": 19,
                },
            }
        ]
    }
    folds = [
        {
            "fold": 3,
            "selected_model_id": "replay",
            "after_selection_overlays_applied": [
                "trim_cooldown_deep_soft",
                "deep_soft_reaction_delay",
            ],
            "test_result": {
                "total_return_pct": 25.9624,
                "max_drawdown_pct": 7.5884,
                "estimated_cost_drag_pct": 3.3615,
                "trade_like_events": 20,
            },
        }
    ]

    diagnostics = _source_replay_diagnostics(source_report, folds)

    assert diagnostics["material_metric_mismatch_count"] == 1
    assert diagnostics["accepted_risk_tradeoff_count"] == 1
    assert diagnostics["unresolved_material_metric_mismatch_count"] == 0
    assert diagnostics["selected_model_accepted_risk_tradeoff_count"] == 1
    assert diagnostics["selected_model_unresolved_mismatch_count"] == 0
    assert diagnostics["drift_quality_counts"] == {"accepted_risk_reduction": 1}
    assert diagnostics["model_mismatch_status_counts"] == {"accepted_risk_reduction": 1}
    accepted = diagnostics["accepted_risk_tradeoff_folds"][0]
    assert accepted["fold"] == 3
    assert accepted["accepted_risk_tradeoff"] is True
    assert accepted["drift_quality"] == "accepted_risk_reduction"
    assert accepted["lineage_status"] == "accepted_risk_reduction"
    assert diagnostics["unresolved_material_mismatch_folds"] == []
    assert diagnostics["accepted_model_mismatch_folds"][0]["fold"] == 3


def test_source_replay_diagnostics_accepts_targeted_stress_floor_repair() -> None:
    source_report = {
        "folds": [
            {
                "fold": 12,
                "selected_model_id": "source-low-return",
                "after_selection_overlays_applied": [
                    "equity_circuit",
                    "event_risk_base_throttle",
                    "low_return_soft_inventory_trim",
                ],
                "test_result": {
                    "total_return_pct": 15.3387,
                    "max_drawdown_pct": 10.1582,
                    "estimated_cost_drag_pct": 5.9655,
                    "trade_like_events": 14,
                },
            }
        ]
    }
    folds = [
        {
            "fold": 12,
            "selected_model_id": "replay-stress-repair",
            "after_selection_overlays_applied": [
                "equity_circuit",
                "event_risk_base_throttle",
                "low_return_soft_inventory_trim",
                "low_return_stress_base_throttle",
            ],
            "test_result": {
                "total_return_pct": 9.582,
                "max_drawdown_pct": 3.1906,
                "estimated_cost_drag_pct": 2.222,
                "trade_like_events": 13,
            },
        }
    ]

    diagnostics = _source_replay_diagnostics(source_report, folds)
    guard = _source_replay_lineage_guard(
        diagnostics,
        fail_on_unresolved_material=True,
    )

    assert diagnostics["material_metric_mismatch_count"] == 1
    assert diagnostics["stress_floor_repair_count"] == 1
    assert diagnostics["accepted_risk_tradeoff_count"] == 0
    assert diagnostics["unresolved_material_metric_mismatch_count"] == 0
    assert diagnostics["selected_model_stress_floor_repair_count"] == 1
    assert diagnostics["selected_model_unresolved_mismatch_count"] == 0
    assert diagnostics["drift_quality_counts"] == {"stress_floor_repair": 1}
    assert diagnostics["model_mismatch_status_counts"] == {"stress_floor_repair": 1}
    repair = diagnostics["stress_floor_repair_folds"][0]
    assert repair["fold"] == 12
    assert repair["accepted_stress_floor_repair"] is True
    assert repair["drift_quality"] == "stress_floor_repair"
    assert repair["lineage_status"] == "stress_floor_repair"
    assert diagnostics["unresolved_material_mismatch_folds"] == []
    assert diagnostics["stress_floor_model_mismatch_folds"][0]["fold"] == 12
    assert guard["status"] == "pass"


def test_source_replay_diagnostics_resolves_return_improving_material_drift() -> None:
    source_report = {
        "folds": [
            {
                "fold": 8,
                "selected_model_id": "source-fragile",
                "after_selection_overlays_applied": [
                    "equity_circuit",
                    "fragile_regime_inventory_trim",
                ],
                "test_result": {
                    "total_return_pct": 16.2227,
                    "max_drawdown_pct": 5.0358,
                    "estimated_cost_drag_pct": 4.5253,
                    "trade_like_events": 13,
                },
            }
        ]
    }
    folds = [
        {
            "fold": 8,
            "selected_model_id": "replay-negative-distribution",
            "after_selection_overlays_applied": [
                "equity_circuit",
                "negative_train_distribution_probe",
            ],
            "test_result": {
                "total_return_pct": 24.7187,
                "max_drawdown_pct": 7.5041,
                "estimated_cost_drag_pct": 7.3577,
                "trade_like_events": 32,
            },
        }
    ]

    diagnostics = _source_replay_diagnostics(source_report, folds)
    guard = _source_replay_lineage_guard(
        diagnostics,
        fail_on_unresolved_material=True,
    )

    assert diagnostics["material_metric_mismatch_count"] == 1
    assert diagnostics["beneficial_return_improvement_count"] == 1
    assert diagnostics["selected_model_beneficial_mismatch_count"] == 1
    assert diagnostics["unresolved_material_metric_mismatch_count"] == 0
    assert diagnostics["selected_model_unresolved_mismatch_count"] == 0
    assert diagnostics["lineage_status_counts"] == {"return_improving": 1}
    assert diagnostics["beneficial_return_improvement_folds"][0]["fold"] == 8
    assert diagnostics["unresolved_material_mismatch_folds"] == []
    assert guard["status"] == "pass"
    assert guard["failed"] is False


def test_source_replay_diagnostics_splits_immaterial_model_id_variant() -> None:
    source_report = {
        "folds": [
            {
                "fold": 12,
                "selected_model_id": "source-without-note",
                "after_selection_overlays_applied": ["low_return_soft_inventory_trim"],
                "test_result": {
                    "total_return_pct": 11.2874,
                    "max_drawdown_pct": 10.5037,
                    "estimated_cost_drag_pct": 5.9594,
                    "trade_like_events": 15,
                },
            }
        ]
    }
    folds = [
        {
            "fold": 12,
            "selected_model_id": "replay-with-note",
            "after_selection_overlays_applied": ["low_return_soft_inventory_trim"],
            "test_result": {
                "total_return_pct": 11.2874,
                "max_drawdown_pct": 10.5037,
                "estimated_cost_drag_pct": 5.9594,
                "trade_like_events": 15,
            },
        }
    ]

    diagnostics = _source_replay_diagnostics(source_report, folds)

    assert diagnostics["selected_model_mismatch_count"] == 1
    assert diagnostics["selected_model_immaterial_mismatch_count"] == 1
    assert diagnostics["selected_model_unresolved_mismatch_count"] == 0
    assert diagnostics["material_metric_mismatch_count"] == 0
    assert diagnostics["lineage_status_counts"] == {"immaterial_model_id_variant": 1}
    assert diagnostics["model_mismatch_status_counts"] == {"immaterial_model_id_variant": 1}
    assert diagnostics["folds"][0]["lineage_status"] == "immaterial_model_id_variant"
    assert diagnostics["immaterial_model_mismatch_folds"][0]["fold"] == 12


def test_source_replay_diagnostics_ignores_noop_event_risk_overlay_variant() -> None:
    source_report = {
        "folds": [
            {
                "fold": 12,
                "selected_model_id": "base:wfEqCb16",
                "after_selection_overlays_applied": ["equity_circuit"],
                "test_result": {
                    "total_return_pct": 11.2874,
                    "max_drawdown_pct": 10.5037,
                    "estimated_cost_drag_pct": 5.9594,
                    "trade_like_events": 15,
                    "event_counts": {},
                },
            }
        ]
    }
    folds = [
        {
            "fold": 12,
            "selected_model_id": "base:wfEqCb16:wfEventBaseHourShortExt2.5M025",
            "after_selection_overlays_applied": [
                "equity_circuit",
                "event_risk_base_throttle",
            ],
            "test_result": {
                "total_return_pct": 11.2874,
                "max_drawdown_pct": 10.5037,
                "estimated_cost_drag_pct": 5.9594,
                "trade_like_events": 15,
                "event_counts": {"event_risk_base_reduced_adds": 0},
            },
        }
    ]

    diagnostics = _source_replay_diagnostics(source_report, folds)

    assert diagnostics["selected_model_match_count"] == 1
    assert diagnostics["selected_model_mismatch_count"] == 0
    assert diagnostics["overlay_match_count"] == 1
    assert diagnostics["overlay_mismatch_count"] == 0
    assert diagnostics["metric_mismatch_count"] == 0
    assert diagnostics["lineage_status_counts"] == {"matched_or_immaterial": 1}
    fold = diagnostics["folds"][0]
    assert fold["selected_model_match"] is True
    assert fold["overlay_match"] is True
    assert fold["ignored_noop_overlays"] == ["event_risk_base_throttle"]
    assert fold["effective_selected_model_id"] == "base:wfEqCb16"
    assert fold["effective_after_selection_overlays_applied"] == ["equity_circuit"]


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


@dataclass(frozen=True)
class _OneWayReversalOnlyConfig:
    model_id: str
    max_possible_units: float
    one_way_reversal_switch_units: float


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


def test_selection_stress_floor_penalty_uses_gross_minus_stressed_cost() -> None:
    result = {
        "score": 1.0,
        "total_return_pct": 20.0,
        "gross_return_pct_before_costs": 30.0,
        "estimated_cost_drag_pct": 9.0,
        "max_drawdown_pct": 10.0,
        "event_diagnostics": {"flags": [], "ratios": {}},
    }

    penalized = _selection_score(
        result,
        flag_penalty=0.0,
        stress_cost_multiplier=3.0,
        stress_funding_proxy_pct=1.0,
        stress_min_return_floor_pct=5.0,
        stress_floor_gap_penalty=0.1,
    )
    sufficient_buffer = _selection_score(
        {**result, "gross_return_pct_before_costs": 45.0},
        flag_penalty=0.0,
        stress_cost_multiplier=3.0,
        stress_funding_proxy_pct=1.0,
        stress_min_return_floor_pct=5.0,
        stress_floor_gap_penalty=0.1,
    )

    assert round(penalized, 6) == 0.7
    assert sufficient_buffer == 1.0


def test_selection_cost_to_gross_penalty_targets_cost_efficiency() -> None:
    result = {
        "score": 1.0,
        "total_return_pct": 20.0,
        "gross_return_pct_before_costs": 40.0,
        "estimated_cost_drag_pct": 12.0,
        "max_drawdown_pct": 10.0,
        "event_diagnostics": {"flags": [], "ratios": {}},
    }

    penalized = _selection_score(
        result,
        flag_penalty=0.0,
        cost_to_gross_threshold=0.25,
        cost_to_gross_penalty=2.0,
    )
    efficient = _selection_score(
        {**result, "estimated_cost_drag_pct": 8.0},
        flag_penalty=0.0,
        cost_to_gross_threshold=0.25,
        cost_to_gross_penalty=2.0,
    )

    assert round(penalized, 6) == 0.9
    assert efficient == 1.0


def test_unresolved_stress_guard_keeps_raw_leader_when_penalty_does_not_solve_floor() -> None:
    args = SimpleNamespace(
        selection_stress_unresolved_keep_raw_leader=True,
        selection_stress_cost_multiplier=3.0,
        selection_stress_funding_proxy_pct=0.5,
        selection_stress_min_return_floor_pct=5.0,
        selection_stress_unresolved_return_giveback_pct=10.0,
        selection_stress_unresolved_leader_metric="raw_score",
        selection_stress_unresolved_low_return_max_selected_pct=None,
        selection_stress_unresolved_low_return_giveback_pct=None,
    )
    penalized_pick = {
        "model_id": "cost-efficient-but-weak",
        "score": 0.4,
        "walk_forward_selection_score": 0.2,
        "total_return_pct": 42.0,
        "gross_return_pct_before_costs": 63.0,
        "estimated_cost_drag_pct": 20.5,
        "max_drawdown_pct": 22.0,
    }
    raw_leader = {
        "model_id": "raw-leader",
        "score": 0.5,
        "walk_forward_selection_score": -0.1,
        "total_return_pct": 62.0,
        "gross_return_pct_before_costs": 98.0,
        "estimated_cost_drag_pct": 36.0,
        "max_drawdown_pct": 31.0,
    }

    guarded, details = _apply_unresolved_stress_raw_leader_guard(
        [penalized_pick, raw_leader],
        args,
    )

    assert guarded[0]["model_id"] == "raw-leader"
    assert details["applied"] is True
    assert details["reason"] == "unresolved_stress_preserve_raw_leader"
    assert details["return_giveback_pct"] == 20.0
    assert details["max_stressed_return_pct"] < 5.0


def test_unresolved_stress_guard_does_not_override_when_floor_candidate_exists() -> None:
    args = SimpleNamespace(
        selection_stress_unresolved_keep_raw_leader=True,
        selection_stress_cost_multiplier=3.0,
        selection_stress_funding_proxy_pct=0.5,
        selection_stress_min_return_floor_pct=5.0,
        selection_stress_unresolved_return_giveback_pct=10.0,
        selection_stress_unresolved_leader_metric="raw_score",
        selection_stress_unresolved_low_return_max_selected_pct=None,
        selection_stress_unresolved_low_return_giveback_pct=None,
    )
    selected = {
        "model_id": "stress-solved",
        "score": 0.4,
        "walk_forward_selection_score": 0.2,
        "total_return_pct": 35.0,
        "gross_return_pct_before_costs": 55.0,
        "estimated_cost_drag_pct": 12.0,
        "max_drawdown_pct": 18.0,
    }
    raw_leader = {
        "model_id": "raw-leader",
        "score": 0.5,
        "walk_forward_selection_score": -0.1,
        "total_return_pct": 62.0,
        "gross_return_pct_before_costs": 98.0,
        "estimated_cost_drag_pct": 36.0,
        "max_drawdown_pct": 31.0,
    }

    guarded, details = _apply_unresolved_stress_raw_leader_guard(
        [selected, raw_leader],
        args,
    )

    assert guarded[0]["model_id"] == "stress-solved"
    assert details["applied"] is False
    assert details["reason"] == "stress_floor_candidate_available"


def test_unresolved_stress_guard_can_preserve_train_return_leader() -> None:
    args = SimpleNamespace(
        selection_stress_unresolved_keep_raw_leader=True,
        selection_stress_cost_multiplier=3.0,
        selection_stress_funding_proxy_pct=0.5,
        selection_stress_min_return_floor_pct=5.0,
        selection_stress_unresolved_return_giveback_pct=5.0,
        selection_stress_unresolved_leader_metric="train_return",
        selection_stress_unresolved_low_return_max_selected_pct=None,
        selection_stress_unresolved_low_return_giveback_pct=None,
    )
    selected = {
        "model_id": "raw-score-leader",
        "score": 0.5,
        "walk_forward_selection_score": 0.2,
        "total_return_pct": 36.0,
        "gross_return_pct_before_costs": 55.0,
        "estimated_cost_drag_pct": 20.0,
        "max_drawdown_pct": 18.0,
    }
    train_return_leader = {
        "model_id": "train-return-leader",
        "score": 0.3,
        "walk_forward_selection_score": -0.2,
        "total_return_pct": 44.0,
        "gross_return_pct_before_costs": 70.0,
        "estimated_cost_drag_pct": 26.0,
        "max_drawdown_pct": 22.0,
    }

    guarded, details = _apply_unresolved_stress_raw_leader_guard(
        [selected, train_return_leader],
        args,
    )

    assert guarded[0]["model_id"] == "train-return-leader"
    assert details["applied"] is True
    assert details["leader_metric"] == "train_return"
    assert details["return_giveback_pct"] == 8.0


def test_unresolved_stress_guard_uses_low_return_band_giveback_threshold() -> None:
    args = SimpleNamespace(
        selection_stress_unresolved_keep_raw_leader=True,
        selection_stress_cost_multiplier=3.0,
        selection_stress_funding_proxy_pct=0.5,
        selection_stress_min_return_floor_pct=5.0,
        selection_stress_unresolved_return_giveback_pct=15.0,
        selection_stress_unresolved_leader_metric="train_return",
        selection_stress_unresolved_low_return_max_selected_pct=15.0,
        selection_stress_unresolved_low_return_giveback_pct=3.0,
    )
    selected = {
        "model_id": "low-return-selected",
        "score": 0.5,
        "walk_forward_selection_score": 0.2,
        "total_return_pct": 10.0,
        "gross_return_pct_before_costs": 24.0,
        "estimated_cost_drag_pct": 14.0,
        "max_drawdown_pct": 22.0,
    }
    train_return_leader = {
        "model_id": "low-return-rescue",
        "score": 0.3,
        "walk_forward_selection_score": -0.2,
        "total_return_pct": 14.0,
        "gross_return_pct_before_costs": 36.0,
        "estimated_cost_drag_pct": 22.0,
        "max_drawdown_pct": 31.0,
    }

    guarded, details = _apply_unresolved_stress_raw_leader_guard(
        [selected, train_return_leader],
        args,
    )

    assert guarded[0]["model_id"] == "low-return-rescue"
    assert details["applied"] is True
    assert details["low_return_band_active"] is True
    assert details["return_giveback_threshold_pct"] == 3.0


def test_unresolved_stress_guard_uses_drawdown_rescue_band() -> None:
    args = SimpleNamespace(
        selection_stress_unresolved_keep_raw_leader=True,
        selection_stress_cost_multiplier=3.0,
        selection_stress_funding_proxy_pct=0.5,
        selection_stress_min_return_floor_pct=5.0,
        selection_stress_unresolved_return_giveback_pct=15.0,
        selection_stress_unresolved_leader_metric="train_return",
        selection_stress_unresolved_low_return_max_selected_pct=None,
        selection_stress_unresolved_low_return_giveback_pct=None,
        selection_stress_unresolved_drawdown_rescue_min_selected_pct=30.0,
        selection_stress_unresolved_drawdown_rescue_max_selected_pct=40.0,
        selection_stress_unresolved_drawdown_rescue_min_leader_dd_pct=30.0,
        selection_stress_unresolved_drawdown_rescue_giveback_pct=5.0,
    )
    selected = {
        "model_id": "smoothed-mid-return",
        "score": 0.6,
        "walk_forward_selection_score": 0.2,
        "total_return_pct": 36.0,
        "gross_return_pct_before_costs": 60.0,
        "estimated_cost_drag_pct": 24.0,
        "max_drawdown_pct": 20.0,
    }
    volatile_leader = {
        "model_id": "volatile-trend-leader",
        "score": 0.3,
        "walk_forward_selection_score": -0.3,
        "total_return_pct": 43.0,
        "gross_return_pct_before_costs": 82.0,
        "estimated_cost_drag_pct": 39.0,
        "max_drawdown_pct": 32.0,
    }

    guarded, details = _apply_unresolved_stress_raw_leader_guard(
        [selected, volatile_leader],
        args,
    )

    assert guarded[0]["model_id"] == "volatile-trend-leader"
    assert details["applied"] is True
    assert details["drawdown_rescue_active"] is True
    assert "drawdown_rescue" in details["threshold_reasons"]
    assert details["return_giveback_threshold_pct"] == 5.0


def test_negative_train_distribution_rescue_prefers_recipe_candidate() -> None:
    args = SimpleNamespace(
        selection_negative_train_distribution_rescue=True,
        selection_negative_train_distribution_min_selected_return_pct=-1.0,
        selection_negative_train_distribution_max_selected_return_pct=1.0,
        selection_negative_train_distribution_max_return_giveback_pct=2.0,
        negative_train_distribution_probe_replay_note="enabled",
    )
    selected = {
        "model_id": "marginal-train-winner",
        "score": 0.7,
        "walk_forward_selection_score": 0.3,
        "total_return_pct": -0.2,
        "estimated_cost_drag_pct": 12.8,
        "max_drawdown_pct": 21.0,
        "config": {"max_possible_units": 1.5},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.52,
                "turnover_events_per_add": 2.04,
            }
        },
    }
    repair_candidate = {
        "model_id": "negative-train-distribution-repair",
        "score": 0.6,
        "walk_forward_selection_score": 0.2,
        "total_return_pct": -1.3,
        "estimated_cost_drag_pct": 19.5,
        "max_drawdown_pct": 30.1,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.52,
                "turnover_events_per_add": 2.04,
            }
        },
    }

    guarded, details = _apply_negative_train_distribution_rescue_guard(
        [selected, repair_candidate],
        args,
    )

    assert guarded[0]["model_id"] == "negative-train-distribution-repair"
    assert details["applied"] is True
    assert details["reason"] == "negative_train_distribution_repair"
    assert details["return_giveback_pct"] == 1.1
    assert details["repair_candidate_drawdown_pct"] == 30.1


def test_negative_train_distribution_rescue_respects_giveback_threshold() -> None:
    args = SimpleNamespace(
        selection_negative_train_distribution_rescue=True,
        selection_negative_train_distribution_min_selected_return_pct=-1.0,
        selection_negative_train_distribution_max_selected_return_pct=1.0,
        selection_negative_train_distribution_max_return_giveback_pct=0.5,
        negative_train_distribution_probe_replay_note="enabled",
    )
    selected = {
        "model_id": "marginal-train-winner",
        "score": 0.7,
        "walk_forward_selection_score": 0.3,
        "total_return_pct": -0.2,
        "estimated_cost_drag_pct": 12.8,
        "max_drawdown_pct": 21.0,
        "config": {"max_possible_units": 1.5},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.52,
                "turnover_events_per_add": 2.04,
            }
        },
    }
    repair_candidate = {
        "model_id": "negative-train-distribution-repair",
        "score": 0.6,
        "walk_forward_selection_score": 0.2,
        "total_return_pct": -1.3,
        "estimated_cost_drag_pct": 19.5,
        "max_drawdown_pct": 30.1,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.52,
                "turnover_events_per_add": 2.04,
            }
        },
    }

    guarded, details = _apply_negative_train_distribution_rescue_guard(
        [selected, repair_candidate],
        args,
    )

    assert guarded[0]["model_id"] == "marginal-train-winner"
    assert details["applied"] is False
    assert details["reason"] == "negative_train_distribution_return_giveback_above_threshold"


def test_high_cost_runner_rescue_prefers_recipe_candidate() -> None:
    args = SimpleNamespace(
        selection_high_cost_runner_rescue=True,
        selection_high_cost_runner_min_selected_return_pct=50.0,
        selection_high_cost_runner_max_selected_return_pct=60.0,
        selection_high_cost_runner_max_return_giveback_pct=6.0,
        balanced_structure_replay_note="enabled",
        high_cost_repair_cut_05_replay_note="enabled",
        high_cost_near_zero_react_replay_note="enabled",
        high_cost_runner_reversal_scale_replay_note="enabled",
        high_cost_runner_tight_repair_replay_note="enabled",
    )
    selected = {
        "model_id": "train-return-leader",
        "score": 0.1,
        "walk_forward_selection_score": -0.5,
        "total_return_pct": 55.6,
        "estimated_cost_drag_pct": 45.0,
        "max_drawdown_pct": 17.0,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.35,
                "turnover_events_per_add": 2.45,
            }
        },
    }
    repair_candidate = {
        "model_id": "high-cost-runner",
        "score": 0.2,
        "walk_forward_selection_score": -0.24,
        "total_return_pct": 51.6,
        "estimated_cost_drag_pct": 43.9,
        "max_drawdown_pct": 20.5,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.375,
                "turnover_events_per_add": 2.453,
            }
        },
    }

    guarded, details = _apply_high_cost_runner_rescue_guard(
        [selected, repair_candidate],
        args,
    )

    assert guarded[0]["model_id"] == "high-cost-runner"
    assert details["applied"] is True
    assert details["reason"] == "high_cost_runner_repair"
    assert details["return_giveback_pct"] == 4.0
    assert details["repair_candidate_drawdown_pct"] == 20.5
    assert details["repair_candidate_cost_drag_pct"] == 43.9


def test_high_cost_runner_rescue_respects_giveback_threshold() -> None:
    args = SimpleNamespace(
        selection_high_cost_runner_rescue=True,
        selection_high_cost_runner_min_selected_return_pct=50.0,
        selection_high_cost_runner_max_selected_return_pct=60.0,
        selection_high_cost_runner_max_return_giveback_pct=3.0,
        balanced_structure_replay_note="enabled",
        high_cost_repair_cut_05_replay_note="enabled",
        high_cost_near_zero_react_replay_note="enabled",
        high_cost_runner_reversal_scale_replay_note="enabled",
        high_cost_runner_tight_repair_replay_note="enabled",
    )
    selected = {
        "model_id": "train-return-leader",
        "score": 0.1,
        "walk_forward_selection_score": -0.5,
        "total_return_pct": 55.6,
        "estimated_cost_drag_pct": 45.0,
        "max_drawdown_pct": 17.0,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.35,
                "turnover_events_per_add": 2.45,
            }
        },
    }
    repair_candidate = {
        "model_id": "high-cost-runner",
        "score": 0.2,
        "walk_forward_selection_score": -0.24,
        "total_return_pct": 51.6,
        "estimated_cost_drag_pct": 43.9,
        "max_drawdown_pct": 20.5,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.375,
                "turnover_events_per_add": 2.453,
            }
        },
    }

    guarded, details = _apply_high_cost_runner_rescue_guard(
        [selected, repair_candidate],
        args,
    )

    assert guarded[0]["model_id"] == "train-return-leader"
    assert details["applied"] is False
    assert details["reason"] == "high_cost_runner_return_giveback_above_threshold"


def test_deep_soft_overlay_rescue_prefers_gate_matched_candidate() -> None:
    args = SimpleNamespace(
        selection_deep_soft_overlay_rescue=True,
        selection_deep_soft_overlay_min_selected_return_pct=40.0,
        selection_deep_soft_overlay_max_selected_return_pct=45.0,
        selection_deep_soft_overlay_max_return_giveback_pct=1.0,
        equity_soft_sizer_deep_after_selection=True,
        near_miss_activity_after_selection=True,
        equity_soft_sizer_deep_after_selection_min_source_max_units=1.0,
        equity_soft_sizer_deep_after_selection_max_source_max_units=1.0,
        equity_soft_sizer_deep_after_selection_min_train_return_pct=40.0,
        equity_soft_sizer_deep_after_selection_max_train_return_pct=45.0,
        equity_soft_sizer_deep_after_selection_min_train_drawdown_pct=30.0,
        equity_soft_sizer_deep_after_selection_max_train_drawdown_pct=33.0,
        equity_soft_sizer_deep_after_selection_min_train_cost_drag_pct=35.0,
        equity_soft_sizer_deep_after_selection_max_train_cost_drag_pct=40.0,
        equity_soft_sizer_deep_after_selection_min_one_way_trim_per_add=0.35,
        equity_soft_sizer_deep_after_selection_max_one_way_trim_per_add=0.42,
        equity_soft_sizer_deep_after_selection_min_turnover_per_add=2.07,
        equity_soft_sizer_deep_after_selection_max_turnover_per_add=2.17,
        near_miss_activity_after_selection_min_source_max_units=1.0,
        near_miss_activity_after_selection_max_source_max_units=1.0,
        near_miss_activity_after_selection_min_train_return_pct=40.0,
        near_miss_activity_after_selection_max_train_return_pct=45.0,
        near_miss_activity_after_selection_min_train_drawdown_pct=30.0,
        near_miss_activity_after_selection_max_train_drawdown_pct=33.0,
        near_miss_activity_after_selection_min_train_cost_drag_pct=35.0,
        near_miss_activity_after_selection_max_train_cost_drag_pct=40.0,
        near_miss_activity_after_selection_min_one_way_trim_per_add=0.35,
        near_miss_activity_after_selection_max_one_way_trim_per_add=0.42,
        near_miss_activity_after_selection_min_turnover_per_add=2.07,
        near_miss_activity_after_selection_max_turnover_per_add=2.17,
    )
    selected = {
        "model_id": "raw-leader",
        "score": 0.19,
        "walk_forward_selection_score": -1.33,
        "total_return_pct": 44.0048,
        "estimated_cost_drag_pct": 38.8725,
        "max_drawdown_pct": 32.7124,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.2973,
                "turnover_events_per_add": 2.1081,
            }
        },
    }
    repair_candidate = {
        "model_id": "deep-soft-candidate",
        "score": 0.2,
        "walk_forward_selection_score": -0.38,
        "total_return_pct": 43.7566,
        "estimated_cost_drag_pct": 38.4444,
        "max_drawdown_pct": 32.3797,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.4,
                "turnover_events_per_add": 2.1455,
            }
        },
    }

    guarded, details = _apply_deep_soft_overlay_rescue_guard(
        [selected, repair_candidate],
        args,
    )

    assert guarded[0]["model_id"] == "deep-soft-candidate"
    assert details["applied"] is True
    assert details["reason"] == "deep_soft_overlay_repair"
    assert details["return_giveback_pct"] == 0.2482


def test_deep_soft_overlay_rescue_respects_giveback_threshold() -> None:
    args = SimpleNamespace(
        selection_deep_soft_overlay_rescue=True,
        selection_deep_soft_overlay_min_selected_return_pct=40.0,
        selection_deep_soft_overlay_max_selected_return_pct=45.0,
        selection_deep_soft_overlay_max_return_giveback_pct=0.1,
        equity_soft_sizer_deep_after_selection=True,
        near_miss_activity_after_selection=True,
        equity_soft_sizer_deep_after_selection_min_source_max_units=1.0,
        equity_soft_sizer_deep_after_selection_max_source_max_units=1.0,
        equity_soft_sizer_deep_after_selection_min_train_return_pct=40.0,
        equity_soft_sizer_deep_after_selection_max_train_return_pct=45.0,
        equity_soft_sizer_deep_after_selection_min_train_drawdown_pct=30.0,
        equity_soft_sizer_deep_after_selection_max_train_drawdown_pct=33.0,
        equity_soft_sizer_deep_after_selection_min_train_cost_drag_pct=35.0,
        equity_soft_sizer_deep_after_selection_max_train_cost_drag_pct=40.0,
        equity_soft_sizer_deep_after_selection_min_one_way_trim_per_add=0.35,
        equity_soft_sizer_deep_after_selection_max_one_way_trim_per_add=0.42,
        equity_soft_sizer_deep_after_selection_min_turnover_per_add=2.07,
        equity_soft_sizer_deep_after_selection_max_turnover_per_add=2.17,
        near_miss_activity_after_selection_min_source_max_units=1.0,
        near_miss_activity_after_selection_max_source_max_units=1.0,
        near_miss_activity_after_selection_min_train_return_pct=40.0,
        near_miss_activity_after_selection_max_train_return_pct=45.0,
        near_miss_activity_after_selection_min_train_drawdown_pct=30.0,
        near_miss_activity_after_selection_max_train_drawdown_pct=33.0,
        near_miss_activity_after_selection_min_train_cost_drag_pct=35.0,
        near_miss_activity_after_selection_max_train_cost_drag_pct=40.0,
        near_miss_activity_after_selection_min_one_way_trim_per_add=0.35,
        near_miss_activity_after_selection_max_one_way_trim_per_add=0.42,
        near_miss_activity_after_selection_min_turnover_per_add=2.07,
        near_miss_activity_after_selection_max_turnover_per_add=2.17,
    )
    selected = {
        "model_id": "raw-leader",
        "score": 0.19,
        "walk_forward_selection_score": -1.33,
        "total_return_pct": 44.0048,
        "estimated_cost_drag_pct": 38.8725,
        "max_drawdown_pct": 32.7124,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.2973,
                "turnover_events_per_add": 2.1081,
            }
        },
    }
    repair_candidate = {
        "model_id": "deep-soft-candidate",
        "score": 0.2,
        "walk_forward_selection_score": -0.38,
        "total_return_pct": 43.7566,
        "estimated_cost_drag_pct": 38.4444,
        "max_drawdown_pct": 32.3797,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.4,
                "turnover_events_per_add": 2.1455,
            }
        },
    }

    guarded, details = _apply_deep_soft_overlay_rescue_guard(
        [selected, repair_candidate],
        args,
    )

    assert guarded[0]["model_id"] == "raw-leader"
    assert details["applied"] is False
    assert details["reason"] == "deep_soft_overlay_return_giveback_above_threshold"


def test_deep_drawdown_reversal_rescue_prefers_recipe_candidate() -> None:
    args = SimpleNamespace(
        selection_deep_drawdown_reversal_rescue=True,
        selection_deep_drawdown_reversal_min_selected_return_pct=60.0,
        selection_deep_drawdown_reversal_max_selected_return_pct=63.0,
        selection_deep_drawdown_reversal_max_return_giveback_pct=1.0,
        deep_drawdown_reversal_scale_replay_note="enabled",
    )
    selected = {
        "model_id": "raw-leader",
        "score": 0.45,
        "walk_forward_selection_score": -0.69,
        "total_return_pct": 62.2277,
        "estimated_cost_drag_pct": 37.0673,
        "max_drawdown_pct": 31.0449,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.3971,
                "turnover_events_per_add": 2.1324,
            }
        },
    }
    repair_candidate = {
        "model_id": "deep-reversal-candidate",
        "score": 0.44,
        "walk_forward_selection_score": -0.09,
        "total_return_pct": 61.6222,
        "estimated_cost_drag_pct": 36.5104,
        "max_drawdown_pct": 31.1137,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.551,
                "turnover_events_per_add": 2.1837,
            }
        },
    }

    guarded, details = _apply_deep_drawdown_reversal_rescue_guard(
        [selected, repair_candidate],
        args,
    )

    assert guarded[0]["model_id"] == "deep-reversal-candidate"
    assert details["applied"] is True
    assert details["reason"] == "deep_drawdown_reversal_repair"
    assert details["return_giveback_pct"] == 0.6055


def test_deep_drawdown_reversal_rescue_respects_giveback_threshold() -> None:
    args = SimpleNamespace(
        selection_deep_drawdown_reversal_rescue=True,
        selection_deep_drawdown_reversal_min_selected_return_pct=60.0,
        selection_deep_drawdown_reversal_max_selected_return_pct=63.0,
        selection_deep_drawdown_reversal_max_return_giveback_pct=0.5,
        deep_drawdown_reversal_scale_replay_note="enabled",
    )
    selected = {
        "model_id": "raw-leader",
        "score": 0.45,
        "walk_forward_selection_score": -0.69,
        "total_return_pct": 62.2277,
        "estimated_cost_drag_pct": 37.0673,
        "max_drawdown_pct": 31.0449,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.3971,
                "turnover_events_per_add": 2.1324,
            }
        },
    }
    repair_candidate = {
        "model_id": "deep-reversal-candidate",
        "score": 0.44,
        "walk_forward_selection_score": -0.09,
        "total_return_pct": 61.6222,
        "estimated_cost_drag_pct": 36.5104,
        "max_drawdown_pct": 31.1137,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.551,
                "turnover_events_per_add": 2.1837,
            }
        },
    }

    guarded, details = _apply_deep_drawdown_reversal_rescue_guard(
        [selected, repair_candidate],
        args,
    )

    assert guarded[0]["model_id"] == "raw-leader"
    assert details["applied"] is False
    assert details["reason"] == "deep_drawdown_reversal_return_giveback_above_threshold"


def test_deep_drawdown_reversal_rescue_blocks_forced_trim_overuse() -> None:
    args = SimpleNamespace(
        selection_deep_drawdown_reversal_rescue=True,
        selection_deep_drawdown_reversal_min_selected_return_pct=60.0,
        selection_deep_drawdown_reversal_max_selected_return_pct=63.0,
        selection_deep_drawdown_reversal_max_return_giveback_pct=1.0,
        selection_deep_drawdown_reversal_max_candidate_one_way_trim_per_add=0.5,
        selection_deep_drawdown_reversal_max_one_way_trim_increase_per_add=0.1,
        deep_drawdown_reversal_scale_replay_note="enabled",
    )
    selected = {
        "model_id": "raw-leader",
        "score": 0.45,
        "walk_forward_selection_score": -0.69,
        "total_return_pct": 62.2277,
        "estimated_cost_drag_pct": 37.0673,
        "max_drawdown_pct": 31.0449,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.3971,
                "turnover_events_per_add": 2.1324,
            }
        },
    }
    churny_repair_candidate = {
        "model_id": "deep-reversal-candidate",
        "score": 0.44,
        "walk_forward_selection_score": -0.09,
        "total_return_pct": 61.6222,
        "estimated_cost_drag_pct": 36.5104,
        "max_drawdown_pct": 31.1137,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.551,
                "turnover_events_per_add": 2.1837,
            }
        },
    }

    guarded, details = _apply_deep_drawdown_reversal_rescue_guard(
        [selected, churny_repair_candidate],
        args,
    )

    assert guarded[0]["model_id"] == "raw-leader"
    assert details["applied"] is False
    assert details["reason"] == "deep_drawdown_reversal_forced_trim_cap_blocked"
    assert details["blocked_candidate_count"] == 1
    assert details["blocked_candidates"][0]["blocked_reasons"] == [
        "candidate_one_way_trim_above_cap",
        "one_way_trim_increase_above_cap",
    ]


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


def test_improvement_backlog_diagnostics_splits_selection_and_candidate_limits() -> None:
    def candidate(
        *,
        rank: int,
        selected: bool,
        ret: float,
        dd: float,
        cost: float,
        flags: list[str] | None = None,
    ) -> dict[str, object]:
        return {
            "rank": rank,
            "is_selected": selected,
            "model_id": f"model-{rank}",
            "train_selection_score": 1.0 / rank,
            "train_return_pct": 30.0,
            "test_return_pct": ret,
            "test_max_drawdown_pct": dd,
            "test_flags": flags or [],
            "test_result": {
                "estimated_cost_drag_pct": cost,
                "trade_like_events": 10 + rank,
            },
        }

    audit = _aggregate_improvement_backlog_diagnostics(
        [
            {
                "fold": 1,
                "test_start": "2026-01-01",
                "test_end": "2026-04-01",
                "train_top_test_results": [
                    candidate(rank=1, selected=True, ret=5.0, dd=3.0, cost=1.0),
                    candidate(rank=2, selected=False, ret=5.4, dd=3.2, cost=1.1),
                ],
            },
            {
                "fold": 2,
                "test_start": "2026-04-01",
                "test_end": "2026-07-01",
                "train_top_test_results": [
                    candidate(rank=1, selected=True, ret=10.0, dd=5.0, cost=2.0),
                    candidate(rank=2, selected=False, ret=14.0, dd=4.0, cost=1.5),
                ],
            },
            {
                "fold": 3,
                "test_start": "2026-07-01",
                "test_end": "2026-10-01",
                "train_top_test_results": [
                    candidate(rank=1, selected=True, ret=40.0, dd=12.0, cost=5.0),
                    candidate(rank=2, selected=False, ret=36.0, dd=11.2, cost=4.0),
                ],
            },
            {
                "fold": 4,
                "test_start": "2026-10-01",
                "test_end": "2027-01-01",
                "train_top_test_results": [
                    candidate(rank=1, selected=True, ret=100.0, dd=9.0, cost=25.0),
                    candidate(rank=2, selected=False, ret=96.0, dd=9.0, cost=22.0),
                ],
            },
        ]
    )

    assert audit["audited_fold_count"] == 4
    assert audit["next_step"] == "tune_selection_policy"
    assert audit["low_return_candidate_ceiling_count"] == 1
    assert audit["low_return_candidate_ceiling_folds"][0]["fold"] == 1
    assert audit["clean_selection_miss_count"] == 1
    assert audit["clean_selection_miss_folds"][0]["fold"] == 2
    assert audit["risk_compression_tradeoff_count"] == 1
    assert audit["risk_compression_tradeoff_folds"][0]["fold"] == 3
    assert audit["risk_compression_tradeoff_folds"][0]["drawdown_reduction_pct"] == 0.8
    assert audit["cost_compression_tradeoff_count"] == 1
    assert audit["cost_compression_tradeoff_folds"][0]["fold"] == 4
    assert audit["cost_compression_tradeoff_folds"][0]["cost_reduction_pct"] == 3.0


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
        [
            "equity_circuit",
            "one_way_impulse_tail",
            "one_way_impulse_tail",
            "risk_smoothing",
        ],
        args,
    )

    assert targets == ["one_way_impulse_tail"]


def test_after_selection_confirmation_targets_all_when_unconfigured() -> None:
    args = SimpleNamespace(after_selection_confirm_overlays="")

    targets = _after_selection_confirmation_targets(
        ["equity_circuit", "one_way_impulse_tail", "equity_circuit"],
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


def test_one_way_reversal_after_selection_overlay_is_noop_when_units_unchanged() -> None:
    args = SimpleNamespace(one_way_reversal_after_selection_switch_units=0.05)
    config = _OneWayReversalOnlyConfig(
        model_id="model:wfOwRev0.05",
        max_possible_units=1.0,
        one_way_reversal_switch_units=0.05,
    )

    tuned = _apply_one_way_reversal_after_selection_overlay(config, args)

    assert tuned == config


def test_one_way_reversal_after_selection_overlay_updates_changed_units() -> None:
    args = SimpleNamespace(one_way_reversal_after_selection_switch_units=0.2)
    tuned = _apply_one_way_reversal_after_selection_overlay(
        _OneWayReversalOnlyConfig(
            model_id="model",
            max_possible_units=1.0,
            one_way_reversal_switch_units=0.05,
        ),
        args,
    )

    assert tuned.one_way_reversal_switch_units == 0.2
    assert tuned.model_id == "model:wfOwRevAS0.2"


def test_legacy_recipe_gate_uses_train_state_ranges() -> None:
    recipe = {
        "gate": {
            "min_source_max_units": 1.0,
            "max_source_max_units": 1.0,
            "min_train_return_pct": 70.0,
            "max_train_return_pct": 80.0,
            "min_train_drawdown_pct": 10.0,
            "max_train_drawdown_pct": 15.0,
            "min_train_cost_drag_pct": 30.0,
            "max_train_cost_drag_pct": 40.0,
            "min_one_way_trim_per_add": 0.34,
            "max_one_way_trim_per_add": 0.39,
            "min_turnover_per_add": 2.10,
            "max_turnover_per_add": 2.20,
        }
    }
    train_result = {
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

    assert _legacy_recipe_allowed(train_result, recipe)
    assert not _legacy_recipe_allowed({**train_result, "total_return_pct": 85.0}, recipe)


def test_legacy_recipe_gate_can_target_source_config_ranges() -> None:
    recipe = {
        "gate": {
            "source_config_ranges": {
                "defensive_trim_cooldown_bars": {"min": 0, "max": 100},
            },
        }
    }
    train_result = {
        "config": {
            "max_possible_units": 1.0,
            "defensive_trim_cooldown_bars": 12,
        },
    }

    assert _legacy_recipe_allowed(train_result, recipe)
    assert not _legacy_recipe_allowed(
        {
            "config": {
                "max_possible_units": 1.0,
                "defensive_trim_cooldown_bars": 12960,
            },
        },
        recipe,
    )
    assert not _legacy_recipe_allowed({"config": {"max_possible_units": 1.0}}, recipe)


def test_legacy_recipe_overlay_applies_material_changes_once() -> None:
    recipe = {
        "name": "legacy_reaction",
        "suffix": "wfLegacyReact1",
        "change": {"reaction_trim_trigger": 1.0},
    }
    config = _ReactionOnlyConfig(
        model_id="model",
        reaction_trim_trigger=0.55,
        repair_cut=0.9,
        repair_stop=1.2,
    )

    tuned = _apply_legacy_recipe_overlay(config, recipe)
    repeated = _apply_legacy_recipe_overlay(tuned, recipe)

    assert tuned.reaction_trim_trigger == 1.0
    assert tuned.model_id == "model:wfLegacyReact1"
    assert repeated == tuned


def test_legacy_recipe_overlay_normalizes_soft_recovery_fields() -> None:
    recipe = {
        "name": "soft_recovery",
        "suffix": "wfSoftRec",
        "change": {
            "equity_soft_circuit_recovery_probe_units": 2.0,
            "equity_soft_circuit_recovery_min_one_way_score": 3.5,
            "equity_soft_circuit_recovery_min_score_diff": 5.9,
            "equity_soft_circuit_recovery_max_extension_atr": 3.5,
        },
    }
    config = _SoftRecoveryOnlyConfig(
        model_id="model",
        max_possible_units=0.5,
        equity_soft_circuit_recovery_probe_units=0.0,
        equity_soft_circuit_recovery_min_one_way_score=3.0,
        equity_soft_circuit_recovery_min_score_diff=4,
        equity_soft_circuit_recovery_max_extension_atr=2.0,
    )

    tuned = _apply_legacy_recipe_overlay(config, recipe)
    repeated = _apply_legacy_recipe_overlay(tuned, recipe)

    assert tuned.equity_soft_circuit_recovery_probe_units == 0.5
    assert tuned.equity_soft_circuit_recovery_min_one_way_score == 3.5
    assert tuned.equity_soft_circuit_recovery_min_score_diff == 5
    assert tuned.equity_soft_circuit_recovery_max_extension_atr == 3.5
    assert tuned.model_id == "model:wfSoftRec"
    assert repeated == tuned


def test_legacy_recipe_overlay_normalizes_soft_sizer_fields() -> None:
    recipe = {
        "name": "soft_sizer_relax",
        "suffix": "wfEqSoftRelax12M025",
        "change": {
            "equity_soft_circuit_drawdown_pct": 12,
            "equity_soft_circuit_size_mult": 1.5,
            "equity_soft_circuit_cooldown_bars": 2880.9,
            "equity_soft_circuit_force_flat": False,
        },
    }
    config = _SoftSizerOnlyConfig(
        model_id="model",
        equity_soft_circuit_drawdown_pct=10.0,
        equity_soft_circuit_size_mult=0.25,
        equity_soft_circuit_cooldown_bars=1440,
        equity_soft_circuit_force_flat=True,
    )

    tuned = _apply_legacy_recipe_overlay(config, recipe)
    repeated = _apply_legacy_recipe_overlay(tuned, recipe)

    assert tuned.equity_soft_circuit_drawdown_pct == 12.0
    assert tuned.equity_soft_circuit_size_mult == 1.0
    assert tuned.equity_soft_circuit_cooldown_bars == 2880
    assert tuned.equity_soft_circuit_force_flat is False
    assert tuned.model_id == "model:wfEqSoftRelax12M025"
    assert repeated == tuned


def test_legacy_recipe_overlay_normalizes_soft_inventory_trim_fields() -> None:
    recipe = {
        "name": "low_return_soft_inventory_trim",
        "suffix": "wfEqSoftInvTrim8F020",
        "change": {
            "equity_soft_circuit_drawdown_pct": 8,
            "equity_soft_circuit_size_mult": 0.25,
            "equity_soft_circuit_cooldown_bars": 2880,
            "equity_soft_circuit_force_flat": False,
            "equity_soft_circuit_inventory_trim_fraction": 1.5,
        },
    }
    config = _SoftSizerOnlyConfig(
        model_id="model",
        equity_soft_circuit_drawdown_pct=10.0,
        equity_soft_circuit_size_mult=0.25,
        equity_soft_circuit_cooldown_bars=1440,
        equity_soft_circuit_force_flat=True,
    )

    tuned = _apply_legacy_recipe_overlay(config, recipe)

    assert tuned.equity_soft_circuit_drawdown_pct == 8.0
    assert tuned.equity_soft_circuit_size_mult == 0.25
    assert tuned.equity_soft_circuit_cooldown_bars == 2880
    assert tuned.equity_soft_circuit_force_flat is False
    assert tuned.equity_soft_circuit_inventory_trim_fraction == 1.0
    assert tuned.model_id == "model:wfEqSoftInvTrim8F020"


def test_legacy_recipe_overlay_normalizes_event_risk_base_fields() -> None:
    recipe = {
        "name": "event_risk_base_throttle",
        "suffix": "wfEventBase",
        "change": {
            "event_risk_base_reduce_size_mult": -0.5,
            "event_risk_base_reduce_min_extension_atr": 2.5,
            "event_risk_base_reduce_side": "short",
            "event_risk_base_reduce_contexts": ["hour_open", "ignored", "hour_open"],
        },
    }
    config = _EventRiskBaseOnlyConfig(
        model_id="model",
        event_risk_base_reduce_size_mult=1.0,
        event_risk_base_reduce_min_extension_atr=0.0,
        event_risk_base_reduce_max_extension_atr=0.0,
        event_risk_base_reduce_side="both",
        event_risk_base_reduce_contexts=(),
    )

    tuned = _apply_legacy_recipe_overlay(config, recipe)
    repeated = _apply_legacy_recipe_overlay(tuned, recipe)

    assert tuned.event_risk_base_reduce_size_mult == 0.0
    assert tuned.event_risk_base_reduce_min_extension_atr == 2.5
    assert tuned.event_risk_base_reduce_max_extension_atr == 0.0
    assert tuned.event_risk_base_reduce_side == "short"
    assert tuned.event_risk_base_reduce_contexts == ("hour_open",)
    assert tuned.model_id == "model:wfEventBase"
    assert repeated == tuned


def test_event_risk_base_overrides_survive_base_reduce_after_selection() -> None:
    args = walk_forward_module._parse_args(
        [
            "--base-entry-reduce-after-selection",
            "--event-risk-base-reduce-size-mult",
            "0.25",
            "--event-risk-base-reduce-min-extension-atr",
            "1.5",
            "--event-risk-base-reduce-side",
            "short",
            "--event-risk-base-reduce-contexts",
            "normal,hour_open",
        ]
    )
    config = _EventRiskBaseOnlyConfig(
        model_id="model",
        event_risk_base_reduce_size_mult=1.0,
        event_risk_base_reduce_min_extension_atr=0.0,
        event_risk_base_reduce_max_extension_atr=0.0,
        event_risk_base_reduce_side="both",
        event_risk_base_reduce_contexts=(),
    )

    tuned = walk_forward_module._apply_config_overrides(
        config,
        args,
        include_base_reduce=False,
    )

    assert tuned.event_risk_base_reduce_size_mult == 0.25
    assert tuned.event_risk_base_reduce_min_extension_atr == 1.5
    assert tuned.event_risk_base_reduce_side == "short"
    assert tuned.event_risk_base_reduce_contexts == ("normal", "hour_open")
    assert tuned.model_id == (
        "model:wfEventBaseMult0.25:wfEventBaseMinExt1.5:"
        "wfEventBaseSideshort:wfEventBaseCtxnormal-hour_open"
    )


def test_cost_throttle_overrides_are_available_in_walk_forward_replay() -> None:
    args = walk_forward_module._parse_args(
        [
            "--one-way-trim-size-mult",
            "0.9",
            "--hard-time-exit-fraction",
            "0.5",
            "--hard-time-exit-cooldown-bars",
            "288",
            "--reaction-trim-trend-hold-trigger-mult",
            "1.4",
            "--hard-time-exit-trend-defer-bars",
            "12",
            "--hard-time-exit-trend-defer-min-favorable-reaction",
            "0.1",
            "--trend-hold-min-trend-strength",
            "0.4",
            "--trend-hold-min-one-way-score",
            "2.5",
            "--reaction-trim-size-mult",
            "0.75",
        ]
    )
    config = _CostThrottleOnlyConfig(
        model_id="model",
        one_way_trim_size_mult=1.0,
        hard_time_exit_fraction=1.0,
        hard_time_exit_cooldown_bars=0,
        reaction_trim_size_mult=1.0,
        reaction_trim_trend_hold_trigger_mult=1.0,
        hard_time_exit_trend_defer_bars=0,
        hard_time_exit_trend_defer_min_favorable_reaction=0.0,
        trend_hold_min_trend_strength=0.35,
        trend_hold_min_one_way_score=0.0,
    )

    tuned = walk_forward_module._apply_config_overrides(config, args)

    assert tuned.one_way_trim_size_mult == 0.9
    assert tuned.hard_time_exit_fraction == 0.5
    assert tuned.hard_time_exit_cooldown_bars == 288
    assert tuned.reaction_trim_size_mult == 0.75
    assert tuned.reaction_trim_trend_hold_trigger_mult == 1.4
    assert tuned.hard_time_exit_trend_defer_bars == 12
    assert tuned.hard_time_exit_trend_defer_min_favorable_reaction == 0.1
    assert tuned.trend_hold_min_trend_strength == 0.4
    assert tuned.trend_hold_min_one_way_score == 2.5
    assert tuned.model_id == (
        "model:wfOwTrimMult0.9:wfHardTimeFrac0.5:"
        "wfHardTimeCool288:wfReactTrendHold1.4:"
        "wfHardTrendDef12:wfHardTrendFav0.1:"
        "wfTrendHoldT0.4:wfTrendHoldO2.5:wfReactTrimMult0.75"
    )

    unchanged = walk_forward_module._apply_config_overrides(tuned, args)
    assert unchanged.model_id == tuned.model_id


def test_exit_trend_hold_overlay_updates_selected_config_only() -> None:
    args = walk_forward_module._parse_args(
        [
            "--exit-trend-hold-after-selection",
            "--exit-trend-hold-after-selection-reaction-trim-trigger-mult",
            "1.25",
            "--exit-trend-hold-after-selection-hard-time-defer-bars",
            "12",
            "--exit-trend-hold-after-selection-hard-time-min-favorable-reaction",
            "0.05",
            "--exit-trend-hold-after-selection-min-trend-strength",
            "0.4",
            "--exit-trend-hold-after-selection-min-one-way-score",
            "2.0",
        ]
    )
    config = _ExitTrendHoldOnlyConfig(
        model_id="model",
        reaction_trim_trend_hold_trigger_mult=1.0,
        hard_time_exit_trend_defer_bars=0,
        hard_time_exit_trend_defer_min_favorable_reaction=0.0,
        trend_hold_min_trend_strength=0.35,
        trend_hold_min_one_way_score=0.0,
    )

    tuned = _apply_exit_trend_hold_overlay(config, args)

    assert tuned.reaction_trim_trend_hold_trigger_mult == 1.25
    assert tuned.hard_time_exit_trend_defer_bars == 12
    assert tuned.hard_time_exit_trend_defer_min_favorable_reaction == 0.05
    assert tuned.trend_hold_min_trend_strength == 0.4
    assert tuned.trend_hold_min_one_way_score == 2.0
    assert tuned.model_id == (
        "model:wfExitTrendReact1.25:wfExitTrendHard12:"
        "wfExitTrendFav0.05:wfExitTrendT0.4:wfExitTrendO2"
    )


def test_legacy_recipe_blockers_detect_applied_overlay_conflict() -> None:
    recipe = {
        "name": "role_border_impulse_micro",
        "blocked_by_applied": ["high_return_soft_sizer_relax"],
    }

    assert _legacy_recipe_blockers(recipe, ["equity_circuit"]) == []
    assert _legacy_recipe_blockers(
        recipe,
        ["equity_circuit", "high_return_soft_sizer_relax"],
    ) == ["high_return_soft_sizer_relax"]


def test_legacy_recipe_catalog_includes_targeted_drawdown_repairs() -> None:
    recipes = _legacy_after_selection_recipes(
        SimpleNamespace(
            deep_soft_reaction_delay_replay_note="enabled",
            deep_drawdown_reversal_scale_replay_note="enabled",
            forced_trim_near_miss_tiny_replay_note="enabled",
            low_return_soft_inventory_trim_replay_note="enabled",
            fast_defense_one_way_delay_replay_note="enabled",
        )
    )
    recipes_by_name = {recipe["name"]: recipe for recipe in recipes}

    assert recipes_by_name["deep_soft_reaction_delay"]["change"] == {
        "reaction_trim_trigger": 1.0
    }
    assert recipes_by_name["deep_soft_reaction_delay"]["blocked_by_applied"] == [
        "trim_cooldown_deep_soft"
    ]
    assert recipes_by_name["forced_trim_near_miss_tiny"]["change"] == {
        "near_miss_probe_units": 0.001
    }
    assert recipes_by_name["deep_drawdown_reversal_scale"]["change"] == {
        "one_way_reversal_switch_units": 0.70
    }
    assert recipes_by_name["low_return_soft_inventory_trim"]["change"] == {
        "equity_soft_circuit_drawdown_pct": 8.0,
        "equity_soft_circuit_cooldown_bars": 2880,
        "equity_soft_circuit_size_mult": 0.25,
        "equity_soft_circuit_force_flat": False,
        "equity_soft_circuit_inventory_trim_fraction": 0.20,
    }
    assert recipes_by_name["fast_defense_one_way_delay"]["required_applied"] == [
        "low_return_soft_inventory_trim"
    ]
    assert recipes_by_name["fast_defense_one_way_delay"]["change"] == {
        "one_way_trim_min_adverse_reaction": 0.50
    }
    assert recipes_by_name["fast_defense_one_way_delay"]["gate"]["source_config_ranges"] == {
        "defensive_trim_cooldown_bars": {"min": 0.0, "max": 100.0}
    }


def test_legacy_recipe_catalog_includes_low_activity_and_base_heavy_repairs() -> None:
    recipes = _legacy_after_selection_recipes(
        SimpleNamespace(
            low_activity_reengage_probe_replay_note="enabled",
            base_heavy_probe_rebalance_replay_note="enabled",
            event_risk_base_throttle_replay_note="enabled",
            event_risk_base_tight_repair_replay_note="enabled",
            low_return_stress_base_throttle_replay_note="enabled",
            low_return_single_unit_compression_replay_note="enabled",
            low_return_single_unit_compression_units=0.50,
            event_risk_reaction_soft_hold_replay_note="enabled",
            event_risk_soft_hold_near_miss_replay_note="enabled",
            negative_train_distribution_probe_replay_note="enabled",
            compressed_trend_distribution_probe_replay_note="enabled",
            event_risk_distribution_base_off_replay_note="enabled",
            event_risk_soft_hold_inventory_release_replay_note="enabled",
            event_risk_soft_hold_inventory_release_fraction=0.0,
            fold13_stress_exit_sizer_replay_note="enabled",
            fold13_stress_exit_sizer_reaction_trim_size_mult=0.50,
            fold13_stress_exit_sizer_hard_time_fraction=0.25,
            fold13_selective_impulse_replay_note="enabled",
            fold13_selective_impulse_probe_units=1.0,
            fold13_selective_impulse_min_one_way_score=3.5,
            fold13_selective_impulse_min_score_diff=5,
            fold13_selective_impulse_reaction_trim_trigger=0.60,
            fold13_near_miss_noise_filter_replay_note="enabled",
            fold13_hard_loss_defer_replay_note="enabled",
            balanced_structure_replay_note="enabled",
            high_cost_runner_reversal_scale_replay_note="enabled",
            high_cost_runner_tight_repair_replay_note="enabled",
            soft_circuit_low_activity_entry_grace_replay_note="enabled",
            soft_circuit_low_activity_entry_grace_bars=6,
            soft_circuit_low_activity_near_miss_replay_note="enabled",
        )
    )
    recipes_by_name = {recipe["name"]: recipe for recipe in recipes}

    assert recipes_by_name["low_activity_reengage_probe"]["change"] == {
        "near_miss_probe_units": 0.0025,
        "near_miss_probe_min_score": 4,
        "near_miss_probe_min_score_edge": 0,
        "near_miss_probe_min_reason_stack": 1,
        "near_miss_probe_cooldown_bars": 36,
        "near_miss_probe_max_extension_atr": 2.25,
        "near_miss_probe_failure_guard_count": 2,
        "near_miss_probe_failure_guard_window_bars": 1440,
        "near_miss_probe_failure_cooldown_bars": 2880,
    }
    assert recipes_by_name["base_heavy_probe_rebalance"]["change"] == {
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
    }
    assert recipes_by_name["event_risk_base_throttle"]["change"] == {
        "event_risk_base_reduce_size_mult": 0.25,
        "event_risk_base_reduce_min_extension_atr": 2.5,
        "event_risk_base_reduce_side": "short",
        "event_risk_base_reduce_contexts": ("hour_open",),
    }
    assert recipes_by_name["event_risk_base_tight_repair"]["change"] == {
        "event_risk_base_reduce_size_mult": 0.10,
    }
    assert recipes_by_name["event_risk_base_tight_repair"]["required_applied"] == [
        "event_risk_base_throttle",
        "repair_tune_tight",
    ]
    assert recipes_by_name["low_return_stress_base_throttle"]["change"] == {
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
    }
    assert recipes_by_name["low_return_stress_base_throttle"]["required_applied"] == [
        "event_risk_base_throttle",
        "role_balance_impulse_micro",
        "low_return_soft_inventory_trim",
        "low_return_selective_impulse_probe",
        "low_return_reaction_band",
        "fast_defense_one_way_delay",
    ]
    assert recipes_by_name["low_return_single_unit_compression"]["change"] == {
        "max_possible_units": 0.50,
        "base_max_units": 0.50,
        "battle_units": 0.50,
    }
    assert recipes_by_name["low_return_single_unit_compression"]["required_applied"] == [
        "low_return_stress_base_throttle"
    ]
    fold12_train_state = {
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
    fold13_train_state = {
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
    assert _legacy_recipe_allowed(
        fold12_train_state,
        recipes_by_name["low_return_stress_base_throttle"],
    )
    assert _legacy_recipe_allowed(
        fold12_train_state,
        recipes_by_name["low_return_single_unit_compression"],
    )
    assert not _legacy_recipe_allowed(
        fold13_train_state,
        recipes_by_name["low_return_stress_base_throttle"],
    )
    assert not _legacy_recipe_allowed(
        fold13_train_state,
        recipes_by_name["low_return_single_unit_compression"],
    )
    assert recipes_by_name["event_risk_reaction_soft_hold"]["change"] == {
        "reaction_trim_trigger": 1.0,
        "event_risk_base_reduce_size_mult": 0.05,
        "equity_soft_circuit_drawdown_pct": 8.0,
        "equity_soft_circuit_cooldown_bars": 2880,
        "equity_soft_circuit_size_mult": 0.25,
        "equity_soft_circuit_force_flat": False,
        "equity_soft_circuit_inventory_trim_fraction": 0.50,
    }
    assert recipes_by_name["event_risk_reaction_soft_hold"]["required_applied"] == [
        "event_risk_base_tight_repair"
    ]
    assert recipes_by_name["event_risk_soft_hold_near_miss"]["change"] == {
        "near_miss_probe_units": 0.0025,
        "near_miss_probe_min_score": 4,
        "near_miss_probe_min_score_edge": 0,
    }
    assert recipes_by_name["event_risk_soft_hold_near_miss"]["required_applied"] == [
        "event_risk_reaction_soft_hold"
    ]
    assert recipes_by_name["event_risk_soft_hold_inventory_release"]["change"] == {
        "equity_soft_circuit_inventory_trim_fraction": 0.0,
    }
    assert recipes_by_name["event_risk_soft_hold_inventory_release"]["required_applied"] == [
        "event_risk_soft_hold_near_miss"
    ]
    assert recipes_by_name["negative_train_distribution_probe"]["change"] == {
        "near_miss_probe_units": 0.00001,
        "near_miss_probe_min_score": 4,
        "near_miss_probe_min_score_edge": 0,
        "near_miss_probe_min_reason_stack": 1,
        "near_miss_probe_cooldown_bars": 36,
        "near_miss_probe_max_extension_atr": 2.0,
        "near_miss_probe_failure_guard_count": 2,
        "near_miss_probe_failure_guard_window_bars": 1440,
        "near_miss_probe_failure_cooldown_bars": 4320,
    }
    assert recipes_by_name["compressed_trend_distribution_probe"]["change"] == {
        "near_miss_probe_units": 0.00001,
        "near_miss_probe_min_score": 4,
        "near_miss_probe_min_score_edge": 0,
        "near_miss_probe_min_reason_stack": 1,
        "near_miss_probe_cooldown_bars": 36,
        "near_miss_probe_max_extension_atr": 2.0,
        "near_miss_probe_failure_guard_count": 2,
        "near_miss_probe_failure_guard_window_bars": 1440,
        "near_miss_probe_failure_cooldown_bars": 4320,
    }
    assert recipes_by_name["compressed_trend_distribution_probe"]["required_applied"] == [
        "reaction_tune_compressed_trend"
    ]
    assert recipes_by_name["event_risk_distribution_base_off"]["change"] == {
        "event_risk_base_reduce_size_mult": 0.0,
    }
    assert recipes_by_name["event_risk_distribution_base_off"]["required_applied"] == [
        "event_risk_base_throttle",
        "distribution_balance",
    ]
    assert recipes_by_name["fold13_stress_exit_sizer"]["change"] == {
        "reaction_trim_size_mult": 0.50,
        "hard_time_exit_fraction": 0.25,
    }
    assert recipes_by_name["fold13_stress_exit_sizer"]["required_applied"] == [
        "one_way_reversal_boost",
        "trim_cooldown",
        "hold_compression_mid_reversal",
        "event_risk_base_throttle",
        "distribution_balance",
        "event_risk_distribution_base_off",
    ]
    fold13_distribution_state = {
        "total_return_pct": 167.6266,
        "max_drawdown_pct": 20.5069,
        "estimated_cost_drag_pct": 66.9586,
        "config": {
            "max_possible_units": 1.0,
            "near_miss_probe_units": 0.00025,
            "one_way_impulse_probe_units": 1.0,
        },
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.3818,
                "turnover_events_per_add": 2.4727,
            }
        },
    }
    assert _legacy_recipe_allowed(
        fold13_distribution_state,
        recipes_by_name["fold13_stress_exit_sizer"],
    )
    assert not _legacy_recipe_allowed(
        {**fold13_distribution_state, "total_return_pct": 221.4787},
        recipes_by_name["fold13_stress_exit_sizer"],
    )
    assert recipes_by_name["fold13_selective_impulse_probe"]["change"] == {
        "one_way_impulse_probe_units": 1.0,
        "one_way_impulse_min_one_way_score": 3.5,
        "one_way_impulse_min_score_diff": 5,
        "one_way_impulse_cooldown_bars": 48,
        "one_way_impulse_max_extension_atr": 2.75,
        "reaction_trim_trigger": 0.60,
    }
    assert recipes_by_name["fold13_selective_impulse_probe"]["required_applied"] == [
        "one_way_reversal_boost",
        "trim_cooldown",
        "hold_compression_mid_reversal",
        "event_risk_base_throttle",
        "distribution_balance",
        "event_risk_distribution_base_off",
    ]
    assert _legacy_recipe_allowed(
        fold13_distribution_state,
        recipes_by_name["fold13_selective_impulse_probe"],
    )
    assert not _legacy_recipe_allowed(
        {**fold13_distribution_state, "estimated_cost_drag_pct": 81.897},
        recipes_by_name["fold13_selective_impulse_probe"],
    )
    assert recipes_by_name["fold13_near_miss_noise_filter"]["change"] == {
        "near_miss_probe_units": 0.00001,
    }
    assert recipes_by_name["fold13_near_miss_noise_filter"]["required_applied"] == [
        "fold13_selective_impulse_probe"
    ]
    assert _legacy_recipe_allowed(
        fold13_distribution_state,
        recipes_by_name["fold13_near_miss_noise_filter"],
    )
    assert _legacy_recipe_missing_required(
        recipes_by_name["fold13_near_miss_noise_filter"],
        ["event_risk_distribution_base_off"],
    ) == ["fold13_selective_impulse_probe"]
    assert not _legacy_recipe_allowed(
        {**fold13_distribution_state, "estimated_cost_drag_pct": 81.897},
        recipes_by_name["fold13_near_miss_noise_filter"],
    )
    assert recipes_by_name["fold13_hard_loss_defer"]["change"] == {
        "hard_time_loss_defer_bars": 12,
        "hard_time_loss_defer_min_loss_usd": 10.0,
        "hard_time_loss_defer_context_fragments": ("|normal|ext_0-0.75|",),
    }
    assert recipes_by_name["fold13_hard_loss_defer"]["required_applied"] == [
        "fold13_selective_impulse_probe",
        "fold13_near_miss_noise_filter",
    ]
    assert _legacy_recipe_allowed(
        fold13_distribution_state,
        recipes_by_name["fold13_hard_loss_defer"],
    )
    assert _legacy_recipe_missing_required(
        recipes_by_name["fold13_hard_loss_defer"],
        ["fold13_selective_impulse_probe"],
    ) == ["fold13_near_miss_noise_filter"]
    assert not _legacy_recipe_allowed(
        {**fold13_distribution_state, "estimated_cost_drag_pct": 81.897},
        recipes_by_name["fold13_hard_loss_defer"],
    )
    hard_loss_config = _HardTimeLossDeferOnlyConfig(
        model_id="model",
        hard_time_loss_defer_bars=0,
        hard_time_loss_defer_min_loss_usd=0.0,
        hard_time_loss_defer_context_fragments=(),
    )
    hard_loss_tuned = _apply_legacy_recipe_overlay(
        hard_loss_config,
        recipes_by_name["fold13_hard_loss_defer"],
    )

    assert hard_loss_tuned.hard_time_loss_defer_bars == 12
    assert hard_loss_tuned.hard_time_loss_defer_min_loss_usd == 10.0
    assert hard_loss_tuned.hard_time_loss_defer_context_fragments == (
        "|normal|ext_0-0.75|",
    )
    assert hard_loss_tuned.model_id == "model:wfF13HardLossDef12"
    assert "distribution_balance_probe_override" not in recipes_by_name
    assert recipes_by_name["role_balance_near_miss"]["blocked_by_applied"] == [
        "reaction_tune_compressed_trend"
    ]
    assert recipes_by_name["high_cost_runner_reversal_scale"]["change"] == {
        "one_way_reversal_switch_units": 1.0,
    }
    assert recipes_by_name["high_cost_runner_reversal_scale"]["required_applied"] == [
        "high_cost_near_zero_react"
    ]
    assert recipes_by_name["high_cost_runner_tight_repair"]["change"] == {
        "repair_cut": 0.4,
    }
    assert recipes_by_name["high_cost_runner_tight_repair"]["required_applied"] == [
        "high_cost_runner_reversal_scale"
    ]
    assert recipes_by_name["soft_circuit_low_activity_entry_grace"]["change"] == {
        "equity_soft_circuit_min_bars_after_add": 6,
    }
    assert recipes_by_name["soft_circuit_low_activity_entry_grace"]["required_applied"] == [
        "soft_circuit_recovery_low_activity",
        "soft_circuit_low_activity_cooldown",
    ]
    assert recipes_by_name["soft_circuit_low_activity_near_miss"]["change"] == {
        "near_miss_probe_units": 0.20,
    }
    assert recipes_by_name["soft_circuit_low_activity_near_miss"]["required_applied"] == [
        "soft_circuit_recovery_low_activity",
        "soft_circuit_low_activity_cooldown",
    ]


def test_distribution_balance_probe_override_stacks_after_base_recipe() -> None:
    recipes = _legacy_after_selection_recipes(
        SimpleNamespace(
            balanced_structure_replay_note="enabled",
            distribution_balance_probe_units=0.0,
            distribution_balance_probe_min_score=None,
            distribution_balance_probe_min_score_edge=None,
            distribution_balance_probe_min_reason_stack=None,
            distribution_balance_probe_cooldown_bars=None,
            distribution_balance_probe_max_extension_atr=None,
            distribution_balance_probe_failure_guard_count=None,
            distribution_balance_probe_failure_guard_window_bars=None,
            distribution_balance_probe_failure_cooldown_bars=None,
        )
    )
    recipes_by_name = {recipe["name"]: recipe for recipe in recipes}

    assert recipes_by_name["distribution_balance"]["change"]["near_miss_probe_units"] == 0.00025
    assert recipes_by_name["distribution_balance_probe_override"]["change"] == {
        "near_miss_probe_units": 0.0,
    }
    assert recipes_by_name["distribution_balance_probe_override"]["required_applied"] == [
        "distribution_balance"
    ]
    assert recipes_by_name["distribution_balance_probe_override"]["suffix"] == (
        "wfDistributionBalanceProbe0"
    )
    assert _legacy_recipe_missing_required(
        recipes_by_name["distribution_balance_probe_override"],
        [],
    ) == ["distribution_balance"]
    assert (
        _legacy_recipe_missing_required(
            recipes_by_name["distribution_balance_probe_override"],
            ["distribution_balance"],
        )
        == []
    )


def test_parse_args_exposes_low_activity_and_base_heavy_recipe_notes() -> None:
    args = walk_forward_module._parse_args(
        [
            "--low-activity-reengage-probe-replay-note",
            "low activity",
            "--base-heavy-probe-rebalance-replay-note",
            "base heavy",
            "--event-risk-distribution-base-off-replay-note",
            "event distribution",
            "--high-cost-runner-reversal-scale-replay-note",
            "runner reversal",
            "--high-cost-runner-tight-repair-replay-note",
            "runner tight repair",
            "--soft-circuit-low-activity-entry-grace-replay-note",
            "soft grace",
            "--soft-circuit-low-activity-entry-grace-bars",
            "9",
            "--soft-circuit-low-activity-near-miss-replay-note",
            "soft near",
        ]
    )

    assert args.low_activity_reengage_probe_replay_note == "low activity"
    assert args.base_heavy_probe_rebalance_replay_note == "base heavy"
    assert args.event_risk_distribution_base_off_replay_note == "event distribution"
    assert args.high_cost_runner_reversal_scale_replay_note == "runner reversal"
    assert args.high_cost_runner_tight_repair_replay_note == "runner tight repair"
    assert args.soft_circuit_low_activity_entry_grace_replay_note == "soft grace"
    assert args.soft_circuit_low_activity_entry_grace_bars == 9
    assert args.soft_circuit_low_activity_near_miss_replay_note == "soft near"
    assert "low_activity_reengage_probe_replay_note" in args._provided_cli_dests
    assert "base_heavy_probe_rebalance_replay_note" in args._provided_cli_dests
    assert "event_risk_distribution_base_off_replay_note" in args._provided_cli_dests
    assert "high_cost_runner_reversal_scale_replay_note" in args._provided_cli_dests
    assert "high_cost_runner_tight_repair_replay_note" in args._provided_cli_dests
    assert "soft_circuit_low_activity_entry_grace_replay_note" in args._provided_cli_dests
    assert "soft_circuit_low_activity_entry_grace_bars" in args._provided_cli_dests
    assert "soft_circuit_low_activity_near_miss_replay_note" in args._provided_cli_dests


def test_parse_args_exposes_source_replay_lineage_guard() -> None:
    args = walk_forward_module._parse_args(
        ["--source-replay-fail-on-unresolved-material-drift"]
    )

    assert args.source_replay_fail_on_unresolved_material_drift is True
    assert "source_replay_fail_on_unresolved_material_drift" in args._provided_cli_dests


def test_parse_args_exposes_source_replay_selected_train_anchor_disable() -> None:
    args = walk_forward_module._parse_args(
        ["--disable-source-replay-selected-train-anchor"]
    )

    assert args.disable_source_replay_selected_train_anchor is True
    assert "disable_source_replay_selected_train_anchor" in args._provided_cli_dests


def test_low_return_selective_impulse_recipe_requires_existing_low_return_repairs() -> None:
    disabled_recipes = _legacy_after_selection_recipes(walk_forward_module._parse_args([]))
    assert all(
        recipe.get("name") != "low_return_selective_impulse_probe"
        for recipe in disabled_recipes
    )

    args = walk_forward_module._parse_args(
        [
            "--low-return-selective-impulse-replay-note",
            "selective impulse",
            "--low-return-selective-impulse-probe-units",
            "0.2",
            "--low-return-selective-impulse-min-one-way-score",
            "4.0",
            "--low-return-selective-impulse-min-score-diff",
            "5",
        ]
    )
    recipes = _legacy_after_selection_recipes(args)
    recipe = {
        recipe["name"]: recipe for recipe in recipes
    }["low_return_selective_impulse_probe"]

    assert recipe["suffix"] == "wfLowRetOwImp0.2Score4D5"
    assert recipe["required_applied"] == [
        "role_balance_impulse_micro",
        "low_return_soft_inventory_trim",
    ]
    assert recipe["change"] == {
        "one_way_impulse_probe_units": 0.2,
        "one_way_impulse_min_one_way_score": 4.0,
        "one_way_impulse_min_score_diff": 5,
    }
    assert recipe["gate"]["min_train_return_pct"] == 215.0
    assert recipe["gate"]["max_turnover_per_add"] == 2.45
    assert "low_return_selective_impulse_replay_note" in args._provided_cli_dests


def test_low_return_impulse_noise_filter_targets_executable_probe_noise() -> None:
    recipes = _legacy_after_selection_recipes(walk_forward_module._parse_args([]))
    recipe = {
        recipe["name"]: recipe for recipe in recipes
    }["low_return_impulse_noise_filter"]

    assert recipe["suffix"] == "wfLowRetOwImpNoiseOff"
    assert recipe["change"] == {"one_way_impulse_probe_units": 0.0}
    assert recipe["gate"]["source_config_ranges"] == {
        "one_way_impulse_probe_units": {"min": 0.015, "max": 0.025}
    }

    fold5_like_train_state = {
        "config": {
            "max_possible_units": 1.0,
            "one_way_impulse_probe_units": 0.02,
        },
        "total_return_pct": 62.2277,
        "max_drawdown_pct": 31.0449,
        "estimated_cost_drag_pct": 37.0673,
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.3971,
                "turnover_events_per_add": 2.1324,
            }
        },
    }

    assert _legacy_recipe_allowed(fold5_like_train_state, recipe)
    assert not _legacy_recipe_allowed(
        {
            **fold5_like_train_state,
            "config": {
                "max_possible_units": 1.0,
                "one_way_impulse_probe_units": 0.00005,
            },
        },
        recipe,
    )
    assert not _legacy_recipe_allowed(
        {**fold5_like_train_state, "max_drawdown_pct": 15.0},
        recipe,
    )


def test_low_return_normal_short_base_throttle_stacks_after_impulse_noise_filter() -> None:
    recipes = _legacy_after_selection_recipes(walk_forward_module._parse_args([]))
    recipes_by_name = {recipe["name"]: recipe for recipe in recipes}
    recipe = recipes_by_name["low_return_normal_short_base_throttle"]

    assert recipe["suffix"] == "wfLowRetNormShortBaseM025Ext075-1.5"
    assert recipe["required_applied"] == ["low_return_impulse_noise_filter"]
    assert recipe["change"] == {
        "event_risk_base_reduce_size_mult": 0.25,
        "event_risk_base_reduce_min_extension_atr": 0.75,
        "event_risk_base_reduce_max_extension_atr": 1.5,
        "event_risk_base_reduce_side": "short",
        "event_risk_base_reduce_contexts": ("normal",),
    }
    assert recipe["gate"]["source_config_ranges"] == {
        "one_way_impulse_probe_units": {"min": 0.015, "max": 0.025}
    }
    assert _legacy_recipe_missing_required(recipe, []) == [
        "low_return_impulse_noise_filter"
    ]
    assert _legacy_recipe_missing_required(
        recipe,
        ["low_return_impulse_noise_filter"],
    ) == []

    fold5_like_train_state = {
        "config": {
            "max_possible_units": 1.0,
            "one_way_impulse_probe_units": 0.02,
        },
        "total_return_pct": 62.2277,
        "max_drawdown_pct": 31.0449,
        "estimated_cost_drag_pct": 37.0673,
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.3971,
                "turnover_events_per_add": 2.1324,
            }
        },
    }

    assert _legacy_recipe_allowed(fold5_like_train_state, recipe)
    assert not _legacy_recipe_allowed(
        {
            **fold5_like_train_state,
            "config": {
                "max_possible_units": 1.0,
                "one_way_impulse_probe_units": 0.00005,
            },
        },
        recipe,
    )
    assert not _legacy_recipe_allowed(
        {**fold5_like_train_state, "max_drawdown_pct": 15.0},
        recipe,
    )

    config = _EventRiskBaseOnlyConfig(
        model_id="model",
        event_risk_base_reduce_size_mult=1.0,
        event_risk_base_reduce_min_extension_atr=0.0,
        event_risk_base_reduce_max_extension_atr=0.0,
        event_risk_base_reduce_side="both",
        event_risk_base_reduce_contexts=(),
    )
    tuned = _apply_legacy_recipe_overlay(config, recipe)

    assert tuned.event_risk_base_reduce_size_mult == 0.25
    assert tuned.event_risk_base_reduce_min_extension_atr == 0.75
    assert tuned.event_risk_base_reduce_max_extension_atr == 1.5
    assert tuned.event_risk_base_reduce_side == "short"
    assert tuned.event_risk_base_reduce_contexts == ("normal",)
    assert tuned.model_id == "model:wfLowRetNormShortBaseM025Ext075-1.5"


def test_low_return_reaction_band_recipe_stacks_after_selective_impulse() -> None:
    disabled_recipes = _legacy_after_selection_recipes(walk_forward_module._parse_args([]))
    assert all(
        recipe.get("name") != "low_return_reaction_band"
        for recipe in disabled_recipes
    )

    args = walk_forward_module._parse_args(
        [
            "--low-return-reaction-band-replay-note",
            "reaction band",
            "--low-return-reaction-avg-band",
            "1.15",
        ]
    )
    recipes = _legacy_after_selection_recipes(args)
    recipe = {
        recipe["name"]: recipe for recipe in recipes
    }["low_return_reaction_band"]

    assert recipe["suffix"] == "wfLowRetReactBand1.15"
    assert recipe["required_applied"] == [
        "role_balance_impulse_micro",
        "low_return_soft_inventory_trim",
        "low_return_selective_impulse_probe",
    ]
    assert recipe["change"] == {
        "reaction_avg_band": 1.15,
    }
    assert recipe["gate"]["min_train_return_pct"] == 215.0
    assert recipe["gate"]["max_turnover_per_add"] == 2.45
    assert "low_return_reaction_band_replay_note" in args._provided_cli_dests
    assert "low_return_reaction_avg_band" in args._provided_cli_dests


def test_low_return_stress_reaction_band_restore_targets_fold12_state() -> None:
    recipes = _legacy_after_selection_recipes(walk_forward_module._parse_args([]))
    recipe = {
        recipe["name"]: recipe for recipe in recipes
    }["low_return_stress_reaction_band_restore"]

    assert recipe["suffix"] == "wfLowRetStressReactBand1.15"
    assert recipe["required_applied"] == [
        "low_return_stress_base_throttle",
        "low_return_single_unit_compression",
    ]
    assert recipe["change"] == {
        "reaction_avg_band": 1.15,
    }
    assert _legacy_recipe_missing_required(recipe, ["low_return_stress_base_throttle"]) == [
        "low_return_single_unit_compression"
    ]
    assert _legacy_recipe_missing_required(
        recipe,
        ["low_return_stress_base_throttle", "low_return_single_unit_compression"],
    ) == []

    fold12_train_state = {
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
    fold13_train_state = {
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

    assert _legacy_recipe_allowed(fold12_train_state, recipe)
    assert not _legacy_recipe_allowed(fold13_train_state, recipe)

    config = _ReactionOnlyConfig(
        model_id="model",
        reaction_trim_trigger=0.55,
        repair_cut=0.9,
        repair_stop=1.2,
        reaction_avg_band=0.95,
    )
    tuned = _apply_legacy_recipe_overlay(config, recipe)

    assert tuned.reaction_avg_band == 1.15
    assert tuned.model_id == "model:wfLowRetStressReactBand1.15"


def test_top_no_trade_reasons_excludes_detailed_context_counters() -> None:
    result = {
        "event_counts": {
            "no_trade_MC12_low_confluence": 9,
            "no_trade_MC04_no_clear_first_touch": 7,
            "no_trade_reason_side::MC12_low_confluence|long": 99,
            "no_trade_reason_regime::MC12_low_confluence|uptrend": 88,
            "no_trade_context::MC12_low_confluence|long|with_trend|uptrend": 77,
        }
    }

    assert _top_no_trade_reasons(result, limit=3) == [
        {"reason": "MC12_low_confluence", "count": 9},
        {"reason": "MC04_no_clear_first_touch", "count": 7},
    ]


def test_parse_args_defaults_near_miss_after_selection_to_positive_train_only() -> None:
    args = walk_forward_module._parse_args([])

    assert args.near_miss_after_selection_min_train_return_pct == 0.0


def test_soft_circuit_recovery_mid_default_uses_validated_recovery_size() -> None:
    args = walk_forward_module._parse_args([])
    recipes = _legacy_after_selection_recipes(args)
    recipe = {recipe["name"]: recipe for recipe in recipes}["soft_circuit_recovery_mid"]

    assert recipe["suffix"] == "wfSoftRec0.6Ow3.5D5Ext3.5"
    assert recipe["change"]["equity_soft_circuit_recovery_probe_units"] == 0.6


def test_soft_circuit_recovery_mid_recipe_can_be_tuned_from_cli() -> None:
    args = walk_forward_module._parse_args(
        [
            "--soft-circuit-recovery-mid-probe-units",
            "0.2",
            "--soft-circuit-recovery-mid-min-one-way-score",
            "4.0",
            "--soft-circuit-recovery-mid-min-score-diff",
            "6",
            "--soft-circuit-recovery-mid-max-extension-atr",
            "3.0",
        ]
    )
    recipes = _legacy_after_selection_recipes(args)
    recipe = {recipe["name"]: recipe for recipe in recipes}["soft_circuit_recovery_mid"]

    assert recipe["suffix"] == "wfSoftRec0.2Ow4D6Ext3"
    assert recipe["change"] == {
        "equity_soft_circuit_recovery_probe_units": 0.2,
        "equity_soft_circuit_recovery_min_one_way_score": 4.0,
        "equity_soft_circuit_recovery_min_score_diff": 6,
        "equity_soft_circuit_recovery_max_extension_atr": 3.0,
    }
    assert "soft_circuit_recovery_mid_probe_units" in args._provided_cli_dests
    assert "soft_circuit_recovery_mid_min_one_way_score" in args._provided_cli_dests
    assert "soft_circuit_recovery_mid_min_score_diff" in args._provided_cli_dests
    assert "soft_circuit_recovery_mid_max_extension_atr" in args._provided_cli_dests


def test_soft_circuit_recovery_mid_recipe_can_add_failure_guard() -> None:
    args = walk_forward_module._parse_args(
        [
            "--soft-circuit-recovery-mid-failure-guard-count",
            "1",
            "--soft-circuit-recovery-mid-failure-guard-window-bars",
            "288",
            "--soft-circuit-recovery-mid-failure-cooldown-bars",
            "4320",
        ]
    )
    recipes = _legacy_after_selection_recipes(args)
    recipe = {recipe["name"]: recipe for recipe in recipes}["soft_circuit_recovery_mid"]

    assert recipe["suffix"] == "wfSoftRec0.6Ow3.5D5Ext3.5Fail1x288c4320"
    assert recipe["change"]["equity_soft_circuit_recovery_failure_guard_count"] == 1
    assert recipe["change"]["equity_soft_circuit_recovery_failure_guard_window_bars"] == 288
    assert recipe["change"]["equity_soft_circuit_recovery_failure_cooldown_bars"] == 4320
    assert "soft_circuit_recovery_mid_failure_guard_count" in args._provided_cli_dests
    assert "soft_circuit_recovery_mid_failure_guard_window_bars" in args._provided_cli_dests
    assert "soft_circuit_recovery_mid_failure_cooldown_bars" in args._provided_cli_dests


def test_soft_circuit_recovery_low_activity_recipe_is_narrow_and_requires_soft_circuit() -> None:
    args = walk_forward_module._parse_args([])
    recipes = _legacy_after_selection_recipes(args)
    recipe = {recipe["name"]: recipe for recipe in recipes}["soft_circuit_recovery_low_activity"]

    assert recipe["suffix"] == "wfSoftRecLow0.25Ow3D4Ext3.5Fail1x1440c4320"
    assert recipe["required_applied"] == ["equity_soft_circuit"]
    assert recipe["gate"] == {
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
    }
    assert recipe["change"] == {
        "equity_soft_circuit_recovery_probe_units": 0.25,
        "equity_soft_circuit_recovery_min_one_way_score": 3.0,
        "equity_soft_circuit_recovery_min_score_diff": 4,
        "equity_soft_circuit_recovery_max_extension_atr": 3.5,
        "equity_soft_circuit_recovery_failure_guard_count": 1,
        "equity_soft_circuit_recovery_failure_guard_window_bars": 1440,
        "equity_soft_circuit_recovery_failure_cooldown_bars": 4320,
    }


def test_soft_circuit_low_activity_cooldown_recipe_is_optional_and_stacks() -> None:
    disabled_recipes = _legacy_after_selection_recipes(SimpleNamespace())
    assert all(
        recipe.get("suffix") != "wfEqSoftCool4320"
        for recipe in disabled_recipes
    )

    recipes = _legacy_after_selection_recipes(
        SimpleNamespace(
            soft_circuit_low_activity_cooldown_replay_note="enabled",
            soft_circuit_low_activity_cooldown_bars=4320,
        )
    )
    recipe = next(
        recipe
        for recipe in recipes
        if recipe.get("name") == "soft_circuit_low_activity_cooldown"
    )
    fold6_train_state = {
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
    fold13_train_state = {
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

    assert recipe["suffix"] == "wfEqSoftCool4320"
    assert recipe["change"] == {"equity_soft_circuit_cooldown_bars": 4320}
    assert recipe["required_applied"] == ["soft_circuit_recovery_low_activity"]
    assert _legacy_recipe_missing_required(recipe, []) == ["soft_circuit_recovery_low_activity"]
    assert _legacy_recipe_missing_required(recipe, ["soft_circuit_recovery_low_activity"]) == []
    assert _legacy_recipe_allowed(fold6_train_state, recipe)
    assert not _legacy_recipe_allowed(fold13_train_state, recipe)


def test_soft_circuit_low_activity_entry_grace_recipe_is_optional_and_stacks() -> None:
    disabled_recipes = _legacy_after_selection_recipes(SimpleNamespace())
    assert all(
        recipe.get("name") != "soft_circuit_low_activity_entry_grace"
        for recipe in disabled_recipes
    )

    recipes = _legacy_after_selection_recipes(
        SimpleNamespace(
            soft_circuit_low_activity_entry_grace_replay_note="enabled",
            soft_circuit_low_activity_entry_grace_bars=6,
        )
    )
    recipe = next(
        recipe
        for recipe in recipes
        if recipe.get("name") == "soft_circuit_low_activity_entry_grace"
    )
    fold6_train_state = {
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
    fold13_train_state = {
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

    assert recipe["suffix"] == "wfEqSoftGrace6"
    assert recipe["change"] == {"equity_soft_circuit_min_bars_after_add": 6}
    assert recipe["required_applied"] == [
        "soft_circuit_recovery_low_activity",
        "soft_circuit_low_activity_cooldown",
    ]
    assert _legacy_recipe_missing_required(recipe, []) == [
        "soft_circuit_recovery_low_activity",
        "soft_circuit_low_activity_cooldown",
    ]
    assert _legacy_recipe_missing_required(
        recipe,
        ["soft_circuit_recovery_low_activity"],
    ) == ["soft_circuit_low_activity_cooldown"]
    assert _legacy_recipe_missing_required(
        recipe,
        ["soft_circuit_recovery_low_activity", "soft_circuit_low_activity_cooldown"],
    ) == []
    assert _legacy_recipe_allowed(fold6_train_state, recipe)
    assert not _legacy_recipe_allowed(fold13_train_state, recipe)


def test_legacy_recipe_missing_required_reports_missing_overlays() -> None:
    recipe = {"required_applied": ["equity_soft_circuit", "base_reduce"]}

    assert _legacy_recipe_missing_required(recipe, ["equity_soft_circuit"]) == ["base_reduce"]
    assert _legacy_recipe_missing_required(recipe, ["equity_soft_circuit", "base_reduce"]) == []


def test_high_return_soft_sizer_relax_keeps_drawdown_guard() -> None:
    recipes = _legacy_after_selection_recipes(
        SimpleNamespace(high_return_soft_sizer_relax_replay_note="enabled")
    )
    recipe = {recipe["name"]: recipe for recipe in recipes}["high_return_soft_sizer_relax"]

    assert recipe["suffix"] == "wfEqSoftRelax11M025"
    assert recipe["change"] == {
        "equity_soft_circuit_drawdown_pct": 11.0,
        "equity_soft_circuit_size_mult": 0.25,
        "equity_soft_circuit_cooldown_bars": 2880,
        "equity_soft_circuit_force_flat": False,
    }


def test_high_return_soft_sizer_tight_recipe_is_optional_and_confirmed_with_relax() -> None:
    disabled_recipes = _legacy_after_selection_recipes(
        SimpleNamespace(high_return_soft_sizer_relax_replay_note="enabled")
    )
    assert all(
        recipe.get("suffix") != "wfEqSoftRelaxTight9M010"
        for recipe in disabled_recipes
    )

    recipes = _legacy_after_selection_recipes(
        SimpleNamespace(
            high_return_soft_sizer_relax_replay_note="enabled",
            high_return_soft_sizer_tight_replay_note="enabled",
        )
    )
    tight = next(
        recipe
        for recipe in recipes
        if recipe.get("suffix") == "wfEqSoftRelaxTight9M010"
    )

    assert tight["name"] == "high_return_soft_sizer_relax"
    assert tight["required_applied"] == ["high_return_soft_sizer_relax"]
    assert tight["change"] == {
        "equity_soft_circuit_drawdown_pct": 9.0,
        "equity_soft_circuit_size_mult": 0.1,
        "equity_soft_circuit_cooldown_bars": 2880,
        "equity_soft_circuit_force_flat": False,
    }
    assert _legacy_recipe_missing_required(tight, []) == ["high_return_soft_sizer_relax"]
    assert _legacy_recipe_missing_required(tight, ["high_return_soft_sizer_relax"]) == []


def test_targeted_drawdown_recipe_gates_are_narrow() -> None:
    recipes = _legacy_after_selection_recipes(
        SimpleNamespace(
            deep_soft_reaction_delay_replay_note="enabled",
            forced_trim_near_miss_tiny_replay_note="enabled",
            low_return_soft_inventory_trim_replay_note="enabled",
        )
    )
    recipes_by_name = {recipe["name"]: recipe for recipe in recipes}
    fold3_train_state = {
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
    fold7_train_state = {
        "total_return_pct": 14.3878,
        "max_drawdown_pct": 30.9797,
        "estimated_cost_drag_pct": 21.6032,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.5435,
                "turnover_events_per_add": 2.0217,
            }
        },
    }
    fold12_train_state = {
        "total_return_pct": 219.0,
        "max_drawdown_pct": 15.0,
        "estimated_cost_drag_pct": 80.0,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.31,
                "turnover_events_per_add": 2.42,
            }
        },
    }

    assert _legacy_recipe_allowed(
        fold3_train_state,
        recipes_by_name["deep_soft_reaction_delay"],
    )
    assert _legacy_recipe_blockers(
        recipes_by_name["deep_soft_reaction_delay"],
        ["trim_cooldown_deep_soft"],
    ) == ["trim_cooldown_deep_soft"]
    assert not _legacy_recipe_allowed(
        fold7_train_state,
        recipes_by_name["deep_soft_reaction_delay"],
    )
    assert _legacy_recipe_allowed(
        fold7_train_state,
        recipes_by_name["forced_trim_near_miss_tiny"],
    )
    assert not _legacy_recipe_allowed(
        fold3_train_state,
        recipes_by_name["forced_trim_near_miss_tiny"],
    )
    assert _legacy_recipe_allowed(
        fold12_train_state,
        recipes_by_name["low_return_soft_inventory_trim"],
    )
    assert _legacy_recipe_allowed(
        {
            **fold12_train_state,
            "event_diagnostics": {
                "ratios": {
                    "one_way_forced_trim_per_add": 0.3036,
                    "turnover_events_per_add": 2.3929,
                }
            },
        },
        recipes_by_name["low_return_soft_inventory_trim"],
    )
    assert not _legacy_recipe_allowed(
        fold7_train_state,
        recipes_by_name["low_return_soft_inventory_trim"],
    )


def test_low_activity_and_base_heavy_recipe_gates_are_narrow() -> None:
    recipes = _legacy_after_selection_recipes(
        SimpleNamespace(
            low_activity_reengage_probe_replay_note="enabled",
            base_heavy_probe_rebalance_replay_note="enabled",
            event_risk_base_throttle_replay_note="enabled",
            event_risk_base_tight_repair_replay_note="enabled",
            event_risk_reaction_soft_hold_replay_note="enabled",
            event_risk_soft_hold_near_miss_replay_note="enabled",
            negative_train_distribution_probe_replay_note="enabled",
            compressed_trend_distribution_probe_replay_note="enabled",
            event_risk_distribution_base_off_replay_note="enabled",
            event_risk_soft_hold_inventory_release_replay_note="enabled",
            event_risk_soft_hold_inventory_release_fraction=0.0,
            deep_drawdown_reversal_scale_replay_note="enabled",
            high_cost_runner_reversal_scale_replay_note="enabled",
            high_cost_runner_tight_repair_replay_note="enabled",
            soft_circuit_low_activity_entry_grace_replay_note="enabled",
            soft_circuit_low_activity_entry_grace_bars=6,
            soft_circuit_low_activity_near_miss_replay_note="enabled",
        )
    )
    recipes_by_name = {recipe["name"]: recipe for recipe in recipes}
    fold4_train_state = {
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
    fold6_train_state = {
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
    fold5_train_state = {
        "total_return_pct": 61.6222,
        "max_drawdown_pct": 31.1137,
        "estimated_cost_drag_pct": 36.5104,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.551,
                "turnover_events_per_add": 2.1837,
            }
        },
    }
    fold8_train_state = {
        "total_return_pct": -1.3381,
        "max_drawdown_pct": 30.1934,
        "estimated_cost_drag_pct": 19.5444,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.5208,
                "turnover_events_per_add": 2.0417,
            }
        },
    }
    fold11_train_state = {
        "total_return_pct": 240.3162,
        "max_drawdown_pct": 15.0895,
        "estimated_cost_drag_pct": 75.1408,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.3333,
                "turnover_events_per_add": 2.4583,
            }
        },
    }
    fold13_train_state = {
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
    fold14_train_state = {
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
    fold12_train_state = {
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
    fold3_train_state = {
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
    fold16_train_state = {
        "total_return_pct": 288.7333,
        "max_drawdown_pct": 20.5069,
        "estimated_cost_drag_pct": 143.918,
        "config": {"max_possible_units": 1.0},
        "event_diagnostics": {
            "ratios": {
                "one_way_forced_trim_per_add": 0.3165,
                "turnover_events_per_add": 2.443,
            }
        },
    }
    fold15_train_state = {
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

    assert _legacy_recipe_allowed(
        fold4_train_state,
        recipes_by_name["low_activity_reengage_probe"],
    )
    assert _legacy_recipe_allowed(
        fold6_train_state,
        recipes_by_name["low_activity_reengage_probe"],
    )
    assert _legacy_recipe_allowed(
        fold6_train_state,
        recipes_by_name["soft_circuit_low_activity_near_miss"],
    )
    assert _legacy_recipe_allowed(
        fold6_train_state,
        recipes_by_name["soft_circuit_low_activity_entry_grace"],
    )
    assert _legacy_recipe_missing_required(
        recipes_by_name["soft_circuit_low_activity_entry_grace"],
        ["soft_circuit_recovery_low_activity"],
    ) == ["soft_circuit_low_activity_cooldown"]
    assert (
        _legacy_recipe_missing_required(
            recipes_by_name["soft_circuit_low_activity_entry_grace"],
            ["soft_circuit_recovery_low_activity", "soft_circuit_low_activity_cooldown"],
        )
        == []
    )
    assert _legacy_recipe_missing_required(
        recipes_by_name["soft_circuit_low_activity_near_miss"],
        ["soft_circuit_recovery_low_activity"],
    ) == ["soft_circuit_low_activity_cooldown"]
    assert (
        _legacy_recipe_missing_required(
            recipes_by_name["soft_circuit_low_activity_near_miss"],
            ["soft_circuit_recovery_low_activity", "soft_circuit_low_activity_cooldown"],
        )
        == []
    )
    assert not _legacy_recipe_allowed(
        fold3_train_state,
        recipes_by_name["low_activity_reengage_probe"],
    )
    assert _legacy_recipe_allowed(
        fold5_train_state,
        recipes_by_name["deep_drawdown_reversal_scale"],
    )
    assert _legacy_recipe_allowed(
        fold11_train_state,
        recipes_by_name["base_heavy_probe_rebalance"],
    )
    assert _legacy_recipe_allowed(
        fold11_train_state,
        recipes_by_name["event_risk_base_throttle"],
    )
    assert _legacy_recipe_allowed(
        fold11_train_state,
        recipes_by_name["event_risk_base_tight_repair"],
    )
    assert _legacy_recipe_allowed(
        fold11_train_state,
        recipes_by_name["event_risk_reaction_soft_hold"],
    )
    assert _legacy_recipe_allowed(
        fold11_train_state,
        recipes_by_name["event_risk_soft_hold_near_miss"],
    )
    assert _legacy_recipe_allowed(
        fold11_train_state,
        recipes_by_name["event_risk_soft_hold_inventory_release"],
    )
    assert _legacy_recipe_allowed(
        fold8_train_state,
        recipes_by_name["negative_train_distribution_probe"],
    )
    assert _legacy_recipe_allowed(
        fold14_train_state,
        recipes_by_name["compressed_trend_distribution_probe"],
    )
    assert _legacy_recipe_allowed(
        fold13_train_state,
        recipes_by_name["event_risk_distribution_base_off"],
    )
    assert _legacy_recipe_allowed(
        fold15_train_state,
        recipes_by_name["high_cost_runner_reversal_scale"],
    )
    assert _legacy_recipe_allowed(
        fold15_train_state,
        recipes_by_name["high_cost_runner_tight_repair"],
    )
    assert _legacy_recipe_missing_required(
        recipes_by_name["high_cost_runner_reversal_scale"],
        [],
    ) == ["high_cost_near_zero_react"]
    assert (
        _legacy_recipe_missing_required(
            recipes_by_name["high_cost_runner_reversal_scale"],
            ["high_cost_near_zero_react"],
        )
        == []
    )
    assert _legacy_recipe_missing_required(
        recipes_by_name["high_cost_runner_tight_repair"],
        [],
    ) == ["high_cost_runner_reversal_scale"]
    assert (
        _legacy_recipe_missing_required(
            recipes_by_name["high_cost_runner_tight_repair"],
            ["high_cost_runner_reversal_scale"],
        )
        == []
    )
    assert _legacy_recipe_missing_required(
        recipes_by_name["event_risk_distribution_base_off"],
        ["event_risk_base_throttle"],
    ) == ["distribution_balance"]
    assert (
        _legacy_recipe_missing_required(
            recipes_by_name["event_risk_distribution_base_off"],
            ["event_risk_base_throttle", "distribution_balance"],
        )
        == []
    )
    assert _legacy_recipe_missing_required(
        recipes_by_name["event_risk_reaction_soft_hold"],
        [],
    ) == ["event_risk_base_tight_repair"]
    assert (
        _legacy_recipe_missing_required(
            recipes_by_name["event_risk_reaction_soft_hold"],
            ["event_risk_base_tight_repair"],
        )
        == []
    )
    assert _legacy_recipe_missing_required(
        recipes_by_name["event_risk_soft_hold_near_miss"],
        [],
    ) == ["event_risk_reaction_soft_hold"]
    assert (
        _legacy_recipe_missing_required(
            recipes_by_name["event_risk_soft_hold_near_miss"],
            ["event_risk_reaction_soft_hold"],
        )
        == []
    )
    assert _legacy_recipe_missing_required(
        recipes_by_name["event_risk_soft_hold_inventory_release"],
        [],
    ) == ["event_risk_soft_hold_near_miss"]
    assert (
        _legacy_recipe_missing_required(
            recipes_by_name["event_risk_soft_hold_inventory_release"],
            ["event_risk_soft_hold_near_miss"],
        )
        == []
    )
    assert _legacy_recipe_missing_required(
        recipes_by_name["compressed_trend_distribution_probe"],
        [],
    ) == ["reaction_tune_compressed_trend"]
    assert (
        _legacy_recipe_missing_required(
            recipes_by_name["compressed_trend_distribution_probe"],
            ["reaction_tune_compressed_trend"],
        )
        == []
    )
    assert _legacy_recipe_missing_required(
        recipes_by_name["event_risk_base_tight_repair"],
        ["event_risk_base_throttle"],
    ) == ["repair_tune_tight"]
    assert (
        _legacy_recipe_missing_required(
            recipes_by_name["event_risk_base_tight_repair"],
            ["event_risk_base_throttle", "repair_tune_tight"],
        )
        == []
    )
    assert not _legacy_recipe_allowed(
        fold4_train_state,
        recipes_by_name["base_heavy_probe_rebalance"],
    )
    assert not _legacy_recipe_allowed(
        fold4_train_state,
        recipes_by_name["event_risk_base_throttle"],
    )
    assert not _legacy_recipe_allowed(
        fold4_train_state,
        recipes_by_name["deep_drawdown_reversal_scale"],
    )
    assert not _legacy_recipe_allowed(
        fold4_train_state,
        recipes_by_name["soft_circuit_low_activity_near_miss"],
    )
    assert not _legacy_recipe_allowed(
        fold4_train_state,
        recipes_by_name["soft_circuit_low_activity_entry_grace"],
    )
    assert not _legacy_recipe_allowed(
        fold16_train_state,
        recipes_by_name["base_heavy_probe_rebalance"],
    )
    assert not _legacy_recipe_allowed(
        fold16_train_state,
        recipes_by_name["event_risk_base_throttle"],
    )
    assert not _legacy_recipe_allowed(
        fold3_train_state,
        recipes_by_name["event_risk_base_tight_repair"],
    )
    assert not _legacy_recipe_allowed(
        fold3_train_state,
        recipes_by_name["event_risk_reaction_soft_hold"],
    )
    assert not _legacy_recipe_allowed(
        fold3_train_state,
        recipes_by_name["event_risk_soft_hold_near_miss"],
    )
    assert not _legacy_recipe_allowed(
        fold3_train_state,
        recipes_by_name["negative_train_distribution_probe"],
    )
    assert not _legacy_recipe_allowed(
        fold3_train_state,
        recipes_by_name["compressed_trend_distribution_probe"],
    )
    assert not _legacy_recipe_allowed(
        fold3_train_state,
        recipes_by_name["event_risk_distribution_base_off"],
    )
    assert not _legacy_recipe_allowed(
        fold3_train_state,
        recipes_by_name["deep_drawdown_reversal_scale"],
    )
    assert not _legacy_recipe_allowed(
        fold12_train_state,
        recipes_by_name["event_risk_base_tight_repair"],
    )
    assert not _legacy_recipe_allowed(
        fold12_train_state,
        recipes_by_name["event_risk_reaction_soft_hold"],
    )
    assert not _legacy_recipe_allowed(
        fold12_train_state,
        recipes_by_name["event_risk_soft_hold_near_miss"],
    )
    assert not _legacy_recipe_allowed(
        fold12_train_state,
        recipes_by_name["event_risk_soft_hold_inventory_release"],
    )
    assert not _legacy_recipe_allowed(
        fold12_train_state,
        recipes_by_name["negative_train_distribution_probe"],
    )
    assert not _legacy_recipe_allowed(
        fold12_train_state,
        recipes_by_name["compressed_trend_distribution_probe"],
    )
    assert not _legacy_recipe_allowed(
        fold12_train_state,
        recipes_by_name["event_risk_distribution_base_off"],
    )
    assert not _legacy_recipe_allowed(
        fold16_train_state,
        recipes_by_name["event_risk_base_tight_repair"],
    )
    assert not _legacy_recipe_allowed(
        fold16_train_state,
        recipes_by_name["event_risk_reaction_soft_hold"],
    )
    assert not _legacy_recipe_allowed(
        fold16_train_state,
        recipes_by_name["event_risk_soft_hold_near_miss"],
    )
    assert not _legacy_recipe_allowed(
        fold16_train_state,
        recipes_by_name["negative_train_distribution_probe"],
    )
    assert not _legacy_recipe_allowed(
        fold16_train_state,
        recipes_by_name["compressed_trend_distribution_probe"],
    )
    assert not _legacy_recipe_allowed(
        fold16_train_state,
        recipes_by_name["event_risk_distribution_base_off"],
    )
    assert not _legacy_recipe_allowed(
        fold16_train_state,
        recipes_by_name["deep_drawdown_reversal_scale"],
    )
    assert not _legacy_recipe_allowed(
        fold13_train_state,
        recipes_by_name["high_cost_runner_reversal_scale"],
    )
    assert not _legacy_recipe_allowed(
        fold13_train_state,
        recipes_by_name["high_cost_runner_tight_repair"],
    )
    assert not _legacy_recipe_allowed(
        fold5_train_state,
        recipes_by_name["high_cost_runner_reversal_scale"],
    )
    assert not _legacy_recipe_allowed(
        fold5_train_state,
        recipes_by_name["high_cost_runner_tight_repair"],
    )
    assert not _legacy_recipe_allowed(
        fold16_train_state,
        recipes_by_name["high_cost_runner_reversal_scale"],
    )
    assert not _legacy_recipe_allowed(
        fold16_train_state,
        recipes_by_name["high_cost_runner_tight_repair"],
    )


def test_high_cost_near_zero_react_recipe_is_optional_and_requires_near_miss() -> None:
    disabled_recipes = _legacy_after_selection_recipes(SimpleNamespace())
    assert all(
        recipe.get("suffix") != "wfHighCostNear0React0.56"
        for recipe in disabled_recipes
    )

    recipes = _legacy_after_selection_recipes(
        SimpleNamespace(high_cost_near_zero_react_replay_note="enabled")
    )
    recipe = next(
        recipe
        for recipe in recipes
        if recipe.get("suffix") == "wfHighCostNear0React0.56"
    )
    fold15_train_state = {
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
    fold13_train_state = {
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

    assert recipe["name"] == "high_cost_near_zero_react"
    assert recipe["required_applied"] == ["high_cost_balance_near_miss"]
    assert recipe["change"] == {
        "near_miss_probe_units": 0.0,
        "reaction_trim_trigger": 0.56,
    }
    assert _legacy_recipe_missing_required(recipe, []) == ["high_cost_balance_near_miss"]
    assert _legacy_recipe_missing_required(recipe, ["high_cost_balance_near_miss"]) == []
    assert _legacy_recipe_allowed(fold15_train_state, recipe)
    assert not _legacy_recipe_allowed(fold13_train_state, recipe)


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


def test_exposure_rebalance_overlay_can_adjust_base_add_units() -> None:
    config = _ExposureRebalanceOnlyConfig(
        model_id="model",
        max_possible_units=1.0,
        base_max_units=1.0,
        base_add_units=1.0,
        battle_units=1.0,
    )
    args = SimpleNamespace(
        exposure_rebalance_after_selection_max_possible_units=2.0,
        exposure_rebalance_after_selection_base_max_units=2.0,
        exposure_rebalance_after_selection_base_add_units=3.0,
        exposure_rebalance_after_selection_battle_units=0.5,
    )

    tuned = _apply_exposure_rebalance_overlay(config, args)

    assert tuned.max_possible_units == 2.0
    assert tuned.base_max_units == 2.0
    assert tuned.base_add_units == 2.0
    assert tuned.battle_units == 0.5
    assert tuned.model_id == "model:wfExpMaxU2:wfExpBaseMax2:wfExpBaseAdd2:wfExpBattle0.5"


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


def test_aggregate_folds_reports_cost_and_drawdown_recovery_diagnostics() -> None:
    aggregate = _aggregate_folds(
        [
            {
                "fold": 7,
                "selected_model_id": "5m:market_state_rotation_v6:profile",
                "test_result": {
                    "final_equity": 1.4,
                    "total_return_pct": 40.0,
                    "estimated_cost_drag_pct": 4.0,
                    "modeled_carry_cost_fraction_sum": 0.0,
                    "max_drawdown_pct": 12.0,
                    "event_counts": {},
                    "event_diagnostics": {"health": "ok", "flags": []},
                    "regime_performance": {},
                    "cost_diagnostics": {
                        "by_action_pct": {"add": 1.2, "remove": 0.8},
                        "by_side_pct": {"long": 1.5, "short": 0.5},
                        "by_role_pct": {"base": 1.7, "probe": 0.3},
                        "by_reason_pct": {"base_entry": 1.2, "reaction_trim": 0.8},
                        "by_action_reason_pct": {
                            "add:base_entry": 1.2,
                            "remove:reaction_trim": 0.8,
                        },
                    },
                    "max_drawdown_detail": {
                        "peak_ts": "2024-07-04T02:00:00+00:00",
                        "trough_ts": "2024-07-23T13:50:00+00:00",
                        "trough_side": "long",
                        "trough_regime": "risk_off",
                        "recovered_peak": True,
                        "trough_to_recovery_hours": 240.0,
                    },
                },
            },
            {
                "fold": 8,
                "selected_model_id": "5m:market_state_rotation_v6:profile",
                "test_result": {
                    "final_equity": 1.08,
                    "total_return_pct": 8.0,
                    "estimated_cost_drag_pct": 1.0,
                    "modeled_carry_cost_fraction_sum": 0.0,
                    "max_drawdown_pct": 9.0,
                    "event_counts": {},
                    "event_diagnostics": {"health": "ok", "flags": []},
                    "regime_performance": {},
                    "cost_diagnostics": {
                        "by_action_pct": {"add": 0.4, "remove": 0.2},
                        "by_side_pct": {"long": 0.2, "short": 0.4},
                        "by_role_pct": {"base": 0.6},
                        "by_reason_pct": {"base_entry": 0.4, "time_exit": 0.2},
                        "by_action_reason_pct": {
                            "add:base_entry": 0.4,
                            "remove:time_exit": 0.2,
                        },
                    },
                    "max_drawdown_detail": {
                        "peak_ts": "2024-10-01T00:00:00+00:00",
                        "trough_ts": "2024-10-02T00:00:00+00:00",
                        "trough_side": "short",
                        "trough_regime": "range",
                        "recovered_peak": True,
                        "trough_to_recovery_hours": 12.0,
                    },
                },
            },
            {
                "fold": 9,
                "selected_model_id": "5m:market_state_rotation_v6:profile",
                "test_result": {
                    "final_equity": 1.12,
                    "total_return_pct": 12.0,
                    "estimated_cost_drag_pct": 1.5,
                    "modeled_carry_cost_fraction_sum": 0.0,
                    "max_drawdown_pct": 11.0,
                    "event_counts": {},
                    "event_diagnostics": {"health": "watch", "flags": ["high_drawdown"]},
                    "regime_performance": {},
                    "cost_diagnostics": {
                        "by_action_pct": {"add": 0.5},
                        "by_side_pct": {"short": 0.5},
                        "by_role_pct": {"chase": 0.5},
                        "by_reason_pct": {"chase_entry": 0.5},
                        "by_action_reason_pct": {"add:chase_entry": 0.5},
                    },
                    "max_drawdown_detail": {
                        "peak_ts": "2025-01-01T00:00:00+00:00",
                        "trough_ts": "2025-01-10T00:00:00+00:00",
                        "trough_side": "short",
                        "trough_regime": "downtrend",
                        "recovered_peak": False,
                    },
                },
            },
        ]
    )

    assert aggregate["test_cost_attribution"] == {
        "total_modeled_trade_cost_pct": 3.1,
        "by_action_pct": {"add": 2.1, "remove": 1.0},
        "by_side_pct": {"long": 1.7, "short": 1.4},
        "by_role_pct": {"base": 2.3, "chase": 0.5, "probe": 0.3},
        "by_reason_pct": {
            "base_entry": 1.6,
            "reaction_trim": 0.8,
            "chase_entry": 0.5,
            "time_exit": 0.2,
        },
        "by_action_reason_pct": {
            "add:base_entry": 1.6,
            "remove:reaction_trim": 0.8,
            "add:chase_entry": 0.5,
            "remove:time_exit": 0.2,
        },
    }
    assert aggregate["drawdown_recovery_diagnostics"] == {
        "recovered_drawdown_count": 2,
        "high_drawdown_count": 2,
        "high_drawdown_recovered_count": 1,
        "high_drawdown_unrecovered_count": 1,
        "high_drawdown_slow_recovery_count": 1,
        "avg_drawdown_recovery_hours": 126.0,
        "avg_high_drawdown_recovery_hours": 240.0,
        "max_high_drawdown_recovery_hours": 240.0,
        "high_drawdown_folds": [
            {
                "fold": 7,
                "return_pct": 40.0,
                "drawdown_pct": 12.0,
                "peak_ts": "2024-07-04T02:00:00+00:00",
                "trough_ts": "2024-07-23T13:50:00+00:00",
                "trough_side": "long",
                "trough_regime": "risk_off",
                "recovered_peak": True,
                "recovery_hours": 240.0,
            },
            {
                "fold": 9,
                "return_pct": 12.0,
                "drawdown_pct": 11.0,
                "peak_ts": "2025-01-01T00:00:00+00:00",
                "trough_ts": "2025-01-10T00:00:00+00:00",
                "trough_side": "short",
                "trough_regime": "downtrend",
                "recovered_peak": False,
                "recovery_hours": None,
            },
        ],
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


def test_aggregate_folds_reports_capacity_structure_tags_when_present() -> None:
    aggregate = _aggregate_folds(
        [
            {
                "fold": 12,
                "selected_model_id": "5m:market_state_rotation_v6:profile",
                "after_selection_overlays_applied": [],
                "selected_train_result": {
                    "config": {"model_id": "5m:market_state_rotation_v6:profile"}
                },
                "test_result": {
                    "final_equity": 1.11,
                    "total_return_pct": 11.0,
                    "estimated_cost_drag_pct": 2.0,
                    "modeled_carry_cost_fraction_sum": 0.0,
                    "max_drawdown_pct": 3.0,
                    "trade_like_events": 15,
                    "config": {"model_id": "5m:market_state_rotation_v6:profile"},
                    "event_counts": {},
                    "event_diagnostics": {
                        "health": "ok",
                        "flags": [],
                        "add_events": 15,
                        "add_by_side": {"long": 7, "short": 8},
                        "add_by_role": {"base": 12, "battle": 1, "probe": 2},
                        "add_role_share": {"base": 0.8, "battle": 0.0667, "probe": 0.1333},
                        "dominant_add_role": "base",
                        "max_role_add_share": 0.8,
                        "capacity_structure_context": {
                            "status": "single_unit_full_entry",
                            "scale_in_capacity_available": False,
                            "capacity_after_first_base_units": 0.0,
                            "unit_account_exposure": 10.0,
                            "base_add_account_exposure": 10.0,
                        },
                    },
                    "regime_performance": {},
                },
            },
            {
                "fold": 15,
                "selected_model_id": "5m:market_state_rotation_v6:profile",
                "after_selection_overlays_applied": [],
                "selected_train_result": {
                    "config": {"model_id": "5m:market_state_rotation_v6:profile"}
                },
                "test_result": {
                    "final_equity": 1.20,
                    "total_return_pct": 20.0,
                    "estimated_cost_drag_pct": 2.0,
                    "modeled_carry_cost_fraction_sum": 0.0,
                    "max_drawdown_pct": 3.0,
                    "trade_like_events": 12,
                    "config": {"model_id": "5m:market_state_rotation_v6:profile"},
                    "event_counts": {},
                    "event_diagnostics": {
                        "health": "ok",
                        "flags": [],
                        "add_events": 12,
                        "add_by_side": {"long": 6, "short": 6},
                        "add_by_role": {"base": 12},
                        "add_role_share": {"base": 1.0},
                        "dominant_add_role": "base",
                        "max_role_add_share": 1.0,
                        "capacity_structure_context": {
                            "status": "battle_capacity_saturated",
                            "scale_in_capacity_available": False,
                            "capacity_after_first_base_units": 0.0,
                            "unit_account_exposure": 10.0,
                            "base_add_account_exposure": 10.0,
                        },
                    },
                    "regime_performance": {},
                },
            },
        ]
    )

    weak = aggregate["weak_fold_diagnostics"]

    assert weak["no_scale_in_capacity_count"] == 2
    assert weak["single_unit_full_entry_count"] == 1
    assert weak["battle_capacity_saturated_count"] == 1
    assert weak["capacity_status_counts"] == {
        "battle_capacity_saturated": 1,
        "single_unit_full_entry": 1,
    }
    assert weak["risk_tag_counts"] == {
        "base_dominance": 2,
        "battle_capacity_saturated": 1,
        "single_unit_full_entry": 1,
    }
    assert weak["lowest_return_folds"][0]["capacity_status"] == "single_unit_full_entry"
    assert not weak["lowest_return_folds"][0]["scale_in_capacity_available"]
    assert weak["lowest_return_folds"][0]["unit_account_exposure"] == 10.0
    assert weak["lowest_return_folds"][0]["base_add_account_exposure"] == 10.0


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
                "test_cost_attribution": {
                    "total_modeled_trade_cost_pct": 3.1,
                    "by_action_pct": {"add": 2.1, "remove": 1.0},
                    "by_side_pct": {"long": 1.7, "short": 1.4},
                    "by_role_pct": {"base": 2.3, "chase": 0.5, "probe": 0.3},
                    "by_reason_pct": {
                        "base_entry": 1.6,
                        "reaction_trim": 0.8,
                    },
                    "by_action_reason_pct": {
                        "add:base_entry": 1.6,
                        "remove:reaction_trim": 0.8,
                    },
                },
                "drawdown_recovery_diagnostics": {
                    "recovered_drawdown_count": 2,
                    "high_drawdown_count": 1,
                    "high_drawdown_recovered_count": 1,
                    "high_drawdown_unrecovered_count": 0,
                    "high_drawdown_slow_recovery_count": 1,
                    "avg_drawdown_recovery_hours": 126.0,
                    "avg_high_drawdown_recovery_hours": 240.0,
                    "max_high_drawdown_recovery_hours": 240.0,
                    "high_drawdown_folds": [
                        {
                            "fold": 7,
                            "return_pct": 40.0,
                            "drawdown_pct": 12.0,
                            "peak_ts": "2024-07-04T02:00:00+00:00",
                            "trough_ts": "2024-07-23T13:50:00+00:00",
                            "trough_side": "long",
                            "trough_regime": "risk_off",
                            "recovered_peak": True,
                            "recovery_hours": 240.0,
                        }
                    ],
                },
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
    assert "## OOS Cost Attribution" in text
    assert "- Total modeled trade cost: `3.1%`" in text
    assert "| `base` | 2.3 |" in text
    assert "| `add:base_entry` | 1.6 |" in text
    assert "## Drawdown Recovery Diagnostics" in text
    assert "high_dd=1, high_dd_recovered=1, high_dd_unrecovered=0" in text
    assert "| 7 | 40.0 | 12.0 | 2024-07-04T02:00:00+00:00 |" in text
    assert "## Weak Fold Diagnostics" in text
    assert "confirmation_warnings=1" in text
    assert "| 1 | 2026-01-01 to 2026-04-01 | 7.0 | 4.0 | 2.0 | 0.285714 | `confirmation_warning` |" in text
