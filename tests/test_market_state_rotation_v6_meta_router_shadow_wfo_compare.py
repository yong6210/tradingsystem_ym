from datetime import UTC, datetime

from scripts.run_market_state_rotation_v6_meta_router_shadow_wfo_compare import (
    build_meta_router_shadow_wfo_compare,
)


def _fold(
    number: int,
    return_pct: float,
    drawdown_pct: float,
    cost_pct: float,
    events: int,
    *,
    model_id: str | None = None,
    add_by_role: dict[str, int] | None = None,
    add_by_side: dict[str, int] | None = None,
) -> dict:
    return {
        "fold": number,
        "selected_model_id": model_id,
        "test_result": {
            "model_id": model_id,
            "total_return_pct": return_pct,
            "max_drawdown_pct": drawdown_pct,
            "estimated_cost_drag_pct": cost_pct,
            "trade_like_events": events,
            "event_diagnostics": {
                "health": "ok",
                "add_by_role": add_by_role or {"base": 2, "chase": 1},
                "add_by_side": add_by_side or {},
                "add_by_router_mode": {"trend_reaction": 2, "one_way_chase": 1},
                "remove_by_router_mode": {"trend_reaction": 1},
                "flags": [],
            },
            "router_mode_performance": {
                "trend_reaction": {
                    "bars": 10,
                    "exposed_bars": 4,
                    "return_pct": return_pct,
                    "max_drawdown_pct": drawdown_pct,
                    "add_events": 2,
                    "remove_events": 1,
                }
            },
        },
    }


