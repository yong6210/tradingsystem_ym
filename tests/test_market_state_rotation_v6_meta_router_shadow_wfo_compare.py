from datetime import UTC, datetime

from scripts.run_market_state_rotation_v6_meta_router_shadow_wfo_compare import (
    build_meta_router_shadow_wfo_compare,
)


def _fold(number: int, return_pct: float, drawdown_pct: float, cost_pct: float, events: int) -> dict:
    return {
        "fold": number,
        "test_result": {
            "total_return_pct": return_pct,
            "max_drawdown_pct": drawdown_pct,
            "estimated_cost_drag_pct": cost_pct,
            "trade_like_events": events,
            "event_diagnostics": {
                "health": "ok",
                "add_by_role": {"base": 2, "chase": 1},
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
    assert "live readiness" in report["next_action"]


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
