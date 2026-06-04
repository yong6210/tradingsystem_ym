from scripts.run_market_state_rotation_v6_stress_current_system import (
    StressScenario,
    _markdown_table,
    build_stress_report,
)


def _fold(
    fold: int,
    *,
    gross: float,
    net: float,
    cost: float,
    drawdown: float,
    avg_exposure: float = 1.0,
    years: float = 1.0,
    cost_diagnostics: dict | None = None,
    event_diagnostics: dict | None = None,
    regime_performance: dict | None = None,
) -> dict:
    result = {
        "gross_return_pct_before_costs": gross,
        "total_return_pct": net,
        "estimated_cost_drag_pct": cost,
        "max_drawdown_pct": drawdown,
        "avg_abs_account_exposure": avg_exposure,
        "years": years,
        "trade_like_events": 10,
    }
    if cost_diagnostics is not None:
        result["cost_diagnostics"] = cost_diagnostics
    if event_diagnostics is not None:
        result["event_diagnostics"] = event_diagnostics
    if regime_performance is not None:
        result["regime_performance"] = regime_performance
    return {
        "fold": fold,
        "test_start": f"2024-0{fold}-01",
        "test_end": f"2024-0{fold}-10",
        "after_selection_overlays_applied": ["equity_circuit"],
        "selected_train_result": {
            "gross_return_pct_before_costs": gross * 2.0,
            "total_return_pct": net * 2.0,
            "estimated_cost_drag_pct": cost * 2.0,
            "max_drawdown_pct": drawdown * 1.5,
            "trade_like_events": 20,
        },
        "test_result": result,
    }


def test_stress_report_scales_selected_fold_cost_drag() -> None:
    source = {
        "created_at": "2026-01-01T00:00:00+00:00",
        "symbol": "BTCUSDT",
        "exec_interval": "5m",
        "cost_model": {"fee_bps_per_side": 4.0, "slippage_bps_per_side": 1.0},
        "folds": [
            _fold(1, gross=30.0, net=20.0, cost=10.0, drawdown=7.0),
            _fold(2, gross=50.0, net=40.0, cost=10.0, drawdown=8.0),
        ],
    }

    report = build_stress_report(
        source,
        scenarios=[
            StressScenario("baseline", trade_cost_multiplier=1.0),
            StressScenario("cost_x2", trade_cost_multiplier=2.0),
        ],
    )

    assert report["baseline_summary"]["compounded_return_pct"] == 68.0
    assert report["scenarios"]["cost_x2"]["summary"]["compounded_return_pct"] == 43.0
    assert report["scenarios"]["cost_x2"]["folds"][0]["stressed_return_pct"] == 10.0
    assert report["scenarios"]["cost_x2"]["folds"][0]["drawdown_proxy_pct"] == 17.0
    assert report["scenarios"]["cost_x2"]["summary"]["drawdown_fragile_folds"][0]["fold"] == 2
    assert report["scenarios"]["cost_x2"]["summary"]["cost_fragile_folds"][0]["fold"] == 1
    assert report["min_breakeven_cost_multiplier"] == 3.0


def test_stress_report_marks_failed_when_cost_and_carry_break_a_fold() -> None:
    source = {
        "symbol": "BTCUSDT",
        "exec_interval": "5m",
        "cost_model": {"fee_bps_per_side": 4.0, "slippage_bps_per_side": 1.0},
        "folds": [
            _fold(1, gross=12.0, net=8.0, cost=4.0, drawdown=6.0, avg_exposure=1.0),
            _fold(2, gross=20.0, net=15.0, cost=5.0, drawdown=7.0, avg_exposure=1.0),
        ],
    }

    report = build_stress_report(
        source,
        scenarios=[StressScenario("harsh", trade_cost_multiplier=2.0, funding_bps_per_8h=5.0)],
    )

    summary = report["scenarios"]["harsh"]["summary"]

    assert summary["positive_fold_count"] < summary["fold_count"]
    assert summary["verdict"] == "fail"
    assert report["scenarios"]["harsh"]["folds"][0]["carry_drag_pct"] == 54.75