def test_meta_router_shadow_compare_uses_common_folds_and_blocks_return_giveback() -> None:
    source = {"folds": [_fold(1, 20.0, 5.0, 2.0, 10), _fold(2, 30.0, 6.0, 2.5, 12)]}
    candidate = {"folds": [_fold(2, 24.0, 6.2, 2.6, 12)], "source_replay_lineage_guard": {"status": "watch"}}

    report = build_meta_router_shadow_wfo_compare(
        source_report=source,
        candidate_reports=[("router_contract_conservative", candidate, "reports/candidate.json")],
        min_formal_folds=2,
        max_return_giveback_pct=3.0,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    row = report["candidates"][0]
    assert report["no_live_order_sent"] is True
    assert row["candidate"]["folds"] == [2]
    assert row["common_fold_baseline"]["compounded_return_pct"] == 30.0
    assert row["candidate"]["return_delta_vs_baseline_pct"] == -6.0
    assert row["decision"] == "retune_or_reject_current_recipe"
    assert "return_giveback_exceeds_gate" in row["decision_reasons"]
    assert report["performance_upgrade_status"] == "no_performance_upgrade_candidate_found"
    assert report["performance_upgrade_candidate_count"] == 0
    assert report["performance_upgrade_smoke_candidate_count"] == 0
    assert report["risk_compression_status"] == "no_risk_compression_candidate_found"
    assert report["risk_compression_candidate_count"] == 0
    assert report["risk_compression_smoke_candidate_count"] == 0


def test_meta_router_shadow_compare_sends_smoke_pass_to_formal_wfo() -> None:
    source = {"folds": [_fold(3, 10.0, 5.0, 2.0, 10)]}
    candidate = {"folds": [_fold(3, 9.0, 5.2, 2.1, 10)], "source_replay_lineage_guard": {"status": "watch"}}

    report = build_meta_router_shadow_wfo_compare(
        source_report=source,
        candidate_reports=[("router_contract_observe_only", candidate, "reports/candidate.json")],
        min_formal_folds=12,
        max_return_giveback_pct=3.0,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    row = report["candidates"][0]
    assert row["decision"] == "smoke_pass_run_formal_wfo"
    assert row["candidate"]["return_delta_vs_baseline_pct"] == -1.0
    assert row["candidate"]["router_mode_summary"]["active_modes"] == ["trend_reaction"]
    assert report["best_performance_upgrade_candidate"] is None
    assert report["best_risk_compression_candidate"] is None
    assert report["best_risk_compression_smoke_candidate"] is None


def test_meta_router_shadow_compare_prefers_formal_promotion_over_smoke() -> None:
    source = {
        "folds": [
            _fold(1, 10.0, 5.0, 2.0, 10),
            _fold(2, 12.0, 5.5, 2.2, 11),
        ]
    }
    smoke = {
        "folds": [_fold(2, 12.0, 5.5, 2.2, 11)],
        "source_replay_lineage_guard": {"status": "pass"},
    }
    formal = {
        "folds": [
            _fold(1, 10.0, 5.0, 2.0, 10),
            _fold(2, 12.0, 5.5, 2.2, 11),
        ],
        "source_replay_lineage_guard": {"status": "pass"},
    }

    report = build_meta_router_shadow_wfo_compare(
        source_report=source,
        candidate_reports=[
            ("router_contract_observe_only", smoke, "reports/smoke.json"),
            ("router_contract_observe_only_formal", formal, "reports/formal.json"),
        ],
        min_formal_folds=2,
        max_return_giveback_pct=3.0,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["best_candidate"]["recipe_id"] == "router_contract_observe_only_formal"
    assert report["best_candidate"]["decision"] == "promotion_candidate_after_formal_wfo"
    assert report["best_candidate"]["execution_change_audit"]["performance_upgrade_ready"] is False
    assert (
        report["best_candidate"]["execution_change_audit"]["status"]
        == "decomposition_only_no_execution_delta"
    )
    assert "live readiness" in report["next_action"]
    assert report["performance_upgrade_candidate_count"] == 0


def test_meta_router_shadow_compare_marks_positive_delta_as_performance_upgrade() -> None:
    source = {
        "folds": [
            _fold(1, 10.0, 5.0, 2.0, 10),
            _fold(2, 12.0, 5.5, 2.2, 11),
        ]
    }
    candidate = {
        "folds": [
            _fold(1, 11.0, 4.9, 1.9, 10),
            _fold(2, 13.0, 5.3, 2.1, 12),
        ],
        "source_replay_lineage_guard": {"status": "pass"},
    }

    report = build_meta_router_shadow_wfo_compare(
        source_report=source,
        candidate_reports=[("winner_only_capacity_formal", candidate, "reports/formal.json")],
        min_formal_folds=2,
        max_return_giveback_pct=3.0,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    audit = report["best_candidate"]["execution_change_audit"]
    assert audit["status"] == "performance_metric_delta_detected"
    assert audit["execution_delta_detected"] is True
    assert audit["performance_upgrade_ready"] is True
    assert audit["return_delta_vs_baseline_pct"] > 0
    assert audit["trade_event_delta_vs_baseline"] == 1
    assert report["performance_upgrade_status"] == "performance_upgrade_candidate_available"
    assert report["performance_upgrade_candidate_count"] == 1
    assert report["performance_upgrade_smoke_candidate_count"] == 0
    assert report["best_performance_upgrade_candidate"]["recipe_id"] == "winner_only_capacity_formal"


def test_meta_router_shadow_compare_flags_conditional_winner_refill_holdout_review() -> None:
    source = {
        "folds": [
            _fold(1, 10.0, 5.0, 2.0, 10, model_id="baseline"),
            _fold(2, 10.0, 5.0, 2.0, 10, model_id="baseline"),
            _fold(3, 10.0, 5.0, 2.0, 10, model_id="baseline"),
        ]
    }
    candidate = {
        "config_overrides": {
            "winner_pyramid_min_extension_after_selection": True,
            "winner_pyramid_min_extension_after_selection_atr": 0.75,
        },
        "folds": [
            _fold(
                1,
                12.0,
                5.0,
                2.1,
                11,
                model_id="candidate:wfWinPyrMinExtAS0.75",
            ),
            _fold(2, 11.0, 5.0, 2.1, 11, model_id="candidate"),
            _fold(3, 10.0, 5.0, 2.0, 10, model_id="candidate"),
        ],
        "source_replay_lineage_guard": {"status": "pass"},
    }

    report = build_meta_router_shadow_wfo_compare(
        source_report=source,
        candidate_reports=[("winner_refill_conditional_formal", candidate, "reports/formal.json")],
        min_formal_folds=3,
        max_cost_increase_pct=1.0,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    audit = report["best_candidate"]["overfit_audit"]

    assert report["best_candidate"]["execution_change_audit"]["performance_upgrade_ready"] is True
    assert audit["status"] == "requires_shadow_holdout_review"
    assert audit["conditional_overlay_detected"] is True
    assert audit["conditional_overlay_keys"] == ["winner_pyramid_min_extension_after_selection"]
    assert audit["conditional_model_token_folds"] == [1]
    assert audit["positive_delta_folds"] == [1, 2]
    assert "conditional_winner_refill_overlay_requires_shadow_holdout_review" in audit["blockers"]


def test_meta_router_shadow_compare_prefers_canonical_recipe_on_identical_smoke_metrics() -> None:
    source = {"folds": [_fold(16, 27.7395, 9.8478, 6.1283, 12)]}
    experimental = {
        "folds": [_fold(16, 28.3837, 9.8478, 6.3444, 13)],
        "source_replay_lineage_guard": {"status": "pass"},
    }
    canonical = {
        "folds": [_fold(16, 28.3837, 9.8478, 6.3444, 13)],
        "source_replay_lineage_guard": {"status": "pass"},
    }

    report = build_meta_router_shadow_wfo_compare(
        source_report=source,
        candidate_reports=[
            (
                "winner_pyramid_profit_unlock_125_r010_s4_stack1",
                experimental,
                "reports/experimental.json",
            ),
            (
                "winner_refill_after_trim_100_r010_s4",
                canonical,
                "reports/canonical.json",
            ),
        ],
        min_formal_folds=12,
        max_return_giveback_pct=3.0,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["performance_upgrade_status"] == (
        "performance_upgrade_smoke_candidate_requires_formal_wfo"
    )
    assert report["performance_upgrade_smoke_candidate_count"] == 2
    assert (
        report["best_performance_upgrade_smoke_candidate"]["recipe_id"]
        == "winner_refill_after_trim_100_r010_s4"
    )
    assert report["candidates"][0]["recipe_id"] == "winner_refill_after_trim_100_r010_s4"


def test_meta_router_shadow_compare_invalidates_smoke_after_formal_counterpart_fails() -> None:
    source = {"folds": [_fold(1, 10.0, 5.0, 2.0, 10), _fold(2, 12.0, 5.0, 2.0, 10)]}
    smoke = {
        "folds": [_fold(2, 13.0, 5.0, 2.1, 11)],
        "source_replay_lineage_guard": {"status": "pass"},
    }
    experimental_duplicate = {
        "folds": [_fold(2, 13.0, 5.0, 2.1, 11)],
        "source_replay_lineage_guard": {"status": "pass"},
    }
    failed_formal = {
        "folds": [_fold(1, 5.0, 6.5, 2.2, 9), _fold(2, 13.0, 5.0, 2.1, 11)],
        "source_replay_lineage_guard": {"status": "pass"},
    }

    report = build_meta_router_shadow_wfo_compare(
        source_report=source,
        candidate_reports=[
            ("winner_refill_after_trim_100_r010_s4", smoke, "reports/smoke.json"),
            (
                "winner_pyramid_profit_unlock_125_r010_s4_stack1",
                experimental_duplicate,
                "reports/experimental.json",
            ),
            (
                "winner_refill_after_trim_100_r010_s4_formal",
                failed_formal,
                "reports/formal.json",
            ),
        ],
        min_formal_folds=2,
        max_return_giveback_pct=3.0,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["performance_upgrade_status"] == (
        "performance_upgrade_smoke_candidate_failed_formal_wfo"
    )
    assert report["performance_upgrade_candidate_count"] == 0
    assert report["performance_upgrade_smoke_candidate_count"] == 0
    assert report["performance_upgrade_invalidated_smoke_candidate_count"] == 2
    assert report["best_performance_upgrade_smoke_candidate"] is None
    assert (
        report["best_performance_upgrade_invalidated_smoke_candidate"]["recipe_id"]
        == "winner_refill_after_trim_100_r010_s4"
    )
    formal_row = next(
        item
        for item in report["candidates"]
        if item["recipe_id"] == "winner_refill_after_trim_100_r010_s4_formal"
    )
    assert formal_row["decision"] == "retune_or_reject_current_recipe"
    assert "return_giveback_exceeds_gate" in formal_row["decision_reasons"]


def test_meta_router_shadow_compare_keeps_risk_smoke_out_of_formal_candidates() -> None:
    source = {"folds": [_fold(1, 30.0, 10.0, 5.0, 10)]}
    candidate = {
        "folds": [_fold(1, 28.0, 8.0, 4.0, 10)],
        "source_replay_lineage_guard": {"status": "pass"},
    }

    report = build_meta_router_shadow_wfo_compare(
        source_report=source,
        candidate_reports=[("winner_pyramid_no_prune_110", candidate, "reports/risk_smoke.json")],
        min_formal_folds=12,
        max_return_giveback_pct=3.0,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    row = report["candidates"][0]
    assert row["decision"] == "smoke_pass_run_formal_wfo"
    assert row["execution_change_audit"]["risk_compression_ready"] is True
    assert report["risk_compression_status"] == "risk_compression_smoke_candidate_requires_formal_wfo"
    assert report["risk_compression_candidate_count"] == 0
    assert report["risk_compression_smoke_candidate_count"] == 1
    assert report["best_risk_compression_candidate"] is None
    assert report["best_risk_compression_smoke_candidate"]["recipe_id"] == "winner_pyramid_no_prune_110"


def test_meta_router_shadow_compare_separates_risk_compression_from_return_upgrade() -> None:
    source = {"folds": [_fold(1, 30.0, 10.0, 5.0, 10)]}
    candidate = {
        "folds": [_fold(1, 26.0, 7.0, 5.5, 10)],
        "source_replay_lineage_guard": {"status": "pass"},
    }

    report = build_meta_router_shadow_wfo_compare(
        source_report=source,
        candidate_reports=[("winner_pyramid_no_prune_125", candidate, "reports/risk.json")],
        min_formal_folds=1,
        max_return_giveback_pct=3.0,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    audit = report["best_candidate"]["execution_change_audit"]
    assert audit["status"] == "risk_compression_return_giveback_exceeds_gate"
    assert audit["performance_upgrade_ready"] is False
    assert audit["risk_compression_detected"] is True
    assert audit["risk_compression_ready"] is False
    assert "risk_compression_return_giveback_exceeds_gate" in audit["blockers"]
    assert audit["cost_delta_vs_baseline_pct"] == 0.5
    assert report["performance_upgrade_candidate_count"] == 0
    assert report["risk_compression_candidate_count"] == 0
    assert report["risk_compression_formal_tradeoff_count"] == 1
    assert report["risk_compression_tradeoff_count"] == 1
    assert (
        report["risk_compression_status"]
        == "risk_compression_formal_tradeoff_found_but_return_giveback_exceeds_gate"
    )
    assert report["best_risk_compression_tradeoff"]["recipe_id"] == "winner_pyramid_no_prune_125"


def test_meta_router_shadow_compare_marks_relative_stability_variant_separately() -> None:
    source = {"folds": [_fold(1, 25857.0416, 14.9814, 7.5657, 290, model_id="base:wfRouter1")]}
    candidate = {
        "folds": [
            _fold(
                1,
                23300.5276,
                12.1064,
                7.4805,
                290,
                model_id="base:wfRouter1:wfRtSelTrend0.7:wfRtSelRangeP0.75",
            )
        ],
        "source_replay_lineage_guard": {
            "status": "watch",
            "unresolved_material_metric_mismatch_count": 1,
            "selected_model_unresolved_mismatch_count": 1,
            "unresolved_material_folds": [1],
        },
    }

    report = build_meta_router_shadow_wfo_compare(
        source_report=source,
        candidate_reports=[("selective_mode_loss_after_selection", candidate, "reports/risk.json")],
        min_formal_folds=1,
        max_return_giveback_pct=3.0,
        max_risk_adjusted_return_giveback_fraction=0.10,
        min_risk_adjusted_drawdown_reduction_fraction=0.15,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    audit = report["best_candidate"]["execution_change_audit"]
    assert audit["status"] == "risk_adjusted_compression_metric_delta_detected"
    assert audit["risk_compression_ready"] is False
    assert audit["risk_adjusted_compression_ready"] is True
    assert audit["return_giveback_fraction_vs_baseline"] == 0.0985
    assert audit["drawdown_reduction_fraction_vs_baseline"] == 0.1919
    assert report["risk_compression_candidate_count"] == 0
    assert report["risk_adjusted_compression_status"] == "risk_adjusted_compression_candidate_available"
    assert report["risk_adjusted_compression_candidate_count"] == 1
    assert (
        report["best_risk_adjusted_compression_candidate"]["recipe_id"]
        == "selective_mode_loss_after_selection"
    )
    switch_policy = report["candidate_switch_policy"]
    assert switch_policy["status"] == "primary_return_default_with_defensive_variant_available"
    assert switch_policy["default_route"] == "primary_return_candidate"
    assert switch_policy["defensive_route"] == "risk_adjusted_compression_candidate"
    assert switch_policy["auto_switch_allowed_now"] is False
    assert switch_policy["defensive_candidate"]["recipe_id"] == "selective_mode_loss_after_selection"
    assert "execution_parity" in switch_policy["switch_allowed_after_gates"]
    assert "defensive_lineage_review" in switch_policy["switch_allowed_after_gates"]
    assert switch_policy["defensive_lineage_review"]["required"] is True
    assert switch_policy["defensive_lineage_review"]["status"] == "pending_operator_lineage_review"
    assert switch_policy["defensive_lineage_review"]["unresolved_material_folds"] == [1]
    packet = switch_policy["defensive_lineage_review"]["review_packet"]
    assert packet["summary"] == "lineage_watch_is_limited_to_intentional_size_overlay_folds"
    assert packet["folds"][0]["interpretation"] == "intentional_size_overlay_delta_detected"
    assert packet["folds"][0]["size_overlay_tokens"] == ["wfRtSelTrend0.7", "wfRtSelRangeP0.75"]
    assert packet["folds"][0]["same_trade_count"] is True


def test_meta_router_shadow_compare_classifies_winner_refill_lineage_delta() -> None:
    source = {
        "folds": [
            _fold(
                8,
                30.0,
                7.5,
                6.4,
                28,
                model_id="base",
                add_by_role={"base": 12, "probe": 16},
                add_by_side={"long": 16, "short": 12},
            )
        ]
    }
    candidate = {
        "folds": [
            _fold(
                8,
                24.0,
                7.5,
                7.3,
                33,
                model_id="base:wfWinPyr0.25:wfWinPyrScore5:wfRouter1:wfRtTrend1",
                add_by_role={"base": 12, "chase": 4, "probe": 17},
                add_by_side={"long": 19, "short": 14},
            )
        ],
        "source_replay_lineage_guard": {
            "status": "watch",
            "unresolved_material_metric_mismatch_count": 1,
            "selected_model_unresolved_mismatch_count": 1,
            "unresolved_material_folds": [8],
        },
    }

    report = build_meta_router_shadow_wfo_compare(
        source_report=source,
        candidate_reports=[
            (
                "winner_refill_after_trim_100_r010_s5_overlay_anchor_formal",
                candidate,
                "reports/winner.json",
            )
        ],
        min_formal_folds=1,
        max_return_giveback_pct=3.0,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    row = report["candidates"][0]
    packet = row["lineage_review_packet"]
    assert row["decision"] == "retune_or_reject_current_recipe"
    assert packet["summary"] == "lineage_watch_is_limited_to_intentional_execution_overlay_folds"
    assert packet["folds"][0]["interpretation"] == "intentional_winner_refill_delta_detected"
    assert packet["folds"][0]["winner_refill_tokens"] == ["wfWinPyr0.25", "wfWinPyrScore5"]
    assert packet["folds"][0]["same_trade_count"] is False


def test_meta_router_shadow_compare_allows_explicit_new_candidate_material_drift() -> None:
    source = {"folds": [_fold(16, 10.0, 5.0, 2.0, 10)]}
    candidate = {
        "folds": [_fold(16, 10.0, 5.0, 2.0, 10)],
        "source_replay_lineage_guard": {
            "status": "watch",
            "unresolved_material_metric_mismatch_count": 1,
            "selected_model_unresolved_mismatch_count": 1,
            "unresolved_material_folds": [16],
        },
    }

    report = build_meta_router_shadow_wfo_compare(
        source_report=source,
        candidate_reports=[("probe_alpha_leak_pruning", candidate, "reports/probe.json")],
        min_formal_folds=12,
        max_return_giveback_pct=3.0,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    row = report["candidates"][0]
    assert row["lineage_policy"] == "explicit_new_candidate"
    assert row["lineage"]["unresolved_material_drift_count"] == 1
    assert row["decision"] == "smoke_pass_run_formal_wfo"


def test_meta_router_shadow_compare_blocks_observe_only_material_drift() -> None:
    source = {"folds": [_fold(16, 10.0, 5.0, 2.0, 10)]}
    candidate = {
        "folds": [_fold(16, 10.0, 5.0, 2.0, 10)],
        "source_replay_lineage_guard": {
            "status": "watch",
            "unresolved_material_metric_mismatch_count": 1,
            "selected_model_unresolved_mismatch_count": 1,
            "unresolved_material_folds": [16],
        },
    }

    report = build_meta_router_shadow_wfo_compare(
        source_report=source,
        candidate_reports=[("router_contract_observe_only", candidate, "reports/observe.json")],
        min_formal_folds=12,
        max_return_giveback_pct=3.0,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    row = report["candidates"][0]
    assert row["lineage_policy"] == "must_match_source"
    assert row["decision"] == "retune_or_reject_current_recipe"
    assert row["decision_reasons"] == ["source_replay_unresolved_material_drift"]
