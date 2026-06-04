from scripts.run_market_state_rotation_v6_live_readiness import build_readiness_report


def _fold(
    fold: int,
    *,
    ret: float,
    dd: float,
    month: str,
    monthly_ret: float,
    health: str = "ok",
    flags: list[str] | None = None,
    max_role_share: float = 0.5,
    include_evidence: bool = False,
) -> dict:
    result = {
        "fold": fold,
        "test_start": f"2024-{fold:02d}-01",
        "test_end": f"2024-{fold:02d}-28",
        "test_result": {
            "total_return_pct": ret,
            "max_drawdown_pct": dd,
            "estimated_cost_drag_pct": 2.0,
            "trade_like_events": 12,
            "config": {"unit_account_exposure": 10.0},
            "monthly": {"monthly_returns": {month: monthly_ret}},
            "event_diagnostics": {
                "health": health,
                "flags": flags or [],
                "max_kst_hour_add_share": 0.12,
                "max_month_add_share": 0.20,
                "max_role_add_share": max_role_share,
                "add_by_kst_hour": {"09": 4, "10": 4, "11": 4},
            },
        },
    }
    if include_evidence:
        test_result = result["test_result"]
        test_result["calendar_rolling"] = {
            "daily_count": 90,
            "windows": {
                "30d": {
                    "count": 3,
                    "min_return_pct": 3.0,
                    "worst_window": {"start_day": "2024-01-01", "end_day": "2024-01-30", "return_pct": 3.0},
                },
                "60d": {
                    "count": 2,
                    "min_return_pct": 6.0,
                    "worst_window": {"start_day": "2024-01-01", "end_day": "2024-03-01", "return_pct": 6.0},
                },
                "90d": {
                    "count": 1,
                    "min_return_pct": 9.0,
                    "worst_window": {"start_day": "2024-01-01", "end_day": "2024-03-30", "return_pct": 9.0},
                },
            },
        }
        diagnostics = test_result["event_diagnostics"]
        diagnostics["remove_by_kst_hour"] = {"09": 2, "10": 1}
        diagnostics["realized_pnl_usd_units_by_kst_hour"] = {"09": 8.0, "10": 1.0}
    return result


def _stress_summary(
    *,
    min_return: float = 8.0,
    max_dd: float = 20.0,
    actionable_dd: float | None = None,
    protected_alpha_count: int = 0,
    verdict: str = "pass",
) -> dict:
    actionable = max_dd if actionable_dd is None else actionable_dd
    return {
        "summary": {
            "compounded_return_pct": 100.0,
            "avg_return_pct": 12.0,
            "min_return_pct": min_return,
            "max_drawdown_proxy_pct": max_dd,
            "max_actionable_drawdown_proxy_pct": actionable,
            "max_protected_alpha_drawdown_proxy_pct": max_dd if protected_alpha_count else 0.0,
            "protected_alpha_fold_count": protected_alpha_count,
            "positive_fold_count": 16,
            "fold_count": 16,
            "verdict": verdict,
        }
    }


def _walk_report(*, include_evidence: bool = False) -> dict:
    folds = [
        _fold(
            idx + 1,
            ret=12.0 + idx,
            dd=6.0,
            month=f"2024-{idx + 1:02d}",
            monthly_ret=0.03,
            include_evidence=include_evidence,
        )
        for idx in range(16)
    ]
    return {
        "symbol": "BTCUSDT",
        "exec_interval": "5m",
        "aggregate": {
            "compounded_oos_return_pct": 500.0,
            "avg_oos_return_pct": 18.0,
        },
        "folds": folds,
    }


def _stress_report(**overrides: dict) -> dict:
    scenarios = {
        "baseline": _stress_summary(),
        "fee6_slip2": _stress_summary(),
        "fee6_slip4": _stress_summary(),
        "cost_x2_funding3": _stress_summary(),
        "cost_x3_funding3": _stress_summary(),
    }
    for name, values in overrides.items():
        scenarios[name] = _stress_summary(**values)
    return {"scenarios": scenarios}


def test_live_readiness_blocks_full_live_without_required_evidence_even_when_history_passes() -> None:
    report = build_readiness_report(_walk_report(), _stress_report())

    assert report["stage"] == "paper_only"
    assert report["ready_for_full_live"] is False
    assert report["ready_for_paper"] is True
    assert "exact_rolling_30_60_90_day_equity_available" in report["blockers"]
    assert "kst_hour_realized_pnl_available" in report["blockers"]
    assert report["summary"]["fold_count"] == 16
    assert report["summary"]["losing_month_count"] == 0


