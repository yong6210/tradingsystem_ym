import json
import subprocess
import sys
from datetime import UTC, datetime

from scripts.run_market_state_rotation_v6_meta_router_promotion_gate import (
    build_meta_router_promotion_gate,
    _conditional_overfit_operator_review_template_report,
    _operator_lineage_review_template_report,
)


def _compare(best_decision: str = "promotion_candidate_after_formal_wfo") -> dict:
    return {
        "performance_upgrade_status": "no_performance_upgrade_candidate_found",
        "performance_upgrade_candidate_count": 0,
        "performance_upgrade_smoke_candidate_count": 0,
        "risk_compression_status": "risk_compression_formal_tradeoff_found_but_return_giveback_exceeds_gate",
        "risk_compression_candidate_count": 0,
        "risk_compression_smoke_candidate_count": 1,
        "risk_compression_formal_tradeoff_count": 1,
        "risk_compression_tradeoff_count": 2,
        "risk_compression_next_action": "Retune the formal risk-compression recipe.",
        "risk_adjusted_compression_status": "risk_adjusted_compression_candidate_available",
        "risk_adjusted_compression_candidate_count": 1,
        "risk_adjusted_compression_smoke_candidate_count": 0,
        "risk_adjusted_compression_next_action": "Route as optional lower-drawdown variant after readiness.",
        "best_risk_compression_tradeoff": {
            "recipe_id": "winner_pyramid_no_prune_110_formal",
            "decision": "retune_or_reject_current_recipe",
            "report_path": "reports/risk_formal.json",
            "candidate": {
                "fold_count": 16,
                "compounded_return_pct": 14594.4729,
                "max_drawdown_pct": 11.7556,
                "avg_cost_drag_pct": 7.7685,
            },
            "execution_change_audit": {
                "status": "risk_compression_return_giveback_exceeds_gate",
                "performance_upgrade_ready": False,
                "risk_compression_detected": True,
                "risk_compression_ready": False,
                "return_delta_vs_baseline_pct": -11262.5687,
                "drawdown_delta_vs_baseline_pct": -3.2258,
                "cost_delta_vs_baseline_pct": 0.2028,
                "trade_event_delta_vs_baseline": -27,
                "blockers": ["risk_compression_return_giveback_exceeds_gate"],
            },
        },
        "best_risk_adjusted_compression_candidate": {
            "recipe_id": "selective_mode_loss_after_selection",
            "decision": "retune_or_reject_current_recipe",
            "report_path": "reports/selective.json",
            "candidate": {
                "fold_count": 16,
                "compounded_return_pct": 23300.5276,
                "max_drawdown_pct": 12.1064,
                "avg_cost_drag_pct": 7.4805,
            },
            "execution_change_audit": {
                "status": "risk_adjusted_compression_metric_delta_detected",
                "performance_upgrade_ready": False,
                "risk_compression_detected": True,
                "risk_compression_ready": False,
                "risk_adjusted_compression_ready": True,
                "return_delta_vs_baseline_pct": -2556.514,
                "return_giveback_fraction_vs_baseline": 0.0985,
                "drawdown_delta_vs_baseline_pct": -2.875,
                "drawdown_reduction_fraction_vs_baseline": 0.1919,
                "cost_delta_vs_baseline_pct": -0.0852,
                "trade_event_delta_vs_baseline": 0,
                "blockers": ["risk_compression_return_giveback_exceeds_gate"],
            },
        },
        "candidate_switch_policy": {
            "status": "primary_return_default_with_defensive_variant_available",
            "default_route": "primary_return_candidate",
            "default_candidate": {"recipe_id": "router_contract_observe_only_formal"},
            "defensive_route": "risk_adjusted_compression_candidate",
            "defensive_candidate": {
                "recipe_id": "selective_mode_loss_after_selection",
                "lineage_guard_status": "watch",
                "lineage_unresolved_material_drift_count": 1,
                "lineage_unresolved_material_folds": [11],
            },
            "defensive_lineage_review": {
                "required": True,
                "status": "pending_operator_lineage_review",
                "guard_status": "watch",
                "unresolved_material_drift_count": 1,
                "unresolved_material_folds": [11],
                "blockers": ["defensive_lineage_guard_watch", "defensive_unresolved_material_drift"],
                "review_packet": {
                    "summary": "lineage_watch_is_limited_to_intentional_size_overlay_folds",
                    "unresolved_material_folds": [11],
                    "fold_count": 1,
                },
            },
            "switch_allowed_after_gates": [
                "paper_readiness",
                "execution_parity",
                "defensive_lineage_review",
                "operator_review",
            ],
            "auto_switch_allowed_now": False,
            "no_live_order_sent": True,
        },
        "best_candidate": {
            "recipe_id": "router_contract_observe_only_formal",
            "decision": best_decision,
            "report_path": "reports/formal.json",
            "lineage": {"guard_status": "pass", "unresolved_material_drift_count": 0},
            "candidate": {
                "fold_count": 16,
                "compounded_return_pct": 25857.0416,
                "min_return_pct": 16.5119,
                "max_drawdown_pct": 14.9814,
                "avg_cost_drag_pct": 7.5657,
                "trade_like_events": 290,
                "return_delta_vs_baseline_pct": 0.0,
                "drawdown_delta_vs_baseline_pct": 0.0,
                "cost_delta_vs_baseline_pct": 0.0,
                "trade_event_delta_vs_baseline": 0,
                "execution_change_audit": {
                    "status": "decomposition_only_no_execution_delta",
                    "execution_delta_detected": False,
                    "metric_delta_detected": False,
                    "beneficial_metric_delta_detected": False,
                    "performance_upgrade_ready": False,
                    "return_delta_vs_baseline_pct": 0.0,
                    "drawdown_delta_vs_baseline_pct": 0.0,
                    "cost_delta_vs_baseline_pct": 0.0,
                    "trade_event_delta_vs_baseline": 0,
                    "candidate_trade_like_events": 290,
                    "baseline_trade_like_events": 290,
                    "active_router_modes": ["trend_reaction", "risk_off"],
                    "blockers": ["candidate_does_not_change_return_drawdown_cost_or_trade_events"],
                    "notes": ["router_modes_are_descriptive_only_for_this_candidate"],
                },
                "router_mode_summary": {"active_modes": ["trend_reaction", "risk_off"]},
            },
        }
    }