def test_stress_report_labels_low_positive_stress_buffer() -> None:
    source = {
        "symbol": "BTCUSDT",
        "exec_interval": "5m",
        "cost_model": {"fee_bps_per_side": 4.0, "slippage_bps_per_side": 1.0},
        "folds": [_fold(1, gross=17.0, net=13.0, cost=4.0, drawdown=6.0)],
    }

    report = build_stress_report(
        source,
        scenarios=[StressScenario("cost_x3", trade_cost_multiplier=3.0)],
    )

    row = report["scenarios"]["cost_x3"]["folds"][0]
    floor = row["stress_floor"]

    assert row["stressed_return_pct"] == 5.0
    assert floor["stress_buffer_to_floor_pct"] == 0.0
    assert floor["gross_return_gain_needed_pct"] == 0.0
    assert floor["baseline_cost_reduction_needed_pct"] == 0.0
    assert floor["target_baseline_cost_drag_pct"] == 4.0
    assert floor["floor_reachable_by_cost_cut"] is True
    assert "low_stress_return_buffer_le_5pct" in row["root_causes"]
    assert "raise_min_stress_return_before_adding_frequency" in row["remediation_hints"]


def test_stress_report_quantifies_floor_gap_when_cost_stress_is_too_high() -> None:
    source = {
        "symbol": "BTCUSDT",
        "exec_interval": "5m",
        "cost_model": {"fee_bps_per_side": 4.0, "slippage_bps_per_side": 1.0},
        "folds": [_fold(1, gross=20.0, net=12.0, cost=8.0, drawdown=6.0)],
    }

    report = build_stress_report(
        source,
        scenarios=[StressScenario("cost_x2", trade_cost_multiplier=2.0)],
    )

    row = report["scenarios"]["cost_x2"]["folds"][0]
    floor = row["stress_floor"]
    summary = report["scenarios"]["cost_x2"]["summary"]

    assert row["stressed_return_pct"] == 4.0
    assert floor["stress_buffer_to_floor_pct"] == -1.0
    assert floor["gross_return_gain_needed_pct"] == 1.0
    assert floor["baseline_cost_reduction_needed_pct"] == 0.5
    assert floor["target_baseline_cost_drag_pct"] == 7.5
    assert floor["target_baseline_cost_reduction_share"] == 0.0625
    assert summary["stress_floor_gap_count"] == 1
    assert summary["max_stress_floor_gap_pct"] == 1.0


def test_stress_report_builds_targeted_cost_reduction_plan_before_base_alpha_cut() -> None:
    source = {
        "symbol": "BTCUSDT",
        "exec_interval": "5m",
        "cost_model": {"fee_bps_per_side": 4.0, "slippage_bps_per_side": 1.0},
        "folds": [
            _fold(
                13,
                gross=24.0,
                net=17.0,
                cost=7.0,
                drawdown=8.0,
                cost_diagnostics={
                    "by_reason_pct": {
                        "base_entry": 2.5,
                        "v6_reaction_inventory_trim": 1.5,
                        "hard_intraday_time_exit": 1.0,
                    },
                },
                event_diagnostics={
                    "add_by_role": {"base": 5},
                    "realized_pnl_usd_units_by_role": {"base": 100.0},
                    "realized_pnl_usd_units_by_entry_context": {
                        "base|long|with_trend|uptrend|normal|ext_0-0.75|break_0-0.1": 100.0,
                    },
                },
            )
        ],
    }

    report = build_stress_report(
        source,
        scenarios=[StressScenario("cost_x3", trade_cost_multiplier=3.0)],
    )

    row = report["scenarios"]["cost_x3"]["folds"][0]
    plan = row["targeted_cost_reduction_plan"]
    summary = report["scenarios"]["cost_x3"]["summary"]

    assert row["stressed_return_pct"] == 3.0
    assert plan["target_reached"] is True
    assert plan["needed_baseline_cost_cut_pct"] == 0.6667
    assert plan["planned_baseline_cost_cut_pct"] == 0.6667
    assert plan["projected_stressed_return_pct"] == 5.0
    assert [step["reason"] for step in plan["steps"]] == [
        "hard_intraday_time_exit",
        "v6_reaction_inventory_trim",
    ]
    assert "base_entry_cost_is_alpha_engine" in row["tradeoff_tags"]
    assert summary["targeted_plan_resolved_floor_gap_count"] == 1
    assert summary["targeted_plan_unresolved_floor_gap_count"] == 0


