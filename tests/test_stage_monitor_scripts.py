from __future__ import annotations

import importlib.util
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError


ROOT_DIR = Path("/Users/yumin/Documents/trading")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ops_stage_board = _load_module(
    "ops_stage_board_test_module",
    ROOT_DIR / "scripts/ops_stage_board.py",
)
notify_stage_change = _load_module(
    "notify_stage_change_test_module",
    ROOT_DIR / "scripts/notify_stage_change.py",
)


def _validation_report(
    *,
    playbook_go_no_go: str = "NO_GO",
    eligible_closed_trades: int = 2,
    trial_runs_written: int = 0,
    selected_trial_run_id=None,
    threshold_lineage_winner_run_id=None,
    threshold_lineage_winner_source: str = "",
    threshold_lineage_winner_type: str = "",
    threshold_lineage_audit_status: str = "",
    execution_degradation: str = "manual_review",
    top_operator_action: str = "continue_candidate_review_under_portfolio_caps",
    alpha_research_next_step: str = "run_shadow_cost_stress_review",
    approval_template_focus=None,
):
    payload = {
        "deployment_approval_summary": {
            "playbook_go_no_go": playbook_go_no_go,
            "deployment_go_no_go": None,
            "topline_code": "true_threshold_winner_with_replay_fail_worst_scenario",
            "threshold_lineage_winner_run_id": threshold_lineage_winner_run_id,
            "threshold_lineage_winner_source": threshold_lineage_winner_source,
            "threshold_lineage_winner_type": threshold_lineage_winner_type,
            "threshold_lineage_audit_status": threshold_lineage_audit_status,
            "replay_derived_worst_scenario": "latency_plus_1_bar",
            "replay_derived_worst_scenario_status": "FAIL",
            "replay_derived_worst_scenario_reason": "catastrophic_drawdown:replay_output",
        },
        "approval_strip_summary": {
            "approve_value": "validation no_go" if playbook_go_no_go == "NO_GO" else "approval usable",
            "align_value": "aligned",
            "act_value": "review_runtime_execution_drag_before_expansion",
        },
        "strategy_v2_pbo_dsr_trial_writer_summary": {
            "selected_trial_run_id": selected_trial_run_id,
            "sample_counts": {
                "eligible_closed_trades": eligible_closed_trades,
                "trial_runs_written": trial_runs_written,
            },
        },
        "execution_degradation_advisory_summary": {
            "status": execution_degradation,
        },
        "execution_friction_measurement_summary": {
            "friction_state": "degraded_friction",
            "reconciliation_state": "degraded_reconciliation",
        },
        "kill_condition_automation_summary": {
            "kill_condition_state": "kill_switch_review",
        },
        "operator_action_priority_summary": {
            "top_action": top_operator_action,
            "top_action_followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action reduce_baseline_allocation_review",
            "experiment_context": {
                "entry_timing_preferred_variant": "early_limit",
                "execution_style_preferred_variant": "passive_limit",
                "entry_timing_target": {
                    "symbol": "BTCUSDC",
                    "status": "ACTIONABLE_ENTRY",
                    "strategy_family": "sweep_reversal",
                    "focus_source": "accepted_candidate_focus",
                },
                "execution_style_target": {
                    "symbol": "BTCUSDC",
                    "status": "ACTIONABLE_ENTRY",
                    "strategy_family": "sweep_reversal",
                    "focus_source": "accepted_candidate_focus",
                },
            },
        },
        "alpha_research_pipeline_summary": {
            "recommended_action": alpha_research_next_step,
        },
        "edge_experiment_review_summary": {
            "edge_state": "watch_edge",
            "summary": "Run controlled split tests before widening scope.",
            "true_edge_ratio": 0.88,
            "edge_decay_rate": -0.04,
            "entry_timing_preferred_variant": "early_limit",
            "execution_style_preferred_variant": "passive_limit",
            "edge_proof_goal_closed_trades": 100,
            "remaining_closed_trades_to_edge_proof_goal": 92,
            "edge_proof_posture": {
                "state": "sample_building",
                "claim_state": "do_not_claim_edge_yet",
            },
            "daily_edge_kpis": {
                "closed_trade_count": 8,
                "sample_maturity_state": "review_ready",
                "true_edge_ratio": 0.88,
                "edge_decay_rate": -0.04,
                "regime_dependency_state": "single_regime_observed",
            },
        },
        "edge_evolution_rule_summary": {
            "evolution_state": "reduce_candidate",
            "recommended_action": "reduce_baseline_allocation_review",
            "allocation_bias": "reduce_baseline",
            "promotion_candidate_axis": "entry_timing",
            "promotion_candidate_variant": "early_limit",
        },
        "review_followup_ledger_summary": {
            "available": True,
            "last_status": "READY",
            "last_action": "reduce_baseline_allocation_review",
            "recent_entry_count": 3,
            "last_followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action reduce_baseline_allocation_review",
        },
    }
    if approval_template_focus is not None:
        payload["approval_template_focus"] = approval_template_focus
    return payload


def _checklist(*, overall_status: str = "FAIL"):
    return {
        "overall_status": overall_status,
        "approval_strip_summary": {
            "approve_value": "validation/checklist no_go" if overall_status == "FAIL" else "approval usable",
            "align_value": "aligned",
            "act_value": "clear_blocking_operational_items_before_rollout",
        },
        "checks": [
            {
                "item_id": "portfolio_headroom",
                "status": "WARN",
                "summary": "portfolio headroom is constrained",
            }
        ],
    }


def _dashboard(*, new_entries_allowed: bool = False, close_only_active: bool = True):
    return {
        "new_entries_allowed": new_entries_allowed,
        "active_locks": (
            [{"reason_code": "close_only_active"}] if close_only_active else []
        ),
        "approval_strip_summary": {
            "approve_value": "entry gate blocked" if not new_entries_allowed else "approval usable",
            "align_value": "aligned",
            "act_value": "continue_candidate_review_under_portfolio_caps",
        },
        "signal_funnel": {
            "edge_evolution_rule": {
                "evolution_state": "reduce_candidate",
                "recommended_action": "reduce_baseline_allocation_review",
                "allocation_bias": "reduce_baseline",
                "promotion_candidate_axis": "entry_timing",
                "promotion_candidate_variant": "early_limit",
            }
        },
        "portfolio_summary": {
            "accepted_candidates": [
                {
                    "symbol": "BTCUSDC",
                    "strategy_family": "sweep_reversal",
                    "edge_experiment_focus": {
                        "edge_state": "watch_edge",
                        "entry_timing_preferred_variant": "early_limit",
                        "execution_style_preferred_variant": "passive_limit",
                    },
                }
            ],
            "blocked_candidates": [
                {
                    "symbol": "ETHUSDC",
                    "strategy_family": "trend_continuation",
                    "block_reason": "portfolio_cap",
                    "edge_experiment_focus": {
                        "edge_state": "fragile_edge",
                        "entry_timing_preferred_variant": "reaction_confirmed",
                        "execution_style_preferred_variant": "market",
                    },
                }
            ],
        },
    }


def test_stage_payload_reports_blocked_state(monkeypatch):
    monkeypatch.setattr(ops_stage_board, "_open_lineage_samples", lambda families, limit=3: {
        "open_sample_count": 0,
        "sample_limit": limit,
        "samples": [],
        "symbols": [],
        "summary": "open lineage samples: 0",
    })
    payload = ops_stage_board._build_stage_payload(
        _validation_report(),
        _checklist(),
        _dashboard(),
    )

    assert payload["generated_at"]
    assert payload["stage"] == "0_BLOCKED"
    assert payload["close_only_active"] is True
    assert payload["playbook_go_no_go"] == "NO_GO"
    assert payload["eligible_closed_trades"] == 2
    assert payload["trial_runs_written"] == 0
    assert payload["selected_trial_run_id"] is None
    assert payload["execution_degradation"] == "manual_review"
    assert payload["top_operator_action_followup_command"].endswith(
        "--symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action reduce_baseline_allocation_review"
    )
    assert payload["dashboard_approval_strip"]["approve_value"] == "entry gate blocked"
    assert payload["validation_approval_strip"]["act_value"] == "review_runtime_execution_drag_before_expansion"
    assert payload["checklist_approval_strip"]["act_value"] == "clear_blocking_operational_items_before_rollout"
    assert payload["edge_experiment_review"]["edge_state"] == "watch_edge"
    assert payload["edge_experiment_review"]["entry_timing_preferred_variant"] == "early_limit"
    assert payload["edge_evolution_rule"]["evolution_state"] == "reduce_candidate"
    assert payload["edge_evolution_rule"]["recommended_action"] == "reduce_baseline_allocation_review"
    assert payload["review_followup_ledger"]["last_status"] == "READY"
    assert payload["review_followup_ledger"]["last_action"] == "reduce_baseline_allocation_review"
    assert payload["risk_gate_summary"]["status"] == "NOT_AVAILABLE"
    assert payload["risk_gate_unlock_summary"]["active"] is False
    assert payload["lineage_sample_summary"]["scope"] == "symbol_edge_proof"
    assert payload["lineage_sample_summary"]["closed_trade_count"] == 8
    assert payload["lineage_sample_summary"]["remaining_closed_trades_to_goal"] == 92
    assert payload["lineage_closed_fill_health"]["status"] == "closed_fills_present"
    assert payload["lineage_closed_fill_health"]["healthy"] is True
    assert payload["lineage_closed_fill_health"]["closed_trade_count"] == 8
    assert payload["open_lineage_sample_summary"]["open_sample_count"] == 0
    assert payload["entry_timing_review_target"]["symbol"] == "BTCUSDC"
    assert payload["entry_timing_review_target"]["action"] == "run_entry_timing_split_review"
    assert payload["entry_timing_review_target"]["followup_command"].endswith(
        "--symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_entry_timing_split_review"
    )
    assert payload["execution_style_review_target"]["symbol"] == "BTCUSDC"
    assert payload["execution_style_review_target"]["followup_command"].endswith(
        "--symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_execution_style_split_review"
    )
    assert payload["representative_candidates"]["accepted"]["symbol"] == "BTCUSDC"
    assert payload["representative_candidates"]["blocked"]["symbol"] == "ETHUSDC"
    assert payload["lineage_gate_ready"] is False
    assert payload["candidate_gate_ready"] is True
    assert payload["edge_sample_gate_ready"] is False
    assert payload["all_readiness_gates_ready"] is False