def test_live_readiness_blocks_stressed_cost_drawdown_and_sets_size_cap() -> None:
    report = build_readiness_report(
        _walk_report(),
        _stress_report(
            cost_x3_funding3={
                "min_return": 1.0,
                "max_dd": 80.0,
                "actionable_dd": 80.0,
                "verdict": "fail",
            }
        ),
    )

    assert report["stage"] == "paper_only"
    assert "cost_x3_funding3_min_return_floor" in report["blockers"]
    assert "cost_x3_funding3_actionable_drawdown_proxy_cap" in report["blockers"]
    assert report["deployment_limits"]["recommended_max_size_multiplier"] == 0.25
    assert report["deployment_limits"]["recommended_effective_leverage_cap"] == 2.5
    assert report["deployment_limits"]["worst_actionable_stress_drawdown_proxy_pct"] == 80.0
    assert "cost_x3_funding3_actionable_drawdown_proxy_cap" in report["stage_blockers"]["tiny_canary"]


def test_live_readiness_warns_instead_of_blocking_protected_alpha_raw_drawdown() -> None:
    report = build_readiness_report(
        _walk_report(include_evidence=True),
        _stress_report(
            cost_x2_funding3={
                "min_return": 8.0,
                "max_dd": 80.0,
                "actionable_dd": 18.0,
                "protected_alpha_count": 1,
                "verdict": "fail",
            }
        ),
    )

    assert "cost_x2_funding3_actionable_drawdown_proxy_cap" not in report["blockers"]
    assert "cost_x2_funding3_protected_alpha_raw_drawdown_proxy_review" in report["warnings"]
    assert report["deployment_limits"]["worst_stress_drawdown_proxy_pct"] == 80.0
    assert report["deployment_limits"]["worst_actionable_stress_drawdown_proxy_pct"] == 20.0


def test_live_readiness_treats_positive_x3_tail_floor_as_tiny_canary_soft_blocker() -> None:
    report = build_readiness_report(
        _walk_report(include_evidence=True),
        _stress_report(
            cost_x2_funding3={"min_return": 8.0, "max_dd": 22.0, "actionable_dd": 22.0},
            cost_x3_funding3={"min_return": 1.0, "max_dd": 30.0, "actionable_dd": 30.0},
        ),
    )

    assert "cost_x3_funding3_min_return_floor" in report["blockers"]
    assert "cost_x3_funding3_min_return_floor" in report["stage_blockers"]["full_live"]
    assert "cost_x3_funding3_min_return_floor" not in report["stage_blockers"]["tiny_canary"]
    assert report["tiny_canary_soft_blocker_exemptions"][0]["name"] == "cost_x3_funding3_min_return_floor"
    assert report["stage_blockers"]["tiny_canary"] == ["live_or_paper_execution_parity_available"]
    assert [item["blocker"] for item in report["remediation_plan"]] == [
        "live_or_paper_execution_parity_available",
        "cost_x3_funding3_min_return_floor",
    ]


def test_live_readiness_accepts_backtest_evidence_but_still_requires_execution_parity() -> None:
    report = build_readiness_report(_walk_report(include_evidence=True), _stress_report())

    assert "exact_rolling_30_60_90_day_equity_available" not in report["blockers"]
    assert "kst_hour_realized_pnl_available" not in report["blockers"]
    assert "live_or_paper_execution_parity_available" in report["blockers"]
    assert report["summary"]["worst_exact_rolling"]["90d"]["fold_count_with_window"] == 16
    assert report["kst_hour_realized_pnl"]["available"] is True
    assert report["stage_blockers"]["paper"] == []
    assert report["stage_blockers"]["tiny_canary"] == ["live_or_paper_execution_parity_available"]
    assert report["remediation_plan"][0]["blocker"] == "live_or_paper_execution_parity_available"
    assert report["remediation_plan"][0]["nested_blockers"] == ["execution_parity_report_missing"]


def test_live_readiness_accepts_passing_execution_parity_report() -> None:
    report = build_readiness_report(
        _walk_report(include_evidence=True),
        _stress_report(),
        execution_parity_report={
            "summary": {
                "passed": True,
                "sample_count": 25,
                "min_sample_count": 20,
                "order_match_rate": 1.0,
                "max_signal_lag_bars": 0,
                "max_position_diff_units": 0.0,
            }
        },
        max_kst_hour_add_share=0.5,
    )

    assert report["stage"] == "full_live_ready"
    assert report["ready_for_full_live"] is True
    assert "live_or_paper_execution_parity_available" not in report["blockers"]
    assert report["execution_parity"]["passed"] is True


