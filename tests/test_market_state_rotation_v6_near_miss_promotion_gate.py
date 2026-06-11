from datetime import UTC, datetime

from scripts.run_market_state_rotation_v6_near_miss_promotion_gate import (
    DEFAULT_FULL_WALK_FORWARD_GATE_REPORT,
    DEFAULT_SMOKE_REPORTS,
    build_near_miss_promotion_gate_report,
)


def _safe_config() -> dict:
    return {
        "near_miss_probe_units": 0.00025,
        "near_miss_probe_min_score": 4,
        "near_miss_probe_min_score_edge": 2,
        "near_miss_probe_min_reason_stack": 2,
        "near_miss_probe_max_extension_atr": 1.5,
        "near_miss_probe_allowed_soft_reasons": ["MC12_low_confluence"],
    }


def _smoke(
    name: str,
    *,
    decision: str,
    d_return: float,
    d_dd: float,
    d_adds: int,
    config_change: dict | None = None,
) -> dict:
    return {
        "window": {"days": 120},
        "candidates": [
            {
                "name": "base",
                "delta_vs_base": {"return_pct": 0, "max_drawdown_pct": 0, "add_events": 0},
            },
            {
                "name": name,
                "total_return_pct": 10 + d_return,
                "max_drawdown_pct": 5 + d_dd,
                "add_events": 10 + d_adds,
                "smoke_decision": decision,
                "primary_use": "paper_evidence_collection_probe",
                "config_change": dict(config_change or _safe_config()),
                "delta_vs_base": {
                    "return_pct": d_return,
                    "max_drawdown_pct": d_dd,
                    "add_events": d_adds,
                },
            },
        ],
    }


def test_near_miss_promotion_gate_blocks_candidate_that_fails_any_window() -> None:
    report = build_near_miss_promotion_gate_report(
        [
            (
                "120d.json",
                _smoke(
                    "near_miss_probe_00025_guarded",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=-3,
                    d_dd=0,
                    d_adds=10,
                ),
            ),
            (
                "365d.json",
                _smoke(
                    "near_miss_probe_00025_guarded",
                    decision="reject_or_keep_for_manual_review",
                    d_return=-12,
                    d_dd=0,
                    d_adds=30,
                ),
            ),
        ],
        generated_at=datetime(2026, 6, 5, tzinfo=UTC),
    )

    assert report["overall_status"] == "no_candidate_promoted"
    assert report["resolution_plan"]["status"] == "blocked_by_window_performance_or_smoke_decision"
    assert report["resolution_plan"]["runtime_filter_change_allowed"] is False
    assert report["candidates"][0]["status"] == "blocked"
    assert report["candidates"][0]["passed_window_count"] == 1
    assert report["candidates"][0]["failed_window_count"] == 1


def test_near_miss_promotion_gate_promotes_only_when_all_windows_pass() -> None:
    report = build_near_miss_promotion_gate_report(
        [
            (
                "120d.json",
                _smoke(
                    "near_miss_probe_00025_guarded",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=-2,
                    d_dd=0,
                    d_adds=10,
                ),
            ),
            (
                "365d.json",
                _smoke(
                    "near_miss_probe_00025_guarded",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=-4,
                    d_dd=1,
                    d_adds=30,
                ),
            ),
        ]
    )

    assert report["overall_status"] == "candidate_promoted"
    assert report["resolution_plan"]["status"] == "full_walk_forward_candidate_available"
    assert report["resolution_plan"]["full_walk_forward_validation_allowed"] is True
    assert report["resolution_plan"]["paper_or_live_promotion_allowed"] is False
    assert report["candidates"][0]["status"] == "promote_to_full_walk_forward"