def test_stage_payload_reports_lineage_ready_when_trial_exists():
    payload = ops_stage_board._build_stage_payload(
        _validation_report(
            playbook_go_no_go="GO",
            eligible_closed_trades=8,
            trial_runs_written=2,
            selected_trial_run_id="trial_run_001",
            execution_degradation="watch",
        ),
        _checklist(overall_status="PASS"),
        _dashboard(new_entries_allowed=True, close_only_active=False),
    )

    assert payload["stage"] == "2_LINEAGE_READY"
    assert payload["close_only_active"] is False
    assert payload["trial_runs_written"] == 2
    assert payload["selected_trial_run_id"] == "trial_run_001"
    assert payload["execution_degradation"] == "watch"
    assert payload["dashboard_approval_strip"]["approve_value"] == "approval usable"
    assert payload["validation_approval_strip"]["approve_value"] == "approval usable"
    assert payload["checklist_approval_strip"]["approve_value"] == "approval usable"
    assert payload["edge_experiment_review"]["execution_style_preferred_variant"] == "passive_limit"
    assert payload["edge_evolution_rule"]["allocation_bias"] == "reduce_baseline"
    assert payload["lineage_gate_ready"] is True
    assert payload["candidate_gate_ready"] is True
    assert payload["edge_sample_gate_ready"] is False
    assert payload["all_readiness_gates_ready"] is False


def test_stage_payload_uses_deployment_threshold_winner_for_lineage_readiness():
    payload = ops_stage_board._build_stage_payload(
        _validation_report(
            playbook_go_no_go="MANUAL_REVIEW",
            eligible_closed_trades=2,
            trial_runs_written=0,
            selected_trial_run_id=None,
            threshold_lineage_winner_run_id="global_true_threshold_001",
            threshold_lineage_winner_source="true_threshold_sweep_runner_v1",
            threshold_lineage_winner_type="true_threshold",
            threshold_lineage_audit_status="PASS",
            execution_degradation="watch",
        ),
        _checklist(overall_status="PASS"),
        _dashboard(new_entries_allowed=True, close_only_active=False),
    )

    assert payload["selected_trial_run_id"] == "global_true_threshold_001"
    assert payload["selected_trial_resolution_source"] == "deployment_threshold_lineage_winner"
    assert payload["raw_trial_writer_selected_trial_run_id"] is None
    assert payload["threshold_lineage_winner_run_id"] == "global_true_threshold_001"
    assert payload["threshold_lineage_winner_type"] == "true_threshold"
    assert payload["threshold_lineage_audit_status"] == "PASS"
    assert payload["lineage_gate_ready"] is True
    assert payload["stage"] == "2_LINEAGE_READY"


def test_stage_payload_predicts_post_unlock_stage_when_risk_gate_is_only_blocker(monkeypatch):
    monkeypatch.setattr(
        ops_stage_board,
        "_risk_gate_summary",
        lambda checklist: {
            "status": "FAIL",
            "blocking": True,
            "summary": "risk gate is CLOSED (daily_loss_limit_reached)",
            "risk_state": "CLOSED",
            "risk_reason": "daily_loss_limit_reached",
            "unlock_at": "2026-04-09T00:00:00+00:00",
            "daily_realized_r": -20.0,
            "daily_trades": 22,
            "daily_loss_streak": 21,
            "daily_loss_limit_r": -2.0,
        },
    )
    checklist = _checklist(overall_status="FAIL")
    checklist["blocking_failures"] = 1
    checklist["warnings"] = 20
    checklist["manual_actions"] = 0

    payload = ops_stage_board._build_stage_payload(
        _validation_report(
            playbook_go_no_go="MANUAL_REVIEW",
            eligible_closed_trades=2,
            trial_runs_written=0,
            selected_trial_run_id=None,
            threshold_lineage_winner_run_id="global_true_threshold_001",
            threshold_lineage_winner_source="true_threshold_sweep_runner_v1",
            threshold_lineage_winner_type="true_threshold",
            threshold_lineage_audit_status="PASS",
            execution_degradation="watch",
        ),
        checklist,
        _dashboard(new_entries_allowed=True, close_only_active=False),
        lineage_sample_scope="family_global",
        lineage_families="sweep_reversal,trend_continuation",
        lineage_proof_goal_closed_trades=100,
        lineage_sample_days=180,
    )

    assert payload["risk_gate_unlock_summary"]["active"] is True
    assert payload["risk_gate_unlock_summary"]["status"] == "scheduled_unlock"
    assert payload["risk_gate_unlock_summary"]["expected_checklist_status_after_unlock"] == "WARN"
    assert payload["risk_gate_unlock_summary"]["expected_stage_after_unlock"] == "2_LINEAGE_READY"
    assert payload["post_unlock_review_summary"]["active"] is True
    assert payload["post_unlock_review_summary"]["review_window_open"] is False
    assert payload["post_unlock_review_summary"]["current_stage"] == "0_BLOCKED"
    assert payload["post_unlock_review_summary"]["expected_stage_after_unlock"] == "2_LINEAGE_READY"
    assert payload["post_unlock_review_summary"]["next_review_step"] == "wait_for_operating_lock_to_clear"
    assert payload["post_unlock_review_summary"]["bundle_review_command"].endswith(
        "scripts/run_post_unlock_review.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30"
    )
    assert payload["post_unlock_bundle_result"]["status"] == "waiting_for_review_window"
    assert payload["runtime_reopen_status"]["status"] == "waiting_for_operating_lock"
    assert payload["runtime_reopen_status"]["ready"] is False
    assert payload["post_unlock_review_summary"]["primary_review_command"].endswith(
        "scripts/run_micro_live_preflight.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30"
    )
    assert payload["post_unlock_review_summary"]["secondary_review_command"].endswith(
        "scripts/run_post_live_pruning_review.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30"
    )


def test_stage_payload_uses_active_lineage_sample_for_candidate_gate(monkeypatch):
    monkeypatch.setattr(
        ops_stage_board,
        "_open_lineage_samples",
        lambda families, limit=3: {
            "open_sample_count": 1,
            "sample_limit": limit,
            "samples": [
                {
                    "symbol": "ARBUSDC",
                    "strategy_family": "sweep_reversal",
                    "status": "OPEN_PAPER_SAMPLE",
                    "plan_id": "plan_zone_c15debc65a13_confirm",
                    "hours_open": 7.25,
                    "last_fill_stage": "ENTRY",
                }
            ],
            "symbols": ["ARBUSDC"],
            "summary": "open lineage samples=1 | top=ARBUSDC:ENTRY",
        },
    )

    dashboard = _dashboard(new_entries_allowed=True, close_only_active=False)
    dashboard["portfolio_summary"] = {
        **dict(dashboard.get("portfolio_summary") or {}),
        "accepted_candidates": [],
        "blocked_candidates": [],
    }

    payload = ops_stage_board._build_stage_payload(
        _validation_report(playbook_go_no_go="GO", eligible_closed_trades=1, trial_runs_written=0, selected_trial_run_id=None),
        _checklist(overall_status="PASS"),
        dashboard,
        lineage_sample_scope="family_global",
        lineage_families="sweep_reversal,trend_continuation",
        lineage_proof_goal_closed_trades=100,
        lineage_sample_days=180,
    )

    assert payload["active_lineage_sample_focus"]["symbol"] == "ARBUSDC"
    assert payload["open_lineage_sample_summary"]["open_sample_count"] == 1
    assert payload["candidate_gate_ready"] is True
    assert payload["active_lineage_sample_health"]["active"] is True
    assert payload["active_lineage_sample_health"]["status"] == "stalled"
    assert payload["active_lineage_sample_health"]["last_fill_stage"] == "ENTRY"