def test_stress_report_attaches_fragility_root_cause_diagnostics() -> None:
    source = {
        "symbol": "BTCUSDT",
        "exec_interval": "5m",
        "cost_model": {"fee_bps_per_side": 4.0, "slippage_bps_per_side": 1.0},
        "folds": [
            _fold(
                1,
                gross=25.0,
                net=16.0,
                cost=9.0,
                drawdown=8.0,
                cost_diagnostics={
                    "modeled_trade_cost_pct": 7.5,
                    "by_reason_pct": {
                        "base_entry": 2.25,
                        "v6_reaction_inventory_trim": 1.75,
                        "one_way_against_forced_trim": 1.0,
                    },
                    "by_role_pct": {"base": 5.0},
                },
                event_diagnostics={
                    "health": "ok",
                    "add_events": 20,
                    "remove_events": 50,
                    "ratios": {"turnover_events_per_add": 2.5},
                    "capacity_structure_context": {
                        "status": "battle_capacity_saturated",
                        "scale_in_capacity_available": False,
                    },
                },
                regime_performance={
                    "downtrend": {"return_pct": 9.0, "max_drawdown_pct": 4.0, "add_events": 8},
                    "uptrend": {"return_pct": 3.0, "max_drawdown_pct": 7.0, "add_events": 4},
                },
            )
        ],
    }

    report = build_stress_report(
        source,
        scenarios=[StressScenario("harsh", trade_cost_multiplier=3.0, funding_bps_per_8h=1.0)],
    )

    row = report["scenarios"]["harsh"]["folds"][0]
    diagnostics = row["source_diagnostics"]

    assert row["cost_to_gross_ratio"] == 0.36
    assert "thin_cost_buffer_lt_3_25x" in row["root_causes"]
    assert "stress_breaks_positive_return" in row["root_causes"]
    assert row["top_cost_reasons"][0] == {"name": "base_entry", "value": 2.25}
    assert diagnostics["event_structure"]["capacity"]["status"] == "battle_capacity_saturated"
    assert diagnostics["regime_structure"]["top_return_regimes"][0]["regime"] == "downtrend"
    assert report["scenarios"]["harsh"]["summary"]["root_cause_counts"][
        "single_unit_capacity_saturated"
    ] == 1


def test_stress_report_marks_high_cost_alpha_engine_tradeoff() -> None:
    source = {
        "symbol": "BTCUSDT",
        "exec_interval": "5m",
        "cost_model": {"fee_bps_per_side": 4.0, "slippage_bps_per_side": 1.0},
        "folds": [
            _fold(
                15,
                gross=240.0,
                net=200.0,
                cost=40.0,
                drawdown=10.0,
                cost_diagnostics={
                    "by_reason_pct": {
                        "base_entry": 4.0,
                        "v6_reaction_inventory_trim": 3.0,
                    },
                },
                event_diagnostics={
                    "capacity_structure_context": {
                        "status": "battle_capacity_saturated",
                        "scale_in_capacity_available": False,
                    },
                },
            )
        ],
    }

    report = build_stress_report(
        source,
        scenarios=[StressScenario("cost_x3", trade_cost_multiplier=3.0)],
    )

    row = report["scenarios"]["cost_x3"]["folds"][0]
    summary = report["scenarios"]["cost_x3"]["summary"]

    assert "high_cost_high_alpha_engine" in row["tradeoff_tags"]
    assert "dd_proxy_from_cost_stress_not_return_failure" in row["tradeoff_tags"]
    assert "reaction_trim_part_of_alpha_engine" in row["tradeoff_tags"]
    assert "test_right_sizing_or_staggered_scale_out_before_blanket_cost_cuts" in row[
        "remediation_hints"
    ]
    assert "validate_replay_drawdown_before_killing_alpha" in row["remediation_hints"]
    assert summary["tradeoff_tag_counts"]["alpha_engine_high_return"] == 1
    assert summary["remediation_hint_counts"][
        "test_selective_capacity_extension_with_dd_guard"
    ] == 1
    assert summary["protected_alpha_fold_count"] == 1
    assert summary["max_actionable_drawdown_proxy_pct"] == 0.0
    assert summary["actionable_drawdown_verdict"] == "pass"
    assert summary["drawdown_verdict"] == "fail"
    assert summary["verdict"] == "watch"
    assert summary["max_protected_alpha_drawdown_proxy_pct"] == row["drawdown_proxy_pct"]
    assert summary["protected_alpha_folds"][0]["fold"] == 15
    assert summary["remediation_priority_folds"] == []