def test_near_miss_promotion_gate_blocks_promoted_candidate_after_failed_full_wfo() -> None:
    report = build_near_miss_promotion_gate_report(
        [
            (
                "120d.json",
                _smoke(
                    "near_miss_probe_00025_guarded",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=-2,
                    d_dd=0,
                    d_adds=10,
                ),
            ),
            (
                "365d.json",
                _smoke(
                    "near_miss_probe_00025_guarded",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=-4,
                    d_dd=1,
                    d_adds=30,
                ),
            ),
        ],
        full_walk_forward_gate_report={
            "overall_status": "blocked",
            "decision": "do_not_promote_to_paper_or_live",
            "failed_checks": ["compounded_return_degradation"],
            "deltas": {"compounded_oos_return_pct": -100.0},
            "activity_regression_summary": {
                "signal_sparsity_fix_failed": True,
                "probe_activity_regressed": True,
                "trade_like_activity_regressed": True,
                "baseline_probe_adds": 126,
                "candidate_probe_adds": 107,
                "probe_add_delta": -19,
                "probe_add_delta_pct": -15.0794,
                "baseline_trade_like_events": 298,
                "candidate_trade_like_events": 295,
                "trade_like_events_delta": -3,
                "trade_like_events_delta_pct": -1.0067,
                "diagnostic_labels": [
                    "candidate_reduces_probe_activity_instead_of_solving_signal_sparsity"
                ],
            },
            "fold_delta_summary": {"return_degraded_fold_count": 16},
            "root_cause_hints": ["candidate_underperforms_baseline_in_every_matched_oos_fold"],
            "no_live_order_sent": True,
        },
    )

    assert report["overall_status"] == "full_walk_forward_candidate_blocked"
    assert report["promoted_candidate_count"] == 1
    assert report["active_full_walk_forward_candidate_count"] == 0
    assert report["resolution_plan"]["status"] == "blocked_by_full_walk_forward_gate"
    assert report["resolution_plan"]["full_walk_forward_validation_allowed"] is False
    assert report["resolution_plan"]["primary_downstream_failure"] == (
        "activity_regression_blocks_signal_sparsity_fix"
    )
    assert report["resolution_plan"]["safe_next_step"] == (
        "abandon_current_activity_regressing_near_miss_family_design_non_regressing_signal_candidate"
    )
    assert report["downstream_full_walk_forward_gate"]["status"] == "blocked_full_walk_forward_gate"
    assert report["downstream_full_walk_forward_gate"]["fold_delta_summary"]["return_degraded_fold_count"] == 16
    activity = report["downstream_activity_regression_summary"]
    assert activity["signal_sparsity_fix_failed_candidate_count"] == 1
    assert activity["probe_activity_regressed_candidate_count"] == 1
    assert "candidate_reduces_probe_activity_instead_of_solving_signal_sparsity" in activity["diagnostic_labels"]
    assert report["resolution_plan"]["downstream_activity_regression_summary"] == activity


def test_near_miss_promotion_gate_prefers_passed_full_wfo_over_stale_blockers() -> None:
    report = build_near_miss_promotion_gate_report(
        [
            (
                "120d.json",
                _smoke(
                    "quality_gated_mc12_near_miss_micro_probe",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=-2,
                    d_dd=0,
                    d_adds=10,
                ),
            ),
            (
                "365d.json",
                _smoke(
                    "quality_gated_mc12_near_miss_micro_probe",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=-4,
                    d_dd=1,
                    d_adds=30,
                ),
            ),
        ],
        full_walk_forward_gate_reports=[
            {
                "candidate_name": "quality_gated_mc12_near_miss_micro_probe",
                "overall_status": "blocked",
                "decision": "do_not_promote_to_paper_or_live",
                "failed_checks": ["drawdown_worsening"],
                "gates": {"require_nonregressing_activity": True},
                "activity_regression_summary": {
                    "signal_sparsity_fix_failed": False,
                    "probe_add_delta": 44,
                    "trade_like_events_delta": 232,
                },
                "no_live_order_sent": True,
            },
            {
                "candidate_name": "seeded_mc12_downtrend_react200_mdd20",
                "overall_status": "return_improving",
                "decision": "eligible_for_paper_evidence_collection_only",
                "failed_checks": [],
                "gates": {"require_nonregressing_activity": True},
                "deltas": {
                    "compounded_oos_return_pct": 723.1,
                    "max_fold_drawdown_pct": -1.19,
                },
                "activity_regression_summary": {
                    "signal_sparsity_fix_failed": False,
                    "probe_add_delta": 17,
                    "trade_like_events_delta": 206,
                },
                "no_live_order_sent": True,
            },
        ],
    )

    assert report["overall_status"] == "candidate_promoted"
    assert report["active_full_walk_forward_candidate_count"] == 0
    assert report["paper_evidence_candidate_count"] == 1
    assert report["paper_evidence_candidate_names"] == [
        "seeded_mc12_downtrend_react200_mdd20"
    ]
    assert report["downstream_blocked_candidate_names"] == [
        "quality_gated_mc12_near_miss_micro_probe"
    ]
    assert report["resolution_plan"]["status"] == (
        "full_walk_forward_candidate_passed_paper_evidence_collection_only"
    )
    assert report["resolution_plan"]["full_walk_forward_validation_allowed"] is False
    assert report["resolution_plan"]["paper_evidence_collection_allowed"] is True
    assert report["resolution_plan"]["paper_evidence_candidate_names"] == [
        "seeded_mc12_downtrend_react200_mdd20"
    ]