def _readiness(*, ready_for_paper: bool = True, execution_parity_passed: bool = False) -> dict:
    blockers = [] if execution_parity_passed else ["live_or_paper_execution_parity_available"]
    return {
        "input_walk_report": "reports/formal.json",
        "stage": "paper_only" if ready_for_paper else "research_only",
        "ready_for_paper": ready_for_paper,
        "ready_for_tiny_canary": False,
        "ready_for_full_live": False,
        "blockers": blockers,
        "warnings": ["all_exact_30d_windows_positive"],
        "stage_blockers": {"paper": [], "tiny_canary": blockers, "full_live": blockers},
        "deployment_limits": {"recommended_max_size_multiplier": 0.2373},
        "execution_parity": {
            "available": execution_parity_passed,
            "passed": execution_parity_passed,
            "blockers": [] if execution_parity_passed else ["execution_parity_report_missing"],
        },
    }


def test_meta_router_promotion_gate_blocks_live_until_execution_parity() -> None:
    report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["no_live_order_sent"] is True
    assert report["promotion_decision"] == "paper_ready_pending_execution_parity"
    assert report["next_blocker"] == "live_or_paper_execution_parity_available"
    assert report["candidate"]["recipe_id"] == "router_contract_observe_only_formal"
    assert report["candidate"]["lineage"]["unresolved_material_drift_count"] == 0
    assert report["readiness_candidate_alignment"]["passed"] is True
    assert report["performance_upgrade_ready"] is False
    assert report["performance_delta_status"] == "decomposition_only_no_execution_delta"
    assert report["performance_upgrade_blockers"] == [
        "candidate_does_not_change_return_drawdown_cost_or_trade_events"
    ]
    assert report["candidate"]["execution_change_audit"]["performance_upgrade_ready"] is False
    assert (
        report["compare_summary"]["risk_compression_status"]
        == "risk_compression_formal_tradeoff_found_but_return_giveback_exceeds_gate"
    )
    assert (
        report["compare_summary"]["best_risk_compression_tradeoff"]["recipe_id"]
        == "winner_pyramid_no_prune_110_formal"
    )
    assert (
        report["compare_summary"]["best_risk_adjusted_compression_candidate"]["recipe_id"]
        == "selective_mode_loss_after_selection"
    )
    assert report["candidate_switch_policy"]["defensive_route"] == "risk_adjusted_compression_candidate"
    assert report["candidate_switch_policy"]["status"] == "candidate_switch_blocked_pending_readiness_or_parity"
    assert "execution_parity_not_passed" in report["candidate_switch_policy"]["promotion_blockers"]
    assert "defensive_lineage_review_not_passed" in report["candidate_switch_policy"]["promotion_blockers"]
    assert report["candidate_switch_policy"]["defensive_lineage_review_required"] is True
    assert report["candidate_switch_policy"]["defensive_lineage_review_passed"] is False