def test_stage_payload_can_use_family_global_lineage_sample(monkeypatch):
    monkeypatch.setattr(
        ops_stage_board,
        "_lineage_sample_summary",
        lambda **kwargs: {
            "scope": "family_global",
            "families": ["sweep_reversal"],
            "proof_goal_closed_trades": 100,
            "closed_trade_count": 104,
            "remaining_closed_trades_to_goal": 0,
            "goal_ready": True,
            "latest_closed_trade_at": "2026-03-27T00:00:00+00:00",
            "sample_days": 180,
            "summary": "scope=family_global | families=sweep_reversal | closes=104/100 | remaining=0 | lookback_days=180",
        },
    )

    payload = ops_stage_board._build_stage_payload(
        _validation_report(playbook_go_no_go="GO", eligible_closed_trades=8, trial_runs_written=2, selected_trial_run_id="trial_run_001", execution_degradation="watch"),
        _checklist(overall_status="PASS"),
        _dashboard(new_entries_allowed=True, close_only_active=False),
        lineage_sample_scope="family_global",
        lineage_families="sweep_reversal",
        lineage_proof_goal_closed_trades=100,
        lineage_sample_days=180,
    )

    assert payload["lineage_sample_summary"]["scope"] == "family_global"
    assert payload["lineage_sample_summary"]["closed_trade_count"] == 104
    assert payload["lineage_closed_fill_health"]["status"] == "closed_fills_present"
    assert payload["edge_sample_gate_ready"] is True
    assert payload["all_readiness_gates_ready"] is True


def test_runtime_signoff_summary_collects_required_reviews():
    summary = ops_stage_board._runtime_signoff_summary(
        validation_report=_validation_report(
            playbook_go_no_go="MANUAL_REVIEW",
            approval_template_focus={
                "replay_max_drawdown_r": 10.1003,
                "replay_p5_r": -1.05,
                "downside_profile": {
                    "stop_loss_share": 0.5341,
                    "worst_loss_streak": 9,
                },
                "post_patch_sample_summary": {
                    "closed_trade_count": 50,
                    "ready_for_replay_refresh": True,
                    "replay_max_drawdown_r": 4.3114,
                    "replay_p5_r": -1.05,
                    "stop_loss_share": 0.3,
                    "worst_loss_streak": 4,
                },
            },
        ),
        checklist=_checklist(overall_status="WARN"),
        runtime_reopen_status={"status": "ready_to_reopen_runtime", "ready": True},
    )

    codes = [item["code"] for item in summary["required_reviews"]]
    advisory_codes = [item["code"] for item in summary["advisory_reviews"]]
    assert summary["status"] == "manual_signoff_required"
    assert "approval_template_review" in codes
    assert "execution_reconciliation_review" in codes
    assert "kill_switch_review" in codes
    assert "portfolio_headroom_review" in advisory_codes
    assert "approval_template_review=>" in summary["required_clearance_line"]
    assert "execution_reconciliation_review=>" in summary["required_clearance_line"]
    assert "kill_switch_review=>" in summary["required_clearance_line"]
    assert summary["operator_recommendation"] == "conditional_micro_live_signoff"
    assert summary["runtime_decision"]["band"] == "AMBER_CONDITIONAL"
    assert summary["runtime_reopen_gate_summary"]["micro_live"]["status"] == "ready"
    assert summary["runtime_reopen_gate_summary"]["full_live"]["status"] == "not_ready"
    approval_review = next(item for item in summary["required_reviews"] if item["code"] == "approval_template_review")
    assert approval_review["worst_scenario"] == "latency_plus_1_bar"
    assert approval_review["worst_scenario_status"] == "FAIL"
    assert approval_review["worst_scenario_reason"] == "catastrophic_drawdown:replay_output"


def test_runtime_signoff_summary_line_includes_decision_band():
    line = ops_stage_board._runtime_signoff_summary_line(
        {
            "status": "manual_signoff_required",
            "required_reviews": [
                {
                    "code": "approval_template_review",
                    "worst_scenario": "latency_plus_1_bar",
                    "worst_scenario_status": "FAIL",
                }
            ],
            "advisory_count": 0,
            "operator_recommendation": "hold_runtime_reopen",
            "required_clearance_line": "approval_template_review=>clear me",
            "runtime_decision": {"band": "RED_HOLD"},
        }
    )

    assert "band=RED_HOLD" in line


def test_runtime_reopen_gate_summary_line_surfaces_micro_and_full_status():
    line = ops_stage_board._runtime_reopen_gate_summary_line(
        {
            "active_scope": "MICRO_LIVE_ONLY",
            "effective_action": "conditional_micro_live_signoff",
            "micro_live": {
                "status": "ready",
                "closed_trade_count": 50,
                "min_closed_trades": 50,
            },
            "full_live": {
                "status": "not_ready",
                "closed_trade_count": 50,
                "min_closed_trades": 80,
            },
        }
    )

    assert "micro=ready(50/50)" in line
    assert "full=not_ready(50/80)" in line
    assert "scope=MICRO_LIVE_ONLY" in line


def test_request_json_retries_validation_report_with_refresh_true_on_cache_miss(monkeypatch):
    calls: list[str] = []

    class _Response:
        def __init__(self, payload: dict[str, object]):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

    def _urlopen(request, timeout):  # noqa: ANN001
        calls.append(request.full_url)
        if "refresh=False" in request.full_url:
            raise HTTPError(
                request.full_url,
                404,
                "Not Found",
                hdrs=None,
                fp=io.BytesIO(b'{"detail":"cached validation payload is not available yet; call with refresh=true first"}'),
            )
        return _Response({"validation_report": {"approval_strip_summary": {"approve_value": "approval usable"}}})

    monkeypatch.setattr(ops_stage_board, "urlopen", _urlopen)

    payload = ops_stage_board._request_json(
        "http://127.0.0.1:8000",
        "POST",
        "/validation/report",
        query={"symbol": "BTCUSDC", "refresh": False},
    )

    assert payload["validation_report"]["approval_strip_summary"]["approve_value"] == "approval usable"
    assert any("refresh=False" in url for url in calls)
    assert any("refresh=True" in url for url in calls)


def test_runtime_preflight_summary_line_surfaces_first_failed_check():
    line = ops_stage_board._runtime_preflight_summary_line(
        {
            "status": "NOT_READY",
            "effective_action": "conditional_micro_live_signoff",
            "summary": "1 blocking preflight check(s) remain.",
            "failed_checks": [
                {
                    "name": "reconciliation",
                    "message": "healthy=False severity=ERROR",
                }
            ],
        }
    )

    assert "status=NOT_READY" in line
    assert "action=conditional_micro_live_signoff" in line
    assert "first_failed=reconciliation/healthy=False severity=ERROR" in line


def test_runtime_operator_signoff_summary_line_surfaces_manual_micro_live_ready():
    line = ops_stage_board._runtime_operator_signoff_summary_line(
        {
            "status": "ready_for_manual_micro_live_signoff",
            "effective_action": "conditional_micro_live_signoff",
            "allowed_scope": "MICRO_LIVE_ONLY",
            "preflight_status": "READY_FOR_MICRO_LIVE",
            "required_review_codes": ["approval_template_review"],
            "next_step": "review_required_warning_and_record_micro_live_signoff",
        }
    )

    assert "status=ready_for_manual_micro_live_signoff" in line
    assert "action=conditional_micro_live_signoff" in line
    assert "scope=MICRO_LIVE_ONLY" in line
    assert "preflight=READY_FOR_MICRO_LIVE" in line
    assert "required=approval_template_review" in line
    assert "next=review_required_warning_and_record_micro_live_signoff" in line


def test_apply_runtime_stage_override_promotes_conditional_micro_live_to_approval_review():
    payload = ops_stage_board._apply_runtime_stage_override(
        {
            "stage": "0_BLOCKED",
            "stage_reason": "checklist_fail + manual_review",
            "next_step_hint": "continue_candidate_review_under_portfolio_caps",
            "sample_progress_hint": "selected lineage winner is resolved",
            "runtime_signoff_summary": {
                "runtime_decision": {
                    "band": "AMBER_CONDITIONAL",
                    "effective_action": "conditional_micro_live_signoff",
                    "allowed_reopen_scope": "MICRO_LIVE_ONLY",
                }
            },
            "runtime_reopen_gate_summary": {
                "micro_live": {"status": "ready", "closed_trade_count": 50, "min_closed_trades": 50},
                "full_live": {"status": "not_ready", "closed_trade_count": 50, "min_closed_trades": 80},
            },
        }
    )

    assert payload["stage"] == "3_APPROVAL_REVIEW"
    assert payload["stage_reason"] == "post-patch cohort cleared the conditional MICRO_LIVE thresholds"
    assert payload["next_step_hint"] == "review manual sign-off and, if accepted, reopen MICRO_LIVE only"
    assert payload["sample_progress_hint"] == "MICRO_LIVE=ready (50/50), FULL_LIVE=not_ready (50/80)"


def test_runtime_mitigation_summary_line_surfaces_primary_and_next_focus():
    line = ops_stage_board._runtime_mitigation_summary_line(
        {
            "primary_focus_label": "confirm 진입 타이밍 축소",
            "primary_action_status": "candidate_review_pending",
            "secondary_focus_label": "non-confirm fail-fast",
            "secondary_status": "deferred_by_experiment_sequence",
            "primary_action_command": "cmd-entry",
        }
    )

    assert "primary=confirm 진입 타이밍 축소/candidate_review_pending" in line
    assert "next=non-confirm fail-fast/deferred_by_experiment_sequence" in line
    assert "cmd=cmd-entry" in line