def test_near_miss_promotion_gate_blocks_non_strict_activity_regressing_full_wfo() -> None:
    report = build_near_miss_promotion_gate_report(
        [
            (
                "120d.json",
                _smoke(
                    "quality_gated_mc12_near_miss_micro_probe",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=-2,
                    d_dd=0,
                    d_adds=10,
                ),
            ),
            (
                "365d.json",
                _smoke(
                    "quality_gated_mc12_near_miss_micro_probe",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=-4,
                    d_dd=1,
                    d_adds=30,
                ),
            ),
        ],
        full_walk_forward_gate_report={
            "candidate_name": "quality_gated_mc12_near_miss_micro_probe",
            "overall_status": "promoted",
            "decision": "eligible_for_paper_evidence_collection_only",
            "failed_checks": [],
            "gates": {"require_nonregressing_activity": False},
            "activity_regression_summary": {
                "signal_sparsity_fix_failed": True,
                "probe_activity_regressed": True,
                "trade_like_activity_regressed": True,
                "probe_add_delta": -19,
                "trade_like_events_delta": -3,
            },
            "no_live_order_sent": True,
        },
    )

    assert report["overall_status"] == "full_walk_forward_candidate_blocked"
    assert report["active_full_walk_forward_candidate_count"] == 0
    downstream = report["downstream_full_walk_forward_gate"]
    assert downstream["status"] == "blocked_full_walk_forward_gate"
    assert downstream["strict_activity_gate_present"] is False
    assert downstream["nonregressing_activity_gate_missing"] is True
    assert downstream["activity_regression_requires_strict_rerun"] is True
    assert (
        "full_walk_forward_gate_missing_require_nonregressing_activity"
        in downstream["failed_checks"]
    )
    assert (
        "activity_regression_requires_nonregressing_gate_rerun"
        in downstream["failed_checks"]
    )
    assert report["downstream_blocked_candidate_names"] == [
        "quality_gated_mc12_near_miss_micro_probe"
    ]


def test_near_miss_promotion_gate_only_blocks_matching_downstream_full_wfo_candidate() -> None:
    report = build_near_miss_promotion_gate_report(
        [
            (
                "120d.json",
                _smoke(
                    "quality_gated_mc12_near_miss_micro_probe",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=-2,
                    d_dd=0,
                    d_adds=10,
                ),
            ),
            (
                "365d.json",
                _smoke(
                    "quality_gated_mc12_near_miss_micro_probe",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=-4,
                    d_dd=1,
                    d_adds=30,
                ),
            ),
            (
                "120d_strict.json",
                _smoke(
                    "quality_gated_mc12_score5_edge2_stack2_ext10_cooldown144",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=0,
                    d_dd=0,
                    d_adds=1,
                ),
            ),
            (
                "365d_strict.json",
                _smoke(
                    "quality_gated_mc12_score5_edge2_stack2_ext10_cooldown144",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=0,
                    d_dd=0,
                    d_adds=6,
                ),
            ),
        ],
        full_walk_forward_gate_report={
            "candidate_name": "quality_gated_mc12_near_miss_micro_probe",
            "overall_status": "blocked",
            "decision": "do_not_promote_to_paper_or_live",
            "failed_checks": ["compounded_return_degradation"],
            "no_live_order_sent": True,
        },
    )

    assert report["overall_status"] == "candidate_promoted"
    assert report["promoted_candidate_count"] == 2
    assert report["active_full_walk_forward_candidate_count"] == 1
    assert report["active_full_walk_forward_candidate_names"] == [
        "quality_gated_mc12_score5_edge2_stack2_ext10_cooldown144"
    ]
    assert report["downstream_blocked_candidate_names"] == ["quality_gated_mc12_near_miss_micro_probe"]
    by_name = {item["name"]: item for item in report["candidates"]}
    assert by_name["quality_gated_mc12_near_miss_micro_probe"]["final_status"] == "blocked_by_full_walk_forward_gate"
    assert (
        by_name["quality_gated_mc12_score5_edge2_stack2_ext10_cooldown144"]["final_status"]
        == "promote_to_full_walk_forward"
    )
    assert report["resolution_plan"]["status"] == "full_walk_forward_candidate_available"
    assert report["resolution_plan"]["full_walk_forward_validation_allowed"] is True