def test_meta_router_promotion_gate_blocks_conditional_overfit_candidate() -> None:
    compare = _compare()
    compare["best_candidate"]["overfit_audit"] = {
        "status": "requires_shadow_holdout_review",
        "blockers": ["conditional_winner_refill_overlay_requires_shadow_holdout_review"],
        "no_live_order_sent": True,
    }

    report = build_meta_router_promotion_gate(
        compare_report=compare,
        readiness_report=_readiness(execution_parity_passed=True),
        conditional_overfit_holdout_audit_report={
            "status": "historical_proxy_pass_real_shadow_required",
            "candidate_report": "reports/formal.json",
            "aggregate_delta": {"return_delta_pct": 731.0727},
            "tail_holdout_proxy": {"passed": True, "return_delta_pct": 2.3921},
            "conditional_token_proxy": {"passed": True},
            "blockers": [],
            "warnings": ["historical_proxy_does_not_replace_real_shadow_holdout"],
            "limitations": ["uses_historical_wfo_archive_after_the_rule_was_known"],
            "no_live_order_sent": True,
        },
        input_conditional_overfit_holdout_audit_report="reports/holdout_proxy.json",
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["promotion_decision"] == "blocked_pending_overfit_holdout_review"
    assert report["next_blocker"] == "conditional_winner_refill_overlay_requires_shadow_holdout_review"
    assert report["overfit_blockers"] == [
        "conditional_winner_refill_overlay_requires_shadow_holdout_review"
    ]
    assert report["conditional_overfit_holdout_audit"]["proxy_passed"] is True
    assert report["conditional_overfit_holdout_audit"]["real_shadow_still_required"] is True
    assert report["conditional_overfit_operator_review"]["required"] is True
    assert report["conditional_overfit_operator_review"]["accepted_for_paper_only"] is False
    assert report["conditional_overfit_operator_review"]["operator_review"]["blockers"] == [
        "conditional_overfit_operator_review_report_missing"
    ]
    assert (
        "historical_proxy_attached_but_real_shadow_or_operator_review_still_required"
        in report["next_actions"]
    )
    assert report["candidate"]["overfit_audit"]["status"] == "requires_shadow_holdout_review"
    assert report["no_live_order_sent"] is True


def test_meta_router_promotion_gate_builds_conditional_overfit_operator_review_template() -> None:
    compare = _compare()
    compare["best_candidate"]["overfit_audit"] = {
        "status": "requires_shadow_holdout_review",
        "blockers": ["conditional_winner_refill_overlay_requires_shadow_holdout_review"],
        "conditional_model_token": "wfWinPyrMinExtAS",
        "no_live_order_sent": True,
    }
    holdout = {
        "status": "historical_proxy_pass_real_shadow_required",
        "candidate_report": "reports/formal.json",
        "aggregate_delta": {"return_delta_pct": 731.0727},
        "tail_holdout_proxy": {"passed": True, "return_delta_pct": 2.3921},
        "conditional_token_proxy": {"passed": True},
        "fold_delta_summary": {"changed_folds": [9, 11, 14]},
        "blockers": [],
        "warnings": ["historical_proxy_does_not_replace_real_shadow_holdout"],
        "limitations": ["uses_historical_wfo_archive_after_the_rule_was_known"],
        "no_live_order_sent": True,
    }
    report = build_meta_router_promotion_gate(
        compare_report=compare,
        readiness_report=_readiness(execution_parity_passed=True),
        conditional_overfit_holdout_audit_report=holdout,
        input_conditional_overfit_holdout_audit_report="reports/holdout_proxy.json",
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    template = _conditional_overfit_operator_review_template_report(
        report=report,
        source_promotion_gate_report="reports/promotion_gate.json",
    )

    assert template is not None
    assert template["status"] == "pending_conditional_overfit_operator_review"
    assert template["candidate_recipe_id"] == "router_contract_observe_only_formal"
    assert template["candidate_report"] == "reports/formal.json"
    assert template["overfit_blockers"] == [
        "conditional_winner_refill_overlay_requires_shadow_holdout_review"
    ]
    assert template["proxy_audit_report"] == "reports/holdout_proxy.json"
    assert template["proxy_passed"] is True
    assert isinstance(template["review_packet_fingerprint"], str)
    assert len(template["review_packet_fingerprint"]) == 64
    assert template["source_promotion_gate_report"] == "reports/promotion_gate.json"
    assert template["operator_fields_to_fill"]["paper_only_scope"] is True
    assert (
        template["operator_fields_to_fill"]["real_shadow_still_required_before_tiny_canary_or_live"]
        is True
    )
    skeleton = template["operator_review_json_skeleton"]
    assert skeleton["candidate_report"] == "reports/formal.json"
    assert skeleton["proxy_audit_report"] == "reports/holdout_proxy.json"
    assert skeleton["review_packet_fingerprint"] == template["review_packet_fingerprint"]
    assert skeleton["acceptance_contract"]["candidate_report_must_match"] == "reports/formal.json"
    assert skeleton["acceptance_contract"]["proxy_audit_report_must_match"] == "reports/holdout_proxy.json"
    assert skeleton["acceptance_contract"]["paper_only_scope_must_be_true"] is True
    assert (
        skeleton["acceptance_contract"][
            "real_shadow_still_required_before_tiny_canary_or_live_must_be_true"
        ]
        is True
    )
    assert "--conditional-overfit-operator-review-report" in template["validation_command_template"]
    assert template["validation_contract"]["paper_only_scope"] is True
    assert template["order_submission_allowed"] is False
    assert template["no_live_order_sent"] is True


def test_meta_router_promotion_gate_accepts_conditional_overfit_operator_review_for_paper_only() -> None:
    compare = _compare()
    compare["best_candidate"]["overfit_audit"] = {
        "status": "requires_shadow_holdout_review",
        "blockers": ["conditional_winner_refill_overlay_requires_shadow_holdout_review"],
        "conditional_model_token": "wfWinPyrMinExtAS",
        "no_live_order_sent": True,
    }
    holdout = {
        "status": "historical_proxy_pass_real_shadow_required",
        "candidate_report": "reports/formal.json",
        "aggregate_delta": {"return_delta_pct": 731.0727},
        "tail_holdout_proxy": {"passed": True, "return_delta_pct": 2.3921},
        "conditional_token_proxy": {"passed": True},
        "fold_delta_summary": {"changed_folds": [9, 11, 14]},
        "blockers": [],
        "warnings": ["historical_proxy_does_not_replace_real_shadow_holdout"],
        "limitations": ["uses_historical_wfo_archive_after_the_rule_was_known"],
        "no_live_order_sent": True,
    }
    pending_report = build_meta_router_promotion_gate(
        compare_report=compare,
        readiness_report=_readiness(execution_parity_passed=True),
        conditional_overfit_holdout_audit_report=holdout,
        input_conditional_overfit_holdout_audit_report="reports/holdout_proxy.json",
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )
    template = pending_report["conditional_overfit_operator_review"]["operator_review_template"]
    review = {
        "status": "conditional_overfit_review_accepted",
        "candidate_recipe_id": "router_contract_observe_only_formal",
        "candidate_report": "reports/formal.json",
        "overfit_blockers": ["conditional_winner_refill_overlay_requires_shadow_holdout_review"],
        "proxy_audit_report": "reports/holdout_proxy.json",
        "review_packet_summary": template["review_packet_summary"],
        "review_packet_fingerprint": template["review_packet_fingerprint"],
        "source_promotion_gate_report": "reports/promotion_gate.json",
        "source_promotion_gate_generated_at": "2026-06-07T00:00:00+00:00",
        "reviewer": "operator",
        "reviewed_at": "2026-06-07T00:01:00+00:00",
        "rationale": "Historical proxy is accepted for paper-only shadow while real shadow remains required.",
        "paper_only_scope": True,
        "real_shadow_still_required_before_tiny_canary_or_live": True,
        "no_live_order_sent": True,
    }

    report = build_meta_router_promotion_gate(
        compare_report=compare,
        readiness_report=_readiness(execution_parity_passed=True),
        conditional_overfit_holdout_audit_report=holdout,
        input_conditional_overfit_holdout_audit_report="reports/holdout_proxy.json",
        conditional_overfit_operator_review_report=review,
        input_conditional_overfit_operator_review_report="reports/conditional_overfit_review.json",
        expected_operator_lineage_source_report="reports/promotion_gate.json",
        generated_at=datetime(2026, 6, 7, 0, 5, tzinfo=UTC),
    )

    assert report["promotion_decision"] == "paper_ready_with_readiness_warnings"
    assert "conditional_overfit_review_accepted_for_paper_only" in report["decision_reasons"]
    assert "complete_real_shadow_holdout_before_tiny_canary_or_full_live" in report["next_actions"]
    assert report["conditional_overfit_operator_review"]["accepted_for_paper_only"] is True
    assert report["conditional_overfit_operator_review"]["operator_review"]["matched"] is True
    assert report["conditional_overfit_operator_review"][
        "real_shadow_still_required_before_tiny_canary_or_live"
    ] is True
    assert report["no_live_order_sent"] is True


def test_meta_router_promotion_gate_blocks_defensive_switch_until_lineage_review() -> None:
    report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["promotion_decision"] == "paper_ready_with_readiness_warnings"
    assert report["candidate_switch_policy"]["status"] == (
        "candidate_switch_blocked_pending_defensive_lineage_review"
    )
    assert report["candidate_switch_policy"]["defensive_route_eligible_after_current_gates"] is False
    assert report["candidate_switch_policy"]["execution_parity_passed"] is True
    assert report["candidate_switch_policy"]["defensive_lineage_review_required"] is True
    assert report["candidate_switch_policy"]["defensive_lineage_review_passed"] is False
    assert "defensive_lineage_review_not_passed" in report["candidate_switch_policy"]["promotion_blockers"]
    assert report["candidate_switch_policy"]["next_action"] == (
        "review_defensive_lineage_delta_before_operator_route_selection"
    )


def test_meta_router_promotion_gate_builds_pending_operator_lineage_review_template() -> None:
    report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    template = _operator_lineage_review_template_report(
        report=report,
        source_promotion_gate_report="reports/promotion_gate.json",
    )

    assert template is not None
    assert template["status"] == "pending_operator_lineage_review"
    assert template["candidate_recipe_id"] == "selective_mode_loss_after_selection"
    assert template["reviewed_folds"] == [11]
    assert template["review_packet_summary"] == "lineage_watch_is_limited_to_intentional_size_overlay_folds"
    assert isinstance(template["review_packet_fingerprint"], str)
    assert len(template["review_packet_fingerprint"]) == 64
    assert template["source_promotion_gate_report"] == "reports/promotion_gate.json"
    assert template["source_promotion_gate_generated_at"] == "2026-06-07T00:00:00+00:00"
    assert template["operator_fields_to_fill"]["source_promotion_gate_report"] == (
        "reports/promotion_gate.json"
    )
    assert template["acceptance_contract"]["source_promotion_gate_report_must_match"] == (
        "reports/promotion_gate.json"
    )
    assert template["acceptance_contract"]["review_packet_fingerprint_must_match"] == (
        template["review_packet_fingerprint"]
    )
    assert template["acceptance_contract"][
        "reviewed_at_must_be_at_or_after_promotion_gate_generated_at"
    ] == "2026-06-07T00:00:00+00:00"
    assert template["acceptance_contract"]["reviewer_must_be_non_empty"] is True
    assert template["acceptance_contract"]["rationale_must_be_non_empty"] is True
    assert template["operator_fields_to_fill"]["reviewed_at"] == (
        "iso8601_timestamp_after_this_template_was_generated"
    )
    assert template["acceptance_contract"]["no_live_order_sent_must_be_true"] is True
    assert template["operator_fields_to_fill"]["no_live_order_sent"] is True
    assert template["operator_review_json_skeleton"] == {
        "status": "operator_lineage_review_accepted_or_rejected",
        "candidate_recipe_id": "selective_mode_loss_after_selection",
        "reviewed_folds": [11],
        "review_packet_summary": "lineage_watch_is_limited_to_intentional_size_overlay_folds",
        "review_packet_fingerprint": template["review_packet_fingerprint"],
        "source_promotion_gate_report": "reports/promotion_gate.json",
        "source_promotion_gate_generated_at": "2026-06-07T00:00:00+00:00",
        "reviewer": "operator_name_or_initials",
        "reviewed_at": "iso8601_timestamp_after_this_template_was_generated",
        "rationale": "why_the_defensive_size_overlay_delta_is_accepted_or_rejected",
        "acceptance_contract": template["acceptance_contract"],
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    assert template["validation_command_template"] == (
        ".venv/bin/python scripts/run_market_state_rotation_v6_meta_router_promotion_gate.py "
        "--operator-lineage-review-report <operator_lineage_review_report.json> "
        "--expected-operator-lineage-source-report reports/promotion_gate.json"
    )
    assert template["validation_contract"] == {
        "purpose": "validate_operator_lineage_review_before_writing_or_promoting_any_route",
        "expected_operator_lineage_source_report": "reports/promotion_gate.json",
        "expected_operator_review_status_path": (
            "candidate_switch_policy.defensive_lineage_review.operator_review.status"
        ),
        "expected_no_live_order_sent": True,
        "write_report_required_for_validation": False,
        "order_submission_allowed": False,
    }
    assert template["order_submission_allowed"] is False
    assert template["no_live_order_sent"] is True


def test_meta_router_promotion_gate_accepts_matching_operator_lineage_review() -> None:
    pending_report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )
    template = pending_report["candidate_switch_policy"]["defensive_lineage_review"][
        "operator_review_template"
    ]
    review = {
        "status": "operator_lineage_review_accepted",
        "candidate_recipe_id": "selective_mode_loss_after_selection",
        "reviewed_folds": [11],
        "review_packet_summary": "lineage_watch_is_limited_to_intentional_size_overlay_folds",
        "review_packet_fingerprint": template["review_packet_fingerprint"],
        "source_promotion_gate_report": "reports/promotion_gate.json",
        "source_promotion_gate_generated_at": "2026-06-07T00:00:00+00:00",
        "reviewer": "operator",
        "reviewed_at": "2026-06-07T00:01:00+00:00",
        "rationale": "Fold 11 delta is the expected defensive size overlay.",
        "no_live_order_sent": True,
    }

    report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        operator_lineage_review_report=review,
        input_operator_lineage_review_report="reports/operator_review.json",
        expected_operator_lineage_source_report="reports/promotion_gate.json",
        generated_at=datetime(2026, 6, 7, 0, 5, tzinfo=UTC),
    )

    policy = report["candidate_switch_policy"]
    assert report["input_operator_lineage_review_report"] == "reports/operator_review.json"
    assert policy["status"] == "candidate_switch_ready_for_operator_review"
    assert policy["defensive_route_eligible_after_current_gates"] is True
    assert policy["defensive_lineage_review_required"] is True
    assert policy["defensive_lineage_review_passed"] is True
    assert policy["defensive_lineage_review"]["status"] == "operator_lineage_review_accepted"
    assert policy["defensive_lineage_review"]["operator_review"]["matched"] is True
    assert policy["defensive_lineage_review"]["operator_review"]["reviewed_at"] == (
        "2026-06-07T00:01:00+00:00"
    )
    assert policy["defensive_lineage_review"]["operator_review"][
        "source_promotion_gate_generated_at"
    ] == "2026-06-07T00:00:00+00:00"
    assert policy["defensive_lineage_review"]["operator_review"][
        "source_promotion_gate_report"
    ] == "reports/promotion_gate.json"
    assert policy["defensive_lineage_review"]["operator_review"][
        "expected_source_promotion_gate_report"
    ] == "reports/promotion_gate.json"
    assert policy["defensive_lineage_review"]["operator_review"]["validation_generated_at"] == (
        "2026-06-07T00:05:00+00:00"
    )
    assert policy["defensive_lineage_review"]["operator_review"]["reviewer"] == "operator"
    assert policy["defensive_lineage_review"]["operator_review"]["rationale"] == (
        "Fold 11 delta is the expected defensive size overlay."
    )
    assert policy["promotion_blockers"] == []
    assert policy["auto_switch_allowed_now"] is False


def test_meta_router_promotion_gate_cli_enforces_report_dir_source_without_write(tmp_path) -> None:
    compare_path = tmp_path / "compare.json"
    readiness_path = tmp_path / "readiness.json"
    review_path = tmp_path / "operator_review.json"
    report_dir = "reports/test_cli_operator_lineage_source"
    expected_source = f"{report_dir}/market_state_rotation_v6_meta_router_promotion_gate.json"

    pending_report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )
    template = pending_report["candidate_switch_policy"]["defensive_lineage_review"][
        "operator_review_template"
    ]
    compare_path.write_text(json.dumps(_compare()), encoding="utf-8")
    readiness_path.write_text(json.dumps(_readiness(execution_parity_passed=True)), encoding="utf-8")
    review_path.write_text(
        json.dumps(
            {
                "status": "operator_lineage_review_accepted",
                "candidate_recipe_id": "selective_mode_loss_after_selection",
                "reviewed_folds": [11],
                "review_packet_summary": "lineage_watch_is_limited_to_intentional_size_overlay_folds",
                "review_packet_fingerprint": template["review_packet_fingerprint"],
                "source_promotion_gate_report": expected_source,
                "source_promotion_gate_generated_at": "2026-06-07T00:00:00+00:00",
                "reviewer": "operator",
                "reviewed_at": "2026-06-07T00:01:00+00:00",
                "rationale": "CLI no-write validation should still enforce source report.",
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_market_state_rotation_v6_meta_router_promotion_gate.py",
            "--compare-report",
            str(compare_path),
            "--readiness-report",
            str(readiness_path),
            "--operator-lineage-review-report",
            str(review_path),
            "--report-dir",
            report_dir,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(result.stdout)
    policy = report["candidate_switch_policy"]
    assert report["expected_operator_lineage_source_report"] == expected_source
    assert policy["defensive_lineage_review"]["operator_review"]["matched"] is True
    assert policy["defensive_lineage_review"]["operator_review"][
        "expected_source_promotion_gate_report"
    ] == expected_source
    assert policy["promotion_blockers"] == []
    assert report["no_live_order_sent"] is True


def test_meta_router_promotion_gate_write_report_emits_operator_review_skeleton(tmp_path) -> None:
    compare_path = tmp_path / "compare.json"
    readiness_path = tmp_path / "readiness.json"
    report_dir = tmp_path / "promotion_gate"
    compare_path.write_text(json.dumps(_compare()), encoding="utf-8")
    readiness_path.write_text(json.dumps(_readiness(execution_parity_passed=True)), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_market_state_rotation_v6_meta_router_promotion_gate.py",
            "--compare-report",
            str(compare_path),
            "--readiness-report",
            str(readiness_path),
            "--report-dir",
            str(report_dir),
            "--write-report",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    report_path = report_dir / "market_state_rotation_v6_meta_router_promotion_gate.json"
    template_path = report_dir / "market_state_rotation_v6_operator_lineage_review_template.json"
    skeleton_path = report_dir / "market_state_rotation_v6_operator_lineage_review_skeleton.json"
    assert report_path.exists()
    assert template_path.exists()
    assert skeleton_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    template = json.loads(template_path.read_text(encoding="utf-8"))
    skeleton = json.loads(skeleton_path.read_text(encoding="utf-8"))
    assert report["operator_lineage_review_template_report"] == str(template_path)
    assert report["operator_lineage_review_skeleton_report"] == str(skeleton_path)
    assert report["operator_lineage_artifact_manifest"]["fingerprint_algorithm"] == "sha256_canonical_json"
    assert report["operator_lineage_artifact_manifest"]["template_report"] == str(template_path)
    assert len(report["operator_lineage_artifact_manifest"]["template_payload_fingerprint"]) == 64
    assert report["operator_lineage_artifact_manifest"]["skeleton_report"] == str(skeleton_path)
    assert len(report["operator_lineage_artifact_manifest"]["skeleton_payload_fingerprint"]) == 64
    assert report["operator_lineage_artifact_manifest"]["order_submission_allowed"] is False
    assert report["operator_lineage_artifact_manifest"]["no_live_order_sent"] is True
    assert template["operator_review_json_skeleton_report"] == str(skeleton_path)
    assert skeleton["source_template_report"] == str(template_path)
    assert skeleton["skeleton_report_path"] == str(skeleton_path)
    assert skeleton["candidate_recipe_id"] == "selective_mode_loss_after_selection"
    assert skeleton["reviewed_folds"] == [11]
    assert skeleton["acceptance_contract"] == template["acceptance_contract"]
    assert "--expected-operator-lineage-source-report" in skeleton["validation_command_template"]
    assert skeleton["order_submission_allowed"] is False
    assert skeleton["no_live_order_sent"] is True


def test_meta_router_promotion_gate_write_report_emits_conditional_overfit_review_skeleton(tmp_path) -> None:
    compare = _compare()
    compare["best_candidate"]["overfit_audit"] = {
        "status": "requires_shadow_holdout_review",
        "blockers": ["conditional_winner_refill_overlay_requires_shadow_holdout_review"],
        "conditional_model_token": "wfWinPyrMinExtAS",
        "no_live_order_sent": True,
    }
    holdout = {
        "status": "historical_proxy_pass_real_shadow_required",
        "candidate_report": "reports/formal.json",
        "aggregate_delta": {"return_delta_pct": 731.0727},
        "tail_holdout_proxy": {"passed": True, "return_delta_pct": 2.3921},
        "conditional_token_proxy": {"passed": True},
        "fold_delta_summary": {"changed_folds": [9, 11, 14]},
        "blockers": [],
        "warnings": ["historical_proxy_does_not_replace_real_shadow_holdout"],
        "limitations": ["uses_historical_wfo_archive_after_the_rule_was_known"],
        "no_live_order_sent": True,
    }
    compare_path = tmp_path / "compare.json"
    readiness_path = tmp_path / "readiness.json"
    holdout_path = tmp_path / "holdout.json"
    report_dir = tmp_path / "promotion_gate"
    compare_path.write_text(json.dumps(compare), encoding="utf-8")
    readiness_path.write_text(json.dumps(_readiness(execution_parity_passed=True)), encoding="utf-8")
    holdout_path.write_text(json.dumps(holdout), encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            "scripts/run_market_state_rotation_v6_meta_router_promotion_gate.py",
            "--compare-report",
            str(compare_path),
            "--readiness-report",
            str(readiness_path),
            "--conditional-overfit-holdout-audit-report",
            str(holdout_path),
            "--report-dir",
            str(report_dir),
            "--write-report",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    report_path = report_dir / "market_state_rotation_v6_meta_router_promotion_gate.json"
    template_path = report_dir / "market_state_rotation_v6_conditional_overfit_operator_review_template.json"
    skeleton_path = report_dir / "market_state_rotation_v6_conditional_overfit_operator_review_skeleton.json"
    assert report_path.exists()
    assert template_path.exists()
    assert skeleton_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    template = json.loads(template_path.read_text(encoding="utf-8"))
    skeleton = json.loads(skeleton_path.read_text(encoding="utf-8"))
    assert report["conditional_overfit_operator_review_template_report"] == str(template_path)
    assert report["conditional_overfit_operator_review_skeleton_report"] == str(skeleton_path)
    manifest = report["conditional_overfit_operator_review_artifact_manifest"]
    assert manifest["fingerprint_algorithm"] == "sha256_canonical_json"
    assert manifest["template_report"] == str(template_path)
    assert len(manifest["template_payload_fingerprint"]) == 64
    assert manifest["skeleton_report"] == str(skeleton_path)
    assert len(manifest["skeleton_payload_fingerprint"]) == 64
    assert manifest["paper_only_scope"] is True
    assert manifest["real_shadow_still_required_before_tiny_canary_or_live"] is True
    assert manifest["order_submission_allowed"] is False
    assert manifest["no_live_order_sent"] is True
    assert template["operator_review_json_skeleton_report"] == str(skeleton_path)
    assert skeleton["source_template_report"] == str(template_path)
    assert skeleton["skeleton_report_path"] == str(skeleton_path)
    assert skeleton["candidate_report"] == "reports/formal.json"
    assert skeleton["proxy_audit_report"] == str(holdout_path)
    assert skeleton["paper_only_scope"] is True
    assert skeleton["real_shadow_still_required_before_tiny_canary_or_live"] is True
    assert "--conditional-overfit-operator-review-report" in skeleton["validation_command_template"]
    assert skeleton["order_submission_allowed"] is False
    assert skeleton["no_live_order_sent"] is True


def test_meta_router_promotion_gate_rejects_mismatched_operator_lineage_review() -> None:
    pending_report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )
    template = pending_report["candidate_switch_policy"]["defensive_lineage_review"][
        "operator_review_template"
    ]
    review = {
        "status": "operator_lineage_review_accepted",
        "candidate_recipe_id": "older_candidate",
        "reviewed_folds": [11],
        "review_packet_summary": "lineage_watch_is_limited_to_intentional_size_overlay_folds",
        "review_packet_fingerprint": template["review_packet_fingerprint"],
        "source_promotion_gate_generated_at": "2026-06-07T00:00:00+00:00",
        "reviewed_at": "2026-06-07T00:01:00+00:00",
        "no_live_order_sent": True,
    }

    report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        operator_lineage_review_report=review,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    policy = report["candidate_switch_policy"]
    assert policy["status"] == "candidate_switch_blocked_pending_defensive_lineage_review"
    assert policy["defensive_route_eligible_after_current_gates"] is False
    assert policy["defensive_lineage_review_passed"] is False
    assert "operator_lineage_review_candidate_mismatch" in policy["promotion_blockers"]


def test_meta_router_promotion_gate_rejects_lineage_review_with_missing_source_report() -> None:
    pending_report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )
    template = pending_report["candidate_switch_policy"]["defensive_lineage_review"][
        "operator_review_template"
    ]
    review = {
        "status": "operator_lineage_review_accepted",
        "candidate_recipe_id": "selective_mode_loss_after_selection",
        "reviewed_folds": [11],
        "review_packet_summary": "lineage_watch_is_limited_to_intentional_size_overlay_folds",
        "review_packet_fingerprint": template["review_packet_fingerprint"],
        "source_promotion_gate_generated_at": "2026-06-07T00:00:00+00:00",
        "reviewed_at": "2026-06-07T00:01:00+00:00",
        "reviewer": "operator",
        "rationale": "Missing source report should fail.",
        "no_live_order_sent": True,
    }

    report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        operator_lineage_review_report=review,
        expected_operator_lineage_source_report="reports/promotion_gate.json",
        generated_at=datetime(2026, 6, 7, 0, 5, tzinfo=UTC),
    )

    policy = report["candidate_switch_policy"]
    assert policy["status"] == "candidate_switch_blocked_pending_defensive_lineage_review"
    assert policy["defensive_lineage_review_passed"] is False
    assert "operator_lineage_review_source_promotion_gate_report_missing" in policy["promotion_blockers"]


def test_meta_router_promotion_gate_rejects_lineage_review_with_mismatched_source_report() -> None:
    pending_report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )
    template = pending_report["candidate_switch_policy"]["defensive_lineage_review"][
        "operator_review_template"
    ]
    review = {
        "status": "operator_lineage_review_accepted",
        "candidate_recipe_id": "selective_mode_loss_after_selection",
        "reviewed_folds": [11],
        "review_packet_summary": "lineage_watch_is_limited_to_intentional_size_overlay_folds",
        "review_packet_fingerprint": template["review_packet_fingerprint"],
        "source_promotion_gate_report": "reports/older_promotion_gate.json",
        "source_promotion_gate_generated_at": "2026-06-07T00:00:00+00:00",
        "reviewed_at": "2026-06-07T00:01:00+00:00",
        "reviewer": "operator",
        "rationale": "Mismatched source report should fail.",
        "no_live_order_sent": True,
    }

    report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        operator_lineage_review_report=review,
        expected_operator_lineage_source_report="reports/promotion_gate.json",
        generated_at=datetime(2026, 6, 7, 0, 5, tzinfo=UTC),
    )

    policy = report["candidate_switch_policy"]
    assert policy["status"] == "candidate_switch_blocked_pending_defensive_lineage_review"
    assert policy["defensive_lineage_review_passed"] is False
    assert "operator_lineage_review_source_promotion_gate_report_mismatch" in policy["promotion_blockers"]