def test_runtime_mitigation_wait_summary_line_surfaces_wait_reason():
    line = ops_stage_board._runtime_mitigation_wait_summary_line(
        {
            "focus_label": "confirm 진입 타이밍 축소",
            "status": "no_lineage_candidate_visible",
            "current_session": "inactive",
            "allowed_sessions": ["london", "new_york"],
            "next_trigger": "actionable_entry_timing_target_appears",
            "wait_constraint": "waiting_for_actionable_entry_timing_target",
            "watch_tick_status": "no_eligible_candidate",
        }
    )

    assert "focus=confirm 진입 타이밍 축소" in line
    assert "status=no_lineage_candidate_visible" in line
    assert "session=inactive" in line
    assert "allowed=london,new_york" in line
    assert "next=actionable_entry_timing_target_appears" in line
    assert "constraint=waiting_for_actionable_entry_timing_target" in line
    assert "watcher=no_eligible_candidate" in line


def test_lineage_sample_summary_uses_closed_fill_metrics_for_family_global(monkeypatch):
    expected_ts = "2026-04-08T07:29:00+00:00"
    monkeypatch.setattr(
        ops_stage_board,
        "_family_closed_fill_metrics",
        lambda **kwargs: (130, ops_stage_board.datetime.fromisoformat(expected_ts)),
    )

    payload = ops_stage_board._lineage_sample_summary(
        scope="family_global",
        symbol="BTCUSDC",
        edge_experiment_review={},
        families=["sweep_reversal", "trend_continuation"],
        proof_goal_closed_trades=100,
        sample_days=180,
    )

    assert payload["scope"] == "family_global"
    assert payload["closed_trade_count"] == 130
    assert payload["remaining_closed_trades_to_goal"] == 0
    assert payload["goal_ready"] is True
    assert payload["latest_closed_trade_at"] == expected_ts


def test_collect_events_emits_transition_events():
    previous = {
        "stage": "1_SAMPLE_COLLECTION",
        "close_only_active": False,
        "playbook_go_no_go": "MANUAL_REVIEW",
        "lineage_gate_ready": False,
        "candidate_gate_ready": False,
        "edge_sample_gate_ready": False,
        "all_readiness_gates_ready": False,
        "dashboard_approval_strip": {
            "approve_value": "manual review first",
            "align_value": "aligned",
            "act_value": "review_runtime_gate_before_reopen",
        },
        "validation_approval_strip": {
            "approve_value": "manual review first",
            "align_value": "aligned",
            "act_value": "review_runtime_execution_drag_before_expansion",
        },
        "checklist_approval_strip": {
            "approve_value": "manual review first",
            "align_value": "aligned",
            "act_value": "clear_open_operational_items_before_rollout",
        },
        "trial_runs_written": 0,
        "selected_trial_run_id": None,
        "execution_degradation": "watch",
        "edge_experiment_review": {
            "edge_state": "watch_edge",
            "entry_timing_preferred_variant": "reaction_confirmed",
            "execution_style_preferred_variant": "market",
            "true_edge_ratio": 0.74,
            "edge_decay_rate": -0.08,
            "edge_proof_goal_closed_trades": 100,
            "remaining_closed_trades_to_edge_proof_goal": 96,
            "edge_proof_posture": {
                "state": "sample_building",
                "claim_state": "do_not_claim_edge_yet",
            },
            "daily_edge_kpis": {
                "closed_trade_count": 4,
                "true_edge_ratio": 0.74,
                "edge_decay_rate": -0.08,
                "regime_dependency_state": "single_regime_observed",
            },
        },
        "edge_evolution_rule": {
            "evolution_state": "hold_baseline",
            "recommended_action": "keep_current_baseline",
            "allocation_bias": "hold_current_baseline",
            "promotion_candidate_axis": "none",
            "promotion_candidate_variant": "none",
        },
        "review_followup_ledger": {
            "last_status": "NO_TARGET",
            "last_action": "reduce_baseline_allocation_review",
            "recent_entry_count": 2,
            "last_followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 30 --action reduce_baseline_allocation_review",
        },
        "entry_timing_review_target": {
            "action": "run_entry_timing_split_review",
            "preferred_variant": "reaction_confirmed",
            "symbol": "ETHUSDC",
            "status": "BLOCKED_SETUP",
            "strategy_family": "trend_continuation",
            "block_reason": "portfolio_cap",
            "focus_source": "blocked_candidate_focus",
            "followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 30 --action run_entry_timing_split_review",
        },
        "execution_style_review_target": {
            "action": "run_execution_style_split_review",
            "preferred_variant": "market",
            "symbol": "ETHUSDC",
            "status": "BLOCKED_SETUP",
            "strategy_family": "trend_continuation",
            "block_reason": "portfolio_cap",
            "focus_source": "blocked_candidate_focus",
            "followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 30 --action run_execution_style_split_review",
        },
        "representative_candidates": {
            "accepted": {
                "symbol": "BTCUSDC",
                "strategy_family": "sweep_reversal",
                "edge_state": "watch_edge",
                "entry_timing_preferred_variant": "reaction_confirmed",
                "execution_style_preferred_variant": "market",
            },
            "blocked": {
                "symbol": "ETHUSDC",
                "strategy_family": "trend_continuation",
                "block_reason": "portfolio_cap",
                "edge_state": "watch_edge",
                "entry_timing_preferred_variant": "reaction_confirmed",
                "execution_style_preferred_variant": "market",
            },
        },
    }
    current = {
        "stage": "2_LINEAGE_READY",
        "close_only_active": True,
        "playbook_go_no_go": "GO",
        "lineage_gate_ready": True,
        "candidate_gate_ready": True,
        "edge_sample_gate_ready": False,
        "all_readiness_gates_ready": False,
        "dashboard_approval_strip": {
            "approve_value": "entry gate blocked",
            "align_value": "aligned",
            "act_value": "continue_candidate_review_under_portfolio_caps",
        },
        "validation_approval_strip": {
            "approve_value": "approval usable",
            "align_value": "aligned",
            "act_value": "review_runtime_execution_drag_before_expansion",
        },
        "checklist_approval_strip": {
            "approve_value": "approval usable",
            "align_value": "aligned",
            "act_value": "clear_blocking_operational_items_before_rollout",
        },
        "trial_runs_written": 1,
        "selected_trial_run_id": "trial_run_001",
        "execution_degradation": "manual_review",
        "edge_experiment_review": {
            "edge_state": "fragile_edge",
            "entry_timing_preferred_variant": "early_limit",
            "execution_style_preferred_variant": "passive_limit",
            "true_edge_ratio": 0.62,
            "edge_decay_rate": -0.12,
            "edge_proof_goal_closed_trades": 100,
            "remaining_closed_trades_to_edge_proof_goal": 91,
            "edge_proof_posture": {
                "state": "sample_building",
                "claim_state": "do_not_claim_edge_yet",
            },
            "daily_edge_kpis": {
                "closed_trade_count": 9,
                "true_edge_ratio": 0.62,
                "edge_decay_rate": -0.12,
                "regime_dependency_state": "regime_dependent",
            },
        },
        "edge_evolution_rule": {
            "evolution_state": "reduce_candidate",
            "recommended_action": "reduce_baseline_allocation_review",
            "allocation_bias": "reduce_baseline",
            "promotion_candidate_axis": "entry_timing",
            "promotion_candidate_variant": "early_limit",
        },
        "review_followup_ledger": {
            "last_status": "READY",
            "last_action": "reduce_baseline_allocation_review",
            "recent_entry_count": 3,
            "last_followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action reduce_baseline_allocation_review",
        },
        "lineage_sample_summary": {
            "scope": "family_global",
            "families": ["sweep_reversal"],
            "proof_goal_closed_trades": 100,
            "closed_trade_count": 12,
            "remaining_closed_trades_to_goal": 88,
        },
        "lineage_closed_fill_health": {
            "status": "closed_fills_present",
            "healthy": True,
            "closed_trade_count": 12,
            "latest_closed_trade_at": "2026-03-27T08:00:00+00:00",
            "summary": "lineage CLOSED fills observed: 12 | latest=2026-03-27T08:00:00+00:00",
        },
        "open_lineage_sample_summary": {
            "open_sample_count": 2,
            "sample_limit": 3,
            "samples": [
                {"symbol": "FILUSDC", "last_fill_stage": "ENTRY"},
                {"symbol": "ARBUSDC", "last_fill_stage": "PARTIAL_EXIT"},
            ],
        },
        "entry_timing_review_target": {
            "action": "run_entry_timing_split_review",
            "preferred_variant": "early_limit",
            "symbol": "BTCUSDC",
            "status": "ACTIONABLE_ENTRY",
            "strategy_family": "sweep_reversal",
            "focus_source": "accepted_candidate_focus",
            "followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_entry_timing_split_review",
        },
        "execution_style_review_target": {
            "action": "run_execution_style_split_review",
            "preferred_variant": "passive_limit",
            "symbol": "BTCUSDC",
            "status": "ACTIONABLE_ENTRY",
            "strategy_family": "sweep_reversal",
            "focus_source": "accepted_candidate_focus",
            "followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_execution_style_split_review",
        },
        "representative_candidates": {
            "accepted": {
                "symbol": "BTCUSDC",
                "strategy_family": "sweep_reversal",
                "edge_state": "watch_edge",
                "entry_timing_preferred_variant": "early_limit",
                "execution_style_preferred_variant": "passive_limit",
            },
            "blocked": {
                "symbol": "ETHUSDC",
                "strategy_family": "trend_continuation",
                "block_reason": "portfolio_cap",
                "edge_state": "fragile_edge",
                "entry_timing_preferred_variant": "early_limit",
                "execution_style_preferred_variant": "passive_limit",
            },
        },
    }

    events = notify_stage_change._collect_events(previous, current)
    event_types = {event["type"] for event in events}

    assert "stage_changed" in event_types
    assert "close_only_changed" in event_types
    assert "dashboard_surface_changed" in event_types
    assert "playbook_changed" in event_types
    assert "checklist_surface_changed" in event_types
    assert "edge_experiment_changed" in event_types
    assert "edge_evolution_changed" in event_types
    assert "review_followup_changed" in event_types
    assert "accepted_candidate_focus_changed" in event_types
    assert "blocked_candidate_focus_changed" in event_types
    assert "entry_timing_review_target_changed" in event_types
    assert "execution_style_review_target_changed" in event_types
    assert "trial_runs_started" in event_types
    assert "winner_selected" in event_types
    assert "lineage_gate_ready" in event_types
    assert "candidate_gate_ready" in event_types
    assert "execution_manual_review" in event_types


