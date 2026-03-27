#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.notification_dispatcher import NotificationDispatcher


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Notify Discord when the operating stage or key blocker signals change."
    )
    parser.add_argument("--stage-file", default=str(ROOT_DIR / "reports/operations/stage_monitor/current_stage.json"))
    parser.add_argument(
        "--state-file",
        default=str(ROOT_DIR / "reports/operations/stage_monitor/last_alert_state.json"),
    )
    parser.add_argument("--webhook-url", default="")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_stage(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise RuntimeError(f"stage file is missing or invalid: {path}")
    return payload


def _webhook_url(cli_value: str) -> str:
    if cli_value.strip():
        return cli_value.strip()
    return str(get_settings().alert_discord_webhook_url or "").strip()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _changed(previous: dict[str, Any] | None, current: dict[str, Any], key: str) -> bool:
    if previous is None:
        return False
    return previous.get(key) != current.get(key)


def _trial_runs_started(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    before = int(previous.get("trial_runs_written") or 0)
    after = int(current.get("trial_runs_written") or 0)
    return before == 0 and after > 0


def _winner_selected(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    before = previous.get("selected_trial_run_id")
    after = current.get("selected_trial_run_id")
    return before is None and after is not None


def _manual_review_trigger(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    current_status = str(current.get("execution_degradation") or "").lower()
    if current_status != "manual_review":
        return False
    if previous is None:
        return True
    previous_status = str(previous.get("execution_degradation") or "").lower()
    return previous_status != "manual_review"


def _gate_flipped_ready(previous: dict[str, Any] | None, current: dict[str, Any], key: str) -> bool:
    if previous is None:
        return False
    return not bool(previous.get(key, False)) and bool(current.get(key, False))


def _edge_sample_stall_trigger(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    current_active = bool(dict(current.get("edge_sample_stall") or {}).get("active", False))
    if not current_active:
        return False
    if previous is None:
        return True
    previous_active = bool(dict(previous.get("edge_sample_stall") or {}).get("active", False))
    return not previous_active


def _surface_summary(payload: dict[str, Any] | None, key: str) -> dict[str, str]:
    summary = dict((payload or {}).get(key) or {})
    if summary:
        return {
            "approve_value": str(summary.get("approve_value") or "n/a"),
            "align_value": str(summary.get("align_value") or "n/a"),
            "act_value": str(summary.get("act_value") or "continue_runtime_monitoring"),
        }

    current = dict(payload or {})
    return {
        "approve_value": str(current.get("deployment_go_no_go") or current.get("checklist_status") or "n/a"),
        "align_value": str(current.get("playbook_go_no_go") or "n/a"),
        "act_value": str(
            current.get("top_operator_action")
            or current.get("alpha_research_next_step")
            or "continue_runtime_monitoring"
        ),
    }


def _surface_summary_line(payload: dict[str, Any] | None, key: str, *, label: str) -> str:
    summary = _surface_summary(payload, key)
    return (
        f"{label}: approve={summary.get('approve_value', 'n/a')} | "
        f"align={summary.get('align_value', 'n/a')} | "
        f"act={summary.get('act_value', 'continue_runtime_monitoring')}"
    )


def _surface_changed(previous: dict[str, Any] | None, current: dict[str, Any], key: str, *, label: str) -> bool:
    if previous is None:
        return False
    return _surface_summary_line(previous, key, label=label) != _surface_summary_line(current, key, label=label)


def _edge_experiment_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict((payload or {}).get("edge_experiment_review") or {})
    if not source:
        return {
            "edge_state": "unavailable",
            "entry_timing_preferred_variant": "none",
            "execution_style_preferred_variant": "none",
            "edge_proof_goal_closed_trades": 0,
            "remaining_closed_trades_to_edge_proof_goal": 0,
            "edge_proof_posture": {"state": "unknown", "claim_state": "unknown"},
            "daily_edge_kpis": {
                "closed_trade_count": 0,
                "true_edge_ratio": 0.0,
                "edge_decay_rate": 0.0,
                "regime_dependency_state": "not_available",
            },
        }
    edge_proof_posture = dict(source.get("edge_proof_posture") or {})
    daily_edge_kpis = dict(source.get("daily_edge_kpis") or {})
    return {
        "edge_state": str(source.get("edge_state") or "insufficient_edge_measurement"),
        "entry_timing_preferred_variant": str(source.get("entry_timing_preferred_variant") or "none"),
        "execution_style_preferred_variant": str(source.get("execution_style_preferred_variant") or "none"),
        "edge_proof_goal_closed_trades": int(
            source.get("edge_proof_goal_closed_trades") or edge_proof_posture.get("edge_proof_goal_closed_trades") or 0
        ),
        "remaining_closed_trades_to_edge_proof_goal": int(
            source.get("remaining_closed_trades_to_edge_proof_goal")
            or edge_proof_posture.get("remaining_closed_trades_to_edge_proof_goal")
            or 0
        ),
        "edge_proof_posture": {
            "state": str(edge_proof_posture.get("state") or "unknown"),
            "claim_state": str(edge_proof_posture.get("claim_state") or "unknown"),
        },
        "daily_edge_kpis": {
            "closed_trade_count": int(daily_edge_kpis.get("closed_trade_count", source.get("closed_trade_count", 0)) or 0),
            "true_edge_ratio": round(_float(daily_edge_kpis.get("true_edge_ratio", source.get("true_edge_ratio"))), 4),
            "edge_decay_rate": round(_float(daily_edge_kpis.get("edge_decay_rate", source.get("edge_decay_rate"))), 4),
            "regime_dependency_state": str(
                daily_edge_kpis.get("regime_dependency_state") or source.get("regime_dependency_state") or "not_available"
            ),
        },
    }


def _edge_experiment_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _edge_experiment_summary(payload)
    posture = dict(summary.get("edge_proof_posture") or {})
    kpis = dict(summary.get("daily_edge_kpis") or {})
    return (
        f"edge_experiment: state={summary.get('edge_state', 'unavailable')} | "
        f"entry_timing={summary.get('entry_timing_preferred_variant', 'none')} | "
        f"execution_style={summary.get('execution_style_preferred_variant', 'none')} | "
        f"proof={posture.get('state', 'unknown')}/{posture.get('claim_state', 'unknown')} | "
        f"closes={int(kpis.get('closed_trade_count', 0) or 0)}/{int(summary.get('edge_proof_goal_closed_trades', 0) or 0)} | "
        f"remaining={int(summary.get('remaining_closed_trades_to_edge_proof_goal', 0) or 0)} | "
        f"regime={kpis.get('regime_dependency_state', 'not_available')} | "
        f"true_edge={float(kpis.get('true_edge_ratio', 0.0) or 0.0):.4f} | "
        f"decay={float(kpis.get('edge_decay_rate', 0.0) or 0.0):.4f}"
    )


def _edge_evolution_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict((payload or {}).get("edge_evolution_rule") or {})
    if not source:
        return {
            "evolution_state": "unavailable",
            "recommended_action": "keep_current_baseline",
            "allocation_bias": "hold_current_baseline",
            "promotion_candidate_axis": "none",
            "promotion_candidate_variant": "none",
        }
    return {
        "evolution_state": str(source.get("evolution_state") or "insufficient_sample"),
        "recommended_action": str(source.get("recommended_action") or "keep_current_baseline"),
        "allocation_bias": str(source.get("allocation_bias") or "hold_current_baseline"),
        "promotion_candidate_axis": str(source.get("promotion_candidate_axis") or "none"),
        "promotion_candidate_variant": str(source.get("promotion_candidate_variant") or "none"),
    }


def _edge_evolution_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _edge_evolution_summary(payload)
    return (
        f"edge_evolution: state={summary.get('evolution_state', 'unavailable')} | "
        f"action={summary.get('recommended_action', 'keep_current_baseline')} | "
        f"bias={summary.get('allocation_bias', 'hold_current_baseline')} | "
        f"promotion={summary.get('promotion_candidate_axis', 'none')}/{summary.get('promotion_candidate_variant', 'none')}"
    )


def _review_followup_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict((payload or {}).get("review_followup_ledger") or {})
    if not source:
        return {
            "last_status": "none",
            "last_action": "none",
            "recent_entry_count": 0,
            "last_followup_command": "",
        }
    return {
        "last_status": str(source.get("last_status") or "none"),
        "last_action": str(source.get("last_action") or "none"),
        "recent_entry_count": int(source.get("recent_entry_count", 0) or 0),
        "last_followup_command": str(source.get("last_followup_command") or ""),
    }


def _review_followup_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _review_followup_summary(payload)
    return (
        f"review_followup_ledger: status={summary.get('last_status', 'none')} | "
        f"action={summary.get('last_action', 'none')} | "
        f"entries={summary.get('recent_entry_count', 0)} | "
        f"cmd={summary.get('last_followup_command', '') or 'none'}"
    )


def _lineage_sample_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict((payload or {}).get("lineage_sample_summary") or {})
    return {
        "scope": str(source.get("scope") or "symbol_edge_proof"),
        "families": list(source.get("families") or []),
        "proof_goal_closed_trades": int(source.get("proof_goal_closed_trades", 0) or 0),
        "closed_trade_count": int(source.get("closed_trade_count", 0) or 0),
        "remaining_closed_trades_to_goal": int(source.get("remaining_closed_trades_to_goal", 0) or 0),
    }


def _lineage_sample_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _lineage_sample_summary(payload)
    families = ",".join(str(item) for item in summary.get("families", []) if str(item).strip()) or "none"
    return (
        f"lineage_sample: scope={summary.get('scope', 'unknown')} | "
        f"families={families} | "
        f"closes={summary.get('closed_trade_count', 0)}/{summary.get('proof_goal_closed_trades', 0)} | "
        f"remaining={summary.get('remaining_closed_trades_to_goal', 0)}"
    )


def _readiness_gates_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    current = dict(payload or {})
    source = dict(current.get("readiness_gates") or {})
    return {
        "lineage_gate_ready": bool(source.get("lineage_gate_ready", current.get("lineage_gate_ready", False))),
        "candidate_gate_ready": bool(source.get("candidate_gate_ready", current.get("candidate_gate_ready", False))),
        "edge_sample_gate_ready": bool(source.get("edge_sample_gate_ready", current.get("edge_sample_gate_ready", False))),
        "all_ready": bool(source.get("all_ready", current.get("all_readiness_gates_ready", False))),
        "summary": str(source.get("summary") or ""),
    }


def _readiness_gates_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _readiness_gates_summary(payload)
    return (
        f"readiness_gates: lineage={summary.get('lineage_gate_ready', False)} | "
        f"candidate={summary.get('candidate_gate_ready', False)} | "
        f"edge_sample={summary.get('edge_sample_gate_ready', False)} | "
        f"all_ready={summary.get('all_ready', False)}"
    )


def _edge_sample_stall_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict((payload or {}).get("edge_sample_stall") or {})
    return {
        "active": bool(source.get("active", False)),
        "threshold_hours": int(source.get("threshold_hours", 0) or 0),
        "hours_since_progress": round(_float(source.get("hours_since_progress", 0.0)), 2),
        "progress_count": int(source.get("progress_count", 0) or 0),
        "current_closed_trade_count": int(source.get("current_closed_trade_count", 0) or 0),
        "last_progress_at": str(source.get("last_progress_at") or ""),
        "status": str(source.get("status") or "unknown"),
        "summary": str(source.get("summary") or ""),
    }


def _edge_sample_stall_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _edge_sample_stall_summary(payload)
    return (
        f"edge_sample_stall: active={summary.get('active', False)} | "
        f"hours_since_progress={summary.get('hours_since_progress', 0.0):.2f} | "
        f"closes={summary.get('current_closed_trade_count', 0)} | "
        f"threshold_hours={summary.get('threshold_hours', 0)}"
    )


def _candidate_focus_summary_line(payload: dict[str, Any] | None, key: str, *, label: str) -> str:
    source = dict((((payload or {}).get("representative_candidates") or {}).get(key) or {}))
    if not source:
        return f"{label}: none"
    line = (
        f"{label}: {source.get('symbol') or 'unknown'} | "
        f"family={source.get('strategy_family') or 'unknown'} | "
        f"edge={source.get('edge_state') or 'insufficient_edge_measurement'} | "
        f"split={(source.get('entry_timing_preferred_variant') or 'none')}/{(source.get('execution_style_preferred_variant') or 'none')}"
    )
    if source.get("status"):
        line = f"{line} | status={source.get('status')}"
    if source.get("block_reason"):
        line = f"{line} | reason={source.get('block_reason')}"
    return line


def _experiment_review_target_summary_line(payload: dict[str, Any] | None, key: str, *, label: str) -> str:
    source = dict((payload or {}).get(key) or {})
    if not source:
        return f"{label}: none"
    line = (
        f"{label}: action={source.get('action') or 'unknown'} | "
        f"target={source.get('symbol') or 'unknown'} | "
        f"variant={source.get('preferred_variant') or 'none'} | "
        f"status={source.get('status') or 'unknown'} | "
        f"family={source.get('strategy_family') or 'unknown'}"
    )
    if source.get("block_reason"):
        line = f"{line} | reason={source.get('block_reason')}"
    if source.get("focus_source"):
        line = f"{line} | focus={source.get('focus_source')}"
    if source.get("followup_command"):
        line = f"{line} | cmd={source.get('followup_command')}"
    return line


def _edge_experiment_changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    return _edge_experiment_summary_line(previous) != _edge_experiment_summary_line(current)


def _edge_evolution_changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    return _edge_evolution_summary_line(previous) != _edge_evolution_summary_line(current)


def _review_followup_changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    return _review_followup_summary_line(previous) != _review_followup_summary_line(current)


def _candidate_focus_changed(previous: dict[str, Any] | None, current: dict[str, Any], key: str, *, label: str) -> bool:
    if previous is None:
        return False
    return _candidate_focus_summary_line(previous, key, label=label) != _candidate_focus_summary_line(
        current, key, label=label
    )


def _experiment_review_target_changed(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    key: str,
    *,
    label: str,
) -> bool:
    if previous is None:
        return False
    return _experiment_review_target_summary_line(previous, key, label=label) != _experiment_review_target_summary_line(
        current, key, label=label
    )


def _collect_events(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    if previous is None:
        events.append(
            {
                "type": "initial_snapshot",
                "title": "Initial stage snapshot",
                "body": f"Current stage is {current.get('stage')}.",
            }
        )
        return events

    if _changed(previous, current, "stage"):
        events.append(
            {
                "type": "stage_changed",
                "title": "Operating stage changed",
                "body": f"{previous.get('stage')} -> {current.get('stage')}",
            }
        )
    if _changed(previous, current, "close_only_active"):
        events.append(
            {
                "type": "close_only_changed",
                "title": "Close-only state changed",
                "body": f"{previous.get('close_only_active')} -> {current.get('close_only_active')}",
            }
        )
    if _surface_changed(previous, current, "dashboard_approval_strip", label="dashboard_surface"):
        events.append(
            {
                "type": "dashboard_surface_changed",
                "title": "Dashboard approval surface changed",
                "body": (
                    f"{_surface_summary_line(previous, 'dashboard_approval_strip', label='dashboard_surface')} -> "
                    f"{_surface_summary_line(current, 'dashboard_approval_strip', label='dashboard_surface')}"
                ),
            }
        )
    if _surface_changed(previous, current, "validation_approval_strip", label="validation_surface"):
        events.append(
            {
                "type": "playbook_changed",
                "title": "Validation approval surface changed",
                "body": (
                    f"{_surface_summary_line(previous, 'validation_approval_strip', label='validation_surface')} -> "
                    f"{_surface_summary_line(current, 'validation_approval_strip', label='validation_surface')}"
                ),
            }
        )
    elif _changed(previous, current, "playbook_go_no_go"):
        events.append(
            {
                "type": "playbook_changed",
                "title": "Validation approval surface changed",
                "body": f"{previous.get('playbook_go_no_go')} -> {current.get('playbook_go_no_go')}",
            }
        )
    if _surface_changed(previous, current, "checklist_approval_strip", label="checklist_surface"):
        events.append(
            {
                "type": "checklist_surface_changed",
                "title": "Checklist approval surface changed",
                "body": (
                    f"{_surface_summary_line(previous, 'checklist_approval_strip', label='checklist_surface')} -> "
                    f"{_surface_summary_line(current, 'checklist_approval_strip', label='checklist_surface')}"
                ),
            }
        )
    if _edge_experiment_changed(previous, current):
        events.append(
            {
                "type": "edge_experiment_changed",
                "title": "Edge experiment focus changed",
                "body": f"{_edge_experiment_summary_line(previous)} -> {_edge_experiment_summary_line(current)}",
            }
        )
    if _edge_evolution_changed(previous, current):
        events.append(
            {
                "type": "edge_evolution_changed",
                "title": "Edge evolution recommendation changed",
                "body": f"{_edge_evolution_summary_line(previous)} -> {_edge_evolution_summary_line(current)}",
            }
        )
    if _review_followup_changed(previous, current):
        events.append(
            {
                "type": "review_followup_changed",
                "title": "Review followup ledger changed",
                "body": f"{_review_followup_summary_line(previous)} -> {_review_followup_summary_line(current)}",
            }
        )
    if _candidate_focus_changed(previous, current, "accepted", label="accepted_candidate_focus"):
        events.append(
            {
                "type": "accepted_candidate_focus_changed",
                "title": "Accepted candidate focus changed",
                "body": (
                    f"{_candidate_focus_summary_line(previous, 'accepted', label='accepted_candidate_focus')} -> "
                    f"{_candidate_focus_summary_line(current, 'accepted', label='accepted_candidate_focus')}"
                ),
            }
        )
    if _candidate_focus_changed(previous, current, "blocked", label="blocked_candidate_focus"):
        events.append(
            {
                "type": "blocked_candidate_focus_changed",
                "title": "Blocked candidate focus changed",
                "body": (
                    f"{_candidate_focus_summary_line(previous, 'blocked', label='blocked_candidate_focus')} -> "
                    f"{_candidate_focus_summary_line(current, 'blocked', label='blocked_candidate_focus')}"
                ),
            }
        )
    if _experiment_review_target_changed(previous, current, "entry_timing_review_target", label="entry_timing_review_target"):
        events.append(
            {
                "type": "entry_timing_review_target_changed",
                "title": "Entry timing review target changed",
                "body": (
                    f"{_experiment_review_target_summary_line(previous, 'entry_timing_review_target', label='entry_timing_review_target')} -> "
                    f"{_experiment_review_target_summary_line(current, 'entry_timing_review_target', label='entry_timing_review_target')}"
                ),
            }
        )
    if _experiment_review_target_changed(previous, current, "execution_style_review_target", label="execution_style_review_target"):
        events.append(
            {
                "type": "execution_style_review_target_changed",
                "title": "Execution style review target changed",
                "body": (
                    f"{_experiment_review_target_summary_line(previous, 'execution_style_review_target', label='execution_style_review_target')} -> "
                    f"{_experiment_review_target_summary_line(current, 'execution_style_review_target', label='execution_style_review_target')}"
                ),
            }
        )
    if _trial_runs_started(previous, current):
        events.append(
            {
                "type": "trial_runs_started",
                "title": "Lineage trial runs started",
                "body": f"trial_runs_written: {previous.get('trial_runs_written')} -> {current.get('trial_runs_written')}",
            }
        )
    if _winner_selected(previous, current):
        events.append(
            {
                "type": "winner_selected",
                "title": "Selected trial run became available",
                "body": f"selected_trial_run_id: {current.get('selected_trial_run_id')}",
            }
        )
    if _gate_flipped_ready(previous, current, "lineage_gate_ready"):
        events.append(
            {
                "type": "lineage_gate_ready",
                "title": "Lineage gate is ready",
                "body": _readiness_gates_summary_line(current),
            }
        )
    if _gate_flipped_ready(previous, current, "candidate_gate_ready"):
        events.append(
            {
                "type": "candidate_gate_ready",
                "title": "Lineage candidate gate is ready",
                "body": _readiness_gates_summary_line(current),
            }
        )
    if _gate_flipped_ready(previous, current, "edge_sample_gate_ready"):
        events.append(
            {
                "type": "edge_sample_gate_ready",
                "title": "Edge sample gate is ready",
                "body": _readiness_gates_summary_line(current),
            }
        )
    if _gate_flipped_ready(previous, current, "all_readiness_gates_ready"):
        events.append(
            {
                "type": "all_readiness_gates_ready",
                "title": "All edge-proof readiness gates are ready",
                "body": _readiness_gates_summary_line(current),
            }
        )
    if _edge_sample_stall_trigger(previous, current):
        events.append(
            {
                "type": "edge_sample_stall",
                "title": "Edge sample accumulation stalled",
                "body": _edge_sample_stall_summary_line(current),
            }
        )
    if _manual_review_trigger(previous, current):
        events.append(
            {
                "type": "execution_manual_review",
                "title": "Execution manual review required",
                "body": f"execution_degradation: {current.get('execution_degradation')}",
            }
        )
    return events


def _render_message(current: dict[str, Any], events: list[dict[str, str]]) -> str:
    lines = ["Trading engine stage monitor"]
    for event in events:
        lines.append(f"- {event['title']}: {event['body']}")
    lines.extend(
        [
            "",
            f"stage: {current.get('stage')}",
            _surface_summary_line(current, "dashboard_approval_strip", label="dashboard_surface"),
            _surface_summary_line(current, "validation_approval_strip", label="validation_surface"),
            _surface_summary_line(current, "checklist_approval_strip", label="checklist_surface"),
            _edge_experiment_summary_line(current),
            _edge_evolution_summary_line(current),
            _review_followup_summary_line(current),
            _lineage_sample_summary_line(current),
            _experiment_review_target_summary_line(current, "entry_timing_review_target", label="entry_timing_review_target"),
            _experiment_review_target_summary_line(current, "execution_style_review_target", label="execution_style_review_target"),
            _candidate_focus_summary_line(current, "accepted", label="accepted_candidate_focus"),
            _candidate_focus_summary_line(current, "blocked", label="blocked_candidate_focus"),
            _readiness_gates_summary_line(current),
            _edge_sample_stall_summary_line(current),
            f"close_only_active: {current.get('close_only_active')}",
            f"checklist_status: {current.get('checklist_status')}",
            f"eligible_closed_trades: {current.get('eligible_closed_trades')}",
            f"trial_runs_written: {current.get('trial_runs_written')}",
            f"selected_trial_run_id: {current.get('selected_trial_run_id')}",
            f"execution_degradation: {current.get('execution_degradation')}",
            f"top_operator_action: {current.get('top_operator_action')}",
            f"alpha_research_next_step: {current.get('alpha_research_next_step')}",
        ]
    )
    return "\n".join(lines)


def _post_discord(webhook_url: str, message: str) -> dict[str, Any]:
    payload = json.dumps({"content": message}).encode("utf-8")
    request = Request(
        url=webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return {"ok": True, "status": getattr(response, "status", 204)}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"discord webhook failed with HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"discord webhook failed: {exc.reason}") from exc


def _notification_symbol(current: dict[str, Any]) -> str:
    for key in ("entry_timing_review_target", "execution_style_review_target"):
        target = dict(current.get(key) or {})
        symbol = str(target.get("symbol") or "").strip().upper()
        if symbol:
            return symbol
    representative = dict(current.get("representative_candidates") or {})
    for key in ("accepted", "blocked"):
        candidate = dict(representative.get(key) or {})
        symbol = str(candidate.get("symbol") or "").strip().upper()
        if symbol:
            return symbol
    return "OPERATIONS"


def _discord_safe_message(message: str, *, max_chars: int = 1800) -> str:
    content = str(message or "")
    if len(content) <= max_chars:
        return content
    suffix = "\n...[truncated]"
    budget = max(0, max_chars - len(suffix))
    return content[:budget].rstrip() + suffix


def _dispatch_stage_notification(current: dict[str, Any], *, message: str, webhook_url: str) -> dict[str, Any]:
    settings = get_settings()
    if webhook_url.strip():
        settings.alert_discord_webhook_url = webhook_url.strip()
    dispatcher = NotificationDispatcher(settings)
    return dispatcher.dispatch(
        channel="discord",
        alert_type="stage_monitor_alert",
        symbol=_notification_symbol(current),
        payload={"message": _discord_safe_message(message)},
    )


def main() -> int:
    args = parse_args()
    stage_file = Path(args.stage_file).resolve()
    state_file = Path(args.state_file).resolve()
    current = _load_stage(stage_file)
    previous = _read_json(state_file)
    events = _collect_events(previous, current)

    result: dict[str, Any] = {
        "stage_file": str(stage_file),
        "state_file": str(state_file),
        "current": current,
        "previous": previous,
        "events": events,
        "notified": False,
        "dry_run": bool(args.dry_run),
    }

    if not events:
        _write_json(state_file, current)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    message = _render_message(current, events)
    result["message"] = message

    if args.dry_run:
        _write_json(state_file, current)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    delivery = _dispatch_stage_notification(current, message=message, webhook_url=args.webhook_url)
    result["delivery"] = delivery
    result["notified"] = bool(delivery.get("delivered"))
    if not result["notified"]:
        result["warning"] = f"discord delivery not completed: {delivery.get('reason')}"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    result["delivery"] = delivery
    _write_json(state_file, current)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
