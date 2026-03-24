from __future__ import annotations

import importlib.util
from pathlib import Path


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
    execution_degradation: str = "manual_review",
    top_operator_action: str = "continue_candidate_review_under_portfolio_caps",
    alpha_research_next_step: str = "run_shadow_cost_stress_review",
):
    return {
        "deployment_approval_summary": {
            "playbook_go_no_go": playbook_go_no_go,
            "deployment_go_no_go": None,
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


def _checklist(*, overall_status: str = "FAIL"):
    return {
        "overall_status": overall_status,
        "approval_strip_summary": {
            "approve_value": "validation/checklist no_go" if overall_status == "FAIL" else "approval usable",
            "align_value": "aligned",
            "act_value": "clear_blocking_operational_items_before_rollout",
        },
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


def test_stage_payload_reports_blocked_state():
    payload = ops_stage_board._build_stage_payload(
        _validation_report(),
        _checklist(),
        _dashboard(),
    )

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


def test_collect_events_emits_transition_events():
    previous = {
        "stage": "1_SAMPLE_COLLECTION",
        "close_only_active": False,
        "playbook_go_no_go": "MANUAL_REVIEW",
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
    assert "execution_manual_review" in event_types


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
    }

    message = notify_stage_change._render_message(current, [])

    assert "dashboard_surface: approve=entry gate blocked | align=aligned | act=continue_candidate_review_under_portfolio_caps" in message
    assert "validation_surface: approve=approval usable | align=aligned | act=review_runtime_execution_drag_before_expansion" in message
    assert "checklist_surface: approve=approval usable | align=aligned | act=clear_blocking_operational_items_before_rollout" in message
    assert "edge_experiment: state=watch_edge | entry_timing=early_limit | execution_style=passive_limit | true_edge=0.8200" in message
    assert "edge_evolution: state=reduce_candidate | action=reduce_baseline_allocation_review | bias=reduce_baseline | promotion=entry_timing/early_limit" in message
    assert "review_followup_ledger: status=READY | action=reduce_baseline_allocation_review | entries=3 | cmd=./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action reduce_baseline_allocation_review" in message
    assert "entry_timing_review_target: action=run_entry_timing_split_review | target=BTCUSDC | variant=early_limit | status=ACTIONABLE_ENTRY | family=sweep_reversal | focus=accepted_candidate_focus | cmd=./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_entry_timing_split_review" in message
    assert "execution_style_review_target: action=run_execution_style_split_review | target=BTCUSDC | variant=passive_limit | status=ACTIONABLE_ENTRY | family=sweep_reversal | focus=accepted_candidate_focus | cmd=./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_execution_style_split_review" in message
    assert "accepted_candidate_focus: BTCUSDC | family=sweep_reversal | edge=watch_edge | split=early_limit/passive_limit" in message
    assert "blocked_candidate_focus: ETHUSDC | family=trend_continuation | edge=fragile_edge | split=reaction_confirmed/market | reason=portfolio_cap" in message
    assert "playbook_go_no_go" not in message
    assert "deployment_go_no_go" not in message