def test_stress_report_keeps_actionable_drawdown_when_non_alpha_fold_is_fragile() -> None:
    source = {
        "symbol": "BTCUSDT",
        "exec_interval": "5m",
        "cost_model": {"fee_bps_per_side": 4.0, "slippage_bps_per_side": 1.0},
        "folds": [
            _fold(
                15,
                gross=240.0,
                net=200.0,
                cost=40.0,
                drawdown=10.0,
                cost_diagnostics={"by_reason_pct": {"base_entry": 4.0}},
            ),
            _fold(
                2,
                gross=50.0,
                net=40.0,
                cost=10.0,
                drawdown=20.0,
            ),
        ],
    }

    report = build_stress_report(
        source,
        scenarios=[StressScenario("cost_x3", trade_cost_multiplier=3.0)],
    )

    rows = report["scenarios"]["cost_x3"]["folds"]
    summary = report["scenarios"]["cost_x3"]["summary"]
    actionable_row = next(row for row in rows if row["fold"] == 2)

    assert summary["max_drawdown_proxy_pct"] == 90.0
    assert summary["max_actionable_drawdown_proxy_pct"] == actionable_row["drawdown_proxy_pct"]
    assert summary["actionable_drawdown_verdict"] == "fail"
    assert summary["verdict"] == "fail"
    assert summary["protected_alpha_fold_count"] == 1
    assert summary["actionable_drawdown_fragile_folds"][0]["fold"] == 2
    assert summary["remediation_priority_folds"][0]["fold"] == 2


def test_stress_report_distinguishes_base_alpha_cost_from_probe_leak() -> None:
    source = {
        "symbol": "BTCUSDT",
        "exec_interval": "5m",
        "cost_model": {"fee_bps_per_side": 4.0, "slippage_bps_per_side": 1.0},
        "folds": [
            _fold(
                13,
                gross=28.0,
                net=18.0,
                cost=10.0,
                drawdown=9.0,
                cost_diagnostics={
                    "by_reason_pct": {
                        "base_entry": 2.5,
                        "v6_reaction_inventory_trim": 1.0,
                    },
                },
                event_diagnostics={
                    "add_by_role": {"base": 8, "probe": 5, "chase": 1},
                    "realized_pnl_usd_units_by_role": {
                        "base": 120.0,
                        "probe": -2.0,
                        "chase": 4.0,
                    },
                    "realized_pnl_usd_units_by_entry_context": {
                        "base|long|with_trend|uptrend|normal|ext_0-0.75|break_0-0.1": 80.0,
                        "base|short|with_trend|downtrend|normal|ext_2.5-4|break_0-0.1": 40.0,
                        "probe|long|neutral|range_or_transition|normal|ext_0.75-1.5|near_miss": -1.5,
                        "probe|short|with_trend|downtrend|normal|ext_1.5-2.5|near_miss": -0.5,
                        "chase|short|with_trend|one_way_short|normal|ext_1.5-2.5|break_0.1-0.5": 4.0,
                    },
                    "realized_pnl_usd_units_per_add_by_entry_context": {
                        "probe|long|neutral|range_or_transition|normal|ext_0.75-1.5|near_miss": -1.5,
                        "probe|short|with_trend|downtrend|normal|ext_1.5-2.5|near_miss": -0.5,
                    },
                },
            )
        ],
    }

    report = build_stress_report(
        source,
        scenarios=[StressScenario("cost_x3", trade_cost_multiplier=3.0)],
    )

    row = report["scenarios"]["cost_x3"]["folds"][0]
    diagnostics = row["source_diagnostics"]
    actionability = diagnostics["alpha_actionability"]
    summary = report["scenarios"]["cost_x3"]["summary"]

    assert row["stressed_return_pct"] == -2.0
    assert actionability["positive_base_alpha"] is True
    assert actionability["negative_probe_alpha"] is True
    assert actionability["tiny_negative_probe_alpha"] is False
    assert actionability["positive_chase_alpha"] is True
    assert actionability["probe_loss_to_base_pnl_ratio"] == 0.016667
    assert actionability["base_role_pnl_usd_units"] == 120.0
    assert actionability["worst_probe_contexts"][0]["value"] == -1.5
    assert "probe_realized_pnl_negative" in row["root_causes"]
    assert "base_entry_cost_is_alpha_engine" in row["tradeoff_tags"]
    assert "probe_alpha_leak" in row["tradeoff_tags"]
    assert "chase_context_adds_alpha" in row["tradeoff_tags"]
    assert "avoid_blanket_base_entry_cuts" in row["remediation_hints"]
    assert "test_probe_suppression_before_base_cuts" in row["remediation_hints"]
    assert "cut_marginal_probe_or_negative_context_entries" in row["remediation_hints"]
    assert "cut_marginal_entries_or_reduce_turnover" not in row["remediation_hints"]
    assert summary["tradeoff_tag_counts"]["base_entry_cost_is_alpha_engine"] == 1
    assert summary["remediation_hint_counts"]["avoid_blanket_base_entry_cuts"] == 1


