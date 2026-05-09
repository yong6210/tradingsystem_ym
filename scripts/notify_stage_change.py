#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.core import operator_surface_contracts as osc
from app.services.notification_dispatcher import NotificationDispatcher


def _resolve_root_path(raw_path: str | Path) -> Path:
    path = Path(raw_path).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


def _ensure_http_url(url: str) -> None:
    scheme = urlparse(url).scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError(f"unsupported webhook URL scheme: {scheme or 'missing'}")


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


def _active_lineage_sample_stall_trigger(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    current_active = bool(dict(current.get("active_lineage_sample_health") or {}).get("active", False))
    if not current_active:
        return False
    if previous is None:
        return True
    previous_active = bool(dict(previous.get("active_lineage_sample_health") or {}).get("active", False))
    return not previous_active


def _active_lineage_sample_progressed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    before = dict(previous.get("active_lineage_sample_focus") or {})
    after = dict(current.get("active_lineage_sample_focus") or {})
    before_plan = str(before.get("plan_id") or "")
    after_plan = str(after.get("plan_id") or "")
    if not after_plan:
        return False
    if before_plan != after_plan:
        return True
    before_stage = str(before.get("last_fill_stage") or "")
    after_stage = str(after.get("last_fill_stage") or "")
    return bool(after_stage) and before_stage != after_stage


def _risk_gate_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict((payload or {}).get("risk_gate_summary") or {})


def _risk_gate_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _risk_gate_summary(payload)
    return (
        f"risk_gate: status={summary.get('status') or 'NOT_AVAILABLE'} | "
        f"state={summary.get('risk_state') or 'UNKNOWN'} | "
        f"reason={summary.get('risk_reason') or 'unknown'} | "
        f"unlock_at={summary.get('unlock_at') or 'n/a'} | "
        f"daily_r={float(summary.get('daily_realized_r', 0.0) or 0.0):.4f}/"
        f"{float(summary.get('daily_loss_limit_r', 0.0) or 0.0):.4f} | "
        f"loss_streak={int(summary.get('daily_loss_streak', 0) or 0)}"
    )


def _risk_gate_unlock_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict((payload or {}).get("risk_gate_unlock_summary") or {})


def _risk_gate_unlock_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _risk_gate_unlock_summary(payload)
    return (
        f"risk_gate_unlock: active={bool(summary.get('active', False))} | "
        f"status={summary.get('status') or 'not_available'} | "
        f"unlock_at={summary.get('unlock_at') or 'n/a'}"
    )


def _post_unlock_review_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict((payload or {}).get("post_unlock_review_summary") or {})
    return {
        "active": bool(source.get("active", False)),
        "review_window_open": bool(source.get("review_window_open", False)),
        "current_stage": str(source.get("current_stage") or "unknown"),
        "current_checklist_status": str(source.get("current_checklist_status") or "UNKNOWN"),
        "current_validation_playbook_go_no_go": str(source.get("current_validation_playbook_go_no_go") or ""),
        "current_validation_approve_value": str(source.get("current_validation_approve_value") or ""),
        "expected_stage_after_unlock": str(source.get("expected_stage_after_unlock") or ""),
        "expected_checklist_status_after_unlock": str(source.get("expected_checklist_status_after_unlock") or ""),
        "next_review_step": str(source.get("next_review_step") or "wait_for_operating_lock_to_clear"),
        "bundle_review_command": str(source.get("bundle_review_command") or ""),
        "primary_review_command": str(source.get("primary_review_command") or ""),
        "secondary_review_command": str(source.get("secondary_review_command") or ""),
        "summary": str(source.get("summary") or ""),
    }


def _post_unlock_review_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _post_unlock_review_summary(payload)
    validation_value = (
        summary.get("current_validation_playbook_go_no_go")
        or summary.get("current_validation_approve_value")
        or "n/a"
    )
    return (
        f"post_unlock_review: active={summary.get('active', False)} | "
        f"review_window_open={summary.get('review_window_open', False)} | "
        f"current_stage={summary.get('current_stage', 'unknown')} | "
        f"checklist={summary.get('current_checklist_status', 'UNKNOWN')} | "
        f"validation={validation_value} | "
        f"next={summary.get('next_review_step', 'wait_for_operating_lock_to_clear')}"
    )


def _post_unlock_review_commands_line(payload: dict[str, Any] | None) -> str:
    summary = _post_unlock_review_summary(payload)
    return (
        f"post_unlock_review_commands: bundle={summary.get('bundle_review_command') or 'n/a'} | "
        f"primary={summary.get('primary_review_command') or 'n/a'} | "
        f"secondary={summary.get('secondary_review_command') or 'n/a'}"
    )


def _post_unlock_bundle_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict((payload or {}).get("post_unlock_bundle_result") or {})
    return {
        "active": bool(source.get("active", False)),
        "executed": bool(source.get("executed", False)),
        "status": str(source.get("status") or "NOT_AVAILABLE"),
        "summary": str(source.get("summary") or ""),
        "bundle_review_command": str(source.get("bundle_review_command") or ""),
        "micro_live_preflight_status": str(source.get("micro_live_preflight_status") or ""),
        "post_live_pruning_review_decision": str(source.get("post_live_pruning_review_decision") or ""),
    }


def _post_unlock_bundle_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _post_unlock_bundle_summary(payload)
    return (
        f"post_unlock_bundle: active={summary.get('active', False)} | "
        f"executed={summary.get('executed', False)} | "
        f"status={summary.get('status', 'NOT_AVAILABLE')} | "
        f"preflight={summary.get('micro_live_preflight_status') or 'n/a'} | "
        f"pruning={summary.get('post_live_pruning_review_decision') or 'n/a'}"
    )


def _runtime_reopen_status_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict((payload or {}).get("runtime_reopen_status") or {})
    return {
        "status": str(source.get("status") or "not_available"),
        "ready": bool(source.get("ready", False)),
        "summary": str(source.get("summary") or ""),
    }


def _runtime_reopen_status_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _runtime_reopen_status_summary(payload)
    return (
        f"runtime_reopen_status: status={summary.get('status', 'not_available')} | "
        f"ready={summary.get('ready', False)}"
    )


def _runtime_operator_signoff_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict((payload or {}).get("runtime_operator_signoff_summary") or {})
    return {
        "status": str(source.get("status") or "not_available"),
        "effective_action": str(source.get("effective_action") or ""),
        "allowed_scope": str(source.get("allowed_scope") or ""),
        "preflight_status": str(source.get("preflight_status") or ""),
        "first_required_review_code": str(source.get("first_required_review_code") or ""),
        "next_step": str(source.get("next_step") or ""),
        "intent_execution_mode": str(source.get("intent_execution_mode") or ""),
        "contract_scope": str(source.get("contract_scope") or ""),
        "review_command": str(source.get("review_command") or ""),
    }


def _runtime_live_cluster_guard_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict((payload or {}).get("runtime_live_cluster_guard_summary") or {})
    return {
        "status": str(source.get("status") or "not_available"),
        "active": bool(source.get("active", False)),
        "current_reason_code": str(source.get("current_reason_code") or ""),
        "current_reason_message": str(source.get("current_reason_message") or ""),
        "cluster_window_blocked_candidates": int(source.get("cluster_window_blocked_candidates", 0) or 0),
        "loss_cooldown_blocked_candidates": int(source.get("loss_cooldown_blocked_candidates", 0) or 0),
        "families": [str(item) for item in list(source.get("families") or []) if str(item).strip()],
        "symbols": [str(item) for item in list(source.get("symbols") or []) if str(item).strip()],
    }


def _runtime_live_cluster_guard_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _runtime_live_cluster_guard_summary(payload)
    return (
        f"runtime_live_cluster_guard: status={summary.get('status', 'not_available')}"
        f" | cluster={int(summary.get('cluster_window_blocked_candidates') or 0)}"
        f" | cooldown={int(summary.get('loss_cooldown_blocked_candidates') or 0)}"
        + (
            f" | families={','.join(summary.get('families') or [])}"
            if summary.get("families")
            else ""
        )
        + (
            f" | symbols={','.join(summary.get('symbols') or [])}"
            if summary.get("symbols")
            else ""
        )
        + (
            f" | reason={summary.get('current_reason_code')}"
            if summary.get("current_reason_code")
            else ""
        )
    )


def _runtime_operator_signoff_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _runtime_operator_signoff_summary(payload)
    submit_mode = str(summary.get("intent_execution_mode") or "")
    contract_scope = str(summary.get("contract_scope") or "")
    submit_path = ""
    if submit_mode:
        submit_path = f"{submit_mode}/live:true"
        if contract_scope:
            submit_path = f"{submit_path}/{contract_scope}"
    return (
        f"runtime_operator_signoff: status={summary.get('status', 'not_available')}"
        + (f" | action={summary.get('effective_action')}" if summary.get("effective_action") else "")
        + (f" | scope={summary.get('allowed_scope')}" if summary.get("allowed_scope") else "")
        + (f" | preflight={summary.get('preflight_status')}" if summary.get("preflight_status") else "")
        + (
            f" | first_required={summary.get('first_required_review_code')}"
            if summary.get("first_required_review_code")
            else ""
        )
        + (f" | next={summary.get('next_step')}" if summary.get("next_step") else "")
        + (f" | submit={submit_path}" if submit_path else "")
        + (f" | review_cmd={summary.get('review_command')}" if summary.get("review_command") else "")
    )


def _runtime_signoff_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    current = dict(payload or {})
    source = dict(current.get("runtime_signoff_summary") or {})
    required_reviews = list(
        current.get("required_reviews")
        if isinstance(current.get("required_reviews"), list)
        else source.get("required_reviews")
        or []
    )
    advisory_reviews = list(
        current.get("advisory_reviews")
        if isinstance(current.get("advisory_reviews"), list)
        else source.get("advisory_reviews")
        or []
    )
    runtime_decision = dict(current.get("runtime_decision") or source.get("runtime_decision") or {})
    runtime_reopen_gate_summary = dict(
        current.get("runtime_reopen_gate_summary") or source.get("runtime_reopen_gate_summary") or {}
    )
    approval_template_focus = dict(current.get("approval_template_focus") or source.get("approval_template_focus") or {})
    operator_recommendation = str(
        current.get("runtime_operator_recommendation")
        or source.get("operator_recommendation")
        or ""
    )
    return {
        "status": str(source.get("status") or "not_available"),
        "required_reviews": required_reviews,
        "advisory_reviews": advisory_reviews,
        "required_count": len(required_reviews),
        "advisory_count": len(advisory_reviews),
        "required_clearance_line": str(source.get("required_clearance_line") or ""),
        "operator_recommendation": operator_recommendation,
        "operator_recommendation_reason": str(source.get("operator_recommendation_reason") or ""),
        "runtime_decision": runtime_decision,
        "runtime_reopen_gate_summary": runtime_reopen_gate_summary,
        "approval_template_focus": approval_template_focus,
        "approval_template_focus_error": str(source.get("approval_template_focus_error") or ""),
        "summary": str(source.get("summary") or ""),
    }


def _runtime_mitigation_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict((payload or {}).get("runtime_mitigation_summary") or {})
    return {
        "available": bool(source.get("available", False)),
        "primary_action_code": str(source.get("primary_action_code") or ""),
        "primary_action_status": str(source.get("primary_action_status") or ""),
        "primary_action_command": str(source.get("primary_action_command") or ""),
        "primary_action_constraint": str(source.get("primary_action_constraint") or ""),
        "primary_focus_code": str(source.get("primary_focus_code") or ""),
        "primary_focus_label": str(source.get("primary_focus_label") or ""),
        "secondary_focus_code": str(source.get("secondary_focus_code") or ""),
        "secondary_focus_label": str(source.get("secondary_focus_label") or ""),
        "secondary_status": str(source.get("secondary_status") or ""),
        "actionable_now_count": int(source.get("actionable_now_count", 0) or 0),
        "candidate_pending_count": int(source.get("candidate_pending_count", 0) or 0),
        "deferred_count": int(source.get("deferred_count", 0) or 0),
        "research_only_count": int(source.get("research_only_count", 0) or 0),
        "summary": str(source.get("summary") or ""),
    }


def _runtime_mitigation_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _runtime_mitigation_summary(payload)
    return (
        f"runtime_mitigation: primary={summary.get('primary_action_code') or 'none'}/"
        f"{summary.get('primary_action_status') or 'none'} | "
        f"focus={summary.get('primary_focus_label') or summary.get('primary_action_code') or 'none'} | "
        f"next={summary.get('secondary_focus_label') or 'none'}/{summary.get('secondary_status') or 'none'} | "
        f"actionable={summary.get('actionable_now_count', 0)} | "
        f"pending={summary.get('candidate_pending_count', 0)} | "
        f"deferred={summary.get('deferred_count', 0)}"
    )


def _runtime_mitigation_packet_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict((payload or {}).get("runtime_mitigation_packet_result") or {})
    return {
        "available": bool(source.get("available", False)),
        "status": str(source.get("status") or "inactive"),
        "executed": bool(source.get("executed", False)),
        "packet_id": str(source.get("packet_id") or ""),
        "command": str(source.get("command") or ""),
        "target_symbol": str(source.get("target_symbol") or ""),
        "target_variant": str(source.get("target_variant") or ""),
        "focus_label": str(source.get("focus_label") or ""),
        "wait_constraint": str(source.get("wait_constraint") or ""),
        "primary_action_status": str(source.get("primary_action_status") or ""),
        "summary": str(source.get("summary") or ""),
    }


def _runtime_mitigation_wait_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict((payload or {}).get("runtime_mitigation_wait_summary") or {})
    return {
        "available": bool(source.get("available", False)),
        "status": str(source.get("status") or "inactive"),
        "focus_label": str(source.get("focus_label") or ""),
        "wait_constraint": str(source.get("wait_constraint") or ""),
        "next_trigger": str(source.get("next_trigger") or ""),
        "current_session": str(source.get("current_session") or ""),
        "session_active": bool(source.get("session_active", False)),
        "allowed_sessions": [str(item) for item in list(source.get("allowed_sessions") or []) if str(item).strip()],
        "candidate_symbol": str(source.get("candidate_symbol") or ""),
        "candidate_family": str(source.get("candidate_family") or ""),
        "candidate_status": str(source.get("candidate_status") or ""),
        "candidate_reason": str(source.get("candidate_reason") or ""),
        "watch_tick_status": str(source.get("watch_tick_status") or ""),
        "watch_generated_at": str(source.get("watch_generated_at") or ""),
        "watch_guard_active": bool(source.get("watch_guard_active", False)),
        "watch_guard_family": str(source.get("watch_guard_family") or ""),
        "watch_guard_families": [str(item) for item in list(source.get("watch_guard_families") or []) if str(item).strip()],
        "watch_guard_reason_code": str(source.get("watch_guard_reason_code") or ""),
        "summary": str(source.get("summary") or ""),
    }


def _runtime_mitigation_packet_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _runtime_mitigation_packet_summary(payload)
    return (
        f"runtime_mitigation_packet: status={summary.get('status') or 'inactive'} | "
        f"focus={summary.get('focus_label') or 'none'} | "
        f"action={summary.get('primary_action_status') or 'none'} | "
        f"executed={summary.get('executed', False)} | "
        f"target={summary.get('target_symbol') or 'none'} | "
        f"variant={summary.get('target_variant') or 'none'}"
        + (
            f" | constraint={summary.get('wait_constraint')}"
            if summary.get("wait_constraint")
            else ""
        )
    )


def _runtime_mitigation_wait_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _runtime_mitigation_wait_summary(payload)
    status = str(summary.get("status") or "").strip().lower()
    allowed_sessions = ",".join(str(item) for item in list(summary.get("allowed_sessions") or []) if str(item).strip())
    guard_text = ""
    if bool(summary.get("watch_guard_active", False)):
        families = ",".join(str(item) for item in list(summary.get("watch_guard_families") or []) if str(item).strip())
        guard_family = str(summary.get("watch_guard_family") or "")
        guard_scope = families or guard_family or "none"
        guard_text = f" | guard={summary.get('watch_guard_reason_code') or 'active'}:{guard_scope}"
    return (
        f"runtime_mitigation_wait: status={osc.EN_RUNTIME_MITIGATION_WAIT_STATUS_LABELS.get(status, status or 'inactive')} | "
        f"focus={summary.get('focus_label') or 'none'} | "
        f"session={summary.get('current_session') or 'unknown'} | "
        f"allowed={allowed_sessions or 'none'} | "
        f"candidate={summary.get('candidate_symbol') or 'none'}/{summary.get('candidate_family') or 'none'} | "
        f"next={summary.get('next_trigger') or 'none'}"
        f"{guard_text}"
        + (
            f" | reason={summary.get('candidate_reason')}"
            if summary.get("candidate_reason")
            else ""
        )
    )


def _risk_gate_changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    return _risk_gate_summary_line(previous) != _risk_gate_summary_line(current)


def _risk_gate_cleared(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    before = _risk_gate_summary(previous)
    after = _risk_gate_summary(current)
    before_status = str(before.get("status") or "").upper()
    after_status = str(after.get("status") or "").upper()
    before_state = str(before.get("risk_state") or "").upper()
    after_state = str(after.get("risk_state") or "").upper()
    return before_status == "FAIL" and after_status == "PASS" and before_state == "CLOSED" and after_state == "OPEN"


def _post_unlock_review_ready(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    before = _post_unlock_review_summary(previous)
    after = _post_unlock_review_summary(current)
    return not bool(before.get("review_window_open", False)) and bool(after.get("review_window_open", False))


def _post_unlock_bundle_changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    return _post_unlock_bundle_summary_line(previous) != _post_unlock_bundle_summary_line(current)


def _runtime_reopen_ready(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    before = _post_unlock_bundle_summary(previous)
    after = _post_unlock_bundle_summary(current)
    return str(before.get("status") or "") != "READY_TO_REOPEN_RUNTIME" and str(after.get("status") or "") == "READY_TO_REOPEN_RUNTIME"


def _runtime_reopen_status_changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    return _runtime_reopen_status_summary_line(previous) != _runtime_reopen_status_summary_line(current)


def _runtime_operator_signoff_ready(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    before = _runtime_operator_signoff_summary(previous)
    after = _runtime_operator_signoff_summary(current)
    ready_statuses = {
        osc.RUNTIME_OPERATOR_SIGNOFF_STATUS_READY_FOR_MANUAL_MICRO_LIVE_SIGNOFF,
        osc.RUNTIME_OPERATOR_SIGNOFF_STATUS_READY_FOR_MANUAL_FULL_LIVE_SIGNOFF,
        osc.RUNTIME_OPERATOR_SIGNOFF_STATUS_READY_FOR_OPERATOR_SIGNOFF,
    }
    return str(before.get("status") or "") not in ready_statuses and str(after.get("status") or "") in ready_statuses


def _runtime_operator_signoff_changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    return _runtime_operator_signoff_summary_line(previous) != _runtime_operator_signoff_summary_line(current)


def _runtime_live_cluster_guard_changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    return _runtime_live_cluster_guard_summary_line(previous) != _runtime_live_cluster_guard_summary_line(current)


def _runtime_mitigation_changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    return _runtime_mitigation_summary_line(previous) != _runtime_mitigation_summary_line(current)


def _runtime_mitigation_actionable(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    before = _runtime_mitigation_summary(previous)
    after = _runtime_mitigation_summary(current)
    return str(before.get("primary_action_status") or "") != osc.MITIGATION_ACTION_STATUS_ACTIONABLE_NOW and str(
        after.get("primary_action_status") or ""
    ) == osc.MITIGATION_ACTION_STATUS_ACTIONABLE_NOW


def _runtime_mitigation_packet_changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    return _runtime_mitigation_packet_summary_line(previous) != _runtime_mitigation_packet_summary_line(current)


def _runtime_mitigation_wait_changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    return _runtime_mitigation_wait_summary_line(previous) != _runtime_mitigation_wait_summary_line(current)


def _runtime_mitigation_packet_ready(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    before = _runtime_mitigation_packet_summary(previous)
    after = _runtime_mitigation_packet_summary(current)
    before_status = str(before.get("status") or "")
    after_status = str(after.get("status") or "")
    return before_status not in {
        osc.MITIGATION_PACKET_STATUS_READY,
        osc.MITIGATION_PACKET_STATUS_FRESH_READY_EXISTS,
    } and after_status in {
        osc.MITIGATION_PACKET_STATUS_READY,
        osc.MITIGATION_PACKET_STATUS_FRESH_READY_EXISTS,
    }


def _open_lineage_sample_count_changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    before = int(_open_lineage_sample_summary(previous).get("open_sample_count", 0) or 0)
    after = int(_open_lineage_sample_summary(current).get("open_sample_count", 0) or 0)
    return before != after


def _lineage_sample_progressed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    before = int(_lineage_sample_summary(previous).get("closed_trade_count", 0) or 0)
    after = int(_lineage_sample_summary(current).get("closed_trade_count", 0) or 0)
    return after > before


def _first_lineage_closed_fill_observed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    before = int(_lineage_sample_summary(previous).get("closed_trade_count", 0) or 0)
    after = int(_lineage_sample_summary(current).get("closed_trade_count", 0) or 0)
    return before <= 0 and after > 0


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
        f"live_validation: state={summary.get('edge_state', 'unavailable')} | "
        f"entry_timing={summary.get('entry_timing_preferred_variant', 'none')} | "
        f"execution_style={summary.get('execution_style_preferred_variant', 'none')} | "
        f"validation={posture.get('state', 'unknown')}/{posture.get('claim_state', 'unknown')} | "
        f"closed={int(kpis.get('closed_trade_count', 0) or 0)}/{int(summary.get('edge_proof_goal_closed_trades', 0) or 0)} | "
        f"remaining_to_goal={int(summary.get('remaining_closed_trades_to_edge_proof_goal', 0) or 0)} | "
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


def _lineage_closed_fill_health_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict((payload or {}).get("lineage_closed_fill_health") or {})
    return {
        "status": str(source.get("status") or "unknown"),
        "healthy": bool(source.get("healthy", False)),
        "closed_trade_count": int(source.get("closed_trade_count", 0) or 0),
        "latest_closed_trade_at": str(source.get("latest_closed_trade_at") or ""),
        "summary": str(source.get("summary") or ""),
    }


def _lineage_closed_fill_health_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _lineage_closed_fill_health_summary(payload)
    line = (
        f"lineage_closed_fill_health: status={summary.get('status', 'unknown')} | "
        f"healthy={summary.get('healthy', False)} | "
        f"closes={summary.get('closed_trade_count', 0)}"
    )
    latest = str(summary.get("latest_closed_trade_at") or "")
    if latest:
        line = f"{line} | latest={latest}"
    return line


def _open_lineage_sample_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict((payload or {}).get("open_lineage_sample_summary") or {})
    samples = list(source.get("samples") or [])
    return {
        "open_sample_count": int(source.get("open_sample_count", 0) or 0),
        "sample_limit": int(source.get("sample_limit", 0) or 0),
        "samples": samples,
        "symbols": list(source.get("symbols") or []),
        "summary": str(source.get("summary") or ""),
    }


def _open_lineage_sample_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _open_lineage_sample_summary(payload)
    preview = ", ".join(
        f"{str(item.get('symbol') or 'unknown')}:{str(item.get('last_fill_stage') or 'none')}"
        for item in summary.get("samples", [])
        if isinstance(item, dict)
    )
    line = (
        f"open_lineage_samples: count={summary.get('open_sample_count', 0)} | "
        f"limit={summary.get('sample_limit', 0)}"
    )
    if preview:
        line = f"{line} | top={preview}"
    return line


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


def _active_lineage_sample_health_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict((payload or {}).get("active_lineage_sample_health") or {})
    return {
        "active": bool(source.get("active", False)),
        "status": str(source.get("status") or "none"),
        "threshold_hours": int(source.get("threshold_hours", 0) or 0),
        "hours_open": round(_float(source.get("hours_open", 0.0)), 2),
        "symbol": str(source.get("symbol") or ""),
        "strategy_family": str(source.get("strategy_family") or ""),
        "plan_id": str(source.get("plan_id") or ""),
        "last_fill_stage": str(source.get("last_fill_stage") or "none"),
        "last_fill_at": str(source.get("last_fill_at") or ""),
        "summary": str(source.get("summary") or ""),
    }


def _active_lineage_sample_health_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _active_lineage_sample_health_summary(payload)
    line = (
        f"active_lineage_sample_health: active={summary.get('active', False)} | "
        f"hours_open={summary.get('hours_open', 0.0):.2f} | "
        f"threshold_hours={summary.get('threshold_hours', 0)} | "
        f"status={summary.get('status', 'none')}"
    )
    if summary.get("symbol"):
        line = f"{line} | symbol={summary.get('symbol')}"
    if summary.get("last_fill_stage"):
        line = f"{line} | last_fill={summary.get('last_fill_stage')}"
    return line


def _active_lineage_sample_focus_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict((payload or {}).get("active_lineage_sample_focus") or {})
    return {
        "symbol": str(source.get("symbol") or ""),
        "status": str(source.get("status") or "none"),
        "strategy_family": str(source.get("strategy_family") or ""),
        "plan_id": str(source.get("plan_id") or ""),
        "submission_id": str(source.get("submission_id") or ""),
        "hours_open": round(_float(source.get("hours_open", 0.0)), 2),
        "last_fill_stage": str(source.get("last_fill_stage") or "none"),
        "last_fill_at": str(source.get("last_fill_at") or ""),
    }


def _active_lineage_sample_focus_summary_line(payload: dict[str, Any] | None) -> str:
    summary = _active_lineage_sample_focus_summary(payload)
    if not summary.get("plan_id"):
        return "active_lineage_sample_focus: none"
    line = (
        f"active_lineage_sample_focus: {summary.get('symbol') or 'unknown'} | "
        f"family={summary.get('strategy_family') or 'unknown'} | "
        f"status={summary.get('status') or 'unknown'} | "
        f"plan_id={summary.get('plan_id') or 'unknown'} | "
        f"hours_open={summary.get('hours_open', 0.0):.2f}"
    )
    if summary.get("last_fill_stage"):
        line = f"{line} | last_fill={summary.get('last_fill_stage')}"
    return line


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
    if _risk_gate_changed(previous, current):
        events.append(
            {
                "type": "risk_gate_changed",
                "title": "Risk gate changed",
                "body": f"{_risk_gate_summary_line(previous)} -> {_risk_gate_summary_line(current)}",
            }
        )
    if _risk_gate_cleared(previous, current):
        events.append(
            {
                "type": "risk_gate_cleared",
                "title": "Risk gate reopened",
                "body": _risk_gate_summary_line(current),
            }
        )
    if _post_unlock_review_ready(previous, current):
        events.append(
            {
                "type": "post_unlock_review_ready",
                "title": "Post-unlock review window is open",
                "body": _post_unlock_review_summary_line(current),
            }
        )
    if _post_unlock_bundle_changed(previous, current):
        events.append(
            {
                "type": "post_unlock_bundle_changed",
                "title": "Post-unlock review bundle changed",
                "body": _post_unlock_bundle_summary_line(current),
            }
        )
    if _runtime_reopen_ready(previous, current):
        events.append(
            {
                "type": "runtime_reopen_ready",
                "title": "Runtime reopen review is ready",
                "body": _post_unlock_bundle_summary_line(current),
            }
        )
    if _runtime_reopen_status_changed(previous, current):
        events.append(
            {
                "type": "runtime_reopen_status_changed",
                "title": "Runtime reopen status changed",
                "body": _runtime_reopen_status_summary_line(current),
            }
        )
    if _runtime_operator_signoff_ready(previous, current):
        events.append(
            {
                "type": "runtime_operator_signoff_ready",
                "title": "Runtime operator sign-off is ready",
                "body": _runtime_operator_signoff_summary_line(current),
            }
        )
    if _runtime_operator_signoff_changed(previous, current):
        events.append(
            {
                "type": "runtime_operator_signoff_changed",
                "title": "Runtime operator sign-off changed",
                "body": _runtime_operator_signoff_summary_line(current),
            }
        )
    if _runtime_live_cluster_guard_changed(previous, current):
        events.append(
            {
                "type": "runtime_live_cluster_guard_changed",
                "title": "Runtime live cluster guard changed",
                "body": _runtime_live_cluster_guard_summary_line(current),
            }
        )
    if _runtime_mitigation_changed(previous, current):
        events.append(
            {
                "type": "runtime_mitigation_changed",
                "title": "Runtime mitigation status changed",
                "body": _runtime_mitigation_summary_line(current),
            }
        )
    if _runtime_mitigation_actionable(previous, current):
        events.append(
            {
                "type": "runtime_mitigation_actionable",
                "title": "Runtime mitigation became actionable",
                "body": _runtime_mitigation_summary_line(current),
            }
        )
    if _runtime_mitigation_packet_changed(previous, current):
        events.append(
            {
                "type": "runtime_mitigation_packet_changed",
                "title": "Runtime mitigation packet changed",
                "body": _runtime_mitigation_packet_summary_line(current),
            }
        )
    if _runtime_mitigation_wait_changed(previous, current):
        events.append(
            {
                "type": "runtime_mitigation_wait_changed",
                "title": "Runtime mitigation wait changed",
                "body": _runtime_mitigation_wait_summary_line(current),
            }
        )
    if _runtime_mitigation_packet_ready(previous, current):
        events.append(
            {
                "type": "runtime_mitigation_packet_ready",
                "title": "Runtime mitigation packet ready",
                "body": _runtime_mitigation_packet_summary_line(current),
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
    if _lineage_sample_progressed(previous, current):
        events.append(
            {
                "type": "lineage_sample_progressed",
                "title": "Lineage sample count increased",
                "body": f"{_lineage_sample_summary_line(previous)} -> {_lineage_sample_summary_line(current)}",
            }
        )
    if _open_lineage_sample_count_changed(previous, current):
        events.append(
            {
                "type": "open_lineage_sample_count_changed",
                "title": "Open lineage sample count changed",
                "body": f"{_open_lineage_sample_summary_line(previous)} -> {_open_lineage_sample_summary_line(current)}",
            }
        )
    if _active_lineage_sample_progressed(previous, current):
        events.append(
            {
                "type": "active_lineage_sample_progressed",
                "title": "Active lineage sample progressed",
                "body": (
                    f"{_active_lineage_sample_focus_summary_line(previous)} -> "
                    f"{_active_lineage_sample_focus_summary_line(current)}"
                ),
            }
        )
    if _first_lineage_closed_fill_observed(previous, current):
        events.append(
            {
                "type": "first_lineage_closed_fill_observed",
                "title": "First lineage CLOSED fill observed",
                "body": _lineage_closed_fill_health_summary_line(current),
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
    if _active_lineage_sample_stall_trigger(previous, current):
        events.append(
            {
                "type": "active_lineage_sample_stall",
                "title": "Open lineage sample stalled",
                "body": _active_lineage_sample_health_summary_line(current),
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
    lines = ["트레이딩 상태 알림"]
    if events:
        lines.append("변화:")
        for event in events:
            lines.append(_event_line_ko(event, current))

    risk = _risk_gate_summary(current)
    runtime = _runtime_reopen_status_summary(current)
    signoff = _runtime_signoff_summary(current)
    post_unlock = _post_unlock_review_summary(current)
    lineage = dict(current.get("lineage_sample_summary") or {})
    edge = dict(current.get("edge_experiment_review") or {})
    posture = dict(edge.get("edge_proof_posture") or {})
    edge_kpis = dict(edge.get("daily_edge_kpis") or {})
    active_sample = dict(current.get("active_lineage_sample_focus") or {})
    active_symbol = str(active_sample.get("symbol") or "없음")
    if active_sample.get("symbol"):
        active_sample_line = (
            f"{active_symbol} / {active_sample.get('last_fill_stage') or 'n/a'} / "
            f"{float(active_sample.get('hours_open') or 0.0):.2f}h"
        )
    else:
        active_sample_line = active_symbol
    readiness = (
        f"lineage={bool(current.get('lineage_gate_ready', False))}, "
        f"candidate={bool(current.get('candidate_gate_ready', False))}, "
        f"sample={bool(current.get('edge_sample_gate_ready', False))}"
    )
    required_reviews = list(signoff.get("required_reviews") or [])
    signoff_line = (
        ", ".join(_ko_signoff_code(item.get("code")) for item in required_reviews[:3])
        if required_reviews
        else "없음"
    )
    clearance_line = _ko_required_clearance_line(signoff)
    detail_line = _ko_required_review_detail(signoff)
    focus_detail_line = _ko_approval_template_focus_detail(signoff)
    downside_detail_line = _ko_approval_template_downside_detail(signoff)
    failure_mode_line = _ko_approval_template_failure_mode_detail(signoff)
    confirm_cluster_line = _ko_confirm_loss_cluster_detail(signoff)
    entry_timing_profile_line = _ko_entry_timing_loss_profile_detail(signoff)
    entry_timing_priority_line = _ko_entry_timing_priority_detail(signoff)
    mitigation_execution_plan_line = _ko_mitigation_execution_plan_detail(signoff)
    mitigation_detail_line = _ko_approval_template_mitigation_detail(signoff)
    mitigation_status_line = _ko_approval_template_mitigation_status_detail(signoff)
    post_patch_line = _ko_post_patch_sample_detail(signoff)
    mitigation_runtime_line = _ko_runtime_mitigation_action_line(current)
    mitigation_packet_line = _ko_runtime_mitigation_packet_line(current)
    mitigation_wait_line = _ko_runtime_mitigation_wait_line(current)
    recommendation_line = _ko_operator_recommendation(signoff.get("operator_recommendation"))
    decision_line = _ko_runtime_decision(signoff)
    gate_line = _ko_runtime_reopen_gate_line(signoff)
    preflight_line = _ko_runtime_preflight_line(current)
    contract_partition_line = _ko_runtime_contract_partition_line(current)
    live_subset_performance_line = _ko_runtime_live_subset_performance_line(current)
    live_cluster_guard_line = _ko_runtime_live_cluster_guard_line(current)
    operator_signoff_line = _ko_runtime_operator_signoff_line(current)
    operator_action_line = _ko_runtime_operator_action_line(current)
    actionable_live_candidate_line = _ko_runtime_actionable_live_candidate_line(current)
    self_heal_line = _ko_runtime_self_heal_line(current)
    trend_proof_watch_line = _ko_trend_proof_watch_line(current)

    lines.extend(
        [
            f"현재 단계: {current.get('stage')} / 사유={current.get('stage_reason') or 'n/a'}",
            (
                "승인 상태: "
                f"대시보드={_ko_approval_value(dict(current.get('dashboard_approval_strip') or {}).get('approve_value'))}, "
                f"검증={_ko_approval_value(dict(current.get('validation_approval_strip') or {}).get('approve_value'))}, "
                f"체크리스트={_ko_approval_value(dict(current.get('checklist_approval_strip') or {}).get('approve_value'))}"
            ),
            (
                "리스크 잠금: "
                f"{'닫힘' if str(risk.get('risk_state') or '').upper() == 'CLOSED' else '열림'}"
                f" / 사유={risk.get('risk_reason') or 'normal'}"
                f" / 해제={risk.get('unlock_at') or 'n/a'}"
            ),
            f"재개 상태: {_ko_runtime_reopen_status(runtime.get('status'))}",
            *([decision_line] if decision_line else []),
            *([gate_line] if gate_line else []),
            *([preflight_line] if preflight_line else []),
            *([contract_partition_line] if contract_partition_line else []),
            *([live_subset_performance_line] if live_subset_performance_line else []),
            *([live_cluster_guard_line] if live_cluster_guard_line else []),
            *([operator_signoff_line] if operator_signoff_line else []),
            *([operator_action_line] if operator_action_line else []),
            *([actionable_live_candidate_line] if actionable_live_candidate_line else []),
            *([self_heal_line] if self_heal_line else []),
            *([trend_proof_watch_line] if trend_proof_watch_line else []),
            f"권장 판단: {recommendation_line}",
            f"수동 서명: {signoff_line}",
            *([detail_line] if detail_line else []),
            *([focus_detail_line] if focus_detail_line else []),
            *([downside_detail_line] if downside_detail_line else []),
            *([failure_mode_line] if failure_mode_line else []),
            *([confirm_cluster_line] if confirm_cluster_line else []),
            *([entry_timing_profile_line] if entry_timing_profile_line else []),
            *([entry_timing_priority_line] if entry_timing_priority_line else []),
            *([mitigation_execution_plan_line] if mitigation_execution_plan_line else []),
            *([mitigation_detail_line] if mitigation_detail_line else []),
            *([mitigation_status_line] if mitigation_status_line else []),
            *([post_patch_line] if post_patch_line else []),
            *([mitigation_runtime_line] if mitigation_runtime_line else []),
            *([mitigation_packet_line] if mitigation_packet_line else []),
            *([mitigation_wait_line] if mitigation_wait_line else []),
            f"해소 기준: {clearance_line}",
            (
                "글로벌 참고표본: "
                f"{int(lineage.get('closed_trade_count') or 0)}/"
                f"{int(lineage.get('proof_goal_closed_trades') or 0)}"
            ),
            (
                "BTCUSDC 운영검증: "
                f"{int(edge.get('closed_trade_count') or edge_kpis.get('closed_trade_count') or 0)}/"
                f"{int(edge.get('edge_proof_goal_closed_trades') or 0)}"
                f" / 상태={posture.get('state') or 'n/a'}"
            ),
            f"준비 게이트: {readiness}",
            f"열린 샘플: {active_sample_line}",
            f"다음 액션: {current.get('top_operator_action') or post_unlock.get('next_review_step') or 'n/a'}",
        ]
    )
    return "\n".join(lines)


def _ko_approval_value(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("_", " ")
    mapping = {
        "runtime no go": "런타임 차단",
        "manual review first": "수동 검토",
        "validation/checklist no go": "체크리스트 차단",
        "approval usable": "사용 가능",
        "entry gate blocked": "진입 차단",
    }
    return mapping.get(raw, str(value or "n/a"))


def _ko_runtime_reopen_status(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return osc.KO_RUNTIME_REOPEN_STATUS_LABELS.get(raw, str(value or "n/a"))


def _ko_operator_recommendation(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return osc.KO_RUNTIME_OPERATOR_RECOMMENDATION_LABELS.get(raw, str(value or "n/a"))


def _ko_runtime_decision(signoff: dict[str, Any] | None) -> str:
    decision = dict(dict(signoff or {}).get("runtime_decision") or {})
    if not decision:
        return ""
    band = str(decision.get("band") or "")
    action = str(decision.get("effective_action") or "")
    scope = str(decision.get("allowed_reopen_scope") or "")
    return (
        "최종 판정: "
        f"{osc.KO_RUNTIME_DECISION_BAND_LABELS.get(band, band or 'n/a')} / "
        f"{osc.KO_RUNTIME_DECISION_ACTION_LABELS.get(action, action or 'n/a')} / "
        f"범위={osc.KO_RUNTIME_DECISION_SCOPE_LABELS.get(scope, scope or 'n/a')}"
    )


def _ko_runtime_reopen_gate_line(signoff: dict[str, Any] | None) -> str:
    gate = dict(dict(signoff or {}).get("runtime_reopen_gate_summary") or {})
    if not gate:
        return ""
    micro = dict(gate.get("micro_live") or {})
    full = dict(gate.get("full_live") or {})
    line = (
        "재개 게이트: "
        f"MICRO={osc.KO_RUNTIME_REOPEN_GATE_STATUS_LABELS.get(str(micro.get('status') or '').strip().lower(), micro.get('status') or 'n/a')} "
        f"({int(micro.get('closed_trade_count') or 0)}/{int(micro.get('min_closed_trades') or 0)})"
        f", FULL={osc.KO_RUNTIME_REOPEN_GATE_STATUS_LABELS.get(str(full.get('status') or '').strip().lower(), full.get('status') or 'n/a')} "
        f"({int(full.get('closed_trade_count') or 0)}/{int(full.get('min_closed_trades') or 0)})"
    )
    contract_scope = str(micro.get("contract_scope") or full.get("contract_scope") or "")
    if contract_scope:
        line += f", contract={contract_scope}"
    return line


def _ko_runtime_preflight_line(current: dict[str, Any] | None) -> str:
    summary = dict(dict(current or {}).get("runtime_preflight_summary") or {})
    if not summary or str(summary.get("status") or "").strip().lower() == "not_applicable":
        return ""
    failed_checks = list(summary.get("failed_checks") or [])
    first_failed = dict(failed_checks[0]) if failed_checks else {}
    raw_status = str(summary.get("status") or "").strip()
    line = (
        "마이크로라이브 사전점검: "
        f"{osc.KO_MICRO_LIVE_PREFLIGHT_STATUS_LABELS.get(raw_status.upper(), summary.get('status') or 'n/a')}"
    )
    if summary.get("summary"):
        line += f" / {summary.get('summary')}"
    if first_failed:
        line += f" / 첫 실패={first_failed.get('name') or 'unknown'}"
    return line


def _ko_runtime_contract_partition_line(current: dict[str, Any] | None) -> str:
    summary = dict(dict(current or {}).get("runtime_contract_partition_summary") or {})
    if not summary:
        return ""
    live_families = ",".join(list(summary.get("live_allowed_families") or [])) or "none"
    live_entry_models = ",".join(list(summary.get("live_allowed_entry_models") or [])) or "none"
    research_entry_models = ",".join(list(summary.get("research_only_entry_models") or [])) or "none"
    priority_symbols = ">".join(list(summary.get("live_symbol_priority") or [])) or "none"
    direction_contract = dict(summary.get("live_direction_contract") or {})
    direction_bits = [f"{symbol}:{'|'.join(list(direction_contract.get(symbol) or []))}" for symbol in sorted(direction_contract)]
    return (
        "운영 계약 분리: "
        f"symbols={','.join(list(summary.get('live_allowed_symbols') or [])) or 'all'} "
        f"| priority={priority_symbols} "
        f"| directions={';'.join(direction_bits) or 'all'} "
        f"| proof={summary.get('active_gate_proof_source') or 'n/a'} "
        f"| execution_subset={int(summary.get('live_execution_closed_trade_count', 0) or 0)} "
        f"| historical_execution={int(summary.get('historical_execution_contract_closed_trade_count', 0) or 0)} "
        f"| historical_walk_forward_execution={int(summary.get('historical_walk_forward_execution_contract_closed_trade_count', 0) or 0)} "
        f"| historical_walk_forward_strategy={int(summary.get('historical_walk_forward_strategy_closed_trade_count', 0) or 0)} "
        f"| trend_proof={int(summary.get('trend_proof_closed_trade_count', 0) or 0)} "
        f"| historical_walk_forward_trend={int(summary.get('historical_walk_forward_trend_closed_trade_count', 0) or 0)} "
        f"| "
        f"live={live_families}/{live_entry_models} "
        f"| research-only={research_entry_models} "
        f"| full_truth={int(summary.get('full_truth_closed_trade_count', 0) or 0)} "
        f"| live_subset={int(summary.get('live_eligible_closed_trade_count', 0) or 0)}"
    )


def _ko_runtime_live_subset_performance_line(current: dict[str, Any] | None) -> str:
    summary = dict(dict(current or {}).get("runtime_live_subset_performance_summary") or {})
    if not summary:
        return ""
    execution = dict(summary.get("execution_subset") or {})
    historical = dict(summary.get("historical_execution_subset") or {})
    historical_walk_forward = dict(summary.get("historical_walk_forward_execution_subset") or {})
    strategy_walk_forward = dict(summary.get("historical_walk_forward_strategy_subset") or {})
    trend = dict(summary.get("trend_proof_subset") or {})
    walk_forward_trend = dict(summary.get("historical_walk_forward_trend_subset") or {})
    live = dict(summary.get("live_subset") or {})
    full = dict(summary.get("full_truth") or {})
    execution_pf = execution.get("profit_factor")
    historical_pf = historical.get("profit_factor")
    historical_walk_forward_pf = historical_walk_forward.get("profit_factor")
    strategy_walk_forward_pf = strategy_walk_forward.get("profit_factor")
    trend_pf = trend.get("profit_factor")
    walk_forward_trend_pf = walk_forward_trend.get("profit_factor")
    live_pf = live.get("profit_factor")
    full_pf = full.get("profit_factor")
    return (
        "실사용 subset 성적: "
        f"exec {int(execution.get('closed_trade_count', 0) or 0)}개 plan "
        f"/ exec 승률 {float(execution.get('win_rate', 0.0) or 0.0):.0%} "
        f"/ exec EV {float(execution.get('ev_r', 0.0) or 0.0):+.2f}R "
        f"/ exec PF {(f'{float(execution_pf):.2f}' if execution_pf is not None else 'n/a')} "
        f"/ exec stop_loss {float(execution.get('stop_loss_share', 0.0) or 0.0):.0%} "
        f"/ historical {int(historical.get('closed_trade_count', 0) or 0)}개 plan "
        f"/ historical 승률 {float(historical.get('win_rate', 0.0) or 0.0):.0%} "
        f"/ historical EV {float(historical.get('ev_r', 0.0) or 0.0):+.2f}R "
        f"/ historical PF {(f'{float(historical_pf):.2f}' if historical_pf is not None else 'n/a')} "
        f"/ historical stop_loss {float(historical.get('stop_loss_share', 0.0) or 0.0):.0%} "
        f"/ historical-wf {int(historical_walk_forward.get('closed_trade_count', 0) or 0)}개 plan "
        f"/ historical-wf 승률 {float(historical_walk_forward.get('win_rate', 0.0) or 0.0):.0%} "
        f"/ historical-wf EV {float(historical_walk_forward.get('ev_r', 0.0) or 0.0):+.2f}R "
        f"/ historical-wf PF {(f'{float(historical_walk_forward_pf):.2f}' if historical_walk_forward_pf is not None else 'n/a')} "
        f"/ historical-wf stop_loss {float(historical_walk_forward.get('stop_loss_share', 0.0) or 0.0):.0%} "
        f"/ strategy-wf {int(strategy_walk_forward.get('closed_trade_count', 0) or 0)}개 plan "
        f"/ strategy-wf 승률 {float(strategy_walk_forward.get('win_rate', 0.0) or 0.0):.0%} "
        f"/ strategy-wf EV {float(strategy_walk_forward.get('ev_r', 0.0) or 0.0):+.2f}R "
        f"/ strategy-wf PF {(f'{float(strategy_walk_forward_pf):.2f}' if strategy_walk_forward_pf is not None else 'n/a')} "
        f"/ strategy-wf stop_loss {float(strategy_walk_forward.get('stop_loss_share', 0.0) or 0.0):.0%} "
        f"/ trend {int(trend.get('closed_trade_count', 0) or 0)}개 plan "
        f"/ trend 승률 {float(trend.get('win_rate', 0.0) or 0.0):.0%} "
        f"/ trend EV {float(trend.get('ev_r', 0.0) or 0.0):+.2f}R "
        f"/ trend PF {(f'{float(trend_pf):.2f}' if trend_pf is not None else 'n/a')} "
        f"/ trend stop_loss {float(trend.get('stop_loss_share', 0.0) or 0.0):.0%} "
        f"/ trend-wf {int(walk_forward_trend.get('closed_trade_count', 0) or 0)}개 plan "
        f"/ trend-wf 승률 {float(walk_forward_trend.get('win_rate', 0.0) or 0.0):.0%} "
        f"/ trend-wf EV {float(walk_forward_trend.get('ev_r', 0.0) or 0.0):+.2f}R "
        f"/ trend-wf PF {(f'{float(walk_forward_trend_pf):.2f}' if walk_forward_trend_pf is not None else 'n/a')} "
        f"/ trend-wf stop_loss {float(walk_forward_trend.get('stop_loss_share', 0.0) or 0.0):.0%} "
        f"/ proxy {int(live.get('closed_trade_count', 0) or 0)}개 plan "
        f"/ 승률 {float(live.get('win_rate', 0.0) or 0.0):.0%} "
        f"/ EV {float(live.get('ev_r', 0.0) or 0.0):+.2f}R "
        f"/ PF {(f'{float(live_pf):.2f}' if live_pf is not None else 'n/a')} "
        f"/ stop_loss {float(live.get('stop_loss_share', 0.0) or 0.0):.0%} "
        f"/ full {int(full.get('closed_trade_count', 0) or 0)}개 plan "
        f"/ full 승률 {float(full.get('win_rate', 0.0) or 0.0):.0%} "
        f"/ full EV {float(full.get('ev_r', 0.0) or 0.0):+.2f}R "
        f"/ full PF {(f'{float(full_pf):.2f}' if full_pf is not None else 'n/a')} "
        f"/ full stop_loss {float(full.get('stop_loss_share', 0.0) or 0.0):.0%}"
    )


def _ko_runtime_operator_signoff_line(current: dict[str, Any] | None) -> str:
    summary = dict(dict(current or {}).get("runtime_operator_signoff_summary") or {})
    status = str(summary.get("status") or "").strip().lower()
    if not summary or status in {"", "not_applicable"}:
        return ""

    line = f"운영 서명 단계: {osc.KO_RUNTIME_OPERATOR_SIGNOFF_STATUS_LABELS.get(status, status)}"
    if summary.get("allowed_scope"):
        line += (
            " / 범위="
            f"{osc.KO_RUNTIME_DECISION_SCOPE_LABELS.get(str(summary.get('allowed_scope') or ''), str(summary.get('allowed_scope') or 'n/a'))}"
        )
    if summary.get("first_required_review_code"):
        line += f" / 우선 검토={_ko_signoff_code(summary.get('first_required_review_code'))}"
    if summary.get("next_step"):
        raw_next_step = str(summary.get("next_step") or "")
        line += f" / 다음={osc.KO_RUNTIME_OPERATOR_SIGNOFF_NEXT_STEP_LABELS.get(raw_next_step, raw_next_step or 'n/a')}"
    submit_mode = str(summary.get("intent_execution_mode") or "")
    contract_scope = str(summary.get("contract_scope") or "")
    if submit_mode:
        submit_text = f"{submit_mode} intent -> live submit"
        if contract_scope:
            submit_text += f" ({contract_scope})"
        line += f" / 실행={submit_text}"
    return line


def _ko_runtime_operator_action_line(current: dict[str, Any] | None) -> str:
    summary = dict(dict(current or {}).get("runtime_operator_signoff_summary") or {})
    status = str(summary.get("status") or "").strip().lower()
    if not summary or status in {"", "not_applicable"}:
        return ""
    review_command = str(summary.get("review_command") or "")
    signoff_review_command = str(summary.get("signoff_review_command") or "")
    candidate_requirements = str(summary.get("candidate_requirements_summary") or "")
    intent_mode = str(summary.get("intent_execution_mode") or "")
    contract_scope = str(summary.get("contract_scope") or "")
    parts: list[str] = []
    if review_command:
        parts.append("1) preflight 재확인")
    if signoff_review_command:
        parts.append("2) signoff review 재확인")
    if intent_mode:
        submit_text = f"3) APPROVED_* plan을 {intent_mode} intent로 생성"
        if contract_scope:
            submit_text += f" ({contract_scope})"
        parts.append(submit_text)
        parts.append("4) live=true submit")
    line = "운영 실행: " + (" -> ".join(parts) if parts else "수동 서명 대기")
    if candidate_requirements:
        line += f" / 조건={candidate_requirements}"
    return line


def _ko_runtime_actionable_live_candidate_line(current: dict[str, Any] | None) -> str:
    summary = dict(dict(current or {}).get("runtime_actionable_live_candidate_summary") or {})
    status = str(summary.get("status") or "").strip().lower()
    if not summary or status in {"", "not_applicable"}:
        return ""
    line = f"실행 후보: {osc.KO_ACTIONABLE_LIVE_CANDIDATE_STATUS_LABELS.get(status, status)}"
    if summary.get("candidate_symbol"):
        line += f" / 후보={summary.get('candidate_symbol')}"
        if summary.get("candidate_family"):
            line += f":{summary.get('candidate_family')}"
        if summary.get("candidate_direction"):
            line += f"/{summary.get('candidate_direction')}"
    recent_symbol = str(summary.get("recent_intent_symbol") or "")
    recent_family = str(summary.get("recent_intent_family") or "")
    recent_mode = str(summary.get("recent_intent_allowed_execution_mode") or summary.get("recent_intent_execution_mode") or "")
    recent_direction = str(summary.get("recent_intent_direction") or "")
    recent_hint = "/".join(item for item in [recent_symbol, recent_family, recent_mode, recent_direction] if item)
    if recent_hint:
        line += f" / 최근 surface={recent_hint}"
    recent_submit_ready_bits = [
        str(summary.get("recent_submit_ready_symbol") or ""),
        str(summary.get("recent_submit_ready_family") or ""),
        str(summary.get("recent_submit_ready_direction") or ""),
    ]
    recent_submit_ready_hint = "/".join(item for item in recent_submit_ready_bits if item)
    if recent_submit_ready_hint:
        line += f" / 최근 submit_ready={recent_submit_ready_hint}"
        if summary.get("recent_submit_ready_created_at"):
            line += f"@{summary.get('recent_submit_ready_created_at')}"
    if summary.get("recent_contract_match_count") is not None:
        line += f" / 최근 계약일치={summary.get('recent_contract_match_count')}"
    if summary.get("next_trigger"):
        raw_next_trigger = str(summary.get("next_trigger") or "")
        line += f" / 다음={osc.KO_ACTIONABLE_LIVE_CANDIDATE_NEXT_TRIGGER_LABELS.get(raw_next_trigger, raw_next_trigger)}"
    if summary.get("summary"):
        line += f" / {summary.get('summary')}"
    return line


def _ko_runtime_self_heal_line(current: dict[str, Any] | None) -> str:
    summary = dict(dict(current or {}).get("runtime_self_heal_summary") or {})
    if not summary:
        return ""
    return (
        "자동 복구 상태: "
        f"{'활성' if bool(summary.get('active', False)) else '비활성'}"
        f" / stale_cleanup={int(summary.get('stale_cleanup_events', 0) or 0)}"
        f" / reentry_ignore={bool(summary.get('latest_reentry_block_ignored', False))}"
        f" / duplicate_ignore={int(summary.get('latest_duplicate_intents_ignored', 0) or 0)}"
        f" / submit_ready_self_heal={bool(summary.get('latest_submit_ready_self_heal_applied', False))}"
    )


def _ko_trend_proof_watch_line(current: dict[str, Any] | None) -> str:
    watch = dict(dict(current or {}).get("paper_lineage_watch_summary") or {})
    summary = dict(watch.get("trend_proof_candidate_summary") or {})
    if not summary:
        return ""
    return (
        "트렌드 proof 후보: "
        f"{summary.get('availability_state') or 'unknown'}"
        f" / scanner={int(summary.get('scanner_candidate_count', 0) or 0)}"
        f" / limit={int(summary.get('scanner_limit_candidate_count', 0) or 0)}"
        f" / runtime={int(summary.get('runtime_eligible_candidate_count', 0) or 0)}"
    )


def _ko_runtime_live_cluster_guard_line(current: dict[str, Any] | None) -> str:
    summary = _runtime_live_cluster_guard_summary(current)
    status = str(summary.get("status") or "").strip().lower()
    if not summary or status in {"", "not_available", "clear"}:
        return ""

    status_map = {
        "cluster_window_cap_active": "같은 family 동시 진입 제한 active",
        "family_loss_cooldown_active": "같은 family 최근 손실 cooldown active",
        "multiple_live_guards_active": "live cluster guard 복합 active",
        "cluster_window_cap_present": "같은 family 동시 진입 제한 관찰",
        "family_loss_cooldown_present": "같은 family 최근 손실 cooldown 관찰",
    }
    line = (
        "라이브 클러스터 가드: "
        f"{status_map.get(status, status)}"
        f" / cluster={int(summary.get('cluster_window_blocked_candidates') or 0)}"
        f" / cooldown={int(summary.get('loss_cooldown_blocked_candidates') or 0)}"
    )
    families = ",".join(summary.get("families") or [])
    symbols = ",".join(summary.get("symbols") or [])
    if families:
        line += f" / family={families}"
    if symbols:
        line += f" / symbol={symbols}"
    if summary.get("current_reason_code"):
        raw_reason = str(summary.get("current_reason_code") or "")
        line += f" / reason={osc.KO_LIVE_CLUSTER_GUARD_REASON_LABELS.get(raw_reason, raw_reason)}"
    return line


def _ko_signoff_code(value: Any) -> str:
    raw = str(value or "").strip().lower()
    mapping = {
        "approval_template_review": "승인 템플릿 경고",
        "execution_reconciliation_review": "실행 정합성 점검",
        "kill_switch_review": "킬스위치 검토",
        "portfolio_headroom_review": "포트폴리오 여유 검토",
        "symbol_edge_thin": "BTCUSDC 표본 얇음",
    }
    return mapping.get(raw, str(value or "n/a"))


def _ko_required_clearance_line(signoff: dict[str, Any] | None) -> str:
    required_reviews = list(dict(signoff or {}).get("required_reviews") or [])
    if not required_reviews:
        return "없음"
    phrases: list[str] = []
    for item in required_reviews[:3]:
        code = str(item.get("code") or "")
        if code == "approval_template_review":
            phrases.append("승인 템플릿 REVIEW 해제")
        elif code == "execution_reconciliation_review":
            phrases.append("실행 정합성 degraded 해제")
        elif code == "kill_switch_review":
            phrases.append("kill_switch_review 해제")
        else:
            phrases.append(_ko_signoff_code(code))
    return ", ".join(phrases)


def _ko_required_review_detail(signoff: dict[str, Any] | None) -> str:
    required_reviews = list(dict(signoff or {}).get("required_reviews") or [])
    for item in required_reviews[:3]:
        code = str(item.get("code") or "")
        if code != "approval_template_review":
            continue
        worst = str(item.get("worst_scenario") or "n/a")
        status = str(item.get("worst_scenario_status") or "NOT_AVAILABLE")
        reason = str(item.get("worst_scenario_reason") or "not_available")
        return f"핵심 경고: 최악 시나리오 {worst} = {status} ({reason})"
    return ""


def _ko_approval_template_focus_detail(signoff: dict[str, Any] | None) -> str:
    focus = dict(dict(signoff or {}).get("approval_template_focus") or {})
    if not focus:
        return ""
    focus_symbol = str(focus.get("focus_symbol") or "n/a")
    max_drawdown = _float(focus.get("replay_max_drawdown_r"))
    p5 = _float(focus.get("replay_p5_r"))
    delta_max_drawdown = _float(focus.get("approximation_gap_max_drawdown_r"))
    return (
        "정량 경고: "
        f"{focus_symbol} / maxDD={max_drawdown:.4f}R / "
        f"p5={p5:.2f}R / ΔDD={delta_max_drawdown:+.2f}R"
    )


def _ko_approval_template_downside_detail(signoff: dict[str, Any] | None) -> str:
    focus = dict(dict(signoff or {}).get("approval_template_focus") or {})
    downside = dict(focus.get("downside_profile") or {})
    if not downside:
        return ""
    stop_loss_count = int(downside.get("stop_loss_count", 0) or 0)
    trade_count = int(downside.get("trade_count", 0) or 0)
    worst_loss_streak = int(downside.get("worst_loss_streak", 0) or 0)
    dominant_regime = str(downside.get("dominant_regime") or "unknown")
    top_loss_waves = list(downside.get("top_loss_waves") or [])
    top_loss_symbols = list(downside.get("top_loss_symbols") or [])
    confirm_share = float(downside.get("confirm_named_loss_share", 0.0) or 0.0)
    median_held_bars = float(downside.get("median_loss_held_bars", 0.0) or 0.0)
    top_loss = dict(top_loss_symbols[0] or {}) if top_loss_symbols else {}
    top_loss_text = ""
    if top_loss:
        top_loss_text = (
            f", 상위 손실 {str(top_loss.get('symbol') or 'UNKNOWN')} "
            f"{float(top_loss.get('negative_r', 0.0) or 0.0):.2f}R"
        )
    wave_text = ""
    if top_loss_waves:
        wave = dict(top_loss_waves[0] or {})
        wave_text = f", 손실 파동 {int(wave.get('loss_trade_count', 0) or 0)}건"
    return (
        "구조 경고: "
        f"{dominant_regime} regime, stop_loss {stop_loss_count}/{trade_count}, "
        f"confirm 손실 {confirm_share:.0%}, "
        f"손실 중앙 보유 {median_held_bars:.0f} bars, "
        f"최대 연속 손실 {worst_loss_streak}회"
        f"{wave_text}{top_loss_text}"
    )


def _ko_approval_template_failure_mode_detail(signoff: dict[str, Any] | None) -> str:
    focus = dict(dict(signoff or {}).get("approval_template_focus") or {})
    downside = dict(focus.get("downside_profile") or {})
    mode = str(downside.get("primary_failure_mode") or "")
    if not mode:
        return ""
    mapping = {
        "range_confirm_entry_loss_wave": "주원인: range 구간 confirm-entry + 장기 보유 손절 + 동시 손실 파동",
        "range_late_entry_loss_wave": "주원인: range 구간 늦은 진입 + 오래 끄는 손절 + 동시 손실 파동",
        "range_long_hold_stopouts": "주원인: range 구간 오래 끄는 손절 누적",
        "clustered_stop_loss_wave": "주원인: 같은 파동에서 stop-loss가 동시 다발로 발생",
        "stop_loss_heavy_distribution": "주원인: 최악 시나리오에서 stop-loss 비중이 과도함",
        "general_replay_drawdown": "주원인: worst-case replay 손실 분포가 아직 과도함",
    }
    return mapping.get(mode, f"주원인: {mode}")


def _ko_confirm_loss_cluster_detail(signoff: dict[str, Any] | None) -> str:
    focus = dict(dict(signoff or {}).get("approval_template_focus") or {})
    cluster = dict(focus.get("confirm_loss_cluster_summary") or {})
    if not cluster:
        return ""
    top_symbols = list(cluster.get("top_symbols") or [])
    top_symbol_labels = "/".join(
        str(item.get("symbol") or "UNKNOWN")
        for item in top_symbols[:3]
    )
    top_text = f", 상위 심볼 {top_symbol_labels}" if top_symbol_labels else ""
    top_waves = list(cluster.get("top_waves") or [])
    wave = dict(top_waves[0] or {}) if top_waves else {}
    wave_text = ""
    if wave:
        wave_text = f", confirm 파동 {int(wave.get('loss_trade_count', 0) or 0)}건"
    held_bar_bands = dict(cluster.get("held_bar_bands") or {})
    long_hold_text = ""
    if held_bar_bands:
        long_hold_text = f", >1000 bars {int(held_bar_bands.get('over_1000', 0) or 0)}건"
    return (
        "confirm 손실군: "
        f"{int(cluster.get('loss_trade_count', 0) or 0)}건, "
        f"중앙 보유 {float(cluster.get('median_held_bars', 0.0) or 0.0):.0f} bars, "
        f"p75 보유 {int(cluster.get('p75_held_bars', 0) or 0)} bars"
        f"{long_hold_text}{wave_text}{top_text}"
    )


def _ko_entry_timing_loss_profile_detail(signoff: dict[str, Any] | None) -> str:
    focus = dict(dict(signoff or {}).get("approval_template_focus") or {})
    profile = dict(focus.get("entry_timing_loss_profile") or {})
    if not profile:
        return ""
    confirm = dict(profile.get("confirm") or {})
    non_confirm = dict(profile.get("non_confirm") or {})
    return (
        "entry timing 비교: "
        f"confirm {int(confirm.get('loss_trade_count', 0) or 0)}건/"
        f"{float(confirm.get('negative_r', 0.0) or 0.0):.2f}R, "
        f"non-confirm {int(non_confirm.get('loss_trade_count', 0) or 0)}건/"
        f"{float(non_confirm.get('negative_r', 0.0) or 0.0):.2f}R, "
        f"confirm 비중 {float(profile.get('confirm_loss_share', 0.0) or 0.0):.0%}, "
        f"보유 격차 {float(profile.get('held_bar_gap_confirm_minus_non_confirm', 0.0) or 0.0):+.0f} bars"
    )


def _ko_entry_timing_priority_detail(signoff: dict[str, Any] | None) -> str:
    focus = dict(dict(signoff or {}).get("approval_template_focus") or {})
    priority = dict(focus.get("entry_timing_priority_summary") or {})
    if not priority:
        return ""
    code_map = {
        "confirm_entry_tighten": "confirm 진입 타이밍 축소",
        "non_confirm_fail_fast": "non-confirm fail-fast",
        "confirm_fail_fast": "confirm fail-fast",
        "loss_wave_cluster": "loss wave cluster",
    }
    primary_code = str(priority.get("primary_focus_code") or "")
    secondary_code = str(priority.get("secondary_focus_code") or "")
    return (
        "진입 우선순위: "
        f"1) {code_map.get(primary_code, primary_code or '추가 검토')}, "
        f"2) {code_map.get(secondary_code, secondary_code or '추가 검토')}"
    )


def _ko_mitigation_execution_plan_detail(signoff: dict[str, Any] | None) -> str:
    focus = dict(dict(signoff or {}).get("approval_template_focus") or {})
    plan = dict(focus.get("mitigation_execution_plan") or {})
    if not plan:
        return ""
    primary_label = str(plan.get("primary_focus_label") or "추가 검토")
    primary_status = osc.KO_RUNTIME_MITIGATION_REVIEW_STATUS_LABELS.get(
        str(plan.get("primary_status") or ""),
        str(plan.get("primary_status") or "미정"),
    )
    secondary_label = str(plan.get("secondary_focus_label") or "")
    secondary_status = osc.KO_RUNTIME_MITIGATION_REVIEW_STATUS_LABELS.get(
        str(plan.get("secondary_status") or ""),
        str(plan.get("secondary_status") or "미정"),
    )
    text = f"실행 순서: 1) {primary_label} ({primary_status})"
    if secondary_label:
        text += f", 2) {secondary_label} ({secondary_status})"
    return text


def _ko_post_patch_sample_detail(signoff: dict[str, Any] | None) -> str:
    focus = dict(dict(signoff or {}).get("approval_template_focus") or {})
    post_patch = dict(focus.get("post_patch_sample_summary") or {})
    if not post_patch:
        return ""
    top_symbols = "/".join(str(item.get("symbol") or "UNKNOWN") for item in list(post_patch.get("top_symbols") or [])[:3])
    return (
        "패치 후 표본: "
        f"{int(post_patch.get('closed_trade_count', 0) or 0)}/"
        f"{int(post_patch.get('target_closed_trades', 0) or 0)}"
        f", stop_loss {float(post_patch.get('stop_loss_share', 0.0) or 0.0):.0%}"
        f", confirm 손실 {float(post_patch.get('confirm_named_loss_share', 0.0) or 0.0):.0%}"
        f", 중앙 보유 {float(post_patch.get('median_held_bars', 0.0) or 0.0):.0f} bars"
        + (f", 상위 심볼 {top_symbols}" if top_symbols else "")
    )


def _ko_approval_template_mitigation_detail(signoff: dict[str, Any] | None) -> str:
    focus = dict(dict(signoff or {}).get("approval_template_focus") or {})
    downside = dict(focus.get("downside_profile") or {})
    items = list(downside.get("mitigation_focus") or [])
    if not items:
        return ""
    labels: list[str] = []
    mapping = {
        "range_entry_timing_review": "range 진입 타이밍 재검토",
        "shadow_fail_fast_review": "fail-fast shadow review",
        "loss_wave_cluster_review": "loss wave cluster 검토",
    }
    for item in items[:3]:
        code = str(item.get("code") or "")
        labels.append(mapping.get(code, code or "추가 검토"))
    return "권장 대응: " + ", ".join(labels)


def _ko_approval_template_mitigation_status_detail(signoff: dict[str, Any] | None) -> str:
    focus = dict(dict(signoff or {}).get("approval_template_focus") or {})
    review_summary = dict(focus.get("mitigation_review_summary") or {})
    items = list(review_summary.get("items") or [])
    if not items:
        return ""
    code_mapping = {
        "range_entry_timing_review": "entry timing split",
        "shadow_fail_fast_review": "fail-fast shadow",
        "loss_wave_cluster_review": "loss wave 검토",
    }
    labels: list[str] = []
    for item in items[:3]:
        code = str(item.get("code") or "")
        status = str(item.get("status") or "")
        labels.append(
            f"{code_mapping.get(code, code or '추가 검토')}="
            f"{osc.KO_RUNTIME_MITIGATION_REVIEW_STATUS_LABELS.get(status, status or '미정')}"
        )
    return "대응 상태: " + ", ".join(labels)


def _ko_runtime_mitigation_focus_label(value: Any) -> str:
    raw = str(value or "").strip()
    mapping = {
        "range_entry_timing_review": "entry timing split",
        "shadow_fail_fast_review": "fail-fast shadow",
        "loss_wave_cluster_review": "loss wave 검토",
    }
    return mapping.get(raw, raw or "추가 검토")


def _ko_runtime_mitigation_action_status(value: Any) -> str:
    raw = str(value or "").strip()
    return osc.KO_RUNTIME_MITIGATION_ACTION_STATUS_LABELS.get(raw, raw or "미정")


def _ko_runtime_mitigation_packet_status(value: Any) -> str:
    raw = str(value or "").strip()
    return (
        osc.KO_RUNTIME_MITIGATION_PACKET_STATUS_LABELS.get(raw)
        or osc.KO_RUNTIME_MITIGATION_PACKET_STATUS_LABELS.get(raw.upper())
        or osc.KO_RUNTIME_MITIGATION_PACKET_STATUS_LABELS.get(raw.lower())
        or raw
        or "미정"
    )


def _ko_runtime_mitigation_wait_constraint(value: Any) -> str:
    raw = str(value or "").strip()
    return osc.KO_RUNTIME_MITIGATION_WAIT_CONSTRAINT_LABELS.get(raw, raw or "none")


def _ko_runtime_mitigation_next_trigger(value: Any) -> str:
    raw = str(value or "").strip()
    return osc.KO_RUNTIME_MITIGATION_NEXT_TRIGGER_LABELS.get(raw, raw or "none")


def _ko_runtime_mitigation_guard_reason(value: Any) -> str:
    raw = str(value or "").strip()
    return osc.KO_RUNTIME_MITIGATION_GUARD_REASON_LABELS.get(raw, raw or "active")


def _ko_runtime_mitigation_wait_status(value: Any) -> str:
    raw = str(value or "").strip()
    return osc.KO_RUNTIME_MITIGATION_WAIT_STATUS_LABELS.get(raw, raw or "비활성")


def _ko_runtime_mitigation_action_line(current: dict[str, Any] | None) -> str:
    summary = _runtime_mitigation_summary(current)
    if not bool(summary.get("available", False)):
        return ""
    status = str(summary.get("primary_action_status") or "")
    code = str(summary.get("primary_action_code") or "")
    command = str(summary.get("primary_action_command") or "")
    constraint = str(summary.get("primary_action_constraint") or "")
    base = f"실행 포커스: {_ko_runtime_mitigation_focus_label(code)} / {_ko_runtime_mitigation_action_status(status)}"
    if status == osc.MITIGATION_ACTION_STATUS_ACTIONABLE_NOW and command:
        return f"{base} / 명령={command}"
    if constraint:
        return f"{base} / 제약={_ko_runtime_mitigation_wait_constraint(constraint)}"
    return base


def _ko_runtime_mitigation_packet_line(current: dict[str, Any] | None) -> str:
    summary = _runtime_mitigation_packet_summary(current)
    if not bool(summary.get("available", False)):
        return ""
    status = str(summary.get("status") or "")
    if status == "inactive":
        return ""
    if status == osc.MITIGATION_PACKET_STATUS_WAITING:
        return (
            f"실행 패킷: {summary.get('focus_label') or '추가 검토'} 대기"
            f" / 상태={_ko_runtime_mitigation_action_status(summary.get('primary_action_status'))}"
            f" / 제약={_ko_runtime_mitigation_wait_constraint(summary.get('wait_constraint'))}"
        )
    base = (
        f"실행 패킷: {_ko_runtime_mitigation_packet_status(status)}"
        f" / 포커스={summary.get('focus_label') or 'none'}"
        f" / 대상={summary.get('target_symbol') or 'none'}"
        f" / variant={summary.get('target_variant') or 'none'}"
    )
    if summary.get("packet_id"):
        base = f"{base} / packet={summary.get('packet_id')}"
    return base


def _ko_runtime_mitigation_wait_line(current: dict[str, Any] | None) -> str:
    summary = _runtime_mitigation_wait_summary(current)
    if not bool(summary.get("available", False)):
        return ""
    status = str(summary.get("status") or "")
    session_name = str(summary.get("current_session") or "unknown")
    allowed_sessions = ",".join(str(item) for item in list(summary.get("allowed_sessions") or []) if str(item).strip())
    candidate_symbol = str(summary.get("candidate_symbol") or "")
    candidate_family = str(summary.get("candidate_family") or "")
    candidate_text = ""
    if candidate_symbol or candidate_family:
        candidate_text = f" / 최근 후보={candidate_symbol or 'none'}:{candidate_family or 'none'}"
    reason_text = ""
    if summary.get("candidate_reason"):
        reason_text = f" / 사유={summary.get('candidate_reason')}"
    guard_text = ""
    if bool(summary.get("watch_guard_active", False)):
        families = ",".join(str(item) for item in list(summary.get("watch_guard_families") or []) if str(item).strip())
        guard_scope = families or str(summary.get("watch_guard_family") or "none")
        guard_text = f" / guard={_ko_runtime_mitigation_guard_reason(summary.get('watch_guard_reason_code'))}:{guard_scope}"
    watch_text = ""
    if summary.get("watch_tick_status"):
        watch_text = f" / watcher={summary.get('watch_tick_status')}"
    return (
        f"대기 사유: {summary.get('focus_label') or '추가 검토'} / "
        f"{_ko_runtime_mitigation_wait_status(status)} / 세션={session_name} / 허용={allowed_sessions or 'none'} / 다음 트리거={_ko_runtime_mitigation_next_trigger(summary.get('next_trigger'))}"
        f"{candidate_text}{guard_text}{reason_text}{watch_text}"
    )


def _event_line_ko(event: dict[str, str], current: dict[str, Any]) -> str:
    event_type = str(event.get("type") or "")
    titles = {
        "initial_snapshot": "초기 상태 수집",
        "stage_changed": "단계 변경",
        "close_only_changed": "close-only 상태 변경",
        "dashboard_surface_changed": "대시보드 표면 변경",
        "playbook_changed": "플레이북 변경",
        "checklist_surface_changed": "체크리스트 표면 변경",
        "edge_experiment_changed": "edge experiment 변경",
        "edge_evolution_changed": "edge evolution 변경",
        "review_followup_changed": "후속 검토 변경",
        "accepted_candidate_focus_changed": "대표 승인 후보 변경",
        "entry_timing_review_target_changed": "진입 타이밍 검토 대상 변경",
        "execution_style_review_target_changed": "실행 스타일 검토 대상 변경",
        "trial_runs_started": "trial 생성 시작",
        "winner_selected": "lineage winner 선택",
        "lineage_gate_ready": "lineage gate 준비 완료",
        "candidate_gate_ready": "candidate gate 준비 완료",
        "edge_sample_gate_ready": "표본 gate 준비 완료",
        "all_readiness_gates_ready": "전체 readiness 준비 완료",
        "edge_sample_stall": "표본 누적 정체",
        "active_lineage_sample_stall": "열린 샘플 정체",
        "execution_manual_review": "실행 수동 검토 필요",
        "risk_gate_changed": "리스크 잠금 상태 변경",
        "risk_gate_cleared": "리스크 잠금 해제",
        "post_unlock_review_ready": "잠금 해제 후 검토 창 열림",
        "post_unlock_bundle_changed": "잠금 해제 후 자동 검토 결과 갱신",
        "runtime_reopen_ready": "런타임 재개 가능",
        "runtime_reopen_status_changed": "런타임 재개 상태 변경",
        "runtime_operator_signoff_ready": "운영 서명 가능",
        "runtime_operator_signoff_changed": "운영 서명 단계 변경",
        "runtime_live_cluster_guard_changed": "라이브 클러스터 가드 변경",
        "runtime_mitigation_changed": "대응 상태 변경",
        "runtime_mitigation_actionable": "대응 실행 가능",
        "runtime_mitigation_packet_changed": "대응 패킷 상태 변경",
        "runtime_mitigation_packet_ready": "대응 패킷 준비 완료",
        "runtime_mitigation_wait_changed": "대응 대기 사유 변경",
        "lineage_sample_progressed": "글로벌 표본 증가",
        "first_lineage_closed_fill_observed": "첫 lineage closed 관측",
        "open_lineage_sample_count_changed": "열린 샘플 수 변경",
        "active_lineage_sample_progressed": "열린 샘플 진행",
        "blocked_candidate_focus_changed": "차단 후보 변경",
    }
    label = titles.get(event_type, str(event.get("title") or event_type or "상태 변경"))
    if event_type == "lineage_sample_progressed":
        lineage = dict(current.get("lineage_sample_summary") or {})
        return f"- {label}: {int(lineage.get('closed_trade_count') or 0)}/{int(lineage.get('proof_goal_closed_trades') or 0)}"
    if event_type in {"risk_gate_changed", "risk_gate_cleared"}:
        risk = _risk_gate_summary(current)
        return f"- {label}: {risk.get('risk_reason') or 'normal'} / 해제={risk.get('unlock_at') or 'n/a'}"
    if event_type in {"runtime_reopen_ready", "runtime_reopen_status_changed"}:
        runtime = _runtime_reopen_status_summary(current)
        return f"- {label}: {_ko_runtime_reopen_status(runtime.get('status'))}"
    if event_type in {"runtime_operator_signoff_ready", "runtime_operator_signoff_changed"}:
        return f"- {label}: {_ko_runtime_operator_signoff_line(current)}"
    if event_type == "runtime_live_cluster_guard_changed":
        line = _ko_runtime_live_cluster_guard_line(current)
        return f"- {label}: {line or '라이브 클러스터 가드 해제'}"
    if event_type in {"runtime_mitigation_changed", "runtime_mitigation_actionable"}:
        mitigation = _runtime_mitigation_summary(current)
        line = (
            f"- {label}: {_ko_runtime_mitigation_focus_label(mitigation.get('primary_action_code'))} / "
            f"{_ko_runtime_mitigation_action_status(mitigation.get('primary_action_status'))}"
        )
        if event_type == "runtime_mitigation_actionable" and mitigation.get("primary_action_command"):
            line = f"{line} / cmd={mitigation.get('primary_action_command')}"
        return line
    if event_type in {"runtime_mitigation_packet_changed", "runtime_mitigation_packet_ready"}:
        packet = _runtime_mitigation_packet_summary(current)
        line = (
            f"- {label}: {_ko_runtime_mitigation_packet_status(packet.get('status'))} / "
            f"{packet.get('target_symbol') or 'none'}"
        )
        if packet.get("packet_id"):
            line = f"{line} / packet={packet.get('packet_id')}"
        return line
    if event_type == "runtime_mitigation_wait_changed":
        wait = _runtime_mitigation_wait_summary(current)
        return (
            f"- {label}: {_ko_runtime_mitigation_wait_status(wait.get('status'))} / "
            f"{wait.get('candidate_symbol') or 'none'} / "
            f"{_ko_runtime_mitigation_next_trigger(wait.get('next_trigger'))}"
        )
    if event_type in {"active_lineage_sample_progressed", "open_lineage_sample_count_changed"}:
        active_sample = dict(current.get("active_lineage_sample_focus") or {})
        symbol = str(active_sample.get("symbol") or "없음")
        stage = str(active_sample.get("last_fill_stage") or "n/a")
        return f"- {label}: {symbol} / {stage}"
    return f"- {label}"


def _post_discord(webhook_url: str, message: str) -> dict[str, Any]:
    _ensure_http_url(webhook_url)
    payload = json.dumps({"content": message}).encode("utf-8")
    request = Request(  # noqa: S310
        url=webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310
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
    stage_file = _resolve_root_path(args.stage_file).resolve()
    state_file = _resolve_root_path(args.state_file).resolve()
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