def test_meta_router_promotion_gate_rejects_stale_lineage_review_fingerprint() -> None:
    review = {
        "status": "operator_lineage_review_accepted",
        "candidate_recipe_id": "selective_mode_loss_after_selection",
        "reviewed_folds": [11],
        "review_packet_summary": "lineage_watch_is_limited_to_intentional_size_overlay_folds",
        "review_packet_fingerprint": "0" * 64,
        "source_promotion_gate_generated_at": "2026-06-07T00:00:00+00:00",
        "reviewer": "operator",
        "reviewed_at": "2026-06-07T00:01:00+00:00",
        "rationale": "Reject stale fingerprint.",
        "no_live_order_sent": True,
    }

    report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        operator_lineage_review_report=review,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    policy = report["candidate_switch_policy"]
    assert policy["status"] == "candidate_switch_blocked_pending_defensive_lineage_review"
    assert policy["defensive_lineage_review_passed"] is False
    assert "operator_lineage_review_fingerprint_mismatch" in policy["promotion_blockers"]


def test_meta_router_promotion_gate_rejects_lineage_review_before_promotion_gate() -> None:
    pending_report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )
    template = pending_report["candidate_switch_policy"]["defensive_lineage_review"][
        "operator_review_template"
    ]
    review = {
        "status": "operator_lineage_review_accepted",
        "candidate_recipe_id": "selective_mode_loss_after_selection",
        "reviewed_folds": [11],
        "review_packet_summary": "lineage_watch_is_limited_to_intentional_size_overlay_folds",
        "review_packet_fingerprint": template["review_packet_fingerprint"],
        "source_promotion_gate_generated_at": "2026-06-07T00:00:00+00:00",
        "reviewed_at": "2026-06-06T23:59:00+00:00",
        "reviewer": "operator",
        "rationale": "Reviewed before template source, should fail.",
        "no_live_order_sent": True,
    }

    report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        operator_lineage_review_report=review,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    policy = report["candidate_switch_policy"]
    assert policy["status"] == "candidate_switch_blocked_pending_defensive_lineage_review"
    assert policy["defensive_lineage_review_passed"] is False
    assert "operator_lineage_review_reviewed_before_promotion_gate" in policy["promotion_blockers"]