def test_live_readiness_accepts_existing_live_replay_parity_pass_payload() -> None:
    report = build_readiness_report(
        _walk_report(include_evidence=True),
        _stress_report(),
        execution_parity_report={
            "overall_status": "PASS",
            "symbol": "BTCUSDT",
            "active_contract": {"filters": {"strategy_families": ["market_state_rotation_v6"]}},
            "evaluation": {
                "status": "PASS",
                "reason": "live_flow_within_replay_baseline",
                "recent_live_intents": 7,
                "recent_live_submissions": 7,
                "live_vs_replay_flow_ratio": 0.94,
                "order_flow_status": "PASS",
                "order_flow_reason": "order_flow_clear",
            },
        },
        max_kst_hour_add_share=0.5,
    )

    assert report["stage"] == "full_live_ready"
    assert report["execution_parity"]["passed"] is True
    assert report["execution_parity"]["value"]["status"] == "PASS"
    assert report["execution_parity"]["value"]["sample_count"] == 7
    assert report["execution_parity"]["value"]["live_vs_replay_flow_ratio"] == 0.94


def test_live_readiness_rejects_execution_parity_for_other_strategy_family() -> None:
    report = build_readiness_report(
        _walk_report(include_evidence=True),
        _stress_report(),
        execution_parity_report={
            "overall_status": "PASS",
            "symbol": "BTCUSDT",
            "active_contract": {"filters": {"strategy_families": ["session_impulse_retest"]}},
            "evaluation": {
                "status": "PASS",
                "reason": "live_flow_within_replay_baseline",
                "recent_live_intents": 7,
                "recent_live_submissions": 7,
                "order_flow_status": "PASS",
            },
        },
    )

    assert report["stage"] == "paper_only"
    assert "live_or_paper_execution_parity_available" in report["blockers"]
    assert "execution_parity_strategy_family_mismatch" in report["execution_parity"]["blockers"]


def test_live_readiness_rejects_execution_parity_for_other_symbol() -> None:
    report = build_readiness_report(
        _walk_report(include_evidence=True),
        _stress_report(),
        execution_parity_report={
            "overall_status": "PASS",
            "symbol": "ETHUSDT",
            "active_contract": {"filters": {"strategy_families": ["market_state_rotation_v6"]}},
            "evaluation": {
                "status": "PASS",
                "reason": "live_flow_within_replay_baseline",
                "recent_live_intents": 7,
                "recent_live_submissions": 7,
                "order_flow_status": "PASS",
            },
        },
    )

    assert report["stage"] == "paper_only"
    assert "live_or_paper_execution_parity_available" in report["blockers"]
    assert "execution_parity_symbol_mismatch" in report["execution_parity"]["blockers"]


def test_live_readiness_rejects_evidence_floor_live_replay_parity_pass_payload() -> None:
    report = build_readiness_report(
        _walk_report(include_evidence=True),
        _stress_report(),
        execution_parity_report={
            "overall_status": "PASS",
            "evaluation": {
                "status": "PASS",
                "reason": "runtime_window_below_live_replay_parity_evidence_floor",
                "runtime_no_actionable_flow": True,
                "recent_live_intents": 0,
                "recent_live_submissions": 0,
                "order_flow_status": "PASS",
            },
        },
    )

    assert report["stage"] == "paper_only"
    assert "live_or_paper_execution_parity_available" in report["blockers"]
    assert report["execution_parity"]["passed"] is False
    assert report["execution_parity"]["blockers"] == [
        "runtime_window_below_execution_parity_evidence_floor"
    ]


def test_live_readiness_rejects_execution_parity_report_with_blockers() -> None:
    report = build_readiness_report(
        _walk_report(include_evidence=True),
        _stress_report(),
        execution_parity_report={
            "summary": {
                "passed": True,
                "sample_count": 25,
                "min_sample_count": 20,
                "blockers": ["position_drift"],
            }
        },
    )

    assert report["stage"] == "paper_only"
    assert "live_or_paper_execution_parity_available" in report["blockers"]
    assert report["execution_parity"]["blockers"] == ["position_drift"]
    assert report["remediation_plan"][0]["nested_blockers"] == ["position_drift"]


