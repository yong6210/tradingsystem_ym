from __future__ import annotations

from scripts import generate_operator_session_brief


def _fake_snapshot() -> dict:
    return {
        "deployment_alignment": "DIVERGED",
        "playbook_alignment": "DIVERGED",
        "approval_strip": {
            "approve_value": "validation/checklist no_go",
            "align_value": "diverged",
            "act_value": "continue_candidate_review_under_portfolio_caps",
            "act_priority_level": "urgent",
            "primary_reason": "MANUAL_REVIEW",
            "approve_reason": "validation=NO_GO | checklist=NO_GO | dashboard=GO | MANUAL_REVIEW",
            "align_reason": "dashboard / checklist / validation surface가 서로 다른 방향을 가리키고 있습니다.",
            "act_reason": "continue candidate review",
        },
        "dashboard_summary": {
            "deployment_go_no_go": "GO",
            "playbook_action": "continue_candidate_review_under_portfolio_caps",
            "top_operator_action": "continue_candidate_review_under_portfolio_caps",
            "top_action_followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review",
            "execution_mode": "live",
            "approval_strip_summary": {
                "approve_value": "approval usable",
                "align_value": "aligned",
                "act_value": "continue_candidate_review_under_portfolio_caps",
            },
        },
        "validation_summary": {
            "deployment_go_no_go": "NO_GO",
            "playbook_action": "resolve_selected_trial_lineage_before_rollout",
            "approval_topline_status": "WARN",
            "validation_report": {
                "approval_strip_summary": {
                    "approve_value": "validation no_go",
                    "align_value": "playbook_drift",
                    "act_value": "review_runtime_execution_drag_before_expansion",
                }
            },
        },
        "checklist_summary": {
            "deployment_go_no_go": "NO_GO",
            "playbook_action": "resolve_selected_trial_lineage_before_rollout",
            "overall_status": "WARN",
            "approval_strip_summary": {
                "approve_value": "validation/checklist no_go",
                "align_value": "aligned",
                "act_value": "clear_blocking_operational_items_before_rollout",
            },
        },
        "kernel_snapshot": {
            "kernel_verdict": "manual_review",
            "money_leak_r": 0.33,
            "strongest_drag_source": "fill_capture_gap",
            "outcome_control_tier": "downgrade_to_manual",
            "rollout_recommendation": "reduce",
            "candidate_surface_priority": "context_only",
            "expected_closed_r": 1.2,
            "post_cost_closed_r": 0.8,
            "closed_post_cost_delta_r": -0.4,
        },
        "operator_ui_sections": {
            "all_present": True,
            "present_sections": ["5-Second Operator Kernel", "Approval Strip"],
            "missing_sections": [],
        },
        "signal_funnel_snapshot": {
            "research_action": "run_shadow_exit_timing_review",
            "shadow_experiment": "shadow_exit_timing_review",
            "top_action_followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review",
            "edge_state": "watch_edge",
            "edge_evolution_state": "reduce_candidate",
            "edge_evolution_action": "reduce_baseline_allocation_review",
            "edge_evolution_bias": "reduce_baseline",
            "edge_evolution_promotion_axis": "entry_timing",
            "edge_evolution_promotion_variant": "early_limit",
            "review_followup_ledger": {
                "available": True,
                "last_status": "READY",
                "last_action": "reduce_baseline_allocation_review",
                "recent_entry_count": 3,
                "last_followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review",
            },
            "entry_timing_focus": "early_limit",
            "execution_style_focus": "passive_limit",
            "entry_timing_review_target": {
                "action": "run_entry_timing_split_review",
                "preferred_variant": "early_limit",
                "symbol": "ETHUSDC",
                "status": "ACTIONABLE_ENTRY",
                "strategy_family": "sweep_reversal",
                "focus_source": "accepted_candidate_focus",
                "followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action run_entry_timing_split_review",
            },
            "execution_style_review_target": {
                "action": "run_execution_style_split_review",
                "preferred_variant": "passive_limit",
                "symbol": "ETHUSDC",
                "status": "ACTIONABLE_ENTRY",
                "strategy_family": "sweep_reversal",
                "focus_source": "accepted_candidate_focus",
                "followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action run_execution_style_split_review",
            },
            "representative_accepted_candidate": {
                "symbol": "ETHUSDC",
                "status": "ACTIONABLE_ENTRY",
                "strategy_family": "sweep_reversal",
                "edge_state": "watch_edge",
                "entry_timing_focus": "early_limit",
                "execution_style_focus": "passive_limit",
            },
            "representative_blocked_candidate": {
                "symbol": "BTCUSDC",
                "status": "BLOCKED_SETUP",
                "strategy_family": "trend_continuation",
                "block_reason": "portfolio_cap",
                "edge_state": "fragile_edge",
                "entry_timing_focus": "reaction_confirmed",
                "execution_style_focus": "market",
            },
            "governance_state": "observe",
            "review_queue": "stable",
            "remediation_queue": "stable",
            "clearance_state": "observe",
            "reopen_queue": "none",
            "decision_brief": "monitor",
            "auto_execution_stage": "manual",
            "hard_gate_bottleneck": "validation_fail",
            "top_family_bottleneck": "legacy_zone_plan",
            "top_regime_bottleneck": "trend_day",
            "top_session_bottleneck": "preferred_live_window",
        },
    }