def test_meta_router_promotion_gate_rejects_lineage_review_without_source_generated_at() -> None:
    pending_report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )
    template = pending_report["candidate_switch_policy"]["defensive_lineage_review"][
        "operator_review_template"
    ]
    review = {
        "status": "operator_lineage_review_accepted",
        "candidate_recipe_id": "selective_mode_loss_after_selection",
        "reviewed_folds": [11],
        "review_packet_summary": "lineage_watch_is_limited_to_intentional_size_overlay_folds",
        "review_packet_fingerprint": template["review_packet_fingerprint"],
        "reviewed_at": "2026-06-07T00:01:00+00:00",
        "reviewer": "operator",
        "rationale": "Missing source timestamp should fail closed.",
        "no_live_order_sent": True,
    }

    report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        operator_lineage_review_report=review,
        generated_at=datetime(2026, 6, 7, 0, 5, tzinfo=UTC),
    )

    policy = report["candidate_switch_policy"]
    assert policy["status"] == "candidate_switch_blocked_pending_defensive_lineage_review"
    assert policy["defensive_lineage_review_passed"] is False
    assert (
        "operator_lineage_review_source_promotion_gate_generated_at_missing_or_invalid"
        in policy["promotion_blockers"]
    )


def test_meta_router_promotion_gate_does_not_treat_review_generated_at_as_source_timestamp() -> None:
    pending_report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )
    template = pending_report["candidate_switch_policy"]["defensive_lineage_review"][
        "operator_review_template"
    ]
    review = {
        "generated_at": "2026-06-07T00:01:00+00:00",
        "status": "operator_lineage_review_accepted",
        "candidate_recipe_id": "selective_mode_loss_after_selection",
        "reviewed_folds": [11],
        "review_packet_summary": "lineage_watch_is_limited_to_intentional_size_overlay_folds",
        "review_packet_fingerprint": template["review_packet_fingerprint"],
        "reviewed_at": "2026-06-07T00:02:00+00:00",
        "reviewer": "operator",
        "rationale": "Generic generated_at is not source promotion gate provenance.",
        "no_live_order_sent": True,
    }

    report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        operator_lineage_review_report=review,
        generated_at=datetime(2026, 6, 7, 0, 5, tzinfo=UTC),
    )

    policy = report["candidate_switch_policy"]
    assert policy["status"] == "candidate_switch_blocked_pending_defensive_lineage_review"
    assert policy["defensive_lineage_review_passed"] is False
    assert (
        "operator_lineage_review_source_promotion_gate_generated_at_missing_or_invalid"
        in policy["promotion_blockers"]
    )


