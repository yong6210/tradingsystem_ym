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
        },
        "alpha_research_pipeline_summary": {
            "recommended_action": alpha_research_next_step,
        },
    }


def _checklist(*, overall_status: str = "FAIL"):
    return {
        "overall_status": overall_status,
    }


def _dashboard(*, new_entries_allowed: bool = False, close_only_active: bool = True):
    return {
        "new_entries_allowed": new_entries_allowed,
        "active_locks": (
            [{"reason_code": "close_only_active"}] if close_only_active else []
        ),
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


def test_collect_events_emits_transition_events():
    previous = {
        "stage": "1_SAMPLE_COLLECTION",
        "close_only_active": False,
        "playbook_go_no_go": "MANUAL_REVIEW",
        "trial_runs_written": 0,
        "selected_trial_run_id": None,
        "execution_degradation": "watch",
    }
    current = {
        "stage": "2_LINEAGE_READY",
        "close_only_active": True,
        "playbook_go_no_go": "GO",
        "trial_runs_written": 1,
        "selected_trial_run_id": "trial_run_001",
        "execution_degradation": "manual_review",
    }

    events = notify_stage_change._collect_events(previous, current)
    event_types = {event["type"] for event in events}

    assert "stage_changed" in event_types
    assert "close_only_changed" in event_types
    assert "playbook_changed" in event_types
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