def test_collect_events_emits_all_readiness_gate_event():
    previous = {
        "lineage_gate_ready": True,
        "candidate_gate_ready": True,
        "edge_sample_gate_ready": False,
        "all_readiness_gates_ready": False,
    }
    current = {
        "lineage_gate_ready": True,
        "candidate_gate_ready": True,
        "edge_sample_gate_ready": True,
        "all_readiness_gates_ready": True,
    }

    events = notify_stage_change._collect_events(previous, current)
    event_types = {event["type"] for event in events}

    assert "edge_sample_gate_ready" in event_types
    assert "all_readiness_gates_ready" in event_types


def test_collect_events_emits_risk_gate_change_event():
    previous = {
        "risk_gate_summary": {
            "status": "FAIL",
            "risk_state": "CLOSED",
            "risk_reason": "daily_loss_limit_reached",
            "unlock_at": "2026-04-09T00:00:00+00:00",
            "daily_realized_r": -20.0,
            "daily_loss_limit_r": -2.0,
            "daily_loss_streak": 21,
        }
    }
    current = {
        "risk_gate_summary": {
            "status": "PASS",
            "risk_state": "OPEN",
            "risk_reason": "normal",
            "unlock_at": None,
            "daily_realized_r": 0.0,
            "daily_loss_limit_r": -2.0,
            "daily_loss_streak": 0,
        }
    }

    events = notify_stage_change._collect_events(previous, current)
    event_types = {event["type"] for event in events}

    assert "risk_gate_changed" in event_types


def test_collect_events_emits_risk_gate_cleared_event():
    previous = {
        "risk_gate_summary": {
            "status": "FAIL",
            "risk_state": "CLOSED",
            "risk_reason": "daily_loss_limit_reached",
            "unlock_at": "2026-04-09T00:00:00+00:00",
            "daily_realized_r": -20.0,
            "daily_loss_limit_r": -2.0,
            "daily_loss_streak": 21,
        }
    }
    current = {
        "risk_gate_summary": {
            "status": "PASS",
            "risk_state": "OPEN",
            "risk_reason": "normal",
            "unlock_at": None,
            "daily_realized_r": 0.0,
            "daily_loss_limit_r": -2.0,
            "daily_loss_streak": 0,
        }
    }

    events = notify_stage_change._collect_events(previous, current)
    event_types = {event["type"] for event in events}

    assert "risk_gate_changed" in event_types
    assert "risk_gate_cleared" in event_types


def test_collect_events_emits_post_unlock_review_ready_event():
    previous = {
        "post_unlock_review_summary": {
            "active": True,
            "review_window_open": False,
            "current_stage": "0_BLOCKED",
            "current_checklist_status": "FAIL",
            "current_validation_playbook_go_no_go": "MANUAL_REVIEW",
            "next_review_step": "wait_for_operating_lock_to_clear",
        }
    }
    current = {
        "post_unlock_review_summary": {
            "active": True,
            "review_window_open": True,
            "current_stage": "2_LINEAGE_READY",
            "current_checklist_status": "WARN",
            "current_validation_playbook_go_no_go": "MANUAL_REVIEW",
            "next_review_step": "review_validation_and_checklist_before_runtime_reopen",
        }
    }

    events = notify_stage_change._collect_events(previous, current)
    event_types = {event["type"] for event in events}

    assert "post_unlock_review_ready" in event_types


def test_collect_events_emits_post_unlock_bundle_and_runtime_ready_events():
    previous = {
        "post_unlock_bundle_result": {
            "active": True,
            "executed": False,
            "status": "waiting_for_review_window",
            "summary": "post-unlock bundle review is waiting for the review window to open",
            "micro_live_preflight_status": "",
            "post_live_pruning_review_decision": "",
        },
        "runtime_reopen_status": {
            "status": "waiting_for_review_window",
            "ready": False,
        },
    }
    current = {
        "post_unlock_bundle_result": {
            "active": True,
            "executed": True,
            "status": "READY_TO_REOPEN_RUNTIME",
            "summary": "Post-unlock review bundle is green.",
            "micro_live_preflight_status": "READY_FOR_MICRO_LIVE",
            "post_live_pruning_review_decision": "REOPEN_PRUNING_REVIEW",
        },
        "runtime_reopen_status": {
            "status": "ready_to_reopen_runtime",
            "ready": True,
        },
    }

    events = notify_stage_change._collect_events(previous, current)
    event_types = {event["type"] for event in events}

    assert "post_unlock_bundle_changed" in event_types
    assert "runtime_reopen_ready" in event_types
    assert "runtime_reopen_status_changed" in event_types


def test_collect_events_emits_runtime_operator_signoff_ready_event():
    previous = {
        "runtime_operator_signoff_summary": {
            "status": "waiting_for_preflight",
            "allowed_scope": "MICRO_LIVE_ONLY",
            "next_step": "clear_preflight_failures_before_manual_signoff",
        }
    }
    current = {
        "runtime_operator_signoff_summary": {
            "status": "ready_for_manual_micro_live_signoff",
            "effective_action": "conditional_micro_live_signoff",
            "allowed_scope": "MICRO_LIVE_ONLY",
            "preflight_status": "READY_FOR_MICRO_LIVE",
            "first_required_review_code": "approval_template_review",
            "next_step": "review_required_warning_and_record_micro_live_signoff",
        }
    }

    events = notify_stage_change._collect_events(previous, current)
    event_types = {event["type"] for event in events}

    assert "runtime_operator_signoff_ready" in event_types
    assert "runtime_operator_signoff_changed" in event_types


def test_collect_events_emits_lineage_sample_progress_event():
    previous = {
        "lineage_sample_summary": {
            "scope": "family_global",
            "families": ["sweep_reversal", "trend_continuation"],
            "proof_goal_closed_trades": 100,
            "closed_trade_count": 2,
            "remaining_closed_trades_to_goal": 98,
        }
    }
    current = {
        "lineage_sample_summary": {
            "scope": "family_global",
            "families": ["sweep_reversal", "trend_continuation"],
            "proof_goal_closed_trades": 100,
            "closed_trade_count": 3,
            "remaining_closed_trades_to_goal": 97,
        }
    }

    events = notify_stage_change._collect_events(previous, current)
    event_types = {event["type"] for event in events}

    assert "lineage_sample_progressed" in event_types


def test_collect_events_emits_open_lineage_sample_count_change_event():
    previous = {
        "open_lineage_sample_summary": {
            "open_sample_count": 1,
            "sample_limit": 3,
            "samples": [
                {
                    "symbol": "ARBUSDC",
                    "last_fill_stage": "PARTIAL_EXIT",
                }
            ],
        }
    }
    current = {
        "open_lineage_sample_summary": {
            "open_sample_count": 2,
            "sample_limit": 3,
            "samples": [
                {
                    "symbol": "FILUSDC",
                    "last_fill_stage": "ENTRY",
                },
                {
                    "symbol": "ARBUSDC",
                    "last_fill_stage": "PARTIAL_EXIT",
                },
            ],
        }
    }

    events = notify_stage_change._collect_events(previous, current)
    event_types = {event["type"] for event in events}

    assert "open_lineage_sample_count_changed" in event_types


def test_collect_events_emits_first_lineage_closed_fill_event():
    previous = {
        "lineage_sample_summary": {
            "scope": "family_global",
            "families": ["sweep_reversal", "trend_continuation"],
            "proof_goal_closed_trades": 100,
            "closed_trade_count": 0,
            "remaining_closed_trades_to_goal": 100,
        },
        "lineage_closed_fill_health": {
            "status": "no_closed_fills_present",
            "healthy": False,
            "closed_trade_count": 0,
            "summary": "no lineage CLOSED fills observed yet",
        },
    }
    current = {
        "lineage_sample_summary": {
            "scope": "family_global",
            "families": ["sweep_reversal", "trend_continuation"],
            "proof_goal_closed_trades": 100,
            "closed_trade_count": 1,
            "remaining_closed_trades_to_goal": 99,
        },
        "lineage_closed_fill_health": {
            "status": "closed_fills_present",
            "healthy": True,
            "closed_trade_count": 1,
            "latest_closed_trade_at": "2026-04-08T09:00:00+00:00",
            "summary": "lineage CLOSED fills observed: 1 | latest=2026-04-08T09:00:00+00:00",
        },
    }

    events = notify_stage_change._collect_events(previous, current)
    event_types = {event["type"] for event in events}

    assert "lineage_sample_progressed" in event_types
    assert "first_lineage_closed_fill_observed" in event_types


