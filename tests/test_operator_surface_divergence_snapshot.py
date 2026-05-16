from __future__ import annotations

import json
import importlib.util
from types import SimpleNamespace
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


snapshot_script = _load_module(
    "collect_operator_surface_divergence_snapshot_test_module",
    ROOT_DIR / "scripts/collect_operator_surface_divergence_snapshot.py",
)


def test_surface_strip_summary_prefers_nested_validation_strip() -> None:
    summary = snapshot_script._surface_strip_summary(
        {
            "deployment_go_no_go": "NO_GO",
            "playbook_action": "legacy_action",
            "validation_report": {
                "approval_strip_summary": {
                    "approve_value": "validation no_go",
                    "align_value": "playbook_drift",
                    "act_value": "review_runtime_execution_drag_before_expansion",
                    "act_priority_level": "urgent",
                }
            },
        },
        surface_type="validation",
    )

    assert summary["approve_value"] == "validation no_go"
    assert summary["align_value"] == "playbook_drift"
    assert summary["act_value"] == "review_runtime_execution_drag_before_expansion"


def test_alignment_normalizes_advisory_only_checklist_manual_review() -> None:
    dashboard_strip = {
        "approve_value": "approval usable",
        "act_value": "continue_candidate_review_under_portfolio_caps",
    }
    validation_strip = {
        "approve_value": "GO",
        "act_value": "proceed_with_configured_rollout",
    }
    checklist_strip = {
        "approve_value": "manual review first",
        "act_value": "proceed_with_configured_rollout",
    }
    checklist = {"blocking_failures": 0, "manual_actions": 0, "warnings": 14}

    deployment_alignment = snapshot_script._alignment(
        [
            snapshot_script._normalized_approve_alignment_value(dashboard_strip, surface={}),
            snapshot_script._normalized_approve_alignment_value(validation_strip, surface={}),
            snapshot_script._normalized_approve_alignment_value(checklist_strip, surface=checklist),
        ]
    )
    playbook_alignment = snapshot_script._alignment(
        [
            snapshot_script._normalized_act_alignment_value(dashboard_strip),
            snapshot_script._normalized_act_alignment_value(validation_strip),
            snapshot_script._normalized_act_alignment_value(checklist_strip),
        ]
    )

    assert deployment_alignment == "ALIGNED"
    assert playbook_alignment == "ALIGNED"