def test_stress_report_marks_tiny_probe_leak_as_distribution_tradeoff() -> None:
    source = {
        "symbol": "BTCUSDT",
        "exec_interval": "5m",
        "cost_model": {"fee_bps_per_side": 4.0, "slippage_bps_per_side": 1.0},
        "folds": [
            _fold(
                13,
                gross=28.0,
                net=18.0,
                cost=10.0,
                drawdown=9.0,
                cost_diagnostics={"by_reason_pct": {"base_entry": 2.5}},
                event_diagnostics={
                    "add_by_role": {"base": 15, "probe": 10},
                    "realized_pnl_usd_units_by_role": {
                        "base": 2600.0,
                        "probe": -0.4,
                    },
                    "realized_pnl_usd_units_by_entry_context": {
                        "base|long|with_trend|uptrend|normal|ext_0-0.75|break_0-0.1": 2600.0,
                        "probe|short|with_trend|downtrend|normal|ext_1.5-2.5|near_miss": -0.4,
                    },
                },
            )
        ],
    }

    report = build_stress_report(
        source,
        scenarios=[StressScenario("cost_x3", trade_cost_multiplier=3.0)],
    )

    row = report["scenarios"]["cost_x3"]["folds"][0]
    actionability = row["source_diagnostics"]["alpha_actionability"]

    assert actionability["negative_probe_alpha"] is True
    assert actionability["tiny_negative_probe_alpha"] is True
    assert actionability["probe_loss_to_base_pnl_ratio"] == 0.000154
    assert "probe_alpha_leak" in row["tradeoff_tags"]
    assert "probe_leak_tiny_vs_base_alpha" in row["tradeoff_tags"]
    assert "treat_probe_suppression_as_distribution_tradeoff" in row["remediation_hints"]
    assert "test_probe_suppression_before_base_cuts" not in row["remediation_hints"]


def test_stress_markdown_surfaces_root_causes_and_top_cost_reasons() -> None:
    source = {
        "symbol": "BTCUSDT",
        "exec_interval": "5m",
        "cost_model": {"fee_bps_per_side": 4.0, "slippage_bps_per_side": 1.0},
        "folds": [
            _fold(
                1,
                gross=25.0,
                net=16.0,
                cost=9.0,
                drawdown=8.0,
                cost_diagnostics={"by_reason_pct": {"base_entry": 2.25}},
            )
        ],
    }

    report = build_stress_report(source, scenarios=[StressScenario("harsh", trade_cost_multiplier=3.0)])
    markdown = _markdown_table(report)

    assert "## Root Cause Counts" in markdown
    assert "## Tradeoff Tag Counts" in markdown
    assert "## Remediation Hint Counts" in markdown
    assert "## Drawdown Fragile Folds" in markdown
    assert "## Cost Fragile Folds" in markdown
    assert "## Protected Alpha Folds" in markdown
    assert "## Remediation Priority Folds" in markdown
    assert "Floor gaps" in markdown
    assert "Need gross %" in markdown
    assert "Need cost cut %" in markdown
    assert "thin_cost_buffer_lt_3_25x" in markdown
    assert "base_entry=2.25" in markdown