def test_collect_events_emits_edge_sample_stall_event():
    previous = {
        "edge_sample_stall": {
            "active": False,
            "threshold_hours": 24,
            "hours_since_progress": 6.0,
            "current_closed_trade_count": 2,
        }
    }
    current = {
        "edge_sample_stall": {
            "active": True,
            "threshold_hours": 24,
            "hours_since_progress": 49.0,
            "current_closed_trade_count": 2,
        }
    }

    events = notify_stage_change._collect_events(previous, current)
    event_types = {event["type"] for event in events}

    assert "edge_sample_stall" in event_types


def test_collect_events_emits_active_lineage_sample_stall_event():
    previous = {
        "active_lineage_sample_health": {
            "active": False,
            "threshold_hours": 6,
            "hours_open": 1.0,
            "status": "tracking",
            "symbol": "ARBUSDC",
            "last_fill_stage": "ENTRY",
        }
    }
    current = {
        "active_lineage_sample_health": {
            "active": True,
            "threshold_hours": 6,
            "hours_open": 7.25,
            "status": "stalled",
            "symbol": "ARBUSDC",
            "last_fill_stage": "ENTRY",
        }
    }

    events = notify_stage_change._collect_events(previous, current)
    event_types = {event["type"] for event in events}

    assert "active_lineage_sample_stall" in event_types


def test_collect_events_emits_active_lineage_sample_progress_event():
    previous = {
        "active_lineage_sample_focus": {
            "symbol": "ARBUSDC",
            "strategy_family": "sweep_reversal",
            "status": "OPEN_PAPER_SAMPLE",
            "plan_id": "plan_zone_c15debc65a13_confirm",
            "hours_open": 0.20,
            "last_fill_stage": "ENTRY",
        }
    }
    current = {
        "active_lineage_sample_focus": {
            "symbol": "ARBUSDC",
            "strategy_family": "sweep_reversal",
            "status": "OPEN_PAPER_SAMPLE",
            "plan_id": "plan_zone_c15debc65a13_confirm",
            "hours_open": 0.40,
            "last_fill_stage": "PARTIAL_EXIT",
        }
    }

    events = notify_stage_change._collect_events(previous, current)
    event_types = {event["type"] for event in events}

    assert "active_lineage_sample_progressed" in event_types


def test_collect_events_initial_snapshot_only_on_first_run():
    current = {
        "stage": "0_BLOCKED",
        "close_only_active": True,
        "playbook_go_no_go": "NO_GO",
        "trial_runs_written": 0,
        "selected_trial_run_id": None,
        "execution_degradation": "manual_review",
    }

    events = notify_stage_change._collect_events(None, current)

    assert events == [
        {
            "type": "initial_snapshot",
            "title": "Initial stage snapshot",
            "body": "Current stage is 0_BLOCKED.",
        }
    ]