def test_live_readiness_remediation_plan_surfaces_execution_contract_fields() -> None:
    report = build_readiness_report(
        _walk_report(include_evidence=True),
        _stress_report(),
        execution_parity_report={
            "overall_status": "WATCH",
            "contract": {"symbol": "BTCUSDT", "expected_strategy_family": "market_state_rotation_v6"},
            "required_fields": {
                "decision_lineage_id": ["decision_id", "lineage_id"],
                "position_diff_units": ["position_diff_units"],
            },
            "summary": {
                "status": "WATCH",
                "passed": False,
                "symbol": "BTCUSDT",
                "strategy_families": ["market_state_rotation_v6"],
                "sample_count": 0,
                "min_sample_count": 20,
                "blockers": ["execution_journal_missing", "insufficient_execution_sample_count"],
            },
        },
    )

    plan = report["remediation_plan"][0]

    assert plan["blocker"] == "live_or_paper_execution_parity_available"
    assert plan["nested_blockers"] == [
        "execution_journal_missing",
        "insufficient_execution_sample_count",
    ]
    assert plan["required_fields"]["decision_lineage_id"] == ["decision_id", "lineage_id"]
    assert plan["contract"]["expected_strategy_family"] == "market_state_rotation_v6"


def test_live_readiness_remediation_plan_surfaces_stress_priority_folds() -> None:
    stress = _stress_report(
        cost_x3_funding3={
            "min_return": 1.0,
            "max_dd": 30.0,
            "actionable_dd": 30.0,
        }
    )
    stress["scenarios"]["cost_x3_funding3"]["summary"].update(
        {
            "stress_floor_gap_count": 1,
            "max_stress_floor_gap_pct": 4.0,
            "remediation_priority_folds": [
                {
                    "fold": 13,
                    "test_start": "2025-05-17",
                    "test_end": "2025-08-15",
                    "stressed_return_pct": 1.0,
                    "drawdown_proxy_pct": 28.0,
                    "stress_floor": {
                        "gross_return_gain_needed_pct": 4.0,
                        "baseline_cost_reduction_needed_pct": 1.3333,
                        "target_baseline_cost_reduction_share": 0.2,
                    },
                    "breakeven_cost_multiplier": 3.1,
                    "cost_to_gross_ratio": 0.32,
                    "root_causes": ["low_stress_return_buffer_le_5pct"],
                    "remediation_hints": ["raise_min_stress_return_before_adding_frequency"],
                    "top_cost_reasons": [{"name": "base_entry", "value": 2.1}],
                    "targeted_cost_reduction_plan": {
                        "needed_baseline_cost_cut_pct": 1.3333,
                        "planned_baseline_cost_cut_pct": 1.3333,
                        "projected_stressed_return_pct": 5.0,
                        "target_reached": True,
                        "steps": [{"reason": "v6_reaction_inventory_trim"}],
                    },
                }
            ],
        }
    )

    report = build_readiness_report(
        _walk_report(include_evidence=True),
        stress,
    )

    stress_plan = next(
        item for item in report["remediation_plan"] if item["blocker"] == "cost_x3_funding3_min_return_floor"
    )

    assert stress_plan["current_min_return_pct"] == 1.0
    assert stress_plan["max_stress_floor_gap_pct"] == 4.0
    assert stress_plan["priority_folds"][0]["fold"] == 13
    assert stress_plan["priority_folds"][0]["baseline_cost_reduction_needed_pct"] == 1.3333
    assert stress_plan["priority_folds"][0]["targeted_cost_reduction_plan"]["target_reached"] is True


def test_live_readiness_warns_when_exact_short_windows_are_not_all_positive() -> None:
    walk = _walk_report(include_evidence=True)
    walk["folds"][4]["test_result"]["calendar_rolling"]["windows"]["30d"]["min_return_pct"] = -7.6
    walk["folds"][4]["test_result"]["calendar_rolling"]["windows"]["30d"]["worst_window"] = {
        "start_day": "2024-05-01",
        "end_day": "2024-05-30",
        "return_pct": -7.6,
    }
    walk["folds"][0]["test_result"]["calendar_rolling"]["windows"]["60d"]["min_return_pct"] = -5.0

    report = build_readiness_report(walk, _stress_report())

    assert "exact_30d_rolling_loss_within_limit" not in report["blockers"]
    assert "exact_60d_rolling_loss_within_limit" not in report["blockers"]
    assert "all_exact_30d_windows_positive" in report["warnings"]
    assert "all_exact_60d_windows_positive" in report["warnings"]
    assert report["summary"]["worst_exact_rolling"]["30d"]["worst_min_return_pct"] == -7.6


def test_live_readiness_surfaces_calendar_and_concentration_warnings() -> None:
    walk = _walk_report()
    walk["folds"][0] = _fold(
        1,
        ret=12.0,
        dd=6.0,
        month="2024-01",
        monthly_ret=-0.10,
        flags=["role_concentration"],
        max_role_share=0.95,
    )

    report = build_readiness_report(walk, _stress_report())

    assert "worst_month_loss_within_limit" in report["blockers"]
    assert "no_fold_flags" in report["warnings"]
    assert "role_add_concentration" in report["warnings"]
