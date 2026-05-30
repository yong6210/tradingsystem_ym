from types import SimpleNamespace

from scripts.run_market_state_rotation_v6_walk_forward_validation import (
    _aggregate_folds,
    _equity_soft_sizer_after_selection_allowed,
    _exposure_rebalance_after_selection_allowed,
    _fragile_regime_entry_after_selection_allowed,
    _fragile_regime_inventory_trim_after_selection_allowed,
    _near_miss_after_selection_allowed,
    _one_way_impulse_after_selection_allowed,
    _one_way_reversal_after_selection_weak_allowed,
    _risk_smoothing_after_selection_allowed,
    _selection_score,
    _train_state_after_selection_allowed,
)


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
                "selected_train_result": {
                    "config": {
                        "model_id": "5m:market_state_rotation_v6:profile",
                        "max_hold_bars": 10,
                        "max_possible_units": 1.0,
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
                    },
                    "event_counts": {},
                    "event_diagnostics": {"health": "watch", "flags": ["month_concentration"]},
                    "regime_performance": {},
                },
            },
            {
                "selected_model_id": "5m:market_state_rotation_v6:profile",
                "selected_train_result": {
                    "config": {
                        "model_id": "5m:market_state_rotation_v6:profile",
                        "max_hold_bars": 11,
                        "max_possible_units": 1.0,
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
                    },
                    "event_counts": {},
                    "event_diagnostics": {
                        "health": "watch",
                        "flags": ["month_concentration", "too_few_orders"],
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
    assert aggregate["selected_hold_counts"] == {"11": 1, "20": 1}
    assert aggregate["selected_max_units_counts"] == {"1.0": 1, "1.5": 1}