def test_render_message_uses_approval_surface_lines() -> None:
    current = {
        "stage": "2_LINEAGE_READY",
        "lineage_gate_ready": True,
        "candidate_gate_ready": True,
        "edge_sample_gate_ready": False,
        "all_readiness_gates_ready": False,
        "dashboard_approval_strip": {
            "approve_value": "entry gate blocked",
            "align_value": "aligned",
            "act_value": "continue_candidate_review_under_portfolio_caps",
        },
        "validation_approval_strip": {
            "approve_value": "approval usable",
            "align_value": "aligned",
            "act_value": "review_runtime_execution_drag_before_expansion",
        },
        "checklist_approval_strip": {
            "approve_value": "approval usable",
            "align_value": "aligned",
            "act_value": "clear_blocking_operational_items_before_rollout",
        },
        "close_only_active": True,
        "checklist_status": "FAIL",
        "eligible_closed_trades": 4,
        "trial_runs_written": 1,
        "selected_trial_run_id": "trial_run_001",
        "execution_degradation": "manual_review",
        "top_operator_action": "continue_candidate_review_under_portfolio_caps",
        "alpha_research_next_step": "review_execution_drag_before_reopen",
        "edge_experiment_review": {
            "edge_state": "watch_edge",
            "entry_timing_preferred_variant": "early_limit",
            "execution_style_preferred_variant": "passive_limit",
            "true_edge_ratio": 0.82,
            "edge_decay_rate": -0.03,
            "edge_proof_goal_closed_trades": 100,
            "remaining_closed_trades_to_edge_proof_goal": 94,
            "edge_proof_posture": {
                "state": "sample_building",
                "claim_state": "do_not_claim_edge_yet",
            },
            "daily_edge_kpis": {
                "closed_trade_count": 6,
                "true_edge_ratio": 0.82,
                "edge_decay_rate": -0.03,
                "regime_dependency_state": "single_regime_observed",
            },
        },
        "edge_evolution_rule": {
            "evolution_state": "reduce_candidate",
            "recommended_action": "reduce_baseline_allocation_review",
            "allocation_bias": "reduce_baseline",
            "promotion_candidate_axis": "entry_timing",
            "promotion_candidate_variant": "early_limit",
        },
        "review_followup_ledger": {
            "last_status": "READY",
            "last_action": "reduce_baseline_allocation_review",
            "recent_entry_count": 3,
            "last_followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action reduce_baseline_allocation_review",
        },
        "lineage_sample_summary": {
            "scope": "family_global",
            "families": ["sweep_reversal"],
            "proof_goal_closed_trades": 100,
            "closed_trade_count": 12,
            "remaining_closed_trades_to_goal": 88,
        },
        "lineage_closed_fill_health": {
            "status": "closed_fills_present",
            "healthy": True,
            "closed_trade_count": 12,
            "latest_closed_trade_at": "2026-03-27T08:00:00+00:00",
            "summary": "lineage CLOSED fills observed: 12 | latest=2026-03-27T08:00:00+00:00",
        },
        "open_lineage_sample_summary": {
            "open_sample_count": 2,
            "sample_limit": 3,
            "samples": [
                {"symbol": "FILUSDC", "last_fill_stage": "ENTRY"},
                {"symbol": "ARBUSDC", "last_fill_stage": "PARTIAL_EXIT"},
            ],
            "symbols": ["FILUSDC", "ARBUSDC"],
        },
        "entry_timing_review_target": {
            "action": "run_entry_timing_split_review",
            "preferred_variant": "early_limit",
            "symbol": "BTCUSDC",
            "status": "ACTIONABLE_ENTRY",
            "strategy_family": "sweep_reversal",
            "focus_source": "accepted_candidate_focus",
            "followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_entry_timing_split_review",
        },
        "execution_style_review_target": {
            "action": "run_execution_style_split_review",
            "preferred_variant": "passive_limit",
            "symbol": "BTCUSDC",
            "status": "ACTIONABLE_ENTRY",
            "strategy_family": "sweep_reversal",
            "focus_source": "accepted_candidate_focus",
            "followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_execution_style_split_review",
        },
        "representative_candidates": {
            "accepted": {
                "symbol": "BTCUSDC",
                "strategy_family": "sweep_reversal",
                "edge_state": "watch_edge",
                "entry_timing_preferred_variant": "early_limit",
                "execution_style_preferred_variant": "passive_limit",
            },
            "blocked": {
                "symbol": "ETHUSDC",
                "strategy_family": "trend_continuation",
                "block_reason": "portfolio_cap",
                "edge_state": "fragile_edge",
                "entry_timing_preferred_variant": "reaction_confirmed",
                "execution_style_preferred_variant": "market",
            },
        },
        "edge_sample_stall": {
            "active": True,
            "threshold_hours": 24,
            "hours_since_progress": 49.0,
            "current_closed_trade_count": 2,
        },
        "post_unlock_review_summary": {
            "active": True,
            "review_window_open": False,
            "current_stage": "2_LINEAGE_READY",
            "current_checklist_status": "FAIL",
            "current_validation_playbook_go_no_go": "MANUAL_REVIEW",
            "next_review_step": "wait_for_operating_lock_to_clear",
            "bundle_review_command": "./.venv/bin/python scripts/run_post_unlock_review.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30",
            "primary_review_command": "./.venv/bin/python scripts/run_micro_live_preflight.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30",
            "secondary_review_command": "./.venv/bin/python scripts/run_post_live_pruning_review.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30",
        },
        "post_unlock_bundle_result": {
            "active": True,
            "executed": False,
            "status": "waiting_for_review_window",
            "summary": "post-unlock bundle review is waiting for the review window to open",
            "micro_live_preflight_status": "",
            "post_live_pruning_review_decision": "",
        },
        "runtime_reopen_status": {
            "status": "waiting_for_operating_lock",
            "ready": False,
        },
            "runtime_signoff_summary": {
                "status": "manual_signoff_required",
                "operator_recommendation": "hold_runtime_reopen",
                "operator_recommendation_reason": "replay-derived worst scenario still fails",
                "runtime_decision": {
                    "band": "RED_HOLD",
                    "effective_action": "hold_runtime_reopen",
                    "allowed_reopen_scope": "none",
                },
                "required_reviews": [
                {
                    "code": "approval_template_review",
                    "worst_scenario": "latency_plus_1_bar",
                    "worst_scenario_status": "FAIL",
                    "worst_scenario_reason": "catastrophic_drawdown:replay_output",
                },
                {"code": "execution_reconciliation_review"},
                {"code": "portfolio_headroom_review"},
            ],
            "advisory_reviews": [],
            "required_count": 3,
            "advisory_count": 0,
            "required_clearance_line": "approval_template_review=>clear | execution_reconciliation_review=>clear | portfolio_headroom_review=>clear",
            "approval_template_focus": {
                "focus_symbol": "LINEAGE_GLOBAL",
                "replay_max_drawdown_r": 10.1003,
                "replay_p5_r": -1.05,
                "approximation_gap_max_drawdown_r": 0.95,
                "confirm_loss_cluster_summary": {
                    "loss_trade_count": 83,
                    "median_held_bars": 1502.0,
                    "p75_held_bars": 2552,
                    "held_bar_bands": {
                        "over_240": 78,
                        "over_1000": 61,
                        "over_2000": 33,
                    },
                    "top_symbols": [
                        {"symbol": "WIFUSDC", "loss_trade_count": 12, "negative_r": -12.6},
                        {"symbol": "SOLUSDC", "loss_trade_count": 9, "negative_r": -9.45},
                        {"symbol": "NEARUSDC", "loss_trade_count": 8, "negative_r": -8.4},
                    ],
                    "top_waves": [
                        {"closed_ts": "2026-04-08T12:24:00+00:00", "loss_trade_count": 64}
                    ],
                },
                "entry_timing_loss_profile": {
                    "dominant_loss_cohort": "confirm",
                    "confirm_loss_share": 0.883,
                    "confirm_negative_r_share": 0.8912,
                    "held_bar_gap_confirm_minus_non_confirm": 1114.0,
                    "confirm": {
                        "loss_trade_count": 83,
                        "negative_r": -87.15,
                    },
                    "non_confirm": {
                        "loss_trade_count": 11,
                        "negative_r": -11.55,
                    },
                },
                "entry_timing_priority_summary": {
                    "primary_focus_code": "confirm_entry_tighten",
                    "primary_summary": "confirm 손실 비중이 높아 range confirm-entry를 먼저 줄여야 함",
                    "secondary_focus_code": "non_confirm_fail_fast",
                    "secondary_summary": "non-confirm 손실은 수는 적지만 더 오래 끌려서 fail-fast shadow 검토가 필요함",
                    "ordered_focus": ["confirm_entry_tighten", "non_confirm_fail_fast"],
                },
                "mitigation_execution_plan": {
                    "primary_focus_label": "confirm 진입 타이밍 축소",
                    "primary_status": "candidate_review_pending",
                    "primary_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_entry_timing_split_review",
                    "secondary_focus_label": "non-confirm fail-fast",
                    "secondary_status": "deferred_by_experiment_sequence",
                    "secondary_command": "",
                    "ordered_steps": [],
                },
                    "downside_profile": {
                        "trade_count": 176,
                        "dominant_regime": "range",
                        "stop_loss_count": 94,
                        "loss_trade_count": 94,
                        "confirm_named_loss_share": 0.883,
                        "median_loss_held_bars": 1594.0,
                        "long_hold_loss_count": 88,
                        "long_hold_loss_share": 0.9362,
                        "worst_loss_streak": 9,
                        "top_loss_waves": [
                            {"closed_ts": "2026-04-08T12:24:00+00:00", "loss_trade_count": 72}
                        ],
                        "top_loss_wave_share_of_losses": 0.766,
                        "primary_failure_mode": "range_confirm_entry_loss_wave",
                        "top_loss_symbols": [
                            {"symbol": "WIFUSDC", "negative_r": -13.65, "loss_trade_count": 13}
                        ],
                    "mitigation_focus": [
                        {"code": "range_entry_timing_review"},
                        {"code": "shadow_fail_fast_review"},
                        {"code": "loss_wave_cluster_review"},
                    ],
                },
                "mitigation_review_summary": {
                    "primary_action_code": "range_entry_timing_review",
                    "primary_action_status": "candidate_review_pending",
                    "primary_action_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_entry_timing_split_review",
                    "items": [
                        {
                            "code": "range_entry_timing_review",
                            "status": "candidate_review_pending",
                            "review_mode": "live_split_review",
                        },
                        {
                            "code": "shadow_fail_fast_review",
                            "status": "deferred_by_experiment_sequence",
                            "review_mode": "shadow_only",
                        },
                        {
                            "code": "loss_wave_cluster_review",
                            "status": "manual_operator_review",
                            "review_mode": "research_only",
                        },
                    ],
                },
            },
        },
        "runtime_mitigation_summary": {
            "available": True,
            "primary_action_code": "range_entry_timing_review",
            "primary_action_status": "candidate_review_pending",
            "primary_action_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_entry_timing_split_review",
            "primary_action_constraint": "waiting_for_actionable_entry_timing_target",
            "actionable_now_count": 0,
            "candidate_pending_count": 1,
            "deferred_count": 1,
            "research_only_count": 1,
        },
        "runtime_mitigation_packet_result": {
            "available": True,
            "status": "waiting_for_actionable_mitigation",
            "executed": False,
            "packet_id": "",
            "target_symbol": "",
            "target_variant": "",
            "focus_label": "confirm 진입 타이밍 축소",
            "wait_constraint": "waiting_for_actionable_entry_timing_target",
            "primary_action_status": "candidate_review_pending",
        },
        "runtime_mitigation_wait_summary": {
            "available": True,
            "status": "watcher_found_candidate_pending_review_target",
            "focus_label": "confirm 진입 타이밍 축소",
            "current_session": "london",
            "allowed_sessions": ["london", "new_york"],
            "wait_constraint": "waiting_for_actionable_entry_timing_target",
            "next_trigger": "entry_timing_review_target_materializes",
            "candidate_symbol": "WIFUSDC",
            "candidate_family": "sweep_reversal",
            "candidate_status": "APPROVED_AUTO",
            "candidate_reason": "Eligible PAPER lineage candidate found on attempt 1.",
            "watch_tick_status": "found_eligible_candidate",
        },
        "runtime_preflight_summary": {
            "status": "READY_FOR_MICRO_LIVE",
            "summary": "All preflight checks passed; MICRO_LIVE can proceed to final operator sign-off.",
            "effective_action": "conditional_micro_live_signoff",
            "failed_checks": [],
        },
        "runtime_operator_signoff_summary": {
            "status": "ready_for_manual_micro_live_signoff",
            "allowed_scope": "MICRO_LIVE_ONLY",
            "first_required_review_code": "approval_template_review",
            "next_step": "review_required_warning_and_record_micro_live_signoff",
        },
    }

    message = notify_stage_change._render_message(current, [])

    assert message.startswith("트레이딩 상태 알림")
    assert "현재 단계: 2_LINEAGE_READY / 사유=n/a" in message
    assert "승인 상태: 대시보드=진입 차단, 검증=사용 가능, 체크리스트=사용 가능" in message
    assert "리스크 잠금: 열림 / 사유=normal / 해제=n/a" in message
    assert "재개 상태: 운영 잠금 해제 대기" in message
    assert "최종 판정: 보류(RED) / 재개 보류 / 범위=재개 금지" in message
    assert "마이크로라이브 사전점검: READY_FOR_MICRO_LIVE / All preflight checks passed; MICRO_LIVE can proceed to final operator sign-off." in message
    assert "운영 서명 단계: MICRO_LIVE만 수동 서명 가능 / 범위=MICRO_LIVE만 / 우선 검토=승인 템플릿 경고 / 다음=경고 검토 후 MICRO_LIVE 서명" in message
    assert "권장 판단: 재개 보류 권장" in message
    assert "수동 서명: 승인 템플릿 경고, 실행 정합성 점검, 포트폴리오 여유 검토" in message
    assert "핵심 경고: 최악 시나리오 latency_plus_1_bar = FAIL (catastrophic_drawdown:replay_output)" in message
    assert "정량 경고: LINEAGE_GLOBAL / maxDD=10.1003R / p5=-1.05R / ΔDD=+0.95R" in message
    assert "구조 경고: range regime, stop_loss 94/176, confirm 손실 88%, 손실 중앙 보유 1594 bars, 최대 연속 손실 9회, 손실 파동 72건, 상위 손실 WIFUSDC -13.65R" in message
    assert "주원인: range 구간 confirm-entry + 장기 보유 손절 + 동시 손실 파동" in message
    assert "confirm 손실군: 83건, 중앙 보유 1502 bars, p75 보유 2552 bars, >1000 bars 61건, confirm 파동 64건, 상위 심볼 WIFUSDC/SOLUSDC/NEARUSDC" in message
    assert "entry timing 비교: confirm 83건/-87.15R, non-confirm 11건/-11.55R, confirm 비중 88%, 보유 격차 +1114 bars" in message
    assert "진입 우선순위: 1) confirm 진입 타이밍 축소, 2) non-confirm fail-fast" in message
    assert "실행 순서: 1) confirm 진입 타이밍 축소 (후보 대기), 2) non-confirm fail-fast (순서상 보류)" in message
    assert "권장 대응: range 진입 타이밍 재검토, fail-fast shadow review, loss wave cluster 검토" in message
    assert "대응 상태: entry timing split=후보 대기, fail-fast shadow=순서상 보류, loss wave 검토=수동 검토" in message
    assert "실행 포커스: entry timing split / 후보 뜰 때 실행 / 제약=waiting_for_actionable_entry_timing_target" in message
    assert "실행 패킷: confirm 진입 타이밍 축소 대기 / 상태=candidate_review_pending / 제약=waiting_for_actionable_entry_timing_target" in message
    assert "대기 사유: confirm 진입 타이밍 축소 / watcher_found_candidate_pending_review_target / 세션=london / 허용=london,new_york / 다음 트리거=entry_timing_review_target_materializes / 최근 후보=WIFUSDC:sweep_reversal / 사유=Eligible PAPER lineage candidate found on attempt 1. / watcher=found_eligible_candidate" in message
    assert "해소 기준: 승인 템플릿 REVIEW 해제, 실행 정합성 degraded 해제, 포트폴리오 여유 검토" in message
    assert "글로벌 표본: 12/100" in message
    assert "BTCUSDC 표본: 6/100 / 상태=sample_building" in message
    assert "준비 게이트: lineage=True, candidate=True, sample=False" in message
    assert "열린 샘플: 없음" in message
    assert "다음 액션: continue_candidate_review_under_portfolio_caps" in message


