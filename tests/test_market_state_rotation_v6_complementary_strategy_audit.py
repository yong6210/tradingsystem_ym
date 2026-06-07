from datetime import UTC, datetime

from scripts.run_market_state_rotation_v6_complementary_strategy_audit import (
    build_complementary_strategy_audit,
)


def _live_readiness() -> dict:
    return {
        "stage": "paper_only",
        "ready_for_paper": True,
        "ready_for_tiny_canary": False,
        "ready_for_full_live": False,
        "blockers": ["live_or_paper_execution_parity_available"],
        "warnings": ["all_exact_30d_windows_positive"],
        "summary": {
            "compounded_oos_return_pct": 25857.0215,
            "max_oos_drawdown_pct": 14.9814,
            "worst_exact_rolling": {"30d": {"worst_min_return_pct": -6.7693}},
        },
        "upgrade_backlog": {
            "items": [
                {"id": "base_negative_context_pruning", "status": "needs_targeted_retest", "priority": "high"},
                {"id": "one_way_forced_trim_cost_repair", "status": "needs_targeted_retest", "priority": "medium"},
                {"id": "single_unit_capacity_review", "status": "needs_capacity_ablation", "priority": "medium"},
            ]
        },
    }


def _weak_turtle_report() -> dict:
    return {
        "top_robust": [
            {
                "name": "btc100_long_short_e480_x168",
                "default_x": 1.885264,
                "min_x": 1.673253,
                "geo_x": 1.767235,
                "max_drawdown_pct": 23.9341,
                "worst_year_pct": -6.5253,
                "avg_gross_exposure": 0.1968,
                "turnover_sum": 106.8484,
                "decision_default": "REJECT_WEAK",
                "config": {"sleeve": "btc100"},
            }
        ]
    }


def _entry_filter_audit() -> dict:
    return {
        "status": "entry_filter_sparsity_review_required",
        "diagnosis": {
            "recommended_experiment_scope": "mc12_quality_gated_micro_probe_only",
            "eligible_probe_context_count": 15,
            "rejected_soft_context_count": 80,
            "mc04_broad_relaxation_rejected": True,
            "paper_fill_collection_will_remain_slow_without_fresh_adds": True,
        },
    }


def _meta_router_audit() -> dict:
    return {
        "status": "adaptive_meta_router_audit_complete",
        "critical_gap_count": 1,
        "high_gap_count": 4,
        "router_mode_summary": {
            "router_contract_active": False,
            "active_modes": ["legacy"],
        },
        "gaps": [
            {"id": "router_contract_not_active_in_current_top_candidate", "severity": "high"},
            {"id": "paper_execution_parity_missing", "severity": "critical"},
        ],
        "next_experiment_order": [
            {"id": "router_contract_shadow_wfo", "enabled": True},
            {"id": "one_way_runner_protection_ablation", "enabled": True},
        ],
    }


def test_complementary_audit_rejects_weak_turtle_sleeve_but_keeps_trend_feature() -> None:
    report = build_complementary_strategy_audit(
        live_readiness_report=_live_readiness(),
        turtle_report=_weak_turtle_report(),
        entry_filter_audit=_entry_filter_audit(),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    turtle = report["external_turtle_benchmark"]
    turtle_decision = next(
        item for item in report["candidate_decisions"] if item["id"] == "external_turtle_atr_btc_sleeve"
    )

    assert report["no_live_order_sent"] is True
    assert turtle["decision"] == "reject_as_independent_sleeve"
    assert turtle["recommended_use"] == "trend_state_feature_or_runner_protection_only"
    assert "default_return_multiple_below_3x" in turtle["reject_reasons"]
    assert turtle_decision["paper_allowed"] is False
    assert turtle_decision["live_allowed"] is False


def test_complementary_audit_promotes_only_targeted_ambiguity_repairs() -> None:
    report = build_complementary_strategy_audit(
        live_readiness_report=_live_readiness(),
        turtle_report=_weak_turtle_report(),
        entry_filter_audit=_entry_filter_audit(),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )
    decisions = {item["id"]: item for item in report["candidate_decisions"]}

    assert report["strategy_addition_policy"]["live_allowed_candidate_count"] == 0
    assert decisions["quality_gated_near_miss_micro_probe"]["decision"] == "promote_to_walk_forward_experiment"
    assert decisions["quality_gated_near_miss_micro_probe"]["paper_allowed"] is True
    assert decisions["negative_base_context_pruning"]["decision"] == "promote_to_targeted_ablation"
    assert decisions["one_way_runner_protection"]["decision"] == "promote_to_targeted_ablation"
    assert decisions["winner_only_capacity_extension"]["decision"] == "promote_to_capacity_ablation"
    assert decisions["wyckoff_like_structure_classifier"]["paper_allowed"] is True
    assert "external_turtle_atr_btc_sleeve" == report["next_experiment_order"][-1]


def test_complementary_audit_promotes_adaptive_meta_router_contract_when_gap_exists() -> None:
    report = build_complementary_strategy_audit(
        live_readiness_report=_live_readiness(),
        turtle_report=_weak_turtle_report(),
        entry_filter_audit=_entry_filter_audit(),
        meta_router_audit=_meta_router_audit(),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )
    decisions = {item["id"]: item for item in report["candidate_decisions"]}

    assert report["adaptive_meta_router"]["router_contract_active"] is False
    assert report["adaptive_meta_router"]["enabled_experiment_ids"] == [
        "router_contract_shadow_wfo",
        "one_way_runner_protection_ablation",
    ]
    assert decisions["adaptive_meta_router_contract"]["decision"] == "promote_to_shadow_wfo_experiment"
    assert decisions["adaptive_meta_router_contract"]["paper_allowed"] is True
    assert decisions["adaptive_meta_router_contract"]["live_allowed"] is False
    assert report["next_experiment_order"][0] == "adaptive_meta_router_contract"