def test_write_report_uses_surface_strip_lines(tmp_path: Path) -> None:
    payload = {
        "generated_at": "2026-03-24T00:00:00+00:00",
        "symbol": "BTCUSDC",
        "universe": "usdc_perp_top30",
        "days": 7,
        "deployment_alignment": "DIVERGED",
        "playbook_alignment": "DIVERGED",
        "approval_strip": {
            "approve_value": "validation/checklist no_go",
            "align_value": "diverged",
            "act_value": "continue_candidate_review_under_portfolio_caps",
            "act_priority_level": "urgent",
            "primary_reason": "MANUAL_REVIEW",
            "approve_reason": "approve reason",
            "align_reason": "align reason",
            "act_reason": "act reason",
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
        "dashboard_summary": {
            "execution_mode": "live",
            "top_operator_action": "continue_candidate_review_under_portfolio_caps",
            "top_action_followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review",
            "approval_strip_summary": {
                "approve_value": "approval usable",
                "align_value": "aligned",
                "act_value": "continue_candidate_review_under_portfolio_caps",
                "act_priority_level": "monitor",
            },
        },
        "validation_summary": {
            "approval_topline_status": "WARN",
            "approval_strip_summary": {
                "approve_value": "validation no_go",
                "align_value": "playbook_drift",
                "act_value": "review_runtime_execution_drag_before_expansion",
                "act_priority_level": "urgent",
            },
        },
        "checklist_summary": {
            "overall_status": "WARN",
            "approval_strip_summary": {
                "approve_value": "validation/checklist no_go",
                "align_value": "aligned",
                "act_value": "clear_blocking_operational_items_before_rollout",
                "act_priority_level": "urgent",
            },
        },
        "operator_ui_sections": {
            "present_sections": ["5-Second Operator Kernel"],
            "missing_sections": [],
        },
        "signal_funnel_snapshot": {
            "research_action": "run_shadow_exit_timing_review",
            "shadow_experiment": "shadow_exit_timing_review",
            "top_action_followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review",
            "edge_state": "watch_edge",
            "edge_proof_state": "sample_building",
            "edge_claim_state": "do_not_claim_edge_yet",
            "edge_proof_goal_closed_trades": 100,
            "remaining_closed_trades_to_edge_proof_goal": 94,
            "edge_closed_trade_count": 6,
            "edge_regime_dependency_state": "single_regime_observed",
            "edge_true_edge_ratio": 0.82,
            "edge_decay_rate": -0.03,
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
        },
        "next_steps": ["step-a"],
    }
    report_path = tmp_path / "snapshot.md"

    snapshot_script._write_report(report_path, payload)

    report = report_path.read_text(encoding="utf-8")
    assert "- dashboard: approve=approval usable | align=aligned | act=continue_candidate_review_under_portfolio_caps | priority=monitor | execution_mode=live | top_action=continue_candidate_review_under_portfolio_caps | top_action_cmd=./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review" in report
    assert "- validation: approve=validation no_go | align=playbook_drift | act=review_runtime_execution_drag_before_expansion | priority=urgent | approval_topline_status=WARN" in report
    assert "- checklist: approve=validation/checklist no_go | align=aligned | act=clear_blocking_operational_items_before_rollout | priority=urgent | overall_status=WARN" in report
    assert "- top_action_followup_command: ./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review" in report
    assert "- live_validation: state=watch_edge | entry_timing=early_limit | execution_style=passive_limit | validation=sample_building/do_not_claim_edge_yet | closed=6/100 | remaining_to_goal=94 | regime=single_regime_observed | true_edge=0.8200 | decay=-0.0300" in report
    assert "- edge_evolution: state=reduce_candidate | action=reduce_baseline_allocation_review | bias=reduce_baseline | promotion=entry_timing/early_limit" in report
    assert "- review_followup_ledger: status=READY | action=reduce_baseline_allocation_review | entries=3 | cmd=./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review" in report
    assert "- entry_timing_review_target: action=run_entry_timing_split_review | target=ETHUSDC | variant=early_limit | status=CONTEXT_REVIEW_SETUP | family=sweep_reversal | focus=accepted_candidate_focus | cmd=./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action run_entry_timing_split_review" in report
    assert "- execution_style_review_target: action=run_execution_style_split_review | target=ETHUSDC | variant=passive_limit | status=CONTEXT_REVIEW_SETUP | family=sweep_reversal | focus=accepted_candidate_focus | cmd=./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action run_execution_style_split_review" in report
    assert "- representative_accepted_candidate: ETHUSDC | family=sweep_reversal | edge=watch_edge | split=early_limit/passive_limit | status=CONTEXT_REVIEW_SETUP" in report
    assert "- representative_blocked_candidate: BTCUSDC | family=trend_continuation | edge=fragile_edge | split=reaction_confirmed/market | status=BLOCKED_SETUP | reason=portfolio_cap" in report


def test_main_uses_cached_fast_surfaces_for_session_brief(monkeypatch, capsys) -> None:
    calls: list[tuple[str, str, dict]] = []

    class _Response:
        def __init__(self, payload=None, *, text: str = "", status_code: int = 200):  # noqa: ANN001
            self._payload = payload or {}
            self.text = text
            self.status_code = status_code

        def json(self):  # noqa: ANN201
            return self._payload

    dashboard = {
        "execution_mode": "MICRO_LIVE",
        "new_entries_allowed": False,
        "deployment_go_no_go": "GO",
        "playbook_action": "continue_runtime_monitoring",
        "approval_strip_summary": {
            "approve_value": "approval usable",
            "align_value": "aligned",
            "act_value": "continue_runtime_monitoring",
            "act_priority_level": "monitor",
        },
        "signal_funnel": {
            "operator_action_priority": {
                "top_action": "continue_runtime_monitoring",
                "priority_level": "monitor",
                "next_actions": [],
            },
            "alpha_research_recommended_action": {},
            "alpha_research_top_shadow_experiment": {},
            "hard_block_summary": {},
            "rollout_block_summary": {},
            "score_to_outcome_funnel": {"money_funnel": {}},
            "outcome_attribution": {},
            "edge_experiment_review": {},
            "edge_evolution_rule": {},
            "review_followup_ledger": {},
            "outcome_control_trace": {},
            "rollout_recommendation": {},
            "family_bottlenecks": [],
            "regime_bottlenecks": [],
            "session_bottlenecks": [],
        },
        "portfolio_summary": {"accepted_candidates": [], "blocked_candidates": []},
        "recent_intents": [],
        "open_orders": [],
        "open_positions": [],
    }
    validation = {
        "deployment_go_no_go": "GO",
        "deployment_code": "cached",
        "deployment_message": "cached validation",
        "playbook_action": "continue_runtime_monitoring",
        "approval_topline_status": "GO",
        "validation_report": {
            "approval_strip_summary": {
                "approve_value": "approval usable",
                "align_value": "aligned",
                "act_value": "continue_runtime_monitoring",
                "act_priority_level": "monitor",
            }
        },
    }
    checklist = {
        "deployment_go_no_go": "GO",
        "deployment_code": "cached",
        "deployment_message": "cached checklist",
        "playbook_action": "continue_runtime_monitoring",
        "overall_status": "GO",
        "blocking_failures": 0,
        "manual_actions": 0,
        "warnings": 0,
        "approval_strip_summary": {
            "approve_value": "approval usable",
            "align_value": "aligned",
            "act_value": "continue_runtime_monitoring",
            "act_priority_level": "monitor",
        },
    }

    class _Client:
        def __init__(self, app):  # noqa: ANN001
            self.app = app

        def __enter__(self):  # noqa: ANN201
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

        def get(self, path, params=None):  # noqa: ANN001, ANN201
            calls.append(("GET", path, dict(params or {})))
            if path == "/execution/operator-dashboard":
                return _Response(dashboard)
            if path == "/execution/operator-ui":
                return _Response(text="\n".join(snapshot_script.EXPECTED_OPERATOR_UI_SECTIONS))
            raise AssertionError(f"unexpected GET {path}")

        def post(self, path, params=None):  # noqa: ANN001, ANN201
            calls.append(("POST", path, dict(params or {})))
            if path == "/validation/report":
                return _Response(validation)
            if path == "/operations/checklist":
                return _Response(checklist)
            raise AssertionError(f"unexpected POST {path}")

    monkeypatch.setattr(snapshot_script, "TestClient", _Client)
    monkeypatch.setattr(
        snapshot_script,
        "parse_args",
        lambda: SimpleNamespace(
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            portfolio_limit=5,
            intent_limit=5,
            reconcile_limit=5,
            full_dashboard=False,
            report_dir="reports/operations/operator_surface_divergence",
            no_write_report=True,
        ),
    )

    assert snapshot_script.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["symbol"] == "BTCUSDC"

    dashboard_call = next(params for method, path, params in calls if method == "GET" and path == "/execution/operator-dashboard")
    validation_call = next(params for method, path, params in calls if method == "POST" and path == "/validation/report")
    checklist_call = next(params for method, path, params in calls if method == "POST" and path == "/operations/checklist")
    assert dashboard_call["fast"] is True
    assert validation_call == {"symbol": "BTCUSDC", "refresh": "false", "cache_fallback": "true"}
    assert checklist_call == {
        "symbol": "BTCUSDC",
        "universe": "usdc_perp_top30",
        "limit": 5,
        "days": 7,
        "write_report": "false",
    }
