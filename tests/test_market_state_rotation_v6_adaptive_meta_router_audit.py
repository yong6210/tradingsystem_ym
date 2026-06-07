from datetime import UTC, datetime

from scripts.run_market_state_rotation_v6_adaptive_meta_router_audit import (
    build_adaptive_meta_router_audit,
)


def _live_readiness() -> dict:
    return {
        "stage": "paper_only",
        "ready_for_paper": True,
        "ready_for_tiny_canary": False,
        "ready_for_full_live": False,
        "blockers": ["live_or_paper_execution_parity_available"],
        "warnings": ["all_exact_30d_windows_positive", "role_add_concentration"],
        "summary": {
            "compounded_oos_return_pct": 25857.0215,
            "max_oos_drawdown_pct": 14.9814,
            "worst_exact_rolling": {"30d": {"worst_min_return_pct": -6.7693}},
        },
        "upgrade_backlog": {
            "items": [
                {"id": "probe_alpha_leak_pruning", "status": "needs_targeted_retest"},
                {"id": "base_negative_context_pruning", "status": "needs_targeted_retest"},
                {"id": "one_way_forced_trim_cost_repair", "status": "needs_targeted_retest"},
                {"id": "single_unit_capacity_review", "status": "needs_capacity_ablation"},
            ]
        },
    }


def _legacy_walk_report() -> dict:
    return {
        "aggregate": {
            "fold_count": 16,
            "compounded_oos_return_pct": 25857.0215,
            "min_oos_return_pct": 16.5119,
            "max_fold_drawdown_pct": 14.9814,
            "avg_oos_cost_drag_pct": 7.5657,
            "max_oos_cost_drag_pct": 36.6152,
            "total_trade_like_events": 290,
            "test_add_by_role_counts": {"base": 161, "probe": 118, "chase": 10, "battle": 1},
            "test_add_by_role_share": {"base": 0.5552, "probe": 0.4069, "chase": 0.0345, "battle": 0.0034},
            "test_add_distribution_diagnostics": {
                "dominant_add_role": "base",
                "dominant_add_role_share": 0.5552,
            },
            "test_cost_attribution": {
                "by_reason_pct": {
                    "base_entry": 23.3005,
                    "v6_reaction_inventory_trim": 15.3271,
                    "one_way_against_forced_trim": 8.1251,
                }
            },
        },
        "folds": [
            {
                "fold": 1,
                "test_result": {
                    "config": {"regime_router_enabled": False},
                    "router_mode_performance": {
                        "legacy": {
                            "bars": 100,
                            "exposed_bars": 40,
                            "return_pct": 12.0,
                            "max_drawdown_pct": 4.0,
                            "add_events": 3,
                            "remove_events": 2,
                            "side_bars": {"long": 40, "flat": 60},
                        }
                    },
                    "event_diagnostics": {
                        "add_by_router_mode": {"legacy": 3},
                        "remove_by_router_mode": {"legacy": 2},
                    },
                },
            }
        ],
    }


def _router_walk_report() -> dict:
    report = _legacy_walk_report()
    report["folds"] = [
        {
            "fold": 1,
            "test_result": {
                "config": {"regime_router_enabled": True},
                "router_mode_performance": {
                    "trend_reaction": {
                        "bars": 200,
                        "exposed_bars": 80,
                        "return_pct": 15.0,
                        "max_drawdown_pct": 5.0,
                        "add_events": 4,
                        "remove_events": 3,
                        "side_bars": {"long": 80, "flat": 120},
                    },
                    "one_way_chase": {
                        "bars": 100,
                        "exposed_bars": 60,
                        "return_pct": -3.0,
                        "max_drawdown_pct": 6.0,
                        "add_events": 1,
                        "remove_events": 4,
                        "side_bars": {"short": 60, "flat": 40},
                    },
                },
                "event_diagnostics": {
                    "add_by_router_mode": {"trend_reaction": 4, "one_way_chase": 1},
                    "remove_by_router_mode": {"trend_reaction": 3, "one_way_chase": 4},
                },
            },
        }
    ]
    return report


def test_adaptive_meta_router_audit_blocks_live_and_flags_missing_router_contract() -> None:
    report = build_adaptive_meta_router_audit(
        walk_forward_report=_legacy_walk_report(),
        live_readiness_report=_live_readiness(),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )
    gap_ids = {item["id"] for item in report["gaps"]}
    experiments = {item["id"]: item for item in report["next_experiment_order"]}

    assert report["no_live_order_sent"] is True
    assert report["policy"]["live_allowed_candidate_count"] == 0
    assert report["router_mode_summary"]["router_contract_active"] is False
    assert "router_contract_not_active_in_current_top_candidate" in gap_ids
    assert "paper_execution_parity_missing" in gap_ids
    assert "base_context_pruning_needed" in gap_ids
    assert "one_way_runner_protection_needed" in gap_ids
    assert experiments["router_contract_shadow_wfo"]["enabled"] is True
    assert experiments["paper_execution_parity_collection"]["enabled"] is True


def test_adaptive_meta_router_audit_surfaces_negative_router_mode_pockets() -> None:
    report = build_adaptive_meta_router_audit(
        walk_forward_report=_router_walk_report(),
        live_readiness_report=_live_readiness(),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )
    gap_ids = {item["id"] for item in report["gaps"]}
    mode_summary = report["router_mode_summary"]
    one_way = mode_summary["modes"]["one_way_chase"]
    contracts = {item["mode"]: item for item in report["playbook_contracts"]}

    assert mode_summary["router_contract_active"] is True
    assert "negative_router_mode_pockets" in gap_ids
    assert one_way["min_return_pct"] == -3.0
    assert one_way["positive_fold_count"] == 0
    assert contracts["one_way_chase"]["blocked_modules"] == [
        "counter_trend_base",
        "unconditional_reversal",
        "forced_trim_without_thesis_break",
    ]
    assert any(item["id"] == "one_way_runner_protection_ablation" for item in report["next_experiment_order"])