def test_near_miss_promotion_gate_reports_smoke_to_full_wfo_activity_inversion() -> None:
    report = build_near_miss_promotion_gate_report(
        [
            (
                "120d.json",
                _smoke(
                    "quality_gated_mc12_near_miss_micro_probe",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=-2,
                    d_dd=0,
                    d_adds=10,
                ),
            ),
            (
                "365d.json",
                _smoke(
                    "quality_gated_mc12_near_miss_micro_probe",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=-4,
                    d_dd=1,
                    d_adds=30,
                ),
            ),
        ],
        full_walk_forward_gate_report={
            "candidate_name": "quality_gated_mc12_near_miss_micro_probe",
            "overall_status": "blocked",
            "decision": "do_not_promote_to_paper_or_live",
            "failed_checks": ["compounded_return_degradation"],
            "activity_regression_summary": {
                "signal_sparsity_fix_failed": True,
                "probe_activity_regressed": True,
                "trade_like_activity_regressed": True,
                "probe_add_delta": -19,
                "trade_like_events_delta": -3,
                "diagnostic_labels": [
                    "candidate_reduces_probe_activity_instead_of_solving_signal_sparsity"
                ],
            },
            "no_live_order_sent": True,
        },
    )

    inversion = report["downstream_activity_inversion_summary"]
    assert inversion["available"] is True
    assert inversion["candidate_names"] == ["quality_gated_mc12_near_miss_micro_probe"]
    assert inversion["diagnostic_label"] == (
        "short_window_smoke_activity_increase_inverts_to_full_wfo_activity_regression"
    )
    assert report["resolution_plan"]["primary_downstream_failure"] == (
        "short_window_activity_inversion_and_full_wfo_activity_regression"
    )
    contract = report["next_candidate_design_contract"]
    assert contract["status"] == "required_before_next_near_miss_family"
    assert contract["minimum_full_walk_forward_requirements"]["probe_add_delta_min"] == 0
    assert contract["minimum_full_walk_forward_requirements"]["trade_like_events_delta_min"] == 1
    assert (
        contract["minimum_full_walk_forward_requirements"][
            "trade_like_activity_increase_required"
        ]
        is True
    )
    assert contract["minimum_full_walk_forward_requirements"]["activity_inversion_allowed"] is False
    assert (
        "full_walk_forward_gate_must_run_with_require_nonregressing_activity"
        in contract["required_validation_sequence"]
    )
    assert report["resolution_plan"]["next_candidate_design_contract"] == contract


def test_near_miss_promotion_gate_blocks_unsafe_probe_even_when_windows_pass() -> None:
    report = build_near_miss_promotion_gate_report(
        [
            (
                "120d.json",
                _smoke(
                    "near_miss_mc12_mc04_oversized",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=3,
                    d_dd=0,
                    d_adds=10,
                    config_change={
                        **_safe_config(),
                        "near_miss_probe_units": 0.001,
                        "near_miss_probe_allowed_soft_reasons": [
                            "MC12_low_confluence",
                            "MC04_no_clear_first_touch",
                        ],
                    },
                ),
            ),
            (
                "365d.json",
                _smoke(
                    "near_miss_mc12_mc04_oversized",
                    decision="promote_to_full_walk_forward_evidence_probe_candidate",
                    d_return=6,
                    d_dd=1,
                    d_adds=20,
                    config_change={
                        **_safe_config(),
                        "near_miss_probe_units": 0.001,
                        "near_miss_probe_allowed_soft_reasons": [
                            "MC12_low_confluence",
                            "MC04_no_clear_first_touch",
                        ],
                    },
                ),
            ),
        ]
    )

    candidate = report["candidates"][0]
    blockers = candidate["safety_blockers_by_window"][0]["blockers"]
    assert report["overall_status"] == "no_candidate_promoted"
    assert report["resolution_plan"]["status"] == "blocked_by_near_miss_safety_contract"
    assert report["resolution_plan"]["primary_safety_blocker"] == "near_miss_probe_allows_mc04_broad_first_touch"
    assert report["safety_blocker_counts"]["near_miss_probe_units_above_0_00025"] == 2
    assert report["safety_blocker_counts"]["near_miss_probe_allows_mc04_broad_first_touch"] == 2
    assert report["resolution_plan"]["runtime_filter_change_allowed"] is False
    assert candidate["status"] == "blocked"
    assert candidate["safety_blocker_count"] == 2
    assert "near_miss_probe_units_above_0_00025" in blockers
    assert "near_miss_probe_allows_mc04_broad_first_touch" in blockers


def test_default_smoke_reports_point_to_quality_gated_mc12_evidence() -> None:
    assert "market_state_rotation_v6_near_miss_smoke_quality_gated_mc12_check" in DEFAULT_SMOKE_REPORTS
    assert "market_state_rotation_v6_near_miss_smoke_quality_gated_mc12_365d_check" in DEFAULT_SMOKE_REPORTS
    assert "imp457" not in DEFAULT_SMOKE_REPORTS
    assert "imp458" not in DEFAULT_SMOKE_REPORTS


def test_default_full_walk_forward_gates_include_current_paper_candidate() -> None:
    assert (
        "market_state_rotation_v6_seeded_mc12_downtrend_score4_edge2_stack2_ext10_"
        "cooldown72_react200cap_mdd20p01_strict_activity_gate"
        in DEFAULT_FULL_WALK_FORWARD_GATE_REPORT
    )