def test_collect_events_reports_runtime_mitigation_actionable_with_command() -> None:
    previous = {
        "runtime_mitigation_summary": {
            "available": True,
            "primary_action_code": "range_entry_timing_review",
            "primary_action_status": "candidate_review_pending",
            "primary_focus_label": "confirm 진입 타이밍 축소",
            "secondary_focus_label": "non-confirm fail-fast",
            "secondary_status": "deferred_by_experiment_sequence",
        }
    }
    current = {
        "runtime_mitigation_summary": {
            "available": True,
            "primary_action_code": "range_entry_timing_review",
            "primary_action_status": "actionable_now",
            "primary_action_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_entry_timing_split_review",
            "primary_focus_label": "confirm 진입 타이밍 축소",
            "secondary_focus_label": "non-confirm fail-fast",
            "secondary_status": "deferred_by_experiment_sequence",
        }
    }

    events = notify_stage_change._collect_events(previous, current)
    event_types = [event["type"] for event in events]

    assert "runtime_mitigation_changed" in event_types
    assert "runtime_mitigation_actionable" in event_types
    actionable = next(event for event in events if event["type"] == "runtime_mitigation_actionable")
    rendered = notify_stage_change._event_line_ko(actionable, current)
    assert "range_entry_timing_review / actionable_now" in rendered
    assert "--action run_entry_timing_split_review" in rendered
    summary_line = notify_stage_change._runtime_mitigation_summary_line(current)
    assert "focus=confirm 진입 타이밍 축소" in summary_line
    assert "next=non-confirm fail-fast/deferred_by_experiment_sequence" in summary_line
    packet_line = notify_stage_change._runtime_mitigation_packet_summary_line(
        {
            "runtime_mitigation_packet_result": {
                "status": "waiting_for_actionable_mitigation",
                "focus_label": "confirm 진입 타이밍 축소",
                "primary_action_status": "candidate_review_pending",
                "executed": False,
                "target_symbol": "",
                "target_variant": "",
                "wait_constraint": "waiting_for_actionable_entry_timing_target",
            }
        }
    )
    assert "focus=confirm 진입 타이밍 축소" in packet_line
    assert "constraint=waiting_for_actionable_entry_timing_target" in packet_line
    wait_line = notify_stage_change._runtime_mitigation_wait_summary_line(
        {
            "runtime_mitigation_wait_summary": {
                "status": "watcher_found_candidate_pending_review_target",
                "focus_label": "confirm 진입 타이밍 축소",
                "current_session": "london",
                "allowed_sessions": ["london", "new_york"],
                "candidate_symbol": "WIFUSDC",
                "candidate_family": "sweep_reversal",
                "candidate_reason": "Eligible PAPER lineage candidate found on attempt 1.",
                "watch_tick_status": "found_eligible_candidate",
                "next_trigger": "entry_timing_review_target_materializes",
            }
        }
    )
    assert "status=watcher_found_candidate_pending_review_target" in wait_line
    assert "focus=confirm 진입 타이밍 축소" in wait_line
    assert "session=london" in wait_line
    assert "allowed=london,new_york" in wait_line
    assert "next=entry_timing_review_target_materializes" in wait_line


def test_collect_events_reports_runtime_mitigation_packet_ready() -> None:
    previous = {
        "runtime_mitigation_packet_result": {
            "available": True,
            "status": "waiting_for_actionable_mitigation",
        }
    }
    current = {
        "runtime_mitigation_packet_result": {
            "available": True,
            "status": "fresh_packet_ready_exists",
            "packet_id": "review_followup:existing",
            "target_symbol": "WIFUSDC",
        }
    }

    events = notify_stage_change._collect_events(previous, current)
    event_types = [event["type"] for event in events]

    assert "runtime_mitigation_packet_changed" in event_types
    assert "runtime_mitigation_packet_ready" in event_types
    ready_event = next(event for event in events if event["type"] == "runtime_mitigation_packet_ready")
    rendered = notify_stage_change._event_line_ko(ready_event, current)
    assert "fresh_packet_ready_exists / WIFUSDC" in rendered
    assert "review_followup:existing" in rendered


def test_main_returns_warning_without_writing_state_when_delivery_fails(monkeypatch, tmp_path, capsys) -> None:
    stage_file = tmp_path / "current_stage.json"
    state_file = tmp_path / "last_alert_state.json"
    stage_file.write_text(json.dumps({"stage": "0_BLOCKED"}, ensure_ascii=False), encoding="utf-8")

    args = notify_stage_change.argparse.Namespace(
        stage_file=str(stage_file),
        state_file=str(state_file),
        webhook_url="",
        dry_run=False,
    )

    monkeypatch.setattr(notify_stage_change, "parse_args", lambda: args)
    monkeypatch.setattr(
        notify_stage_change,
        "_dispatch_stage_notification",
        lambda current, *, message, webhook_url: {
            "channel": "discord",
            "delivered": False,
            "skipped": False,
            "reason": "http_403",
            "status_code": 403,
        },
    )

    exit_code = notify_stage_change.main()

    captured = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert captured["notified"] is False
    assert captured["delivery"]["reason"] == "http_403"
    assert captured["warning"] == "discord delivery not completed: http_403"
    assert state_file.exists() is False


def test_reuse_recent_runtime_monitor_fields_keeps_authoritative_runtime_status() -> None:
    payload = {
        "generated_at": "2026-04-09T06:10:00+00:00",
        "stage": "0_BLOCKED",
        "selected_trial_run_id": "LINEAGE_GLOBAL_v2_true_threshold",
        "checklist_status": "WARN",
        "playbook_go_no_go": "MANUAL_REVIEW",
        "lineage_sample_summary": {"closed_trade_count": 183},
        "risk_gate_summary": {"risk_state": "OPEN"},
        "runtime_reopen_status": {"status": "manual_review_required"},
    }
    previous = {
        "generated_at": "2026-04-09T06:05:00+00:00",
        "stage": "3_APPROVAL_REVIEW",
        "selected_trial_run_id": "LINEAGE_GLOBAL_v2_true_threshold",
        "checklist_status": "WARN",
        "playbook_go_no_go": "MANUAL_REVIEW",
        "lineage_sample_summary": {"closed_trade_count": 183},
        "risk_gate_summary": {"risk_state": "OPEN"},
        "runtime_reopen_status": {"status": "ready_to_reopen_runtime"},
        "runtime_signoff_summary": {"status": "manual_signoff_required"},
        "runtime_operator_signoff_summary": {"status": "ready_for_manual_micro_live_signoff"},
        "runtime_mitigation_wait_summary": {"status": "no_lineage_candidate_visible"},
    }

    reused = ops_stage_board._reuse_recent_runtime_monitor_fields(
        payload,
        previous,
        now=datetime(2026, 4, 9, 6, 12, tzinfo=timezone.utc),
    )

    assert reused["runtime_reopen_status"]["status"] == "ready_to_reopen_runtime"
    assert reused["runtime_signoff_summary"]["status"] == "manual_signoff_required"
    assert reused["runtime_operator_signoff_summary"]["status"] == "ready_for_manual_micro_live_signoff"
    assert reused["runtime_mitigation_wait_summary"]["status"] == "no_lineage_candidate_visible"
    assert reused["runtime_monitor_snapshot_reused"] is True


def test_dispatch_stage_notification_truncates_message_for_discord(monkeypatch) -> None:
    calls: list[dict] = []

    class _FakeDispatcher:
        def __init__(self, settings):  # noqa: ANN001
            self.settings = settings

        def dispatch(self, *, channel, alert_type, symbol, payload):  # noqa: ANN001
            calls.append(
                {
                    "channel": channel,
                    "alert_type": alert_type,
                    "symbol": symbol,
                    "payload": payload,
                }
            )
            return {"delivered": True, "reason": "delivered"}

    monkeypatch.setattr(notify_stage_change, "NotificationDispatcher", _FakeDispatcher)

    result = notify_stage_change._dispatch_stage_notification(
        {"entry_timing_review_target": {"symbol": "BTCUSDC"}},
        message="x" * 2500,
        webhook_url="",
    )

    assert result["delivered"] is True
    assert calls[0]["symbol"] == "BTCUSDC"
    assert len(calls[0]["payload"]["message"]) <= 1800
    assert calls[0]["payload"]["message"].endswith("...[truncated]")