def test_headline_starts_with_approval_strip() -> None:
    headline = generate_operator_session_brief._headline(_fake_snapshot(), "DEPLOYMENT_REVIEW_REQUIRED")

    assert headline.startswith(
        "approval_strip: approve=validation/checklist no_go | align=diverged | act=continue_candidate_review_under_portfolio_caps;"
    )
    assert "dashboard and validation/checklist disagree on deployment posture" in headline


def test_write_report_includes_approval_strip_section(tmp_path) -> None:
    payload = {
        "generated_at": "2026-03-24T00:00:00+00:00",
        "symbol": "BTCUSDC",
        "universe": "usdc_perp_top30",
        "days": 7,
        "brief_status": "DEPLOYMENT_REVIEW_REQUIRED",
        "headline": generate_operator_session_brief._headline(_fake_snapshot(), "DEPLOYMENT_REVIEW_REQUIRED"),
        "next_steps": ["step-a"],
        "snapshot": _fake_snapshot(),
    }
    report_path = tmp_path / "brief.md"

    generate_operator_session_brief._write_report(report_path, payload)

    report = report_path.read_text(encoding="utf-8")
    assert "## Approval Strip" in report
    assert "- approval_strip: approve=validation/checklist no_go | align=diverged | act=continue_candidate_review_under_portfolio_caps | priority=urgent" in report
    assert "- primary_reason: MANUAL_REVIEW" in report
    assert "- dashboard: approve=approval usable / align=aligned / act=continue_candidate_review_under_portfolio_caps / mode=live" in report
    assert "- validation: approve=validation no_go / align=playbook_drift / act=review_runtime_execution_drag_before_expansion / approval_topline_status=WARN" in report
    assert "- checklist: approve=validation/checklist no_go / align=aligned / act=clear_blocking_operational_items_before_rollout / overall_status=WARN" in report
    assert "- top_action_followup_command: ./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review" in report
    assert "- edge_experiment: state=watch_edge | entry_timing=early_limit | execution_style=passive_limit" in report
    assert "- edge_evolution: state=reduce_candidate | action=reduce_baseline_allocation_review | bias=reduce_baseline | promotion=entry_timing/early_limit" in report
    assert "- review_followup_ledger: status=READY / action=reduce_baseline_allocation_review / entries=3 / cmd=./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review" in report
    assert "- entry_timing_review_target: action=run_entry_timing_split_review / target=ETHUSDC / variant=early_limit / status=ACTIONABLE_ENTRY / family=sweep_reversal / focus=accepted_candidate_focus / cmd=./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action run_entry_timing_split_review" in report
    assert "- execution_style_review_target: action=run_execution_style_split_review / target=ETHUSDC / variant=passive_limit / status=ACTIONABLE_ENTRY / family=sweep_reversal / focus=accepted_candidate_focus / cmd=./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action run_execution_style_split_review" in report
    assert "- representative_accepted_candidate: ETHUSDC / family=sweep_reversal / edge=watch_edge / split=early_limit/passive_limit / status=ACTIONABLE_ENTRY" in report
    assert "- representative_blocked_candidate: BTCUSDC / family=trend_continuation / edge=fragile_edge / split=reaction_confirmed/market / status=BLOCKED_SETUP / reason=portfolio_cap" in report