def test_meta_router_promotion_gate_rejects_lineage_review_without_reviewer_or_rationale() -> None:
    pending_report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )
    template = pending_report["candidate_switch_policy"]["defensive_lineage_review"][
        "operator_review_template"
    ]
    review = {
        "status": "operator_lineage_review_accepted",
        "candidate_recipe_id": "selective_mode_loss_after_selection",
        "reviewed_folds": [11],
        "review_packet_summary": "lineage_watch_is_limited_to_intentional_size_overlay_folds",
        "review_packet_fingerprint": template["review_packet_fingerprint"],
        "source_promotion_gate_generated_at": "2026-06-07T00:00:00+00:00",
        "reviewed_at": "2026-06-07T00:01:00+00:00",
        "reviewer": "  ",
        "rationale": "",
        "no_live_order_sent": True,
    }

    report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(execution_parity_passed=True),
        operator_lineage_review_report=review,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    policy = report["candidate_switch_policy"]
    assert policy["status"] == "candidate_switch_blocked_pending_defensive_lineage_review"
    assert policy["defensive_lineage_review_passed"] is False
    assert "operator_lineage_review_reviewer_missing" in policy["promotion_blockers"]
    assert "operator_lineage_review_rationale_missing" in policy["promotion_blockers"]


def test_meta_router_promotion_gate_requires_formal_candidate() -> None:
    report = build_meta_router_promotion_gate(
        compare_report=_compare(best_decision="smoke_pass_run_formal_wfo"),
        readiness_report=_readiness(),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["promotion_decision"] == "blocked_no_formal_wfo_promotion_candidate"
    assert report["decision_reasons"] == ["best_candidate_is_not_formal_promotion_candidate"]


def test_meta_router_promotion_gate_blocks_mismatched_readiness_report() -> None:
    readiness = _readiness()
    readiness["input_walk_report"] = "reports/older_candidate.json"

    report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=readiness,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["promotion_decision"] == "blocked_readiness_candidate_mismatch"
    assert report["next_blocker"] == "readiness_candidate_report_mismatch"
    assert report["readiness_candidate_alignment"]["passed"] is False


def test_meta_router_promotion_gate_distinguishes_attached_failed_parity() -> None:
    readiness = _readiness()
    readiness["execution_parity"] = {
        "available": True,
        "passed": False,
        "blockers": ["execution_journal_missing", "insufficient_execution_sample_count"],
    }

    report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=readiness,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["promotion_decision"] == "paper_ready_pending_execution_parity"
    assert report["decision_reasons"] == [
        "formal_wfo_passed",
        "paper_readiness_passed",
        "execution_parity_not_passed",
    ]


def test_meta_router_promotion_gate_reconstructs_execution_delta_when_compare_audit_missing() -> None:
    compare = _compare()
    candidate_metrics = compare["best_candidate"]["candidate"]
    candidate_metrics.pop("execution_change_audit")
    candidate_metrics["return_delta_vs_baseline_pct"] = 4.2
    candidate_metrics["drawdown_delta_vs_baseline_pct"] = -0.5
    candidate_metrics["cost_delta_vs_baseline_pct"] = -0.1
    candidate_metrics["trade_event_delta_vs_baseline"] = 3

    report = build_meta_router_promotion_gate(
        compare_report=compare,
        readiness_report=_readiness(),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["performance_upgrade_ready"] is True
    assert report["performance_delta_status"] == "performance_metric_delta_detected"
    assert report["performance_upgrade_blockers"] == []
    assert report["candidate"]["execution_change_audit"]["trade_event_delta_vs_baseline"] == 3
